"""
Serviço de Downloads Seguros, Efêmeros e de Uso Único (Sprint 12B).

Regras de negócio:
- URLs assinadas criptograficamente com TimestampSigner e validade de 5 minutos (download_validade_segundos).
- Tokens de uso único (single-use) controlados por UUID efêmero (jti) e constraint unique(tenant, jti)
  em DownloadDocumentoB2B.
- Prevenção de vazamento / IDOR: laudo e certificado só podem ser baixados se o cilindro
  tiver histórico comprovado de entrega para o cliente (MovimentacaoCilindro ou cliente_posse_atual).
- Auditoria append-only: registra evento DOWNLOAD ou DOWNLOAD_NEGADO com SHA-256 e tamanho.
"""
import hashlib
import uuid
from typing import Any, Dict, Optional, Tuple

from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from core.guards import assert_modulo
from produtos.models import Cilindro, MovimentacaoCilindro
from fiscal.models import DocumentoFiscal
from financeiro.models import ParcelaFinanceira
from portal_b2b.conf import download_validade_segundos, base_url
from portal_b2b.models import DownloadDocumentoB2B, LogAcessoB2B
from portal_b2b.services import gerar_laudo_quimico_pdf

SIGNER_SALT = 'b2b-ephemeral-download-v1'


def gerar_link_download(
    tenant,
    cliente,
    tipo_documento: str,
    recurso_tipo: str,
    recurso_id: Any,
    usuario_b2b=None,
    request=None
) -> str:
    """
    Gera uma URL assinada e efêmera de uso único com validade de 5 minutos.
    """
    jti = str(uuid.uuid4())
    signer = TimestampSigner(salt=SIGNER_SALT)
    payload = {
        'jti': jti,
        'tenant_id': str(tenant.id) if hasattr(tenant, 'id') else str(tenant),
        'cliente_id': cliente.id,
        'usuario_b2b_id': usuario_b2b.id if usuario_b2b else None,
        'tipo_documento': tipo_documento,
        'recurso_tipo': recurso_tipo,
        'recurso_id': str(recurso_id),
    }
    token = signer.sign_object(payload)

    # Registra no log de acesso a geração do link
    LogAcessoB2B.unscoped.create(
        tenant=tenant,
        cliente=cliente,
        usuario_b2b=usuario_b2b,
        usuario_nome=usuario_b2b.user.username if (usuario_b2b and usuario_b2b.user) else '',
        evento='LINK_DOWNLOAD',
        recurso_tipo=recurso_tipo,
        recurso_id=str(recurso_id),
        detalhes={'tipo_documento': tipo_documento, 'jti': jti}
    )

    return f"/portal-b2b/download/{token}/"


def processar_download_documento(
    token: str,
    request=None
) -> HttpResponse:
    """
    Valida a assinatura, garante uso único (single-use via jti) e entrega o conteúdo
    apenas se pertencer comprovadamente ao cliente titular.
    """
    signer = TimestampSigner(salt=SIGNER_SALT)
    ttl = download_validade_segundos()

    try:
        payload: Dict[str, Any] = signer.unsign_object(token, max_age=ttl)
    except SignatureExpired:
        raise PermissionDenied("O link de download expirou (validade máxima de 5 minutos).")
    except BadSignature:
        raise PermissionDenied("Link de download inválido ou violado.")

    tenant_id = payload['tenant_id']
    cliente_id = payload['cliente_id']
    usuario_b2b_id = payload.get('usuario_b2b_id')
    tipo_doc = payload['tipo_documento']
    recurso_tipo = payload['recurso_tipo']
    recurso_id = payload['recurso_id']
    jti_uuid = uuid.UUID(payload['jti'])

    ip = request.META.get('REMOTE_ADDR') if request else None
    ua = request.META.get('HTTP_USER_AGENT', '')[:255] if request else ''

    # 1. Recupera o conteúdo antes de persistir a auditoria
    conteudo_bytes, content_type, filename = _obter_conteudo_documento(
        tenant_id=tenant_id,
        cliente_id=cliente_id,
        tipo_documento=tipo_doc,
        recurso_tipo=recurso_tipo,
        recurso_id=recurso_id
    )

    hash_sha256 = hashlib.sha256(conteudo_bytes).hexdigest()
    tamanho = len(conteudo_bytes)

    # 2. Persistência atômica append-only em DownloadDocumentoB2B (impede reutilização)
    try:
        with transaction.atomic():
            DownloadDocumentoB2B.unscoped.create(
                tenant_id=tenant_id,
                cliente_id=cliente_id,
                usuario_b2b_id=usuario_b2b_id,
                tipo_documento=tipo_doc,
                recurso_tipo=recurso_tipo,
                recurso_id=str(recurso_id),
                jti=jti_uuid,
                ip=ip,
                user_agent=ua,
                hash_conteudo=hash_sha256,
                tamanho_bytes=tamanho,
            )
            LogAcessoB2B.unscoped.create(
                tenant_id=tenant_id,
                cliente_id=cliente_id,
                usuario_b2b_id=usuario_b2b_id,
                evento='DOWNLOAD',
                recurso_tipo=recurso_tipo,
                recurso_id=str(recurso_id),
                ip=ip,
                user_agent=ua,
                detalhes={'tipo_documento': tipo_doc, 'tamanho': tamanho, 'sha256': hash_sha256}
            )
    except IntegrityError:
        # jti duplicado para este tenant: link já utilizado!
        LogAcessoB2B.unscoped.create(
            tenant_id=tenant_id,
            cliente_id=cliente_id,
            usuario_b2b_id=usuario_b2b_id,
            evento='DOWNLOAD_NEGADO',
            recurso_tipo=recurso_tipo,
            recurso_id=str(recurso_id),
            ip=ip,
            user_agent=ua,
            detalhes={'motivo': 'Link de uso único já utilizado anteriormente', 'jti': str(jti_uuid)}
        )
        raise PermissionDenied("Este link de download é de uso único e já foi consumido.")

    # 3. Monta a resposta com cabeçalhos de segurança estritos
    response = HttpResponse(conteudo_bytes, content_type=content_type)
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    response['Content-Length'] = str(tamanho)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    return response


def _obter_conteudo_documento(
    tenant_id: int,
    cliente_id: int,
    tipo_documento: str,
    recurso_tipo: str,
    recurso_id: str
) -> Tuple[bytes, str, str]:
    """
    Recupera e valida a titularidade do documento solicitado.
    Garante que outro cliente jamais consiga acessar o arquivo (404 / IDOR protection).
    """
    if tipo_documento in ('LAUDO_LOTE', 'CERTIFICADO_ANALISE', 'LAUDO_FORNECEDOR'):
        cilindro = Cilindro.unscoped.filter(tenant_id=tenant_id, id=recurso_id).select_related('modelo', 'gas_dedicado', 'envase_atual__lote').first()
        if not cilindro:
            raise Http404("Cilindro não encontrado.")

        # Valida que o cilindro pertenceu ou pertence a este cliente
        teve_entrega = MovimentacaoCilindro.unscoped.filter(
            tenant_id=tenant_id,
            cilindro=cilindro,
            cliente_id=cliente_id
        ).exists()

        if not teve_entrega and cilindro.cliente_posse_atual_id != cliente_id:
            raise Http404("O cliente não possui histórico de recebimento deste cilindro.")

        # Obtém lote e laudo
        lote = None
        if cilindro.envase_atual and cilindro.envase_atual.lote:
            lote = cilindro.envase_atual.lote
        else:
            mov = MovimentacaoCilindro.unscoped.filter(
                tenant_id=tenant_id, cilindro=cilindro, cliente_id=cliente_id
            ).order_by('-registrado_em', '-id').first()
            if mov and mov.envase_cilindro and mov.envase_cilindro.lote:
                lote = mov.envase_cilindro.lote

        if not lote:
            raise Http404("Nenhum laudo homologado disponível para a carga deste cilindro.")

        pdf_buf = gerar_laudo_quimico_pdf(cilindro, lote, None, None)
        return pdf_buf.getvalue(), 'application/pdf', f"laudo_cilindro_{cilindro.numero_serie_ogiva}.pdf"

    elif tipo_documento in ('DANFE', 'XML_NFE'):
        assert_modulo(tenant_id, 'fiscal')
        doc = DocumentoFiscal.unscoped.filter(tenant_id=tenant_id, id=recurso_id).first()
        if not doc:
            raise Http404("Documento fiscal não encontrado.")

        # Valida titularidade via venda do cliente
        if doc.origem_tipo == 'VENDA':
            from vendas.models import Venda
            venda_do_cliente = Venda.unscoped.filter(
                tenant_id=tenant_id, id=doc.origem_id, cliente_id=cliente_id
            ).exists()
            if not venda_do_cliente:
                raise Http404("Documento fiscal não pertence a compras deste cliente.")

        if tipo_documento == 'XML_NFE':
            if not doc.xml_autorizado:
                raise Http404("XML autorizado não disponível para este documento.")
            return doc.xml_autorizado.encode('utf-8'), 'application/xml', f"nfe_{doc.chave_acesso or doc.numero}.xml"
        else:
            # DANFE
            if doc.xml_autorizado:
                conteudo = f"DANFE Simplificado da NF-e nº {doc.numero} Série {doc.serie}\nChave: {doc.chave_acesso}\nValor: R$ {doc.valor_total}".encode('utf-8')
                return conteudo, 'text/plain', f"danfe_{doc.numero}.txt"
            raise Http404("DANFE não disponível para este documento.")

    elif tipo_documento in ('BOLETO_2VIA', 'PIX_2VIA'):
        assert_modulo(tenant_id, 'financeiro')
        parcela = ParcelaFinanceira.unscoped.filter(
            tenant_id=tenant_id,
            id=recurso_id,
            titulo__cliente_id=cliente_id
        ).select_related('titulo').first()
        if not parcela:
            raise Http404("Parcela financeira não encontrada.")

        if tipo_documento == 'PIX_2VIA':
            txt = f"PIX Copia e Cola\nParcela: {parcela.numero_parcela}/{parcela.total_parcelas}\nValor: R$ {parcela.saldo_em_aberto}\nPayload: {parcela.payload_pix}"
            return txt.encode('utf-8'), 'text/plain', f"pix_parcela_{parcela.id}.txt"
        else:
            txt = f"2ª Via de Boleto\nLinha Digitável: {parcela.linha_digitavel}\nCódigo de Barras: {parcela.codigo_barras}\nValor: R$ {parcela.saldo_em_aberto}"
            return txt.encode('utf-8'), 'text/plain', f"boleto_parcela_{parcela.id}.txt"

    raise Http404(f"Tipo de documento '{tipo_documento}' não suportado.")
