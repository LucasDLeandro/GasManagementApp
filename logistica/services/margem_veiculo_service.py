"""
Serviço Canônico de Margem de Contribuição por Veículo e TCO por Km/Parada (Sprint 10C - Tarefas 5 e 6 / Correção F-23).
Fórmulas estritamente auditáveis com validação rigorosa de odômetro (dados insuficientes quando ausente).
"""

import datetime
from decimal import Decimal
from typing import Optional, Union, Dict, Any, List

from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, Count

from core.guards import assert_modulo
from core.money import quantize
from financeiro.models import (
    PartidaContabil,
    PlanoContas,
    DepreciacaoMensal,
    ParametroGestaoTenant,
)
from logistica.models import (
    Veiculo,
    LeituraOdometro,
    Entrega,
    TabelaFreteInterno,
    AlocacaoMotoristaVeiculo,
    ApoliceVeiculo,
)


import calendar
from django.db.models import F

def calcular_margem_contribuicao_veiculo(
    *,
    tenant,
    veiculo_id: int,
    data_inicio: Union[str, datetime.date],
    data_fim: Union[str, datetime.date],
    politica: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calcula a Margem de Contribuição por Veículo (Sprint 10C - Tarefa 5).
    O Tenant escolhe politica_receita_veiculo:
    1. Contribuição de Frete: Frete Imputado - Custos Variáveis Diretos da Placa.
    2. Contribuição Comercial da Entrega: Receita Líquida Entregue - CPV - Custos Variáveis da Placa.
    Custos variáveis vêm do Razão contábil filtrados pela dimensão veiculo.
    """
    assert_modulo(tenant, 'logistica')
    assert_modulo(tenant, 'financeiro')

    if isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)
    if isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    veiculo = Veiculo.unscoped.get(tenant=tenant, id=veiculo_id)

    # 1. Política do Tenant
    if not politica:
        param, _ = ParametroGestaoTenant.unscoped.get_or_create(
            tenant=tenant,
            defaults={'politica_receita_veiculo': 'CONTRIBUICAO_COMERCIAL'}
        )
        politica = param.politica_receita_veiculo

    # 2. Custos Variáveis Diretos da Placa via Razão Contábil (dimensão veiculo)
    # Contas de custos variáveis operacionais: combustível, pneus, pedágios, manutenção corretiva
    partidas_var = (
        PartidaContabil.unscoped
        .filter(
            tenant=tenant,
            veiculo=veiculo,
            tipo_partida='DEBITO',
            lancamento__data_competencia__gte=data_inicio,
            lancamento__data_competencia__lte=data_fim
        )
        .select_related('conta_contabil')
    )

    custos_variaveis_total = Decimal('0.00')
    detalhes_custos_var = {}

    for p in partidas_var:
        cod = p.conta_contabil.codigo_estrutural
        # Contas de despesas operacionais da frota (5.1) ou custos de viagem
        if cod.startswith('5.1') or cod.startswith('4.1') or 'FROTA' in (p.conta_contabil.tipo_dre or ''):
            val = quantize(p.valor, 2)
            custos_variaveis_total = quantize(custos_variaveis_total + val, 2)
            c_nome = p.conta_contabil.nome
            detalhes_custos_var[c_nome] = quantize(detalhes_custos_var.get(c_nome, Decimal('0.00')) + val, 2)

    # 3. Entregas e Vendas Atendidas pelo Veículo no Período
    entregas = (
        Entrega.unscoped
        .filter(
            tenant=tenant,
            veiculo=veiculo,
            status__in=['Concluída', 'ENTREGUE', 'Entregue'],
            data_saida__date__gte=data_inicio,
            data_saida__date__lte=data_fim
        )
        .prefetch_related('vendas__itens__sku')
    )
    total_paradas = sum(e.vendas.count() for e in entregas) or entregas.count()

    # Quilometragem percorrida no período
    leituras = (
        LeituraOdometro.unscoped
        .filter(
            tenant=tenant,
            veiculo=veiculo,
            validada=True,
            data_hora__date__gte=data_inicio,
            data_hora__date__lte=data_fim
        )
        .order_by('data_hora')
    )
    km_rodados = Decimal('0.000')
    if leituras.count() >= 2:
        km_ini = leituras.first().km
        km_fim = leituras.last().km
        if km_fim >= km_ini:
            km_rodados = quantize(km_fim - km_ini, 3)

    # 4. Cálculo Conforme Política Selecionada
    if politica == 'CONTRIBUICAO_FRETE':
        # Frete imputado: destacado nas entregas ou tabela de frete interno
        frete_destacado = Decimal('0.00')
        for e in entregas:
            for v in e.vendas.all():
                if hasattr(v, 'valor_frete'):
                    frete_destacado = quantize(frete_destacado + (v.valor_frete or Decimal('0.00')), 2)

        if frete_destacado > Decimal('0.00'):
            frete_imputado = frete_destacado
            fonte_frete = "Frete destacado nas vendas entregues (Conta 3.1.4)"
        else:
            # Tabela de Frete Interno (por km ou por parada)
            tabela_frete = (
                TabelaFreteInterno.unscoped
                .filter(
                    tenant=tenant,
                    ativo=True,
                    vigencia_inicio__lte=data_fim
                )
                .filter(Q(veiculo=veiculo) | Q(veiculo__isnull=True))
                .order_by(F('veiculo').desc(nulls_last=True), '-vigencia_inicio')
                .first()
            )
            if tabela_frete:
                if tabela_frete.tipo == 'POR_KM':
                    frete_imputado = quantize(km_rodados * tabela_frete.valor, 2)
                    fonte_frete = f"Tabela Frete Interno R$ {tabela_frete.valor}/km * {km_rodados} km"
                else:
                    frete_imputado = quantize(Decimal(total_paradas) * tabela_frete.valor, 2)
                    fonte_frete = f"Tabela Frete Interno R$ {tabela_frete.valor}/parada * {total_paradas} paradas"
            else:
                frete_imputado = Decimal('0.00')
                fonte_frete = "Sem frete destacado ou tabela interna parametrizada"

        margem_contribuicao = quantize(frete_imputado - custos_variaveis_total, 2)
        margem_pct = quantize((margem_contribuicao / frete_imputado * Decimal('100.00')) if frete_imputado > Decimal('0.00') else Decimal('0.0000'), 4)

        return {
            'veiculo': {'id': veiculo.id, 'placa': veiculo.placa, 'modelo': veiculo.modelo},
            'periodo': {'inicio': data_inicio.isoformat(), 'fim': data_fim.isoformat()},
            'politica': 'CONTRIBUICAO_FRETE',
            'formula': "Frete Imputado - Custos Variáveis Diretos da Placa",
            'receita_bruta': frete_imputado,
            'frete_imputado': frete_imputado,
            'fonte_frete': fonte_frete,
            'custos_variaveis_total': custos_variaveis_total,
            'custos_variaveis_diretos': custos_variaveis_total,
            'detalhes_custos_variaveis': detalhes_custos_var,
            'margem_contribuicao': margem_contribuicao,
            'margem_contribuicao_pct': margem_pct,
            'total_paradas': total_paradas,
            'km_rodados': km_rodados
        }

    else:
        # CONTRIBUICAO_COMERCIAL: Receita Líquida Entregue - CPV - Custos Variáveis
        receita_liquida_entregue = Decimal('0.00')
        cpv_entregue = Decimal('0.00')

        for e in entregas:
            for v in e.vendas.all():
                v_tot = quantize(v.valor_total or Decimal('0.00'), 2)
                receita_liquida_entregue = quantize(receita_liquida_entregue + v_tot, 2)
                for item in v.itens.all():
                    custo_unit = getattr(item.sku, 'custo_medio_unitario', Decimal('0.00')) or Decimal('0.00')
                    cpv_item = quantize(custo_unit * item.quantidade, 2)
                    cpv_entregue = quantize(cpv_entregue + cpv_item, 2)

        lucro_bruto_comercial = quantize(receita_liquida_entregue - cpv_entregue, 2)
        margem_contribuicao = quantize(lucro_bruto_comercial - custos_variaveis_total, 2)
        margem_pct = quantize((margem_contribuicao / receita_liquida_entregue * Decimal('100.00')) if receita_liquida_entregue > Decimal('0.00') else Decimal('0.0000'), 4)

        return {
            'veiculo': {'id': veiculo.id, 'placa': veiculo.placa, 'modelo': veiculo.modelo},
            'periodo': {'inicio': data_inicio.isoformat(), 'fim': data_fim.isoformat()},
            'politica': 'CONTRIBUICAO_COMERCIAL',
            'formula': "Receita Líquida das Vendas Entregues - CPV - Custos Variáveis Diretos da Placa",
            'receita_bruta': receita_liquida_entregue,
            'receita_liquida_entregue': receita_liquida_entregue,
            'cpv_entregue': cpv_entregue,
            'lucro_bruto_comercial': lucro_bruto_comercial,
            'custos_variaveis_total': custos_variaveis_total,
            'custos_variaveis_diretos': custos_variaveis_total,
            'detalhes_custos_variaveis': detalhes_custos_var,
            'margem_contribuicao': margem_contribuicao,
            'margem_contribuicao_pct': margem_pct,
            'total_paradas': total_paradas,
            'km_rodados': km_rodados
        }


def calcular_tco_veiculo(
    *,
    tenant,
    veiculo_id: int,
    data_inicio: Optional[Union[str, datetime.date]] = None,
    data_fim: Optional[Union[str, datetime.date]] = None,
    ano: Optional[int] = None,
    mes: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calcula o Custo Total de Propriedade (TCO) por Km e por Parada (Sprint 10C - Tarefa 6).
    Fórmula: (Custos Variáveis + Custos Fixos Alocados) / Km Rodados (e por parada).
    Fixos alocados: Depreciação do ledger, seguro, IPVA/12, licenciamento/12, equipe (motorista/ajudante).
    REGRA CRÍTICA: Veículo sem odômetro validado no mês devolve 'dados insuficientes', nunca inventado.
    """
    assert_modulo(tenant, 'logistica')
    assert_modulo(tenant, 'financeiro')

    if data_inicio is None and ano and mes:
        data_inicio = datetime.date(ano, mes, 1)
        _, last_day = calendar.monthrange(ano, mes)
        data_fim = datetime.date(ano, mes, last_day)

    if isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)
    if isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    veiculo = Veiculo.unscoped.get(tenant=tenant, id=veiculo_id)

    # 1. Validação Obrigatória de Odômetro
    leituras = (
        LeituraOdometro.unscoped
        .filter(
            tenant=tenant,
            veiculo=veiculo,
            validada=True,
            data_hora__date__gte=data_inicio,
            data_hora__date__lte=data_fim
        )
        .order_by('data_hora')
    )

    if leituras.count() < 2:
        return {
            'veiculo': {'id': veiculo.id, 'placa': veiculo.placa, 'modelo': veiculo.modelo},
            'periodo': {'inicio': data_inicio.isoformat(), 'fim': data_fim.isoformat()},
            'status': 'DADOS_INSUFICIENTES',
            'mensagem': "dados insuficientes",
            'motivo': "O veículo não possui leituras de odômetro validadas no período para aferição de quilometragem percorrida.",
            'km_rodados': None,
            'tco_por_km': None,
            'tco_por_parada': None,
            'custos_totais': None
        }

    km_ini = leituras.first().km
    km_fim = leituras.last().km
    if km_fim <= km_ini:
        return {
            'veiculo': {'id': veiculo.id, 'placa': veiculo.placa, 'modelo': veiculo.modelo},
            'periodo': {'inicio': data_inicio.isoformat(), 'fim': data_fim.isoformat()},
            'status': 'DADOS_INSUFICIENTES',
            'mensagem': "dados insuficientes",
            'motivo': f"Diferença de quilometragem nula ou inconsistente ({km_fim} <= {km_ini}).",
            'km_rodados': None,
            'tco_por_km': None,
            'tco_por_parada': None,
            'custos_totais': None
        }

    km_rodados = quantize(km_fim - km_ini, 3)

    # 2. Custos Variáveis no Período (combustível, pneus, manutenção corretiva, pedágio)
    partidas_var = (
        PartidaContabil.unscoped
        .filter(
            tenant=tenant,
            veiculo=veiculo,
            tipo_partida='DEBITO',
            lancamento__data_competencia__gte=data_inicio,
            lancamento__data_competencia__lte=data_fim
        )
        .select_related('conta_contabil')
    )
    custos_variaveis = Decimal('0.00')
    detalhes_var = {}
    for p in partidas_var:
        cod = p.conta_contabil.codigo_estrutural
        if cod.startswith('5.1') or cod.startswith('4.1'):
            val = quantize(p.valor, 2)
            custos_variaveis = quantize(custos_variaveis + val, 2)
            detalhes_var[p.conta_contabil.nome] = quantize(detalhes_var.get(p.conta_contabil.nome, Decimal('0.00')) + val, 2)

    # 3. Custos Fixos Alocados
    # A) Depreciação do Veículo via Ledger DepreciacaoMensal
    deprec_veiculo = Decimal('0.00')
    if veiculo.ativo_imobilizado_id:
        ano_meses = []
        cur = data_inicio
        while cur <= data_fim:
            ano_meses.append(cur.strftime('%Y-%m'))
            cur = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

        deprec_ledger = (
            DepreciacaoMensal.unscoped
            .filter(
                tenant=tenant,
                tipo_alvo='ATIVO_IMOBILIZADO',
                alvo_id=veiculo.ativo_imobilizado_id,
                periodo__in=ano_meses
            )
            .aggregate(total=Sum('quota'))
        )
        deprec_veiculo = quantize(deprec_ledger['total'] or Decimal('0.00'), 2)

    # B) Seguro e Proteção Veicular
    seguro_alocado = Decimal('0.00')
    apolice_v = ApoliceVeiculo.unscoped.filter(tenant=tenant, veiculo=veiculo).select_related('apolice').first()
    if apolice_v and apolice_v.apolice and getattr(apolice_v.apolice, 'premio_total', None):
        meses_periodo = max(1, (data_fim.year - data_inicio.year) * 12 + data_fim.month - data_inicio.month + 1)
        seguro_alocado = quantize(apolice_v.apolice.premio_total * Decimal(meses_periodo) / Decimal('12.00'), 2)

    # C) IPVA e Licenciamento (rateados por 12 meses)
    ipva_alocado = Decimal('0.00')
    licenciamento_alocado = Decimal('0.00')
    if hasattr(veiculo, 'ipva_anual') and veiculo.ipva_anual:
        ipva_alocado = quantize(veiculo.ipva_anual / Decimal('12.00'), 2)
    if hasattr(veiculo, 'licenciamento_anual') and veiculo.licenciamento_anual:
        licenciamento_alocado = quantize(veiculo.licenciamento_anual / Decimal('12.00'), 2)

    # D) Equipe (Motorista e Ajudante) via AlocacaoMotoristaVeiculo
    alocacoes = (
        AlocacaoMotoristaVeiculo.unscoped
        .filter(
            tenant=tenant,
            veiculo=veiculo,
            data_inicio__lte=data_fim,
            data_fim__gte=data_inicio
        )
    )
    custo_equipe_total = Decimal('0.00')
    for al in alocacoes:
        custo_equipe_total = quantize(custo_equipe_total + (al.custo_diaria_total * al.dias_alocados), 2)

    custos_fixos_total = quantize(
        deprec_veiculo + seguro_alocado + ipva_alocado + licenciamento_alocado + custo_equipe_total,
        2
    )

    custos_totais = quantize(custos_variaveis + custos_fixos_total, 2)

    # 4. Total de Paradas / Entregas Realizadas
    total_paradas = Entrega.unscoped.filter(
        tenant=tenant,
        veiculo=veiculo,
        status__in=['Concluída', 'ENTREGUE', 'Entregue'],
        data_saida__date__gte=data_inicio,
        data_saida__date__lte=data_fim
    ).count()

    tco_por_km = quantize(custos_totais / km_rodados, 2)
    tco_por_parada = quantize(custos_totais / Decimal(total_paradas), 2) if total_paradas > 0 else None

    return {
        'veiculo': {'id': veiculo.id, 'placa': veiculo.placa, 'modelo': veiculo.modelo},
        'periodo': {'inicio': data_inicio.isoformat(), 'fim': data_fim.isoformat()},
        'status': 'SUCESSO',
        'formula': "(Custos Variáveis + Custos Fixos Alocados) / Km Rodados",
        'km_rodados': km_rodados,
        'total_paradas': total_paradas,
        'custos_variaveis': custos_variaveis,
        'detalhes_custos_variaveis': detalhes_var,
        'custos_fixos_alocados': custos_fixos_total,
        'detalhes_custos_fixos': {
            'depreciacao_veiculo': deprec_veiculo,
            'seguro': seguro_alocado,
            'ipva_rateado': ipva_alocado,
            'licenciamento_rateado': licenciamento_alocado,
            'equipe_motorista_ajudante': custo_equipe_total,
            'total_fixo': custos_fixos_total
        },
        'custo_total': custos_totais,
        'custos_totais': custos_totais,
        'tco_por_km': tco_por_km,
        'tco_por_parada': tco_por_parada
    }
