import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable[[dict[str, Any]], Any]]] = defaultdict(list)


def assinar(nome_evento: str, handler: Callable[[dict[str, Any]], Any]) -> None:
    """Registra um manipulador (handler) para um evento de domínio específico."""
    if handler not in _handlers[nome_evento]:
        _handlers[nome_evento].append(handler)


def desassinar(nome_evento: str, handler: Callable[[dict[str, Any]], Any]) -> None:
    """Remove um manipulador previamente registrado."""
    if handler in _handlers[nome_evento]:
        _handlers[nome_evento].remove(handler)


def limpar_assinantes(nome_evento: str | None = None) -> None:
    """Limpa assinantes registrados (útil para isolamento em testes)."""
    if nome_evento:
        _handlers[nome_evento].clear()
    else:
        _handlers.clear()


def publicar(nome_evento: str, payload: dict[str, Any]) -> list[Any]:
    """
    Publica um evento de domínio e executa os handlers síncronos registrados.
    Eventos da Sprint 7B: 'venda_faturada', 'fatura_estadia_fechada'.
    """
    handlers = list(_handlers.get(nome_evento, []))
    respostas = []

    for h in handlers:
        try:
            res = h(payload)
            respostas.append(res)
        except Exception:
            logger.exception(
                f"[Eventos] Erro ao executar handler '{getattr(h, '__name__', str(h))}' "
                f"para evento '{nome_evento}'"
            )
            raise

    return respostas


# ==============================================================================
# HANDLERS FINANCEIROS PADRÃO (Sprint 7B - Correção F-31)
# ==============================================================================

def handler_financeiro_venda_faturada(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Assinante financeiro para o evento 'venda_faturada'.
    Se modulo_financeiro_ativo: agenda lançamento de Contas a Receber.
    Se inativo: mantém estritamente o registro operacional, sem título financeiro.
    """
    tenant = payload.get('tenant')
    from core.modulos import is_modulo_ativo

    if not is_modulo_ativo(tenant, 'financeiro'):
        return {
            'evento': 'venda_faturada',
            'modulo': 'financeiro',
            'status': 'IGNORADO_SEM_MODULO_FINANCEIRO',
            'detalhes': 'Módulo financeiro inativo no tenant. Registro mantido puramente operacional.'
        }

    return {
        'evento': 'venda_faturada',
        'modulo': 'financeiro',
        'status': 'TITULO_A_RECEBER_PROCESSADO',
        'venda_id': payload.get('venda_id'),
        'valor': str(payload.get('valor_total', '0.00'))
    }


def handler_financeiro_fatura_estadia_fechada(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Assinante financeiro para o evento 'fatura_estadia_fechada'.
    Se modulo_financeiro_ativo: agenda faturamento/recebimento de estadia.
    Se inativo: ignora integração financeira.
    """
    tenant = payload.get('tenant')
    from core.modulos import is_modulo_ativo

    if not is_modulo_ativo(tenant, 'financeiro'):
        return {
            'evento': 'fatura_estadia_fechada',
            'modulo': 'financeiro',
            'status': 'IGNORADO_SEM_MODULO_FINANCEIRO',
            'detalhes': 'Módulo financeiro inativo no tenant. Estadia gravada sem título financeiro.'
        }

    return {
        'evento': 'fatura_estadia_fechada',
        'modulo': 'financeiro',
        'status': 'FATURA_ESTADIA_PROCESSADA',
        'fatura_id': payload.get('fatura_id'),
        'valor': str(payload.get('valor_total', '0.00'))
    }


# Registra os handlers nativos
assinar('venda_faturada', handler_financeiro_venda_faturada)
assinar('fatura_estadia_fechada', handler_financeiro_fatura_estadia_fechada)
