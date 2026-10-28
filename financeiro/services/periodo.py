"""
Serviços de gestão de períodos contábeis e travas de competência (Sprint 9A - Tarefa 5 / Correção F-17).
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from financeiro.models import PeriodoContabil


def checar_periodo_aberto(tenant, data):
    """
    Verifica se a competência contábil ou liquidação financeira de uma determinada data está aberta.
    Lança ValidationError se o período estiver formalmente FECHADO.
    """
    if not data:
        return
    ano = data.year
    mes = data.month
    periodo = PeriodoContabil.objects.filter(
        tenant=tenant,
        ano=ano,
        mes=mes
    ).first()

    if periodo and periodo.status == 'FECHADO':
        raise ValidationError(
            f"Operação rejeitada: o período contábil {mes:02d}/{ano} encontra-se formalmente FECHADO."
        )


@transaction.atomic
def fechar_periodo(*, tenant, ano: int, mes: int, usuario=None):
    """
    Fecha formalmente um período contábil/financeiro (Sprint 9A - Tarefa 5).
    Bloqueia novos lançamentos contábeis e movimentações financeiras na competência.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if mes < 1 or mes > 12:
        raise ValidationError(f"Mês inválido: {mes}. Deve estar entre 1 e 12.")

    periodo, _ = PeriodoContabil.objects.select_for_update().get_or_create(
        tenant=tenant,
        ano=ano,
        mes=mes,
        defaults={'status': 'ABERTO'}
    )

    if periodo.status == 'FECHADO':
        raise ValidationError(f"O período {mes:02d}/{ano} já se encontra fechado.")

    periodo.status = 'FECHADO'
    periodo.fechado_por = usuario
    periodo.fechado_em = timezone.now()
    periodo.save(update_fields=['status', 'fechado_por', 'fechado_em'])

    return periodo


@transaction.atomic
def reabrir_periodo(*, tenant, ano: int, mes: int, motivo: str, usuario=None):
    """
    Reabre um período contábil previamente fechado (Sprint 9A - Tarefa 5).
    Regra estrita: Só é permitida a reabertura do ÚLTIMO período fechado, com justificativa obrigatória.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal da reabertura do período é estritamente obrigatório.")

    periodo = PeriodoContabil.objects.select_for_update().filter(
        tenant=tenant,
        ano=ano,
        mes=mes
    ).first()

    if not periodo or periodo.status != 'FECHADO':
        raise ValidationError(f"O período {mes:02d}/{ano} não está fechado para ser reaberto.")

    # Regra: só é permitido reabrir o último período fechado da linha do tempo
    ultimo_fechado = PeriodoContabil.objects.filter(
        tenant=tenant,
        status='FECHADO'
    ).order_by('-ano', '-mes').first()

    if ultimo_fechado and (ultimo_fechado.ano != ano or ultimo_fechado.mes != mes):
        raise ValidationError(
            f"Não é permitido reabrir o período {mes:02d}/{ano} enquanto houver períodos posteriores fechados. "
            f"O último período fechado é {ultimo_fechado.mes:02d}/{ultimo_fechado.ano}."
        )

    periodo.status = 'ABERTO'
    periodo.reaberto_por = usuario
    periodo.reaberto_em = timezone.now()
    periodo.motivo_reabertura = motivo.strip()
    periodo.save(update_fields=['status', 'reaberto_por', 'reaberto_em', 'motivo_reabertura'])

    return periodo
