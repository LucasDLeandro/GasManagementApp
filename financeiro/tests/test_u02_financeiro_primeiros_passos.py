"""
Testes da Sprint U02 — Financeiro: primeiros passos e plano de contas padrão.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.context import tenant_context
from core.models import Membership, Tenant
from core.seeds import executar_seeds
from financeiro.models import CentroCusto, CondicaoPagamento, PlanoContas
from financeiro.selectors.balancete import obter_balancete_verificacao

User = get_user_model()


class U02FinanceiroPrimeirosPassosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant_com_fin = Tenant.objects.create(
            razao_social="Distribuidora Financeiro Ativo Ltda",
            nome_fantasia="FinAtivo",
            cnpj="11222333000181",
            modulo_financeiro_ativo=True,
        )
        cls.tenant_sem_fin = Tenant.objects.create(
            razao_social="Distribuidora Sem Financeiro Ltda",
            nome_fantasia="SemFin",
            cnpj="44555666000199",
            modulo_financeiro_ativo=False,
        )

        cls.user_admin = User.objects.create_user(
            username="admin_u02", email="admin_u02@test.com", password="123"
        )
        Membership.objects.create(
            user=cls.user_admin, tenant=cls.tenant_com_fin, papel="ADMIN", ativo=True
        )

        cls.user_vendedor = User.objects.create_user(
            username="vend_u02", email="vend_u02@test.com", password="123"
        )
        Membership.objects.create(
            user=cls.user_vendedor, tenant=cls.tenant_com_fin, papel="VENDEDOR", ativo=True
        )

        cls.user_admin_sem_fin = User.objects.create_user(
            username="admin_sem_fin_u02",
            email="admin_sem_fin_u02@test.com",
            password="123",
        )
        Membership.objects.create(
            user=cls.user_admin_sem_fin,
            tenant=cls.tenant_sem_fin,
            papel="ADMIN",
            ativo=True,
        )

        cls.superuser = User.objects.create_superuser(
            username="super_u02", email="super_u02@test.com", password="123"
        )

    def test_01_ligar_modulo_financeiro_executa_seed_idempotente(self):
        """Ligar o módulo financeiro via backoffice/executar_seeds cria plano, CC e condições sem duplicar."""
        executar_seeds(self.tenant_com_fin, modulo="financeiro")

        with tenant_context(self.tenant_com_fin):
            qtd_plano_1 = PlanoContas.objects.count()
            qtd_cc_1 = CentroCusto.objects.count()
            qtd_cond_1 = CondicaoPagamento.objects.count()

        self.assertGreater(qtd_plano_1, 0)
        self.assertGreater(qtd_cc_1, 0)
        self.assertGreater(qtd_cond_1, 0)

        # Segunda execução não duplica
        executar_seeds(self.tenant_com_fin, modulo="financeiro")
        with tenant_context(self.tenant_com_fin):
            self.assertEqual(PlanoContas.objects.count(), qtd_plano_1)
            self.assertEqual(CentroCusto.objects.count(), qtd_cc_1)
            self.assertEqual(CondicaoPagamento.objects.count(), qtd_cond_1)

    def test_02_balancete_sem_lancamentos_informa_estado(self):
        """Com zero lançamentos, obter_balancete_verificacao devolve sem_lancamentos=True."""
        hoje = datetime.date(2026, 11, 12)
        with tenant_context(self.tenant_com_fin):
            res = obter_balancete_verificacao(
                tenant=self.tenant_com_fin,
                data_inicio=hoje.replace(day=1).isoformat(),
                data_fim=hoje.isoformat(),
            )
        self.assertTrue(res.get("sem_lancamentos"))
        self.assertEqual(res.get("status_texto"), "Sem lançamentos no período")

    def test_03_action_seed_padrao_restrita_a_admin_e_modulo_ativo(self):
        """POST /financeiro/api/plano-contas/seed-padrao/ aceita ADMIN e superuser; outros papéis e sem módulo -> 403."""
        client = APIClient()

        # Vendedor -> 403
        client.force_authenticate(user=self.user_vendedor)
        r_vend = client.post(
            "/financeiro/api/plano-contas/seed-padrao/",
            HTTP_X_TENANT_ID=str(self.tenant_com_fin.id),
        )
        self.assertEqual(r_vend.status_code, 403)

        # Admin de empresa sem módulo -> 403
        client.force_authenticate(user=self.user_admin_sem_fin)
        r_sem = client.post(
            "/financeiro/api/plano-contas/seed-padrao/",
            HTTP_X_TENANT_ID=str(self.tenant_sem_fin.id),
        )
        self.assertEqual(r_sem.status_code, 403)

        # Admin de empresa com módulo -> 200
        client.force_authenticate(user=self.user_admin)
        r_adm = client.post(
            "/financeiro/api/plano-contas/seed-padrao/",
            HTTP_X_TENANT_ID=str(self.tenant_com_fin.id),
        )
        self.assertEqual(r_adm.status_code, 200)
        with tenant_context(self.tenant_com_fin):
            self.assertGreater(PlanoContas.objects.count(), 0)

    def test_04_comando_seed_aplica_apenas_modulo_ativo_e_plano_vazio(self):
        """Comando/serviço de backfill aplica seed apenas onde módulo financeiro ativo e plano vazio."""
        from financeiro.seeds import aplicar_seed_tenants_plano_vazio

        # tenant_sem_fin tem módulo desligado e plano vazio -> NÃO deve receber seed
        # tenant_com_fin tem módulo ligado e plano vazio -> DEVE receber seed
        aplicados = aplicar_seed_tenants_plano_vazio()
        self.assertIn(self.tenant_com_fin.id, aplicados)
        self.assertNotIn(self.tenant_sem_fin.id, aplicados)

        with tenant_context(self.tenant_com_fin):
            self.assertGreater(PlanoContas.objects.count(), 0)
        with tenant_context(self.tenant_sem_fin):
            self.assertEqual(PlanoContas.objects.count(), 0)

        # Segunda chamada: tenant_com_fin já tem plano -> não aplica de novo
        aplicados_2 = aplicar_seed_tenants_plano_vazio()
        self.assertEqual(aplicados_2, [])

    def test_05_usuario_sem_modulo_nao_ve_menu_e_recebe_403_na_tela(self):
        """Usuário comum (mesmo ADMIN) de empresa sem módulo financeiro não vê item no menu e recebe 403 em /financeiro/."""
        self.client.force_login(self.user_admin_sem_fin)
        session = self.client.session
        session["tenant_id"] = str(self.tenant_sem_fin.id)
        session.save()

        resp_home = self.client.get("/inicio/")
        self.assertEqual(resp_home.status_code, 200)
        self.assertNotIn(b"/financeiro/", resp_home.content)

        resp_fin = self.client.get("/financeiro/")
        self.assertEqual(resp_fin.status_code, 403)
