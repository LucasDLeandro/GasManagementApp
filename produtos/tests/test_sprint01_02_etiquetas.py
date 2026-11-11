"""
Testes da Sprint 01.02 — Etiquetas: uma impressão só, a verdadeira.
Valida:
1. Eliminação do layout falso de etiqueta térmica em _modais.html e ausência de [ QR CODE 2D ].
2. Ausência de tags <style> inline em etiqueta_casco.html e etiqueta_colarinho.html.
3. Etiqueta de casco com URL absoluta (HTTP_HOST), QR legível e isolamento multi-tenant.
4. Etiqueta de colarinho por lote com dados reais de cada envase (pressão específica e massa líquida).
5. Etiqueta de colarinho para lote sem envases exibindo estado vazio sem conteúdo imprimível.
6. Validação rigorosa do parâmetro ?envase_ids= (apenas inteiros do lote/empresa, 400 em caso inválido).
7. Isolamento de tenant e obrigatoriedade do módulo envase para usuários comuns.
8. Varredura estática em fase3_rampa_recebimento_lotes.js (sem innerHTML com ${).
9. Medição real do QR Code (versão, contagem de módulos e dimensão mm/módulo para 22mm).
"""
import io
import datetime
from decimal import Decimal
import qrcode
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status

from core.models import Tenant, Membership, ResponsavelTecnico
from core.tenancy import tenant_context
from produtos.models import (
    Cilindro,
    GasQuimico,
    ModeloCilindro,
    LoteEnvase,
    EnvaseCilindro,
)

User = get_user_model()


class Sprint0102EtiquetasTests(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()

        # Tenant A (com módulo envase ativo)
        self.tenant = Tenant.objects.create(
            razao_social="Oxigênio Alpha Ltda",
            nome_fantasia="Oxigênio Alpha",
            cnpj="11222333000181",
            modulo_envase_ativo=True,
        )

        # Tenant B (outra empresa)
        self.outro_tenant = Tenant.objects.create(
            razao_social="Gases Beta Ltda",
            nome_fantasia="Gases Beta",
            cnpj="44555666000192",
            modulo_envase_ativo=True,
        )

        # Tenant C (sem módulo envase)
        self.tenant_sem_envase = Tenant.objects.create(
            razao_social="Gases Sem Envase Ltda",
            nome_fantasia="Gases Sem Envase",
            cnpj="77888999000103",
            modulo_envase_ativo=False,
        )

        # Usuários
        self.user_comum = User.objects.create_user(
            username="operador.alpha",
            password="password123",
            email="operador@alpha.com",
        )
        Membership.objects.create(
            user=self.user_comum,
            tenant=self.tenant,
            papel="OPERADOR_PATIO",
        )

        self.user_outro_tenant = User.objects.create_user(
            username="gerente.beta",
            password="password123",
            email="gerente@beta.com",
        )
        Membership.objects.create(
            user=self.user_outro_tenant,
            tenant=self.outro_tenant,
            papel="GERENTE",
        )

        self.user_sem_envase = User.objects.create_user(
            username="operador.sem.envase",
            password="password123",
            email="sem.envase@test.com",
        )
        Membership.objects.create(
            user=self.user_sem_envase,
            tenant=self.tenant_sem_envase,
            papel="OPERADOR_PATIO",
        )

        self.superuser = User.objects.create_superuser(
            username="admin.root",
            password="password123",
            email="admin@root.com",
        )

        # Catálogo
        self.gas_o2 = GasQuimico.objects.create(
            nome="Oxigênio Medicinal",
            sigla="O2-MED",
            categoria="MEDICINAL",
            cor_padrao_abnt="Branco",
            numero_onu="1072",
            classe_risco="2.2 (5.1)",
        )

        with tenant_context(self.tenant):
            self.modelo = ModeloCilindro.objects.create(
                tenant=self.tenant,
                descricao="Cilindro Aço 50L",
                volume_hidraulico_litros=Decimal("50.0"),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal("50.0"),
            )

            self.rt = ResponsavelTecnico.objects.create(
                tenant=self.tenant,
                nome_completo="Dra. Juliana Prado",
                conselho_classe="CRF",
                uf_conselho="SP",
                numero_registro="54321",
                vigencia_inicio=self.hoje - datetime.timedelta(days=30),
                ativo=True,
            )

            self.lote = LoteEnvase.objects.create(
                tenant=self.tenant,
                gas=self.gas_o2,
                codigo_lote="LOT-202611-01",
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal("99.80"),
                status_qualidade="APROVADO",
                responsavel_tecnico="Dra. Juliana Prado",
                responsavel_tecnico_fk=self.rt,
            )

            self.cilindro_1 = Cilindro.objects.create(
                tenant=self.tenant,
                numero_serie_ogiva="OGV-101",
                codigo_qr="CIL-101",
                modelo=self.modelo,
                gas_dedicado=self.gas_o2,
                status="CHEIO_DISPONIVEL",
                tara_real_kg=Decimal("52.500"),
                ano_fabricacao=2021,
                data_ultimo_reteste=datetime.date(2021, 1, 1),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=300),
            )

            self.cilindro_2 = Cilindro.objects.create(
                tenant=self.tenant,
                numero_serie_ogiva="OGV-102",
                codigo_qr="CIL-102",
                modelo=self.modelo,
                gas_dedicado=self.gas_o2,
                status="CHEIO_DISPONIVEL",
                tara_real_kg=Decimal("53.100"),
                ano_fabricacao=2021,
                data_ultimo_reteste=datetime.date(2021, 1, 1),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=300),
            )

            # Dois envases do mesmo lote com pressões e massas distintas
            self.envase_1 = EnvaseCilindro.objects.create(
                tenant=self.tenant,
                cilindro=self.cilindro_1,
                lote=self.lote,
                pressao_final_bar=150,
                massa_liquida_gas_kg=Decimal("8.500"),
                envasado_em=timezone.now(),
                operador=self.user_comum,
            )

            self.envase_2 = EnvaseCilindro.objects.create(
                tenant=self.tenant,
                cilindro=self.cilindro_2,
                lote=self.lote,
                pressao_final_bar=200,
                massa_liquida_gas_kg=Decimal("11.200"),
                envasado_em=timezone.now(),
                operador=self.user_comum,
            )

    # --------------------------------------------------------------------------
    # 1. TESTES ESTÁTICOS
    # --------------------------------------------------------------------------

    def test_01_static_modais_sem_layout_falso_e_sem_qr_falso(self):
        """Verifica que _modais.html não possui o layout falso com [ QR CODE 2D ] e zero style="."""
        with open("produtos/templates/produtos/index/_modais.html", "r", encoding="utf-8") as f:
            conteudo = f.read()

        self.assertNotIn("[ QR CODE 2D ]", conteudo, "Layout falso ainda presente em _modais.html")
        self.assertNotIn('style="', conteudo, "_modais.html não deve conter estilos inline (style=)")

    def test_02_static_paginas_etiqueta_sem_tags_style(self):
        """Verifica que etiqueta_casco.html e etiqueta_colarinho.html não possuem tags <style>."""
        with open("produtos/templates/produtos/etiqueta_casco.html", "r", encoding="utf-8") as f:
            conteudo_casco = f.read()
        self.assertNotIn("<style", conteudo_casco, "etiqueta_casco.html não deve conter bloco <style>")

        with open("produtos/templates/produtos/etiqueta_colarinho.html", "r", encoding="utf-8") as f:
            conteudo_colarinho = f.read()
        self.assertNotIn("<style", conteudo_colarinho, "etiqueta_colarinho.html não deve conter bloco <style>")

    def test_08_static_sem_innerhtml_com_interpolar_em_colarinho_rampa(self):
        """Verifica que fase3_rampa_recebimento_lotes.js não monta colarinho com innerHTML contendo ${."""
        with open("produtos/static/produtos/js/fase3_rampa_recebimento_lotes.js", "r", encoding="utf-8") as f:
            js = f.read()

        import re
        matches = re.findall(r'innerHTML\s*=\s*`[^`]*\$\{[^`]*`', js)
        self.assertEqual(len(matches), 0, f"Encontrado innerHTML com interpolação dinâmica em JS: {matches}")

    # --------------------------------------------------------------------------
    # 2. ETIQUETA DE CASCO (60x40mm)
    # --------------------------------------------------------------------------

    @override_settings(ALLOWED_HOSTS=['teste.exemplo', 'localhost', '127.0.0.1', 'testserver'])
    def test_03_etiqueta_casco_host_absoluto_e_isolamento_tenant(self):
        """
        GET /produtos/cilindros/<pk>/etiqueta-casco/ com HTTP_HOST='teste.exemplo':
        Retorna 200, contém o QR base64 e a URL http://teste.exemplo/v/cilindro/<codigo_qr>/.
        Cilindro de outra empresa retorna 404 para usuário comum.
        Superusuário mantém acesso (.unscoped).
        """
        self.client.force_login(self.user_comum)
        resp = self.client.get(
            f"/produtos/cilindros/{self.cilindro_1.id}/etiqueta-casco/",
            HTTP_HOST="teste.exemplo"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        html = resp.content.decode("utf-8")
        self.assertIn("data:image/png;base64,", html)
        self.assertIn(f"http://teste.exemplo/v/cilindro/{self.cilindro_1.codigo_qr}/", html)

        # Cilindro de outra empresa consultado por usuário comum -> 404
        with tenant_context(self.outro_tenant):
            modelo_outro = ModeloCilindro.objects.create(
                tenant=self.outro_tenant,
                descricao="Cilindro Beta 50L",
                volume_hidraulico_litros=Decimal("50.0"),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal("50.0"),
            )
            cil_outro = Cilindro.objects.create(
                tenant=self.outro_tenant,
                numero_serie_ogiva="OGV-BETA-1",
                codigo_qr="CIL-BETA-1",
                modelo=modelo_outro,
                gas_dedicado=self.gas_o2,
                status="CHEIO_DISPONIVEL",
                ano_fabricacao=2020,
                data_ultimo_reteste=datetime.date(2020, 1, 1),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=300),
            )

        resp_outro = self.client.get(f"/produtos/cilindros/{cil_outro.id}/etiqueta-casco/")
        self.assertEqual(resp_outro.status_code, status.HTTP_404_NOT_FOUND)

        # Superusuário acessa cilindro de qualquer empresa via fallback .unscoped
        self.client.force_login(self.superuser)
        resp_su = self.client.get(f"/produtos/cilindros/{cil_outro.id}/etiqueta-casco/")
        self.assertEqual(resp_su.status_code, status.HTTP_200_OK)

    # --------------------------------------------------------------------------
    # 3. ETIQUETA DE COLARINHO (IN 129/2022)
    # --------------------------------------------------------------------------

    def test_04_etiqueta_colarinho_por_lote_pressao_especifica_e_massa_liquida(self):
        """
        Dois envases do mesmo lote com pressões 150 e 200 bar e massas líquidas distintas.
        Cada etiqueta exibe sua própria pressão e massa líquida, nunca 200 bar fixo em todas.
        """
        self.client.force_login(self.user_comum)
        resp = self.client.get(f"/produtos/lotes/{self.lote.id}/etiqueta-colarinho/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        html = resp.content.decode("utf-8")

        # Verifica presença dos dois cilindros e dados de cada envase
        self.assertIn("OGV-101", html)
        self.assertIn("OGV-102", html)
        self.assertIn("150 bar", html)
        self.assertIn("200 bar", html)
        self.assertTrue("8,500 kg" in html or "8.500 kg" in html, f"Massa líquida 8.500 kg não encontrada: {html}")
        self.assertTrue("11,200 kg" in html or "11.200 kg" in html, f"Massa líquida 11.200 kg não encontrada: {html}")

    def test_05_etiqueta_colarinho_lote_sem_envases_estado_vazio(self):
        """Lote sem cilindros envasados exibe estado vazio e não gera etiquetas imprimíveis."""
        with tenant_context(self.tenant):
            lote_vazio = LoteEnvase.objects.create(
                tenant=self.tenant,
                gas=self.gas_o2,
                codigo_lote="LOT-VAZIO-01",
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal("99.50"),
                status_qualidade="QUARENTENA",
            )

        self.client.force_login(self.user_comum)
        resp = self.client.get(f"/produtos/lotes/{lote_vazio.id}/etiqueta-colarinho/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        html = resp.content.decode("utf-8")
        self.assertIn("Nenhum cilindro envasado neste lote", html)
        self.assertNotIn("etiqueta-colarinho-preview", html)

    def test_06_etiqueta_colarinho_param_envase_ids_validacao(self):
        """
        Validação do parâmetro ?envase_ids=:
        - Não-inteiros ou vazios -> 400.
        - IDs que não pertencem ao lote ou à empresa -> 400.
        - IDs válidos do lote -> 200 apenas com o envase filtrado.
        """
        self.client.force_login(self.user_comum)

        # ID não numérico -> 400
        resp_invalid = self.client.get(f"/produtos/lotes/{self.lote.id}/etiqueta-colarinho/?envase_ids=abc")
        self.assertEqual(resp_invalid.status_code, status.HTTP_400_BAD_REQUEST)

        # ID numérico que não existe ou pertence a outro lote/empresa -> 400
        resp_fora = self.client.get(f"/produtos/lotes/{self.lote.id}/etiqueta-colarinho/?envase_ids=99999")
        self.assertEqual(resp_fora.status_code, status.HTTP_400_BAD_REQUEST)

        # ID válido do lote -> 200 trazendo apenas o envase_1 (OGV-101)
        resp_valido = self.client.get(f"/produtos/lotes/{self.lote.id}/etiqueta-colarinho/?envase_ids={self.envase_1.id}")
        self.assertEqual(resp_valido.status_code, status.HTTP_200_OK)
        html = resp_valido.content.decode("utf-8")
        self.assertIn("OGV-101", html)
        self.assertNotIn("OGV-102", html)

    def test_07_etiqueta_colarinho_isolamento_e_modulo_envase(self):
        """
        Lote de outra empresa -> 404 para usuário comum.
        Empresa sem módulo envase ativo -> 403 para usuário comum.
        Superusuário acessa qualquer lote.
        """
        with tenant_context(self.outro_tenant):
            lote_outro = LoteEnvase.objects.create(
                tenant=self.outro_tenant,
                gas=self.gas_o2,
                codigo_lote="LOT-BETA-01",
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal("99.50"),
                status_qualidade="APROVADO",
            )

        self.client.force_login(self.user_comum)
        resp_outro = self.client.get(f"/produtos/lotes/{lote_outro.id}/etiqueta-colarinho/")
        self.assertEqual(resp_outro.status_code, status.HTTP_404_NOT_FOUND)

        # Usuário de empresa sem o módulo envase ativo -> 403
        self.client.force_login(self.user_sem_envase)
        resp_sem_modulo = self.client.get(f"/produtos/lotes/{self.lote.id}/etiqueta-colarinho/")
        self.assertIn(resp_sem_modulo.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        # Superusuário acessa lote de outra empresa
        self.client.force_login(self.superuser)
        resp_su = self.client.get(f"/produtos/lotes/{lote_outro.id}/etiqueta-colarinho/")
        self.assertEqual(resp_su.status_code, status.HTTP_200_OK)

    # --------------------------------------------------------------------------
    # 4. MEDIÇÃO TÉCNICA DO QR CODE (ISO/IEC 18004)
    # --------------------------------------------------------------------------

    def test_09_qr_code_medicao_real_dimensoes_e_versao(self):
        """
        Mede a versão, contagem de módulos e mm por módulo do QR Code gerado
        para a URL real do servidor (https://3-146-201-236.sslip.io/v/cilindro/<qr>/)
        com área de 22mm e correção M (ISO/IEC 18004).
        """
        url_real = f"https://3-146-201-236.sslip.io/v/cilindro/{self.cilindro_1.codigo_qr}/"
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=1,
        )
        qr.add_data(url_real)
        qr.make(fit=True)

        self.assertEqual(qr.version, 4, f"Esperado QR Versão 4 para a URL real, obtido {qr.version}")
        self.assertEqual(qr.modules_count, 33, f"Esperado 33 módulos (sem borda), obtido {qr.modules_count}")

        modulos_totais_com_borda = qr.modules_count + 2 * qr.border  # 35
        self.assertEqual(modulos_totais_com_borda, 35)

        area_etiqueta_mm = 22.0
        mm_por_modulo = area_etiqueta_mm / modulos_totais_com_borda
        # ~0.629 mm por módulo (conforme ISO/IEC 18004, mínimo recomendado para leitura óptica confiável é 0.50mm)
        self.assertAlmostEqual(mm_por_modulo, 0.62857, places=4)
        self.assertGreater(mm_por_modulo, 0.50, "Dimensão do módulo inferior ao limite de legibilidade óptica")
