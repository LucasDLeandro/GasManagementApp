import uuid
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant, Membership
from core.tenancy import (
    TenantNotSet,
    get_current_tenant,
    set_current_tenant,
    reset_current_tenant,
    tenant_context
)
from datetime import timedelta
from django.utils import timezone

from clientes.models import Cliente
from produtos.models import Produto, GasQuimico, ModeloCilindro, LoteEnvase, Cilindro, EnvaseCilindro
from vendas.models import Venda
from logistica.models import Veiculo

User = get_user_model()

class TenancyIsolationTests(TestCase):
    """
    Testes de isolamento obrigatórios para a arquitetura Multi-Tenant Fail-Closed.
    Garante:
    1. Impossibilidade de consultar modelos protegidos fora de um tenant_context (Fail-Closed).
    2. Isolamento de dados entre diferentes Tenants (Tenant A não vê registros do Tenant B).
    3. Proteção no nível de API/ViewSet com retorno 404 ao tentar acessar recursos de outro Tenant.
    """

    def setUp(self):
        # Garante que iniciamos sem tenant no contexto
        set_current_tenant(None)

        self.client = APIClient()

        # Criar Tenant A (Oxigênio Brasília)
        self.tenant_a = Tenant.objects.create(
            id=uuid.UUID('11111111-1111-1111-1111-111111111111'),
            cnpj='11.111.111/0001-11',
            razao_social='Oxigênio Brasília Ltda',
            nome_fantasia='Oxigênio Brasília',
            plano='PRO'
        )

        # Criar Tenant B (Gases Goiás)
        self.tenant_b = Tenant.objects.create(
            id=uuid.UUID('22222222-2222-2222-2222-222222222222'),
            cnpj='22.222.222/0001-22',
            razao_social='Gases Goiás S/A',
            nome_fantasia='Gases Goiás',
            plano='ENTERPRISE'
        )

        # Usuário do Tenant A
        self.user_a = User.objects.create_user(
            username='gerente_brasilia',
            password='senha_forte_123',
            tipo_usuario='GERENTE'
        )
        Membership.objects.create(
            user=self.user_a,
            tenant=self.tenant_a,
            papel='GERENTE',
            ativo=True
        )

        # Usuário do Tenant B
        self.user_b = User.objects.create_user(
            username='gerente_goias',
            password='senha_forte_123',
            tipo_usuario='GERENTE'
        )
        Membership.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            papel='GERENTE',
            ativo=True
        )

    def test_fail_closed_raises_tenant_not_set_outside_context(self):
        """
        1. Prova que tentar dar .objects.all() fora de tenant_context lança TenantNotSet.
        """
        self.assertIsNone(get_current_tenant())

        with self.assertRaises(TenantNotSet):
            list(Cliente.objects.all())

        with self.assertRaises(TenantNotSet):
            list(Produto.objects.all())

        with self.assertRaises(TenantNotSet):
            list(Venda.objects.all())

        with self.assertRaises(TenantNotSet):
            list(Veiculo.objects.all())

        # Prova que o acesso irrestrito funciona exclusivamente via .unscoped
        self.assertIsNotNone(Cliente.unscoped.all())

    def test_data_isolation_between_tenants(self):
        """
        2. Prova que dados criados no Tenant A retornam 0 registros quando consultados no Tenant B.
        """
        # Criar dados no Tenant A
        with tenant_context(self.tenant_a):
            cliente_a = Cliente.objects.create(
                cnpj='11.123.456/0001-99',
                nome='Hospital Base Brasília',
                endereco='Asa Sul',
                telefone='6133334444',
                estado='DF',
                cidade='Brasília',
                proprietario='Governo DF'
            )
            produto_a = Produto.objects.create(
                nome='Oxigênio Medicinal 10m³',
                categoria='Medicinal',
                capacidade=Decimal('10.00'),
                unidade_medida='m³',
                preco=Decimal('170.00'),
                estoque=30
            )
            venda_a = Venda.objects.create(
                cliente=cliente_a,
                vendedor=self.user_a,
                status='Pendente'
            )

            self.assertEqual(Cliente.objects.count(), 1)
            self.assertEqual(Produto.objects.count(), 1)
            self.assertEqual(Venda.objects.count(), 1)

        # Consultar no contexto do Tenant B
        with tenant_context(self.tenant_b):
            self.assertEqual(Cliente.objects.count(), 0)
            self.assertEqual(Produto.objects.count(), 0)
            self.assertEqual(Venda.objects.count(), 0)
            self.assertFalse(Cliente.objects.filter(id=cliente_a.id).exists())
            self.assertFalse(Venda.objects.filter(id=venda_a.id).exists())

            # Criar dados no Tenant B
            cliente_b = Cliente.objects.create(
                cnpj='22.987.654/0001-88',
                nome='Hospital Santa Helena Goiânia',
                endereco='Setor Bueno',
                telefone='6233335555',
                estado='GO',
                cidade='Goiânia',
                proprietario='Dra. Lúcia'
            )
            self.assertEqual(Cliente.objects.count(), 1)
            self.assertEqual(Cliente.objects.first().id, cliente_b.id)

        # Confirmar que Tenant A continua vendo apenas os seus dados
        with tenant_context(self.tenant_a):
            self.assertEqual(Cliente.objects.count(), 1)
            self.assertEqual(Cliente.objects.first().id, cliente_a.id)

    def test_api_viewset_isolation_returns_404_for_other_tenant(self):
        """
        3. Prova que uma view/API autenticada com usuário do Tenant A recebe 404
           ao tentar acessar o ID de um Cliente ou Venda do Tenant B.
        """
        # Cria Cliente e Venda no Tenant B
        with tenant_context(self.tenant_b):
            cliente_b = Cliente.objects.create(
                cnpj='22.555.666/0001-77',
                nome='Clínica Privada Goiânia',
                endereco='Av. T-63',
                telefone='62988889999',
                estado='GO',
                cidade='Goiânia',
                proprietario='Dr. Paulo'
            )
            venda_b = Venda.objects.create(
                cliente=cliente_b,
                vendedor=self.user_b,
                status='Pendente'
            )

        # Autentica como Usuário do Tenant A via JWT
        token_user_a = RefreshToken.for_user(self.user_a).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(token_user_a)}')

        # Tentativa de acessar Cliente e Venda do Tenant B pelo Tenant A -> Deve retornar 404 Not Found
        response_cliente = self.client.get(f'/clientes/api/{cliente_b.id}/')
        self.assertEqual(response_cliente.status_code, 404)

        response_venda = self.client.get(f'/vendas/api/{venda_b.id}/')
        self.assertEqual(response_venda.status_code, 404)

        # Agora autentica como Usuário do Tenant B -> Deve retornar 200 OK
        token_user_b = RefreshToken.for_user(self.user_b).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(token_user_b)}')

        response_cliente_b = self.client.get(f'/clientes/api/{cliente_b.id}/')
        self.assertEqual(response_cliente_b.status_code, 200)
        self.assertEqual(response_cliente_b.data['nome'], 'Clínica Privada Goiânia')

        response_venda_b = self.client.get(f'/vendas/api/{venda_b.id}/')
        self.assertEqual(response_venda_b.status_code, 200)

    def test_token_lifecycle_and_reset_enforcement(self):
        """
        4. Valida o ciclo de vida estrito do token de tenant:
        - set_current_tenant define o tenant e retorna token.
        - reset_current_tenant com o token limpa/restaura o contexto.
        - Tentar dar reset pela segunda vez no mesmo token LANÇA RuntimeError (fail-closed de concorrência).
        - tenant_context executa com segurança e restaura o estado anterior.
        """
        set_current_tenant(None)
        self.assertIsNone(get_current_tenant())

        token_a = set_current_tenant(self.tenant_a)
        self.assertEqual(get_current_tenant(), self.tenant_a)

        # Reset limpa o contexto
        reset_current_tenant(token_a)
        self.assertIsNone(get_current_tenant())

        # Reset duplo com o mesmo token DEVE lançar RuntimeError
        with self.assertRaises(RuntimeError):
            reset_current_tenant(token_a)

        # tenant_context aninhado
        with tenant_context(self.tenant_a):
            self.assertEqual(get_current_tenant(), self.tenant_a)
            with tenant_context(self.tenant_b):
                self.assertEqual(get_current_tenant(), self.tenant_b)
            self.assertEqual(get_current_tenant(), self.tenant_a)
        self.assertIsNone(get_current_tenant())

    def test_cross_tenant_recall_cilindro_and_envase_isolation(self):
        """
        5. Prova que endpoints de Recall, Cilindro e Envase retornam 404 Not Found
        ao serem consultados por usuário de outro tenant, e rejeitam spoofing via X-Tenant-ID.
        """
        hoje = timezone.now().date()
        agora = timezone.now()

        gas, _ = GasQuimico.objects.get_or_create(
            sigla='O2-MED-ISOL',
            defaults={
                'nome': 'Oxigênio Medicinal Isolamento',
                'categoria': 'MEDICINAL',
                'numero_onu': '1072',
                'classe_risco': '2.2',
                'cor_padrao_abnt': 'Verde',
                'exige_lote_anvisa': True
            }
        )

        # Criar Modelo, Lote, Cilindro e Envase no Tenant B
        with tenant_context(self.tenant_b):
            modelo, _ = ModeloCilindro.objects.get_or_create(
                descricao='Cilindro Aço 50L Isolamento',
                defaults={
                    'material': 'ACO',
                    'volume_hidraulico_litros': Decimal('50.00'),
                    'pressao_servico_bar': 200,
                    'tara_nominal_kg': Decimal('60.00'),
                    'padrao_valvula_abnt': 'ABNT 218-1',
                    'periodicidade_reteste_anos': 5
                }
            )
            lote_b = LoteEnvase.objects.create(
                gas=gas,
                codigo_lote='LOTE-B-CONFIDENCIAL',
                data_envase=hoje - timedelta(days=5),
                data_validade=hoje + timedelta(days=365),
                pureza_percentual=Decimal('99.80'),
                responsavel_tecnico='Dra. Goiás CRF-GO 9999'
            )
            cilindro_b = Cilindro.objects.create(
                codigo_qr='QR-TENANT-B-001',
                numero_serie_ogiva='SN-TB-001',
                fabricante='Mannesmann',
                ano_fabricacao=2022,
                modelo=modelo,
                gas_dedicado=gas,
                tara_real_kg=Decimal('59.50'),
                data_ultimo_reteste=hoje - timedelta(days=365),
                data_proximo_reteste=hoje + timedelta(days=365 * 4),
                status='CHEIO_DISPONIVEL'
            )
            envase_b = EnvaseCilindro.objects.create(
                cilindro=cilindro_b,
                lote=lote_b,
                pressao_final_bar=200,
                envasado_em=agora - timedelta(days=4),
                operador=self.user_b,
                observacoes='Envase exclusivo Tenant B'
            )
            cilindro_b.envase_atual = envase_b
            cilindro_b.save(update_fields=['envase_atual'])

        # Autentica como Usuário do Tenant A
        token_user_a = RefreshToken.for_user(self.user_a).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(token_user_a)}')

        # 1. Recall API com Lote do Tenant B -> Deve retornar 404 Not Found
        res_recall = self.client.get(f'/produtos/api/lotes-anvisa/recall/?codigo_lote={lote_b.codigo_lote}')
        self.assertEqual(res_recall.status_code, 404)

        # 2. Detalhe de Cilindro do Tenant B -> Deve retornar 404 Not Found
        res_cilindro = self.client.get(f'/produtos/api/cilindros/{cilindro_b.id}/')
        self.assertEqual(res_cilindro.status_code, 404)

        # 3. Detalhe de Envase do Tenant B -> Deve retornar 404 Not Found
        res_envase = self.client.get(f'/produtos/api/envases/{envase_b.id}/')
        self.assertEqual(res_envase.status_code, 404)

        # 4. Listagem de Lotes do Tenant A não contém o lote do Tenant B
        res_lotes_list = self.client.get('/produtos/api/lotes-anvisa/')
        self.assertEqual(res_lotes_list.status_code, 200)
        codigos = [item['codigo_lote'] for item in res_lotes_list.data]
        self.assertNotIn(lote_b.codigo_lote, codigos)

        # 5. Tentativa de Spoofing via Header X-Tenant-ID do Tenant B por Usuário A
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(token_user_a)}',
            HTTP_X_TENANT_ID=str(self.tenant_b.id)
        )
        res_spoofing = self.client.get(f'/produtos/api/cilindros/{cilindro_b.id}/')
        self.assertEqual(res_spoofing.status_code, 404)

        # 6. Autentica como Usuário do Tenant B -> Acesso com 200 OK
        token_user_b = RefreshToken.for_user(self.user_b).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(token_user_b)}')

        res_recall_b = self.client.get(f'/produtos/api/lotes-anvisa/recall/?codigo_lote={lote_b.codigo_lote}')
        self.assertEqual(res_recall_b.status_code, 200)
        self.assertEqual(res_recall_b.data['lote']['codigo_lote'], lote_b.codigo_lote)

        res_cilindro_b = self.client.get(f'/produtos/api/cilindros/{cilindro_b.id}/')
        self.assertEqual(res_cilindro_b.status_code, 200)
        self.assertEqual(res_cilindro_b.data['codigo_qr'], 'QR-TENANT-B-001')

        res_envase_b = self.client.get(f'/produtos/api/envases/{envase_b.id}/')
        self.assertEqual(res_envase_b.status_code, 200)
        self.assertEqual(res_envase_b.data['lote_codigo'], lote_b.codigo_lote)
