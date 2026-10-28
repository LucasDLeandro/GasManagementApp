from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.money import MONEY_KWARGS, PCT_KWARGS, QTY_KWARGS, allocate, quantize


# Testes com Hypothesis (Testes de Propriedade - Sprint 7A)
@given(
    total=st.decimals(min_value=Decimal('0.01'), max_value=Decimal('999999999.99'), places=2),
    pesos=st.lists(
        st.decimals(min_value=Decimal('0.01'), max_value=Decimal('1000.00'), places=2),
        min_size=1,
        max_size=30
    )
)
def test_hypothesis_allocate_invariante_soma_exata(total, pesos):
    """
    Invariante Fundamental:
    A soma das parcelas devolvidas por allocate DEVE ser rigorosamente idêntica ao valor total inicial.
    Nenhuma parcela pode ser negativa (quando pesos e total são positivos).
    """
    parcelas = allocate(total, pesos)

    assert len(parcelas) == len(pesos)
    assert sum(parcelas) == total
    for p in parcelas:
        assert p >= Decimal('0.00'), f"Parcela negativa encontrada: {p} em {parcelas}"


@given(
    total=st.decimals(min_value=Decimal('0.00'), max_value=Decimal('999999999.99'), places=2),
    qtd_parcelas=st.integers(min_value=1, max_value=36)
)
def test_hypothesis_allocate_parcelamento_uniforme(total, qtd_parcelas):
    """
    Invariante:
    Distribuição uniforme (pesos iguais) soma exatamente o total e não gera parcelas negativas.
    """
    pesos = [Decimal(1)] * qtd_parcelas
    parcelas = allocate(total, pesos)

    assert len(parcelas) == qtd_parcelas
    assert sum(parcelas) == total


def test_quantize_round_half_up():
    assert quantize(Decimal('10.255'), casas=2) == Decimal('10.26')
    assert quantize(Decimal('10.254'), casas=2) == Decimal('10.25')
    assert quantize(Decimal('10.2550'), casas=2) == Decimal('10.26')
    assert quantize('100.555', casas=2) == Decimal('100.56')
    assert quantize(10, casas=2) == Decimal('10.00')


def test_quantize_proibe_float():
    with pytest.raises(TypeError, match="Proibido o uso de float"):
        quantize(10.55)


def test_allocate_proibe_float():
    with pytest.raises(TypeError):
        allocate(10.55, [1, 2])
    with pytest.raises(TypeError):
        allocate(Decimal('10.00'), [1.5, 2])


def test_allocate_pesos_zerados():
    with pytest.raises(ValueError, match="A soma dos pesos deve ser estritamente maior que zero"):
        allocate(Decimal('100.00'), [Decimal(0), Decimal(0)])


def test_allocate_residuo_centavos_na_ultima_parcela():
    # 100 dividido em 3 partes com pesos iguais
    total = Decimal('100.00')
    pesos = [1, 1, 1]
    parcelas = allocate(total, pesos)

    assert parcelas == [Decimal('33.33'), Decimal('33.33'), Decimal('33.34')]
    assert sum(parcelas) == total


def test_constantes_kwargs():
    assert MONEY_KWARGS == {'max_digits': 14, 'decimal_places': 2}
    assert QTY_KWARGS == {'max_digits': 14, 'decimal_places': 3}
    assert PCT_KWARGS == {'max_digits': 8, 'decimal_places': 4}
