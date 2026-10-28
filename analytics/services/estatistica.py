"""
Módulo de Estatística Descritiva e Detecção de Outliers (Sprint 12C - Tarefa 2).

Implementa:
- Mediana e MAD (Median Absolute Deviation);
- Remoção robusta de outliers por Modified Z-score (Iglewicz & Hoaglin);
- Média aritmética (μ) e desvio padrão amostral (σ);
- Totalmente explicável e determinístico (sem heurísticas ocultas ou aprendizado de máquina).
"""
import math
from typing import List, Tuple, Union
from decimal import Decimal


def calcular_mediana(valores: List[Union[int, float, Decimal]]) -> float:
    """Calcula a mediana de uma lista de valores numéricos."""
    if not valores:
        return 0.0
    ordenados = sorted([float(v) for v in valores])
    n = len(ordenados)
    meio = n // 2
    if n % 2 == 1:
        return float(ordenados[meio])
    else:
        return float((ordenados[meio - 1] + ordenados[meio]) / 2.0)


def calcular_mad(
    valores: List[Union[int, float, Decimal]],
    mediana: float = None
) -> float:
    """
    Calcula a Mediana dos Desvios Absolutos (MAD):
    MAD = median(|x_i - median(X)|)
    """
    if not valores:
        return 0.0
    if mediana is None:
        mediana = calcular_mediana(valores)
    desvios = [abs(float(v) - mediana) for v in valores]
    return calcular_mediana(desvios)


def filtrar_outliers_mad(
    valores: List[Union[int, float, Decimal]],
    threshold: float = 3.0
) -> Tuple[List[float], List[float]]:
    """
    Filtra outliers utilizando o Modified Z-score com base no MAD (Iglewicz & Hoaglin):
    M_i = 0.6745 * |x_i - mediana| / MAD

    Se MAD == 0 (ex: mais da metade dos valores são idênticos), utiliza o desvio padrão
    amostral ou desvio médio para evitar divisão por zero. Se todos os valores forem idênticos,
    nenhum valor é descartado.

    Retorna:
    - valores_filtrados: lista de valores inliers
    - outliers_removidos: lista de valores considerados outliers
    """
    if not valores:
        return [], []

    floats = [float(v) for v in valores]
    if len(floats) <= 2:
        return floats, []

    mediana = calcular_mediana(floats)
    mad = calcular_mad(floats, mediana)

    valores_filtrados: List[float] = []
    outliers_removidos: List[float] = []

    if mad > 0:
        for x in floats:
            mod_z = 0.6745 * abs(x - mediana) / mad
            if mod_z > threshold:
                outliers_removidos.append(x)
            else:
                valores_filtrados.append(x)
    else:
        # Fallback para MAD == 0: calcula desvio médio absoluto
        desvio_medio = sum(abs(x - mediana) for x in floats) / len(floats)
        if desvio_medio > 0:
            for x in floats:
                score = abs(x - mediana) / desvio_medio
                if score > threshold:
                    outliers_removidos.append(x)
                else:
                    valores_filtrados.append(x)
        else:
            # Todos os valores são idênticos: nenhum é outlier
            valores_filtrados = floats
            outliers_removidos = []

    # Garante que se todos foram considerados outliers por extrema discrepância, mantém ao menos os inliers mais próximos
    if not valores_filtrados and floats:
        valores_filtrados = floats
        outliers_removidos = []

    return valores_filtrados, outliers_removidos


def calcular_media_e_desvio(
    valores: List[Union[int, float, Decimal]]
) -> Tuple[float, float]:
    """
    Calcula a média aritmética (μ) e o desvio padrão amostral (σ).
    Retorna (media, desvio_padrao).
    """
    if not valores:
        return 0.0, 0.0

    floats = [float(v) for v in valores]
    n = len(floats)
    media = sum(floats) / float(n)

    if n <= 1:
        return round(media, 4), 0.0

    variancia = sum((x - media) ** 2 for x in floats) / float(n - 1)
    desvio = math.sqrt(max(0.0, variancia))
    return round(media, 4), round(desvio, 4)
