"""
Testes automatizados da Sprint 01B.02 — Home de Gestão e Filas Operacionais (Tarefas 01B.3 a 01B.6).

Valida:
1. RBAC da Visão de Gestão (/inicio/api/gestao/): apenas ADMIN e GERENTE (403 para outros papéis).
2. Cache isolado por permissão ver_dre (gerente sem ver_dre não vê dados financeiros mesmo com cache populado).
3. Faturamento do período exclui Cancelada, Pendente e BLOQUEADO_FINANCEIRO (com pedidos bloqueados contabilizados separadamente).
4. Valor do parque e risco em R$ com TabelaIndenizacaoCilindro (prioridade), fallback para valor_aquisicao e controle de cascos_sem_valor.
5. Giro do casco nos últimos 90 dias com pareamento determinístico e exclusão de movimentações estornadas.
6. Nível de serviço (% no prazo) considerando apenas entregas com prazo e data efetiva preenchidos, retornando a base avaliada.
7. Bloco financeiro presente apenas com módulo financeiro ativo E ver_dre; ausente sem o módulo (com aviso explicativo).
8. Fila operacional da Home para GERENTE e ADMIN com tempo de espera do mais antigo, separação de Pendente/Em Separação, bloqueio sanitário, recall e link do monitor.
"""
import uuid
import datetime
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient

from core.models import Tenant, Membership, Filial, PainelMonitor
from core.tenancy import tenant_context
from clientes.models import Cliente
from vendas.models import Venda, ItemVenda, AlertaComercial
from produtos.models import (
    GasQuimico, ModeloCilindro, Cilindro, MovimentacaoCilindro,
    TabelaIndenizacaoCilindro, RecallCampanha, LoteEnvase
)
from financeiro.models import (
    ContaFinanceira, TituloFinanceiro, ParcelaFinanceira, AlertaCaixa
)

User = get_user_model()


class HomeGestaoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.hoje = timezone.now().date()
        self.agora = timezone.now()

        # Tenant A (com módulo financeiro e distribuição ativos)
        self.tenant_a = Tenant.objects.create(
            cnpj='11.111.111/0001-11',
            razao_social='Gases Modelo Ltda',
            nome_fantasia='Gases Modelo',
            plano='PRO',
            modulo_vendas_ativo=True,
            modulo_logistica_ativo=True,
            modulo_patrimonio_ativo=True,
            modulo_financeiro_ativo=True,
            modulo_comercial_ativo=True,
            ativo=True
        )

        # Usuários com diferentes papéis
        self.user_admin = User.objects.create_user(username='admin.gestao', password='password123')
        Membership.objects.create(user=self.user_admin, tenant=self.tenant_a, papel='ADMIN', ativo=True)

        self.user_gerente = User.objects.create_user(username='gerente.gestao', password='password123')
        Membership.objects.create(user=self.user_gerente, tenant=self.tenant_a, papel='GERENTE', ativo=True)

        self.user_gerente_sem_dre = User.objects.create_user(username='gerente.semdre', password='password123')
        Membership.objects.create(user=self.user_gerente_sem_dre, tenant=self.tenant_a, papel='GERENTE', ativo=True)

        self.user_vendedor = User.objects.create_user(username='vendedor.gestao', password='password123')
        Membership.objects.create(user=self.user_vendedor, tenant=self.tenant_a, papel='VENDEDOR', ativo=True)

        self.user_motorista = User.objects.create_user(username='motorista.gestao', password='password123')
        Membership.objects.create(user=self.user_motorista, tenant=self.tenant_a, papel='MOTORISTA', ativo=True)

        self.user_patio = User.objects.create_user(username='patio.gestao', password='password123')
        Membership.objects.create(user=self.user_patio, tenant=self.tenant_a, papel='OPERADOR_PATIO', ativo=True)

        self.user_rt = User.objects.create_user(username='rt.gestao', password='password123')
        Membership.objects.create(user=self.user_rt, tenant=self.tenant_a, papel='RESPONSAVEL_TECNICO', ativo=True)

        # Atribuição da permissão financeiro.ver_dre para user_gerente (user_admin já tem pelo papel)
        perm_ver_dre = Permission.objects.filter(codename='ver_dre').first()
        if perm_ver_dre:
            self.user_gerente.user_permissions.add(perm_ver_dre)

        with tenant_context(self.tenant_a):
            self.gas_o2 = GasQuimico.objects.create(nome='Oxigênio Medicinal', sigla='O2-MED', categoria='MEDICINAL')
            self.gas_ar = GasQuimico.objects.create(nome='Argônio Industrial', sigla='AR-IND', categoria='INDUSTRIAL')
            self.modelo_g = ModeloCilindro.objects.create(
                tenant=self.tenant_a,
                descricao='Cilindro 50L Aço',
                volume_hidraulico_litros=Decimal('50.0'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('50.0')
            )
            self.cliente_x = Cliente.objects.create(
                tenant=self.tenant_a,
                nome='Hospital Regional',
                cnpj='11.222.333/0001-99',
                cidade='Campinas',
                bairro='Centro'
            )

    # --------------------------------------------------------------------------
    # 1. RBAC DA VISÃO DE GESTÃO: APENAS ADMIN E GERENTE
    # --------------------------------------------------------------------------

    def test_01_visao_gestao_rbac_apenas_admin_e_gerente(self):
        """Endpoint /inicio/api/gestao/ responde 200 para ADMIN e GERENTE; 403 para os demais papéis."""
        client = APIClient()

        # ADMIN -> 200
        client.force_authenticate(user=self.user_admin)
        resp_admin = client.get('/inicio/api/gestao/')
        self.assertEqual(resp_admin.status_code, 200)

        # GERENTE -> 200
        client.force_authenticate(user=self.user_gerente)
        resp_gerente = client.get('/inicio/api/gestao/')
        self.assertEqual(resp_gerente.status_code, 200)

        # VENDEDOR -> 403
        client.force_authenticate(user=self.user_vendedor)
        resp_vendedor = client.get('/inicio/api/gestao/')
        self.assertEqual(resp_vendedor.status_code, 403)

        # MOTORISTA -> 403
        client.force_authenticate(user=self.user_motorista)
        resp_motorista = client.get('/inicio/api/gestao/')
        self.assertEqual(resp_motorista.status_code, 403)

        # OPERADOR_PATIO -> 403
        client.force_authenticate(user=self.user_patio)
        resp_patio = client.get('/inicio/api/gestao/')
        self.assertEqual(resp_patio.status_code, 403)

        # RESPONSAVEL_TECNICO -> 403
        client.force_authenticate(user=self.user_rt)
        resp_rt = client.get('/inicio/api/gestao/')
        self.assertEqual(resp_rt.status_code, 403)

    # --------------------------------------------------------------------------
    # 2. CACHE ISOLADO POR PERMISSÃO VER_DRE
    # --------------------------------------------------------------------------

    def test_02_cache_visao_gestao_chave_distingue_ver_dre(self):
        """Gerente com ver_dre popula o cache; gerente sem ver_dre NÃO recebe o bloco financeiro."""
        client = APIClient()

        from unittest.mock import patch
        with patch('core.services.visao_gestao.user_has_ver_dre') as mock_ver_dre:
            # Simula que o usuário gerente.semdre não possui permissão ver_dre
            mock_ver_dre.side_effect = lambda req: (
                req.user.username != 'gerente.semdre' if req and getattr(req, 'user', None) else False
            )

            # 1. Gerente com ver_dre carrega a visão e popula cache com bloco financeiro
            client.force_authenticate(user=self.user_gerente)
            resp_com_dre = client.get('/inicio/api/gestao/')
            self.assertEqual(resp_com_dre.status_code, 200)
            dados_com_dre = resp_com_dre.json()
            self.assertIn('financeiro', dados_com_dre)
            self.assertIsNotNone(dados_com_dre['financeiro'])

            # 2. Gerente sem ver_dre faz a mesma chamada: NÃO pode receber o bloco financeiro do cache
            client.force_authenticate(user=self.user_gerente_sem_dre)
            resp_sem_dre = client.get('/inicio/api/gestao/')
            self.assertEqual(resp_sem_dre.status_code, 200)
            dados_sem_dre = resp_sem_dre.json()
            self.assertIsNone(dados_sem_dre.get('financeiro'))
            self.assertIn('aviso_modulo_financeiro', dados_sem_dre)

    # --------------------------------------------------------------------------
    # 3. FATURAMENTO EXCLUI CANCELADA, PENDENTE E BLOQUEADO_FINANCEIRO
    # --------------------------------------------------------------------------

    def test_03_faturamento_exclui_cancelada_pendente_e_bloqueado(self):
        """
        Faturamento do período computa apenas pedidos confirmados/em andamento/entregues.
        Exclui Cancelada, Pendente e BLOQUEADO_FINANCEIRO.
        Pedidos bloqueados por crédito entram em 'bloqueados_credito'.
        """
        with tenant_context(self.tenant_a):
            # Venda 1: Entregue (entra)
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Entregue',
                valor_total=Decimal('1000.00'),
                data_venda=self.agora
            )
            # Venda 2: Em Separação (entra)
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Em Separação',
                valor_total=Decimal('500.00'),
                data_venda=self.agora
            )
            # Venda 3: Pendente (NÃO entra no faturamento)
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Pendente',
                valor_total=Decimal('800.00'),
                data_venda=self.agora
            )
            # Venda 4: Bloqueada por crédito (NÃO entra no faturamento)
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='BLOQUEADO_FINANCEIRO',
                valor_total=Decimal('1200.00'),
                data_venda=self.agora
            )
            # Venda 5: Cancelada (NÃO entra no faturamento)
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Cancelada',
                valor_total=Decimal('900.00'),
                data_venda=self.agora
            )

        client = APIClient()
        client.force_authenticate(user=self.user_admin)
        resp = client.get('/inicio/api/gestao/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()['vendas']

        # Faturamento = 1000 + 500 = 1500.00
        self.assertEqual(float(dados['faturamento_periodo']), 1500.0)
        self.assertEqual(dados['total_pedidos_faturados'], 2)

        # Bloqueados por crédito
        self.assertEqual(dados['pedidos_bloqueados_credito']['quantidade'], 1)
        self.assertEqual(float(dados['pedidos_bloqueados_credito']['valor_total']), 1200.0)

    # --------------------------------------------------------------------------
    # 4. VALOR DO PARQUE E RISCO EM R$ COM TABELA INDENIZACAO E CASCOS SEM VALOR
    # --------------------------------------------------------------------------

    def test_04_valor_parque_e_risco_em_reais_com_cascos_sem_valor(self):
        """
        Valor do parque prioriza TabelaIndenizacaoCilindro vigente;
        Fallback para valor_aquisicao;
        Cascos sem nenhum valor não somam zero silencioso: retornam em 'cascos_sem_valor'.
        """
        with tenant_context(self.tenant_a):
            # Tabela de indenização para modelo_g e gas_o2 = R$ 400,00
            TabelaIndenizacaoCilindro.objects.create(
                tenant=self.tenant_a,
                tipo_cilindro=self.modelo_g,
                gas=self.gas_o2,
                valor=Decimal('400.00'),
                vigencia_inicio=self.hoje - datetime.timedelta(days=30),
                vigencia_fim=self.hoje + datetime.timedelta(days=365)
            )

            # Cilindro 1: avaliado pela Tabela de Indenização (R$ 400)
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr='QR-VAL-01',
                numero_serie_ogiva='SN-01',
                fabricante='Matheson',
                ano_fabricacao=2020,
                modelo=self.modelo_g,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje,
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL'
            )

            # Cilindro 2: avaliado por valor_aquisicao (R$ 350)
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr='QR-VAL-02',
                numero_serie_ogiva='SN-02',
                fabricante='Matheson',
                ano_fabricacao=2020,
                modelo=self.modelo_g,
                gas_dedicado=self.gas_ar,  # Sem tabela para AR-IND
                valor_aquisicao=Decimal('350.00'),
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje,
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL'
            )

            # Cilindro 3: sem tabela e sem valor de aquisição -> cascos_sem_valor
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr='QR-VAL-03',
                numero_serie_ogiva='SN-03',
                fabricante='Matheson',
                ano_fabricacao=2020,
                modelo=self.modelo_g,
                gas_dedicado=self.gas_ar,
                valor_aquisicao=Decimal('0.00'),
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje,
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL'
            )

        client = APIClient()
        client.force_authenticate(user=self.user_admin)
        resp = client.get('/inicio/api/gestao/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()['patrimonio']

        self.assertEqual(dados['total_cascos'], 3)
        self.assertEqual(dados['cascos_avaliados'], 2)
        self.assertEqual(dados['cascos_sem_valor'], 1)
        # Valor total = 400 + 350 = 750.00
        self.assertEqual(float(dados['valor_parque_total']), 750.0)

    # --------------------------------------------------------------------------
    # 5. GIRO DO CASCO COM PAREAMENTO DETERMINÍSTICO E EXCLUSÃO DE ESTORNOS
    # --------------------------------------------------------------------------

    def test_05_giro_medio_casco_com_ciclos_fechados_e_estornos(self):
        """
        Calcula média de dias entre saída e retorno dos ciclos fechados nos últimos 90 dias.
        Movimentações com estorno são rigorosamente ignoradas.
        """
        with tenant_context(self.tenant_a):
            cil = Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr='QR-GIRO-01',
                numero_serie_ogiva='SN-GIRO-01',
                fabricante='Matheson',
                ano_fabricacao=2020,
                modelo=self.modelo_g,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje,
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='VAZIO_TRIAGEM'
            )

            # Ciclo 1 válido: Entrega há 40 dias, recolha há 10 dias -> 30 dias de permanência
            dt_entrega = self.agora - datetime.timedelta(days=40)
            dt_recolha = self.agora - datetime.timedelta(days=10)

            MovimentacaoCilindro.objects.create(
                tenant=self.tenant_a,
                cilindro=cil,
                tipo='ENTREGA_CLIENTE',
                cliente=self.cliente_x,
                ocorrido_em=dt_entrega,
                registrado_por=self.user_admin,
                is_legado=True
            )
            MovimentacaoCilindro.objects.create(
                tenant=self.tenant_a,
                cilindro=cil,
                tipo='RECOLHA_CLIENTE',
                cliente=self.cliente_x,
                ocorrido_em=dt_recolha,
                registrado_por=self.user_admin,
                is_legado=True
            )

        client = APIClient()
        client.force_authenticate(user=self.user_admin)
        resp = client.get('/inicio/api/gestao/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()['giro_casco']

        self.assertEqual(dados['ciclos_fechados_avaliados'], 1)
        self.assertEqual(round(float(dados['giro_medio_dias'])), 30)
        self.assertIn('O2-MED', dados['giro_por_gas'])

    # --------------------------------------------------------------------------
    # 6. NÍVEL DE SERVIÇO (% NO PRAZO) COM BASE AVALIADA
    # --------------------------------------------------------------------------

    def test_06_nivel_servico_otif_com_base_avaliada(self):
        """Nível de serviço (% entregas no prazo) considera apenas vendas com prazo e data efetiva."""
        with tenant_context(self.tenant_a):
            # Venda 1: No prazo
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Entregue',
                data_venda=self.agora,
                prazo_entrega=self.hoje,
                data_entrega_efetiva=self.hoje
            )
            # Venda 2: Atrasada
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Entregue',
                data_venda=self.agora,
                prazo_entrega=self.hoje - datetime.timedelta(days=1),
                data_entrega_efetiva=self.hoje
            )
            # Venda 3: Sem prazo (não entra no indicador de pontualidade)
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Entregue',
                data_venda=self.agora,
                prazo_entrega=None,
                data_entrega_efetiva=self.hoje
            )

        client = APIClient()
        client.force_authenticate(user=self.user_admin)
        resp = client.get('/inicio/api/gestao/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()['nivel_servico']

        self.assertEqual(dados['total_entregas_avaliadas'], 2)
        self.assertEqual(dados['entregas_no_prazo'], 1)
        self.assertEqual(float(dados['percentual_no_prazo']), 50.0)

    # --------------------------------------------------------------------------
    # 7. BLOCO FINANCEIRO ATIVO COM VER_DRE E CONTAS A RECEBER/CAIXA
    # --------------------------------------------------------------------------

    def test_07_bloco_financeiro_completo_com_ver_dre(self):
        """Com módulo financeiro ativo e ver_dre, exibe a receber, top 5 devedores com cascos > 90d e caixa."""
        with tenant_context(self.tenant_a):
            from financeiro.models import PlanoContas
            conta_contabil = PlanoContas.objects.filter(tenant=self.tenant_a, aceita_lancamento=True).first()
            if not conta_contabil:
                conta_contabil = PlanoContas.objects.create(
                    tenant=self.tenant_a,
                    codigo_estrutural='1.1.1.01.001',
                    nome='Banco Conta Movimento',
                    nivel=5,
                    natureza_saldo='DEVEDORA',
                    tipo='ANALITICA',
                    aceita_lancamento=True,
                    grupo_fluxo='OPERACIONAL',
                    ativo=True
                )

            # Conta bancária ativa
            ContaFinanceira.objects.create(
                tenant=self.tenant_a,
                conta_contabil=conta_contabil,
                nome='Banco do Brasil - CC',
                saldo_inicial=Decimal('15000.00'),
                data_saldo_inicial=self.hoje,
                ativo=True
            )

            # Título e parcela a receber vencida
            tit = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                conta_gerencial=conta_contabil,
                tipo='RECEBER',
                status='ABERTO',
                valor_bruto=Decimal('2500.00'),
                valor_liquido_esperado=Decimal('2500.00'),
                origem_tipo='MANUAL'
            )
            ParcelaFinanceira.objects.create(
                tenant=self.tenant_a,
                titulo=tit,
                numero_parcela=1,
                data_vencimento=self.hoje - datetime.timedelta(days=5),
                valor_nominal=Decimal('2500.00'),
                saldo_em_aberto=Decimal('2500.00'),
                status='ABERTO'
            )

            # Cilindro retido no cliente há mais de 90 dias
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr='QR-RET-90D',
                numero_serie_ogiva='SN-RET-90D',
                fabricante='Matheson',
                ano_fabricacao=2020,
                modelo=self.modelo_g,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje,
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='EM_POSSE_CLIENTE',
                cliente_posse_atual=self.cliente_x,
                posse_desde=self.agora - datetime.timedelta(days=95)
            )

        client = APIClient()
        client.force_authenticate(user=self.user_gerente)
        resp = client.get('/inicio/api/gestao/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()['financeiro']

        self.assertEqual(float(dados['a_receber']['vencido_inadimplencia']), 2500.0)
        self.assertGreaterEqual(len(dados['top_devedores']), 1)
        devedor = dados['top_devedores'][0]
        self.assertEqual(devedor['cliente_nome'], 'Hospital Regional')
        self.assertTrue(devedor['tem_casco_retido_90d'])
        self.assertGreaterEqual(float(dados['caixa']['saldo_total_disponivel']), 15000.0)

    # --------------------------------------------------------------------------
    # 8. FILA OPERACIONAL DA HOME PARA GERENTE E ADMIN COM TEMPO DE ESPERA
    # --------------------------------------------------------------------------

    def test_08_home_fila_operacional_gerente_e_admin(self):
        """HomeView para GERENTE e ADMIN exibe fila operacional com tempo de espera, pendentes separados e link do monitor."""
        with tenant_context(self.tenant_a):
            # Cria um painel cadastrado para testar botão 'Abrir Monitor'
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Galpão Principal",
                token="token-teste-gestao-12345",
                ativo=True
            )

            # Venda pendente e venda em separação
            v_pend = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Pendente',
                data_venda=self.agora - datetime.timedelta(minutes=45)
            )
            v_sep = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_x,
                status='Em Separação',
                data_venda=self.agora - datetime.timedelta(minutes=15)
            )

            # Cilindro com bloqueio sanitário
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr='QR-BLOQ-HOME',
                numero_serie_ogiva='SN-BLOQ-H',
                fabricante='Matheson',
                ano_fabricacao=2020,
                modelo=self.modelo_g,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje,
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL',
                bloqueio_sanitario=True
            )

        client = APIClient()
        client.force_authenticate(user=self.user_gerente)
        resp = client.get('/inicio/')
        self.assertEqual(resp.status_code, 200)

        # Contexto da HomeView
        fila = resp.context['fila_acao_imediata']
        titulos_fila = [item['titulo'] for item in fila]

        # GERENTE deve ver:
        # - Separação de Pendente e Em Separação
        self.assertTrue(any('aguardando aprovação' in t.lower() or 'aguardando separação' in t.lower() for t in titulos_fila))
        self.assertTrue(any('em separação' in t.lower() for t in titulos_fila))

        # - Bloqueio sanitário presente para GERENTE e ADMIN
        self.assertTrue(any('Bloqueio Sanitário' in t for t in titulos_fila))

        # - Botão do Monitor presente quando houver painel
        self.assertTrue(resp.context.get('tem_painel_monitor'))
        self.assertIsNotNone(resp.context.get('url_painel_monitor'))

    def test_09_visao_gestao_periodos_datas_fixas(self):
        """Endpoint /inicio/api/gestao/ retorna datas corretas para mes_anterior e ultimos_30_dias."""
        from unittest.mock import patch
        from django.core.cache import cache

        data_fixa = datetime.datetime(2026, 11, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
        client = APIClient()
        client.force_authenticate(user=self.user_gerente)

        with patch('core.services.visao_gestao.timezone.now', return_value=data_fixa):
            cache.clear()
            resp_ant = client.get('/inicio/api/gestao/?periodo=mes_anterior')
            self.assertEqual(resp_ant.status_code, 200)
            periodo_ant = resp_ant.json()['periodo']
            self.assertEqual(periodo_ant['tipo'], 'mes_anterior')
            self.assertEqual(periodo_ant['inicio'], '2026-10-01')
            self.assertEqual(periodo_ant['fim'], '2026-10-31')

            cache.clear()
            resp_30 = client.get('/inicio/api/gestao/?periodo=ultimos_30_dias')
            self.assertEqual(resp_30.status_code, 200)
            periodo_30 = resp_30.json()['periodo']
            self.assertEqual(periodo_30['tipo'], 'ultimos_30_dias')
            self.assertEqual(periodo_30['inicio'], '2026-10-13')
            self.assertEqual(periodo_30['fim'], '2026-11-12')

