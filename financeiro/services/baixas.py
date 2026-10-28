"""
Serviços de liquidação financeira (Baixa de Parcelas, Baixa em Lote e Estorno de Baixas) (Sprint 9B - Tarefa 6).
Gera MovimentoConta e LancamentoContabil em partidas dobradas perfeitamente balanceadas.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    BaixaParcela,
    ContaFinanceira,
    MovimentoConta,
    ParcelaFinanceira,
    PlanoContas,
    TituloFinanceiro,
)
from financeiro.services.conta import registrar_movimento_conta
from financeiro.services.periodo import checar_periodo_aberto
from financeiro.services.razao import estornar, lancar


@transaction.atomic
def baixar_parcela(
    *,
    tenant,
    parcela_id,
    conta_financeira_id,
    valor_principal,
    data_liquidacao=None,
    valor_juros=Decimal('0.00'),
    valor_multa=Decimal('0.00'),
    valor_desconto=Decimal('0.00'),
    valor_tarifa=Decimal('0.00'),
    comprovante: str = '',
    usuario=None
) -> BaixaParcela:
    """
    Realiza a baixa (parcial ou total) de uma parcela financeira (Sprint 9B - Tarefa 6).
    Escritura MovimentoConta e LancamentoContabil no Razão contábil.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    dt_liq = data_liquidacao or timezone.localdate()
    checar_periodo_aberto(tenant, dt_liq)

    # 1. Lock na parcela e validações de integridade
    parcela = ParcelaFinanceira.objects.select_for_update().get(id=parcela_id)
    if parcela.tenant_id != tenant.id:
        raise ValidationError("Parcela financeira pertence a outro Tenant.")

    titulo = TituloFinanceiro.objects.select_for_update().get(id=parcela.titulo_id)

    # Segregação de funções em Contas a Pagar: Quem lançou não aprova nem baixa (F-03)
    if titulo.tipo == 'PAGAR' and usuario and titulo.criado_por_id == usuario.id:
        raise ValidationError(
            f"Violação de Segregação de Funções: O usuário '{usuario.username}' criou este título "
            f"e está estritamente proibido de realizar sua baixa/liquidação."
        )

    # Título a pagar exige estar formalmente ABERTO ou PARCIAL
    if titulo.tipo == 'PAGAR' and titulo.status not in ('ABERTO', 'PARCIAL'):
        raise ValidationError(
            f"Baixa rejeitada: o título a pagar #{titulo.id} está com status '{titulo.status}'. "
            f"Apenas títulos com status ABERTO ou PARCIAL podem ser baixados."
        )

    if parcela.status in ('PAGA', 'CANCELADA', 'RENEGOCIADA'):
        raise ValidationError(f"A parcela #{parcela.numero_parcela} encontra-se com status '{parcela.status}' e não aceita baixas.")

    # 2. Lock na conta financeira
    conta = ContaFinanceira.objects.select_for_update().get(id=conta_financeira_id)
    if conta.tenant_id != tenant.id:
        raise ValidationError("Conta financeira pertence a outro Tenant.")
    if not conta.ativo:
        raise ValidationError(f"A conta financeira {conta.nome} está inativa.")

    # 3. Tratamento monetário
    v_princ = quantize(Decimal(str(valor_principal)), 2)
    v_jur = quantize(Decimal(str(valor_juros)), 2)
    v_mul = quantize(Decimal(str(valor_multa)), 2)
    v_desc = quantize(Decimal(str(valor_desconto)), 2)
    v_tar = quantize(Decimal(str(valor_tarifa)), 2)

    if v_princ <= Decimal('0.00'):
        raise ValidationError("O valor principal da baixa deve ser estritamente maior que zero.")

    if v_princ > parcela.saldo_em_aberto:
        raise ValidationError(
            f"Valor principal solicitado (R$ {v_princ}) excede o saldo em aberto da parcela (R$ {parcela.saldo_em_aberto})."
        )

    # Fórmula canônica: Total movimentado = Principal + Juros + Multa − Desconto
    v_movimentado = quantize(v_princ + v_jur + v_mul - v_desc, 2)
    if v_movimentado <= Decimal('0.00'):
        raise ValidationError(
            f"O valor total movimentado (R$ {v_movimentado}) deve ser maior que zero "
            f"(Principal: R$ {v_princ}, Juros/Multa: R$ {v_jur + v_mul}, Desconto: R$ {v_desc})."
        )

    # 4. Atualiza saldo da parcela e status
    parcela.saldo_em_aberto = quantize(parcela.saldo_em_aberto - v_princ, 2)
    if parcela.saldo_em_aberto == Decimal('0.00'):
        parcela.status = 'PAGA'
    else:
        parcela.status = 'PARCIAL'
    parcela.save(update_fields=['saldo_em_aberto', 'status', 'atualizado_em'])

    # 5. Atualiza status do título
    todas_parcelas = list(titulo.parcelas.all())
    if all(p.status == 'PAGA' for p in todas_parcelas):
        titulo.status = 'LIQUIDADO'
    elif any(p.status in ('PAGA', 'PARCIAL') for p in todas_parcelas):
        titulo.status = 'PARCIAL'
    titulo.save(update_fields=['status', 'atualizado_em'])

    # 6. Registra MovimentoConta
    tipo_mov = 'ENTRADA' if titulo.tipo == 'RECEBER' else 'SAIDA'
    hist_mov = f"Baixa Parcela {parcela.numero_parcela}/{parcela.total_parcelas} Título #{titulo.id} ({titulo.tipo})"

    mov_principal = registrar_movimento_conta(
        tenant=tenant,
        conta=conta,
        data_movimento=dt_liq,
        tipo=tipo_mov,
        valor=v_movimentado,
        historico=hist_mov
    )

    if v_tar > Decimal('0.00'):
        registrar_movimento_conta(
            tenant=tenant,
            conta=conta,
            data_movimento=dt_liq,
            tipo='TARIFA',
            valor=v_tar,
            historico=f"Tarifa bancária baixa parcela {parcela.numero_parcela} Título #{titulo.id}"
        )

    # 7. Contabilização no Razão Contábil (partidas dobradas)
    # Contas padrão do razão
    c_banco = conta.conta_contabil
    c_clientes = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.2.01').first()
    c_fornecedores = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.1.1.01', '2.1.1']).first()
    c_rec_fin = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['7.1.1', '7.1']).first()
    c_desp_fin = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['7.2.1', '7.2']).first()

    partidas = []
    if titulo.tipo == 'RECEBER':
        # (D) Banco/Caixa: valor total recebido
        partidas.append({
            'conta': c_banco,
            'tipo_partida': 'DEBITO',
            'valor': v_movimentado,
            'cliente': titulo.cliente
        })
        # (C) Clientes: valor principal liquidado
        partidas.append({
            'conta': c_clientes,
            'tipo_partida': 'CREDITO',
            'valor': v_princ,
            'cliente': titulo.cliente
        })
        # Juros e multa recebidos -> (C) Receitas Financeiras
        encargos = v_jur + v_mul
        if encargos > Decimal('0.00') and c_rec_fin:
            partidas.append({
                'conta': c_rec_fin,
                'tipo_partida': 'CREDITO',
                'valor': encargos,
                'cliente': titulo.cliente
            })
        # Desconto concedido na baixa -> (D) Despesas Financeiras
        if v_desc > Decimal('0.00') and c_desp_fin:
            partidas.append({
                'conta': c_desp_fin,
                'tipo_partida': 'DEBITO',
                'valor': v_desc,
                'cliente': titulo.cliente
            })
    else:
        # PAGAR
        # (D) Fornecedores: valor principal amortizado
        partidas.append({
            'conta': c_fornecedores,
            'tipo_partida': 'DEBITO',
            'valor': v_princ
        })
        # (C) Banco/Caixa: valor total pago
        partidas.append({
            'conta': c_banco,
            'tipo_partida': 'CREDITO',
            'valor': v_movimentado
        })
        # Juros e multa pagos -> (D) Despesas Financeiras
        encargos = v_jur + v_mul
        if encargos > Decimal('0.00') and c_desp_fin:
            partidas.append({
                'conta': c_desp_fin,
                'tipo_partida': 'DEBITO',
                'valor': encargos
            })
        # Desconto obtido na baixa -> (C) Receitas Financeiras
        if v_desc > Decimal('0.00') and c_rec_fin:
            partidas.append({
                'conta': c_rec_fin,
                'tipo_partida': 'CREDITO',
                'valor': v_desc
            })

    lancamento, _ = lancar(
        tenant=tenant,
        filial=titulo.filial,
        data_competencia=dt_liq,
        historico=f"Liquidação Parcela #{parcela.id} Título #{titulo.id} Ref: {comprovante or 'Balcão/Boleto'}",
        partidas=partidas,
        origem_tipo='BaixaParcela',
        origem_id=str(parcela.id),
        usuario=usuario
    )

    # 8. Persistência do registro de BaixaParcela
    baixa = BaixaParcela.objects.create(
        tenant=tenant,
        parcela=parcela,
        conta_financeira=conta,
        data_liquidacao=dt_liq,
        valor_principal=v_princ,
        valor_juros=v_jur,
        valor_multa=v_mul,
        valor_desconto=v_desc,
        valor_total_movimentado=v_movimentado,
        valor_tarifa=v_tar,
        comprovante=comprovante.strip(),
        executado_por=usuario,
        movimento_conta=mov_principal,
        lancamento=lancamento
    )

    return baixa


@transaction.atomic
def baixar_em_lote(
    *,
    tenant,
    itens_baixa: list[dict],
    conta_financeira_id,
    data_liquidacao=None,
    comprovante: str = '',
    usuario=None
) -> list[BaixaParcela]:
    """
    Executa a baixa em lote de múltiplas parcelas com garantias atômicas de liquidação.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    resultados = []
    for item in itens_baixa:
        p_id = item['parcela_id']
        v_princ = item['valor_principal']
        v_jur = item.get('valor_juros', Decimal('0.00'))
        v_mul = item.get('valor_multa', Decimal('0.00'))
        v_desc = item.get('valor_desconto', Decimal('0.00'))
        v_tar = item.get('valor_tarifa', Decimal('0.00'))

        baixa = baixar_parcela(
            tenant=tenant,
            parcela_id=p_id,
            conta_financeira_id=conta_financeira_id,
            valor_principal=v_princ,
            data_liquidacao=data_liquidacao,
            valor_juros=v_jur,
            valor_multa=v_mul,
            valor_desconto=v_desc,
            valor_tarifa=v_tar,
            comprovante=comprovante,
            usuario=usuario
        )
        resultados.append(baixa)

    return resultados


@transaction.atomic
def estornar_baixa(
    *,
    tenant,
    baixa_id,
    motivo: str = 'Estorno solicitado',
    usuario=None
) -> BaixaParcela:
    """
    Estorna formalmente uma baixa financeira (Sprint 9B - Tarefa 6).
    Recompõe o saldo da parcela, ajusta o título, estorna o lançamento no Razão
    e gera o movimento financeiro inverso.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal do estorno da baixa é estritamente obrigatório.")

    baixa = BaixaParcela.objects.select_for_update().get(id=baixa_id)
    if baixa.tenant_id != tenant.id:
        raise ValidationError("Baixa pertence a outro Tenant.")

    if baixa.estornado:
        raise ValidationError(f"A baixa #{baixa.id} já se encontra estornada.")

    parcela = ParcelaFinanceira.objects.select_for_update().get(id=baixa.parcela_id)
    titulo = TituloFinanceiro.objects.select_for_update().get(id=parcela.titulo_id)

    # 1. Recompõe o saldo da parcela
    parcela.saldo_em_aberto = quantize(parcela.saldo_em_aberto + baixa.valor_principal, 2)
    if parcela.saldo_em_aberto == parcela.valor_nominal:
        parcela.status = 'PENDENTE'
    else:
        parcela.status = 'PARCIAL'
    parcela.save(update_fields=['saldo_em_aberto', 'status', 'atualizado_em'])

    # 2. Reavalia o status do título
    todas_parcelas = list(titulo.parcelas.all())
    if all(p.status == 'PENDENTE' for p in todas_parcelas):
        titulo.status = 'ABERTO'
    elif any(p.status in ('PAGA', 'PARCIAL') for p in todas_parcelas):
        titulo.status = 'PARCIAL'
    else:
        titulo.status = 'ABERTO'
    titulo.save(update_fields=['status', 'atualizado_em'])

    # 3. Estorna o lançamento no Razão contábil
    if baixa.lancamento:
        estornar(baixa.lancamento, motivo=motivo.strip(), usuario=usuario)

    # 4. Movimento financeiro inverso no extrato da conta
    tipo_inverso = 'SAIDA' if titulo.tipo == 'RECEBER' else 'ENTRADA'
    registrar_movimento_conta(
        tenant=tenant,
        conta=baixa.conta_financeira,
        tipo=tipo_inverso,
        valor=baixa.valor_total_movimentado,
        historico=f"Estorno da Baixa #{baixa.id} - Motivo: {motivo.strip()}"
    )

    # 5. Marca a baixa como estornada
    baixa.estornado = True
    baixa.estornado_em = timezone.now()
    baixa.estornado_por = usuario
    baixa.motivo_estorno = motivo.strip()
    baixa.save(update_fields=['estornado', 'estornado_em', 'estornado_por', 'motivo_estorno'])

    return baixa
