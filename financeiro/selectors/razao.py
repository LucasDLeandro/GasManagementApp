"""
Seletores de consulta ao Livro Razão Contábil (Sprint 9A - Tarefa 12).
"""

from decimal import Decimal
from django.core.exceptions import ValidationError

from core.money import quantize
from financeiro.models import PlanoContas, LancamentoContabil, PartidaContabil


def consultar_razao_conta(*, tenant, conta_id, data_inicio, data_fim):
    """
    Retorna o extrato cronológico do Razão de uma conta contábil analítica no período,
    com cálculo do saldo progressivo acumulado.
    """
    conta = PlanoContas.objects.filter(tenant=tenant, id=conta_id).first()
    if not conta:
        raise ValidationError("Conta contábil não encontrada no Tenant.")

    # Saldo anterior à data de início
    partidas_ant = PartidaContabil.objects.filter(
        tenant=tenant,
        conta_contabil=conta,
        lancamento__data_competencia__lt=data_inicio
    )
    d_ant = sum((p.valor for p in partidas_ant if p.tipo_partida == 'DEBITO'), Decimal('0.00'))
    c_ant = sum((p.valor for p in partidas_ant if p.tipo_partida == 'CREDITO'), Decimal('0.00'))

    if conta.natureza_saldo == 'DEVEDORA':
        saldo_acumulado = d_ant - c_ant
    else:
        saldo_acumulado = c_ant - d_ant

    saldo_inicial_periodo = quantize(saldo_acumulado, 2)

    # Partidas do período
    partidas = PartidaContabil.objects.filter(
        tenant=tenant,
        conta_contabil=conta,
        lancamento__data_competencia__gte=data_inicio,
        lancamento__data_competencia__lte=data_fim
    ).select_related(
        'lancamento',
        'centro_custo',
        'veiculo',
        'produto_gas',
        'cliente',
        'entrega'
    ).order_by('lancamento__data_competencia', 'lancamento__numero', 'id')

    linhas = []
    for p in partidas:
        if conta.natureza_saldo == 'DEVEDORA':
            if p.tipo_partida == 'DEBITO':
                saldo_acumulado += p.valor
            else:
                saldo_acumulado -= p.valor
        else:
            if p.tipo_partida == 'CREDITO':
                saldo_acumulado += p.valor
            else:
                saldo_acumulado -= p.valor

        linhas.append({
            'partida_id': p.id,
            'lancamento_id': p.lancamento.id,
            'lancamento_numero': p.lancamento.numero,
            'data_competencia': p.lancamento.data_competencia,
            'historico': p.lancamento.historico,
            'tipo_partida': p.tipo_partida,
            'debito': p.valor if p.tipo_partida == 'DEBITO' else Decimal('0.00'),
            'credito': p.valor if p.tipo_partida == 'CREDITO' else Decimal('0.00'),
            'saldo_acumulado': quantize(saldo_acumulado, 2),
            'centro_custo': p.centro_custo.nome if p.centro_custo else None,
            'veiculo': str(p.veiculo) if p.veiculo else None,
            'produto_gas': p.produto_gas.sigla if p.produto_gas else None,
            'cliente': p.cliente.nome if p.cliente else None,
        })

    return {
        'conta': {
            'id': conta.id,
            'codigo_estrutural': conta.codigo_estrutural,
            'nome': conta.nome,
            'natureza_saldo': conta.natureza_saldo
        },
        'periodo': {
            'inicio': data_inicio,
            'fim': data_fim
        },
        'saldo_inicial': saldo_inicial_periodo,
        'saldo_final': quantize(saldo_acumulado, 2),
        'linhas': linhas
    }


def consultar_lancamento(*, tenant, lancamento_id):
    """
    Retorna os detalhes completos de um lançamento contábil com suas partidas.
    """
    lanc = LancamentoContabil.objects.filter(
        tenant=tenant,
        id=lancamento_id
    ).select_related('filial', 'lancamento_estornado', 'criado_por').prefetch_related(
        'partidas__conta_contabil',
        'partidas__centro_custo',
        'partidas__veiculo',
        'partidas__produto_gas',
        'partidas__cliente'
    ).first()

    if not lanc:
        raise ValidationError("Lançamento contábil não encontrado no Tenant.")

    partidas_info = []
    total_debitos = Decimal('0.00')
    total_creditos = Decimal('0.00')

    for p in lanc.partidas.all():
        if p.tipo_partida == 'DEBITO':
            total_debitos += p.valor
        else:
            total_creditos += p.valor

        partidas_info.append({
            'id': p.id,
            'conta_id': p.conta_contabil.id,
            'conta_codigo': p.conta_contabil.codigo_estrutural,
            'conta_nome': p.conta_contabil.nome,
            'tipo_partida': p.tipo_partida,
            'valor': p.valor,
            'centro_custo': p.centro_custo.nome if p.centro_custo else None,
            'veiculo': str(p.veiculo) if p.veiculo else None,
            'produto_gas': p.produto_gas.sigla if p.produto_gas else None,
            'cliente': p.cliente.nome if p.cliente else None,
            'entrega_id': p.entrega_id
        })

    return {
        'id': lanc.id,
        'numero': lanc.numero,
        'data_competencia': lanc.data_competencia,
        'data_registro': lanc.data_registro,
        'historico': lanc.historico,
        'origem_tipo': lanc.origem_tipo,
        'origem_id': lanc.origem_id,
        'hash_anterior': lanc.hash_anterior,
        'hash_integridade': lanc.hash_integridade,
        'lancamento_estornado_id': lanc.lancamento_estornado_id,
        'estornado': lanc.estornos.exists(),
        'partidas': partidas_info,
        'total_debitos': quantize(total_debitos, 2),
        'total_creditos': quantize(total_creditos, 2)
    }
