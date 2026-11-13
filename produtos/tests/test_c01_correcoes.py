"""
Testes da Sprint C01 — Correções das Sprints 02, 03, H01, U01 e U02.
"""
import datetime
import io
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.context import tenant_context
from core.models import Membership, Tenant
from financeiro.models import PlanoContas
from produtos.models import (
    BaixaPatrimonial,
    Cilindro,
    EnvioReteste,
    GasQuimico,
    HistoricoRetesteHidrostatico,
    ItemEnvioReteste,
    ModeloCilindro,
)

User = get_user_model()


class C01CorrecoesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            razao_social="Distribuidora C01 Ltda",
            nome_fantasia="DistC01",
            cnpj="12345678000190",
            modulo_patrimonio_ativo=True,
            modulo_financeiro_ativo=False,
        )
        cls.outro_tenant = Tenant.objects.create(
            razao_social="Outra Empresa C01 Ltda",
            nome_fantasia="OutraC01",
            cnpj="98765432000111",
            modulo_patrimonio_ativo=True,
            modulo_financeiro_ativo=True,
        )

        cls.users = {}
        for papel in (
            "ADMIN",
            "GERENTE",
            "RESPONSAVEL_TECNICO",
            "OPERADOR_PATIO",
            "VENDEDOR",
            "MOTORISTA",
        ):
            u = User.objects.create_user(
                username=f"c01_{papel.lower()}",
                email=f"c01_{papel.lower()}@test.com",
                password="123",
            )
            Membership.objects.create(user=u, tenant=cls.tenant, papel=papel, ativo=True)
            cls.users[papel] = u

        cls.superuser = User.objects.create_superuser(
            username="c01_super", email="c01_super@test.com", password="123"
        )

        hoje = datetime.date(2026, 11, 13)
        prox = datetime.date(2029, 11, 13)
        cls.gas = GasQuimico.objects.create(sigla="O2C01", nome="Oxigênio C01", categoria="MEDICINAL")
        with tenant_context(cls.tenant):
            cls.modelo = ModeloCilindro.objects.create(
                tenant=cls.tenant,
                descricao="Cilindro 50L Aço C01",
                volume_hidraulico_litros=Decimal("50.00"),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal("55.00"),
                periodicidade_reteste_anos=3,
            )
            cls.cil_baixa = Cilindro.objects.create(
                tenant=cls.tenant,
                modelo=cls.modelo,
                gas_dedicado=cls.gas,
                fabricante="MAT",
                ano_fabricacao=2020,
                tara_real_kg=Decimal("55.000"),
                numero_serie_ogiva="C01-BAIXA-01",
                codigo_qr="QR-C01-B1",
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje,
                data_proximo_reteste=prox,
            )
            cls.cil_envio_1 = Cilindro.objects.create(
                tenant=cls.tenant,
                modelo=cls.modelo,
                gas_dedicado=cls.gas,
                fabricante="MAT",
                ano_fabricacao=2020,
                tara_real_kg=Decimal("55.000"),
                numero_serie_ogiva="C01-ENV-01",
                codigo_qr="QR-C01-E1",
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje,
                data_proximo_reteste=prox,
            )
            cls.cil_envio_2 = Cilindro.objects.create(
                tenant=cls.tenant,
                modelo=cls.modelo,
                gas_dedicado=cls.gas,
                fabricante="MAT",
                ano_fabricacao=2020,
                tara_real_kg=Decimal("55.000"),
                numero_serie_ogiva="C01-ENV-02",
                codigo_qr="QR-C01-E2",
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje,
                data_proximo_reteste=prox,
            )
            cls.cil_ret = Cilindro.objects.create(
                tenant=cls.tenant,
                modelo=cls.modelo,
                gas_dedicado=cls.gas,
                fabricante="MAT",
                ano_fabricacao=2020,
                tara_real_kg=Decimal("55.000"),
                numero_serie_ogiva="C01-RET-01",
                codigo_qr="QR-C01-R1",
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje,
                data_proximo_reteste=prox,
            )
            cls.reteste = HistoricoRetesteHidrostatico.objects.create(
                tenant=cls.tenant,
                cilindro=cls.cil_ret,
                data_execucao=datetime.date(2026, 11, 1),
                numero_certificado="CERT-C01-01",
                oficina_nome="Oficina C01",
                oficina_cnpj="11222333000181",
                registro_inmetro="INM-C01",
                pressao_teste_bar=Decimal("250.00"),
                expansao_total_cm3=Decimal("10.00"),
                expansao_permanente_cm3=Decimal("0.50"),
                tara_real_kg=Decimal("55.00"),
                resultado="APROVADO",
                data_proximo_reteste=datetime.date(2031, 11, 1),
                usuario=cls.users["RESPONSAVEL_TECNICO"],
            )

        with tenant_context(cls.outro_tenant):
            cls.modelo_outro = ModeloCilindro.objects.create(
                tenant=cls.outro_tenant,
                descricao="Cilindro Outro C01",
                volume_hidraulico_litros=Decimal("50.00"),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal("55.00"),
                periodicidade_reteste_anos=3,
            )
            cls.cil_outro = Cilindro.objects.create(
                tenant=cls.outro_tenant,
                modelo=cls.modelo_outro,
                gas_dedicado=cls.gas,
                fabricante="MAT",
                ano_fabricacao=2020,
                tara_real_kg=Decimal("55.000"),
                numero_serie_ogiva="OUTRO-RET-01",
                codigo_qr="QR-OUTRO-R1",
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje,
                data_proximo_reteste=prox,
            )
            cls.reteste_outro = HistoricoRetesteHidrostatico.objects.create(
                tenant=cls.outro_tenant,
                cilindro=cls.cil_outro,
                data_execucao=datetime.date(2026, 11, 1),
                numero_certificado="CERT-OUTRO-01",
                oficina_nome="Oficina Outra",
                oficina_cnpj="99888777000166",
                registro_inmetro="INM-OUTRO",
                pressao_teste_bar=Decimal("250.00"),
                expansao_total_cm3=Decimal("10.00"),
                expansao_permanente_cm3=Decimal("0.50"),
                tara_real_kg=Decimal("55.00"),
                resultado="APROVADO",
                data_proximo_reteste=datetime.date(2031, 11, 1),
            )

    def _client_para(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_01_baixa_patrimonial_imutavel_sem_patch_put_delete(self):
        client = self._client_para(self.users["ADMIN"])
        r_create = client.post(
            "/produtos/api/patrimonio/baixas/",
            {
                "cilindro": self.cil_baixa.id,
                "tipo": "INUTILIZACAO_TECNICA",
                "data": "2026-11-12",
                "motivo": "Cilindro condenado por corrosão severa na base.",
            },
            format="json",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_create.status_code, 201)
        baixa_id = r_create.data["id"]

        r_patch = client.patch(
            f"/produtos/api/patrimonio/baixas/{baixa_id}/",
            {"status_anterior": "CHEIO_ESTOQUE", "motivo": "Alterado indevidamente"},
            format="json",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_patch.status_code, 405)

        r_put = client.put(
            f"/produtos/api/patrimonio/baixas/{baixa_id}/",
            {"status_anterior": "CHEIO_ESTOQUE"},
            format="json",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_put.status_code, 405)

        r_del = client.delete(
            f"/produtos/api/patrimonio/baixas/{baixa_id}/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_del.status_code, 405)

        with tenant_context(self.tenant):
            baixa = BaixaPatrimonial.objects.get(id=baixa_id)
            self.assertEqual(baixa.status_anterior, "VAZIO_TRIAGEM")

    def test_02_envio_reteste_permissoes_d1_e_imutabilidade_patch_put_delete(self):
        # VENDEDOR e MOTORISTA -> 403 no POST, 200 no GET
        for papel in ("VENDEDOR", "MOTORISTA"):
            c = self._client_para(self.users[papel])
            r_get = c.get(
                "/produtos/api/patrimonio/envios-reteste/",
                HTTP_X_TENANT_ID=str(self.tenant.id),
            )
            self.assertEqual(r_get.status_code, 200)

            r_post = c.post(
                "/produtos/api/patrimonio/envios-reteste/",
                {
                    "oficina_nome": "Oficina Teste",
                    "oficina_cnpj": "11222333000181",
                    "cilindro_ids": [self.cil_envio_1.id],
                },
                format="json",
                HTTP_X_TENANT_ID=str(self.tenant.id),
            )
            self.assertEqual(r_post.status_code, 403, f"Esperado 403 para {papel}")

        # OPERADOR_PATIO e RESPONSAVEL_TECNICO -> 201 no POST
        c_op = self._client_para(self.users["OPERADOR_PATIO"])
        r_op = c_op.post(
            "/produtos/api/patrimonio/envios-reteste/",
            {
                "oficina_nome": "Oficina Teste OP",
                "oficina_cnpj": "11222333000181",
                "cilindro_ids": [self.cil_envio_1.id],
            },
            format="json",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_op.status_code, 201)
        envio_id = r_op.data["id"]

        c_rt = self._client_para(self.users["RESPONSAVEL_TECNICO"])
        r_rt = c_rt.post(
            "/produtos/api/patrimonio/envios-reteste/",
            {
                "oficina_nome": "Oficina Teste RT",
                "oficina_cnpj": "11222333000181",
                "cilindro_ids": [self.cil_envio_2.id],
            },
            format="json",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_rt.status_code, 201)

        # PATCH, PUT, DELETE -> 405 e itens continuam existindo
        c_adm = self._client_para(self.users["ADMIN"])
        for method in ("patch", "put", "delete"):
            resp = getattr(c_adm, method)(
                f"/produtos/api/patrimonio/envios-reteste/{envio_id}/",
                {"oficina_nome": "Hack"},
                format="json",
                HTTP_X_TENANT_ID=str(self.tenant.id),
            )
            self.assertEqual(resp.status_code, 405)

        with tenant_context(self.tenant):
            self.assertTrue(EnvioReteste.objects.filter(id=envio_id).exists())
            self.assertEqual(ItemEnvioReteste.objects.filter(envio_id=envio_id).count(), 1)

    def test_03_retificar_reteste_motivo_obrigatorio_papeis_d2_e_404_outro_tenant(self):
        # VENDEDOR, OPERADOR_PATIO e MOTORISTA -> 403
        for papel in ("VENDEDOR", "OPERADOR_PATIO", "MOTORISTA"):
            c = self._client_para(self.users[papel])
            r = c.post(
                f"/produtos/api/patrimonio/retestes/{self.reteste.id}/retificar/",
                {"motivo": "Correção válida com mais de 10 caracteres."},
                format="json",
                HTTP_X_TENANT_ID=str(self.tenant.id),
            )
            self.assertEqual(r.status_code, 403, f"Esperado 403 para {papel}")

        c_rt = self._client_para(self.users["RESPONSAVEL_TECNICO"])

        # Sem motivo ou motivo < 10 chars -> 400 {"motivo": [...]}
        for payload in ({}, {"motivo": "curto"}):
            r_bad = c_rt.post(
                f"/produtos/api/patrimonio/retestes/{self.reteste.id}/retificar/",
                payload,
                format="json",
                HTTP_X_TENANT_ID=str(self.tenant.id),
            )
            self.assertEqual(r_bad.status_code, 400)
            self.assertIn("motivo", r_bad.data)

        # Reteste de outro tenant -> 404
        r_outro = c_rt.post(
            f"/produtos/api/patrimonio/retestes/{self.reteste_outro.id}/retificar/",
            {"motivo": "Tentativa cross-tenant com motivo válido."},
            format="json",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_outro.status_code, 404)

        # RESPONSAVEL_TECNICO com motivo válido -> 201
        r_ok = c_rt.post(
            f"/produtos/api/patrimonio/retestes/{self.reteste.id}/retificar/",
            {
                "motivo": "Ajuste do número do certificado após conferência.",
                "numero_certificado": "CERT-C01-01-RET",
            },
            format="json",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(r_ok.status_code, 201)
        self.assertEqual(r_ok.data["numero_certificado"], "CERT-C01-01-RET")

    def test_04_estaticos_js_data_local_e_guard_condenado(self):
        base = Path(settings.BASE_DIR)
        retestes_js = (base / "produtos/static/produtos/js/retestes.js").read_text(encoding="utf-8")
        drawer_js = (base / "produtos/static/produtos/js/cilindros_drawer.js").read_text(encoding="utf-8")
        core_js = (base / "core/static/core/js/core.js").read_text(encoding="utf-8")

        self.assertIn("hojeISO", core_js)
        self.assertNotIn("toISOString().slice(0, 10)", retestes_js)
        self.assertNotIn("toISOString().slice(0, 10)", drawer_js)

        idx_cond = retestes_js.rindex("REPROVADO_CONDENADO")
        trecho = retestes_js[idx_cond : idx_cond + 600]
        self.assertIn("podeEditarPatrimonio", trecho)
        self.assertLess(trecho.index("podeEditarPatrimonio"), trecho.index("abrirModalBaixa"))

    def test_05_migracao_0012_nao_importa_financeiro_seeds(self):
        base = Path(settings.BASE_DIR)
        mig_path = base / "financeiro/migrations/0012_seed_plano_contas_tenants_ativos.py"
        conteudo = mig_path.read_text(encoding="utf-8")
        self.assertNotIn("financeiro.seeds", conteudo)
        self.assertIn("RunPython.noop", conteudo)

    def test_06_comando_seed_financeiro_plano_vazio(self):
        out_dry = io.StringIO()
        call_command("seed_financeiro_plano_vazio", "--dry-run", stdout=out_dry)
        with tenant_context(self.outro_tenant):
            self.assertEqual(PlanoContas.objects.count(), 0)

        out_real = io.StringIO()
        call_command("seed_financeiro_plano_vazio", stdout=out_real)
        with tenant_context(self.outro_tenant):
            count_1 = PlanoContas.objects.count()
            self.assertGreater(count_1, 0)
        with tenant_context(self.tenant):
            self.assertEqual(PlanoContas.objects.count(), 0)

        # Rodar novamente não duplica
        call_command("seed_financeiro_plano_vazio", stdout=io.StringIO())
        with tenant_context(self.outro_tenant):
            self.assertEqual(PlanoContas.objects.count(), count_1)

    def test_07_backoffice_toggle_modulo_mostra_erro_quando_seed_falha(self):
        self.client.force_login(self.superuser)
        session = self.client.session
        session["baros_admin_mfa_verified"] = True
        session.save()

        with patch("core.views_baros_admin.executar_seeds", side_effect=RuntimeError("Falha simulada no seed")):
            resp = self.client.post(
                f"/baros-admin/tenants/{self.tenant.id}/toggle-modulo/",
                {"modulo": "financeiro", "ativo": "true"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["sucesso"])
        self.assertTrue(data["ativo"])
        self.assertFalse(data["seed_aplicado"])
        self.assertIn("aviso_seed", data)
        self.assertIn("Falha simulada no seed", data["aviso_seed"])

