"""
Máquina de estados e rastreabilidade temporal da Entrega (Sprint 01B - Tarefa 01B.1).
Toda transição de status de Entrega passa por transicionar_entrega() ou grava histórico.
"""
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from logistica.models import Entrega, HistoricoStatusEntrega

TRANSICOES_ENTREGA: dict[str, set[str]] = {
    'Agendada': {'Em Produção', 'Em Rota', 'Cancelada'},
    'Em Produção': {'Em Rota', 'Cancelada'},
    'Em Rota': {'Concluída', 'Cancelada', 'Agendada'},  # Agendada: reentrega após sinistro / avaria
    'Concluída': set(),
    'Cancelada': {'Agendada'},  # Nova tentativa ou reativação
}


def validar_origem_e_usuario(origem: str, usuario) -> None:
    if origem in ('SISTEMA', 'API'):
        return
    if origem in ('TELA', 'APP_CAMPO'):
        if usuario is None or (hasattr(usuario, 'is_authenticated') and not usuario.is_authenticated):
            raise ValidationError(f"Operações com origem '{origem}' exigem um usuário autenticado.")
    else:
        raise ValidationError(f"Origem desconhecida: '{origem}'.")


def validar_transicao_entrega(entrega: Entrega, novo_status: str) -> None:
    atual = entrega.status
    if novo_status == atual:
        raise ValidationError(f"A entrega #{entrega.id} já está em '{atual}'.")
    permitidas = TRANSICOES_ENTREGA.get(atual, set())
    if novo_status not in permitidas:
        raise ValidationError(
            f"Transição inválida: '{atual}' → '{novo_status}'. "
            f"Permitidas: {', '.join(sorted(permitidas)) or 'nenhuma (status final)'}."
        )


def registrar_historico_entrega(
    entrega: Entrega,
    novo_status: str,
    status_anterior: str = None,
    usuario=None,
    origem: str = 'SISTEMA',
    observacoes: str = ''
) -> HistoricoStatusEntrega:
    """Registra uma entrada no histórico de status da Entrega."""
    return HistoricoStatusEntrega.unscoped.create(
        tenant=entrega.tenant,
        entrega=entrega,
        status_anterior=status_anterior,
        status_novo=novo_status,
        alterado_por=usuario if (usuario and hasattr(usuario, 'pk') and usuario.pk) else None,
        origem=origem,
        observacoes=observacoes
    )


@transaction.atomic
def transicionar_entrega(
    entrega: Entrega,
    novo_status: str,
    usuario=None,
    origem: str = 'SISTEMA',
    observacoes: str = ''
) -> None:
    """Valida papel/transição/origem, atualiza o status da entrega e registra o histórico."""
    validar_origem_e_usuario(origem, usuario)
    validar_transicao_entrega(entrega, novo_status)
    status_anterior = entrega.status
    entrega.status = novo_status
    if entrega.pk:
        fields = ['status']
        if novo_status == 'Em Rota' and not entrega.data_saida:
            entrega.data_saida = timezone.now()
            fields.append('data_saida')
        entrega.save(update_fields=fields)
        registrar_historico_entrega(
            entrega=entrega,
            novo_status=novo_status,
            status_anterior=status_anterior,
            usuario=usuario,
            origem=origem,
            observacoes=observacoes
        )


def desde_quando_no_status(entrega: Entrega):
    """
    Retorna datetime em que a entrega entrou no status atual.
    Busca o último registro de HistoricoStatusEntrega com status_novo == entrega.status.
    Fallback: entrega.data_saida ou data de criação.
    """
    ultimo_hist = HistoricoStatusEntrega.unscoped.filter(
        entrega=entrega, status_novo=entrega.status
    ).order_by('-alterado_em').first()
    if ultimo_hist and ultimo_hist.alterado_em:
        return ultimo_hist.alterado_em
    return getattr(entrega, 'data_saida', None)

