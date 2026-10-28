import hmac
import hashlib
import json
import logging
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from core.models import Tenant
from faturamento.models import ConfiguracaoFiscalTenant, NotaFiscal, FaturaCobranca
from vendas.models import Venda
from clientes.models import FechamentoFaturaEstadia

logger = logging.getLogger(__name__)

def validar_assinatura_webhook(body_bytes: bytes, signature_header: str, secret_key: str) -> bool:
    """
    Valida a assinatura criptográfica HMAC-SHA256 do webhook (Gateway ou SEFAZ).
    Garante integridade e autenticidade (Fail-Closed).
    """
    if not signature_header or not secret_key:
        return False

    # Trata cabeçalhos com prefixo 'sha256='
    provided_sig = signature_header.strip()
    if provided_sig.startswith('sha256='):
        provided_sig = provided_sig[7:].strip()

    expected_sig = hmac.new(
        secret_key.encode('utf-8'),
        body_bytes,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_sig, provided_sig)


def montar_payload_focus_nfe(tenant: Tenant, config_fiscal: ConfiguracaoFiscalTenant, entidade, tipo_entidade: str) -> dict:
    """
    Monta o payload JSON padronizado para a API Focus NFe (v2).
    """
    if tipo_entidade.upper() == 'VENDA':
        venda: Venda = entidade
        cliente = venda.cliente
        itens_payload = []
        for idx, item in enumerate(venda.itens.all(), start=1):
            produto = item.sku or item.produto
            nome_prod = getattr(produto, 'nome_comercial', getattr(produto, 'nome', 'Produto'))
            preco_unitario = float(item.valor_unitario or item.preco_unitario_congelado or 0)
            qtd = float(item.quantidade)
            itens_payload.append({
                "numero_item": idx,
                "codigo_produto": f"PROD-{produto.id if produto else idx}",
                "descricao": nome_prod,
                "codigo_ncm": getattr(produto, 'ncm', '28042100') or '28042100',
                "codigo_cfop": "5102",
                "unidade_comercial": "UN",
                "quantidade_comercial": qtd,
                "valor_unitario_comercial": preco_unitario,
                "valor_bruto": float(item.valor_total),
                "unidade_tributavel": "UN",
                "quantidade_tributavel": qtd,
                "valor_unitario_tributavel": preco_unitario,
                "origem": 0,
                "icms_situacao_tributaria": "102"
            })

        payload = {
            "natureza_operacao": "Venda de Mercadorias / Gases Industriais e Medicinais",
            "data_emissao": timezone.now().strftime('%Y-%m-%dT%H:%M:%S-03:00'),
            "tipo_documento": 1, # 1=Saída
            "finalidade_emissao": 1, # 1=Normal
            "cnpj_emitente": config_fiscal.cnpj_emissor.replace('.', '').replace('/', '').replace('-', ''),
            "nome_destinatario": cliente.nome,
            "cnpj_destinatario": (cliente.cnpj or '').replace('.', '').replace('/', '').replace('-', ''),
            "inscricao_estadual_destinatario": getattr(cliente, 'inscricao_estadual', 'ISENTO') or "ISENTO",
            "logradouro_destinatario": cliente.endereco or "Rua Comercial",
            "numero_destinatario": getattr(cliente, 'numero', 'S/N') or "S/N",
            "bairro_destinatario": getattr(cliente, 'bairro', 'Centro') or 'Centro',
            "municipio_destinatario": getattr(cliente, 'cidade', 'São Paulo') or 'São Paulo',
            "uf_destinatario": getattr(cliente, 'estado', 'SP') or 'SP',
            "cep_destinatario": (getattr(cliente, 'cep', '01001-000') or '01001-000').replace('-', ''),
            "valor_produtos": float(venda.valor_total),
            "valor_total": float(venda.valor_total),
            "modalidade_frete": 0,
            "items": itens_payload,
            "informacoes_adicionais_contribuinte": f"Venda ID #{venda.id} - Sistema Baros SaaS."
        }
        return payload

    elif tipo_entidade.upper() == 'ESTADIA':
        fatura_estadia: FechamentoFaturaEstadia = entidade
        cliente = fatura_estadia.cliente
        payload = {
            "natureza_operacao": "Faturamento de Locação / Estadia e Demurrage de Cilindros",
            "data_emissao": timezone.now().strftime('%Y-%m-%dT%H:%M:%S-03:00'),
            "tipo_documento": 1,
            "finalidade_emissao": 1,
            "cnpj_emitente": config_fiscal.cnpj_emissor.replace('.', '').replace('/', '').replace('-', ''),
            "nome_destinatario": cliente.nome,
            "cnpj_destinatario": (cliente.cnpj or '').replace('.', '').replace('/', '').replace('-', ''),
            "valor_total": float(fatura_estadia.valor_liquido_total),
            "items": [
                {
                    "numero_item": 1,
                    "codigo_produto": "SERV-ESTADIA-DEMURRAGE",
                    "descricao": f"Estadia de Cilindros - Competência {fatura_estadia.competencia_ano_mes}",
                    "codigo_ncm": "00000000",
                    "codigo_cfop": "5949",
                    "unidade_comercial": "UN",
                    "quantidade_comercial": 1.0,
                    "valor_unitario_comercial": float(fatura_estadia.valor_liquido_total),
                    "valor_bruto": float(fatura_estadia.valor_liquido_total),
                    "icms_situacao_tributaria": "400"
                }
            ],
            "informacoes_adicionais_contribuinte": f"Fatura de Estadia ID #{fatura_estadia.id} - Competência {fatura_estadia.competencia_ano_mes}."
        }
        return payload

    raise ValueError(f"Tipo de entidade '{tipo_entidade}' não suportado para emissão de NF-e.")
