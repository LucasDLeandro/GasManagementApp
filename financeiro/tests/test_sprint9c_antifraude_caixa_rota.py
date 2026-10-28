"""
Testes abrangentes da Sprint 9C:
- Antifraude e detecção de todas as anomalias (caso positivo e negativo)
- Idempotência por client_uuid
- Fatura consolidada que cruza meses gerando múltiplos títulos de competência
- Segregação de funções (aprovador != autor/motorista)
- Contagem cega de caixa de rota (saldo_esperado oculto antes da contagem na API e no Template)
- Lançamento contábil direto para despesas em dinheiro de rota (sem título)
- Apuração de quebra de caixa e transferência para o cofre
- Relatórios de consumo, ranking de anomalias e quebras de caixa
- Isolamento multi-tenant (404 estrito)
- Validação da migração IndexedDB v8 (ADR-040)
"""

import os
import uuid
from decimal import Decimal
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Tenant, Filial, Membership
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from logistica.models import Veiculo, LeituraOdometro, Entrega, CoordenadaRastreamento
from financeiro.models import (
    PlanoContas,
    Fornecedor,
    ContaFinanceira,
    PrecoReferenciaCombustivel,
    PreLancamentoDespesaCampo,
    FaturaConsolidadaPosto,
    ItemFaturaPosto,
    FechamentoCaixaRota,
    QuebraCaixa,
    ChequeRecebido,
    TituloFinanceiro,
    LancamentoContabil,
    ParametroFinanceiroTenant,
)
from financeiro.seeds import seed_financeiro_tenant_completo
from financeiro.antifraude import analisar_despesa_campo, importar_precos_referencia_csv
from financeiro.services.despesas_campo import (
    criar_pre_lancamento_despesa,
    aprovar_despesa_campo,
    rejeitar_despesa_campo,
    aprovar_despesas_campo_em_lote,
)
from financeiro.services.fatura_posto import (
    importar_fatura_csv,
    conciliar_itens_fatura,
    aprovar_fatura_posto,
)
from financeiro.services.caixa_rota import (
    obter_ou_criar_fechamento_caixa,
    registrar_contagem_cega,
    conferir_e_fechar_caixa,
    registrar_cheque_recebido,
)
from financeiro.selectors.relatorios_frota import (
    relatorio_consumo_veiculos,
    ranking_motoristas_anomalias,
    relatorio_quebras_caixa,
)

User = get_user_model()


class BaseSprint9CTestCase(TestCase):
    """Setup base multi-tenant para a Sprint 9C."""

    def setUp(self):
        super().setUp()
        cnpj_a = f"11.222.{uuid.uuid4().hex[:3]}/0001-91"
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Alfa de Gases Ltda",
            nome_fantasia="Alfa Gases",
            cnpj=cnpj_a,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.token = set_current_tenant(self.tenant)

        self.filial = Filial.objects.create(
            tenant=self.tenant,
            nome="Matriz",
            cnpj=cnpj_a,
            uf="SP",
            matriz=True
        )

        # Gestor / Conferente
        self.gestor = User.objects.create_user(
            username=f"gestor_{uuid.uuid4().hex[:6]}",
            email="gestor@alfagases.com.br",
            password="secret_password"
        )
        Membership.objects.create(
            user=self.gestor,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True
        )

        # Motorista
        self.motorista = User.objects.create_user(
            username=f"motorista_{uuid.uuid4().hex[:6]}",
            email="motorista@alfagases.com.br",
            password="secret_password"
        )
        Membership.objects.create(
            user=self.motorista,
            tenant=self.tenant,
            papel="MOTORISTA",
            ativo=True
        )

        # Sementes do plano de contas e parâmetros
        seed_financeiro_tenant_completo(self.tenant)

        # Contas Financeiras
        self.conta_cofre_contabil = PlanoContas.objects.get(codigo_estrutural='1.1.1.01')
        self.conta_rota_contabil = PlanoContas.objects.get(codigo_estrutural='1.1.1.03')

        self.caixa_cofre = ContaFinanceira.objects.create(
            tenant=self.tenant,
            nome="Cofre Central",
            tipo="CAIXA",
            conta_contabil=self.conta_cofre_contabil,
            saldo_inicial=Decimal('1000.00'),
            ativo=True
        )

        self.caixa_rota = ContaFinanceira.objects.create(
            tenant=self.tenant,
            nome="Caixa da Rota - João",
            tipo="CAIXA",
            conta_contabil=self.conta_rota_contabil,
            saldo_inicial=Decimal('0.00'),
            ativo=True
        )

        # Veículo
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="ABC1D23",
            modelo="Mercedes-Benz Accelo 1016",
            marca="Mercedes-Benz",
            ano=2022,
            capacidade_carga=Decimal('5000.00'),
            capacidade_tanque_litros=Decimal('100.000'),
            consumo_referencia_kml=Decimal('5.000'),
            tipo_combustivel="DIESEL",
            odometro_atual_km=Decimal('50000.000')
        )

        # Preço de referência semanal ANP
        self.preco_ref = PrecoReferenciaCombustivel.objects.create(
            tenant=self.tenant,
            uf="SP",
            municipio="SAO PAULO",
            combustivel="DIESEL",
            semana="2026-W42",
            preco_medio=Decimal('6.00')
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

        # Clientes HTTP DRF
        self.client_gestor = APIClient()
        self.client_gestor.force_authenticate(user=self.gestor)

        self.client_motorista = APIClient()
        self.client_motorista.force_authenticate(user=self.motorista)

        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()


class TestAntifraudeDespesasCampo(BaseSprint9CTestCase):
    """Testes de todas as regras e anomalias do módulo antifraude."""

    def test_anomalia_litros_acima_do_tanque_positivo_e_negativo(self):
        # Tanque = 100L. Limite = 100 * 1.05 = 105L.
        # Positivo: 106L -> flag LITROS_ACIMA_DO_TANQUE
        alerta_pos, motivos_pos = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('106.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertTrue(alerta_pos)
        self.assertIn("LITROS_ACIMA_DO_TANQUE", motivos_pos)

        # Negativo: 104L -> não flag LITROS_ACIMA_DO_TANQUE
        alerta_neg, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('104.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertNotIn("LITROS_ACIMA_DO_TANQUE", motivos_neg)

    def test_anomalia_odometro_regrediu_positivo_e_negativo(self):
        # Odômetro atual do veículo = 50.000 km
        # Positivo: informado 49.900 km -> flag ODOMETRO_REGREDIU
        alerta_pos, motivos_pos = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('49900.000'),
            litros=Decimal('50.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertTrue(alerta_pos)
        self.assertIn("ODOMETRO_REGREDIU", motivos_pos)

        # Negativo: informado 50.250 km -> não flag ODOMETRO_REGREDIU
        alerta_neg, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50250.000'),
            litros=Decimal('50.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertNotIn("ODOMETRO_REGREDIU", motivos_neg)

    def test_anomalia_consumo_fora_da_faixa_positivo_e_negativo(self):
        # Cria leitura anterior validada: 50.000 km
        LeituraOdometro.objects.create(
            veiculo=self.veiculo,
            km=Decimal('50000.000'),
            data_hora=timezone.now() - timedelta(hours=5),
            origem="ROTA",
            validada=True
        )
        # Consumo referência = 5.0 km/L. Tolerância = 20% -> Faixa válida: [4.0, 6.0] km/L.

        # Positivo 1 (Consumo altíssimo / km/L muito baixo): 50 km com 25L = 2.0 km/L (< 4.0)
        _, motivos_pos1 = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50050.000'),
            litros=Decimal('25.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertIn("CONSUMO_FORA_DA_FAIXA", motivos_pos1)

        # Positivo 2 (Consumo anormalmente baixo / km/L muito alto): 200 km com 10L = 20.0 km/L (> 6.0)
        _, motivos_pos2 = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50200.000'),
            litros=Decimal('10.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertIn("CONSUMO_FORA_DA_FAIXA", motivos_pos2)

        # Negativo (Dentro da faixa): 100 km com 20L = 5.0 km/L
        _, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('20.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertNotIn("CONSUMO_FORA_DA_FAIXA", motivos_neg)

    def test_anomalia_preco_fora_da_faixa_positivo_e_negativo(self):
        # Preço ref ANP = R$ 6.00. Tolerância = 15% -> Faixa válida: [5.10, 6.90]
        # Positivo: R$ 8.00 / L
        _, motivos_pos = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('30.000'),
            preco_litro=Decimal('8.00'),
            tem_foto=True,
            uf_posto="SP"
        )
        self.assertIn("PRECO_FORA_DA_FAIXA", motivos_pos)

        # Negativo: R$ 6.20 / L
        _, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('30.000'),
            preco_litro=Decimal('6.20'),
            tem_foto=True,
            uf_posto="SP"
        )
        self.assertNotIn("PRECO_FORA_DA_FAIXA", motivos_neg)

    def test_anomalia_duplicidade_positivo_e_negativo(self):
        agora = timezone.now()
        # Cria pré-lançamento 10 minutos atrás
        PreLancamentoDespesaCampo.objects.create(
            tenant=self.tenant,
            tipo="ABASTECIMENTO",
            veiculo=self.veiculo,
            motorista=self.motorista,
            data_hora=agora - timedelta(minutes=10),
            valor_informado=Decimal('100.00'),
            forma_pagamento="CARTAO_FROTA"
        )

        # Positivo: novo lançamento dentro da janela de 60 minutos
        _, motivos_pos = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=agora,
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('20.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertIn("DUPLICIDADE", motivos_pos)

        # Negativo: data_hora com 3 horas de diferença
        _, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=agora + timedelta(hours=3),
            odometro_informado=Decimal('50200.000'),
            litros=Decimal('20.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertNotIn("DUPLICIDADE", motivos_neg)

    def test_anomalia_sem_foto_positivo_e_negativo(self):
        # Positivo: sem foto
        _, motivos_pos = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('20.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=False
        )
        self.assertIn("SEM_FOTO", motivos_pos)

        # Negativo: com foto
        _, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('20.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertNotIn("SEM_FOTO", motivos_neg)

    def test_anomalia_local_distante_da_rota_positivo_e_negativo(self):
        # Entrega programada no centro de São Paulo (-23.5505, -46.6333)
        entrega = Entrega.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            motorista=self.motorista,
            status='Em Rota'
        )
        CoordenadaRastreamento.objects.create(
            entrega=entrega,
            latitude=Decimal('-23.5505000'),
            longitude=Decimal('-46.6333000')
        )

        # Positivo: abastecimento no Rio de Janeiro (-22.9068, -43.1729) ~350 km de distância (> 15 km)
        _, motivos_pos = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            entrega=entrega,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('20.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True,
            latitude_despesa=Decimal('-22.9068000'),
            longitude_despesa=Decimal('-43.1729000')
        )
        self.assertIn("LOCAL_DISTANTE_DA_ROTA", motivos_pos)

        # Negativo: abastecimento a 500 metros do destino (-23.5510, -46.6340)
        _, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=self.veiculo,
            entrega=entrega,
            data_hora=timezone.now(),
            odometro_informado=Decimal('50100.000'),
            litros=Decimal('20.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True,
            latitude_despesa=Decimal('-23.5510000'),
            longitude_despesa=Decimal('-46.6340000')
        )
        self.assertNotIn("LOCAL_DISTANTE_DA_ROTA", motivos_neg)

    def test_anomalia_primeiro_registro_positivo_e_negativo(self):
        # Veículo novo sem leituras anteriores
        v_novo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="NEW0001",
            modelo="VW Delivery",
            marca="Volkswagen",
            ano=2023,
            capacidade_carga=Decimal('4000.00'),
            capacidade_tanque_litros=Decimal('80.000'),
            consumo_referencia_kml=Decimal('4.500'),
            tipo_combustivel="DIESEL"
        )
        # Positivo: Primeiro registro marca PRIMEIRO_REGISTRO e não calcula consumo
        _, motivos_pos = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=v_novo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('100.000'),
            litros=Decimal('40.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertIn("PRIMEIRO_REGISTRO", motivos_pos)
        self.assertNotIn("CONSUMO_FORA_DA_FAIXA", motivos_pos)

        # Adiciona leitura validada
        LeituraOdometro.objects.create(
            veiculo=v_novo,
            km=Decimal('100.000'),
            data_hora=timezone.now() - timedelta(hours=1),
            origem="ABASTECIMENTO",
            validada=True
        )
        # Negativo: segundo registro não é primeiro registro
        _, motivos_neg = analisar_despesa_campo(
            tenant=self.tenant,
            veiculo=v_novo,
            data_hora=timezone.now(),
            odometro_informado=Decimal('150.000'),
            litros=Decimal('11.000'),
            preco_litro=Decimal('6.00'),
            tem_foto=True
        )
        self.assertNotIn("PRIMEIRO_REGISTRO", motivos_neg)


class TestDespesasCampoServicesEIdempotencia(BaseSprint9CTestCase):
    """Testes de criação, idempotência e aprovação de despesas de campo."""

    def test_reenvio_mesmo_client_uuid_nao_duplica(self):
        c_uuid = uuid.uuid4()
        # Primeiro envio
        d1 = criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="PEDAGIO",
            veiculo_id=self.veiculo.id,
            motorista_id=self.motorista.id,
            data_hora=timezone.now(),
            valor_informado=Decimal('35.50'),
            forma_pagamento="CARTAO_FROTA",
            client_uuid=c_uuid
        )

        # Segundo envio com mesmo client_uuid
        d2 = criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="PEDAGIO",
            veiculo_id=self.veiculo.id,
            motorista_id=self.motorista.id,
            data_hora=timezone.now(),
            valor_informado=Decimal('35.50'),
            forma_pagamento="CARTAO_FROTA",
            client_uuid=c_uuid
        )

        self.assertEqual(d1.id, d2.id)
        self.assertEqual(PreLancamentoDespesaCampo.objects.filter(client_uuid=c_uuid).count(), 1)

    def test_aprovador_igual_ao_autor_eh_rejeitado(self):
        despesa = criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="ABASTECIMENTO",
            veiculo_id=self.veiculo.id,
            motorista_id=self.motorista.id,
            data_hora=timezone.now(),
            valor_informado=Decimal('200.00'),
            forma_pagamento="CARTAO_FROTA"
        )

        # O próprio motorista tentando aprovar sua despesa deve falhar
        with self.assertRaises(ValidationError) as ctx:
            aprovar_despesa_campo(self.tenant, despesa.id, self.motorista)
        self.assertIn("Segregação de funções violada", str(ctx.exception))

        # Rejeitar também deve exigir segregação
        with self.assertRaises(ValidationError) as ctx:
            rejeitar_despesa_campo(self.tenant, despesa.id, self.motorista, "Motivo")
        self.assertIn("Segregação de funções violada", str(ctx.exception))

        # Aprovador diferente (gestor) aprova com sucesso
        despesa_ok = aprovar_despesa_campo(self.tenant, despesa.id, self.gestor)
        self.assertEqual(despesa_ok.status, "APROVADO")
        self.assertEqual(despesa_ok.aprovado_por, self.gestor)

    def test_pagamento_dinheiro_rota_sem_titulo_com_lancamento_direto(self):
        # Pré-lançamento em DINHEIRO_ROTA
        despesa = criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="MANUTENCAO_EMERGENCIAL",
            veiculo_id=self.veiculo.id,
            motorista_id=self.motorista.id,
            data_hora=timezone.now(),
            valor_informado=Decimal('150.00'),
            forma_pagamento="DINHEIRO_ROTA"
        )

        titulos_antes = TituloFinanceiro.objects.count()
        lancamentos_antes = LancamentoContabil.objects.count()

        # Aprovação da despesa
        aprovar_despesa_campo(self.tenant, despesa.id, self.gestor)

        # Regra 7: após aprovação, lançamento direto sem gerar TituloFinanceiro
        self.assertEqual(TituloFinanceiro.objects.count(), titulos_antes)
        self.assertEqual(LancamentoContabil.objects.count(), lancamentos_antes + 1)

        ultimo_lanc = LancamentoContabil.objects.order_by('-id').first()
        partidas = list(ultimo_lanc.partidas.all())
        # Débito Despesa (5.1) e Crédito Caixa de Rota (1.1.1.03)
        debitos = [p for p in partidas if p.tipo == 'D']
        creditos = [p for p in partidas if p.tipo == 'C']
        self.assertEqual(len(debitos), 1)
        self.assertEqual(len(creditos), 1)
        self.assertEqual(debitos[0].conta_contabil.codigo_estrutural, '5.1')
        self.assertEqual(creditos[0].conta_contabil.codigo_estrutural, '1.1.1.03')
        self.assertEqual(debitos[0].valor, Decimal('150.00'))


class TestFaturaPostoConsolidada(BaseSprint9CTestCase):
    """Testes de importação, conciliação e desdobramento contábil por competência."""

    def test_fatura_que_cruza_meses_gera_dois_titulos_com_valores_corretos(self):
        csv_conteudo = (
            "placa;cartao_numero;data_hora;combustivel;litros;valor_total;posto_nome;posto_cnpj\n"
            "ABC1D23;CARD-01;2026-03-29 14:30:00;DIESEL;50.000;300.00;Posto Alvorada;11.222.333/0001-44\n"
            "ABC1D23;CARD-01;2026-04-02 09:15:00;DIESEL;70.000;420.00;Posto Estrela;22.333.444/0001-55\n"
        )

        fatura = importar_fatura_csv(
            tenant=self.tenant,
            cartao_ou_convenio="CARTAO_FROTA_ALFA",
            csv_content=csv_conteudo,
            usuario=self.gestor,
            numero_fatura="FAT-2026-001"
        )

        self.assertEqual(fatura.valor_total, Decimal('720.00'))
        self.assertEqual(fatura.itens.count(), 2)

        # Conciliação
        conciliar_itens_fatura(self.tenant, fatura.id)

        # Aprovação da fatura
        titulos = aprovar_fatura_posto(self.tenant, fatura.id, self.gestor)

        # Deve gerar 2 títulos: 1 para Março (R$ 300.00) e 1 para Abril (R$ 420.00)
        self.assertEqual(len(titulos), 2)

        titulos_mar = [t for t in titulos if t.data_emissao.month == 3]
        titulos_abr = [t for t in titulos if t.data_emissao.month == 4]
        self.assertEqual(len(titulos_mar), 1)
        self.assertEqual(len(titulos_abr), 1)

        t_mar = titulos_mar[0]
        t_abr = titulos_abr[0]

        self.assertEqual(t_mar.valor_total, Decimal('300.00'))
        self.assertEqual(t_abr.valor_total, Decimal('420.00'))

        # Ambos devem ter origem_tipo = FATURA_POSTO e rateio em CC-02
        self.assertEqual(t_mar.origem_tipo, "FATURA_POSTO")
        self.assertEqual(t_abr.origem_tipo, "FATURA_POSTO")

        rateio_mar = t_mar.rateios_centros_custo.first()
        self.assertIsNotNone(rateio_mar)
        self.assertEqual(rateio_mar.centro_custo.codigo, "CC-02")
        self.assertEqual(rateio_mar.valor, Decimal('300.00'))


class TestCaixaRotaEContagemCega(BaseSprint9CTestCase):
    """Testes de fechamento de caixa de rota e sigilo da contagem cega."""

    def test_tela_fechamento_nao_expoe_saldo_esperado_antes_da_contagem(self):
        hoje = timezone.localdate()
        fechamento = obter_ou_criar_fechamento_caixa(
            tenant=self.tenant,
            motorista_id=self.motorista.id,
            data_fechamento=hoje,
            conta_caixa_id=self.caixa_rota.id
        )
        self.assertIsNone(fechamento.valor_contado_cego)

        # 1. Teste de API DRF
        res_api = self.client_motorista.get(f"/financeiro/api/fechamentos-caixa/{fechamento.id}/")
        self.assertEqual(res_api.status_code, status.HTTP_200_OK)
        # saldo_esperado e diferenca DEVEM ser None
        self.assertIsNone(res_api.data['saldo_esperado'])
        self.assertIsNone(res_api.data['diferenca'])

        # 2. Teste de Template HTML
        self.client_motorista.login(username=self.motorista.username, password="secret_password")
        res_tpl = self.client_motorista.get(f"/financeiro/fechamento-caixa/{fechamento.id}/")
        self.assertEqual(res_tpl.status_code, 200)
        html = res_tpl.content.decode('utf-8')

        # O HTML NÃO deve conter o id de exibição do saldo esperado
        self.assertNotIn('id="saldo-esperado-valor"', html)
        self.assertIn('id="painel-sigilo-contagem"', html)
        self.assertIn('Contagem Cega Obrigatória', html)

        # Agora realiza a contagem cega via API
        res_contagem = self.client_motorista.post(
            f"/financeiro/api/fechamentos-caixa/{fechamento.id}/contagem-cega/",
            {"valor_contado_cego": "350.00"}
        )
        self.assertEqual(res_contagem.status_code, status.HTTP_200_OK)

        # Agora a API expõe o saldo_esperado e a diferença
        res_api_pos = self.client_motorista.get(f"/financeiro/api/fechamentos-caixa/{fechamento.id}/")
        self.assertIsNotNone(res_api_pos.data['saldo_esperado'])
        self.assertIsNotNone(res_api_pos.data['diferenca'])

        # E o template passa a exibir o painel de apuração
        res_tpl_pos = self.client_motorista.get(f"/financeiro/fechamento-caixa/{fechamento.id}/")
        html_pos = res_tpl_pos.content.decode('utf-8')
        self.assertIn('id="saldo-esperado-valor"', html_pos)
        self.assertIn('R$ 350.00', html_pos)

    def test_fechamento_caixa_apuracao_diferenca_quebra_caixa_e_transferencia(self):
        hoje = timezone.localdate()
        fechamento = obter_ou_criar_fechamento_caixa(
            tenant=self.tenant,
            motorista_id=self.motorista.id,
            data_fechamento=hoje,
            conta_caixa_id=self.caixa_rota.id
        )
        # Simula saldo esperado = 500.00 (manual para teste isolado)
        fechamento.saldo_esperado = Decimal('500.00')
        fechamento.save(update_fields=['saldo_esperado'])

        # Motorista conta 480.00 (diferença -20.00, acima da tolerância de R$ 5.00)
        registrar_contagem_cega(self.tenant, fechamento.id, Decimal('480.00'))

        # Segregação de funções: motorista não pode conferir/fechar
        with self.assertRaises(ValidationError) as ctx:
            conferir_e_fechar_caixa(
                tenant=self.tenant,
                fechamento_id=fechamento.id,
                conferente=self.motorista,
                valor_entregue_tesouraria=Decimal('480.00'),
                conta_cofre_id=self.caixa_cofre.id
            )
        self.assertIn("Segregação de funções violada", str(ctx.exception))

        # Gestor confere e fecha
        fechado = conferir_e_fechar_caixa(
            tenant=self.tenant,
            fechamento_id=fechamento.id,
            conferente=self.gestor,
            valor_entregue_tesouraria=Decimal('480.00'),
            conta_cofre_id=self.caixa_cofre.id
        )

        self.assertEqual(fechado.status, "FECHADO")
        self.assertEqual(fechado.diferenca, Decimal('-20.00'))

        # Quebra de caixa registrada
        quebra = QuebraCaixa.objects.filter(fechamento=fechamento).first()
        self.assertIsNotNone(quebra)
        self.assertEqual(quebra.valor, Decimal('20.00'))
        self.assertEqual(quebra.tipo, "FALTA")

        # Transferência para o cofre gerada
        self.assertIsNotNone(fechado.transferencia)
        self.assertEqual(fechado.transferencia.valor, Decimal('480.00'))
        self.assertEqual(fechado.transferencia.tipo, "SAIDA")


class TestMultiTenantEADR(BaseSprint9CTestCase):
    """Testes de isolamento multi-tenant (404) e ADR-040 de versionamento IndexedDB."""

    def test_multi_tenant_404_despesa_fatura_fechamento(self):
        # Cria registros no Tenant A
        despesa_a = PreLancamentoDespesaCampo.objects.create(
            tenant=self.tenant,
            tipo="PEDAGIO",
            veiculo=self.veiculo,
            motorista=self.motorista,
            data_hora=timezone.now(),
            valor_informado=Decimal('50.00'),
            forma_pagamento="CARTAO_FROTA"
        )

        fornecedor_a = Fornecedor.objects.create(
            tenant=self.tenant,
            razao_social="Posto A Ltda",
            documento="11.222.333/0001-44"
        )
        fatura_a = FaturaConsolidadaPosto.objects.create(
            tenant=self.tenant,
            fornecedor=fornecedor_a,
            numero_fatura="FAT-A-001",
            data_emissao=timezone.localdate(),
            data_vencimento=timezone.localdate() + timedelta(days=15),
            valor_total=Decimal('100.00')
        )

        fechamento_a = FechamentoCaixaRota.objects.create(
            tenant=self.tenant,
            conta_caixa=self.caixa_rota,
            motorista=self.motorista,
            data=timezone.localdate()
        )

        # Usuário do Tenant B tentando acessar recursos do Tenant A deve receber 404
        r1 = self.client_b.get(f"/financeiro/api/despesas-campo/{despesa_a.id}/")
        self.assertEqual(r1.status_code, status.HTTP_404_NOT_FOUND)

        r2 = self.client_b.get(f"/financeiro/api/faturas-posto/{fatura_a.id}/")
        self.assertEqual(r2.status_code, status.HTTP_404_NOT_FOUND)

        r3 = self.client_b.get(f"/financeiro/api/fechamentos-caixa/{fechamento_a.id}/")
        self.assertEqual(r3.status_code, status.HTTP_404_NOT_FOUND)

    def test_relatorios_consumo_ranking_anomalias_quebras(self):
        # Registra leituras para apurar consumo
        LeituraOdometro.objects.create(
            veiculo=self.veiculo,
            km=Decimal('50000.000'),
            data_hora=timezone.now() - timedelta(days=2),
            origem="ROTA",
            validada=True
        )
        LeituraOdometro.objects.create(
            veiculo=self.veiculo,
            km=Decimal('50500.000'),
            data_hora=timezone.now() - timedelta(days=1),
            origem="ROTA",
            validada=True
        )
        PreLancamentoDespesaCampo.objects.create(
            tenant=self.tenant,
            tipo="ABASTECIMENTO",
            veiculo=self.veiculo,
            motorista=self.motorista,
            data_hora=timezone.now() - timedelta(days=1),
            litros=Decimal('100.000'),
            valor_informado=Decimal('600.00'),
            forma_pagamento="CARTAO_FROTA",
            status="APROVADO",
            alerta_auditoria=True,
            motivos_alerta_json=["PRECO_FORA_DA_FAIXA"]
        )

        dados_consumo = relatorio_consumo_veiculos(tenant=self.tenant)
        self.assertGreaterEqual(len(dados_consumo), 1)
        item_v = next(x for x in dados_consumo if x['veiculo_id'] == self.veiculo.id)
        self.assertEqual(item_v['km_rodados'], Decimal('500.000'))
        self.assertEqual(item_v['litros_consumidos'], Decimal('100.000'))
        self.assertEqual(item_v['km_por_litro_real'], Decimal('5.000'))

        ranking = ranking_motoristas_anomalias(tenant=self.tenant)
        self.assertGreaterEqual(len(ranking), 1)
        item_m = next(x for x in ranking if x['motorista_id'] == self.motorista.id)
        self.assertEqual(item_m['total_alertas'], 1)

    def test_validacao_adr040_versionamento_indexeddb(self):
        """Valida que o ADR-040 existe e que offline_sync.js possui DB_VERSION = 8."""
        adr_path = os.path.join("docs", "adr", "ADR-040-indexeddb-versioning.md")
        self.assertTrue(os.path.exists(adr_path), "ADR-040 não encontrado.")

        with open(adr_path, "r", encoding="utf-8") as f:
            adr_content = f.read()
            self.assertIn("DB_VERSION", adr_content)
            self.assertIn("8", adr_content)
            self.assertIn("despesas_pendentes", adr_content)

        js_path = os.path.join("static", "js", "offline_sync.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()
            self.assertIn("DB_VERSION = 8", js_content)
            self.assertIn("despesas_pendentes", js_content)
            self.assertIn("enfileirarDespesaCampo", js_content)

    def test_servicos_cobertura_adicional(self):
        """Testes adicionais para garantir >= 85% de cobertura nos 3 services."""
        # 1. despesas_campo: Rejeição formal com motivo e validações
        d_rej = criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="OUTRO",
            veiculo=self.veiculo,
            motorista=self.motorista,
            valor_informado=Decimal('45.00')
        )
        with self.assertRaises(ValidationError):
            rejeitar_despesa_campo(self.tenant, d_rej.id, self.gestor, "")

        d_rejeitada = rejeitar_despesa_campo(self.tenant, d_rej.id, self.gestor, "Cupom ilegível")
        self.assertEqual(d_rejeitada.status, "REJEITADO")
        self.assertEqual(d_rejeitada.motivo_rejeicao, "Cupom ilegível")

        # Tentativa de aprovar despesa já rejeitada
        with self.assertRaises(ValidationError):
            aprovar_despesa_campo(self.tenant, d_rejeitada.id, self.gestor)

        # Aprovação em lote com abastecimento criando LeituraOdometro
        d_abast1 = criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="ABASTECIMENTO",
            veiculo=self.veiculo,
            motorista=self.motorista,
            valor_informado=Decimal('100.00'),
            litros=Decimal('20.000'),
            odometro_informado=Decimal('50300.000'),
            forma_pagamento="CARTAO_FROTA"
        )
        d_pedag = criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="PEDAGIO",
            veiculo=self.veiculo,
            motorista=self.motorista,
            valor_informado=Decimal('20.00'),
            forma_pagamento="CARTAO_FROTA"
        )
        lote = aprovar_despesas_campo_em_lote(self.tenant, [d_abast1.id, d_pedag.id], self.gestor)
        self.assertEqual(len(lote), 2)
        self.assertTrue(LeituraOdometro.objects.filter(km=Decimal('50300.000')).exists())

        # Validação valor <= 0
        with self.assertRaises(ValidationError):
            criar_pre_lancamento_despesa(
                tenant=self.tenant,
                tipo="PEDAGIO",
                veiculo=self.veiculo,
                motorista=self.motorista,
                valor_informado=Decimal('0.00')
            )

        # 2. caixa_rota: Cheque recebido, sobra de caixa e validações de valores negativos
        fech = obter_ou_criar_fechamento_caixa(
            tenant=self.tenant,
            motorista=self.motorista,
            data=timezone.localdate()
        )
        chq = registrar_cheque_recebido(
            tenant=self.tenant,
            fechamento_id=fech.id,
            numero="123456",
            banco="001",
            valor=Decimal('500.00'),
            bom_para=timezone.localdate() + timedelta(days=30)
        )
        self.assertEqual(chq.numero, "123456")
        self.assertEqual(fech.cheques.count(), 1)

        # Validações de contagem negativa
        with self.assertRaises(ValidationError):
            registrar_contagem_cega(tenant=self.tenant, fechamento_id=fech.id, valor_contado_cego=Decimal('-10.00'))

        # Sobra de caixa (Contado = 100.00 > Esperado = 0.00)
        fech.saldo_esperado = Decimal('0.00')
        fech.save(update_fields=['saldo_esperado'])
        registrar_contagem_cega(tenant=self.tenant, fechamento_id=fech.id, valor_contado_cego=Decimal('100.00'))

        # Validação de entrega tesouraria negativa
        with self.assertRaises(ValidationError):
            conferir_e_fechar_caixa(
                tenant=self.tenant,
                fechamento_id=fech.id,
                conferente=self.gestor,
                valor_entregue_tesouraria=Decimal('-5.00')
            )

        fech_sobra = conferir_e_fechar_caixa(
            tenant=self.tenant,
            fechamento_id=fech.id,
            conferente=self.gestor,
            valor_entregue_tesouraria=Decimal('100.00')
        )
        self.assertEqual(fech_sobra.status, "FECHADO")
        self.assertEqual(fech_sobra.diferenca, Decimal('100.00'))
        q_sobra = QuebraCaixa.objects.filter(fechamento=fech_sobra).first()
        self.assertEqual(q_sobra.tipo, "SOBRA")

        # Relatório de quebras de caixa
        rep_quebras = relatorio_quebras_caixa(tenant=self.tenant)
        self.assertGreaterEqual(len(rep_quebras), 1)

        # 3. fatura_posto: Tentativa de reaprovação de fatura já aprovada
        forn = Fornecedor.objects.create(
            tenant=self.tenant,
            razao_social="Posto Frota Beta",
            documento="33.444.555/0001-66"
        )
        fat_csv = (
            "placa;cartao_numero;data_hora;combustivel;litros;valor_total;posto_nome;posto_cnpj\n"
            "ABC1D23;CARD-02;2026-05-10 10:00:00;DIESEL;40.000;240.00;Posto Beta;33.444.555/0001-66\n"
        )
        fat2 = importar_fatura_csv(
            tenant=self.tenant,
            fornecedor=forn,
            numero_fatura="FAT-2026-BETA",
            csv_content=fat_csv,
            usuario=self.gestor
        )
        from datetime import datetime
        dt_abast = timezone.make_aware(datetime(2026, 5, 10, 10, 0, 0))
        criar_pre_lancamento_despesa(
            tenant=self.tenant,
            tipo="ABASTECIMENTO",
            veiculo=self.veiculo,
            motorista=self.motorista,
            data_hora=dt_abast,
            valor_informado=Decimal('240.00'),
            litros=Decimal('40.000'),
            forma_pagamento="CARTAO_FROTA"
        )
        conc_res = conciliar_itens_fatura(self.tenant, fat2.id)
        self.assertEqual(conc_res['casados'], 1)

        aprovar_fatura_posto(self.tenant, fat2.id, self.gestor)
        with self.assertRaises(ValidationError):
            aprovar_fatura_posto(self.tenant, fat2.id, self.gestor)
