from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.context import get_current_ip, get_current_request_id


class TransicaoInvalidaError(ValueError):
    """Disparada quando uma transição de status de assinatura viola a máquina de estados."""


def transicionar(tenant: Any, novo_status: str, executor: Any = None, motivo: str = '') -> Any:
    """
    Máquina de estados da assinatura SaaS (Sprint 7B - v2.0).

    Transições permitidas:
    - TRIAL -> ATIVO | SUSPENSO | CANCELADO
    - ATIVO -> SUSPENSO | CANCELADO
    - SUSPENSO -> ATIVO | CANCELADO
    - CANCELADO -> ATIVO (apenas por superusuário e com motivo obrigatório)

    Toda transição é atômica com select_for_update e grava em LogAuditoriaSaaS.
    """
    if tenant is None:
        raise ValueError("Tenant obrigatório para transição de status de assinatura.")

    from core.models import LogAuditoriaSaaS, Tenant

    transicoes_permitidas: dict[str, set[str]] = {
        'TRIAL': {'ATIVO', 'SUSPENSO', 'CANCELADO'},
        'ATIVO': {'SUSPENSO', 'CANCELADO'},
        'SUSPENSO': {'ATIVO', 'CANCELADO'},
        'CANCELADO': {'ATIVO'},
    }

    with transaction.atomic():
        tenant_lock = Tenant.objects.select_for_update().get(id=tenant.id)
        status_anterior = tenant_lock.status_assinatura

        if status_anterior == novo_status:
            return tenant_lock

        permitidos = transicoes_permitidas.get(status_anterior, set())
        if novo_status not in permitidos:
            raise TransicaoInvalidaError(
                f"Transição de assinatura inválida de '{status_anterior}' para '{novo_status}'. "
                f"Status permitidos a partir de '{status_anterior}': {sorted(permitidos)}."
            )

        # Regra de superusuário e motivo para reativação pós-cancelamento
        if status_anterior == 'CANCELADO' and novo_status == 'ATIVO':
            is_super = bool(executor and getattr(executor, 'is_superuser', False))
            if not is_super:
                raise TransicaoInvalidaError(
                    "Reativação de empresa CANCELADA é restrita exclusivamente a Superusuários do SaaS."
                )
            if not motivo or not motivo.strip():
                raise TransicaoInvalidaError(
                    "Reativação de empresa CANCELADA exige motivo formal obrigatório."
                )

        hoje = timezone.localdate()

        if novo_status == 'CANCELADO':
            tenant_lock.data_cancelamento = hoje
            tenant_lock.data_limite_exportacao = hoje + timedelta(days=90)
            tenant_lock.motivo_suspensao = motivo
        elif novo_status == 'SUSPENSO':
            tenant_lock.motivo_suspensao = motivo
        elif novo_status == 'ATIVO':
            tenant_lock.motivo_suspensao = ''
            tenant_lock.data_cancelamento = None

        tenant_lock.status_assinatura = novo_status
        tenant_lock.save()

        # Grava auditoria obrigatória do SaaS
        user_audit = executor if (executor and getattr(executor, 'is_authenticated', False)) else None
        LogAuditoriaSaaS.objects.create(
            tenant=tenant_lock,
            usuario=user_audit,
            acao='TRANSICAO_STATUS',
            modulo='assinatura',
            detalhes_json={
                'status_anterior': status_anterior,
                'status_novo': novo_status,
                'motivo': motivo,
                'executor': getattr(executor, 'username', 'sistema') if executor else 'sistema',
            },
            ip=get_current_ip(),
            request_id=get_current_request_id(),
            timestamp=timezone.now(),
        )

        return tenant_lock
