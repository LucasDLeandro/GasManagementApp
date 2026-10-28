import base64
import hashlib
import hmac
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from unittest.mock import patch, MagicMock

from core.models import Tenant, Membership, WebhookEndpoint, WebhookDeliveryLog
from core.tenancy import set_current_tenant, reset_current_tenant
from core.webhooks import disparar_webhooks_tenant
from clientes.models import Cliente
from produtos.models import (
    GasQuimico, ModeloCilindro, Cilindro, LoteEnvase, EnvaseCilindro, MovimentacaoCilindro
)
from produtos.services import (
    registrar_envase_cilindro,
    registrar_entrega_cilindro,
    registrar_recolha_cilindro,
    sincronizar_movimentacoes_offline
)
from logistica.models import Veiculo, Rota, Entrega, ComprovanteEntrega
from logistica.services import (
    validar_capacidade_veiculo_entrega,
    gerar_romaneio_carga_antt_pdf,
    gerar_ficha_emergencia_antt_pdf,
    gerar_envelope_transporte_antt_pdf
)

User = get_user_model()


class Sprint6FieldOperationPWATests(APITestCase):
    """
    Testes de aceitação (DoD) da Sprint 6:
    1. Sincronização em lote offline com idempotência estrita via client_uuid.
    2. Recolha de casco divergente e reteste vencido permitida na rua; entrega de vencido/bloqueado impedida.
    3. Romaneio bilateral com assinatura eletrônica e hash SHA-256 de integridade imutável e seguro.
    4. Validação de capacidade do veículo (bloqueio de sobrecarga) e PDFs ANTT.
    5. Webhooks com assinatura HMAC-SHA256 e APIs canônicas de exportação ERP.
    """

    def setUp(self):
        # Tenant 1
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Gás & Vida Oxigênio Ltda',
            nome_fantasia='Gás & Vida'
        )
        self.token = set_current_tenant(self.tenant)

        # Tenant 2 (para testes de isolamento)
        self.tenant_outro = Tenant.objects.create(
            cnpj='99.888.777/0001-11',
            razao_social='Outra Distribuidora SA',
            nome_fantasia='OutraGas'
        )

        # Usuários
        self.motorista = User.objects.create_user(username='motorista.jose', password='pwd')
        Membership.objects.create(user=self.motorista, tenant=self.tenant, papel='MOTORISTA')

        self.gerente = User.objects.create_user(username='gerente.carlos', password='pwd')
        Membership.objects.create(user=self.gerente, tenant=self.tenant, papel='GERENTE')

        self.user_outro = User.objects.create_user(username='invasor.outro', password='pwd')
        Membership.objects.create(user=self.user_outro, tenant=self.tenant_outro, papel='GERENTE')

        # Cliente
        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome='Hospital São Bento',
            cnpj='22.333.444/0001-55',
            endereco='Av. Paulista, 1000',
            telefone='11999999999',
            estado='SP',
            cidade='São Paulo',
            proprietario='Diretoria'
        )


        # Veículo e Rota
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa='GAS-2026',
            modelo='Iveco Daily 35S14',
            marca='Iveco',
            ano=2024,
            capacidade_carga=Decimal('800.00'), # 800 kg
            status='Ativo'
        )
        self.rota = Rota.objects.create(
            tenant=self.tenant,
            nome='Rota Hospitalar Central',
            origem='Matriz',
            destino='Zona Hospitalar',
            distancia_km=Decimal('25.0'),
            tempo_estimado_horas=Decimal('2.0')
        )
        self.entrega = Entrega.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            rota=self.rota,
            motorista=self.motorista,
            status='Em Rota'
        )

        # Gás e Modelo
        self.gas_o2 = GasQuimico.objects.create(
            sigla='O2-MED',
            nome='Oxigênio Medicinal',
            numero_onu='UN 1072',
            classe_risco='2.2',
            categoria='MEDICINAL',
            exige_lote_anvisa=True
        )

        self.modelo_t50 = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao='T-50 50 Litros',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('55.00')
        )

        # Lote de Envase
        self.lote_valido = LoteEnvase.objects.create(
            tenant=self.tenant,
            codigo_lote='LOT-2026-OK',
            gas=self.gas_o2,
            data_envase=date(2026, 1, 1),
            data_validade=date(2028, 1, 1),
            status_qualidade='APROVADO',
            responsavel_tecnico='Dr. Roberto RT (CRF 1234)'
        )

        # Cilindros de Teste
        # 1. Cilindro Cheio Válido
        self.cilindro_cheio_1 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-CHEIO-001',
            numero_serie_ogiva='SERIE-001',
            fabricante='MAT',
            ano_fabricacao=2021,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.00'),
            data_ultimo_reteste=date(2022, 1, 1),
            data_proximo_reteste=date(2027, 1, 1),
            status='VAZIO_TRIAGEM'
        )
        registrar_envase_cilindro(
            cilindro=self.cilindro_cheio_1,
            lote=self.lote_valido,
            pressao_bar=200,
            usuario=self.gerente,
            client_uuid=uuid.uuid4()
        )
        self.cilindro_cheio_1.refresh_from_db()

        # 2. Cilindro Cheio Válido 2
        self.cilindro_cheio_2 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-CHEIO-002',
            numero_serie_ogiva='SERIE-002',
            fabricante='MAT',
            ano_fabricacao=2021,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.00'),
            data_ultimo_reteste=date(2022, 1, 1),
            data_proximo_reteste=date(2027, 1, 1),
            status='VAZIO_TRIAGEM'
        )
        registrar_envase_cilindro(
            cilindro=self.cilindro_cheio_2,
            lote=self.lote_valido,
            pressao_bar=200,
            usuario=self.gerente,
            client_uuid=uuid.uuid4()
        )
        self.cilindro_cheio_2.refresh_from_db()

        # 3. Cilindro em Posse do Cliente (Para Recolha)
        self.cilindro_no_cliente = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-POSSE-003',
            numero_serie_ogiva='SERIE-003',
            fabricante='MAT',
            ano_fabricacao=2020,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.00'),
            data_ultimo_reteste=date(2020, 1, 1),
            data_proximo_reteste=date(2025, 1, 1), # Reteste Vencido!
            status='EM_POSSE_CLIENTE',
            cliente_posse_atual=self.cliente
        )

        # 4. Cilindro com Reteste Vencido no Pátio (Não pode ser entregue)
        self.cilindro_reteste_vencido = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-VENCIDO-004',
            numero_serie_ogiva='SERIE-004',
            fabricante='MAT',
            ano_fabricacao=2015,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.00'),
            data_ultimo_reteste=date(2018, 1, 1),
            data_proximo_reteste=date(2023, 1, 1), # Vencido!
            status='VAZIO_TRIAGEM'
        )

        # 5. Cilindro com Bloqueio Sanitário
        self.cilindro_bloqueado = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-BLOQUEADO-005',
            numero_serie_ogiva='SERIE-005',
            fabricante='MAT',
            ano_fabricacao=2022,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.00'),
            data_ultimo_reteste=date(2022, 1, 1),
            data_proximo_reteste=date(2027, 1, 1),
            status='VAZIO_TRIAGEM',
            bloqueio_sanitario=True,
            motivo_bloqueio_sanitario='Contaminação por particulado particulado'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    # ==========================================================================
    # 1. TESTE DE SINCRONIZAÇÃO EM LOTE OFFLINE E IDEMPOTÊNCIA ESTRITA (DoD)
    # ==========================================================================

    def test_sincronizacao_offline_lote_idempotencia_estrita(self):
        """
        Critério de Aceite Principal (DoD):
        Teste automatizado de sincronização offline enviando um lote de movimentações
        duas vezes seguidas com os mesmos client_uuids sem gerar duplicatas no banco.
        """
        self.client.force_authenticate(user=self.motorista)

        uuid_entrega_1 = str(uuid.uuid4())
        uuid_entrega_2 = str(uuid.uuid4())
        uuid_recolha_3 = str(uuid.uuid4())

        lote_movimentacoes = [
            {
                'client_uuid': uuid_entrega_1,
                'tipo': 'ENTREGA_CLIENTE',
                'codigo_qr': self.cilindro_cheio_1.codigo_qr,
                'cliente_id': self.cliente.id,
                'entrega_id': self.entrega.id,
                'recebedor_nome': 'Enfermeira Clara',
                'recebedor_documento': '111.222.333-44',
                'assinatura_base64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
                'latitude': -23.5505,
                'longitude': -46.6333
            },
            {
                'client_uuid': uuid_entrega_2,
                'tipo': 'ENTREGA_CLIENTE',
                'codigo_qr': self.cilindro_cheio_2.codigo_qr,
                'cliente_id': self.cliente.id,
                'entrega_id': self.entrega.id
            },
            {
                'client_uuid': uuid_recolha_3,
                'tipo': 'RECOLHA_CLIENTE',
                'codigo_qr': self.cilindro_no_cliente.codigo_qr,
                'cliente_id': self.cliente.id,
                'entrega_id': self.entrega.id,
                'observacao': 'Recolhido casco vazio da enfermaria'
            }
        ]

        # 1º ENVIO DO LOTE
        resp1 = self.client.post('/api/movimentacoes/sync-offline/', {'itens': lote_movimentacoes}, format='json')
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        data1 = resp1.json()
        self.assertEqual(data1['total'], 3)
        self.assertEqual(data1['processados'], 3)
        self.assertEqual(data1['ja_existentes'], 0)
        self.assertEqual(data1['erros'], 0)

        # Verifica persistência no Ledger
        movs_count = MovimentacaoCilindro.objects.filter(entrega=self.entrega).count()
        self.assertEqual(movs_count, 3)

        # 2º ENVIO DO MESMO LOTE COM OS MESMOS CLIENT_UUIDs (Reenvio offline após queda de conexão)
        resp2 = self.client.post('/api/movimentacoes/sync-offline/', {'itens': lote_movimentacoes}, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        data2 = resp2.json()
        self.assertEqual(data2['total'], 3)
        self.assertEqual(data2['processados'], 0)
        self.assertEqual(data2['ja_existentes'], 3) # Todos identificados como já processados
        self.assertEqual(data2['erros'], 0)

        for detalhe in data2['detalhes']:
            self.assertEqual(detalhe['status'], 'ja_processado')
            self.assertIn('idempotência', detalhe['mensagem'].lower())

        # CRUCIAL: Contagem de linhas no banco NÃO duplicou!
        movs_count_after = MovimentacaoCilindro.objects.filter(entrega=self.entrega).count()
        self.assertEqual(movs_count_after, 3)

    # ==========================================================================
    # 2. REGRAS DE RUA: CASCO DIVERGENTE E RETESTE VENCIDO NA RECOLHA VS BLOQUEIO NA ENTREGA
    # ==========================================================================

    def test_recolha_casco_divergente_e_reteste_vencido_permitida(self):
        """
        Recolha de casco divergente e recolha de cilindro com reteste vencido
        devem funcionar normalmente na rua (retorno à base).
        """
        self.client.force_authenticate(user=self.motorista)

        # Cilindro com reteste vencido que estava no cliente
        uuid_recolha_vencido = str(uuid.uuid4())
        item_vencido = [{
            'client_uuid': uuid_recolha_vencido,
            'tipo': 'RECOLHA_CLIENTE',
            'codigo_qr': self.cilindro_no_cliente.codigo_qr,
            'cliente_id': self.cliente.id,
            'entrega_id': self.entrega.id
        }]

        resp = self.client.post('/api/movimentacoes/sync-offline/', {'itens': item_vencido}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()['processados'], 1)

        self.cilindro_no_cliente.refresh_from_db()
        self.assertEqual(self.cilindro_no_cliente.status, 'VAZIO_TRIAGEM')
        self.assertIsNone(self.cilindro_no_cliente.cliente_posse_atual)

    def test_entrega_reteste_vencido_e_bloqueio_sanitario_bloqueadas(self):
        """
        Entrega de cilindro vencido ou com bloqueio_sanitario deve ser estritamente bloqueada.
        """
        self.client.force_authenticate(user=self.motorista)

        # Tentativa 1: Entrega de cilindro com reteste vencido
        resp1 = self.client.post('/api/movimentacoes/sync-offline/', {'itens': [{
            'client_uuid': str(uuid.uuid4()),
            'tipo': 'ENTREGA_CLIENTE',
            'codigo_qr': self.cilindro_reteste_vencido.codigo_qr,
            'cliente_id': self.cliente.id,
            'entrega_id': self.entrega.id
        }]}, format='json')
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        detalhe1 = resp1.json()['detalhes'][0]
        self.assertEqual(detalhe1['status'], 'erro')
        self.assertIn('teste hidrostático', detalhe1['mensagem'])

        # Tentativa 2: Entrega de cilindro com bloqueio sanitário
        resp2 = self.client.post('/api/movimentacoes/sync-offline/', {'itens': [{
            'client_uuid': str(uuid.uuid4()),
            'tipo': 'ENTREGA_CLIENTE',
            'codigo_qr': self.cilindro_bloqueado.codigo_qr,
            'cliente_id': self.cliente.id,
            'entrega_id': self.entrega.id
        }]}, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        detalhe2 = resp2.json()['detalhes'][0]
        self.assertEqual(detalhe2['status'], 'erro')
        self.assertIn('Bloqueio Sanitário', detalhe2['mensagem'])

    # ==========================================================================
    # 3. COMPROVANTE ELETRÔNICO, ASSINATURA, HASH SHA-256 E PROTEÇÃO (DoD)
    # ==========================================================================

    def test_comprovante_entrega_assinatura_imutabilidade_e_protecao(self):
        """
        Assinatura do recebedor vinculada de forma imutável à entrega e protegida contra acesso não autenticado.
        """
        self.client.force_authenticate(user=self.motorista)

        # 1. Cria comprovante via endpoint de entrega
        raw_b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        resp = self.client.post(f'/logistica/api/entregas/{self.entrega.id}/comprovante-assinatura/', {
            'recebedor_nome': 'Dr. Marcos Santos',
            'recebedor_documento': '123.456.789-00',
            'assinatura_base64': raw_b64,
            'latitude': -23.5505,
            'longitude': -46.6333
        }, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        comp_id = resp.json()['id']
        hash_sha256 = resp.json()['hash_integridade_sha256']
        self.assertTrue(len(hash_sha256) == 64) # SHA-256 válido

        comprovante = ComprovanteEntrega.objects.get(id=comp_id)

        # 2. Testa IMUTABILIDADE do comprovante
        with self.assertRaises(ValidationError):
            comprovante.recebedor_nome = 'Nome Alterado Fraudulento'
            comprovante.save()

        with self.assertRaises(ValidationError):
            comprovante.delete()

        # 3. Testa PROTEÇÃO contra acesso não autenticado
        self.client.logout()
        resp_public = self.client.get(f'/logistica/api/comprovantes/{comprovante.id}/assinatura/')
        self.assertIn(resp_public.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # 4. Testa PROTEÇÃO contra usuário de outro tenant
        self.client.force_authenticate(user=self.user_outro)
        resp_outro = self.client.get(f'/logistica/api/comprovantes/{comprovante.id}/assinatura/')
        self.assertEqual(resp_outro.status_code, status.HTTP_404_NOT_FOUND)

        # 5. Acesso com usuário autorizado do mesmo tenant
        self.client.force_authenticate(user=self.gerente)
        resp_auth = self.client.get(f'/logistica/api/comprovantes/{comprovante.id}/assinatura/')
        self.assertEqual(resp_auth.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_auth['Content-Type'], 'image/png')

    # ==========================================================================
    # 4. VALIDAÇÃO DE CAPACIDADE DE CARGA DO VEÍCULO E SOBRECARGA (DoD)
    # ==========================================================================

    def test_bloqueio_sobrecarga_capacidade_veiculo(self):
        """
        Cálculo de peso da rota bloqueando sobrecarga acima da capacidade do veículo.
        """
        # Veículo com capacidade de 100 kg
        veiculo_leve = Veiculo.objects.create(
            tenant=self.tenant,
            placa='LEVE-100',
            modelo='Fiorino',
            marca='Fiat',
            ano=2023,
            capacidade_carga=Decimal('100.00'), # 100 kg máx
            status='Ativo'
        )
        entrega_pequena = Entrega.objects.create(
            tenant=self.tenant,
            veiculo=veiculo_leve,
            rota=self.rota,
            motorista=self.motorista,
            status='Agendada'
        )

        # Tentativa de carregar 2 cilindros T-50 (55 kg tara + 10 kg gás = 65 kg cada, total 130 kg > 100 kg)
        cilindros_excesso = [self.cilindro_cheio_1, self.cilindro_cheio_2]

        with self.assertRaises(ValidationError) as ctx:
            validar_capacidade_veiculo_entrega(entrega_pequena, novos_cilindros=cilindros_excesso)

        self.assertIn("Capacidade de carga do veículo excedida", str(ctx.exception))
        self.assertIn("130.00 kg", str(ctx.exception))
        self.assertIn("100.00 kg", str(ctx.exception))

        # Teste via endpoint REST de validação de capacidade
        self.client.force_authenticate(user=self.gerente)
        resp = self.client.post(f'/logistica/api/entregas/{entrega_pequena.id}/validar-capacidade/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()['valido'])

    # ==========================================================================
    # 5. GERAÇÃO DE DOCUMENTAÇÃO DE TRANSPORTE ANTT (PDF)
    # ==========================================================================

    def test_geracao_documentos_antt_pdf(self):
        """
        Geração em PDF do Romaneio de Carga, Ficha de Emergência e Envelope de Transporte (ANTT).
        """
        # Associa um cilindro à entrega
        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=self.cilindro_cheio_1,
            tipo='SAIDA_ROTA',
            status_anterior='CHEIO_DISPONIVEL',
            status_novo='RESERVADO_ROTA',
            entrega=self.entrega,
            cliente=self.cliente,
            ocorrido_em=timezone.now(),
            registrado_por=self.motorista,
            envase_cilindro=self.cilindro_cheio_1.envase_atual
        )

        # 1. Romaneio de Carga ANTT PDF
        pdf_romaneio = gerar_romaneio_carga_antt_pdf(self.entrega)
        self.assertTrue(pdf_romaneio.startswith(b'%PDF'))
        self.assertGreater(len(pdf_romaneio), 1000)

        # 2. Ficha de Emergência ABNT NBR 7503 PDF
        pdf_ficha = gerar_ficha_emergencia_antt_pdf(self.entrega)
        self.assertTrue(pdf_ficha.startswith(b'%PDF'))
        self.assertGreater(len(pdf_ficha), 1000)

        # 3. Envelope para Transporte ANTT PDF
        pdf_envelope = gerar_envelope_transporte_antt_pdf(self.entrega)
        self.assertTrue(pdf_envelope.startswith(b'%PDF'))
        self.assertGreater(len(pdf_envelope), 1000)


        # 4. Teste via endpoints da API
        self.client.force_authenticate(user=self.motorista)
        
        resp_r = self.client.get(f'/logistica/api/entregas/{self.entrega.id}/romaneio-antt-pdf/')
        self.assertEqual(resp_r.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_r['Content-Type'], 'application/pdf')

        resp_f = self.client.get(f'/logistica/api/entregas/{self.entrega.id}/ficha-emergencia-pdf/')
        self.assertEqual(resp_f.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_f['Content-Type'], 'application/pdf')

        resp_e = self.client.get(f'/logistica/api/entregas/{self.entrega.id}/envelope-transporte-pdf/')
        self.assertEqual(resp_e.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_e['Content-Type'], 'application/pdf')

    # ==========================================================================
    # 6. WEBHOOKS COM ASSINATURA HMAC-SHA256 E EXPORTAÇÃO CANÔNICA ERP
    # ==========================================================================

    @patch('requests.post')
    def test_webhooks_com_assinatura_hmac_e_conclusao_romaneio(self, mock_post):
        """
        Disparo de Webhooks assinados via HMAC-SHA256 por tenant ao concluir romaneio.
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"received": true}'
        mock_post.return_value = mock_resp

        secret_key = 'chave-secreta-erp-acme'
        endpoint = WebhookEndpoint.objects.create(
            tenant=self.tenant,
            url='https://erp.hospital.com.br/api/webhooks/',
            secret=secret_key,
            eventos=['romaneio.concluido', 'fatura.fechada'],
            descricao='ERP Central Protheus'
        )

        self.client.force_authenticate(user=self.motorista)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(f'/logistica/api/entregas/{self.entrega.id}/concluir-romaneio/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.entrega.refresh_from_db()
        self.assertEqual(self.entrega.status, 'Concluída')

        # Verifica chamada HTTP do webhook
        self.assertTrue(mock_post.called)
        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_args[0], 'https://erp.hospital.com.br/api/webhooks/')

        # Valida Assinatura HMAC-SHA256 no Header
        headers = call_kwargs['headers']
        self.assertIn('X-Signature-SHA256', headers)
        self.assertEqual(headers['X-Event'], 'romaneio.concluido')
        self.assertEqual(headers['X-Tenant-ID'], str(self.tenant.id))

        payload_sent = call_kwargs['data']
        expected_sig = hmac.new(secret_key.encode('utf-8'), payload_sent.encode('utf-8'), hashlib.sha256).hexdigest()
        self.assertEqual(headers['X-Signature-SHA256'], expected_sig)

        # Valida registro de log auditável
        log = WebhookDeliveryLog.objects.filter(endpoint=endpoint, evento='romaneio.concluido').first()
        self.assertIsNotNone(log)
        self.assertTrue(log.sucesso)
        self.assertEqual(log.status_code, 200)

    def test_endpoints_exportacao_canonica_erp(self):
        """
        Endpoints REST paginados de exportação canônica para faturas e romaneios.
        """
        self.client.force_authenticate(user=self.gerente)

        # 1. Exportação de Faturas ERP
        resp_fat = self.client.get('/api/erp/faturas/')
        self.assertEqual(resp_fat.status_code, status.HTTP_200_OK)
        self.assertIn('faturas', resp_fat.json())

        # 2. Exportação de Entregas ERP
        resp_ent = self.client.get('/api/erp/entregas/')
        self.assertEqual(resp_ent.status_code, status.HTTP_200_OK)
        self.assertIn('entregas', resp_ent.json())
        self.assertGreaterEqual(resp_ent.json()['total'], 1)
