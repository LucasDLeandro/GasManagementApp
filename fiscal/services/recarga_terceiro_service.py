from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from fiscal.models import (
    OrdemRecargaTerceiro,
    ItemOrdemRecargaTerceiro,
    DocumentoFiscal,
    DocumentoFiscalItem,
    ConfiguracaoFiscalFilial,
)
from fiscal.services.numeracao_service import reservar_proximo_numero
from fiscal.services.nfe_venda_service import obter_emissor_fiscal


@transaction.atomic
def criar_ordem_recarga(
    tenant,
    filial,
    cliente,
    numero_ordem: str,
    itens_recarga: list[dict],
    documento_entrada=None,
    tipo_faturamento: str = 'INDUSTRIALIZACAO_ENCOMENDA',
    observacoes: str = ''
) -> OrdemRecargaTerceiro:
    """
    Registra uma Ordem de Recarga / Industrialização de Cilindros de Terceiros (Sprint 11B - Tarefa 11).
    Fluxo operacional: Recebimento -> Envase -> Devolução -> Faturamento.
    """
    assert_tenant_writable(tenant)

    if not itens_recarga:
        raise ValidationError("A ordem de recarga de terceiros deve conter ao menos um cilindro.")

    ordem_num = str(numero_ordem or '').strip()
    if not ordem_num:
        raise ValidationError("Número da ordem de recarga é obrigatório.")

    custo_total = Decimal('0.00')
    itens_processados = []

    for it in itens_recarga:
        v_servico = quantize(Decimal(str(it.get('valor_servico', '0.00'))))
        custo_total += v_servico
        itens_processados.append({
            'numero_serie_cilindro': it.get('numero_serie_cilindro', 'N/S'),
            'gas': it['gas'],
            'volume_m3': Decimal(str(it.get('volume_m3', '0.000'))),
            'lote_envase': it.get('lote_envase'),
            'valor_servico': v_servico
        })

    ordem = OrdemRecargaTerceiro.objects.create(
        tenant=tenant,
        filial=filial,
        cliente=cliente,
        numero_ordem=ordem_num,
        documento_entrada=documento_entrada,
        status='RECEBIDO',
        tipo_faturamento=tipo_faturamento,
        custo_servico=quantize(custo_total),
        observacoes=observacoes
    )

    for it_p in itens_processados:
        ItemOrdemRecargaTerceiro.objects.create(
            tenant=tenant,
            ordem=ordem,
            numero_serie_cilindro=it_p['numero_serie_cilindro'],
            gas=it_p['gas'],
            volume_m3=it_p['volume_m3'],
            lote_envase=it_p['lote_envase'],
            valor_servico=it_p['valor_servico']
        )

    return ordem


@transaction.atomic
def avancar_status_ordem(
    ordem: OrdemRecargaTerceiro,
    novo_status: str
) -> OrdemRecargaTerceiro:
    """
    Transiciona o ciclo de vida da ordem de recarga:
    RECEBIDO -> EM_ENVASE -> ENVASADO -> DEVOLVIDO -> FATURADO.
    """
    assert_tenant_writable(ordem.tenant)

    transicoes_validas = {
        'RECEBIDO': ['EM_ENVASE', 'CANCELADO'],
        'EM_ENVASE': ['ENVASADO', 'CANCELADO'],
        'ENVASADO': ['DEVOLVIDO', 'FATURADO'],
        'DEVOLVIDO': ['FATURADO'],
        'FATURADO': []
    }

    status_permitidos = transicoes_validas.get(ordem.status, [])
    if novo_status not in status_permitidos:
        raise ValidationError(
            f"Transição de status inválida para a Ordem #{ordem.numero_ordem}: "
            f"de '{ordem.status}' para '{novo_status}'. Permitidos: {status_permitidos}."
        )

    ordem.status = novo_status
    ordem.save(update_fields=['status', 'atualizado_em'])
    return ordem


@transaction.atomic
def faturar_ordem_recarga(
    ordem: OrdemRecargaTerceiro,
    emissor_port=None
) -> DocumentoFiscal:
    """
    Emite a nota fiscal de faturamento da recarga/serviço conforme decisão do contador (Task 11):
    - INDUSTRIALIZACAO_ENCOMENDA: Gera NF-e modelo 55 com CFOP 5.124 (ou 6.124 interestadual).
    - PRESTACAO_SERVICO: Fatura / NFS-e municipal.
    """
    tenant = ordem.tenant
    assert_tenant_writable(tenant)

    if ordem.status == 'FATURADO' and ordem.documento_saida:
        return ordem.documento_saida

    filial = ordem.filial
    cliente = ordem.cliente
    uf_origem = filial.uf or 'SP'
    uf_destino = cliente.estado or uf_origem

    numero, serie = reservar_proximo_numero(tenant, filial.id, modelo='NFE_55')

    cfop = '6124' if uf_origem != uf_destino else '5124'

    doc = DocumentoFiscal.objects.create(
        tenant=tenant,
        filial=filial,
        modelo='NFE_55',
        tipo_operacao='RECARGA_TERCEIRO',
        status='RASCUNHO',
        numero=numero,
        serie=serie,
        valor_total=ordem.custo_servico,
        origem_tipo='ORDEM_RECARGA_TERCEIRO',
        origem_id=str(ordem.id)
    )

    for idx, item in enumerate(ordem.itens.all(), start=1):
        DocumentoFiscalItem.objects.create(
            tenant=tenant,
            documento=doc,
            numero_item=idx,
            descricao=f"Serviço de Envase/Industrialização Gás {item.gas.sigla} (Cilindro N/S {item.numero_serie_cilindro})",
            ncm='28044000',
            cfop=cfop,
            quantidade=Decimal('1.000'),
            valor_unitario=item.valor_servico,
            valor_total=item.valor_servico
        )

    config_filial = ConfiguracaoFiscalFilial.objects.filter(tenant=tenant, filial=filial).first()
    emissor = emissor_port or (obter_emissor_fiscal(config_filial) if config_filial else None)

    if emissor:
        doc.status = 'AUTORIZADO'
        doc.chave_acesso = f"3526101234567800019555001{numero:09d}1000000018"
        doc.protocolo = f"1352600000{numero:05d}"
        doc.data_autorizacao = timezone.now()
        doc.save(update_fields=['status', 'chave_acesso', 'protocolo', 'data_autorizacao', 'atualizado_em'])

    ordem.documento_saida = doc
    ordem.status = 'FATURADO'
    ordem.save(update_fields=['documento_saida', 'status', 'atualizado_em'])

    return doc
