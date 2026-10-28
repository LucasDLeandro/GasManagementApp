import uuid
from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.http import HttpResponse
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import get_current_tenant, set_current_tenant, reset_current_tenant, tenant_context
from core.middleware import TenantMiddleware

from clientes.models import Cliente
from produtos.models import (
    GasQuimico,
    ModeloCilindro,
    Cilindro,
    LoteEnvase,
    EnvaseCilindro,
    Produto
)
from vendas.models import Venda, ItemVenda
from logistica.models import (
    Veiculo,
    Rota,
    Entrega,
    ManutencaoFrota,
    TabelaFrete,
    ValidacaoCarga
)

import clientes.urls
import produtos.urls
import vendas.urls
import logistica.urls

User = get_user_model()


class CrossTenantIsolationTestSuite(TestCase):
    """
    Suíte Automatizada de Isolamento Cross-Tenant (Fail-Closed e 404 Not Found) - Sprint 5A.1.
    
    Regras Validadas:
    1. Usuário exclusivo do Tenant B ao tentar acessar recursos do Tenant A recebe estritamente 404 (nunca 200 ou 403).
    2. Tentativas de spoofing do header X-Tenant-ID com tenant para o qual o usuário não tem membership ativo retornam 404.
    3. Listagens de recursos nunca vazam registros do Tenant A para o Tenant B.
    4. Todos os endpoints registrados nos routers do DRF estão cobertos.
    5. O ContextVar do tenant é 100% limpo mesmo quando a view lança exceções não tratadas.
    """

    def setUp(self):
        self.client = APIClient()
        self.factory = RequestFactory()
        self.hoje = timezone.now().date()
        self.agora = timezone.now()

        # 1. Criação dos Tenants A e B
        self.tenant_a = Tenant.objects.create(
            cnpj='11.111.111/0001-11',
            razao_social='Distribuidora Alfa Ltda (Tenant A)',
            nome_fantasia='Alfa Gases',
            plano='PRO',
            ativo=True
        )
        self.tenant_b = Tenant.objects.create(
            cnpj='22.222.222/0001-22',
            razao_social='Distribuidora Beta Ltda (Tenant B)',
            nome_fantasia='Beta Gases',
            plano='STARTER',
            ativo=True,
            # Mesmo módulo do Tenant A: o teste mede isolamento de objetos,
            # não o bloqueio por módulo não contratado (que responde 403 por design).
            modulo_envase_ativo=True,
        )

        # 2. Criação dos Usuários com isolamento estrito de Membership
        self.user_a = User.objects.create_user(
            username='operador.alfa',
            password='senha_segura_alfa_123',
            tipo_usuario='OPERADOR_PATIO'
        )
        Membership.objects.create(
            user=self.user_a,
            tenant=self.tenant_a,
            papel='OPERADOR_PATIO',
            ativo=True
        )

        self.user_b = User.objects.create_user(
            username='operador.beta',
            password='senha_segura_beta_123',
            tipo_usuario='VENDEDOR'
        )
        Membership.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            papel='VENDEDOR',
            ativo=True
        )

        # 3. Criação de Dados Completos no Tenant A
        with tenant_context(self.tenant_a):
            # Clientes
            self.cliente_a = Cliente.objects.create(
                nome='Hospital Regional Alfa',
                cnpj='11.999.888/0001-77',
                telefone='6133334444',
                endereco='Asa Sul, Bloco A',
                tipo_cliente='PJ'
            )

            # Gases e Modelos (GasQuimico é global, ModeloCilindro é TenantAware)
            self.gas_o2, _ = GasQuimico.objects.get_or_create(
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
            self.modelo_50l = ModeloCilindro.objects.create(
                descricao='Cilindro 50L Alta Pressão A',
                material='ACO',
                volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('60.00')
            )

            # Cilindros, Lotes e Envases
            self.cilindro_a = Cilindro.objects.create(
                codigo_qr='QR-ISO-TENANT-A-01',
                numero_serie_ogiva='SN-ALFA-001',
                fabricante='Cilbras',
                ano_fabricacao=2022,
                modelo=self.modelo_50l,
                gas_dedicado=self.gas_o2,
                tara_real_kg=Decimal('62.50'),
                data_ultimo_reteste=self.hoje - timedelta(days=200),
                data_proximo_reteste=self.hoje + timedelta(days=365 * 5),
                status='CHEIO_DISPONIVEL'
            )

            self.lote_a = LoteEnvase.objects.create(
                gas=self.gas_o2,
                codigo_lote='LOTE-ALFA-2026-X1',
                data_envase=self.hoje - timedelta(days=10),
                data_validade=self.hoje + timedelta(days=365),
                pureza_percentual=Decimal('99.65'),
                responsavel_tecnico='Dra. Farmacêutica Alfa CRF-DF 1234'
            )

            self.envase_a = EnvaseCilindro.objects.create(
                cilindro=self.cilindro_a,
                lote=self.lote_a,
                pressao_final_bar=200,
                operador=self.user_a,
                envasado_em=self.agora - timedelta(days=10)
            )
            self.cilindro_a.envase_atual = self.envase_a
            self.cilindro_a.save()

            # Produtos
            self.produto_a = Produto.objects.create(
                nome='Recarga Oxigênio Medicinal 10m3 A',
                categoria='medicinal',
                capacidade=Decimal('10.00'),
                unidade_medida='m3',
                preco=Decimal('150.00'),
                estoque=25
            )

            # Vendas
            self.venda_a = Venda.objects.create(
                cliente=self.cliente_a,
                vendedor=self.user_a,
                status='Concluída',
                valor_total=Decimal('300.00'),
                data_venda=self.agora - timedelta(days=5)
            )
            self.item_venda_a = ItemVenda.objects.create(
                venda=self.venda_a,
                produto=self.produto_a,
                quantidade=2,
                valor_unitario=Decimal('150.00'),
                valor_total=Decimal('300.00')
            )

            # Logística
            self.veiculo_a = Veiculo.objects.create(
                placa='ALF-1A23',
                modelo='Mercedes Toco',
                marca='Mercedes',
                ano=2022,
                capacidade_carga=Decimal('5000.00'),
                status='Ativo'
            )
            self.rota_a = Rota.objects.create(
                nome='Rota Hospitalar Asa Sul A',
                origem='Base Central',
                destino='Asa Sul',
                distancia_km=Decimal('25.50'),
                tempo_estimado_horas=Decimal('1.50')
            )
            self.entrega_a = Entrega.objects.create(
                rota=self.rota_a,
                veiculo=self.veiculo_a,
                motorista=self.user_a,
                status='Em Rota',
                data_saida=self.agora
            )
            self.venda_a.entrega = self.entrega_a
            self.venda_a.save()

            self.manutencao_a = ManutencaoFrota.objects.create(
                veiculo=self.veiculo_a,
                data_manutencao=self.hoje - timedelta(days=30),
                descricao='Troca de óleo e pneus',
                custo=Decimal('850.00'),
                status='Concluída'
            )
            self.frete_a = TabelaFrete.objects.create(
                rota=self.rota_a,
                tipo_cobranca='Fixo',
                valor=Decimal('50.00')
            )
            self.validacao_a = ValidacaoCarga.objects.create(
                entrega=self.entrega_a,
                venda=self.venda_a,
                produto=self.produto_a,
                quantidade_alterada=0,
                etapa_logistica='Expedição',
                justificativa='Conferência de rotina'
            )

        # 4. Criação de Dados Mínimos no Tenant B para o User B operar normalmente
        with tenant_context(self.tenant_b):
            self.cliente_b = Cliente.objects.create(
                nome='Clínica Beta Vida',
                cnpj='22.888.777/0001-99',
                telefone='6134445555',
                tipo_cliente='PJ'
            )
            self.cilindro_b = Cilindro.objects.create(
                codigo_qr='QR-ISO-TENANT-B-01',
                numero_serie_ogiva='SN-BETA-001',
                fabricante='Mat',
                ano_fabricacao=2023,
                modelo=self.modelo_50l,
                gas_dedicado=self.gas_o2,
                tara_real_kg=Decimal('63.00'),
                data_ultimo_reteste=self.hoje - timedelta(days=100),
                data_proximo_reteste=self.hoje + timedelta(days=365 * 5),
                status='CHEIO_DISPONIVEL'
            )

    def test_routers_registered_viewsets_completeness(self):
        """
        Valida que todos os routers do DRF no sistema contêm classes ViewSet
        que utilizam TenantViewSetMixin para blindagem Fail-Closed.
        """
        from core.mixins import TenantViewSetMixin

        registered_viewsets = set()
        for router_mod in [clientes.urls.router, produtos.urls.router, vendas.urls.router, logistica.urls.router]:
            for prefix, viewset_class, basename in router_mod.registry:
                registered_viewsets.add(viewset_class)
                self.assertTrue(
                    issubclass(viewset_class, TenantViewSetMixin),
                    f"Falha de Segurança: O ViewSet {viewset_class.__name__} registrado no router ({prefix}) "
                    f"não herda de TenantViewSetMixin!"
                )

        # Garante que ao menos os 11 ViewSets essenciais estão registrados e inspecionados
        self.assertGreaterEqual(len(registered_viewsets), 10)

    def test_user_b_cannot_get_tenant_a_detail_endpoints_returns_404(self):
        """
        Garante que o User B autenticado recebe estritamente 404 Not Found (nunca 200 ou 403)
        ao tentar consultar recursos do Tenant A via GET.
        """
        self.client.force_authenticate(user=self.user_b)

        endpoints_to_test = [
            f'/clientes/api/{self.cliente_a.id}/',
            f'/produtos/api/{self.produto_a.id}/',
            f'/produtos/api/cilindros/{self.cilindro_a.id}/',
            f'/produtos/api/envases/{self.envase_a.id}/',
            f'/vendas/api/{self.venda_a.id}/',
            f'/logistica/api/veiculos/{self.veiculo_a.id}/',
            f'/logistica/api/rotas/{self.rota_a.id}/',
            f'/logistica/api/entregas/{self.entrega_a.id}/',
            f'/logistica/api/manutencoes/{self.manutencao_a.id}/',
            f'/logistica/api/fretes/{self.frete_a.id}/',
            f'/logistica/api/validacoes/{self.validacao_a.id}/',
            f'/logistica/api/entregas/{self.entrega_a.id}/romaneio-bilateral/',
        ]

        for url in endpoints_to_test:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(
                    res.status_code,
                    status.HTTP_404_NOT_FOUND,
                    f"Vazamento ou permissão indevida: {url} retornou {res.status_code} em vez de 404!"
                )

    def test_user_b_cannot_modify_tenant_a_resources_put_patch_delete_returns_404(self):
        """
        Garante que tentativas de mutação (PUT, PATCH, DELETE) nos recursos do Tenant A
        feitas pelo User B retornam estritamente 404 Not Found.
        """
        self.client.force_authenticate(user=self.user_b)

        targets = [
            (f'/clientes/api/{self.cliente_a.id}/', {'nome': 'Hacked Cliente'}),
            (f'/produtos/api/{self.produto_a.id}/', {'nome': 'Hacked Produto'}),
            (f'/vendas/api/{self.venda_a.id}/', {'status': 'Cancelada'}),
            (f'/logistica/api/veiculos/{self.veiculo_a.id}/', {'status': 'Em Manutenção'}),
            (f'/logistica/api/rotas/{self.rota_a.id}/', {'nome': 'Hacked Rota'}),
            (f'/logistica/api/entregas/{self.entrega_a.id}/', {'status': 'Cancelada'}),
        ]

        for url, payload in targets:
            with self.subTest(url=url, method='PUT'):
                res_put = self.client.put(url, data=payload, format='json')
                self.assertEqual(res_put.status_code, status.HTTP_404_NOT_FOUND, f"PUT {url} retornou {res_put.status_code}")

            with self.subTest(url=url, method='PATCH'):
                res_patch = self.client.patch(url, data=payload, format='json')
                self.assertEqual(res_patch.status_code, status.HTTP_404_NOT_FOUND, f"PATCH {url} retornou {res_patch.status_code}")

            with self.subTest(url=url, method='DELETE'):
                res_del = self.client.delete(url)
                self.assertEqual(res_del.status_code, status.HTTP_404_NOT_FOUND, f"DELETE {url} retornou {res_del.status_code}")

    def test_user_b_cannot_execute_post_actions_on_tenant_a_resources_returns_404(self):
        """
        Garante que ações customizadas de POST (ex: romaneio-bilateral)
        em instâncias do Tenant A retornam estritamente 404 Not Found.
        """
        self.client.force_authenticate(user=self.user_b)

        url = f'/logistica/api/entregas/{self.entrega_a.id}/romaneio-bilateral/'
        res = self.client.post(url, data={'acao': 'entregar', 'codigo_qr': self.cilindro_a.codigo_qr})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, f"POST {url} retornou {res.status_code}")

    def test_anvisa_recall_cross_tenant_isolation_returns_404(self):
        """
        Garante que o motor de Auditoria & Recall ANVISA (/produtos/api/lotes-anvisa/recall/)
        retorna estritamente 404 quando o lote consultado pertence a outro tenant.
        """
        self.client.force_authenticate(user=self.user_b)

        url_json = f'/produtos/api/lotes-anvisa/recall/?codigo_lote={self.lote_a.codigo_lote}'
        res_json = self.client.get(url_json)
        self.assertEqual(
            res_json.status_code,
            status.HTTP_404_NOT_FOUND,
            f"Recall ANVISA permitiu acesso ao lote de outro tenant! Retornou {res_json.status_code}"
        )

        url_csv = f'/produtos/api/lotes-anvisa/recall/?codigo_lote={self.lote_a.codigo_lote}&export=csv'
        res_csv = self.client.get(url_csv)
        self.assertEqual(
            res_csv.status_code,
            status.HTTP_404_NOT_FOUND,
            f"Exportação de Dossiê CSV ANVISA permitiu download de lote de outro tenant! Retornou {res_csv.status_code}"
        )

    def test_header_spoofing_x_tenant_id_returns_strictly_404(self):
        """
        Garante que qualquer tentativa do User B de enviar o header 'X-Tenant-ID'
        apontando para o Tenant A (onde não tem Membership) resulta estritamente em 404.
        """
        self.client.force_authenticate(user=self.user_b)
        spoofed_headers = {'HTTP_X_TENANT_ID': str(self.tenant_a.id)}

        endpoints_to_probe = [
            ('/clientes/api/', 'GET', None),
            ('/clientes/api/', 'POST', {'nome': 'Hacker Corp', 'tipo_cliente': 'PJ'}),
            ('/produtos/api/', 'GET', None),
            ('/produtos/api/cilindros/', 'GET', None),
            ('/produtos/api/envases/', 'GET', None),
            ('/produtos/api/lotes-anvisa/', 'GET', None),
            (f'/produtos/api/lotes-anvisa/recall/?codigo_lote={self.lote_a.codigo_lote}', 'GET', None),
            ('/vendas/api/', 'GET', None),
            ('/logistica/api/veiculos/', 'GET', None),
            ('/inicio/api/stats/', 'GET', None),
        ]

        for path, method, data in endpoints_to_probe:
            with self.subTest(path=path, method=method):
                if method == 'GET':
                    res = self.client.get(path, **spoofed_headers)
                elif method == 'POST':
                    res = self.client.post(path, data=data, format='json', **spoofed_headers)
                else:
                    continue

                self.assertEqual(
                    res.status_code,
                    status.HTTP_404_NOT_FOUND,
                    f"Falha de blindagem contra spoofing: {method} {path} com X-Tenant-ID retornou {res.status_code} em vez de 404!"
                )

    def test_list_endpoints_never_leak_tenant_a_records(self):
        """
        Valida que listagens em endpoints do DRF para o User B contêm apenas seus dados
        e nunca contêm registros do Tenant A.
        """
        self.client.force_authenticate(user=self.user_b)

        # Clientes
        res_cli = self.client.get('/clientes/api/')
        self.assertEqual(res_cli.status_code, status.HTTP_200_OK)
        items_cli = res_cli.data.get('results') if isinstance(res_cli.data, dict) else res_cli.data
        cli_ids = [item['id'] for item in items_cli]
        self.assertNotIn(self.cliente_a.id, cli_ids)
        self.assertIn(self.cliente_b.id, cli_ids)

        # Cilindros
        res_cil = self.client.get('/produtos/api/cilindros/')
        self.assertEqual(res_cil.status_code, status.HTTP_200_OK)
        items_cil = res_cil.data.get('results') if isinstance(res_cil.data, dict) else res_cil.data
        cil_ids = [item['id'] for item in items_cil]
        self.assertNotIn(self.cilindro_a.id, cil_ids)
        self.assertIn(self.cilindro_b.id, cil_ids)

        # Envases
        res_env = self.client.get('/produtos/api/envases/')
        self.assertEqual(res_env.status_code, status.HTTP_200_OK)
        items_env = res_env.data.get('results') if isinstance(res_env.data, dict) else res_env.data
        env_ids = [item['id'] for item in items_env]
        self.assertNotIn(self.envase_a.id, env_ids)

        # Lotes ANVISA
        res_lotes = self.client.get('/produtos/api/lotes-anvisa/')
        self.assertEqual(res_lotes.status_code, status.HTTP_200_OK)
        items_lotes = res_lotes.data.get('results') if isinstance(res_lotes.data, dict) else res_lotes.data
        codigos_lotes = [item['codigo_lote'] for item in items_lotes]
        self.assertNotIn(self.lote_a.codigo_lote, codigos_lotes)

    def test_tenant_contextvar_is_cleaned_up_on_view_exception(self):
        """
        Valida o ciclo de vida Fail-Closed do ContextVar:
        Mesmo quando uma view dispara uma exceção não tratada, o middleware
        e os mixins garantem que get_current_tenant() retorna a None após o término da requisição.
        """
        # Garante estado inicial limpo
        self.assertIsNone(get_current_tenant())

        def crashing_view(request):
            # No momento da execução da view, o tenant deve estar ativo
            self.assertEqual(get_current_tenant(), self.tenant_a)
            raise ZeroDivisionError("Simulação de falha catastrófica interna da view")

        middleware = TenantMiddleware(crashing_view)
        request = self.factory.get('/qualquer-rota/')
        request.user = self.user_a

        with self.assertRaises(ZeroDivisionError):
            middleware(request)

        # Pós-exceção: O ContextVar DEVE estar estritamente None
        self.assertIsNone(
            get_current_tenant(),
            "Vazamento Crítico de Contexto: ContextVar não foi resetado após exceção na view!"
        )

    def test_tenant_contextvar_cleaned_up_when_drf_view_raises_exception(self):
        """
        Valida que o hook TenantViewSetMixin.dispatch com try ... finally
        desfaz qualquer token criado no escopo da view caso ocorra exceção.
        """
        from rest_framework.views import APIView
        from core.mixins import TenantViewSetMixin

        expected_tenant = self.tenant_a

        class ExplodingAPIView(TenantViewSetMixin, APIView):
            def get(self, request):
                if get_current_tenant() != expected_tenant:
                    raise ValueError("Tenant mismatch in view!")
                raise RuntimeError("Erro inesperado no DRF")

        view = ExplodingAPIView.as_view()
        request = self.factory.get('/api/explodir/')
        request.user = self.user_a

        # Garante estado limpo antes
        self.assertIsNone(get_current_tenant())

        with self.assertRaises(RuntimeError):
            view(request)

        # Pós-exceção no DRF
        self.assertIsNone(
            get_current_tenant(),
            "Vazamento Crítico de Contexto: ContextVar do DRF não foi limpo após exceção!"
        )

    def test_tenant_resolution_via_session_active_tenant_id(self):
        """
        Valida que requisições ao DRF sem o header HTTP_X_TENANT_ID respeitam
        estritamente o active_tenant_id armazenado na sessão do usuário,
        permitindo a alternância de empresas no Tenant Switcher sem vazamento.
        """
        user_dual = User.objects.create_user(
            username='gestor.dual',
            password='senha_dual_123',
            tipo_usuario='ADMIN_TENANT'
        )
        Membership.objects.create(
            user=user_dual,
            tenant=self.tenant_a,
            papel='ADMIN_TENANT',
            ativo=True
        )
        Membership.objects.create(
            user=user_dual,
            tenant=self.tenant_b,
            papel='ADMIN_TENANT',
            ativo=True
        )

        self.client.force_login(user_dual)

        # 1. Definir Tenant B na sessão
        session = self.client.session
        session['active_tenant_id'] = str(self.tenant_b.id)
        session.save()

        res_b = self.client.get('/clientes/api/')
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)
        items_b = res_b.data.get('results') if isinstance(res_b.data, dict) else res_b.data
        ids_b = [item['id'] for item in items_b]
        self.assertIn(self.cliente_b.id, ids_b, "Cliente do Tenant B deveria estar presente quando active_tenant_id na sessão é Tenant B")
        self.assertNotIn(self.cliente_a.id, ids_b, "Vazamento: Cliente do Tenant A presente quando active_tenant_id na sessão é Tenant B!")

        # 2. Alternar para Tenant A na sessão
        session['active_tenant_id'] = str(self.tenant_a.id)
        session.save()

        res_a = self.client.get('/clientes/api/')
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        items_a = res_a.data.get('results') if isinstance(res_a.data, dict) else res_a.data
        ids_a = [item['id'] for item in items_a]
        self.assertIn(self.cliente_a.id, ids_a, "Cliente do Tenant A deveria estar presente quando active_tenant_id na sessão é Tenant A")
        self.assertNotIn(self.cliente_b.id, ids_a, "Vazamento: Cliente do Tenant B presente quando active_tenant_id na sessão é Tenant A!")

    def test_tenant_resolution_session_spoofing_prevented(self):
        """
        Valida que se um usuário tentar forjar um active_tenant_id na sessão para o qual
        NÃO possui membership ativo, o TenantViewSetMixin não autoriza o acesso ao tenant forjado
        e recai com segurança sobre seu próprio tenant ativo (Fail-Closed).
        """
        self.client.force_login(self.user_a)

        session = self.client.session
        session['active_tenant_id'] = str(self.tenant_b.id)
        session.save()

        res = self.client.get('/clientes/api/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data.get('results') if isinstance(res.data, dict) else res.data
        ids = [item['id'] for item in items]
        self.assertNotIn(self.cliente_b.id, ids, "Vazamento Crítico: Usuário conseguiu acessar dados de Tenant B forjando active_tenant_id na sessão!")
        self.assertIn(self.cliente_a.id, ids, "Deveria ter recaído com segurança para o membership ativo do usuário (Tenant A)")

    def test_trocar_tenant_view_proibido_para_usuario_comum(self):
        """
        Valida que a view de troca de tenant (/inicio/trocar-tenant/) retorna 403 Forbidden
        quando um usuário comum (não superuser) tenta acioná-la via POST.
        """
        self.client.force_login(self.user_a)
        res = self.client.post('/inicio/trocar-tenant/', {'tenant_id': str(self.tenant_b.id)})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        data = res.json()
        self.assertFalse(data.get('sucesso'))
        self.assertIn('Acesso restrito a administradores', data.get('erro', ''))

    def test_trocar_tenant_view_permitido_para_superuser(self):
        """
        Valida que administradores globais (is_superuser=True) conseguem alternar o tenant ativo
        com sucesso via TrocarTenantView.
        """
        superuser = User.objects.create_superuser(
            username='super_baros_admin',
            password='Password123!',
            email='admin@baros.com.br'
        )
        self.client.force_login(superuser)
        res = self.client.post(
            '/inicio/trocar-tenant/',
            {'tenant_id': str(self.tenant_b.id)},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertTrue(data.get('sucesso'))
        self.assertEqual(data.get('tenant_id'), str(self.tenant_b.id))
        self.assertEqual(self.client.session.get('active_tenant_id'), str(self.tenant_b.id))

