"""
Serviço de fechamento industrial de lote de envase e apropriação de custos (Sprint 8C - Tarefa 7 / Correção F-20).
Apropriação de custos:
- Matéria-prima: Gás a granel baixado do tanque ao custo médio móvel vigente.
- Perdas de rampa/purga rateadas.
- Energia elétrica: taxa estimada por kg comprimido via CustoEnergiaRampa.
- Mão de obra operacional de envase.
- Entrada automática no estoque de produto acabado (MovimentoEstoqueProduto) ao custo apurado por cilindro.
- Suporte a estorno auditado com recomposição integral de estoques.
"""

from decimal import Decimal
import uuid
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.eventos import publicar
from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from produtos.models import (
    LoteEnvase,
    TanqueCriogenico,
    MovimentoEstoqueGas,
    CustoLoteEnvase,
    CustoEnergiaRampa,
    SkuRecarga,
)
from produtos.services.estoque_produto import movimentar_estoque_produto
from produtos.unidades import converter_m3_para_kg


@transaction.atomic
def fechar_lote_envase(
    *,
    lote_id,
    tanque_id,
    taxa_energia_kwh_por_kg=None,
    custo_kwh=None,
    custo_mao_de_obra=Decimal('0.00'),
    percentual_perda_rampa=Decimal('0.0000'),
    usuario=None,
    client_uuid=None
):
    """
    Realiza o fechamento técnico e financeiro do lote de envase (Sprint 8C - Tarefa 7).
    Baixa do tanque criogênico a massa de gás envasada, apura os custos de produção,
    cria o CustoLoteEnvase imutável e dá entrada no estoque de produto acabado.
    Publica o evento 'lote_envase_fechado'.
    """
    lote = LoteEnvase.objects.select_for_update().get(id=lote_id)
    tenant = lote.tenant

    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'envase')

    if lote.fechado:
        # Idempotência se o custo já foi apurado
        custo_existente = CustoLoteEnvase.objects.filter(lote=lote, estornado=False).first()
        if custo_existente:
            return lote, custo_existente
        raise ValidationError(f"O lote {lote.codigo_lote} já se encontra fechado.")

    tanque = TanqueCriogenico.objects.select_for_update().get(id=tanque_id)
    if tanque.tenant_id != tenant.id:
        raise ValidationError("O tanque criogênico pertence a outro tenant.")

    if not tanque.ativo:
        raise ValidationError(f"O tanque {tanque.codigo} está inativo.")

    if tanque.gas_id != lote.gas_id:
        raise ValidationError(
            f"Incompatibilidade química: o lote {lote.codigo_lote} envasa {lote.gas.sigla}, "
            f"mas o tanque {tanque.codigo} armazena {tanque.gas.sigla}."
        )

    # Coleta cilindros envasados no lote
    envases = lote.cilindros_envasados.select_related('cilindro', 'cilindro__modelo').all()
    if not envases.exists():
        raise ValidationError(f"O lote {lote.codigo_lote} não possui nenhum cilindro envasado apontado.")

    massa_total_lote_kg = Decimal('0.000')

    # Apura massa líquida de cada cilindro
    fator_conversao = lote.gas.fator_conversao_m3_por_kg or Decimal('0.7500')

    for envase in envases:
        if envase.massa_liquida_gas_kg and envase.massa_liquida_gas_kg > Decimal('0.000'):
            massa_cil = envase.massa_liquida_gas_kg
        elif envase.peso_cheio_kg and envase.tara_cilindro_kg:
            massa_cil = max(Decimal('0.000'), envase.peso_cheio_kg - envase.tara_cilindro_kg)
        elif envase.cilindro.modelo and envase.cilindro.modelo.massa_gas_padrao_kg:
            massa_cil = envase.cilindro.modelo.massa_gas_padrao_kg
        elif envase.cilindro.modelo and envase.cilindro.modelo.volume_hidraulico_litros:
            # Fallback por conversão volumétrica
            vol_m3 = quantize(envase.cilindro.modelo.volume_hidraulico_litros / Decimal('1000.0'), 3)
            massa_cil = converter_m3_para_kg(vol_m3, fator_conversao)
        else:
            massa_cil = Decimal('10.000') # Padrão industrial

        massa_total_lote_kg += massa_cil

    massa_total_lote_kg = quantize(massa_total_lote_kg, 3)

    if massa_total_lote_kg <= Decimal('0.000'):
        raise ValidationError("A massa total calculada de gás do lote deve ser maior que zero.")

    # Validação mandatória: nenhum saldo de tanque fica negativo
    if tanque.saldo_atual_kg < massa_total_lote_kg:
        raise ValidationError(
            f"Saldo insuficiente no tanque {tanque.codigo} ({tanque.saldo_atual_kg} kg) "
            f"para atender o envase de {massa_total_lote_kg} kg do lote {lote.codigo_lote}."
        )

    # 1. Custo da matéria-prima (Gás líquido baixado ao custo médio móvel vigente)
    custo_medio_gas = tanque.custo_medio_kg_atual
    custo_gas = quantize(massa_total_lote_kg * custo_medio_gas, 2)

    # Baixa do tanque
    novo_saldo_tanque_kg = quantize(tanque.saldo_atual_kg - massa_total_lote_kg, 3)
    novo_saldo_tanque_valor = quantize(tanque.saldo_valor_atual - custo_gas, 2)
    novo_saldo_tanque_valor = max(Decimal('0.00'), novo_saldo_tanque_valor)

    tanque.saldo_atual_kg = novo_saldo_tanque_kg
    tanque.saldo_valor_atual = novo_saldo_tanque_valor
    tanque.save(update_fields=['saldo_atual_kg', 'saldo_valor_atual', 'atualizado_em'])

    # Grava MovimentoEstoqueGas imutável
    mov_gas = MovimentoEstoqueGas.objects.create(
        tenant=tenant,
        tanque=tanque,
        gas=tanque.gas,
        tipo='CONSUMO_ENVASE',
        quantidade_kg=-massa_total_lote_kg,
        custo_unitario=custo_medio_gas,
        custo_total=custo_gas,
        saldo_quantidade_apos=novo_saldo_tanque_kg,
        saldo_valor_apos=novo_saldo_tanque_valor,
        custo_medio_apos=custo_medio_gas,
        origem_tipo='LoteEnvase',
        origem_id=str(lote.id),
        justificativa=f"Consumo de gás no fechamento do Lote de Envase #{lote.codigo_lote}",
        usuario=usuario
    )

    # 2. Custo de perda rateada de rampa
    pct_perda = quantize(percentual_perda_rampa, 4)
    custo_perda_rateada = quantize(custo_gas * pct_perda, 2)

    # 3. Custo de energia elétrica da rampa
    mes_competencia = timezone.localdate().strftime('%Y-%m')
    filial = getattr(tanque, 'filial', None)
    param_energia = CustoEnergiaRampa.objects.filter(
        tenant=tenant,
        filial=filial,
        mes_ano=mes_competencia
    ).first()

    kwh_kg = quantize(taxa_energia_kwh_por_kg or (param_energia.kwh_por_kg_padrao if param_energia else Decimal('0.1500')), 4)
    v_kwh = quantize(custo_kwh or (param_energia.custo_kwh_estimado if param_energia else Decimal('0.8500')), 4)
    custo_energia = quantize(massa_total_lote_kg * kwh_kg * v_kwh, 2)

    # 4. Mão de obra operacional
    custo_mo = quantize(custo_mao_de_obra, 2)

    # 5. Custo industrial total e unitário
    custo_total_lote = quantize(custo_gas + custo_perda_rateada + custo_energia + custo_mo, 2)
    total_cilindros = envases.count()
    custo_por_cilindro = quantize(custo_total_lote / Decimal(str(total_cilindros)), 2)
    custo_por_kg = quantize(custo_total_lote / massa_total_lote_kg, 4)

    custo_lote = CustoLoteEnvase.objects.create(
        tenant=tenant,
        lote=lote,
        tanque_origem=tanque,
        massa_gas_kg=massa_total_lote_kg,
        custo_gas=custo_gas,
        custo_perda_rateada=custo_perda_rateada,
        custo_energia=custo_energia,
        custo_mao_de_obra=custo_mo,
        custo_total=custo_total_lote,
        quantidade_cilindros=total_cilindros,
        custo_por_cilindro=custo_por_cilindro,
        custo_por_kg=custo_por_kg
    )

    # Atualiza status do lote
    lote.fechado = True
    lote.fechado_em = timezone.now()
    lote.tanque_origem = tanque
    lote.massa_gas_total_kg = massa_total_lote_kg
    lote.save(update_fields=['fechado', 'fechado_em', 'tanque_origem', 'massa_gas_total_kg'])

    # 6. Entrada de produto acabado no estoque (Sprint 8C - Tarefa 8)
    # Agrupa por SKU de recarga dos cilindros
    for envase in envases:
        sku = SkuRecarga.objects.filter(
            tenant=tenant,
            gas=lote.gas,
            modelo_cilindro=envase.cilindro.modelo
        ).first()

        movimentar_estoque_produto(
            tenant=tenant,
            filial=filial,
            sku=sku,
            produto=None,
            tipo='ENTRADA_PRODUCAO',
            quantidade=Decimal('1.000'),
            custo_unitario=custo_por_cilindro,
            origem_tipo='LoteEnvase',
            origem_id=str(lote.id),
            justificativa=f"Produção Lote #{lote.codigo_lote} Cilindro {envase.cilindro.numero_serie_ogiva}",
            usuario=usuario
        )

    # Publica evento de domínio
    publicar('lote_envase_fechado', {
        'tenant': tenant,
        'lote_id': lote.id,
        'codigo_lote': lote.codigo_lote,
        'tanque_id': tanque.id,
        'gas_id': lote.gas_id,
        'massa_total_kg': str(massa_total_lote_kg),
        'total_cilindros': total_cilindros,
        'custo_gas': str(custo_gas),
        'custo_energia': str(custo_energia),
        'custo_total': str(custo_total_lote),
        'custo_por_cilindro': str(custo_por_cilindro),
        'custo_por_kg': str(custo_por_kg)
    })

    return lote, custo_lote


@transaction.atomic
def estornar_fechamento_lote(
    *,
    lote_id,
    motivo="Estorno operacional de fechamento de lote",
    usuario=None
):
    """
    Estorna o fechamento de um lote de envase (Sprint 8C - Tarefa 7).
    Recompõe o saldo de gás no tanque criogênico via AJUSTE_INVENTARIO,
    estorna o CustoLoteEnvase e remove a entrada no estoque de produtos acabados.
    """
    lote = LoteEnvase.objects.select_for_update().get(id=lote_id)
    tenant = lote.tenant

    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'envase')

    if not lote.fechado:
        raise ValidationError(f"O lote {lote.codigo_lote} não está fechado.")

    custo = CustoLoteEnvase.objects.select_for_update().filter(lote=lote, estornado=False).first()
    if not custo:
        raise ValidationError(f"Não há custo ativo a estornar para o lote {lote.codigo_lote}.")

    tanque = TanqueCriogenico.objects.select_for_update().get(id=custo.tanque_origem_id)

    # Recompõe saldo do tanque
    massa_devolver = custo.massa_gas_kg
    valor_devolver = custo.custo_gas

    novo_saldo_tanque_kg = quantize(tanque.saldo_atual_kg + massa_devolver, 3)
    novo_saldo_tanque_valor = quantize(tanque.saldo_valor_atual + valor_devolver, 2)

    tanque.saldo_atual_kg = novo_saldo_tanque_kg
    tanque.saldo_valor_atual = novo_saldo_tanque_valor
    tanque.save(update_fields=['saldo_atual_kg', 'saldo_valor_atual', 'atualizado_em'])

    # Movimento de ajuste de estoque no tanque
    MovimentoEstoqueGas.objects.create(
        tenant=tenant,
        tanque=tanque,
        gas=tanque.gas,
        tipo='AJUSTE_INVENTARIO',
        quantidade_kg=massa_devolver,
        custo_unitario=tanque.custo_medio_kg_atual,
        custo_total=valor_devolver,
        saldo_quantidade_apos=novo_saldo_tanque_kg,
        saldo_valor_apos=novo_saldo_tanque_valor,
        custo_medio_apos=tanque.custo_medio_kg_atual,
        origem_tipo='EstornoLoteEnvase',
        origem_id=str(lote.id),
        justificativa=f"Recomposição por estorno do fechamento do Lote #{lote.codigo_lote}: {motivo}",
        usuario=usuario
    )

    # Reverte as entradas de produto acabado
    envases = lote.cilindros_envasados.select_related('cilindro', 'cilindro__modelo').all()
    filial = getattr(tanque, 'filial', None)

    for envase in envases:
        sku = SkuRecarga.objects.filter(
            tenant=tenant,
            gas=lote.gas,
            modelo_cilindro=envase.cilindro.modelo
        ).first()

        movimentar_estoque_produto(
            tenant=tenant,
            filial=filial,
            sku=sku,
            produto=None,
            tipo='AJUSTE',
            quantidade=Decimal('-1.000'),
            custo_unitario=custo.custo_por_cilindro,
            origem_tipo='EstornoLoteEnvase',
            origem_id=str(lote.id),
            justificativa=f"Estorno de produção do Lote #{lote.codigo_lote}"
        )

    # Marca custo como estornado
    custo.estornado = True
    custo.data_estorno = timezone.now()
    custo.motivo_estorno = motivo
    custo.usuario_estorno = usuario
    custo.save(update_fields=['estornado', 'data_estorno', 'motivo_estorno', 'usuario_estorno'])

    # Reabre o lote
    lote.fechado = False
    lote.save(update_fields=['fechado'])

    return lote, custo
