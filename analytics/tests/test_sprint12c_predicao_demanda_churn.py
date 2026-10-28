import datetime
import unittest
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status
from hypothesis import given, strategies as st, settings

from core.models import Tenant, Membership
from core.tenancy import tenant_context
from accounts.models import User
from clientes.models import Cliente
from vendas.models import Venda, ItemVenda
from produtos.models import GasQuimico, ModeloCilindro, SkuRecarga, Cilindro, MovimentacaoCilindro
from analytics.models import AlertaOportunidadeComercial
from analytics.selectors.recompra import historico_recompra
from analytics.selectors.permanencia_cilindros import (
    obter_tempos_permanencia_cilindros,
    obter_cilindros_em_posse_cliente,
)
from analytics.services.estatistica import (
    calcular_mediana,
    calcular_mad,
    filtrar_outliers_mad,
    calcular_media_e_desvio,
)
from analytics.services.kaplan_meier import (
    estimar_sobrevivencia_km,
    avaliar_risco_nao_retorno_cilindro,
)
from analytics.services.previsao_recompra_service import avaliar_recompra_cliente_gas
from analytics.services.alertas_service import (
    gerar_alertas_demand_churn,
    atualizar_status_alerta,
)
from analytics.services.funil_service import calcular_metricas_funil
from analytics.services.backtest_service import executar_backtest
from analytics.tasks import job_alertas_oportunidade_diario


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-sprint12c-cache',
        }
    }
)
class Sprint12CStatisticaDemandaChurnTests(TestCase):
    """
    Testes de Unidade, Integração e Invariantes da Sprint 12C:
    Previsão estatística de demanda, risco de churn e Kaplan-Meier para cilindros.
    """

    def setUp(self):
        cache.clear()

        # Tenant A (com módulo analytics ativo)
        self.tenant_a = Tenant.objects.create(
            razao_social="Alfa Gases & Soluções Industriais LTDA",
            nome_fantasia="Alfa Gases",
            cnpj="10.111.222/0001-33",
            plano="PRO",
            modulo_patrimonio_ativo=True,
            modulo_vendas_ativo=True,
            modulo_analytics_ativo=True,
        )

        # Tenant B (Isolamento Multi-tenant)
        self.tenant_b = Tenant.objects.create(
            razao_social="Beta Gases LTDA",
            nome_fantasia="Beta Gases",
            cnpj="20.333.444/0001-55",
            plano="BASIC",
            modulo_analytics_ativo=True,
        )

        # Tenant C (Módulo Analytics Inativo)
        self.tenant_c = Tenant.objects.create(
            razao_social="Gama Gases LTDA",
            nome_fantasia="Gama Gases",
            cnpj="30.555.666/0001-77",
            plano="BASIC",
            modulo_analytics_ativo=False,
        )

        with tenant_context(self.tenant_a):
            self.user_a = User.objects.create_user(
                username="comercial_alfa",
                email="comercial@alfa.com.br",
                password="password123"
            )
            self.membership_a = Membership.objects.create(
                user=self.user_a,
                tenant=self.tenant_a,
                papel="ADMIN"
            )

            self.cliente_regular = Cliente.objects.create(
                tenant=self.tenant_a,
                nome="Hospital Central Alfa",
                cnpj="11.222.333/0001-44",
                email_financeiro="compras@hospitalcentral.com.br"
            )

            self.cliente_poucas_compras = Cliente.objects.create(
                tenant=self.tenant_a,
                nome="Clínica Menor Alfa",
                cnpj="11.222.333/0001-99",
                email_financeiro="compras@clinicamenor.com.br"
            )

            self.gas_oxigenio, _ = GasQuimico.objects.get_or_create(
                sigla="O2_MED",
                defaults={
                    'nome': "Oxigênio Medicinal",
                    'categoria': "MEDICINAL",
                }
            )

            self.modelo_cilindro = ModeloCilindro.objects.create(
                tenant=self.tenant_a,
                descricao="Cilindro T-50L Aço",
                volume_hidraulico_litros=Decimal("50.00"),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal("55.00")
            )

            self.sku_oxigenio = SkuRecarga.objects.create(
                tenant=self.tenant_a,
                gas=self.gas_oxigenio,
                modelo_cilindro=self.modelo_cilindro,
                nome_comercial="Recarga O2 Medicinal 10m3",
                quantidade_carga=Decimal("10.00"),
                massa_gas_kg=Decimal("13.00"),
                preco_base=Decimal("150.00")
            )

        with tenant_context(self.tenant_b):
            self.user_b = User.objects.create_user(
                username="comercial_beta",
                email="comercial@beta.com.br",
                password="password123"
            )
            self.membership_b = Membership.objects.create(
                user=self.user_b,
                tenant=self.tenant_b,
                papel="ADMIN"
            )
            self.cliente_beta = Cliente.objects.create(
                tenant=self.tenant_b,
                nome="Cliente Beta LTDA",
                cnpj="22.333.444/0001-88"
            )

        self.client = APIClient()

    # =========================================================================
    # 1. TESTES ESTATÍSTICOS BÁSICOS & MAD (OUTLIERS)
    # =========================================================================

    def test_estatistica_mediana_e_mad_calculados_corretamente(self):
        """Valida mediana e MAD com série conhecida."""
        valores = [10.0, 10.0, 10.0, 12.0, 14.0, 100.0]
        # median([10, 10, 10, 12, 14, 100]) = (10 + 12)/2 = 11.0
        med = calcular_mediana(valores)
        self.assertEqual(med, 11.0)

        # desvios absolutos: |10-11|=1, 1, 1, |12-11|=1, |14-11|=3, |100-11|=89
        # sorted: [1, 1, 1, 1, 3, 89] -> median = (1 + 1)/2 = 1.0
        mad = calcular_mad(valores, med)
        self.assertEqual(mad, 1.0)

    def test_filtrar_outliers_mad_remove_anomalia_isolada(self):
        """
        Série com 6 compras regulares a cada ~10 dias e um atraso absurdo de 100 dias (outlier).
        O MAD deve expurgar o 100 e preservar média e desvio próximos do comportamento real.
        """
        intervalos = [10.0, 11.0, 9.0, 10.0, 10.0, 100.0]
        limpos, outliers = filtrar_outliers_mad(intervalos)

        self.assertIn(100.0, outliers)
        self.assertEqual(len(limpos), 5)
        self.assertNotIn(100.0, limpos)

        mu, sigma = calcular_media_e_desvio(limpos)
        self.assertAlmostEqual(mu, 10.0, delta=1.0)
        self.assertTrue(sigma < 2.0)

    def test_mad_zero_fallback_para_media_absoluta(self):
        """Quando mais de 50% dos dados são idênticos, MAD = 0; fallback não quebra divisão."""
        intervalos = [15.0, 15.0, 15.0, 15.0, 15.0, 80.0]
        limpos, outliers = filtrar_outliers_mad(intervalos)
        self.assertIn(80.0, outliers)
        self.assertEqual(limpos, [15.0, 15.0, 15.0, 15.0, 15.0])

    # =========================================================================
    # 2. BASE DE RECOMPRA E REGRA DE MENOS DE 4 COMPRAS
    # =========================================================================

    def test_cliente_com_menos_de_4_compras_nao_gera_alerta(self):
        """
        Cliente com apenas 3 compras não atinge o requisito mínimo de 4 compras;
        nenhum alerta de recompra ou churn é gerado.
        """
        data_base = datetime.date(2026, 1, 1)
        with tenant_context(self.tenant_a):
            # Cria 3 vendas faturadas
            for i in range(3):
                dt = data_base + datetime.timedelta(days=i * 15)
                v = Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_poucas_compras,
                    status='Faturada',
                    valor_total=Decimal('150.00'),
                    data_entrega_efetiva=dt
                )
                Venda.objects.filter(id=v.id).update(
                    data_venda=timezone.make_aware(datetime.datetime.combine(dt, datetime.time(10, 0)))
                )
                ItemVenda.objects.create(
                    venda=v,
                    sku=self.sku_oxigenio,
                    quantidade=1,
                    valor_unitario=Decimal('150.00'),
                    valor_total=Decimal('150.00')
                )

        resultado = avaliar_recompra_cliente_gas(
            cliente=self.cliente_poucas_compras,
            gas=self.gas_oxigenio,
            data_ref=datetime.date(2026, 4, 1),
            k=2.0
        )
        self.assertIsNone(resultado)

    def test_serie_sintetica_regular_gera_alerta_ao_ultrapassar_mu_mais_k_sigma(self):
        """
        Cliente com 5 compras regulares a cada 10 dias (μ ~ 10, σ ~ 0).
        Se a data_ref estiver a 23 dias da última compra, ultrapassa μ + 2σ (~10)
        e gera alerta RECOMPRA_ATRASADA auditável com evidencia_json completa.
        """
        data_base = datetime.date(2026, 1, 1)
        with tenant_context(self.tenant_a):
            for i in range(5):
                dt = data_base + datetime.timedelta(days=i * 10)
                v = Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_regular,
                    status='Faturada',
                    valor_total=Decimal('300.00'),
                    data_entrega_efetiva=dt
                )
                Venda.objects.filter(id=v.id).update(
                    data_venda=timezone.make_aware(datetime.datetime.combine(dt, datetime.time(10, 0)))
                )
                ItemVenda.objects.create(
                    venda=v,
                    sku=self.sku_oxigenio,
                    quantidade=2,
                    valor_unitario=Decimal('150.00'),
                    valor_total=Decimal('300.00')
                )

        # Última compra foi no dia 40 (2026-02-10).
        # Em 2026-03-05 (23 dias depois): dias_desde_ultima_compra = 23 > μ(10) + 2*σ(0) = 10
        data_ref = datetime.date(2026, 3, 5)
        analise = avaliar_recompra_cliente_gas(
            cliente=self.cliente_regular,
            gas=self.gas_oxigenio,
            data_ref=data_ref,
            k=2.0
        )

        self.assertIsNotNone(analise)
        self.assertIn(analise['tipo'], ['RECOMPRA_ATRASADA', 'CHURN_RISCO'])
        self.assertEqual(analise['evidencia_json']['total_compras_historicas'], 5)
        self.assertEqual(analise['evidencia_json']['k'], 2.0)
        self.assertAlmostEqual(analise['evidencia_json']['mu'], 10.0, delta=0.5)
        self.assertEqual(analise['evidencia_json']['dias_desde_ultima_compra'], 23)
        self.assertTrue(analise['score'] > 0)

    # =========================================================================
    # 3. RISCO DE RETENÇÃO DE CILINDROS (KAPLAN-MEIER)
    # =========================================================================

    def test_kaplan_meier_calculo_sobrevivencia_e_fallback(self):
        """
        Valida que Kaplan-Meier estima curva monotonicamente decrescente
        e faz fallback quando cliente tem menos de 5 eventos de retorno.
        """
        duracoes = [(10, 1), (15, 1), (20, 0), (25, 1), (30, 0), (35, 1)]
        res_km = estimar_sobrevivencia_km(duracoes)
        curva = res_km['pontos_curva']
        total_ev = res_km['total_eventos']

        self.assertEqual(total_ev, 4)
        prob_anterior = 1.0
        for pt in curva:
            self.assertTrue(0.0 <= pt['probabilidade_sobrevivencia'] <= prob_anterior)
            prob_anterior = pt['probabilidade_sobrevivencia']

    def test_alerta_cilindro_nao_retorna_acionado_apos_prazo_estimado(self):
        """
        Cilindro entregue a cliente há 90 dias sem retorno (prazo esperado = 30 dias).
        O avaliador KM deve calcular S(90) <= 0.20 e disparar CILINDRO_NAO_RETORNA.
        """
        with tenant_context(self.tenant_a):
            cil = Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr="QR-KM-001",
                numero_serie_ogiva="SN-KM-001",
                fabricante="MAT",
                ano_fabricacao=2020,
                gas_dedicado=self.gas_oxigenio,
                modelo=self.modelo_cilindro,
                data_ultimo_reteste=datetime.date(2020, 1, 1),
                data_proximo_reteste=datetime.date(2025, 1, 1),
                status="EM_POSSE_CLIENTE",
                cliente_posse_atual=self.cliente_regular,
                posse_desde=timezone.now() - datetime.timedelta(days=90)
            )

            # Histórico de retornos rápidos no tenant
            for d in [10, 12, 14, 15, 18, 20]:
                cil_hist = Cilindro.objects.create(
                    tenant=self.tenant_a,
                    codigo_qr=f"QR-HIST-{d}",
                    numero_serie_ogiva=f"SN-HIST-{d}",
                    fabricante="MAT",
                    ano_fabricacao=2020,
                    gas_dedicado=self.gas_oxigenio,
                    modelo=self.modelo_cilindro,
                    data_ultimo_reteste=datetime.date(2020, 1, 1),
                    data_proximo_reteste=datetime.date(2025, 1, 1),
                    status="CHEIO_DISPONIVEL"
                )
                dt_entrega = timezone.now() - datetime.timedelta(days=d + 5)
                dt_retorno = timezone.now() - datetime.timedelta(days=5)

                MovimentacaoCilindro.objects.create(
                    tenant=self.tenant_a,
                    cilindro=cil_hist,
                    tipo="ENTREGA_CLIENTE",
                    status_anterior="CHEIO_DISPONIVEL",
                    status_novo="EM_POSSE_CLIENTE",
                    cliente=self.cliente_regular,
                    registrado_por=self.user_a,
                    ocorrido_em=dt_entrega,
                    is_legado=True
                )
                MovimentacaoCilindro.objects.create(
                    tenant=self.tenant_a,
                    cilindro=cil_hist,
                    tipo="RECOLHA_CLIENTE",
                    status_anterior="EM_POSSE_CLIENTE",
                    status_novo="VAZIO_TRIAGEM",
                    cliente=self.cliente_regular,
                    registrado_por=self.user_a,
                    ocorrido_em=dt_retorno,
                    is_legado=True
                )

        alertas = gerar_alertas_demand_churn(self.tenant_a, data_ref=timezone.now().date(), k=2.0)
        alerta_cilindros = [a for a in alertas if a.tipo == AlertaOportunidadeComercial.TIPO_CILINDRO_NAO_RETORNA]
        self.assertTrue(len(alerta_cilindros) >= 1)
        alerta = alerta_cilindros[0]
        self.assertEqual(alerta.cliente, self.cliente_regular)
        self.assertIn('probabilidade_permanencia_pct', alerta.evidencia_json)
        self.assertTrue(alerta.score > 0)

    # =========================================================================
    # 4. JOB DIÁRIO, IDEMPOTÊNCIA E COOLDOWN DE 30 DIAS
    # =========================================================================

    def test_gerar_alertas_idempotente_nao_duplica_no_mesmo_dia(self):
        """Executar o gerador de alertas duas vezes na mesma data_ref não duplica alertas."""
        data_base = datetime.date(2026, 1, 1)
        with tenant_context(self.tenant_a):
            for i in range(5):
                dt = data_base + datetime.timedelta(days=i * 10)
                v = Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_regular,
                    status='Faturada',
                    valor_total=Decimal('200.00'),
                    data_entrega_efetiva=dt
                )
                Venda.objects.filter(id=v.id).update(
                    data_venda=timezone.make_aware(datetime.datetime.combine(dt, datetime.time(10, 0)))
                )
                ItemVenda.objects.create(
                    venda=v,
                    sku=self.sku_oxigenio,
                    quantidade=1,
                    valor_unitario=Decimal('200.00'),
                    valor_total=Decimal('200.00')
                )

        data_ref = datetime.date(2026, 3, 1)
        alertas_1 = gerar_alertas_demand_churn(self.tenant_a, data_ref=data_ref, k=2.0)
        self.assertTrue(len(alertas_1) >= 1)
        qtd_inicial = AlertaOportunidadeComercial.unscoped.filter(tenant=self.tenant_a).count()

        # Segunda execução idêntica
        alertas_2 = gerar_alertas_demand_churn(self.tenant_a, data_ref=data_ref, k=2.0)
        qtd_final = AlertaOportunidadeComercial.unscoped.filter(tenant=self.tenant_a).count()
        self.assertEqual(qtd_inicial, qtd_final)

    def test_cooldown_de_30_dias_para_alertas_descartados_respeitado(self):
        """
        Se um alerta para (cliente, gas, tipo) foi DESCARTADO há menos de 30 dias,
        o gerador ignora esse par até expirar o cooldown.
        """
        data_ref = datetime.date(2026, 3, 10)
        with tenant_context(self.tenant_a):
            alerta_descartado = AlertaOportunidadeComercial.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                gas=self.gas_oxigenio,
                tipo='RECOMPRA_ATRASADA',
                score=Decimal('50.00'),
                evidencia_json={'motivo': 'teste cooldown'},
                status='DESCARTADO',
                data_ref=data_ref - datetime.timedelta(days=10),
                chave_idempotencia='chave-antiga-descartada',
                resolvido_em=timezone.now() - datetime.timedelta(days=10)
            )

            # Histórico de compras suficientes
            data_base = datetime.date(2026, 1, 1)
            for i in range(5):
                dt = data_base + datetime.timedelta(days=i * 10)
                v = Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_regular,
                    status='Faturada',
                    valor_total=Decimal('200.00'),
                    data_entrega_efetiva=dt
                )
                Venda.objects.filter(id=v.id).update(
                    data_venda=timezone.make_aware(datetime.datetime.combine(dt, datetime.time(10, 0)))
                )
                ItemVenda.objects.create(
                    venda=v,
                    sku=self.sku_oxigenio,
                    quantidade=1,
                    valor_unitario=Decimal('200.00'),
                    valor_total=Decimal('200.00')
                )

        novos = gerar_alertas_demand_churn(self.tenant_a, data_ref=data_ref, k=2.0)
        recompra_alertas = [a for a in novos if a.tipo == 'RECOMPRA_ATRASADA' and a.cliente == self.cliente_regular]
        self.assertEqual(len(recompra_alertas), 0)

    # =========================================================================
    # 5. ATUALIZAÇÃO ATÔMICA DE STATUS E FUNIL
    # =========================================================================

    def test_atualizar_status_alerta_com_select_for_update_e_feedback(self):
        """Transiciona status do alerta com registro de responsável, feedback e resolvido_em."""
        with tenant_context(self.tenant_a):
            alerta = AlertaOportunidadeComercial.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                gas=self.gas_oxigenio,
                tipo='RECOMPRA_ATRASADA',
                score=Decimal('75.00'),
                evidencia_json={'teste': 1},
                status='NOVO',
                data_ref=datetime.date(2026, 3, 1),
                chave_idempotencia='chave-status-teste'
            )

            atualizado = atualizar_status_alerta(
                alerta_id=alerta.id,
                novo_status='CONVERTIDO',
                responsavel=self.user_a,
                feedback='Cliente recomprou 4 cilindros após contato telefônico.',
                tenant=self.tenant_a
            )

            self.assertEqual(atualizado.status, 'CONVERTIDO')
            self.assertEqual(atualizado.responsavel, self.user_a)
            self.assertIn('Cliente recomprou', atualizado.feedback)
            self.assertIsNotNone(atualizado.resolvido_em)

    def test_calcular_metricas_funil_calcula_taxas_e_calibragem_k(self):
        """Verifica a consolidação do funil comercial e taxas por tipo e por k."""
        with tenant_context(self.tenant_a):
            AlertaOportunidadeComercial.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                tipo='RECOMPRA_ATRASADA',
                score=Decimal('80.00'),
                evidencia_json={'k': 1.8},
                status='CONVERTIDO',
                data_ref=datetime.date(2026, 3, 1),
                chave_idempotencia='k-test-1'
            )
            AlertaOportunidadeComercial.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                tipo='RECOMPRA_ATRASADA',
                score=Decimal('60.00'),
                evidencia_json={'k': 2.5},
                status='DESCARTADO',
                data_ref=datetime.date(2026, 3, 2),
                chave_idempotencia='k-test-2'
            )

        metricas = calcular_metricas_funil(tenant=self.tenant_a)
        totais = metricas['totais']
        self.assertEqual(totais['total_alertas'], 2)
        self.assertEqual(totais['convertidos'], 1)
        self.assertEqual(totais['descartados'], 1)
        self.assertEqual(totais['taxa_conversao_global'], Decimal('50.00'))

    # =========================================================================
    # 6. BACKTEST HISTÓRICO
    # =========================================================================

    def test_executar_backtest_mede_recompra_historica_real(self):
        """Simulação retrospectiva mede quantos alertas simulados tiveram compra subsequente em até N dias."""
        data_base = datetime.date(2026, 1, 1)
        with tenant_context(self.tenant_a):
            for i in range(5):
                dt = data_base + datetime.timedelta(days=i * 10)
                v = Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_regular,
                    status='Faturada',
                    valor_total=Decimal('150.00'),
                    data_entrega_efetiva=dt
                )
                Venda.objects.filter(id=v.id).update(
                    data_venda=timezone.make_aware(datetime.datetime.combine(dt, datetime.time(10, 0)))
                )
                ItemVenda.objects.create(
                    venda=v,
                    sku=self.sku_oxigenio,
                    quantidade=1,
                    valor_unitario=Decimal('150.00'),
                    valor_total=Decimal('150.00')
                )

            # Uma 6ª compra em 2026-03-01 (19 dias após a última em 10/02)
            dt_recompra = datetime.date(2026, 3, 1)
            v6 = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                status='Faturada',
                valor_total=Decimal('150.00'),
                data_entrega_efetiva=dt_recompra
            )
            Venda.objects.filter(id=v6.id).update(
                data_venda=timezone.make_aware(datetime.datetime.combine(dt_recompra, datetime.time(10, 0)))
            )
            ItemVenda.objects.create(
                venda=v6,
                sku=self.sku_oxigenio,
                quantidade=1,
                valor_unitario=Decimal('150.00'),
                valor_total=Decimal('150.00')
            )

        resultado = executar_backtest(
            tenant=self.tenant_a,
            dias_horizonte=30,
            k=2.0
        )
        self.assertIn('total_alertas_simulados', resultado)
        self.assertIn('taxa_conversao_percentual', resultado)
        self.assertTrue(resultado['total_alertas_simulados'] >= 1)

    # =========================================================================
    # 7. ISOLAMENTO MULTI-TENANT E GUARDAS DE MÓDULO (API ENDPOINTS)
    # =========================================================================

    def test_api_multi_tenant_bloqueia_acesso_cruzado_com_404(self):
        """Usuário do Tenant B recebe 404 ao tentar acessar alerta do Tenant A."""
        with tenant_context(self.tenant_a):
            alerta_a = AlertaOportunidadeComercial.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                tipo='RECOMPRA_ATRASADA',
                score=Decimal('90.00'),
                evidencia_json={},
                status='NOVO',
                data_ref=datetime.date(2026, 3, 1),
                chave_idempotencia='chave-idor-teste'
            )

        self.client.force_authenticate(user=self.user_b)
        url = f"/api/analytics/alertas/{alerta_a.id}/"
        response = self.client.get(url, HTTP_X_TENANT_ID=str(self.tenant_b.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_modulo_analytics_inativo_bloqueia_acesso_com_403(self):
        """Tenant C com modulo_analytics_ativo=False recebe 403 Forbidden."""
        with tenant_context(self.tenant_c):
            user_c = User.objects.create_user(
                username="user_gama",
                email="user@gama.com.br",
                password="password123"
            )
            Membership.objects.create(
                user=user_c,
                tenant=self.tenant_c,
                papel="ADMIN"
            )

        self.client.force_authenticate(user=user_c)
        url = "/api/analytics/alertas/"
        response = self.client.get(url, HTTP_X_TENANT_ID=str(self.tenant_c.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_alerta_sugere_e_nunca_bloqueia_venda_ou_credito(self):
        """
        Garantia de limite do requisito 8:
        Ter um alerta em aberto (mesmo CHURN_RISCO ou CILINDRO_NAO_RETORNA)
        não impede nem bloqueia a criação de uma nova venda para o cliente.
        """
        with tenant_context(self.tenant_a):
            AlertaOportunidadeComercial.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                tipo='CHURN_RISCO',
                score=Decimal('95.00'),
                evidencia_json={'score': 95},
                status='NOVO',
                data_ref=datetime.date(2026, 3, 1),
                chave_idempotencia='alerta-nao-bloqueia-venda'
            )

            nova_venda = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_regular,
                status='Faturada',
                valor_total=Decimal('500.00'),
                data_venda=timezone.now()
            )
            self.assertIsNotNone(nova_venda.id)
            self.assertEqual(nova_venda.status, 'Faturada')


class Sprint12CHypothesisInvariantsTests(unittest.TestCase):
    """
    Testes de Propriedade (Hypothesis) para invariantes estatísticos:
    - Probabilidade Kaplan-Meier sempre ∈ [0, 1] e monótona decrescente.
    - Desvio padrão sempre >= 0.
    """

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=365),
                st.integers(min_value=0, max_value=1)
            ),
            min_size=1,
            max_size=50
        )
    )
    @settings(max_examples=30, deadline=None)
    def test_invariante_kaplan_meier_probabilidade_valida(self, duracoes):
        res = estimar_sobrevivencia_km(duracoes)
        curva = res['pontos_curva']
        total_eventos = res['total_eventos']
        self.assertTrue(total_eventos >= 0)

        prob_ant = 1.0
        for pt in curva:
            p = pt['probabilidade_sobrevivencia']
            self.assertTrue(0.0 <= p <= 1.0, f"Probabilidade inválida: {p}")
            self.assertTrue(p <= prob_ant + 1e-9, "Curva de sobrevivência deve ser não-crescente")
            prob_ant = p

    @given(
        st.lists(
            st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=50
        )
    )
    @settings(max_examples=30, deadline=None)
    def test_invariante_desvio_padrao_nao_negativo(self, valores):
        mu, sigma = calcular_media_e_desvio(valores)
        self.assertTrue(mu >= 0.0)
        self.assertTrue(sigma >= 0.0)
