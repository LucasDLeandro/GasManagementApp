"""
Seletor de Documentos Fiscais (NF-e, DANFE, XML) do Portal B2B (Sprint 12B).

Regras de negócio:
- Exige módulo 'fiscal' ativo no plano do Tenant; se inativo, lança ModuloInativoError.
- Retorna NF-e/DANFE autorizadas vinculadas a vendas ou comodatos do cliente.
"""
from typing import Any, Dict, List
from core.guards import assert_modulo
from fiscal.models import DocumentoFiscal
from vendas.models import Venda


def get_documentos_fiscais_cliente(tenant, cliente) -> List[Dict[str, Any]]:
    """
    Lista todos os documentos fiscais autorizados do cliente.
    """
    assert_modulo(tenant, 'fiscal')

    vendas_ids = list(Venda.unscoped.filter(
        tenant=tenant,
        cliente=cliente
    ).values_list('id', flat=True))

    docs_qs = DocumentoFiscal.unscoped.filter(
        tenant=tenant,
        origem_tipo='VENDA',
        origem_id__in=[str(vid) for vid in vendas_ids],
        status='AUTORIZADO'
    ).select_related('filial').order_by('-data_autorizacao', '-numero')

    resultado = []
    for doc in docs_qs:
        resultado.append({
            'id': doc.id,
            'numero': doc.numero,
            'serie': doc.serie,
            'modelo': doc.modelo,
            'chave_acesso': doc.chave_acesso or '',
            'data_autorizacao': doc.data_autorizacao.isoformat() if doc.data_autorizacao else None,
            'valor_total': str(doc.valor_total),
            'tem_xml': bool(doc.xml_autorizado),
            'tem_danfe': bool(doc.danfe_url or doc.xml_autorizado),
            'venda_id': doc.origem_id,
        })
    return resultado
