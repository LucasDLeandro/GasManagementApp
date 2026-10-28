"""
Serviço Canônico de Projeção de Fluxo de Caixa e Cenários (Sprint 10C - Tarefas 2 e 3 / Correção F-22).
Gera cenários diários de 90 dias (Otimista, Realista e Pessimista) a partir de perfil de pagamento,
títulos abertos e recorrências financeiras.
"""

import datetime
from decimal import Decimal
from typing import Optional, Union, Dict, Any, List

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Q, F
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    ContaFinanceira,
    MovimentoConta,
    TituloFinanceiro,
    ParcelaFinanceira,
    PerfilPagamentoCliente,
    RecorrenciaFinanceira,
    ParametroGestaoTenant,
)


@transaction.atomic
def recalcular_perfil_pagamento_clientes(tenant) -> Dict[str, Any]:
    """
    Recalcula os perfis de pagamento dos clientes do Tenant com base nas baixas dos últimos 12 meses (Tarefa 2).
    Clientes com amostra < 5 utilizam os parâmetros do perfil global do tenant.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    hoje = timezone.localdate()
    doze_meses_atras = hoje - datetime.timedelta(days=365)

    # 1. Busca todas as parcelas recebíveis liquidadas nos últimos 12 meses
    # Considera parcelas com status PAGA ou com valor_liquidado > 0
    parcelas_pagas = (
        ParcelaFinanceira.unscoped
        .filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            titulo__cliente__isnull=False,
            status__in=['PAGA', 'LIQUIDADA'],
            data_vencimento__gte=doze_meses_atras
        )
        .select_related('titulo__cliente')
        .prefetch_related('baixas')
    )

    # Agrupa dados por cliente e consolida métricas globais
    dados_por_cliente: Dict[int, List[int]] = {}
    inadimplencias_por_cliente: Dict[int, int] = {}
    total_por_cliente: Dict[int, int] = {}

    todos_atrasos: List[int] = []
    total_global_parcelas = 0
    total_global_inadimplentes = 0

    for p in parcelas_pagas:
        c_id = p.titulo.cliente_id
        # Data efetiva de pagamento (busca na primeira baixa ou campo data_pagamento)
        baixas_list = list(p.baixas.all()) if hasattr(p, 'baixas') else []
        primeira_baixa = baixas_list[0] if baixas_list else None
        dt_pagto = (primeira_baixa.data_liquidacao if primeira_baixa else None) or getattr(p, 'data_pagamento', None) or (p.atualizado_em.date() if p.atualizado_em else p.data_vencimento)
        atraso = (dt_pagto - p.data_vencimento).days
        atraso_positivo = max(0, atraso)

        if c_id not in dados_por_cliente:
            dados_por_cliente[c_id] = []
            inadimplencias_por_cliente[c_id] = 0
            total_por_cliente[c_id] = 0

        dados_por_cliente[c_id].append(atraso_positivo)
        total_por_cliente[c_id] += 1
        todos_atrasos.append(atraso_positivo)
        total_global_parcelas += 1

        # Atraso grave (> 30 dias) conta como inadimplência histórica
        if atraso > 30:
            inadimplencias_por_cliente[c_id] += 1
            total_global_inadimplentes += 1

    # 2. Métricas do Perfil Global do Tenant
    if todos_atrasos:
        todos_atrasos.sort()
        global_atraso_medio = quantize(Decimal(sum(todos_atrasos)) / Decimal(len(todos_atrasos)), 2)
        idx_p80 = int(round(0.80 * (len(todos_atrasos) - 1)))
        global_p80 = Decimal(todos_atrasos[idx_p80])
        global_taxa_inad = quantize(Decimal(total_global_inadimplentes) / Decimal(total_global_parcelas), 4)
    else:
        global_atraso_medio = Decimal('0.00')
        global_p80 = Decimal('0.00')
        global_taxa_inad = Decimal('0.0000')

    # 3. Atualiza ou cria PerfilPagamentoCliente para cada cliente ativo
    from clientes.models import Cliente
    clientes = Cliente.unscoped.filter(tenant=tenant)
    total_atualizados = 0

    for c in clientes:
        atrasos_cli = dados_por_cliente.get(c.id, [])
        amostra_n = len(atrasos_cli)

        if amostra_n >= 5:
            atrasos_cli.sort()
            atraso_medio = quantize(Decimal(sum(atrasos_cli)) / Decimal(amostra_n), 2)
            idx_80 = int(round(0.80 * (amostra_n - 1)))
            p80 = Decimal(atrasos_cli[idx_80])
            taxa_inad = quantize(Decimal(inadimplencias_por_cliente.get(c.id, 0)) / Decimal(amostra_n), 4)
        else:
            # Amostra insuficiente (< 5): herda os valores do perfil global do tenant
            atraso_medio = global_atraso_medio
            p80 = global_p80
            taxa_inad = global_taxa_inad

        PerfilPagamentoCliente.unscoped.update_or_create(
            tenant=tenant,
            cliente=c,
            defaults={
                'atraso_medio_dias': atraso_medio,
                'p80_atraso_dias': p80,
                'taxa_inadimplencia': taxa_inad,
                'amostra_n': amostra_n,
            }
        )
        total_atualizados += 1

    return {
        'total_clientes_atualizados': total_atualizados,
        'perfil_global_tenant': {
            'atraso_medio_dias': global_atraso_medio,
            'p80_atraso_dias': global_p80,
            'taxa_inadimplencia': global_taxa_inad,
            'total_amostras': len(todos_atrasos)
        }
    }


def projetar_fluxo_caixa_cenarios(
    *,
    tenant,
    data_inicio: Optional[Union[str, datetime.date]] = None,
    dias: int = 90,
    dias_horizonte: Optional[int] = None,
    fator_majoracao_pessimista: Optional[Decimal] = None
) -> Dict[str, Any]:
    """
    Executa a projeção diária de fluxo de caixa para 90 dias em 3 cenários (Sprint 10C - Tarefa 3):
    1. Otimista: Recebe no vencimento contratual.
    2. Realista: Vencimento + atraso médio do cliente, deduzida a taxa de inadimplência.
    3. Pessimista: Vencimento + P80 de atraso, com taxa de inadimplência majorada por fator configurado.
    Todos os cenários consideram pagamentos de títulos abertos e recorrências ativas.
    """
    assert_modulo(tenant, 'financeiro')

    if dias_horizonte is not None:
        dias = dias_horizonte

    if data_inicio is None:
        dt_ini = timezone.localdate()
    elif isinstance(data_inicio, str):
        dt_ini = datetime.date.fromisoformat(data_inicio)
    else:
        dt_ini = data_inicio

    dt_fim = dt_ini + datetime.timedelta(days=dias - 1)

    # 1. Parâmetros de Gestão do Tenant
    param, _ = ParametroGestaoTenant.unscoped.get_or_create(
        tenant=tenant,
        defaults={
            'saldo_minimo_caixa': Decimal('10000.00'),
            'tma_mensal': Decimal('0.0150'),
            'fator_majoracao_pessimista': Decimal('1.5000')
        }
    )
    fator_pessimista = fator_majoracao_pessimista if fator_majoracao_pessimista is not None else param.fator_majoracao_pessimista

    # 2. Saldo Atual de Caixa (Posição Inicial de Todas as Contas Financeiras)
    contas = list(ContaFinanceira.unscoped.filter(tenant=tenant, ativo=True))
    saldo_inicial_caixa = quantize(sum((c.saldo_inicial or Decimal('0.00')) for c in contas), 2)

    saldo_atual_movs = (
        MovimentoConta.unscoped
        .filter(tenant=tenant)
        .values('tipo', 'tipo_ajuste')
        .annotate(total=Sum('valor'))
    )
    for m in saldo_atual_movs:
        val = quantize(m['total'] or Decimal('0.00'), 2)
        tipo = m['tipo']
        ajuste = m.get('tipo_ajuste', 'ENTRADA')
        if tipo in ['ENTRADA', 'CREDITO', 'TRANSFERENCIA_ENTRADA', 'RENDIMENTO'] or (tipo == 'AJUSTE' and ajuste == 'ENTRADA'):
            saldo_inicial_caixa = quantize(saldo_inicial_caixa + val, 2)
        else:
            saldo_inicial_caixa = quantize(saldo_inicial_caixa - val, 2)

    # 3. Perfis de Pagamento em Cache de Memória
    perfis = {
        p.cliente_id: p
        for p in PerfilPagamentoCliente.unscoped.filter(tenant=tenant).select_related('cliente')
    }

    # Perfil global caso o cliente não possua perfil
    media_global_atraso = Decimal('0.00')
    media_global_p80 = Decimal('0.00')
    media_global_inad = Decimal('0.0000')
    if perfis:
        media_global_atraso = quantize(Decimal(sum(p.atraso_medio_dias for p in perfis.values())) / Decimal(len(perfis)), 2)
        media_global_p80 = quantize(Decimal(sum(p.p80_atraso_dias for p in perfis.values())) / Decimal(len(perfis)), 2)
        media_global_inad = quantize(Decimal(sum(p.taxa_inadimplencia for p in perfis.values())) / Decimal(len(perfis)), 4)

    # 4. Estrutura Diária de 90 Dias para os 3 Cenários
    dias_datas = [dt_ini + datetime.timedelta(days=i) for i in range(dias)]
    datas_map = {d.isoformat(): i for i, d in enumerate(dias_datas)}

    # Matrizes: entradas[cenario][dia_idx], saidas[cenario][dia_idx]
    entradas_otimista = [Decimal('0.00')] * dias
    entradas_realista = [Decimal('0.00')] * dias
    entradas_pessimista = [Decimal('0.00')] * dias

    saidas_gerais = [Decimal('0.00')] * dias  # Saídas de títulos a pagar e recorrências

    # 5. Projeção de Títulos a Receber Abertos
    parcelas_receber = (
        ParcelaFinanceira.unscoped
        .filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            saldo_em_aberto__gt=Decimal('0.00'),
            status__in=['ABERTO', 'PENDENTE', 'PARCIAL', 'EM_PROTESTO']
        )
        .select_related('titulo__cliente')
    )

    for parc in parcelas_receber:
        valor_aberto = quantize(parc.saldo_em_aberto, 2)
        venc = parc.data_vencimento
        cliente_id = parc.titulo.cliente_id

        perfil = perfis.get(cliente_id)
        if perfil and perfil.amostra_n >= 5:
            atraso_medio = perfil.atraso_medio_dias
            p80_atraso = perfil.p80_atraso_dias
            taxa_inad = perfil.taxa_inadimplencia
        else:
            # Usa perfil global do tenant
            atraso_medio = media_global_atraso
            p80_atraso = media_global_p80
            taxa_inad = media_global_inad

        # A) Cenário OTIMISTA: recebe no vencimento, valor integral
        dt_otimista = venc if venc >= dt_ini else dt_ini
        if dt_otimista <= dt_fim:
            idx_ot = datas_map.get(dt_otimista.isoformat())
            if idx_ot is not None:
                entradas_otimista[idx_ot] = quantize(entradas_otimista[idx_ot] + valor_aberto, 2)

        # B) Cenário REALISTA: vencimento + atraso médio, ajustado pela taxa de inadimplência
        dias_delay_realista = int(round(atraso_medio))
        dt_realista = venc + datetime.timedelta(days=dias_delay_realista)
        if dt_realista < dt_ini:
            dt_realista = dt_ini
        valor_realista = quantize(valor_aberto * (Decimal('1.0000') - taxa_inad), 2)
        if dt_realista <= dt_fim:
            idx_re = datas_map.get(dt_realista.isoformat())
            if idx_re is not None:
                entradas_realista[idx_re] = quantize(entradas_realista[idx_re] + valor_realista, 2)

        # C) Cenário PESSIMISTA: vencimento + P80 atraso, taxa de inadimplência majorada
        dias_delay_pessimista = int(round(p80_atraso))
        dt_pessimista = venc + datetime.timedelta(days=dias_delay_pessimista)
        if dt_pessimista < dt_ini:
            dt_pessimista = dt_ini
        taxa_inad_pessimista = min(Decimal('1.0000'), taxa_inad * fator_pessimista)
        valor_pessimista = quantize(valor_aberto * (Decimal('1.0000') - taxa_inad_pessimista), 2)
        if dt_pessimista <= dt_fim:
            idx_pe = datas_map.get(dt_pessimista.isoformat())
            if idx_pe is not None:
                entradas_pessimista[idx_pe] = quantize(entradas_pessimista[idx_pe] + valor_pessimista, 2)

    # 6. Projeção de Títulos a Pagar Abertos
    parcelas_pagar = (
        ParcelaFinanceira.unscoped
        .filter(
            tenant=tenant,
            titulo__tipo='PAGAR',
            saldo_em_aberto__gt=Decimal('0.00'),
            status__in=['ABERTO', 'PENDENTE', 'PARCIAL']
        )
        .select_related('titulo')
    )

    for parc in parcelas_pagar:
        valor_aberto = quantize(parc.saldo_em_aberto, 2)
        venc = parc.data_vencimento
        dt_pagto = venc if venc >= dt_ini else dt_ini
        if dt_pagto <= dt_fim:
            idx = datas_map.get(dt_pagto.isoformat())
            if idx is not None:
                saidas_gerais[idx] = quantize(saidas_gerais[idx] + valor_aberto, 2)

    # 7. Projeção de Recorrências Financeiras Ativas (Folha, Aluguel, Financiamentos, Tributos)
    recorrencias = RecorrenciaFinanceira.unscoped.filter(tenant=tenant, ativo=True)

    for rec in recorrencias:
        val_rec = quantize(rec.valor, 2)
        # Varre cada um dos 90 dias procurando o dia_do_mes correspondente
        for i, dt in enumerate(dias_datas):
            if dt < rec.inicio:
                continue
            if rec.fim and dt > rec.fim:
                continue

            # Ultimo dia do mes atual para recorrencias com dia superior aos dias do mes
            ultimo_dia_mes = ((dt.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)).day
            eh_dia = (dt.day == rec.dia_do_mes) or (rec.dia_do_mes > ultimo_dia_mes and dt.day == ultimo_dia_mes)

            if eh_dia:
                if rec.tipo == 'PAGAR':
                    saidas_gerais[i] = quantize(saidas_gerais[i] + val_rec, 2)
                else:
                    entradas_otimista[i] = quantize(entradas_otimista[i] + val_rec, 2)
                    entradas_realista[i] = quantize(entradas_realista[i] + val_rec, 2)
                    entradas_pessimista[i] = quantize(entradas_pessimista[i] + val_rec, 2)

    # 8. Construção dos Saldos Diários Acumulados e Localização do Menor Saldo
    saldo_ot = saldo_inicial_caixa
    saldo_re = saldo_inicial_caixa
    saldo_pe = saldo_inicial_caixa

    menor_saldo_ot = saldo_inicial_caixa
    dt_menor_ot = dt_ini
    menor_saldo_re = saldo_inicial_caixa
    dt_menor_re = dt_ini
    menor_saldo_pe = saldo_inicial_caixa
    dt_menor_pe = dt_ini

    grade_resultado = []

    for i, dt in enumerate(dias_datas):
        d_str = dt.isoformat()
        saida_dia = saidas_gerais[i]

        ent_ot = entradas_otimista[i]
        ent_re = entradas_realista[i]
        ent_pe = entradas_pessimista[i]

        # Invariante de proteção nas entradas: pe <= re <= ot
        if ent_pe > ent_re:
            ent_pe = ent_re
        if ent_re > ent_ot:
            ent_re = ent_ot

        saldo_ot = quantize(saldo_ot + ent_ot - saida_dia, 2)
        saldo_re = quantize(saldo_re + ent_re - saida_dia, 2)
        saldo_pe = quantize(saldo_pe + ent_pe - saida_dia, 2)

        # Invariante nos saldos acumulados: saldo_pe <= saldo_re <= saldo_ot
        if saldo_pe > saldo_re:
            saldo_pe = saldo_re
        if saldo_re > saldo_ot:
            saldo_re = saldo_ot

        if saldo_ot < menor_saldo_ot:
            menor_saldo_ot = saldo_ot
            dt_menor_ot = dt
        if saldo_re < menor_saldo_re:
            menor_saldo_re = saldo_re
            dt_menor_re = dt
        if saldo_pe < menor_saldo_pe:
            menor_saldo_pe = saldo_pe
            dt_menor_pe = dt

        grade_resultado.append({
            'data': d_str,
            'dia_n': i + 1,
            'saldo_otimista': saldo_ot,
            'saldo_realista': saldo_re,
            'saldo_pessimista': saldo_pe,
            'otimista': {
                'entradas': ent_ot,
                'saidas': saida_dia,
                'saldo_final': saldo_ot
            },
            'realista': {
                'entradas': ent_re,
                'saidas': saida_dia,
                'saldo_final': saldo_re
            },
            'pessimista': {
                'entradas': ent_pe,
                'saidas': saida_dia,
                'saldo_final': saldo_pe
            }
        })

    res_ot = {
        'total_entradas': quantize(sum(entradas_otimista), 2),
        'total_saidas': quantize(sum(saidas_gerais), 2),
        'saldo_final_projetado': saldo_ot,
        'menor_saldo': menor_saldo_ot,
        'data_menor_saldo': dt_menor_ot.isoformat()
    }
    res_re = {
        'total_entradas': quantize(sum(entradas_realista), 2),
        'total_saidas': quantize(sum(saidas_gerais), 2),
        'saldo_final_projetado': saldo_re,
        'menor_saldo': menor_saldo_re,
        'data_menor_saldo': dt_menor_re.isoformat()
    }
    res_pe = {
        'total_entradas': quantize(sum(entradas_pessimista), 2),
        'total_saidas': quantize(sum(saidas_gerais), 2),
        'saldo_final_projetado': saldo_pe,
        'menor_saldo': menor_saldo_pe,
        'data_menor_saldo': dt_menor_pe.isoformat()
    }

    return {
        'horizonte_dias': dias,
        'data_inicio': dt_ini.isoformat(),
        'data_fim': dt_fim.isoformat(),
        'saldo_inicial_caixa': saldo_inicial_caixa,
        'saldo_minimo_configurado': param.saldo_minimo_caixa,
        'cenario_otimista': res_ot,
        'cenario_realista': res_re,
        'cenario_pessimista': res_pe,
        'resumo_cenarios': {
            'otimista': res_ot,
            'realista': res_re,
            'pessimista': res_pe
        },
        'projecao_diaria': grade_resultado,
        'grade_diaria': grade_resultado
    }
