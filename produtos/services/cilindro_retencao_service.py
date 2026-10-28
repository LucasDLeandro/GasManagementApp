"""
Serviço Canônico de Custo Líquido de Retenção de Cilindros Parados (Sprint 10C - Tarefa 7 / F-23).
Fórmula estritamente determinística (sem IA):
Custo Líquido = Σ dias_retido * (depreciação_diária + valor_contábil * TMA_mensal / 30) - receita_estadia_faturada.
Resultado positivo classifica o cilindro como DESTRUIDOR_DE_MARGEM.
Visões: por cilindro, por cliente e por contrato de comodato.
"""

import datetime
from decimal import Decimal
from typing import Optional, Union, Dict, Any, List

from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, Count
from django.utils import timezone

from core.guards import assert_modulo
from core.money import quantize
from financeiro.models import DepreciacaoMensal, ParametroGestaoTenant
from produtos.models import Cilindro
from clientes.models import Cliente, ContratoComodato, DiaCilindro, ItemFaturaEstadia


def calcular_custo_retencao_cilindro(
    *,
    tenant,
    cilindro_id: int,
    data_inicio: Union[str, datetime.date],
    data_fim: Union[str, datetime.date],
    tma_mensal_override: Optional[Decimal] = None
) -> Dict[str, Any]:
    """
    Calcula o custo líquido de retenção determinístico de um cilindro no período (Sprint 10C - Tarefa 7).
    Fórmula: dias_retido * (depreciacao_diaria + valor_contabil * TMA_mensal / 30) - receita_estadia.
    Resultado positivo marca o cilindro como DESTRUIDOR_DE_MARGEM.
    """
    assert_modulo(tenant, 'patrimonio')

    if isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)
    if isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    cilindro = Cilindro.unscoped.get(tenant=tenant, id=cilindro_id)

    # 1. Taxa Mínima de Atratividade (TMA) do Tenant
    if tma_mensal_override is not None:
        tma_mensal = tma_mensal_override
    else:
        param, _ = ParametroGestaoTenant.unscoped.get_or_create(
            tenant=tenant,
            defaults={'tma_mensal': Decimal('0.0150')}
        )
        tma_mensal = param.tma_mensal

    # 2. Valor Contábil Líquido e Depreciação Diária
    # Busca do Ledger DepreciacaoMensal caso exista registro
    ultimo_ledger = (
        DepreciacaoMensal.unscoped
        .filter(
            tenant=tenant,
            tipo_alvo__in=['CILINDRO_AVULSO', 'LOTE_CILINDROS'],
            alvo_id=cilindro.id
        )
        .order_by('-periodo')
        .first()
    )

    if ultimo_ledger and ultimo_ledger.valor_contabil_apos is not None:
        valor_contabil = quantize(ultimo_ledger.valor_contabil_apos, 2)
        depreciacao_mensal = quantize(ultimo_ledger.quota, 2)
    else:
        # Fallback determinístico a partir do cadastro do ativo
        v_aq = cilindro.valor_aquisicao or Decimal('0.00')
        v_res = cilindro.valor_residual or Decimal('0.00')
        vida_m = cilindro.vida_util_meses or 120
        depreciacao_mensal = quantize((v_aq - v_res) / Decimal(vida_m) if vida_m > 0 else Decimal('0.00'), 2)
        # Valor contábil simplificado
        valor_contabil = quantize(v_aq, 2)

    depreciacao_diaria = quantize(depreciacao_mensal / Decimal('30.00'), 4)
    custo_capital_diario = quantize(valor_contabil * (tma_mensal / Decimal('30.00')), 4)
    custo_posse_diario = quantize(depreciacao_diaria + custo_capital_diario, 4)

    # 3. Dias de Retenção / Posse no Período
    # Verifica em DiaCilindro ou no status de posse atual
    dias_retido_db = (
        DiaCilindro.unscoped
        .filter(
            tenant=tenant,
            cilindro=cilindro,
            data_referencia__gte=data_inicio,
            data_referencia__lte=data_fim
        )
        .count()
    )

    if dias_retido_db > 0:
        dias_retido = dias_retido_db
    elif cilindro.status == 'EM_POSSE_CLIENTE' and cilindro.posse_desde:
        # Calcula dias corridos dentro da janela [data_inicio, data_fim]
        posse_ini = max(cilindro.posse_desde.date(), data_inicio)
        posse_fim = min(timezone.localdate(), data_fim)
        dias_retido = max(0, (posse_fim - posse_ini).days + 1)
    else:
        dias_retido = 0

    # 4. Receita de Estadia / Demurrage Faturada no Período
    itens_fatura = (
        ItemFaturaEstadia.unscoped
        .filter(
            tenant=tenant,
            cilindro=cilindro,
            fatura__data_fechamento__date__gte=data_inicio,
            fatura__data_fechamento__date__lte=data_fim
        )
        .aggregate(total=Sum('subtotal'))
    )
    receita_estadia = quantize(itens_fatura['total'] or Decimal('0.00'), 2)

    # 5. Cálculo Final do Custo Líquido
    custo_retencao_bruto = quantize(Decimal(dias_retido) * custo_posse_diario, 2)
    custo_liquido = quantize(custo_retencao_bruto - receita_estadia, 2)

    classificacao = 'DESTRUIDOR_DE_MARGEM' if custo_liquido > Decimal('0.00') else ('SUPERAVIT_ESTADIA' if receita_estadia > Decimal('0.00') else 'NEUTRO')

    cliente_atual = cilindro.cliente_posse_atual
    contrato_atual = None
    if cliente_atual:
        contrato_atual = ContratoComodato.unscoped.filter(tenant=tenant, cliente=cliente_atual).first()

    return {
        'cilindro': {
            'id': cilindro.id,
            'codigo_qr': cilindro.codigo_qr,
            'numero_serie_ogiva': cilindro.numero_serie_ogiva,
            'modelo': cilindro.modelo.descricao,
            'gas': cilindro.gas_dedicado.sigla
        },
        'cliente': {
            'id': cliente_atual.id,
            'nome': cliente_atual.nome
        } if cliente_atual else None,
        'contrato_id': contrato_atual.id if contrato_atual else None,
        'periodo': {'inicio': data_inicio.isoformat(), 'fim': data_fim.isoformat()},
        'formula': "Σ dias_retido * (depreciação_diária + valor_contábil * TMA_mensal / 30) - receita_estadia_faturada",
        'parametros': {
            'tma_mensal': tma_mensal,
            'valor_contabil_liquido': valor_contabil,
            'depreciacao_diaria': depreciacao_diaria,
            'custo_capital_diario': custo_capital_diario,
            'custo_posse_diario': custo_posse_diario
        },
        'dias_retido': dias_retido,
        'custo_retencao_bruto': custo_retencao_bruto,
        'receita_estadia_faturada': receita_estadia,
        'custo_liquido': custo_liquido,
        'classificacao': classificacao,
        'destruidor_de_margem': (classificacao == 'DESTRUIDOR_DE_MARGEM')
    }


def analise_retencao_cilindros_consolidada(
    *,
    tenant,
    data_inicio: Union[str, datetime.date],
    data_fim: Union[str, datetime.date],
    visao: str = 'cilindro'
) -> Dict[str, Any]:
    """
    Gera visão consolidada de custo de retenção por cilindro, por cliente ou por contrato de comodato (Tarefa 7).
    """
    assert_modulo(tenant, 'patrimonio')

    if isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)
    if isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    cilindros = Cilindro.unscoped.filter(
        tenant=tenant,
        status__in=['EM_POSSE_CLIENTE', 'RESERVADO_ROTA', 'CHEIO_DISPONIVEL']
    ).select_related('modelo', 'gas_dedicado', 'cliente_posse_atual')

    itens_analisados = []
    total_custo_liquido = Decimal('0.00')
    total_destruidores = 0

    for c in cilindros:
        res = calcular_custo_retencao_cilindro(
            tenant=tenant,
            cilindro_id=c.id,
            data_inicio=data_inicio,
            data_fim=data_fim
        )
        itens_analisados.append(res)
        total_custo_liquido = quantize(total_custo_liquido + res['custo_liquido'], 2)
        if res['destruidor_de_margem']:
            total_destruidores += 1

    # Agrupamentos por cliente ou contrato
    if visao == 'cliente':
        agrupado_cli: Dict[int, Dict[str, Any]] = {}
        for item in itens_analisados:
            cli = item['cliente']
            c_id = cli['id'] if cli else 0
            c_nome = cli['nome'] if cli else 'Sem Cliente Atribuído'

            if c_id not in agrupado_cli:
                agrupado_cli[c_id] = {
                    'cliente_id': c_id,
                    'cliente_nome': c_nome,
                    'total_cilindros': 0,
                    'dias_retido_total': 0,
                    'custo_retencao_bruto': Decimal('0.00'),
                    'receita_estadia': Decimal('0.00'),
                    'custo_liquido': Decimal('0.00'),
                    'qtd_destruidores': 0
                }
            agrupado_cli[c_id]['total_cilindros'] += 1
            agrupado_cli[c_id]['dias_retido_total'] += item['dias_retido']
            agrupado_cli[c_id]['custo_retencao_bruto'] = quantize(agrupado_cli[c_id]['custo_retencao_bruto'] + item['custo_retencao_bruto'], 2)
            agrupado_cli[c_id]['receita_estadia'] = quantize(agrupado_cli[c_id]['receita_estadia'] + item['receita_estadia_faturada'], 2)
            agrupado_cli[c_id]['custo_liquido'] = quantize(agrupado_cli[c_id]['custo_liquido'] + item['custo_liquido'], 2)
            if item['destruidor_de_margem']:
                agrupado_cli[c_id]['qtd_destruidores'] += 1

        linhas_resultado = list(agrupado_cli.values())
        linhas_resultado.sort(key=lambda x: -x['custo_liquido'])

    elif visao == 'contrato':
        agrupado_con: Dict[Any, Dict[str, Any]] = {}
        for item in itens_analisados:
            con_id = item.get('contrato_id') or 'SEM_CONTRATO'
            if con_id not in agrupado_con:
                agrupado_con[con_id] = {
                    'contrato_id': con_id,
                    'cliente': item['cliente']['nome'] if item['cliente'] else 'N/A',
                    'total_cilindros': 0,
                    'dias_retido_total': 0,
                    'custo_retencao_bruto': Decimal('0.00'),
                    'receita_estadia': Decimal('0.00'),
                    'custo_liquido': Decimal('0.00'),
                    'qtd_destruidores': 0
                }
            agrupado_con[con_id]['total_cilindros'] += 1
            agrupado_con[con_id]['dias_retido_total'] += item['dias_retido']
            agrupado_con[con_id]['custo_retencao_bruto'] = quantize(agrupado_con[con_id]['custo_retencao_bruto'] + item['custo_retencao_bruto'], 2)
            agrupado_con[con_id]['receita_estadia'] = quantize(agrupado_con[con_id]['receita_estadia'] + item['receita_estadia_faturada'], 2)
            agrupado_con[con_id]['custo_liquido'] = quantize(agrupado_con[con_id]['custo_liquido'] + item['custo_liquido'], 2)
            if item['destruidor_de_margem']:
                agrupado_con[con_id]['qtd_destruidores'] += 1

        linhas_resultado = list(agrupado_con.values())
        linhas_resultado.sort(key=lambda x: -x['custo_liquido'])

    else:
        linhas_resultado = itens_analisados
        linhas_resultado.sort(key=lambda x: -x['custo_liquido'])

    return {
        'visao': visao,
        'periodo': {'inicio': data_inicio.isoformat(), 'fim': data_fim.isoformat()},
        'total_itens': len(linhas_resultado),
        'total_destruidores_de_margem': total_destruidores,
        'custo_liquido_total': total_custo_liquido,
        'linhas': linhas_resultado
    }
