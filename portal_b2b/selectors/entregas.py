"""
Seletor de Pedidos e Rastreio Logístico do Portal B2B (Sprint 12B).

Regras de negócio:
- Retorna histórico de pedidos e vendas do cliente.
- Retorna status das entregas e paradas de entrega vinculadas ao cliente.
- Se houver TokenRastreio válido emitido pela 12A, fornece o link de rastreamento em tempo real (/rastreio/<token>/).
"""
from typing import Any, Dict, List
from django.utils import timezone

from vendas.models import Venda
from logistica.models import ParadaEntrega, TokenRastreio


def get_historico_pedidos(tenant, cliente) -> List[Dict[str, Any]]:
    """
    Retorna o histórico de pedidos e vendas do cliente.
    """
    vendas = Venda.unscoped.filter(
        tenant=tenant,
        cliente=cliente
    ).select_related('filial').prefetch_related('itens__sku').order_by('-data_venda', '-id')

    resultado = []
    for v in vendas:
        itens_resumo = []
        for it in v.itens.all():
            itens_resumo.append({
                'sku_codigo': it.sku.codigo if it.sku else '',
                'descricao': it.sku.descricao if it.sku else '',
                'quantidade': str(it.quantidade),
                'preco_unitario': str(it.preco_unitario),
                'subtotal': str(it.subtotal),
            })

        resultado.append({
            'id': v.id,
            'numero': getattr(v, 'numero', f"PED-{v.id}"),
            'data_venda': v.data_venda.isoformat() if v.data_venda else None,
            'status': v.status,
            'status_display': v.get_status_display() if hasattr(v, 'get_status_display') else v.status,
            'valor_total': str(v.valor_total),
            'itens': itens_resumo,
            'observacoes': v.observacoes or '',
        })
    return resultado


def get_status_entregas(tenant, cliente) -> List[Dict[str, Any]]:
    """
    Retorna o status das entregas ativas e recentes com link de rastreamento TokenRastreio.
    """
    agora = timezone.now()
    paradas = ParadaEntrega.unscoped.filter(
        tenant=tenant,
        cliente=cliente
    ).select_related('entrega', 'entrega__veiculo', 'pedido').order_by('-criado_em')[:50]

    resultado = []
    for p in paradas:
        token_obj = TokenRastreio.objects.filter(
            tenant=tenant,
            parada=p,
            revogado=False,
            expira_em__gte=agora
        ).order_by('-criado_em').first()

        link_rastreio = None
        if token_obj:
            link_rastreio = f"/rastreio/{token_obj.token}/"

        resultado.append({
            'parada_id': p.id,
            'entrega_id': p.entrega_id,
            'pedido_id': p.pedido_id,
            'status': p.status,
            'status_display': p.get_status_display() if hasattr(p, 'get_status_display') else p.status,
            'ordem': p.ordem,
            'eta_estimado': p.eta_estimado.isoformat() if p.eta_estimado else None,
            'chegada_em': p.chegada_em.isoformat() if p.chegada_em else None,
            'concluida_em': p.concluida_em.isoformat() if p.concluida_em else None,
            'placa_veiculo': p.entrega.veiculo.placa if (p.entrega and p.entrega.veiculo) else None,
            'link_rastreio': link_rastreio,
        })
    return resultado
