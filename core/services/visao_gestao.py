import datetime
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.modulos import is_modulo_ativo
from core.permissions import user_has_ver_dre
from vendas.models import Venda, AlertaComercial
from produtos.models import (
    Cilindro, MovimentacaoCilindro, TabelaIndenizacaoCilindro
)
from clientes.services import calcular_radar_comodato_tenant


def calcular_periodo_datas(tipo_periodo: str, hoje: datetime.date):
    """
    Retorna (data_inicio, data_fim, data_inicio_ant, data_fim_ant)
    para o período solicitado e o período homólogo anterior para variação percentual.
    """
    if tipo_periodo == 'mes_anterior':
        # Primeiro e último dia do mês anterior
        primeiro_dia_mes_atual = hoje.replace(day=1)
        ultimo_dia_mes_ant = primeiro_dia_mes_atual - datetime.timedelta(days=1)
        data_inicio = ultimo_dia_mes_ant.replace(day=1)
        data_fim = ultimo_dia_mes_ant

        # Mês retrasado como comparativo
        ultimo_dia_mes_retrasado = data_inicio - datetime.timedelta(days=1)
        data_inicio_ant = ultimo_dia_mes_retrasado.replace(day=1)
        data_fim_ant = ultimo_dia_mes_retrasado
    elif tipo_periodo == 'ultimos_30_dias':
        data_inicio = hoje - datetime.timedelta(days=30)
        data_fim = hoje
        data_inicio_ant = data_inicio - datetime.timedelta(days=30)
        data_fim_ant = data_inicio - datetime.timedelta(days=1)
    else:
        # Default: mes_atual até a data de hoje
        data_inicio = hoje.replace(day=1)
        data_fim = hoje

        # Mês anterior homólogo: do dia 1 até o mesmo dia do mês anterior
        primeiro_dia_mes_atual = hoje.replace(day=1)
        ultimo_dia_mes_ant = primeiro_dia_mes_atual - datetime.timedelta(days=1)
        data_inicio_ant = ultimo_dia_mes_ant.replace(day=1)
        # Limita ao número de dias do mês anterior
        dia_ant = min(hoje.day, ultimo_dia_mes_ant.day)
        data_fim_ant = data_inicio_ant.replace(day=dia_ant)

    return data_inicio, data_fim, data_inicio_ant, data_fim_ant


def montar_visao_gestao(tenant: Any, user: Any, tipo_periodo: str = 'mes_atual', request: Any = None) -> dict:
    """
    Constrói a Visão do Negócio unificada para ADMIN e GERENTE.
    Suporta cache de 5 minutos particionado por tenant, período e permissão ver_dre.
    """
    tem_financeiro = is_modulo_ativo(tenant, 'financeiro')
    tem_dre = user_has_ver_dre(request) if request else False
    pode_ver_financeiro = bool(tem_financeiro and tem_dre)

    # Chave de cache inclui a permissão ver_dre para evitar vazamento entre usuários
    cache_key = f"cache_visao_gestao_{tenant.id}_{tipo_periodo}_{int(pode_ver_financeiro)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    agora = timezone.now()
    hoje = agora.date()
    dt_ini, dt_fim, dt_ini_ant, dt_fim_ant = calcular_periodo_datas(tipo_periodo, hoje)

    # --------------------------------------------------------------------------
    # 1. VENDAS & FATURAMENTO
    # Faturamento do período exclui estritamente Cancelada, Pendente e BLOQUEADO_FINANCEIRO.
    # Pedidos com crédito bloqueado são contabilizados em indicador apartado.
    # --------------------------------------------------------------------------
    vendas_periodo_qs = Venda.unscoped.filter(
        tenant=tenant,
        data_venda__date__gte=dt_ini,
        data_venda__date__lte=dt_fim
    )

    vendas_faturadas_qs = vendas_periodo_qs.exclude(
        status__in=['Cancelada', 'Pendente', 'BLOQUEADO_FINANCEIRO']
    )

    aggr_vendas = vendas_faturadas_qs.aggregate(
        total=Sum('valor_total'),
        pedidos_count=Count('id')
    )
    fat_periodo = aggr_vendas['total'] or Decimal('0.00')
    pedidos_faturados_count = aggr_vendas['pedidos_count'] or 0

    ticket_medio = round(fat_periodo / pedidos_faturados_count, 2) if pedidos_faturados_count > 0 else Decimal('0.00')

    # Faturamento no período homólogo anterior para cálculo da variação %
    fat_anterior = Venda.unscoped.filter(
        tenant=tenant,
        data_venda__date__gte=dt_ini_ant,
        data_venda__date__lte=dt_fim_ant
    ).exclude(
        status__in=['Cancelada', 'Pendente', 'BLOQUEADO_FINANCEIRO']
    ).aggregate(total=Sum('valor_total'))['total'] or Decimal('0.00')

    if fat_anterior > 0:
        variacao_fat_pct = round(float((fat_periodo - fat_anterior) / fat_anterior * 100), 1)
    else:
        variacao_fat_pct = None

    # Gráfico diário de faturamento (consulta única agrupada com TruncDate)
    vendas_diarias_qs = vendas_faturadas_qs.annotate(
        dia=TruncDate('data_venda')
    ).values('dia').annotate(
        total=Sum('valor_total')
    ).order_by('dia')

    grafico_faturamento = [
        {'data': v['dia'].isoformat(), 'valor': float(v['total'] or 0)}
        for v in vendas_diarias_qs if v['dia']
    ]

    # Vendas a Prazo × À Vista
    # À vista: PIX, DINHEIRO, CARTAO
    # A prazo: BOLETO, FATURADO, EMPENHO
    vendas_a_vista_total = vendas_faturadas_qs.filter(
        forma_pagamento__in=['PIX', 'DINHEIRO', 'CARTAO']
    ).aggregate(total=Sum('valor_total'))['total'] or Decimal('0.00')

    vendas_a_prazo_total = vendas_faturadas_qs.filter(
        forma_pagamento__in=['BOLETO', 'FATURADO', 'EMPENHO']
    ).aggregate(total=Sum('valor_total'))['total'] or Decimal('0.00')

    # Pedidos Bloqueados por Crédito (BLOQUEADO_FINANCEIRO)
    aggr_bloqueados = vendas_periodo_qs.filter(
        status='BLOQUEADO_FINANCEIRO'
    ).aggregate(
        qtd=Count('id'),
        valor=Sum('valor_total')
    )

    # --------------------------------------------------------------------------
    # 2. PATRIMÔNIO & VALOR DO PARQUE
    # --------------------------------------------------------------------------
    cilindros_ativos_qs = Cilindro.unscoped.filter(tenant=tenant).exclude(status='BAIXADO')
    total_cascos = cilindros_ativos_qs.count()
    cascos_em_clientes = cilindros_ativos_qs.filter(status='EM_POSSE_CLIENTE').count()

    # Valoração com TabelaIndenizacaoCilindro vigente (prioridade) e fallback para valor_aquisicao
    tabelas_indenizacao = list(TabelaIndenizacaoCilindro.unscoped.filter(
        tenant=tenant,
        vigencia_inicio__lte=hoje
    ).filter(
        Q(vigencia_fim__gte=hoje) | Q(vigencia_fim__isnull=True)
    ))
    mapa_indenizacao = {}
    for tib in tabelas_indenizacao:
        chave_tib = (tib.tipo_cilindro_id, tib.gas_id)
        mapa_indenizacao[chave_tib] = tib.valor

    valor_parque_total = Decimal('0.00')
    cascos_avaliados = 0
    cascos_sem_valor = 0

    # Carrega cascos com modelo e gas_dedicado para cálculo de avaliação
    cilindros_dados = cilindros_ativos_qs.values(
        'id', 'modelo_id', 'gas_dedicado_id', 'valor_aquisicao', 'status', 'posse_desde'
    )

    # Contadores de risco patrimonial (cascos retidos > 90d e > 180d)
    limite_90d = agora - datetime.timedelta(days=90)
    limite_180d = agora - datetime.timedelta(days=180)
    cascos_retidos_90d_count = 0
    risco_reais_90d = Decimal('0.00')
    cascos_retidos_180d_count = 0
    risco_reais_180d = Decimal('0.00')

    for c in cilindros_dados:
        # Determina o valor do casco
        v_casco = mapa_indenizacao.get((c['modelo_id'], c['gas_dedicado_id']))
        if v_casco is None or v_casco <= 0:
            v_casco = c['valor_aquisicao']

        if v_casco and v_casco > 0:
            valor_parque_total += v_casco
            cascos_avaliados += 1
            valor_unitario = v_casco
        else:
            cascos_sem_valor += 1
            valor_unitario = Decimal('0.00')

        # Se estiver em posse do cliente, verifica as faixas de risco
        if c['status'] == 'EM_POSSE_CLIENTE' and c['posse_desde']:
            if c['posse_desde'] <= limite_90d:
                cascos_retidos_90d_count += 1
                risco_reais_90d += valor_unitario
            if c['posse_desde'] <= limite_180d:
                cascos_retidos_180d_count += 1
                risco_reais_180d += valor_unitario

    # Estadia a faturar calculada pelo motor determinístico do radar de comodato
    radar_data = calcular_radar_comodato_tenant(tenant)
    estadia_a_faturar = radar_data.get('receita_locacao_acumulada', Decimal('0.00'))

    # --------------------------------------------------------------------------
    # 3. GIRO MÉDIO DO CASCO (CICLOS FECHADOS NOS ÚLTIMOS 90 DIAS)
    # --------------------------------------------------------------------------
    limite_giro_90d = agora - datetime.timedelta(days=90)
    movs_qs = MovimentacaoCilindro.unscoped.filter(
        tenant=tenant,
        ocorrido_em__gte=limite_giro_90d - datetime.timedelta(days=180),  # margem para buscar saídas anteriores
        estorna_movimentacao__isnull=True
    ).exclude(
        estornada_por__isnull=False
    ).select_related('cilindro__gas_dedicado').order_by('cilindro_id', 'ocorrido_em')

    # Agrupa movimentações por cilindro e calcula a permanência de cada ciclo fechado
    movs_por_cilindro = {}
    for m in movs_qs:
        movs_por_cilindro.setdefault(m.cilindro_id, []).append(m)

    duracoes_ciclos = []
    duracoes_por_gas = {}

    for cil_id, lista_movs in movs_por_cilindro.items():
        ultima_saida = None
        for m in lista_movs:
            if m.tipo in ('ENTREGA_CLIENTE', 'SAIDA_ENTREGA'):
                ultima_saida = m
            elif m.tipo in ('RECOLHA_CLIENTE', 'RETORNO_VAZIO') and ultima_saida:
                # O ciclo fechou nos últimos 90 dias
                if m.ocorrido_em >= limite_giro_90d:
                    segundos = (m.ocorrido_em - ultima_saida.ocorrido_em).total_seconds()
                    dias = max(0.0, round(segundos / 86400.0, 1))
                    duracoes_ciclos.append(dias)

                    gas = m.cilindro.gas_dedicado if m.cilindro else None
                    gas_sigla = (gas.sigla or gas.nome) if gas else 'Outros'
                    duracoes_por_gas.setdefault(gas_sigla, []).append(dias)
                ultima_saida = None

    giro_medio_global = round(sum(duracoes_ciclos) / len(duracoes_ciclos), 1) if duracoes_ciclos else 0.0
    giro_por_gas_map = {
        g: round(sum(vals) / len(vals), 1)
        for g, vals in duracoes_por_gas.items() if vals
    }

    # --------------------------------------------------------------------------
    # 4. CONFORMIDADE & RETESTES
    # --------------------------------------------------------------------------
    retestes_vencidos_count = cilindros_ativos_qs.filter(
        data_proximo_reteste__lt=hoje
    ).count()

    retestes_90d_qs = cilindros_ativos_qs.filter(
        data_proximo_reteste__gte=hoje,
        data_proximo_reteste__lte=hoje + datetime.timedelta(days=90)
    )
    retestes_90d_count = retestes_90d_qs.count()

    # Agrupamento mês a mês dos retestes nos próximos 90 dias
    retestes_meses_map = {}
    for d_ret in retestes_90d_qs.values_list('data_proximo_reteste', flat=True):
        if d_ret:
            chave_mes = d_ret.strftime('%m/%Y')
            retestes_meses_map[chave_mes] = retestes_meses_map.get(chave_mes, 0) + 1

    retestes_por_mes = [
        {'mes': k, 'quantidade': v} for k, v in sorted(retestes_meses_map.items())
    ]

    # --------------------------------------------------------------------------
    # 5. NÍVEL DE SERVIÇO (ENTREGAS NO PRAZO)
    # --------------------------------------------------------------------------
    vendas_entregues_qs = vendas_periodo_qs.filter(
        status='Entregue',
        prazo_entrega__isnull=False,
        data_entrega_efetiva__isnull=False
    )
    total_entregues_avaliadas = vendas_entregues_qs.count()

    from django.db.models import F
    entregas_no_prazo_count = vendas_entregues_qs.filter(
        data_entrega_efetiva__lte=F('prazo_entrega')
    ).count()

    if total_entregues_avaliadas > 0:
        nivel_servico_pct = round((entregas_no_prazo_count / total_entregues_avaliadas * 100), 1)
    else:
        nivel_servico_pct = 100.0

    # --------------------------------------------------------------------------
    # 6. CLIENTES EM RISCO DE CHURN
    # --------------------------------------------------------------------------
    alertas_churn_qs = AlertaComercial.unscoped.filter(
        tenant=tenant,
        tipo='RISCO_CHURN',
        resolvido=False
    ).select_related('cliente').order_by('-dias_sem_comprar')

    total_clientes_risco_churn = alertas_churn_qs.count()
    top_5_churn = [
        {
            'cliente_id': a.cliente_id,
            'cliente_nome': a.cliente.nome_fantasia or a.cliente.nome,
            'dias_sem_comprar': a.dias_sem_comprar
        }
        for a in alertas_churn_qs[:5]
    ]

    # --------------------------------------------------------------------------
    # 7. BLOCO FINANCEIRO (CONDICIONAL A MÓDULO E PERMISSÃO VER_DRE)
    # --------------------------------------------------------------------------
    bloco_financeiro = None
    aviso_modulo_financeiro = None

    if pode_ver_financeiro:
        from financeiro.models import ParcelaFinanceira, ContaFinanceira, AlertaCaixa

        # Contas a Receber
        parcelas_receber_abertas = ParcelaFinanceira.unscoped.filter(
            titulo__tenant=tenant,
            titulo__tipo='RECEBER',
            status__in=['ABERTO', 'PARCIAL']
        )
        total_a_receber = parcelas_receber_abertas.aggregate(total=Sum('saldo_em_aberto'))['total'] or Decimal('0.00')

        vencido_inadimplencia = parcelas_receber_abertas.filter(
            data_vencimento__lt=hoje
        ).aggregate(total=Sum('saldo_em_aberto'))['total'] or Decimal('0.00')

        a_vencer_30d = parcelas_receber_abertas.filter(
            data_vencimento__gte=hoje,
            data_vencimento__lte=hoje + datetime.timedelta(days=30)
        ).aggregate(total=Sum('saldo_em_aberto'))['total'] or Decimal('0.00')

        # Top 5 Devedores e cruzamento com retenção de cascos > 90 dias
        devedores_aggr = parcelas_receber_abertas.values(
            'titulo__cliente_id',
            'titulo__cliente__nome',
            'titulo__cliente__nome_fantasia'
        ).annotate(
            total_devido=Sum('saldo_em_aberto')
        ).order_by('-total_devido')[:5]

        clientes_com_casco_90d = set(
            cilindros_ativos_qs.filter(
                status='EM_POSSE_CLIENTE',
                posse_desde__lte=limite_90d,
                cliente_posse_atual__isnull=False
            ).values_list('cliente_posse_atual_id', flat=True)
        )

        top_devedores = [
            {
                'cliente_id': d['titulo__cliente_id'],
                'cliente_nome': d['titulo__cliente__nome_fantasia'] or d['titulo__cliente__nome'],
                'total_devido': float(d['total_devido']),
                'tem_casco_retido_90d': d['titulo__cliente_id'] in clientes_com_casco_90d
            }
            for d in devedores_aggr
        ]

        # Caixa (Saldo das contas ativas)
        contas_ativas = list(ContaFinanceira.unscoped.filter(tenant=tenant, ativo=True))
        saldo_caixa_total = sum((c.saldo_atual for c in contas_ativas), Decimal('0.00'))

        alerta_caixa_obj = AlertaCaixa.unscoped.filter(
            tenant=tenant,
            resolvido=False
        ).order_by('-data_alerta').first()

        alerta_caixa_info = None
        if alerta_caixa_obj:
            alerta_caixa_info = {
                'data_menor_saldo': alerta_caixa_obj.data_menor_saldo.isoformat() if alerta_caixa_obj.data_menor_saldo else None,
                'menor_saldo_projetado': float(alerta_caixa_obj.menor_saldo_projetado or 0),
                'saldo_minimo_configurado': float(alerta_caixa_obj.saldo_minimo_configurado or 0)
            }

        # Contas a Pagar (próximos 7 dias)
        a_pagar_7d = ParcelaFinanceira.unscoped.filter(
            titulo__tenant=tenant,
            titulo__tipo='PAGAR',
            status__in=['ABERTO', 'PARCIAL'],
            data_vencimento__gte=hoje,
            data_vencimento__lte=hoje + datetime.timedelta(days=7)
        ).aggregate(total=Sum('saldo_em_aberto'))['total'] or Decimal('0.00')

        bloco_financeiro = {
            'a_receber': {
                'total_em_aberto': float(total_a_receber),
                'vencido_inadimplencia': float(vencido_inadimplencia),
                'a_vencer_30_dias': float(a_vencer_30d)
            },
            'top_devedores': top_devedores,
            'caixa': {
                'saldo_total_disponivel': float(saldo_caixa_total),
                'alerta_caixa': alerta_caixa_info
            },
            'a_pagar': {
                'proximos_7_dias': float(a_pagar_7d)
            }
        }
    else:
        aviso_modulo_financeiro = (
            "Contas a receber, inadimplência e fluxo de caixa ficam disponíveis com a ativação do módulo Financeiro."
        )

    dados = {
        'periodo': {
            'tipo': tipo_periodo,
            'inicio': dt_ini.isoformat(),
            'fim': dt_fim.isoformat()
        },
        'vendas': {
            'faturamento_periodo': float(fat_periodo),
            'variacao_faturamento_pct': variacao_fat_pct,
            'total_pedidos_faturados': pedidos_faturados_count,
            'ticket_medio': float(ticket_medio),
            'vendas_a_prazo': float(vendas_a_prazo_total),
            'vendas_a_vista': float(vendas_a_vista_total),
            'pedidos_bloqueados_credito': {
                'quantidade': aggr_bloqueados['qtd'] or 0,
                'valor_total': float(aggr_bloqueados['valor'] or 0)
            },
            'grafico_diario': grafico_faturamento
        },
        'patrimonio': {
            'total_cascos': total_cascos,
            'cascos_avaliados': cascos_avaliados,
            'cascos_sem_valor': cascos_sem_valor,
            'valor_parque_total': float(valor_parque_total),
            'cascos_em_clientes': cascos_em_clientes,
            'risco_reais_90d': float(risco_reais_90d),
            'cascos_retidos_90d_count': cascos_retidos_90d_count,
            'risco_reais_180d': float(risco_reais_180d),
            'cascos_retidos_180d_count': cascos_retidos_180d_count,
            'estadia_a_faturar': float(estadia_a_faturar)
        },
        'giro_casco': {
            'giro_medio_dias': giro_medio_global,
            'ciclos_fechados_avaliados': len(duracoes_ciclos),
            'giro_por_gas': giro_por_gas_map
        },
        'conformidade': {
            'retestes_vencidos': retestes_vencidos_count,
            'retestes_90_dias': retestes_90d_count,
            'retestes_por_mes': retestes_por_mes
        },
        'nivel_servico': {
            'total_entregas_avaliadas': total_entregues_avaliadas,
            'entregas_no_prazo': entregas_no_prazo_count,
            'percentual_no_prazo': nivel_servico_pct
        },
        'risco_churn': {
            'total_clientes_em_risco': total_clientes_risco_churn,
            'top_5_clientes': top_5_churn
        },
        'financeiro': bloco_financeiro,
        'aviso_modulo_financeiro': aviso_modulo_financeiro
    }

    # Guarda no cache por 300 segundos (5 minutos)
    cache.set(cache_key, dados, timeout=300)
    return dados
