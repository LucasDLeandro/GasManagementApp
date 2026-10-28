from decimal import Decimal
from django.db import models
from django.conf import settings

from core.tenancy import TenantAwareModel
from clientes.models import Cliente
from produtos.models import GasQuimico


class AlertaOportunidadeComercial(TenantAwareModel):
    """
    Alerta comercial preditivo auditável (Sprint 12C).
    Gera oportunidades comerciais e prevenção de churn com estatística transparente e auditável.
    """
    TIPO_RECOMPRA_ATRASADA = 'RECOMPRA_ATRASADA'
    TIPO_CHURN_RISCO = 'CHURN_RISCO'
    TIPO_CILINDRO_NAO_RETORNA = 'CILINDRO_NAO_RETORNA'
    TIPO_ESTADIA_CRESCENTE = 'ESTADIA_CRESCENTE'
    TIPO_CHOICES = [
        (TIPO_RECOMPRA_ATRASADA, 'Recompra Atrasada'),
        (TIPO_CHURN_RISCO, 'Risco de Churn'),
        (TIPO_CILINDRO_NAO_RETORNA, 'Cilindro com Risco de Não Retorno (Sobrevivência KM)'),
        (TIPO_ESTADIA_CRESCENTE, 'Estadia Excessiva / Crescente'),
    ]

    STATUS_NOVO = 'NOVO'
    STATUS_EM_CONTATO = 'EM_CONTATO'
    STATUS_CONVERTIDO = 'CONVERTIDO'
    STATUS_DESCARTADO = 'DESCARTADO'
    STATUS_CHOICES = [
        (STATUS_NOVO, 'Novo'),
        (STATUS_EM_CONTATO, 'Em Contato'),
        (STATUS_CONVERTIDO, 'Convertido (Recompra Realizada)'),
        (STATUS_DESCARTADO, 'Descartado'),
    ]

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='alertas_oportunidade',
        verbose_name="Cliente"
    )
    gas = models.ForeignKey(
        GasQuimico,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alertas_oportunidade',
        verbose_name="Gás Químico"
    )
    tipo = models.CharField(
        max_length=40,
        choices=TIPO_CHOICES,
        db_index=True,
        verbose_name="Tipo de Alerta"
    )
    score = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal('0.0000'),
        verbose_name="Score / Desvios / Probabilidade"
    )
    evidencia_json = models.JSONField(
        default=dict,
        verbose_name="Evidências Estatísticas Auditáveis (JSON)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NOVO,
        db_index=True,
        verbose_name="Status do Alerta"
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alertas_oportunidade_atribuidos',
        verbose_name="Responsável Comercial"
    )
    data_ref = models.DateField(
        verbose_name="Data de Referência do Cálculo"
    )
    chave_idempotencia = models.CharField(
        max_length=150,
        db_index=True,
        verbose_name="Chave de Idempotência Diária"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    resolvido_em = models.DateTimeField(null=True, blank=True, verbose_name="Resolvido em")
    feedback = models.TextField(blank=True, default='', verbose_name="Feedback da Equipe Comercial")

    class Meta:
        verbose_name = "Alerta de Oportunidade Comercial"
        verbose_name_plural = "Alertas de Oportunidades Comerciais"
        ordering = ['-score', '-criado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'chave_idempotencia'],
                name='unique_alerta_oportunidade_tenant_chave'
            )
        ]

    def __str__(self):
        gas_nome = self.gas.nome if self.gas else "Geral"
        return f"[{self.get_tipo_display()}] {self.cliente.nome} ({gas_nome}) - Score: {self.score} [{self.status}]"
