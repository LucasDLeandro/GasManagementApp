from typing import Any

from core.modulos import MODULOS_REGISTRO, is_modulo_ativo


class AssinaturaInativaError(PermissionError):
    """
    Disparada quando uma operação de escrita (POST/PUT/PATCH/DELETE) é tentada
    sobre um Tenant cuja assinatura está suspensa ou cancelada.
    """


class ModuloInativoError(PermissionError):
    """
    Disparada quando uma operação de serviço, API ou tarefa assíncrona
    tenta acessar recursos de um módulo que não está ativo no plano do Tenant.
    """


def assert_tenant_writable(tenant: Any) -> None:
    """
    Valida em camada de serviço se o Tenant está ativo e com assinatura apta a escritas.
    Bloqueia estritamente tenants com status 'SUSPENSO' ou 'CANCELADO'.
    """
    if tenant is None:
        raise ValueError("Tenant obrigatório para validação de escrita.")

    if not getattr(tenant, 'ativo', True):
        nome = getattr(tenant, 'nome', str(tenant))
        raise AssinaturaInativaError(f"Operação de escrita bloqueada: a empresa '{nome}' está inativa.")

    status = getattr(tenant, 'status_assinatura', 'TRIAL')
    if status in ('SUSPENSO', 'CANCELADO'):
        nome = getattr(tenant, 'nome', str(tenant))
        motivo = getattr(tenant, 'motivo_suspensao', '')
        detalhe_motivo = f" Motivo: {motivo}" if motivo else ""
        raise AssinaturaInativaError(
            f"Operação de escrita bloqueada: a assinatura da empresa '{nome}' está {status}.{detalhe_motivo}"
        )


def assert_modulo(tenant: Any, codigo_modulo: str) -> None:
    """
    Valida em camada de serviço se o módulo requisitado está ativo no plano do Tenant.
    Lança ModuloInativoError caso o módulo esteja desligado.
    """
    if tenant is None:
        raise ValueError("Tenant obrigatório para validação de módulo.")

    if not is_modulo_ativo(tenant, codigo_modulo):
        rotulo = MODULOS_REGISTRO.get(codigo_modulo, {}).get('rotulo', codigo_modulo)
        nome = getattr(tenant, 'nome', str(tenant))
        raise ModuloInativoError(
            f"O módulo '{rotulo}' ({codigo_modulo}) não está ativo no plano da empresa '{nome}'."
        )
