"""
Serviço de Previsão Estatística de Recompra e Risco de Churn (Sprint 12C - Tarefa 1 e 2).

Regras de negócio:
- Utiliza histórico de compras faturadas via historico_recompra(cliente, gas).
- Exige no mínimo 4 compras faturadas do gás (sem previsão para menos de 4).
- Calcula intervalos entre compras consecutivas.
- Remove outliers pelo Modified Z-score (mediana e MAD).
- Calcula média (μ) e desvio padrão amostral (σ).
- Dispara alerta quando: dias_desde_a_ultima_compra > μ + k·σ (k padrão: 2.0).
- Fornece evidência completa e auditável em evidencia_json.
"""
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from django.utils import timezone

from core.money import quantize
from clientes.models import Cliente
from produtos.models import GasQuimico
from analytics.selectors.recompra import historico_recompra
from analytics.services.estatistica import (
    calcular_mediana,
    calcular_mad,
    filtrar_outliers_mad,
    calcular_media_e_desvio,
)


def avaliar_recompra_cliente_gas(
    cliente: Cliente,
    gas: GasQuimico,
    data_ref: Optional[datetime.date] = None,
    k: float = 2.0,
    tenant=None
) -> Optional[Dict[str, Any]]:
    """
    Avalia se o cliente está com a recompra atrasada ou em risco de churn para o gás especificado.
    Retorna None se o cliente não tiver dados suficientes (< 4 compras) ou se o intervalo estiver em dia.
    """
    hoje = data_ref or timezone.now().date()
    historico = historico_recompra(cliente=cliente, gas=gas, tenant=tenant)

    if not historico.get('elegivel'):
        return None

    compras: List[datetime.date] = historico['compras']
    n_compras = len(compras)
    if n_compras < 4:
        return None

    # 1. Calcula intervalos entre compras consecutivas (em dias)
    intervalos_brutos: List[int] = [
        (compras[i + 1] - compras[i]).days
        for i in range(n_compras - 1)
    ]

    # 2. Remoção de outliers por mediana e MAD
    mediana_bruta = calcular_mediana(intervalos_brutos)
    mad_bruto = calcular_mad(intervalos_brutos, mediana_bruta)
    intervalos_filtrados, outliers_removidos = filtrar_outliers_mad(intervalos_brutos, threshold=3.0)

    # 3. Média e desvio padrão sobre a série filtrada
    mu, sigma = calcular_media_e_desvio(intervalos_filtrados)

    # 4. Cálculo do limiar e verificação de atraso
    k_float = float(k)
    limite_alerta = round(mu + (k_float * sigma), 2)

    ultima_compra = compras[-1]
    dias_desde_ultima = max(0, (hoje - ultima_compra).days)

    if dias_desde_ultima <= limite_alerta:
        # Recompra está dentro da tolerância esperada: sem alerta
        return None

    # 5. Cálculo do Score explicável (z-score padronizado)
    atraso_dias = round(dias_desde_ultima - limite_alerta, 2)
    if sigma > 0:
        score_z = round((dias_desde_ultima - mu) / sigma, 4)
    else:
        # Quando desvio é zero (série perfeitamente regular)
        score_z = round(1.0 + (atraso_dias / max(1.0, mu)), 4)

    score_decimal = quantize(Decimal(str(max(0.0, score_z))), 4)

    # Define o tipo principal de alerta
    # Se o atraso for extremo (> 3 * sigma ou dobro do limite), classifica como CHURN_RISCO
    if dias_desde_ultima > (mu + 3.5 * sigma) and dias_desde_ultima >= 30:
        tipo_alerta = 'CHURN_RISCO'
        rotulo_tipo = "Risco de Churn"
    else:
        tipo_alerta = 'RECOMPRA_ATRASADA'
        rotulo_tipo = "Recompra Atrasada"

    explicacao = (
        f"O cliente {cliente.nome} costuma recomprar {gas.nome} a cada {mu:.1f} ± {sigma:.1f} dias "
        f"(limite parametrizado de alerta para k={k_float:.1f}: {limite_alerta:.1f} dias). "
        f"A última compra ocorreu há {dias_desde_ultima} dias ({ultima_compra.strftime('%d/%m/%Y')}), "
        f"com atraso estatístico de {atraso_dias:.1f} dias além do esperado (score Z={score_z:.2f})."
    )

    evidencia_json = {
        'cliente_id': cliente.id,
        'cliente_nome': cliente.nome,
        'gas_id': gas.id,
        'gas_nome': gas.nome,
        'data_referencia': hoje.isoformat(),
        'total_compras_faturadas': n_compras,
        'total_compras_historicas': n_compras,
        'datas_compras': [d.isoformat() for d in compras],
        'intervalos_brutos_dias': intervalos_brutos,
        'mediana_dias': mediana_bruta,
        'mad_dias': mad_bruto,
        'outliers_removidos_dias': outliers_removidos,
        'intervalos_filtrados_dias': intervalos_filtrados,
        'media_mu_dias': mu,
        'desvio_sigma_dias': sigma,
        'mu': mu,
        'sigma': sigma,
        'k': k_float,
        'k_parametro': k_float,
        'limite_alerta': limite_alerta,
        'limite_alerta_dias': limite_alerta,
        'data_ultima_compra': ultima_compra.isoformat(),
        'dias_desde_ultima_compra': dias_desde_ultima,
        'dias_em_atraso': atraso_dias,
        'score_z': float(score_decimal),
        'explicacao': explicacao
    }

    return {
        'cliente': cliente,
        'gas': gas,
        'tipo': tipo_alerta,
        'score': score_decimal,
        'data_ref': hoje,
        'dias_desde_ultima': dias_desde_ultima,
        'evidencia_json': evidencia_json,
        'explicacao': explicacao
    }
