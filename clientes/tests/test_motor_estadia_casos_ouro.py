import uuid
import zoneinfo
from datetime import datetime, date, timedelta
from decimal import Decimal
from django.db import models
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from django.core.exceptions import ValidationError, PermissionDenied
from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import (
    Cliente, ContratoComodato, FranquiaModeloContrato, DiaCilindro,
    FechamentoFaturaEstadia, ItemFaturaEstadia, AjusteCompetenciaEstadia, ExtravioCilindroRegistro
)
from clientes.services import (
    calcular_diarias_cliente_data,
    recalcular_estadia_periodo,
    recalcular_diarias_posse,
    calcular_radar_comodato_tenant,
    fechar_fatura_estadia_competencia,
    declarar_cilindro_extraviado,
    identificar_cilindros_limite_extravio,
    gerar_espelho_medicao_csv,
    gerar_espelho_medicao_pdf,
    gerar_exportacao_canonica_erp,
    FUSO_HORARIO_PADRAO
)
from produtos.models import (
    GasQuimico,
    ModeloCilindro,
    Cilindro,
    LoteEnvase,
    EnvaseCilindro,
    InspecaoPreEnvase,
    MovimentacaoCilindro
)
from produtos.services import registrar_entrega_cilindro, registrar_recolha_cilindro

User = get_user_model()


class MotorEstadiaCasosOuroTests(TestCase):
    """
    Suíte Oficial dos 10 Casos de Ouro do Motor Determinístico de Estadia e Demurrage
    (Sprint 5B.1 — Seção 3.1 e Apêndice A do Plano Consolidado v5 e ADR-001).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='12.345.678/0001-99',
            razao_social='Oxigênio Centro-Oeste Ltda',
            nome_fantasia='OxiOeste'
        )
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(
            username='operador.comodato',
            password='senha_segura_123'
        )
        Membership.objects.create(user=self.user, tenant=self.tenant, papel='GERENTE')

        # Catálogo Base
        self.gas_o2 = GasQuimico.objects.create(
            sigla='O2-MED',
            nome='Oxigênio Medicinal',
            categoria='MEDICINAL',
            exige_lote_anvisa=True
        )

        self.gas_n2 = GasQuimico.objects.create(
            sigla='N2-IND',
            nome='Nitrogênio Industrial',
            categoria='INDUSTRIAL',
            exige_lote_anvisa=False
        )

        # Modelos
        self.modelo_t50 = ModeloCilindro.objects.create(
            descricao='Cilindro T-50 (50 Litros)',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('60.00'),
            periodicidade_reteste_anos=5
        )

        self.modelo_pp = ModeloCilindro.objects.create(
            descricao='Cilindro PP (10 Litros)',
            volume_hidraulico_litros=Decimal('10.00'),
            pressao_servico_bar=150,
            tara_nominal_kg=Decimal('15.00'),
            periodicidade_reteste_anos=5
        )

        # Cliente Hospitalar Principal
        self.hospital = Cliente.objects.create(
            cnpj='00.111.222/0001-33',
            nome='Hospital Santa Maria',
            endereco='Av. Saúde, 100',
            telefone='6133334444',
            estado='DF',
            cidade='Brasília',
            proprietario='Diretoria Geral'
        )

        # Lote de Envase para permitir expedição regulamentar
        self.lote_o2 = LoteEnvase.objects.create(
            gas=self.gas_o2,
            codigo_lote='LOT-O2-2026-01',
            status_qualidade='APROVADO',
            data_envase=date(2026, 1, 1),
            data_validade=date(2028, 1, 1),
            pureza_percentual=Decimal('99.60'),
            responsavel_tecnico='Dr. Lucas Farmacêutico (CRF-DF 9999)',
            rt_nome_snapshot='Dr. Lucas Farmacêutico',
            rt_registro_snapshot='CRF-DF 9999'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    # --------------------------------------------------------------------------
    # Helpers de Criação e Movimentação no Ledger
    # --------------------------------------------------------------------------
    def _criar_cilindro(
        self,
        serial,
        modelo=None,
        gas=None,
        propriedade='DISTRIBUIDORA',
        is_reserva=False
    ):
        mod = modelo or self.modelo_t50
        g = gas or self.gas_o2
        cil = Cilindro.objects.create(
            codigo_qr=f"QR-{serial}",
            numero_serie_ogiva=serial,
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=mod,
            gas_dedicado=g,
            tara_real_kg=mod.tara_nominal_kg,
            propriedade=propriedade,
            is_reserva_tecnica=is_reserva,
            data_ultimo_reteste=date(2024, 1, 1),
            data_proximo_reteste=date(2029, 1, 1),
            status='CHEIO_DISPONIVEL'
        )
        # Cria envase ativo para conformidade sanitária
        env = EnvaseCilindro.objects.create(
            cilindro=cil,
            lote=self.lote_o2,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.user
        )
        cil.envase_atual = env
        cil.save(update_fields=['envase_atual'])
        return cil

    def _entregar_no_ledger(self, cilindro, cliente, data_entrega, hora=10):
        """Registra movimentação ENTREGA_CLIENTE com timestamp exato no fuso de Brasília."""
        dt_sp = datetime.combine(data_entrega, datetime.min.time(), tzinfo=FUSO_HORARIO_PADRAO).replace(hour=hora)
        cilindro, mov = registrar_entrega_cilindro(
            cilindro=cilindro,
            cliente=cliente,
            usuario=self.user,
            ocorrido_em=dt_sp,
            client_uuid=uuid.uuid4()
        )
        return mov

    def _recolher_no_ledger(self, cilindro, cliente, data_recolha, hora=16):
        """Registra movimentação RECOLHA_CLIENTE com timestamp exato no fuso de Brasília."""
        dt_sp = datetime.combine(data_recolha, datetime.min.time(), tzinfo=FUSO_HORARIO_PADRAO).replace(hour=hora)
        cilindro, mov = registrar_recolha_cilindro(
            cilindro=cilindro,
            cliente=cliente,
            usuario=self.user,
            ocorrido_em=dt_sp,
            client_uuid=uuid.uuid4()
        )
        return mov

    # ==========================================================================
    # CASO DE OURO 1: Carência Individual sem Consumo de Franquia
    # ==========================================================================
    def test_caso_ouro_01_carencia_individual_sem_consumo_franquia(self):
        """
        Regra Determinística Fundamental:
        Cilindros dentro da carência individual (< carencia) são ISENTO_CARENCIA (R$ 0,00)
        e NUNCA consomem as vagas da franquia do modelo!
        """
        dia_d = date(2026, 10, 15)

        # Contrato: Franquia de 2 cilindros T-50, Carência = 30 dias, Taxa = R$ 3,50
        contrato = ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=2,
            dias_carencia_giro=30,
            valor_diaria_excedente=Decimal('3.50')
        )
        FranquiaModeloContrato.objects.create(
            contrato=contrato,
            modelo=self.modelo_t50,
            franquia_cilindros_isentos=2,
            dias_carencia_giro=30,
            taxa_diaria=Decimal('3.50')
        )

        # Cilindro A: entregue há 40 dias (passou da carência)
        cil_a = self._criar_cilindro('CIL-A-01', self.modelo_t50)
        self._entregar_no_ledger(cil_a, self.hospital, dia_d - timedelta(days=40))

        # Cilindros B e C: entregues há 10 dias (dentro da carência)
        cil_b = self._criar_cilindro('CIL-B-01', self.modelo_t50)
        self._entregar_no_ledger(cil_b, self.hospital, dia_d - timedelta(days=10))

        cil_c = self._criar_cilindro('CIL-C-01', self.modelo_t50)
        self._entregar_no_ledger(cil_c, self.hospital, dia_d - timedelta(days=10))

        # Executa o cálculo determinístico no dia D
        resultados = calcular_diarias_cliente_data(self.hospital, dia_d, persistir=True)
        res_map = {r['cilindro'].id: r for r in resultados}

        # B e C devem ser ISENTO_CARENCIA
        self.assertEqual(res_map[cil_b.id]['classe_cobranca'], 'ISENTO_CARENCIA')
        self.assertEqual(res_map[cil_b.id]['valor_diaria'], Decimal('0.00'))

        self.assertEqual(res_map[cil_c.id]['classe_cobranca'], 'ISENTO_CARENCIA')
        self.assertEqual(res_map[cil_c.id]['valor_diaria'], Decimal('0.00'))

        # A tem idade=40 >= 30, então disputa a franquia.
        # Como B e C NÃO consumiram a franquia, há 2 vagas livres de franquia.
        # Logo, Cilindro A deve receber ISENTO_FRANQUIA (R$ 0,00) em vez de ser cobrado!
        self.assertEqual(res_map[cil_a.id]['classe_cobranca'], 'ISENTO_FRANQUIA')
        self.assertEqual(res_map[cil_a.id]['valor_diaria'], Decimal('0.00'))

        # Total cobrado no dia D deve ser exatamente R$ 0,00
        total_dia = sum(r['valor_diaria'] for r in resultados)
        self.assertEqual(total_dia, Decimal('0.00'))

    # ==========================================================================
    # CASO DE OURO 2: Franquia por Modelo (T-50 vs PP)
    # ==========================================================================
    def test_caso_ouro_02_franquia_por_modelo_t50_e_pp(self):
        """
        Garante que a franquia e carência operem de forma independente por modelo:
        - T-50: Franquia = 2, Carência = 30d, Taxa = R$ 5,00
        - PP: Franquia = 1, Carência = 15d, Taxa = R$ 2,50
        """
        dia_d = date(2026, 10, 15)

        contrato = ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            criterio_franquia='FIFO'
        )
        FranquiaModeloContrato.objects.create(
            contrato=contrato,
            modelo=self.modelo_t50,
            franquia_cilindros_isentos=2,
            dias_carencia_giro=30,
            taxa_diaria=Decimal('5.00')
        )
        FranquiaModeloContrato.objects.create(
            contrato=contrato,
            modelo=self.modelo_pp,
            franquia_cilindros_isentos=1,
            dias_carencia_giro=15,
            taxa_diaria=Decimal('2.50')
        )

        # 3 cilindros T-50 com idade = 40 dias (> 30d)
        t50_1 = self._criar_cilindro('T50-01', self.modelo_t50)
        self._entregar_no_ledger(t50_1, self.hospital, dia_d - timedelta(days=42))

        t50_2 = self._criar_cilindro('T50-02', self.modelo_t50)
        self._entregar_no_ledger(t50_2, self.hospital, dia_d - timedelta(days=41))

        t50_3 = self._criar_cilindro('T50-03', self.modelo_t50)
        self._entregar_no_ledger(t50_3, self.hospital, dia_d - timedelta(days=40))

        # 2 cilindros PP com idade = 20 dias (> 15d)
        pp_1 = self._criar_cilindro('PP-01', self.modelo_pp)
        self._entregar_no_ledger(pp_1, self.hospital, dia_d - timedelta(days=22))

        pp_2 = self._criar_cilindro('PP-02', self.modelo_pp)
        self._entregar_no_ledger(pp_2, self.hospital, dia_d - timedelta(days=20))

        resultados = calcular_diarias_cliente_data(self.hospital, dia_d, persistir=True)
        res_map = {r['cilindro'].id: r for r in resultados}

        # T-50: 2 primeiros isentos por franquia, 3º cobrável a R$ 5,00
        self.assertEqual(res_map[t50_1.id]['classe_cobranca'], 'ISENTO_FRANQUIA')
        self.assertEqual(res_map[t50_2.id]['classe_cobranca'], 'ISENTO_FRANQUIA')
        self.assertEqual(res_map[t50_3.id]['classe_cobranca'], 'COBRAVEL')
        self.assertEqual(res_map[t50_3.id]['valor_diaria'], Decimal('5.00'))

        # PP: 1 primeiro isento por franquia, 2º cobrável a R$ 2,50
        self.assertEqual(res_map[pp_1.id]['classe_cobranca'], 'ISENTO_FRANQUIA')
        self.assertEqual(res_map[pp_2.id]['classe_cobranca'], 'COBRAVEL')
        self.assertEqual(res_map[pp_2.id]['valor_diaria'], Decimal('2.50'))

        # Total do dia: R$ 5,00 + R$ 2,50 = R$ 7,50
        total_dia = sum(r['valor_diaria'] for r in resultados)
        self.assertEqual(total_dia, Decimal('7.50'))

    # ==========================================================================
    # CASO DE OURO 3: Critério de Franquia — FIFO vs LIFO
    # ==========================================================================
    def test_caso_ouro_03_criterio_franquia_fifo_vs_lifo(self):
        """
        Valida que sob FIFO o cilindro entregue há mais tempo recebe a franquia,
        enquanto sob LIFO o mais recentemente entregue recebe a franquia.
        """
        dia_d = date(2026, 10, 15)

        contrato = ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            criterio_franquia='FIFO',
            franquia_cilindros_isentos=1,
            dias_carencia_giro=30,
            valor_diaria_excedente=Decimal('4.00')
        )
        FranquiaModeloContrato.objects.create(
            contrato=contrato,
            modelo=self.modelo_t50,
            franquia_cilindros_isentos=1,
            dias_carencia_giro=30,
            taxa_diaria=Decimal('4.00')
        )

        # 3 cilindros com idades 50, 40 e 35 dias (todos fora da carência)
        c1 = self._criar_cilindro('FIFO-50D', self.modelo_t50)
        self._entregar_no_ledger(c1, self.hospital, dia_d - timedelta(days=50))

        c2 = self._criar_cilindro('FIFO-40D', self.modelo_t50)
        self._entregar_no_ledger(c2, self.hospital, dia_d - timedelta(days=40))

        c3 = self._criar_cilindro('FIFO-35D', self.modelo_t50)
        self._entregar_no_ledger(c3, self.hospital, dia_d - timedelta(days=35))

        # --- Teste 1: Sob FIFO (Primeiro a Entrar, Primeiro a Isentar) ---
        contrato.criterio_franquia = 'FIFO'
        contrato.save(update_fields=['criterio_franquia'])

        res_fifo = calcular_diarias_cliente_data(self.hospital, dia_d, persistir=False)
        map_fifo = {r['cilindro'].id: r for r in res_fifo}

        self.assertEqual(map_fifo[c1.id]['classe_cobranca'], 'ISENTO_FRANQUIA')
        self.assertEqual(map_fifo[c2.id]['classe_cobranca'], 'COBRAVEL')
        self.assertEqual(map_fifo[c3.id]['classe_cobranca'], 'COBRAVEL')
        self.assertEqual(sum(r['valor_diaria'] for r in res_fifo), Decimal('8.00'))

        # --- Teste 2: Sob LIFO (Último a Entrar, Primeiro a Isentar) ---
        contrato.criterio_franquia = 'LIFO'
        contrato.save(update_fields=['criterio_franquia'])

        res_lifo = calcular_diarias_cliente_data(self.hospital, dia_d, persistir=False)
        map_lifo = {r['cilindro'].id: r for r in res_lifo}

        # No LIFO, c3 (entregue há 35d, mais recente) ganha a franquia!
        self.assertEqual(map_lifo[c3.id]['classe_cobranca'], 'ISENTO_FRANQUIA')
        self.assertEqual(map_lifo[c1.id]['classe_cobranca'], 'COBRAVEL')
        self.assertEqual(map_lifo[c2.id]['classe_cobranca'], 'COBRAVEL')
        self.assertEqual(sum(r['valor_diaria'] for r in res_lifo), Decimal('8.00'))

    # ==========================================================================
    # CASO DE OURO 4: Cascos de Terceiros e Reserva Técnica
    # ==========================================================================
    def test_caso_ouro_04_cascos_terceiros_e_reserva_tecnica(self):
        """
        Cilindros com propriedade do cliente/terceiro recebem NAO_COBRAVEL_PROPRIEDADE (R$ 0,00).
        Cilindros em Reserva Técnica recebem ISENTO_RESERVA (R$ 0,00).
        Nenhum deles consome a franquia do contrato!
        """
        dia_d = date(2026, 10, 15)

        contrato = ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=1,
            dias_carencia_giro=30,
            valor_diaria_excedente=Decimal('3.50')
        )
        FranquiaModeloContrato.objects.create(
            contrato=contrato,
            modelo=self.modelo_t50,
            franquia_cilindros_isentos=1,
            dias_carencia_giro=30,
            taxa_diaria=Decimal('3.50')
        )

        # Cilindro 1: Propriedade do Cliente
        cil_cli = self._criar_cilindro('CLI-PROP', self.modelo_t50, propriedade='CLIENTE')
        self._entregar_no_ledger(cil_cli, self.hospital, dia_d - timedelta(days=60))

        # Cilindro 2: Casco de Parceiro / Intercâmbio
        cil_terc = self._criar_cilindro('TERC-PROP', self.modelo_t50, propriedade='TERCEIRO_INTERCAMBIO')
        self._entregar_no_ledger(cil_terc, self.hospital, dia_d - timedelta(days=60))

        # Cilindro 3: Reserva Técnica Homologada
        cil_res = self._criar_cilindro('RESERVA-01', self.modelo_t50, is_reserva=True)
        self._entregar_no_ledger(cil_res, self.hospital, dia_d - timedelta(days=60))

        # Cilindros 4 e 5: Próprios normais
        cil_p1 = self._criar_cilindro('PROP-01', self.modelo_t50, propriedade='DISTRIBUIDORA')
        self._entregar_no_ledger(cil_p1, self.hospital, dia_d - timedelta(days=55))

        cil_p2 = self._criar_cilindro('PROP-02', self.modelo_t50, propriedade='DISTRIBUIDORA')
        self._entregar_no_ledger(cil_p2, self.hospital, dia_d - timedelta(days=50))

        resultados = calcular_diarias_cliente_data(self.hospital, dia_d, persistir=True)
        res_map = {r['cilindro'].id: r for r in resultados}

        # Validações de Não Cobrável e Reserva
        self.assertEqual(res_map[cil_cli.id]['classe_cobranca'], 'NAO_COBRAVEL_PROPRIEDADE')
        self.assertEqual(res_map[cil_cli.id]['valor_diaria'], Decimal('0.00'))

        self.assertEqual(res_map[cil_terc.id]['classe_cobranca'], 'NAO_COBRAVEL_PROPRIEDADE')
        self.assertEqual(res_map[cil_terc.id]['valor_diaria'], Decimal('0.00'))

        self.assertEqual(res_map[cil_res.id]['classe_cobranca'], 'ISENTO_RESERVA')
        self.assertEqual(res_map[cil_res.id]['valor_diaria'], Decimal('0.00'))

        # Cilindro Próprio 1 ganha a 1 única franquia disponível
        self.assertEqual(res_map[cil_p1.id]['classe_cobranca'], 'ISENTO_FRANQUIA')
        self.assertEqual(res_map[cil_p1.id]['valor_diaria'], Decimal('0.00'))

        # Cilindro Próprio 2 excede e é cobrado
        self.assertEqual(res_map[cil_p2.id]['classe_cobranca'], 'COBRAVEL')
        self.assertEqual(res_map[cil_p2.id]['valor_diaria'], Decimal('3.50'))

    # ==========================================================================
    # CASO DE OURO 5: Entrega e Recolha no Mesmo Dia Calendário (0 Dias)
    # ==========================================================================
    def test_caso_ouro_05_entrega_e_recolha_mesmo_dia(self):
        """
        Entrega e recolha no mesmo dia resulta em 0 diárias geradas,
        pois a última movimentação às 23:59:59 não é posse do cliente.
        """
        dia_d = date(2026, 10, 15)

        contrato = ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=0,
            dias_carencia_giro=0,
            valor_diaria_excedente=Decimal('10.00')
        )

        cil = self._criar_cilindro('SAME-DAY-01', self.modelo_t50)

        # Entrega às 09:00
        self._entregar_no_ledger(cil, self.hospital, dia_d, hora=9)

        # Recolha às 15:00 do mesmo dia
        self._recolher_no_ledger(cil, self.hospital, dia_d, hora=15)

        resultados = calcular_diarias_cliente_data(self.hospital, dia_d, persistir=True)

        # Cilindro não deve constar na posse do dia D (0 registros gerados)
        self.assertEqual(len(resultados), 0)
        self.assertFalse(DiaCilindro.unscoped.filter(cilindro=cil, data_referencia=dia_d).exists())

    # ==========================================================================
    # CASO DE OURO 6: Equivalência: Recálculo Incremental vs. Recálculo do Zero
    # ==========================================================================
    def test_caso_ouro_06_equivalencia_recalculo_incremental_vs_completo(self):
        """
        Teste de Propriedade Fundamental:
        O resultado final de DiaCilindro gravado passo a passo incrementalmente
        a cada nova movimentação DEVE ser 100% IDÊNTICO ao recálculo completo do zero
        para todo o período.
        """
        data_inicio = date(2026, 10, 1)
        data_fim = date(2026, 10, 10)

        contrato = ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=1,
            dias_carencia_giro=3,
            valor_diaria_excedente=Decimal('5.00')
        )

        cil_1 = self._criar_cilindro('INC-01', self.modelo_t50)
        cil_2 = self._criar_cilindro('INC-02', self.modelo_t50)

        # Passo a Passo com recálculo incremental (chamado pelo service de entrega/recolha)
        # Dia 1: entrega cil_1
        self._entregar_no_ledger(cil_1, self.hospital, data_inicio)

        # Dia 4: entrega cil_2
        self._entregar_no_ledger(cil_2, self.hospital, data_inicio + timedelta(days=3))

        # Dia 7: recolhe cil_1
        self._recolher_no_ledger(cil_1, self.hospital, data_inicio + timedelta(days=6))

        # Garante recálculo até data_fim
        recalcular_estadia_periodo(self.tenant.id, data_inicio, data_fim, cliente_id=self.hospital.id)

        # Snapshot do Modo Incremental no período [data_inicio, data_fim]
        dados_incremental = list(
            DiaCilindro.unscoped
            .filter(
                tenant_id=self.tenant.id,
                cliente=self.hospital,
                data_referencia__gte=data_inicio,
                data_referencia__lte=data_fim
            )
            .order_by('data_referencia', 'cilindro_id')
            .values('cilindro_id', 'data_referencia', 'idade_posse_dias', 'classe_cobranca', 'valor_diaria')
        )
        self.assertGreater(len(dados_incremental), 0)

        # Limpa completamente a tabela de diárias
        DiaCilindro.unscoped.filter(tenant_id=self.tenant.id).delete()
        self.assertEqual(DiaCilindro.unscoped.filter(tenant_id=self.tenant.id).count(), 0)

        # Modo Completo do Zero
        recalcular_estadia_periodo(self.tenant.id, data_inicio, data_fim, cliente_id=self.hospital.id)

        dados_completo = list(
            DiaCilindro.unscoped
            .filter(
                tenant_id=self.tenant.id,
                cliente=self.hospital,
                data_referencia__gte=data_inicio,
                data_referencia__lte=data_fim
            )
            .order_by('data_referencia', 'cilindro_id')
            .values('cilindro_id', 'data_referencia', 'idade_posse_dias', 'classe_cobranca', 'valor_diaria')
        )

        # Valida igualdade estrita elemento a elemento
        self.assertEqual(len(dados_incremental), len(dados_completo))
        for item_inc, item_comp in zip(dados_incremental, dados_completo):
            self.assertEqual(item_inc['cilindro_id'], item_comp['cilindro_id'])
            self.assertEqual(item_inc['data_referencia'], item_comp['data_referencia'])
            self.assertEqual(item_inc['idade_posse_dias'], item_comp['idade_posse_dias'])
            self.assertEqual(item_inc['classe_cobranca'], item_comp['classe_cobranca'])
            self.assertEqual(item_inc['valor_diaria'], item_comp['valor_diaria'])

    # ==========================================================================
    # ==========================================================================
    # CASO DE OURO 7: Fechamento de Fatura de Estadia e Imutabilidade Estrita
    # ==========================================================================
    def test_caso_ouro_07_fechamento_fatura_estadia_e_imutabilidade(self):
        """
        Caso de Ouro #7:
        1. Gera o snapshot oficial de fechamento mensal da fatura de estadia.
        2. Valida cálculo determinístico e analítico dos itens por cilindro.
        3. Prova que a fatura fechada resiste a qualquer tentativa de mutação ou exclusão
           (ORM save, delete, bulk update, bulk delete e exclusão de itens).
        4. Impede fechamento duplicado da mesma competência.
        """
        dia_inicio = date(2026, 10, 1)

        ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=0,
            dias_carencia_giro=0,
            valor_diaria_excedente=Decimal('10.00')
        )

        cil = self._criar_cilindro('FAT-01', self.modelo_t50)
        self._entregar_no_ledger(cil, self.hospital, dia_inicio)

        # Fecha a competência 2026-10 (31 dias * R$ 10,00 = R$ 310,00)
        fatura = fechar_fatura_estadia_competencia(
            cliente=self.hospital,
            competencia_ano_mes='2026-10',
            usuario=self.user,
            tenant_id=self.tenant.id
        )

        self.assertEqual(fatura.status_pagamento, 'FECHADA')
        self.assertEqual(fatura.competencia_ano_mes, '2026-10')
        self.assertEqual(fatura.valor_bruto_diarias, Decimal('310.00'))
        self.assertEqual(fatura.valor_liquido_total, Decimal('310.00'))
        self.assertEqual(fatura.itens.count(), 1)

        item = fatura.itens.first()
        self.assertEqual(item.cilindro, cil)
        self.assertEqual(item.dias_posse_mes, 31)
        self.assertEqual(item.dias_cobraveis, 31)
        self.assertEqual(item.diaria_aplicada, Decimal('10.00'))
        self.assertEqual(item.subtotal, Decimal('310.00'))

        # Prova de Imutabilidade 1: Tentativa de alterar valor via .save()
        fatura.valor_liquido_total = Decimal('100.00')
        with self.assertRaises(ValidationError):
            fatura.save()

        # Prova de Imutabilidade 2: Tentativa de exclusão via .delete()
        fatura.refresh_from_db()
        with self.assertRaises(ValidationError):
            fatura.delete()

        # Prova de Imutabilidade 3: Tentativa de update em lote no QuerySet
        with self.assertRaises(ValidationError):
            FechamentoFaturaEstadia.objects.filter(id=fatura.id).update(valor_liquido_total=Decimal('50.00'))

        # Prova de Imutabilidade 4: Tentativa de exclusão em lote no QuerySet
        with self.assertRaises(ValidationError):
            FechamentoFaturaEstadia.objects.filter(id=fatura.id).delete()

        # Prova de Imutabilidade 5: Tentativa de excluir item da fatura
        with self.assertRaises(ValidationError):
            item.delete()

        # Prova de Imutabilidade 6: Tentativa de fechar novamente o mesmo mês
        with self.assertRaises(ValidationError):
            fechar_fatura_estadia_competencia(
                cliente=self.hospital,
                competencia_ano_mes='2026-10',
                usuario=self.user,
                tenant_id=self.tenant.id
            )

    # ==========================================================================
    # CASO DE OURO 8: Extravio, Alerta e Reposição Patrimonial (Caso de Ouro #9)
    # ==========================================================================
    def test_caso_ouro_08_extravio_apos_limite_dias_e_reposicao(self):
        """
        Caso de Ouro #8 / #9:
        1. Cilindro em posse além de dias_limite_extravio (180d) gera alerta no painel.
        2. Restrição RBAC: usuários não autorizados são bloqueados de declarar extravio.
        3. Gerente/Admin declara extravio formal com justificativa.
        4. O cilindro encerra a contagem de diárias imediatamente.
        5. O valor de reposição contratual é gerado e cobrado no fechamento da fatura.
        """
        dia_d = date(2026, 10, 15)

        contrato = ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            dias_limite_extravio=180,
            custo_reposicao_casco=Decimal('2200.00'),
            valor_diaria_excedente=Decimal('5.00')
        )
        FranquiaModeloContrato.objects.create(
            contrato=contrato,
            modelo=self.modelo_t50,
            valor_reposicao_extravio=Decimal('2500.00'),
            taxa_diaria=Decimal('5.00')
        )

        # Entregue há 195 dias
        cil = self._criar_cilindro('EXTRAVIO-01', self.modelo_t50)
        self._entregar_no_ledger(cil, self.hospital, dia_d - timedelta(days=195))

        # 1. Alerta de Extravio
        alertas = identificar_cilindros_limite_extravio(tenant_id=self.tenant.id, cliente=self.hospital, data_referencia=dia_d)
        self.assertEqual(len(alertas), 1)
        alerta = alertas[0]
        self.assertEqual(alerta['cilindro_id'], cil.id)
        self.assertEqual(alerta['dias_em_posse'], 195)
        self.assertEqual(alerta['dias_limite_extravio'], 180)
        self.assertEqual(alerta['dias_excedentes_extravio'], 15)
        self.assertEqual(alerta['valor_reposicao'], 2500.00)

        # 2. RBAC: Operador sem permissão não pode declarar extravio
        user_op = User.objects.create_user(username='operador.patio.teste', password='pwd')
        Membership.objects.create(user=user_op, tenant=self.tenant, papel='OPERADOR_PATIO')
        with self.assertRaises(PermissionDenied):
            declarar_cilindro_extraviado(
                cilindro=cil,
                usuario=user_op,
                data_extravio=dia_d,
                justificativa="Extravio não autorizado"
            )

        # 3. Gerente declara extravio formal
        registro = declarar_cilindro_extraviado(
            cilindro=cil,
            usuario=self.user,
            data_extravio=dia_d,
            justificativa="Cilindro extraviado pelo hospital em reforma de ala."
        )

        self.assertEqual(registro.valor_reposicao, Decimal('2500.00'))
        self.assertFalse(registro.cobrado)
        self.assertEqual(registro.dias_em_posse_sem_giro, 195)

        cil.refresh_from_db()
        self.assertEqual(cil.status, 'EXTRAVIADO')
        self.assertIsNone(cil.cliente_posse_atual)

        # 4. Encerra contagem de diárias em e após a data do extravio
        dia_pos_extravio = dia_d + timedelta(days=1)
        res_depois = calcular_diarias_cliente_data(self.hospital, dia_pos_extravio, persistir=True)
        self.assertEqual(len(res_depois), 0)

        # 5. Fechamento de Fatura inclui a cobrança da reposição patrimonial
        fatura = fechar_fatura_estadia_competencia(
            cliente=self.hospital,
            competencia_ano_mes='2026-10',
            usuario=self.user,
            tenant_id=self.tenant.id
        )

        self.assertEqual(fatura.valor_reposicao_extravios, Decimal('2500.00'))
        # 14 dias cobráveis de estadia em outubro (01/10 a 14/10) a R$ 5,00 = R$ 70,00
        self.assertEqual(fatura.valor_bruto_diarias, Decimal('70.00'))
        self.assertEqual(fatura.valor_liquido_total, Decimal('2570.00'))

        registro.refresh_from_db()
        self.assertTrue(registro.cobrado)
        self.assertEqual(registro.fatura_cobranca, fatura)

    # ==========================================================================
    # CASO DE OURO 9: Movimentação Tardia e Ajuste Retroativo (Caso de Ouro #7)
    # ==========================================================================
    def test_caso_ouro_09_movimentacao_tardia_e_ajuste_competencia_seguinte(self):
        """
        Caso de Ouro #7 (Apêndice A e ADR-001):
        1. Competência 2026-10 é fechada com fatura formal e imutável.
        2. Em novembro, uma movimentação de recolha com ocorrido_em retroativo (03/10)
           é sincronizada (ex.: sync offline tardio).
        3. A fatura de outubro NUNCA é alterada.
        4. O motor detecta o recálculo e gera automaticamente AjusteCompetenciaEstadia (crédito).
        5. No fechamento da competência 2026-11, o crédito é automaticamente abatido do valor líquido.
        """
        dia_out_ini = date(2026, 10, 1)

        ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=0,
            dias_carencia_giro=0,
            valor_diaria_excedente=Decimal('10.00')
        )

        cil_out = self._criar_cilindro('RETRO-01', self.modelo_t50)
        self._entregar_no_ledger(cil_out, self.hospital, dia_out_ini)

        # Simulando que a posse de RETRO-01 foi recolhida no dia 06/10 originalmente
        # (posse ativa nos dias 01, 02, 03, 04 e 05 às 23:59:59 = 5 dias * R$ 10,00 = R$ 50,00)
        self._recolher_no_ledger(cil_out, self.hospital, date(2026, 10, 6))

        # Fecha a fatura de outubro: 5 dias (01, 02, 03, 04, 05) * R$ 10,00 = R$ 50,00
        fatura_out = fechar_fatura_estadia_competencia(
            cliente=self.hospital,
            competencia_ano_mes='2026-10',
            usuario=self.user,
            tenant_id=self.tenant.id
        )

        self.assertEqual(fatura_out.valor_bruto_diarias, Decimal('50.00'))
        self.assertEqual(fatura_out.valor_liquido_total, Decimal('50.00'))
        self.assertEqual(fatura_out.status_pagamento, 'FECHADA')

        # Em Novembro, sync offline registra recolha tardia ocorrida em 03/10
        # (na verdade o cilindro saiu no dia 03/10, restando ativos apenas os dias 01 e 02 = R$ 20,00)
        self._recolher_no_ledger(cil_out, self.hospital, date(2026, 10, 3))

        # Recálculo do período abrangendo a data retroativa
        recalcular_estadia_periodo(
            self.tenant.id,
            date(2026, 10, 1),
            date(2026, 11, 30),
            cliente_id=self.hospital.id
        )

        # A FATURA DE OUTUBRO CONTINUA ESTRITAMENTE IMUTÁVEL!
        fatura_out.refresh_from_db()
        self.assertEqual(fatura_out.valor_bruto_diarias, Decimal('50.00'))
        self.assertEqual(fatura_out.valor_liquido_total, Decimal('50.00'))

        # Ajuste de Competência gerado automaticamente (Crédito de 3 dias = R$ 30,00)
        ajuste = AjusteCompetenciaEstadia.objects.filter(
            cliente=self.hospital,
            fatura_origem=fatura_out
        ).first()

        self.assertIsNotNone(ajuste)
        self.assertEqual(ajuste.tipo_ajuste, 'CREDITO')
        self.assertEqual(ajuste.valor_ajuste, Decimal('30.00'))
        self.assertFalse(ajuste.compensado)

        # Em Novembro, novo cilindro é entregue em 01/11 e recolhido em 11/11 (10 dias ativos * R$ 10 = R$ 100,00)
        cil_nov = self._criar_cilindro('NOV-01', self.modelo_t50)
        self._entregar_no_ledger(cil_nov, self.hospital, date(2026, 11, 1))
        self._recolher_no_ledger(cil_nov, self.hospital, date(2026, 11, 11))

        # Fecha a competência de Novembro (2026-11)
        fatura_nov = fechar_fatura_estadia_competencia(
            cliente=self.hospital,
            competencia_ano_mes='2026-11',
            usuario=self.user,
            tenant_id=self.tenant.id
        )

        # R$ 100,00 brutos - R$ 30,00 de crédito retroativo = R$ 70,00 líquido!
        self.assertEqual(fatura_nov.valor_bruto_diarias, Decimal('100.00'))
        self.assertEqual(fatura_nov.valor_ajustes_retroativos, Decimal('-30.00'))
        self.assertEqual(fatura_nov.valor_liquido_total, Decimal('70.00'))

        ajuste.refresh_from_db()
        self.assertTrue(ajuste.compensado)
        self.assertEqual(ajuste.fatura_compensacao, fatura_nov)

    # ==========================================================================
    # CASO DE OURO 11 (Sprint 5B.2): Espelho PDF/CSV e Exportação Canônica ERP
    # ==========================================================================
    def test_espelho_medicao_pdf_csv_e_exportacao_erp(self):
        """
        Valida a geração de artefatos de faturamento da Sprint 5B.2:
        1. Espelho de Medição em formato CSV.
        2. Espelho de Medição em formato PDF (ReportLab).
        3. Exportação Canônica para ERP em JSON e CSV.
        """
        ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=0,
            dias_carencia_giro=0,
            valor_diaria_excedente=Decimal('10.00')
        )

        cil = self._criar_cilindro('EXP-01', self.modelo_t50)
        self._entregar_no_ledger(cil, self.hospital, date(2026, 5, 1))
        self._recolher_no_ledger(cil, self.hospital, date(2026, 5, 11))

        fatura = fechar_fatura_estadia_competencia(
            cliente=self.hospital,
            competencia_ano_mes='2026-05',
            usuario=self.user,
            tenant_id=self.tenant.id
        )

        # 1. Espelho de Medição CSV
        csv_data = gerar_espelho_medicao_csv(fatura)
        self.assertIn('ESPELHO DE MEDIÇÃO', csv_data)
        self.assertIn(self.hospital.nome, csv_data)
        self.assertIn('2026-05', csv_data)
        self.assertIn('EXP-01', csv_data)
        self.assertIn('100.00', csv_data)

        # 2. Espelho de Medição PDF
        pdf_bytes = gerar_espelho_medicao_pdf(fatura)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

        # 3. Exportação Canônica ERP JSON
        erp_json = gerar_exportacao_canonica_erp(self.tenant.id, '2026-05', formato='json')
        self.assertEqual(erp_json['versao_schema'], '1.0')
        self.assertEqual(erp_json['competencia'], '2026-05')
        self.assertEqual(erp_json['total_faturas'], 1)
        self.assertEqual(erp_json['valor_total_faturado'], 100.0)
        self.assertEqual(len(erp_json['faturas']), 1)
        fat_data = erp_json['faturas'][0]
        self.assertEqual(fat_data['cliente_cnpj'], self.hospital.cnpj)
        self.assertEqual(len(fat_data['itens']), 1)

        # 4. Exportação Canônica ERP CSV
        erp_csv = gerar_exportacao_canonica_erp(self.tenant.id, '2026-05', formato='csv')
        self.assertIn('FATURA_ID;CLIENTE_CNPJ', erp_csv)
        self.assertIn(self.hospital.cnpj, erp_csv)
        self.assertIn('100.00', erp_csv)


    # ==========================================================================
    # CASO DE OURO 10: Precisão Matemática com Decimal
    # ==========================================================================
    def test_caso_ouro_10_precisao_decimal_sem_ponto_flutuante(self):
        """
        Prova a ausência absoluta de dízimas ou erros de arredondamento de float.
        31 dias com taxa de R$ 3,33 devem somar estritamente Decimal('103.23').
        """
        dia_inicio = date(2026, 10, 1)
        dia_fim = date(2026, 10, 31)

        ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=0,
            dias_carencia_giro=0,
            valor_diaria_excedente=Decimal('3.33')
        )

        cil = self._criar_cilindro('PRECISAO-01', self.modelo_t50)
        self._entregar_no_ledger(cil, self.hospital, dia_inicio)

        recalcular_estadia_periodo(self.tenant.id, dia_inicio, dia_fim, cliente_id=self.hospital.id)

        diarias = DiaCilindro.unscoped.filter(
            cliente=self.hospital,
            data_referencia__gte=dia_inicio,
            data_referencia__lte=dia_fim
        )

        self.assertEqual(diarias.count(), 31)
        for d in diarias:
            self.assertEqual(d.valor_diaria, Decimal('3.33'))

        soma_total = diarias.aggregate(total=models.Sum('valor_diaria'))['total']
        self.assertEqual(soma_total, Decimal('103.23'))
        self.assertIsInstance(soma_total, Decimal)

    # ==========================================================================
    # Teste de Integração: Radar do Dashboard Unificado
    # ==========================================================================
    def test_radar_dashboard_integracao_motor_estadia(self):
        """
        Valida que calcular_radar_comodato_tenant consome a nova inteligência determinística
        e retorna todos os KPIs esperados pelo Dashboard.
        """
        hoje = timezone.now().astimezone(FUSO_HORARIO_PADRAO).date()

        ContratoComodato.objects.create(
            cliente=self.hospital,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=1,
            dias_carencia_giro=30,
            valor_diaria_excedente=Decimal('5.00'),
            custo_reposicao_casco=Decimal('2000.00')
        )

        # 1 em carência (10d)
        cil_car = self._criar_cilindro('RADAR-CAR', self.modelo_t50)
        self._entregar_no_ledger(cil_car, self.hospital, hoje - timedelta(days=10))

        # 2 excedendo carência (45d)
        cil_exc1 = self._criar_cilindro('RADAR-EXC1', self.modelo_t50)
        self._entregar_no_ledger(cil_exc1, self.hospital, hoje - timedelta(days=45))

        cil_exc2 = self._criar_cilindro('RADAR-EXC2', self.modelo_t50)
        self._entregar_no_ledger(cil_exc2, self.hospital, hoje - timedelta(days=45))

        radar = calcular_radar_comodato_tenant(self.tenant)

        self.assertEqual(radar['total_cilindros_em_posse'], 3)
        self.assertEqual(radar['cilindros_sem_giro_30_mais'], 2)
        self.assertEqual(radar['risco_patrimonial_total'], 6000.00)

        # Com franquia de 1 isento, 1 dos excedentes recebe isento franquia e o outro gera diária
        # 15 dias excedentes * 5.00 = R$ 75.00
        self.assertEqual(radar['receita_locacao_acumulada'], 75.00)
