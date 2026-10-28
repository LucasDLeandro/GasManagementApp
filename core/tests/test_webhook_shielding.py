from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Tenant, Membership, WebhookEndpoint, WebhookDeliveryLog, validar_url_webhook_segura
from core.tenancy import set_current_tenant
from core.webhooks import disparar_webhooks_tenant

User = get_user_model()


class WebhookShieldingTestCase(APITestCase):
    """
    Testes de blindagem de Webhooks (D7 - Fase 0):
    1. Secret write_only: não retornado em leituras GET.
    2. Validador SSRF: bloqueio de IPs privados, loopback e link-local.
    3. Outbox transacional: gravação com status PENDENTE e execução com SUCESSO/FALHA.
    4. Comando de gerenciamento para retentativas outbox.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='33.444.555/0001-66',
            razao_social='Segurança Webhooks Ltda',
            nome_fantasia='SegWeb'
        )
        self.token = set_current_tenant(self.tenant)

        self.admin = User.objects.create_user(username='admin_seg', password='pwd')
        Membership.objects.create(user=self.admin, tenant=self.tenant, papel='ADMIN')

    def test_secret_is_write_only_in_api(self):
        """
        Garante que o segredo do webhook nunca seja retornado em leituras GET (D7).
        """
        self.client.force_authenticate(user=self.admin)

        # 1. Cria endpoint via API com secret
        payload = {
            'url': 'https://api.erp-parceiro.com.br/hooks/',
            'secret': 'minha-chave-ultra-secreta-12345',
            'eventos': ['fatura.fechada'],
            'descricao': 'ERP Hospitalar Externo'
        }
        create_resp = self.client.post('/api/webhooks/', payload, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        endpoint_id = create_resp.data['id']

        # 2. Faz GET no endpoint criado e valida ausência do secret
        get_resp = self.client.get(f'/api/webhooks/{endpoint_id}/')
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)
        self.assertNotIn('secret', get_resp.data, "Vulnerabilidade D7: secret não pode ser retornado em GET!")

        # 3. Faz GET na listagem geral e valida ausência do secret
        list_resp = self.client.get('/api/webhooks/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        results = list_resp.data.get('results', list_resp.data)
        for ep in results:
            self.assertNotIn('secret', ep)

    def test_validador_ssrf_bloqueia_loopback_e_ips_privados(self):
        """
        Garante o bloqueio de domínios loopback, link-local e IPs privados para prevenir SSRF (D7).
        """
        urls_proibidas = [
            'http://127.0.0.1:8000/internal-api/',
            'http://localhost:5000/admin/',
            'http://169.254.169.254/latest/meta-data/', # AWS/GCP Metadata link-local
            'http://10.0.0.1/admin',                   # RFC 1918 Classe A
            'http://192.168.1.1/router',               # RFC 1918 Classe C
            'http://172.16.0.1/backend',               # RFC 1918 Classe B
            'http://[::1]/debug',                      # IPv6 loopback
        ]

        for u in urls_proibidas:
            with self.subTest(url=u):
                with self.assertRaises(ValidationError):
                    validar_url_webhook_segura(u)

    @patch('core.webhooks.requests.post')
    def test_outbox_transacional_grava_pendente_e_executa(self, mock_post):
        """
        Valida que o disparo de webhook utiliza o padrão Transactional Outbox (D7).
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true}'
        mock_post.return_value = mock_resp

        endpoint = WebhookEndpoint.objects.create(
            tenant=self.tenant,
            url='https://erp.notifica.com.br/hooks/',
            secret='segredo-outbox-teste',
            eventos=['fatura.fechada']
        )

        with self.captureOnCommitCallbacks(execute=True):
            logs = disparar_webhooks_tenant(
                tenant=self.tenant,
                evento='fatura.fechada',
                payload={'fatura_id': 999, 'total': 1500.0}
            )

        self.assertEqual(len(logs), 1)
        log = logs[0]
        log.refresh_from_db()
        self.assertEqual(log.status, 'SUCESSO')
        self.assertTrue(log.sucesso)
        self.assertEqual(log.tentativas, 1)

    @patch('core.webhooks.requests.post')
    def test_processar_webhooks_outbox_command_retenta_falhas(self, mock_post):
        """
        Valida que o comando processar_webhooks_outbox reprocessa registros com FALHA ou PENDENTE.
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"received": true}'
        mock_post.return_value = mock_resp

        endpoint = WebhookEndpoint.objects.create(
            tenant=self.tenant,
            url='https://erp.retentativa.com.br/hooks/',
            secret='segredo-retry',
            eventos=['romaneio.concluido']
        )

        log = WebhookDeliveryLog.objects.create(
            tenant=self.tenant,
            endpoint=endpoint,
            evento='romaneio.concluido',
            payload={'romaneio_id': 1},
            status='FALHA',
            status_code=500,
            sucesso=False,
            tentativas=1
        )

        # Executa o comando de gerenciamento
        call_command('processar_webhooks_outbox', max_tentativas=5)

        log.refresh_from_db()
        self.assertEqual(log.status, 'SUCESSO')
        self.assertTrue(log.sucesso)
        self.assertEqual(log.tentativas, 2)
