"""
Máquina de estados da Venda (Plano de Correção, tarefa 0.3.2).

Toda mudança de status feita por usuário passa por transicionar_venda().
O bloqueio financeiro só é desfeito por liberacao_service.liberar_bloqueio_venda().
"""
from django.core.exceptions import PermissionDenied, ValidationError

from core.models import Membership

TRANSICOES_VENDA: dict[str, set[str]] = {
    'Pendente': {'Faturada', 'Em Separação', 'Cancelada'},
    'BLOQUEADO_FINANCEIRO': {'Cancelada'},
    'Faturada': {'Em Separação', 'Finalizada', 'Cancelada'},
    'Em Separação': {'Em Rota', 'Entregue', 'Finalizada', 'Cancelada'},
    'Em Rota': {'Entregue', 'Finalizada', 'Cancelada'},
    'Entregue': {'Finalizada'},
    'Finalizada': set(),
    'Cancelada': set(),
}

# Status que contam como faturamento (baixa de estoque + evento contábil).
STATUS_FATURAMENTO = {'Faturada', 'Finalizada'}

PAPEIS_ALTERAR_STATUS = {'ADMIN', 'GERENTE', 'VENDEDOR', 'OPERADOR_PATIO'}


def validar_transicao_venda(venda, novo_status: str) -> None:
    atual = venda.status
    if novo_status == atual:
        raise ValidationError(f"A venda #{venda.id} já está em '{atual}'.")
    if atual == 'BLOQUEADO_FINANCEIRO' and novo_status != 'Cancelada':
        raise ValidationError(
            "Venda bloqueada por crédito: libere o bloqueio (com motivo) antes de alterar o status."
        )
    permitidas = TRANSICOES_VENDA.get(atual, set())
    if novo_status not in permitidas:
        raise ValidationError(
            f"Transição inválida: '{atual}' → '{novo_status}'. "
            f"Permitidas: {', '.join(sorted(permitidas)) or 'nenhuma (status final)'}."
        )


def validar_papel_alteracao(usuario, tenant) -> None:
    if usuario.is_superuser:
        return
    autorizado = Membership.objects.filter(
        tenant=tenant, user=usuario, ativo=True, papel__in=PAPEIS_ALTERAR_STATUS
    ).exists()
    if not autorizado:
        raise PermissionDenied("Seu papel nesta empresa não permite alterar o status de vendas.")


def estoque_ja_baixado(venda) -> bool:
    from produtos.models import MovimentoEstoqueProduto
    return MovimentoEstoqueProduto.unscoped.filter(
        tenant=venda.tenant, tipo='SAIDA_VENDA', origem_tipo='Venda', origem_id=str(venda.id)
    ).exists()


def transicionar_venda(venda, novo_status: str, usuario) -> None:
    """Valida papel e transição. Não salva: quem chama aplica os efeitos e salva."""
    validar_papel_alteracao(usuario, venda.tenant)
    validar_transicao_venda(venda, novo_status)
    if novo_status == 'Cancelada' and estoque_ja_baixado(venda):
        raise ValidationError(
            "Esta venda já foi faturada (estoque baixado e contabilizado). "
            "O cancelamento após o faturamento exige estorno, ainda não disponível."
        )
    venda.status = novo_status
