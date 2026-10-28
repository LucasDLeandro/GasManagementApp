"""
Seletor de Histórico de Recompra (Sprint 12C - Tarefa 1).

Regras de negócio:
- Recupera datas de compras faturadas a partir de Venda e ItemVenda para um determinado cliente e gás.
- Vendas confirmadas: status faturada, entregue ou finalizada (exclui canceladas e bloqueadas por crédito).
- Regra fundamental: Cliente com menos de 4 compras do gás fica sem previsão (sem alerta gerado).
"""
import datetime
from typing import Any, Dict, List, Optional, Tuple, Set

from django.db.models import Q
from django.utils import timezone

from clientes.models import Cliente
from produtos.models import GasQuimico
from vendas.models import Venda, ItemVenda

STATUS_VENDAS_FATURADAS = [
    'Faturada', 'Entregue', 'Finalizada',
    'faturada', 'entregue', 'finalizada',
    'Concluida', 'concluida'
]


def historico_recompra(
    cliente: Cliente,
    gas: Optional[GasQuimico] = None,
    tenant=None
) -> Dict[str, Any]:
    """
    Retorna o histórico cronológico de datas de compra de um determinado gás por um cliente.

    Critério estrito:
    - Se houver menos de 4 compras faturadas do gás, 'elegivel' é False e nenhuma previsão é gerada.
    """
    resolved_tenant = tenant or getattr(cliente, 'tenant', None)

    qs_itens = ItemVenda.unscoped.filter(
        venda__cliente=cliente,
        venda__status__in=STATUS_VENDAS_FATURADAS
    ).exclude(
        venda__status__in=['Cancelada', 'cancelada', 'BLOQUEADO_FINANCEIRO']
    )

    if resolved_tenant:
        qs_itens = qs_itens.filter(venda__tenant=resolved_tenant)

    if gas is not None:
        qs_itens = qs_itens.filter(sku__gas=gas)

    # Coleta as datas únicas de compra ordenadas cronologicamente
    vendas_qs = qs_itens.select_related('venda').values_list(
        'venda_id', 'venda__data_venda', 'venda__data_entrega_efetiva'
    ).distinct()

    datas_set: Set[datetime.date] = set()
    for _, dt_venda, dt_entrega in vendas_qs:
        data_efetiva = dt_entrega or (dt_venda.date() if dt_venda else None)
        if data_efetiva:
            datas_set.add(data_efetiva)

    datas_ordenadas: List[datetime.date] = sorted(list(datas_set))
    total_compras = len(datas_ordenadas)

    if total_compras < 4:
        return {
            'cliente_id': cliente.id,
            'gas_id': gas.id if gas else None,
            'compras': datas_ordenadas,
            'total_compras': total_compras,
            'elegivel': False,
            'motivo': f"Cliente possui apenas {total_compras} compras faturadas deste gás (mínimo exigido: 4).",
            'ultima_compra': datas_ordenadas[-1] if datas_ordenadas else None,
        }

    return {
        'cliente_id': cliente.id,
        'gas_id': gas.id if gas else None,
        'compras': datas_ordenadas,
        'total_compras': total_compras,
        'elegivel': True,
        'motivo': "Histórico suficiente para inferência estatística de recompra.",
        'primeira_compra': datas_ordenadas[0],
        'ultima_compra': datas_ordenadas[-1],
    }


def obter_pares_cliente_gas_ativos(tenant) -> List[Tuple[Cliente, GasQuimico]]:
    """
    Retorna pares únicos (cliente, gas) que possuem movimentação de vendas no tenant.
    """
    itens = ItemVenda.unscoped.filter(
        venda__tenant=tenant,
        venda__status__in=STATUS_VENDAS_FATURADAS,
        sku__gas__isnull=False
    ).exclude(
        venda__status__in=['Cancelada', 'cancelada', 'BLOQUEADO_FINANCEIRO']
    ).select_related('venda__cliente', 'sku__gas')

    pares_map: Dict[Tuple[int, int], Tuple[Cliente, GasQuimico]] = {}

    for it in itens:
        cliente = it.venda.cliente
        gas = it.sku.gas if it.sku else None
        if cliente and gas:
            chave = (cliente.id, gas.id)
            if chave not in pares_map:
                pares_map[chave] = (cliente, gas)

    return list(pares_map.values())
