import uuid
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Tenant, Membership, PerfilRegulatorioTenant
from core.tenancy import tenant_context
from accounts.models import User
from clientes.models import Cliente
from vendas.models import Venda
from logistica.models import Veiculo, Rota, Entrega, CoordenadaRastreamento
from logistica.services.routing import otimizar_ordem_paradas


class Sprint8TorreControleTrackingTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            razao_social="Logística Express Baros LTDA",
            nome_fantasia="Baros Log",
            cnpj="11.222.333/0001-44",
            plano="PRO"
        )
        self.perfil = PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='DISTRIBUIDORA',
            afe_numero='AFE-LOG-01',
            licenca_sanitaria_numero='LIC-LOG-01',
            licenca_sanitaria_validade=timezone.now().date() + timezone.timedelta(days=365)
        )

        with tenant_context(self.tenant):
            self.motorista = User.objects.create_user(
                username="motorista_joao",
                email="joao@baroslog.com.br",
                password="senha_segura_123",
                first_name="João",
                last_name="Silva"
            )
            Membership.objects.create(
                user=self.motorista,
                tenant=self.tenant,
                papel='MOTORISTA',
                ativo=True
            )

            self.cliente_1 = Cliente.objects.create(
                tenant=self.tenant,
                nome="Hospital das Clínicas",
                cnpj="22.333.444/0001-55",
                endereco="Rua das Acácias, 120",
                bairro="Jardins",
                cidade="São Paulo",
                estado="SP",
                cep="01400-000",
                telefone="1133334444",
                proprietario="Dr. Roberto"
            )

            self.cliente_2 = Cliente.objects.create(
                tenant=self.tenant,
                nome="Clínica Santa Clara",
                cnpj="33.444.555/0001-66",
                endereco="Av. Rebouças, 500",
                bairro="Pinheiros",
                cidade="São Paulo",
                estado="SP",
                cep="05401-000",
                telefone="1133335555",
                proprietario="Dra. Maria"
            )

            self.veiculo = Veiculo.objects.create(
                tenant=self.tenant,
                placa="BRA2E19",
                modelo="Mercedes Accelo 1016",
                marca="Mercedes-Benz",
                ano=2023,
                capacidade_carga=Decimal('6000.00')
            )

            self.rota = Rota.objects.create(
                tenant=self.tenant,
                nome="Rota Zona Oeste SP"
            )

            self.entrega = Entrega.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                rota=self.rota,
                motorista=self.motorista,
                status='Em Rota'
            )

            self.venda_1 = Venda.objects.create(
                tenant=self.tenant,
                cliente=self.cliente_1,
                entrega=self.entrega,
                valor_total=Decimal('450.00'),
                status='Em Rota'
            )

            self.venda_2 = Venda.objects.create(
                tenant=self.tenant,
                cliente=self.cliente_2,
                entrega=self.entrega,
                valor_total=Decimal('320.00'),
                status='Em Rota'
            )

        self.client = APIClient()

    # =========================================================================
    # 8.2. Modelagem & Mascaramento
    # =========================================================================
    def test_token_rastreio_uuid_gerado_automaticamente(self):
        """Valida que Entrega possui token_rastreio UUIDv4 gerado por padrão e único."""
        self.assertIsNotNone(self.entrega.token_rastreio)
        self.assertIsInstance(self.entrega.token_rastreio, uuid.UUID)

        with tenant_context(self.tenant):
            outra_entrega = Entrega.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                rota=self.rota,
                status='Agendada'
            )
            self.assertNotEqual(self.entrega.token_rastreio, outra_entrega.token_rastreio)

    def test_mascaramento_placa_e_nome_motorista(self):
        """Garante que a placa é mascarada para proteção e o nome do motorista é exposto amigavelmente."""
        self.assertEqual(self.entrega.placa_mascarada, "BRA-***9")
        self.assertIn("João Silva", self.entrega.nome_motorista)

    def test_coordenada_rastreamento_criacao_e_multitenancy(self):
        """Verifica que CoordenadaRastreamento herda de TenantAwareModel."""
        with tenant_context(self.tenant):
            coord = CoordenadaRastreamento.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                latitude=Decimal('-23.5505200'),
                longitude=Decimal('-46.6333080')
            )
            self.assertEqual(coord.tenant, self.tenant)
            self.assertEqual(coord.entrega, self.entrega)
            self.assertEqual(self.entrega.coordenadas_rastreamento.count(), 1)

    # =========================================================================
    # 8.2. Roteirização e Waypoints
    # =========================================================================
    def test_otimizar_ordem_paradas_service(self):
        """Testa o cálculo da ordem otimizada de waypoints para os clientes da entrega."""
        with tenant_context(self.tenant):
            resultado = otimizar_ordem_paradas(self.entrega.id)
        self.assertTrue(resultado['sucesso'])
        self.assertEqual(resultado['total_paradas'], 2)
        # Contrato da Sprint 12A: paradas persistidas em ParadaEntrega.
        self.assertEqual(len(resultado['paradas_ordenadas']), 2)
        clientes_roteirizados = {p['cliente_id'] for p in resultado['paradas_ordenadas']}
        self.assertEqual(clientes_roteirizados, {self.venda_1.cliente_id, self.venda_2.cliente_id})
        self.assertTrue(resultado['distancia_total_km'] > 0)
        self.assertTrue(resultado['tempo_total_min'] > 0)

    # =========================================================================
    # 8.1. API de Sincronização em Lote de GPS (PWA de Campo)
    # =========================================================================
    def test_sync_tracking_gps_em_lote(self):
        """Valida que o PWA de Campo pode enviar lotes de telemetria GPS offline."""
        self.client.force_authenticate(user=self.motorista)

        payload = {
            "coordenadas": [
                {
                    "entrega_id": self.entrega.id,
                    "lat": -23.5510000,
                    "lng": -46.6340000,
                    "timestamp": "2026-10-21T12:00:00Z"
                },
                {
                    "entrega_id": self.entrega.id,
                    "lat": -23.5520000,
                    "lng": -46.6350000,
                    "timestamp": "2026-10-21T12:00:30Z"
                }
            ]
        }

        response = self.client.post(
            '/logistica/api/tracking/sync/',
            data=payload,
            format='json',
            HTTP_X_TENANT_ID=str(self.tenant.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('total_sincronizado'), 2)

        with tenant_context(self.tenant):
            self.assertEqual(CoordenadaRastreamento.objects.filter(entrega=self.entrega).count(), 2)

    # =========================================================================
    # 8.3. View Pública de Rastreio (Sem DRF Auth - Fail-Closed)
    # =========================================================================
    def test_view_publica_rastreio_html_e_json(self):
        """Valida que clientes finais conseguem consultar o tracking via token UUID sem login."""
        with tenant_context(self.tenant):
            CoordenadaRastreamento.objects.create(
                tenant=self.tenant,
                entrega=self.entrega,
                latitude=Decimal('-23.5600000'),
                longitude=Decimal('-46.6500000')
            )

        # 1. Consulta HTML
        response_html = self.client.get(f'/rastreio/{self.entrega.token_rastreio}/')
        self.assertEqual(response_html.status_code, 200)
        self.assertContains(response_html, '<div id="map">')
        # Correção F-34 (Sprint 12A / LGPD): o nome do motorista não é exposto no rastreio público.
        self.assertNotContains(response_html, 'João Silva')
        self.assertContains(response_html, 'BRA-***9')
        # Garante Fail-Closed: Não contém valores em R$ ou nomes de clientes da rota
        self.assertNotContains(response_html, 'R$ 450,00')
        self.assertNotContains(response_html, 'Hospital das Clínicas')

        # 2. Consulta JSON
        response_json = self.client.get(
            f'/rastreio/{self.entrega.token_rastreio}/',
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(response_json.status_code, 200)
        data = response_json.json()
        self.assertEqual(data['status_entrega'], 'Em Rota')
        self.assertEqual(data['veiculo_placa_mascarada'], 'BRA-***9')
        self.assertNotIn('nome_motorista', data)
        self.assertTrue(data['posicao_visivel'])
        self.assertEqual(data['ultima_posicao']['latitude'], -23.56)
        self.assertEqual(data['ultima_posicao']['longitude'], -46.65)

    def test_view_publica_rastreio_token_invalido_retorna_404(self):
        """Token inexistente ou adulterado deve retornar 404 (Fail-Closed)."""
        token_inexistente = uuid.uuid4()
        response = self.client.get(
            f'/rastreio/{token_inexistente}/',
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(response.status_code, 404)
