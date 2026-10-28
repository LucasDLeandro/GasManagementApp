from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class RespostaEmissao:
    """Resposta canônica de emissão de documento fiscal (NF-e, CT-e, MDF-e)."""
    sucesso: bool
    status: str  # 'AUTORIZADO', 'PROCESSANDO', 'REJEITADO', 'ERRO'
    chave_acesso: Optional[str] = None
    numero: Optional[int] = None
    serie: Optional[int] = None
    protocolo: Optional[str] = None
    xml_autorizado: Optional[str] = None
    danfe_url_ou_pdf: Optional[str] = None
    codigo_status_sefaz: Optional[str] = None
    motivo_status_sefaz: Optional[str] = None
    acao_sugerida: Optional[str] = None
    recibo: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)

    @property
    def mensagem_erro(self) -> str:
        return self.motivo_status_sefaz or ''

    @property
    def status_sefaz(self) -> str:
        return self.codigo_status_sefaz or self.status

    @property
    def xml(self) -> str:
        return self.xml_autorizado or ''

    @property
    def danfe_url(self) -> str:
        return self.danfe_url_ou_pdf or ''


@dataclass
class RespostaConsulta:
    """Resposta de consulta de situação de documento na SEFAZ."""
    sucesso: bool
    status: str  # 'AUTORIZADO', 'REJEITADO', 'CANCELADO', 'PROCESSANDO'
    chave_acesso: Optional[str] = None
    protocolo: Optional[str] = None
    xml_autorizado: Optional[str] = None
    codigo_status_sefaz: Optional[str] = None
    motivo_status_sefaz: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)

    @property
    def mensagem_erro(self) -> str:
        return self.motivo_status_sefaz or ''

    @property
    def status_sefaz(self) -> str:
        return self.codigo_status_sefaz or self.status


@dataclass
class RespostaEvento:
    """Resposta de registro de evento fiscal (Cancelamento, CC-e, Inutilização, Encerramento MDF-e)."""
    sucesso: bool
    status: str  # 'AUTORIZADO', 'REJEITADO', 'ERRO'
    tipo_evento: str  # 'CANCELAMENTO', 'CCE', 'INUTILIZACAO', 'ENCERRAMENTO'
    protocolo: Optional[str] = None
    xml_evento: Optional[str] = None
    codigo_status_sefaz: Optional[str] = None
    motivo_status_sefaz: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)

    @property
    def mensagem_erro(self) -> str:
        return self.motivo_status_sefaz or ''

    @property
    def status_sefaz(self) -> str:
        return self.codigo_status_sefaz or self.status

    @property
    def xml(self) -> str:
        return self.xml_evento or ''


@dataclass
class RespostaDownload:
    """Resposta para download de arquivos oficiais (XML e DANFE PDF)."""
    sucesso: bool
    xml_conteudo: Optional[str] = None
    danfe_pdf_bytes: Optional[bytes] = None
    motivo_erro: Optional[str] = None


class EmissorFiscalPort(ABC):
    """
    Porta de comunicação com a SEFAZ / Gateways Fiscais (Task 1 / ADR-042).
    Desacopla a camada de aplicação de qualquer provedor específico (Focus NFe, Nuvem Fiscal, SEFAZ direta).
    """

    @abstractmethod
    def emitir_nfe(self, payload: Dict[str, Any], config: Optional[Any] = None) -> RespostaEmissao:
        """Transmite NF-e (modelo 55) para autorização."""
        pass

    @abstractmethod
    def consultar(self, chave_ou_recibo: str, config: Optional[Any] = None) -> RespostaConsulta:
        """Consulta o status de um documento na SEFAZ pelo recibo ou chave de 44 dígitos."""
        pass

    @abstractmethod
    def cancelar(self, chave: str, justificativa: str, protocolo: str, config: Optional[Any] = None) -> RespostaEvento:
        """Transmite evento de cancelamento para NF-e autorizada."""
        pass

    @abstractmethod
    def carta_correcao(self, chave: str, texto_correcao: str, seq: int, config: Optional[Any] = None) -> RespostaEvento:
        """Transmite Carta de Correção Eletrônica (CC-e)."""
        pass

    @abstractmethod
    def inutilizar(self, serie: int, numero_inicial: int, numero_final: int, justificativa: str, config: Optional[Any] = None) -> RespostaEvento:
        """Inutiliza faixa ou número único de NF-e não utilizado na SEFAZ."""
        pass

    @abstractmethod
    def emitir_mdfe(self, payload: Dict[str, Any], config: Optional[Any] = None) -> RespostaEmissao:
        """Transmite MDF-e (modelo 58)."""
        pass

    @abstractmethod
    def encerrar_mdfe(self, chave: str, protocolo: str, municipio_ibge: str, config: Optional[Any] = None) -> RespostaEvento:
        """Encerra MDF-e perante a SEFAZ de destino."""
        pass

    @abstractmethod
    def emitir_cte(self, payload: Dict[str, Any], config: Optional[Any] = None) -> RespostaEmissao:
        """Transmite CT-e (modelo 57)."""
        pass

    @abstractmethod
    def baixar_xml_danfe(self, chave: str, config: Optional[Any] = None) -> RespostaDownload:
        """Baixa o XML autorizado e o DANFE gerado."""
        pass
