from typing import Any

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

PERMISSOES_FINANCEIRAS = [
    ('lancar', 'Pode lançar títulos, contas e faturas'),
    ('aprovar', 'Pode aprovar títulos e liquidações'),
    ('baixar', 'Pode baixar e liquidar títulos pagos/recebidos'),
    ('estornar', 'Pode estornar liquidações e lançamentos'),
    ('fechar_periodo', 'Pode fechar competências e períodos contábeis'),
    ('ver_dre', 'Pode visualizar DRE, Balancete e Relatórios Gerenciais'),
    ('auditar', 'Pode auditar logs de auditoria e trilha financeira'),
]

GRUPOS_FINANCEIROS_MAP = {
    'FIN_LANCADOR': ['lancar'],
    'FIN_APROVADOR': ['aprovar', 'ver_dre'],
    'FIN_TESOUREIRO': ['baixar', 'estornar'],
    'FIN_AUDITOR': ['auditar', 'ver_dre'],
    'FIN_ADMIN': [
        'lancar',
        'aprovar',
        'baixar',
        'estornar',
        'fechar_periodo',
        'ver_dre',
        'auditar'
    ],
}


def seed_rbac_financeiro():
    """
    Seed idempotente de grupos e permissões do subsistema Financeiro (Sprint 7A - Lacuna F-33).
    Garante que todos os grupos RBAC e permissões granulares existam no banco sem duplicidade.
    """
    # ContentType dummy ou financeiro
    ct, _ = ContentType.objects.get_or_create(app_label='financeiro', model='modulo_financeiro')

    perms_dict = {}
    for codename, name in PERMISSOES_FINANCEIRAS:
        perm, _ = Permission.objects.get_or_create(
            content_type=ct,
            codename=codename,
            defaults={'name': name}
        )
        perms_dict[codename] = perm

    for group_name, perms_codenames in GRUPOS_FINANCEIROS_MAP.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group_perms = [perms_dict[c] for c in perms_codenames if c in perms_dict]
        group.permissions.set(group_perms)

    return True


def pode_aprovar(usuario: Any, objeto: Any) -> bool:
    """
    Regra Estrita de Segregação de Funções (SoD - Segregation of Duties):
    - O usuário deve possuir a permissão 'financeiro.aprovar' (ou grupo FIN_APROVADOR / FIN_ADMIN).
    - O usuário que LANÇOU ou CRIOU o registro NÃO PODE aprová-lo em hipótese alguma.
    """
    if not (usuario and usuario.is_authenticated):
        return False

    # Superusuário sem segregação estrita violada: a regra de ouro proíbe auto-aprovação
    criador = (
        getattr(objeto, 'criado_por', None) or
        getattr(objeto, 'registrado_por', None) or
        getattr(objeto, 'lancado_por', None) or
        getattr(objeto, 'vendedor', None)
    )

    if criador and criador == usuario:
        return False

    # Valida se o usuário possui permissão de aprovação ou pertence aos grupos autorizados
    has_perm = usuario.has_perm('financeiro.aprovar')
    in_group = usuario.groups.filter(name__in=['FIN_APROVADOR', 'FIN_ADMIN']).exists()

    return bool(has_perm or in_group or usuario.is_superuser)


def pode_baixar(usuario: Any, objeto: Any) -> bool:
    """
    Regra Estrita de Segregação de Funções:
    - O usuário deve possuir a permissão 'financeiro.baixar' (ou grupo FIN_TESOUREIRO / FIN_ADMIN).
    - O usuário que LANÇOU ou CRIOU o registro NÃO PODE baixá-lo (evita auto-liquidação).
    """
    if not (usuario and usuario.is_authenticated):
        return False

    criador = (
        getattr(objeto, 'criado_por', None) or
        getattr(objeto, 'registrado_por', None) or
        getattr(objeto, 'lancado_por', None) or
        getattr(objeto, 'vendedor', None)
    )

    if criador and criador == usuario:
        return False

    has_perm = usuario.has_perm('financeiro.baixar')
    in_group = usuario.groups.filter(name__in=['FIN_TESOUREIRO', 'FIN_ADMIN']).exists()

    return bool(has_perm or in_group or usuario.is_superuser)
