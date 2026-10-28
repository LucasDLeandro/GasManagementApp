"""
Serviço de Backtest Histórico de Alertas Preditivos (Sprint 12C - Tarefa 7).

Regras de negócio:
- Mede no histórico real quantos alertas teriam resultado em recompra dentro de N dias (horizonte).
- Realiza simulação temporal estrita (walk-forward): a cada ponto temporal t, calcula μ e σ
  utilizando unicamente compras anteriores a t (sem look-ahead bias).
- Verifica se após o disparo simulado ocorreu nova compra faturada dentro do prazo de N dias.
- Exibe os números brutos e reais como estão, sem metas inventadas ou distorções.
"""
import datetime
from typing import Any, Dict, List, Optional
from django.utils import timezone

from core.guards import assert_modulo
from analytics.selectors.recompra import historico_recompra, obter_pares_cliente_gas_ativos
from analytics.services.estatistica import (
    calcular_mediana,
    calcular_mad,
    filtrar_outliers_mad,
    calcular_media_e_desvio,
)


def executar_backtest(
    tenant,
    dias_horizonte: int = 30,
    k: float = 2.0,
    data_limite_simulacao: Optional[datetime.date] = None
) -> Dict[str, Any]:
    """
    Executa a simulação histórica retrospectiva de alertas de recompra atrasada.

    Para cada par (cliente, gas):
    - Percorre a série temporal de compras [d_1, d_2, ..., d_n];
    - A partir da 4ª compra (i >= 4), simula a data em que um alerta dispararia: d_i + (μ + k·σ);
    - Checa se a próxima compra d_{i+1} ocorreu dentro de (data_disparo + dias_horizonte);
    - Contabiliza os números brutos de alertas simulados e recompras observadas.
    """
    assert_modulo(tenant, 'analytics')

    hoje = data_limite_simulacao or timezone.now().date()
    k_float = float(k)
    pares = obter_pares_cliente_gas_ativos(tenant)

    total_alertas_simulados = 0
    recompras_no_horizonte = 0
    sem_recompra_no_horizonte = 0

    detalhes_simulacao: List[Dict[str, Any]] = []
    por_gas_map: Dict[str, Dict[str, int]] = {}

    for cliente, gas in pares:
        historico = historico_recompra(cliente=cliente, gas=gas, tenant=tenant)
        if not historico.get('elegivel'):
            continue

        compras = [d for d in historico['compras'] if d <= hoje]
        n_compras = len(compras)
        if n_compras < 4:
            continue

        nome_gas = gas.nome
        if nome_gas not in por_gas_map:
            por_gas_map[nome_gas] = {'total_alertas': 0, 'recompras_horizonte': 0}

        # Simulação walk-forward a partir da 4ª compra
        for i in range(3, n_compras):
            subserie_compras = compras[:i]
            d_atual = subserie_compras[-1]

            intervalos_passados = [
                (subserie_compras[j + 1] - subserie_compras[j]).days
                for j in range(len(subserie_compras) - 1)
            ]

            filtrados, _ = filtrar_outliers_mad(intervalos_passados, threshold=3.0)
            mu, sigma = calcular_media_e_desvio(filtrados)

            limite_alerta_dias = int(round(mu + (k_float * sigma)))
            if limite_alerta_dias <= 0:
                limite_alerta_dias = 1

            data_disparo_alerta = d_atual + datetime.timedelta(days=limite_alerta_dias)

            # Só avalia se a data de disparo for anterior ao horizonte máximo de análise
            if data_disparo_alerta + datetime.timedelta(days=dias_horizonte) > hoje:
                continue

            total_alertas_simulados += 1
            por_gas_map[nome_gas]['total_alertas'] += 1

            # Checa se houve compra no horizonte
            proxima_compra = compras[i] if i < n_compras else None
            houve_recompra = False
            dias_ate_proxima = None

            if proxima_compra and proxima_compra >= data_disparo_alerta:
                dias_ate_proxima = (proxima_compra - data_disparo_alerta).days
                if dias_ate_proxima <= dias_horizonte:
                    houve_recompra = True

            if houve_recompra:
                recompras_no_horizonte += 1
                por_gas_map[nome_gas]['recompras_horizonte'] += 1
            else:
                sem_recompra_no_horizonte += 1

            detalhes_simulacao.append({
                'cliente_id': cliente.id,
                'cliente_nome': cliente.nome,
                'gas': nome_gas,
                'data_ultima_compra': d_atual.isoformat(),
                'limite_alerta_dias': limite_alerta_dias,
                'data_disparo_alerta': data_disparo_alerta.isoformat(),
                'proxima_compra': proxima_compra.isoformat() if proxima_compra else None,
                'dias_ate_proxima': dias_ate_proxima,
                'recompra_dentro_horizonte': houve_recompra,
            })

    taxa_assertividade_pct = (
        round((recompras_no_horizonte / float(total_alertas_simulados) * 100), 2)
        if total_alertas_simulados > 0 else 0.0
    )

    resumo_por_gas = []
    for g_nome, g_dados in por_gas_map.items():
        tot_g = g_dados['total_alertas']
        rec_g = g_dados['recompras_horizonte']
        tx_g = round((rec_g / float(tot_g) * 100), 2) if tot_g > 0 else 0.0
        resumo_por_gas.append({
            'gas': g_nome,
            'total_alertas_simulados': tot_g,
            'recompras_no_horizonte': rec_g,
            'taxa_conversao_pct': tx_g
        })

    return {
        'horizonte_dias': dias_horizonte,
        'dias_horizonte': dias_horizonte,
        'parametro_k': k_float,
        'k': k_float,
        'data_referencia': hoje.isoformat(),
        'total_alertas_simulados': total_alertas_simulados,
        'recompras_no_horizonte': recompras_no_horizonte,
        'total_convertidos_no_prazo': recompras_no_horizonte,
        'sem_recompra_no_horizonte': sem_recompra_no_horizonte,
        'taxa_assertividade_real_pct': taxa_assertividade_pct,
        'taxa_conversao_percentual': taxa_assertividade_pct,
        'explicacao': f"No período histórico simulado, foram gerados {total_alertas_simulados} alertas retrospectivos, dos quais {recompras_no_horizonte} tiveram nova compra em até {dias_horizonte} dias ({taxa_assertividade_pct}% de conversão real).",
        'resumo_por_gas': resumo_por_gas,
        'amostra_detalhes': detalhes_simulacao[:50],
    }
