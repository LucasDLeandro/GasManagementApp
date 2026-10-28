"""
Serviço Canônico de Provisão para Devedores Duvidosos (PDD) e Baixa Definitiva de Perdas (Sprint 10B - Tarefa 10).
Calcula a provisão necessária por faixa de atraso, apura o ajuste em relação ao saldo vigente e efetua write-offs.
"""

import datetime
from decimal import Decimal
from typing import Optional, Union

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Q

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    ParametroPDD,
    ParcelaFinanceira,
    PlanoContas,
    PartidaContabil,
    LancamentoContabil,
)
from financeiro.services.razao import lancar


FAIXAS_PDD_PADRAO = [
    {'dias_min': 1, 'dias_max': 30, 'percentual': Decimal('0.0500')},
    {'dias_min': 31, 'dias_max': 60, 'percentual': Decimal('0.1000')},
    {'dias_min': 61, 'dias_max': 90, 'percentual': Decimal('0.2500')},
    {'dias_min': 91, 'dias_max': 180, 'percentual': Decimal('0.5000')},
    {'dias_min': 181, 'dias_max': 9999, 'percentual': Decimal('1.0000')},
]


def garantir_parametros_pdd_padrao(tenant) -> list[ParametroPDD]:
    """Garante a existência das faixas regulamentares padrão de PDD para o tenant."""
    faixas = list(ParametroPDD.unscoped.filter(tenant=tenant, ativo=True).order_by('dias_atraso_min'))
    if not faixas:
        novas = []
        for f in FAIXAS_PDD_PADRAO:
            obj, _ = ParametroPDD.unscoped.get_or_create(
                tenant=tenant,
                dias_atraso_min=f['dias_min'],
                dias_atraso_max=f['dias_max'],
                defaults={'percentual_provisao': f['percentual'], 'ativo': True}
            )
            novas.append(obj)
        faixas = novas
    return faixas


@transaction.atomic
def calcular_pdd(
    tenant,
    periodo: Union[str, datetime.date],
    usuario=None
) -> dict:
    """
    Calcula a Provisão para Devedores Duvidosos (PDD) para o período indicado (Sprint 10B - Tarefa 10).
    Regras estritas:
    1. Base de cálculo = parcelas a receber vencidas e não pagas na data de referência;
    2. Enquadramento por faixa de dias de atraso conforme ParametroPDD;
    3. Apuração do saldo vigente na conta contábil redutora 1.1.2.02 ((-) PDD);
    4. Escrituração apenas da variação (ajuste necessário):
       - Se ajuste > 0: Débito em 5.4 (Despesa PDD), Crédito em 1.1.2.02 ((-) PDD);
       - Se ajuste < 0: Débito em 1.1.2.02 ((-) PDD), Crédito em 8.1 (Reversão de PDD);
       - Se ajuste == 0: nenhuma escrituração (segunda execução no mesmo período gera ajuste zero).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if isinstance(periodo, str):
        partes = periodo.strip().split('-')
        if len(partes) >= 3:
            dt_ref = datetime.date(int(partes[0]), int(partes[1]), int(partes[2]))
        else:
            # Primeiro dia do mês seguinte ou último do mês
            ano, mes = int(partes[0]), int(partes[1])
            if mes == 12:
                dt_ref = datetime.date(ano, 12, 31)
            else:
                dt_ref = datetime.date(ano, mes + 1, 1) - datetime.timedelta(days=1)
    else:
        dt_ref = periodo

    faixas = garantir_parametros_pdd_padrao(tenant)

    # 1. Busca todas as parcelas a receber vencidas até a data de referência
    parcelas_vencidas = ParcelaFinanceira.unscoped.filter(
        tenant=tenant,
        titulo__tipo='RECEBER',
        status__in=['ABERTO', 'PENDENTE', 'PARCIAL', 'EM_PROTESTO'],
        data_vencimento__lt=dt_ref,
        saldo_em_aberto__gt=Decimal('0.00')
    ).select_related('titulo')

    total_provisao_necessaria = Decimal('0.00')
    detalhes_faixas = {f.id: {'faixa': f, 'qtd_parcelas': 0, 'saldo_total': Decimal('0.00'), 'provisao': Decimal('0.00')} for f in faixas}

    for p in parcelas_vencidas:
        dias_atraso = (dt_ref - p.data_vencimento).days
        faixa_aplicavel = None
        for f in faixas:
            if f.dias_atraso_min <= dias_atraso <= f.dias_atraso_max:
                faixa_aplicavel = f
                break

        if faixa_aplicavel:
            prov_parcela = quantize(p.saldo_em_aberto * faixa_aplicavel.percentual_provisao, 2)
            total_provisao_necessaria += prov_parcela
            df = detalhes_faixas[faixa_aplicavel.id]
            df['qtd_parcelas'] += 1
            df['saldo_total'] = quantize(df['saldo_total'] + p.saldo_em_aberto, 2)
            df['provisao'] = quantize(df['provisao'] + prov_parcela, 2)

    total_provisao_necessaria = quantize(total_provisao_necessaria, 2)

    # 2. Localiza as contas contábeis no Plano de Contas
    cta_despesa_pdd = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='5.4').first()
    cta_pdd_redutora = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='1.1.2.02').first()
    cta_reversao = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='8.1').first()

    if not cta_despesa_pdd or not cta_pdd_redutora:
        raise ValidationError(
            "Contas de PDD não encontradas no plano de contas (5.4 Despesas com PDD ou 1.1.2.02 (-) PDD)."
        )

    # 3. Saldo vigente da provisão no Razão até a data de referência
    totais_pdd = PartidaContabil.unscoped.filter(
        tenant=tenant,
        conta_contabil=cta_pdd_redutora,
        lancamento__data_competencia__lte=dt_ref
    ).aggregate(
        total_deb=Sum('valor', filter=Q(tipo_partida='DEBITO')),
        total_cred=Sum('valor', filter=Q(tipo_partida='CREDITO'))
    )
    total_deb = totais_pdd['total_deb'] or Decimal('0.00')
    total_cred = totais_pdd['total_cred'] or Decimal('0.00')
    # Conta redutora do ativo: natureza credora -> saldo = créditos - débitos
    saldo_vigente = quantize(total_cred - total_deb, 2)

    ajuste = quantize(total_provisao_necessaria - saldo_vigente, 2)
    lancamento = None

    if ajuste > Decimal('0.00'):
        # Necessidade de reforço da provisão: D Despesa PDD (5.4) / C (-) PDD (1.1.2.02)
        partidas = [
            {'conta_id': cta_despesa_pdd.id, 'tipo_partida': 'DEBITO', 'valor': ajuste},
            {'conta_id': cta_pdd_redutora.id, 'tipo_partida': 'CREDITO', 'valor': ajuste},
        ]
        lancamento, _ = lancar(
            tenant=tenant,
            data_competencia=dt_ref,
            historico=f"Constituição/Reforço de PDD - Vencimento até {dt_ref.strftime('%d/%m/%Y')}",
            partidas=partidas,
            origem_tipo='PDD',
            origem_id=dt_ref.strftime('%Y-%m'),
            usuario=usuario
        )
    elif ajuste < Decimal('0.00'):
        # Reversão de excesso de provisão: D (-) PDD (1.1.2.02) / C Reversão PDD (8.1)
        val_reversao = abs(ajuste)
        partidas = [
            {'conta_id': cta_pdd_redutora.id, 'tipo_partida': 'DEBITO', 'valor': val_reversao},
            {'conta_id': (cta_reversao or cta_despesa_pdd).id, 'tipo_partida': 'CREDITO', 'valor': val_reversao},
        ]
        lancamento, _ = lancar(
            tenant=tenant,
            data_competencia=dt_ref,
            historico=f"Reversão de Excesso de PDD - Vencimento até {dt_ref.strftime('%d/%m/%Y')}",
            partidas=partidas,
            origem_tipo='PDD_REVERSAO',
            origem_id=dt_ref.strftime('%Y-%m'),
            usuario=usuario
        )

    return {
        'data_referencia': dt_ref,
        'provisao_necessaria': total_provisao_necessaria,
        'saldo_vigente': saldo_vigente,
        'ajuste': ajuste,
        'ajuste_escriturado': ajuste,
        'lancamento': lancamento,
        'lancamento_id': lancamento.id if lancamento else None,
        'detalhes_faixas': detalhes_faixas
    }


@transaction.atomic
def baixar_perda_pdd(
    *,
    tenant,
    parcela_id: Union[str, int],
    motivo: str,
    aprovado_por=None,
    usuario=None
) -> LancamentoContabil:
    """
    Realiza a baixa definitiva de perda de crédito incobrável (Write-off) contra o saldo de PDD (Sprint 10B - Tarefa 10).
    Ação estritamente manual sujeita à aprovação formal de alçada.
    Escrituração: Débito em 1.1.2.02 (-) PDD / Crédito em 1.1.2.01 Clientes a Receber.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    aprovador = aprovado_por or usuario
    if not aprovador:
        raise ValidationError("A baixa definitiva de perda por PDD exige aprovação formal de alçada.")

    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal do write-off é obrigatório.")

    parcela = ParcelaFinanceira.unscoped.select_for_update().get(tenant=tenant, id=parcela_id)
    if parcela.status == 'PAGA':
        raise ValidationError("Não é permitido baixar por PDD uma parcela já liquidada.")

    valor_perda = parcela.saldo_em_aberto
    if valor_perda <= Decimal('0.00'):
        raise ValidationError("A parcela não possui saldo em aberto para baixa por perda.")

    cta_pdd = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='1.1.2.02').first()
    cta_clientes = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='1.1.2.01').first()

    if not cta_pdd or not cta_clientes:
        raise ValidationError("Contas contábeis de Clientes ou PDD não encontradas no Plano de Contas.")

    hoje = datetime.date.today()
    partidas = [
        {'conta_id': cta_pdd.id, 'tipo_partida': 'DEBITO', 'valor': valor_perda},
        {'conta_id': cta_clientes.id, 'tipo_partida': 'CREDITO', 'valor': valor_perda},
    ]

    lancamento, _ = lancar(
        tenant=tenant,
        data_competencia=hoje,
        historico=f"Baixa Definitiva de Perda (Write-off PDD) - Parcela #{parcela.id} ({motivo.strip()})",
        partidas=partidas,
        origem_tipo='WRITE_OFF_PDD',
        origem_id=str(parcela.id),
        usuario=aprovador
    )

    parcela.status = 'CANCELADA'
    parcela.saldo_em_aberto = Decimal('0.00')
    parcela.save(update_fields=['status', 'saldo_em_aberto'])

    return lancamento
