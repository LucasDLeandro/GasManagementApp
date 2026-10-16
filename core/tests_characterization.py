from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import Cliente
from produtos.models import Produto
from vendas.models import Venda, ItemVenda
from logistica.models import Veiculo, Rota, Entrega

User = get_user_model()

class LegacyCharacterizationTests(TestCase):
    """
    Testes de caracterização para garantir a integridade do comportamento legado
    agora com suporte à fundação Multi-Tenant Fail-Closed.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            cnpj='00.000.000/0001-00',
            razao_social='Distribuidora Teste Ltda',
            nome_fantasia='Gases Teste'
        )
        self.token = set_current_tenant(self.tenant)
        self.user = User.objects.create_user(
            username='operador_teste',
            password='senha_segura_123',
            tipo_usuario='VENDEDOR'
        )
        Membership.objects.create(user=self.user, tenant=self.tenant, papel='VENDEDOR')

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_criacao_cliente_produto_venda_item(self):
        """
        a) Testa a criação de Cliente, Produto, Venda e ItemVenda e o cálculo de total.
        """
        cliente = Cliente.objects.create(
            tipo_cliente='PJ',
            cnpj='12.345.678/0001-99',
            nome='Hospital Teste Esperança',
            endereco='Av. Saúde, 500',
            telefone='11988887777',
            estado='SP',
            cidade='São Paulo',
            proprietario='Diretoria'
        )

        produto = Produto.objects.create(
            nome='Cilindro Oxigênio Medicinal',
            categoria='Medicinal',
            capacidade=Decimal('10.00'),
            unidade_medida='m³',
            preco=Decimal('150.00'),
            estoque=25
        )

        venda = Venda.objects.create(
            cliente=cliente,
            vendedor=self.user,
            status='Pendente'
        )

        item = ItemVenda.objects.create(
            venda=venda,
            produto=produto,
            forma_faturamento='cilindro',
            quantidade=3,
            peso_unitario=Decimal('10.00'),
            valor_unitario=Decimal('150.00')
        )

        # Valida cálculo do item: 3 * 150 = 450
        self.assertEqual(item.valor_total, Decimal('450.00'))

        venda.calcular_total()
        venda.refresh_from_db()
        self.assertEqual(venda.valor_total, Decimal('450.00'))

    def test_calculo_entrega_peso_total_carregado(self):
        """
        b) Testa o cálculo de Entrega.peso_total_carregado no app logistica.
        """
        veiculo = Veiculo.objects.create(
            placa='ABC-1020',
            modelo='Cargo 816',
            marca='Ford',
            ano=2020,
            capacidade_carga=Decimal('3000.00'),
            status='Ativo'
        )

        rota = Rota.objects.create(
            nome='Rota Hospitalar Central',
            origem='Base Operacional',
            destino='Centro Médico',
            distancia_km=Decimal('20.00'),
            tempo_estimado_horas=Decimal('1.00')
        )

        entrega = Entrega.objects.create(
            veiculo=veiculo,
            rota=rota,
            motorista=self.user,
            status='Agendada'
        )

        cliente = Cliente.objects.create(
            cnpj='98.765.432/0001-11',
            nome='Clínica São Marcos',
            endereco='Rua 1, 10',
            telefone='1133334444',
            estado='SP',
            cidade='São Paulo',
            proprietario='Marcos'
        )

        produto = Produto.objects.create(
            nome='Cilindro Argônio',
            categoria='Industrial',
            capacidade=Decimal('15.00'),
            unidade_medida='m³',
            preco=Decimal('200.00'),
            estoque=10
        )

        venda = Venda.objects.create(
            cliente=cliente,
            vendedor=self.user,
            entrega=entrega,
            status='Em Separação'
        )

        ItemVenda.objects.create(
            venda=venda,
            produto=produto,
            forma_faturamento='cilindro',
            quantidade=4,
            peso_unitario=Decimal('15.00'),
            valor_unitario=Decimal('200.00')
        )

        # 4 cilindros * 15.00 kg/capacidade = 60.0
        self.assertEqual(entrega.peso_total_carregado, 60.0)
        self.assertEqual(entrega.capacidade_disponivel, 2940.0)
        self.assertEqual(entrega.percentual_lotacao, 2.0)

    def test_autenticacao_jwt_login_atual(self):
        """
        c) Testa a autenticação JWT / Login atual via CustomLoginAPIView.
        """
        response = self.client.post('/accounts/api/login/', {
            'username': 'operador_teste',
            'password': 'senha_segura_123'
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['tipo_usuario'], 'VENDEDOR')
