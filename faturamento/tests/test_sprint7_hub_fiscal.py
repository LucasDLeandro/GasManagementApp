import hmac
import hashlib
import json
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils import timezone
from django.conf import settings
from rest_framework.test import APIClient

from core.models import Tenant, Membership, PerfilRegulatorioTenant
from core.tenancy import tenant_context, set_current_tenant, reset_current_tenant
from accounts.models import User
from clientes.models import Cliente, FechamentoFaturaEstadia
from vendas.models import Venda, ItemVenda
from produtos.models import Produto, GasQuimico, ModeloCilindro
from faturamento.models import ConfiguracaoFiscalTenant, NotaFiscal, FaturaCobranca
from faturamento.tasks import emitir_nfe_task
from faturamento.crypto import encrypt_secret, decrypt_secret

TEST_GATEWAY_SECRET = "super_segredo_gateway_teste_123"
TEST_NFE_SECRET = "super_segredo_nfe_teste_456"


@override_settings(
    GATEWAY_WEBHOOK_SECRET=TEST_GATEWAY_SECRET,
    NFE_WEBHOOK_SECRET=TEST_NFE_SECRET,
    FIELD_ENCRYPTION_KEY="mvI3kOqWn0Rm4IAEw7MWZ8eWJZUJb7RU2moN0PGYqjo="
)
class Sprint7HubFiscalTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            razao_social="Oxigênio & Gases Baros LTDA",
            nome_fantasia="Baros Gás",
            cnpj="12.345.678/0001-90",
            plano="PRO"
        )
        self.perfil = PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='DISTRIBUIDORA',
            afe_numero='AFE-123',
            licenca_sanitaria_numero='LIC-123',
            licenca_sanitaria_validade=timezone.now().date() + timezone.timedelta(days=365)
        )

        with tenant_context(self.tenant):
            self.user = User.objects.create_user(
                username="gerente_fiscal",
                email="fiscal@baros.com.br",
                password="senha_segura_123"
            )
            Membership.objects.create(
                user=self.user,
                tenant=self.tenant,
                papel='ADMIN',
                ativo=True
            )

            self.cliente = Cliente.objects.create(
                tenant=self.tenant,
                nome="Hospital Central de Urgência",
                cnpj="98.765.432/0001-10",
                endereco="Av. Paulista, 1000",
                bairro="Bela Vista",
                cidade="São Paulo",
                estado="SP",
                cep="01310-100",
                telefone="11999998888",
                proprietario="Dr. Carlos"
            )

            self.produto = Produto.objects.create(
                tenant=self.tenant,
                nome="Carga O2 10m3",
                categoria="Medicinal",
                capacidade=Decimal('10.0'),
                unidade_medida="m³",
                preco=Decimal('150.00'),
                estoque=10
            )

            self.venda = Venda.objects.create(
                tenant=self.tenant,
                cliente=self.cliente,
                valor_total=Decimal('300.00'),
                status='Pendente'
            )
            ItemVenda.objects.create(
                tenant=self.tenant,
                venda=self.venda,
                produto=self.produto,
                quantidade=2,
                valor_unitario=Decimal('150.00'),
                valor_total=Decimal('300.00')
            )

            self.config_fiscal = ConfiguracaoFiscalTenant.objects.create(
                tenant=self.tenant,
                cnpj_emissor="12.345.678/0001-90",
                inscricao_estadual="123456789",
                ambiente="HOMOLOGACAO",
                token_api_focus="focus_token_valido_xyz"
            )
            self.config_fiscal.set_senha_certificado("SenhaSuperSecretaCertA1")
            self.config_fiscal.save()

        self.client = APIClient()

    # =========================================================================
    # 7.1. Modelagem & Criptografia
    # =========================================================================
    def test_criptografia_simetrica_senha_certificado(self):
        """Verifica que a senha do certificado A1 é cifrada no banco e decifrada corretamente."""
        cf = ConfiguracaoFiscalTenant.objects.get(tenant=self.tenant)
        self.assertNotEqual(cf.senha_certificado, "SenhaSuperSecretaCertA1")
        self.assertTrue(len(cf.senha_certificado) > 30)
        self.assertEqual(cf.get_senha_certificado(), "SenhaSuperSecretaCertA1")
        self.assertEqual(cf.senha_descriptografada, "SenhaSuperSecretaCertA1")

    def test_criacao_fatura_cobranca_com_uuid_e_status(self):
        """Valida que FaturaCobranca herda de TenantAwareModel e possui UUID público."""
        with tenant_context(self.tenant):
            fatura = FaturaCobranca.objects.create(
                tenant=self.tenant,
                venda=self.venda,
                gateway_id="pay_abc123456",
                valor=Decimal('300.00'),
                data_vencimento=timezone.now().date() + timezone.timedelta(days=5)
            )
            self.assertIsNotNone(fatura.uuid)
            self.assertEqual(fatura.status, 'ABERTA')
            self.assertEqual(fatura.tenant, self.tenant)

    # =========================================================================
    # 7.2. Celery Async Task & Retries
    # =========================================================================
    @patch('requests.post')
    def test_emitir_nfe_task_sucesso_autorizada(self, mock_post):
        """Valida execução assíncrona com transição de status para AUTORIZADA."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "autorizado",
            "chave_nfe": "35261012345678000190550010000000011000000011",
            "numero": "1",
            "caminho_xml_nota_fiscal": "https://api.focusnfe.com.br/xml/35261012345.xml",
            "caminho_danfe": "https://api.focusnfe.com.br/danfe/35261012345.pdf"
        }
        mock_post.return_value = mock_response

        resultado = emitir_nfe_task(str(self.tenant.id), self.venda.id, 'VENDA')
        self.assertTrue(resultado['sucesso'])
        self.assertEqual(resultado['status'], 'AUTORIZADA')

        with tenant_context(self.tenant):
            nfe = NotaFiscal.objects.get(venda=self.venda)
            self.assertEqual(nfe.status, 'AUTORIZADA')
            self.assertEqual(nfe.chave_acesso, "35261012345678000190550010000000011000000011")
            self.assertEqual(nfe.danfe_url, "https://api.focusnfe.com.br/danfe/35261012345.pdf")
            self.assertIsNotNone(nfe.data_emissao)

    @patch('requests.post')
    def test_emitir_nfe_task_timeout_agenda_retry(self, mock_post):
        """Valida que HTTP 504 (Gateway Timeout) dispara retry automático no Celery."""
        mock_response = MagicMock()
        mock_response.status_code = 504
        mock_response.text = "Gateway Timeout"
        mock_post.return_value = mock_response

        with self.assertRaises(Exception):
            # No modo de teste síncrono, self.retry lança a exceção de retry
            emitir_nfe_task(str(self.tenant.id), self.venda.id, 'VENDA')

        with tenant_context(self.tenant):
            nfe = NotaFiscal.objects.get(venda=self.venda)
            self.assertEqual(nfe.status, 'PROCESSANDO')

    def test_emitir_nfe_task_sem_configuracao_fiscal_rejeita(self):
        """Se o tenant não possuir configuração fiscal, a NF-e é rejeitada imediatamente (Fail-Closed)."""
        ConfiguracaoFiscalTenant.objects.filter(tenant=self.tenant).delete()

        resultado = emitir_nfe_task(str(self.tenant.id), self.venda.id, 'VENDA')
        self.assertFalse(resultado['sucesso'])

        with tenant_context(self.tenant):
            nfe = NotaFiscal.objects.get(venda=self.venda)
            self.assertEqual(nfe.status, 'REJEITADA')
            self.assertIn("não cadastrada", nfe.motivo_rejeicao)

    # =========================================================================
    # 7.3. Segurança de Webhooks (HMAC-SHA256 & Fail-Closed)
    # =========================================================================
    def test_webhook_gateway_sem_assinatura_retorna_403(self):
        """Webhook sem cabeçalho HMAC deve ser rejeitado imediatamente com HTTP 403."""
        payload = {"gateway_id": "pay_999", "status": "PAGA"}
        response = self.client.post(
            '/faturamento/webhooks/gateway/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("Assinatura HMAC", response.json().get('erro', ''))

    def test_webhook_gateway_assinatura_invalida_retorna_403(self):
        """Webhook com assinatura HMAC divergente deve ser sumariamente bloqueado."""
        payload = {"gateway_id": "pay_999", "status": "PAGA"}
        response = self.client.post(
            '/faturamento/webhooks/gateway/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_SIGNATURE="sha256=hash_adulterado_ou_invalido"
        )
        self.assertEqual(response.status_code, 403)

    def test_webhook_gateway_assinatura_valida_liquida_fatura(self):
        """Webhook autêntico processa o pagamento e atualiza a FaturaCobranca para PAGA."""
        with tenant_context(self.tenant):
            fatura = FaturaCobranca.objects.create(
                tenant=self.tenant,
                venda=self.venda,
                gateway_id="pay_gateway_valido_777",
                valor=Decimal('300.00'),
                data_vencimento=timezone.now().date()
            )

        payload_dict = {
            "gateway_id": "pay_gateway_valido_777",
            "evento": "payment.succeeded",
            "status": "PAGA"
        }
        body_bytes = json.dumps(payload_dict).encode('utf-8')
        sig = hmac.new(TEST_GATEWAY_SECRET.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()

        response = self.client.post(
            '/faturamento/webhooks/gateway/',
            data=body_bytes,
            content_type='application/json',
            HTTP_X_SIGNATURE=f"sha256={sig}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('sucesso'))

        with tenant_context(self.tenant):
            fatura.refresh_from_db()
            self.assertEqual(fatura.status, 'PAGA')
            self.assertIsNotNone(fatura.data_pagamento)
            self.venda.refresh_from_db()
            self.assertEqual(self.venda.status, 'Em Separação')

    def test_webhook_nfe_callback_sefaz_autorizada(self):
        """Webhook assinado da SEFAZ atualiza NotaFiscal para AUTORIZADA."""
        with tenant_context(self.tenant):
            nfe = NotaFiscal.objects.create(
                tenant=self.tenant,
                venda=self.venda,
                chave_acesso="35261000000000000000550010000000021000000022",
                status='PROCESSANDO',
                valor_total=Decimal('300.00')
            )

        payload_dict = {
            "chave_nfe": "35261000000000000000550010000000021000000022",
            "status": "autorizado",
            "caminho_xml_nota_fiscal": "https://api.focusnfe.com.br/xml/autorizado.xml",
            "caminho_danfe": "https://api.focusnfe.com.br/danfe/autorizado.pdf"
        }
        body_bytes = json.dumps(payload_dict).encode('utf-8')
        sig = hmac.new(TEST_NFE_SECRET.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()

        response = self.client.post(
            '/faturamento/webhooks/nfe/',
            data=body_bytes,
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE=sig
        )
        self.assertEqual(response.status_code, 200)

        with tenant_context(self.tenant):
            nfe.refresh_from_db()
            self.assertEqual(nfe.status, 'AUTORIZADA')
            self.assertEqual(nfe.danfe_url, "https://api.focusnfe.com.br/danfe/autorizado.pdf")

    # =========================================================================
    # Consulta Pública Segura (UUIDv4)
    # =========================================================================
    def test_consulta_cobranca_publica_por_uuid(self):
        """Endpoint público de fatura deve ser acessível por UUIDv4 sem vazar IDs de outros tenants."""
        with tenant_context(self.tenant):
            fatura = FaturaCobranca.objects.create(
                tenant=self.tenant,
                venda=self.venda,
                gateway_id="pay_pub_123",
                valor=Decimal('300.00'),
                qr_code_pix="00020126580014BR.GOV.BCB.PIX...",
                data_vencimento=timezone.now().date()
            )

        response = self.client.get(f'/faturamento/cobranca/{fatura.uuid}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['uuid'], str(fatura.uuid))
        self.assertEqual(data['status'], 'ABERTA')
        self.assertEqual(data['cliente'], "Hospital Central de Urgência")
        self.assertIn("00020126580014BR.GOV.BCB.PIX", data['qr_code_pix'])

        # Busca com UUID inexistente retorna 404
        random_uuid = uuid.uuid4()
        resp_404 = self.client.get(f'/faturamento/cobranca/{random_uuid}/')
        self.assertEqual(resp_404.status_code, 404)
