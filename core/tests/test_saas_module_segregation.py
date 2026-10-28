from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Tenant, Membership, PerfilRegulatorioTenant
from core.tenancy import set_current_tenant
from produtos.models import GasQuimico, ModeloCilindro, Cilindro, LoteEnvase

User = get_user_model()


class SaasModuleSegregationTests(APITestCase):
    """
    Suíte de testes de Segregação de Módulos SaaS (Etapas 2, 3 e 4).
    Valida a blindagem 403 Forbidden nas APIs, o controle de acesso por plano/módulo
    (ENVASADORA, DISTRIBUIDORA, MISTO) e a integridade da Home/Sidebar.
    """

    def setUp(self):
        # 1. Gás global
        self.gas = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2',
            categoria='MEDICINAL',
            numero_onu='1072',
            classe_risco='2.2',
            exige_lote_anvisa=True
        )

        # 2. Tenant Envasadora Pura
        self.tenant_envase = Tenant.objects.create(
            cnpj='11.111.111/0001-11',
            razao_social='Usina de Envase Pura SA',
            nome_fantasia='Usina Envase',
            modulo_envase_ativo=True,
            modulo_logistica_ativo=False,
            modulo_vendas_ativo=False,
            modulo_comercial_ativo=False,
        )
        validade_licenca = timezone.now().date() + timezone.timedelta(days=365)
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant_envase,
            modo_operacao='ENVASADORA',
            afe_numero='AFE-11111',
            licenca_sanitaria_numero='VISA-11111',
            licenca_sanitaria_validade=validade_licenca
        )
        self.user_envase = User.objects.create_user(
            username='user_envase', password='password123', email='envase@usina.com'
        )
        Membership.objects.create(
            user=self.user_envase, tenant=self.tenant_envase, papel='ADMIN', ativo=True
        )

        # 3. Tenant Distribuidora Pura
        self.tenant_dist = Tenant.objects.create(
            cnpj='22.222.222/0001-22',
            razao_social='Logística e Distribuição de Gases Ltda',
            nome_fantasia='Log Gás',
            modulo_envase_ativo=False,
            modulo_logistica_ativo=True,
            modulo_vendas_ativo=True,
            modulo_comercial_ativo=True,
        )
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant_dist,
            modo_operacao='DISTRIBUIDORA',
            afe_numero='AFE-22222',
            licenca_sanitaria_numero='VISA-22222',
            licenca_sanitaria_validade=validade_licenca
        )
        self.user_dist = User.objects.create_user(
            username='user_dist', password='password123', email='dist@loggas.com'
        )
        Membership.objects.create(
            user=self.user_dist, tenant=self.tenant_dist, papel='ADMIN', ativo=True
        )

        # 4. Tenant Misto
        self.tenant_misto = Tenant.objects.create(
            cnpj='33.333.333/0001-33',
            razao_social='Gases do Brasil Completo SA',
            nome_fantasia='Gases Brasil Full',
            modulo_envase_ativo=True,
            modulo_logistica_ativo=True,
            modulo_vendas_ativo=True,
            modulo_comercial_ativo=True,
        )
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant_misto,
            modo_operacao='MISTO',
            afe_numero='AFE-33333',
            licenca_sanitaria_numero='VISA-33333',
            licenca_sanitaria_validade=validade_licenca
        )
        self.user_misto = User.objects.create_user(
            username='user_misto', password='password123', email='misto@gasesbrasil.com'
        )
        Membership.objects.create(
            user=self.user_misto, tenant=self.tenant_misto, papel='ADMIN', ativo=True
        )

        # 5. Superusuário
        self.superuser = User.objects.create_superuser(
            username='root_admin', password='password123', email='admin@baros.io'
        )

    def test_propriedades_modulos_computadas_no_tenant(self):
        """Valida que o model PerfilRegulatorioTenant e o Tenant delegam corretamente as flags."""
        self.assertTrue(self.tenant_envase.tem_modulo_envase)
        self.assertFalse(self.tenant_envase.tem_modulo_distribuicao)
        self.assertEqual(self.tenant_envase.modo_operacao, 'ENVASADORA')

        self.assertFalse(self.tenant_dist.tem_modulo_envase)
        self.assertTrue(self.tenant_dist.tem_modulo_distribuicao)
        self.assertEqual(self.tenant_dist.modo_operacao, 'DISTRIBUIDORA')

        self.assertTrue(self.tenant_misto.tem_modulo_envase)
        self.assertTrue(self.tenant_misto.tem_modulo_distribuicao)
        self.assertEqual(self.tenant_misto.modo_operacao, 'MISTO')

    def test_envasadora_bloqueada_em_rotas_distribuicao_403(self):
        """Tenant ENVASADORA recebe 403 Forbidden em vendas, rotas, veículos, contratos e estadias."""
        set_current_tenant(self.tenant_envase)
        self.client.force_authenticate(user=self.user_envase)

        # Vendas
        res = self.client.get('/vendas/api/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Veículos
        res = self.client.get('/logistica/api/veiculos/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Rotas
        res = self.client.get('/logistica/api/rotas/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Entregas
        res = self.client.get('/logistica/api/entregas/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Contratos de Comodato
        res = self.client.get('/clientes/api/contratos/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Faturas de Estadia
        res = self.client.get('/clientes/api/faturas-estadia/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Extravios
        res = self.client.get('/clientes/api/extravios/alertas/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

    def test_envasadora_autorizada_em_rotas_envase_200(self):
        """Tenant ENVASADORA acessa normalmente lotes, envases e rampa."""
        set_current_tenant(self.tenant_envase)
        self.client.force_authenticate(user=self.user_envase)

        # Lotes de envase
        res = self.client.get('/produtos/api/lotes/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Histórico de Envase
        res = self.client.get('/produtos/api/envases/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_distribuidora_bloqueada_em_rotas_envase_403(self):
        """Tenant DISTRIBUIDORA recebe 403 Forbidden em lotes de envase e histórico de rampa."""
        set_current_tenant(self.tenant_dist)
        self.client.force_authenticate(user=self.user_dist)

        # Lotes de envase
        res = self.client.get('/produtos/api/lotes/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Histórico de Envase
        res = self.client.get('/produtos/api/envases/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

        # Inspeções Pré-Envase
        res = self.client.get('/produtos/api/inspecoes/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MODULO_INATIVO", str(res.data))

    def test_distribuidora_autorizada_em_rotas_distribuicao_200(self):
        """Tenant DISTRIBUIDORA acessa normalmente vendas, veículos, contratos e estadias."""
        set_current_tenant(self.tenant_dist)
        self.client.force_authenticate(user=self.user_dist)

        # Vendas
        res = self.client.get('/vendas/api/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Veículos
        res = self.client.get('/logistica/api/veiculos/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Contratos de Comodato
        res = self.client.get('/clientes/api/contratos/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_plano_misto_acessa_ambos_os_modulos(self):
        """Tenant MISTO acessa tanto endpoints de distribuição quanto de envase sem bloqueio."""
        set_current_tenant(self.tenant_misto)
        self.client.force_authenticate(user=self.user_misto)

        # Distribuição
        self.assertEqual(self.client.get('/vendas/api/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/logistica/api/veiculos/').status_code, status.HTTP_200_OK)

        # Envase
        self.assertEqual(self.client.get('/produtos/api/lotes/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/produtos/api/envases/').status_code, status.HTTP_200_OK)

    def test_superuser_ignora_restricoes_de_modulo(self):
        """Superuser possui acesso irrestrito a todos os endpoints em qualquer tenant."""
        set_current_tenant(self.tenant_envase)
        self.client.force_authenticate(user=self.superuser)

        self.assertEqual(self.client.get('/vendas/api/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/logistica/api/veiculos/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/produtos/api/lotes/').status_code, status.HTTP_200_OK)

    def test_dashboard_stats_api_metamorfica(self):
        """Endpoint /inicio/api/stats/ retorna flags de módulo e métricas adaptadas."""
        # 1. Envasadora
        set_current_tenant(self.tenant_envase)
        self.client.force_authenticate(user=self.user_envase)
        res_envase = self.client.get('/inicio/api/stats/')
        self.assertEqual(res_envase.status_code, status.HTTP_200_OK)
        self.assertTrue(res_envase.data['tem_modulo_envase'])
        self.assertFalse(res_envase.data['tem_modulo_distribuicao'])
        self.assertIn('lotes_ativos', res_envase.data)
        self.assertIn('volume_envasado_mes', res_envase.data)

        # 2. Distribuidora
        set_current_tenant(self.tenant_dist)
        self.client.force_authenticate(user=self.user_dist)
        res_dist = self.client.get('/inicio/api/stats/')
        self.assertEqual(res_dist.status_code, status.HTTP_200_OK)
        self.assertFalse(res_dist.data['tem_modulo_envase'])
        self.assertTrue(res_dist.data['tem_modulo_distribuicao'])
        self.assertIn('receita_locacao_acumulada', res_dist.data)
        self.assertIn('cilindros_sem_giro_30_mais', res_dist.data)

    def test_sidebar_renderiza_condicionalmente_conforme_modulo(self):
        """Template da sidebar oculta links conforme o plano contratado."""
        # 1. Envasadora logada
        set_current_tenant(self.tenant_envase)
        self.client.force_login(self.user_envase)
        res = self.client.get('/inicio/')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        # Deve ter Rampa de Envase
        self.assertIn('Rampa de Envase (IN 129/2022)', html)
        # Não deve ter Vendas ou Logística
        self.assertNotIn('/vendas/', html)
        self.assertNotIn('/logistica/', html)
        # Links universais devem existir
        self.assertIn('/produtos/', html)
        self.assertIn('Ativos 360', html)

        # 2. Distribuidora logada
        set_current_tenant(self.tenant_dist)
        self.client.force_login(self.user_dist)
        res = self.client.get('/inicio/')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        # Deve ter Vendas e Logística
        self.assertIn('/vendas/', html)
        self.assertIn('/logistica/', html)
        # Não deve ter Rampa de Envase
        self.assertNotIn('Rampa de Envase (IN 129/2022)', html)
