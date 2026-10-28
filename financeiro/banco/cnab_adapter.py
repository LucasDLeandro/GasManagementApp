"""
Adaptador de Arquivo CNAB (Itaú CNAB 400/240) para remessa e retorno (Sprint 10A - Tarefa 1).
Implementa geração de arquivo de remessa e parsing resiliente de retorno.
"""
import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from core.money import quantize
from financeiro.banco.ports import (
    BancoGatewayPort,
    CobrancaEmitidaResult,
    CobrancaConsultaResult,
    WebhookProcessadoResult,
)


@dataclass
class ItemRetornoCNAB:
    """Item parseado de registro detalhe de arquivo de retorno CNAB."""
    nosso_numero: str
    data_ocorrencia: datetime.date
    data_vencimento: Optional[datetime.date]
    valor_titulo: Decimal
    valor_pago: Decimal
    valor_tarifa: Decimal
    valor_juros: Decimal
    valor_multa: Decimal
    valor_desconto: Decimal
    codigo_ocorrencia: str
    descricao_ocorrencia: str
    numero_documento: str = ""


class ArquivoCNABAdapter(BancoGatewayPort):
    """
    Adaptador de Remessa e Retorno bancário via arquivos de layout padrão CNAB 400 (Banco Itaú 341).
    """

    def emitir_boleto(self, config, parcela) -> CobrancaEmitidaResult:
        """
        No fluxo CNAB, a emissão gera o Nosso Número na carteira configurada para a remessa.
        """
        carteira = config.carteira or "109"
        nosso_numero = parcela.nosso_numero or f"{carteira}{parcela.id:08d}"
        linha_digitavel = f"34191.{nosso_numero[:5]} {nosso_numero[5:]}8 00000.000000 1 90000000{int(parcela.valor_nominal * 100):06d}"
        codigo_barras = f"34191900000000{int(parcela.valor_nominal * 100):06d}{nosso_numero}"

        return CobrancaEmitidaResult(
            gateway_charge_id=f"cnab_{parcela.id}_{nosso_numero}",
            nosso_numero=nosso_numero,
            linha_digitavel=linha_digitavel,
            codigo_barras=codigo_barras,
            detalhes_brutos={"layout": "CNAB_400_ITAU", "carteira": carteira}
        )

    def emitir_pix(self, config, parcela) -> CobrancaEmitidaResult:
        """CNAB tradicional não emite PIX de forma nativa síncrona."""
        return self.emitir_boleto(config, parcela)

    def consultar_cobranca(self, config, gateway_charge_id: str) -> CobrancaConsultaResult:
        return CobrancaConsultaResult(gateway_charge_id=gateway_charge_id, status="PENDENTE")

    def cancelar(self, config, gateway_charge_id: str) -> bool:
        return True

    def processar_webhook(self, config, payload, signature, raw_body) -> WebhookProcessadoResult:
        # CNAB opera via arquivos em lote, não via webhook HTTP direto
        return WebhookProcessadoResult(valido=True, evento="CNAB_BATCH")

    # Aliases padronizados
    def gerar_remessa(self, config, parcelas: list, sequencial_remessa: int = 1) -> str:
        return self.gerar_remessa_cnab400(config, parcelas)

    def processar_retorno(self, config, conteudo_arquivo: str) -> list:
        return self.processar_retorno_cnab400(config, conteudo_arquivo)

    # -------------------------------------------------------------------------
    # OPERAÇÕES DE ARQUIVO CNAB 400 (ITAÚ)
    # -------------------------------------------------------------------------

    def gerar_remessa_cnab400(self, config, parcelas: list) -> str:
        """
        Gera o conteúdo de texto de um arquivo de remessa CNAB 400 Itaú (Layout Cobrança Registrada).
        Linhas com tamanho rigoroso de 400 caracteres cada.
        """
        hoje = datetime.date.today()
        linhas = []
        agencia = (config.conta_financeira.agencia or "0000")[:4].zfill(4)
        conta = (config.conta_financeira.conta or "00000")[:5].zfill(5)
        razao_empresa = (config.tenant.nome if hasattr(config, 'tenant') else "EMPRESA")[:30].ljust(30)

        # 1. Header do Arquivo (Registro 0)
        header_parts = [
            "0",
            "1",
            "REMESSA".ljust(7),
            "01",
            "COBRANCA".ljust(15),
            agencia,
            "00",
            conta,
            "0",
            "".ljust(8),
            razao_empresa,
            "341",
            "BANCO ITAU SA".ljust(15),
            hoje.strftime('%d%m%y'),
            "".ljust(294),
            "000001",
        ]
        header = "".join(header_parts)
        linhas.append(header[:400].ljust(400))

        # 2. Detalhes (Registro 1 por parcela)
        seq = 2
        for p in parcelas:
            nosso_num = (p.nosso_numero or f"{p.id:08d}")[:8].zfill(8)
            carteira = (config.carteira or "109")[:3].zfill(3)
            num_doc = str(p.id)[:10].ljust(10)
            vencimento_str = p.data_vencimento.strftime("%d%m%y")
            centavos_valor = f"{int(p.valor_nominal * 100):013d}"
            
            nome_pagador = "CLIENTE PADRAO"
            doc_pagador = "00000000000"
            if p.titulo.cliente:
                nome_pagador = p.titulo.cliente.nome[:30].ljust(30)
                doc_pagador = "".join(filter(str.isdigit, p.titulo.cliente.documento or "0")).zfill(14)
            else:
                nome_pagador = nome_pagador.ljust(30)
                doc_pagador = doc_pagador.zfill(14)

            tipo_inscricao = "02" if len(doc_pagador) == 14 else "01"

            detalhe_parts = [
                "1",
                tipo_inscricao,
                doc_pagador[:14],
                agencia,
                "00",
                conta,
                "0",
                "".ljust(4),
                "0000",
                num_doc,
                nosso_num,
                "".ljust(13),
                carteira,
                "".ljust(21),
                "I",
                "01",
                num_doc,
                vencimento_str,
                centavos_valor,
                "341",
                "00000",
                "01",
                "N",
                hoje.strftime('%d%m%y'),
                "00",
                "00",
                "0000000000000",
                "000000",
                "0000000000000",
                "0000000000000",
                "0000000000000",
                tipo_inscricao,
                doc_pagador[:14],
                nome_pagador,
                "".ljust(10),
                "".ljust(40),
                "".ljust(12),
                "00000000",
                "".ljust(15),
                "SP",
                "".ljust(34),
                f"{seq:06d}",
            ]
            linha_detalhe = "".join(detalhe_parts)
            linhas.append(linha_detalhe[:400].ljust(400))
            seq += 1

        # 3. Trailler (Registro 9)
        trailler_parts = [
            "9",
            "".ljust(393),
            f"{seq:06d}",
        ]
        trailler = "".join(trailler_parts)
        linhas.append(trailler[:400].ljust(400))
        return "\r\n".join(linhas) + "\r\n"

    def processar_retorno_cnab400(self, conteudo_texto: str) -> List[ItemRetornoCNAB]:
        """
        Lê e interpreta o conteúdo textual de um arquivo de retorno CNAB 400 Itaú.
        Retorna lista estruturada de ItemRetornoCNAB para conciliação bancária.
        """
        itens = []
        linhas = conteudo_texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")

        for num_linha, linha in enumerate(linhas, start=1):
            if len(linha) < 400:
                continue

            tipo_registro = linha[0]
            if tipo_registro != "1":
                continue  # Processa apenas registros de Detalhe (tipo 1)

            # Extração segundo Layout Itaú CNAB 400 Retorno
            # Nosso número: posições 86-93 (8 dígitos) ou 63-70
            nosso_numero = linha[85:93].strip() or linha[62:70].strip()
            codigo_ocorrencia = linha[108:110].strip()  # ex: 06 = Liquidação normal
            
            data_ocorrencia_str = linha[110:116].strip()
            num_documento = linha[116:126].strip()
            vencimento_str = linha[146:152].strip()

            valor_titulo_centavos = linha[152:165].strip()
            valor_pago_centavos = linha[253:266].strip()
            tarifa_centavos = linha[175:188].strip()
            juros_centavos = linha[266:279].strip()
            multa_centavos = "0"
            desconto_centavos = linha[240:253].strip()

            def parse_date(d_str: str) -> Optional[datetime.date]:
                if not d_str or len(d_str) != 6 or not d_str.isdigit() or d_str == "000000":
                    return None
                try:
                    dia = int(d_str[:2])
                    mes = int(d_str[2:4])
                    ano = int(d_str[4:6]) + 2000
                    return datetime.date(ano, mes, dia)
                except ValueError:
                    return None

            def parse_cents(c_str: str) -> Decimal:
                if not c_str or not c_str.isdigit():
                    return Decimal("0.00")
                return quantize(Decimal(c_str) / Decimal(100), 2)

            data_ocorr = parse_date(data_ocorrencia_str) or datetime.date.today()
            data_venc = parse_date(vencimento_str)

            valor_titulo = parse_cents(valor_titulo_centavos)
            valor_pago = parse_cents(valor_pago_centavos)
            valor_tarifa = parse_cents(tarifa_centavos)
            valor_juros = parse_cents(juros_centavos)
            valor_desconto = parse_cents(desconto_centavos)

            descricao_ocorr = "Liquidação Normal" if codigo_ocorrencia in ("06", "08", "09", "10") else f"Ocorrência {codigo_ocorrencia}"

            itens.append(ItemRetornoCNAB(
                nosso_numero=nosso_numero,
                data_ocorrencia=data_ocorr,
                data_vencimento=data_venc,
                valor_titulo=valor_titulo,
                valor_pago=valor_pago,
                valor_tarifa=valor_tarifa,
                valor_juros=valor_juros,
                valor_multa=Decimal("0.00"),
                valor_desconto=valor_desconto,
                codigo_ocorrencia=codigo_ocorrencia,
                descricao_ocorrencia=descricao_ocorr,
                numero_documento=num_documento
            ))

        return itens
