"""
Serviços de gestão de gás criogênico a granel, medições e balanço de massa (Sprint 8C - Tarefas 3, 4, 5, 6).
Controla o custo médio ponderado móvel em kg, apuração de boil-off por balanço de massa e divergência de pesagem.
"""

from decimal import Decimal
import uuid
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.eventos import publicar
from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from core.validators import validar_chave_nfe
from produtos.models import (
    TanqueCriogenico,
    MedicaoTanque,
    EntradaGasGranel,
    MovimentoEstoqueGas,
    FechamentoPeriodoTanque,
)


@transaction.atomic
def registrar_entrada_granel(
    *,
    tenant,
    tanque_id,
    fornecedor_nome,
    fornecedor_documento,
    chave_nfe,
    data_entrada=None,
    quantidade_kg_nf,
    quantidade_kg_recebida,
    custo_total_nf,
    custo_frete=Decimal('0.00'),
    impostos_recuperaveis=Decimal('0.00'),
    observacoes="",
    usuario=None,
    client_uuid=None
):
    """
    Registra o recebimento de carga criogênica a granel (Sprint 8C - Tarefa 4).
    Calcula custo unitário efetivo por kg = (custo NF + frete - impostos recuperáveis) ÷ peso recebido.
    Apura divergência entre NF e pesagem na balança, gerando alerta se exceder a tolerância.
    Recalcula o custo médio ponderado móvel do tanque e grava no ledger imutável MovimentoEstoqueGas.
    Idempotente por chave NF-e e tanque.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'envase')

    validar_chave_nfe(chave_nfe)

    tanque = TanqueCriogenico.objects.select_for_update().get(id=tanque_id)
    if tanque.tenant_id != tenant.id:
        raise ValidationError("Tanque criogênico pertence a outro tenant.")

    if not tanque.ativo:
        raise ValidationError(f"O tanque {tanque.codigo} está inativo e não pode receber cargas.")

    # Idempotência: se já existir entrada para a mesma chave NF-e neste tanque
    entrada_existente = EntradaGasGranel.objects.filter(
        tenant=tenant,
        tanque=tanque,
        chave_nfe=chave_nfe
    ).first()
    if entrada_existente:
        mov = MovimentoEstoqueGas.objects.filter(
            tenant=tenant,
            tanque=tanque,
            origem_tipo='EntradaGasGranel',
            origem_id=str(entrada_existente.id)
        ).first()
        return tanque, entrada_existente, mov

    qtd_nf = quantize(quantidade_kg_nf, 3)
    qtd_rec = quantize(quantidade_kg_recebida, 3)
    c_nf = quantize(custo_total_nf, 2)
    c_frete = quantize(custo_frete, 2)
    c_imp = quantize(impostos_recuperaveis, 2)

    if qtd_rec <= Decimal('0.000'):
        raise ValidationError("A quantidade recebida de gás deve ser estritamente maior que zero.")

    if qtd_nf <= Decimal('0.000'):
        raise ValidationError("A quantidade faturada na NF deve ser estritamente maior que zero.")

    # Custo efetivo por kg
    custo_liquido_aquisicao = c_nf + c_frete - c_imp
    if custo_liquido_aquisicao < Decimal('0.00'):
        raise ValidationError("O custo líquido de aquisição (NF + frete - impostos) não pode ser negativo.")

    custo_unitario_efetivo = quantize(custo_liquido_aquisicao / qtd_rec, 4)
    custo_total_entrada = quantize(qtd_rec * custo_unitario_efetivo, 2)

    # Divergência de pesagem: NF x Balança
    div_kg = quantize(qtd_nf - qtd_rec, 3)
    div_pct = quantize(abs(div_kg) / qtd_nf, 4)
    alerta_div = div_pct > tanque.tolerancia_pesagem_pct

    data_rec = data_entrada or timezone.localdate()

    entrada = EntradaGasGranel.objects.create(
        tenant=tenant,
        tanque=tanque,
        fornecedor_nome=fornecedor_nome,
        fornecedor_documento=fornecedor_documento,
        chave_nfe=chave_nfe,
        data_entrada=data_rec,
        quantidade_kg_nf=qtd_nf,
        quantidade_kg_recebida=qtd_rec,
        custo_total_nf=c_nf,
        custo_frete=c_frete,
        impostos_recuperaveis=c_imp,
        custo_unitario_kg_efetivo=custo_unitario_efetivo,
        divergencia_peso_kg=div_kg,
        divergencia_peso_pct=div_pct,
        alerta_divergencia=alerta_div,
        observacoes=observacoes,
        usuario=usuario
    )

    # Recálculo do custo médio móvel ponderado (Sprint 8C - Tarefa 5)
    saldo_anterior_kg = tanque.saldo_atual_kg
    saldo_anterior_valor = tanque.saldo_valor_atual

    novo_saldo_kg = quantize(saldo_anterior_kg + qtd_rec, 3)
    novo_saldo_valor = quantize(saldo_anterior_valor + custo_total_entrada, 2)
    novo_custo_medio = quantize(novo_saldo_valor / novo_saldo_kg, 4) if novo_saldo_kg > Decimal('0.000') else Decimal('0.0000')

    tanque.saldo_atual_kg = novo_saldo_kg
    tanque.saldo_valor_atual = novo_saldo_valor
    tanque.custo_medio_kg_atual = novo_custo_medio
    tanque.save(update_fields=['saldo_atual_kg', 'saldo_valor_atual', 'custo_medio_kg_atual', 'atualizado_em'])

    mov = MovimentoEstoqueGas.objects.create(
        tenant=tenant,
        tanque=tanque,
        gas=tanque.gas,
        tipo='ENTRADA',
        quantidade_kg=qtd_rec,
        custo_unitario=custo_unitario_efetivo,
        custo_total=custo_total_entrada,
        saldo_quantidade_apos=novo_saldo_kg,
        saldo_valor_apos=novo_saldo_valor,
        custo_medio_apos=novo_custo_medio,
        origem_tipo='EntradaGasGranel',
        origem_id=str(entrada.id),
        justificativa=f"Entrada NFe {chave_nfe} fornecedor {fornecedor_nome}",
        usuario=usuario
    )

    publicar('entrada_gas_granel', {
        'tenant': tenant,
        'tanque_id': tanque.id,
        'entrada_id': entrada.id,
        'gas_id': tanque.gas_id,
        'quantidade_kg': str(qtd_rec),
        'custo_unitario_kg': str(custo_unitario_efetivo),
        'custo_total': str(custo_total_entrada),
        'novo_custo_medio_kg': str(novo_custo_medio),
        'alerta_divergencia': alerta_div,
        'divergencia_pct': str(div_pct)
    })

    return tanque, entrada, mov


@transaction.atomic
def registrar_medicao_tanque(
    *,
    tenant,
    tanque_id,
    massa_kg_medida,
    pressao_bar=Decimal('0.00'),
    nivel_percentual=None,
    origem='MANUAL',
    observacoes="",
    usuario=None,
    data_hora=None
):
    """
    Registra uma medição física de nível/massa do tanque criogênico (Sprint 8C - Tarefa 3).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'envase')

    tanque = TanqueCriogenico.objects.get(id=tanque_id)
    if tanque.tenant_id != tenant.id:
        raise ValidationError("Tanque criogênico pertence a outro tenant.")

    massa = quantize(massa_kg_medida, 3)
    if massa < Decimal('0.000'):
        raise ValidationError("A massa medida do tanque não pode ser negativa.")

    pressao = quantize(pressao_bar, 2)
    dt = data_hora or timezone.now()

    medicao = MedicaoTanque.objects.create(
        tenant=tenant,
        tanque=tanque,
        data_hora=dt,
        massa_kg_medida=massa,
        pressao_bar=pressao,
        nivel_percentual=nivel_percentual,
        origem=origem,
        usuario=usuario,
        observacoes=observacoes
    )
    return medicao


@transaction.atomic
def fechar_periodo_tanque(
    *,
    tenant,
    tanque_id,
    data_inicio,
    data_fim,
    medicao_final_kg,
    justificativa="",
    usuario=None
):
    """
    Fecha o balanço de massa do tanque e apura a perda por evaporação (boil-off) (Sprint 8C - Tarefa 6).
    Fórmula de balanço de massa:
        Perda = Saldo Inicial + Entradas do Período - Consumos de Envase do Período - Saldo Final Medido
    Se Perda > 0: grava MovimentoEstoqueGas com tipo PERDA_EVAPORACAO valorizado ao custo médio vigente.
    Se a perda percentual superar a tolerância do tanque, exige justificativa obrigatória.
    Publica o evento 'perda_gas_registrada'.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'envase')

    tanque = TanqueCriogenico.objects.select_for_update().get(id=tanque_id)
    if tanque.tenant_id != tenant.id:
        raise ValidationError("Tanque criogênico pertence a outro tenant.")

    med_final = quantize(medicao_final_kg, 3)
    if med_final < Decimal('0.000'):
        raise ValidationError("A medição final física não pode ser negativa.")

    if data_fim < data_inicio:
        raise ValidationError("A data final do período não pode ser anterior à data inicial.")

    # Apura movimentações dentro da janela do período
    movimentos_periodo = MovimentoEstoqueGas.objects.filter(
        tenant=tenant,
        tanque=tanque,
        criado_em__date__gte=data_inicio,
        criado_em__date__lte=data_fim
    ).order_by('criado_em')

    # Identifica o saldo inicial do período (último movimento antes da data_inicio)
    mov_anterior = MovimentoEstoqueGas.objects.filter(
        tenant=tenant,
        tanque=tanque,
        criado_em__date__lt=data_inicio
    ).order_by('-criado_em').first()

    saldo_inicial_kg = mov_anterior.saldo_quantidade_apos if mov_anterior else Decimal('0.000')

    # Totaliza entradas e consumos de rampa no período
    entradas_kg = sum(
        m.quantidade_kg for m in movimentos_periodo if m.tipo == 'ENTRADA'
    )
    consumo_envase_kg = sum(
        abs(m.quantidade_kg) for m in movimentos_periodo if m.tipo == 'CONSUMO_ENVASE'
    )

    # Saldo teórico esperado
    saldo_calculado_kg = quantize(saldo_inicial_kg + entradas_kg - consumo_envase_kg, 3)

    # Perda apurada por balanço de massa
    perda_kg = quantize(saldo_calculado_kg - med_final, 3)
    base_movimentada = saldo_inicial_kg + entradas_kg
    perda_pct = quantize(perda_kg / base_movimentada, 4) if base_movimentada > Decimal('0.000') else Decimal('0.0000')

    excedeu_tolerancia = perda_pct > tanque.tolerancia_perda_pct

    if excedeu_tolerancia and not justificativa.strip():
        raise ValidationError(
            f"Perda por evaporação ({perda_pct * Decimal('100.0')}%) excedeu a tolerância normativa do tanque "
            f"({tanque.tolerancia_perda_pct * Decimal('100.0')}%). Justificativa técnica é mandatória."
        )

    custo_medio_vigente = tanque.custo_medio_kg_atual
    mov_perda = None
    custo_perda = Decimal('0.00')

    if perda_kg > Decimal('0.000'):
        custo_perda = quantize(perda_kg * custo_medio_vigente, 2)
        novo_saldo_kg = med_final
        novo_saldo_valor = quantize(tanque.saldo_valor_atual - custo_perda, 2)
        novo_saldo_valor = max(Decimal('0.00'), novo_saldo_valor)

        tanque.saldo_atual_kg = novo_saldo_kg
        tanque.saldo_valor_atual = novo_saldo_valor
        # No boil-off de líquido puro a granel, o custo médio unitário kg permanece o mesmo
        tanque.save(update_fields=['saldo_atual_kg', 'saldo_valor_atual', 'atualizado_em'])

        mov_perda = MovimentoEstoqueGas.objects.create(
            tenant=tenant,
            tanque=tanque,
            gas=tanque.gas,
            tipo='PERDA_EVAPORACAO',
            quantidade_kg=-perda_kg,
            custo_unitario=custo_medio_vigente,
            custo_total=custo_perda,
            saldo_quantidade_apos=novo_saldo_kg,
            saldo_valor_apos=novo_saldo_valor,
            custo_medio_apos=custo_medio_vigente,
            origem_tipo='FechamentoPeriodoTanque',
            origem_id='',
            justificativa=justificativa or "Perda apurada por balanço de massa no fechamento de período.",
            usuario=usuario
        )

    fechamento = FechamentoPeriodoTanque.objects.create(
        tenant=tenant,
        tanque=tanque,
        data_inicio=data_inicio,
        data_fim=data_fim,
        saldo_inicial_kg=saldo_inicial_kg,
        total_entradas_kg=entradas_kg,
        total_consumo_envase_kg=consumo_envase_kg,
        saldo_final_calculado_kg=saldo_calculado_kg,
        saldo_final_medido_kg=med_final,
        perda_evaporacao_kg=perda_kg if perda_kg > Decimal('0.000') else Decimal('0.000'),
        perda_evaporacao_pct=perda_pct if perda_pct > Decimal('0.0000') else Decimal('0.0000'),
        custo_perda=custo_perda,
        excedeu_tolerancia=excedeu_tolerancia,
        justificativa=justificativa,
        movimento_perda=mov_perda,
        fechado_por=usuario
    )

    if mov_perda:
        mov_perda.origem_id = str(fechamento.id)
        mov_perda.save(update_fields=['origem_id'], force=True)

        publicar('perda_gas_registrada', {
            'tenant': tenant,
            'tanque_id': tanque.id,
            'fechamento_id': fechamento.id,
            'tipo_perda': 'BOIL_OFF_EVAPORACAO',
            'perda_kg': str(perda_kg),
            'perda_pct': str(perda_pct),
            'custo_perda': str(custo_perda),
            'excedeu_tolerancia': excedeu_tolerancia
        })

    return fechamento, mov_perda


@transaction.atomic
def registrar_perda_purga(
    *,
    tenant,
    tanque_id,
    quantidade_kg,
    justificativa="Purga técnica de rampa de envase",
    usuario=None
):
    """
    Registra a purga intencional de gás da rampa/linhas (Sprint 8C - Tarefa 6).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'envase')

    tanque = TanqueCriogenico.objects.select_for_update().get(id=tanque_id)
    if tanque.tenant_id != tenant.id:
        raise ValidationError("Tanque criogênico pertence a outro tenant.")

    qtd = quantize(quantidade_kg, 3)
    if qtd <= Decimal('0.000'):
        raise ValidationError("A quantidade purgada deve ser maior que zero.")

    if tanque.saldo_atual_kg < qtd:
        raise ValidationError(f"Saldo insuficiente no tanque {tanque.codigo} para registrar purga de {qtd} kg.")

    custo_medio = tanque.custo_medio_kg_atual
    custo_purga = quantize(qtd * custo_medio, 2)

    novo_saldo_kg = quantize(tanque.saldo_atual_kg - qtd, 3)
    novo_saldo_valor = quantize(tanque.saldo_valor_atual - custo_purga, 2)

    tanque.saldo_atual_kg = novo_saldo_kg
    tanque.saldo_valor_atual = novo_saldo_valor
    tanque.save(update_fields=['saldo_atual_kg', 'saldo_valor_atual', 'atualizado_em'])

    mov = MovimentoEstoqueGas.objects.create(
        tenant=tenant,
        tanque=tanque,
        gas=tanque.gas,
        tipo='PERDA_PURGA',
        quantidade_kg=-qtd,
        custo_unitario=custo_medio,
        custo_total=custo_purga,
        saldo_quantidade_apos=novo_saldo_kg,
        saldo_valor_apos=novo_saldo_valor,
        custo_medio_apos=custo_medio,
        origem_tipo='PurgaRampa',
        origem_id='',
        justificativa=justificativa,
        usuario=usuario
    )

    publicar('perda_gas_registrada', {
        'tenant': tenant,
        'tanque_id': tanque.id,
        'tipo_perda': 'PURGA_RAMPA',
        'perda_kg': str(qtd),
        'custo_perda': str(custo_purga)
    })

    return tanque, mov
