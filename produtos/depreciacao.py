import datetime
from decimal import Decimal
from typing import Optional

from core.money import quantize


def quota_mensal(
    valor_aquisicao: Decimal,
    valor_residual: Decimal,
    vida_util_meses: int
) -> Decimal:
    """
    Calcula a quota mensal de depreciação linear (método das quotas constantes).
    quota = max(0, (valor - residual) / vida_util_meses)
    """
    if valor_aquisicao is None or valor_residual is None or not vida_util_meses or vida_util_meses <= 0:
        return Decimal('0.00')

    base_depreciavel = valor_aquisicao - valor_residual
    if base_depreciavel <= Decimal('0.00'):
        return Decimal('0.00')

    quota = quantize(base_depreciavel / Decimal(str(vida_util_meses)), 2)
    return max(Decimal('0.00'), quota)


def meses_depreciados(
    data_inicio_depreciacao: Optional[datetime.date],
    data_referencia: Optional[datetime.date] = None
) -> int:
    """
    Retorna o número de meses completos depreciados.
    A depreciação contábil padrão inicia no mês seguinte à data_inicio_depreciacao.
    Exemplo: aquisição em 15/01/2024 -> 1º mês depreciado em 02/2024.
    """
    if not data_inicio_depreciacao:
        return 0

    if data_referencia is None:
        from django.utils import timezone
        data_referencia = timezone.localdate()

    if data_referencia <= data_inicio_depreciacao:
        return 0

    diferenca_meses = (
        (data_referencia.year - data_inicio_depreciacao.year) * 12
        + (data_referencia.month - data_inicio_depreciacao.month)
    )
    return max(0, diferenca_meses)


def depreciacao_acumulada(
    valor_aquisicao: Decimal,
    valor_residual: Decimal,
    vida_util_meses: int,
    data_inicio_depreciacao: Optional[datetime.date],
    data_referencia: Optional[datetime.date] = None
) -> Decimal:
    """
    Calcula o valor acumulado de depreciação até a data de referência,
    limitado à base depreciável total (valor_aquisicao - valor_residual).
    """
    if not valor_aquisicao or not vida_util_meses or vida_util_meses <= 0:
        return Decimal('0.00')

    valor_res = valor_residual if valor_residual is not None else Decimal('0.00')
    base_depreciavel = max(Decimal('0.00'), valor_aquisicao - valor_res)
    if base_depreciavel == Decimal('0.00'):
        return Decimal('0.00')

    meses = meses_depreciados(data_inicio_depreciacao, data_referencia)
    meses_efetivos = min(meses, vida_util_meses)
    quota = quota_mensal(valor_aquisicao, valor_res, vida_util_meses)

    acumulada = quantize(quota * Decimal(str(meses_efetivos)), 2)
    return min(base_depreciavel, acumulada)


def valor_contabil_liquido(
    valor_aquisicao: Decimal,
    valor_residual: Decimal,
    vida_util_meses: int,
    data_inicio_depreciacao: Optional[datetime.date],
    data_referencia: Optional[datetime.date] = None
) -> Decimal:
    """
    Calcula o Valor Contábil Líquido (VCL = Valor Aquisição - Depreciação Acumulada).
    Invariante: o VCL nunca fica abaixo do valor residual.
    """
    if valor_aquisicao is None:
        return Decimal('0.00')

    valor_res = valor_residual if valor_residual is not None else Decimal('0.00')
    if not vida_util_meses or vida_util_meses <= 0 or not data_inicio_depreciacao:
        return quantize(valor_aquisicao, 2)

    acumulada = depreciacao_acumulada(
        valor_aquisicao=valor_aquisicao,
        valor_residual=valor_res,
        vida_util_meses=vida_util_meses,
        data_inicio_depreciacao=data_inicio_depreciacao,
        data_referencia=data_referencia,
    )
    vcl = quantize(valor_aquisicao - acumulada, 2)
    return max(valor_res, vcl)
