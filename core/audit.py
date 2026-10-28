import logging

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

from core.context import (
    get_current_ip,
    get_current_request_id,
    get_current_tenant,
    get_current_user,
)

SENSITIVE_AUDIT_KEYWORDS = {
    'senha',
    'password',
    'token',
    'secret',
    'certificado_senha',
    'chave_privada',
    'field_encryption_key',
}


class AuditedModelMixin(models.Model):
    """
    Mixin para rastreabilidade e gravação automática de trilha de auditoria em LogAuditoriaDados.
    Grava snapshot de criação e diff de alteração/exclusão com mascaramento de dados sensíveis.
    """

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initial_state = self._snapshot_fields()

    def _snapshot_fields(self):
        if not self.pk:
            return {}
        state = {}
        for f in self._meta.fields:
            state[f.name] = f.value_from_object(self)
        return state

    def _is_sensitive(self, field_name: str) -> bool:
        sensitive_fields = getattr(self, 'SENSITIVE_AUDIT_FIELDS', set())
        if field_name in sensitive_fields:
            return True
        field_lower = field_name.lower()
        return any(kw in field_lower for kw in SENSITIVE_AUDIT_KEYWORDS)

    def _mask_value(self, field_name: str, value):
        if value is None:
            return None
        if self._is_sensitive(field_name):
            return '********'
        return str(value)

    def save(self, *args, **kwargs):
        is_creation = self._state.adding or not self.pk
        old_state = getattr(self, '_initial_state', {})
        super().save(*args, **kwargs)
        new_state = self._snapshot_fields()

        diff = {}
        if is_creation:
            acao = 'CRIACAO'
            for k, v in new_state.items():
                diff[k] = {'antigo': None, 'novo': self._mask_value(k, v)}
        else:
            acao = 'ALTERACAO'
            for k, new_val in new_state.items():
                old_val = old_state.get(k)
                if old_val != new_val:
                    diff[k] = {
                        'antigo': self._mask_value(k, old_val),
                        'novo': self._mask_value(k, new_val),
                    }

        if diff or is_creation:
            self._record_audit_event(acao=acao, diff=diff)

        self._initial_state = new_state

    def delete(self, *args, **kwargs):
        diff = {
            k: {'antigo': self._mask_value(k, v), 'novo': None}
            for k, v in self._snapshot_fields().items()
        }
        self._record_audit_event(acao='EXCLUSAO', diff=diff)
        super().delete(*args, **kwargs)

    def _record_audit_event(self, acao: str, diff: dict):
        tenant = getattr(self, 'tenant', None) or get_current_tenant()
        if not tenant:
            return
        try:
            from core.models import LogAuditoriaDados
            content_type = ContentType.objects.get_for_model(self.__class__)
            LogAuditoriaDados.unscoped.create(
                tenant=tenant,
                usuario=get_current_user(),
                content_type=content_type,
                object_id=str(self.pk or ''),
                acao=acao,
                diff_json=diff,
                ip=get_current_ip(),
                request_id=get_current_request_id(),
                timestamp=timezone.now()
            )
        except Exception as err:
            logger.warning("Falha ao registrar log de auditoria defensiva: %s", err, exc_info=True)
