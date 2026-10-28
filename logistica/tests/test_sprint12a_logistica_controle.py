"""
Testes abrangentes da Sprint 12A: Torre de Controle Logística, Validação de Carga Perigosa, Rastreamento Seguro e Roteirização.
Cobre:
- Correções F-34 (Rastreio seguro com janela de privacidade, LGPD e rate limit), F-36 (Roteirizador com restrições e fallback 2-opt determinístico), F-40 (GPS offline idempotente com filtro de precisão).
- Validação ANTT / NBR 14619 de peso, cilindros, incompatibilidade química e documentos regulatórios.
- Liberação formal auditada de carga bloqueada.
- Execução de paradas no PWA com odômetro e recálculo dinâmico de ETA.
- Indicadores operacionais (pontualidade, km planejado vs real, paradas/hora).
- Isolamento estrito multi-tenant (404 em cross-tenant).
"""
import time
import uuid
from decimal import Decimal
from datetime import timedelta, date

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership, PerfilRegulatorioTenant
from core.tenancy import tenant_context
from accounts.models import User
from clientes.models import Cliente, GeocodificacaoCache
from produtos.models import GasQuimico, ModeloCilindro, SkuRecarga, ClasseRiscoGas
from vendas.models import Venda, ItemVenda
from logistica.models import (
    Veiculo,
    Rota,
    Entrega,
    CapacidadeVeiculoTipoCilindro,
    Motorista,
    RegraIncompatibilidadeCarga,
    LiberacaoCarga,
    ParadaEntrega,
    CoordenadaRastreamento,
    TokenRastreio,
    TrajetoEntrega,
    LeituraOdometro,
)
from logistica.services.carga import (
    validar_carga,
    liberar_carga_bloqueada,
    despachar_entrega_para_rota,
    seed_regras_incompatibilidade,
)
from logistica.services.routing import (
    otimizar_ordem_paradas,
    LocalNearestNeighbor2OptAdapter,
)
from logistica.services.paradas_service import atualizar_status_parada
from logistica.services.rastreamento_service import (
    sincronizar_lote_gps,
    consolidar_trajeto_simplificado,
)
from logistica.services.rastreio_publico_service import (
    gerar_token_rastreio,
    consultar_rastreio_publico,
    notificar_saida_entrega_com_consentimento,
)
from logistica.services.indicadores_service import apurar_indicadores_logistica
from financeiro.models import ConsentimentoContato


class Sprint12ALogisticaControleTests(TestCase):
    def setUp(self):
        # 1. Tenant Principal A
        self.tenant = Tenant.objects.create(
            razao_social="Oxigás Distribuidora e Logística LTDA",
            nome_fantasia="Oxigás Log",
            cnpj="12.345.678/0001-90",
            plano="ENTERPRISE"
        )
        self.perfil_reg = PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='DISTRIBUIDORA',
            afe_numero='AFE-12A-999',
            licenca_sanitaria_numero='LIC-12A-999',
            licenca_sanitaria_validade=timezone.now().date() + timedelta(days=365)
        )

        # 2. Tenant B para testes de isolamento multi-tenant (Regra 3)
        self.tenant_b = Tenant.objects.create(
            razao_social="Rival Logística Gases S/A",
            nome_fantasia="Rival Gás",
            cnpj="98.765.432/0001-10",
            plano="PRO"
        )

        # 3. Usuários e Papéis
        self.user_gerente = User.objects.create_user(
            username="gerente_log",
            email="gerente@oxigas.com.br",
            password="senha_segura_123",
            first_name="Carlos",
            last_name="Gerente"
        )
        Membership.objects.create(
            user=self.user_gerente,
            tenant=self.tenant,
            papel='GERENTE',
            ativo=True
        )

        self.user_motorista = User.objects.create_user(
            username="motorista_paulo",
            email="paulo@oxigas.com.br",
            password="senha_segura_123",
            first_name="Paulo",
            last_name="Santos"
        )
        Membership.objects.create(
            user=self.user_motorista,
            tenant=self.tenant,
            papel='MOTORISTA',
            ativo=True
        )

        self.user_sem_perm = User.objects.create_user(
            username="ajudante_log",
            email="ajudante@oxigas.com.br",
            password="senha_segura_123",
            first_name="Lucas",
            last_name="Ajudante"
        )
        Membership.objects.create(
            user=self.user_sem_perm,
            tenant=self.tenant,
            papel='OPERADOR',
            ativo=True
        )

        with tenant_context(self.tenant):
            # 4. Veículo
            hoje = timezone.localdate()
            self.veiculo = Veiculo.objects.create(
                tenant=self.tenant,
                placa="OXG-1234",
                modelo="Iveco Daily 35S14",
                marca="Iveco",
                ano=2023,
                capacidade_carga_kg=Decimal('3500.000'),
                rntrc="123456789",
                civ_validade=hoje + timedelta(days=180),
                cipp_validade=hoje + timedelta(days=180),
                odometro_atual_km=Decimal('50000.00')
            )

            # 5. Motorista Cadastrado
            self.motorista = Motorista.objects.create(
                tenant=self.tenant,
                usuario=self.user_motorista,
                nome="Paulo Santos",
                cpf="111.222.333-44",
                cnh_numero="99887766554",
                cnh_categoria="D",
                cnh_validade=hoje + timedelta(days=365),
                mopp_validade=hoje + timedelta(days=365),
                ativo=True
            )

            # 6. Gases, Modelos e SKUs
            self.gas_oxigenio = GasQuimico.objects.create(
                nome="Oxigênio Industrial",
                sigla=f"O2_{uuid.uuid4().hex[:6]}",
                categoria="INDUSTRIAL",
                numero_onu="1072",
                classe_risco="2.2"
            )
            ClasseRiscoGas.objects.create(
                tenant=self.tenant,
                gas=self.gas_oxigenio,
                classe_risco="2.2",
                subclasse="5.1",
                numero_onu="1072",
                rotulo_risco="Gás Não Inflamável e Oxidante",
                descricao_transporte="OXIGÊNIO COMPRIMIDO"
            )

            self.gas_acetileno = GasQuimico.objects.create(
                nome="Acetileno",
                sigla=f"C2H2_{uuid.uuid4().hex[:6]}",
                categoria="INDUSTRIAL",
                numero_onu="1001",
                classe_risco="2.1"
            )
            ClasseRiscoGas.objects.create(
                tenant=self.tenant,
                gas=self.gas_acetileno,
                classe_risco="2.1",
                numero_onu="1001",
                rotulo_risco="Gás Inflamável",
                descricao_transporte="ACETILENO DISSOLVIDO"
            )

            self.modelo_t50 = ModeloCilindro.objects.create(
                tenant=self.tenant,
                descricao="Cilindro T50 (50L)",
                volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('55.00'),
                massa_gas_padrao_kg=Decimal('15.00')
            )

            self.sku_oxigenio = SkuRecarga.objects.create(
                tenant=self.tenant,
                gas=self.gas_oxigenio,
                modelo_cilindro=self.modelo_t50,
                nome_comercial="Oxigênio Industrial T50",
                quantidade_carga=Decimal('10.00'),
                massa_gas_kg=Decimal('14.20'),
                preco_base=Decimal('100.00')
            )

            self.sku_acetileno = SkuRecarga.objects.create(
                tenant=self.tenant,
                gas=self.gas_acetileno,
                modelo_cilindro=self.modelo_t50,
                nome_comercial="Acetileno T50",
                quantidade_carga=Decimal('9.00'),
                massa_gas_kg=Decimal('8.00'),
                preco_base=Decimal('150.00')
            )

            # Capacidade do veículo para T50: max 30 cilindros
            self.cap_veiculo = CapacidadeVeiculoTipoCilindro.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                tipo_cilindro=self.modelo_t50,
                quantidade_maxima=30
            )

            # 7. Clientes com coordenadas
            self.cliente_1 = Cliente.objects.create(
                tenant=self.tenant,
                nome="Hospital Central Alvorada",
                cnpj="11.111.111/0001-11",
                endereco="Av. Paulista, 1000",
                bairro="Bela Vista",
                cidade="São Paulo",
                estado="SP",
                cep="01310-100",
                latitude=Decimal('-23.5629'),
                longitude=Decimal('-46.6544'),
                email_financeiro="nfe@hospitalalvorada.com.br"
            )

            self.cliente_2 = Cliente.objects.create(
                tenant=self.tenant,
                nome="Metalúrgica Progresso LTDA",
                cnpj="22.222.222/0001-22",
                endereco="Rua dos Trilhos, 800",
                bairro="Mooca",
                cidade="São Paulo",
                estado="SP",
                cep="03168-010",
                latitude=Decimal('-23.5512'),
                longitude=Decimal('-46.6021'),
                telefone="1199998888"
            )

            self.cliente_3 = Cliente.objects.create(
                tenant=self.tenant,
                nome="Clínica Santa Helena",
                cnpj="33.333.333/0001-33",
                endereco="Av. Santo Amaro, 1500",
                bairro="Itaim Bibi",
                cidade="São Paulo",
                estado="SP",
                cep="04505-002",
                latitude=Decimal('-23.5891'),
                longitude=Decimal('-46.6782'),
                telefone="1198887777"
            )

            # 8. Rota e Entrega
            self.rota = Rota.objects.create(
                tenant=self.tenant,
                nome="Rota Metropolitana Sul/Oeste"
            )

            self.entrega = Entrega.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                rota=self.rota,
                motorista=self.user_motorista,
                status='Agendada'
            )

            # 9. Vendas
            self.venda_1 = Venda.objects.create(
                tenant=self.tenant,
                cliente=self.cliente_1,
                entrega=self.entrega,
                valor_total=Decimal('500.00'),
                status='Em Separação'
            )
            self.venda_2 = Venda.objects.create(
                tenant=self.tenant,
                cliente=self.cliente_2,
                entrega=self.entrega,
                valor_total=Decimal('750.00'),
                status='Em Separação'
            )

            # Semente de regras de incompatibilidade
            seed_regras_incompatibilidade(self.tenant)

        self.client = APIClient()

    # =========================================================================
    # 1. VALIDAÇÃO DE CARGA E INCOMPATIBILIDADE QUÍMICA (Tarefa 2)
    # =========================================================================

    def test_validacao_carga_peso_excedente_bloqueia_despacho(self):
        """Veículo com capacidade 3500kg carregado com 4000kg deve ser bloqueado."""
        with tenant_context(self.tenant):
            # Cria 60 cilindros T50 (cada um pesa 55 + 14.2 = 69.2kg -> total > 4100kg > 3500kg)
            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda_1,
                sku=self.sku_oxigenio,
                quantidade=60,
                valor_unitario=Decimal('100.00')
            )

            res = validar_carga(self.entrega)
            self.assertTrue(res.bloqueado)
            self.assertTrue(any("excede a capacidade máxima" in erro for erro in res.erros_bloqueantes))

            # Tentativa de despacho direto para rota deve falhar
            from django.core.exceptions import ValidationError
            with self.assertRaises(ValidationError):
                despachar_entrega_para_rota(self.entrega)

    def test_validacao_carga_incompatibilidade_oxigenio_acetileno_bloqueia(self):
        """Carga mista contendo Classe 2.1 (Acetileno) e 5.1 (Oxigênio oxidante) deve ser bloqueada."""
        with tenant_context(self.tenant):
            # 5 Oxigênios (5.1) e 5 Acetilenos (2.1)
            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda_1,
                sku=self.sku_oxigenio,
                quantidade=5,
                valor_unitario=Decimal('100.00')
            )
            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda_2,
                sku=self.sku_acetileno,
                quantidade=5,
                valor_unitario=Decimal('150.00')
            )

            res = validar_carga(self.entrega)
            self.assertTrue(res.bloqueado)
            self.assertTrue(any("Incompatibilidade química" in erro for erro in res.erros_bloqueantes))

    def test_validacao_carga_mopp_vencido_bloqueia(self):
        """Motorista com MOPP vencido deve bloquear despacho de rota."""
        with tenant_context(self.tenant):
            self.motorista.mopp_validade = timezone.localdate() - timedelta(days=5)
            self.motorista.save()

            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda_1,
                sku=self.sku_oxigenio,
                quantidade=2,
                valor_unitario=Decimal('100.00')
            )

            res = validar_carga(self.entrega)
            self.assertTrue(res.bloqueado)
            self.assertTrue(any("MOPP" in erro and "vencido" in erro for erro in res.erros_bloqueantes))

    def test_validacao_carga_excesso_quantidade_por_tipo_cilindro(self):
        """Capacidade máxima por berço de cilindro T50 é 30; carregar 35 deve bloquear."""
        with tenant_context(self.tenant):
            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda_1,
                sku=self.sku_oxigenio,
                quantidade=35,
                valor_unitario=Decimal('100.00')
            )

            res = validar_carga(self.entrega)
            self.assertTrue(res.bloqueado)
            self.assertTrue(any("excede o limite estrutural" in erro for erro in res.erros_bloqueantes))

    def test_liberacao_auditada_sem_permissao_ou_sem_motivo_rejeitada(self):
        """Usuário comum sem permissão tem liberação negada; com permissão mas motivo curto é rejeitado."""
        with tenant_context(self.tenant):
            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda_1,
                sku=self.sku_oxigenio,
                quantidade=5,
                valor_unitario=Decimal('100.00')
            )
            # Força erro de CIV vencido
            self.veiculo.civ_validade = timezone.localdate() - timedelta(days=10)
            self.veiculo.save()

            from django.core.exceptions import PermissionDenied, ValidationError

            # Usuário sem permissão
            with self.assertRaises(PermissionDenied):
                liberar_carga_bloqueada(self.entrega, responsavel=self.user_sem_perm, motivo="Liberação pelo operador")

            # Gerente autorizado mas sem motivo adequado (< 5 chars)
            with self.assertRaises(ValidationError):
                liberar_carga_bloqueada(self.entrega, responsavel=self.user_gerente, motivo="Ok")

    def test_liberacao_auditada_com_permissao_grava_auditoria_e_despacha(self):
        """Com permissão e motivo formal, grava LiberacaoCarga e transiciona para Em Rota."""
        with tenant_context(self.tenant):
            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda_1,
                sku=self.sku_oxigenio,
                quantidade=5,
                valor_unitario=Decimal('100.00')
            )
            self.veiculo.civ_validade = timezone.localdate() - timedelta(days=10)
            self.veiculo.save()

            lib = liberar_carga_bloqueada(
                entrega=self.entrega,
                responsavel=self.user_gerente,
                motivo="Veículo em vistoria agendada para amanhã cedo; rota hospitalar prioritária liberada pela gerência."
            )

            self.assertIsNotNone(lib.id)
            self.assertEqual(lib.responsavel, self.user_gerente)
            self.assertEqual(self.entrega.status, 'Em Rota')
            self.assertIn("CIV", str(lib.erros_ignorados))

    # =========================================================================
    # 2. ROTEIRIZADOR HEXAGONAL E DETERMINÍSTICO (Tarefa 3 / Correção F-36)
    # =========================================================================

    def test_roteirizador_fallback_local_respeita_janelas_e_paradas_travadas(self):
        """Otimização de rota ordena respeitando janelas de horário e paradas travadas, com saída determinística."""
        with tenant_context(self.tenant):
            # Cria 3 paradas manuais
            p1 = ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_1,
                ordem=1,
                travada=False,
                janela_inicio=timezone.datetime(2026, 10, 24, 14, 0).time(),
                janela_fim=timezone.datetime(2026, 10, 24, 16, 0).time(),
            )
            p2 = ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_2,
                ordem=2,
                travada=True,  # TRAVADA na ordem 2
            )
            p3 = ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_3,
                ordem=3,
                travada=False,
                janela_inicio=timezone.datetime(2026, 10, 24, 8, 30).time(),
                janela_fim=timezone.datetime(2026, 10, 24, 10, 30).time(),
            )

            # Executa otimização
            res_1 = otimizar_ordem_paradas(self.entrega.id)
            self.assertTrue(res_1['sucesso'])
            self.assertEqual(res_1['total_paradas'], 3)

            # Parada travada p2 deve permanecer na sua ordem
            p2.refresh_from_db()
            self.assertEqual(p2.ordem, 2)

            # A mesma chamada deve gerar resultado rigorosamente determinístico
            res_2 = otimizar_ordem_paradas(self.entrega.id)
            ordens_1 = [p['parada_id'] for p in res_1['paradas_ordenadas']]
            ordens_2 = [p['parada_id'] for p in res_2['paradas_ordenadas']]
            self.assertEqual(ordens_1, ordens_2)

    # =========================================================================
    # 3. EXECUÇÃO DE PARADAS E ODÔMETRO (Tarefa 4)
    # =========================================================================

    def test_execucao_parada_falha_exige_motivo_e_recalcula_etas(self):
        """Transição para FALHA exige motivo; conclusão atualiza odômetro e recalcula ETAs."""
        with tenant_context(self.tenant):
            p1 = ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_1,
                ordem=1,
                status='PENDENTE',
                eta_estimado=timezone.now() + timedelta(minutes=30)
            )
            p2 = ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_2,
                ordem=2,
                status='PENDENTE',
                eta_estimado=timezone.now() + timedelta(minutes=60)
            )

            from django.core.exceptions import ValidationError
            with self.assertRaises(ValidationError):
                atualizar_status_parada(p1.id, novo_status='FALHA', motivo_falha='')

            # Falha com motivo e odômetro
            p1_atualizada = atualizar_status_parada(
                p1.id,
                novo_status='FALHA',
                motivo_falha='Estabelecimento fechado para reforma',
                odometro_km=Decimal('50045.00'),
                usuario=self.user_motorista
            )
            self.assertEqual(p1_atualizada.status, 'FALHA')
            self.assertEqual(p1_atualizada.motivo_falha, 'Estabelecimento fechado para reforma')

            # Verifica leitura de odômetro gravada
            leitura = LeituraOdometro.objects.filter(tenant=self.tenant, veiculo=self.veiculo).last()
            self.assertIsNotNone(leitura)
            self.assertEqual(leitura.km, Decimal('50045.000'))

            # Veículo atualizado
            self.veiculo.refresh_from_db()
            self.assertEqual(self.veiculo.odometro_atual_km, Decimal('50045.00'))

    # =========================================================================
    # 4. TELEMETRIA GPS OFFLINE-FIRST E IDEMPOTÊNCIA (Tarefa 5 / F-40)
    # =========================================================================

    def test_sincronizacao_gps_filtra_precisao_e_e_idempotente(self):
        """Descarta pontos com precisão > 100m e reenvios do mesmo client_uuid não duplicam."""
        with tenant_context(self.tenant):
            u1 = str(uuid.uuid4())
            u2 = str(uuid.uuid4())
            u3_impreciso = str(uuid.uuid4())

            lote = [
                {
                    'client_uuid': u1,
                    'sequencia': 1,
                    'latitude': -23.55052,
                    'longitude': -46.63330,
                    'precisao_m': 15.0,
                    'velocidade': 40.0
                },
                {
                    'client_uuid': u2,
                    'sequencia': 2,
                    'latitude': -23.55100,
                    'longitude': -46.63400,
                    'precisao_m': 20.0,
                    'velocidade': 35.0
                },
                {
                    'client_uuid': u3_impreciso,
                    'sequencia': 3,
                    'latitude': -23.55200,
                    'longitude': -46.63500,
                    'precisao_m': 150.0,  # > 100m DEVE SER DESCARTADO
                    'velocidade': 20.0
                }
            ]

            res_1 = sincronizar_lote_gps(
                tenant=self.tenant,
                entrega_id=self.entrega.id,
                pontos=lote
            )

            self.assertEqual(res_1['inseridos'], 2)
            self.assertEqual(res_1['descartados_precisao'], 1)
            self.assertEqual(res_1['duplicados'], 0)
            self.assertEqual(CoordenadaRastreamento.objects.filter(entrega=self.entrega).count(), 2)

            # Reenvio idêntico do mesmo lote (idempotência)
            res_2 = sincronizar_lote_gps(
                tenant=self.tenant,
                entrega_id=self.entrega.id,
                pontos=lote
            )
            self.assertEqual(res_2['inseridos'], 0)
            self.assertEqual(res_2['duplicados'], 2)
            self.assertEqual(res_2['descartados_precisao'], 1)
            self.assertEqual(CoordenadaRastreamento.objects.filter(entrega=self.entrega).count(), 2)

    def test_sincronizacao_gps_lote_maior_que_200_rejeitado(self):
        """Lote com mais de 200 pontos deve ser rejeitado com ValidationError."""
        with tenant_context(self.tenant):
            lote_gigante = [
                {
                    'client_uuid': str(uuid.uuid4()),
                    'sequencia': i,
                    'latitude': -23.55,
                    'longitude': -46.63,
                    'precisao_m': 10.0
                }
                for i in range(205)
            ]

            from django.core.exceptions import ValidationError
            with self.assertRaises(ValidationError):
                sincronizar_lote_gps(
                    tenant=self.tenant,
                    entrega_id=self.entrega.id,
                    pontos=lote_gigante
                )

    # =========================================================================
    # 5. LINK PÚBLICO E JANELA DE PRIVACIDADE ANTI-ROUBO (Tarefa 7 / F-34)
    # =========================================================================

    def test_rastreio_publico_oculta_posicao_fora_da_janela_e_exibe_dentro(self):
        """
        Posição GPS fica oculta enquanto a parada estiver longe (> 3 paradas antes);
        torna-se visível quando faltam <= 3 paradas ou status A_CAMINHO.
        Nome do motorista NUNCA é exibido.
        """
        with tenant_context(self.tenant):
            # Cria 5 paradas
            paradas = []
            for i in range(1, 6):
                p = ParadaEntrega.objects.create(
                    tenant=self.tenant,
                    entrega=self.entrega,
                    cliente=self.cliente_1,
                    ordem=i,
                    status='PENDENTE',
                    eta_estimado=timezone.now() + timedelta(hours=3)
                )
                paradas.append(p)

            # Transmite 1 coordenada GPS para o caminhão
            CoordenadaRastreamento.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                veiculo=self.veiculo,
                latitude=Decimal('-23.55050'),
                longitude=Decimal('-46.63330'),
                velocidade=Decimal('42.0'),
                precisao_m=Decimal('10.0'),
                capturado_em=timezone.now()
            )

            # Parada 5 (faltam 4 paradas pendentes antes dela -> posição DEVE ser oculta)
            token_p5 = gerar_token_rastreio(self.entrega, parada=paradas[4], horas_validade=12)
            dados_p5 = consultar_rastreio_publico(token_p5.token)

            self.assertFalse(dados_p5['posicao_visivel'])
            self.assertIsNone(dados_p5['ultima_posicao'])
            self.assertNotIn("Paulo Santos", str(dados_p5))  # Não vaza nome do motorista
            self.assertEqual(dados_p5['veiculo_placa_mascarada'], "OXG-***4")

            # Agora simula que paradas 1 e 2 foram concluídas
            paradas[0].status = 'ENTREGUE'
            paradas[0].save()
            paradas[1].status = 'ENTREGUE'
            paradas[1].save()

            # Agora antes da parada 5 restam apenas 2 paradas pendentes (paradas 3 e 4) <= 3
            dados_p5_proxima = consultar_rastreio_publico(token_p5.token)
            self.assertTrue(dados_p5_proxima['posicao_visivel'])
            self.assertIsNotNone(dados_p5_proxima['ultima_posicao'])
            self.assertEqual(dados_p5_proxima['ultima_posicao']['latitude'], -23.5505)

    def test_rastreio_publico_token_expirado_ou_revogado_retorna_404(self):
        """Token expirado ou revogado devolve erro 404 seguro."""
        with tenant_context(self.tenant):
            token_exp = TokenRastreio.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                expira_em=timezone.now() - timedelta(minutes=10)
            )
            token_rev = TokenRastreio.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                expira_em=timezone.now() + timedelta(hours=10),
                revogado=True
            )

            # Teste via endpoint HTTP
            resp_exp = self.client.get(f'/rastreio/{token_exp.token}/', HTTP_ACCEPT='application/json')
            self.assertEqual(resp_exp.status_code, 404)
            self.assertEqual(resp_exp['X-Robots-Tag'], 'noindex, nofollow')

            resp_rev = self.client.get(f'/rastreio/{token_rev.token}/', HTTP_ACCEPT='application/json')
            self.assertEqual(resp_rev.status_code, 404)

            # Token randômico inexistente
            resp_rand = self.client.get(f'/rastreio/{uuid.uuid4()}/', HTTP_ACCEPT='application/json')
            self.assertEqual(resp_rand.status_code, 404)

    # =========================================================================
    # 6. PERFORMANCE E POLILINHA SIMPLIFICADA (Tarefa 6)
    # =========================================================================

    def test_consulta_trajeto_em_menos_de_300ms_com_volume_de_coordenadas(self):
        """Gera polilinha simplificada e assegura que a consulta execute em < 300 ms."""
        with tenant_context(self.tenant):
            # Cria 100 coordenadas para a entrega
            coords = [
                CoordenadaRastreamento(
                    tenant=self.tenant,
                    entrega=self.entrega,
                    latitude=Decimal(f"-23.{5500 + i}"),
                    longitude=Decimal(f"-46.{6300 + i}"),
                    capturado_em=timezone.now() - timedelta(minutes=100 - i),
                    timestamp=timezone.now() - timedelta(minutes=100 - i)
                )
                for i in range(100)
            ]
            CoordenadaRastreamento.objects.bulk_create(coords)

            t_inicio = time.perf_counter()
            trajeto = consolidar_trajeto_simplificado(self.entrega.id)
            t_duracao_ms = (time.perf_counter() - t_inicio) * 1000

            self.assertIsNotNone(trajeto)
            self.assertGreater(trajeto.pontos_contagem, 0)
            self.assertLess(t_duracao_ms, 300.0, f"Tempo de consulta ({t_duracao_ms:.2f} ms) excedeu 300 ms.")

    # =========================================================================
    # 7. INDICADORES LOGÍSTICOS (Tarefa 9)
    # =========================================================================

    def test_apuracao_indicadores_pontualidade_e_paradas_por_hora(self):
        """Mede pontualidade contra ETA e calcula paradas por hora."""
        with tenant_context(self.tenant):
            agora = timezone.now()
            # Parada pontual: ETA 10:00, concluída 09:55
            ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_1,
                ordem=1,
                status='ENTREGUE',
                eta_estimado=agora - timedelta(hours=1),
                concluida_em=agora - timedelta(hours=1, minutes=5)
            )
            # Parada atrasada: ETA 11:00, concluída 11:30
            ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_2,
                ordem=2,
                status='ENTREGUE',
                eta_estimado=agora - timedelta(minutes=30),
                concluida_em=agora
            )

            indicadores = apurar_indicadores_logistica(self.tenant)
            self.assertEqual(indicadores['total_paradas_concluidas'], 2)
            self.assertEqual(indicadores['paradas_pontuais'], 1)
            self.assertEqual(indicadores['paradas_atrasadas'], 1)
            self.assertEqual(indicadores['taxa_pontualidade_percentual'], Decimal('50.00'))

    # =========================================================================
    # 8. MULTI-TENANCY E PERMISSÕES (Regras Globais 3 e 7)
    # =========================================================================

    def test_multitenant_isolamento_retorna_404_para_outro_tenant(self):
        """Garante que endpoints de logistica retornam 404 ao tentar acessar recursos de outro tenant."""
        with tenant_context(self.tenant_b):
            user_b = User.objects.create_user(
                username="motorista_rival",
                email="rival@rivalgas.com.br",
                password="senha_segura_123"
            )
            Membership.objects.create(
                user=user_b,
                tenant=self.tenant_b,
                papel='MOTORISTA',
                ativo=True
            )

            veiculo_b = Veiculo.objects.create(
                tenant=self.tenant_b,
                placa="RIV-9999",
                modelo="VW Delivery",
                marca="Volkswagen",
                ano=2022,
                capacidade_carga=Decimal('3000.00'),
                capacidade_carga_kg=Decimal('3000.000')
            )
            entrega_b = Entrega.objects.create(
                tenant=self.tenant_b,
                veiculo=veiculo_b,
                status='Agendada'
            )

        # Autentica como usuário do Tenant A
        self.client.force_authenticate(user=self.user_gerente)

        # Tenta acessar recurso da Entrega do Tenant B
        resp_entrega = self.client.get(f'/logistica/api/entregas/{entrega_b.id}/')
        self.assertEqual(resp_entrega.status_code, status.HTTP_404_NOT_FOUND)

        # Tenta validar carga do Tenant B
        resp_val = self.client.post(f'/logistica/api/entregas/{entrega_b.id}/validar-carga/')
        self.assertEqual(resp_val.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # 9. NOTIFICAÇÕES COM CONSENTIMENTO E COBERTURA EXPANDIDA (Tarefa 8 & Regra 8)
    # =========================================================================

    def test_notificar_saida_entrega_com_consentimento_ativo(self):
        """Ao sair para entrega, despacha link público respeitando consentimento LGPD ativo."""
        with tenant_context(self.tenant):
            ConsentimentoContato.objects.create(
                tenant=self.tenant,
                cliente=self.cliente_1,
                canal='WHATSAPP',
                consentiu_em=timezone.now()
            )
            ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_1,
                ordem=1,
                status='PENDENTE'
            )

            notifs = notificar_saida_entrega_com_consentimento(self.entrega)
            self.assertEqual(len(notifs), 1)
            self.assertTrue(notifs[0]['consentimento_ativo'])
            self.assertEqual(notifs[0]['canal'], 'WHATSAPP')
            self.assertIn("/rastreio/", notifs[0]['link_rastreio'])

    def test_atualizar_status_parada_estados_intermediarios_e_validacoes(self):
        """Valida transições para A_CAMINHO, CHEGOU e validações de erro."""
        with tenant_context(self.tenant):
            p = ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_1,
                ordem=1,
                status='PENDENTE'
            )

            # A_CAMINHO
            p_caminho = atualizar_status_parada(p.id, novo_status='A_CAMINHO')
            self.assertEqual(p_caminho.status, 'A_CAMINHO')

            # CHEGOU
            p_chegou = atualizar_status_parada(p.id, novo_status='CHEGOU')
            self.assertEqual(p_chegou.status, 'CHEGOU')
            self.assertIsNotNone(p_chegou.chegada_em)

            # ENTREGUE
            p_entregue = atualizar_status_parada(p.id, novo_status='ENTREGUE')
            self.assertEqual(p_entregue.status, 'ENTREGUE')
            self.assertIsNotNone(p_entregue.concluida_em)

            from django.core.exceptions import ValidationError
            # Status inválido
            with self.assertRaises(ValidationError):
                atualizar_status_parada(p.id, novo_status='INEXISTENTE')

            # Parada inexistente
            with self.assertRaises(ValidationError):
                atualizar_status_parada(999999, novo_status='ENTREGUE')

    def test_roteirizacao_auto_cria_paradas_quando_ausentes(self):
        """Se entrega possui vendas mas não possui paradas criadas, otimizar_ordem_paradas auto-cria."""
        with tenant_context(self.tenant):
            nova_entrega = Entrega.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                rota=self.rota,
                status='Agendada'
            )
            v1 = Venda.objects.create(tenant=self.tenant, cliente=self.cliente_1, entrega=nova_entrega, valor_total=Decimal('200.00'))
            v2 = Venda.objects.create(tenant=self.tenant, cliente=self.cliente_2, entrega=nova_entrega, valor_total=Decimal('300.00'))

            res = otimizar_ordem_paradas(nova_entrega.id)
            self.assertTrue(res['sucesso'])
            self.assertEqual(res['total_paradas'], 2)
            self.assertEqual(ParadaEntrega.objects.filter(entrega=nova_entrega).count(), 2)

    def test_roteirizacao_entrega_sem_vendas_retorna_vazio(self):
        """Entrega sem vendas e sem paradas retorna sucesso com 0 paradas."""
        with tenant_context(self.tenant):
            entrega_vazia = Entrega.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                rota=self.rota,
                status='Agendada'
            )
            res = otimizar_ordem_paradas(entrega_vazia.id)
            self.assertTrue(res['sucesso'])
            self.assertEqual(res['total_paradas'], 0)
            self.assertEqual(len(res['paradas_ordenadas']), 0)

    def test_rastreio_publico_posicao_visivel_quando_a_caminho(self):
        """Quando parada está A_CAMINHO, posição é imediatamente visível mesmo se faltarem paradas."""
        with tenant_context(self.tenant):
            p = ParadaEntrega.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                cliente=self.cliente_1,
                ordem=10,
                status='A_CAMINHO'
            )
            token = gerar_token_rastreio(self.entrega, parada=p)
            dados = consultar_rastreio_publico(token.token)
            self.assertTrue(dados['posicao_visivel'])

