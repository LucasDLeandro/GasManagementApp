"""
Serviço Canônico de Fluxo de Caixa Realizado (Sprint 10C - Tarefa 1).
Apura entradas, saídas e saldos diários derivados estritamente de MovimentoConta,
agrupados por grupo_fluxo (Operacional, Investimento, Financiamento) e por Conta Financeira.
"""

import datetime
from decimal import Decimal
from typing import Optional, Union, Dict, Any, List

from django.core.exceptions import ValidationError
from django.db.models import Sum, Q

from core.guards import assert_modulo
from core.money import quantize
from financeiro.models import MovimentoConta, ContaFinanceira


def obter_fluxo_caixa_realizado(
    *,
    tenant,
    data_inicio: Union[str, datetime.date],
    data_fim: Union[str, datetime.date],
    conta_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Gera o demonstrativo do Fluxo de Caixa Realizado estritamente derivado de MovimentoConta (Sprint 10C - Tarefa 1).
    Apura:
    - Saldo inicial consolidado e por conta antes de data_inicio;
    - Movimentações diárias agrupadas por grupo_fluxo (OPERACIONAL, INVESTIMENTO, FINANCIAMENTO);
    - Saldo diário acumulado por conta e consolidado;
    - Saldo final consolidado e por conta.
    """
    assert_modulo(tenant, 'financeiro')

    if isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)
    if isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    if data_fim < data_inicio:
        raise ValidationError("A data final do período de fluxo de caixa não pode ser anterior à data inicial.")

    qs_contas = ContaFinanceira.unscoped.filter(tenant=tenant, ativo=True)
    if conta_id:
        qs_contas = qs_contas.filter(id=conta_id)
    contas_list = list(qs_contas)
    contas_ids = [c.id for c in contas_list]

    # 1. Saldo Inicial antes de data_inicio (por conta e consolidado)
    movs_anteriores = (
        MovimentoConta.unscoped
        .filter(
            tenant=tenant,
            conta_id__in=contas_ids,
            data_movimento__lt=data_inicio
        )
        .values('conta_id', 'tipo', 'tipo_ajuste')
        .annotate(total=Sum('valor'))
    )

    saldos_iniciais_por_conta = {c.id: Decimal('0.00') for c in contas_list}
    for m in movs_anteriores:
        c_id = m['conta_id']
        val = quantize(m['total'] or Decimal('0.00'), 2)
        tipo = m['tipo']
        ajuste = m.get('tipo_ajuste', 'ENTRADA')

        if tipo in ['ENTRADA', 'CREDITO', 'TRANSFERENCIA_ENTRADA', 'RENDIMENTO'] or (tipo == 'AJUSTE' and ajuste == 'ENTRADA'):
            saldos_iniciais_por_conta[c_id] = quantize(saldos_iniciais_por_conta[c_id] + val, 2)
        else:
            saldos_iniciais_por_conta[c_id] = quantize(saldos_iniciais_por_conta[c_id] - val, 2)

    saldo_inicial_consolidado = quantize(sum(saldos_iniciais_por_conta.values()), 2)

    # 2. Movimentos no período
    movimentos_periodo = (
        MovimentoConta.unscoped
        .filter(
            tenant=tenant,
            conta_id__in=contas_ids,
            data_movimento__gte=data_inicio,
            data_movimento__lte=data_fim
        )
        .select_related('conta')
        .order_by('data_movimento', 'criado_em')
    )

    # Dicionários de agregação por grupo de fluxo
    totais_grupo = {
        'OPERACIONAL': {'entradas': Decimal('0.00'), 'saidas': Decimal('0.00'), 'liquido': Decimal('0.00')},
        'INVESTIMENTO': {'entradas': Decimal('0.00'), 'saidas': Decimal('0.00'), 'liquido': Decimal('0.00')},
        'FINANCIAMENTO': {'entradas': Decimal('0.00'), 'saidas': Decimal('0.00'), 'liquido': Decimal('0.00')},
    }

    # Estruturação dia a dia
    dias_totais = (data_fim - data_inicio).days + 1
    grade_diaria = {}
    saldos_correntes_conta = dict(saldos_iniciais_por_conta)
    saldo_corrente_consolidado = saldo_inicial_consolidado

    for offset in range(dias_totais):
        dia_dt = data_inicio + datetime.timedelta(days=offset)
        dia_str = dia_dt.isoformat()
        grade_diaria[dia_str] = {
            'data': dia_str,
            'entradas': Decimal('0.00'),
            'saidas': Decimal('0.00'),
            'movimentacao_consolidada': Decimal('0.00'),
            'saldo_inicial': saldo_corrente_consolidado,
            'saldo_final': saldo_corrente_consolidado,
            'por_grupo': {
                'OPERACIONAL': {'entradas': Decimal('0.00'), 'saidas': Decimal('0.00')},
                'INVESTIMENTO': {'entradas': Decimal('0.00'), 'saidas': Decimal('0.00')},
                'FINANCIAMENTO': {'entradas': Decimal('0.00'), 'saidas': Decimal('0.00')},
            },
            'saldos_por_conta': dict(saldos_correntes_conta)
        }

    total_entradas_periodo = Decimal('0.00')
    total_saidas_periodo = Decimal('0.00')

    for mov in movimentos_periodo:
        dia_str = mov.data_movimento.isoformat()
        if dia_str not in grade_diaria:
            continue

        grupo = mov.grupo_fluxo or 'OPERACIONAL'
        if grupo not in totais_grupo:
            grupo = 'OPERACIONAL'

        val = quantize(mov.valor, 2)
        tipo = mov.tipo
        ajuste = mov.tipo_ajuste or 'ENTRADA'

        is_entrada = (tipo in ['ENTRADA', 'CREDITO', 'TRANSFERENCIA_ENTRADA', 'RENDIMENTO']) or (tipo == 'AJUSTE' and ajuste == 'ENTRADA')

        if is_entrada:
            totais_grupo[grupo]['entradas'] = quantize(totais_grupo[grupo]['entradas'] + val, 2)
            total_entradas_periodo = quantize(total_entradas_periodo + val, 2)
            grade_diaria[dia_str]['entradas'] = quantize(grade_diaria[dia_str]['entradas'] + val, 2)
            grade_diaria[dia_str]['por_grupo'][grupo]['entradas'] = quantize(grade_diaria[dia_str]['por_grupo'][grupo]['entradas'] + val, 2)
            saldos_correntes_conta[mov.conta_id] = quantize(saldos_correntes_conta[mov.conta_id] + val, 2)
            saldo_corrente_consolidado = quantize(saldo_corrente_consolidado + val, 2)
        else:
            totais_grupo[grupo]['saidas'] = quantize(totais_grupo[grupo]['saidas'] + val, 2)
            total_saidas_periodo = quantize(total_saidas_periodo + val, 2)
            grade_diaria[dia_str]['saidas'] = quantize(grade_diaria[dia_str]['saidas'] + val, 2)
            grade_diaria[dia_str]['por_grupo'][grupo]['saidas'] = quantize(grade_diaria[dia_str]['por_grupo'][grupo]['saidas'] + val, 2)
            saldos_correntes_conta[mov.conta_id] = quantize(saldos_correntes_conta[mov.conta_id] - val, 2)
            saldo_corrente_consolidado = quantize(saldo_corrente_consolidado - val, 2)

        grade_diaria[dia_str]['saldo_final'] = saldo_corrente_consolidado
        grade_diaria[dia_str]['saldos_por_conta'] = dict(saldos_correntes_conta)

    # 3. Consolida saldos finais diários
    saldo_dia_ant = saldo_inicial_consolidado
    saldos_conta_ant = dict(saldos_iniciais_por_conta)
    for dia_str, info in grade_diaria.items():
        info['saldo_inicial'] = saldo_dia_ant
        liquido_dia = quantize(info['entradas'] - info['saidas'], 2)
        info['movimentacao_consolidada'] = liquido_dia
        info['saldo_final'] = quantize(saldo_dia_ant + liquido_dia, 2)
        saldo_dia_ant = info['saldo_final']

    for g, vals in totais_grupo.items():
        vals['liquido'] = quantize(vals['entradas'] - vals['saidas'], 2)

    liquido_total = quantize(total_entradas_periodo - total_saidas_periodo, 2)

    return {
        'periodo': {'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat()},
        'saldo_inicial_consolidado': saldo_inicial_consolidado,
        'saldo_final_consolidado': saldo_corrente_consolidado,
        'total_entradas': total_entradas_periodo,
        'total_saidas': total_saidas_periodo,
        'variacao_liquida_caixa': liquido_total,
        'saldo_liquido_periodo': liquido_total,
        'saldos_iniciais_por_conta': {cid: str(v) for cid, v in saldos_iniciais_por_conta.items()},
        'saldos_finais_por_conta': {cid: str(v) for cid, v in saldos_correntes_conta.items()},
        'por_grupo_fluxo': totais_grupo,
        'fluxo_diario': list(grade_diaria.values()),
        'saldos_diarios': grade_diaria
    }
