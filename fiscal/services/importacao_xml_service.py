import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import date
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from fiscal.models import DocumentoFiscalEntrada


def extrair_texto_tag(elemento, tag_nome: str, default: str = '') -> str:
    """Extrai o texto de uma tag XML ignorando namespaces."""
    if elemento is None:
        return default
    # Busca por tag ignorando namespace
    for child in elemento.iter():
        tag_sem_ns = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag_sem_ns == tag_nome:
            return child.text or default
    return default


@transaction.atomic
def importar_xml_nfe_compra(
    tenant,
    filial,
    xml_content: str,
    criar_titulo_pagar: bool = True
) -> tuple[DocumentoFiscalEntrada, bool]:
    """
    Importação idempotente de NF-e de compra de insumos/gás/cilindros (Sprint 11B - Tarefa 9).
    Regras estritas:
    - Idempotência por chave de acesso: se a mesma chave de acesso for enviada duas vezes,
      o sistema NÃO recria o documento nem duplica entradas de estoque ou títulos a pagar.
    - Extração de créditos fiscais (ICMS, PIS, COFINS, IPI) para custo e apuração gerencial.
    - Pré-preenchimento ou integração com Título PAGAR no módulo financeiro (9B).
    Retorna tupla: (documento, criado_boolean).
    """
    assert_tenant_writable(tenant)

    xml_limpo = xml_content.strip()
    if not xml_limpo:
        raise ValidationError("O conteúdo XML da NF-e está vazio.")

    try:
        root = ET.fromstring(xml_limpo)
    except ET.ParseError as e:
        raise ValidationError(f"Erro ao analisar arquivo XML: Formato XML inválido ({e}).")

    # Localiza o nó infNFe
    inf_nfe = None
    for elem in root.iter():
        tag = elem.tag.split('}')[-1]
        if tag == 'infNFe':
            inf_nfe = elem
            break

    if inf_nfe is None:
        raise ValidationError("Estrutura da NF-e inválida: elemento <infNFe> não localizado.")

    # Chave de Acesso (44 dígitos)
    chave_raw = inf_nfe.attrib.get('Id', '')
    chave = re.sub(r'\D', '', chave_raw)
    if not chave or len(chave) != 44:
        # Tenta buscar tag chNFe
        chave_alt = extrair_texto_tag(root, 'chNFe')
        chave = re.sub(r'\D', '', chave_alt)
        if not chave or len(chave) != 44:
            raise ValidationError("Chave de acesso da NF-e de compra inválida ou não encontrada no XML.")

    # ==============================================================================
    # VERIFICAÇÃO DE IDEMPOTÊNCIA: Se já foi importado no tenant, retorna existente
    # ==============================================================================
    existente = DocumentoFiscalEntrada.objects.filter(
        tenant=tenant,
        chave_acesso=chave
    ).first()
    if existente:
        return existente, False

    # Extrai Identificação (<ide>)
    ide = None
    for elem in inf_nfe.iter():
        if elem.tag.split('}')[-1] == 'ide':
            ide = elem
            break

    numero = int(extrair_texto_tag(ide, 'nNF', '0'))
    serie = int(extrair_texto_tag(ide, 'serie', '1'))
    data_emi_str = extrair_texto_tag(ide, 'dhEmi') or extrair_texto_tag(ide, 'dEmi')
    try:
        data_emissao = timezone.datetime.fromisoformat(data_emi_str[:10]).date() if data_emi_str else timezone.localdate()
    except Exception:
        data_emissao = timezone.localdate()

    # Extrai Emitente / Fornecedor (<emit>)
    emit = None
    for elem in inf_nfe.iter():
        if elem.tag.split('}')[-1] == 'emit':
            emit = elem
            break

    fornecedor_nome = extrair_texto_tag(emit, 'xNome', 'Fornecedor Desconhecido')
    fornecedor_cnpj = extrair_texto_tag(emit, 'CNPJ') or extrair_texto_tag(emit, 'CPF', '')

    # Extrai Totais e Créditos (<total><ICMSTot>)
    v_nf = Decimal(extrair_texto_tag(inf_nfe, 'vNF', '0.00'))
    v_prod = Decimal(extrair_texto_tag(inf_nfe, 'vProd', '0.00'))
    v_frete = Decimal(extrair_texto_tag(inf_nfe, 'vFrete', '0.00'))
    c_icms = Decimal(extrair_texto_tag(inf_nfe, 'vICMS', '0.00'))
    c_pis = Decimal(extrair_texto_tag(inf_nfe, 'vPIS', '0.00'))
    c_cofins = Decimal(extrair_texto_tag(inf_nfe, 'vCOFINS', '0.00'))
    c_ipi = Decimal(extrair_texto_tag(inf_nfe, 'vIPI', '0.00'))

    # Extrai Itens
    itens = []
    tipo_entrada = 'INSUMO_GERAL'
    for elem in inf_nfe.iter():
        if elem.tag.split('}')[-1] == 'det':
            prod_elem = None
            for p in elem.iter():
                if p.tag.split('}')[-1] == 'prod':
                    prod_elem = p
                    break
            if prod_elem:
                ncm = extrair_texto_tag(prod_elem, 'NCM', '')
                item_info = {
                    'item': int(elem.attrib.get('nItem', len(itens) + 1)),
                    'codigo': extrair_texto_tag(prod_elem, 'cProd', ''),
                    'descricao': extrair_texto_tag(prod_elem, 'xProd', ''),
                    'ncm': ncm,
                    'cfop': extrair_texto_tag(prod_elem, 'CFOP', ''),
                    'quantidade': str(quantize(Decimal(extrair_texto_tag(prod_elem, 'qCom', '1')), 3)),
                    'valor_unitario': str(quantize(Decimal(extrair_texto_tag(prod_elem, 'vUnCom', '0.00')), 2)),
                    'valor_total': str(quantize(Decimal(extrair_texto_tag(prod_elem, 'vProd', '0.00')), 2)),
                }
                itens.append(item_info)
                if ncm.startswith('2804'):  # Gases Elementares / Oxigênio / Nitrogênio / Argônio
                    tipo_entrada = 'GAS_GRANEL'
                elif ncm.startswith('7311') and tipo_entrada != 'GAS_GRANEL':  # Cilindros de aço
                    tipo_entrada = 'CILINDROS_CASCOS'

    doc_entrada = DocumentoFiscalEntrada.objects.create(
        tenant=tenant,
        filial=filial,
        chave_acesso=chave,
        numero=numero,
        serie=serie,
        data_emissao=data_emissao,
        fornecedor_nome=fornecedor_nome,
        fornecedor_cnpj=fornecedor_cnpj,
        valor_total=quantize(v_nf),
        valor_produtos=quantize(v_prod),
        valor_frete=quantize(v_frete),
        credito_icms=quantize(c_icms),
        credito_pis=quantize(c_pis),
        credito_cofins=quantize(c_cofins),
        credito_ipi=quantize(c_ipi),
        xml_conteudo=xml_limpo,
        itens_json=itens,
        tipo_entrada=tipo_entrada,
        status='IMPORTADO'
    )

    # Integração Financeira: Criação automática de Título a Pagar
    if criar_titulo_pagar and getattr(tenant, 'modulo_financeiro_ativo', False) and v_nf > Decimal('0.00'):
        try:
            from financeiro.models import TituloFinanceiro, ParcelaFinanceira, PlanoContas
            conta_fornecedores = PlanoContas.objects.filter(
                tenant=tenant,
                codigo_estrutural__startswith='2.1.1',
                tipo='ANALITICA',
                aceita_lancamento=True
            ).first()
            if not conta_fornecedores:
                conta_fornecedores = PlanoContas.objects.filter(tenant=tenant, tipo='ANALITICA', aceita_lancamento=True).first()

            v_tot = quantize(v_nf)
            titulo = TituloFinanceiro.objects.create(
                tenant=tenant,
                filial=filial,
                tipo='PAGAR',
                beneficiario_texto=fornecedor_nome or f"Fornecedor CNPJ {fornecedor_cnpj}",
                conta_gerencial=conta_fornecedores,
                origem_tipo='COMPRA_GRANEL',
                origem_id=str(doc_entrada.id),
                valor_bruto=v_tot,
                valor_liquido_esperado=v_tot,
                data_emissao=data_emissao,
                data_competencia=data_emissao,
                status='ABERTO',
                historico=f"Importação NF-e Compra #{numero}/{serie} ({fornecedor_nome})"
            )
            ParcelaFinanceira.objects.create(
                tenant=tenant,
                titulo=titulo,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=data_emissao + timezone.timedelta(days=30),
                valor_nominal=v_tot,
                saldo_em_aberto=v_tot,
                status='PENDENTE'
            )
            doc_entrada.titulo_pagar = titulo
            doc_entrada.status = 'INTEGRADO'
            doc_entrada.save(update_fields=['titulo_pagar', 'status', 'atualizado_em'])
        except Exception:
            pass

    return doc_entrada, True
