from decimal import Decimal
from django.utils import timezone
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from logistica.models import Veiculo, Entrega
from logistica.services import validar_capacidade_veiculo_entrega
from produtos.models import GasQuimico, ModeloCilindro, Cilindro, SkuRecarga, MovimentacaoCilindro

User = get_user_model()


class D11PhysicalWeightCalculationTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(razao_social="Distribuidora D11 Ltda", nome_fantasia="Distribuidora D11", cnpj="11111111000199")
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(username="motorista_d11", password="password123")
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="MOTORISTA",
            ativo=True
        )

        self.gas = GasQuimico.objects.create(
            nome="Oxigênio Industrial",
            sigla="O2",
            categoria="Industrial",
            numero_onu="UN 1072",
            classe_risco="2.2"
        )

        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao="Cilindro T-50L",
            volume_hidraulico_litros=Decimal("50.00"),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal("55.00"),
            massa_gas_padrao_kg=Decimal("12.50")
        )

        self.sku = SkuRecarga.objects.create(
            tenant=self.tenant,
            gas=self.gas,
            modelo_cilindro=self.modelo,
            nome_comercial="Recarga O2 10m3",
            quantidade_carga=Decimal("10.00"),
            massa_gas_kg=Decimal("13.20"),
            preco_base=Decimal("150.00")
        )

        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="D11-9999",
            modelo="Caminhão 3/4",
            marca="Mercedes-Benz",
            ano=2022,
            capacidade_carga=Decimal("100.00"),  # 100 kg máx
            status="Disponível"
        )

        self.entrega = Entrega.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            status="Em Rota"
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        if hasattr(self, 'token'):
            reset_current_tenant(self.token)
        super().tearDown()

    def test_calculo_fisico_tara_real_mais_sku(self):
        """Cilindro com tara real e SKU de gás deve somar tara_real_kg + sku.massa_gas_kg"""
        cil = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-D11-01",
            numero_serie_ogiva="OG-01",
            fabricante="Cilbras",
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("54.20"),
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1800),
            status="CHEIO"
        )

        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=cil,
            tipo="ENTREGA_CLIENTE",
            entrega=self.entrega,
            status_anterior="CHEIO",
            status_novo="EM_CLIENTE",
            ocorrido_em=timezone.now(),
            is_legado=True,
            registrado_por=self.user
        )

        # 54.20 + 13.20 = 67.40 kg
        self.assertEqual(self.entrega.peso_total_carregado, 67.40)
        self.assertFalse(self.entrega.possui_peso_estimado)

    def test_calculo_fisico_usa_massa_padrao_modelo_quando_sem_sku(self):
        """Quando não há SKU configurado, utiliza massa_gas_padrao_kg do modelo"""
        gas_sem_sku = GasQuimico.objects.create(
            nome="Argônio Puro",
            sigla="AR",
            categoria="Industrial"
        )
        cil = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-D11-02",
            numero_serie_ogiva="OG-02",
            fabricante="Cilbras",
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=gas_sem_sku,
            tara_real_kg=Decimal("56.00"),
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1800),
            status="CHEIO"
        )

        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=cil,
            tipo="ENTREGA_CLIENTE",
            entrega=self.entrega,
            status_anterior="CHEIO",
            status_novo="EM_CLIENTE",
            ocorrido_em=timezone.now(),
            is_legado=True,
            registrado_por=self.user
        )

        # 56.00 + 12.50 (massa_gas_padrao_kg do modelo) = 68.50 kg
        self.assertEqual(self.entrega.peso_total_carregado, 68.50)
        self.assertFalse(self.entrega.possui_peso_estimado)

    def test_possui_peso_estimado_quando_tara_real_ausente(self):
        """Se o cilindro não tem tara_real_kg, possui_peso_estimado deve ser True"""
        cil = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-D11-03",
            numero_serie_ogiva="OG-03",
            fabricante="Cilbras",
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=None,  # Sem aferição física
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1800),
            status="CHEIO"
        )

        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=cil,
            tipo="ENTREGA_CLIENTE",
            entrega=self.entrega,
            status_anterior="CHEIO",
            status_novo="EM_CLIENTE",
            ocorrido_em=timezone.now(),
            is_legado=True,
            registrado_por=self.user
        )

        # Nominal (55.00) + SKU (13.20) = 68.20 kg
        self.assertEqual(self.entrega.peso_total_carregado, 68.20)
        self.assertTrue(self.entrega.possui_peso_estimado)

    def test_bloqueio_sobrecarga_e_api_validar_capacidade(self):
        """Validação de capacidade bloqueia sobrecarga e expõe possui_peso_estimado na API"""
        # Adiciona 2 cilindros pesados de 67.40 kg cada -> 134.80 kg > 100 kg (capacidade veículo)
        cil1 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-D11-A",
            numero_serie_ogiva="OG-A",
            fabricante="Cilbras",
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("54.20"),
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1800),
            status="CHEIO"
        )
        cil2 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-D11-B",
            numero_serie_ogiva="OG-B",
            fabricante="Cilbras",
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("54.20"),
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1800),
            status="CHEIO"
        )
        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=cil1,
            tipo="ENTREGA_CLIENTE",
            entrega=self.entrega,
            status_anterior="CHEIO",
            status_novo="EM_CLIENTE",
            ocorrido_em=timezone.now(),
            is_legado=True,
            registrado_por=self.user
        )
        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=cil2,
            tipo="ENTREGA_CLIENTE",
            entrega=self.entrega,
            status_anterior="CHEIO",
            status_novo="EM_CLIENTE",
            ocorrido_em=timezone.now(),
            is_legado=True,
            registrado_por=self.user
        )

        with self.assertRaises(ValidationError) as ctx:
            validar_capacidade_veiculo_entrega(self.entrega)
        self.assertIn("Capacidade de carga do veículo excedida", str(ctx.exception))

        # Teste endpoint API validar-capacidade
        url = f"/logistica/api/entregas/{self.entrega.id}/validar-capacidade/"
        response = self.client.get(url, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data['valido'])
        self.assertIn('erro', response.data)
        self.assertIn('possui_peso_estimado', response.data)
        self.assertFalse(response.data['possui_peso_estimado'])
