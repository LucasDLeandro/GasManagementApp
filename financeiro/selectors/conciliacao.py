"""
Seletores para a Tela e API de Conciliação Bancária (Sprint 10A - Tarefa 6).
Estrutura dados para a visualização lado a lado (Extrato à esquerda, Sistema à direita).
"""
from decimal import Decimal
from typing import Dict, Any, List

from core.money import quantize
from financeiro.models import (
    ContaFinanceira,
    ExtratoBancarioItem,
    ParcelaFinanceira,
    ImportacaoExtrato,
)
from financeiro.services.conta import saldo_em


def obter_painel_conciliacao(
    *,
    tenant,
    conta_id: int
) -> Dict[str, Any]:
    """
    Retorna os dados consolidados para a interface de conciliação:
    - Extrato Bancário à Esquerda (não conciliados, sugeridos)
    - Sistema Financeiro à Direita (parcelas a receber em aberto)
    - Indicadores de batimento de saldo (Extrato x Razão)
    """
    conta = ContaFinanceira.objects.get(id=conta_id, tenant=tenant)
    saldo_razao = saldo_em(conta)

    ultima_importacao = ImportacaoExtrato.objects.filter(
        tenant=tenant,
        conta=conta
    ).order_by('-criado_em').first()

    saldo_extrato = ultima_importacao.saldo_final_arquivo if ultima_importacao else None
    diferenca = quantize(saldo_extrato - saldo_razao, 2) if saldo_extrato is not None else None

    # Lado Esquerdo: Itens de extrato pendentes ou sugeridos
    itens_extrato = ExtratoBancarioItem.objects.filter(
        tenant=tenant,
        conta=conta
    ).exclude(status__in=['CONCILIADO', 'IGNORADO']).order_by('-data', '-id')

    # Lado Direito: Parcelas em aberto para conciliação
    parcelas_sistema = ParcelaFinanceira.objects.filter(
        tenant=tenant,
        titulo__tipo='RECEBER',
        status__in=['PENDENTE', 'PARCIAL'],
        saldo_em_aberto__gt=Decimal('0.00')
    ).select_related('titulo', 'titulo__cliente').order_by('data_vencimento')

    # Histórico recente de conciliados e ignorados
    itens_conciliados_recentes = ExtratoBancarioItem.objects.filter(
        tenant=tenant,
        conta=conta,
        status__in=['CONCILIADO', 'IGNORADO']
    ).order_by('-data', '-id')[:20]

    return {
        'conta': conta,
        'saldo_razao': saldo_razao,
        'saldo_extrato': saldo_extrato,
        'diferenca': diferenca,
        'conciliacao_fechada_ate': conta.conciliacao_fechada_ate,
        'itens_extrato': itens_extrato,
        'parcelas_sistema': parcelas_sistema,
        'itens_conciliados_recentes': itens_conciliados_recentes,
        'total_pendentes': itens_extrato.count(),
    }
