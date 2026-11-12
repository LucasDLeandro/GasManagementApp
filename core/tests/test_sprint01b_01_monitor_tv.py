"""
Testes automatizados da Sprint 01B.01 — Monitor de TV (Tarefa 01B.2).
Valida:
1. Resolução pública por token seguro (secrets.token_urlsafe(32)), retorno 404 para token inválido ou inativo.
2. Isolamento multi-tenant estrito (token da empresa A nunca mostra dados da empresa B).
3. Ausência total de dados financeiros (R$, limites, dívidas) e dados de contato (telefone, e-mail, CNPJ, endereço completo).
4. Mascaramento de clientes quando mostrar_nomes_clientes=False (apenas número do pedido e bairro/cidade).
5. Throttle por token (12 req/min) retornando HTTP 429.
6. Respeito aos módulos ativos (Fábrica só com 'envase'; Esteira só com 'distribuicao').
7. Cálculo de tempo na etapa pelo histórico de status da 01B.00 com cores de alerta.
8. Desempenho sem N+1 (<= 15 queries) e cache de 15 segundos.
9. RBAC de gestão de painéis (somente ADMIN e GERENTE em Configurações).
10. Revogação e regeneração de token.
11. Segurança de frontend (zero innerHTML dinâmico, zero estilos inline, uso de textContent).
"""
import uuid
import datetime
from decimal import Decimal
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient

from core.models import Tenant, Membership
from core.tenancy import tenant_context
from clientes.models import Cliente
from vendas.models import Venda
from logistica.models import Entrega, Veiculo
from produtos.models import GasQuimico, ModeloCilindro, SkuRecarga, Cilindro, TanqueCriogenico

User = get_user_model()


class MonitorTVTests(TestCase):
    def setUp(self):
        cache.clear()
        self.hoje = timezone.now().date()

        # Tenants
        self.tenant_a = Tenant.objects.create(
            cnpj='11.111.111/0001-11',
            razao_social='Distribuidora Alfa Ltda',
            nome_fantasia='Alfa Gases',
            plano='PRO',
            ativo=True
        )
        self.tenant_b = Tenant.objects.create(
            cnpj='22.222.222/0001-22',
            razao_social='Distribuidora Beta Ltda',
            nome_fantasia='Beta Gases',
            plano='PRO',
            ativo=True
        )

        # Usuários
        self.user_admin = User.objects.create_user(
            username='admin.alfa',
            password='password123',
            email='admin@alfa.com'
        )
        Membership.objects.create(
            user=self.user_admin,
            tenant=self.tenant_a,
            papel='ADMIN',
            ativo=True
        )

        self.user_gerente = User.objects.create_user(
            username='gerente.alfa',
            password='password123',
            email='gerente@alfa.com'
        )
        Membership.objects.create(
            user=self.user_gerente,
            tenant=self.tenant_a,
            papel='GERENTE',
            ativo=True
        )

        self.user_vendedor = User.objects.create_user(
            username='vendedor.alfa',
            password='password123',
            email='vendedor@alfa.com'
        )
        Membership.objects.create(
            user=self.user_vendedor,
            tenant=self.tenant_a,
            papel='VENDEDOR',
            ativo=True
        )

        self.user_motorista = User.objects.create_user(
            username='motorista.alfa',
            password='password123',
            email='motorista@alfa.com'
        )
        Membership.objects.create(
            user=self.user_motorista,
            tenant=self.tenant_a,
            papel='MOTORISTA',
            ativo=True
        )

        with tenant_context(self.tenant_a):
            self.cliente_a = Cliente.objects.create(
                tenant=self.tenant_a,
                nome='Hospital São Lucas',
                nome_fantasia='Hospital São Lucas',
                cnpj='11.222.333/0001-44',
                email_financeiro='contato@saolucas.com.br',
                telefone='(11) 98765-4321',
                cidade='São Paulo',
                bairro='Cerqueira César'
            )
            self.gas_o2 = GasQuimico.objects.create(
                nome='Oxigênio Medicinal',
                sigla='O2-MED',
                categoria='MEDICINAL'
            )
            self.modelo_10m3 = ModeloCilindro.objects.create(
                tenant=self.tenant_a,
                descricao='Cilindro 50L Aço',
                volume_hidraulico_litros=Decimal('50.0'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('50.0')
            )
            self.sku_o2 = SkuRecarga.objects.create(
                tenant=self.tenant_a,
                gas=self.gas_o2,
                modelo_cilindro=self.modelo_10m3,
                nome_comercial='Cilindro O2 10m³',
                quantidade_carga=Decimal('10.0'),
                massa_gas_kg=Decimal('13.3'),
                preco_base=Decimal('150.00')
            )

        with tenant_context(self.tenant_b):
            self.cliente_b = Cliente.objects.create(
                tenant=self.tenant_b,
                nome='Clínica Beta',
                nome_fantasia='Clínica Beta',
                cnpj='99.888.777/0001-66',
                email_financeiro='contato@beta.com.br',
                telefone='(21) 99999-8888',
                cidade='Rio de Janeiro',
                bairro='Copacabana'
            )

    # --------------------------------------------------------------------------
    # 1. TOKEN INVÁLIDO OU PAINEL INATIVO -> 404
    # --------------------------------------------------------------------------

    def test_01_token_invalido_ou_painel_inativo_retorna_404(self):
        """Token inexistente ou painel inativo responde 404 em HTML e JSON (nunca 403)."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        client = APIClient()

        # Token inexistente
        resp_fake_html = client.get('/painel/token-inexistente-12345/')
        self.assertEqual(resp_fake_html.status_code, 404)

        resp_fake_json = client.get('/painel/token-inexistente-12345/dados/')
        self.assertEqual(resp_fake_json.status_code, 404)

        # Painel desativado
        token_inativo = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="Painel Desativado",
                token=token_inativo,
                ativo=False
            )

        resp_inativo_html = client.get(f'/painel/{token_inativo}/')
        self.assertEqual(resp_inativo_html.status_code, 404)

        resp_inativo_json = client.get(f'/painel/{token_inativo}/dados/')
        self.assertEqual(resp_inativo_json.status_code, 404)

    # --------------------------------------------------------------------------
    # 2. ISOLAMENTO MULTI-TENANT: EMPRESA A NUNCA VÊ EMPRESA B
    # --------------------------------------------------------------------------

    def test_02_isolamento_multitenant_token_empresa_a_nao_mostra_dados_empresa_b(self):
        """Monitor com token da empresa A nunca exibe dados da empresa B."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token_a = gerar_token_painel()
        with tenant_context(self.tenant_a):
            painel_a = PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Alfa",
                token=token_a,
                ativo=True
            )
            venda_a = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )

        with tenant_context(self.tenant_b):
            venda_b = Venda.objects.create(
                tenant=self.tenant_b,
                cliente=self.cliente_b,
                status='Pendente'
            )

        client = APIClient()
        resp = client.get(f'/painel/{token_a}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        # O pedido da empresa A está presente
        ids_a_separar = [item['id'] for item in dados['esteira']['a_separar']]
        self.assertIn(venda_a.id, ids_a_separar)
        # O pedido da empresa B NUNCA deve estar presente
        self.assertNotIn(venda_b.id, ids_a_separar)
        # O nome do cliente da empresa B não deve aparecer
        self.assertNotIn('Clínica Beta', str(dados))

    # --------------------------------------------------------------------------
    # 3. AUSÊNCIA TOTAL DE DADOS FINANCEIROS E DE CONTATO (LGPD / PRIVACIDADE)
    # --------------------------------------------------------------------------

    def test_03_ausencia_total_de_dados_financeiros_e_contato_varredura_recursiva(self):
        """O JSON do painel não pode conter R$, valores monetários, telefones, e-mails nem CNPJs."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Monitor",
                token=token,
                ativo=True
            )
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente',
                valor_total=Decimal('1500.50'),
                observacoes="Cobrar cliente via boleto bancário"
            )

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        termos_proibidos = [
            'r$', 'reais', 'valor', 'preco', 'preço', 'faturamento',
            'saldo_devedor', 'cnpj', 'cpf', 'telefone', 'email', 'e-mail',
            'endereco', 'endereço', 'logradouro', 'cep', 'motivo'
        ]

        def verificar_recursivo(obj, caminho=''):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    k_lower = str(k).lower()
                    for termo in termos_proibidos:
                        # Exceção permitida: se a chave contiver apenas contadores como 'contagem' ou 'percentual'
                        self.assertNotIn(
                            termo,
                            k_lower,
                            f"Chave proibida encontrada: '{k}' em {caminho}"
                        )
                    verificar_recursivo(v, f"{caminho}.{k}")
            elif isinstance(obj, list):
                for i, elem in enumerate(obj):
                    verificar_recursivo(elem, f"{caminho}[{i}]")
            elif isinstance(obj, str):
                v_lower = obj.lower()
                for termo in ['r$', 'reais', '1500.50', '1500,50', 'contato@saolucas', '98765-4321', '11.222.333/0001-44']:
                    self.assertNotIn(
                        termo,
                        v_lower,
                        f"Dado sensível vazado no valor: '{obj}' em {caminho}"
                    )

        verificar_recursivo(dados)

    # --------------------------------------------------------------------------
    # 4. MASCARAMENTO DE CLIENTES QUANDO MOSTRAR_NOMES_CLIENTES=FALSE
    # --------------------------------------------------------------------------

    def test_04_mostrar_nomes_clientes_false_mascara_para_bairro_cidade(self):
        """Quando mostrar_nomes_clientes=False, exibe apenas bairro/cidade e omite o nome."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Externa",
                token=token,
                ativo=True,
                mostrar_nomes_clientes=False
            )
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        item = dados['esteira']['a_separar'][0]
        self.assertNotIn('Hospital São Lucas', item['cliente'])
        self.assertIn('Cerqueira César', item['cliente'])
        self.assertIn('São Paulo', item['cliente'])

    # --------------------------------------------------------------------------
    # 5. THROTTLE POR TOKEN (12 REQ/MIN) -> 429
    # --------------------------------------------------------------------------

    def test_05_rate_limit_throttle_por_token_retorna_429(self):
        """Mais de 12 requisições por minuto com o mesmo token retorna HTTP 429."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Rate Limit",
                token=token,
                ativo=True
            )

        client = APIClient()
        # Faz 12 chamadas com sucesso (limpando cache de dados mas mantendo rate limit)
        for i in range(12):
            cache.delete(f"cache_monitor_dados_{token}")
            resp = client.get(f'/painel/{token}/dados/')
            self.assertEqual(resp.status_code, 200, f"Chamada {i+1} deveria ser 200")

        # 13ª chamada deve ser barrada por throttle
        resp_bloqueada = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp_bloqueada.status_code, 429)
        self.assertIn('Limite', resp_bloqueada.json().get('erro', ''))

    # --------------------------------------------------------------------------
    # 6. SEÇÕES RESPEITAM MÓDULOS ATIVOS
    # --------------------------------------------------------------------------

    def test_06_secoes_respeitam_modulos_fabrica_e_esteira(self):
        """Seção 'fabrica' só aparece se módulo 'envase' estiver ativo."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Modulos",
                token=token,
                ativo=True,
                secoes={'fabrica': True, 'esteira': True}
            )

        client = APIClient()

        # Sem módulo envase (plano STARTER, distribuição ativa, envase inativo)
        self.tenant_a.plano = 'STARTER'
        self.tenant_a.modulo_patrimonio_ativo = True
        self.tenant_a.modulo_vendas_ativo = True
        self.tenant_a.modulo_envase_ativo = False
        self.tenant_a.save()
        cache.clear()

        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()
        self.assertNotIn('fabrica', dados)
        self.assertIn('esteira', dados)

        # Com módulo envase ativo
        self.tenant_a.modulo_envase_ativo = True
        self.tenant_a.save()
        cache.clear()

        resp2 = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp2.status_code, 200)
        dados2 = resp2.json()
        self.assertIn('fabrica', dados2)

    # --------------------------------------------------------------------------
    # 7. TEMPO NA ETAPA COM HISTÓRICO DA 01B.00 E NÍVEIS DE ALERTA
    # --------------------------------------------------------------------------

    def test_07_tempo_na_etapa_calculado_com_historico_01b00_e_cores_alerta(self):
        """Calcula minutos_na_etapa pelo desde_quando_no_status e atribui normal/alerta/critico."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel
        from vendas.services.status import transicionar_venda

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Alertas",
                token=token,
                ativo=True,
                tempo_alerta_min=30,
                tempo_critico_min=60
            )

            # Venda normal (< 30 min)
            venda_normal = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )

            # Venda em alerta (passou de 30 min)
            venda_alerta = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )
            # Simula entrada há 45 min atrás no histórico
            hist_alerta = venda_alerta.historico_status.first()
            if hist_alerta:
                hist_alerta.alterado_em = timezone.now() - datetime.timedelta(minutes=45)
                hist_alerta.save(update_fields=['alterado_em'])

            # Venda crítica (passou de 60 min)
            venda_critica = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )
            hist_critica = venda_critica.historico_status.first()
            if hist_critica:
                hist_critica.alterado_em = timezone.now() - datetime.timedelta(minutes=75)
                hist_critica.save(update_fields=['alterado_em'])

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        itens = resp.json()['esteira']['a_separar']

        mapa_status = {item['id']: item for item in itens}
        self.assertEqual(mapa_status[venda_normal.id]['nivel_alerta'], 'normal')
        self.assertEqual(mapa_status[venda_alerta.id]['nivel_alerta'], 'alerta')
        self.assertEqual(mapa_status[venda_critica.id]['nivel_alerta'], 'critico')

    # --------------------------------------------------------------------------
    # 8. SEM N+1 (MÁXIMO 15 QUERIES) E CACHE DE 15 SEGUNDOS
    # --------------------------------------------------------------------------

    def test_08_sem_n_mais_um_e_cache_15s(self):
        """Garante no máximo 15 consultas por atualização e 0 queries na requisição em cache."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Performance",
                token=token,
                ativo=True
            )
            # Cria 15 pedidos espalhados em vários status
            for i in range(15):
                st = ['Pendente', 'Em Separação', 'Faturada', 'Em Rota'][i % 4]
                Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_a,
                    status=st
                )

        client = APIClient()

        # 1. Primeira consulta: sem N+1, <= 15 queries
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            resp = client.get(f'/painel/{token}/dados/')
            self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(ctx), 15, f"Esperado <= 15 queries, foram executadas {len(ctx)}")

        # 2. Segunda consulta imediata: consome cache de 15s
        # Executa apenas 1 query de validação pré-cache do token (ativo=True), sem nenhuma query de negócio
        with CaptureQueriesContext(connection) as ctx_cache:
            resp_cache = client.get(f'/painel/{token}/dados/')
            self.assertEqual(resp_cache.status_code, 200)
        queries_app = [q for q in ctx_cache if 'SAVEPOINT' not in q['sql'].upper()]
        self.assertLessEqual(len(queries_app), 1, f"Consultas de banco inesperadas durante hit de cache: {queries_app}")
        if queries_app:
            self.assertIn("core_painelmonitor", queries_app[0]['sql'])

    # --------------------------------------------------------------------------
    # 9. RBAC DE GESTÃO DE PAINÉIS (CONFIGURAÇÕES: SÓ ADMIN E GERENTE)
    # --------------------------------------------------------------------------

    def test_09_gestao_paineis_rbac_apenas_admin_e_gerente(self):
        """Apenas ADMIN e GERENTE gerenciam painéis; outros papéis recebem 403."""
        client = APIClient()

        # ADMIN -> 200 / 201
        client.force_authenticate(user=self.user_admin)
        resp_admin = client.post(
            '/inicio/api/paineis/',
            {'nome': 'Painel Galpão Admin'},
            format='json'
        )
        self.assertIn(resp_admin.status_code, [200, 201])
        painel_id = resp_admin.json()['id']

        # GERENTE -> 200
        client.force_authenticate(user=self.user_gerente)
        resp_gerente = client.get('/inicio/api/paineis/')
        self.assertEqual(resp_gerente.status_code, 200)

        # VENDEDOR -> 403
        client.force_authenticate(user=self.user_vendedor)
        resp_vendedor = client.get('/inicio/api/paineis/')
        self.assertEqual(resp_vendedor.status_code, 403)

        # MOTORISTA -> 403
        client.force_authenticate(user=self.user_motorista)
        resp_motorista = client.post(
            '/inicio/api/paineis/',
            {'nome': 'Tentativa Motorista'},
            format='json'
        )
        self.assertEqual(resp_motorista.status_code, 403)

    # --------------------------------------------------------------------------
    # 10. REVOGAÇÃO E REGENERAÇÃO DE TOKEN
    # --------------------------------------------------------------------------

    def test_10_revogacao_e_regeneracao_de_token(self):
        """Revogar desativa o painel (404); regenerar gera token de 32 bytes e invalida anterior."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token_orig = gerar_token_painel()
        with tenant_context(self.tenant_a):
            painel = PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Ciclo Vida",
                token=token_orig,
                ativo=True
            )

        client = APIClient()
        client.force_authenticate(user=self.user_admin)

        # 1. Regenerar token
        resp_regen = client.post(f'/inicio/api/paineis/{painel.id}/regenerar_token/')
        self.assertEqual(resp_regen.status_code, 200)
        novo_token = resp_regen.json()['token']
        self.assertNotEqual(novo_token, token_orig)
        self.assertGreaterEqual(len(novo_token), 32)

        # Token antigo agora dá 404
        client_anonimo = APIClient()
        resp_antigo = client_anonimo.get(f'/painel/{token_orig}/dados/')
        self.assertEqual(resp_antigo.status_code, 404)

        # Novo token responde 200
        resp_novo = client_anonimo.get(f'/painel/{novo_token}/dados/')
        self.assertEqual(resp_novo.status_code, 200)

        # 2. Revogar painel (desativar)
        resp_revogar = client.post(f'/inicio/api/paineis/{painel.id}/revogar/')
        self.assertEqual(resp_revogar.status_code, 200)
        self.assertFalse(resp_revogar.json()['ativo'])

        # Novo token agora também dá 404 pois está inativo
        resp_revogado = client_anonimo.get(f'/painel/{novo_token}/dados/')
        self.assertEqual(resp_revogado.status_code, 404)

    # --------------------------------------------------------------------------
    # 11. SEGURANÇA DE FRONTEND: SEM INNERHTML DINÂMICO E SEM ESTILOS INLINE
    # --------------------------------------------------------------------------

    def test_11_seguranca_frontend_static_scan_sem_innerhtml_e_sem_estilos_inline(self):
        """Varredura estática garantindo zero innerHTML com dados dinâmicos e zero estilos inline."""
        import os
        from django.conf import settings

        caminho_js = os.path.join(settings.BASE_DIR, 'core', 'static', 'core', 'js', 'painel_monitor.js')
        caminho_html = os.path.join(settings.BASE_DIR, 'core', 'templates', 'core', 'painel_monitor.html')

        self.assertTrue(os.path.exists(caminho_js), f"Arquivo JS {caminho_js} deve existir.")
        self.assertTrue(os.path.exists(caminho_html), f"Arquivo HTML {caminho_html} deve existir.")

        with open(caminho_js, 'r', encoding='utf-8') as f:
            conteudo_js = f.read()

        # Proibido innerHTML no JS de renderização
        self.assertNotIn('innerHTML', conteudo_js, "Proibido uso de innerHTML em painel_monitor.js (use textContent)")
        self.assertIn('textContent', conteudo_js, "Deve utilizar textContent para dados de cadastro no DOM")

        with open(caminho_html, 'r', encoding='utf-8') as f:
            conteudo_html = f.read()

        # Proibido style="..." inline no HTML do monitor
        import re
        matches_style = re.findall(r'style\s*=\s*["\'][^"\']+["\']', conteudo_html, flags=re.IGNORECASE)
        self.assertEqual(len(matches_style), 0, f"Estilos inline proibidos encontrados no HTML: {matches_style}")

    # --------------------------------------------------------------------------
    # 12. DADOS REAIS POR SEÇÃO DIFERENTES DE ZERO (REVISÃO SPRINT 01B.01)
    # --------------------------------------------------------------------------

    def test_12_dados_reais_por_secao_diferentes_de_zero(self):
        """
        Monta dados reais para cada indicador das seções alertas, retornos e fabrica,
        garantindo que cada contagem venha diferente de zero e precisa conforme modelos.
        """
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel
        from produtos.models import LoteEnvase, RecallCampanha

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Indicadores Operacionais",
                token=token,
                ativo=True,
                secoes={'fabrica': True, 'patio_demanda': True, 'retornos': True, 'alertas': True}
            )

            # 1. Bloqueio sanitário (Cilindro.bloqueio_sanitario=True, exceto BAIXADO)
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr=f'QR-SAN-{uuid.uuid4().hex[:6]}',
                numero_serie_ogiva='SN-SAN-01',
                fabricante='Cilbras',
                ano_fabricacao=2021,
                modelo=self.modelo_10m3,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL',
                bloqueio_sanitario=True
            )

            # 2. Reteste vencido no pátio
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr=f'QR-RET-{uuid.uuid4().hex[:6]}',
                numero_serie_ogiva='SN-RET-01',
                fabricante='Cilbras',
                ano_fabricacao=2015,
                modelo=self.modelo_10m3,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=1900),
                data_proximo_reteste=self.hoje - datetime.timedelta(days=20),
                status='CHEIO_DISPONIVEL',
                bloqueio_sanitario=False
            )

            # 3. Cilindro em VAZIO_TRIAGEM sem inspeção (conta para vazios_triagem e inspeções pendentes)
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr=f'QR-VAZ-{uuid.uuid4().hex[:6]}',
                numero_serie_ogiva='SN-VAZ-01',
                fabricante='Cilbras',
                ano_fabricacao=2022,
                modelo=self.modelo_10m3,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='VAZIO_TRIAGEM',
                bloqueio_sanitario=False
            )

            # 4. Lote de envase em quarentena
            lote = LoteEnvase.objects.create(
                tenant=self.tenant_a,
                gas=self.gas_o2,
                codigo_lote=f'LOT-{uuid.uuid4().hex[:6].upper()}',
                status_qualidade='QUARENTENA',
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal('99.50'),
                responsavel_tecnico='Dra. Farmacêutica RT',
                massa_gas_total_kg=Decimal('250.0')
            )

            # 5. Recall em andamento
            RecallCampanha.objects.create(
                tenant=self.tenant_a,
                lote=lote,
                codigo_campanha=f'REC-{uuid.uuid4().hex[:6].upper()}',
                status='ABERTO',
                motivo='Desvio analítico de pureza residual',
                criado_por=self.user_admin
            )

            # 6. Tanque criogênico com nível baixo (< 20%)
            TanqueCriogenico.objects.create(
                tenant=self.tenant_a,
                codigo='TQ-CRYO-01',
                descricao='Tanque O2 Principal',
                gas=self.gas_o2,
                capacidade_kg=Decimal('1000.0'),
                saldo_atual_kg=Decimal('180.0')
            )

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        # Validações dos Alertas
        self.assertEqual(dados['alertas']['bloqueios_sanitarios'], 1)
        self.assertEqual(dados['alertas']['recalls_abertos'], 1)
        self.assertEqual(dados['alertas']['reteste_vencido_patio'], 1)

        # Validações dos Retornos
        self.assertEqual(dados['retornos']['vazios_triagem'], 1)

        # Validações da Fábrica / Envase
        self.assertEqual(dados['fabrica']['lotes_quarentena'], 1)
        self.assertEqual(dados['fabrica']['inspecoes_pendentes'], 1)
        self.assertEqual(len(dados['fabrica']['tanques']), 1)
        tanque = dados['fabrica']['tanques'][0]
        self.assertEqual(tanque['nome'], 'TQ-CRYO-01 - Tanque O2 Principal')
        self.assertEqual(tanque['percentual_nivel'], 18.0)
        self.assertTrue(tanque['alerta_nivel_baixo'])

    # --------------------------------------------------------------------------
    # 13. PAINEL COM FILIAL ASSOCIADA RESPONDE 200 SEM ERRO NO PÁTIO
    # --------------------------------------------------------------------------

    def test_13_painel_com_filial_responde_200_sem_erro_no_patio(self):
        """Painel vinculado a uma filial não causa erro 500 no pátio (Cilindro não tem filial)."""
        from core.models import PainelMonitor, Filial
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            filial = Filial.objects.create(
                tenant=self.tenant_a,
                nome='Filial Valinhos',
                cnpj='11.111.111/0003-88',
                matriz=False,
                ativo=True
            )
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                filial=filial,
                nome="TV Filial Valinhos",
                token=token,
                ativo=True
            )

        client = APIClient()
        resp_html = client.get(f'/painel/{token}/')
        self.assertEqual(resp_html.status_code, 200)

        resp_json = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp_json.status_code, 200)
        dados = resp_json.json()
        self.assertIn('patio_demanda', dados)

    # --------------------------------------------------------------------------
    # 14. PÁTIO × DEMANDA POR GÁS COM SKU E PRODUTO LEGADO
    # --------------------------------------------------------------------------

    def test_14_patio_demanda_por_gas_com_sku_e_produto_legado(self):
        """
        Pátio x Demanda calcula cheios disponíveis, demanda e saldo individualmente por gás:
        - Gas 1 (SKU): demanda maior que pátio -> em_falta=True
        - Gas 2 (Produto legado): pátio suficiente -> em_falta=False
        """
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel
        from produtos.models import GasQuimico, Produto
        from vendas.models import ItemVenda

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Demanda por Gás",
                token=token,
                ativo=True
            )

            # Gás 1: O2 (via SKU) -> 2 cheios no pátio, pedido de 5 -> falta 3
            for i in range(2):
                Cilindro.objects.create(
                    tenant=self.tenant_a,
                    codigo_qr=f'QR-O2-{uuid.uuid4().hex[:6]}',
                    numero_serie_ogiva=f'SN-O2-{i}',
                    fabricante='Cilbras',
                    ano_fabricacao=2020,
                    modelo=self.modelo_10m3,
                    gas_dedicado=self.gas_o2,
                    propriedade='PROPRIO',
                    data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                    data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                    status='CHEIO_DISPONIVEL'
                )

            venda_o2 = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente',
                prazo_entrega=self.hoje
            )
            ItemVenda.objects.create(
                tenant=self.tenant_a,
                venda=venda_o2,
                sku=self.sku_o2,
                forma_faturamento='CARGA',
                quantidade=5,
                valor_total=Decimal('750.00')
            )

            # Gás 2: Argônio (via Produto Legado) -> 10 cheios no pátio, pedido de 4 -> saldo +6
            gas_ar = GasQuimico.objects.create(
                nome='Argônio Puro',
                sigla='AR-IND',
                categoria='INDUSTRIAL'
            )
            prod_argonio = Produto.objects.create(
                tenant=self.tenant_a,
                nome='Argônio Puro 10m³',
                categoria='GAS_INDUSTRIAL',
                capacidade=Decimal('10.0'),
                unidade_medida='M3',
                preco=Decimal('220.00'),
                estoque=20,
                origem='0',
                medicinal=False,
                exige_rastro=True
            )
            for j in range(10):
                Cilindro.objects.create(
                    tenant=self.tenant_a,
                    codigo_qr=f'QR-AR-{uuid.uuid4().hex[:6]}',
                    numero_serie_ogiva=f'SN-AR-{j}',
                    fabricante='Cilbras',
                    ano_fabricacao=2021,
                    modelo=self.modelo_10m3,
                    gas_dedicado=gas_ar,
                    propriedade='PROPRIO',
                    data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                    data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                    status='CHEIO_DISPONIVEL'
                )

            venda_ar = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Em Separação',
                prazo_entrega=self.hoje
            )
            ItemVenda.objects.create(
                tenant=self.tenant_a,
                venda=venda_ar,
                produto=prod_argonio,
                forma_faturamento='CARGA',
                quantidade=4,
                valor_total=Decimal('880.00')
            )

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        gases = dados['patio_demanda']['gases']
        mapa_gases = {g['gas']: g for g in gases}

        # Gás 1 (O2) em falta
        self.assertIn('O2-MED', mapa_gases)
        item_o2 = mapa_gases['O2-MED']
        self.assertEqual(item_o2['cheios_disponiveis'], 2)
        self.assertEqual(item_o2['quantidade_pedida'], 5)
        self.assertEqual(item_o2['saldo'], -3)
        self.assertTrue(item_o2['em_falta'])

        # Gás 2 (Argônio) com saldo positivo
        self.assertIn('AR-IND', mapa_gases)
        item_ar = mapa_gases['AR-IND']
        self.assertEqual(item_ar['cheios_disponiveis'], 10)
        self.assertEqual(item_ar['quantidade_pedida'], 4)
        self.assertEqual(item_ar['saldo'], 6)
        self.assertFalse(item_ar['em_falta'])

        # Status global de falta
        self.assertTrue(dados['patio_demanda']['em_falta'])

    # --------------------------------------------------------------------------
    # 15. REVOGAÇÃO IMEDIATA MESMO COM CACHE QUENTE
    # --------------------------------------------------------------------------

    def test_15_revogacao_imediata_mesmo_com_cache_quente(self):
        """Ao desativar/revogar um painel, requisições subsequentes recebem 404 imediatamente mesmo com cache populado."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            painel = PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Revogação Cache",
                token=token,
                ativo=True
            )

        client = APIClient()

        # 1. Primeira consulta gera cache quente
        resp1 = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp1.status_code, 200)

        # 2. Força um dado em cache para testar se a view resolve o painel ANTES do cache
        cache_key = f"cache_monitor_dados_{token}"
        cache.set(cache_key, {"forged": True}, timeout=60)

        # 3. Desativa o painel no banco
        painel.ativo = False
        painel.save(update_fields=['ativo'])

        # 4. Requisição deve retornar 404 imediatamente, sem retornar os dados em cache
        resp_revogado = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp_revogado.status_code, 404)
        self.assertNotIn('forged', resp_revogado.json())

    # --------------------------------------------------------------------------
    # 16. PÁTIO DO MONITOR CONTA SÓ CHEIOS APTOS (FIX PRELIMINAR 01B.02)
    # --------------------------------------------------------------------------

    def test_16_monitor_patio_conta_so_cheios_aptos(self):
        """
        'Cheios disponíveis' no monitor deve excluir:
        - Cilindros com bloqueio_sanitario=True
        - Cilindros com envase_atual em lote cujo status_qualidade NÃO seja APROVADO (ex: QUARENTENA ou REPROVADO)
        """
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel
        from produtos.models import LoteEnvase, EnvaseCilindro

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Cheios Aptos",
                token=token,
                ativo=True
            )

            # Lote aprovado
            lote_aprovado = LoteEnvase.objects.create(
                tenant=self.tenant_a,
                gas=self.gas_o2,
                codigo_lote=f'LOT-OK-{uuid.uuid4().hex[:6].upper()}',
                status_qualidade='APROVADO',
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal('99.8'),
                responsavel_tecnico='Dra. RT',
                massa_gas_total_kg=Decimal('200.0')
            )

            # Lote em quarentena
            lote_quarentena = LoteEnvase.objects.create(
                tenant=self.tenant_a,
                gas=self.gas_o2,
                codigo_lote=f'LOT-QUAR-{uuid.uuid4().hex[:6].upper()}',
                status_qualidade='QUARENTENA',
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal('99.1'),
                responsavel_tecnico='Dra. RT',
                massa_gas_total_kg=Decimal('200.0')
            )

            # 1. Apto com lote aprovado
            cil_apto = Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr=f'QR-APTO-{uuid.uuid4().hex[:6]}',
                numero_serie_ogiva='SN-APTO-01',
                fabricante='Cilbras',
                ano_fabricacao=2021,
                modelo=self.modelo_10m3,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL',
                bloqueio_sanitario=False
            )
            env_apto = EnvaseCilindro.objects.create(
                tenant=self.tenant_a,
                cilindro=cil_apto,
                lote=lote_aprovado,
                pressao_final_bar=200,
                envasado_em=timezone.now(),
                operador=self.user_admin
            )
            cil_apto.envase_atual = env_apto
            cil_apto.save(update_fields=['envase_atual'])

            # 2. Apto sem envase_atual (comprado cheio de terceiro / distribuidora)
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr=f'QR-TERC-{uuid.uuid4().hex[:6]}',
                numero_serie_ogiva='SN-TERC-01',
                fabricante='Cilbras',
                ano_fabricacao=2021,
                modelo=self.modelo_10m3,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL',
                bloqueio_sanitario=False
            )

            # 3. Inapto: bloqueio sanitário ativo
            Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr=f'QR-BLOQ-{uuid.uuid4().hex[:6]}',
                numero_serie_ogiva='SN-BLOQ-01',
                fabricante='Cilbras',
                ano_fabricacao=2021,
                modelo=self.modelo_10m3,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL',
                bloqueio_sanitario=True
            )

            # 4. Inapto: lote de envase atual em QUARENTENA
            cil_quar = Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr=f'QR-QUAR-{uuid.uuid4().hex[:6]}',
                numero_serie_ogiva='SN-QUAR-01',
                fabricante='Cilbras',
                ano_fabricacao=2021,
                modelo=self.modelo_10m3,
                gas_dedicado=self.gas_o2,
                propriedade='PROPRIO',
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                status='CHEIO_DISPONIVEL',
                bloqueio_sanitario=False
            )
            env_quar = EnvaseCilindro.objects.create(
                tenant=self.tenant_a,
                cilindro=cil_quar,
                lote=lote_quarentena,
                pressao_final_bar=200,
                envasado_em=timezone.now(),
                operador=self.user_admin
            )
            cil_quar.envase_atual = env_quar
            cil_quar.save(update_fields=['envase_atual'])

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        # Deve contabilizar EXATAMENTE os 2 cilindros aptos (1 com lote aprovado + 1 sem envase interno)
        self.assertEqual(dados['patio_demanda']['cheios_disponiveis'], 2)

        gases = dados['patio_demanda']['gases']
        mapa_gases = {g['gas']: g for g in gases}
        self.assertIn('O2-MED', mapa_gases)
        self.assertEqual(mapa_gases['O2-MED']['cheios_disponiveis'], 2)
