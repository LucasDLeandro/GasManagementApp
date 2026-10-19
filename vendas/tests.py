from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import tenant_context
from clientes.models import Cliente
from produtos.models import Produto, GasQuimico, ModeloCilindro, SkuRecarga
from vendas.models import Venda, ItemVenda
from logistica.models import Entrega

User = get_user_model()


class VendaModelAndApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.hoje = timezone.now().date()

        # Tenants
        self.tenant_a = Tenant.objects.create(
            cnpj='11.111.111/0001-11',
            razao_social='Distribuidora Alfa Ltda',
            nome_fantasia='Alfa Gases',
            plano='PRO',
            ativo=True
        )
        self.tenant_b = Tenant.objects.create(
            cnpj='22.222.222/0001-22',
            razao_social='Distribuidora Beta Ltda',
            nome_fantasia='Beta Gases',
            plano='STARTER',
            ativo=True
        )

        # Usuários e Memberships
        self.user_a = User.objects.create_user(
            username='vendedor.alfa',
            password='senha_alfa_123',
            tipo_usuario='VENDEDOR'
        )
        Membership.objects.create(
            user=self.user_a,
            tenant=self.tenant_a,
            papel='VENDEDOR',
            ativo=True
        )

        with tenant_context(self.tenant_a):
            self.cliente_a = Cliente.objects.create(
                nome='Hospital Alfa Med',
                cnpj='11.222.333/0001-44',
                tipo_cliente='PJ',
                is_medicinal=True
            )
            self.produto_o2 = Produto.objects.create(
                nome='Oxigênio 10m³',
                categoria='Medicinal',
                capacidade=Decimal('10.00'),
                unidade_medida='m³',
                preco=Decimal('150.00'),
                estoque=20
            )

        with tenant_context(self.tenant_b):
            self.cliente_b = Cliente.objects.create(
                nome='Metalúrgica Beta',
                cnpj='22.333.444/0001-55',
                tipo_cliente='PJ',
                is_medicinal=False
            )
            self.produto_co2 = Produto.objects.create(
                nome='Dióxido de Carbono 25kg',
                categoria='Industrial',
                capacidade=Decimal('25.00'),
                unidade_medida='kg',
                preco=Decimal('200.00'),
                estoque=10
            )

    # ---------------------------------------------------------
    # 1. Testes de Model e Regras de Negócio
    # ---------------------------------------------------------
    def test_calcular_total_com_desconto(self):
        """Valida cálculo do valor total considerando itens e desconto comercial."""
        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                cliente=self.cliente_a,
                valor_desconto=Decimal('30.00'),
                tipo_operacao='RECARGA_TROCA',
                forma_pagamento='PIX',
                condicao_pagamento='À Vista'
            )
            # Item 1: 2x 150.00 = 300.00
            ItemVenda.objects.create(
                venda=venda,
                produto=self.produto_o2,
                quantidade=2,
                valor_unitario=Decimal('150.00')
            )
            venda.calcular_total()
            self.assertEqual(venda.valor_total, Decimal('270.00'))

    def test_calcular_total_desconto_maior_que_subtotal_nao_fica_negativo(self):
        """Garante que o valor_total nunca fica negativo mesmo com desconto excessivo."""
        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                cliente=self.cliente_a,
                valor_desconto=Decimal('500.00')
            )
            ItemVenda.objects.create(
                venda=venda,
                produto=self.produto_o2,
                quantidade=1,
                valor_unitario=Decimal('150.00')
            )
            venda.calcular_total()
            self.assertEqual(venda.valor_total, Decimal('0.00'))

    # ---------------------------------------------------------
    # 2. Testes de API DRF: Criação e Integração com Logística
    # ---------------------------------------------------------
    def test_criar_venda_api_com_gerar_entrega_logistica(self):
        """Valida que POST /vendas/api/ cria itens, baixa estoque e gera entrega na logística."""
        self.client.force_login(self.user_a)

        payload = {
            'cliente': self.cliente_a.id,
            'tipo_operacao': 'RECARGA_TROCA',
            'forma_pagamento': 'FATURADO',
            'condicao_pagamento': '30 Dias',
            'valor_desconto': '20.00',
            'documento_fiscal_ref': 'NF-99881',
            'observacoes': 'Entregar na portaria 2',
            'gerar_entrega_logistica': True,
            'itens': [
                {
                    'produto': self.produto_o2.id,
                    'forma_faturamento': 'cilindro',
                    'quantidade': 3,
                    'valor_unitario': '150.00'
                }
            ]
        }

        res = self.client.post('/vendas/api/', data=payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        venda_id = res.data['id']
        with tenant_context(self.tenant_a):
            venda = Venda.objects.get(id=venda_id)
            # 3 x 150 = 450 - 20 = 430
            self.assertEqual(venda.valor_total, Decimal('430.00'))
            self.assertEqual(venda.tipo_operacao, 'RECARGA_TROCA')
            self.assertEqual(venda.documento_fiscal_ref, 'NF-99881')
            self.assertIsNotNone(venda.entrega, "Entrega logística deveria ter sido criada e vinculada")
            self.assertEqual(venda.entrega.status, 'Agendada')
            self.assertEqual(venda.entrega.tenant, self.tenant_a)

            # Checar baixa de estoque
            self.produto_o2.refresh_from_db()
            self.assertEqual(self.produto_o2.estoque, 17)

    # ---------------------------------------------------------
    # 3. Testes de Filtro de Grupo de Status e Busca
    # ---------------------------------------------------------
    def test_filtros_grupo_status_e_busca(self):
        """Valida filtros ?grupo_status=ativas|concluidas|canceladas e ?search=."""
        self.client.force_login(self.user_a)

        with tenant_context(self.tenant_a):
            # 1. Pendente (ativa)
            v1 = Venda.objects.create(cliente=self.cliente_a, status='Pendente', documento_fiscal_ref='NF-001')
            # 2. Em Rota (ativa)
            v2 = Venda.objects.create(cliente=self.cliente_a, status='Em Rota', documento_fiscal_ref='NF-002')
            # 3. Finalizada (concluída)
            v3 = Venda.objects.create(cliente=self.cliente_a, status='Finalizada', documento_fiscal_ref='NF-003')
            # 4. Cancelada (cancelada)
            v4 = Venda.objects.create(cliente=self.cliente_a, status='Cancelada', documento_fiscal_ref='NF-004')

        # Testar ?grupo_status=ativas
        res_ativas = self.client.get('/vendas/api/?grupo_status=ativas')
        self.assertEqual(res_ativas.status_code, status.HTTP_200_OK)
        results_ativas = res_ativas.data.get('results', res_ativas.data)
        ids_ativas = [item['id'] for item in results_ativas]
        self.assertIn(v1.id, ids_ativas)
        self.assertIn(v2.id, ids_ativas)
        self.assertNotIn(v3.id, ids_ativas)
        self.assertNotIn(v4.id, ids_ativas)

        # Testar ?grupo_status=concluidas
        res_concluidas = self.client.get('/vendas/api/?grupo_status=concluidas')
        results_concluidas = res_concluidas.data.get('results', res_concluidas.data)
        ids_concluidas = [item['id'] for item in results_concluidas]
        self.assertEqual(ids_concluidas, [v3.id])

        # Testar ?grupo_status=canceladas
        res_canceladas = self.client.get('/vendas/api/?grupo_status=canceladas')
        results_canceladas = res_canceladas.data.get('results', res_canceladas.data)
        ids_canceladas = [item['id'] for item in results_canceladas]
        self.assertEqual(ids_canceladas, [v4.id])

        # Testar busca por documento fiscal
        res_busca = self.client.get('/vendas/api/?search=NF-002')
        results_busca = res_busca.data.get('results', res_busca.data)
        self.assertEqual(len(results_busca), 1)
        self.assertEqual(results_busca[0]['id'], v2.id)

    # ---------------------------------------------------------
    # 4. Teste de Métricas do Dashboard e Isolamento de Tenant
    # ---------------------------------------------------------
    def test_dashboard_metrics_isolamento_tenant(self):
        """Valida que dashboard_metrics calcula faturamento, contagens e gráficos restritos ao tenant."""
        self.client.force_login(self.user_a)

        with tenant_context(self.tenant_a):
            venda_a = Venda.objects.create(cliente=self.cliente_a, status='Pendente', valor_total=Decimal('300.00'))
            ItemVenda.objects.create(venda=venda_a, produto=self.produto_o2, quantidade=2, valor_total=Decimal('300.00'))

        with tenant_context(self.tenant_b):
            venda_b = Venda.objects.create(cliente=self.cliente_b, status='Finalizada', valor_total=Decimal('800.00'))
            ItemVenda.objects.create(venda=venda_b, produto=self.produto_co2, quantidade=4, valor_total=Decimal('800.00'))

        res = self.client.get('/vendas/api/dashboard_metrics/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        dados = res.data

        # Tenant A deve ver apenas sua venda de 300,00 e 1 venda pendente
        self.assertEqual(dados['faturamento_total'], 300.0)
        self.assertEqual(dados['total_vendas'], 1)
        self.assertEqual(dados['vendas_pendentes'], 1)
        self.assertEqual(dados['vendas_em_entrega'], 0)

        # Formato de data dd/mm no gráfico
        self.assertGreater(len(dados['grafico']), 0)
        dia_formatado = dados['grafico'][0]['dia']
        self.assertRegex(dia_formatado, r'^\d{2}/\d{2}$', f"Data do gráfico deveria estar no formato dd/mm, veio {dia_formatado}")

        # Top produtos deve listar apenas o produto de Tenant A
        top_nomes = [tp['nome'] for tp in dados['top_produtos']]
        self.assertIn(self.produto_o2.nome, top_nomes)
        self.assertNotIn(self.produto_co2.nome, top_nomes)

    # ---------------------------------------------------------
    # 5. Teste de Ações Rápidas (Alterar Status e Enviar para Logística)
    # ---------------------------------------------------------
    def test_actions_alterar_status_e_enviar_para_logistica(self):
        """Valida actions alterar_status e enviar_para_logistica com transição de entrega."""
        self.client.force_login(self.user_a)

        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(cliente=self.cliente_a, status='Pendente', valor_total=Decimal('150.00'))

        # 1. Enviar para logística
        res = self.client.post(f'/vendas/api/{venda.id}/enviar_para_logistica/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        with tenant_context(self.tenant_a):
            venda.refresh_from_db()
            self.assertEqual(venda.status, 'Em Separação')
            self.assertIsNotNone(venda.entrega)

        # 2. Alterar status para Finalizada
        res2 = self.client.post(f'/vendas/api/{venda.id}/alterar_status/', data={'status': 'Finalizada'}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        with tenant_context(self.tenant_a):
            venda.refresh_from_db()
            self.assertEqual(venda.status, 'Finalizada')
