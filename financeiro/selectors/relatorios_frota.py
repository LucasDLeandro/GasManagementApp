from decimal import Decimal
from django.db.models import Sum, Count, Q, Min, Max
from django.utils import timezone
from core.money import quantize
from financeiro.models import (
    PreLancamentoDespesaCampo,
    FechamentoCaixaRota,
    QuebraCaixa,
)
from logistica.models import Veiculo, LeituraOdometro


def relatorio_consumo_veiculos(tenant, data_inicio=None, data_fim=None) -> list[dict]:
    """
    Relatório de consumo médio km/L por veículo (Sprint 9C - Tarefa 9).
    Calcula quilometragem percorrida, volume total de combustível e variação frente à referência.
    """
    veiculos = Veiculo.objects.filter(tenant=tenant).order_by('placa')

    qs_abast = PreLancamentoDespesaCampo.objects.filter(
        tenant=tenant,
        tipo='ABASTECIMENTO',
        status__in=['APROVADO', 'CONSOLIDADO', 'PENDENTE_CONFERENCIA']
    )
    if data_inicio:
        qs_abast = qs_abast.filter(data_hora__date__gte=data_inicio)
    if data_fim:
        qs_abast = qs_abast.filter(data_hora__date__lte=data_fim)

    resultado = []
    for veic in veiculos:
        abasts_v = qs_abast.filter(veiculo=veic)
        tot_litros = sum(a.litros for a in abasts_v if a.litros) or Decimal('0.000')
        tot_valor = sum(a.valor_informado for a in abasts_v) or Decimal('0.00')

        # Odômetros no período
        qs_odo = LeituraOdometro.objects.filter(tenant=tenant, veiculo=veic, validada=True)
        if data_inicio:
            qs_odo = qs_odo.filter(data_hora__date__gte=data_inicio)
        if data_fim:
            qs_odo = qs_odo.filter(data_hora__date__lte=data_fim)

        odo_min = qs_odo.aggregate(Min('km'))['km__min']
        odo_max = qs_odo.aggregate(Max('km'))['km__max']

        km_rodado = Decimal('0.000')
        if odo_min is not None and odo_max is not None and odo_max > odo_min:
            km_rodado = quantize(odo_max - odo_min, 3)

        consumo_real = Decimal('0.000')
        if tot_litros > Decimal('0.000') and km_rodado > Decimal('0.000'):
            consumo_real = quantize(km_rodado / tot_litros, 3)

        ref_kml = veic.consumo_referencia_kml or veic.consumo_referencia_km_l or Decimal('0.000')

        variacao_pct = Decimal('0.0000')
        if ref_kml > Decimal('0.000') and consumo_real > Decimal('0.000'):
            variacao_pct = quantize(((consumo_real - ref_kml) / ref_kml) * Decimal('100.0000'), 4)

        resultado.append({
            'veiculo_id': veic.id,
            'placa': veic.placa,
            'modelo': veic.modelo,
            'tipo_combustivel': veic.tipo_combustivel or veic.combustivel_padrao,
            'total_litros': quantize(tot_litros, 3),
            'litros_consumidos': quantize(tot_litros, 3),
            'total_valor': quantize(tot_valor, 2),
            'km_rodado': km_rodado,
            'km_rodados': km_rodado,
            'consumo_real_kml': consumo_real,
            'km_por_litro_real': consumo_real,
            'consumo_referencia_kml': quantize(ref_kml, 3),
            'variacao_percentual': variacao_pct
        })

    return resultado


def ranking_motoristas_anomalias(tenant, data_inicio=None, data_fim=None) -> list[dict]:
    """
    Ranking de motoristas por anomalias e índice de conformidade (Sprint 9C - Tarefa 9).
    """
    qs = PreLancamentoDespesaCampo.objects.filter(tenant=tenant)
    if data_inicio:
        qs = qs.filter(data_hora__date__gte=data_inicio)
    if data_fim:
        qs = qs.filter(data_hora__date__lte=data_fim)

    motoristas_map = {}
    for d in qs.select_related('motorista'):
        m_id = d.motorista_id
        if m_id not in motoristas_map:
            motoristas_map[m_id] = {
                'motorista_id': m_id,
                'nome': d.motorista.get_full_name() or d.motorista.username,
                'username': d.motorista.username,
                'total_lancamentos': 0,
                'total_com_alerta': 0,
                'total_alertas': 0,
                'anomalias_por_codigo': {}
            }

        rec = motoristas_map[m_id]
        rec['total_lancamentos'] += 1
        if d.alerta_auditoria:
            rec['total_com_alerta'] += 1
            rec['total_alertas'] += 1

        for cod in (d.motivos_alerta_json or []):
            rec['anomalias_por_codigo'][cod] = rec['anomalias_por_codigo'].get(cod, 0) + 1

    ranking = []
    for rec in motoristas_map.values():
        total = rec['total_lancamentos']
        com_alerta = rec['total_com_alerta']
        taxa_conformidade = quantize(
            Decimal('100.0000') - (Decimal(str(com_alerta)) / Decimal(str(total)) * Decimal('100.0000')),
            4
        ) if total > 0 else Decimal('100.0000')

        rec['taxa_conformidade_pct'] = taxa_conformidade
        ranking.append(rec)

    # Ordena pelo maior número de alertas / menor conformidade
    ranking.sort(key=lambda x: (x['total_com_alerta'], -float(x['taxa_conformidade_pct'])), reverse=True)
    return ranking


def relatorio_quebras_caixa(tenant, data_inicio=None, data_fim=None) -> list[dict]:
    """
    Relatório consolidado de quebras de caixa por motorista (Sprint 9C - Tarefa 9).
    """
    qs = QuebraCaixa.objects.filter(tenant=tenant).select_related('motorista', 'fechamento')
    if data_inicio:
        qs = qs.filter(fechamento__data__gte=data_inicio)
    if data_fim:
        qs = qs.filter(fechamento__data__lte=data_fim)

    quebras_map = {}
    for q in qs:
        m_id = q.motorista_id
        if m_id not in quebras_map:
            quebras_map[m_id] = {
                'motorista_id': m_id,
                'nome': q.motorista.get_full_name() or q.motorista.username,
                'username': q.motorista.username,
                'total_ocorrencias': 0,
                'sobras_acumuladas': Decimal('0.00'),
                'faltas_acumuladas': Decimal('0.00'),
                'saldo_liquido_quebras': Decimal('0.00')
            }

        rec = quebras_map[m_id]
        rec['total_ocorrencias'] += 1
        if q.tipo == 'SOBRA':
            rec['sobras_acumuladas'] += q.valor
        else:
            rec['faltas_acumuladas'] += q.valor

    relatorio = []
    for rec in quebras_map.values():
        rec['sobras_acumuladas'] = quantize(rec['sobras_acumuladas'], 2)
        rec['faltas_acumuladas'] = quantize(rec['faltas_acumuladas'], 2)
        # Saldo líquido = Sobras - Faltas
        rec['saldo_liquido_quebras'] = quantize(rec['sobras_acumuladas'] - rec['faltas_acumuladas'], 2)
        relatorio.append(rec)

    relatorio.sort(key=lambda x: x['faltas_acumuladas'], reverse=True)
    return relatorio
