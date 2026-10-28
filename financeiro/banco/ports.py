"""
Portas e abstrações para integração bancária e provedores de cobrança (Sprint 10A - Tarefa 1).
Segue ADR-041: BancoGatewayPort desacoplado da lógica de negócio.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, List, Dict, Any
import datetime


@dataclass
class CobrancaEmitidaResult:
    """Resultado da emissão de cobrança registrada (Boleto / PIX)."""
    gateway_charge_id: str
    nosso_numero: str = ""
    linha_digitavel: str = ""
    codigo_barras: str = ""
    payload_pix: str = ""
    txid_pix: str = ""
    url_segunda_via: str = ""
    detalhes_brutos: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CobrancaConsultaResult:
    """Resultado da consulta de cobrança no gateway."""
    gateway_charge_id: str
    status: str  # PENDENTE, PAGO, CANCELADO
    valor_original: Decimal = Decimal('0.00')
    valor_pago: Decimal = Decimal('0.00')
    pago_em: Optional[datetime.date] = None
    detalhes_brutos: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookProcessadoResult:
    """Resultado da decodificação e validação de webhook."""
    valido: bool
    evento: str  # ex: 'PAYMENT_RECEIVED', 'PAYMENT_OVERDUE', 'PAYMENT_DELETED'
    gateway_charge_id: str = ""
    nosso_numero: str = ""
    txid_pix: str = ""
    valor_pago: Decimal = Decimal('0.00')
    valor_tarifa: Decimal = Decimal('0.00')
    valor_juros: Decimal = Decimal('0.00')
    valor_multa: Decimal = Decimal('0.00')
    valor_desconto: Decimal = Decimal('0.00')
    data_pagamento: Optional[datetime.date] = None
    mensagem_erro: str = ""


class AssinaturaInvalidaError(Exception):
    """Exceção levantada quando a assinatura criptográfica do webhook for inválida."""
    pass


class BancoGatewayPort(ABC):
    """
    Porta abstrata de integração com Gateways de Cobrança e Bancos.
    Permite alternar entre Gateway PSP (ex: Asaas) e Arquivo CNAB (ex: Itaú).
    """

    @abstractmethod
    def emitir_boleto(self, config, parcela) -> CobrancaEmitidaResult:
        """Emite boleto registrado para a parcela financeira."""
        pass

    @abstractmethod
    def emitir_pix(self, config, parcela) -> CobrancaEmitidaResult:
        """Gera cobrança PIX com QR Code / Copia e Cola associado à parcela."""
        pass

    @abstractmethod
    def consultar_cobranca(self, config, gateway_charge_id: str) -> CobrancaConsultaResult:
        """Consulta o estado atual da cobrança no provedor."""
        pass

    @abstractmethod
    def cancelar(self, config, gateway_charge_id: str) -> bool:
        """Cancela ou dá baixa de instrução de cobrança no provedor."""
        pass

    @abstractmethod
    def processar_webhook(
        self,
        config,
        payload: dict,
        signature: str,
        raw_body: bytes
    ) -> WebhookProcessadoResult:
        """
        Valida a autenticidade da requisição webhook (HMAC/Token) e traduz o evento.
        Deve levantar AssinaturaInvalidaError caso a assinatura não confira.
        """
        pass
