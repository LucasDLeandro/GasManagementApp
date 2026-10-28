import io
import zipfile
from datetime import date
from django.utils import timezone
from fiscal.models import ConfiguracaoFiscalFilial, DocumentoFiscal


def verificar_vencimento_certificados(dias: int = 30) -> list[dict]:
    """
    Monitora a validade dos certificados digitais de todas as filiais (Task 2).
    Gera alerta antecipado para certificados que vencem dentro de 'dias' (padrão 30 dias).
    """
    hoje = timezone.localdate()
    limite = hoje + timezone.timedelta(days=dias)

    alertas = []
    configs = ConfiguracaoFiscalFilial.objects.filter(
        certificado_valido_ate__isnull=False,
        certificado_valido_ate__lte=limite
    ).select_related('filial', 'tenant')

    for cfg in configs:
        valido_ate = cfg.certificado_valido_ate
        dias_restantes = (valido_ate - hoje).days
        alertas.append({
            'tenant_id': str(cfg.tenant_id),
            'tenant_nome': cfg.tenant.nome,
            'filial_id': cfg.filial_id,
            'filial_nome': cfg.filial.nome,
            'valido_ate': valido_ate.isoformat(),
            'dias_restantes': dias_restantes,
            'expirado': dias_restantes < 0,
            'mensagem': (
                f"Certificado Digital da filial '{cfg.filial.nome}' EXPIRADO há {abs(dias_restantes)} dias!"
                if dias_restantes < 0 else
                f"Certificado Digital da filial '{cfg.filial.nome}' vence em {dias_restantes} dias ({valido_ate.strftime('%d/%m/%Y')})."
            )
        })

    return alertas


def gerar_lote_xmls_contador(
    tenant,
    filial_id: int = None,
    data_inicio: date = None,
    data_fim: date = None
) -> bytes:
    """
    Gera arquivo ZIP contendo todos os XMLs autorizados do período para envio à contabilidade (Task 10).
    Acesso restrito a usuários autorizados.
    """
    qs = DocumentoFiscal.objects.filter(
        tenant=tenant,
        status__in=['AUTORIZADO', 'CANCELADO']
    ).exclude(xml_autorizado='')

    if filial_id:
        qs = qs.filter(filial_id=filial_id)

    if data_inicio:
        qs = qs.filter(criado_em__date__gte=data_inicio)

    if data_fim:
        qs = qs.filter(criado_em__date__lte=data_fim)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc in qs:
            nome_arquivo = f"{doc.chave_acesso or f'doc_{doc.numero}_{doc.serie}'}.xml"
            zf.writestr(nome_arquivo, doc.xml_autorizado.encode('utf-8'))

    buffer.seek(0)
    return buffer.getvalue()
