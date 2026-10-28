from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from produtos.models import ClasseRiscoGas, GasQuimico
from logistica.models import Entrega, Veiculo
from fiscal.models import (
    DocumentoFiscal,
    DocumentoFiscalEvento,
    ConfiguracaoMDFe,
    ConfiguracaoFiscalFilial,
)
from fiscal.services.numeracao_service import reservar_proximo_numero
from fiscal.services.nfe_venda_service import obter_emissor_fiscal


@transaction.atomic
def emitir_cte_transporte(
    tenant,
    filial,
    tomador_cliente,
    remetente,
    destinatario,
    valor_frete: Decimal,
    aliquota_icms: Decimal = Decimal('0.1200'),
    observacoes: str = '',
    emissor_port=None
) -> DocumentoFiscal:
    """
    Emite CT-e (modelo 57) para prestação de serviço de transporte remunerado a terceiros (Task 7 / Correção F-27).
    Regra de negócio estrita:
    - Apenas tenants com presta_servico_transporte = True podem emitir CT-e.
    - Venda com frete próprio (CIF) NÃO emite CT-e (o transporte é coberto pela NF-e e MDF-e).
    """
    assert_tenant_writable(tenant)

    if not getattr(tenant, 'presta_servico_transporte', False):
        raise ValidationError(
            "Emissão de CT-e bloqueada (Correção F-27): O Tenant não está habilitado para prestação "
            "de serviços de transporte remunerado a terceiros (presta_servico_transporte=False). "
            "Vendas com frete próprio (CIF) são cobertas pela NF-e e MDF-e."
        )

    if valor_frete <= Decimal('0.00'):
        raise ValidationError("O valor do frete para emissão de CT-e deve ser maior que zero.")

    config_filial = ConfiguracaoFiscalFilial.objects.filter(tenant=tenant, filial=filial).first()
    emissor = emissor_port or (obter_emissor_fiscal(config_filial) if config_filial else None)

    numero, serie = reservar_proximo_numero(tenant, filial.id, modelo='CTE_57')
    v_frete = quantize(valor_frete)
    v_icms = quantize(v_frete * aliquota_icms)

    payload_cte = {
        'identificacao': {
            'numero': numero,
            'serie': serie,
            'modelo': '57',
            'natureza_operacao': 'PRESTACAO DE SERVICO DE TRANSPORTE',
            'cfop': '5353' if filial.uf == destinatario.estado else '6353',
            'data_emissao': timezone.now().isoformat(),
        },
        'tomador': {
            'nome': tomador_cliente.nome,
            'documento': tomador_cliente.cnpj or tomador_cliente.cpf,
            'uf': tomador_cliente.estado or filial.uf
        },
        'valores': {
            'valor_prestacao': v_frete,
            'valor_a_receber': v_frete,
            'base_icms': v_frete,
            'aliquota_icms': aliquota_icms,
            'valor_icms': v_icms
        }
    }

    doc = DocumentoFiscal.objects.create(
        tenant=tenant,
        filial=filial,
        modelo='CTE_57',
        tipo_operacao='CTE_TRANSPORTE',
        status='ENVIADO',
        numero=numero,
        serie=serie,
        valor_total=v_frete,
        origem_tipo='PRESTACAO_TRANSPORTE',
        origem_id=str(tomador_cliente.id)
    )

    if emissor:
        resposta = emissor.emitir_cte(payload_cte)
        if resposta.sucesso:
            doc.status = 'AUTORIZADO'
            doc.chave_acesso = resposta.chave_acesso
            doc.protocolo = resposta.protocolo
            doc.data_autorizacao = timezone.now()
        else:
            doc.status = 'REJEITADO'
            doc.motivo_rejeicao = resposta.mensagem_erro
        doc.save(update_fields=['status', 'chave_acesso', 'protocolo', 'motivo_rejeicao', 'data_autorizacao', 'atualizado_em'])

    return doc


@transaction.atomic
def montar_e_emitir_mdfe(
    entrega: Entrega,
    config_mdfe: ConfiguracaoMDFe = None,
    emissor_port=None
) -> DocumentoFiscal:
    """
    Emite Manifesto Eletrônico de Documentos Fiscais - MDF-e modelo 58 (Task 8).
    - Agrupa as NF-es das vendas vinculadas à entrega.
    - Inclui dados do veículo (placa, RNTRC, tara, capacidade).
    - Inclui dados do condutor (motorista).
    - Agrupa dados de Produtos Perigosos da ClasseRiscoGas para cada gás transportado.
    - UFs de percurso (origem -> destino).
    """
    tenant = entrega.tenant
    assert_tenant_writable(tenant)

    filial = entrega.filial
    veiculo = entrega.veiculo
    motorista = entrega.motorista

    if not veiculo:
        raise ValidationError(f"A entrega #{entrega.id} não possui veículo alocado para emissão de MDF-e.")

    # Busca NF-es autorizadas das vendas da entrega
    vendas_ids = list(entrega.vendas.values_list('id', flat=True))
    documentos_nfe = list(DocumentoFiscal.objects.filter(
        tenant=tenant,
        origem_tipo='VENDA',
        origem_id__in=[str(v_id) for v_id in vendas_ids],
        modelo='NFE_55',
        status='AUTORIZADO'
    ))

    # Identifica produtos perigosos transportados a partir dos gases
    gases_transportados = set()
    for v in entrega.vendas.all():
        for item in v.itens.all():
            if item.sku and item.sku.gas:
                gases_transportados.add(item.sku.gas)
            elif item.produto and hasattr(item.produto, 'gas') and item.produto.gas:
                gases_transportados.add(item.produto.gas)

    perigosos_info = []
    for g in gases_transportados:
        cr = ClasseRiscoGas.objects.filter(tenant=tenant, gas=g).first()
        if cr:
            perigosos_info.append({
                'numero_onu': cr.numero_onu,
                'nome_embarque': cr.descricao_transporte,
                'classe_risco': cr.classe_risco,
                'grupo_embalagem': cr.grupo_embalagem
            })

    numero, serie = reservar_proximo_numero(tenant, filial.id, modelo='MDFE_58')
    valor_total_carga = sum((doc.valor_total for doc in documentos_nfe), Decimal('0.00'))

    payload_mdfe = {
        'identificacao': {
            'numero': numero,
            'serie': serie,
            'modelo': '58',
            'uf_emissor': filial.uf or 'SP',
            'tipo_emissao': 1,  # Normal
            'data_emissao': timezone.now().isoformat(),
        },
        'veiculo': {
            'placa': veiculo.placa,
            'rntrc': veiculo.rntrc_antt or '',
            'tara': int(veiculo.tara_veiculo_kg or 0),
            'capacidade_kg': int(veiculo.capacidade_carga or 0)
        },
        'condutor': {
            'nome': motorista.get_full_name() or motorista.username if motorista else 'Condutor Designado',
            'cpf': getattr(motorista, 'cpf', '') or '00000000000'
        },
        'documentos_nfe': [d.chave_acesso for d in documentos_nfe if d.chave_acesso],
        'produtos_perigosos': perigosos_info,
        'totais': {
            'valor_total_carga': quantize(valor_total_carga),
            'peso_bruto': entrega.peso_total_carregado
        }
    }

    doc = DocumentoFiscal.objects.create(
        tenant=tenant,
        filial=filial,
        modelo='MDFE_58',
        tipo_operacao='MDFE_CARGA',
        status='ENVIADO',
        numero=numero,
        serie=serie,
        valor_total=quantize(valor_total_carga),
        origem_tipo='ENTREGA_ROTA',
        origem_id=str(entrega.id)
    )

    config_filial = ConfiguracaoFiscalFilial.objects.filter(tenant=tenant, filial=filial).first()
    emissor = emissor_port or (obter_emissor_fiscal(config_filial) if config_filial else None)

    if emissor:
        resposta = emissor.emitir_mdfe(payload_mdfe)
        if resposta.sucesso:
            doc.status = 'AUTORIZADO'
            doc.chave_acesso = resposta.chave_acesso
            doc.protocolo = resposta.protocolo
            doc.data_autorizacao = timezone.now()
        else:
            doc.status = 'REJEITADO'
            doc.motivo_rejeicao = resposta.mensagem_erro
        doc.save(update_fields=['status', 'chave_acesso', 'protocolo', 'motivo_rejeicao', 'data_autorizacao', 'atualizado_em'])

    return doc


@transaction.atomic
def encerrar_mdfe_entrega(
    entrega: Entrega,
    municipio_ibge: str = None,
    emissor_port=None
) -> DocumentoFiscalEvento:
    """
    Encerra automaticamente o MDF-e vinculado à entrega ao ser concluída no PWA (Task 8).
    """
    tenant = entrega.tenant
    assert_tenant_writable(tenant)

    mdfe_doc = DocumentoFiscal.objects.filter(
        tenant=tenant,
        modelo='MDFE_58',
        origem_tipo='ENTREGA_ROTA',
        origem_id=str(entrega.id),
        status='AUTORIZADO'
    ).first()

    if not mdfe_doc:
        return None

    config_filial = ConfiguracaoFiscalFilial.objects.filter(tenant=tenant, filial=entrega.filial).first()
    emissor = emissor_port or (obter_emissor_fiscal(config_filial) if config_filial else None)
    cod_ibge = municipio_ibge or entrega.filial.municipio_ibge or '3550308'

    if not emissor:
        raise ValidationError("Emissor fiscal não configurado para encerramento de MDF-e.")

    resposta = emissor.encerrar_mdfe(
        chave=mdfe_doc.chave_acesso,
        protocolo=mdfe_doc.protocolo,
        municipio_ibge=cod_ibge
    )

    evento = DocumentoFiscalEvento.objects.create(
        tenant=tenant,
        documento=mdfe_doc,
        tipo_evento='ENCERRAMENTO',
        sequencial=1,
        protocolo=resposta.protocolo or '135260000000000',
        justificativa="Encerramento de manifesto de carga na conclusão da entrega",
        status='AUTORIZADO' if resposta.sucesso else 'REJEITADO'
    )

    if resposta.sucesso:
        mdfe_doc.status = 'CANCELADO'  # Ou status representativo de finalizado/encerrado
        mdfe_doc.save(update_fields=['status', 'atualizado_em'])

    return evento


def verificar_mdfes_abertos_alerta(tenant, filial=None, prazo_horas: int = 24) -> list[dict]:
    """
    Auditoria periódica (Task 8): detecta MDF-es autorizados abertos há mais de prazo_horas (ex: 24h)
    sem o respectivo evento de encerramento perante a SEFAZ.
    """
    limite = timezone.now() - timedelta(hours=prazo_horas)
    qs = DocumentoFiscal.objects.filter(
        tenant=tenant,
        modelo='MDFE_58',
        status='AUTORIZADO',
        data_autorizacao__lte=limite
    )
    if filial:
        qs = qs.filter(filial=filial)

    alertas = []
    for doc in qs:
        # Verifica se já possui evento de encerramento
        tem_encerramento = DocumentoFiscalEvento.objects.filter(
            tenant=tenant,
            documento=doc,
            tipo_evento='ENCERRAMENTO',
            status='AUTORIZADO'
        ).exists()

        if not tem_encerramento:
            horas_aberto = int((timezone.now() - doc.data_autorizacao).total_seconds() / 3600)
            alertas.append({
                'documento_id': doc.id,
                'numero': doc.numero,
                'serie': doc.serie,
                'chave_acesso': doc.chave_acesso,
                'filial': doc.filial.nome,
                'horas_aberto': horas_aberto,
                'mensagem': f"MDF-e #{doc.numero} Série {doc.serie} aberto há {horas_aberto} horas sem encerramento na SEFAZ (limite: {prazo_horas}h)."
            })

    return alertas
