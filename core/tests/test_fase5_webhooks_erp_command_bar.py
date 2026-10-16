from unittest.mock import patch, MagicMock
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Tenant, Membership, WebhookEndpoint, WebhookDeliveryLog
from core.tenancy import set_current_tenant, tenant_context
from clientes.models import Cliente, FechamentoFaturaEstadia
from logistica.models import Veiculo, Entrega, Rota
from produtos.models import Cilindro, ModeloCilindro, GasQuimico, LoteEnvase

User = get_user_model()


class Fase5WebhooksERPCommandBarTestCase(APITestCase):
    """
    Testes de integração e unidade para a Fase 5:
    1. Gestão de Webhooks HMAC, exibição única de segredo, rotação e anti-SSRF.
    2. Disparo de Ping de Teste assinado com X-Signature-SHA256 e latência em ms.
    3. Transactional Outbox Delivery Logs e reenvio manual pela API.
    4. Exportação Canônica ERP (JSON paginado e CSV).
    5. Barra de Comando Global (Ctrl+K) com pesquisa federada e isolamento multi-tenant.
    6. Matriz de RBAC (Apenas ADMIN e GERENTE no Cockpit de Integrações).
    """

    def setUp(self):
        # 1. Tenant A
        self.tenant_a = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Gás & Soluções Industriais S/A',
            nome_fantasia='GasSol'
        )
        self.token_tenant = set_current_tenant(self.tenant_a)

        # 2. Usuários e Papéis
        self.admin_user = User.objects.create_user(username='admin_fase5', password='pwd')
        Membership.objects.create(user=self.admin_user, tenant=self.tenant_a, papel='ADMIN')

        self.gerente_user = User.objects.create_user(username='gerente_fase5', password='pwd')
        Membership.objects.create(user=self.gerente_user, tenant=self.tenant_a, papel='GERENTE')

        self.operador_user = User.objects.create_user(username='operador_fase5', password='pwd')
        Membership.objects.create(user=self.operador_user, tenant=self.tenant_a, papel='OPERADOR_PATIO')

        # 3. Tenant B (para teste de isolamento da busca global e webhooks)
        self.tenant_b = Tenant.objects.create(
            cnpj='99.888.777/0001-66',
            razao_social='Concorrente Isolado Ltda',
            nome_fantasia='ConcGas'
        )

        # 4. Dados Básicos para a Busca Global e ERP
        self.gas_o2 = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2-MED',
            categoria='MEDICINAL',
            exige_lote_anvisa=True
        )
        self.modelo_c = ModeloCilindro.objects.create(
            tenant=self.tenant_a,
            descricao='Cilindro Padrão 50L',
            volume_hidraulico_litros=Decimal('50.0'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('45.0')
        )
        self.cilindro_a = Cilindro.objects.create(
            tenant=self.tenant_a,
            codigo_qr='QR-FASE5-001',
            numero_serie_ogiva='OG-998877',
            fabricante='Cilbras',
            ano_fabricacao=2022,
            modelo=self.modelo_c,
            gas_dedicado=self.gas_o2,
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1825),
            status='CHEIO_DISPONIVEL'
        )
        self.lote_a = LoteEnvase.objects.create(
            tenant=self.tenant_a,
            gas=self.gas_o2,
            codigo_lote='LT-2026-F5',
            pureza_percentual=Decimal('99.8'),
            status_qualidade='APROVADO',
            data_envase=timezone.now().date(),
            data_validade=timezone.now().date() + timezone.timedelta(days=730),
            responsavel_tecnico='Dra. Farmacêutica'
        )
        self.cliente_a = Cliente.objects.create(
            tenant=self.tenant_a,
            nome='Hospital São Lucas Central',
            cnpj='44.555.666/0001-77',
            endereco='Av. Paulista, 1000',
            telefone='11999998888',
            estado='SP',
            cidade='São Paulo',
            proprietario='Diretoria Hospitalar'
        )
        self.veiculo_a = Veiculo.objects.create(
            tenant=self.tenant_a,
            placa='BRA5F55',
            modelo='Mercedes Accelo 1016',
            marca='Mercedes-Benz',
            ano=2023,
            capacidade_carga=Decimal('5500.0'),
            status='Ativo'
        )

        # Dado do Tenant B para validar que a busca não vaza
        with tenant_context(self.tenant_b):
            modelo_b = ModeloCilindro.objects.create(
                tenant=self.tenant_b,
                descricao='Cilindro B 50L',
                volume_hidraulico_litros=Decimal('50.0'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('45.0')
            )
            self.cilindro_b = Cilindro.objects.create(
                tenant=self.tenant_b,
                codigo_qr='QR-TENANT-B-999',
                numero_serie_ogiva='OG-B-EXCLUSIVE',
                fabricante='Cilbras',
                ano_fabricacao=2021,
                modelo=modelo_b,
                gas_dedicado=self.gas_o2,
                data_ultimo_reteste=timezone.now().date(),
                data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1825),
                status='CHEIO_DISPONIVEL'
            )

    # ==============================================================================
    # 1. GESTÃO DE WEBHOOKS & EXIBIÇÃO ÚNICA DE SEGREDO HMAC (D7)
    # ==============================================================================
    def test_cadastro_webhook_retorna_secret_apenas_na_criacao(self):
        """
        Garante que o segredo gerado seja exibido apenas na resposta de criação (POST)
        e nunca em leituras posteriores (GET).
        """
        self.client.force_authenticate(user=self.admin_user)

        payload = {
            'url': 'https://api.erp-cliente.com.br/hooks/receber/',
            'descricao': 'ERP Matriz Hospitalar',
            'eventos': ['fatura.fechada', 'romaneio.concluido'],
            'ativo': True
        }

        # 1. Criação via POST
        create_resp = self.client.post('/api/webhooks/', payload, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('secret_exclusivo', create_resp.data, "Deveria retornar o segredo na criação única!")
        raw_secret = create_resp.data['secret_exclusivo']
        self.assertTrue(len(raw_secret) >= 32)
        endpoint_id = create_resp.data['id']

        # 2. Leitura individual via GET
        get_resp = self.client.get(f'/api/webhooks/{endpoint_id}/')
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)
        self.assertNotIn('secret', get_resp.data, "Vulnerabilidade D7: segredo não pode ser exposto no GET!")
        self.assertNotIn('secret_exclusivo', get_resp.data, "Secret exclusivo não pode persistir em GET!")
        self.assertEqual(get_resp.data.get('secret_mascarado'), '••••••••••••••••••••••••••••••••')

        # 3. Leitura em lista via GET
        list_resp = self.client.get('/api/webhooks/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        results = list_resp.data.get('results', list_resp.data)
        for ep in results:
            self.assertNotIn('secret', ep)
            self.assertNotIn('secret_exclusivo', ep)
            self.assertEqual(ep.get('secret_mascarado'), '••••••••••••••••••••••••••••••••')

    def test_rotacionar_secret_gera_nova_chave_e_retorna_uma_unica_vez(self):
        """
        Testa ação de rotação de segredo criptográfico HMAC (POST /api/webhooks/{id}/rotacionar-secret/).
        """
        self.client.force_authenticate(user=self.gerente_user)

        endpoint = WebhookEndpoint.objects.create(
            tenant=self.tenant_a,
            url='https://erp.hospital.com.br/notificacoes/',
            secret='segredo-antigo-123',
            eventos=['fatura.fechada']
        )

        resp = self.client.post(f'/api/webhooks/{endpoint.id}/rotacionar-secret/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['sucesso'])
        self.assertIn('secret_exclusivo', resp.data)
        novo_secret = resp.data['secret_exclusivo']
        self.assertNotEqual(novo_secret, 'segredo-antigo-123')

        # Valida que foi gravado no banco de dados
        endpoint.refresh_from_db()
        self.assertEqual(endpoint.secret, novo_secret)

    def test_bloqueio_antissrf_na_criacao_de_webhook(self):
        """
        Garante que a trava anti-SSRF bloqueia URLs de localhost, 127.0.0.1 e IPs RFC1918.
        """
        self.client.force_authenticate(user=self.admin_user)

        urls_invalidas = [
            'http://127.0.0.1:8000/api/',
            'http://localhost:3000/webhook',
            'http://169.254.169.254/latest/meta-data/'
        ]

        for u in urls_invalidas:
            resp = self.client.post('/api/webhooks/', {'url': u, 'descricao': 'Teste SSRF'}, format='json')
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ==============================================================================
    # 2. DISPARO DE PING DE TESTE COM ASSINATURA HMAC-SHA256 & LATÊNCIA
    # ==============================================================================
    @patch('core.webhooks.requests.post')
    def test_disparar_ping_de_teste_com_hmac_e_latencia(self, mock_post):
        """
        Testa POST /api/webhooks/{id}/testar/ enviando evento ping.teste assinado
        com X-Signature-SHA256 e retornando status e latência em ms.
        """
        self.client.force_authenticate(user=self.admin_user)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": "pong"}'
        mock_post.return_value = mock_resp

        endpoint = WebhookEndpoint.objects.create(
            tenant=self.tenant_a,
            url='https://erp.recebe-webhook.com.br/ping/',
            secret='chave-hmac-teste-ping',
            eventos=['fatura.fechada']  # Mesmo não tendo ping.teste na lista, deve permitir teste direto
        )

        resp = self.client.post(f'/api/webhooks/{endpoint.id}/testar/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['sucesso'])
        self.assertEqual(resp.data['status_code'], 200)
        self.assertIsNotNone(resp.data['latencia_ms'])

        # Garante que requests.post recebeu os cabeçalhos HMAC-SHA256 corretos
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        headers = kwargs['headers']
        self.assertIn('X-Signature-SHA256', headers)
        self.assertEqual(headers['X-Event'], 'ping.teste')
        self.assertEqual(headers['X-Tenant-ID'], str(self.tenant_a.id))

    # ==============================================================================
    # 3. HISTÓRICO DE ENTREGAS (DELIVERY LOGS) & REENVIO MANUAL
    # ==============================================================================
    @patch('core.webhooks.requests.post')
    def test_consulta_logs_outbox_e_reenvio_manual(self, mock_post):
        """
        Testa listagem de WebhookDeliveryLog e o endpoint de reenvio manual POST /api/webhook-logs/{id}/reenviar/.
        """
        self.client.force_authenticate(user=self.admin_user)

        endpoint = WebhookEndpoint.objects.create(
            tenant=self.tenant_a,
            url='https://erp.parceiro.com.br/hooks/',
            secret='segredo-retry',
            eventos=['romaneio.concluido']
        )

        log_falha = WebhookDeliveryLog.objects.create(
            tenant=self.tenant_a,
            endpoint=endpoint,
            evento='romaneio.concluido',
            payload={'romaneio_id': 42},
            status='FALHA',
            status_code=503,
            sucesso=False,
            tentativas=1,
            latencia_ms=120.5
        )

        # 1. Consulta logs na API
        logs_resp = self.client.get('/api/webhook-logs/')
        self.assertEqual(logs_resp.status_code, status.HTTP_200_OK)
        results = logs_resp.data.get('results', logs_resp.data)
        self.assertTrue(any(l['id'] == log_falha.id for l in results))

        # 2. Mock de sucesso no reenvio
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"reprocessado": true}'
        mock_post.return_value = mock_resp

        retry_resp = self.client.post(f'/api/webhook-logs/{log_falha.id}/reenviar/')
        self.assertEqual(retry_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(retry_resp.data['sucesso'])
        self.assertEqual(retry_resp.data['status'], 'SUCESSO')
        self.assertEqual(retry_resp.data['status_code'], 200)

        log_falha.refresh_from_db()
        self.assertEqual(log_falha.status, 'SUCESSO')
        self.assertEqual(log_falha.tentativas, 2)

    # ==============================================================================
    # 4. EXPORTAÇÃO CANÔNICA ERP (JSON E CSV)
    # ==============================================================================
    def test_exportacao_canonica_faturas_json_e_csv(self):
        """
        Valida GET /api/erp/faturas/ em JSON paginado e CSV com colunas canônicas.
        """
        self.client.force_authenticate(user=self.gerente_user)

        fatura = FechamentoFaturaEstadia.objects.create(
            tenant=self.tenant_a,
            cliente=self.cliente_a,
            competencia_ano_mes='2026-10',
            data_fechamento=timezone.now(),
            fechado_por=self.admin_user,
            valor_bruto_diarias=Decimal('1500.00'),
            valor_desconto_carencia=Decimal('200.00'),
            valor_desconto_franquia=Decimal('100.00'),
            valor_ajustes_retroativos=Decimal('0.00'),
            valor_reposicao_extravios=Decimal('0.00'),
            valor_liquido_total=Decimal('1200.00'),
            status_pagamento='ABERTA'
        )

        # 1. Exportação JSON
        json_resp = self.client.get('/api/erp/faturas/?competencia=2026-10')
        self.assertEqual(json_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(json_resp.data['total'], 1)
        fat_data = json_resp.data['faturas'][0]
        self.assertEqual(fat_data['fatura_id'], fatura.id)
        self.assertEqual(fat_data['valores']['liquido_total'], 1200.0)

        # 2. Exportação CSV
        csv_resp = self.client.get('/api/erp/faturas/?format=csv&competencia=2026-10')
        self.assertEqual(csv_resp.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', csv_resp['Content-Type'])
        self.assertIn('faturas_estadia_erp.csv', csv_resp['Content-Disposition'])
        content = csv_resp.content.decode('utf-8-sig')
        self.assertIn('Hospital São Lucas Central', content)
        self.assertIn('1200.00', content)

    def test_exportacao_canonica_entregas_json_e_csv(self):
        """
        Valida GET /api/erp/entregas/ em JSON paginado e CSV com colunas canônicas.
        """
        self.client.force_authenticate(user=self.admin_user)

        rota = Rota.objects.create(
            tenant=self.tenant_a,
            nome='Rota Hospitalar Sul',
            distancia_km=Decimal('25.0'),
            tempo_estimado_horas=Decimal('1.5')
        )
        entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            motorista=self.admin_user,
            rota=rota,
            status='Concluída'
        )

        # 1. Exportação JSON
        json_resp = self.client.get('/api/erp/entregas/?status=Concluída')
        self.assertEqual(json_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(json_resp.data['total'], 1)

        # 2. Exportação CSV
        csv_resp = self.client.get('/api/erp/entregas/?format=csv')
        self.assertEqual(csv_resp.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', csv_resp['Content-Type'])
        content = csv_resp.content.decode('utf-8-sig')
        self.assertIn('BRA5F55', content)
        self.assertIn('Rota Hospitalar Sul', content)

    # ==============================================================================
    # 5. BARRA DE COMANDO GLOBAL (Ctrl+K) & BUSCA UNIFICADA
    # ==============================================================================
    def test_busca_global_pesquisa_federada_e_isolamento(self):
        """
        Testa GET /api/busca-global/?q=... com correspondência por Cilindro, Lote, Cliente e Veículo.
        Valida isolamento multi-tenant estrito (Cilindro do Tenant B não deve aparecer).
        """
        self.client.force_authenticate(user=self.admin_user)

        # 1. Busca por Cilindro (Ogiva)
        resp_cil = self.client.get('/api/busca-global/?q=OG-9988')
        self.assertEqual(resp_cil.status_code, status.HTTP_200_OK)
        results_cil = resp_cil.data['results']
        self.assertTrue(any(r['tipo'] == 'cilindro' and 'OG-998877' in r['titulo'] for r in results_cil))

        # 2. Busca por Lote Químico
        resp_lote = self.client.get('/api/busca-global/?q=LT-2026')
        self.assertEqual(resp_lote.status_code, status.HTTP_200_OK)
        results_lote = resp_lote.data['results']
        self.assertTrue(any(r['tipo'] == 'lote' and 'LT-2026-F5' in r['titulo'] for r in results_lote))

        # 3. Busca por Cliente (CNPJ / Nome)
        resp_cli = self.client.get('/api/busca-global/?q=São Lucas')
        self.assertEqual(resp_cli.status_code, status.HTTP_200_OK)
        results_cli = resp_cli.data['results']
        self.assertTrue(any(r['tipo'] == 'cliente' and 'Hospital São Lucas' in r['titulo'] for r in results_cli))

        # 4. Busca por Veículo (Placa)
        resp_veic = self.client.get('/api/busca-global/?q=BRA5F55')
        self.assertEqual(resp_veic.status_code, status.HTTP_200_OK)
        results_veic = resp_veic.data['results']
        self.assertTrue(any(r['tipo'] == 'veiculo' and 'BRA5F55' in r['titulo'] for r in results_veic))

        # 5. ISOLAMENTO MULTI-TENANT: Buscar pelo cilindro do Tenant B não pode retornar nada
        resp_isol = self.client.get('/api/busca-global/?q=OG-B-EXCLUSIVE')
        self.assertEqual(resp_isol.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_isol.data['results']), 0, "Falha de isolamento: dado do Tenant B retornado no Tenant A!")

    # ==============================================================================
    # 6. MATRIZ DE RBAC: CONTROLE DE ACESSO AO COCKPIT DE INTEGRAÇÕES
    # ==============================================================================
    def test_rbac_acesso_integracoes(self):
        """
        ADMIN e GERENTE têm acesso liberado ao cockpit de integrações e APIs.
        OPERADOR_PATIO é bloqueado com 403 Forbidden.
        """
        # 1. Admin acessa
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(self.client.get('/integracoes/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/api/webhooks/').status_code, status.HTTP_200_OK)

        # 2. Gerente acessa
        self.client.force_authenticate(user=self.gerente_user)
        self.assertEqual(self.client.get('/integracoes/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/api/webhooks/').status_code, status.HTTP_200_OK)

        # 3. Operador de Pátio é bloqueado
        self.client.force_authenticate(user=self.operador_user)
        self.assertEqual(self.client.get('/integracoes/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/webhooks/').status_code, status.HTTP_403_FORBIDDEN)
