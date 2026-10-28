import logging
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from fiscal.models import (
    DocumentoFiscal,
    DocumentoFiscalEvento,
    TarefaInutilizacaoNumeracao,
    ConfiguracaoFiscalFilial,
)
from fiscal.services.nfe_venda_service import obter_emissor_fiscal

logger = logging.getLogger(__name__)


@transaction.atomic
def cancelar_nfe(
    documento: DocumentoFiscal,
    justificativa: str,
    emissor_port=None
) -> DocumentoFiscalEvento:
    """
    Realiza o cancelamento formal de NF-e autorizada perante a SEFAZ (Task 8).
    Validações:
    - Documento deve estar com status 'AUTORIZADO'.
    - Justificativa mínima de 15 caracteres (regra SEFAZ).
    - Verificação de prazo regulamentar por UF/Filial (padrão 24h, configurável na filial).
    """
    assert_tenant_writable(documento.tenant)

    if documento.status != 'AUTORIZADO':
        raise ValidationError(
            f"Apenas documentos com status AUTORIZADO podem ser cancelados. Status atual: {documento.status}"
        )

    justificativa_limpa = str(justificativa or '').strip()
    if len(justificativa_limpa) < 15:
        raise ValidationError(
            "A justificativa de cancelamento perante a SEFAZ deve conter no mínimo 15 caracteres."
        )

    # Verificação do prazo regulamentar da filial
    config = ConfiguracaoFiscalFilial.objects.filter(
        tenant=documento.tenant,
        filial=documento.filial
    ).first()

    prazo_horas = config.prazo_cancelamento_horas if config else 24
    if documento.data_autorizacao:
        limite_cancelamento = documento.data_autorizacao + timezone.timedelta(hours=prazo_horas)
        if timezone.now() > limite_cancelamento:
            raise ValidationError(
                f"Prazo regulamentar de cancelamento ({prazo_horas}h) expirado para a NF-e #{documento.numero}. "
                f"Autorizada em {documento.data_autorizacao.strftime('%d/%m/%Y %H:%M')}, limite era {limite_cancelamento.strftime('%d/%m/%Y %H:%M')}."
            )

    emissor = emissor_port or (obter_emissor_fiscal(config) if config else None)
    if not emissor:
        raise ValidationError("Emissor fiscal não configurado para processar o cancelamento.")

    resposta = emissor.cancelar(
        chave_acesso=documento.chave_acesso,
        protocolo_autorizacao=documento.protocolo,
        justificativa=justificativa_limpa
    )

    if not resposta.sucesso:
        raise ValidationError(f"Cancelamento rejeitado pela SEFAZ: {resposta.mensagem_erro}")

    # Registra o evento de cancelamento
    evento = DocumentoFiscalEvento.objects.create(
        tenant=documento.tenant,
        documento=documento,
        tipo_evento='CANCELAMENTO',
        sequencial=1,
        protocolo=resposta.protocolo,
        xml_evento=resposta.xml,
        justificativa=justificativa_limpa,
        status='AUTORIZADO'
    )

    documento.status = 'CANCELADO'
    documento.save(update_fields=['status', 'atualizado_em'])

    return evento


@transaction.atomic
def carta_correcao_nfe(
    documento: DocumentoFiscal,
    correcao: str,
    emissor_port=None
) -> DocumentoFiscalEvento:
    """
    Emite Carta de Correção Eletrônica (CC-e) vinculada à NF-e (Task 8).
    Validações:
    - Documento deve estar AUTORIZADO.
    - Texto com no mínimo 15 caracteres e máximo 1000.
    - Sequencial incremental automático (máximo 20 eventos por NF-e).
    """
    assert_tenant_writable(documento.tenant)

    if documento.status != 'AUTORIZADO':
        raise ValidationError("CC-e só pode ser emitida para documentos com status AUTORIZADO.")

    correcao_limpa = str(correcao or '').strip()
    if len(correcao_limpa) < 15:
        raise ValidationError("O texto da Carta de Correção deve conter no mínimo 15 caracteres.")
    if len(correcao_limpa) > 1000:
        raise ValidationError("O texto da Carta de Correção não pode exceder 1000 caracteres.")

    # Sequencial do evento
    eventos_anteriores = DocumentoFiscalEvento.objects.filter(
        tenant=documento.tenant,
        documento=documento,
        tipo_evento='CCE'
    ).count()

    proximo_seq = eventos_anteriores + 1
    if proximo_seq > 20:
        raise ValidationError("Limite máximo de 20 Cartas de Correção atingido para esta NF-e.")

    config = ConfiguracaoFiscalFilial.objects.filter(
        tenant=documento.tenant,
        filial=documento.filial
    ).first()
    emissor = emissor_port or (obter_emissor_fiscal(config) if config else None)
    if not emissor:
        raise ValidationError("Emissor fiscal não configurado.")

    resposta = emissor.carta_correcao(
        chave_acesso=documento.chave_acesso,
        sequencial=proximo_seq,
        correcao=correcao_limpa
    )

    if not resposta.sucesso:
        raise ValidationError(f"CC-e rejeitada pela SEFAZ: {resposta.mensagem_erro}")

    evento = DocumentoFiscalEvento.objects.create(
        tenant=documento.tenant,
        documento=documento,
        tipo_evento='CCE',
        sequencial=proximo_seq,
        protocolo=resposta.protocolo,
        xml_evento=resposta.xml,
        justificativa=correcao_limpa,
        status='AUTORIZADO'
    )

    return evento


@transaction.atomic
def processar_inutilizacao(
    tarefa: TarefaInutilizacaoNumeracao,
    emissor_port=None
) -> TarefaInutilizacaoNumeracao:
    """
    Transmite o pedido formal de inutilização de numeração para a SEFAZ (Task 6 e Task 8).
    """
    assert_tenant_writable(tarefa.tenant)

    if tarefa.status == 'INUTILIZADO':
        return tarefa

    config = ConfiguracaoFiscalFilial.objects.filter(
        tenant=tarefa.tenant,
        filial=tarefa.filial
    ).first()
    emissor = emissor_port or (obter_emissor_fiscal(config) if config else None)
    if not emissor:
        raise ValidationError("Emissor fiscal não configurado.")

    tarefa.tentativas += 1
    resposta = emissor.inutilizar(
        serie=tarefa.serie,
        numero_inicial=tarefa.numero_inicial,
        numero_final=tarefa.numero_final,
        justificativa=tarefa.motivo
    )

    if resposta.sucesso:
        tarefa.status = 'INUTILIZADO'
        tarefa.protocolo = resposta.protocolo
    else:
        tarefa.status = 'ERRO'
        logger.error(f"[Fiscal] Erro ao inutilizar numeração ({tarefa}): {resposta.mensagem_erro}")

    tarefa.save(update_fields=['status', 'protocolo', 'tentativas', 'atualizado_em'])
    return tarefa
