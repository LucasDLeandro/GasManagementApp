"""
Máquina de estados da Venda (Plano de Correção, tarefa 0.3.2).

Toda mudança de status feita por usuário passa por transicionar_venda().
O bloqueio financeiro só é desfeito por liberacao_service.liberar_bloqueio_venda().
"""
from django.db import transaction
from django.core.exceptions import PermissionDenied, ValidationError

from core.models import Membership

TRANSICOES_VENDA: dict[str, set[str]] = {
    'Pendente': {'Faturada', 'Em Separação', 'Cancelada', 'BLOQUEADO_FINANCEIRO'},
    'BLOQUEADO_FINANCEIRO': {'Cancelada', 'Pendente'},
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


def validar_origem_e_usuario(origem: str, usuario) -> None:
    if origem in ('SISTEMA', 'API'):
        return
    if origem in ('TELA', 'APP_CAMPO'):
        if usuario is None or (hasattr(usuario, 'is_authenticated') and not usuario.is_authenticated):
            raise ValidationError(f"Operações com origem '{origem}' exigem um usuário autenticado.")
    else:
        raise ValidationError(f"Origem desconhecida: '{origem}'.")


def validar_transicao_venda(venda, novo_status: str) -> None:
    atual = venda.status
    if novo_status == atual:
        raise ValidationError(f"A venda #{venda.id} já está em '{atual}'.")
    if atual == 'BLOQUEADO_FINANCEIRO' and novo_status not in ('Cancelada', 'Pendente'):
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
    if usuario is None:
        return
    if getattr(usuario, 'is_superuser', False):
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


def registrar_historico_venda(
    venda,
    novo_status: str,
    status_anterior: str = None,
    usuario=None,
    origem: str = 'TELA',
    observacoes: str = ''
):
    """Registra uma entrada no histórico de status da Venda."""
    from vendas.models import HistoricoStatusVenda
    return HistoricoStatusVenda.unscoped.create(
        tenant=venda.tenant,
        venda=venda,
        status_anterior=status_anterior,
        status_novo=novo_status,
        alterado_por=usuario if (usuario and hasattr(usuario, 'pk') and usuario.pk) else None,
        origem=origem,
        observacoes=observacoes
    )


@transaction.atomic
def transicionar_venda(
    venda,
    novo_status: str,
    usuario,
    origem: str = 'TELA',
    observacoes: str = ''
) -> None:
    """Valida papel, origem e transição. Atualiza o status da venda e registra o histórico."""
    validar_origem_e_usuario(origem, usuario)
    validar_papel_alteracao(usuario, venda.tenant)
    validar_transicao_venda(venda, novo_status)
    if novo_status == 'Cancelada' and estoque_ja_baixado(venda):
        raise ValidationError(
            "Esta venda já foi faturada (estoque baixado e contabilizado). "
            "O cancelamento após o faturamento exige estorno, ainda não disponível."
        )
    status_anterior = venda.status
    venda.status = novo_status
    if venda.pk:
        venda.save(update_fields=['status', 'data_atualizacao'])
        registrar_historico_venda(
            venda=venda,
            novo_status=novo_status,
            status_anterior=status_anterior,
            usuario=usuario,
            origem=origem,
            observacoes=observacoes
        )


def desde_quando_no_status(venda):
    """
    Retorna datetime em que a venda entrou no status atual.
    Busca o último registro de HistoricoStatusVenda com status_novo == venda.status.
    Fallback: data_atualizacao ou data_venda.
    """
    from vendas.models import HistoricoStatusVenda
    ultimo_hist = HistoricoStatusVenda.unscoped.filter(
        venda=venda, status_novo=venda.status
    ).order_by('-alterado_em').first()
    if ultimo_hist and ultimo_hist.alterado_em:
        return ultimo_hist.alterado_em
    return getattr(venda, 'data_atualizacao', None) or getattr(venda, 'data_venda', None)

