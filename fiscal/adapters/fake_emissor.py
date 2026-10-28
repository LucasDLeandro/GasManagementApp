import datetime
from typing import Dict, Any, Optional, List
from fiscal.ports.emissor_fiscal_port import (
    EmissorFiscalPort,
    RespostaEmissao,
    RespostaConsulta,
    RespostaEvento,
    RespostaDownload,
)


class TimeoutFiscalException(Exception):
    """Exceção simulada de timeout na comunicação com o gateway / SEFAZ."""
    pass


class FakeEmissor(EmissorFiscalPort):
    """
    Adaptador de teste que implementa EmissorFiscalPort (Task 1).
    Permite simular cenários controlados:
    - Autorização com geração de chave válida e protocolo;
    - Rejeição SEFAZ com código e mensagem oficial;
    - Timeout de conexão;
    - Duplicidade de emissão;
    - Eventos de cancelamento, carta de correção e inutilização.
    """

    def __init__(
        self,
        comportamento: Optional[str] = None,
        modo: Optional[str] = None,
        codigo_rejeicao: Optional[str] = None,
        motivo_rejeicao: Optional[str] = None,
        acao_sugerida: Optional[str] = None,
        **kwargs
    ):
        escolhido = modo or comportamento or 'AUTORIZAR'
        self.modo: str = escolhido.upper()
        self.codigo_rejeicao: str = codigo_rejeicao or '539'
        self.motivo_rejeicao: str = motivo_rejeicao or 'Duplicidade de NF-e com diferença na Chave de Acesso'
        self.acao_sugerida: str = acao_sugerida or 'Consulte a chave de acesso anterior ou altere a numeração.'
        if self.modo == 'REJEITAR':
            if codigo_rejeicao:
                self.configurar_rejeicao(codigo_rejeicao, motivo_rejeicao or '', acao_sugerida or '')
            else:
                self.configurar_rejeicao('225', 'Rejeição 225: Falha no Schema XML do lote de NFe', 'Revise a formatação dos campos do XML.')
        elif self.modo == 'TIMEOUT':
            self.configurar_timeout()
        elif self.modo == 'DUPLICIDADE':
            self.configurar_duplicidade()

        self.chamadas: List[Dict[str, Any]] = []
        self.documentos_emitidos: Dict[str, Dict[str, Any]] = {}
        self.eventos_registrados: List[Dict[str, Any]] = []

    def configurar_autorizacao(self):
        """Configura o fake para responder com sucesso e autorização."""
        self.modo = 'AUTORIZAR'

    def configurar_rejeicao(self, codigo: str = '600', motivo: str = 'CSOSN incompatível na operação com Não Contribuinte', acao_sugerida: str = 'Ajuste a regra tributária e informe CSOSN compatível.'):
        """Configura o fake para simular rejeição pela SEFAZ."""
        self.modo = 'REJEITAR'
        self.codigo_rejeicao = codigo
        self.motivo_rejeicao = motivo
        self.acao_sugerida = acao_sugerida

    def configurar_timeout(self):
        """Configura o fake para simular timeout de rede."""
        self.modo = 'TIMEOUT'

    def configurar_duplicidade(self):
        """Configura o fake para simular duplicidade de chave ou número consumido."""
        self.modo = 'DUPLICIDADE'
        self.codigo_rejeicao = '204'
        self.motivo_rejeicao = 'Rejeição 204: Duplicidade de NF-e [chNFe: 35261011222333000144550010000000011000000018]'
        self.acao_sugerida = 'A nota fiscal já foi autorizada previamente pela SEFAZ. Utilize a chave existente.'

    def _gerar_chave_fake(self, uf: str, cnpj: str, mod: str, serie: int, numero: int) -> str:
        """Gera uma chave de acesso com 44 dígitos coerente com o padrão SEFAZ."""
        agora = datetime.datetime.now()
        aamm = agora.strftime('%y%m')
        uf_cod = '35' if uf.upper() == 'SP' else '33' if uf.upper() == 'RJ' else '31' if uf.upper() == 'MG' else '41'
        cnpj_clean = ''.join(c for c in str(cnpj) if c.isdigit()).zfill(14)[:14]
        mod_fmt = str(mod).replace('NFE_', '').zfill(2)[:2]
        serie_fmt = str(serie).zfill(3)[:3]
        num_fmt = str(numero).zfill(9)[:9]
        tipo_emissao = '1'
        codigo_numerico = '12345678'
        chave_sem_dv = f"{uf_cod}{aamm}{cnpj_clean}{mod_fmt}{serie_fmt}{num_fmt}{tipo_emissao}{codigo_numerico}"
        # Dígito verificador fixo para mock
        dv = '8'
        return f"{chave_sem_dv}{dv}"[:44]

    def emitir_nfe(self, payload: Dict[str, Any], config: Optional[Any] = None) -> RespostaEmissao:
        self.chamadas.append({'operacao': 'emitir_nfe', 'payload': payload, 'config': config})

        if self.modo == 'TIMEOUT':
            raise TimeoutFiscalException("Timeout ao conectar com gateway fiscal / SEFAZ após 30 segundos.")

        if self.modo == 'REJEITAR':
            return RespostaEmissao(
                sucesso=False,
                status='REJEITADO',
                codigo_status_sefaz=self.codigo_rejeicao,
                motivo_status_sefaz=self.motivo_rejeicao,
                acao_sugerida=self.acao_sugerida,
                raw_response={'status': 'rejeitado', 'codigo': self.codigo_rejeicao, 'mensagem': self.motivo_rejeicao}
            )

        if self.modo == 'DUPLICIDADE':
            return RespostaEmissao(
                sucesso=False,
                status='REJEITADO',
                codigo_status_sefaz=self.codigo_rejeicao,
                motivo_status_sefaz=self.motivo_rejeicao,
                acao_sugerida=self.acao_sugerida,
                raw_response={'status': 'duplicidade', 'codigo': self.codigo_rejeicao}
            )

        # Sucesso: autorização
        serie = payload.get('serie', getattr(config, 'serie_nfe', 1))
        numero = payload.get('numero', getattr(config, 'proximo_numero_nfe', 1))
        uf = payload.get('uf_emitente', 'SP')
        cnpj = payload.get('cnpj_emitente', '11222333000144')

        chave = self._gerar_chave_fake(uf, cnpj, '55', serie, numero)
        protocolo = f"1352600{numero:08d}"
        xml_mock = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><nfeProc versao=\"4.00\"><NFe><infNFe Id=\"NFe{chave}\"><ide><nNF>{numero}</nNF><serie>{serie}</serie></ide></infNFe></NFe><protNFe><infProt><nProt>{protocolo}</nProt><cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe></nfeProc>"

        res = RespostaEmissao(
            sucesso=True,
            status='AUTORIZADO',
            chave_acesso=chave,
            numero=numero,
            serie=serie,
            protocolo=protocolo,
            xml_autorizado=xml_mock,
            danfe_url_ou_pdf=f"https://fiscal-storage.local/danfe/{chave}.pdf",
            codigo_status_sefaz='100',
            motivo_status_sefaz='Autorizado o uso da NF-e',
            acao_sugerida=None,
            raw_response={'status': 'autorizado', 'chave': chave, 'protocolo': protocolo}
        )
        self.documentos_emitidos[chave] = {
            'payload': payload,
            'resposta': res,
            'status': 'AUTORIZADO'
        }
        return res

    def consultar(self, chave_ou_recibo: str, config: Optional[Any] = None) -> RespostaConsulta:
        self.chamadas.append({'operacao': 'consultar', 'chave': chave_ou_recibo})
        if self.modo == 'TIMEOUT':
            raise TimeoutFiscalException("Timeout de consulta.")

        doc = self.documentos_emitidos.get(chave_ou_recibo)
        if doc:
            return RespostaConsulta(
                sucesso=True,
                status=doc['status'],
                chave_acesso=chave_ou_recibo,
                protocolo=doc['resposta'].protocolo,
                xml_autorizado=doc['resposta'].xml_autorizado,
                codigo_status_sefaz='100',
                motivo_status_sefaz='Autorizado o uso da NF-e'
            )
        return RespostaConsulta(
            sucesso=False,
            status='NAO_ENCONTRADO',
            chave_acesso=chave_ou_recibo,
            motivo_status_sefaz='Documento não localizado na SEFAZ'
        )

    def cancelar(self, chave: Optional[str] = None, *args, **kwargs) -> RespostaEvento:
        chave = chave or kwargs.get('chave_acesso') or kwargs.get('chave') or ''
        justificativa = kwargs.get('justificativa') or ''
        protocolo = kwargs.get('protocolo') or kwargs.get('protocolo_autorizacao') or ''
        for a in args:
            if isinstance(a, str):
                if not protocolo and (a.startswith('135') or len(a) < 15):
                    protocolo = a
                elif not justificativa:
                    justificativa = a

        self.chamadas.append({
            'operacao': 'cancelar',
            'chave': chave,
            'justificativa': justificativa,
            'protocolo': protocolo
        })
        if self.modo == 'REJEITAR':
            return RespostaEvento(
                sucesso=False,
                status='REJEITADO',
                tipo_evento='CANCELAMENTO',
                codigo_status_sefaz=self.codigo_rejeicao,
                motivo_status_sefaz=self.motivo_rejeicao
            )

        prot_evento = f"1352699{len(self.eventos_registrados) + 1:06d}"
        xml_ev = f"<procEventoNFe><evento><infEvento><tpEvento>110111</tpEvento><chNFe>{chave}</chNFe><nProt>{prot_evento}</nProt><xJust>{justificativa}</xJust></infEvento></evento></procEventoNFe>"
        evento_info = {
            'tipo': 'CANCELAMENTO',
            'chave': chave,
            'protocolo': prot_evento,
            'justificativa': justificativa
        }
        self.eventos_registrados.append(evento_info)
        if chave in self.documentos_emitidos:
            self.documentos_emitidos[chave]['status'] = 'CANCELADO'

        return RespostaEvento(
            sucesso=True,
            status='AUTORIZADO',
            tipo_evento='CANCELAMENTO',
            protocolo=prot_evento,
            xml_evento=xml_ev,
            codigo_status_sefaz='135',
            motivo_status_sefaz='Evento registrado e vinculado a NF-e'
        )

    def carta_correcao(self, chave: Optional[str] = None, *args, **kwargs) -> RespostaEvento:
        chave = chave or kwargs.get('chave_acesso') or kwargs.get('chave') or ''
        texto_correcao = kwargs.get('correcao') or kwargs.get('texto_correcao')
        seq = kwargs.get('sequencial') or kwargs.get('seq')

        if len(args) == 1:
            if isinstance(args[0], int):
                seq = args[0]
            else:
                texto_correcao = str(args[0])
        elif len(args) >= 2:
            if isinstance(args[0], int):
                seq, texto_correcao = args[0], args[1]
            else:
                texto_correcao, seq = args[0], args[1]

        seq = int(seq or 1)
        texto_correcao = str(texto_correcao or '')

        self.chamadas.append({
            'operacao': 'carta_correcao',
            'chave': chave,
            'texto_correcao': texto_correcao,
            'seq': seq
        })
        if self.modo == 'REJEITAR':
            return RespostaEvento(
                sucesso=False,
                status='REJEITADO',
                tipo_evento='CCE',
                codigo_status_sefaz=self.codigo_rejeicao,
                motivo_status_sefaz=self.motivo_rejeicao
            )

        prot_cce = f"1352688{seq:06d}"
        xml_cce = f"<procEventoNFe><evento><infEvento><tpEvento>110110</tpEvento><chNFe>{chave}</chNFe><nSeqEvento>{seq}</nSeqEvento><nProt>{prot_cce}</nProt><xCorrecao>{texto_correcao}</xCorrecao></infEvento></evento></procEventoNFe>"
        self.eventos_registrados.append({
            'tipo': 'CCE',
            'chave': chave,
            'seq': seq,
            'protocolo': prot_cce
        })
        return RespostaEvento(
            sucesso=True,
            status='AUTORIZADO',
            tipo_evento='CCE',
            protocolo=prot_cce,
            xml_evento=xml_cce,
            codigo_status_sefaz='135',
            motivo_status_sefaz='Evento registrado e vinculado a NF-e'
        )

    def inutilizar(self, *args, **kwargs) -> RespostaEvento:
        serie = kwargs.get('serie') or (args[0] if len(args) > 0 else 1)
        num_inicial = kwargs.get('numero_inicial') or kwargs.get('num_inicial') or (args[1] if len(args) > 1 else 1)
        num_final = kwargs.get('numero_final') or kwargs.get('num_final') or (args[2] if len(args) > 2 else num_inicial)
        justificativa = kwargs.get('justificativa') or (args[3] if len(args) > 3 else '')

        num_ini = int(num_inicial)
        self.chamadas.append({
            'operacao': 'inutilizar',
            'serie': serie,
            'numero_inicial': num_ini,
            'numero_final': int(num_final),
            'justificativa': justificativa
        })
        if self.modo == 'REJEITAR':
            return RespostaEvento(
                sucesso=False,
                status='REJEITADO',
                tipo_evento='INUTILIZACAO',
                codigo_status_sefaz=self.codigo_rejeicao,
                motivo_status_sefaz=self.motivo_rejeicao
            )

        prot_inut = f"1352677{num_ini:06d}"
        xml_inut = f"<retInutNFe><infInut><nProt>{prot_inut}</nProt><cStat>102</cStat><xMotivo>Inutilização de número homologada</xMotivo></infInut></retInutNFe>"
        return RespostaEvento(
            sucesso=True,
            status='AUTORIZADO',
            tipo_evento='INUTILIZACAO',
            protocolo=prot_inut,
            xml_evento=xml_inut,
            codigo_status_sefaz='102',
            motivo_status_sefaz='Inutilização de número homologada'
        )

    def emitir_mdfe(self, payload: Dict[str, Any], config: Optional[Any] = None) -> RespostaEmissao:
        self.chamadas.append({'operacao': 'emitir_mdfe', 'payload': payload})
        chave = self._gerar_chave_fake('SP', '11222333000144', '58', 1, 1)
        return RespostaEmissao(
            sucesso=True,
            status='AUTORIZADO',
            chave_acesso=chave,
            numero=1,
            serie=1,
            protocolo="135265500001234",
            codigo_status_sefaz='100',
            motivo_status_sefaz='Autorizado o uso do MDF-e'
        )

    def encerrar_mdfe(self, chave: str, protocolo: str, municipio_ibge: str, config: Optional[Any] = None) -> RespostaEvento:
        self.chamadas.append({'operacao': 'encerrar_mdfe', 'chave': chave, 'municipio_ibge': municipio_ibge})
        return RespostaEvento(
            sucesso=True,
            status='AUTORIZADO',
            tipo_evento='ENCERRAMENTO',
            protocolo="135264400001234",
            codigo_status_sefaz='135',
            motivo_status_sefaz='Encerramento homologado'
        )

    def emitir_cte(self, payload: Dict[str, Any], config: Optional[Any] = None) -> RespostaEmissao:
        self.chamadas.append({'operacao': 'emitir_cte', 'payload': payload})
        chave = self._gerar_chave_fake('SP', '11222333000144', '57', 1, 1)
        return RespostaEmissao(
            sucesso=True,
            status='AUTORIZADO',
            chave_acesso=chave,
            numero=1,
            serie=1,
            protocolo="135263300001234",
            codigo_status_sefaz='100',
            motivo_status_sefaz='Autorizado o uso do CT-e'
        )

    def baixar_xml_danfe(self, chave: str, config: Optional[Any] = None) -> RespostaDownload:
        self.chamadas.append({'operacao': 'baixar_xml_danfe', 'chave': chave})
        xml = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><nfeProc><infNFe Id=\"NFe{chave}\"/></nfeProc>"
        pdf = b"%PDF-1.4 Mock DANFE PDF Content"
        return RespostaDownload(
            sucesso=True,
            xml_conteudo=xml,
            danfe_pdf_bytes=pdf
        )
