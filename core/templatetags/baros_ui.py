"""Filtros de apoio aos componentes do Design System (templates/components/)."""
from django import template

register = template.Library()


@register.filter
def dividir(valor, separador='|'):
    """'Dados|Endereço|Revisão' -> ['Dados', 'Endereço', 'Revisão'] (usado pelo _stepper.html)."""
    if not valor:
        return []
    return [parte.strip() for parte in str(valor).split(separador) if parte.strip()]
