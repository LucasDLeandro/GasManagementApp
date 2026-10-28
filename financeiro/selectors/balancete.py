"""
Seletor do Balancete de Verificação Contábil (Sprint 9A - Tarefa 11).
Soma débitos e créditos por período e conta analítica e sintética, demonstrando o fechamento em zero.
"""

from decimal import Decimal
from django.db.models import Sum, Q

from core.money import quantize
from financeiro.models import PlanoContas, PartidaContabil


def obter_balancete_verificacao(*, tenant, data_inicio, data_fim, filial=None, apenas_com_movimento=False):
    """
    Gera o Balancete de Verificação contábil por período para o Tenant (Sprint 9A - Tarefa 11).
    Apura:
    - Saldo Anterior (antes de data_inicio);
    - Débitos do Período;
    - Créditos do Período;
    - Saldo Final (na data_fim);
    - Totalizadores gerais comprovando que a soma de débitos == soma de créditos (diferença == 0).
    """
    contas = PlanoContas.objects.filter(tenant=tenant, ativo=True).order_by('codigo_estrutural')

    # Partidas antes do período (Saldo Anterior)
    qs_anterior = PartidaContabil.objects.filter(
        tenant=tenant,
        lancamento__data_competencia__lt=data_inicio
    )
    # Partidas no período
    qs_periodo = PartidaContabil.objects.filter(
        tenant=tenant,
        lancamento__data_competencia__gte=data_inicio,
        lancamento__data_competencia__lte=data_fim
    )

    if filial:
        qs_anterior = qs_anterior.filter(lancamento__filial=filial)
        qs_periodo = qs_periodo.filter(lancamento__filial=filial)

    # Agrupamentos analíticos rápidos no banco
    mov_ant_debitos = {
        item['conta_contabil_id']: item['total']
        for item in qs_anterior.filter(tipo_partida='DEBITO').values('conta_contabil_id').annotate(total=Sum('valor'))
    }
    mov_ant_creditos = {
        item['conta_contabil_id']: item['total']
        for item in qs_anterior.filter(tipo_partida='CREDITO').values('conta_contabil_id').annotate(total=Sum('valor'))
    }

    mov_per_debitos = {
        item['conta_contabil_id']: item['total']
        for item in qs_periodo.filter(tipo_partida='DEBITO').values('conta_contabil_id').annotate(total=Sum('valor'))
    }
    mov_per_creditos = {
        item['conta_contabil_id']: item['total']
        for item in qs_periodo.filter(tipo_partida='CREDITO').values('conta_contabil_id').annotate(total=Sum('valor'))
    }

    linhas_contas = []
    total_debitos_periodo = Decimal('0.00')
    total_creditos_periodo = Decimal('0.00')
    total_saldo_anterior_devedor = Decimal('0.00')
    total_saldo_anterior_credor = Decimal('0.00')
    total_saldo_final_devedor = Decimal('0.00')
    total_saldo_final_credor = Decimal('0.00')

    # 1. Processa contas analíticas
    analiticas_dict = {}
    for c in contas:
        if c.tipo != 'ANALITICA':
            continue

        d_ant = mov_ant_debitos.get(c.id, Decimal('0.00'))
        c_ant = mov_ant_creditos.get(c.id, Decimal('0.00'))

        d_per = mov_per_debitos.get(c.id, Decimal('0.00'))
        c_per = mov_per_creditos.get(c.id, Decimal('0.00'))

        # Saldo anterior de acordo com a natureza da conta
        if c.natureza_saldo == 'DEVEDORA':
            s_ant = d_ant - c_ant
            s_fim = s_ant + d_per - c_per
        else:
            s_ant = c_ant - d_ant
            s_fim = s_ant + c_per - d_per

        s_ant = quantize(s_ant, 2)
        s_fim = quantize(s_fim, 2)

        analiticas_dict[c.id] = {
            'conta': c,
            'saldo_anterior': s_ant,
            'debitos_periodo': d_per,
            'creditos_periodo': c_per,
            'saldo_final': s_fim,
        }

        total_debitos_periodo += d_per
        total_creditos_periodo += c_per

        if c.natureza_saldo == 'DEVEDORA':
            total_saldo_anterior_devedor += s_ant
            total_saldo_final_devedor += s_fim
        else:
            total_saldo_anterior_credor += s_ant
            total_saldo_final_credor += s_fim

    # 2. Monta hierarquia incluindo contas sintéticas (totalizadoras)
    for c in contas:
        if c.tipo == 'ANALITICA':
            dados = analiticas_dict.get(c.id)
            s_ant = dados['saldo_anterior']
            d_per = dados['debitos_periodo']
            c_per = dados['creditos_periodo']
            s_fim = dados['saldo_final']
        else:
            # Conta sintética totaliza todas as analíticas que começam com o seu prefixo
            prefixo = c.codigo_estrutural
            d_per = Decimal('0.00')
            c_per = Decimal('0.00')
            s_ant = Decimal('0.00')
            s_fim = Decimal('0.00')

            for a_id, a_data in analiticas_dict.items():
                if a_data['conta'].codigo_estrutural.startswith(prefixo + '.'):
                    d_per += a_data['debitos_periodo']
                    c_per += a_data['creditos_periodo']
                    if c.natureza_saldo == a_data['conta'].natureza_saldo:
                        s_ant += a_data['saldo_anterior']
                        s_fim += a_data['saldo_final']
                    else:
                        s_ant -= a_data['saldo_anterior']
                        s_fim -= a_data['saldo_final']

            s_ant = quantize(s_ant, 2)
            d_per = quantize(d_per, 2)
            c_per = quantize(c_per, 2)
            s_fim = quantize(s_fim, 2)

        if apenas_com_movimento and (s_ant == 0 and d_per == 0 and c_per == 0 and s_fim == 0):
            continue

        linhas_contas.append({
            'conta_id': c.id,
            'codigo_estrutural': c.codigo_estrutural,
            'nome': c.nome,
            'tipo': c.tipo,
            'nivel': c.nivel,
            'natureza_saldo': c.natureza_saldo,
            'saldo_anterior': s_ant,
            'debitos_periodo': d_per,
            'creditos_periodo': c_per,
            'saldo_final': s_fim,
        })

    diferenca = quantize(total_debitos_periodo - total_creditos_periodo, 2)
    fechado = (diferenca == Decimal('0.00'))

    # Resultado do exercício no período (Receitas - Despesas / grupos 3 a 9)
    resultado_exercicio = Decimal('0.00')
    for l in linhas_contas:
        if l['tipo'] == 'ANALITICA':
            cod = l['codigo_estrutural']
            if cod and cod[0] in ['3', '4', '5', '6', '7', '8', '9']:
                if l['natureza_saldo'] == 'CREDORA':
                    resultado_exercicio += (l['creditos_periodo'] - l['debitos_periodo'])
                else:
                    resultado_exercicio -= (l['debitos_periodo'] - l['creditos_periodo'])
    resultado_exercicio = quantize(resultado_exercicio, 2)

    return {
        'tenant_id': tenant.id,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'total_contas': len(linhas_contas),
        'fechamento_correto': fechado,
        'diferenca': diferenca,
        'resultado_exercicio': resultado_exercicio,
        'linhas': linhas_contas,
        'totais': {
            'saldo_anterior_devedor': quantize(total_saldo_anterior_devedor, 2),
            'saldo_anterior_credor': quantize(total_saldo_anterior_credor, 2),
            'total_debitos': quantize(total_debitos_periodo, 2),
            'total_creditos': quantize(total_creditos_periodo, 2),
            'total_debitos_analiticos': quantize(total_debitos_periodo, 2),
            'total_creditos_analiticos': quantize(total_creditos_periodo, 2),
            'saldo_final_devedor': quantize(total_saldo_final_devedor, 2),
            'saldo_final_credor': quantize(total_saldo_final_credor, 2),
            'diferenca': diferenca,
            'balanceado': fechado
        }
    }
