"""
Módulo de conversão técnica de unidades para gases industriais e medicinais (Sprint 8C - Tarefa 1).
Referência técnica: Condições Normais de Temperatura e Pressão (NTP: 20 °C, 1 atm conforme ABNT NBR 12274 e ISO 9809).
A unidade base de estoque de gás no sistema é sempre o QUILOGRAMA (kg), com 3 casas decimais.
É terminantemente proibido o uso de ponto flutuante binário (float).
"""

from decimal import Decimal
from core.money import quantize


def _to_decimal(val: Decimal | int | str, nome: str) -> Decimal:
    if isinstance(val, float):
        raise TypeError(f"Proibido o uso de float em '{nome}'. Forneça Decimal, int ou str.")
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def converter_m3_para_kg(
    m3: Decimal | int | str,
    fator_m3_por_kg: Decimal | int | str
) -> Decimal:
    """
    Converte volume em m³ gasoso (20 °C, 1 atm) para massa em kg.
    Fórmula: kg = m³ ÷ (fator m³/kg)
    Exemplo O2: 10 m³ ÷ 0.7519 m³/kg = 13.299 kg
    """
    m3_dec = _to_decimal(m3, "m3")
    fator_dec = _to_decimal(fator_m3_por_kg, "fator_m3_por_kg")

    if fator_dec <= Decimal('0.0000'):
        raise ValueError("O fator de conversão m³/kg deve ser estritamente maior que zero.")

    kg = m3_dec / fator_dec
    return quantize(kg, 3)


def converter_kg_para_m3(
    kg: Decimal | int | str,
    fator_m3_por_kg: Decimal | int | str
) -> Decimal:
    """
    Converte massa em kg para volume em m³ gasoso (20 °C, 1 atm).
    Fórmula: m³ = kg × (fator m³/kg)
    """
    kg_dec = _to_decimal(kg, "kg")
    fator_dec = _to_decimal(fator_m3_por_kg, "fator_m3_por_kg")

    if fator_dec <= Decimal('0.0000'):
        raise ValueError("O fator de conversão m³/kg deve ser estritamente maior que zero.")

    m3 = kg_dec * fator_dec
    return quantize(m3, 3)


def converter_litros_para_kg(
    litros: Decimal | int | str,
    densidade_liquido_kg_l: Decimal | int | str
) -> Decimal:
    """
    Converte volume de líquido criogênico em Litros para massa em kg.
    Fórmula: kg = Litros × (densidade kg/L)
    Exemplo LOX (oxigênio líquido a -183 °C): 1000 L × 1.141 kg/L = 1141.000 kg
    """
    litros_dec = _to_decimal(litros, "litros")
    dens_dec = _to_decimal(densidade_liquido_kg_l, "densidade_liquido_kg_l")

    if dens_dec <= Decimal('0.0000'):
        raise ValueError("A densidade do líquido em kg/L deve ser estritamente maior que zero.")

    kg = litros_dec * dens_dec
    return quantize(kg, 3)


def converter_kg_para_litros(
    kg: Decimal | int | str,
    densidade_liquido_kg_l: Decimal | int | str
) -> Decimal:
    """
    Converte massa em kg para volume de líquido criogênico em Litros.
    Fórmula: Litros = kg ÷ (densidade kg/L)
    """
    kg_dec = _to_decimal(kg, "kg")
    dens_dec = _to_decimal(densidade_liquido_kg_l, "densidade_liquido_kg_l")

    if dens_dec <= Decimal('0.0000'):
        raise ValueError("A densidade do líquido em kg/L deve ser estritamente maior que zero.")

    litros = kg_dec / dens_dec
    return quantize(litros, 3)
