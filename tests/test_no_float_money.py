import pytest
from django.apps import apps
from django.db import models

PALAVRAS_PROIBIDAS_EM_FLOAT = [
    'valor',
    'preco',
    'custo',
    'saldo',
    'volume',
    'peso',
    'percentual',
    'taxa',
    'pressao',
    'tara',
]


@pytest.mark.django_db
def test_anti_float_em_campos_financeiros_e_quantitativos():
    """
    Regra 2 & Tarefa 2 (Sprint 7A):
    Garante que nenhum model do sistema utilize models.FloatField em campos
    financeiros, monetários, métricos ou percentuais.
    Todo campo de valor, preço, custo, saldo, volume, peso, taxa, pressão ou tara
    DEVE obrigatoriamente utilizar DecimalField com precisão definida em core/money.py.
    """
    violacoes = []

    for model in apps.get_models():
        # Filtra apenas apps do próprio projeto
        app_label = model._meta.app_label
        if app_label.startswith('django.') or app_label in ('admin', 'contenttypes', 'auth', 'sessions', 'messages'):
            continue

        for field in model._meta.get_fields():
            if not isinstance(field, models.Field):
                continue

            if isinstance(field, models.FloatField):
                nome_campo = field.name.lower()
                for palavra in PALAVRAS_PROIBIDAS_EM_FLOAT:
                    if palavra in nome_campo:
                        violacoes.append(
                            f"Model {model.__module__}.{model.__name__} possui campo FloatField proibido: "
                            f"'{field.name}' (termo detectado: '{palavra}'). Deve ser DecimalField."
                        )

    assert not violacoes, (
        "Detectadas violações da regra anti-float (Sprint 7A):\n" + "\n".join(violacoes)
    )
