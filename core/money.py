from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

# Constantes padronizadas de modelagem para campos monetários, quantitativos e percentuais (Sprint 7A)
MONEY_KWARGS = {
    'max_digits': 14,
    'decimal_places': 2,
}

QTY_KWARGS = {
    'max_digits': 14,
    'decimal_places': 3,
}

PCT_KWARGS = {
    'max_digits': 8,
    'decimal_places': 4,
}


def quantize(valor: Decimal | int | str, casas: int | Decimal = 2) -> Decimal:
    """
    Quantiza um valor monetário ou numérico com precisão fixa usando ROUND_HALF_UP.
    Proíbe terminantemente o uso de float para evitar imprecisões de ponto flutuante binário.
    """
    if isinstance(valor, float):
        raise TypeError(
            "Proibido o uso de float em operações financeiras e quantitativas. "
            "Converta explicitamente para Decimal, int ou str antes de quantizar."
        )

    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))

    if isinstance(casas, Decimal):
        if casas < Decimal('1'):
            exp = casas
        else:
            exp = Decimal(10) ** -int(casas)
    else:
        exp = Decimal(10) ** -int(casas)

    return valor.quantize(exp, rounding=ROUND_HALF_UP)


def allocate(
    total: Decimal | int | str,
    pesos: Sequence[Decimal | int | str],
    casas: int = 2
) -> list[Decimal]:
    """
    Distribui um valor total proporcionalmente a uma sequência de pesos.
    Garante que a soma de todas as parcelas é exatamente igual ao valor total inicial:
        sum(allocate(total, pesos)) == total
    O resíduo de centavos decorrente do arredondamento é integralmente direcionado
    à última parcela (regra estrita para parcelamento, rateio e DRE).
    """
    if isinstance(total, float):
        raise TypeError("Total não pode ser float. Use Decimal, int ou str.")

    if not isinstance(total, Decimal):
        total = Decimal(str(total))

    total = quantize(total, casas=casas)

    if not pesos:
        return []

    # Validação dos pesos e proibição de float
    pesos_dec = []
    for idx, p in enumerate(pesos):
        if isinstance(p, float):
            raise TypeError(f"Peso na posição {idx} é float. Use Decimal, int ou str.")
        p_dec = Decimal(str(p)) if not isinstance(p, Decimal) else p
        if p_dec < Decimal(0):
            raise ValueError(f"Peso na posição {idx} não pode ser negativo: {p_dec}")
        pesos_dec.append(p_dec)

    soma_pesos = sum(pesos_dec)
    if soma_pesos == Decimal(0):
        raise ValueError("A soma dos pesos deve ser estritamente maior que zero.")

    if len(pesos_dec) == 1:
        return [total]

    from decimal import ROUND_DOWN

    exp = Decimal(10) ** -casas
    parcelas = []
    soma_acumulada = Decimal(0)

    # Calcula as primeiras parcelas com ROUND_DOWN para garantir que a soma acumulada
    # nunca exceda o total inicial (invariante matematicamente comprovada: sem parcelas negativas).
    for p in pesos_dec[:-1]:
        parcela = ((total * p) / soma_pesos).quantize(exp, rounding=ROUND_DOWN)
        parcelas.append(parcela)
        soma_acumulada += parcela

    # A última parcela recebe o resíduo exato de centavos
    ultima_parcela = total - soma_acumulada
    parcelas.append(ultima_parcela)

    return parcelas
