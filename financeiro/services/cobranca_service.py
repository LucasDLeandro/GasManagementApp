"""
Serviço de Cobrança Registrada e Integração de Gateways/Webhooks (Sprint 10A - Tarefa 7).
Emissão de Boleto/PIX por parcela de forma idempotente, cancelamento e baixa automática por webhook validado.
"""
from decimal import Decimal
from typing import Optional, Dict, Any, List

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    ParcelaFinanceira,
    TituloFinanceiro,
    ConfiguracaoCobranca,
    ContaFinanceira,
    BaixaParcela,
)
from financeiro.banco.ports import BancoGatewayPort, AssinaturaInvalidaError
from financeiro.banco.psp_adapter import GatewayPSPAdapter
from financeiro.banco.cnab_adapter import ArquivoCNABAdapter
from financeiro.services.baixas import baixar_parcela


def obter_adaptador(config: ConfiguracaoCobranca) -> BancoGatewayPort:
    """Retorna a instância do adaptador bancário configurado."""
    if config.adaptador == 'GATEWAY_PSP':
        return GatewayPSPAdapter()
    elif config.adaptador == 'ARQUIVO_CNAB':
        return ArquivoCNABAdapter()
    raise ValidationError(f"Adaptador '{config.adaptador}' não reconhecido.")


@transaction.atomic
def emitir_cobranca_parcela(
    *,
    tenant,
    parcela_id: int,
    force: bool = False
) -> ParcelaFinanceira:
    """
    Emite cobrança registrada (Boleto e PIX) para uma parcela de título a RECEBER (Sprint 10A - Tarefa 7).
    Garante idempotência através do gateway_charge_id.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    parcela = ParcelaFinanceira.objects.select_for_update().get(id=parcela_id)
    if parcela.tenant_id != tenant.id:
        raise ValidationError("Parcela financeira pertence a outro Tenant.")

    titulo = parcela.titulo
    if titulo.tipo != 'RECEBER':
        raise ValidationError("Apenas títulos do tipo A RECEBER permitem emissão de cobrança.")

    if parcela.status in ('PAGA', 'CANCELADA', 'RENEGOCIADA'):
        raise ValidationError(f"A parcela #{parcela.id} encontra-se com status '{parcela.status}' e não aceita nova emissão.")

    # Idempotência estrita: se já possui charge_id e não é forçado, retorna a cobrança existente
    if parcela.gateway_charge_id and not force:
        return parcela

    # Localiza a configuração de cobrança ativa da conta ou tenant
    config = ConfiguracaoCobranca.objects.filter(
        tenant=tenant,
        ativo=True
    ).first()
    if not config:
        raise ValidationError("Nenhuma Configuração de Cobrança ativa foi encontrada para este Tenant.")

    adapter = obter_adaptador(config)

    # 1. Emissão de Boleto
    res_boleto = adapter.emitir_boleto(config, parcela)
    # 2. Emissão de PIX
    res_pix = adapter.emitir_pix(config, parcela)

    parcela.gateway_charge_id = res_boleto.gateway_charge_id or res_pix.gateway_charge_id
    parcela.nosso_numero = res_boleto.nosso_numero or parcela.nosso_numero
    parcela.linha_digitavel = res_boleto.linha_digitavel or parcela.linha_digitavel
    parcela.codigo_barras = res_boleto.codigo_barras or parcela.codigo_barras
    parcela.payload_pix = res_pix.payload_pix or parcela.payload_pix
    parcela.txid_pix = res_pix.txid_pix or parcela.txid_pix
    parcela.url_segunda_via_boleto = res_boleto.url_segunda_via or res_pix.url_segunda_via
    parcela.save(update_fields=[
        'gateway_charge_id',
        'nosso_numero',
        'linha_digitavel',
        'codigo_barras',
        'payload_pix',
        'txid_pix',
        'url_segunda_via_boleto',
        'atualizado_em'
    ])

    return parcela


@transaction.atomic
def emitir_cobranca_titulo(
    *,
    tenant,
    titulo_id: int
) -> List[ParcelaFinanceira]:
    """Emite cobrança para todas as parcelas em aberto de um título."""
    titulo = TituloFinanceiro.objects.get(id=titulo_id, tenant=tenant)
    parcelas_emitidas = []
    for p in titulo.parcelas.filter(status__in=['PENDENTE', 'PARCIAL']):
        p_emitida = emitir_cobranca_parcela(tenant=tenant, parcela_id=p.id)
        parcelas_emitidas.append(p_emitida)
    return parcelas_emitidas


@transaction.atomic
def cancelar_cobranca_parcela(
    *,
    tenant,
    parcela_id: int
) -> bool:
    """Cancela instrução de cobrança no provedor bancário (ao cancelar ou renegociar parcela)."""
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    parcela = ParcelaFinanceira.objects.select_for_update().get(id=parcela_id)
    if parcela.tenant_id != tenant.id:
        raise ValidationError("Parcela pertence a outro Tenant.")

    if not parcela.gateway_charge_id:
        return True

    config = ConfiguracaoCobranca.objects.filter(tenant=tenant, ativo=True).first()
    if config:
        adapter = obter_adaptador(config)
        adapter.cancelar(config, parcela.gateway_charge_id)

    return True


@transaction.atomic
def processar_webhook_cobranca(
    *,
    tenant,
    payload: Dict[str, Any],
    signature: str = '',
    raw_body: bytes = b''
) -> Dict[str, Any]:
    """
    Recebe notificação de webhook de pagamento com validação rigorosa de assinatura HMAC/Token (Sprint 10A - Tarefa 7).
    Garante idempotência: webhook repetido não gera segunda baixa.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    config = ConfiguracaoCobranca.objects.filter(tenant=tenant, ativo=True).first()
    if not config:
        raise ValidationError("Configuração de cobrança não encontrada para validação do webhook.")

    adapter = obter_adaptador(config)

    # 1. Validação estrita da assinatura
    res_webhook = adapter.processar_webhook(
        config=config,
        payload=payload,
        signature=signature,
        raw_body=raw_body
    )

    # 2. Localização da Parcela correspondente
    parcela = None
    if res_webhook.gateway_charge_id:
        parcela = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            gateway_charge_id=res_webhook.gateway_charge_id
        ).select_for_update().first()

    if not parcela and res_webhook.txid_pix:
        parcela = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            txid_pix=res_webhook.txid_pix
        ).select_for_update().first()

    if not parcela and res_webhook.nosso_numero:
        parcela = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            nosso_numero=res_webhook.nosso_numero
        ).select_for_update().first()

    if not parcela:
        return {
            "status": "ignored",
            "message": "Nenhuma parcela correspondente aos identificadores recebidos foi localizada."
        }

    # 3. Verificação de IDEMPOTÊNCIA: Parcela já liquidada não pode ser baixada novamente
    if parcela.status == 'PAGA' or parcela.saldo_em_aberto == Decimal('0.00'):
        baixa_existente = BaixaParcela.objects.filter(parcela=parcela, estornado=False).first()
        return {
            "status": "already_paid",
            "parcela_id": parcela.id,
            "baixa_id": baixa_existente.id if baixa_existente else None,
            "message": f"Parcela #{parcela.id} já se encontra liquidada. Segunda baixa bloqueada por idempotência."
        }

    # 4. Execução da Baixa Automática da Parcela
    valor_liq = min(res_webhook.valor_pago, parcela.saldo_em_aberto)
    baixa = baixar_parcela(
        tenant=tenant,
        parcela_id=parcela.id,
        conta_financeira_id=config.conta_financeira_id,
        valor_principal=valor_liq,
        data_liquidacao=res_webhook.data_pagamento or timezone.localdate(),
        valor_tarifa=res_webhook.valor_tarifa,
        valor_juros=res_webhook.valor_juros,
        valor_multa=res_webhook.valor_multa,
        valor_desconto=res_webhook.valor_desconto,
        comprovante=f"Webhook {res_webhook.evento}: Charge {res_webhook.gateway_charge_id or res_webhook.txid_pix}",
        usuario=None
    )

    return {
        "status": "success",
        "parcela_id": parcela.id,
        "baixa_id": baixa.id,
        "valor_baixado": str(valor_liq)
    }
