import uuid
from decimal import Decimal
from datetime import timedelta, date

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from produtos.models import Produto
from clientes.models import Cliente
from vendas.models import Venda, ItemVenda
from logistica.models import (
    Veiculo,
    Rota,
    Entrega,
    Abastecimento,
    OrdemServico,
    ApoliceSeguro,
    ApoliceCobertura,
    ApoliceVeiculo,
    Sinistro,
    TabelaFrete,
    PrecoCombustivelReferencia,
    ConfiguracaoRentabilidade,
    CustoViagem,
    CustoViagemItem,
)
from logistica.services.rentabilidade import (
    estimar_custo_combustivel_pre_saida,
    calcular_rateios_viagem,
    apurar_receita_frete_entrega,
    verificar_alerta_averbacao,
    verificar_alerta_baixa_ocupacao,
    consolidar_custo_viagem,
    obter_indicadores_rentabilidade,
    obter_tco_frota,
    gerar_csv_rentabilidade,
)

User = get_user_model()


class SprintL6RentabilidadeTCOTestCase(TestCase):
    def setUp(self):
        # 1. Tenants
        self.tenant_a = Tenant.objects.create(
            razao_social="Distribuidora Alfa Ltda",
            nome_fantasia="Alfa Log",
            cnpj="12345678000101"
        )
        self.tenant_b = Tenant.objects.create(
            razao_social="Distribuidora Beta Ltda",
            nome_fantasia="Beta Log",
            cnpj="98765432000199"
        )

        self.token = set_current_tenant(self.tenant_a)

        # 2. Usuários
        self.user_a = User.objects.create_user(
            username="admin_alfa",
            email="admin@alfa.com",
            password="password123"
        )
        Membership.objects.create(tenant=self.tenant_a, user=self.user_a, papel='ADMIN')

        self.user_b = User.objects.create_user(
            username="admin_beta",
            email="admin@beta.com",
            password="password123"
        )
        Membership.objects.create(tenant=self.tenant_b, user=self.user_b, papel='ADMIN')

        # 3. Clientes
        self.cliente_1 = Cliente.objects.create(
            tenant=self.tenant_a,
            nome="Supermercado Alvorada",
            cnpj="22333444000155",
            endereco="Av. Central, 100",
            cidade="São Paulo",
            estado="SP",
            telefone="11999998888",
            proprietario="Carlos"
        )
        self.cliente_2 = Cliente.objects.create(
            tenant=self.tenant_a,
            nome="Hospital Esperança",
            cnpj="55666777000188",
            endereco="Rua da Paz, 200",
            cidade="São Paulo",
            estado="SP",
            telefone="11988887777",
            proprietario="Dra. Ana"
        )

        # 4. Produtos
        self.prod_glp = Produto.objects.create(
            tenant=self.tenant_a,
            nome="GLP P13",
            categoria="Industrial",
            capacidade=Decimal("13.00"),
            unidade_medida="kg",
            preco=Decimal("110.00"),
            estoque=100
        )

        # 5. Rotas
        self.rota_sul = Rota.objects.create(
            tenant=self.tenant_a,
            nome="Rota Sul Hospitalar",
            origem="Base Central",
            destino="Setor Hospitalar Sul",
            distancia_km=Decimal("100.00"),
            tempo_estimado_min=120
        )
        self.rota_norte = Rota.objects.create(
            tenant=self.tenant_a,
            nome="Rota Norte Comercial",
            origem="Base Central",
            destino="Setor Norte",
            distancia_km=Decimal("50.00"),
            tempo_estimado_min=60
        )

        # 6. Veículos
        self.veiculo_1 = Veiculo.objects.create(
            tenant=self.tenant_a,
            placa="ALF1001",
            modelo="Delivery 11.180",
            marca="VW",
            ano=2022,
            ano_fabricacao=2022,
            capacidade_carga=Decimal("5000.00"),
            combustivel_padrao="Diesel S10",
            consumo_referencia_km_l=Decimal("5.00"),
            odometro_atual_km=Decimal("40000.00"),
            fipe_valor=Decimal("150000.00")
        )
        self.veiculo_2 = Veiculo.objects.create(
            tenant=self.tenant_a,
            placa="ALF2002",
            modelo="Accelo 1016",
            marca="Mercedes-Benz",
            ano=2021,
            ano_fabricacao=2021,
            capacidade_carga=Decimal("6000.00"),
            combustivel_padrao="Diesel S10",
            consumo_referencia_km_l=Decimal("4.00"),
            odometro_atual_km=Decimal("80000.00"),
            fipe_valor=Decimal("180000.00")
        )

        # 7. Preço de Referência de Combustível (L2)
        PrecoCombustivelReferencia.objects.create(
            tenant=self.tenant_a,
            fonte="ANP",
            produto="Diesel S10",
            uf="GO",
            municipio="",
            data_inicial=timezone.localdate() - timedelta(days=5),
            data_final=timezone.localdate(),
            preco_medio=Decimal("6.0000")
        )

        # 8. Tabela de Frete (R$ 5,00 por km)
        TabelaFrete.objects.create(
            tenant=self.tenant_a,
            tipo_cobranca="Distancia",
            valor=Decimal("5.00")
        )

        # 9. Configuração de Rentabilidade
        self.config_rentab = ConfiguracaoRentabilidade.objects.create(
            tenant=self.tenant_a,
            metodo_rateio_seguro="Km Rodado",
            km_anual_estimado_veiculo=40000,
            vida_util_anos=5,
            percentual_residual=Decimal("20.00"),
            usar_estimativa_combustivel=True,
            media_lotacao_alerta_minima=Decimal("50.00"),
            viagens_baixa_ocupacao_alerta=3
        )

        # 10. API Client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user_a)

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_01_estimativa_combustivel_pre_saida_fallback_e_real(self):
        """Valida estimativa de combustível pré-saída com consumo de referência e preço ANP."""
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,
            status='Agendada'
        )

        # Rota Sul: 100 km. Consumo ref veiculo_1: 5.0 km/L. Preço ANP: R$ 6.00
        # Litros previstos: 100 / 5 = 20 L. Custo previsto: 20 * 6 = R$ 120.00
        estimativa = estimar_custo_combustivel_pre_saida(entrega)
        self.assertEqual(estimativa['custo_estimado'], Decimal("120.00"))
        self.assertEqual(estimativa['litros_estimados'], Decimal("20.00"))
        self.assertEqual(estimativa['consumo_km_l'], Decimal("5.00"))
        self.assertEqual(estimativa['preco_litro'], Decimal("6.00"))
        self.assertIn("ANP", estimativa['fonte_preco'])
        self.assertIsNotNone(estimativa['data_preco'])

        # Agora criamos abastecimento fechado (L2) para o veículo_1 calculando consumo real
        # 100 km rodados com 25 litros => consumo real de 4.0 km/L
        Abastecimento.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            data_hora=timezone.now() - timedelta(days=2),
            tipo_combustivel="Diesel S10",
            odometro_km=40000,
            litros=Decimal("25.000"),
            valor_litro=Decimal("6.0000"),
            valor_total=Decimal("150.00"),
            tanque_cheio=True,
            km_rodados_desde_anterior=100,
            consumo_km_l=Decimal("4.00")
        )

        estimativa_real = estimar_custo_combustivel_pre_saida(entrega)
        # 100 km / 4 km/L = 25 L * 6.00 = R$ 150.00
        self.assertEqual(estimativa_real['custo_estimado'], Decimal("150.00"))
        self.assertEqual(estimativa_real['consumo_km_l'], Decimal("4.00"))

    def test_02_rateios_viagem_manutencao_depreciacao_seguro(self):
        """Valida as fórmulas de rateio contábil para manutenção, depreciação e seguros."""
        # 1. Manutenção: criar OS concluída de R$ 4.000 para veículo_1 que tem 40.000 km
        # R$/km = 4.000 / 40.000 = R$ 0,10 por km
        OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            tipo="Corretiva",
            status="Concluída",
            odometro_entrada=40000,
            odometro_saida=40000,
            custo_total=Decimal("4000.00"),
            data_abertura=timezone.now() - timedelta(days=10),
            data_conclusao=timezone.now() - timedelta(days=5)
        )

        # 2. Seguro: apólice anual de R$ 8.000 vinculada a 2 veículos (veiculo_1 e veiculo_2)
        # Premio por veículo: R$ 4.000 / ano. Km anual estimado da empresa: 40.000 km
        # R$/km seguro = 4.000 / 40.000 = R$ 0,10 por km
        apolice = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            numero_apolice="APOL-FROTA-100",
            tipo="Frota/Casco+RCF",
            seguradora="Porto Seguro",
            premio_total=Decimal("8000.00"),
            vigencia_inicio=timezone.now().date() - timedelta(days=30),
            vigencia_fim=timezone.now().date() + timedelta(days=335),
            ativa=True
        )
        ApoliceVeiculo.objects.create(tenant=self.tenant_a, apolice=apolice, veiculo=self.veiculo_1)
        ApoliceVeiculo.objects.create(tenant=self.tenant_a, apolice=apolice, veiculo=self.veiculo_2)

        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,
            status='Agendada'
        )

        # Para viagem de 100 km:
        # Rateio Manut: 100 * 0,10 = R$ 10,00
        # Rateio Depreciação:
        # FIPE = 150.000. Residual = 20% (120.000 depreciável). Vida útil = 5 anos.
        # Deprec anual = 120.000 / 5 = 24.000 / ano.
        # R$/km = 24.000 / 40.000 km = R$ 0,60 por km.
        # Viagem de 100 km: 100 * 0,60 = R$ 60,00.
        # Rateio Seguro: 100 * 0,10 = R$ 10,00.
        rateios = calcular_rateios_viagem(entrega, km=Decimal("100.00"))
        self.assertEqual(rateios['rateio_manutencao'], Decimal("10.00"))
        self.assertEqual(rateios['rateio_depreciacao'], Decimal("60.00"))
        self.assertEqual(rateios['rateio_seguro'], Decimal("10.00"))

    def test_03_apuracao_receita_frete_tabela(self):
        """Valida apuração da receita de frete a partir da TabelaFrete."""
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,  # 100 km
            status='Agendada'
        )
        # Tabela: R$ 5,00 por km * 100 km = R$ 500,00
        receita = apurar_receita_frete_entrega(entrega)
        self.assertEqual(receita, Decimal("500.00"))

    def test_04_alerta_averbacao_limite_apolice_carga(self):
        """Valida disparo de alerta quando o valor da carga ultrapassa o limite da apólice ou não há apólice ativa."""
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,
            status='Agendada'
        )
        # Venda com 100 botijões P13 = R$ 11.000,00
        venda = Venda.objects.create(
            tenant=self.tenant_a,
            cliente=self.cliente_1,
            entrega=entrega,
            valor_total=Decimal("11000.00"),
            status="Em Separação"
        )
        ItemVenda.objects.create(
            venda=venda,
            produto=self.prod_glp,
            quantidade=100,
            peso_unitario=Decimal("28.00"),
            valor_unitario=Decimal("110.00"),
            valor_total=Decimal("11000.00")
        )

        # Sem apólice de carga ativa cadastrada: deve disparar alerta
        alerta, motivo, valor_carga = verificar_alerta_averbacao(entrega)
        self.assertTrue(alerta)
        self.assertIn("Não há apólice ativa", motivo)
        self.assertEqual(valor_carga, Decimal("11000.00"))

        # Cadastra apólice de carga com limite de R$ 10.000 (menor que R$ 11.000)
        apolice_carga = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            numero_apolice="APOL-CARGA-RCTR-1",
            tipo="Carga RCTR-C",
            seguradora="Sompo Seguros",
            premio_total=Decimal("3000.00"),
            limite_maximo_por_viagem=Decimal("10000.00"),
            vigencia_inicio=timezone.now().date() - timedelta(days=10),
            vigencia_fim=timezone.now().date() + timedelta(days=350),
            ativa=True
        )
        alerta, motivo, _ = verificar_alerta_averbacao(entrega)
        self.assertTrue(alerta)
        self.assertIn("ultrapassa o limite de averbação", motivo)

        # Aumenta limite da apólice para R$ 50.000: alerta não deve mais disparar
        apolice_carga.limite_maximo_por_viagem = Decimal("50000.00")
        apolice_carga.save()
        alerta_ok, _, _ = verificar_alerta_averbacao(entrega)
        self.assertFalse(alerta_ok)

    def test_05_alerta_baixa_ocupacao_rota(self):
        """Valida detecção de rota ociosa com média D11 abaixo de 50% nas últimas N viagens."""
        # Criar 3 viagens anteriores na rota_norte com lotação de 30%
        # veiculo_1 tem capacidade 5000 kg. Carregar 1400 kg = 28%
        for i in range(3):
            ent_passada = Entrega.objects.create(
                tenant=self.tenant_a,
                veiculo=self.veiculo_1,
                rota=self.rota_norte,
                status="Concluída",
                data_saida=timezone.now() - timedelta(days=i + 1)
            )
            v = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_1,
                entrega=ent_passada,
                valor_total=Decimal("1000.00"),
                status="Entregue"
            )
            # 50 unidades de P13 * 28 kg peso_total = 1400 kg (28%)
            ItemVenda.objects.create(
                venda=v,
                produto=self.prod_glp,
                quantidade=50,
                peso_unitario=Decimal("28.00"),
                valor_unitario=Decimal("20.00"),
                valor_total=Decimal("1000.00")
            )

        nova_entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_norte,
            status="Agendada"
        )
        alerta, motivo = verificar_alerta_baixa_ocupacao(nova_entrega)
        self.assertTrue(alerta)
        self.assertIn("abaixo de 50%", motivo)

    def test_06_snapshot_imutavel_apos_conclusao(self):
        """Garante que ao concluir a entrega, os valores reais são congelados e não mudam com alterações posteriores."""
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,
            status='Agendada'
        )
        # Adiciona item de pedágio avulso
        cv = consolidar_custo_viagem(entrega, congelar=False)
        CustoViagemItem.objects.create(
            tenant=self.tenant_a,
            custo_viagem=cv,
            tipo="Pedágio",
            descricao="Pedágio Rodovia Sul Km 35",
            valor=Decimal("25.50")
        )

        # Concluir entrega (dispara congelar=True)
        entrega.status = 'Concluída'
        entrega.save()

        cv.refresh_from_db()
        self.assertTrue(cv.snapshot_congelado)
        custo_congelado = cv.custo_total_real
        margem_congelada = cv.margem_bruta

        # Simular alteração retroativa de preço de combustível e custo de OS
        PrecoCombustivelReferencia.objects.filter(tenant=self.tenant_a).update(preco_medio=Decimal("15.0000"))
        OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            tipo="Corretiva",
            status="Concluída",
            odometro_entrada=40000,
            odometro_saida=40000,
            custo_total=Decimal("50000.00"),
            data_abertura=timezone.now() - timedelta(days=2),
            data_conclusao=timezone.now() - timedelta(days=1)
        )

        # Tentar reconsolidar: não deve alterar
        cv_re = consolidar_custo_viagem(entrega)
        self.assertEqual(cv_re.custo_total_real, custo_congelado)
        self.assertEqual(cv_re.margem_bruta, margem_congelada)

    def test_07_cenario_incompleto_sem_dados_vs_zero_enganoso(self):
        """Verifica a sinalização de 'sem dados' quando odômetro ou rota não tem km informado."""
        rota_sem_km = Rota.objects.create(
            tenant=self.tenant_a,
            nome="Rota Sem Distância",
            origem="Base",
            destino="Interior",
            distancia_km=None
        )
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=rota_sem_km,
            status='Agendada'
        )

        cv = consolidar_custo_viagem(entrega, congelar=False)
        self.assertTrue(cv.dados_incompletos)
        self.assertIn("Sem quilometragem registrada", cv.motivo_dados_incompletos)

    def test_08_endpoint_rentabilidade_agrupamentos(self):
        """Testa o endpoint /logistica/api/rentabilidade/ agrupando por rota, veiculo, cliente e motorista."""
        # Cria uma entrega concluída para ter dados
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,
            status='Concluída'
        )
        Venda.objects.create(
            tenant=self.tenant_a,
            cliente=self.cliente_1,
            entrega=entrega,
            valor_total=Decimal("2500.00"),
            status="Entregue"
        )
        consolidar_custo_viagem(entrega, congelar=True)

        for agrupar in ['rota', 'veiculo', 'cliente', 'motorista']:
            resp = self.client.get(f'/logistica/api/rentabilidade/?agrupar={agrupar}')
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            data = resp.json()
            self.assertIn('total_viagens', data)
            self.assertIn('itens', data)
            self.assertGreaterEqual(len(data['itens']), 1)
            det = data['itens'][0]
            self.assertIn('nome', det)
            self.assertIn('receita', det)
            self.assertIn('custo', det)
            self.assertIn('margem', det)

    def test_09_exportacao_csv_rentabilidade(self):
        """Testa o download de CSV via endpoint com cabeçalhos apropriados."""
        resp = self.client.get('/logistica/api/rentabilidade/?agrupar=rota&formato=csv')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', resp['Content-Type'])
        self.assertIn('attachment; filename="rentabilidade_', resp['Content-Disposition'])
        conteudo = resp.content.decode('utf-8-sig')
        self.assertIn('RELATÓRIO DE RENTABILIDADE E CUSTO TOTAL DE FRETES', conteudo)

    def test_10_tco_consolidado_frota(self):
        """Valida o endpoint /logistica/api/rentabilidade/tco/ integrando combustível L2, OS L3 e seguros L5."""
        # 1. Combustível L2: abastecimento de R$ 600
        Abastecimento.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            data_hora=timezone.now() - timedelta(days=5),
            tipo_combustivel="Diesel S10",
            odometro_km=40000,
            litros=Decimal("100.000"),
            valor_litro=Decimal("6.0000"),
            valor_total=Decimal("600.00"),
            tanque_cheio=True,
            km_rodados_desde_anterior=500,
            consumo_km_l=Decimal("5.00")
        )

        # 2. Manutenção L3: OS de R$ 1.500
        OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            tipo="Preventiva",
            status="Concluída",
            odometro_entrada=40000,
            odometro_saida=40000,
            custo_total=Decimal("1500.00"),
            data_abertura=timezone.now() - timedelta(days=20),
            data_conclusao=timezone.now() - timedelta(days=18)
        )

        # 3. Seguros L5: apólice anual de R$ 6.000 para veiculo_1 (1 veículo)
        apolice = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            numero_apolice="APOL-TEST-TCO",
            tipo="Frota/Casco+RCF",
            seguradora="Tokio Marine",
            premio_total=Decimal("6000.00"),
            vigencia_inicio=timezone.now().date() - timedelta(days=30),
            vigencia_fim=timezone.now().date() + timedelta(days=335),
            ativa=True
        )
        ApoliceVeiculo.objects.create(tenant=self.tenant_a, apolice=apolice, veiculo=self.veiculo_1)

        resp = self.client.get('/logistica/api/rentabilidade/tco/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertIn('veiculos', data)
        self.assertIn('composicao_geral', data)
        
        v1_tco = next((v for v in data['veiculos'] if v['placa'] == 'ALF1001'), None)
        self.assertIsNotNone(v1_tco)
        self.assertEqual(Decimal(str(v1_tco['custo_combustivel'])), Decimal("600.00"))
        self.assertEqual(Decimal(str(v1_tco['custo_manutencao'])), Decimal("1500.00"))
        self.assertEqual(Decimal(str(v1_tco['custo_seguro_rateado'])), Decimal("6000.00"))
        self.assertGreater(Decimal(str(v1_tco['custo_depreciacao'])), Decimal("0.00"))
        self.assertGreater(Decimal(str(v1_tco['custo_total_acumulado'])), Decimal("8100.00"))

    def test_11_custo_viagem_item_lancamento_avulso(self):
        """Valida adição de itens avulsos (pedágio, chapa, diárias) ao custo da viagem."""
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,
            status='Agendada'
        )
        cv = consolidar_custo_viagem(entrega, congelar=False)
        custo_base = cv.custo_total_real

        # Adiciona pedágio de R$ 32,50 e diária de R$ 100,00
        resp = self.client.post('/logistica/api/custos-viagem-itens/', {
            'custo_viagem': cv.id,
            'tipo': 'Pedágio',
            'descricao': 'Pedágio Km 120',
            'valor': '32.50'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        resp2 = self.client.post('/logistica/api/custos-viagem-itens/', {
            'custo_viagem': cv.id,
            'tipo': 'Diária',
            'descricao': 'Diária de viagem almoço',
            'valor': '100.00'
        }, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)

        cv.refresh_from_db()
        self.assertEqual(cv.pedagios, Decimal("32.50"))
        self.assertEqual(cv.diarias_motorista, Decimal("100.00"))
        self.assertEqual(cv.custo_total_real, custo_base + Decimal("132.50"))

    def test_12_isolamento_multi_tenant(self):
        """Garante que dados e TCO do Tenant A não vazam para o Tenant B."""
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_1,
            rota=self.rota_sul,
            status='Concluída'
        )
        consolidar_custo_viagem(entrega, congelar=True)

        # Autentica como Tenant B
        client_b = APIClient()
        client_b.force_authenticate(user=self.user_b)

        # Mudar contexto para Tenant B
        token_b = set_current_tenant(self.tenant_b)
        try:
            resp_rentab = client_b.get('/logistica/api/rentabilidade/')
            self.assertEqual(resp_rentab.status_code, status.HTTP_200_OK)
            data = resp_rentab.json()
            self.assertEqual(data['total_viagens'], 0)
            self.assertEqual(len(data['itens']), 0)

            resp_tco = client_b.get('/logistica/api/rentabilidade/tco/')
            self.assertEqual(resp_tco.status_code, status.HTTP_200_OK)
            data_tco = resp_tco.json()
            self.assertEqual(len(data_tco['veiculos']), 0)
        finally:
            reset_current_tenant(token_b)
