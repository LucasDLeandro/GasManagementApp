"""
Serviço de Métricas do Funil Comercial e Calibragem de K (Sprint 12C - Tarefa 6).

Calcula:
- Volume de alertas por status (NOVO, EM_CONTATO, CONVERTIDO, DESCARTADO);
- Taxa de conversão por tipo de oportunidade comercial;
- Taxa de conversão estratificada por valor de k (alimenta a calibragem do limiar estatístico).
"""
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from django.db.models import Count, Q

from core.guards import assert_modulo
from analytics.models import AlertaOportunidadeComercial


def calcular_metricas_funil(
    tenant,
    data_inicio: Optional[datetime.date] = None,
    data_fim: Optional[datetime.date] = None
) -> Dict[str, Any]:
    """
    Retorna métricas consolidadas do funil comercial de oportunidades e calibragem de k.
    """
    assert_modulo(tenant, 'analytics')

    qs = AlertaOportunidadeComercial.unscoped.filter(tenant=tenant)
    if data_inicio:
        qs = qs.filter(criado_em__date__gte=data_inicio)
    if data_fim:
        qs = qs.filter(criado_em__date__lte=data_fim)

    total_alertas = qs.count()

    status_counts = qs.aggregate(
        novos=Count('id', filter=Q(status=AlertaOportunidadeComercial.STATUS_NOVO)),
        em_contato=Count('id', filter=Q(status=AlertaOportunidadeComercial.STATUS_EM_CONTATO)),
        convertidos=Count('id', filter=Q(status=AlertaOportunidadeComercial.STATUS_CONVERTIDO)),
        descartados=Count('id', filter=Q(status=AlertaOportunidadeComercial.STATUS_DESCARTADO)),
    )

    novos = status_counts['novos'] or 0
    em_contato = status_counts['em_contato'] or 0
    convertidos = status_counts['convertidos'] or 0
    descartados = status_counts['descartados'] or 0
    resolvidos = convertidos + descartados

    taxa_conversao_global = round((convertidos / float(resolvidos) * 100), 2) if resolvidos > 0 else 0.0

    # 1. Taxa de conversão por tipo de alerta
    tipos_metricas = {}
    for cod_tipo, rotulo_tipo in AlertaOportunidadeComercial.TIPO_CHOICES:
        qs_tipo = qs.filter(tipo=cod_tipo)
        total_t = qs_tipo.count()
        conv_t = qs_tipo.filter(status=AlertaOportunidadeComercial.STATUS_CONVERTIDO).count()
        desc_t = qs_tipo.filter(status=AlertaOportunidadeComercial.STATUS_DESCARTADO).count()
        res_t = conv_t + desc_t
        taxa_t = round((conv_t / float(res_t) * 100), 2) if res_t > 0 else 0.0

        tipos_metricas[cod_tipo] = {
            'tipo': cod_tipo,
            'rotulo': rotulo_tipo,
            'total_alertas': total_t,
            'convertidos': conv_t,
            'descartados': desc_t,
            'em_aberto': total_t - res_t,
            'taxa_conversao_pct': taxa_t
        }

    # 2. Calibragem de k: conversão por faixa de k em evidencia_json
    faixas_k = {
        'k_baixo (< 1.8)': {'total': 0, 'convertidos': 0, 'descartados': 0},
        'k_padrao (1.8 a 2.2)': {'total': 0, 'convertidos': 0, 'descartados': 0},
        'k_alto (> 2.2)': {'total': 0, 'convertidos': 0, 'descartados': 0},
    }

    # Percorre alertas de recompra/churn para tabular por k
    alertas_com_k = qs.filter(
        tipo__in=[
            AlertaOportunidadeComercial.TIPO_RECOMPRA_ATRASADA,
            AlertaOportunidadeComercial.TIPO_CHURN_RISCO
        ]
    ).only('evidencia_json', 'status')

    for a in alertas_com_k:
        k_val = a.evidencia_json.get('k') if 'k' in a.evidencia_json else a.evidencia_json.get('k_parametro')
        if k_val is None:
            continue
        try:
            k_f = float(k_val)
        except (ValueError, TypeError):
            continue

        if k_f < 1.8:
            fx = 'k_baixo (< 1.8)'
        elif k_f <= 2.2:
            fx = 'k_padrao (1.8 a 2.2)'
        else:
            fx = 'k_alto (> 2.2)'

        faixas_k[fx]['total'] += 1
        if a.status == AlertaOportunidadeComercial.STATUS_CONVERTIDO:
            faixas_k[fx]['convertidos'] += 1
        elif a.status == AlertaOportunidadeComercial.STATUS_DESCARTADO:
            faixas_k[fx]['descartados'] += 1

    calibragem_k_resumo = []
    for nome_faixa, dados_fx in faixas_k.items():
        res_fx = dados_fx['convertidos'] + dados_fx['descartados']
        tx_fx = round((dados_fx['convertidos'] / float(res_fx) * 100), 2) if res_fx > 0 else 0.0
        calibragem_k_resumo.append({
            'faixa_k': nome_faixa,
            'total_alertas': dados_fx['total'],
            'convertidos': dados_fx['convertidos'],
            'descartados': dados_fx['descartados'],
            'taxa_conversao_pct': tx_fx
        })

    totais_dict = {
        'total_alertas': total_alertas,
        'novos': novos,
        'em_contato': em_contato,
        'convertidos': convertidos,
        'descartados': descartados,
        'resolvidos': resolvidos,
        'taxa_conversao_global': Decimal(str(taxa_conversao_global)),
    }

    return {
        'totais': totais_dict,
        'total_alertas': total_alertas,
        'novos': novos,
        'em_contato': em_contato,
        'convertidos': convertidos,
        'descartados': descartados,
        'resolvidos': resolvidos,
        'taxa_conversao_global_pct': taxa_conversao_global,
        'por_tipo': tipos_metricas,
        'calibragem_k': calibragem_k_resumo,
    }
