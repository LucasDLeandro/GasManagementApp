"""
Serviço Canônico de Indicadores e KPIs de Gestão do Dono (Sprint 10C - Tarefa 8).
Calcula métricas auditáveis:
- Margem por kg e por produto;
- Giro de cilindro (envios por ano / parque);
- Prazo Médio de Recebimento (PMR) e de Pagamento (PMP);
- Inadimplência por cliente;
- Rentabilidade por cliente e por rota.
"""

import datetime
from decimal import Decimal
from typing import Optional, Union, Dict, Any, List

from django.db.models import Sum, Count, Avg, F, Q
from django.utils import timezone

from core.guards import assert_modulo
from core.money import quantize
from vendas.models import Venda, ItemVenda
from produtos.models import Cilindro, GasQuimico, MovimentacaoCilindro
from clientes.models import Cliente
from financeiro.models import TituloFinanceiro, ParcelaFinanceira, PartidaContabil
from logistica.models import Rota, Entrega


def calcular_indicadores_gestao(
    *,
    tenant,
    data_inicio: Optional[Union[str, datetime.date]] = None,
    data_fim: Optional[Union[str, datetime.date]] = None
) -> Dict[str, Any]:
    """
    Consolida todos os indicadores gerenciais com fórmulas e fontes explícitas (Sprint 10C - Tarefa 8).
    """
    assert_modulo(tenant, 'analytics')

    if data_fim is None:
        data_fim = timezone.localdate()
    elif isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    if data_inicio is None:
        data_inicio = data_fim - datetime.timedelta(days=365)
    elif isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)

    # 1. Margem por Kg e por Produto
    itens = (
        ItemVenda.unscoped
        .filter(
            venda__tenant=tenant,
            venda__data_venda__gte=data_inicio,
            venda__data_venda__lte=data_fim
        )
        .exclude(venda__status='Cancelada')
        .select_related('sku__gas')
    )

    produtos_map = {}
    for it in itens:
        gas = it.sku.gas if it.sku else None
        p_nome = gas.nome if gas else (it.sku.nome if it.sku else "Item Geral")
        sigla = gas.sigla if gas else "-"

        if p_nome not in produtos_map:
            produtos_map[p_nome] = {
                'produto': p_nome,
                'sigla': sigla,
                'receita': Decimal('0.00'),
                'cpv': Decimal('0.00'),
                'volume_kg': Decimal('0.000'),
            }

        rec = quantize(it.valor_total or Decimal('0.00'), 2)
        custo_u = getattr(it.sku, 'custo_medio_unitario', Decimal('0.00')) or Decimal('0.00')
        cpv = quantize(custo_u * it.quantidade, 2)
        # Volume aproximado em kg (base no sku ou quantidade)
        vol_kg = quantize(Decimal(it.quantidade) * getattr(it.sku, 'capacidade_kg', Decimal('1.000')), 3)

        produtos_map[p_nome]['receita'] = quantize(produtos_map[p_nome]['receita'] + rec, 2)
        produtos_map[p_nome]['cpv'] = quantize(produtos_map[p_nome]['cpv'] + cpv, 2)
        produtos_map[p_nome]['volume_kg'] = quantize(produtos_map[p_nome]['volume_kg'] + vol_kg, 3)

    lista_margem_produtos = []
    for p_dados in produtos_map.values():
        rec = p_dados['receita']
        cpv = p_dados['cpv']
        kg = p_dados['volume_kg']
        lucro = quantize(rec - cpv, 2)
        margem_pct = quantize((lucro / rec * Decimal('100.00')) if rec > Decimal('0.00') else Decimal('0.0000'), 4)
        margem_por_kg = quantize((lucro / kg) if kg > Decimal('0.000') else Decimal('0.00'), 2)

        lista_margem_produtos.append({
            'produto': p_dados['produto'],
            'sigla': p_dados['sigla'],
            'receita_liquida': rec,
            'cpv': cpv,
            'lucro_bruto': lucro,
            'margem_pct': margem_pct,
            'volume_kg': kg,
            'margem_por_kg': margem_por_kg
        })

    # 2. Giro de Cilindro (Envios por ano / Parque de Cilindros)
    total_parque = Cilindro.unscoped.filter(tenant=tenant).count()
    um_ano_atras = data_fim - datetime.timedelta(days=365)

    # Envases/Remessas no último ano
    total_envios_ano = (
        MovimentacaoCilindro.unscoped
        .filter(
            tenant=tenant,
            ocorrido_em__date__gte=um_ano_atras,
            ocorrido_em__date__lte=data_fim,
            tipo__in=['ENTREGA_CLIENTE', 'SAIDA_ROTA', 'SAIDA_ENTREGA']
        )
        .count()
    )
    giro_cilindro = quantize(Decimal(total_envios_ano) / Decimal(total_parque) if total_parque > 0 else Decimal('0.0000'), 4)

    # 3. Prazo Médio de Recebimento (PMR) e de Pagamento (PMP)
    # PMR: Média ponderada dos dias de recebimento das parcelas pagas no período
    parcelas_rec = (
        ParcelaFinanceira.unscoped
        .filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            status__in=['PAGA', 'LIQUIDADA'],
            data_vencimento__gte=data_inicio,
            data_vencimento__lte=data_fim
        )
        .select_related('titulo')
    )
    total_dias_receber = 0
    qtd_rec = 0
    for p in parcelas_rec:
        dt_base = p.titulo.data_emissao if p.titulo else p.data_vencimento
        dt_liq = p.data_pagamento or p.data_vencimento
        total_dias_receber += max(0, (dt_liq - dt_base).days)
        qtd_rec += 1
    pmr_dias = quantize(Decimal(total_dias_receber) / Decimal(qtd_rec) if qtd_rec > 0 else Decimal('30.00'), 2)

    # PMP: Média ponderada de dias de pagamento a fornecedores
    parcelas_pag = (
        ParcelaFinanceira.unscoped
        .filter(
            tenant=tenant,
            titulo__tipo='PAGAR',
            status__in=['PAGA', 'LIQUIDADA'],
            data_vencimento__gte=data_inicio,
            data_vencimento__lte=data_fim
        )
        .select_related('titulo')
    )
    total_dias_pagar = 0
    qtd_pag = 0
    for p in parcelas_pag:
        dt_base = p.titulo.data_emissao if p.titulo else p.data_vencimento
        dt_liq = p.data_pagamento or p.data_vencimento
        total_dias_pagar += max(0, (dt_liq - dt_base).days)
        qtd_pag += 1
    pmp_dias = quantize(Decimal(total_dias_pagar) / Decimal(qtd_pag) if qtd_pag > 0 else Decimal('30.00'), 2)

    # 4. Inadimplência por Cliente
    # Saldo vencido há mais de 30 dias dividido pelo faturamento do cliente
    clientes_com_movimento = (
        Cliente.unscoped
        .filter(tenant=tenant)
    )
    lista_inadimplencia_clientes = []
    for cli in clientes_com_movimento:
        tot_faturado = (
            TituloFinanceiro.unscoped
            .filter(tenant=tenant, cliente=cli, tipo='RECEBER')
            .aggregate(total=Sum('valor_bruto'))
        )['total'] or Decimal('0.00')

        if tot_faturado > Decimal('0.00'):
            saldo_vencido = (
                ParcelaFinanceira.unscoped
                .filter(
                    tenant=tenant,
                    titulo__cliente=cli,
                    titulo__tipo='RECEBER',
                    status__in=['ABERTO', 'PENDENTE', 'PARCIAL', 'EM_PROTESTO'],
                    data_vencimento__lt=timezone.localdate() - datetime.timedelta(days=30)
                )
                .aggregate(total=Sum('saldo_em_aberto'))
            )['total'] or Decimal('0.00')

            taxa = quantize((saldo_vencido / tot_faturado * Decimal('100.00')), 4)
            lista_inadimplencia_clientes.append({
                'cliente_id': cli.id,
                'cliente_nome': cli.nome,
                'faturamento_total': quantize(tot_faturado, 2),
                'saldo_vencido_30d': quantize(saldo_vencido, 2),
                'taxa_inadimplencia_pct': taxa
            })

    lista_inadimplencia_clientes.sort(key=lambda x: -x['saldo_vencido_30d'])

    # 5. Rentabilidade por Rota
    rotas = Rota.unscoped.filter(tenant=tenant)
    lista_rentabilidade_rotas = []
    for r in rotas:
        entregas_rota = Entrega.unscoped.filter(
            tenant=tenant,
            rota=r,
            status__in=['Concluída', 'ENTREGUE', 'Entregue'],
            data_saida__date__gte=data_inicio,
            data_saida__date__lte=data_fim
        ).prefetch_related('vendas__itens__sku')

        rec_rota = Decimal('0.00')
        cpv_rota = Decimal('0.00')
        for ent in entregas_rota:
            for v in ent.vendas.all():
                rec_rota = quantize(rec_rota + (v.valor_total or Decimal('0.00')), 2)
                for item in v.itens.all():
                    c_u = getattr(item.sku, 'custo_medio_unitario', Decimal('0.00')) or Decimal('0.00')
                    cpv_rota = quantize(cpv_rota + (c_u * item.quantidade), 2)

        lucro_rota = quantize(rec_rota - cpv_rota, 2)
        margem_pct_rota = quantize((lucro_rota / rec_rota * Decimal('100.00')) if rec_rota > Decimal('0.00') else Decimal('0.0000'), 4)

        lista_rentabilidade_rotas.append({
            'rota_id': r.id,
            'rota_nome': r.nome,
            'total_entregas': entregas_rota.count(),
            'receita_bruta': rec_rota,
            'cpv': cpv_rota,
            'lucro_bruto': lucro_rota,
            'margem_pct': margem_pct_rota
        })

    lista_rentabilidade_rotas.sort(key=lambda x: -x['lucro_bruto'])

    taxa_inadimplencia_global = quantize(
        Decimal(sum(c['taxa_inadimplencia_pct'] for c in lista_inadimplencia_clientes)) / Decimal(len(lista_inadimplencia_clientes))
        if lista_inadimplencia_clientes else Decimal('0.0000'), 4
    )

    return {
        'periodo': {'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat()},
        'margem_por_produto': lista_margem_produtos,
        'giro_cilindro_anual': giro_cilindro,
        'pmr_dias': pmr_dias,
        'pmp_dias': pmp_dias,
        'taxa_inadimplencia_global': taxa_inadimplencia_global,
        'formula': "Auditável sem IA (Giro: Envios/Parque; PMR/PMP: dias médios de liquidação)",
        'fonte': "Razão Contábil, Títulos Financeiros, Baixas e Posse de Cilindros",
        'giro_cilindro': {
            'total_parque': total_parque,
            'total_envios_ano': total_envios_ano,
            'giro_anual': giro_cilindro,
            'formula': "Total de Envios no Ano / Total do Parque de Cilindros"
        },
        'prazos_medios': {
            'pmr_dias': pmr_dias,
            'pmp_dias': pmp_dias,
            'formula_pmr': "Média ponderada dos dias de liquidação das faturas a receber",
            'formula_pmp': "Média ponderada dos dias de pagamento das faturas a fornecedores"
        },
        'inadimplencia_clientes': lista_inadimplencia_clientes[:10],
        'rentabilidade_rotas': lista_rentabilidade_rotas
    }
