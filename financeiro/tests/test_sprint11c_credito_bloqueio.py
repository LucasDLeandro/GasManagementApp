"""
Testes abrangentes da Sprint 11C:
Bloqueio comercial por inadimplência, promessa de pagamento, limites de crédito,
segurança assistencial hospitalar e liberação auditada de bloqueio.
"""
from decimal import Decimal
from datetime import date, timedelta
import pytest

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Tenant, Filial, Membership
from core.money import quantize
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import Cliente
from produtos.models import Produto
from vendas.models import Venda, ItemVenda, LiberacaoBloqueio
from financeiro.models import (
    ContaFinanceira,
    PlanoContas,
    CentroCusto,
    TituloFinanceiro,
    ParcelaFinanceira,
    ParametroCredito,
    LimiteCreditoCliente,
    PromessaPagamento,
    ReguaCobranca,
)
from financeiro.seeds import seed_financeiro_tenant_completo
from financeiro.services.credito_service import (
    obter_parametro_credito,
    obter_limite_credito_cliente,
    avaliar_credito,
    criar_promessa_pagamento,
    atualizar_status_promessas_diario,
)
from financeiro.services.regua_service import executar_regua_cobranca
from vendas.services.liberacao_service import liberar_bloqueio_venda

User = get_user_model()


class BaseSprint11CTestCase(TestCase):
    """Setup base multi-tenant para testes de crédito e bloqueio."""

    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()

        # Tenant A
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora de Gases 11C Ltda",
            nome_fantasia="Distribuidora 11C",
            cnpj="11.222.333/0001-99",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.token = set_current_tenant(self.tenant)

        self.filial = Filial.objects.create(
            tenant=self.tenant,
            nome="Matriz 11C",
            cnpj="11.222.333/0001-99",
            matriz=True
        )
        seed_financeiro_tenant_completo(self.tenant)

        # Usuários Tenant A
        self.admin_user = User.objects.create_user(
            username="admin_11c",
            email="admin@dist11c.com",
            password="password123"
        )
        Membership.objects.create(user=self.admin_user, tenant=self.tenant, papel="ADMIN")

        self.vendedor_user = User.objects.create_user(
            username="vendedor_11c",
            email="vendedor@dist11c.com",
            password="password123"
        )
        Membership.objects.create(user=self.vendedor_user, tenant=self.tenant, papel="VENDEDOR")

        # Contas contábeis
        self.conta_contabil_banco = PlanoContas.objects.filter(
            tenant=self.tenant,
            tipo='ANALITICA',
            codigo_estrutural__startswith='1.1.1'
        ).first()

        self.conta_financeira = ContaFinanceira.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            nome="Banco do Brasil CC 11C",
            tipo='CONTA_CORRENTE',
            banco_codigo='001',
            agencia='1111',
            conta='22222-3',
            saldo_inicial=Decimal('1000.00'),
            conta_contabil=self.conta_contabil_banco
        )

        # Clientes
        self.cliente_comum = Cliente.objects.create(
            tenant=self.tenant,
            nome="Metalúrgica Alfa Ltda",
            cnpj="33.444.555/0001-11",
            tipo_cliente="PJ",
            tipo_estabelecimento="GERAL"
        )

        self.cliente_hospital = Cliente.objects.create(
            tenant=self.tenant,
            nome="Hospital Samaritano S/A",
            cnpj="44.555.666/0001-22",
            tipo_cliente="PJ",
            tipo_estabelecimento="HOSPITAL"
        )

        # Produto
        self.produto_oxigenio = Produto.objects.create(
            tenant=self.tenant,
            nome="Oxigênio Industrial 10m3",
            categoria="Industrial",
            capacidade=Decimal('10.00'),
            unidade_medida="m³",
            preco=Decimal('150.00')
        )

        # API Clients
        self.client_admin = APIClient()
        self.client_admin.force_authenticate(user=self.admin_user)

        self.client_vendedor = APIClient()
        self.client_vendedor.force_authenticate(user=self.vendedor_user)

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def _criar_titulo_e_parcela_a_receber(self, cliente, valor, data_vencimento, saldo_aberto=None):
        """Helper para criar título e parcela a receber."""
        if saldo_aberto is None:
            saldo_aberto = valor

        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            cliente=cliente,
            tipo='RECEBER',
            historico=f"Faturamento Cliente {cliente.nome}",
            data_emissao=self.hoje - timedelta(days=30),
            data_competencia=self.hoje - timedelta(days=30),
            valor_bruto=valor,
            valor_liquido_esperado=valor,
            status='ABERTO' if saldo_aberto > Decimal('0.00') else 'LIQUIDADO',
            conta_gerencial=self.conta_contabil_banco
        )

        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            numero_parcela=1,
            data_vencimento=data_vencimento,
            valor_nominal=valor,
            saldo_em_aberto=saldo_aberto,
            status='PENDENTE' if saldo_aberto > Decimal('0.00') else 'PAGA'
        )
        return titulo, parcela


class CreditoBloqueioMatrizTestCase(BaseSprint11CTestCase):
    """Testa a matriz de decisão de crédito comercial."""

    def test_cliente_sem_pendencias_retorna_liberado(self):
        """Cliente sem parcelas vencidas e dentro do limite deve ser LIBERADO."""
        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('500.00'))
        self.assertEqual(res.status, 'LIBERADO')
        self.assertTrue(res.liberado)
        self.assertEqual(len(res.motivos), 0)

    def test_vencido_alem_tolerancia_sem_promessa_bloqueia(self):
        """Parcela vencida há mais de dias_tolerancia (padrão 5) bloqueia por PARCELA_VENCIDA."""
        param = obter_parametro_credito(self.tenant)
        param.dias_tolerancia = 5
        param.save()

        # Vencida há 10 dias (> 5)
        vencimento = self.hoje - timedelta(days=10)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('200.00'), vencimento)

        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('100.00'))
        self.assertEqual(res.status, 'BLOQUEADO_FINANCEIRO')
        self.assertFalse(res.liberado)
        self.assertIn('PARCELA_VENCIDA', res.motivos)

    def test_tolerancia_no_limite_exato_nao_bloqueia(self):
        """Parcela vencida exatamente no dia limite de tolerância não deve bloquear."""
        param = obter_parametro_credito(self.tenant)
        param.dias_tolerancia = 5
        param.save()

        # Vencida exatamente há 5 dias (no limite da tolerância)
        vencimento_limite = self.hoje - timedelta(days=5)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('200.00'), vencimento_limite)

        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('100.00'))
        self.assertEqual(res.status, 'LIBERADO')
        self.assertTrue(res.liberado)

        # Se vencer há 6 dias, ultrapassa a tolerância e bloqueia
        vencimento_estourado = self.hoje - timedelta(days=6)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('200.00'), vencimento_estourado)

        res2 = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('100.00'))
        self.assertEqual(res2.status, 'BLOQUEADO_FINANCEIRO')
        self.assertIn('PARCELA_VENCIDA', res2.motivos)

    def test_valor_minimo_considerado_ignora_pequenos_saldos(self):
        """Parcela vencida com saldo inferior ao valor_minimo_considerado (padrão R$ 50,00) não bloqueia."""
        param = obter_parametro_credito(self.tenant)
        param.valor_minimo_considerado = Decimal('50.00')
        param.save()

        vencimento = self.hoje - timedelta(days=15)
        # Saldo aberto R$ 30,00 (< R$ 50,00)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('30.00'), vencimento)

        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('100.00'))
        self.assertEqual(res.status, 'LIBERADO')

        # Se adicionarmos uma de R$ 60,00 (>= R$ 50,00), bloqueia
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('60.00'), vencimento)
        res2 = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('100.00'))
        self.assertEqual(res2.status, 'BLOQUEADO_FINANCEIRO')
        self.assertIn('PARCELA_VENCIDA', res2.motivos)

    def test_limite_de_credito_padrao_e_exposicao(self):
        """Bloqueia quando a exposição (saldo em aberto + pedido) excede o limite."""
        param = obter_parametro_credito(self.tenant)
        param.limite_credito_padrao = Decimal('1000.00')
        param.save()

        # Saldo aberto R$ 600,00 a vencer (não vencido)
        vencimento_futuro = self.hoje + timedelta(days=10)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('600.00'), vencimento_futuro)

        # Pedido de R$ 300,00 (Total R$ 900,00 <= 1000,00) -> LIBERADO
        res1 = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('300.00'))
        self.assertEqual(res1.status, 'LIBERADO')

        # Pedido de R$ 500,00 (Total R$ 1100,00 > 1000,00) -> BLOQUEADO por LIMITE_EXCEDIDO
        res2 = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('500.00'))
        self.assertEqual(res2.status, 'BLOQUEADO_FINANCEIRO')
        self.assertIn('LIMITE_EXCEDIDO', res2.motivos)

    def test_limite_credito_individual_cliente_sobrepoe_padrao(self):
        """LimiteCreditoCliente específico do cliente prevalece sobre o padrão do tenant."""
        param = obter_parametro_credito(self.tenant)
        param.limite_credito_padrao = Decimal('1000.00')
        param.save()

        # Concede limite especial de R$ 10.000,00 ao cliente
        LimiteCreditoCliente.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_comum,
            limite=Decimal('10000.00'),
            vigencia_inicio=self.hoje - timedelta(days=1),
            vigencia_fim=self.hoje + timedelta(days=30),
            ativo=True
        )

        # Pedido de R$ 3000,00 (excederia 1000, mas cabe em 10000)
        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('3000.00'))
        self.assertEqual(res.status, 'LIBERADO')
        self.assertEqual(res.limite, Decimal('10000.00'))


class PromessaPagamentoTestCase(BaseSprint11CTestCase):
    """Testa criação, neutralização de bloqueio e rotina diária de promessas de pagamento."""

    def test_promessa_ativa_neutraliza_bloqueio_por_inadimplencia(self):
        """Parcela vencida vinculada a promessa ATIVA válida não causa bloqueio comercial."""
        vencimento = self.hoje - timedelta(days=15)
        _, parcela = self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('400.00'), vencimento)

        # Antes da promessa: bloqueado
        res_antes = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('100.00'))
        self.assertEqual(res_antes.status, 'BLOQUEADO_FINANCEIRO')

        # Cria promessa para daqui a 7 dias
        data_prom = self.hoje + timedelta(days=7)
        promessa = criar_promessa_pagamento(
            cliente=self.cliente_comum,
            parcelas=[parcela],
            data_promessa=data_prom,
            usuario=self.admin_user,
            observacao="Prometeu pagar no dia 15 após recebimento"
        )
        self.assertEqual(promessa.status, 'ATIVA')

        # Após promessa ativa: liberado
        res_depois = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('100.00'))
        self.assertEqual(res_depois.status, 'LIBERADO')

    def test_validacao_limite_dias_e_max_promessas_ativas(self):
        """Valida que promessa rejeita prazos maiores que max_dias_promessa e excesso de promessas ativas."""
        param = obter_parametro_credito(self.tenant)
        param.max_dias_promessa = 10
        param.max_promessas_ativas = 1
        param.save()

        vencimento = self.hoje - timedelta(days=5)
        _, p1 = self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('100.00'), vencimento)
        _, p2 = self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('200.00'), vencimento)

        # 1. Tentar prazo de 15 dias (> 10)
        with self.assertRaises(ValidationError):
            criar_promessa_pagamento(
                cliente=self.cliente_comum,
                parcelas=[p1],
                data_promessa=self.hoje + timedelta(days=15),
                usuario=self.admin_user
            )

        # 2. Criar 1ª promessa com sucesso
        criar_promessa_pagamento(
            cliente=self.cliente_comum,
            parcelas=[p1],
            data_promessa=self.hoje + timedelta(days=5),
            usuario=self.admin_user
        )

        # 3. Tentar 2ª promessa quando o limite é 1
        with self.assertRaises(ValidationError):
            criar_promessa_pagamento(
                cliente=self.cliente_comum,
                parcelas=[p2],
                data_promessa=self.hoje + timedelta(days=5),
                usuario=self.admin_user
            )

    def test_job_diario_marca_quebrada_e_cumprida(self):
        """Job diário marca QUEBRADA promessa vencida sem pagamento e CUMPRIDA quando paga."""
        vencimento = self.hoje - timedelta(days=20)
        _, p1 = self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('300.00'), vencimento)
        _, p2 = self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('500.00'), vencimento)

        # Promessa 1: data no passado (ontem) sem quitação
        prom1 = PromessaPagamento.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_comum,
            data_promessa=self.hoje - timedelta(days=1),
            valor=Decimal('300.00'),
            status='ATIVA',
            criado_por=self.admin_user
        )
        prom1.parcelas.set([p1])

        # Promessa 2: quitada
        prom2 = PromessaPagamento.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_comum,
            data_promessa=self.hoje + timedelta(days=5),
            valor=Decimal('500.00'),
            status='ATIVA',
            criado_por=self.admin_user
        )
        prom2.parcelas.set([p2])
        p2.saldo_em_aberto = Decimal('0.00')
        p2.status = 'PAGA'
        p2.save()

        # Executa job diário
        res = atualizar_status_promessas_diario(tenant=self.tenant)
        self.assertEqual(res['quebradas'], 1)
        self.assertEqual(res['cumpridas'], 1)

        prom1.refresh_from_db()
        prom2.refresh_from_db()
        self.assertEqual(prom1.status, 'QUEBRADA')
        self.assertEqual(prom2.status, 'CUMPRIDA')

        # Com a promessa 1 QUEBRADA, a parcela p1 volta a bloquear o cliente
        res_cred = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('50.00'))
        self.assertEqual(res_cred.status, 'BLOQUEADO_FINANCEIRO')
        self.assertIn('PARCELA_VENCIDA', res_cred.motivos)

    def test_suspensao_regua_cobranca_por_promessa_ativa(self):
        """A existência de promessa ativa suspende o envio automático da régua de cobrança."""
        vencimento = self.hoje - timedelta(days=5)
        _, parcela = self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('250.00'), vencimento)

        regua = ReguaCobranca.objects.create(
            tenant=self.tenant,
            nome="Cobrança D+5",
            dias_offset=5,
            canal="EMAIL",
            template_assunto="Aviso de Vencimento",
            template_corpo="Olá {cliente_nome}, sua fatura de R$ {valor} venceu.",
            ativo=True
        )

        # Cria promessa ativa para a parcela
        criar_promessa_pagamento(
            cliente=self.cliente_comum,
            parcelas=[parcela],
            data_promessa=self.hoje + timedelta(days=7),
            usuario=self.admin_user
        )

        # Executa régua ignorando janela de horário comercial
        envios = executar_regua_cobranca(
            tenant=self.tenant,
            data_referencia=self.hoje,
            ignorar_janela_horario=True
        )
        self.assertEqual(len(envios), 0)


class SegurancaAssistencialHospitalTestCase(BaseSprint11CTestCase):
    """Testa regra de segurança assistencial para clientes hospitalares e gás medicinal."""

    def test_hospital_inadimplente_alerta_e_nao_bloqueia_politica_padrao(self):
        """Cliente hospitalar inadimplente recebe ALERTA_ASSISTENCIAL e não é bloqueado na política padrão."""
        param = obter_parametro_credito(self.tenant)
        self.assertEqual(param.politica_gas_medicinal, 'ALERTAR_E_ESCALAR')

        vencimento = self.hoje - timedelta(days=20)
        self._criar_titulo_e_parcela_a_receber(self.cliente_hospital, Decimal('5000.00'), vencimento)

        res = avaliar_credito(self.cliente_hospital, valor_pedido=Decimal('1200.00'))
        self.assertEqual(res.status, 'ALERTA_ASSISTENCIAL')
        self.assertTrue(res.liberado)
        self.assertIn('PARCELA_VENCIDA', res.motivos)
        self.assertTrue(res.detalhes.get('seguranca_assistencial'))

    def test_item_gas_medicinal_para_cliente_geral_tambem_alerta(self):
        """Cliente comum comprando gás medicinal também é protegido pela segurança assistencial."""
        vencimento = self.hoje - timedelta(days=15)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('3000.00'), vencimento)

        # Produto medicinal
        produto_medicinal = Produto.objects.create(
            tenant=self.tenant,
            nome="Oxigênio Medicinal 10m3",
            categoria="Medicinal",
            capacidade=Decimal('10.00'),
            unidade_medida="m³",
            preco=Decimal('200.00'),
            medicinal=True
        )

        res = avaliar_credito(
            self.cliente_comum,
            valor_pedido=Decimal('400.00'),
            itens=[{'produto': produto_medicinal, 'quantidade': 2}]
        )
        self.assertEqual(res.status, 'ALERTA_ASSISTENCIAL')
        self.assertTrue(res.liberado)
        self.assertTrue(res.detalhes.get('tem_item_medicinal'))

    def test_politica_endurecida_por_escrito_bloqueia_hospital(self):
        """Se o tenant configurar expressamente BLOQUEAR_SEMPRE, bloqueia até hospital."""
        param = obter_parametro_credito(self.tenant)
        param.politica_gas_medicinal = 'BLOQUEAR_SEMPRE'
        param.save()

        vencimento = self.hoje - timedelta(days=20)
        self._criar_titulo_e_parcela_a_receber(self.cliente_hospital, Decimal('5000.00'), vencimento)

        res = avaliar_credito(self.cliente_hospital, valor_pedido=Decimal('1200.00'))
        self.assertEqual(res.status, 'BLOQUEADO_FINANCEIRO')
        self.assertFalse(res.liberado)


class IsencaoEDegradacaoTestCase(BaseSprint11CTestCase):
    """Testa isenção controlada de clientes e degradação graciosa com módulo desligado."""

    def test_cliente_com_isencao_valida_liberado(self):
        """Cliente com bloqueio_isento ativo e dentro da validade não sofre bloqueio."""
        self.cliente_comum.bloqueio_isento = True
        self.cliente_comum.isencao_justificativa = "Parceria estratégica com diretoria"
        self.cliente_comum.isencao_validade = self.hoje + timedelta(days=30)
        self.cliente_comum.save()

        # Inadimplente há 30 dias
        vencimento = self.hoje - timedelta(days=30)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('8000.00'), vencimento)

        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('1500.00'))
        self.assertEqual(res.status, 'LIBERADO')
        self.assertTrue(res.liberado)
        self.assertEqual(res.detalhes.get('motivo'), 'CLIENTE_ISENTO')

    def test_cliente_com_isencao_expirada_sofre_bloqueio(self):
        """Isenção vencida perde efeito e volta a bloquear cliente inadimplente."""
        self.cliente_comum.bloqueio_isento = True
        self.cliente_comum.isencao_justificativa = "Antiga autorização de diretoria"
        self.cliente_comum.isencao_validade = self.hoje - timedelta(days=1)  # Expirou ontem
        self.cliente_comum.save()

        vencimento = self.hoje - timedelta(days=20)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('2000.00'), vencimento)

        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('500.00'))
        self.assertEqual(res.status, 'BLOQUEADO_FINANCEIRO')

    def test_modulo_financeiro_desligado_devolve_liberado(self):
        """Com modulo_financeiro_ativo=False, avaliar_credito devolve LIBERADO sem consultar débitos."""
        self.tenant.modulo_financeiro_ativo = False
        self.tenant.save()

        vencimento = self.hoje - timedelta(days=60)
        self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('50000.00'), vencimento)

        res = avaliar_credito(self.cliente_comum, valor_pedido=Decimal('10000.00'))
        self.assertEqual(res.status, 'LIBERADO')
        self.assertTrue(res.liberado)
        self.assertEqual(res.detalhes.get('motivo'), 'MODULO_FINANCEIRO_INATIVO')


class LiberacaoBloqueioAuditoriaTestCase(BaseSprint11CTestCase):
    """Testa liberação formal e auditada de venda com BLOQUEADO_FINANCEIRO."""

    def setUp(self):
        super().setUp()
        # Venda com status BLOQUEADO_FINANCEIRO
        self.venda = Venda.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_comum,
            filial=self.filial,
            status='BLOQUEADO_FINANCEIRO',
            valor_total=Decimal('1500.00')
        )

    def test_liberacao_sem_permissao_rejeitada(self):
        """Usuário vendedor sem permissão é rejeitado com PermissionDenied."""
        with self.assertRaises(PermissionDenied):
            liberar_bloqueio_venda(
                venda=self.venda,
                usuario=self.vendedor_user,
                motivo="Tentativa de liberação sem permissão"
            )

    def test_liberacao_com_motivo_curto_rejeitada(self):
        """Motivo com menos de 5 caracteres deve falhar na validação."""
        with self.assertRaises(ValidationError):
            liberar_bloqueio_venda(
                venda=self.venda,
                usuario=self.admin_user,
                motivo="Ok"
            )

    def test_liberacao_com_permissao_e_motivo_valido_sucesso_auditado(self):
        """Administrador ou usuário com permissão libera venda com auditoria completa."""
        liberacao = liberar_bloqueio_venda(
            venda=self.venda,
            usuario=self.admin_user,
            motivo="Autorizado pelo Diretor Financeiro conforme e-mail protocolo #9988."
        )

        self.assertIsNotNone(liberacao.id)
        self.assertEqual(liberacao.venda, self.venda)
        self.assertEqual(liberacao.usuario, self.admin_user)
        self.assertEqual(liberacao.valor, Decimal('1500.00'))

        self.venda.refresh_from_db()
        self.assertEqual(self.venda.status, 'Pendente')

    def test_liberacao_via_api_action(self):
        """Testa liberação via endpoint POST /vendas/api/{id}/liberar-bloqueio/."""
        # 1. Vendedor sem permissão -> 403
        resp_vend = self.client_vendedor.post(
            f"/vendas/api/{self.venda.id}/liberar-bloqueio/",
            {'motivo': "Liberação pelo vendedor sem alçada"}
        )
        self.assertEqual(resp_vend.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Admin com motivo curto -> 400
        resp_curto = self.client_admin.post(
            f"/vendas/api/{self.venda.id}/liberar-bloqueio/",
            {'motivo': "123"}
        )
        self.assertEqual(resp_curto.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Admin com motivo válido -> 200 OK
        resp_ok = self.client_admin.post(
            f"/vendas/api/{self.venda.id}/liberar-bloqueio/",
            {'motivo': "Autorizado formalmente para entrega emergencial."}
        )
        self.assertEqual(resp_ok.status_code, status.HTTP_200_OK)
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.status, 'Pendente')


class PainelBloqueiosEMultiTenantTestCase(BaseSprint11CTestCase):
    """Testa painel de bloqueios e isolamento multi-tenant (404)."""

    def setUp(self):
        super().setUp()
        # Tenant B
        self.tenant_b = Tenant.objects.create(
            razao_social="Distribuidora Secundária B Ltda",
            nome_fantasia="Distribuidora B",
            cnpj="55.666.777/0001-33",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user_b = User.objects.create_user(
            username="admin_tenant_b",
            email="admin@tenantb.com",
            password="password123"
        )
        Membership.objects.create(user=self.user_b, tenant=self.tenant_b, papel="ADMIN")

        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)

    def test_painel_bloqueios_api(self):
        """Verifica se /financeiro/api/painel-bloqueios/ compila dados do tenant."""
        Venda.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_comum,
            filial=self.filial,
            status='BLOQUEADO_FINANCEIRO',
            valor_total=Decimal('2300.00')
        )

        resp = self.client_admin.get("/financeiro/api/painel-bloqueios/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        dados = resp.data
        self.assertIn('vendas_bloqueadas', dados)
        self.assertIn('promessas_ativas', dados)
        self.assertIn('liberacoes_recentes', dados)
        self.assertEqual(dados['total_vendas_bloqueadas'], 1)

    def test_multi_tenant_isolamento_404(self):
        """Usuário do Tenant B não visualiza nem edita parâmetros ou promessas do Tenant A."""
        param_a = obter_parametro_credito(self.tenant)

        # Tenant B tenta acessar parâmetro de crédito do Tenant A -> 404
        resp = self.client_b.get(f"/financeiro/api/parametros-credito/{param_a.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # Promessa do Tenant A
        vencimento = self.hoje + timedelta(days=5)
        _, parc = self._criar_titulo_e_parcela_a_receber(self.cliente_comum, Decimal('100.00'), vencimento)
        prom_a = PromessaPagamento.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_comum,
            data_promessa=vencimento,
            valor=Decimal('100.00'),
            status='ATIVA',
            criado_por=self.admin_user
        )

        resp_prom = self.client_b.get(f"/financeiro/api/promessas-pagamento/{prom_a.id}/")
        self.assertEqual(resp_prom.status_code, status.HTTP_404_NOT_FOUND)
