"""
Serviços de gestão de contas financeiras e extrato de movimentações (Sprint 9A - Tarefas 6 e 7 / Lacuna F-16).
Regra: O saldo de uma conta financeira é SEMPRE derivado de MovimentoConta.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    ContaFinanceira,
    MovimentoConta,
    PlanoContas,
)
from financeiro.services.periodo import checar_periodo_aberto
from financeiro.services.razao import lancar


def saldo_em(conta: ContaFinanceira, data=None) -> Decimal:
    """
    Calcula o saldo de uma conta financeira em uma determinada data (Sprint 9A - Tarefa 7).
    Fórmula estrita: Saldo = Saldo Inicial + Entradas − Saídas.
    """
    qs = MovimentoConta.objects.filter(conta=conta)
    if data:
        qs = qs.filter(data_movimento__lte=data)

    entradas_q = Q(tipo__in=['ENTRADA', 'TRANSFERENCIA_ENTRADA', 'RENDIMENTO']) | Q(tipo='AJUSTE', tipo_ajuste='ENTRADA')
    saidas_q = Q(tipo__in=['SAIDA', 'TRANSFERENCIA_SAIDA', 'TARIFA']) | Q(tipo='AJUSTE', tipo_ajuste='SAIDA')

    total_entradas = qs.filter(entradas_q).aggregate(total=Sum('valor'))['total'] or Decimal('0.00')
    total_saidas = qs.filter(saidas_q).aggregate(total=Sum('valor'))['total'] or Decimal('0.00')

    # Considera saldo_inicial apenas se a data da consulta for posterior ou igual a data_saldo_inicial
    saldo_inicial = conta.saldo_inicial
    if data and data < conta.data_saldo_inicial:
        saldo_inicial = Decimal('0.00')

    saldo_final = saldo_inicial + total_entradas - total_saidas
    return quantize(saldo_final, 2)


@transaction.atomic
def criar_conta_financeira(
    *,
    tenant,
    nome: str,
    tipo: str,
    conta_contabil_id=None,
    conta_contabil=None,
    filial=None,
    banco_codigo: str = '',
    agencia: str = '',
    conta: str = '',
    saldo_inicial: Decimal = Decimal('0.00'),
    data_saldo_inicial=None,
    responsavel_caixa=None
):
    """
    Cria uma nova ContaFinanceira vinculada a uma conta contábil analítica (Sprint 9A - Tarefa 6).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if conta_contabil is not None:
        conta_contabil_obj = conta_contabil
    elif conta_contabil_id is not None:
        conta_contabil_obj = PlanoContas.objects.filter(tenant=tenant, id=conta_contabil_id).first()
    else:
        raise ValidationError("É obrigatório informar a conta contábil analítica (conta_contabil ou conta_contabil_id).")

    if not conta_contabil_obj:
        raise ValidationError("Conta contábil analítica informada não foi encontrada no Tenant.")

    if conta_contabil_obj.tipo != 'ANALITICA' or not conta_contabil_obj.aceita_lancamento:
        raise ValidationError(
            f"A conta contábil {conta_contabil_obj.codigo_estrutural} deve ser analítica e aceitar lançamentos diretos."
        )

    dt_ini = data_saldo_inicial or timezone.localdate()
    v_ini = quantize(saldo_inicial, 2)

    cf = ContaFinanceira.objects.create(
        tenant=tenant,
        filial=filial,
        nome=nome.strip(),
        tipo=tipo,
        banco_codigo=banco_codigo.strip(),
        agencia=agencia.strip(),
        conta=conta.strip(),
        saldo_inicial=v_ini,
        data_saldo_inicial=dt_ini,
        responsavel_caixa=responsavel_caixa,
        conta_contabil=conta_contabil_obj,
        ativo=True
    )
    return cf


@transaction.atomic
def registrar_movimento_conta(
    *,
    tenant,
    conta=None,
    conta_id=None,
    tipo: str,
    valor,
    data_movimento=None,
    historico: str = '',
    tipo_ajuste: str = 'ENTRADA',
    lancamento=None,
    baixa=None,
    extrato_item=None,
    conciliado: bool = False
):
    """
    Registra um lançamento unitário no extrato de uma conta financeira (Sprint 9A - Tarefa 7).
    Valida período contábil aberto e trava financeira da competência.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if conta is not None:
        conta_id = getattr(conta, 'id', conta)
    if not conta_id:
        raise ValidationError("Conta financeira deve ser informada.")

    conta = ContaFinanceira.objects.select_for_update().get(id=conta_id)
    if conta.tenant_id != tenant.id:
        raise ValidationError("Conta financeira pertence a outro Tenant.")

    if not conta.ativo:
        raise ValidationError(f"A conta financeira {conta.nome} está inativa.")

    dt_mov = data_movimento or timezone.localdate()
    checar_periodo_aberto(tenant, dt_mov)

    val = quantize(Decimal(str(valor)), 2)
    if val <= Decimal('0.00'):
        raise ValidationError(f"O valor da movimentação deve ser estritamente positivo (recebido: R$ {val}).")

    mov = MovimentoConta.objects.create(
        tenant=tenant,
        conta=conta,
        data_movimento=dt_mov,
        tipo=tipo,
        tipo_ajuste=tipo_ajuste,
        valor=val,
        baixa=baixa,
        lancamento=lancamento,
        extrato_item=extrato_item,
        conciliado=conciliado,
        historico=historico.strip()
    )
    return mov


@transaction.atomic
def transferir_entre_contas(
    *,
    tenant,
    conta_origem_id,
    conta_destino_id,
    valor,
    data_transferencia=None,
    historico: str = '',
    usuario=None
):
    """
    Realiza transferência financeira entre duas contas bancárias/caixas (Sprint 9A - Tarefa 7).
    Regra: Gera exatamente DOIS movimentos de conta e UM lançamento no razão contábil.
    Partidas do Lançamento:
      (D) Débito na conta contábil da Conta Destino
      (C) Crédito na conta contábil da Conta Origem
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if conta_origem_id == conta_destino_id:
        raise ValidationError("As contas de origem e destino da transferência devem ser distintas.")

    dt_transf = data_transferencia or timezone.localdate()
    checar_periodo_aberto(tenant, dt_transf)

    val = quantize(Decimal(str(valor)), 2)
    if val <= Decimal('0.00'):
        raise ValidationError(f"O valor da transferência deve ser estritamente maior que zero (recebido: R$ {val}).")

    # Lock nas duas contas financeiras em ordem de ID para evitar deadlocks
    ids_ordenados = sorted([conta_origem_id, conta_destino_id])
    contas_bloqueadas = {
        c.id: c
        for c in ContaFinanceira.objects.select_for_update().filter(tenant=tenant, id__in=ids_ordenados)
    }

    conta_origem = contas_bloqueadas.get(conta_origem_id)
    conta_destino = contas_bloqueadas.get(conta_destino_id)

    if not conta_origem or not conta_destino:
        raise ValidationError("Conta de origem ou destino não encontrada no Tenant atual.")

    if not conta_origem.ativo or not conta_destino.ativo:
        raise ValidationError("Ambas as contas financeiras devem estar ativas para realizar transferências.")

    # 1. Validação de saldo disponível na conta de origem
    saldo_atual_origem = saldo_em(conta_origem, dt_transf)
    if saldo_atual_origem < val:
        raise ValidationError(
            f"Saldo insuficiente na conta de origem {conta_origem.nome} "
            f"(Saldo em {dt_transf.strftime('%d/%m/%Y')}: R$ {saldo_atual_origem}). "
            f"Valor solicitado para transferência: R$ {val}."
        )

    hist = historico.strip() or f"Transferência entre contas: de {conta_origem.nome} para {conta_destino.nome}"

    # 2. Escritura o Lançamento Contábil no Razão em partidas dobradas
    partidas = [
        {
            'conta': conta_destino.conta_contabil,
            'tipo_partida': 'DEBITO',
            'valor': val,
        },
        {
            'conta': conta_origem.conta_contabil,
            'tipo_partida': 'CREDITO',
            'valor': val,
        }
    ]

    lancamento, _ = lancar(
        tenant=tenant,
        filial=conta_origem.filial,
        data_competencia=dt_transf,
        historico=hist,
        partidas=partidas,
        origem_tipo='TransferenciaContas',
        origem_id=f"{conta_origem.id}->{conta_destino.id}",
        usuario=usuario
    )

    # 3. Gera os 2 MovimentoConta vinculados ao lançamento contábil
    mov_saida = MovimentoConta.objects.create(
        tenant=tenant,
        conta=conta_origem,
        data_movimento=dt_transf,
        tipo='TRANSFERENCIA_SAIDA',
        valor=val,
        lancamento=lancamento,
        historico=f"Saída para {conta_destino.nome} - {hist}"
    )

    mov_entrada = MovimentoConta.objects.create(
        tenant=tenant,
        conta=conta_destino,
        data_movimento=dt_transf,
        tipo='TRANSFERENCIA_ENTRADA',
        valor=val,
        lancamento=lancamento,
        historico=f"Entrada de {conta_origem.nome} - {hist}"
    )

    return lancamento, mov_saida, mov_entrada
