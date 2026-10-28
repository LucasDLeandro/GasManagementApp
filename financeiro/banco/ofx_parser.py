"""
Parser OFX tolerante a codificação e variações SGML/XML (Sprint 10A - Tarefa 4).
Extrai transações, saldos e período com tratamento de encoding resiliente (UTF-8, Latin-1, CP1252).
"""
import re
import hashlib
import datetime
from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from core.money import quantize


@dataclass
class OFXTransacao:
    tipo: str  # CREDIT / DEBIT / OTHER
    data: datetime.date
    valor: Decimal  # com sinal: negativo=saída/débito, positivo=entrada/crédito
    fitid: str
    documento: str
    descricao: str
    hash_dedup: str = ""


@dataclass
class OFXExtratoResult:
    banco_codigo: str = ""
    agencia: str = ""
    conta: str = ""
    data_inicio: Optional[datetime.date] = None
    data_fim: Optional[datetime.date] = None
    saldo_final: Optional[Decimal] = None
    data_saldo_final: Optional[datetime.date] = None
    transacoes: List[OFXTransacao] = field(default_factory=list)


class OFXParser:
    """
    Parser robusto para arquivos OFX (Open Financial Exchange) versões 1.x (SGML) e 2.x (XML).
    Suporta tags não fechadas, quebras de linha irregulares e encodings múltiplos.
    """

    @classmethod
    def parse(cls, conteudo_bytes: bytes, conta_id: Optional[int] = None) -> OFXExtratoResult:
        """
        Decodifica bytes tentando UTF-8, CP1252 e ISO-8859-1, e realiza o parsing dos blocos OFX.
        """
        texto = cls._decodificar_bytes(conteudo_bytes)
        return cls._parse_texto(texto, conta_id)

    @classmethod
    def _decodificar_bytes(cls, conteudo: bytes) -> str:
        for enc in ['utf-8-sig', 'utf-8', 'cp1252', 'iso-8859-1', 'latin1']:
            try:
                return conteudo.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        # Fallback tolerante com substituição de caracteres inválidos
        return conteudo.decode('latin1', errors='replace')

    @classmethod
    def _parse_texto(cls, texto: str, conta_id: Optional[int] = None) -> OFXExtratoResult:
        result = OFXExtratoResult()

        # Remove cabeçalhos de SGML se existirem antes da tag <OFX>
        idx_ofx = texto.find("<OFX>")
        if idx_ofx == -1:
            idx_ofx = texto.find("<ofx>")
        
        corpo = texto[idx_ofx:] if idx_ofx != -1 else texto

        # 1. Informações de Conta Bancária
        bankid_match = re.search(r'<BANKID>\s*([^<\r\n]+)', corpo, re.IGNORECASE)
        if bankid_match:
            result.banco_codigo = bankid_match.group(1).strip()

        branchid_match = re.search(r'<BRANCHID>\s*([^<\r\n]+)', corpo, re.IGNORECASE)
        if branchid_match:
            result.agencia = branchid_match.group(1).strip()

        acctid_match = re.search(r'<ACCTID>\s*([^<\r\n]+)', corpo, re.IGNORECASE)
        if acctid_match:
            result.conta = acctid_match.group(1).strip()

        # 2. Período do Extrato
        dtstart_match = re.search(r'<DTSTART>\s*([^<\r\n]+)', corpo, re.IGNORECASE)
        if dtstart_match:
            result.data_inicio = cls._parse_ofx_date(dtstart_match.group(1))

        dtend_match = re.search(r'<DTEND>\s*([^<\r\n]+)', corpo, re.IGNORECASE)
        if dtend_match:
            result.data_fim = cls._parse_ofx_date(dtend_match.group(1))

        # 3. Saldo Final do Arquivo (LEDGERBAL)
        ledger_match = re.search(r'<LEDGERBAL>(.*?)</LEDGERBAL>', corpo, re.DOTALL | re.IGNORECASE)
        ledger_bloco = ledger_match.group(1) if ledger_match else corpo

        balamt_match = re.search(r'<BALAMT>\s*([^<\r\n]+)', ledger_bloco, re.IGNORECASE)
        if balamt_match:
            try:
                val_limpo = balamt_match.group(1).strip().replace(',', '.')
                result.saldo_final = quantize(Decimal(val_limpo), 2)
            except Exception:
                pass

        dtasof_match = re.search(r'<DTASOF>\s*([^<\r\n]+)', ledger_bloco, re.IGNORECASE)
        if dtasof_match:
            result.data_saldo_final = cls._parse_ofx_date(dtasof_match.group(1))

        # 4. Transações Bancárias (<STMTTRN>)
        pattern_trn = re.compile(r'<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|$)', re.DOTALL | re.IGNORECASE)
        trn_matches = pattern_trn.finditer(corpo)

        datas_encontradas = []

        for match in trn_matches:
            bloco_trn = match.group(1)
            if not bloco_trn.strip():
                continue

            tipo_m = re.search(r'<TRNTYPE>\s*([^<\r\n]+)', bloco_trn, re.IGNORECASE)
            dt_m = re.search(r'<DTPOSTED>\s*([^<\r\n]+)', bloco_trn, re.IGNORECASE)
            amt_m = re.search(r'<TRNAMT>\s*([^<\r\n]+)', bloco_trn, re.IGNORECASE)
            fitid_m = re.search(r'<FITID>\s*([^<\r\n]+)', bloco_trn, re.IGNORECASE)
            chk_m = re.search(r'<CHECKNUM>\s*([^<\r\n]+)', bloco_trn, re.IGNORECASE)
            memo_m = re.search(r'<MEMO>\s*([^<\r\n]+)', bloco_trn, re.IGNORECASE)
            name_m = re.search(r'<NAME>\s*([^<\r\n]+)', bloco_trn, re.IGNORECASE)

            if not dt_m or not amt_m:
                continue

            dt_trn = cls._parse_ofx_date(dt_m.group(1))
            if not dt_trn:
                continue

            datas_encontradas.append(dt_trn)

            try:
                amt_str = amt_m.group(1).strip().replace(',', '.')
                valor = quantize(Decimal(amt_str), 2)
            except Exception:
                continue

            tipo_trn = tipo_m.group(1).strip().upper() if tipo_m else ('DEBIT' if valor < Decimal('0.00') else 'CREDIT')
            fitid = fitid_m.group(1).strip() if fitid_m else ''
            documento = chk_m.group(1).strip() if chk_m else ''
            
            memo = memo_m.group(1).strip() if memo_m else ''
            name = name_m.group(1).strip() if name_m else ''
            descricao = memo or name or 'LANÇAMENTO EXTRATO'

            # Geração de hash de desduplicação robusto
            id_ref = str(conta_id or result.conta or "0")
            raw_dedup = f"{id_ref}|{dt_trn.isoformat()}|{valor}|{fitid}|{descricao}"
            hash_dedup = hashlib.sha256(raw_dedup.encode('utf-8')).hexdigest()

            result.transacoes.append(OFXTransacao(
                tipo=tipo_trn,
                data=dt_trn,
                valor=valor,
                fitid=fitid,
                documento=documento,
                descricao=descricao,
                hash_dedup=hash_dedup
            ))

        # Inferência de datas de início/fim caso não estejam explícitas no cabeçalho
        if datas_encontradas:
            if not result.data_inicio:
                result.data_inicio = min(datas_encontradas)
            if not result.data_fim:
                result.data_fim = max(datas_encontradas)

        return result

    @staticmethod
    def _parse_ofx_date(data_str: str) -> Optional[datetime.date]:
        """
        Interpreta data no formato YYYYMMDD ou YYYYMMDDHHMMSS[-03:EST].
        """
        limpo = data_str.strip()
        if len(limpo) < 8:
            return None
        ano_str = limpo[:4]
        mes_str = limpo[4:6]
        dia_str = limpo[6:8]
        if not (ano_str.isdigit() and mes_str.isdigit() and dia_str.isdigit()):
            return None
        try:
            return datetime.date(int(ano_str), int(mes_str), int(dia_str))
        except ValueError:
            return None
