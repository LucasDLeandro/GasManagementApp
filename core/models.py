import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from core.tenancy import TenantAwareModel, TenantQuerySet, TenantManager
from core.validators import validar_cnpj

class Tenant(models.Model):
    PLANO_CHOICES = [
        ('STARTER', 'Starter'),
        ('PRO', 'Profissional'),
        ('ENTERPRISE', 'Enterprise'),
    ]

    STATUS_ASSINATURA_CHOICES = [
        ('TRIAL', 'Trial'),
        ('ATIVO', 'Ativo'),
        ('SUSPENSO', 'Suspenso'),
        ('CANCELADO', 'Cancelado'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    razao_social = models.CharField(max_length=255, verbose_name="Razão Social")
    nome_fantasia = models.CharField(max_length=255, verbose_name="Nome Fantasia")
    cnpj = models.CharField(max_length=18, unique=True, verbose_name="CNPJ")
    plano = models.CharField(max_length=20, choices=PLANO_CHOICES, default='STARTER', verbose_name="Plano")

    # Gestão de Assinatura e Cotas (Sprint 7B - v2.0)
    status_assinatura = models.CharField(
        max_length=20,
        choices=STATUS_ASSINATURA_CHOICES,
        default='TRIAL',
        db_index=True,
        verbose_name="Status da Assinatura"
    )
    data_vencimento_licenca = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data de Vencimento da Licença"
    )
    limite_usuarios = models.PositiveIntegerField(
        default=5,
        verbose_name="Limite de Usuários"
    )
    limite_cilindros = models.PositiveIntegerField(
        default=500,
        verbose_name="Limite de Cilindros"
    )
    valor_mensalidade_saas = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor da Mensalidade SaaS"
    )

    # 9 Flags Granulares de Módulos (Sprint 7B)
    modulo_patrimonio_ativo = models.BooleanField(
        default=True,
        verbose_name="Módulo Patrimônio Ativo"
    )
    modulo_comercial_ativo = models.BooleanField(
        default=True,
        verbose_name="Módulo Comercial Ativo"
    )
    modulo_vendas_ativo = models.BooleanField(
        default=True,
        verbose_name="Módulo Vendas Ativo"
    )
    modulo_envase_ativo = models.BooleanField(
        default=False,
        verbose_name="Módulo Envase Ativo"
    )
    modulo_logistica_ativo = models.BooleanField(
        default=True,
        verbose_name="Módulo Logística Ativo"
    )
    modulo_fiscal_ativo = models.BooleanField(
        default=False,
        verbose_name="Módulo Fiscal Ativo"
    )
    modulo_b2b_ativo = models.BooleanField(
        default=False,
        verbose_name="Módulo B2B Ativo"
    )
    modulo_financeiro_ativo = models.BooleanField(
        default=True,
        verbose_name="Módulo Financeiro Ativo"
    )
    modulo_analytics_ativo = models.BooleanField(
        default=False,
        verbose_name="Módulo Analytics Ativo"
    )

    # Lacunas F-29 e F-30
    dias_carencia = models.PositiveIntegerField(
        default=5,
        verbose_name="Dias de Carência"
    )
    motivo_suspensao = models.TextField(
        blank=True,
        default='',
        verbose_name="Motivo da Suspensão"
    )
    data_cancelamento = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data de Cancelamento"
    )
    data_limite_exportacao = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data Limite de Exportação"
    )

    # Parâmetros Fiscais (Sprint 11B - Tarefas 4 e 7)
    presta_servico_transporte = models.BooleanField(
        default=False,
        verbose_name="Presta Serviço de Transporte a Terceiros (Emite CT-e)"
    )
    tratamento_locacao = models.CharField(
        max_length=40,
        choices=[
            ('FATURA_SEM_DOCUMENTO_FISCAL', 'Fatura de Locação sem Documento Fiscal (Não Tributada)'),
            ('NFSE_MUNICIPAL', 'NFS-e Municipal via Gateway'),
        ],
        default='FATURA_SEM_DOCUMENTO_FISCAL',
        verbose_name="Tratamento Fiscal da Fatura de Locação"
    )

    # Sprint 13 - Rollout Controlado & Tenant Piloto (Tarefa 1)
    is_piloto = models.BooleanField(
        default=False,
        verbose_name="Tenant Piloto (Early Access / Beta)"
    )
    flags_piloto = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Feature Flags de Rollout Piloto"
    )

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

    @property
    def perfil_regulatorio_obj(self):
        perfil = getattr(self, 'perfil_regulatorio', None)
        if not perfil:
            from core.models import PerfilRegulatorioTenant
            perfil = PerfilRegulatorioTenant.objects.filter(tenant=self).first()
        return perfil

    @property
    def modo_operacao(self):
        perfil = self.perfil_regulatorio_obj
        return perfil.modo_operacao if perfil else 'MISTO'

    @property
    def tem_modulo_envase(self):
        """Desacoplado comercialmente: depende exclusivamente do flag do módulo no SaaS."""
        return bool(self.modulo_envase_ativo)

    @property
    def tem_modulo_distribuicao(self):
        """Desacoplado comercialmente: depende do módulo de logística e vendas."""
        return bool(self.modulo_logistica_ativo)

    @property
    def is_subscription_active(self):
        """Verifica se a assinatura está apta para uso (TRIAL ou ATIVO)."""
        return self.status_assinatura in ('TRIAL', 'ATIVO')

    @property
    def is_tenant_writable(self):
        """Verifica se o tenant está ativo e com assinatura apta a operações de escrita."""
        return self.ativo and self.is_subscription_active

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

    @property
    def tem_modulo_envase(self):
        return self.modo_operacao in ['ENVASADORA', 'MISTO']

    @property
    def tem_modulo_distribuicao(self):
        return self.modo_operacao in ['DISTRIBUIDORA', 'MISTO']


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


# ==============================================================================
# SPRINT 7A: FUNDAÇÃO TRANSVERSAL (FILIAIS, AUDITORIA, IDEMPOTÊNCIA, JOBS)
# ==============================================================================

from core.audit import AuditedModelMixin


class Filial(AuditedModelMixin, TenantAwareModel):
    """
    Filial ou unidade operacional do Tenant (Sprint 7A - Lacuna F-14).
    Cada tenant possui exatamente uma Matriz (matriz=True).
    """
    nome = models.CharField(max_length=255, verbose_name="Nome da Filial / Unidade")
    cnpj = models.CharField(max_length=18, validators=[validar_cnpj], verbose_name="CNPJ da Filial")
    inscricao_estadual = models.CharField(max_length=30, blank=True, default='ISENTO', verbose_name="Inscrição Estadual")
    uf = models.CharField(max_length=2, verbose_name="UF")
    municipio_ibge = models.CharField(max_length=7, blank=True, null=True, verbose_name="Código IBGE do Município")
    matriz = models.BooleanField(default=False, verbose_name="É Matriz?")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Filial / Unidade"
        verbose_name_plural = "Filiais / Unidades"
        ordering = ['-matriz', 'nome']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant'],
                condition=models.Q(matriz=True),
                name='unique_matriz_por_tenant'
            ),
            models.UniqueConstraint(
                fields=['tenant', 'cnpj'],
                name='unique_tenant_filial_cnpj'
            )
        ]

    def __str__(self):
        tipo = "Matriz" if self.matriz else "Filial"
        return f"{self.nome} ({self.cnpj}) [{tipo}]"


class LogAuditoriaQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaDados é estritamente append-only: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaDados é estritamente append-only: exclusões são proibidas.")


class LogAuditoriaManager(TenantManager.from_queryset(LogAuditoriaQuerySet)):
    pass


class UnscopedLogAuditoriaQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaDados é estritamente append-only: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaDados é estritamente append-only: exclusões são proibidas.")


class UnscopedLogAuditoriaManager(models.Manager.from_queryset(UnscopedLogAuditoriaQuerySet)):
    pass


class LogAuditoriaDados(TenantAwareModel):
    """
    Trilha de auditoria profunda e imutável para dados (Sprint 7A - Lacuna F-33).
    Registra toda criação, alteração, exclusão e estorno com diff serializado em JSON.
    Estritamente append-only: bloqueia UPDATE e DELETE a nível de ORM e de model.
    """
    ACAO_CHOICES = [
        ('CRIACAO', 'Criação'),
        ('ALTERACAO', 'Alteração'),
        ('EXCLUSAO', 'Exclusão'),
        ('ESTORNO', 'Estorno'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logs_auditoria_dados',
        verbose_name="Usuário Responsável"
    )
    content_type = models.ForeignKey(
        'contenttypes.ContentType',
        on_delete=models.PROTECT,
        verbose_name="Tipo de Conteúdo"
    )
    object_id = models.CharField(max_length=255, verbose_name="ID do Objeto")
    acao = models.CharField(max_length=20, choices=ACAO_CHOICES, verbose_name="Ação")
    diff_json = models.JSONField(default=dict, blank=True, verbose_name="Diff das Alterações (JSON)")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="Endereço IP")
    request_id = models.CharField(max_length=64, null=True, blank=True, db_index=True, verbose_name="Request ID")
    timestamp = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Data/Hora do Evento")

    objects = LogAuditoriaManager()
    unscoped = UnscopedLogAuditoriaManager()

    class Meta:
        verbose_name = "Log de Auditoria de Dados"
        verbose_name_plural = "Logs de Auditoria de Dados"
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("LogAuditoriaDados é somente inserção (append-only): alterações são proibidas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaDados é somente inserção (append-only): exclusões são proibidas.")

    def __str__(self):
        usr = self.usuario.username if self.usuario else "Sistema"
        return f"[{self.acao}] {self.content_type.model}#{self.object_id} por {usr} em {self.timestamp.strftime('%d/%m/%Y %H:%M:%S')}"


class IdempotencyKey(TenantAwareModel):
    """
    Controle transacional de idempotência para APIs e Jobs (Sprint 7A).
    Garante que re-execuções de operações não gerem efeitos colaterais duplicados.
    """
    escopo = models.CharField(max_length=100, db_index=True, verbose_name="Escopo da Operação")
    chave = models.CharField(max_length=255, db_index=True, verbose_name="Chave de Idempotência")
    resultado_ref = models.CharField(max_length=255, null=True, blank=True, verbose_name="Referência do Resultado")
    resultado_json = models.JSONField(null=True, blank=True, verbose_name="Payload do Resultado (JSON)")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Chave de Idempotência"
        verbose_name_plural = "Chaves de Idempotência"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'escopo', 'chave'],
                name='unique_tenant_escopo_chave_idempotency'
            )
        ]

    def __str__(self):
        return f"Idempotency [{self.escopo}] {self.chave} ({self.tenant.nome_fantasia})"


class JobExecucao(TenantAwareModel):
    """
    Registro e observabilidade de tarefas assíncronas periódicas e pontuais (Sprint 7A - Correção F-38).
    Permite rastrear status, tempo de execução, retentativas e mensagens de erro por Tenant.
    """
    STATUS_CHOICES = [
        ('INICIADO', 'Iniciado'),
        ('SUCESSO', 'Sucesso'),
        ('FALHA', 'Falha'),
        ('RETRY', 'Em Retry'),
    ]

    nome = models.CharField(max_length=255, db_index=True, verbose_name="Nome do Job / Tarefa")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='INICIADO', verbose_name="Status")
    inicio = models.DateTimeField(default=timezone.now, verbose_name="Início da Execução")
    fim = models.DateTimeField(null=True, blank=True, verbose_name="Fim da Execução")
    duracao_ms = models.IntegerField(null=True, blank=True, verbose_name="Duração (ms)")
    erro = models.TextField(null=True, blank=True, verbose_name="Erro / Stacktrace")
    payload_json = models.JSONField(default=dict, blank=True, verbose_name="Payload / Parâmetros (JSON)")

    class Meta:
        verbose_name = "Execução de Job Assíncrono"
        verbose_name_plural = "Execuções de Jobs Assíncronos"
        ordering = ['-inicio']

    def __str__(self):
        return f"Job {self.nome} [{self.status}] - Tenant {self.tenant.nome_fantasia}"


# ==============================================================================
# 5. GOVERNANÇA SAAS, AUDITORIA SAAS E BREAK-GLASS (Sprint 7B - v2.0)
# ==============================================================================

class LogAuditoriaSaaSQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaSaaS é estritamente append-only: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaSaaS é estritamente append-only: exclusões são proibidas.")


class LogAuditoriaSaaSManager(models.Manager.from_queryset(LogAuditoriaSaaSQuerySet)):
    pass


class LogAuditoriaSaaS(models.Model):
    """
    Trilha de auditoria exclusiva para governança do SaaS v2.0 (somente inserção).
    Registra alterações de status de assinatura, toggles de módulos, cotas e acessos de suporte.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logs_auditoria_saas',
        verbose_name="Tenant"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logs_auditoria_saas_executados',
        verbose_name="Usuário Executor"
    )
    acao = models.CharField(max_length=64, verbose_name="Ação Executada")
    modulo = models.CharField(max_length=64, blank=True, default='', verbose_name="Módulo")
    detalhes_json = models.JSONField(default=dict, blank=True, verbose_name="Detalhes da Operação")
    ip = models.CharField(max_length=64, null=True, blank=True, verbose_name="Endereço IP")
    user_agent = models.CharField(max_length=512, blank=True, default='', verbose_name="User-Agent")
    request_id = models.CharField(max_length=64, null=True, blank=True, verbose_name="Request ID")
    timestamp = models.DateTimeField(default=timezone.now, editable=False, db_index=True, verbose_name="Data/Hora")

    objects = LogAuditoriaSaaSManager()

    class Meta:
        verbose_name = "Log de Auditoria SaaS"
        verbose_name_plural = "Logs de Auditoria SaaS"
        ordering = ['-timestamp']

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._is_persisted = True
        return instance

    def save(self, *args, **kwargs):
        if getattr(self, '_is_persisted', False) or (not self._state.adding and self.pk):
            raise PermissionError("LogAuditoriaSaaS é estritamente append-only: atualizações são proibidas.")
        super().save(*args, **kwargs)
        self._is_persisted = True

    def delete(self, *args, **kwargs):
        raise PermissionError("LogAuditoriaSaaS é estritamente append-only: exclusões são proibidas.")

    def __str__(self):
        tenant_str = self.tenant.nome_fantasia if self.tenant else "Global"
        return f"LogSaaS [{self.acao}] {self.modulo} - {tenant_str} ({self.timestamp:%d/%m/%Y %H:%M})"


class AcessoSuporte(models.Model):
    """
    Registro de Break-Glass para suporte técnico de superusuários em tenants específicos.
    Sessão temporária estrita com expiração em no máximo 30 minutos (Sprint 7B - F-32).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    superadmin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='acessos_suporte_realizados',
        verbose_name="Superusuário"
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='acessos_suporte_recebidos',
        verbose_name="Tenant Acessado"
    )
    motivo = models.TextField(verbose_name="Motivo Justificado do Acesso")
    inicio = models.DateTimeField(default=timezone.now, verbose_name="Início do Acesso")
    expira_em = models.DateTimeField(verbose_name="Expiração do Acesso (máx 30min)")
    encerrado_em = models.DateTimeField(null=True, blank=True, verbose_name="Encerrado em")

    class Meta:
        verbose_name = "Acesso de Suporte (Break-Glass)"
        verbose_name_plural = "Acessos de Suporte (Break-Glass)"
        ordering = ['-inicio']

    @property
    def is_valido(self):
        agora = timezone.now()
        return self.encerrado_em is None and self.inicio <= agora <= self.expira_em

    def __str__(self):
        return f"BreakGlass {self.superadmin} -> {self.tenant.nome_fantasia} (Ativo: {self.is_valido})"


class PlanoSaaS(models.Model):
    """
    Catálogo de Planos Globais do SaaS Baros (Sprint 7B - Lacuna F-29).
    Define preços bases e defaults de módulos habilitados.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=100, unique=True, verbose_name="Nome do Plano")
    preco_base = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Preço Base (R$)"
    )
    limite_usuarios = models.PositiveIntegerField(default=5, verbose_name="Limite de Usuários Padrão")
    limite_cilindros = models.PositiveIntegerField(default=500, verbose_name="Limite de Cilindros Padrão")

    # Módulos ativos por padrão no plano
    modulo_patrimonio_ativo = models.BooleanField(default=True)
    modulo_comercial_ativo = models.BooleanField(default=True)
    modulo_vendas_ativo = models.BooleanField(default=True)
    modulo_envase_ativo = models.BooleanField(default=False)
    modulo_logistica_ativo = models.BooleanField(default=True)
    modulo_fiscal_ativo = models.BooleanField(default=False)
    modulo_b2b_ativo = models.BooleanField(default=False)
    modulo_financeiro_ativo = models.BooleanField(default=True)
    modulo_analytics_ativo = models.BooleanField(default=False)

    ativo = models.BooleanField(default=True, verbose_name="Plano Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Plano SaaS"
        verbose_name_plural = "Planos SaaS"
        ordering = ['preco_base']

    def __str__(self):
        return f"{self.nome} - R$ {self.preco_base}"


class FaturaSaaS(TenantAwareModel):
    """
    Faturas de mensalidade geradas para os tenants (Sprint 7B - Lacuna F-29).
    Cobrança manual no backoffice v2.0 (sem gateway nesta sprint).
    """
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('PAGO', 'Pago'),
        ('VENCIDO', 'Vencido'),
        ('CANCELADO', 'Cancelado'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plano = models.ForeignKey(
        PlanoSaaS,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='faturas',
        verbose_name="Plano Referência"
    )
    competencia = models.DateField(verbose_name="Competência (Mês/Ano)")
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor da Fatura (R$)"
    )
    vencimento = models.DateField(verbose_name="Data de Vencimento")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDENTE',
        db_index=True,
        verbose_name="Status do Pagamento"
    )
    pago_em = models.DateField(null=True, blank=True, verbose_name="Pago em")
    comprovante_ref = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name="Referência / Comprovante"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Fatura SaaS"
        verbose_name_plural = "Faturas SaaS"
        ordering = ['-vencimento']

    def __str__(self):
        return f"Fatura {self.competencia:%m/%Y} - {self.tenant.nome_fantasia} - R$ {self.valor} [{self.status}]"


class SolicitacaoTitularLGPD(TenantAwareModel):
    """
    Registro e controle auditável de solicitações dos titulares de dados pessoais (Sprint 13 - Tarefa 4).
    Em conformidade estrita com os Artigos 16, 18 e 19 da Lei 13.709/2018 (LGPD).
    """
    TIPO_CHOICES = [
        ('ACESSO_EXPORTACAO', 'Acesso e Exportação de Dados Pessoais (Art. 19)'),
        ('ELIMINACAO_ANONIMIZACAO', 'Eliminação / Anonimização de Dados (Art. 16)'),
        ('REVOGACAO_CONSENTIMENTO', 'Revogação de Consentimento (Art. 8º)'),
        ('CONFIRMACAO_TRATAMENTO', 'Confirmação da Existência de Tratamento (Art. 18)'),
    ]

    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente de Análise'),
        ('EM_PROCESSAMENTO', 'Em Processamento'),
        ('CONCLUIDO', 'Concluído'),
        ('NEGADO_REQUISITO_LEGAL', 'Negado por Obrigação Legal/Regulatória (Art. 16, I)'),
    ]

    protocolo = models.CharField(max_length=64, db_index=True, verbose_name="Número de Protocolo")
    tipo = models.CharField(max_length=35, choices=TIPO_CHOICES, verbose_name="Tipo de Solicitação")
    identificador_titular = models.CharField(max_length=150, db_index=True, verbose_name="Identificador do Titular (CPF ou E-mail)")
    nome_titular = models.CharField(max_length=255, blank=True, default='', verbose_name="Nome do Titular")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDENTE', verbose_name="Status da Solicitação")
    justificativa = models.TextField(blank=True, default='', verbose_name="Justificativa da Solicitação / Decisão")
    resultado_json = models.JSONField(default=dict, blank=True, verbose_name="Resultado Estruturado")
    solicitado_em = models.DateTimeField(auto_now_add=True, verbose_name="Solicitado em")
    concluido_em = models.DateTimeField(null=True, blank=True, verbose_name="Concluído em")
    operador_responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitacoes_lgpd_atendidas',
        verbose_name="Operador Responsável"
    )

    class Meta:
        verbose_name = "Solicitação de Titular (LGPD)"
        verbose_name_plural = "Solicitações de Titulares (LGPD)"
        ordering = ['-solicitado_em']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'protocolo'], name='unique_tenant_solicitacao_lgpd_protocolo')
        ]

    def __str__(self):
        return f"Protocolo LGPD #{self.protocolo} - {self.identificador_titular} [{self.get_status_display()}]"


