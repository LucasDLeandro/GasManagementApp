import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from core.tenancy import TenantAwareModel

class Tenant(models.Model):
    PLANO_CHOICES = [
        ('STARTER', 'Starter'),
        ('PRO', 'Profissional'),
        ('ENTERPRISE', 'Enterprise'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    razao_social = models.CharField(max_length=255, verbose_name="Razão Social")
    nome_fantasia = models.CharField(max_length=255, verbose_name="Nome Fantasia")
    cnpj = models.CharField(max_length=18, unique=True, verbose_name="CNPJ")
    plano = models.CharField(max_length=20, choices=PLANO_CHOICES, default='STARTER', verbose_name="Plano")
    limite_cilindros = models.PositiveIntegerField(default=500, verbose_name="Limite de Cilindros")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Empresa (Tenant)"
        verbose_name_plural = "Empresas (Tenants)"
        ordering = ['nome_fantasia']

    def __str__(self):
        return f"{self.nome_fantasia} ({self.cnpj})"

    @property
    def nome(self):
        return self.nome_fantasia or self.razao_social

    def validar_aptidao_medicinal(self, exigir_envase=False):
        """Valida a conformidade sanitária do Tenant perante a ANVISA."""
        from core.regulatorio import validar_aptidao_medicinal
        return validar_aptidao_medicinal(self, exigir_envase=exigir_envase)


class Membership(models.Model):
    PAPEL_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('GERENTE', 'Gerente'),
        ('OPERADOR_PATIO', 'Operador de Pátio'),
        ('MOTORISTA', 'Motorista'),
        ('VENDEDOR', 'Vendedor'),
        ('RESPONSAVEL_TECNICO', 'Responsável Técnico (CRF/CRQ)'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name="Usuário"
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name="Empresa (Tenant)"
    )
    papel = models.CharField(max_length=25, choices=PAPEL_CHOICES, default='VENDEDOR', verbose_name="Papel")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Vínculo de Usuário e Tenant (Membership)"
        verbose_name_plural = "Vínculos de Usuários e Tenants"
        unique_together = ('user', 'tenant')

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.nome_fantasia} ({self.get_papel_display()})"


class ResponsavelTecnico(TenantAwareModel):
    """
    Registro do Responsável Técnico (Farmacêutico ou Químico) perante o Conselho de Classe
    e Vigilância Sanitária (ANVISA), conforme Resolução CFF nº 731/2022 e normas do CFQ.
    """
    CONSELHO_CHOICES = [
        ('CRF', 'Conselho Regional de Farmácia (CRF)'),
        ('CRQ', 'Conselho Regional de Química (CRQ)'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_rt',
        verbose_name="Usuário Vinculado"
    )
    nome_completo = models.CharField(max_length=255, verbose_name="Nome Completo do RT")
    conselho_classe = models.CharField(max_length=10, choices=CONSELHO_CHOICES, default='CRF', verbose_name="Conselho de Classe")
    numero_registro = models.CharField(max_length=50, verbose_name="Número de Registro no Conselho")
    uf_conselho = models.CharField(max_length=2, verbose_name="UF do Conselho")
    vigencia_inicio = models.DateField(verbose_name="Início da Vigência / Assunção de RT")
    vigencia_fim = models.DateField(null=True, blank=True, verbose_name="Término da Vigência")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Responsável Técnico (RT)"
        verbose_name_plural = "Responsáveis Técnicos (RTs)"
        ordering = ['nome_completo']

    @property
    def esta_vigente(self):
        """Retorna True se o RT estiver ativo e com prazo de vigência regular."""
        hoje = timezone.now().date()
        if not self.ativo:
            return False
        if self.vigencia_inicio > hoje:
            return False
        if self.vigencia_fim and self.vigencia_fim < hoje:
            return False
        return True

    def __str__(self):
        return f"{self.nome_completo} ({self.conselho_classe}-{self.uf_conselho} {self.numero_registro})"


class PerfilRegulatorioTenant(models.Model):
    """
    Perfil e Licenciamento Sanitário do Tenant perante a ANVISA e Vigilância Sanitária local.
    Define o modo de operação (Envasadora vs Distribuidora) e habilitações para gases medicinais.
    """
    MODO_CHOICES = [
        ('ENVASADORA', 'Envasadora de Gases (Fabricação/Envase)'),
        ('DISTRIBUIDORA', 'Distribuidora de Gases (Logística/Distribuição sem Envase)'),
        ('MISTO', 'Misto (Envasadora e Distribuidora)'),
    ]

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='perfil_regulatorio',
        verbose_name="Empresa (Tenant)"
    )
    modo_operacao = models.CharField(
        max_length=20,
        choices=MODO_CHOICES,
        default='ENVASADORA',
        verbose_name="Modo de Operação Regulatório"
    )
    afe_numero = models.CharField(max_length=50, verbose_name="Autorização de Funcionamento ANVISA (AFE)")
    afe_validade = models.DateField(null=True, blank=True, verbose_name="Validade da AFE")
    licenca_sanitaria_numero = models.CharField(max_length=50, verbose_name="Número da Licença Sanitária (VISA)")
    licenca_sanitaria_validade = models.DateField(verbose_name="Validade da Licença Sanitária")
    cbpf_cbpda_numero = models.CharField(max_length=50, blank=True, default='', verbose_name="Certificado de BPF/CBPDA (ANVISA)")
    cbpf_cbpda_validade = models.DateField(null=True, blank=True, verbose_name="Validade do CBPF/CBPDA")
    responsavel_tecnico_vigente = models.ForeignKey(
        ResponsavelTecnico,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='perfis_vigentes',
        verbose_name="Responsável Técnico Vigente"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Perfil Regulatório do Tenant"
        verbose_name_plural = "Perfis Regulatórios dos Tenants"

    def __str__(self):
        return f"Perfil Regulatório - {self.tenant.nome_fantasia} [{self.get_modo_operacao_display()}]"


# ==============================================================================
# WEBHOOKS & INTEGRAÇÃO ERP CANÔNICA (SPRINT 6)
# ==============================================================================

import ipaddress
import socket
from urllib.parse import urlparse
from django.core.exceptions import ValidationError


def validar_url_webhook_segura(value):
    """
    Validador de segurança para URLs de Webhook (Prevenção de SSRF - D7):
    - Exige HTTPS em produção (a menos que settings.DEBUG=True para desenvolvimento local).
    - Bloqueia resolução para loopback (127.0.0.0/8, ::1, localhost).
    - Bloqueia IPs privados (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16).
    - Bloqueia Link-Local (169.254.0.0/16, fe80::/10), multicast e endereços reservados.
    """
    if not value:
        raise ValidationError("URL do webhook é obrigatória.")

    parsed = urlparse(value)
    if not parsed.scheme:
        raise ValidationError("URL inválida: esquema não informado.")

    # Em produção, exige HTTPS
    if not settings.DEBUG and parsed.scheme.lower() != 'https':
        raise ValidationError("Em ambiente de produção, webhooks devem obrigatoriamente utilizar protocolo HTTPS seguro.")

    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("Hostname inválido na URL do webhook.")

    # Bloqueia literais localhost e variantes
    if hostname.lower() in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
        if not settings.DEBUG:
            raise ValidationError("Endereço de webhook não pode apontar para localhost ou loopback (SSRF).")

    # Resolução de DNS e validação de IP
    try:
        ip = ipaddress.ip_address(hostname)
        ips_to_check = [ip]
    except ValueError:
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            ips_to_check = [ipaddress.ip_address(addr[4][0]) for addr in addr_info]
        except socket.gaierror:
            ips_to_check = []

    for ip in ips_to_check:
        if ip.is_loopback:
            raise ValidationError("Endereço de webhook não pode apontar para loopback (SSRF).")
        if ip.is_private and not settings.DEBUG:
            raise ValidationError("Endereço de webhook não pode apontar para endereços de IP privados / RFC 1918 (SSRF).")
        if ip.is_link_local:
            raise ValidationError("Endereço de webhook não pode apontar para endereços de link-local (SSRF).")
        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValidationError("Endereço de webhook inválido ou reservado (SSRF).")


class WebhookEndpoint(TenantAwareModel):
    """
    Cadastramento de endpoints de webhooks externos (ERPs, TMS, sistemas de terceiros)
    com assinatura criptográfica HMAC-SHA256 por tenant.
    """
    url = models.URLField(max_length=500, validators=[validar_url_webhook_segura], verbose_name="URL de Destino")
    secret = models.CharField(max_length=128, default=uuid.uuid4, verbose_name="Secret para Assinatura HMAC")
    eventos = models.JSONField(
        default=list,
        help_text="Lista de eventos inscritos (ex.: ['fatura.fechada', 'romaneio.concluido'] ou ['*'])"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    descricao = models.CharField(max_length=255, blank=True, default="", verbose_name="Descrição da Integração")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Endpoint de Webhook"
        verbose_name_plural = "Endpoints de Webhook"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Webhook {self.url} [{self.tenant.nome_fantasia}]"


class WebhookDeliveryLog(TenantAwareModel):
    """
    Registro histórico de envios de webhooks para auditoria, outbox transacional e retentativas (D7).
    """
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('FALHA', 'Falha'),
    ]

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='logs', verbose_name="Endpoint")
    evento = models.CharField(max_length=100, verbose_name="Evento")
    payload = models.JSONField(verbose_name="Payload JSON Enviado")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE', verbose_name="Status de Entrega")
    status_code = models.IntegerField(null=True, blank=True, verbose_name="Status HTTP Retornado")
    sucesso = models.BooleanField(default=False, verbose_name="Sucesso na Entrega")
    resposta_body = models.TextField(blank=True, default="", verbose_name="Corpo da Resposta")
    latencia_ms = models.FloatField(null=True, blank=True, verbose_name="Latência (ms)")
    tentativas = models.PositiveIntegerField(default=1, verbose_name="Tentativas")
    enviado_em = models.DateTimeField(default=timezone.now, verbose_name="Enviado em")

    class Meta:
        verbose_name = "Log de Disparo de Webhook"
        verbose_name_plural = "Logs de Disparo de Webhooks"
        ordering = ['-enviado_em']

    def __str__(self):
        status_txt = "OK" if self.sucesso else f"{self.status} ({self.status_code})"
        return f"WebhookLog {self.evento} -> {self.endpoint.url} [{status_txt}]"

