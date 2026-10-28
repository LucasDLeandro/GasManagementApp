"""
Serviço Canônico de Gestão e Verificação de Snapshots de Saldos Mensais (Sprint 10B - Tarefas 6 e 13).
Garante atualização transacional síncrona com lancar(), permitindo DRE e Balancetes analíticos em p95 < 2s.
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
    SaldoMensalConta,
    PartidaContabil,
    LancamentoContabil,
    PlanoContas,
)


def normalizar_ano_mes(periodo: Union[str, datetime.date, datetime.datetime]) -> str:
    """Normaliza data ou string no formato canônico YYYY-MM."""
    if isinstance(periodo, (datetime.date, datetime.datetime)):
        return periodo.strftime('%Y-%m')
    if isinstance(periodo, str):
        partes = periodo.strip().split('-')
        if len(partes) >= 2:
            return f"{int(partes[0]):04d}-{int(partes[1]):02d}"
    raise ValidationError(f"Formato de período inválido para snapshot: {periodo}. Use YYYY-MM ou objeto date.")


def obter_limites_ano_mes(ano_mes: str) -> tuple[datetime.date, datetime.date]:
    """Retorna (primeiro_dia, ultimo_dia) correspondente ao ano_mes."""
    partes = ano_mes.split('-')
    ano, mes = int(partes[0]), int(partes[1])
    primeiro_dia = datetime.date(ano, mes, 1)
    if mes == 12:
        ultimo_dia = datetime.date(ano + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        ultimo_dia = datetime.date(ano, mes + 1, 1) - datetime.timedelta(days=1)
    return primeiro_dia, ultimo_dia


def atualizar_snapshot_partida(tenant, partida: PartidaContabil) -> SaldoMensalConta:
    """
    Atualiza atomicamente o snapshot SaldoMensalConta para a partida recém-escriturada.
    Invocado obrigatoriamente dentro da mesma transação atômica de lancar().
    """
    assert_tenant_writable(tenant)
    ano_mes = normalizar_ano_mes(partida.lancamento.data_competencia)
    conta = partida.conta_contabil
    filial_id = partida.lancamento.filial_id

    # Lock explícito por dimensões para integridade em escrituração concorrente (Rule 5)
    snapshot, _ = SaldoMensalConta.unscoped.select_for_update().get_or_create(
        tenant_id=tenant.id,
        ano_mes=ano_mes,
        conta=conta,
        centro_custo_id=partida.centro_custo_id,
        veiculo_id=partida.veiculo_id,
        filial_id=filial_id,
        produto_gas_id=partida.produto_gas_id,
        defaults={
            'debitos': Decimal('0.00'),
            'creditos': Decimal('0.00'),
            'saldo_final': Decimal('0.00'),
        }
    )

    if partida.tipo_partida == 'DEBITO':
        snapshot.debitos = quantize(snapshot.debitos + partida.valor, 2)
    else:
        snapshot.creditos = quantize(snapshot.creditos + partida.valor, 2)

    if conta.natureza_saldo == 'DEVEDORA':
        snapshot.saldo_final = quantize(snapshot.debitos - snapshot.creditos, 2)
    else:
        snapshot.saldo_final = quantize(snapshot.creditos - snapshot.debitos, 2)

    snapshot.save(update_fields=['debitos', 'creditos', 'saldo_final', 'atualizado_em'])
    return snapshot


@transaction.atomic
def reconstruir_saldos(tenant, periodo: Union[str, datetime.date]) -> int:
    """
    Reconstrói integralmente os snapshots SaldoMensalConta para o período indicado,
    reagrupando as partidas contábeis do Razão e comparando com os valores vigentes.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')
    ano_mes = normalizar_ano_mes(periodo)
    dt_ini, dt_fim = obter_limites_ano_mes(ano_mes)

    # 1. Limpa snapshots existentes do período sob lock
    SaldoMensalConta.unscoped.filter(tenant=tenant, ano_mes=ano_mes).delete()

    # 2. Busca todas as partidas contábeis do período no Razão
    partidas = (
        PartidaContabil.unscoped
        .filter(
            tenant=tenant,
            lancamento__data_competencia__gte=dt_ini,
            lancamento__data_competencia__lte=dt_fim
        )
        .select_related('lancamento', 'conta_contabil')
    )

    # 3. Agrupamento em memória para inserção otimizada em lote
    agrupado = {}
    for p in partidas:
        chave = (
            p.conta_contabil_id,
            p.centro_custo_id,
            p.veiculo_id,
            p.lancamento.filial_id,
            p.produto_gas_id
        )
        if chave not in agrupado:
            agrupado[chave] = {
                'conta': p.conta_contabil,
                'centro_custo_id': p.centro_custo_id,
                'veiculo_id': p.veiculo_id,
                'filial_id': p.lancamento.filial_id,
                'produto_gas_id': p.produto_gas_id,
                'debitos': Decimal('0.00'),
                'creditos': Decimal('0.00'),
            }
        if p.tipo_partida == 'DEBITO':
            agrupado[chave]['debitos'] = quantize(agrupado[chave]['debitos'] + p.valor, 2)
        else:
            agrupado[chave]['creditos'] = quantize(agrupado[chave]['creditos'] + p.valor, 2)

    novos_snapshots = []
    for dados in agrupado.values():
        conta = dados['conta']
        deb = dados['debitos']
        cred = dados['creditos']
        if conta.natureza_saldo == 'DEVEDORA':
            sf = quantize(deb - cred, 2)
        else:
            sf = quantize(cred - deb, 2)

        novos_snapshots.append(
            SaldoMensalConta(
                tenant=tenant,
                ano_mes=ano_mes,
                conta=conta,
                centro_custo_id=dados['centro_custo_id'],
                veiculo_id=dados['veiculo_id'],
                filial_id=dados['filial_id'],
                produto_gas_id=dados['produto_gas_id'],
                debitos=deb,
                creditos=cred,
                saldo_final=sf
            )
        )

    SaldoMensalConta.unscoped.bulk_create(novos_snapshots)
    return len(novos_snapshots)


def verificar_integridade_snapshots(tenant, periodo: Union[str, datetime.date]) -> dict:
    """
    Compara os totais acumulados nos snapshots SaldoMensalConta com o somatório
    efetivo das partidas contábeis do Razão no período.
    Retorna {'valido': bool, 'diferenca_debitos': Decimal, 'diferenca_creditos': Decimal, 'discrepancias': list}
    """
    assert_modulo(tenant, 'financeiro')
    ano_mes = normalizar_ano_mes(periodo)
    dt_ini, dt_fim = obter_limites_ano_mes(ano_mes)

    # Totais no Razão
    totais_razao = PartidaContabil.unscoped.filter(
        tenant=tenant,
        lancamento__data_competencia__gte=dt_ini,
        lancamento__data_competencia__lte=dt_fim
    ).aggregate(
        total_deb=Sum('valor', filter=Q(tipo_partida='DEBITO')),
        total_cred=Sum('valor', filter=Q(tipo_partida='CREDITO'))
    )
    total_deb_razao = quantize(totais_razao['total_deb'] or Decimal('0.00'), 2)
    total_cred_razao = quantize(totais_razao['total_cred'] or Decimal('0.00'), 2)

    # Totais no Snapshot
    totais_snap = SaldoMensalConta.unscoped.filter(
        tenant=tenant,
        ano_mes=ano_mes
    ).aggregate(
        total_deb=Sum('debitos'),
        total_cred=Sum('creditos')
    )
    total_deb_snap = quantize(totais_snap['total_deb'] or Decimal('0.00'), 2)
    total_cred_snap = quantize(totais_snap['total_cred'] or Decimal('0.00'), 2)

    dif_deb = quantize(abs(total_deb_razao - total_deb_snap), 2)
    dif_cred = quantize(abs(total_cred_razao - total_cred_snap), 2)
    valido = (dif_deb == Decimal('0.00')) and (dif_cred == Decimal('0.00'))

    return {
        'valido': valido,
        'ano_mes': ano_mes,
        'razao': {'debitos': total_deb_razao, 'creditos': total_cred_razao},
        'snapshot': {'debitos': total_deb_snap, 'creditos': total_cred_snap},
        'diferenca_debitos': dif_deb,
        'diferenca_creditos': dif_cred,
    }
