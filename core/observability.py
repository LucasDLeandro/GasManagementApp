import json
import logging
from datetime import datetime

from django.utils import timezone

from core.context import get_current_request_id, get_current_tenant, get_current_user


class JSONLogFormatter(logging.Formatter):
    """
    Formatador de logs estruturados em JSON para observabilidade centralizada (Sprint 7A).
    Injeta automaticamente request_id, tenant_id e user do contexto de execução ativo.
    """

    def format(self, record):
        tenant = get_current_tenant()
        user = get_current_user()
        request_id = get_current_request_id()

        log_data = {
            'timestamp': datetime.fromtimestamp(
                record.created,
                tz=timezone.get_current_timezone()
            ).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'request_id': request_id,
            'tenant_id': str(tenant.id) if tenant else None,
            'user': str(user) if user else None,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def track_telemetry_event(event_name: str, properties: dict | None = None) -> dict:
    """
    Ponto de extensão para Sentry, OpenTelemetry (OTel) e APM (Sprint 7A).
    Permite enviar métricas de telemetria e breadcrumbs com escopo estrito de Tenant.
    """
    tenant = get_current_tenant()
    request_id = get_current_request_id()

    payload = {
        'event': event_name,
        'tenant_id': str(tenant.id) if tenant else None,
        'request_id': request_id,
        'properties': properties or {},
    }

    try:
        import sentry_sdk
        with sentry_sdk.configure_scope() as scope:
            if tenant:
                scope.set_tag("tenant_id", str(tenant.id))
            if request_id:
                scope.set_tag("request_id", request_id)
            sentry_sdk.add_breadcrumb(
                category='telemetry',
                message=event_name,
                data=payload
            )
    except (ImportError, AttributeError):
        pass

    return payload
