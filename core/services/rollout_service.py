"""
Serviço de Rollout Controlado e Gestão de Tenants Piloto (Sprint 13 - Tarefa 1).

Implementa:
- Habilitação granular de módulos e feature flags para Tenants Piloto (Canary / Beta);
- Verificação de elegibilidade para rollout controlado;
- Protocolo de Rollback atômico por módulo com trilha de auditoria e revogação de acessos;
- Segurança fail-closed para tenants não participantes do piloto.
"""
from typing import Any, Dict, List, Optional
from django.db import transaction
from django.utils import timezone
from core.guards import assert_tenant_writable
from core.models import Tenant, LogAuditoriaDados
from core.tenancy import tenant_context


def habilitar_feature_piloto(tenant: Tenant, feature_key: str, habilitado: bool = True) -> Dict[str, Any]:
    """
    Habilita ou desabilita uma feature flag específica para um tenant piloto.
    """
    assert_tenant_writable(tenant)

    flags = dict(tenant.flags_piloto or {})
    flags[feature_key] = bool(habilitado)
    tenant.flags_piloto = flags
    tenant.save(update_fields=['flags_piloto'])

    return {
        'tenant_id': str(tenant.id),
        'is_piloto': tenant.is_piloto,
        'feature_key': feature_key,
        'habilitado': habilitado,
        'flags_ativas': tenant.flags_piloto
    }


def is_feature_piloto_ativa(tenant: Optional[Tenant], feature_key: str) -> bool:
    """
    Retorna True se a feature estiver habilitada para o tenant.
    Se o tenant não for piloto, retorna False por padrão (fail-closed).
    """
    if not tenant or not tenant.is_piloto:
        return False

    flags = tenant.flags_piloto or {}
    return bool(flags.get(feature_key, False))


def marcar_tenant_como_piloto(tenant: Tenant, piloto: bool = True) -> Tenant:
    """
    Define se o tenant faz parte do grupo de distribuição antecipada (piloto).
    """
    assert_tenant_writable(tenant)
    tenant.is_piloto = piloto
    tenant.save(update_fields=['is_piloto'])
    return tenant


def listar_features_piloto(tenant: Optional[Tenant]) -> Dict[str, bool]:
    """
    Retorna o dicionário de feature flags ativas para o tenant piloto.
    """
    if not tenant:
        return {}
    return dict(tenant.flags_piloto or {})


def executar_rollback_modulo(
    tenant: Tenant,
    modulo_codigo: Optional[str] = None,
    motivo: str = "",
    executado_por=None,
    solicitante: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Executa o plano de rollback seguro de um módulo:
    1. Desabilita a flag do módulo no Tenant de forma atômica;
    2. Registra o evento de rollback em LogAuditoriaDados (imutável);
    3. Retorna o status consolidado de rollback.
    """
    assert_tenant_writable(tenant)

    mod = modulo_codigo or kwargs.get('modulo')
    if not mod:
        raise ValueError("O código do módulo para rollback deve ser informado.")

    campo_modulo = f"modulo_{mod.lower()}_ativo"
    if not hasattr(tenant, campo_modulo):
        raise ValueError(f"Módulo '{mod}' inválido para rollback.")


    with transaction.atomic():
        # Desativa o módulo
        setattr(tenant, campo_modulo, False)
        tenant.save(update_fields=[campo_modulo])

        # Grava auditoria estruturada
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Tenant)
        log = LogAuditoriaDados.objects.create(
            tenant=tenant,
            usuario=executado_por,
            content_type=ct,
            object_id=str(tenant.id),
            acao='ALTERACAO',
            diff_json={
                'evento': 'ROLLBACK_MODULO',
                'modulo': mod,
                'motivo': motivo,
                'solicitante': solicitante,
                'status_anterior': True,
                'status_novo': False,
                'timestamp': timezone.now().isoformat()
            }
        )


    return {
        'sucesso': True,
        'tenant_id': str(tenant.id),
        'modulo': mod,
        'flags_desativadas': [mod, campo_modulo],
        'status_modulo': 'ROLLBACK_CONCLUIDO',
        'motivo': motivo,
        'log_auditoria_id': log.id,
        'executado_em': timezone.now().isoformat()
    }


