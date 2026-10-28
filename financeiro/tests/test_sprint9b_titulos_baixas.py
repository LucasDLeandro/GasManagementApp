import datetime
from decimal import Decimal
import threading
import uuid
import pytest

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from hypothesis import given, strategies as st, settings, HealthCheck
from rest_framework import status
from rest_framework.test import APIClient

from core.money import allocate, quantize
from core.models import Filial, Membership, Tenant
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from clientes.models import Cliente
from financeiro.models import (
    AlcadaAprovacao,
    AprovacaoTitulo,
    BaixaParcela,
    CentroCusto,
    CondicaoPagamento,
    ContaFinanceira,
    Fornecedor,
    ImportacaoSaldoAbertura,
    LancamentoContabil,
    MovimentoConta,
    ParametroFinanceiroTenant,
    ParcelaFinanceira,
    PendenciaContabilizacao,
    PlanoContas,
    RateioCentroCusto,
    Renegociacao,
    RetencaoTitulo,
    TituloFinanceiro,
)
from financeiro.seeds import seed_financeiro_tenant_completo
from financeiro.services.titulos import (
    criar_titulo,
    gerar_parcelas,
    transicionar,
    calcular_encargos,
    pode_aprovar,
    aprovar_titulo,
    renegociar_parcelas,
    obter_parametros_financeiros,
)
from financeiro.services.baixas import (
    baixar_parcela,
    baixar_em_lote,
    estornar_baixa,
)
from financeiro.services.saldo_abertura import (
    simular_saldo_abertura,
    confirmar_saldo_abertura,
    estornar_saldo_abertura,
)
from financeiro.contabilizacao import (
    processar_evento_financeiro,
    reprocessar_pendencia,
)

User = get_user_model()


class BaseSprint9BTestCase(TestCase):
    """Setup base multi-tenant para testes da Sprint 9B."""

    def setUp(self):
        super().setUp()
        cnpj_a = f"11.222.{uuid.uuid4().hex[:3]}/0001-91"
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Alfa Oxigênio Ltda",
            nome_fantasia="Alfa Gases",
            cnpj=cnpj_a,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        # Ativa contexto do Tenant A antes de criar qualquer modelo TenantAware
        self.token = set_current_tenant(self.tenant)

        self.filial = Filial.objects.create(
            tenant=self.tenant,
            nome="Matriz Curitiba",
            cnpj=cnpj_a,
            uf="PR",
            matriz=True
        )
        self.user = User.objects.create_user(
            username=f"gestor_{uuid.uuid4().hex[:6]}",
            email="gestor@alfagases.com.br",
            password="secret_password"
        )
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True
        )

        self.user2 = User.objects.create_user(
            username=f"diretor_{uuid.uuid4().hex[:6]}",
            email="diretor@alfagases.com.br",
            password="secret_password"
        )
        self.membership2 = Membership.objects.create(
            user=self.user2,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True
        )

        # Seeds contábeis completos no Tenant A
        seed_financeiro_tenant_completo(self.tenant)

        # Contas contábeis chave
        self.conta_caixa = PlanoContas.objects.get(codigo_estrutural='1.1.1.01')
        self.conta_banco = PlanoContas.objects.get(codigo_estrutural='1.1.1.02')
        self.conta_clientes = PlanoContas.objects.get(codigo_estrutural='1.1.2.01')
        self.conta_fornecedores = PlanoContas.objects.get(codigo_estrutural='2.1.1')
        self.conta_receita_med = PlanoContas.objects.get(codigo_estrutural='3.1.1')
        self.conta_desp_adm = PlanoContas.objects.get(codigo_estrutural='5.3')

        # Centros de Custo
        self.cc_adm = CentroCusto.objects.get(codigo='CC-04')
        self.cc_com = CentroCusto.objects.get(codigo='CC-02')

        # Condição de Pagamento
        self.cond_30_60 = CondicaoPagamento.objects.filter(tenant=self.tenant).first()

        # Conta Financeira bancária
        self.conta_fin = ContaFinanceira.objects.create(
            tenant=self.tenant,
            nome="Banco do Brasil C/C",
            tipo="BANCO",
            conta_contabil=self.conta_banco,
            saldo_inicial=Decimal('10000.00'),
            ativo=True
        )

        # Fornecedor
        self.fornecedor = Fornecedor.objects.create(
            tenant=self.tenant,
            razao_social="White Martins Gases Industriais",
            documento=f"44.555.{uuid.uuid4().hex[:3]}/0001-88",
            tipo_pessoa="PJ"
        )

        # Cliente
        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome="Hospital Santa Cruz",
            cnpj=f"33.444.{uuid.uuid4().hex[:3]}/0001-77"
        )

        # Tenant Secundário para testes multi-tenant
        cnpj_b = f"22.333.{uuid.uuid4().hex[:3]}/0001-92"
        self.tenant_b = Tenant.objects.create(
            razao_social="Beta Comércio de Gases",
            nome_fantasia="Beta Gás",
            cnpj=cnpj_b,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user_b = User.objects.create_user(
            username=f"user_b_{uuid.uuid4().hex[:6]}",
            email="userb@betagas.com.br",
            password="secret_password"
        )
        Membership.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            papel="ADMIN",
            ativo=True
        )
        with tenant_context(self.tenant_b):
            seed_financeiro_tenant_completo(self.tenant_b)

        # Client DRF autenticado
        self.client_drf = APIClient()
        self.client_drf.force_authenticate(user=self.user)

        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()


class TestTitulosERateioSprint9B(BaseSprint9BTestCase):
    """Testes de títulos, rateio de centro de custo, retenções e parcelamento exato."""

    def test_rateio_e_parcelamento_com_residuo_soma_exata(self):
        """
        Teste 1 (Tarefa 4 & 5): Rateio e parcelamento com valores com resíduo de centavos
        alocam o centavo remanescente na última linha, garantindo soma estritamente exata.
        """
        valor_bruto = Decimal('100.00')

        # Condição de 3 parcelas iguais (100 / 3 = 33.33 + 33.33 + 33.34)
        cond_3x = CondicaoPagamento.objects.create(
            tenant=self.tenant,
            nome="3x Sem Juros",
            parcelas_json=[
                {"dias": 30, "percentual": 33.3333},
                {"dias": 60, "percentual": 33.3333},
                {"dias": 90, "percentual": 33.3334},
            ]
        )

        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=valor_bruto,
            cliente=self.cliente,
            condicao_pagamento=cond_3x,
            rateios=[
                {"centro_custo": self.cc_adm.id, "percentual": Decimal('33.3333')},
                {"centro_custo": self.cc_com.id, "percentual": Decimal('66.6667')},
            ]
        )

        # 1. Verifica rateios
        rateios = list(titulo.rateios.all().order_by('id'))
        assert len(rateios) == 2
        soma_rateios = sum(r.valor_rateado for r in rateios)
        assert soma_rateios == valor_bruto
        assert rateios[0].valor_rateado == Decimal('33.33')
        assert rateios[1].valor_rateado == Decimal('66.67')

        # 2. Verifica parcelas
        parcelas = list(titulo.parcelas.all().order_by('numero_parcela'))
        assert len(parcelas) == 3
        soma_parcelas = sum(p.valor_nominal for p in parcelas)
        assert soma_parcelas == valor_bruto
        assert parcelas[0].valor_nominal == Decimal('33.33')
        assert parcelas[1].valor_nominal == Decimal('33.33')
        assert parcelas[2].valor_nominal == Decimal('33.34')

    def test_titulo_com_retencoes_fiscais_f13(self):
        """
        Teste Tarefa 3 (F-13): Título a pagar com retenções federais e municipais.
        valor_liquido_esperado = valor_bruto - soma(retencoes).
        """
        conta_impostos = PlanoContas.objects.get(codigo_estrutural='2.1.2')

        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='PAGAR',
            conta_gerencial=self.conta_desp_adm,
            valor_bruto=Decimal('1000.00'),
            fornecedor=self.fornecedor,
            retencoes=[
                {
                    'tipo': 'IRRF',
                    'base': Decimal('1000.00'),
                    'aliquota': Decimal('0.0150'),  # 1.5%
                    'conta_passivo': conta_impostos.id,
                    'data_recolhimento': timezone.localdate() + datetime.timedelta(days=20)
                },
                {
                    'tipo': 'ISS',
                    'base': Decimal('1000.00'),
                    'aliquota': Decimal('0.0500'),  # 5.0%
                    'conta_passivo': conta_impostos.id,
                    'data_recolhimento': timezone.localdate() + datetime.timedelta(days=15)
                }
            ]
        )

        assert titulo.valor_bruto == Decimal('1000.00')
        assert titulo.valor_retencoes == Decimal('65.00')  # 15 + 50
        assert titulo.valor_liquido_esperado == Decimal('935.00')

        # As parcelas devem totalizar o valor líquido esperado
        soma_parc = sum(p.valor_nominal for p in titulo.parcelas.all())
        assert soma_parc == Decimal('935.00')

    def test_validacao_origem_tipo_f12(self):
        """
        Teste Tarefa 1 (F-12):
        UniqueConstraint(tenant, tipo, origem_tipo, origem_id) impede títulos duplicados para a mesma origem operacional.
        """
        criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=Decimal('250.00'),
            cliente=self.cliente,
            origem_tipo='VENDA',
            origem_id='VENDA-1234'
        )

        # Tentativa de criar outro título com a mesma origem para o mesmo tenant deve falhar
        with pytest.raises(Exception):
            criar_titulo(
                tenant=self.tenant,
                tipo='RECEBER',
                conta_gerencial=self.conta_receita_med,
                valor_bruto=Decimal('250.00'),
                cliente=self.cliente,
                origem_tipo='VENDA',
                origem_id='VENDA-1234'
            )

    def test_maquina_estados_titulo_e_bloqueio_cancelamento(self):
        """
        Teste Tarefa 2: Máquina de estados do título.
        Cancelar título com baixa ativa é estritamente proibido.
        """
        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=Decimal('500.00'),
            cliente=self.cliente
        )
        assert titulo.status == 'ABERTO'
        parc = titulo.parcelas.first()

        # Baixa parcial de R$ 100
        baixa = baixar_parcela(
            tenant=self.tenant,
            parcela_id=parc.id,
            conta_financeira_id=self.conta_fin.id,
            valor_principal=Decimal('100.00')
        )
        titulo.refresh_from_db()
        assert titulo.status == 'PARCIAL'

        # Tenta cancelar título diretamente com baixa ativa
        with pytest.raises(ValidationError) as exc:
            transicionar(titulo, 'CANCELADO')
        assert "baixas ativas" in str(exc.value).lower()

        # Estorna a baixa e agora pode cancelar
        estornar_baixa(baixa_id=baixa.id, tenant=self.tenant)
        titulo.refresh_from_db()
        assert titulo.status == 'ABERTO'

        transicionar(titulo, 'CANCELADO')
        titulo.refresh_from_db()
        assert titulo.status == 'CANCELADO'
        assert titulo.parcelas.first().status == 'CANCELADA'


class TestBaixasEContabilizacaoSprint9B(BaseSprint9BTestCase):
    """Testes de liquidação de parcelas, estornos e lançamentos contábeis perfeitamente balanceados."""

    def test_baixa_parcial_seguida_de_final_e_estorno_recompoe_saldos(self):
        """
        Teste 2 do prompt: Baixa parcial seguida de baixa final; estorno de baixa
        recompõe saldo da parcela e da conta financeira.
        """
        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=Decimal('500.00'),
            cliente=self.cliente
        )
        parcela = titulo.parcelas.first()
        assert parcela.saldo_em_aberto == Decimal('500.00')

        saldo_inicial_conta = self.conta_fin.saldo_atual

        # 1. Baixa Parcial de R$ 200,00
        baixa_1 = baixar_parcela(
            tenant=self.tenant,
            parcela_id=parcela.id,
            conta_financeira_id=self.conta_fin.id,
            valor_principal=Decimal('200.00'),
            usuario=self.user
        )
        parcela.refresh_from_db()
        titulo.refresh_from_db()

        assert parcela.saldo_em_aberto == Decimal('300.00')
        assert parcela.status == 'PARCIAL'
        assert titulo.status == 'PARCIAL'
        assert self.conta_fin.saldo_atual == saldo_inicial_conta + Decimal('200.00')

        # Verifica lançamento contábil da baixa 1
        assert baixa_1.lancamento_contabil is not None
        partidas_1 = list(baixa_1.lancamento_contabil.partidas.all())
        deb_1 = sum(p.valor for p in partidas_1 if p.tipo_partida == 'DEBITO')
        crd_1 = sum(p.valor for p in partidas_1 if p.tipo_partida == 'CREDITO')
        assert deb_1 == crd_1 == Decimal('200.00')

        # 2. Baixa Final de R$ 300,00 com Juros de R$ 10,00 e Multa de R$ 5,00
        baixa_2 = baixar_parcela(
            tenant=self.tenant,
            parcela_id=parcela.id,
            conta_financeira_id=self.conta_fin.id,
            valor_principal=Decimal('300.00'),
            valor_juros=Decimal('10.00'),
            valor_multa=Decimal('5.00'),
            usuario=self.user
        )
        parcela.refresh_from_db()
        titulo.refresh_from_db()

        assert parcela.saldo_em_aberto == Decimal('0.00')
        assert parcela.status == 'PAGA'
        assert titulo.status == 'LIQUIDADO'
        # Total movimentado = 300 + 10 + 5 = 315.00
        assert self.conta_fin.saldo_atual == saldo_inicial_conta + Decimal('200.00') + Decimal('315.00')

        # Verifica partidas dobradas da baixa final (Banco D: 315 | Clientes C: 300 | Receitas Fin C: 15)
        partidas_2 = list(baixa_2.lancamento_contabil.partidas.all())
        deb_2 = sum(p.valor for p in partidas_2 if p.tipo_partida == 'DEBITO')
        crd_2 = sum(p.valor for p in partidas_2 if p.tipo_partida == 'CREDITO')
        assert deb_2 == crd_2 == Decimal('315.00')

        # 3. Estorno da Baixa Final
        estornar_baixa(baixa_id=baixa_2.id, tenant=self.tenant, motivo="Erro de cobrança de encargos")
        parcela.refresh_from_db()
        titulo.refresh_from_db()
        baixa_2.refresh_from_db()

        assert baixa_2.estornado is True
        assert parcela.saldo_em_aberto == Decimal('300.00')
        assert parcela.status == 'PARCIAL'
        assert titulo.status == 'PARCIAL'
        assert self.conta_fin.saldo_atual == saldo_inicial_conta + Decimal('200.00')

    def test_calculo_encargos_pro_rata_die(self):
        """
        Teste Tarefa 6: calcular_encargos calcula multa de 2% e juros diários pro rata die.
        """
        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=Decimal('1000.00'),
            cliente=self.cliente
        )
        parc = titulo.parcelas.first()
        # Venceu há 10 dias atrás
        parc.data_vencimento = timezone.localdate() - datetime.timedelta(days=10)
        parc.save()

        res = calcular_encargos(parc)
        assert res['dias_atraso'] == 10
        # Multa: 2% de 1000 = 20.00
        assert res['valor_multa'] == Decimal('20.00')
        # Juros: 10 dias * 0.0333% ao dia = 0.333% de 1000 = 3.33
        assert res['valor_juros'] == Decimal('3.33')
        assert res['total_encargos'] == Decimal('23.33')
        assert res['total_devido'] == Decimal('1023.33')

    def test_renegociacao_de_parcelas(self):
        """
        Teste Tarefa 7: Renegociação substitui parcelas vencidas de origem por novas parcelas.
        """
        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=Decimal('1000.00'),
            cliente=self.cliente
        )
        p1 = titulo.parcelas.first()

        novas_parcelas_input = [
            {"dias": 15, "valor": Decimal('450.00')},
            {"dias": 30, "valor": Decimal('450.00')},
        ]

        reneg = renegociar_parcelas(
            tenant=self.tenant,
            parcelas_origem_ids=[p1.id],
            novas_parcelas=novas_parcelas_input,
            desconto_concedido=Decimal('100.00'),
            motivo="Acordo amigável para quitação",
            usuario=self.user
        )

        p1.refresh_from_db()
        assert p1.status == 'RENEGOCIADA'
        assert p1.saldo_em_aberto == Decimal('0.00')

        # Novas parcelas
        novas = list(reneg.novas_parcelas.all().order_by('numero_parcela'))
        assert len(novas) == 2
        assert novas[0].valor_nominal == Decimal('450.00')
        assert novas[1].valor_nominal == Decimal('450.00')
        assert sum(n.valor_nominal for n in novas) == Decimal('900.00')

    def test_baixa_em_lote_multiplas_parcelas(self):
        """
        Teste Tarefa 6/12: Baixa em lote de múltiplas parcelas com liquidação atômica.
        """
        cond_2x = CondicaoPagamento.objects.create(
            tenant=self.tenant,
            nome="2x 30/60 Teste Baixa",
            parcelas_json=[
                {"dias": 30, "percentual": 50.0},
                {"dias": 60, "percentual": 50.0},
            ]
        )
        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=Decimal('600.00'),
            cliente=self.cliente,
            condicao_pagamento=cond_2x
        )
        parcelas = list(titulo.parcelas.all().order_by('numero_parcela'))
        assert len(parcelas) == 2

        itens = [
            {'parcela_id': parcelas[0].id, 'valor_principal': Decimal('300.00')},
            {'parcela_id': parcelas[1].id, 'valor_principal': Decimal('300.00')},
        ]

        baixas = baixar_em_lote(
            tenant=self.tenant,
            conta_financeira_id=self.conta_fin.id,
            itens_baixa=itens,
            usuario=self.user
        )

        assert len(baixas) == 2
        for p in parcelas:
            p.refresh_from_db()
            assert p.status == 'PAGA'
            assert p.saldo_em_aberto == Decimal('0.00')

        titulo.refresh_from_db()
        assert titulo.status == 'LIQUIDADO'


class TestAlcadaEAprovacaoSprint9B(BaseSprint9BTestCase):
    """Testes de alçadas de aprovação, segregação de funções e alçadas automáticas (Correção F-03)."""

    def test_titulo_acima_da_primeira_alcada_entra_em_aprovacao_e_segregacao_estrita(self):
        """
        Teste 4 do prompt (F-03):
        Título PAGAR acima da primeira alçada entra em EM_APROVACAO.
        O lançador/criador NÃO pode aprovar nem baixar o título.
        """
        param = obter_parametros_financeiros(self.tenant)
        param.valor_primeira_alcada = Decimal('1000.00')
        param.save()

        # Título de R$ 1.500 criado pelo usuário gestor
        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='PAGAR',
            conta_gerencial=self.conta_desp_adm,
            valor_bruto=Decimal('1500.00'),
            fornecedor=self.fornecedor,
            criado_por=self.user
        )

        assert titulo.status == 'EM_APROVACAO'

        # 1. Regra de Segregação: Lançador NÃO pode aprovar
        assert pode_aprovar(titulo, self.user) is False

        with pytest.raises(ValidationError) as exc:
            aprovar_titulo(
                titulo_id=titulo.id,
                usuario=self.user,
                decisao='APROVADO',
                motivo='Tentando auto-aprovar'
            )
        assert "segregação" in str(exc.value).lower()

        # 2. Lançador NÃO pode baixar título enquanto em aprovação ou sendo o criador
        parc = titulo.parcelas.first()
        with pytest.raises(ValidationError) as exc_baixa:
            baixar_parcela(
                tenant=self.tenant,
                parcela_id=parc.id,
                conta_financeira_id=self.conta_fin.id,
                valor_principal=Decimal('500.00'),
                usuario=self.user
            )
        assert "segregação" in str(exc_baixa.value).lower() or "aberto" in str(exc_baixa.value).lower()

        # 3. Outro usuário com perfil diretoria aprova o título
        assert pode_aprovar(titulo, self.user2) is True
        aprovacao = aprovar_titulo(
            titulo_id=titulo.id,
            usuario=self.user2,
            decisao='APROVADO',
            motivo='Aprovado conforme verba orçamentária'
        )
        assert aprovacao.decisao == 'APROVADO'

        titulo.refresh_from_db()
        assert titulo.status == 'ABERTO'

        # 4. Agora o usuário 2 (não criador) pode baixar normalmente
        baixa = baixar_parcela(
            tenant=self.tenant,
            parcela_id=parc.id,
            conta_financeira_id=self.conta_fin.id,
            valor_principal=Decimal('1500.00'),
            usuario=self.user2
        )
        assert baixa.id is not None
        titulo.refresh_from_db()
        assert titulo.status == 'LIQUIDADO'


class TestContabilizacaoEventosSprint9B(BaseSprint9BTestCase):
    """Testes da tabela de eventos de contabilização automática e resiliência (Tarefas 9 e 10)."""

    def test_todos_os_eventos_geram_lancamentos_balanceados(self):
        """
        Teste 5 do prompt: Cada linha da tabela de contabilização gera lançamento balanceado.
        """
        origem_base = uuid.uuid4().hex[:6]

        eventos_para_testar = [
            (
                'venda_faturada',
                {
                    'tenant': self.tenant,
                    'venda_id': f'VD-{origem_base}-1',
                    'cliente_id': self.cliente.id,
                    'valor_bruto': Decimal('1200.00'),
                    'valor_deducoes': Decimal('120.00'),
                    'valor_custo': Decimal('600.00'),
                    'tipo_produto': 'MEDICINAL',
                }
            ),
            (
                'fatura_estadia_fechada',
                {
                    'tenant': self.tenant,
                    'fatura_id': f'EST-{origem_base}-1',
                    'cliente_id': self.cliente.id,
                    'valor_total': Decimal('450.00'),
                }
            ),
            (
                'entrada_gas_granel',
                {
                    'tenant': self.tenant,
                    'entrada_id': f'GRANEL-{origem_base}-1',
                    'fornecedor_id': self.fornecedor.id,
                    'valor_total': Decimal('5000.00'),
                    'valor_impostos_recuperar': Decimal('500.00'),
                }
            ),
            (
                'lote_envase_fechado',
                {
                    'tenant': self.tenant,
                    'lote_id': f'LOTE-{origem_base}-1',
                    'custo_gas': Decimal('800.00'),
                    'custo_energia': Decimal('100.00'),
                    'custo_mod': Decimal('150.00'),
                }
            ),
            (
                'perda_gas_registrada',
                {
                    'tenant': self.tenant,
                    'origem_id': f'PERDA-{origem_base}-1',
                    'valor_perda': Decimal('220.00'),
                }
            ),
            (
                'compra_imobilizado',
                {
                    'tenant': self.tenant,
                    'origem_id': f'IMOB-{origem_base}-1',
                    'fornecedor_id': self.fornecedor.id,
                    'valor_total': Decimal('12000.00'),
                }
            ),
            (
                'reteste_concluido',
                {
                    'tenant': self.tenant,
                    'origem_id': f'RETESTE-{origem_base}-1',
                    'fornecedor_id': self.fornecedor.id,
                    'valor_servico': Decimal('350.00'),
                    'capitalizar': False,
                }
            ),
            (
                'baixa_patrimonial',
                {
                    'tenant': self.tenant,
                    'origem_id': f'BAIXAIMOB-{origem_base}-1',
                    'custo_original': Decimal('10000.00'),
                    'depreciacao_acumulada': Decimal('4000.00'),
                    'valor_venda': Decimal('6500.00'),
                }
            ),
            (
                'extravio_cobrado',
                {
                    'tenant': self.tenant,
                    'origem_id': f'EXTRAVIO-{origem_base}-1',
                    'cliente_id': self.cliente.id,
                    'valor_indenizacao': Decimal('850.00'),
                }
            ),
            (
                'caucao_recebida',
                {
                    'tenant': self.tenant,
                    'origem_id': f'CAUCAO-{origem_base}-1',
                    'valor_caucao': Decimal('300.00'),
                }
            ),
        ]

        for evento_nome, payload in eventos_para_testar:
            res = processar_evento_financeiro(evento_nome, payload)
            assert res.get('status') == 'SUCESSO', f"Falha no evento {evento_nome}: {res}"

            origem_id = str(payload.get('origem_id') or payload.get('venda_id') or payload.get('fatura_id') or payload.get('lote_id') or payload.get('entrada_id'))
            lancamentos = LancamentoContabil.objects.filter(
                tenant=self.tenant,
                origem_tipo=evento_nome,
                origem_id=origem_id
            )
            assert lancamentos.exists(), f"Lançamento não encontrado para {evento_nome}"

            for lanc in lancamentos:
                partidas = list(lanc.partidas.all())
                total_deb = sum(p.valor for p in partidas if p.tipo_partida == 'DEBITO')
                total_crd = sum(p.valor for p in partidas if p.tipo_partida == 'CREDITO')
                assert total_deb == total_crd, f"Lançamento desbalanceado em {evento_nome}: D={total_deb} != C={total_crd}"
                assert total_deb > Decimal('0.00')

    def test_idempotencia_reprocessar_mesmo_evento_nao_duplica(self):
        """
        Teste 3 do prompt: Reprocessar o mesmo evento não duplica título nem lançamento.
        """
        payload = {
            'tenant': self.tenant,
            'venda_id': 'VEND-IDEM-001',
            'cliente_id': self.cliente.id,
            'valor_bruto': Decimal('750.00'),
            'valor_deducoes': Decimal('50.00'),
            'valor_custo': Decimal('300.00'),
            'tipo_produto': 'MEDICINAL',
        }

        # Primeira execução
        res1 = processar_evento_financeiro('venda_faturada', payload)
        assert res1['status'] == 'SUCESSO'

        total_titulos_antes = TituloFinanceiro.objects.filter(origem_tipo='VENDA', origem_id='VEND-IDEM-001').count()
        total_lancamentos_antes = LancamentoContabil.objects.filter(origem_tipo='venda_faturada', origem_id='VEND-IDEM-001').count()
        assert total_titulos_antes == 1
        assert total_lancamentos_antes == 1

        # Segunda execução idêntica
        res2 = processar_evento_financeiro('venda_faturada', payload)
        assert res2['status'] == 'JA_PROCESSADO'

        total_titulos_depois = TituloFinanceiro.objects.filter(origem_tipo='VENDA', origem_id='VEND-IDEM-001').count()
        total_lancamentos_depois = LancamentoContabil.objects.filter(origem_tipo='venda_faturada', origem_id='VEND-IDEM-001').count()
        assert total_titulos_depois == 1
        assert total_lancamentos_depois == 1

    def test_venda_sem_modulo_financeiro_ativo_nao_cria_nada(self):
        """
        Teste 7 do prompt: Venda sem modulo_financeiro_ativo não cria título nem lançamento.
        """
        self.tenant.modulo_financeiro_ativo = False
        self.tenant.save()

        payload = {
            'tenant': self.tenant,
            'venda_id': 'VEND-SEM-FIN-01',
            'cliente_id': self.cliente.id,
            'valor_bruto': Decimal('500.00'),
        }

        res = processar_evento_financeiro('venda_faturada', payload)
        assert res['status'] == 'IGNORADO_SEM_MODULO_FINANCEIRO'

        assert not TituloFinanceiro.objects.filter(origem_id='VEND-SEM-FIN-01').exists()
        assert not LancamentoContabil.objects.filter(origem_id='VEND-SEM-FIN-01').exists()

    def test_resiliencia_falha_nao_perde_evento_e_registra_pendencia(self):
        """
        Teste Tarefa 10: Falha no handler não quebra operação de origem e grava PendenciaContabilizacao.
        """
        payload_invalido = {
            'tenant': self.tenant,
            'origem_id': 'EXTRAVIO-FALHA-1',
            # Falta o valor ou cliente obrigatório
            'valor_indenizacao': 'invalido',
        }

        # Não deve levantar exceção não tratada
        res = processar_evento_financeiro('extravio_cobrado', payload_invalido)
        assert res['status'] == 'PENDENCIA_REGISTRADA'

        pendencia = PendenciaContabilizacao.objects.get(
            tenant=self.tenant,
            evento='extravio_cobrado',
            origem_id='EXTRAVIO-FALHA-1'
        )
        assert pendencia.resolvido is False
        assert pendencia.tentativas == 1
        assert "extravio" in pendencia.erro_mensagem.lower() or "decimal" in pendencia.erro_mensagem.lower() or "invalido" in pendencia.erro_mensagem.lower()

        # Reprocessamento após correção do payload
        pendencia.payload_json['valor_indenizacao'] = '350.00'
        pendencia.payload_json['cliente_id'] = str(self.cliente.id)
        pendencia.save()

        reprocessar_pendencia(pendencia.id)
        pendencia.refresh_from_db()
        assert pendencia.resolvido is True
        assert pendencia.tentativas == 2


class TestSaldoAberturaSprint9B(BaseSprint9BTestCase):
    """Testes de importação, simulação e confirmação de saldo de abertura (Tarefa 11 / Lacuna F-15)."""

    def test_simulacao_nao_grava_confirmacao_grava_uma_vez_e_estorno(self):
        """
        Teste 6 do prompt: Saldo de abertura em simulação não grava lançamentos;
        confirmação grava uma vez; tentativa de confirmar duas vezes é bloqueada.
        """
        dados_carga = {
            'saldos_bancarios': [
                {'conta_financeira_id': self.conta_fin.id, 'saldo': '15000.00'}
            ],
            'titulos_receber': [
                {'cliente_id': self.cliente.id, 'valor': '5000.00', 'vencimento': '2026-11-30'}
            ],
            'titulos_pagar': [
                {'fornecedor_id': self.fornecedor.id, 'valor': '8000.00', 'vencimento': '2026-11-15'}
            ],
            'estoques': [
                {'produto_id': 1, 'valor_total': '12000.00'}
            ],
            'imobilizado': [
                {'descricao': 'Caminhão VUC', 'custo_aquisicao': '100000.00', 'depreciacao_acumulada': '20000.00'}
            ]
        }
        # Total Ativo = 15000 + 5000 + 12000 + (100000 - 20000) = 112000.00
        # Total Passivo = 8000.00
        # Total PL Abertura = 104000.00

        dt_corte = timezone.localdate() - datetime.timedelta(days=1)

        # 1. Simulação
        simulacao = simular_saldo_abertura(
            tenant=self.tenant,
            data_corte=dt_corte,
            dados_carga=dados_carga,
            usuario=self.user
        )

        assert simulacao.status == 'SIMULACAO'
        assert simulacao.total_ativo == Decimal('112000.00')
        assert simulacao.total_passivo == Decimal('8000.00')
        assert simulacao.total_pl_abertura == Decimal('104000.00')

        # Não deve haver lançamentos contábeis no razão ainda
        assert LancamentoContabil.objects.filter(origem_tipo='SALDO_ABERTURA').count() == 0

        # 2. Confirmação
        confirmada = confirmar_saldo_abertura(
            importacao_id=simulacao.id,
            tenant=self.tenant,
            usuario=self.user
        )

        assert confirmada.status == 'CONFIRMADO'
        assert confirmada.lancamento is not None

        # Partidas contábeis do lançamento de abertura (Ativo Bruto 132k = Passivo + PL 132k)
        partidas = list(confirmada.lancamento.partidas.all())
        deb = sum(p.valor for p in partidas if p.tipo_partida == 'DEBITO')
        crd = sum(p.valor for p in partidas if p.tipo_partida == 'CREDITO')
        assert deb == crd == Decimal('132000.00')
        assert confirmada.total_pl_abertura == Decimal('104000.00')

        # 3. Tentar confirmar uma segunda importação sem estornar a primeira deve falhar
        sim2 = simular_saldo_abertura(
            tenant=self.tenant,
            data_corte=dt_corte,
            dados_carga=dados_carga,
            usuario=self.user
        )
        with pytest.raises(ValidationError) as exc:
            confirmar_saldo_abertura(
                importacao_id=sim2.id,
                tenant=self.tenant,
                usuario=self.user
            )
        assert "já existe um saldo de abertura confirmado" in str(exc.value).lower() or "já possui um saldo de abertura" in str(exc.value).lower()

        # 4. Estorno da importação confirmada
        estornar_saldo_abertura(
            importacao_id=confirmada.id,
            tenant=self.tenant,
            motivo="Cancelamento de carga para recálculo",
            usuario=self.user
        )
        confirmada.refresh_from_db()
        assert confirmada.status == 'ESTORNADO'
        assert confirmada.lancamento.foi_estornado is True


class TestMultiTenantSprint9B(BaseSprint9BTestCase):
    """Testes de isolamento multi-tenant (Regra 3) provando 404 em acessos cruzados."""

    def test_multi_tenant_404_em_endpoints_novos(self):
        """
        Regra 3: Todo endpoint novo tem teste provando 404 para recurso de outro tenant.
        """
        # Cria título no Tenant A
        titulo_a = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita_med,
            valor_bruto=Decimal('500.00'),
            cliente=self.cliente
        )
        parc_a = titulo_a.parcelas.first()

        # Baixa no Tenant A
        baixa_a = baixar_parcela(
            tenant=self.tenant,
            parcela_id=parc_a.id,
            conta_financeira_id=self.conta_fin.id,
            valor_principal=Decimal('100.00'),
            usuario=self.user
        )

        # Pendência no Tenant A
        pend_a = PendenciaContabilizacao.objects.create(
            tenant=self.tenant,
            evento='teste_evento',
            origem_id='ORIG-999',
            payload_json={'origem_id': 'ORIG-999'},
            erro_mensagem='Erro teste'
        )

        # Importação no Tenant A
        imp_a = ImportacaoSaldoAbertura.objects.create(
            tenant=self.tenant,
            data_corte=timezone.localdate(),
            status='SIMULACAO',
            total_ativo=Decimal('100.00'),
            total_passivo=Decimal('50.00'),
            total_pl_abertura=Decimal('50.00'),
            dados_json={'origem': 'teste'}
        )

        # Usuário do Tenant B tenta acessar recursos do Tenant A via API DRF
        url_titulo = f"/financeiro/api/titulos/{titulo_a.id}/"
        res_tit = self.client_b.get(url_titulo)
        assert res_tit.status_code == status.HTTP_404_NOT_FOUND

        url_parc = f"/financeiro/api/parcelas/{parc_a.id}/"
        res_parc = self.client_b.get(url_parc)
        assert res_parc.status_code == status.HTTP_404_NOT_FOUND

        url_baixa = f"/financeiro/api/baixas/{baixa_a.id}/"
        res_baixa = self.client_b.get(url_baixa)
        assert res_baixa.status_code == status.HTTP_404_NOT_FOUND

        url_pend = f"/financeiro/api/pendencias-contabilizacao/{pend_a.id}/"
        res_pend = self.client_b.get(url_pend)
        assert res_pend.status_code == status.HTTP_404_NOT_FOUND

        url_imp = f"/financeiro/api/saldo-abertura/{imp_a.id}/"
        res_imp = self.client_b.get(url_imp)
        assert res_imp.status_code == status.HTTP_404_NOT_FOUND


class TestConcorrenciaBaixaSprint9B(TransactionTestCase):
    """Teste de concorrência com select_for_update na baixa de parcelas (Regra 5 e 8)."""

    def setUp(self):
        super().setUp()
        cnpj = f"11.999.{uuid.uuid4().hex[:3]}/0001-33"
        self.tenant = Tenant.objects.create(
            razao_social="Concorrencia Gás Ltda",
            nome_fantasia="Conc Gás",
            cnpj=cnpj,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.token = set_current_tenant(self.tenant)
        self.user = User.objects.create_user(
            username=f"conc_user_{uuid.uuid4().hex[:6]}",
            password="pwd"
        )
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True
        )
        seed_financeiro_tenant_completo(self.tenant)

        self.conta_banco = PlanoContas.objects.get(codigo_estrutural='1.1.1.02')
        self.conta_receita = PlanoContas.objects.get(codigo_estrutural='3.1.1')
        self.conta_fin = ContaFinanceira.objects.create(
            tenant=self.tenant,
            nome="Banco Teste Concorrencia",
            tipo="BANCO",
            conta_contabil=self.conta_banco,
            saldo_inicial=Decimal('1000.00'),
            ativo=True
        )
        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome="Cliente Concorrencia",
            cnpj=f"55.666.{uuid.uuid4().hex[:3]}/0001-22"
        )

    def tearDown(self):
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_lancamento;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_delete_lancamento;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_partida;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_delete_partida;")
        reset_current_tenant(self.token)
        super().tearDown()

    def test_concorrencia_baixa_parcela_impede_dupla_liquidacao(self):
        """
        Regra 8: Teste de concorrência onde houver select_for_update.
        Dois threads tentam baixar integralmente a mesma parcela simultaneamente.
        Apenas um thread deve obter sucesso; o outro deve falhar com erro de validação.
        """
        titulo = criar_titulo(
            tenant=self.tenant,
            tipo='RECEBER',
            conta_gerencial=self.conta_receita,
            valor_bruto=Decimal('100.00'),
            cliente=self.cliente
        )
        parc = titulo.parcelas.first()

        erros = []
        sucessos = []
        sqlite_lock = threading.Lock()

        def worker():
            token_t = set_current_tenant(self.tenant)
            try:
                if connection.vendor == 'sqlite':
                    with sqlite_lock:
                        baixa = baixar_parcela(
                            tenant=self.tenant,
                            parcela_id=parc.id,
                            conta_financeira_id=self.conta_fin.id,
                            valor_principal=Decimal('100.00'),
                            usuario=self.user
                        )
                        sucessos.append(baixa.id)
                else:
                    baixa = baixar_parcela(
                        tenant=self.tenant,
                        parcela_id=parc.id,
                        conta_financeira_id=self.conta_fin.id,
                        valor_principal=Decimal('100.00'),
                        usuario=self.user
                    )
                    sucessos.append(baixa.id)
            except Exception as e:
                erros.append(str(e))
            finally:
                connection.close()
                reset_current_tenant(token_t)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exatamente 1 sucesso e 1 erro
        assert len(sucessos) == 1, f"Esperado 1 sucesso, obteve: {sucessos}"
        assert len(erros) == 1, f"Esperado 1 erro, obteve: {erros}"

        parc.refresh_from_db()
        assert parc.status == 'PAGA'
        assert parc.saldo_em_aberto == Decimal('0.00')


class TestHypothesisSprint9B:
    """Testes baseados em propriedade (Hypothesis) para invariantes de parcelamento e rateio (Regra 8)."""

    @settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
    @given(
        valor_centavos=st.integers(min_value=100, max_value=5000000),  # R$ 1,00 a R$ 50.000,00
        n_parcelas=st.integers(min_value=2, max_value=12)
    )
    def test_invariante_allocate_parcelas_soma_exata(self, valor_centavos, n_parcelas):
        """
        Regra 8: Invariante de propriedade via hypothesis.
        A soma de todas as parcelas geradas por allocate DEVE ser estritamente igual
        ao valor total nominal, sem perder ou criar um único centavo.
        """
        total = quantize(Decimal(valor_centavos) / Decimal('100'), 2)
        ratios = [1] * n_parcelas
        parcelas_alocadas = allocate(total, ratios)

        assert sum(parcelas_alocadas) == total
        assert len(parcelas_alocadas) == n_parcelas
        for p in parcelas_alocadas:
            assert p > Decimal('0.00')
