import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError

from core.money import quantize, allocate
from core.guards import assert_tenant_writable
from core.eventos import publicar
from core.modulos import is_modulo_ativo
from fiscal.models import (
    ConfiguracaoFiscalFilial,
    DocumentoFiscal,
    DocumentoFiscalItem,
    ItemDocumentoTributo,
)
from fiscal.validators import (
    validar_cpf_ou_cnpj,
    validar_inscricao_estadual,
    validar_ncm,
    validar_cest,
    validar_cfop,
    limpar_formatacao,
)
from fiscal.services.motor_tributario_service import resolver_regra, calcular_tributos_item
from fiscal.services.numeracao_service import reservar_proximo_numero, registrar_lacuna_inutilizacao
from fiscal.adapters.fake_emissor import FakeEmissor
from fiscal.adapters.gateway_emissor import GatewayEmissor

logger = logging.getLogger(__name__)


def obter_emissor_fiscal(config: ConfiguracaoFiscalFilial):
    """Retorna a implementação de EmissorFiscalPort adequada para a configuração da filial."""
    backend = getattr(settings, 'FISCAL_EMISSOR_BACKEND', 'AUTO')
    if backend == 'FAKE' or config.ambiente == 'HOMOLOGACAO' and not config.credenciais_gateway_cifradas:
        return FakeEmissor()
    
    credenciais = config.get_credenciais()
    if credenciais:
        return GatewayEmissor(
            ambiente=config.ambiente,
            api_key=credenciais.get('api_key', ''),
            api_secret=credenciais.get('api_secret', ''),
            endpoint_url=credenciais.get('endpoint_url', '')
        )
    return FakeEmissor()


def montar_nfe(venda, config: ConfiguracaoFiscalFilial, numero: int, serie: int) -> dict:
    """
    Função pura que constrói a estrutura de dados (payload) canônica da NF-e (Task 7).
    Garante a conformidade com o Manual de Orientação do Contribuinte (MOC) e as NTs da SEFAZ.
    """
    filial = config.filial
    cliente = venda.cliente

    uf_origem = str(getattr(filial, 'uf', 'SP') or 'SP').strip().upper()
    uf_destino = str(getattr(cliente, 'estado', uf_origem) or uf_origem).strip().upper()

    itens_payload = []
    total_produtos = Decimal('0.00')
    itens_venda = getattr(venda, 'itens_override', None)
    if itens_venda is None:
        itens_venda = list(venda.itens.all())

    if not itens_venda:
        raise ValidationError("A venda deve possuir ao menos um item para emissão de NF-e.")

    for idx, item in enumerate(itens_venda, start=1):
        # Extração de atributos fiscais do produto ou SKU
        sku = getattr(item, 'sku', None)
        prod = getattr(item, 'produto', None)

        ncm = (sku.ncm if sku and sku.ncm else (prod.ncm if prod and prod.ncm else ''))
        cest = (sku.cest if sku and sku.cest else (prod.cest if prod and prod.cest else ''))
        unid = (sku.unidade_tributavel if sku and sku.unidade_tributavel else (prod.unidade_tributavel if prod and prod.unidade_tributavel else 'm3'))
        descricao = sku.nome_comercial if sku else (prod.nome if prod else f"Item {idx}")
        prod_id = str(sku.id if sku else (prod.id if prod else idx))

        qtd = quantize(Decimal(str(item.quantidade)), 3)
        v_unit = quantize(Decimal(str(item.valor_unitario or item.preco_unitario_congelado or '0.00')), 2)
        v_item_total = quantize(Decimal(str(item.valor_total or (qtd * v_unit))), 2)

        # Resolução da Regra Tributária por Especificidade Estrita (Task 4)
        regra = resolver_regra(
            tenant=venda.tenant,
            item_ncm=ncm,
            operacao='VENDA',
            data_competencia=venda.data_venda.date() if hasattr(venda, 'data_venda') and venda.data_venda else timezone.localdate(),
            uf_origem=uf_origem,
            uf_destino=uf_destino,
            ambiente=config.ambiente
        )

        tributos_calc = calcular_tributos_item(
            regra=regra,
            quantidade=qtd,
            valor_unitario=v_unit,
            valor_total=v_item_total
        )

        # Rastreabilidade Farmacêutica e Gás Medicinal (Sprint 11B - Tarefa 5)
        is_medicinal = bool((sku and sku.medicinal) or (prod and prod.medicinal))
        exige_rastro = bool((sku and sku.exige_rastro) or (prod and prod.exige_rastro) or is_medicinal)
        reg_anvisa = (sku.registro_anvisa if sku and sku.registro_anvisa else (prod.registro_anvisa if prod and prod.registro_anvisa else '')).strip()

        grupo_med = None
        grupos_rastro = []

        if is_medicinal or exige_rastro:
            if not reg_anvisa:
                raise ValidationError(f"Item medicinal '{descricao}' não possui Registro ANVISA preenchido.")
            grupo_med = {
                'cProdANVISA': reg_anvisa,
                'vPMC': v_unit
            }

            # Identifica lotes vinculados ao item
            lotes_candidatos = []
            if hasattr(item, 'lotes_info') and item.lotes_info:
                lotes_candidatos = item.lotes_info
            elif hasattr(item, 'lote') and item.lote:
                lotes_candidatos = [{'lote': item.lote, 'quantidade': qtd}]
            elif hasattr(item, 'lote_envase') and item.lote_envase:
                lotes_candidatos = [{'lote': item.lote_envase, 'quantidade': qtd}]

            if not lotes_candidatos:
                raise ValidationError(f"Item medicinal '{descricao}' exige identificação de lote de envase (<med> e <rastro>).")

            for info in lotes_candidatos:
                lote_obj = info.get('lote')
                q_lote = quantize(Decimal(str(info.get('quantidade', qtd))), 3)

                if not lote_obj:
                    raise ValidationError(f"Item medicinal '{descricao}' com referência de lote inválida.")

                # Bloqueia a emissão se o lote não tem laudo de CQ liberado/aprovado
                if getattr(lote_obj, 'status_qualidade', None) != 'APROVADO':
                    raise ValidationError(
                        f"Lote '{lote_obj.codigo_lote}' do item medicinal '{descricao}' não possui laudo de CQ liberado/aprovado "
                        f"(Status: {getattr(lote_obj, 'status_qualidade', 'DESCONHECIDO')}). Emissão de NF-e bloqueada."
                    )

                grupos_rastro.append({
                    'nLote': lote_obj.codigo_lote,
                    'qLote': q_lote,
                    'dFab': lote_obj.data_envase.strftime('%Y-%m-%d') if hasattr(lote_obj, 'data_envase') and lote_obj.data_envase else timezone.localdate().strftime('%Y-%m-%d'),
                    'dVal': lote_obj.data_validade.strftime('%Y-%m-%d') if hasattr(lote_obj, 'data_validade') and lote_obj.data_validade else (timezone.localdate() + timezone.timedelta(days=365)).strftime('%Y-%m-%d')
                })

        item_dict = {
            'numero_item': idx,
            'produto_id': prod_id,
            'descricao': descricao,
            'ncm': ncm,
            'cest': cest,
            'cfop': regra.cfop,
            'unidade': unid,
            'quantidade': qtd,
            'valor_unitario': v_unit,
            'valor_total': v_item_total,
            'tributos': tributos_calc,
            'regra_id': regra.id
        }
        if grupo_med:
            item_dict['grupo_med'] = grupo_med
        if grupos_rastro:
            item_dict['grupos_rastro'] = grupos_rastro

        itens_payload.append(item_dict)
        total_produtos += v_item_total

    desconto = quantize(Decimal(str(venda.valor_desconto or '0.00')), 2)
    valor_total_nf = quantize(max(Decimal('0.00'), total_produtos - desconto), 2)

    # Detalhamento de Cobrança / Parcelamento (Task 7)
    cobranca_duplicatas = []
    if valor_total_nf > Decimal('0.00'):
        cobranca_duplicatas.append({
            'numero': f"{numero}/01",
            'vencimento': str(venda.prazo_entrega or timezone.localdate()),
            'valor': valor_total_nf
        })

    payload = {
        'identificacao': {
            'numero': numero,
            'serie': serie,
            'natureza_operacao': 'VENDA DE MERCADORIA',
            'modelo': '55',
            'tipo_operacao': 1,  # 1 = Saída
            'data_emissao': timezone.now().isoformat(),
            'ambiente': config.ambiente,
        },
        'emitente': {
            'cnpj': limpar_formatacao(filial.cnpj if hasattr(filial, 'cnpj') and filial.cnpj else venda.tenant.cnpj),
            'razao_social': filial.nome,
            'nome_fantasia': filial.nome,
            'inscricao_estadual': config.filial.inscricao_estadual if hasattr(config.filial, 'inscricao_estadual') else '',
            'crt': config.crt,
            'endereco': {
                'logradouro': getattr(filial, 'endereco', 'Rua Principal'),
                'numero': getattr(filial, 'numero', 'S/N'),
                'bairro': getattr(filial, 'bairro', 'Centro'),
                'municipio': getattr(filial, 'cidade', 'São Paulo'),
                'uf': uf_origem,
                'cep': limpar_formatacao(getattr(filial, 'cep', '01001000')),
            }
        },
        'destinatario': {
            'documento': limpar_formatacao(cliente.cnpj),
            'razao_social': cliente.nome,
            'indicador_ie': getattr(cliente, 'indicador_ie', '9'),
            'inscricao_estadual': getattr(cliente, 'ie', ''),
            'endereco': {
                'logradouro': cliente.endereco,
                'numero': getattr(cliente, 'numero', 'S/N'),
                'bairro': getattr(cliente, 'bairro', 'Bairro'),
                'municipio': cliente.cidade,
                'codigo_ibge': getattr(cliente, 'municipio_ibge', ''),
                'uf': uf_destino,
                'cep': limpar_formatacao(getattr(cliente, 'cep', '')),
            }
        },
        'itens': itens_payload,
        'totais': {
            'valor_produtos': total_produtos,
            'valor_desconto': desconto,
            'valor_total_nfe': valor_total_nf,
            'valor_tributos_reais': sum(t['valor'] for it in itens_payload for t in it['tributos']),
        },
        'cobranca': {
            'duplicatas': cobranca_duplicatas
        },
        'origem': {
            'tipo': 'VENDA',
            'id': str(venda.id),
        }
    }

    return payload


def validar_pre_emissao(payload: dict):
    """
    Pré-validação estrita do payload antes da transmissão para SEFAZ (Task 7):
    - Campos obrigatórios
    - Soma dos itens coerente com o total da NF-e
    - NCM válido de 8 dígitos
    - Validação de CPF/CNPJ do destinatário
    - Validação de Inscrição Estadual por UF
    - Coerência de CFOP com as UFs de origem e destino
    """
    ident = payload.get('identificacao', {})
    emit = payload.get('emitente', {})
    dest = payload.get('destinatario', {})
    itens = payload.get('itens', [])
    totais = payload.get('totais', {})

    if not itens:
        raise ValidationError("NF-e sem itens. Impossível emitir.")

    # Validação do documento do destinatário
    doc_dest = dest.get('documento')
    if not doc_dest:
        raise ValidationError("Destinatário sem CNPJ ou CPF informado.")
    validar_cpf_ou_cnpj(doc_dest)

    # Validação da IE do destinatário
    uf_dest = dest.get('endereco', {}).get('uf')
    ie_dest = dest.get('inscricao_estadual')
    ind_ie = dest.get('indicador_ie', '9')
    if ind_ie == '1' and not ie_dest:
        raise ValidationError("Contribuinte de ICMS (indIEDest=1) exige preenchimento da Inscrição Estadual.")
    if ie_dest:
        validar_inscricao_estadual(ie_dest, uf_dest)

    # Validação de coerência da soma dos itens
    soma_itens = sum(it['valor_total'] for it in itens)
    v_desc = totais.get('valor_desconto', Decimal('0.00'))
    total_esperado = quantize(soma_itens - v_desc, 2)
    if quantize(totais.get('valor_total_nfe'), 2) != total_esperado:
        raise ValidationError(
            f"Divergência matemática na soma dos itens: "
            f"Itens ({soma_itens}) - Desconto ({v_desc}) != Total ({totais.get('valor_total_nfe')})"
        )

    # Validação dos itens, NCM e coerência do CFOP com UFs
    uf_origem = emit.get('endereco', {}).get('uf')
    for it in itens:
        validar_ncm(it.get('ncm'))
        if it.get('cest'):
            validar_cest(it.get('cest'))
        validar_cfop(it.get('cfop'), uf_origem, uf_dest)

        # Validação regulatória de grupos <med> e <rastro>
        if it.get('grupo_med'):
            med = it['grupo_med']
            if not med.get('cProdANVISA'):
                raise ValidationError(f"Item #{it.get('numero_item')} com registro ANVISA inválido ou em branco.")
        if it.get('grupos_rastro'):
            for rastro in it['grupos_rastro']:
                if not rastro.get('nLote'):
                    raise ValidationError(f"Item #{it.get('numero_item')} com grupo de rastreabilidade sem número de lote.")


def emitir_nfe_venda(
    venda,
    filial=None,
    emissor_port=None,
    idempotency_key: str = None,
    assincrono: bool = False
) -> DocumentoFiscal:
    """
    Orquestra a emissão da NF-e de venda de ponta a ponta (Task 7):
    - Idempotência: impede duplo clique ou emissão duplicada com o mesmo idempotency_key.
    - Reserva de numeração atômica com select_for_update (Task 6).
    - Montagem pura e pré-validação do payload.
    - Gravação de DocumentoFiscal, DocumentoFiscalItem e ItemDocumentoTributo.
    - Envio ao emissor fiscal (gateway ou FakeEmissor).
    - Mapeamento amigável de rejeição.
    - Em caso de autorização, sincronização com o financeiro publicando 'venda_faturada' com os tributos reais (Task 9).
    """
    assert_tenant_writable(venda.tenant)

    # 1. Checagem de Idempotência estrita
    if idempotency_key:
        doc_existente = DocumentoFiscal.objects.filter(
            tenant=venda.tenant,
            idempotency_key=idempotency_key
        ).first()
        if doc_existente:
            logger.info(f"[Fiscal] Retornando NF-e existente por idempotency_key '{idempotency_key}': Doc #{doc_existente.numero}")
            return doc_existente

    # Checagem de documento ativo para a mesma venda
    doc_venda_ativo = DocumentoFiscal.objects.filter(
        tenant=venda.tenant,
        origem_tipo='VENDA',
        origem_id=str(venda.id),
        status__in=['AUTORIZADO', 'ENVIADO', 'VALIDANDO']
    ).first()
    if doc_venda_ativo:
        logger.info(f"[Fiscal] Venda #{venda.id} já possui documento fiscal em processamento ou autorizado: Doc #{doc_venda_ativo.numero}")
        return doc_venda_ativo

    filial_alvo = filial or venda.filial
    if not filial_alvo:
        raise ValidationError(f"Venda #{venda.id} não possui filial associada para emissão fiscal.")

    config = ConfiguracaoFiscalFilial.objects.filter(tenant=venda.tenant, filial=filial_alvo).first()
    if not config:
        raise ValidationError(f"Filial '{filial_alvo.nome}' não possui Configuração Fiscal cadastrada.")

    emissor = emissor_port or obter_emissor_fiscal(config)

    # 2. Transação atômica de reserva de número e gravação preliminar
    with transaction.atomic():
        numero, serie = reservar_proximo_numero(venda.tenant, filial_alvo.id, modelo='NFE_55')

        payload = montar_nfe(venda, config, numero, serie)
        validar_pre_emissao(payload)

        doc = DocumentoFiscal.objects.create(
            tenant=venda.tenant,
            filial=filial_alvo,
            modelo='NFE_55',
            tipo_operacao='SAIDA',
            status='VALIDANDO',
            ambiente=config.ambiente,
            numero=numero,
            serie=serie,
            valor_total=payload['totais']['valor_total_nfe'],
            origem_tipo='VENDA',
            origem_id=str(venda.id),
            idempotency_key=idempotency_key
        )

        for it_data in payload['itens']:
            item_doc = DocumentoFiscalItem.objects.create(
                tenant=venda.tenant,
                documento=doc,
                numero_item=it_data['numero_item'],
                produto_id=it_data['produto_id'],
                descricao=it_data['descricao'],
                ncm=it_data['ncm'],
                cest=it_data.get('cest', ''),
                cfop=it_data['cfop'],
                unidade=it_data['unidade'],
                quantidade=it_data['quantidade'],
                valor_unitario=it_data['valor_unitario'],
                valor_total=it_data['valor_total']
            )
            for trib_data in it_data['tributos']:
                ItemDocumentoTributo.objects.create(
                    tenant=venda.tenant,
                    item=item_doc,
                    tributo=trib_data['tributo'],
                    cst=trib_data['cst'],
                    base=trib_data['base'],
                    aliquota=trib_data['aliquota'],
                    valor=trib_data['valor']
                )

    # 3. Transmissão para SEFAZ via EmissorFiscalPort
    doc.status = 'ENVIADO'
    doc.tentativas += 1
    doc.save(update_fields=['status', 'tentativas', 'atualizado_em'])

    resposta = emissor.emitir_nfe(payload)

    # 4. Processamento do Retorno da SEFAZ
    if resposta.sucesso and resposta.status_sefaz == '100':  # 100 = Autorizado o uso da NF-e
        doc.status = 'AUTORIZADO'
        doc.chave_acesso = resposta.chave_acesso
        doc.protocolo = resposta.protocolo
        doc.xml_autorizado = resposta.xml
        doc.danfe_url = resposta.danfe_url or ''
        doc.data_autorizacao = timezone.now()
        doc.motivo_rejeicao = ''
        doc.acao_sugerida = ''
        doc.save(update_fields=[
            'status', 'chave_acesso', 'protocolo', 'xml_autorizado',
            'danfe_url', 'data_autorizacao', 'motivo_rejeicao', 'acao_sugerida', 'atualizado_em'
        ])

        # Atualiza a referência da venda
        venda.documento_fiscal_ref = f"NF-e {numero}/{serie} - Chave {resposta.chave_acesso}"
        venda.save(update_fields=['documento_fiscal_ref', 'data_atualizacao'])

        # Task 9: Regra de sequência com o financeiro
        # Com modulo_fiscal_ativo, a venda só publica venda_faturada agora que está AUTORIZADA,
        # enviando os tributos reais calculados para dedução exata no financeiro.
        if is_modulo_ativo(venda.tenant, 'fiscal'):
            custo_total_cpv = Decimal('0.00')
            try:
                from produtos.services.estoque_produto import baixar_estoque_venda_faturada
                custo_total_cpv = baixar_estoque_venda_faturada(venda)
            except Exception:
                pass

            tributos_reais = sum(
                t.valor for it in doc.itens.all() for t in it.tributos.all()
            )

            publicar('venda_faturada', {
                'tenant': venda.tenant,
                'venda_id': str(venda.id),
                'cliente_id': str(venda.cliente_id) if venda.cliente else None,
                'valor_total': venda.valor_total,
                'custo_total': custo_total_cpv,
                'valor_deducoes': tributos_reais,
            })

    elif resposta.status_sefaz == 'REJEITADO' or not resposta.sucesso:
        doc.status = 'REJEITADO'
        doc.motivo_rejeicao = resposta.mensagem_erro
        doc.acao_sugerida = resposta.acao_sugerida or 'Corrija os dados cadastrais informados e tente a reemissão.'
        doc.save(update_fields=['status', 'motivo_rejeicao', 'acao_sugerida', 'atualizado_em'])

        # Task 6: Documento rejeitado que consome número gera tarefa de inutilização
        registrar_lacuna_inutilizacao(
            tenant=venda.tenant,
            filial_id=filial_alvo.id,
            modelo='NFE_55',
            serie=serie,
            numero_inicial=numero,
            numero_final=numero,
            motivo=f"Rejeição SEFAZ ({resposta.mensagem_erro[:120]}) consumiu a numeração sequencial."
        )

    return doc
