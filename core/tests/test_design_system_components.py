"""Parciais do Design System (templates/components/) renderizam como documentado em docs/DESIGN_SYSTEM.md."""
from django.template.loader import render_to_string


def test_stepper_gera_uma_etapa_por_item_com_a_primeira_ativa():
    html = render_to_string('components/_stepper.html', {'id': 'novo', 'etapas': 'Dados|Endereço| Revisão '})

    assert html.count('class="step-item') == 3
    assert html.count('step-divider') == 2
    assert 'class="step-item active" data-step="1"' in html
    assert 'data-step="3"' in html
    assert '>Revisão<' in html


def test_metric_card_com_tom_e_valor_padrao():
    html = render_to_string('components/_metric_card.html', {'rotulo': 'Vencidos', 'tom': 'danger'})

    assert 'metric-card--danger' in html
    assert '>Vencidos<' in html
    assert '—' in html


def test_empty_state_de_erro():
    html = render_to_string('components/_empty_state.html', {'titulo': 'Falhou', 'tom': 'danger'})

    assert 'ds-empty--danger' in html
    assert 'role="status"' in html
