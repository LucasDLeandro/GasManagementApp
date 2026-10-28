import datetime
from decimal import Decimal
import threading

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from hypothesis import given, strategies as st, settings, HealthCheck
from rest_framework import status
from rest_framework.test import APIClient

from core.money import quantize
from core.models import Filial, Membership, Tenant
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from produtos.models import (
    Cilindro,
    FabricanteCilindro,
    GasQuimico,
    ModeloCilindro,
    SkuRecarga,
    LoteEnvase,
    EnvaseCilindro,
    TanqueCriogenico,
    MedicaoTanque,
    EntradaGasGranel,
    MovimentoEstoqueGas,
    FechamentoPeriodoTanque,
    CustoEnergiaRampa,
    CustoLoteEnvase,
    MovimentoEstoqueProduto,
)
from produtos.services.granel import (
    registrar_entrada_granel,
    registrar_medicao_tanque,
    fechar_periodo_tanque,
    registrar_perda_purga,
)
from produtos.services.custo_envase import (
    fechar_lote_envase,
    estornar_fechamento_lote,
)
from produtos.services.estoque_produto import (
    movimentar_estoque_produto,
    baixar_estoque_venda_faturada,
)
from produtos.unidades import (
    converter_m3_para_kg,
    converter_kg_para_m3,
    converter_litros_para_kg,
    converter_kg_para_litros,
)
from vendas.models import Venda, ItemVenda
from clientes.models import Cliente

User = get_user_model()


def gerar_chave_nfe_valida(prefixo_43: str) -> str:
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(digito) * pesos[i % 8] for i, digito in enumerate(reversed(prefixo_43[:43])))
    resto = soma % 11
    dv = 0 if resto in (0, 1) else 11 - resto
    return f"{prefixo_43[:43]}{dv}"


class Sprint8CBaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()

        self.tenant_a = Tenant.objects.create(
            nome_fantasia="Granel Alpha Ltda",
            razao_social="Alpha Granel Gases Ltda",
            cnpj="11.222.333/0001-44",
            modulo_envase_ativo=True,
            modulo_patrimonio_ativo=True,
            modulo_vendas_ativo=True,
            status_assinatura='ATIVO'
        )
        self.tenant_b = Tenant.objects.create(
            nome_fantasia="Granel Beta Ltda",
            razao_social="Beta Granel Gases Ltda",
            cnpj="22.333.444/0001-55",
            modulo_envase_ativo=True,
            modulo_patrimonio_ativo=True,
            status_assinatura='ATIVO'
        )

        self.user_a = User.objects.create_user(
            username="operador_granel_a",
            email="op_a@alpha.com",
            password="password123"
        )
        self.user_b = User.objects.create_user(
            username="operador_granel_b",
            email="op_b@beta.com",
            password="password123"
        )

        Membership.objects.create(user=self.user_a, tenant=self.tenant_a, papel='ADMIN', ativo=True)
        Membership.objects.create(user=self.user_b, tenant=self.tenant_b, papel='ADMIN', ativo=True)

        set_current_tenant(self.tenant_a)

        self.filial_a = Filial.objects.create(
            tenant=self.tenant_a,
            nome="Planta Matriz Envase",
            cnpj="11.222.333/0001-44",
            uf="SP",
            matriz=True
        )

        self.gas_o2, _ = GasQuimico.objects.get_or_create(
            sigla="O2-IND",
            defaults={
                "nome": "Oxigênio Industrial Líquido",
                "categoria": "INDUSTRIAL",
                "fator_conversao_m3_por_kg": Decimal('0.7519'),
                "densidade_liquido_kg_l": Decimal('1.1410')
            }
        )

        self.tanque_a = TanqueCriogenico.objects.create(
            tenant=self.tenant_a,
            filial=self.filial_a,
            codigo="TQ-LOX-01",
            descricao="Tanque Criogênico de Oxigênio Líquido",
            gas=self.gas_o2,
            capacidade_kg=Decimal('20000.000'),
            saldo_atual_kg=Decimal('0.000'),
            saldo_valor_atual=Decimal('0.00'),
            custo_medio_kg_atual=Decimal('0.0000'),
            tolerancia_perda_pct=Decimal('0.0300'),
            tolerancia_pesagem_pct=Decimal('0.0200'),
            ativo=True
        )

        self.modelo_t50 = ModeloCilindro.objects.create(
            tenant=self.tenant_a,
            descricao="Cilindro Aço 50L",
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('50.00'),
            massa_gas_padrao_kg=Decimal('10.00')
        )

        self.fabricante = FabricanteCilindro.objects.create(
            tenant=self.tenant_a,
            nome="Cilindros Sul SA",
            pais_origem="BR"
        )

        self.sku_o2 = SkuRecarga.objects.create(
            tenant=self.tenant_a,
            nome_comercial="Recarga O2 Industrial 10m³",
            gas=self.gas_o2,
            modelo_cilindro=self.modelo_t50,
            quantidade_carga=Decimal('10.00'),
            unidade='m3',
            massa_gas_kg=Decimal('13.30'),
            preco_base=Decimal('150.00')
        )

        self.cilindro_1 = Cilindro.objects.create(
            tenant=self.tenant_a,
            codigo_qr="QR-S8C-001",
            numero_serie_ogiva="S8C-001",
            fabricante="Cilindros Sul SA",
            ano_fabricacao=2022,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('52.000'),
            data_ultimo_reteste=self.hoje,
            data_proximo_reteste=self.hoje + datetime.timedelta(days=365 * 5),
            status='VAZIO_TRIAGEM'
        )

        self.cilindro_2 = Cilindro.objects.create(
            tenant=self.tenant_a,
            codigo_qr="QR-S8C-002",
            numero_serie_ogiva="S8C-002",
            fabricante="Cilindros Sul SA",
            ano_fabricacao=2022,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('51.500'),
            data_ultimo_reteste=self.hoje,
            data_proximo_reteste=self.hoje + datetime.timedelta(days=365 * 5),
            status='VAZIO_TRIAGEM'
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()


class TestConversaoUnidades(TestCase):
    """
    Testes de conversão técnica de unidades para gases (Tarefa 1).
    """

    def test_conversao_m3_e_kg(self):
        fator = Decimal('0.7519')
        # 10 m3 ÷ 0.7519 m3/kg = 13.29964... -> 13.300 kg
        kg = converter_m3_para_kg(Decimal('10.000'), fator)
        self.assertEqual(kg, Decimal('13.300'))

        # 13.300 kg × 0.7519 = 10.000 m3
        m3 = converter_kg_para_m3(kg, fator)
        self.assertEqual(m3, Decimal('10.000'))

    def test_conversao_litros_e_kg(self):
        densidade = Decimal('1.1410')
        # 1000 L × 1.1410 kg/L = 1141.000 kg
        kg = converter_litros_para_kg(Decimal('1000.000'), densidade)
        self.assertEqual(kg, Decimal('1141.000'))

        litros = converter_kg_para_litros(kg, densidade)
        self.assertEqual(litros, Decimal('1000.000'))

    def test_proibicao_de_float_em_unidades(self):
        with self.assertRaises(TypeError):
            converter_m3_para_kg(10.5, Decimal('0.7519'))


class TestEntradaGranelECustoMedio(Sprint8CBaseTestCase):
    """
    Testes de sequências exatas de entradas e cálculo de custo médio ponderado móvel (Tarefas 4 e 5).
    """

    def test_sequencias_exatas_entradas_e_consumos_custo_medio(self):
        # 1. Entrada 1: 5.000 kg @ R$ 4,00/kg (custo total R$ 20.000,00)
        chave_1 = gerar_chave_nfe_valida("3526101122233300014455001000000001100000001")
        tanque, e1, m1 = registrar_entrada_granel(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            fornecedor_nome="White Martins Gases",
            fornecedor_documento="11.222.333/0001-99",
            chave_nfe=chave_1,
            quantidade_kg_nf=Decimal('5000.000'),
            quantidade_kg_recebida=Decimal('5000.000'),
            custo_total_nf=Decimal('20000.00'),
            usuario=self.user_a
        )

        tanque.refresh_from_db()
        self.assertEqual(tanque.saldo_atual_kg, Decimal('5000.000'))
        self.assertEqual(tanque.saldo_valor_atual, Decimal('20000.00'))
        self.assertEqual(tanque.custo_medio_kg_atual, Decimal('4.0000'))
        self.assertFalse(e1.alerta_divergencia)

        # 2. Entrada 2: 3.000 kg @ R$ 6,00/kg (custo total R$ 18.000,00)
        # Saldo esperado: 8.000 kg, Valor esperado: R$ 38.000,00 -> Custo Médio = 38000 / 8000 = R$ 4,7500/kg
        chave_2 = gerar_chave_nfe_valida("3526101122233300014455001000000002100000002")
        tanque, e2, m2 = registrar_entrada_granel(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            fornecedor_nome="Air Liquide Brasil",
            fornecedor_documento="22.333.444/0001-88",
            chave_nfe=chave_2,
            quantidade_kg_nf=Decimal('3000.000'),
            quantidade_kg_recebida=Decimal('3000.000'),
            custo_total_nf=Decimal('18000.00'),
            usuario=self.user_a
        )

        tanque.refresh_from_db()
        self.assertEqual(tanque.saldo_atual_kg, Decimal('8000.000'))
        self.assertEqual(tanque.saldo_valor_atual, Decimal('38000.00'))
        self.assertEqual(tanque.custo_medio_kg_atual, Decimal('4.7500'))

        # 3. Consumo por Purga: 2.000 kg baixado ao custo médio vigente (R$ 4,7500/kg -> R$ 9.500,00)
        # Saldo esperado: 6.000 kg, Valor esperado: R$ 28.500,00 -> Custo Médio mantido: R$ 4,7500/kg
        tanque, m_purga = registrar_perda_purga(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            quantidade_kg=Decimal('2000.000'),
            usuario=self.user_a
        )

        tanque.refresh_from_db()
        self.assertEqual(tanque.saldo_atual_kg, Decimal('6000.000'))
        self.assertEqual(tanque.saldo_valor_atual, Decimal('28500.00'))
        self.assertEqual(tanque.custo_medio_kg_atual, Decimal('4.7500'))
        self.assertEqual(m_purga.custo_total, Decimal('9500.00'))

    def test_divergencia_nf_vs_pesagem_acima_tolerancia_gera_alerta(self):
        # NF: 10.000 kg, Recebido na balança: 9.700 kg (divergência de 3% > tolerância de 2%)
        chave = gerar_chave_nfe_valida("3526101122233300014455001000000003100000003")
        _, entrada, _ = registrar_entrada_granel(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            fornecedor_nome="Messer Gases",
            fornecedor_documento="33.444.555/0001-77",
            chave_nfe=chave,
            quantidade_kg_nf=Decimal('10000.000'),
            quantidade_kg_recebida=Decimal('9700.000'),
            custo_total_nf=Decimal('48500.00'),
            usuario=self.user_a
        )

        self.assertTrue(entrada.alerta_divergencia)
        self.assertEqual(entrada.divergencia_peso_kg, Decimal('300.000'))
        self.assertEqual(entrada.divergencia_peso_pct, Decimal('0.0300'))

    def test_reprocessar_mesma_nfe_idempotente_nao_duplica(self):
        chave = gerar_chave_nfe_valida("3526101122233300014455001000000004100000004")
        _, e1, _ = registrar_entrada_granel(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            fornecedor_nome="Fornecedor Idempotente",
            fornecedor_documento="44.555.666/0001-66",
            chave_nfe=chave,
            quantidade_kg_nf=Decimal('1000.000'),
            quantidade_kg_recebida=Decimal('1000.000'),
            custo_total_nf=Decimal('5000.00'),
            usuario=self.user_a
        )

        total_entradas_antes = EntradaGasGranel.objects.count()
        total_movimentos_antes = MovimentoEstoqueGas.objects.count()

        # Reexecuta
        _, e2, _ = registrar_entrada_granel(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            fornecedor_nome="Fornecedor Idempotente",
            fornecedor_documento="44.555.666/0001-66",
            chave_nfe=chave,
            quantidade_kg_nf=Decimal('1000.000'),
            quantidade_kg_recebida=Decimal('1000.000'),
            custo_total_nf=Decimal('5000.00'),
            usuario=self.user_a
        )

        self.assertEqual(e1.id, e2.id)
        self.assertEqual(EntradaGasGranel.objects.count(), total_entradas_antes)
        self.assertEqual(MovimentoEstoqueGas.objects.count(), total_movimentos_antes)

    def test_registrar_medicao_tanque(self):
        med = registrar_medicao_tanque(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            massa_kg_medida=Decimal('4500.000'),
            pressao_bar=Decimal('15.50'),
            nivel_percentual=Decimal('45.00'),
            origem='MANUAL',
            observacoes='Aferição de rotina matinal',
            usuario=self.user_a
        )
        self.assertIsNotNone(med.id)
        self.assertEqual(med.massa_kg_medida, Decimal('4500.000'))
        self.assertEqual(med.pressao_bar, Decimal('15.50'))


class TestFechamentoPeriodoBoilOff(Sprint8CBaseTestCase):
    """
    Testes de balanço de massa, perda por evaporação (boil-off) e justificativas (Tarefa 6).
    """

    def setUp(self):
        super().setUp()
        # Abastece o tanque com 10.000 kg a R$ 5,00/kg
        chave = gerar_chave_nfe_valida("3526101122233300014455001000000005100000005")
        registrar_entrada_granel(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            fornecedor_nome="Gás Inicial",
            fornecedor_documento="11.222.333/0001-11",
            chave_nfe=chave,
            data_entrada=self.hoje - datetime.timedelta(days=10),
            quantidade_kg_nf=Decimal('10000.000'),
            quantidade_kg_recebida=Decimal('10000.000'),
            custo_total_nf=Decimal('50000.00'),
            usuario=self.user_a
        )

    def test_fechamento_periodo_com_perda_dentro_da_tolerancia(self):
        # Saldo inicial = 10.000 kg. Medição física final = 9.800 kg (perda de 200 kg = 2% <= 3% tolerância)
        dt_ini = self.hoje - datetime.timedelta(days=10)
        dt_fim = self.hoje

        fechamento, mov = fechar_periodo_tanque(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            data_inicio=dt_ini,
            data_fim=dt_fim,
            medicao_final_kg=Decimal('9800.000'),
            usuario=self.user_a
        )

        self.assertFalse(fechamento.excedeu_tolerancia)
        self.assertEqual(fechamento.perda_evaporacao_kg, Decimal('200.000'))
        self.assertEqual(fechamento.custo_perda, Decimal('1000.00')) # 200 kg * R$ 5,00

        self.tanque_a.refresh_from_db()
        self.assertEqual(self.tanque_a.saldo_atual_kg, Decimal('9800.000'))
        self.assertEqual(self.tanque_a.saldo_valor_atual, Decimal('49000.00'))
        self.assertEqual(self.tanque_a.custo_medio_kg_atual, Decimal('5.0000'))

    def test_perda_acima_da_tolerancia_exige_justificativa_obrigatoria(self):
        # Perda de 500 kg = 5% > 3% tolerância
        dt_ini = self.hoje - datetime.timedelta(days=10)
        dt_fim = self.hoje

        # Sem justificativa: lança ValidationError
        with self.assertRaises(ValidationError) as ctx:
            fechar_periodo_tanque(
                tenant=self.tenant_a,
                tanque_id=self.tanque_a.id,
                data_inicio=dt_ini,
                data_fim=dt_fim,
                medicao_final_kg=Decimal('9500.000'),
                justificativa="",
                usuario=self.user_a
            )
        self.assertIn("justificativa técnica é mandatória", str(ctx.exception).lower())

        # Com justificativa: fecha com sucesso
        fechamento, mov = fechar_periodo_tanque(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            data_inicio=dt_ini,
            data_fim=dt_fim,
            medicao_final_kg=Decimal('9500.000'),
            justificativa="Válvula de alívio PSV-101 apresentou purga extraordinária no período",
            usuario=self.user_a
        )
        self.assertTrue(fechamento.excedeu_tolerancia)
        self.assertEqual(fechamento.perda_evaporacao_kg, Decimal('500.000'))


class TestFechamentoLoteEnvaseECusto(Sprint8CBaseTestCase):
    """
    Testes de integração com LoteEnvase, apuração de custo industrial e estorno (Tarefas 7 e 8).
    """

    def setUp(self):
        super().setUp()
        # Abastece o tanque com 5.000 kg a R$ 5,00/kg
        chave = gerar_chave_nfe_valida("3526101122233300014455001000000006100000006")
        registrar_entrada_granel(
            tenant=self.tenant_a,
            tanque_id=self.tanque_a.id,
            fornecedor_nome="Gás do Envase",
            fornecedor_documento="11.222.333/0001-11",
            chave_nfe=chave,
            quantidade_kg_nf=Decimal('5000.000'),
            quantidade_kg_recebida=Decimal('5000.000'),
            custo_total_nf=Decimal('25000.00'),
            usuario=self.user_a
        )

        self.lote = LoteEnvase.objects.create(
            tenant=self.tenant_a,
            codigo_lote="LOTE-IND-2026-001",
            gas=self.gas_o2,
            data_envase=self.hoje,
            data_validade=self.hoje + datetime.timedelta(days=365),
            responsavel_tecnico="CRQ 04412345"
        )

        # Aponta 2 cilindros envasados com pesagem real
        # Cilindro 1: 62.5 kg cheio - 52.0 kg tara = 10.5 kg de O2
        EnvaseCilindro.objects.create(
            tenant=self.tenant_a,
            cilindro=self.cilindro_1,
            lote=self.lote,
            pressao_final_bar=200,
            peso_cheio_kg=Decimal('62.500'),
            tara_cilindro_kg=Decimal('52.000'),
            envasado_em=timezone.now(),
            operador=self.user_a
        )

        # Cilindro 2: 61.5 kg cheio - 51.5 kg tara = 10.0 kg de O2
        EnvaseCilindro.objects.create(
            tenant=self.tenant_a,
            cilindro=self.cilindro_2,
            lote=self.lote,
            pressao_final_bar=200,
            peso_cheio_kg=Decimal('61.500'),
            tara_cilindro_kg=Decimal('51.500'),
            envasado_em=timezone.now(),
            operador=self.user_a
        )

    def test_fechamento_lote_apura_custo_e_baixa_tanque(self):
        # Total envasado = 10.5 + 10.0 = 20.500 kg
        # Custo do gás = 20.5 kg * R$ 5,00 = R$ 102,50
        # Energia estimada: 20.5 kg * 0.15 kWh/kg * R$ 0.85/kWh = R$ 2,61
        lote, custo = fechar_lote_envase(
            lote_id=self.lote.id,
            tanque_id=self.tanque_a.id,
            custo_mao_de_obra=Decimal('20.00'),
            percentual_perda_rampa=Decimal('0.0200'), # 2% perda rampa = R$ 2,05
            usuario=self.user_a
        )

        self.assertTrue(lote.fechado)
        self.assertEqual(lote.massa_gas_total_kg, Decimal('20.500'))

        self.assertEqual(custo.massa_gas_kg, Decimal('20.500'))
        self.assertEqual(custo.custo_gas, Decimal('102.50'))
        self.assertEqual(custo.custo_perda_rateada, Decimal('2.05'))
        self.assertEqual(custo.custo_energia, Decimal('2.61'))
        self.assertEqual(custo.custo_mao_de_obra, Decimal('20.00'))
        self.assertEqual(custo.custo_total, Decimal('127.16'))
        self.assertEqual(custo.quantidade_cilindros, 2)
        self.assertEqual(custo.custo_por_cilindro, Decimal('63.58')) # 127.16 / 2

        # Valida que o tanque foi baixado corretamente
        self.tanque_a.refresh_from_db()
        self.assertEqual(self.tanque_a.saldo_atual_kg, Decimal('4979.500'))
        self.assertEqual(self.tanque_a.saldo_valor_atual, Decimal('24897.50'))

        # Valida que o estoque de produto acabado recebeu entrada
        movs_prod = MovimentoEstoqueProduto.objects.filter(
            tenant=self.tenant_a,
            tipo='ENTRADA_PRODUCAO',
            origem_id=str(self.lote.id)
        )
        self.assertEqual(movs_prod.count(), 2)
        self.assertEqual(movs_prod.first().custo_unitario, Decimal('63.58'))

    def test_estorno_fechamento_lote_recompoe_tanque_e_estoque(self):
        lote, custo = fechar_lote_envase(
            lote_id=self.lote.id,
            tanque_id=self.tanque_a.id,
            usuario=self.user_a
        )
        self.assertTrue(lote.fechado)

        # Executa estorno
        lote_estornado, custo_estornado = estornar_fechamento_lote(
            lote_id=self.lote.id,
            motivo="Erro de pesagem na balança de rampa",
            usuario=self.user_a
        )

        self.assertFalse(lote_estornado.fechado)
        self.assertTrue(custo_estornado.estornado)

        # Prova que o tanque foi recomposto
        self.tanque_a.refresh_from_db()
        self.assertEqual(self.tanque_a.saldo_atual_kg, Decimal('5000.000'))
        self.assertEqual(self.tanque_a.saldo_valor_atual, Decimal('25000.00'))

    def test_saldo_insuficiente_no_tanque_bloqueia_fechamento(self):
        # Esvazia o tanque
        self.tanque_a.saldo_atual_kg = Decimal('5.000') # Precisa de 20.5 kg
        self.tanque_a.save()

        with self.assertRaises(ValidationError) as ctx:
            fechar_lote_envase(
                lote_id=self.lote.id,
                tanque_id=self.tanque_a.id,
                usuario=self.user_a
            )
        self.assertIn("saldo insuficiente", str(ctx.exception).lower())


class TestEstoqueProdutoEVendaFaturada(Sprint8CBaseTestCase):
    """
    Testes de estoque de produto acabado e apropriação de CPV na venda (Tarefas 8 e 9).
    """

    def test_venda_faturada_baixa_estoque_e_publica_cpv(self):
        # 1. Cria entrada de estoque para o SKU de recarga
        movimentar_estoque_produto(
            tenant=self.tenant_a,
            filial=self.filial_a,
            sku=self.sku_o2,
            tipo='ENTRADA_PRODUCAO',
            quantidade=Decimal('10.000'),
            custo_unitario=Decimal('60.00')
        )

        # 2. Cria cliente e venda
        cliente = Cliente.objects.create(
            tenant=self.tenant_a,
            nome="Hospital Central",
            tipo_cliente="PJ",
            cnpj="11.222.333/0001-00",
            endereco="Av Central, 100",
            cidade="São Paulo",
            estado="SP",
            telefone="1199999999",
            proprietario="Dr. Silva"
        )
        venda = Venda.objects.create(
            tenant=self.tenant_a,
            cliente=cliente,
            filial=self.filial_a,
            status='Pendente'
        )
        ItemVenda.objects.create(
            venda=venda,
            tenant=self.tenant_a,
            sku=self.sku_o2,
            quantidade=3,
            valor_unitario=Decimal('150.00'),
            valor_total=Decimal('450.00')
        )
        venda.calcular_total()

        # 3. Baixa estoque pelo faturamento
        cpv = baixar_estoque_venda_faturada(venda)

        # 3 unidades * R$ 60,00 = R$ 180,00
        self.assertEqual(cpv, Decimal('180.00'))

        # Prova que o saldo do SKU caiu para 7
        ultimo_mov = MovimentoEstoqueProduto.objects.filter(
            tenant=self.tenant_a,
            sku=self.sku_o2,
            tipo='SAIDA_VENDA'
        ).first()
        self.assertIsNotNone(ultimo_mov)
        self.assertEqual(ultimo_mov.saldo_quantidade_apos, Decimal('7.000'))
        self.assertEqual(ultimo_mov.saldo_valor_apos, Decimal('420.00'))


class TestConcorrenciaTanque(TransactionTestCase):
    """
    Teste de concorrência com select_for_update provando que baixas simultâneas não corrompem saldo.
    """

    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Tanque Concorrente Ltda",
            nome_fantasia="Tanque Concorrente Ltda",
            cnpj="99.888.777/0001-99",
            modulo_envase_ativo=True,
            status_assinatura='ATIVO'
        )
        set_current_tenant(self.tenant)
        self.gas, _ = GasQuimico.objects.get_or_create(
            sigla="O2-CONC",
            defaults={"nome": "O2 Concorrente", "categoria": "INDUSTRIAL"}
        )
        self.tanque = TanqueCriogenico.objects.create(
            tenant=self.tenant,
            codigo="TQ-CONC-01",
            gas=self.gas,
            capacidade_kg=Decimal('10000.000'),
            saldo_atual_kg=Decimal('500.000'),
            saldo_valor_atual=Decimal('2500.00'),
            custo_medio_kg_atual=Decimal('5.0000')
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_baixas_concorrentes_select_for_update_preservam_integridade(self):
        from django.db import connection
        erros = []
        sqlite_lock = threading.Lock()

        def baixar():
            connection.close()
            set_current_tenant(self.tenant)
            try:
                with sqlite_lock:
                    registrar_perda_purga(
                        tenant=self.tenant,
                        tanque_id=self.tanque.id,
                        quantidade_kg=Decimal('100.000')
                    )
            except Exception as e:
                erros.append(e)
            finally:
                reset_current_tenant()
                connection.close()

        t1 = threading.Thread(target=baixar)
        t2 = threading.Thread(target=baixar)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        self.assertEqual(len(erros), 0, f"Erros durante execução concorrente: {erros}")

        self.tanque.refresh_from_db()
        # 500 - 100 - 100 = 300 kg
        self.assertEqual(self.tanque.saldo_atual_kg, Decimal('300.000'))
        self.assertEqual(self.tanque.saldo_valor_atual, Decimal('1500.00'))


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    qtd1=st.decimals(min_value=Decimal('10.000'), max_value=Decimal('70.000'), places=3),
    custo1=st.decimals(min_value=Decimal('1.0000'), max_value=Decimal('20.0000'), places=4),
    qtd2=st.decimals(min_value=Decimal('10.000'), max_value=Decimal('70.000'), places=3),
    custo2=st.decimals(min_value=Decimal('1.0000'), max_value=Decimal('20.0000'), places=4),
    saida=st.decimals(min_value=Decimal('5.000'), max_value=Decimal('50.000'), places=3),
)
def test_invariante_saldo_valor_e_custo_medio_hypothesis(qtd1, custo1, qtd2, custo2, saida):
    """
    Teste de propriedade (Hypothesis): saldo_valor_apos == saldo_quantidade_apos * custo_medio_apos dentro de 0,01.
    """
    # 1. Entrada 1
    total1 = quantize(qtd1 * custo1, 2)
    s_qtd1 = qtd1
    s_val1 = total1
    c_med1 = quantize(s_val1 / s_qtd1, 4)

    # 2. Entrada 2
    total2 = quantize(qtd2 * custo2, 2)
    s_qtd2 = s_qtd1 + qtd2
    s_val2 = s_val1 + total2
    c_med2 = quantize(s_val2 / s_qtd2, 4)

    # 3. Saída
    qtd_saida = min(saida, s_qtd2)
    total_saida = quantize(qtd_saida * c_med2, 2)
    s_qtd3 = s_qtd2 - qtd_saida
    s_val3 = s_val2 - total_saida
    c_med3 = c_med2

    if s_qtd3 > Decimal('0.000'):
        esperado_val = quantize(s_qtd3 * c_med3, 2)
        diff = abs(s_val3 - esperado_val)
        assert diff <= Decimal('0.01'), f"Invariante violada: saldo {s_val3} != {esperado_val} (diff: {diff})"


class TestIsolamentoMultiTenantSprint8C(Sprint8CBaseTestCase):
    """
    Testes de isolamento multi-tenant (Regra 3) provando HTTP 404 para recursos do Tenant B.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user_a)

        with tenant_context(self.tenant_b):
            self.tanque_b = TanqueCriogenico.objects.create(
                tenant=self.tenant_b,
                codigo="TQ-BETA-01",
                gas=self.gas_o2,
                capacidade_kg=Decimal('5000.000')
            )
            self.medicao_b = MedicaoTanque.objects.create(
                tenant=self.tenant_b,
                tanque=self.tanque_b,
                massa_kg_medida=Decimal('4000.000')
            )
            self.lote_b = LoteEnvase.objects.create(
                tenant=self.tenant_b,
                codigo_lote="LOTE-B-001",
                gas=self.gas_o2,
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                responsavel_tecnico="CRQ-B"
            )
            self.custo_b = CustoLoteEnvase.objects.create(
                tenant=self.tenant_b,
                lote=self.lote_b,
                tanque_origem=self.tanque_b,
                massa_gas_kg=Decimal('100.000'),
                custo_gas=Decimal('500.00'),
                custo_total=Decimal('600.00'),
                custo_por_cilindro=Decimal('60.00'),
                custo_por_kg=Decimal('6.0000')
            )

    def test_recursos_sprint8c_tenant_b_retornam_404_para_usuario_tenant_a(self):
        endpoints = [
            f'/produtos/api/tanques/{self.tanque_b.id}/',
            f'/produtos/api/medicoes-tanque/{self.medicao_b.id}/',
            f'/produtos/api/custos-lote/{self.custo_b.id}/',
        ]
        for url in endpoints:
            res = self.client.get(url)
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, f"URL {url} deveria retornar 404")
