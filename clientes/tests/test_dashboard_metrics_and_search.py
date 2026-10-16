import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import Cliente, ContratoComodato
from vendas.models import Venda, ItemVenda
from produtos.models import GasQuimico, ModeloCilindro, Produto

User = get_user_model()


class DashboardMetricsAndSearchTests(APITestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(
            cnpj="11.111.111/0001-11",
            razao_social="Tenant A Ltda",
            nome_fantasia="Tenant A"
        )
        self.tenant_b = Tenant.objects.create(
            cnpj="22.222.222/0001-22",
            razao_social="Tenant B Ltda",
            nome_fantasia="Tenant B"
        )

        self.user_a = User.objects.create_user(username="user_a", password="password123")
        Membership.objects.create(user=self.user_a, tenant=self.tenant_a, papel="ADMIN")

        self.user_b = User.objects.create_user(username="user_b", password="password123")
        Membership.objects.create(user=self.user_b, tenant=self.tenant_b, papel="ADMIN")

        # Configura contexto para Tenant A
        token = set_current_tenant(self.tenant_a)
        self.cliente_a = Cliente.objects.create(
            cnpj="12.345.678/0001-90",
            nome="Hospital Samaritano A",
            nome_fantasia="Samaritano Unidade 1",
            endereco="Rua 1, Lote 2",
            telefone="61999990001",
            estado="DF",
            cidade="Brasília",
            proprietario="Dr. Silva",
            is_medicinal=True,
            cnes_licenca_sanitaria="2678910"
        )
        self.contrato_a = ContratoComodato.objects.create(
            cliente=self.cliente_a,
            vigencia_inicio=timezone.now().date(),
            franquia_cilindros_isentos=5
        )

        # Venda no Tenant A
        self.venda_a = Venda.objects.create(
            cliente=self.cliente_a,
            valor_total=Decimal("500.00"),
            status="CONCLUIDA"
        )
        reset_current_tenant(token)

        # Configura contexto para Tenant B
        token_b = set_current_tenant(self.tenant_b)
        self.cliente_b = Cliente.objects.create(
            cnpj="98.765.432/0001-09",
            nome="Hospital São Paulo B",
            nome_fantasia="São Paulo Central",
            endereco="Av. Paulista, 1000",
            telefone="11999990002",
            estado="SP",
            cidade="São Paulo",
            proprietario="Dra. Santos"
        )
        self.venda_b = Venda.objects.create(
            cliente=self.cliente_b,
            valor_total=Decimal("50000.00"),
            status="CONCLUIDA"
        )
        reset_current_tenant(token_b)

    def tearDown(self):
        reset_current_tenant()

    def test_dashboard_metrics_filters_top_clientes_by_tenant(self):
        """
        Garante que dashboard_metrics não vaza os top clientes nem valores de outros tenants.
        """
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get('/clientes/api/dashboard_metrics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        top_clientes = data.get('top_clientes', [])

        # Deve conter apenas vendas do cliente_a
        cnpjs_retornados = [c['cnpj'] for c in top_clientes]
        self.assertIn(self.cliente_a.cnpj, cnpjs_retornados)
        self.assertNotIn(self.cliente_b.cnpj, cnpjs_retornados)

        # Verifica métricas adicionais
        self.assertIn('cilindros_em_posse', data)
        self.assertIn('contratos_ativos', data)
        self.assertIn('receita_estimada_mes', data)
        self.assertEqual(data['contratos_ativos'], 1)

    def test_cliente_search_filter(self):
        """
        Garante busca rápida por nome, nome_fantasia e cnpj.
        """
        self.client.force_authenticate(user=self.user_a)

        # Busca por nome
        res1 = self.client.get('/clientes/api/?search=Samaritano')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        results1 = res1.json().get('results', res1.json())
        self.assertEqual(len(results1), 1)

        # Busca por nome fantasia
        res2 = self.client.get('/clientes/api/?search=Unidade 1')
        results2 = res2.json().get('results', res2.json())
        self.assertEqual(len(results2), 1)

        # Busca por CNPJ
        res3 = self.client.get('/clientes/api/?search=12.345.678')
        results3 = res3.json().get('results', res3.json())
        self.assertEqual(len(results3), 1)

        # Busca inexistente
        res4 = self.client.get('/clientes/api/?search=InexistenteXYZ')
        results4 = res4.json().get('results', res4.json())
        self.assertEqual(len(results4), 0)

    def test_sem_paginacao_param(self):
        """
        Garante que ?sem_paginacao=1 retorna array plano de clientes para os selects.
        """
        self.client.force_authenticate(user=self.user_a)
        res = self.client.get('/clientes/api/?sem_paginacao=1')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

    def test_cliente_serializer_computed_fields(self):
        """
        Valida que o ClienteSerializer retorna os campos calculados e os novos campos opcionais.
        """
        self.client.force_authenticate(user=self.user_a)
        res = self.client.get(f'/clientes/api/{self.cliente_a.id}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertTrue(data.get('is_medicinal'))
        self.assertEqual(data.get('cnes_licenca_sanitaria'), '2678910')
        self.assertTrue(data.get('tem_contrato_ativo'))
        self.assertIn('cilindros_em_posse_count', data)
