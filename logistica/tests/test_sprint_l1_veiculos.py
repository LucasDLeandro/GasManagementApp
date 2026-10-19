import io
import uuid
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock
from PIL import Image

from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from logistica.models import (
    Veiculo,
    VeiculoFoto,
    VeiculoDocumento,
    DocumentoObrigatorioVeiculo,
    VeiculoValorFipe,
    LogExcecaoOperacionalVeiculo,
    Entrega,
    Rota
)
from logistica.services import veiculo_apto_para_operar
from logistica.services.fipe import (
    obter_marcas_fipe,
    obter_modelos_fipe,
    obter_valor_fipe,
    obter_valor_por_codigo_fipe,
    parse_fipe_valor
)
from logistica.views import validar_upload_imagem, validar_upload_documento

User = get_user_model()


def gerar_imagem_em_memoria(formato='PNG', size=(100, 100), color='blue'):
    file_io = io.BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(file_io, format=formato)
    file_io.seek(0)
    return file_io


class SprintL1VeiculoModelTestCase(TestCase):
    def setUp(self):
        self.tenant1 = Tenant.objects.create(
            razao_social="Transportes Alfa Ltda",
            nome_fantasia="Alfa Log",
            cnpj="11111111000111"
        )
        self.tenant2 = Tenant.objects.create(
            razao_social="Transportes Beta Ltda",
            nome_fantasia="Beta Log",
            cnpj="22222222000122"
        )
        self.token = set_current_tenant(self.tenant1)

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_unicidade_chassi_por_empresa(self):
        chassi_teste = "9BWZZZ377VT004251"
        # Cria veículo no tenant 1
        v1 = Veiculo.objects.create(
            tenant=self.tenant1,
            placa="ABC1D23",
            modelo="Delivery 11.180",
            marca="VW",
            ano=2023,
            capacidade_carga=Decimal("5000.00"),
            chassi=chassi_teste
        )
        self.assertIsNotNone(v1.id)

        from django.db import transaction
        # Tentativa de criar outro veículo com MESMO chassi no MESMO tenant deve falhar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Veiculo.objects.create(
                    tenant=self.tenant1,
                    placa="XYZ9K88",
                    modelo="Delivery 9.170",
                    marca="VW",
                    ano=2023,
                    capacidade_carga=Decimal("4000.00"),
                    chassi=chassi_teste
                )

        # Criar veículo com o mesmo chassi em OUTRO tenant deve ter sucesso (multi-tenant isolado)
        set_current_tenant(self.tenant2)
        v2 = Veiculo.objects.create(
            tenant=self.tenant2,
            placa="BTA2E44",
            modelo="Accelo 1016",
            marca="Mercedes-Benz",
            ano=2023,
            capacidade_carga=Decimal("5500.00"),
            chassi=chassi_teste
        )
        self.assertIsNotNone(v2.id)

    def test_chassi_vazio_ou_nulo_permite_multiplos(self):
        # Múltiplos veículos sem chassi não devem colidir
        v1 = Veiculo.objects.create(
            tenant=self.tenant1,
            placa="AAA1A11",
            modelo="Caminhão A",
            marca="Ford",
            ano=2020,
            capacidade_carga=Decimal("3000.00"),
            chassi=None
        )
        v2 = Veiculo.objects.create(
            tenant=self.tenant1,
            placa="BBB2B22",
            modelo="Caminhão B",
            marca="Ford",
            ano=2020,
            capacidade_carga=Decimal("3000.00"),
            chassi=""
        )
        self.assertIsNotNone(v1.id)
        self.assertIsNotNone(v2.id)

    def test_valor_mercado_estimado_property(self):
        v = Veiculo.objects.create(
            tenant=self.tenant1,
            placa="VAL1E23",
            modelo="Constellation",
            marca="VW",
            ano=2022,
            capacidade_carga=Decimal("14000.00"),
            fipe_valor=Decimal("280000.00"),
            valor_adicionais=Decimal("45000.00")
        )
        # Valor de mercado = FIPE + Adicionais
        self.assertEqual(v.valor_mercado_estimado, Decimal("325000.00"))

    def test_foto_principal_unica_garantida(self):
        v = Veiculo.objects.create(
            tenant=self.tenant1,
            placa="FOT1E23",
            modelo="Accelo",
            marca="Mercedes",
            ano=2021,
            capacidade_carga=Decimal("6000.00")
        )

        img_bytes1 = gerar_imagem_em_memoria('JPEG', color='red').getvalue()
        file1 = SimpleUploadedFile("frente.jpg", img_bytes1, content_type="image/jpeg")
        foto1 = VeiculoFoto.objects.create(
            tenant=self.tenant1,
            veiculo=v,
            imagem=file1,
            tipo="Frente",
            principal=True
        )
        self.assertTrue(foto1.principal)
        self.assertIsNotNone(foto1.miniatura)

        # Cria segunda foto marcando como principal
        img_bytes2 = gerar_imagem_em_memoria('PNG', color='green').getvalue()
        file2 = SimpleUploadedFile("traseira.png", img_bytes2, content_type="image/png")
        foto2 = VeiculoFoto.objects.create(
            tenant=self.tenant1,
            veiculo=v,
            imagem=file2,
            tipo="Traseira",
            principal=True
        )

        foto1.refresh_from_db()
        foto2.refresh_from_db()
        # Foto 1 deve ter perdido o status de principal
        self.assertFalse(foto1.principal)
        self.assertTrue(foto2.principal)
        self.assertEqual(v.foto_principal.id, foto2.id)


class SprintL1UploadValidationTestCase(TestCase):
    def test_validar_upload_imagem_tamanho_excedido(self):
        # Simula arquivo maior que 5 MB
        conteudo = b"0" * (6 * 1024 * 1024)
        arquivo = SimpleUploadedFile("pesado.jpg", conteudo, content_type="image/jpeg")
        with self.assertRaises(DRFValidationError) as ctx:
            validar_upload_imagem(arquivo, max_mb=5)
        self.assertIn("excede o limite de 5 MB", str(ctx.exception))

    def test_validar_upload_imagem_extensao_invalida(self):
        img_bytes = gerar_imagem_em_memoria('PNG').getvalue()
        arquivo = SimpleUploadedFile("script.exe", img_bytes, content_type="application/octet-stream")
        with self.assertRaises(DRFValidationError) as ctx:
            validar_upload_imagem(arquivo, max_mb=5)
        self.assertIn("Extensão .exe não permitida", str(ctx.exception))

    def test_validar_upload_imagem_mime_falso(self):
        # Arquivo de texto renomeado para .jpg
        falso = SimpleUploadedFile("foto_falsa.jpg", b"Texto comum disfarcado de imagem", content_type="image/jpeg")
        with self.assertRaises(DRFValidationError) as ctx:
            validar_upload_imagem(falso, max_mb=5)
        self.assertIn("Arquivo corrompido ou formato de imagem inválido", str(ctx.exception))

    def test_validar_upload_documento_pdf_falso(self):
        # Arquivo não contendo cabeçalho %PDF
        pdf_falso = SimpleUploadedFile("laudo.pdf", b"Conteudo fake sem header PDF", content_type="application/pdf")
        with self.assertRaises(DRFValidationError) as ctx:
            validar_upload_documento(pdf_falso, max_mb=10)
        self.assertIn("não é um PDF válido", str(ctx.exception))

    def test_validar_upload_documento_valido(self):
        pdf_valido = SimpleUploadedFile("laudo.pdf", b"%PDF-1.4 header valido ...", content_type="application/pdf")
        # Não deve levantar exceção
        validar_upload_documento(pdf_valido, max_mb=10)


class SprintL1BloqueioOperacionalTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            razao_social="Transportadora Nacional Ltda",
            nome_fantasia="Nacional Log",
            cnpj="33333333000133"
        )
        self.token = set_current_tenant(self.tenant)

        self.gestor = User.objects.create_user(username="gestor_frota", password="password123")
        Membership.objects.create(user=self.gestor, tenant=self.tenant, papel="GERENTE", ativo=True)

        self.motorista = User.objects.create_user(username="motorista_comum", password="password123")
        Membership.objects.create(user=self.motorista, tenant=self.tenant, papel="MOTORISTA", ativo=True)

        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="OPR1A23",
            modelo="Atego 1719",
            marca="Mercedes",
            ano=2022,
            capacidade_carga=Decimal("8000.00"),
            status_ativo="Ativo"
        )
        self.rota = Rota.objects.create(
            tenant=self.tenant,
            nome="Rota Norte",
            origem="Base",
            destino="Filial Norte",
            distancia_km=Decimal("40.00"),
            tempo_estimado_horas=Decimal("2.00")
        )
        self.client = APIClient()

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_bloqueio_por_status_inativo(self):
        self.veiculo.status_ativo = "Em Manutenção"
        self.veiculo.save()

        apto, motivos = veiculo_apto_para_operar(self.veiculo, tenant=self.tenant)
        self.assertFalse(apto)
        self.assertIn("Em Manutenção", motivos[0])

        # Tentativa de criar Entrega com veículo em manutenção via API
        self.client.force_authenticate(user=self.motorista)
        res = self.client.post("/logistica/api/entregas/", {
            "veiculo": self.veiculo.id,
            "rota": self.rota.id,
            "status": "Agendada"
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("inapto para operar", str(res.data))

    def test_bloqueio_por_documento_vencido(self):
        # Adiciona CRLV vencido há 5 dias
        ontem = timezone.localdate() - timedelta(days=5)
        VeiculoDocumento.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            tipo="CRLV",
            numero="123456",
            vencimento=ontem,
            ativo=True
        )

        apto, motivos = veiculo_apto_para_operar(self.veiculo, tenant=self.tenant)
        self.assertFalse(apto)
        self.assertTrue(any("vencido" in m.lower() for m in motivos))

    def test_bloqueio_por_documento_obrigatorio_ausente(self):
        # Empresa configura CRLV e RNTRC como obrigatórios
        DocumentoObrigatorioVeiculo.objects.create(
            tenant=self.tenant,
            tipo="CRLV",
            ativo=True
        )
        DocumentoObrigatorioVeiculo.objects.create(
            tenant=self.tenant,
            tipo="RNTRC",
            ativo=True
        )

        # Veículo não possui nenhum documento
        apto, motivos = veiculo_apto_para_operar(self.veiculo, tenant=self.tenant)
        self.assertFalse(apto)
        self.assertTrue(any("CRLV" in m for m in motivos))
        self.assertTrue(any("RNTRC" in m for m in motivos))

        # Cadastra CRLV e RNTRC em dia
        hoje = timezone.localdate()
        VeiculoDocumento.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            tipo="CRLV",
            vencimento=hoje + timedelta(days=180),
            ativo=True
        )
        VeiculoDocumento.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            tipo="RNTRC",
            vencimento=hoje + timedelta(days=365),
            ativo=True
        )

        apto_agora, motivos_agora = veiculo_apto_para_operar(self.veiculo, tenant=self.tenant)
        self.assertTrue(apto_agora)
        self.assertEqual(len(motivos_agora), 0)

    def test_excecao_gestor_com_log_auditavel(self):
        # Veículo inapto por estar em manutenção
        self.veiculo.status_ativo = "Em Manutenção"
        self.veiculo.save()

        # 1. Operador comum tenta forçar com justificativa -> rejeitado
        self.client.force_authenticate(user=self.motorista)
        res_negada = self.client.post("/logistica/api/entregas/", {
            "veiculo": self.veiculo.id,
            "rota": self.rota.id,
            "status": "Agendada",
            "justificativa_excecao": "Tentei liberar"
        }, format="json")
        self.assertEqual(res_negada.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Gestor envia justificativa obrigatória -> liberado e registrado em auditoria
        self.client.force_authenticate(user=self.gestor)
        justificativa = "Liberação emergencial autorizada por gestor para atendimento hospitalar crítico."
        res_aprovada = self.client.post("/logistica/api/entregas/", {
            "veiculo": self.veiculo.id,
            "rota": self.rota.id,
            "status": "Agendada",
            "justificativa_excecao": justificativa
        }, format="json")
        self.assertEqual(res_aprovada.status_code, status.HTTP_201_CREATED)

        # Verifica log de auditoria
        log = LogExcecaoOperacionalVeiculo.objects.filter(veiculo=self.veiculo).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.usuario, self.gestor)
        self.assertEqual(log.justificativa, justificativa)
        self.assertTrue(any("Em Manutenção" in m for m in log.motivos_bloqueio))


class SprintL1FipeIntegrationTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            razao_social="Fipe Teste Ltda",
            cnpj="44444444000144"
        )
        self.token = set_current_tenant(self.tenant)
        from django.core.cache import cache
        cache.clear()

    def tearDown(self):
        reset_current_tenant(self.token)
        from django.core.cache import cache
        cache.clear()

    @patch('logistica.services.fipe.requests.get')
    def test_fipe_sucesso_e_cache(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"code": "102", "name": "Volkswagen"},
            {"code": "103", "name": "Mercedes-Benz"}
        ]
        mock_get.return_value = mock_response

        # Primeira chamada busca na API
        sucesso1, marcas1, erro1 = obter_marcas_fipe('caminhoes')
        self.assertTrue(sucesso1)
        self.assertEqual(len(marcas1), 2)
        self.assertEqual(mock_get.call_count, 1)

        # Segunda chamada deve ser servida pelo cache Django
        sucesso2, marcas2, erro2 = obter_marcas_fipe('caminhoes')
        self.assertTrue(sucesso2)
        self.assertEqual(len(marcas2), 2)
        self.assertEqual(mock_get.call_count, 1)

    @patch('logistica.services.fipe.requests.get')
    def test_fipe_rate_limit_429(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        sucesso, marcas, erro = obter_marcas_fipe('caminhoes')
        self.assertFalse(sucesso)
        self.assertIsNotNone(erro)
        self.assertIn('Limite diário', erro)

    @patch('logistica.services.fipe.requests.get')
    def test_fipe_timeout_ou_indisponivel(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        sucesso, marcas, erro = obter_marcas_fipe('caminhoes')
        self.assertFalse(sucesso)
        self.assertIsNotNone(erro)
        self.assertTrue('timeout' in erro.lower() or 'indisponível' in erro.lower())

    @patch('logistica.services.fipe.requests.get')
    def test_comando_atualizar_fipe(self, mock_get):
        v = Veiculo.objects.create(
            tenant=self.tenant,
            placa="FIP1A23",
            modelo="Delivery",
            marca="VW",
            ano=2023,
            capacidade_carga=Decimal("5000.00"),
            fipe_codigo="002165-2",
            fipe_ano_codigo="2023-1"
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "price": "R$ 250.000,00",
            "referenceMonth": "outubro de 2026",
            "codeFipe": "002165-2",
            "brand": "VW",
            "model": "Delivery"
        }
        mock_get.return_value = mock_resp

        call_command('atualizar_fipe', limite_reqs=10)

        v.refresh_from_db()
        self.assertEqual(v.fipe_valor, Decimal("250000.00"))
        self.assertEqual(v.fipe_mes_referencia, "outubro de 2026")

        snapshot = VeiculoValorFipe.objects.filter(veiculo=v, mes_referencia="outubro de 2026").first()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.valor, Decimal("250000.00"))


class SprintL1IsolamentoMidiaTestCase(TestCase):
    def setUp(self):
        self.tenant1 = Tenant.objects.create(razao_social="Tenant 1", cnpj="55555555000155")
        self.tenant2 = Tenant.objects.create(razao_social="Tenant 2", cnpj="66666666000166")

        self.u1 = User.objects.create_user(username="user_t1", password="password123")
        Membership.objects.create(user=self.u1, tenant=self.tenant1, papel="OPERADOR", ativo=True)

        self.u2 = User.objects.create_user(username="user_t2", password="password123")
        Membership.objects.create(user=self.u2, tenant=self.tenant2, papel="OPERADOR", ativo=True)

        set_current_tenant(self.tenant1)
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant1,
            placa="ISO1A23",
            modelo="Caminhão T1",
            marca="Scania",
            ano=2021,
            capacidade_carga=Decimal("10000.00")
        )

        img_bytes = gerar_imagem_em_memoria('PNG').getvalue()
        file_img = SimpleUploadedFile("foto.png", img_bytes, content_type="image/png")
        self.foto = VeiculoFoto.objects.create(
            tenant=self.tenant1,
            veiculo=self.veiculo,
            imagem=file_img,
            tipo="Frente",
            principal=True
        )

        pdf_bytes = b"%PDF-1.4 documento confidencial"
        file_doc = SimpleUploadedFile("crlv.pdf", pdf_bytes, content_type="application/pdf")
        self.doc = VeiculoDocumento.objects.create(
            tenant=self.tenant1,
            veiculo=self.veiculo,
            tipo="CRLV",
            arquivo=file_doc,
            vencimento=timezone.localdate() + timedelta(days=90)
        )
        self.client = APIClient()

    def test_acesso_bloqueado_entre_tenants_para_fotos_e_documentos(self):
        # Usuário do Tenant 2 tenta acessar a foto do veículo do Tenant 1
        self.client.force_authenticate(user=self.u2)
        res_foto = self.client.get(f"/logistica/api/veiculos/fotos/{self.foto.id}/arquivo/", HTTP_X_TENANT_ID=str(self.tenant2.id))
        self.assertEqual(res_foto.status_code, status.HTTP_404_NOT_FOUND)

        # Usuário do Tenant 2 tenta acessar documento sensível do veículo do Tenant 1
        res_doc = self.client.get(f"/logistica/api/veiculos/documentos/{self.doc.id}/arquivo/", HTTP_X_TENANT_ID=str(self.tenant2.id))
        self.assertEqual(res_doc.status_code, status.HTTP_404_NOT_FOUND)

        # Usuário do Tenant 1 acessa normalmente
        self.client.force_authenticate(user=self.u1)
        res_foto_ok = self.client.get(f"/logistica/api/veiculos/fotos/{self.foto.id}/arquivo/", HTTP_X_TENANT_ID=str(self.tenant1.id))
        self.assertEqual(res_foto_ok.status_code, status.HTTP_200_OK)

        res_doc_ok = self.client.get(f"/logistica/api/veiculos/documentos/{self.doc.id}/arquivo/", HTTP_X_TENANT_ID=str(self.tenant1.id))
        self.assertEqual(res_doc_ok.status_code, status.HTTP_200_OK)
