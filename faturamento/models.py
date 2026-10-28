import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from core.tenancy import TenantAwareModel
from core.models import Tenant
from faturamento.crypto import encrypt_secret, decrypt_secret

class ConfiguracaoFiscalTenant(models.Model):
    """
    Configurações fiscais e certificado digital A1 (.pfx) do emissor por Tenant.
    """
    AMBIENTE_CHOICES = [
        ('HOMOLOGACAO', 'Homologação (Ambiente de Testes / SEFAZ-QA)'),
        ('PRODUCAO', 'Produção'),
    ]

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='configuracao_fiscal',
        verbose_name="Empresa (Tenant)"
    )
    cnpj_emissor = models.CharField(max_length=18, verbose_name="CNPJ do Emissor")
    inscricao_estadual = models.CharField(max_length=30, verbose_name="Inscrição Estadual")
    certificado_pfx = models.FileField(
        upload_to='certificados_fiscais/',
        null=True,
        blank=True,
        verbose_name="Certificado A1 (.pfx)"
    )
    senha_certificado = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Senha do Certificado (Criptografada)"
    )
    ambiente = models.CharField(
        max_length=20,
        choices=AMBIENTE_CHOICES,
        default='HOMOLOGACAO',
        verbose_name="Ambiente de Emissão"
    )
    token_api_focus = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Token API Fiscal (ex: Focus NFe)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração Fiscal do Tenant"
        verbose_name_plural = "Configurações Fiscais dos Tenants"

    def __str__(self):
        return f"Config Fiscal - {self.tenant.nome_fantasia} [{self.ambiente}]"

    def set_senha_certificado(self, raw_password: str):
        """Criptografa a senha do certificado com chave simétrica Fernet."""
        if raw_password:
            self.senha_certificado = encrypt_secret(raw_password)
        else:
            self.senha_certificado = ""

    def get_senha_certificado(self) -> str:
        """Descriptografa e retorna a senha do certificado."""
        return decrypt_secret(self.senha_certificado)

    @property
    def senha_descriptografada(self) -> str:
        return self.get_senha_certificado()


class NotaFiscal(TenantAwareModel):
    """
    Registro canônico de NF-e emitida para Venda ou Fatura de Estadia/Demurrage.
    Possui chave de acesso de 44 dígitos e rastreamento de ciclo na SEFAZ.
    """
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente de Envio'),
        ('PROCESSANDO', 'Em Processamento na SEFAZ'),
        ('AUTORIZADA', 'Autorizada'),
        ('REJEITADA', 'Rejeitada pela SEFAZ'),
        ('CANCELADA', 'Cancelada'),
    ]

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name="UUID Público de Consulta"
    )
    venda = models.OneToOneField(
        'vendas.Venda',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='nota_fiscal',
        verbose_name="Venda Associada"
    )
    fatura_estadia = models.OneToOneField(
        'clientes.FechamentoFaturaEstadia',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='nota_fiscal',
        verbose_name="Fatura de Estadia/Demurrage"
    )
    chave_acesso = models.CharField(
        max_length=44,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Chave de Acesso (44 dígitos)"
    )
    numero_nfe = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="Número da NF-e"
    )
    serie_nfe = models.CharField(
        max_length=10,
        default='1',
        verbose_name="Série"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDENTE',
        db_index=True,
        verbose_name="Status da NF-e"
    )
    valor_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor Total da Nota (R$)"
    )
    xml_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name="URL do XML Autorizado"
    )
    danfe_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name="URL do DANFE (PDF)"
    )
    motivo_rejeicao = models.TextField(
        null=True,
        blank=True,
        verbose_name="Motivo de Rejeição / Erro SEFAZ"
    )
    data_emissao = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/Hora de Autorização"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Nota Fiscal (NF-e)"
        verbose_name_plural = "Notas Fiscais (NF-e)"
        ordering = ['-criado_em']

    def __str__(self):
        destinatario = ""
        if self.venda and self.venda.cliente:
            destinatario = f" - {self.venda.cliente.nome}"
        elif self.fatura_estadia and self.fatura_estadia.cliente:
            destinatario = f" - {self.fatura_estadia.cliente.nome}"
        return f"NF-e {self.numero_nfe or self.chave_acesso or self.uuid} [{self.status}]{destinatario}"


class FaturaCobranca(TenantAwareModel):
    """
    Título de cobrança / fatura integrada a gateway de pagamentos (PIX, Boleto, Cartão).
    """
    STATUS_CHOICES = [
        ('ABERTA', 'Aberta / Aguardando Pagamento'),
        ('PAGA', 'Paga / Liquidada'),
        ('VENCIDA', 'Vencida'),
        ('CANCELADA', 'Cancelada'),
    ]

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name="UUID Público de Cobrança"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='faturas_cobranca',
        verbose_name="Cliente Destinatário"
    )
    venda = models.ForeignKey(
        'vendas.Venda',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='faturas_cobranca',
        verbose_name="Venda Vinculada"
    )
    estadia = models.ForeignKey(
        'clientes.FechamentoFaturaEstadia',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='faturas_cobranca',
        verbose_name="Fatura de Estadia Vinculada"
    )
    gateway_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="ID no Gateway de Pagamento"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='ABERTA',
        db_index=True,
        verbose_name="Status da Cobrança"
    )
    valor = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor Nominal (R$)"
    )
    qr_code_pix = models.TextField(
        null=True,
        blank=True,
        verbose_name="Payload Copia-e-Cola PIX / QR Code"
    )
    linha_digitavel = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Linha Digitável do Boleto"
    )
    link_pagamento = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name="Link de Pagamento / Checkout"
    )
    data_vencimento = models.DateField(
        verbose_name="Data de Vencimento"
    )
    data_pagamento = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data e Hora da Liquidação"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fatura de Cobrança"
        verbose_name_plural = "Faturas de Cobrança"
        ordering = ['-data_vencimento', '-criado_em']

    def __str__(self):
        return f"Cobrança #{self.gateway_id or self.uuid} - R$ {self.valor} [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.cliente_id:
            if self.venda and self.venda.cliente:
                self.cliente = self.venda.cliente
            elif self.estadia and self.estadia.cliente:
                self.cliente = self.estadia.cliente
        super().save(*args, **kwargs)

