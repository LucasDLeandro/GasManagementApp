"""
Ledger de estoque de produtos acabados e recargas de cilindros (Sprint 8C - Tarefa 8).
Método de valorização: Custo Médio Ponderado Móvel por Filial e Produto/SKU.
Estritamente append-only e sob bloqueio de concorrência.
"""

from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from produtos.models import MovimentoEstoqueProduto, SkuRecarga, Produto


@transaction.atomic
def movimentar_estoque_produto(
    *,
    tenant,
    filial=None,
    sku=None,
    produto=None,
    tipo,
    quantidade,
    custo_unitario=Decimal('0.00'),
    origem_tipo="",
    origem_id="",
    justificativa="",
    usuario=None
):
    """
    Registra movimentação no ledger de produto acabado (Sprint 8C - Tarefa 8).
    Entradas recalculam a média móvel:
        Novo Saldo Quantidade = Saldo Anterior + Qtd
        Novo Saldo Valor = Saldo Valor Anterior + (Qtd × Custo Unitário)
        Novo Custo Médio = Novo Saldo Valor ÷ Novo Saldo Quantidade
    Saídas valorizam ao custo médio ponderado vigente:
        Custo Total = |Qtd| × Custo Médio Vigente
        Novo Saldo Quantidade = Saldo Anterior - |Qtd|
        Novo Saldo Valor = Saldo Valor Anterior - Custo Total
    """
    assert_tenant_writable(tenant)

    if not sku and not produto:
        raise ValidationError("É obrigatório informar ao menos o SKU de Recarga ou o Produto.")

    qtd = quantize(quantidade, 3)
    if qtd == Decimal('0.000'):
        raise ValidationError("A quantidade a movimentar não pode ser zero.")

    # Busca o último saldo deste item na filial
    ultimo_mov = MovimentoEstoqueProduto.objects.select_for_update().filter(
        tenant=tenant,
        filial=filial,
        sku=sku,
        produto=produto
    ).order_by('-criado_em').first()

    saldo_anterior_qtd = ultimo_mov.saldo_quantidade_apos if ultimo_mov else Decimal('0.000')
    saldo_anterior_valor = ultimo_mov.saldo_valor_apos if ultimo_mov else Decimal('0.00')
    custo_medio_vigente = ultimo_mov.custo_medio_apos if ultimo_mov else Decimal('0.00')

    is_entrada = tipo in ('ENTRADA_PRODUCAO', 'ENTRADA_COMPRA') or (tipo == 'AJUSTE' and qtd > Decimal('0.000'))

    if is_entrada:
        qtd_positiva = abs(qtd)
        custo_unit = quantize(custo_unitario, 2)
        custo_total = quantize(qtd_positiva * custo_unit, 2)

        novo_saldo_qtd = quantize(saldo_anterior_qtd + qtd_positiva, 3)
        novo_saldo_valor = quantize(saldo_anterior_valor + custo_total, 2)
        novo_custo_medio = quantize(novo_saldo_valor / novo_saldo_qtd, 2) if novo_saldo_qtd > Decimal('0.000') else Decimal('0.00')

        mov = MovimentoEstoqueProduto.objects.create(
            tenant=tenant,
            filial=filial,
            sku=sku,
            produto=produto,
            tipo=tipo,
            quantidade=qtd_positiva,
            custo_unitario=custo_unit,
            custo_total=custo_total,
            saldo_quantidade_apos=novo_saldo_qtd,
            saldo_valor_apos=novo_saldo_valor,
            custo_medio_apos=novo_custo_medio,
            origem_tipo=origem_tipo,
            origem_id=origem_id,
            justificativa=justificativa
        )
    else:
        # Saída (venda, perda ou ajuste negativo)
        qtd_saida = abs(qtd)
        custo_unit = custo_medio_vigente
        custo_total = quantize(qtd_saida * custo_unit, 2)

        novo_saldo_qtd = quantize(saldo_anterior_qtd - qtd_saida, 3)
        novo_saldo_valor = quantize(saldo_anterior_valor - custo_total, 2)
        novo_saldo_valor = max(Decimal('0.00'), novo_saldo_valor)
        novo_custo_medio = custo_medio_vigente

        mov = MovimentoEstoqueProduto.objects.create(
            tenant=tenant,
            filial=filial,
            sku=sku,
            produto=produto,
            tipo=tipo,
            quantidade=-qtd_saida,
            custo_unitario=custo_unit,
            custo_total=custo_total,
            saldo_quantidade_apos=novo_saldo_qtd,
            saldo_valor_apos=novo_saldo_valor,
            custo_medio_apos=novo_custo_medio,
            origem_tipo=origem_tipo,
            origem_id=origem_id,
            justificativa=justificativa
        )

    return mov


@transaction.atomic
def baixar_estoque_venda_faturada(venda):
    """
    Realiza a baixa de estoque dos itens vendidos e apura o CPV total da venda (Sprint 8C - Tarefa 8).
    Retorna o custo total de CPV para inclusão no payload do evento 'venda_faturada'.
    """
    cpv_total = Decimal('0.00')

    # Idempotente: a venda pode passar por 'Faturada' e depois 'Finalizada';
    # o estoque só é baixado uma vez por venda.
    baixas_existentes = MovimentoEstoqueProduto.unscoped.filter(
        tenant=venda.tenant, tipo='SAIDA_VENDA', origem_tipo='Venda', origem_id=str(venda.id)
    )
    if baixas_existentes.exists():
        for mov in baixas_existentes:
            cpv_total += mov.custo_total
        return quantize(cpv_total, 2)

    for item in venda.itens.all():
        qtd_item = Decimal(str(item.quantidade))
        sku = item.sku
        produto = item.produto

        mov = movimentar_estoque_produto(
            tenant=venda.tenant,
            filial=venda.filial,
            sku=sku,
            produto=produto,
            tipo='SAIDA_VENDA',
            quantidade=qtd_item,
            origem_tipo='Venda',
            origem_id=str(venda.id),
            justificativa=f"Baixa por faturamento da Venda #{venda.id}"
        )
        cpv_total += mov.custo_total

    return quantize(cpv_total, 2)
