"""
Modelos do Portal B2B do Cliente Final (Sprint 12B).

Todos os modelos herdam de TenantAwareModel e toda UniqueConstraint inclui o tenant.
Logs e downloads são append-only (auditoria): UPDATE/DELETE levantam PermissionError.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.tenancy import TenantAwareModel, TenantManager, TenantQuerySet


# ==============================================================================
# Infraestrutura append-only (mesmo padrão de LogAuditoriaDados)
# ==============================================================================

class _AppendOnlyMixin:
    def update(self, *args, **kwargs):
        raise PermissionError("Registro de auditoria do portal é append-only: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        raise PermissionError("Registro de auditoria do portal é append-only: exclusões são proibidas.")


class AppendOnlyTenantQuerySet(_AppendOnlyMixin, TenantQuerySet):
    pass


class AppendOnlyUnscopedQuerySet(_AppendOnlyMixin, models.QuerySet):
    pass


class AppendOnlyTenantManager(TenantManager.from_queryset(AppendOnlyTenantQuerySet)):
    pass


class AppendOnlyUnscopedManager(models.Manager.from_queryset(AppendOnlyUnscopedQuerySet)):
    pass


class AppendOnlyModel(TenantAwareModel):
    objects = AppendOnlyTenantManager()
    unscoped = AppendOnlyUnscopedManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError(f"{self.__class__.__name__} é estritamente append-only: atualizações são proibidas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(f"{self.__class__.__name__} é estritamente append-only: exclusões são proibidas.")


# ==============================================================================
# Auditoria de acesso e de download
# ==============================================================================

class LogAcessoB2B(AppendOnlyModel):
    """Trilha de auditoria de acesso ao portal (login, MFA, consultas sensíveis, downloads, reposição)."""
    EVENTO_CHOICES = [
        ('LOGIN_OK', 'Login realizado'),
        ('LOGIN_FALHA', 'Falha de login'),
        ('LOGIN_BLOQUEADO', 'Login negado por bloqueio temporário'),
        ('MFA_OK', 'MFA validada'),
        ('MFA_FALHA', 'Falha de MFA'),
        ('MFA_CONFIGURADA', 'Dispositivo MFA configurado'),
        ('LOGOUT', 'Logout'),
        ('CONSULTA', 'Consulta a recurso'),
        ('LINK_DOWNLOAD', 'URL assinada de download emitida'),
        ('DOWNLOAD', 'Documento baixado'),
        ('DOWNLOAD_NEGADO', 'Download negado (link inválido, expirado ou reutilizado)'),
        ('REPOSICAO', 'Solicitação de reposição'),
        ('ACESSO_NEGADO', 'Acesso negado'),
        ('CONVITE_EMITIDO', 'Convite emitido'),
        ('CONVITE_ACEITO', 'Convite aceito'),
        ('TERMO_ACEITO', 'Termo de uso aceito'),
        ('ACESSO_REVOGADO', 'Acesso revogado'),
    ]

    usuario_b2b = models.ForeignKey(
        'clientes.UsuarioClienteB2B', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='logs_acesso', verbose_name="Usuário B2B"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='logs_acesso_b2b', verbose_name="Cliente"
    )
    usuario_nome = models.CharField(max_length=150, blank=True, default='', verbose_name="Usuário (snapshot)")
    evento = models.CharField(max_length=20, choices=EVENTO_CHOICES, db_index=True, verbose_name="Evento")
    recurso_tipo = models.CharField(max_length=40, blank=True, default='', verbose_name="Tipo do Recurso")
    recurso_id = models.CharField(max_length=60, blank=True, default='', verbose_name="ID do Recurso")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP de Origem")
    user_agent = models.CharField(max_length=255, blank=True, default='', verbose_name="User-Agent")
    request_id = models.CharField(max_length=64, blank=True, default='', verbose_name="Request ID")
    detalhes = models.JSONField(default=dict, blank=True, verbose_name="Detalhes")
    criado_em = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Registrado em")

    class Meta:
        verbose_name = "Log de Acesso B2B"
        verbose_name_plural = "Logs de Acesso B2B"
        ordering = ['-criado_em', '-id']
        indexes = [
            models.Index(fields=['tenant', 'cliente', 'evento']),
            models.Index(fields=['tenant', 'usuario_b2b', 'criado_em']),
        ]

    def __str__(self):
        return f"[{self.evento}] {self.usuario_nome or '-'} {self.recurso_tipo}:{self.recurso_id}"


class DownloadDocumentoB2B(AppendOnlyModel):
    """
    Registro auditável de CADA download de documento (laudo, certificado, DANFE, XML, 2ª via).

    A restrição única (tenant, jti) garante que cada URL assinada seja de uso único:
    uma reutilização falha com IntegrityError e é negada.
    """
    TIPO_CHOICES = [
        ('LAUDO_LOTE', 'Laudo de análise do lote (PDF)'),
        ('CERTIFICADO_ANALISE', 'Certificado de análise (PDF)'),
        ('LAUDO_FORNECEDOR', 'Laudo do fornecedor do cilindro cheio (PDF)'),
        ('BOLETO_2VIA', '2ª via de boleto'),
        ('PIX_2VIA', '2ª via de PIX'),
        ('DANFE', 'DANFE'),
        ('XML_NFE', 'XML da NF-e'),
    ]

    usuario_b2b = models.ForeignKey(
        'clientes.UsuarioClienteB2B', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='downloads', verbose_name="Usuário B2B"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente', on_delete=models.PROTECT, related_name='downloads_b2b', verbose_name="Cliente"
    )
    tipo_documento = models.CharField(max_length=24, choices=TIPO_CHOICES, db_index=True, verbose_name="Tipo de Documento")
    recurso_tipo = models.CharField(max_length=40, verbose_name="Tipo do Recurso de Origem")
    recurso_id = models.CharField(max_length=60, verbose_name="ID do Recurso de Origem")
    jti = models.UUIDField(default=uuid.uuid4, verbose_name="Identificador Único da URL Assinada")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP de Origem")
    user_agent = models.CharField(max_length=255, blank=True, default='', verbose_name="User-Agent")
    hash_conteudo = models.CharField(max_length=64, blank=True, default='', verbose_name="SHA-256 do Conteúdo Entregue")
    tamanho_bytes = models.PositiveBigIntegerField(default=0, verbose_name="Tamanho (bytes)")
    criado_em = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Baixado em")

    class Meta:
        verbose_name = "Download de Documento B2B"
        verbose_name_plural = "Downloads de Documentos B2B"
        ordering = ['-criado_em', '-id']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'jti'], name='unique_tenant_download_b2b_jti'),
        ]
        indexes = [
            models.Index(fields=['tenant', 'cliente', 'tipo_documento']),
        ]

    def __str__(self):
        return f"{self.tipo_documento} {self.recurso_tipo}:{self.recurso_id} por {self.usuario_b2b_id}"


# ==============================================================================
# Convites
# ==============================================================================

class ConviteB2B(TenantAwareModel):
    """
    Convite por e-mail para ativação de um usuário do portal. O token em claro nunca é
    persistido: apenas seu SHA-256. Uso único e com validade (B2B_INVITE_VALID_HOURS).
    """
    usuario_b2b = models.ForeignKey(
        'clientes.UsuarioClienteB2B', on_delete=models.CASCADE, related_name='convites', verbose_name="Usuário B2B"
    )
    email_destino = models.EmailField(verbose_name="E-mail de Destino")
    token_hash = models.CharField(max_length=64, db_index=True, verbose_name="SHA-256 do Token")
    expira_em = models.DateTimeField(verbose_name="Expira em")
    aceito_em = models.DateTimeField(null=True, blank=True, verbose_name="Aceito em")
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name="Emitido por"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Convite B2B"
        verbose_name_plural = "Convites B2B"
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'token_hash'], name='unique_tenant_convite_b2b_token'),
        ]

    def __str__(self):
        return f"Convite {self.email_destino} (expira {self.expira_em:%d/%m/%Y %H:%M})"

    @property
    def esta_valido(self) -> bool:
        return self.aceito_em is None and self.expira_em > timezone.now()


# ==============================================================================
# Reposição em 1 clique
# ==============================================================================

class SolicitacaoReposicao(TenantAwareModel):
    """
    Pedido de reposição pré-validado disparado no portal. Idempotente por
    (tenant, cliente, chave_idempotencia): a mesma chave nunca cria dois pedidos.
    """
    STATUS_CHOICES = [
        ('CRIADA', 'Criada — na fila comercial'),
        ('BLOQUEADA_CREDITO', 'Registrada — retida pelo crédito (análise financeira)'),
    ]

    cliente = models.ForeignKey(
        'clientes.Cliente', on_delete=models.PROTECT, related_name='solicitacoes_reposicao', verbose_name="Cliente"
    )
    usuario_b2b = models.ForeignKey(
        'clientes.UsuarioClienteB2B', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='solicitacoes_reposicao', verbose_name="Solicitante"
    )
    chave_idempotencia = models.CharField(max_length=100, verbose_name="Chave de Idempotência")
    payload_hash = models.CharField(max_length=64, verbose_name="SHA-256 do Conteúdo Solicitado")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CRIADA', db_index=True)
    avaliacao_credito = models.CharField(max_length=30, blank=True, default='', verbose_name="Resultado da Avaliação de Crédito")
    motivos_credito = models.JSONField(default=list, blank=True, verbose_name="Motivos da Avaliação de Crédito")
    alerta_assistencial = models.BooleanField(default=False, verbose_name="Alerta Assistencial (gás medicinal/hospital)")
    itens = models.JSONField(default=list, verbose_name="Itens Solicitados (snapshot com preço aplicado)")
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Total (R$)")
    venda = models.OneToOneField(
        'vendas.Venda', null=True, blank=True, on_delete=models.PROTECT,
        related_name='solicitacao_reposicao_b2b', verbose_name="Pedido Gerado"
    )
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações do Cliente")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Solicitação de Reposição B2B"
        verbose_name_plural = "Solicitações de Reposição B2B"
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'cliente', 'chave_idempotencia'],
                name='unique_tenant_cliente_reposicao_chave'
            ),
            models.CheckConstraint(
                condition=models.Q(valor_total__gte=Decimal('0.00')),
                name='chk_reposicao_valor_nao_negativo'
            ),
        ]

    def __str__(self):
        return f"Reposição #{self.pk} - cliente {self.cliente_id} [{self.status}]"


# ==============================================================================
# Notificações
# ==============================================================================

class NotificacaoB2B(TenantAwareModel):
    """
    Notificação ativa ao cliente (reteste, estadia crescente, boleto a vencer).
    Canais externos só são usados com consentimento LGPD ativo (ConsentimentoContato);
    sem consentimento, a notificação existe apenas dentro do portal (canal PORTAL).
    """
    TIPO_CHOICES = [
        ('RETESTE_VENCENDO', 'Reteste hidrostático próximo do vencimento'),
        ('ESTADIA_CRESCENTE', 'Estadia de cilindro crescente'),
        ('BOLETO_A_VENCER', 'Boleto a vencer'),
    ]
    CANAL_CHOICES = [
        ('PORTAL', 'Somente no portal'),
        ('EMAIL', 'E-mail'),
        ('WHATSAPP', 'WhatsApp'),
    ]
    STATUS_CHOICES = [
        ('REGISTRADA', 'Registrada (exibida no portal)'),
        ('ENVIADA', 'Enviada'),
        ('ENFILEIRADA', 'Enfileirada para o despachante do canal'),
        ('SEM_DESTINATARIO', 'Sem destinatário cadastrado no canal'),
        ('FALHA', 'Falha no envio'),
    ]

    cliente = models.ForeignKey(
        'clientes.Cliente', on_delete=models.CASCADE, related_name='notificacoes_b2b', verbose_name="Cliente"
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, db_index=True)
    canal = models.CharField(max_length=10, choices=CANAL_CHOICES)
    destinatario = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='REGISTRADA', db_index=True)
    chave = models.CharField(max_length=150, verbose_name="Chave de Idempotência do Evento")
    titulo = models.CharField(max_length=200)
    mensagem = models.TextField()
    recurso_tipo = models.CharField(max_length=40, blank=True, default='')
    recurso_id = models.CharField(max_length=60, blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Notificação B2B"
        verbose_name_plural = "Notificações B2B"
        ordering = ['-criado_em', '-id']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'canal', 'chave'], name='unique_tenant_notificacao_b2b_canal_chave'),
        ]
        indexes = [
            models.Index(fields=['tenant', 'cliente', 'tipo']),
        ]

    def __str__(self):
        return f"{self.tipo} -> {self.canal} ({self.status})"
