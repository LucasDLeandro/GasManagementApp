from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.guards import assert_tenant_writable, assert_modulo
from core.money import quantize
from financeiro.models import (
    FechamentoCaixaRota,
    QuebraCaixa,
    ChequeRecebido,
    ContaFinanceira,
    MovimentoConta,
    PlanoContas,
    PreLancamentoDespesaCampo,
    BaixaParcela,
    ParametroFinanceiroTenant,
)
from financeiro.services.titulos import obter_parametros_financeiros
from financeiro.services.razao import lancar


from django.contrib.auth import get_user_model


def apurar_saldo_esperado_motorista(
    *,
    tenant,
    motorista=None,
    motorista_id=None,
    data=None,
    data_fechamento=None
) -> Decimal:
    """
    Apura o saldo teórico esperado em caixa de rota:
    Saldo Esperado = (Recebimentos em Dinheiro na Rota) - (Despesas Aprovadas Pagas em Dinheiro de Rota).
    """
    User = get_user_model()
    m_target = motorista or motorista_id
    if isinstance(m_target, User):
        motorista_obj = m_target
    else:
        motorista_obj = User.objects.get(id=m_target)

    dt_target = data or data_fechamento or timezone.localdate()

    # 1. Total de recebimentos em dinheiro no dia
    baixas_dinheiro = BaixaParcela.objects.filter(
        tenant=tenant,
        executado_por=motorista_obj,
        data_liquidacao=dt_target,
        estornado=False
    )
    total_recebimentos = sum(
        b.valor_total_movimentado for b in baixas_dinheiro
        if b.conta_financeira.tipo in ['CAIXA', 'OUTRO'] or 'rota' in b.conta_financeira.nome.lower()
    )
    total_recebimentos = quantize(Decimal(str(total_recebimentos)), 2)

    # 2. Despesas aprovadas com pagamento em DINHEIRO_ROTA no dia
    despesas_dinheiro = PreLancamentoDespesaCampo.objects.filter(
        tenant=tenant,
        motorista=motorista_obj,
        data_hora__date=dt_target,
        status='APROVADO',
        forma_pagamento='DINHEIRO_ROTA'
    )
    total_despesas = sum(d.valor_informado for d in despesas_dinheiro)
    total_despesas = quantize(Decimal(str(total_despesas)), 2)

    saldo_esperado = quantize(total_recebimentos - total_despesas, 2)
    return saldo_esperado


@transaction.atomic
def obter_ou_criar_fechamento_caixa(
    *,
    tenant,
    motorista=None,
    motorista_id=None,
    data=None,
    data_fechamento=None,
    conta_caixa=None,
    conta_caixa_id=None
) -> FechamentoCaixaRota:
    """
    Recupera ou inicializa o fechamento diário do caixa de rota do motorista.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    User = get_user_model()
    m_target = motorista or motorista_id
    if isinstance(m_target, User):
        motorista_obj = m_target
    else:
        motorista_obj = User.objects.get(id=m_target)

    dt_target = data or data_fechamento or timezone.localdate()

    fechamento = FechamentoCaixaRota.objects.filter(
        tenant=tenant,
        motorista=motorista_obj,
        data=dt_target
    ).first()

    saldo_teorico = apurar_saldo_esperado_motorista(
        tenant=tenant,
        motorista=motorista_obj,
        data=dt_target
    )

    if fechamento:
        if fechamento.status == 'ABERTO':
            fechamento.saldo_esperado = saldo_teorico
            fechamento.save(update_fields=['saldo_esperado', 'atualizado_em'])
        return fechamento

    # Resolução da ContaFinanceira do motorista
    c_target = conta_caixa or conta_caixa_id
    conta_caixa_obj = None
    if c_target:
        if isinstance(c_target, ContaFinanceira):
            conta_caixa_obj = c_target
        else:
            conta_caixa_obj = ContaFinanceira.objects.filter(tenant=tenant, id=c_target).first()

    if not conta_caixa_obj:
        c_contabil_rota = PlanoContas.objects.filter(
            tenant=tenant,
            codigo_estrutural__in=['1.1.1.03', '1.1.1.01']
        ).first()

        nome_caixa = f"Caixa de Rota - {motorista_obj.get_full_name() or motorista_obj.username}"
        conta_caixa_obj, _ = ContaFinanceira.objects.get_or_create(
            tenant=tenant,
            nome=nome_caixa,
            defaults={
                'tipo': 'CAIXA',
                'conta_contabil': c_contabil_rota,
                'saldo_inicial': Decimal('0.00'),
                'ativo': True
            }
        )

    fechamento = FechamentoCaixaRota.objects.create(
        tenant=tenant,
        motorista=motorista_obj,
        data=dt_target,
        conta_caixa=conta_caixa_obj,
        saldo_esperado=saldo_teorico,
        status='ABERTO'
    )
    return fechamento


@transaction.atomic
def registrar_contagem_cega(
    tenant=None,
    fechamento_id: int = None,
    valor_contado_cego=None,
    motorista=None,
    **kwargs
) -> FechamentoCaixaRota:
    """
    O motorista informa o valor físico contado no final da rota sem visualizar o saldo esperado (Sprint 9C - Tarefa 8).
    """
    # Suporta chamada por kwargs
    t_obj = tenant or kwargs.get('tenant')
    f_id = fechamento_id or kwargs.get('fechamento_id')
    val_raw = valor_contado_cego if valor_contado_cego is not None else kwargs.get('valor_contado_cego')
    mot_obj = motorista or kwargs.get('motorista')

    assert_tenant_writable(t_obj)
    assert_modulo(t_obj, 'financeiro')

    fechamento = FechamentoCaixaRota.objects.select_for_update().get(id=f_id, tenant=t_obj)

    if fechamento.status not in ['ABERTO', 'DIVERGENTE']:
        raise ValidationError(f"O caixa #{fechamento.id} está com status '{fechamento.status}' e não aceita contagem.")

    # O motorista deve ser o titular do caixa
    if mot_obj and mot_obj.id != fechamento.motorista_id:
        raise ValidationError("Apenas o motorista titular pode registrar sua contagem física cega.")

    val_contado = quantize(Decimal(str(val_raw)), 2)
    if val_contado < Decimal('0.00'):
        raise ValidationError("O valor contado pelo motorista não pode ser negativo.")

    # Recalcula saldo esperado atualizado somente se não tiver sido prefixado
    if fechamento.saldo_esperado is None:
        fechamento.saldo_esperado = apurar_saldo_esperado_motorista(
            tenant=t_obj,
            motorista=fechamento.motorista,
            data=fechamento.data
        )

    fechamento.valor_contado_cego = val_contado
    fechamento.diferenca = quantize(val_contado - fechamento.saldo_esperado, 2)
    fechamento.save(update_fields=['valor_contado_cego', 'saldo_esperado', 'diferenca', 'atualizado_em'])

    return fechamento


@transaction.atomic
def conferir_e_fechar_caixa(
    *,
    fechamento_id: int,
    tenant,
    valor_entregue_tesouraria,
    conferido_por=None,
    conferente=None,
    conta_cofre_id=None,
    tratamento_quebra: str = 'RECEBIVEL_FUNCIONARIO'
) -> FechamentoCaixaRota:
    """
    Conferência formal de tesouraria e encerramento do caixa de rota (Sprint 9C - Tarefa 8).
    Regras estritas:
    - Conferente deve ser obrigatoriamente diferente do motorista (segregação de funções).
    - Diferença acima da tolerância gera QuebraCaixa e lançamento contábil.
    - Realiza movimentação de transferência física para a conta cofre/banco.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    conferente_efetivo = conferido_por or conferente

    fechamento = FechamentoCaixaRota.objects.select_for_update().get(id=fechamento_id, tenant=tenant)

    # 1. Segregação de Funções estrita
    if conferente_efetivo and conferente_efetivo.id == fechamento.motorista_id:
        raise ValidationError("Segregação de funções violada: O conferente da tesouraria não pode ser o motorista do caixa.")

    # 2. Exige contagem cega prévia do motorista
    if fechamento.valor_contado_cego is None:
        raise ValidationError("O motorista deve registrar a contagem física cega antes da conferência pela tesouraria.")

    val_entregue = quantize(Decimal(str(valor_entregue_tesouraria)), 2)
    if val_entregue < Decimal('0.00'):
        raise ValidationError("O valor físico entregue à tesouraria não pode ser negativo.")

    param = obter_parametros_financeiros(tenant)
    tolerancia = getattr(param, 'tolerancia_quebra_caixa', Decimal('5.00'))

    # Diferença apurada: (Contado Cego - Esperado)
    diferenca = quantize(fechamento.valor_contado_cego - fechamento.saldo_esperado, 2)
    fechamento.diferenca = diferenca
    fechamento.valor_entregue_tesouraria = val_entregue
    fechamento.conferido_por = conferente_efetivo

    # 3. Tratamento de Quebra de Caixa
    if abs(diferenca) > tolerancia:
        tipo_quebra = 'SOBRA' if diferenca > Decimal('0.00') else 'FALTA'
        tratamento_efetivo = 'RECEITA_OPERACIONAL' if tipo_quebra == 'SOBRA' else tratamento_quebra

        # Lançamento contábil no Razão da Quebra
        c_caixa_rota = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['1.1.1.03', '1.1.1.01']).first()

        partidas = []
        if tipo_quebra == 'SOBRA':
            c_receita = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='8.1').first()
            partidas = [
                {'conta': c_caixa_rota, 'tipo_partida': 'DEBITO', 'valor': diferenca},
                {'conta': c_receita, 'tipo_partida': 'CREDITO', 'valor': diferenca},
            ]
        else:
            val_falta = abs(diferenca)
            if tratamento_efetivo == 'RECEBIVEL_FUNCIONARIO':
                c_contra = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.2.01').first()
            else:
                c_contra = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['4.1.2', '5.1']).first()

            partidas = [
                {'conta': c_contra, 'tipo_partida': 'DEBITO', 'valor': val_falta},
                {'conta': c_caixa_rota, 'tipo_partida': 'CREDITO', 'valor': val_falta},
            ]

        lanc, _ = lancar(
            tenant=tenant,
            data_competencia=fechamento.data,
            historico=f"Quebra de Caixa de Rota ({tipo_quebra}) - Motorista {fechamento.motorista.username} [Fechamento #{fechamento.id}]",
            partidas=partidas,
            origem_tipo='quebra_caixa_rota',
            origem_id=str(fechamento.id),
            usuario=conferido_por
        )

        QuebraCaixa.objects.update_or_create(
            tenant=tenant,
            fechamento=fechamento,
            defaults={
                'motorista': fechamento.motorista,
                'tipo': tipo_quebra,
                'valor': abs(diferenca),
                'tratamento': tratamento_efetivo,
                'lancamento_contabil': lanc,
                'observacao': f"Apurada diferença de R$ {diferenca} no fechamento cego de caixa."
            }
        )
        fechamento.status = 'DIVERGENTE'
    else:
        fechamento.status = 'CONFERIDO'

    # 4. Transferência do montante entregue para a Conta Cofre / Banco
    if val_entregue > Decimal('0.00'):
        conta_cofre = None
        if conta_cofre_id:
            conta_cofre = ContaFinanceira.objects.filter(tenant=tenant, id=conta_cofre_id).first()

        if not conta_cofre:
            conta_cofre = ContaFinanceira.objects.filter(
                tenant=tenant,
                tipo='BANCO'
            ).first() or fechamento.conta_caixa

        # Movimento de saída do caixa de rota
        mov_saida = MovimentoConta.objects.create(
            tenant=tenant,
            conta=fechamento.conta_caixa,
            tipo='SAIDA',
            valor=val_entregue,
            data_movimento=fechamento.data,
            historico=f"Transferência Fechamento Caixa Rota #{fechamento.id} para {conta_cofre.nome}"
        )

        # Movimento de entrada no cofre/banco
        if conta_cofre.id != fechamento.conta_caixa.id:
            MovimentoConta.objects.create(
                tenant=tenant,
                conta=conta_cofre,
                tipo='ENTRADA',
                valor=val_entregue,
                data_movimento=fechamento.data,
                historico=f"Recebimento de Rota: Motorista {fechamento.motorista.username} [Fechamento #{fechamento.id}]"
            )

            # Lançamento contábil da transferência
            c_caixa_rota = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['1.1.1.03', '1.1.1.01']).first()
            c_cofre = conta_cofre.conta_contabil or PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.1.01').first()

            if c_caixa_rota and c_cofre:
                lancar(
                    tenant=tenant,
                    data_competencia=fechamento.data,
                    historico=f"Transferência de Numerário: Caixa Rota #{fechamento.id} para {conta_cofre.nome}",
                    partidas=[
                        {'conta': c_cofre, 'tipo_partida': 'DEBITO', 'valor': val_entregue},
                        {'conta': c_caixa_rota, 'tipo_partida': 'CREDITO', 'valor': val_entregue},
                    ],
                    origem_tipo='transferencia_caixa_rota',
                    origem_id=str(fechamento.id),
                    usuario=conferido_por
                )

        fechamento.transferencia = mov_saida

    fechamento.status = 'FECHADO'
    fechamento.save()
    return fechamento


@transaction.atomic
def registrar_cheque_recebido(
    *,
    fechamento_id: int,
    tenant,
    numero: str,
    banco: str,
    valor,
    bom_para=None,
    emitente_nome: str = '',
    emitente_documento: str = ''
) -> ChequeRecebido:
    """
    Registra um cheque recebido pelo motorista vinculado ao fechamento de caixa (Sprint 9C - Tarefa 8).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    fechamento = FechamentoCaixaRota.objects.get(id=fechamento_id, tenant=tenant)
    val_cheque = quantize(Decimal(str(valor)), 2)

    cheque = ChequeRecebido.objects.create(
        tenant=tenant,
        fechamento=fechamento,
        numero=str(numero).strip(),
        banco=str(banco).strip(),
        valor=val_cheque,
        bom_para=bom_para,
        status='EM_CARTEIRA',
        emitente_nome=emitente_nome.strip() if emitente_nome else '',
        emitente_documento=emitente_documento.strip() if emitente_documento else ''
    )
    return cheque
