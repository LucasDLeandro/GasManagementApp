from decimal import Decimal
from datetime import timedelta
import uuid
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import Cliente, ContratoComodato
from clientes.services import calcular_radar_comodato_tenant
from produtos.models import GasQuimico, ModeloCilindro, SkuRecarga, Cilindro, Produto, LoteEnvase, EnvaseCilindro
from produtos.services import registrar_entrega_cilindro, registrar_recolha_cilindro
from vendas.models import Venda, ItemVenda
from logistica.models import Veiculo, Rota, Entrega

User = get_user_model()

class Sprint3CommercialMVPTests(TestCase):
    """
    Suíte de Testes Automatizados da SPRINT 3 (MVP Comercial):
    1. Strangler Pattern em Vendas (ItemVenda com SkuRecarga e preco_unitario_congelado).
    2. Contrato de Comodato e Motor de Cálculo do Radar (faixas 0-29, 30-59, 60-89, 90+ dias).
    3. Logística Full-for-Empty e Cálculo de Peso Real (tara + gás vs tara vazia).
    4. Endpoint DRF do Romaneio Bilateral.
    5. API do Dashboard Radar de Comodato & Pátio.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Oxigênio Brasil Central Ltda',
            nome_fantasia='Oxigênio Brasil'
        )
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(
            username='gerente.comercial',
            password='senha_segura_123',
            tipo_usuario='GERENTE'
        )
        Membership.objects.create(user=self.user, tenant=self.tenant, papel='GERENTE')
        self.client.force_authenticate(user=self.user)

        # Dados Globais e Base de Catálogo
        self.gas_o2, _ = GasQuimico.objects.get_or_create(
            sigla='O2-MED',
            defaults={
                'nome': 'Oxigênio Medicinal Comprimido',
                'categoria': 'MEDICINAL',
                'numero_onu': '1072',
                'classe_risco': '2.2',
                'cor_padrao_abnt': 'Verde Emblema',
                'exige_lote_anvisa': True
            }
        )

        self.gas_n2, _ = GasQuimico.objects.get_or_create(
            sigla='N2-IND',
            defaults={
                'nome': 'Nitrogênio Industrial',
                'categoria': 'INDUSTRIAL',
                'numero_onu': '1066',
                'classe_risco': '2.2',
                'cor_padrao_abnt': 'Cinza Médio',
                'exige_lote_anvisa': False
            }
        )

        self.modelo_50l = ModeloCilindro.objects.create(
            descricao='Cilindro Aço 50L / 10m³',
            material='ACO',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('60.00'),
            padrao_valvula_abnt='ABNT 218-1',
            periodicidade_reteste_anos=5
        )

        self.sku_o2 = SkuRecarga.objects.create(
            nome_comercial='Carga O2 Medicinal 10m³',
            gas=self.gas_o2,
            modelo_cilindro=self.modelo_50l,
            quantidade_carga=Decimal('10.00'),
            unidade='m3',
            massa_gas_kg=Decimal('13.30'),
            preco_base=Decimal('175.00'),
            ativo=True
        )

        self.cliente = Cliente.objects.create(
            tipo_cliente='PJ',
            cnpj='33.444.555/0001-66',
            nome='Hospital Santa Lúcia',
            endereco='SHLS 716 Conjunto C',
            telefone='6133450000',
            estado='DF',
            cidade='Brasília'
        )

        self.contrato = ContratoComodato.objects.create(
            cliente=self.cliente,
            franquia_cilindros_isentos=0,
            dias_carencia_giro=30,
            valor_diaria_excedente=Decimal('3.50'),
            custo_reposicao_casco=Decimal('1800.00')
        )

        self.lote_o2 = LoteEnvase.objects.create(
            gas=self.gas_o2,
            codigo_lote='LOTE-SP3-O2-01',
            data_envase=timezone.now().date() - timedelta(days=10),
            data_validade=timezone.now().date() + timedelta(days=365),
            pureza_percentual=Decimal('99.60'),
            responsavel_tecnico='Dra. Camila'
        )

        self.lote_n2 = LoteEnvase.objects.create(
            gas=self.gas_n2,
            codigo_lote='LOTE-SP3-N2-01',
            data_envase=timezone.now().date() - timedelta(days=10),
            data_validade=timezone.now().date() + timedelta(days=365),
            pureza_percentual=Decimal('99.90'),
            responsavel_tecnico='Eng. Marcos'
        )

    def _envasar_cilindro(self, cilindro):
        lote = self.lote_o2 if cilindro.gas_dedicado == self.gas_o2 else self.lote_n2
        env = EnvaseCilindro.objects.create(
            cilindro=cilindro,
            lote=lote,
            pressao_final_bar=200,
            envasado_em=timezone.now() - timedelta(days=5),
            operador=self.user
        )
        cilindro.envase_atual = env
        cilindro.save(update_fields=['envase_atual'])

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_strangler_pattern_item_venda_com_sku_e_preco_congelado(self):
        """
        1. Valida o Strangler Pattern em Vendas:
        - ItemVenda com sku populado e produto legado nulo (produto opcional).
        - Congelamento automático do preco_unitario_congelado a partir do preco_base do SKU.
        - Cálculo de valor total sem quebrar compatibilidade.
        """
        venda = Venda.objects.create(
            cliente=self.cliente,
            vendedor=self.user,
            status='Pendente'
        )

        item = ItemVenda.objects.create(
            venda=venda,
            sku=self.sku_o2,
            produto=None,
            quantidade=4,
            forma_faturamento='cilindro'
        )

        self.assertIsNone(item.produto)
        self.assertEqual(item.sku, self.sku_o2)
        self.assertEqual(item.preco_unitario_congelado, Decimal('175.00'))
        self.assertEqual(item.valor_unitario, Decimal('175.00'))
        self.assertEqual(item.valor_total, Decimal('700.00')) # 4 * 175.00

        venda.calcular_total()
        self.assertEqual(venda.valor_total, Decimal('700.00'))

    def test_strangler_pattern_item_venda_compatibilidade_legada(self):
        """
        Garante que vendas com o modelo legado Produto continuam funcionando perfeitamente.
        """
        prod_legado = Produto.objects.create(
            nome='Cilindro Legado 10m³',
            categoria='Medicinal',
            capacidade=Decimal('10.00'),
            unidade_medida='m³',
            preco=Decimal('160.00'),
            estoque=10
        )

        venda = Venda.objects.create(
            cliente=self.cliente,
            vendedor=self.user,
            status='Pendente'
        )

        item = ItemVenda.objects.create(
            venda=venda,
            produto=prod_legado,
            sku=None,
            quantidade=2,
            forma_faturamento='cilindro'
        )

        self.assertEqual(item.preco_unitario_congelado, Decimal('160.00'))
        self.assertEqual(item.valor_total, Decimal('320.00'))

    def test_motor_radar_comodato_faixas_e_locacao_acumulada(self):
        """
        2. Valida o Contrato de Comodato e Motor de Cálculo do Radar:
        - Cilindros entregues há 15, 45 e 95 dias.
        - Faixas: 0-29 (isento), 30-59 (15d excedentes), 90+ (65d excedentes).
        - Total acumulado = (15 * 3.50) + (65 * 3.50) = 52.50 + 227.50 = 280.00.
        - Risco Patrimonial = 3 * 1800.00 = 5400.00.
        """
        agora = timezone.now()
        hoje = agora.date()

        # Cilindro 15 dias (dentro da carência de 30 dias)
        cil_15d = Cilindro.objects.create(
            codigo_qr='QR-TEST-15D',
            numero_serie_ogiva='SN-15D',
            fabricante='Mannesmann',
            ano_fabricacao=2020,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('59.50'),
            data_ultimo_reteste=hoje - timedelta(days=365),
            data_proximo_reteste=hoje + timedelta(days=365 * 4),
            status='CHEIO_DISPONIVEL'
        )
        self._envasar_cilindro(cil_15d)
        registrar_entrega_cilindro(
            cilindro_id=cil_15d.id,
            cliente=self.cliente,
            usuario=self.user,
            ocorrido_em=agora - timedelta(days=15),
            client_uuid=uuid.uuid4()
        )

        # Cilindro 45 dias (15 dias excedentes = R$ 52.50)
        cil_45d = Cilindro.objects.create(
            codigo_qr='QR-TEST-45D',
            numero_serie_ogiva='SN-45D',
            fabricante='Cilbras',
            ano_fabricacao=2019,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=hoje - timedelta(days=365),
            data_proximo_reteste=hoje + timedelta(days=365 * 4),
            status='CHEIO_DISPONIVEL'
        )
        self._envasar_cilindro(cil_45d)
        registrar_entrega_cilindro(
            cilindro_id=cil_45d.id,
            cliente=self.cliente,
            usuario=self.user,
            ocorrido_em=agora - timedelta(days=45),
            client_uuid=uuid.uuid4()
        )

        # Cilindro 95 dias (65 dias excedentes = R$ 227.50)
        cil_95d = Cilindro.objects.create(
            codigo_qr='QR-TEST-95D',
            numero_serie_ogiva='SN-95D',
            fabricante='Matheson',
            ano_fabricacao=2018,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_n2,
            tara_real_kg=Decimal('60.20'),
            data_ultimo_reteste=hoje - timedelta(days=365 * 4),
            data_proximo_reteste=hoje + timedelta(days=365),
            status='CHEIO_DISPONIVEL'
        )
        self._envasar_cilindro(cil_95d)
        registrar_entrega_cilindro(
            cilindro_id=cil_95d.id,
            cliente=self.cliente,
            usuario=self.user,
            ocorrido_em=agora - timedelta(days=95),
            client_uuid=uuid.uuid4()
        )

        radar = calcular_radar_comodato_tenant()

        self.assertEqual(radar['total_cilindros_em_posse'], 3)
        self.assertEqual(radar['cilindros_sem_giro_30_mais'], 2) # 45d e 95d
        self.assertEqual(radar['receita_locacao_acumulada'], 280.00)
        self.assertEqual(radar['risco_patrimonial_total'], 5400.00)

        # Faixas
        self.assertEqual(radar['faixas']['dias_0_a_29'], 1)
        self.assertEqual(radar['faixas']['dias_30_a_59'], 1)
        self.assertEqual(radar['faixas']['dias_60_a_89'], 0)
        self.assertEqual(radar['faixas']['dias_90_mais'], 1)

    def test_logistica_peso_real_full_for_empty(self):
        """
        3. Valida Logística Full-for-Empty e Cálculo de Peso Real:
        - Cilindro cheio entregue: tara_real (60.0) + massa_gas (13.3) = 73.3 kg.
        - Cilindro vazio recolhido: tara_real (59.0) = 59.0 kg.
        - Peso total = 132.30 kg.
        """
        veiculo = Veiculo.objects.create(
            placa='LOG8899',
            modelo='Accelo 1016',
            marca='Mercedes-Benz',
            ano=2021,
            capacidade_carga=Decimal('5000.00'),
            status='Ativo'
        )
        rota = Rota.objects.create(
            nome='Rota Hospitalar',
            origem='Matriz',
            destino='Zona Sul',
            distancia_km=Decimal('25.00'),
            tempo_estimado_horas=Decimal('1.00')
        )
        entrega = Entrega.objects.create(
            veiculo=veiculo,
            rota=rota,
            motorista=self.user,
            status='Em Rota'
        )

        hoje = timezone.now().date()
        cil_cheio = Cilindro.objects.create(
            codigo_qr='QR-FULL-01',
            numero_serie_ogiva='SN-FULL-01',
            fabricante='Mannesmann',
            ano_fabricacao=2020,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=hoje - timedelta(days=365),
            data_proximo_reteste=hoje + timedelta(days=365 * 4),
            status='CHEIO_DISPONIVEL'
        )

        cil_vazio = Cilindro.objects.create(
            codigo_qr='QR-EMPTY-01',
            numero_serie_ogiva='SN-EMPTY-01',
            fabricante='Cilbras',
            ano_fabricacao=2018,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('59.00'),
            data_ultimo_reteste=hoje - timedelta(days=365 * 2),
            data_proximo_reteste=hoje + timedelta(days=365 * 3),
            status='VAZIO_TRIAGEM'
        )

        # Entrega cheio (tara 60.0 + gas 13.3 = 73.3 kg)
        self._envasar_cilindro(cil_cheio)
        registrar_entrega_cilindro(
            cilindro_id=cil_cheio.id,
            cliente=self.cliente,
            entrega=entrega,
            usuario=self.user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4()
        )

        # Recolhe vazio (tara 59.0 kg)
        registrar_recolha_cilindro(
            cilindro_id=cil_vazio.id,
            cliente=self.cliente,
            entrega=entrega,
            usuario=self.user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4()
        )

        self.assertEqual(entrega.peso_total_carregado, 132.30)
        self.assertEqual(entrega.capacidade_disponivel, 5000.00 - 132.30)
        self.assertEqual(entrega.percentual_lotacao, round((132.30 / 5000.0) * 100, 1))

    def test_drf_romaneio_bilateral_endpoint(self):
        """
        4. Valida endpoint DRF do Romaneio Bilateral (GET e POST):
        - GET retorna colunas entregues/recolhidos e saldos de comodato.
        - POST com acao='entregar' e 'recolher' executa a troca física via services.
        """
        veiculo = Veiculo.objects.create(
            placa='BIL1234',
            modelo='Iveco Daily',
            marca='Iveco',
            ano=2022,
            capacidade_carga=Decimal('3500.00')
        )
        rota = Rota.objects.create(
            nome='Rota Expressa',
            origem='Centro',
            destino='Norte',
            distancia_km=Decimal('15.00'),
            tempo_estimado_horas=Decimal('0.50')
        )
        entrega = Entrega.objects.create(veiculo=veiculo, rota=rota, motorista=self.user, status='Em Rota')

        hoje = timezone.now().date()
        cilindro_entrega = Cilindro.objects.create(
            codigo_qr='QR-BIP-ENTREGA',
            numero_serie_ogiva='SN-BIP-01',
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=hoje - timedelta(days=365),
            data_proximo_reteste=hoje + timedelta(days=365 * 4),
            status='CHEIO_DISPONIVEL'
        )
        self._envasar_cilindro(cilindro_entrega)

        # 1. Bipagem de Entrega via POST
        url_romaneio = f'/logistica/api/entregas/{entrega.id}/romaneio-bilateral/'
        payload_entrega = {
            'acao': 'entregar',
            'codigo_qr': 'QR-BIP-ENTREGA',
            'cliente_id': self.cliente.id
        }
        res_post = self.client.post(url_romaneio, payload_entrega, format='json')
        self.assertEqual(res_post.status_code, status.HTTP_200_OK)
        self.assertEqual(res_post.data['status'], 'sucesso')

        cilindro_entrega.refresh_from_db()
        self.assertEqual(cilindro_entrega.status, 'EM_POSSE_CLIENTE')
        self.assertEqual(cilindro_entrega.cliente_posse_atual, self.cliente)

        # 2. Bipagem de Recolha via POST
        cilindro_recolha = Cilindro.objects.create(
            codigo_qr='QR-BIP-RECOLHA',
            numero_serie_ogiva='SN-BIP-02',
            fabricante='Mannesmann',
            ano_fabricacao=2019,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('59.50'),
            data_ultimo_reteste=hoje - timedelta(days=365 * 2),
            data_proximo_reteste=hoje + timedelta(days=365 * 3),
            status='EM_POSSE_CLIENTE',
            cliente_posse_atual=self.cliente
        )
        payload_recolha = {
            'acao': 'recolher',
            'codigo_qr': 'QR-BIP-RECOLHA',
            'cliente_id': self.cliente.id,
            'observacao': 'Recolhido casco vazio'
        }
        res_recolha = self.client.post(url_romaneio, payload_recolha, format='json')
        self.assertEqual(res_recolha.status_code, status.HTTP_200_OK)

        cilindro_recolha.refresh_from_db()
        self.assertEqual(cilindro_recolha.status, 'VAZIO_TRIAGEM')
        self.assertIsNone(cilindro_recolha.cliente_posse_atual)

        # 3. Consulta GET do Romaneio
        res_get = self.client.get(url_romaneio)
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_get.data['cilindros_entregues']), 1)
        self.assertEqual(len(res_get.data['cilindros_recolhidos']), 1)
        self.assertGreater(res_get.data['peso_total_carregado'], 0)

    def test_dashboard_stats_api_view_kpis_e_radar(self):
        """
        5. Valida a API do Dashboard Radar de Comodato (/inicio/api/stats/):
        - Retorna os 4 KPIs: frota_total, cilindros_sem_giro_30_mais, receita_locacao_acumulada, alertas_reteste_inmetro.
        - Retorna donut ApexCharts, faixas e itens do radar.
        """
        hoje = timezone.now().date()
        Cilindro.objects.create(
            codigo_qr='QR-RETESTE-ALERTA',
            numero_serie_ogiva='SN-RET-01',
            fabricante='Mannesmann',
            ano_fabricacao=2015,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=hoje - timedelta(days=365 * 5),
            data_proximo_reteste=hoje + timedelta(days=10),
            status='CHEIO_DISPONIVEL'
        )

        res = self.client.get('/inicio/api/stats/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        data = res.data
        self.assertIn('frota_total', data)
        self.assertIn('cilindros_sem_giro_30_mais', data)
        self.assertIn('receita_locacao_acumulada', data)
        self.assertIn('alertas_reteste_inmetro', data)
        self.assertIn('donut_labels', data)
        self.assertIn('donut_series', data)
        self.assertIn('radar_faixas', data)
        self.assertIn('radar_itens', data)

        self.assertGreaterEqual(data['frota_total'], 1)
        self.assertGreaterEqual(data['alertas_reteste_inmetro'], 1)
