"""
Serviço Canônico de Provisão Tributária de IRPJ e CSLL (Sprint 10B - Tarefa 8).
Calcula bases fiscais por Lucro Presumido ou Lucro Real, apura adicional de IRPJ e escritura no Razão.
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
    ParametroTributarioLucro,
    PlanoContas,
    SaldoMensalConta,
    LancamentoContabil,
)
from financeiro.services.razao import lancar


def garantir_parametro_tributario(tenant) -> ParametroTributarioLucro:
    """Garante existência dos parâmetros fiscais com fallbacks seguros para o plano de contas."""
    param, _ = ParametroTributarioLucro.unscoped.get_or_create(
        tenant=tenant,
        defaults={
            'regime': 'LUCRO_PRESUMIDO',
            'aliquota_irpj': Decimal('0.1500'),
            'aliquota_adicional_irpj': Decimal('0.1000'),
            'teto_isencao_adicional_mensal': Decimal('20000.00'),
            'aliquota_csll': Decimal('0.0900'),
            'presuncao_irpj': Decimal('0.0800'),
            'presuncao_csll': Decimal('0.1200'),
        }
    )
    if not param.conta_despesa_irpj:
        param.conta_despesa_irpj = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='9.1').first()
    if not param.conta_despesa_csll:
        param.conta_despesa_csll = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='9.2').first()
    if not param.conta_passivo_irpj:
        param.conta_passivo_irpj = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='2.1.2').first()
    if not param.conta_passivo_csll:
        param.conta_passivo_csll = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='2.1.2').first()
    param.save()
    return param


@transaction.atomic
def calcular_e_lancar_provisao_tributaria(
    tenant,
    ano: int,
    mes: int,
    usuario=None
) -> dict:
    """
    Calcula e escritura a provisão mensal de IRPJ e CSLL (Sprint 10B - Tarefa 8).
    Idempotente por período (ano/mês).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    ano_mes = f"{ano:04d}-{mes:02d}"
    if mes == 12:
        dt_comp = datetime.date(ano, 12, 31)
    else:
        dt_comp = datetime.date(ano, mes + 1, 1) - datetime.timedelta(days=1)

    # 1. Idempotência: verifica se a provisão do período já foi escriturada
    lanc_existente = LancamentoContabil.unscoped.filter(
        tenant=tenant,
        origem_tipo='PROVISAO_IRPJ_CSLL',
        origem_id=ano_mes
    ).first()
    if lanc_existente:
        return {
            'ano_mes': ano_mes,
            'status': 'JA_CALCULADO',
            'lancamento_id': lanc_existente.id,
            'valor_irpj': Decimal('0.00'),
            'valor_csll': Decimal('0.00')
        }

    param = garantir_parametro_tributario(tenant)

    # 2. Apuração da base de cálculo
    if param.regime == 'LUCRO_PRESUMIDO':
        # Receita Bruta do Mês: Créditos das contas com tipo_dre='RECEITA_BRUTA'
        totais_rec = SaldoMensalConta.unscoped.filter(
            tenant=tenant,
            ano_mes=ano_mes,
            conta__tipo_dre='RECEITA_BRUTA'
        ).aggregate(tot=Sum('creditos'))
        receita_bruta = quantize(totais_rec['tot'] or Decimal('0.00'), 2)

        base_irpj = quantize(receita_bruta * param.presuncao_irpj, 2)
        base_csll = quantize(receita_bruta * param.presuncao_csll, 2)
    elif param.regime == 'LUCRO_REAL':
        # Resultado Operacional antes de IRPJ/CSLL
        totais = SaldoMensalConta.unscoped.filter(
            tenant=tenant,
            ano_mes=ano_mes
        ).exclude(conta__tipo_dre='IMPOSTOS_SOBRE_LUCRO').aggregate(
            rec=Sum('creditos', filter=Q(conta__natureza_saldo='CREDORA')),
            desp=Sum('debitos', filter=Q(conta__natureza_saldo='DEVEDORA'))
        )
        rec = totais['rec'] or Decimal('0.00')
        desp = totais['desp'] or Decimal('0.00')
        lucro_contabil = quantize(rec - desp, 2)
        base_irpj = max(Decimal('0.00'), lucro_contabil)
        base_csll = max(Decimal('0.00'), lucro_contabil)
    else:  # SIMPLES_NACIONAL
        base_irpj = Decimal('0.00')
        base_csll = Decimal('0.00')

    # 3. Cálculo do IRPJ (Básico + Adicional de 10% sobre excedente a R$ 20.000)
    irpj_basico = quantize(base_irpj * param.aliquota_irpj, 2)
    excedente = max(Decimal('0.00'), base_irpj - param.teto_isencao_adicional_mensal)
    irpj_adicional = quantize(excedente * param.aliquota_adicional_irpj, 2)
    valor_irpj = quantize(irpj_basico + irpj_adicional, 2)

    # 4. Cálculo da CSLL (9%)
    valor_csll = quantize(base_csll * param.aliquota_csll, 2)

    if valor_irpj == Decimal('0.00') and valor_csll == Decimal('0.00'):
        return {
            'ano_mes': ano_mes,
            'status': 'SEM_IMPOSTO_DEVIDO',
            'base_irpj': base_irpj,
            'base_csll': base_csll,
            'valor_irpj': Decimal('0.00'),
            'valor_csll': Decimal('0.00'),
            'lancamento_id': None
        }

    # 5. Escrituração Contábil das Partidas Dobradas
    partidas = []
    if valor_irpj > Decimal('0.00'):
        partidas.append({
            'conta_id': param.conta_despesa_irpj_id,
            'tipo_partida': 'DEBITO',
            'valor': valor_irpj
        })
        partidas.append({
            'conta_id': param.conta_passivo_irpj_id,
            'tipo_partida': 'CREDITO',
            'valor': valor_irpj
        })

    if valor_csll > Decimal('0.00'):
        partidas.append({
            'conta_id': param.conta_despesa_csll_id,
            'tipo_partida': 'DEBITO',
            'valor': valor_csll
        })
        partidas.append({
            'conta_id': param.conta_passivo_csll_id,
            'tipo_partida': 'CREDITO',
            'valor': valor_csll
        })

    lancamento, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Provisão Mensal IRPJ e CSLL - Competência {mes:02d}/{ano} ({param.get_regime_display()})",
        partidas=partidas,
        origem_tipo='PROVISAO_IRPJ_CSLL',
        origem_id=ano_mes,
        usuario=usuario
    )

    return {
        'ano_mes': ano_mes,
        'status': 'ESCRITURADO',
        'regime': param.regime,
        'base_irpj': base_irpj,
        'base_csll': base_csll,
        'valor_irpj': valor_irpj,
        'valor_csll': valor_csll,
        'lancamento_id': lancamento.id
    }
