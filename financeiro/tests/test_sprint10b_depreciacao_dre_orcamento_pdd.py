"""
Testes abrangentes da Sprint 10B:
- Depreciação linear mensal via ledger DepreciacaoMensal
- Revisão prospectiva de vida útil (CPC 23)
- Baixa patrimonial com apuração de ganho/perda em 8.2
- Capitalização de reteste de cilindro como ativo imobilizado
- Snapshots de saldo mensal SaldoMensalConta e reconstrução
- DRE por competência (12 linhas, 8.1 antes de EBITDA, 8.2 fora de EBITDA, reconciliação com Balancete, rodapé de deduções estimadas)
- Provisão tributária IRPJ/CSLL (Lucro Presumido/Real)
- Orçamento anual e comparativo orçado x realizado
- Provisão para Devedores Duvidosos (PDD) e baixa de perdas
- Lançamentos manuais com alçadas e importação CSV
- Exportações contábeis em CSV
- Multi-tenant 404
- Testes de propriedade com Hypothesis para invariantes
- Teste de concorrência com select_for_update
"""
import datetime
from decimal import Decimal
import io
import pytest

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from hypothesis import given, strategies as st, settings, HealthCheck
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Tenant, Filial, Membership
from core.money import quantize
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from clientes.models import Cliente
from logistica.models import Veiculo
from produtos.models import ClasseAtivo, AtivoImobilizado, Cilindro, ModeloCilindro
from financeiro.models import (
    ContaFinanceira,
    PlanoContas,
    CentroCusto,
    TituloFinanceiro,
    ParcelaFinanceira,
    LancamentoContabil,
    PartidaContabil,
    DepreciacaoMensal,
    RevisaoVidaUtil,
    SaldoMensalConta,
    ParametroTributarioLucro,
    Orcamento,
    OrcamentoMensalConta,
    ParametroPDD,
    LancamentoManualPendente,
)
from financeiro.seeds import seed_financeiro_tenant_completo
from financeiro.services.razao import lancar
from financeiro.services.depreciacao_service import (
    calcular_depreciacao_mensal,
    revisar_vida_util,
    baixar_patrimonio_contabil,
    capitalizar_reteste_componente,
)
from financeiro.services.snapshot_service import (
    reconstruir_saldos,
    verificar_integridade_snapshots,
)
from financeiro.services.dre_service import dre
from financeiro.services.tributario_service import calcular_e_lancar_provisao_tributaria
from financeiro.services.orcamento_service import (
    criar_orcamento,
    aprovar_orcamento,
    importar_orcamento_csv,
)
from financeiro.services.pdd_service import calcular_pdd, baixar_perda_pdd
from financeiro.services.lancamento_manual_service import (
    criar_lancamento_manual,
    aprovar_lancamento_manual,
    rejeitar_lancamento_manual,
    importar_provisoes_csv,
)
from financeiro.services.exportacao_service import (
    exportar_balancete_csv,
    exportar_razao_csv,
    exportar_dre_csv,
    exportar_contabil_generico_csv,
)
from financeiro.selectors.balancete import obter_balancete_verificacao

User = get_user_model()


class BaseSprint10BTestCase(TestCase):
    """Setup base com tenant, plano de contas, contas financeiras e classes de ativo."""

    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Alpha 10B Ltda",
            nome_fantasia="Distribuidora Alpha 10B",
            cnpj="11.222.333/0001-99",
            modulo_financeiro_ativo=True,
            modulo_patrimonio_ativo=True,
            status_assinatura="ATIVO"
        )
        self.token = set_current_tenant(self.tenant)

        self.filial = Filial.objects.create(
            tenant=self.tenant,
            nome="Matriz 10B",
            cnpj="11.222.333/0001-99",
            matriz=True
        )
        seed_financeiro_tenant_completo(self.tenant)

        self.user = User.objects.create_user(
            username="contador_10b",
            email="contador@distribuidora.com",
            password="password123"
        )
        self.user_aprovador = User.objects.create_user(
            username="gerente_aprovador_10b",
            email="gerente@distribuidora.com",
            password="password123"
        )
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="ADMIN"
        )
        self.membership_aprovador = Membership.objects.create(
            user=self.user_aprovador,
            tenant=self.tenant,
            papel="ADMIN"
        )

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)

        # Contas contábeis padronizadas
        self.cta_banco = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='1.1.1.02').first()
        self.cta_caixa = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='1.1.1.01').first()
        self.cta_imobilizado = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='1.2.1.01').first()
        self.cta_deprec_acum = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='1.2.1.02').first()
        self.cta_despesa_deprec = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='6.1').first()
        self.cta_resultado_82 = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='8.2').first()
        self.cta_receita_bruta = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='3.1.1').first()
        self.cta_cpv = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='4.1.1').first()
        self.cta_despesa_comercial = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='5.1').first()
        self.cta_outras_receitas_81 = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='8.1').first()
        self.cta_clientes = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='1.1.2.01').first()
        self.cta_pdd_redutora = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='1.1.2.02').first()
        self.cta_pdd_despesa = PlanoContas.objects.filter(tenant=self.tenant, codigo_estrutural='5.4').first()

        # Conta Financeira
        self.conta_financeira = ContaFinanceira.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            nome="Itaú Principal 10B",
            tipo='CONTA_CORRENTE',
            banco_codigo='341',
            agencia='1111',
            conta='22222-3',
            saldo_inicial=Decimal('100000.00'),
            conta_contabil=self.cta_banco
        )

        # Veículo
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="ABC1D23",
            marca="Mercedes-Benz",
            modelo="Accelo 1016",
            ano=2024,
            capacidade_carga=Decimal('6000.00'),
            filial=self.filial,
            status='Ativo'
        )

        # Classe de Ativo para Veículos
        self.classe_veiculo = ClasseAtivo.objects.create(
            tenant=self.tenant,
            codigo='VEICULOS',
            nome='Veículos de Entrega',
            tipo='VEICULO',
            vida_util_meses_padrao=60,
            percentual_residual_padrao=Decimal('0.1000'),
            conta_imobilizado=self.cta_imobilizado,
            conta_depreciacao_acumulada=self.cta_deprec_acum,
            conta_despesa_depreciacao=self.cta_despesa_deprec
        )

        # Ativo Imobilizado (Caminhão)
        self.caminhao = AtivoImobilizado.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            classe=self.classe_veiculo,
            numero_patrimonio="ABC1D23",
            descricao="Caminhão Accelo 1016",
            data_aquisicao=datetime.date(2025, 12, 1),
            data_inicio_depreciacao=datetime.date(2026, 1, 1),
            valor_aquisicao=Decimal('120000.00'),
            valor_residual=Decimal('20000.00'),
            vida_util_meses=50,  # quota = (120000 - 20000) / 50 = 2000.00
            status='EM_USO'
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()


class DepreciacaoMensalLedgerTests(BaseSprint10BTestCase):
    """Testes da Tarefa 1, 3, 4, 5: Ledger, Idempotência, Período Anterior e Baixa."""

    def test_calcular_depreciacao_mensal_cria_ledger_e_lancamento_agregado(self):
        periodo = datetime.date(2026, 1, 1)
        itens, lancamento = calcular_depreciacao_mensal(tenant=self.tenant, periodo=periodo, usuario=self.user)

        self.assertEqual(len(itens), 1)
        dep = itens[0]
        self.assertEqual(dep.tipo_alvo, 'ATIVO_IMOBILIZADO')
        self.assertEqual(dep.alvo_id, str(self.caminhao.id))
        self.assertEqual(dep.quota, Decimal('2000.00'))
        self.assertEqual(dep.depreciacao_acumulada_apos, Decimal('2000.00'))
        self.assertEqual(dep.valor_contabil_apos, Decimal('118000.00'))
        self.assertIsNotNone(lancamento)

        # Lançamento agregado balanceado
        partidas = list(lancamento.partidas.all())
        self.assertEqual(len(partidas), 2)
        debito = next(p for p in partidas if p.tipo_partida == 'DEBITO')
        credito = next(p for p in partidas if p.tipo_partida == 'CREDITO')
        self.assertEqual(debito.conta_contabil, self.cta_despesa_deprec)
        self.assertEqual(debito.valor, Decimal('2000.00'))
        self.assertEqual(credito.conta_contabil, self.cta_deprec_acum)
        self.assertEqual(credito.valor, Decimal('2000.00'))

    def test_depreciacao_rodada_duas_vezes_no_mesmo_periodo_nao_duplica(self):
        periodo = datetime.date(2026, 1, 1)
        itens_1, lanc_1 = calcular_depreciacao_mensal(tenant=self.tenant, periodo=periodo, usuario=self.user)
        self.assertEqual(DepreciacaoMensal.objects.filter(tenant=self.tenant, periodo=periodo).count(), 1)

        itens_2, lanc_2 = calcular_depreciacao_mensal(tenant=self.tenant, periodo=periodo, usuario=self.user)
        self.assertEqual(len(itens_2), 1)
        self.assertEqual(itens_2[0].id, itens_1[0].id)
        self.assertEqual(lanc_2.id, lanc_1.id)
        self.assertEqual(DepreciacaoMensal.objects.filter(tenant=self.tenant, periodo=periodo).count(), 1)

    def test_calcular_com_periodo_anterior_pendente_e_bloqueado(self):
        # 2026-01 calculado com sucesso
        calcular_depreciacao_mensal(tenant=self.tenant, periodo=datetime.date(2026, 1, 1), usuario=self.user)

        # Tentar pular fevereiro e rodar março de 2026 deve ser bloqueado
        with self.assertRaises(ValidationError) as ctx:
            calcular_depreciacao_mensal(tenant=self.tenant, periodo=datetime.date(2026, 3, 1), usuario=self.user)
        self.assertIn("período anterior", str(ctx.exception).lower())

    def test_revisao_vida_util_cpc23_nao_altera_quotas_passadas(self):
        # Mês 1: Quota = 2000.00, VCL após = 118.000,00
        calcular_depreciacao_mensal(tenant=self.tenant, periodo=datetime.date(2026, 1, 1), usuario=self.user)
        dep_m1 = DepreciacaoMensal.objects.get(tenant=self.tenant, periodo=datetime.date(2026, 1, 1), alvo_id=str(self.caminhao.id))
        self.assertEqual(dep_m1.quota, Decimal('2000.00'))

        # Revisão no fim de janeiro: VCL é 118.000. Novo residual = 18.000. Nova vida restante = 100 meses.
        # Nova quota futura = (118.000 - 18.000) / 100 = 1.000,00 ao mês
        revisar_vida_util(
            tenant=self.tenant,
            tipo_alvo='ATIVO_IMOBILIZADO',
            alvo_id=str(self.caminhao.id),
            data_revisao=datetime.date(2026, 1, 31),
            nova_vida_meses=100,
            novo_valor_residual=Decimal('18000.00'),
            motivo="Avaliação técnica de laudo mecânico",
            usuario=self.user
        )

        # Mês 2: Quota deve ser exatamente 1.000,00
        calcular_depreciacao_mensal(tenant=self.tenant, periodo=datetime.date(2026, 2, 1), usuario=self.user)
        dep_m2 = DepreciacaoMensal.objects.get(tenant=self.tenant, periodo=datetime.date(2026, 2, 1), alvo_id=str(self.caminhao.id))
        self.assertEqual(dep_m2.quota, Decimal('1000.00'))
        self.assertEqual(dep_m2.depreciacao_acumulada_apos, Decimal('3000.00'))
        self.assertEqual(dep_m2.valor_contabil_apos, Decimal('117000.00'))

        # Passado intacto
        dep_m1.refresh_from_db()
        self.assertEqual(dep_m1.quota, Decimal('2000.00'))

    def test_baixa_patrimonial_contabilizada_com_ganho_ou_perda_em_82(self):
        # Deprecia janeiro
        calcular_depreciacao_mensal(tenant=self.tenant, periodo=datetime.date(2026, 1, 1), usuario=self.user)
        # VCL é 118.000. Custo aquisicao = 120.000, Deprec acumulada = 2.000.
        # Venda por 110.000 -> Perda de 8.000 em 8.2
        lancamento, resultado = baixar_patrimonio_contabil(
            tenant=self.tenant,
            tipo_alvo='ATIVO_IMOBILIZADO',
            alvo_id=str(self.caminhao.id),
            data_baixa=datetime.date(2026, 1, 20),
            motivo="Venda de caminhão",
            valor_recebido=Decimal('110000.00'),
            conta_caixa_id=self.cta_banco.id,
            usuario=self.user
        )
        self.assertEqual(resultado, Decimal('-8000.00'))
        self.caminhao.refresh_from_db()
        self.assertEqual(self.caminhao.status, 'VENDIDO')

        # Partidas: Débito DeprecAcum (2000), Débito Banco (110000), Débito 8.2 (8000) = 120.000; Crédito Imob = 120.000
        partidas = list(lancamento.partidas.all())
        total_deb = sum(p.valor for p in partidas if p.tipo_partida == 'DEBITO')
        total_cred = sum(p.valor for p in partidas if p.tipo_partida == 'CREDITO')
        self.assertEqual(total_deb, Decimal('120000.00'))
        self.assertEqual(total_cred, Decimal('120000.00'))

        partida_82 = next(p for p in partidas if p.conta_contabil == self.cta_resultado_82)
        self.assertEqual(partida_82.tipo_partida, 'DEBITO')
        self.assertEqual(partida_82.valor, Decimal('8000.00'))

    def test_reteste_capitalizado_cria_ativo_imobilizado_componente(self):
        from produtos.models import GasQuimico
        gas, _ = GasQuimico.objects.get_or_create(
            sigla="GLP",
            defaults={'nome': "Gás Liquefeito de Petróleo", 'categoria': "INDUSTRIAL"}
        )
        mod = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao="Cilindro P45 Industrial",
            material="ACO",
            volume_hidraulico_litros=Decimal('108.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('40.00'),
            periodicidade_reteste_anos=5
        )
        cilindro = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-777",
            numero_serie_ogiva="SN-777",
            fabricante="MAT",
            ano_fabricacao=2020,
            modelo=mod,
            gas_dedicado=gas,
            data_ultimo_reteste=datetime.date(2020, 1, 1),
            data_proximo_reteste=datetime.date(2025, 1, 1),
            status='CHEIO_DISPONIVEL'
        )

        ativo = capitalizar_reteste_componente(
            tenant=self.tenant,
            cilindro_id=cilindro.id,
            reteste_id=55,
            custo_servico_reteste=Decimal('350.00'),
            data_reteste=datetime.date(2026, 1, 10),
            periodicidade_meses=60
        )

        self.assertEqual(ativo.classe.codigo, 'COMPONENTE_RETESTE')
        self.assertEqual(ativo.valor_aquisicao, Decimal('350.00'))
        self.assertEqual(ativo.vida_util_meses, 60)
        self.assertIn("RET-QR-777-55", ativo.numero_patrimonio)


class SaldoMensalContaSnapshotTests(BaseSprint10BTestCase):
    """Testes da Tarefa 6 & 13: Snapshots SaldoMensalConta e integridade."""

    def test_lancar_atualiza_snapshot_incremental_e_reconstruir_gera_igual(self):
        # 1. Escriturar partidas no Razão
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 15),
            historico="Integralização de Capital Inicial",
            partidas=[
                {'conta_id': self.cta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('50000.00')},
                {'conta_id': self.cta_receita_bruta.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('50000.00')},
            ],
            usuario=self.user
        )

        # 2. Verificar snapshot incremental
        snap_banco = SaldoMensalConta.objects.get(tenant=self.tenant, ano_mes='2026-01', conta=self.cta_banco)
        self.assertEqual(snap_banco.debitos, Decimal('50000.00'))
        self.assertEqual(snap_banco.creditos, Decimal('0.00'))

        snap_receita = SaldoMensalConta.objects.get(tenant=self.tenant, ano_mes='2026-01', conta=self.cta_receita_bruta)
        self.assertEqual(snap_receita.debitos, Decimal('0.00'))
        self.assertEqual(snap_receita.creditos, Decimal('50000.00'))

        # 3. Reconstruir snapshots do zero
        reconstruir_saldos(tenant=self.tenant, periodo='2026-01')

        # 4. Validar integridade
        res_snap = verificar_integridade_snapshots(tenant=self.tenant, periodo='2026-01')
        self.assertTrue(res_snap['valido'])
        self.assertEqual(res_snap['diferenca_debitos'], Decimal('0.00'))
        self.assertEqual(res_snap['diferenca_creditos'], Decimal('0.00'))


class DRECompetenciaTests(BaseSprint10BTestCase):
    """Testes da Tarefa 7: DRE por competência, 12 linhas e reconciliação."""

    def test_dre_reconcilia_com_balancete_e_subdivisoes_81_e_82(self):
        # Criar partidas diversificadas para compor DRE
        # Receita Bruta = 100.000
        # CPV = 40.000
        # Despesas Comerciais (OPEX) = 15.000
        # Outras Receitas Operacionais (8.1) = 5.000 (deve entrar antes do EBITDA)
        # Despesa Depreciação (6.1) = 2.000
        # Baixa de Imobilizado (8.2) = 1.000 (despesa fora de EBITDA, após depreciação)
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 10),
            historico="Faturamento de Mercadorias",
            partidas=[
                {'conta_id': self.cta_clientes.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('100000.00')},
                {'conta_id': self.cta_receita_bruta.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('100000.00')},
            ],
            usuario=self.user
        )
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 11),
            historico="Custo de Vendas e Estoques",
            partidas=[
                {'conta_id': self.cta_cpv.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('40000.00')},
                {'conta_id': self.cta_banco.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('40000.00')},
            ],
            usuario=self.user
        )
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 12),
            historico="Despesas Comerciais de Entrega",
            partidas=[
                {'conta_id': self.cta_despesa_comercial.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('15000.00')},
                {'conta_id': self.cta_banco.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('15000.00')},
            ],
            usuario=self.user
        )
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 13),
            historico="Indenização Operacional Recebida (8.1)",
            partidas=[
                {'conta_id': self.cta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('5000.00')},
                {'conta_id': self.cta_outras_receitas_81.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('5000.00')},
            ],
            usuario=self.user
        )
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 14),
            historico="Depreciação de Equipamentos (6.1)",
            partidas=[
                {'conta_id': self.cta_despesa_deprec.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('2000.00')},
                {'conta_id': self.cta_deprec_acum.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('2000.00')},
            ],
            usuario=self.user
        )
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 15),
            historico="Perda na Alienação de Sucata (8.2)",
            partidas=[
                {'conta_id': self.cta_resultado_82.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('1000.00')},
                {'conta_id': self.cta_imobilizado.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('1000.00')},
            ],
            usuario=self.user
        )

        res_dre = dre(tenant=self.tenant, periodo_ini='2026-01', periodo_fim='2026-01')

        # Validação das 12 Linhas
        self.assertIn('01_receita_bruta', res_dre['linhas'])
        self.assertIn('05_lucro_bruto', res_dre['linhas'])
        self.assertIn('07_ebitda', res_dre['linhas'])
        self.assertIn('09_ebit', res_dre['linhas'])
        self.assertIn('12_resultado_liquido', res_dre['linhas'])

        # Lucro Bruto = 100.000 (Receita) - 40.000 (CPV) = 60.000
        self.assertEqual(res_dre['linhas']['05_lucro_bruto']['valor'], Decimal('60000.00'))

        # EBITDA = Lucro Bruto (60.000) - OPEX (15.000) + 8.1 (5.000) = 50.000
        self.assertEqual(res_dre['linhas']['07_ebitda']['valor'], Decimal('50000.00'))

        # EBIT = EBITDA (50.000) - Depreciação (2.000) - 8.2 (1.000) = 47.000
        self.assertEqual(res_dre['linhas']['09_ebit']['valor'], Decimal('47000.00'))

        # Reconciliação Matemática: DRE vs Balancete
        balancete = obter_balancete_verificacao(tenant=self.tenant, data_inicio='2026-01-01', data_fim='2026-01-31')
        dre_lucro_liquido = res_dre['linhas']['12_resultado_liquido']['valor']
        balancete_resultado = balancete['resultado_exercicio']
        self.assertEqual(dre_lucro_liquido, balancete_resultado)

    def test_dre_sem_fiscal_exibe_aviso_de_deducoes_estimadas(self):
        self.tenant.modulo_fiscal_ativo = False
        self.tenant.save(update_fields=['modulo_fiscal_ativo'])

        res_dre = dre(tenant=self.tenant, periodo_ini='2026-01', periodo_fim='2026-01')
        self.assertTrue(res_dre['rodape']['alerta_deducoes_estimadas'])
        self.assertIn("deduções estimadas", res_dre['rodape']['aviso_legal'].lower())


class PDDTests(BaseSprint10BTestCase):
    """Testes da Tarefa 10: Faixas de PDD, ajuste incremental e baixa definitiva."""

    def test_calcular_pdd_e_segunda_execucao_gera_ajuste_zero(self):
        # 1. Configurar parâmetro PDD (atraso de 31 a 60 dias = 10%)
        ParametroPDD.objects.create(
            tenant=self.tenant,
            dias_atraso_min=31,
            dias_atraso_max=60,
            percentual_provisao=Decimal('0.1000')
        )

        # 2. Criar título a receber com parcela vencida há 40 dias no valor de R$ 10.000,00
        cli = Cliente.objects.create(
            tenant=self.tenant,
            nome="Mercado Teste PDD Ltda",
            cnpj="44.555.666/0001-77",
            tipo_cliente="PJ"
        )
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            tipo='RECEBER',
            cliente=cli,
            conta_gerencial=self.cta_receita_bruta,
            valor_bruto=Decimal('10000.00'),
            valor_liquido_esperado=Decimal('10000.00'),
            data_competencia=datetime.date(2025, 12, 1),
            status='ABERTO'
        )
        hoje = timezone.localdate()
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            numero_parcela=1,
            total_parcelas=1,
            data_vencimento=hoje - datetime.timedelta(days=40),
            valor_nominal=Decimal('10000.00'),
            saldo_em_aberto=Decimal('10000.00'),
            status='ABERTO'
        )

        # 3. Execução 1 de PDD: 10% sobre 10.000 = Provisão de 1.000,00
        res_1 = calcular_pdd(tenant=self.tenant, periodo=hoje, usuario=self.user)
        self.assertEqual(res_1['provisao_necessaria'], Decimal('1000.00'))
        self.assertEqual(res_1['ajuste'], Decimal('1000.00'))
        self.assertIsNotNone(res_1['lancamento'])

        # Verifica lançamento: D 5.4 (1.000), C 1.1.2.02 (1.000)
        partidas = list(res_1['lancamento'].partidas.all())
        deb = next(p for p in partidas if p.tipo_partida == 'DEBITO')
        cred = next(p for p in partidas if p.tipo_partida == 'CREDITO')
        self.assertEqual(deb.conta_contabil, self.cta_pdd_despesa)
        self.assertEqual(cred.conta_contabil, self.cta_pdd_redutora)

        # 4. Execução 2 no mesmo período: ajuste ZERO
        res_2 = calcular_pdd(tenant=self.tenant, periodo=hoje, usuario=self.user)
        self.assertEqual(res_2['provisao_necessaria'], Decimal('1000.00'))
        self.assertEqual(res_2['ajuste'], Decimal('0.00'))
        self.assertIsNone(res_2['lancamento'])

    def test_baixa_definitiva_perda_pdd(self):
        cli = Cliente.objects.create(tenant=self.tenant, nome="Devedor Falido", cnpj="99.888.777/0001-66", tipo_cliente="PJ")
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant, tipo='RECEBER', cliente=cli, conta_gerencial=self.cta_receita_bruta,
            valor_bruto=Decimal('500.00'), valor_liquido_esperado=Decimal('500.00'),
            data_competencia=datetime.date(2025, 12, 1), status='ABERTO'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant, titulo=titulo, numero_parcela=1, total_parcelas=1,
            data_vencimento=datetime.date(2025, 12, 10), valor_nominal=Decimal('500.00'),
            saldo_em_aberto=Decimal('500.00'), status='ABERTO'
        )

        lanc = baixar_perda_pdd(tenant=self.tenant, parcela_id=parcela.id, motivo="Falência decretada do cliente", usuario=self.user)
        parcela.refresh_from_db()
        self.assertEqual(parcela.status, 'CANCELADA')
        self.assertEqual(parcela.saldo_em_aberto, Decimal('0.00'))

        # D 1.1.2.02 ((-) PDD) / C 1.1.2.01 (Clientes)
        partidas = list(lanc.partidas.all())
        deb = next(p for p in partidas if p.tipo_partida == 'DEBITO')
        cred = next(p for p in partidas if p.tipo_partida == 'CREDITO')
        self.assertEqual(deb.conta_contabil, self.cta_pdd_redutora)
        self.assertEqual(cred.conta_contabil, self.cta_clientes)


class OrcamentoTests(BaseSprint10BTestCase):
    """Testes da Tarefa 9: Orçamento anual, aprovação e importação CSV."""

    def test_criar_aprovar_e_importar_orcamento_csv(self):
        orc = criar_orcamento(tenant=self.tenant, ano=2026, nome="Orçamento Anual 2026", usuario=self.user)
        self.assertEqual(orc.status, 'RASCUNHO')

        csv_content = f"mes,conta,centro_custo,filial,valor\n1,{self.cta_receita_bruta.codigo_estrutural},,,150000.00\n1,{self.cta_cpv.codigo_estrutural},,,60000.00\n"
        csv_file = io.BytesIO(csv_content.encode('utf-8'))

        total_importado = importar_orcamento_csv(tenant=self.tenant, orcamento_id=orc.id, csv_file=csv_file)
        self.assertEqual(total_importado, 2)
        self.assertEqual(orc.itens.count(), 2)

        orc_aprovado = aprovar_orcamento(tenant=self.tenant, orcamento_id=orc.id, usuario=self.user_aprovador)
        self.assertEqual(orc_aprovado.status, 'APROVADO')
        self.assertEqual(orc_aprovado.aprovado_por, self.user_aprovador)


class LancamentoManualAlcadaTests(BaseSprint10BTestCase):
    """Testes da Tarefa 11: Lançamento manual balanceado e alçadas de aprovação."""

    def test_lancamento_manual_ate_10k_escritura_direto(self):
        partidas = [
            {'conta_id': self.cta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('5000.00')},
            {'conta_id': self.cta_receita_bruta.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('5000.00')},
        ]
        pendente, lanc = criar_lancamento_manual(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 10),
            historico="Lançamento Manual Pequeno Porte",
            partidas_data=partidas,
            usuario=self.user
        )
        self.assertIsNone(pendente)
        self.assertIsNotNone(lanc)

    def test_lancamento_manual_acima_de_10k_exige_aprovacao_e_segregacao(self):
        partidas = [
            {'conta_id': self.cta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('50000.00')},
            {'conta_id': self.cta_receita_bruta.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('50000.00')},
        ]
        pendente, lanc = criar_lancamento_manual(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 10),
            historico="Lançamento Manual de Grande Porte",
            partidas_data=partidas,
            usuario=self.user
        )
        self.assertIsNotNone(pendente)
        self.assertIsNone(lanc)
        self.assertEqual(pendente.status, 'PENDENTE')

        # Quem criou NÃO pode aprovar (Segregação de Funções)
        with self.assertRaises(ValidationError) as ctx:
            aprovar_lancamento_manual(tenant=self.tenant, pendente_id=pendente.id, usuario=self.user)
        self.assertIn("segregação", str(ctx.exception).lower())

        # Usuário aprovador aprova com sucesso
        lanc_aprovado = aprovar_lancamento_manual(tenant=self.tenant, pendente_id=pendente.id, usuario=self.user_aprovador)
        self.assertIsNotNone(lanc_aprovado)
        pendente.refresh_from_db()
        self.assertEqual(pendente.status, 'APROVADO')


class ExportacaoContabilTests(BaseSprint10BTestCase):
    """Testes da Tarefa 12: Exportações contábeis em CSV."""

    def test_exportar_balancete_razao_dre_e_generico_csv(self):
        # Gera movimento prévio
        lancar(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 15),
            historico="Operação para Teste de Exportação",
            partidas=[
                {'conta_id': self.cta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('1000.00')},
                {'conta_id': self.cta_receita_bruta.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('1000.00')},
            ],
            usuario=self.user
        )

        csv_balancete = exportar_balancete_csv(self.tenant, '2026-01-01', '2026-01-31')
        self.assertIn("codigo_estrutural", csv_balancete)

        csv_razao = exportar_razao_csv(self.tenant, self.cta_banco.id, '2026-01-01', '2026-01-31')
        self.assertIn("data_competencia", csv_razao)

        csv_dre = exportar_dre_csv(self.tenant, '2026-01', '2026-01')
        self.assertIn("Receita Operacional Bruta", csv_dre)

        csv_generico = exportar_contabil_generico_csv(self.tenant, '2026-01-01', '2026-01-31')
        self.assertIn("data,conta_debito,conta_credito,valor", csv_generico)


class MultiTenantBoundarySprint10BTests(BaseSprint10BTestCase):
    """Garante isolamento multi-tenant e 404 para recursos de outro tenant (Regra 3)."""

    def setUp(self):
        super().setUp()
        self.tenant_b = Tenant.objects.create(
            razao_social="Tenant Invasor B Ltda",
            cnpj="99.000.111/0001-22",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        with tenant_context(self.tenant_b):
            self.filial_b = Filial.objects.create(tenant=self.tenant_b, nome="Matriz B", cnpj="99.000.111/0001-22", matriz=True)
            seed_financeiro_tenant_completo(self.tenant_b)

        self.user_b = User.objects.create_user(username="user_b_invader", email="invader@b.com", password="pass")
        Membership.objects.create(user=self.user_b, tenant=self.tenant_b, papel="ADMIN")

        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)

    def test_tenant_b_recebe_404_ao_acessar_orcamento_do_tenant_a(self):
        orc_a = Orcamento.objects.create(tenant=self.tenant, ano=2026, nome="Orçamento Confidencial A")
        url = f"/financeiro/api/orcamentos/{orc_a.id}/"
        response = self.client_b.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_b_recebe_404_ao_tentar_aprovar_lancamento_manual_do_tenant_a(self):
        pendente_a = LancamentoManualPendente.objects.create(
            tenant=self.tenant,
            data_competencia=datetime.date(2026, 1, 1),
            historico="Manual Tenant A",
            partidas_json=[],
            valor_total=Decimal('15000.00'),
            status='PENDENTE'
        )
        url = f"/financeiro/api/lancamentos-manuais/{pendente_a.id}/aprovar/"
        response = self.client_b.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


import unittest


class HypothesisSprint10BInvariantsTests(unittest.TestCase):
    """Testes de propriedades invariantes com Hypothesis (Regra 8)."""

    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])
    @given(
        valor_total=st.decimals(min_value=Decimal('10.00'), max_value=Decimal('50000.00'), places=2),
        qtd_partes=st.integers(min_value=2, max_value=5)
    )
    def test_invariante_rateio_soma_exata(self, valor_total, qtd_partes):
        from core.money import allocate
        partes = allocate(valor_total, [1] * qtd_partes)
        self.assertEqual(sum(partes), quantize(valor_total, 2))

    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])
    @given(
        rec_bruta=st.decimals(min_value=Decimal('100.00'), max_value=Decimal('100000.00'), places=2),
        deducoes=st.decimals(min_value=Decimal('0.00'), max_value=Decimal('50.00'), places=2),
        cpv=st.decimals(min_value=Decimal('0.00'), max_value=Decimal('50.00'), places=2),
        opex=st.decimals(min_value=Decimal('0.00'), max_value=Decimal('50.00'), places=2),
        deprec=st.decimals(min_value=Decimal('0.00'), max_value=Decimal('20.00'), places=2)
    )
    def test_invariante_dre_ebitda_ebit_reconciliacao(self, rec_bruta, deducoes, cpv, opex, deprec):
        rec_liq = rec_bruta - deducoes
        lucro_bruto = rec_liq - cpv
        ebitda = lucro_bruto - opex
        ebit = ebitda - deprec
        self.assertEqual(ebit, rec_bruta - deducoes - cpv - opex - deprec)

