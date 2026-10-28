import json
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.tenancy import TenantAwareModel
from core.models import Filial
from fiscal.crypto import encrypt_fiscal_secret, decrypt_fiscal_secret

AMBIENTE_CHOICES = [
    ('HOMOLOGACAO', 'Homologação (Testes SEFAZ)'),
    ('PRODUCAO', 'Produção'),
]

REGIME_TRIBUTARIO_CHOICES = [
    ('SIMPLES_NACIONAL', 'Simples Nacional'),
    ('SIMPLES_EXCESSO', 'Simples Nacional - Excesso de Sublimite de Receita'),
    ('REGIME_NORMAL', 'Regime Normal (Lucro Presumido / Lucro Real)'),
]

CRT_CHOICES = [
    ('1', '1 - Simples Nacional'),
    ('2', '2 - Simples Nacional - Excesso de Sublimite'),
    ('3', '3 - Regime Normal'),
    ('4', '4 - Simples Nacional - Microempreendedor Individual (MEI)'),
]

MODELO_DF_CHOICES = [
    ('NFE_55', 'NF-e (Modelo 55 - Mercadorias)'),
    ('CTE_57', 'CT-e (Modelo 57 - Conhecimento de Transporte)'),
    ('MDFE_58', 'MDF-e (Modelo 58 - Manifesto de Carga)'),
    ('FATURA_LOCACAO', 'Fatura de Locação / Estadia de Cilindros'),
]

STATUS_DF_CHOICES = [
    ('RASCUNHO', 'Rascunho'),
    ('VALIDANDO', 'Em Validação Pré-Emissão'),
    ('ENVIADO', 'Enviado para SEFAZ'),
    ('AUTORIZADO', 'Autorizado pela SEFAZ'),
    ('REJEITADO', 'Rejeitado pela SEFAZ'),
    ('CANCELADO', 'Cancelado'),
    ('INUTILIZADO', 'Inutilizado'),
    ('CONTINGENCIA', 'Em Contingência'),
]

TRIBUTO_CHOICES = [
    ('ICMS', 'ICMS Próprio'),
    ('ICMS_ST', 'ICMS Substituição Tributária'),
    ('PIS', 'PIS'),
    ('COFINS', 'COFINS'),
    ('IPI', 'IPI'),
    ('ISS', 'ISS Municipal'),
    ('IBS', 'IBS (Reforma Tributária)'),
    ('CBS', 'CBS (Reforma Tributária)'),
    ('IS', 'Imposto Seletivo (Reforma Tributária)'),
]

TIPO_OPERACAO_FISCAL_CHOICES = [
    ('VENDA', 'Venda de Mercadoria / Gás'),
    ('DEVOLUCAO', 'Devolução de Mercadoria'),
    ('DEVOLUCAO_VENDA', 'Devolução de Venda de Mercadorias'),
    ('TRANSFERENCIA', 'Transferência entre Filiais'),
    ('REMESSA_COMODATO', 'Remessa de Cilindro em Comodato'),
    ('RETORNO_COMODATO', 'Retorno de Cilindro em Comodato'),
    ('REMESSA_VASILHAME', 'Remessa de Vasilhame / Sacaria'),
    ('RETORNO_VASILHAME', 'Retorno de Vasilhame / Sacaria'),
    ('REMESSA_CONSERTO', 'Remessa para Reteste / Manutenção / Conserto'),
    ('RETORNO_CONSERTO', 'Retorno de Reteste / Manutenção / Conserto'),
    ('COMPRA', 'Compra / Entrada de Insumos'),
    ('RECARGA_TERCEIRO', 'Recarga de Cilindros de Terceiros / Industrialização'),
    ('FATURA_LOCACAO', 'Fatura de Locação / Estadia de Cilindros'),
    ('CTE_TRANSPORTE', 'Prestação de Serviço de Transporte Tributado (CT-e)'),
    ('MDFE_CARGA', 'Manifesto Eletrônico de Carga (MDF-e)'),
]


class ConfiguracaoFiscalFilial(TenantAwareModel):
    """
    Configuração fiscal e credenciais operacionais por Filial (Task 2 / 1:1 com Filial).
    Certificado A1 (.pfx) e credenciais de gateway são rigorosamente cifrados.
    Chaves de cifra residem em variáveis de ambiente / KMS, NUNCA no banco de dados.
    """
    filial = models.OneToOneField(
        Filial,
        on_delete=models.CASCADE,
        related_name='configuracao_fiscal',
        verbose_name="Filial / Unidade Operacional"
    )
    regime_tributario = models.CharField(
        max_length=30,
        choices=REGIME_TRIBUTARIO_CHOICES,
        default='SIMPLES_NACIONAL',
        verbose_name="Regime Tributário"
    )
    crt = models.CharField(
        max_length=1,
        choices=CRT_CHOICES,
        default='1',
        verbose_name="Código de Regime Tributário (CRT)"
    )
    ambiente = models.CharField(
        max_length=20,
        choices=AMBIENTE_CHOICES,
        default='HOMOLOGACAO',
        verbose_name="Ambiente de Emissão"
    )
    serie_nfe = models.PositiveIntegerField(default=1, verbose_name="Série NF-e (55)")
    proximo_numero_nfe = models.PositiveIntegerField(default=1, verbose_name="Próximo Número NF-e")
    serie_mdfe = models.PositiveIntegerField(default=1, verbose_name="Série MDF-e (58)")
    proximo_numero_mdfe = models.PositiveIntegerField(default=1, verbose_name="Próximo Número MDF-e")
    serie_cte = models.PositiveIntegerField(default=1, verbose_name="Série CT-e (57)")
    proximo_numero_cte = models.PositiveIntegerField(default=1, verbose_name="Próximo Número CT-e")

    inscricao_municipal = models.CharField(max_length=30, blank=True, default='', verbose_name="Inscrição Municipal")
    cnae = models.CharField(max_length=10, blank=True, default='', verbose_name="CNAE Principal")

    # Arquivo de certificado e credenciais cifradas
    certificado_ref = models.CharField(max_length=500, blank=True, default='', verbose_name="Referência/Caminho Cifrado do Certificado A1")
    certificado_valido_ate = models.DateField(null=True, blank=True, verbose_name="Validade do Certificado Digital A1")
    credenciais_gateway_cifradas = models.TextField(blank=True, default='', verbose_name="Credenciais do Gateway Cifradas")
    prazo_cancelamento_horas = models.PositiveIntegerField(default=24, verbose_name="Prazo Regulamentar de Cancelamento (Horas)")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração Fiscal da Filial"
        verbose_name_plural = "Configurações Fiscais das Filiais"

    def __str__(self):
        return f"Config Fiscal - {self.filial.nome} [{self.ambiente}]"

    def set_credenciais(self, dados: dict):
        """Criptografa e armazena dicionário de credenciais de gateway com chave de ambiente."""
        if dados:
            raw_str = json.dumps(dados)
            self.credenciais_gateway_cifradas = encrypt_fiscal_secret(raw_str)
        else:
            self.credenciais_gateway_cifradas = ""

    def get_credenciais(self) -> dict:
        """Descriptografa credenciais de gateway usando chave de ambiente."""
        if not self.credenciais_gateway_cifradas:
            return {}
        try:
            raw_str = decrypt_fiscal_secret(self.credenciais_gateway_cifradas)
            return json.loads(raw_str) if raw_str else {}
        except Exception:
            return {}

    def certificado_expira_em_breve(self, dias: int = 30) -> bool:
        """Retorna True se o certificado digital vencer dentro da janela informada (padrão 30 dias - Task 2)."""
        if not self.certificado_valido_ate:
            return False
        hoje = timezone.localdate()
        limite = hoje + timezone.timedelta(days=dias)
        return self.certificado_valido_ate <= limite


class RegraTributaria(TenantAwareModel):
    """
    Regra Tributária parametrizável e auditável aprovada pelo contador (Task 4 / F-25).
    Determina o CFOP e os tributos incidentes com base em especificidade rigorosa:
    NCM + UFs + Operação vence NCM + Operação, que vence apenas Operação.
    Em PRODUÇÃO, somente regras aprovadas (`aprovada_por`) podem ser utilizadas.
    """
    descricao = models.CharField(max_length=255, verbose_name="Descrição da Regra")
    vigencia_inicio = models.DateField(verbose_name="Início da Vigência")
    vigencia_fim = models.DateField(null=True, blank=True, verbose_name="Fim da Vigência")
    uf_origem = models.CharField(max_length=2, blank=True, default='', verbose_name="UF Origem (* para qualquer)")
    uf_destino = models.CharField(max_length=2, blank=True, default='', verbose_name="UF Destino (* para qualquer)")
    tipo_operacao = models.CharField(max_length=30, choices=TIPO_OPERACAO_FISCAL_CHOICES, default='VENDA', verbose_name="Tipo de Operação")
    ncm = models.CharField(max_length=8, blank=True, default='', verbose_name="NCM Específico (* para qualquer)")
    cfop = models.CharField(max_length=4, verbose_name="CFOP")

    # Governança e aprovação formal contábil (F-25)
    aprovada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='regras_tributarias_aprovadas',
        verbose_name="Contador / Usuário Aprovador"
    )
    aprovada_em = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora de Aprovação")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regra Tributária"
        verbose_name_plural = "Regras Tributárias"
        ordering = ['-vigencia_inicio', 'descricao']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'uf_origem', 'uf_destino', 'tipo_operacao', 'ncm', 'vigencia_inicio'],
                name='unique_tenant_regra_tributaria_chave'
            )
        ]

    def __str__(self):
        aprov = "APROVADA" if self.aprovada_por else "NÃO APROVADA"
        ncm_info = f" NCM {self.ncm}" if self.ncm else ""
        return f"{self.descricao} (CFOP {self.cfop}{ncm_info}) [{aprov}]"

    def is_aprovada(self) -> bool:
        return self.aprovada_por is not None


class RegraTributariaTributo(TenantAwareModel):
    """
    Incidência tributária específica vinculada à Regra Tributária (Task 4).
    Grava alíquota, base de cálculo, CST/CSOSN e reduções.
    Suporta desde já a Reforma Tributária (IBS, CBS e IS) ativáveis por vigência.
    """
    regra = models.ForeignKey(
        RegraTributaria,
        on_delete=models.CASCADE,
        related_name='tributos',
        verbose_name="Regra Tributária"
    )
    tributo = models.CharField(max_length=15, choices=TRIBUTO_CHOICES, verbose_name="Tributo")
    cst_csosn = models.CharField(max_length=4, verbose_name="CST / CSOSN")
    reducao_base_pct = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal('0.0000'),
        verbose_name="Redução de Base (%)"
    )
    aliquota = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal('0.0000'),
        verbose_name="Alíquota (%)"
    )
    modo_calculo = models.CharField(
        max_length=20,
        choices=[('PERCENTUAL', 'Percentual sobre Base'), ('VALOR_PAUTA', 'Valor de Pauta Fixa')],
        default='PERCENTUAL',
        verbose_name="Modo de Cálculo"
    )
    codigo_beneficio = models.CharField(
        max_length=10,
        blank=True,
        default='',
        verbose_name="Código de Benefício Fiscal (cBenef)"
    )

    class Meta:
        verbose_name = "Tributo da Regra Tributária"
        verbose_name_plural = "Tributos da Regra Tributária"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'regra', 'tributo'],
                name='unique_tenant_regra_tributo'
            )
        ]

    def __str__(self):
        return f"{self.tributo} ({self.cst_csosn}) - {self.aliquota}%"


class DocumentoFiscal(TenantAwareModel):
    """
    Registro canônico de Documento Fiscal Eletrônico (Task 5 / NF-e 55, CT-e 57, MDF-e 58).
    Garante numeração sequencial sem buracos, idempotência e trilha auditável de XML e DANFE.
    """
    filial = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name='documentos_fiscais',
        verbose_name="Filial Emissora"
    )
    modelo = models.CharField(
        max_length=20,
        choices=MODELO_DF_CHOICES,
        default='NFE_55',
        verbose_name="Modelo Fiscal"
    )
    tipo_operacao = models.CharField(
        max_length=10,
        choices=[('SAIDA', 'Saída / Venda'), ('ENTRADA', 'Entrada / Compra')],
        default='SAIDA',
        verbose_name="Tipo de Operação"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_DF_CHOICES,
        default='RASCUNHO',
        db_index=True,
        verbose_name="Status Fiscal"
    )
    ambiente = models.CharField(
        max_length=20,
        choices=AMBIENTE_CHOICES,
        default='HOMOLOGACAO',
        verbose_name="Ambiente SEFAZ"
    )
    numero = models.PositiveIntegerField(verbose_name="Número do Documento")
    serie = models.PositiveIntegerField(default=1, verbose_name="Série")
    chave_acesso = models.CharField(
        max_length=44,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Chave de Acesso (44 dígitos)"
    )
    protocolo = models.CharField(max_length=50, blank=True, default='', verbose_name="Protocolo SEFAZ")
    xml_autorizado = models.TextField(blank=True, default='', verbose_name="XML Oficial Autorizado")
    danfe_url = models.URLField(max_length=500, blank=True, default='', verbose_name="URL do DANFE PDF")
    valor_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor Total (R$)"
    )
    origem_tipo = models.CharField(max_length=50, default='VENDA', verbose_name="Tipo da Origem")
    origem_id = models.CharField(max_length=50, db_index=True, verbose_name="ID da Origem (ex: venda_id)")
    motivo_rejeicao = models.TextField(blank=True, default='', verbose_name="Motivo de Rejeição SEFAZ")
    acao_sugerida = models.TextField(blank=True, default='', verbose_name="Ação Corretiva Sugerida")
    tentativas = models.PositiveIntegerField(default=0, verbose_name="Tentativas de Transmissão")
    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Chave de Idempotência"
    )
    data_autorizacao = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora de Autorização")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Documento Fiscal"
        verbose_name_plural = "Documentos Fiscais"
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'filial', 'modelo', 'serie', 'numero'],
                name='unique_tenant_filial_modelo_serie_numero'
            )
        ]

    def __str__(self):
        return f"{self.get_modelo_display()} #{self.numero} Série {self.serie} [{self.status}]"


class DocumentoFiscalItem(TenantAwareModel):
    """Item analítico do documento fiscal com amarração de NCM, CFOP e tributos incidentes."""
    documento = models.ForeignKey(
        DocumentoFiscal,
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Documento Fiscal"
    )
    numero_item = models.PositiveIntegerField(verbose_name="Número do Item")
    produto_id = models.CharField(max_length=50, blank=True, default='', verbose_name="ID do Produto")
    descricao = models.CharField(max_length=255, verbose_name="Descrição do Produto/Serviço")
    ncm = models.CharField(max_length=8, verbose_name="NCM")
    cest = models.CharField(max_length=7, blank=True, default='', verbose_name="CEST")
    cfop = models.CharField(max_length=4, verbose_name="CFOP")
    unidade = models.CharField(max_length=10, default='m3', verbose_name="Unidade")
    quantidade = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Quantidade")
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Unitário (R$)")
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Total do Item (R$)")

    class Meta:
        verbose_name = "Item do Documento Fiscal"
        verbose_name_plural = "Itens do Documento Fiscal"
        ordering = ['numero_item']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'documento', 'numero_item'],
                name='unique_tenant_documento_item'
            )
        ]

    def __str__(self):
        return f"Item {self.numero_item}: {self.descricao} (R$ {self.valor_total})"


class ItemDocumentoTributo(TenantAwareModel):
    """
    Linha por tributo e item gravando base, alíquota, valor e CST (Task 4).
    Aceita ICMS, PIS, COFINS, IPI, ISS, e a Reforma Tributária (IBS, CBS e IS).
    """
    item = models.ForeignKey(
        DocumentoFiscalItem,
        on_delete=models.CASCADE,
        related_name='tributos',
        verbose_name="Item do Documento"
    )
    tributo = models.CharField(max_length=15, choices=TRIBUTO_CHOICES, verbose_name="Tributo")
    cst = models.CharField(max_length=4, verbose_name="CST / CSOSN")
    base = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Base de Cálculo (R$)")
    aliquota = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal('0.0000'), verbose_name="Alíquota (%)")
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor do Tributo (R$)")

    class Meta:
        verbose_name = "Tributo do Item Fiscal"
        verbose_name_plural = "Tributos do Item Fiscal"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'item', 'tributo'],
                name='unique_tenant_item_tributo'
            )
        ]

    def __str__(self):
        return f"{self.tributo} CST {self.cst}: R$ {self.valor} ({self.aliquota}%)"


class DocumentoFiscalEvento(TenantAwareModel):
    """
    Registro histórico e imutável de eventos fiscais (Task 5 e Task 8):
    Cancelamento, Carta de Correção (CC-e), Inutilização e Encerramento de MDF-e.
    """
    documento = models.ForeignKey(
        DocumentoFiscal,
        on_delete=models.CASCADE,
        related_name='eventos',
        verbose_name="Documento Fiscal"
    )
    tipo_evento = models.CharField(
        max_length=20,
        choices=[
            ('CANCELAMENTO', 'Cancelamento de NF-e'),
            ('CCE', 'Carta de Correção Eletrônica'),
            ('INUTILIZACAO', 'Inutilização de Numeração'),
            ('ENCERRAMENTO', 'Encerramento de MDF-e')
        ],
        verbose_name="Tipo de Evento"
    )
    sequencial = models.PositiveIntegerField(default=1, verbose_name="Sequencial do Evento")
    protocolo = models.CharField(max_length=50, blank=True, default='', verbose_name="Protocolo SEFAZ")
    xml_evento = models.TextField(blank=True, default='', verbose_name="XML do Evento")
    justificativa = models.TextField(verbose_name="Justificativa")
    data_evento = models.DateTimeField(default=timezone.now, verbose_name="Data/Hora do Evento")
    status = models.CharField(
        max_length=20,
        choices=[('ENVIADO', 'Enviado'), ('AUTORIZADO', 'Homologado / Vinculado'), ('REJEITADO', 'Rejeitado')],
        default='ENVIADO',
        verbose_name="Status do Evento"
    )

    class Meta:
        verbose_name = "Evento de Documento Fiscal"
        verbose_name_plural = "Eventos de Documentos Fiscais"
        ordering = ['-data_evento']

    def __str__(self):
        return f"Evento {self.tipo_evento} seq {self.sequencial} - Doc #{self.documento.numero} [{self.status}]"


class TarefaInutilizacaoNumeracao(TenantAwareModel):
    """
    Garante a numeração sem buracos (Task 6):
    Documentos rejeitados, perdidos ou saltos de série detectados geram
    tarefa de inutilização perante a SEFAZ.
    """
    filial = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name='inutilizacoes_pendentes',
        verbose_name="Filial"
    )
    modelo = models.CharField(max_length=20, choices=MODELO_DF_CHOICES, default='NFE_55', verbose_name="Modelo")
    serie = models.PositiveIntegerField(default=1, verbose_name="Série")
    numero_inicial = models.PositiveIntegerField(verbose_name="Número Inicial")
    numero_final = models.PositiveIntegerField(verbose_name="Número Final")
    motivo = models.TextField(verbose_name="Justificativa da Inutilização (mínimo 15 caracteres)")
    protocolo = models.CharField(max_length=50, blank=True, default='', verbose_name="Protocolo de Inutilização")
    status = models.CharField(
        max_length=20,
        choices=[('PENDENTE', 'Pendente de Transmissão'), ('INUTILIZADO', 'Inutilizado na SEFAZ'), ('ERRO', 'Erro de Transmissão')],
        default='PENDENTE',
        verbose_name="Status"
    )
    tentativas = models.PositiveIntegerField(default=0, verbose_name="Tentativas")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tarefa de Inutilização de Numeração"
        verbose_name_plural = "Tarefas de Inutilização de Numeração"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Inutilização {self.modelo} Série {self.serie} [{self.numero_inicial}-{self.numero_final}] - {self.status}"


# ==============================================================================
# SPRINT 11B: FLUXOS FISCAIS PRÓPRIOS DE GASES
# ==============================================================================

class MovimentoComodatoFiscal(TenantAwareModel):
    """
    Rastreamento fiscal individual de cilindros em comodato/vasilhame (Sprint 11B - Tarefas 2 e 3).
    Permite auditar a conciliação entre a posse física e a posse fiscal de ativos em campo.
    """
    TIPO_MOVIMENTO_CHOICES = [
        ('REMESSA', 'Remessa em Comodato (Saída)'),
        ('RETORNO', 'Retorno de Comodato (Entrada)'),
    ]

    cilindro = models.ForeignKey(
        'produtos.Cilindro',
        on_delete=models.PROTECT,
        related_name='movimentos_comodato_fiscal',
        verbose_name="Cilindro / Ativo Rastreado"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.PROTECT,
        related_name='movimentos_comodato_fiscal',
        verbose_name="Cliente Destinatário / Depositário"
    )
    filial = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name='movimentos_comodato_fiscal',
        verbose_name="Filial Emitente"
    )
    documento_fiscal = models.ForeignKey(
        DocumentoFiscal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='movimentos_comodato',
        verbose_name="NF-e Vinculada"
    )
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_MOVIMENTO_CHOICES,
        verbose_name="Tipo de Movimento Fiscal"
    )
    data_movimento = models.DateTimeField(
        default=timezone.now,
        verbose_name="Data/Hora do Movimento"
    )
    valor_bem = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor de Avaliação / Reposição do Bem (R$)"
    )
    chave_nfe = models.CharField(
        max_length=44,
        blank=True,
        default='',
        verbose_name="Chave de Acesso da NF-e"
    )
    observacao = models.TextField(
        blank=True,
        default='',
        verbose_name="Observações"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Movimento de Comodato Fiscal"
        verbose_name_plural = "Movimentos de Comodato Fiscal"
        ordering = ['-data_movimento']
        indexes = [
            models.Index(fields=['tenant', 'cilindro', 'tipo']),
            models.Index(fields=['tenant', 'cliente', 'tipo']),
        ]

    def __str__(self):
        return f"{self.tipo} - Cilindro {self.cilindro.numero_serie_ogiva} ({self.cliente.nome})"


class ConfiguracaoMDFe(TenantAwareModel):
    """
    Configurações operacionais e regras estaduais para emissão de MDF-e (Sprint 11B - Tarefa 8).
    Exige MDF-e sempre em transporte interestadual e parametriza regras intermunicipais por UF.
    """
    filial = models.ForeignKey(
        Filial,
        on_delete=models.CASCADE,
        related_name='configuracoes_mdfe',
        verbose_name="Filial"
    )
    uf = models.CharField(
        max_length=2,
        verbose_name="UF de Origem"
    )
    exigir_sempre_interestadual = models.BooleanField(
        default=True,
        verbose_name="Exigir MDF-e Sempre em Operações Interestaduais"
    )
    exigir_intermunicipal = models.BooleanField(
        default=False,
        verbose_name="Exigir MDF-e em Operações Intermunicipais na UF"
    )
    prazo_alerta_horas = models.PositiveIntegerField(
        default=24,
        verbose_name="Prazo de Alerta para MDF-e Aberto sem Encerramento (Horas)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração de MDF-e"
        verbose_name_plural = "Configurações de MDF-e"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'filial', 'uf'], name='unique_tenant_filial_uf_mdfe')
        ]

    def __str__(self):
        return f"MDF-e {self.filial.nome} - UF {self.uf}"


class DocumentoFiscalEntrada(TenantAwareModel):
    """
    Registro e importação idempotente de NF-e de compra de fornecedores (Sprint 11B - Tarefa 9).
    Lê XML de compra, previne duplicidades pela chave de acesso e pré-preenche
    entradas de gás a granel (8C), aquisição de cilindros (8A) e contas a pagar (9B).
    """
    TIPO_ENTRADA_CHOICES = [
        ('GAS_GRANEL', 'Entrada de Gás a Granel (Tanque Criogênico)'),
        ('CILINDROS_CASCOS', 'Aquisição de Cilindros / Vazos de Pressão'),
        ('INSUMO_GERAL', 'Insumos Gerais / Peças / Válvulas'),
    ]

    filial = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name='documentos_entrada',
        verbose_name="Filial Receptora"
    )
    chave_acesso = models.CharField(
        max_length=44,
        db_index=True,
        verbose_name="Chave de Acesso da NF-e (44 dígitos)"
    )
    numero = models.PositiveIntegerField(verbose_name="Número da NF-e")
    serie = models.PositiveIntegerField(default=1, verbose_name="Série")
    data_emissao = models.DateField(verbose_name="Data de Emissão")
    fornecedor_nome = models.CharField(max_length=255, verbose_name="Razão Social do Fornecedor")
    fornecedor_cnpj = models.CharField(max_length=18, verbose_name="CNPJ do Fornecedor")
    valor_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Total da Nota (R$)"
    )
    valor_produtos = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor dos Produtos (R$)"
    )
    valor_frete = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor do Frete Destacado (R$)"
    )
    # Créditos tributários recuperáveis (apuração e custo de estoque)
    credito_icms = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Crédito de ICMS (R$)"
    )
    credito_pis = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Crédito de PIS (R$)"
    )
    credito_cofins = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Crédito de COFINS (R$)"
    )
    credito_ipi = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Crédito de IPI (R$)"
    )
    xml_conteudo = models.TextField(verbose_name="Conteúdo XML da NF-e de Compra")
    itens_json = models.JSONField(default=list, verbose_name="Itens Importados da NF-e")
    tipo_entrada = models.CharField(
        max_length=30,
        choices=TIPO_ENTRADA_CHOICES,
        default='INSUMO_GERAL',
        verbose_name="Destinação da Entrada"
    )
    entrada_gas_granel_id = models.IntegerField(null=True, blank=True, verbose_name="ID EntradaGasGranel")
    lote_aquisicao_id = models.IntegerField(null=True, blank=True, verbose_name="ID LoteAquisicaoCilindros")
    titulo_pagar = models.ForeignKey(
        'financeiro.TituloFinanceiro',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='documentos_entrada_origem',
        verbose_name="Título a Pagar Gerado"
    )
    status = models.CharField(
        max_length=20,
        choices=[('IMPORTADO', 'Importado'), ('INTEGRADO', 'Integrado com Estoque/Financeiro'), ('CANCELADO', 'Cancelado')],
        default='IMPORTADO',
        verbose_name="Status"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Documento Fiscal de Entrada (Compra)"
        verbose_name_plural = "Documentos Fiscais de Entrada (Compras)"
        ordering = ['-data_emissao', '-criado_em']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'chave_acesso'], name='unique_tenant_nfe_entrada_chave')
        ]

    def __str__(self):
        return f"NF-e Entrada #{self.numero}/{self.serie} - {self.fornecedor_nome} (R$ {self.valor_total})"


class ApuracaoImposto(TenantAwareModel):
    """
    Apuração gerencial de impostos por filial, competência e tributo (Sprint 11B - Tarefa 10).
    Consolida débitos (documentos de saída emitidos) e créditos (documentos de entrada).
    Gera título PAGAR de obrigações tributárias para saldos devedores.
    """
    STATUS_APURACAO_CHOICES = [
        ('ABERTO', 'Aberto / Em Andamento'),
        ('FECHADO', 'Fechado / Consolidado'),
        ('GUIA_GERADA', 'Guia Gerada / Título Criado'),
    ]

    filial = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name='apuracoes_imposto',
        verbose_name="Filial"
    )
    periodo = models.CharField(
        max_length=7,
        verbose_name="Período de Competência (AAAA-MM)"
    )
    tributo = models.CharField(
        max_length=20,
        choices=TRIBUTO_CHOICES,
        verbose_name="Tributo Apurado"
    )
    debitos = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Débitos do Período (Saídas)"
    )
    creditos = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Créditos do Período (Entradas)"
    )
    saldo_credor_anterior = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Saldo Credor Anterior (R$)"
    )
    saldo_apurado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Saldo Apurado (Positivo=A Recolher, Negativo=Credor)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_APURACAO_CHOICES,
        default='ABERTO',
        verbose_name="Status da Apuração"
    )
    fechado_em = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora de Fechamento")
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        verbose_name="Fechado Por"
    )
    titulo_pagar = models.ForeignKey(
        'financeiro.TituloFinanceiro',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='apuracoes_imposto',
        verbose_name="Título a Pagar da Guia de Recolhimento"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Apuração Gerencial de Imposto"
        verbose_name_plural = "Apurações Gerenciais de Impostos"
        ordering = ['-periodo', 'tributo']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'filial', 'periodo', 'tributo'], name='unique_tenant_filial_periodo_tributo')
        ]

    def __str__(self):
        return f"Apuração {self.tributo} - {self.periodo} ({self.filial.nome}): R$ {self.saldo_apurado}"


class OrdemRecargaTerceiro(TenantAwareModel):
    """
    Fluxo de recebimento, envase e devolução de cilindros pertencentes a clientes (Sprint 11B - Tarefa 11).
    Suporta industrialização por encomenda ou prestação de serviço conforme parecer contábil.
    """
    STATUS_RECARGA_CHOICES = [
        ('RECEBIDO', 'Cilindros Recebidos'),
        ('EM_ENVASE', 'Em Processo de Envase'),
        ('ENVASADO', 'Envasado / Pronto para Retirada'),
        ('DEVOLVIDO', 'Devolvido ao Cliente'),
        ('FATURADO', 'Faturado / Concluído'),
    ]

    TIPO_FATURAMENTO_CHOICES = [
        ('INDUSTRIALIZACAO_ENCOMENDA', 'Industrialização por Encomenda (NF-e 55 - CFOP 5.124)'),
        ('PRESTACAO_SERVICO', 'Prestação de Serviço (NFS-e Municipal)'),
    ]

    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.PROTECT,
        related_name='ordens_recarga_terceiro',
        verbose_name="Cliente Proprietário dos Cilindros"
    )
    filial = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name='ordens_recarga_terceiro',
        verbose_name="Filial Executora"
    )
    numero_ordem = models.CharField(
        max_length=50,
        verbose_name="Número da Ordem de Serviço / Recarga"
    )
    documento_entrada = models.ForeignKey(
        DocumentoFiscalEntrada,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ordens_recarga',
        verbose_name="NF-e de Remessa para Industrialização do Cliente"
    )
    documento_saida = models.ForeignKey(
        DocumentoFiscal,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ordens_recarga',
        verbose_name="NF-e de Retorno / Faturamento"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_RECARGA_CHOICES,
        default='RECEBIDO',
        verbose_name="Status da Ordem"
    )
    tipo_faturamento = models.CharField(
        max_length=30,
        choices=TIPO_FATURAMENTO_CHOICES,
        default='INDUSTRIALIZACAO_ENCOMENDA',
        verbose_name="Tratamento Fiscal de Faturamento"
    )
    custo_servico = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor Total do Serviço / Envase (R$)"
    )
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ordem de Recarga de Terceiros"
        verbose_name_plural = "Ordens de Recarga de Terceiros"
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'numero_ordem'], name='unique_tenant_ordem_recarga')
        ]

    def __str__(self):
        return f"Ordem #{self.numero_ordem} - {self.cliente.nome} [{self.status}]"


class ItemOrdemRecargaTerceiro(TenantAwareModel):
    """
    Cilindro individual integrante da Ordem de Recarga de Terceiros.
    """
    ordem = models.ForeignKey(
        OrdemRecargaTerceiro,
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Ordem de Recarga"
    )
    numero_serie_cilindro = models.CharField(
        max_length=100,
        verbose_name="Número de Série / Identificação do Cilindro"
    )
    gas = models.ForeignKey(
        'produtos.GasQuimico',
        on_delete=models.PROTECT,
        verbose_name="Gás Envasado"
    )
    volume_m3 = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        verbose_name="Volume Envasado (m³)"
    )
    lote_envase = models.ForeignKey(
        'produtos.LoteEnvase',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='recargas_terceiros',
        verbose_name="Lote de Envase Utilizado"
    )
    valor_servico = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor do Serviço Unitário (R$)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item da Ordem de Recarga de Terceiro"
        verbose_name_plural = "Itens da Ordem de Recarga de Terceiros"

    def __str__(self):
        return f"Cilindro {self.numero_serie_cilindro} - {self.gas.sigla} (Ordem #{self.ordem.numero_ordem})"

