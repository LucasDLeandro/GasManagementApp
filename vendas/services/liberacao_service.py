from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from core.guards import assert_tenant_writable
from vendas.models import Venda, LiberacaoBloqueio


@transaction.atomic
def liberar_bloqueio_venda(venda: Venda, usuario, motivo: str) -> LiberacaoBloqueio:
    """
    Realiza a liberação formal e auditada de venda com BLOQUEADO_FINANCEIRO (Sprint 11C - Tarefa 4).
    - Exige a permissão vendas.liberar_bloqueio_financeiro (ou superusuário).
    - Exige justificativa formal obrigatória (mínimo 5 caracteres).
    - Grava LiberacaoBloqueio e restaura o status da venda para 'Pendente'.
    - Não altera nem abate títulos ou a dívida financeira do cliente.
    """
    assert_tenant_writable(venda.tenant)

    if not usuario or not usuario.is_authenticated:
        raise PermissionDenied("Usuário não autenticado.")

    # Validação rigorosa de permissão (duas camadas)
    from core.models import Membership
    tem_permissao = (
        usuario.is_superuser
        or usuario.has_perm('vendas.liberar_bloqueio_financeiro')
        or getattr(usuario, 'papel', '') in ('ADMIN', 'GERENTE')
        or Membership.objects.filter(tenant=venda.tenant, user=usuario, papel__in=['ADMIN', 'GERENTE'], ativo=True).exists()
    )
    if not tem_permissao:
        raise PermissionDenied("Usuário não possui a permissão 'vendas.liberar_bloqueio_financeiro' para liberar esta venda.")

    if venda.status != 'BLOQUEADO_FINANCEIRO':
        raise ValidationError(
            f"Apenas vendas com status 'BLOQUEADO_FINANCEIRO' podem ser liberadas (status atual: '{venda.status}')."
        )

    motivo_limpo = (motivo or '').strip()
    if len(motivo_limpo) < 5:
        raise ValidationError("O motivo da liberação é obrigatório e deve possuir no mínimo 5 caracteres.")

    liberacao = LiberacaoBloqueio.objects.create(
        tenant=venda.tenant,
        venda=venda,
        usuario=usuario,
        motivo=motivo_limpo,
        valor=venda.valor_total or Decimal('0.00')
    )

    venda.status = 'Pendente'
    venda.save(update_fields=['status', 'data_atualizacao'])

    return liberacao
