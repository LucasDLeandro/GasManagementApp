import sys
import time
import hmac
import hashlib
import json
import requests
import logging
from django.utils import timezone
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder
from core.models import WebhookEndpoint, WebhookDeliveryLog, validar_url_webhook_segura

logger = logging.getLogger(__name__)


def processar_envio_webhook_log(log_id):
    """
    Executa o envio HTTP de um item do Transactional Outbox (WebhookDeliveryLog).
    Atualiza status para 'SUCESSO' ou 'FALHA', mede latência em ms,
    aplica trava anti-SSRF e registra log estruturado com contagem de tentativas.
    """
    try:
        log = WebhookDeliveryLog.unscoped.select_related('endpoint', 'tenant').filter(id=log_id).first()
        if not log or not log.endpoint:
            return None

        endpoint = log.endpoint

        # 1. Trava anti-SSRF em tempo de execução
        try:
            validar_url_webhook_segura(endpoint.url)
        except Exception as exc_ssrf:
            log.status_code = None
            log.sucesso = False
            log.status = 'FALHA'
            log.resposta_body = f"Bloqueado pela trava de segurança anti-SSRF: {str(exc_ssrf)}"
            log.latencia_ms = 0.0
            log.tentativas += 1
            log.enviado_em = timezone.now()
            log.save(update_fields=['status_code', 'sucesso', 'status', 'resposta_body', 'latencia_ms', 'tentativas', 'enviado_em'])
            logger.warning(f"[Webhook Anti-SSRF] URL {endpoint.url} bloqueada: {exc_ssrf}")
            return log

        payload_json = json.dumps(log.payload, cls=DjangoJSONEncoder, sort_keys=True)
        timestamp_envio = timezone.now().isoformat()

        # Calcula assinatura HMAC-SHA256
        secret_bytes = endpoint.secret.encode('utf-8')
        signature = hmac.new(secret_bytes, payload_json.encode('utf-8'), hashlib.sha256).hexdigest()

        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Baros-Webhooks/1.0',
            'X-Tenant-ID': str(log.tenant_id),
            'X-Event': log.evento,
            'X-Signature-SHA256': signature,
            'X-Timestamp': timestamp_envio
        }

        status_code = None
        sucesso = False
        resposta_body = ""
        latencia_ms = None

        t0 = time.perf_counter()
        try:
            resp = requests.post(
                endpoint.url,
                data=payload_json,
                headers=headers,
                timeout=5.0
            )
            latencia_ms = round((time.perf_counter() - t0) * 1000, 2)
            status_code = resp.status_code
            resposta_body = resp.text[:2000] if resp.text else ""
            sucesso = 200 <= status_code < 300
        except requests.exceptions.RequestException as exc:
            latencia_ms = round((time.perf_counter() - t0) * 1000, 2)
            resposta_body = f"Erro de conexão/timeout: {str(exc)[:500]}"
            logger.warning(
                f"[Webhook Outbox] Falha no envio do webhook #{log.id} ({log.evento}) "
                f"para {endpoint.url}: {exc} (Tentativa #{log.tentativas + 1})"
            )

        log.status_code = status_code
        log.sucesso = sucesso
        log.status = 'SUCESSO' if sucesso else 'FALHA'
        log.resposta_body = resposta_body
        log.latencia_ms = latencia_ms
        log.tentativas += 1
        log.enviado_em = timezone.now()
        log.save(update_fields=['status_code', 'sucesso', 'status', 'resposta_body', 'latencia_ms', 'tentativas', 'enviado_em'])

        return log
    except Exception as e:
        logger.error(f"[Webhook Outbox] Erro inesperado ao processar log #{log_id}: {e}", exc_info=True)
        return None


def disparar_webhooks_tenant(tenant, evento, payload, endpoint_especifico=None):
    """
    Padrão Transactional Outbox (D7 - Fase 0):
    1. Grava WebhookDeliveryLog na transação atômica corrente com status='PENDENTE'.
    2. Agenda o envio HTTP assíncrono via transaction.on_commit (ou executa imediatamente no test runner).
    3. Retorna os registros outbox criados.
    """
    if not tenant:
        return []

    if endpoint_especifico:
        endpoints = [endpoint_especifico] if endpoint_especifico.ativo else []
    else:
        endpoints = list(WebhookEndpoint.unscoped.filter(tenant=tenant, ativo=True))

    logs_gerados = []

    for endpoint in endpoints:
        # Verifica se o endpoint está inscrito no evento ('*' ou nome exato, ou evento de teste)
        eventos_inscritos = endpoint.eventos or []
        if evento != 'ping.teste' and '*' not in eventos_inscritos and evento not in eventos_inscritos:
            continue

        # 1. Gravação com status PENDENTE no banco na transação atômica (Outbox)
        log = WebhookDeliveryLog.objects.create(
            tenant=tenant,
            endpoint=endpoint,
            evento=evento,
            payload=payload,
            status='PENDENTE',
            status_code=None,
            sucesso=False,
            resposta_body="",
            latencia_ms=None,
            tentativas=0,
            enviado_em=timezone.now()
        )
        # 2. Agendamento para processamento pós-commit
        if transaction.get_connection().in_atomic_block and 'test' not in sys.argv:
            transaction.on_commit(lambda target_id=log.id: processar_envio_webhook_log(target_id))
        else:
            resultado = processar_envio_webhook_log(log.id)
            if resultado:
                log = resultado

        logs_gerados.append(log)

    return logs_gerados

