from decimal import Decimal
from typing import Any

from django.db import transaction

from core.money import quantize


class CotaExcedida(ValueError):
    """
    Disparada quando uma operação tenta criar ou importar recursos além do limite
    contratado na assinatura do Tenant (Sprint 7B - Correção F-10).
    """


def checar_cota(tenant: Any, recurso: str, incremento: int = 1) -> dict[str, Any]:
    """
    Verifica e reserva cotas contratuais do Tenant utilizando select_for_update
    para evitar condições de corrida em concorrência.
    Alerta a partir de 90% de uso e bloqueia estritamente em 100%.

    Recursos suportados: 'cilindros', 'usuarios'.
    """
    if tenant is None:
        raise ValueError("Tenant obrigatório para verificação de cota.")

    from core.models import Tenant

    with transaction.atomic():
        tenant_lock = Tenant.objects.select_for_update().get(id=tenant.id)

        if recurso == 'cilindros':
            from produtos.models import Cilindro
            uso_atual = Cilindro.unscoped.filter(tenant=tenant_lock).exclude(status__in=['BAIXADO', 'EXTRAVIADO']).exclude(propriedade='CLIENTE').count()
            limite = tenant_lock.limite_cilindros
        elif recurso == 'usuarios':
            from core.models import Membership
            uso_atual = Membership.objects.filter(tenant=tenant_lock, ativo=True).count()
            limite = tenant_lock.limite_usuarios
        else:
            raise ValueError(f"Recurso inválido para verificação de cota: '{recurso}'. Use 'cilindros' ou 'usuarios'.")

        novo_total = uso_atual + incremento

        if limite > 0 and novo_total > limite:
            raise CotaExcedida(
                f"Cota de {recurso} excedida para a empresa '{tenant_lock.nome}'. "
                f"Limite contratado: {limite}, Uso atual: {uso_atual}, Tentativa: {novo_total}."
            )

        if limite > 0:
            pct_raw = (Decimal(str(novo_total)) / Decimal(str(limite))) * Decimal(100)
            percentual = quantize(pct_raw, casas=2)
            alerta_90 = percentual >= Decimal('90.00')
        else:
            percentual = Decimal('0.00')
            alerta_90 = False

        return {
            'tenant_id': str(tenant_lock.id),
            'recurso': recurso,
            'uso_atual': uso_atual,
            'novo_total': novo_total,
            'limite': limite,
            'percentual': percentual,
            'alerta_90': alerta_90,
        }
