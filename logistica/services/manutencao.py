from decimal import Decimal
from django.utils import timezone
from django.db import models
from django.db.models import Sum, Count, Q, Min, Max
from logistica.models import (
    Veiculo,
    PlanoManutencao,
    OrdemServico,
    OSItem,
    ChecklistModelo,
    ChecklistExecucao,
    Abastecimento,
    Entrega
)


def processar_alertas_manutencao(tenant=None):
    """
    Varre os planos de manutenção preventiva ativos e gera alertas e Ordens de Serviço (OS)
    preventivas automaticamente.
    Operação estritamente idempotente: nunca duplica OS aberta para o mesmo plano preventivo.
    """
    qs = PlanoManutencao.objects.filter(ativo=True, veiculo__status_ativo='Ativo')
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.filter(tenant__ativo=True)

    qs = qs.select_related('veiculo', 'tenant', 'fornecedor_preferido')

    hoje = timezone.localdate()
    planos_analisados = 0
    alertas_gerados = []
    ordens_criadas = []

    for plano in qs:
        planos_analisados += 1
        odometro_veiculo = getattr(plano.veiculo, 'odometro_atual_km', Decimal('0.00')) or Decimal('0.00')
        resultado = plano.calcular_status_vencimento(odometro_atual=odometro_veiculo, data_referencia=hoje)

        if resultado['vencido'] or resultado['alerta']:
            # Verifica idempotência: se já existe OS aberta, orçada, aprovada ou em execução para este plano
            os_em_aberto = OrdemServico.objects.filter(
                plano=plano,
                status__in=['Aberta', 'Orçada', 'Aprovada', 'Em Execução']
            ).first()

            if resultado['vencido'] and not os_em_aberto:
                # Criação automática de OS preventiva
                prioridade = 'Alta' if 'Km atingido' in resultado['motivo'] else 'Normal'
                desc = (
                    f"Manutenção Preventiva Automática gerada pelo Plano '{plano.descricao}'.\n"
                    f"Gatilho: {resultado['motivo']}.\n"
                    f"Odômetro do veículo: {odometro_veiculo:.0f} km. Data: {hoje.strftime('%d/%m/%Y')}."
                )

                nova_os = OrdemServico.objects.create(
                    tenant=plano.tenant,
                    veiculo=plano.veiculo,
                    tipo='Preventiva',
                    origem='Plano',
                    plano=plano,
                    prioridade=prioridade,
                    status='Aberta',
                    imobiliza_veiculo=False,
                    descricao_problema=desc,
                    fornecedor=plano.fornecedor_preferido,
                    odometro_entrada=odometro_veiculo,
                    custo_total=plano.custo_estimado or Decimal('0.00'),
                    custo_mao_de_obra=plano.custo_estimado or Decimal('0.00'),
                    observacoes="Abertura automática via rotina do motor de manutenção preventiva."
                )
                ordens_criadas.append({
                    'os_id': nova_os.id,
                    'numero': nova_os.numero,
                    'veiculo': plano.veiculo.placa,
                    'plano': plano.descricao,
                    'motivo': resultado['motivo']
                })
            else:
                alertas_gerados.append({
                    'plano_id': plano.id,
                    'veiculo': plano.veiculo.placa,
                    'plano': plano.descricao,
                    'status': resultado['status'],
                    'motivo': resultado['motivo'],
                    'os_existente': os_em_aberto.numero if os_em_aberto else None
                })

    return {
        'planos_analisados': planos_analisados,
        'ordens_criadas': ordens_criadas,
        'total_ordens_criadas': len(ordens_criadas),
        'os_geradas': len(ordens_criadas),
        'alertas_gerados': alertas_gerados,
        'total_alertas': len(alertas_gerados)
    }


def calcular_indicadores_manutencao(tenant, data_inicio=None, data_fim=None, percentual_substituicao_fipe=Decimal('30.00')):
    """
    Calcula indicadores consolidados de manutenção e frota para o tenant e período informado:
    - Custo total e custo por km
    - TCO por veículo (manutenção + combustível da L2)
    - MTBF (Mean Time Between Failures)
    - MTTR (Mean Time To Repair)
    - Disponibilidade da frota (%)
    - Proporção Preventiva vs. Corretiva (quantidade e custo)
    - Ranking dos veículos mais caros
    - Alerta 'Avaliar Substituição' quando custo anual > X% (padrão 30%) da tabela FIPE
    """
    hoje = timezone.localdate()
    if not data_fim:
        data_fim = hoje
    if not data_inicio:
        data_inicio = data_fim - timezone.timedelta(days=365)

    dias_periodo = max(1, (data_fim - data_inicio).days)

    # Ordens de serviço no período
    os_periodo_qs = OrdemServico.objects.filter(
        tenant=tenant,
        data_abertura__date__gte=data_inicio,
        data_abertura__date__lte=data_fim
    )

    os_concluidas_qs = os_periodo_qs.filter(status='Concluída')

    # Custos de Manutenção
    custo_total_manutencao = os_concluidas_qs.aggregate(total=Sum('custo_total'))['total'] or Decimal('0.00')
    custo_pecas = os_concluidas_qs.aggregate(total=Sum('custo_pecas'))['total'] or Decimal('0.00')
    custo_mao_de_obra = os_concluidas_qs.aggregate(total=Sum('custo_mao_de_obra'))['total'] or Decimal('0.00')
    custo_terceiros = os_concluidas_qs.aggregate(total=Sum('custo_terceiros'))['total'] or Decimal('0.00')

    # Km rodados no período (a partir dos abastecimentos e/ou odômetros)
    abastecimentos_qs = Abastecimento.objects.filter(
        tenant=tenant,
        data_hora__date__gte=data_inicio,
        data_hora__date__lte=data_fim
    )
    km_rodados_total = abastecimentos_qs.aggregate(total=Sum('km_rodados_desde_anterior'))['total'] or 0

    # Fallback se não houver registros de km rodados em abastecimentos
    if km_rodados_total <= 0:
        km_calc = 0
        veiculos_com_os = os_concluidas_qs.values('veiculo').distinct()
        for v_dict in veiculos_com_os:
            v_id = v_dict['veiculo']
            max_km = os_concluidas_qs.filter(veiculo_id=v_id).aggregate(m=Max('odometro_saida'))['m'] or 0
            min_km = os_concluidas_qs.filter(veiculo_id=v_id).aggregate(m=Min('odometro_entrada'))['m'] or 0
            if max_km > min_km:
                km_calc += (max_km - min_km)
        km_rodados_total = km_calc

    custo_por_km = Decimal('0.0000')
    if km_rodados_total > 0:
        custo_por_km = round(custo_total_manutencao / Decimal(str(km_rodados_total)), 4)

    # Proporção Preventiva vs. Corretiva
    preventivas_qs = os_concluidas_qs.filter(tipo='Preventiva')
    corretivas_qs = os_concluidas_qs.filter(tipo='Corretiva')
    outras_qs = os_concluidas_qs.exclude(tipo__in=['Preventiva', 'Corretiva'])

    qtd_preventiva = preventivas_qs.count()
    qtd_corretiva = corretivas_qs.count()
    qtd_outras = outras_qs.count()
    qtd_total_concluidas = os_concluidas_qs.count()

    custo_preventiva = preventivas_qs.aggregate(total=Sum('custo_total'))['total'] or Decimal('0.00')
    custo_corretiva = corretivas_qs.aggregate(total=Sum('custo_total'))['total'] or Decimal('0.00')

    pct_qtd_preventiva = round((qtd_preventiva / qtd_total_concluidas * 100), 1) if qtd_total_concluidas > 0 else 0.0
    pct_qtd_corretiva = round((qtd_corretiva / qtd_total_concluidas * 100), 1) if qtd_total_concluidas > 0 else 0.0
    pct_custo_preventiva = round(float(custo_preventiva / custo_total_manutencao * 100), 1) if custo_total_manutencao > 0 else 0.0
    pct_custo_corretiva = round(float(custo_corretiva / custo_total_manutencao * 100), 1) if custo_total_manutencao > 0 else 0.0

    # MTBF (Mean Time Between Failures) e MTTR (Mean Time To Repair)
    # MTTR: Duração média de reparo das manutenções corretivas (em horas)
    duracoes_horas = []
    for os_c in corretivas_qs.exclude(data_conclusao__isnull=True):
        inicio_os = os_c.data_entrada or os_c.data_abertura
        if os_c.data_conclusao and inicio_os and os_c.data_conclusao > inicio_os:
            horas = (os_c.data_conclusao - inicio_os).total_seconds() / 3600.0
            duracoes_horas.append(horas)

    mttr_horas = round(sum(duracoes_horas) / len(duracoes_horas), 1) if duracoes_horas else 0.0

    # MTBF: Tempo médio operacional entre falhas corretivas (em dias)
    # Se houver corretivas, calcula o intervalo médio entre quebras consecutivas de cada veículo
    intervalos_dias = []
    veiculos_ids = list(corretivas_qs.values_list('veiculo_id', flat=True).distinct())
    for vid in veiculos_ids:
        datas_corretivas = list(
            corretivas_qs.filter(veiculo_id=vid)
            .order_by('data_abertura')
            .values_list('data_abertura', flat=True)
        )
        if len(datas_corretivas) > 1:
            for i in range(1, len(datas_corretivas)):
                dias = (datas_corretivas[i].date() - datas_corretivas[i-1].date()).days
                intervalos_dias.append(max(1, dias))
        elif len(datas_corretivas) == 1:
            dias = max(1, (data_fim - datas_corretivas[0].date()).days)
            intervalos_dias.append(dias)

    mtbf_dias = round(sum(intervalos_dias) / len(intervalos_dias), 1) if intervalos_dias else float(dias_periodo)

    # Disponibilidade da Frota (%)
    # Dias operacionais totais = veículos ativos * dias do período
    veiculos_frota_qs = Veiculo.objects.filter(tenant=tenant, status_ativo__in=['Ativo', 'Reserva', 'Em Manutenção'])
    total_veiculos = veiculos_frota_qs.count()

    dias_totais_frota = max(1, total_veiculos * dias_periodo)

    # Dias em oficina com imobilização
    dias_imobilizados = 0.0
    os_imobilizantes = os_periodo_qs.filter(imobiliza_veiculo=True)
    for os_imob in os_imobilizantes:
        dt_inicio = (os_imob.data_entrada or os_imob.data_abertura).date()
        dt_fim = os_imob.data_conclusao.date() if os_imob.data_conclusao else data_fim
        dt_inicio_ajustada = max(dt_inicio, data_inicio)
        dt_fim_ajustada = min(dt_fim, data_fim)
        if dt_fim_ajustada >= dt_inicio_ajustada:
            dias_imobilizados += (dt_fim_ajustada - dt_inicio_ajustada).days + 1

    disponibilidade_pct = round(max(0.0, min(100.0, ((dias_totais_frota - dias_imobilizados) / dias_totais_frota) * 100.0)), 1)

    # Custo Total de Propriedade (TCO) por Veículo e Ranking dos mais caros
    todos_veiculos = Veiculo.objects.filter(tenant=tenant)
    ranking_veiculos = []
    alertas_substituicao = []

    for v in todos_veiculos:
        # Manutenção do veículo no período
        custo_manut_v = os_concluidas_qs.filter(veiculo=v).aggregate(total=Sum('custo_total'))['total'] or Decimal('0.00')
        # Combustível da L2 no período
        custo_comb_v = abastecimentos_qs.filter(veiculo=v).aggregate(total=Sum('valor_total'))['total'] or Decimal('0.00')
        # Km do veículo no período
        km_v = abastecimentos_qs.filter(veiculo=v).aggregate(total=Sum('km_rodados_desde_anterior'))['total'] or 0
        if km_v <= 0:
            max_km = os_concluidas_qs.filter(veiculo=v).aggregate(m=Max('odometro_saida'))['m'] or 0
            min_km = os_concluidas_qs.filter(veiculo=v).aggregate(m=Min('odometro_entrada'))['m'] or 0
            km_v = max(0, max_km - min_km)

        tco_v = custo_manut_v + custo_comb_v
        custo_km_v = round(tco_v / Decimal(str(km_v)), 4) if km_v > 0 else Decimal('0.0000')

        ranking_veiculos.append({
            'veiculo_id': v.id,
            'placa': v.placa,
            'modelo': f"{v.marca} {v.modelo}",
            'ano': v.ano,
            'custo_manutencao': float(custo_manut_v),
            'custo_combustivel': float(custo_comb_v),
            'tco_total': float(tco_v),
            'km_rodados': km_v,
            'custo_por_km': float(custo_km_v),
            'fipe_valor': float(v.fipe_valor or (v.historico_fipe.order_by('-registrado_em').first().valor if v.historico_fipe.exists() else 0.0))
        })

        # Alerta 'Avaliar Substituição' se custo anual de manutenção > X% do valor FIPE
        fipe_val = v.fipe_valor
        if not fipe_val or fipe_val == Decimal('0.00'):
            ultimo_fipe = v.historico_fipe.order_by('-registrado_em').first()
            if ultimo_fipe:
                fipe_val = ultimo_fipe.valor
        fipe_val = fipe_val or Decimal('0.00')
        if fipe_val > Decimal('0.00'):
            # Anualiza o custo de manutenção caso período seja diferente de 365 dias
            custo_anual_estimado = (custo_manut_v / Decimal(str(dias_periodo))) * Decimal('365')
            pct_atingido = round(float((custo_anual_estimado / fipe_val) * 100), 1)
            limite_pct = float(percentual_substituicao_fipe)
            if pct_atingido >= limite_pct:
                alertas_substituicao.append({
                    'veiculo_id': v.id,
                    'placa': v.placa,
                    'modelo': f"{v.marca} {v.modelo}",
                    'custo_anual_manutencao': float(custo_anual_estimado),
                    'fipe_valor': float(fipe_val),
                    'percentual_atingido': pct_atingido,
                    'percentual_limite': limite_pct,
                    'motivo': f"Custo anual de manutenção (R$ {custo_anual_estimado:,.2f}) representa {pct_atingido}% do valor FIPE do veículo (limite de {limite_pct}%)."
                })

    # Ordenar ranking por TCO decrescente
    ranking_veiculos.sort(key=lambda x: x['tco_total'], reverse=True)

    # Próximos vencimentos de planos preventivos
    planos_qs = PlanoManutencao.objects.filter(tenant=tenant, ativo=True).select_related('veiculo')
    proximos_vencimentos = []
    for p in planos_qs:
        status_info = p.calcular_status_vencimento(data_referencia=hoje)
        proximos_vencimentos.append({
            'plano_id': p.id,
            'veiculo': p.veiculo.placa,
            'modelo': f"{p.veiculo.marca} {p.veiculo.modelo}",
            'descricao': p.descricao,
            'status': status_info['status'],
            'motivo': status_info['motivo'],
            'vencido': status_info['vencido'],
            'alerta': status_info['alerta'],
            'km_restantes': status_info['km_restantes'],
            'dias_restantes': status_info['dias_restantes'],
            'proximo_km': status_info['proximo_km'],
            'proxima_data': status_info['proxima_data']
        })

    # Ordenar próximos vencimentos: primeiro vencidos, depois alertas, depois em dia
    ordem_status = {'Vencido': 0, 'Alerta': 1, 'Em dia': 2, 'Inativo': 3}
    proximos_vencimentos.sort(key=lambda x: (ordem_status.get(x['status'], 9), x['dias_restantes'] or 9999))

    return {
        'periodo': {
            'inicio': data_inicio.strftime('%Y-%m-%d'),
            'fim': data_fim.strftime('%Y-%m-%d'),
            'dias': dias_periodo
        },
        'resumo_custos': {
            'custo_total_manutencao': float(custo_total_manutencao),
            'custo_pecas': float(custo_pecas),
            'custo_mao_de_obra': float(custo_mao_de_obra),
            'custo_terceiros': float(custo_terceiros),
            'km_rodados_total': km_rodados_total,
            'custo_por_km': float(custo_por_km)
        },
        'indicadores_operacionais': {
            'disponibilidade_frota_pct': disponibilidade_pct,
            'mtbf_dias': mtbf_dias,
            'mttr_horas': mttr_horas,
            'total_os_concluidas': qtd_total_concluidas,
            'total_os_abertas': os_periodo_qs.filter(status__in=['Aberta', 'Orçada', 'Aprovada', 'Em Execução']).count(),
            'veiculos_na_oficina': OrdemServico.objects.filter(
                tenant=tenant,
                imobiliza_veiculo=True,
                status__in=['Aberta', 'Orçada', 'Aprovada', 'Em Execução']
            ).values('veiculo').distinct().count()
        },
        'proporcao_preventiva_corretiva': {
            'preventiva': {
                'quantidade': qtd_preventiva,
                'pct_quantidade': pct_qtd_preventiva,
                'custo_total': float(custo_preventiva),
                'pct_custo': pct_custo_preventiva
            },
            'corretiva': {
                'quantidade': qtd_corretiva,
                'pct_quantidade': pct_qtd_corretiva,
                'custo_total': float(custo_corretiva),
                'pct_custo': pct_custo_corretiva
            },
            'outras': {
                'quantidade': qtd_outras,
                'pct_quantidade': round((qtd_outras / qtd_total_concluidas * 100), 1) if qtd_total_concluidas > 0 else 0.0
            }
        },
        'ranking_veiculos_mais_caros': ranking_veiculos[:10],
        'ranking_tco': ranking_veiculos[:10],
        'alertas_substituicao_veiculo': alertas_substituicao,
        'alertas_substituicao_fipe': alertas_substituicao,
        'custo_total_manutencao': float(custo_total_manutencao),
        'proximos_vencimentos': proximos_vencimentos[:15]
    }
