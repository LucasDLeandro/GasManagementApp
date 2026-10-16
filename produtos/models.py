import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.tenancy import TenantAwareModel, TenantQuerySet, TenantManager

# ==============================================================================
# MODELO LEGADO (Preservado para não quebrar funcionalidades existentes)
# ==============================================================================

class Produto(TenantAwareModel):
    CATEGORIA_CHOICES = [
        ('Medicinal', 'Medicinal'),
        ('Industrial', 'Industrial'),
    ]

    UNIDADE_CHOICES = [
        ('m³', 'Metros Cúbicos (m³)'),
        ('kg', 'Quilogramas (kg)'),
        ('litros', 'Litros'),
    ]

    nome = models.CharField(max_length=255, verbose_name="Nome do Gás")
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, verbose_name="Categoria")
    capacidade = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Capacidade")
    unidade_medida = models.CharField(max_length=10, choices=UNIDADE_CHOICES, verbose_name="Unidade de Medida")
    preco = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço de Venda")
    estoque = models.IntegerField(default=0, verbose_name="Quantidade em Estoque")
    codigo_barras = models.CharField(max_length=100, blank=True, null=True, verbose_name="Código de Barras/SKU")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Produto (Legado)"
        verbose_name_plural = "Produtos (Legados)"
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} - {self.capacidade}{self.unidade_medida} ({self.categoria})"


# ==============================================================================
# 1. CATÁLOGO DESACOPLADO
# ==============================================================================

class GasQuimico(models.Model):
    """
    Tabela global de referência técnica e química (independente de Tenant).
    Contém a especificação e classificação do gás conforme normas ABNT e ANVISA.
    """
    CATEGORIA_CHOICES = [
        ('MEDICINAL', 'Medicinal'),
        ('INDUSTRIAL', 'Industrial'),
        ('ALIMENTICIO', 'Alimentício'),
        ('ESPECIAL', 'Especial / Analítico'),
    ]

    nome = models.CharField(max_length=150, verbose_name="Nome do Gás")
    sigla = models.CharField(max_length=20, unique=True, verbose_name="Sigla")
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, verbose_name="Categoria")
    numero_onu = models.CharField(max_length=10, blank=True, verbose_name="Número ONU")
    classe_risco = models.CharField(max_length=10, blank=True, verbose_name="Classe de Risco")
    cor_padrao_abnt = models.CharField(max_length=50, blank=True, verbose_name="Cor Padrão ABNT")
    exige_lote_anvisa = models.BooleanField(default=False, verbose_name="Exige Lote ANVISA")

    class Meta:
        verbose_name = "Gás Químico"
        verbose_name_plural = "Gases Químicos"
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} ({self.sigla}) - {self.get_categoria_display()}"


class ModeloCilindro(TenantAwareModel):
    """
    Especificação física do casco / vaso de pressão (propriedade do Tenant).
    """
    MATERIAL_CHOICES = [
        ('ACO', 'Aço Carbono / Liga'),
        ('ALUMINIO', 'Alumínio'),
    ]

    descricao = models.CharField(max_length=150, verbose_name="Descrição do Modelo")
    material = models.CharField(max_length=20, choices=MATERIAL_CHOICES, default='ACO', verbose_name="Material")
    volume_hidraulico_litros = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="Volume Hidráulico (L)")
    pressao_servico_bar = models.IntegerField(verbose_name="Pressão de Serviço (bar)")
    tara_nominal_kg = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="Tara Nominal (kg)")
    massa_gas_padrao_kg = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('10.00'), null=True, blank=True, verbose_name="Massa de Gás Padrão (kg)")
    padrao_valvula_abnt = models.CharField(max_length=50, blank=True, verbose_name="Padrão Válvula ABNT")
    periodicidade_reteste_anos = models.IntegerField(default=5, verbose_name="Periodicidade do Reteste (Anos)")

    class Meta:
        verbose_name = "Modelo de Cilindro"
        verbose_name_plural = "Modelos de Cilindros"
        ordering = ['descricao']

    def __str__(self):
        return f"{self.descricao} ({self.volume_hidraulico_litros}L - {self.get_material_display()})"


class SkuRecarga(TenantAwareModel):
    """
    Item comercial precificado (Carga de determinado gás para determinado modelo de cilindro).
    """
    UNIDADE_CHOICES = [
        ('m3', 'm³'),
        ('kg', 'kg'),
        ('l', 'Litros'),
    ]

    gas = models.ForeignKey(GasQuimico, on_delete=models.PROTECT, related_name='skus_recarga', verbose_name="Gás Químico")
    modelo_cilindro = models.ForeignKey(ModeloCilindro, on_delete=models.PROTECT, related_name='skus_recarga', verbose_name="Modelo do Cilindro")
    nome_comercial = models.CharField(max_length=200, verbose_name="Nome Comercial")
    quantidade_carga = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Quantidade da Carga")
    unidade = models.CharField(max_length=10, choices=UNIDADE_CHOICES, default='m3', verbose_name="Unidade")
    massa_gas_kg = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="Massa do Gás (kg)")
    preco_base = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço Base")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    class Meta:
        verbose_name = "SKU de Recarga"
        verbose_name_plural = "SKUs de Recargas"
        ordering = ['nome_comercial']

    def __str__(self):
        return f"{self.nome_comercial} - R$ {self.preco_base}"


# ==============================================================================
# 2. RASTREABILIDADE FARMACÊUTICA E ANVISA (LOTES E ENVASES)
# ==============================================================================

class LoteEnvase(TenantAwareModel):
    """
    Lote de envase de gás industrial ou medicinal (em conformidade com RDC nº 658/2022, IN nº 129/2022 e RDC nº 870/2024 - ANVISA).
    Registra pureza físico-química, laudo de análise e prazos regulatórios.
    """
    STATUS_QUALIDADE_CHOICES = [
        ('QUARENTENA', 'Em Quarentena / Análise'),
        ('APROVADO', 'Aprovado pelo CQ/RT'),
        ('REPROVADO', 'Reprovado pelo CQ/RT'),
    ]

    gas = models.ForeignKey(GasQuimico, on_delete=models.PROTECT, related_name='lotes_envase', verbose_name="Gás Químico")
    codigo_lote = models.CharField(max_length=100, db_index=True, verbose_name="Código do Lote")
    status_qualidade = models.CharField(
        max_length=20,
        choices=STATUS_QUALIDADE_CHOICES,
        default='APROVADO',
        db_index=True,
        verbose_name="Status de Qualidade"
    )
    data_envase = models.DateField(verbose_name="Data de Envase")
    data_validade = models.DateField(verbose_name="Data de Validade")
    pureza_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=99.5, verbose_name="Pureza (%)")
    responsavel_tecnico = models.CharField(max_length=150, verbose_name="Responsável Técnico (CRQ/CRF)")
    responsavel_tecnico_fk = models.ForeignKey(
        'core.ResponsavelTecnico',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='lotes_homologados',
        verbose_name="Responsável Técnico Homologador (RT)"
    )
    rt_nome_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome RT (Snapshot)")
    rt_conselho_snapshot = models.CharField(max_length=20, null=True, blank=True, verbose_name="Conselho RT (Snapshot)")
    rt_registro_snapshot = models.CharField(max_length=50, null=True, blank=True, verbose_name="Registro RT (Snapshot)")
    laudo_pdf = models.FileField(upload_to='laudos_lotes/', null=True, blank=True, verbose_name="Laudo de Análise (PDF)")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lote de Envase"
        verbose_name_plural = "Lotes de Envase"
        ordering = ['-data_envase']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'codigo_lote'], name='unique_tenant_lote_codigo')
        ]

    def __str__(self):
        return f"Lote {self.codigo_lote} - {self.gas.sigla} (Val: {self.data_validade.strftime('%d/%m/%Y')})"

    def save(self, *args, **kwargs):
        if self.responsavel_tecnico_fk:
            if not self.rt_nome_snapshot:
                self.rt_nome_snapshot = self.responsavel_tecnico_fk.nome_completo
            if not self.rt_conselho_snapshot:
                self.rt_conselho_snapshot = self.responsavel_tecnico_fk.conselho_classe
            if not self.rt_registro_snapshot:
                self.rt_registro_snapshot = self.responsavel_tecnico_fk.numero_registro
            if not self.responsavel_tecnico:
                self.responsavel_tecnico = f"{self.responsavel_tecnico_fk.nome_completo} ({self.rt_conselho_snapshot} {self.rt_registro_snapshot})"
        super().save(*args, **kwargs)

    @property
    def esta_vencido(self):
        """Retorna True se o prazo de validade do lote expirou."""
        return timezone.now().date() > self.data_validade

    @property
    def expirado(self):
        """Alias para esta_vencido."""
        return self.esta_vencido


# ==============================================================================
# 3. ATIVOS RASTREADOS E LEDGER IMUTÁVEL
# ==============================================================================

class Cilindro(TenantAwareModel):
    """
    Ativo físico rastreado individualmente (vaso de pressão) por QR Code e Número de Série.
    Possui projeção do estado atual e datas de teste hidrostático (INMETRO/ABNT).
    """
    STATUS_CHOICES = [
        ('CHEIO_DISPONIVEL', 'Cheio Disponível no Pátio'),
        ('RESERVADO_ROTA', 'Reservado / Em Rota'),
        ('EM_POSSE_CLIENTE', 'Em Posse do Cliente'),
        ('VAZIO_TRIAGEM', 'Vazio em Triagem'),
        ('EM_ENVASE', 'Em Envase'),
        ('EM_RETESTE', 'Em Reteste / Manutenção'),
        ('BAIXADO', 'Baixado / Condenado'),
        ('EXTRAVIADO', 'Extraviado / Indenização Patrimonial'),
    ]

    PROPRIEDADE_CHOICES = [
        ('DISTRIBUIDORA', 'Patrimônio da Distribuidora'),
        ('PROPRIO', 'Patrimônio Próprio'),
        ('CLIENTE', 'Propriedade do Cliente'),
        ('PARCEIRO', 'Parceiro Comercial'),
        ('TERCEIRO_INTERCAMBIO', 'Terceiro / Intercâmbio'),
    ]

    codigo_qr = models.CharField(max_length=100, db_index=True, verbose_name="Código QR / Barcode")
    numero_serie_ogiva = models.CharField(max_length=100, verbose_name="Número de Série (Ogiva)")
    fabricante = models.CharField(max_length=100, verbose_name="Fabricante")
    ano_fabricacao = models.IntegerField(verbose_name="Ano de Fabricação")

    modelo = models.ForeignKey(ModeloCilindro, on_delete=models.PROTECT, related_name='cilindros', verbose_name="Modelo do Cilindro")
    gas_dedicado = models.ForeignKey(GasQuimico, on_delete=models.PROTECT, related_name='cilindros', verbose_name="Gás Dedicado")

    tara_real_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name="Tara Real Aferida (kg)")
    propriedade = models.CharField(max_length=30, choices=PROPRIEDADE_CHOICES, default='DISTRIBUIDORA', verbose_name="Propriedade")
    cliente_proprietario = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, null=True, blank=True, related_name='cilindros_proprios', verbose_name="Cliente Proprietário")
    is_reserva_tecnica = models.BooleanField(default=False, verbose_name="Cilindro em Reserva Técnica")

    data_ultimo_reteste = models.DateField(verbose_name="Data do Último Reteste")
    data_proximo_reteste = models.DateField(verbose_name="Data do Próximo Reteste")

    # Projeção do estado atual (mantido de forma estrita via produtos/services.py)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='VAZIO_TRIAGEM', verbose_name="Status Atual")
    cliente_posse_atual = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, null=True, blank=True, related_name='cilindros_em_posse', verbose_name="Cliente em Posse Atual")
    posse_desde = models.DateTimeField(null=True, blank=True, verbose_name="Em Posse Desde")

    # Envase Ativo Atual (para validação imediata em expedição sem perda de histórico)
    envase_atual = models.ForeignKey('EnvaseCilindro', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name="Envase Ativo Atual")
    recebimento_externo_atual = models.ForeignKey('RecebimentoCilindroCheio', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name="Recebimento Externo Ativo Atual")

    # Bloqueio Sanitário ANVISA / Quarentena
    bloqueio_sanitario = models.BooleanField(default=False, verbose_name="Bloqueio Sanitário ANVISA")
    motivo_bloqueio_sanitario = models.CharField(max_length=255, null=True, blank=True, verbose_name="Motivo do Bloqueio Sanitário")

    class Meta:
        verbose_name = "Cilindro (Ativo)"
        verbose_name_plural = "Cilindros (Ativos)"
        ordering = ['codigo_qr']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'codigo_qr'], name='unique_tenant_cilindro_qr'),
            models.UniqueConstraint(fields=['tenant', 'fabricante', 'numero_serie_ogiva'], name='unique_tenant_cilindro_serie'),
        ]

    @property
    def reteste_vencido(self):
        """Retorna True se o teste hidrostático ABNT/INMETRO estiver vencido."""
        return timezone.now().date() >= self.data_proximo_reteste

    @property
    def carga_atual(self):
        """Retorna o vínculo de envase próprio ativo ou recebimento externo ativo."""
        return self.envase_atual or self.recebimento_externo_atual

    @property
    def is_propriedade_distribuidora(self):
        """Retorna True se o cilindro pertencer à distribuidora (elegível para demurrage/estadia)."""
        return self.propriedade in ['DISTRIBUIDORA', 'PROPRIO']

    def __str__(self):
        return f"Cilindro {self.numero_serie_ogiva} ({self.codigo_qr}) - {self.gas_dedicado.sigla} [{self.get_status_display()}]"


class EnvaseQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Histórico de envase imutável: registros de envase não podem ser atualizados.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Histórico de envase imutável: registros de envase não podem ser excluídos.")


class EnvaseManager(TenantManager.from_queryset(EnvaseQuerySet)):
    pass


class UnscopedEnvaseQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Histórico de envase imutável: registros de envase não podem ser atualizados.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Histórico de envase imutável: registros de envase não podem ser excluídos.")


class UnscopedEnvaseManager(models.Manager.from_queryset(UnscopedEnvaseQuerySet)):
    pass


class EnvaseCilindro(TenantAwareModel):
    """
    Registro histórico de envase de um cilindro específico com um lote químico determinado.
    Preserva a rastreabilidade completa e perpétua para auditorias ANVISA.
    Imutável (append-only): proíbe edições e exclusões após a criação.
    """
    cilindro = models.ForeignKey(Cilindro, on_delete=models.PROTECT, related_name='historico_envases', verbose_name="Cilindro")
    lote = models.ForeignKey(LoteEnvase, on_delete=models.PROTECT, related_name='cilindros_envasados', verbose_name="Lote de Envase")
    pressao_final_bar = models.PositiveIntegerField(verbose_name="Pressão Final (bar)")
    envasado_em = models.DateTimeField(verbose_name="Envasado Em")
    operador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='envases_operados', verbose_name="Operador do Envase")
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações")

    objects = EnvaseManager()
    unscoped = UnscopedEnvaseManager()

    class Meta:
        verbose_name = "Envase de Cilindro"
        verbose_name_plural = "Histórico de Envases"
        ordering = ['-envasado_em']

    def __str__(self):
        return f"Envase {self.cilindro.numero_serie_ogiva} - Lote {self.lote.codigo_lote} ({self.pressao_final_bar} bar)"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Histórico de envase imutável: registros de envase não podem ser alterados após a criação.")
        if not self.tenant_id:
            if self.cilindro_id and hasattr(self.cilindro, 'tenant_id'):
                self.tenant_id = self.cilindro.tenant_id
            elif self.lote_id and hasattr(self.lote, 'tenant_id'):
                self.tenant_id = self.lote.tenant_id
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Histórico de envase imutável: registros de envase não podem ser excluídos.")


# ==============================================================================
# 2.1 INSPEÇÃO PRÉ-ENVASE (IN 129/2022 - ANVISA)
# ==============================================================================

class InspecaoPreEnvaseQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Inspeção pré-envase imutável: registros não podem ser alterados após a realização.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Inspeção pré-envase imutável: registros não podem ser excluídos.")


class InspecaoPreEnvaseManager(TenantManager.from_queryset(InspecaoPreEnvaseQuerySet)):
    pass


class UnscopedInspecaoQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Inspeção pré-envase imutável: registros não podem ser alterados após a realização.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Inspeção pré-envase imutável: registros não podem ser excluídos.")


class UnscopedInspecaoManager(models.Manager.from_queryset(UnscopedInspecaoQuerySet)):
    pass


class InspecaoPreEnvase(TenantAwareModel):
    """
    Checklist de Inspeção Física Pré-Envase (em conformidade estrita com a IN nº 129/2022 - ANVISA).
    Verificação individual obrigatória antes de qualquer liberação de rampa para envase de gás medicinal.
    Imutável e auditável (append-only).
    """
    cilindro = models.ForeignKey(
        'Cilindro',
        on_delete=models.PROTECT,
        related_name='inspecoes_pre_envase',
        verbose_name="Cilindro Inspecionado"
    )
    operador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='inspecoes_pre_envase_operadas',
        verbose_name="Operador Responsável"
    )

    # Checklist físico regulatório (IN 129/2022)
    valvula_integra = models.BooleanField(
        default=True,
        verbose_name="Válvula Íntegra (sem vazamento, rosca e conexões íntegras)"
    )
    pressao_residual_positiva = models.BooleanField(
        default=True,
        verbose_name="Pressão Residual Positiva (isento de contaminação atmosférica)"
    )
    pintura_cor_padrao_ok = models.BooleanField(
        default=True,
        verbose_name="Pintura e Cor de Identificação Conformes (Norma ABNT)"
    )
    rotulo_identificacao_ok = models.BooleanField(
        default=True,
        verbose_name="Rótulo e Marcação Regulamentar Conformes"
    )

    aprovado = models.BooleanField(
        default=True,
        verbose_name="Aprovado na Inspeção Pré-Envase"
    )
    observacoes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observações Técnicas da Inspeção"
    )
    realizado_em = models.DateTimeField(
        default=timezone.now,
        verbose_name="Data/Hora da Inspeção"
    )

    objects = InspecaoPreEnvaseManager()
    unscoped = UnscopedInspecaoManager()

    class Meta:
        verbose_name = "Inspeção Pré-Envase (Checklist)"
        verbose_name_plural = "Inspeções Pré-Envase (Checklists)"
        ordering = ['-realizado_em']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Inspeção pré-envase imutável: registros não podem ser alterados após a realização.")
        if not (self.valvula_integra and self.pressao_residual_positiva and self.pintura_cor_padrao_ok and self.rotulo_identificacao_ok):
            self.aprovado = False
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Inspeção pré-envase imutável: registros não podem ser excluídos.")

    def __str__(self):
        status_txt = "APROVADO" if self.aprovado else "REPROVADO"
        return f"Inspeção Pré-Envase {self.cilindro.numero_serie_ogiva} [{status_txt}] em {self.realizado_em.strftime('%d/%m/%Y %H:%M')}"


# ==============================================================================
# 2.2 RECEBIMENTO EXTERNO DE FORNECEDORES (RDC 887/2024 - DISTRIBUIDORAS)
# ==============================================================================

class RecebimentoQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Recebimento externo imutável: registros não podem ser atualizados.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Recebimento externo imutável: registros não podem ser excluídos.")


class RecebimentoManager(TenantManager.from_queryset(RecebimentoQuerySet)):
    pass


class UnscopedRecebimentoQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Recebimento externo imutável: registros não podem ser atualizados.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Recebimento externo imutável: registros não podem ser excluídos.")


class UnscopedRecebimentoManager(models.Manager.from_queryset(UnscopedRecebimentoQuerySet)):
    pass


class RecebimentoCilindroCheio(TenantAwareModel):
    """
    Entrada de cilindros cheios adquiridos de fornecedores externos / envasadoras
    (conforme RDC nº 887/2024 e RDC nº 658/2022 - ANVISA).
    Permite que Distribuidoras que não possuem planta de envase própria realizem
    expedição rastreável com vínculo sanitário oficial.
    """
    cilindro = models.ForeignKey(
        'Cilindro',
        on_delete=models.PROTECT,
        related_name='recebimentos_fornecedores',
        verbose_name="Cilindro Recebido"
    )
    fornecedor_nome = models.CharField(max_length=255, verbose_name="Fornecedor / Envasadora de Origem")
    fornecedor_cnpj = models.CharField(max_length=18, verbose_name="CNPJ do Fornecedor")
    nota_fiscal = models.CharField(max_length=60, verbose_name="Nota Fiscal de Entrada")
    lote_fornecedor = models.CharField(max_length=100, db_index=True, verbose_name="Código do Lote do Fornecedor")
    data_envase_origem = models.DateField(verbose_name="Data de Envase na Origem")
    data_validade = models.DateField(verbose_name="Data de Validade do Gás")
    pressao_recebimento_bar = models.PositiveIntegerField(default=200, verbose_name="Pressão no Recebimento (bar)")
    laudo_pdf = models.FileField(upload_to='laudos_fornecedores/', null=True, blank=True, verbose_name="Laudo / Certificado de Análise (PDF)")

    responsavel_recebimento = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recebimentos_operados',
        verbose_name="Operador / Conferente"
    )
    responsavel_tecnico = models.ForeignKey(
        'core.ResponsavelTecnico',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='recebimentos_homologados',
        verbose_name="Responsável Técnico que Conferiu Entrada"
    )
    rt_nome_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome RT (Snapshot)")
    rt_registro_snapshot = models.CharField(max_length=100, null=True, blank=True, verbose_name="Registro RT (Snapshot)")

    recebido_em = models.DateTimeField(default=timezone.now, verbose_name="Recebido em")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações de Entrada")

    objects = RecebimentoManager()
    unscoped = UnscopedRecebimentoManager()

    class Meta:
        verbose_name = "Recebimento de Cilindro Cheio (Fornecedor)"
        verbose_name_plural = "Recebimentos de Cilindros Cheios (Fornecedores)"
        ordering = ['-recebido_em']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Recebimento externo imutável: registros não podem ser atualizados.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Recebimento externo imutável: registros não podem ser excluídos.")

    @property
    def esta_vencido(self):
        return timezone.now().date() > self.data_validade

    def __str__(self):
        return f"Recebimento {self.cilindro.numero_serie_ogiva} - Fornecedor: {self.fornecedor_nome} (Lote: {self.lote_fornecedor})"


class MovimentacaoLedgerQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise PermissionError("Ledger imutável: registros de movimentação não podem ser atualizados.")

    def delete(self, *args, **kwargs):
        raise PermissionError("Ledger imutável: registros de movimentação não podem ser excluídos.")


class MovimentacaoLedgerManager(TenantManager.from_queryset(MovimentacaoLedgerQuerySet)):
    pass


class UnscopedLedgerQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise PermissionError("Ledger imutável: registros de movimentação não podem ser atualizados.")

    def delete(self, *args, **kwargs):
        raise PermissionError("Ledger imutável: registros de movimentação não podem ser excluídos.")


class UnscopedLedgerManager(models.Manager.from_queryset(UnscopedLedgerQuerySet)):
    pass


class MovimentacaoCilindro(TenantAwareModel):
    """
    Livro-razão (Ledger) imutável append-only de movimentações patrimoniais e operacionais de cilindros.
    Proíbe terminantemente operações de UPDATE e DELETE.
    """
    TIPO_CHOICES = [
        ('ENTRADA_ESTOQUE', 'Entrada em Estoque'),
        ('ENVASE', 'Envase'),
        ('SAIDA_ROTA', 'Saída para Rota'),
        ('ENTREGA_CLIENTE', 'Entrega no Cliente'),
        ('RECOLHA_CLIENTE', 'Recolha no Cliente'),
        ('ENVIO_RETESTE', 'Envio para Reteste'),
        ('RETORNO_RETESTE', 'Retorno de Reteste'),
        ('RECLASSIFICACAO', 'Reclassificação'),
        ('BAIXA', 'Baixa Patrimonial'),
        ('ESTORNO', 'Estorno de Movimentação'),
        ('EXTRAVIADO', 'Declaração de Extravio'),
        # Aliases / Operações adicionais
        ('COMPRA', 'Compra / Aquisição de Casco'),
        ('RETORNO_VAZIO', 'Retorno de Casco Vazio'),
        ('SAIDA_ENTREGA', 'Saída para Entrega'),
        ('RESERVA_ROTA', 'Reserva para Rota'),
        ('RECEBIMENTO_FORNECEDOR', 'Recebimento de Cilindro Cheio (Fornecedor)'),
    ]

    cilindro = models.ForeignKey(Cilindro, on_delete=models.PROTECT, related_name='movimentacoes', verbose_name="Cilindro")
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, verbose_name="Tipo de Movimentação")
    status_anterior = models.CharField(max_length=30, verbose_name="Status Anterior")
    status_novo = models.CharField(max_length=30, verbose_name="Status Novo")

    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, null=True, blank=True, related_name='movimentacoes_cilindros', verbose_name="Cliente")
    entrega = models.ForeignKey('logistica.Entrega', on_delete=models.PROTECT, null=True, blank=True, related_name='movimentacoes_cilindros', verbose_name="Entrega")

    ocorrido_em = models.DateTimeField(verbose_name="Ocorrido em")
    registrado_em = models.DateTimeField(auto_now_add=True, verbose_name="Registrado em")
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='movimentacoes_registradas', verbose_name="Registrado por")

    client_uuid = models.UUIDField(default=uuid.uuid4, verbose_name="UUID do Cliente (Idempotência)")
    estorna_movimentacao = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True, related_name='estornada_por', verbose_name="Movimentação Estornada")
    observacao = models.TextField(blank=True, verbose_name="Observação")
    lote_envase = models.CharField(max_length=100, null=True, blank=True, verbose_name="Lote de Envase")

    # Sprint 5A.2 / 5A.3: Vínculo estrito com EnvaseCilindro próprio OU Recebimento externo
    envase_cilindro = models.ForeignKey(
        'EnvaseCilindro',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimentacoes',
        verbose_name="Envase de Origem"
    )
    recebimento_externo = models.ForeignKey(
        'RecebimentoCilindroCheio',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimentacoes',
        verbose_name="Recebimento Externo de Origem"
    )
    documento_fiscal_ref = models.CharField(
        max_length=60,
        null=True,
        blank=True,
        verbose_name="Doc Fiscal / NF-e Ref"
    )
    is_legado = models.BooleanField(
        default=False,
        verbose_name="Registro Legado Anterior"
    )

    objects = MovimentacaoLedgerManager()
    unscoped = UnscopedLedgerManager()

    class Meta:
        verbose_name = "Movimentação de Cilindro (Ledger)"
        verbose_name_plural = "Movimentações de Cilindros (Ledger)"
        ordering = ['-registrado_em']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'client_uuid'], name='unique_tenant_movimentacao_uuid'),
            models.CheckConstraint(
                condition=(
                    models.Q(is_legado=True) |
                    (
                        (
                            models.Q(tipo__in=[
                                'ENVASE',
                                'SAIDA_ROTA',
                                'ENTREGA_CLIENTE',
                                'SAIDA_ENTREGA',
                                'RESERVA_ROTA',
                                'RECEBIMENTO_FORNECEDOR'
                            ]) &
                            (models.Q(envase_cilindro__isnull=False) | models.Q(recebimento_externo__isnull=False))
                        ) |
                        (
                            models.Q(tipo__in=[
                                'RECOLHA_CLIENTE',
                                'ENVIO_RETESTE',
                                'RETORNO_RETESTE',
                                'BAIXA',
                                'ENTRADA_ESTOQUE',
                                'COMPRA',
                                'RETORNO_VAZIO'
                            ]) &
                            models.Q(envase_cilindro__isnull=True) &
                            models.Q(recebimento_externo__isnull=True)
                        ) |
                        models.Q(tipo__in=['RECLASSIFICACAO', 'ESTORNO', 'EXTRAVIADO'])
                    )
                ),
                name='check_movimentacao_envase_coerente'
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Ledger imutável: edições não são permitidas após a criação do registro.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Ledger imutável: registros de movimentação não podem ser excluídos.")

    def __str__(self):
        return f"[{self.tipo}] Cilindro {self.cilindro.numero_serie_ogiva} ({self.status_anterior} -> {self.status_novo}) em {self.registrado_em}"


class VinculoLegadoInferido(TenantAwareModel):
    """
    Tabela auxiliar para mapeamento histórico inferido de movimentações legadas pré-Sprint 5A.2.
    Preserva a imutabilidade do Ledger histórico e não entra no Dossiê de Rastreabilidade oficial.
    """
    movimentacao = models.OneToOneField(
        'MovimentacaoCilindro',
        on_delete=models.CASCADE,
        related_name='vinculo_inferido',
        verbose_name="Movimentação Legada"
    )
    envase_cilindro = models.ForeignKey(
        'EnvaseCilindro',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Envase Inferido"
    )
    justificativa = models.CharField(max_length=255, default="Registro legado anterior à Sprint 5A.2", verbose_name="Justificativa")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Vínculo Legado Inferido"
        verbose_name_plural = "Vínculos Legados Inferidos"

    def __str__(self):
        return f"Vínculo Inferido Movimentação #{self.movimentacao_id} -> Envase #{self.envase_cilindro_id}"


# ==============================================================================
# 4. RECLASSIFICAÇÃO AUDITADA DE GÁS DE CILINDRO
# ==============================================================================

class ReclassificacaoQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Registro de reclassificação imutável: não pode ser alterado após criação.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Registro de reclassificação imutável: não pode ser excluído.")


class ReclassificacaoManager(TenantManager.from_queryset(ReclassificacaoQuerySet)):
    pass


class UnscopedReclassificacaoQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Registro de reclassificação imutável: não pode ser alterado após criação.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Registro de reclassificação imutável: não pode ser excluído.")


class UnscopedReclassificacaoManager(models.Manager.from_queryset(UnscopedReclassificacaoQuerySet)):
    pass


class ReclassificacaoCilindro(TenantAwareModel):
    """
    Registro auditado de conversão e reclassificação de gás dedicado de um cilindro
    (ex.: Industrial para Medicinal, ou vice-versa), conforme diretrizes sanitárias da ANVISA.
    Exige procedimentos técnicos comprovados (descontaminação, purga, troca de válvula, pintura)
    e homologação exclusiva do Responsável Técnico (CRF/CRQ) para gás medicinal.
    """
    cilindro = models.ForeignKey(
        'Cilindro',
        on_delete=models.PROTECT,
        related_name='reclassificacoes',
        verbose_name="Cilindro"
    )
    gas_origem = models.ForeignKey(
        GasQuimico,
        on_delete=models.PROTECT,
        related_name='reclassificacoes_origem',
        verbose_name="Gás de Origem"
    )
    gas_destino = models.ForeignKey(
        GasQuimico,
        on_delete=models.PROTECT,
        related_name='reclassificacoes_destino',
        verbose_name="Novo Gás Dedicado"
    )

    descontaminacao_purga_executada = models.BooleanField(
        default=False,
        verbose_name="Descontaminação e Purga Térmica/Vácuo Executadas"
    )
    troca_valvula_executada = models.BooleanField(
        default=False,
        verbose_name="Substituição da Válvula pelo Padrão ABNT Específico"
    )
    pintura_adequada_abnt = models.BooleanField(
        default=False,
        verbose_name="Repintura na Cor Padrão ABNT Executada"
    )
    laudo_descontaminacao_pdf = models.FileField(
        upload_to='laudos_reclassificacao/',
        null=True,
        blank=True,
        verbose_name="Laudo / Certificado de Descontaminação (PDF)"
    )

    homologado_por_rt = models.ForeignKey(
        'core.ResponsavelTecnico',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='reclassificacoes_homologadas',
        verbose_name="Responsável Técnico Homologador (RT)"
    )
    rt_nome_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome RT (Snapshot)")
    rt_registro_snapshot = models.CharField(max_length=100, null=True, blank=True, verbose_name="Registro RT (Snapshot)")

    executado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reclassificacoes_executadas',
        verbose_name="Executado por"
    )
    realizado_em = models.DateTimeField(default=timezone.now, verbose_name="Realizado em")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações Técnicas")

    objects = ReclassificacaoManager()
    unscoped = UnscopedReclassificacaoManager()

    class Meta:
        verbose_name = "Reclassificação de Gás de Cilindro"
        verbose_name_plural = "Reclassificações de Gás de Cilindros"
        ordering = ['-realizado_em']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Registro de reclassificação imutável: não pode ser alterado após criação.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Registro de reclassificação imutável: não pode ser excluído.")

    def __str__(self):
        return f"Reclassificação {self.cilindro.numero_serie_ogiva}: {self.gas_origem.sigla} -> {self.gas_destino.sigla} em {self.realizado_em.strftime('%d/%m/%Y')}"


# ==============================================================================
# 5. AUDITORIA DE BLOQUEIO SANITÁRIO E CAMPANHAS DE RECALL
# ==============================================================================

class AuditoriaBloqueioQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Trilha de auditoria sanitária imutável: registros não podem ser alterados.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Trilha de auditoria sanitária imutável: registros não podem ser excluídos.")


class AuditoriaBloqueioManager(TenantManager.from_queryset(AuditoriaBloqueioQuerySet)):
    pass


class UnscopedAuditoriaBloqueioQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Trilha de auditoria sanitária imutável: registros não podem ser alterados.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Trilha de auditoria sanitária imutável: registros não podem ser excluídos.")


class UnscopedAuditoriaBloqueioManager(models.Manager.from_queryset(UnscopedAuditoriaBloqueioQuerySet)):
    pass


class AuditoriaBloqueioSanitario(TenantAwareModel):
    """
    Trilha de auditoria regulatória e sanitária (RDC 658/2022 e IN 129/2022).
    Registra cada bloqueio ou liberação sanitária efetuado em um cilindro,
    exigindo justificativa técnica e identificação do Responsável Técnico.
    Imutável (append-only).
    """
    ACAO_CHOICES = [
        ('BLOQUEIO', 'Bloqueio Sanitário'),
        ('DESBLOQUEIO', 'Liberação Sanitária'),
    ]

    cilindro = models.ForeignKey(
        'Cilindro',
        on_delete=models.PROTECT,
        related_name='auditorias_bloqueio',
        verbose_name="Cilindro"
    )
    acao = models.CharField(
        max_length=20,
        choices=ACAO_CHOICES,
        verbose_name="Ação Executada"
    )
    motivo = models.TextField(
        verbose_name="Justificativa Técnica / Motivo Sanitário"
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='bloqueios_sanitarios_executados',
        verbose_name="Usuário Operador"
    )
    responsavel_tecnico = models.ForeignKey(
        'core.ResponsavelTecnico',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='bloqueios_sanitarios_homologados',
        verbose_name="Responsável Técnico Homologador (RT)"
    )
    rt_nome_snapshot = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Nome RT (Snapshot)"
    )
    rt_registro_snapshot = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Registro RT (Snapshot)"
    )
    criado_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Registrado em"
    )

    objects = AuditoriaBloqueioManager()
    unscoped = UnscopedAuditoriaBloqueioManager()

    class Meta:
        verbose_name = "Auditoria de Bloqueio Sanitário"
        verbose_name_plural = "Auditorias de Bloqueio Sanitário"
        ordering = ['-criado_em']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Trilha de auditoria sanitária imutável: registros não podem ser alterados.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Trilha de auditoria sanitária imutável: registros não podem ser excluídos.")

    def __str__(self):
        return f"[{self.acao}] Cilindro {self.cilindro.numero_serie_ogiva} em {self.criado_em.strftime('%d/%m/%Y %H:%M')}"


class RecallCampanha(TenantAwareModel):
    """
    Campanha formal de Recall Sanitário Farmacêutico (ANVISA / IN 129/2022).
    Controla o processo de recolhimento, notificação a hospitais/clientes e
    homologação do Responsável Técnico.
    """
    STATUS_CHOICES = [
        ('ABERTO', 'Aberto / Em Elaboração'),
        ('HOMOLOGADO_RT', 'Homologado pelo RT'),
        ('EM_NOTIFICACAO', 'Em Notificação e Recolhimento'),
        ('CONCLUIDO', 'Concluído'),
        ('CANCELADO', 'Cancelado'),
    ]

    lote = models.ForeignKey(
        LoteEnvase,
        on_delete=models.PROTECT,
        related_name='campanhas_recall',
        verbose_name="Lote de Envase Alvo"
    )
    codigo_campanha = models.CharField(
        max_length=60,
        db_index=True,
        verbose_name="Código da Campanha"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='ABERTO',
        verbose_name="Status da Campanha"
    )
    motivo = models.TextField(
        verbose_name="Motivo / Desvio de Qualidade Detectado"
    )
    texto_notificacao = models.TextField(
        verbose_name="Texto Padrão da Notificação aos Clientes"
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='campanhas_recall_criadas',
        verbose_name="Criado por"
    )
    homologado_por_rt = models.ForeignKey(
        'core.ResponsavelTecnico',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='campanhas_recall_homologadas',
        verbose_name="RT Homologador"
    )
    rt_nome_snapshot = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Nome RT (Snapshot)"
    )
    rt_registro_snapshot = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Registro RT (Snapshot)"
    )
    aberto_em = models.DateTimeField(
        default=timezone.now,
        verbose_name="Data/Hora de Abertura"
    )
    homologado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/Hora da Homologação pelo RT"
    )
    concluido_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/Hora de Conclusão"
    )

    class Meta:
        verbose_name = "Campanha de Recall"
        verbose_name_plural = "Campanhas de Recall"
        ordering = ['-aberto_em']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'codigo_campanha'], name='unique_tenant_campanha_codigo')
        ]

    def __str__(self):
        return f"Recall {self.codigo_campanha} - Lote {self.lote.codigo_lote} [{self.get_status_display()}]"


class ItemRecallCliente(TenantAwareModel):
    """
    Item individual de notificação e recolha por cliente e cilindro em uma campanha de recall.
    Distingue se o cilindro ainda é risco ativo físico (Contenção Ativa) ou se é histórico de exposição passada.
    """
    TIPO_EXPOSICAO_CHOICES = [
        ('CONTENCAO_ATIVA', 'Contenção Ativa (Risco Imediato - Cilindro ainda com carga do lote)'),
        ('EXPOSICAO_PASSADA', 'Exposição Passada (Gás consumido ou cilindro já devolvido vazio)'),
    ]

    STATUS_NOTIFICACAO_CHOICES = [
        ('PENDENTE', 'Notificação Pendente'),
        ('NOTIFICADO', 'Cliente Formalmente Notificado'),
        ('RECOLHIDO', 'Cilindro Físico Recolhido'),
        ('CONSUMIDO_DECLARADO', 'Gás Declarado Consumido pelo Cliente'),
    ]

    campanha = models.ForeignKey(
        RecallCampanha,
        on_delete=models.CASCADE,
        related_name='itens_cliente',
        verbose_name="Campanha de Recall"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.PROTECT,
        related_name='itens_recall',
        verbose_name="Cliente Exposto / Notificado"
    )
    cilindro = models.ForeignKey(
        Cilindro,
        on_delete=models.PROTECT,
        related_name='itens_recall',
        verbose_name="Cilindro"
    )
    envase_cilindro = models.ForeignKey(
        EnvaseCilindro,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='itens_recall',
        verbose_name="Envase Histórico Vinculado"
    )
    tipo_exposicao = models.CharField(
        max_length=30,
        choices=TIPO_EXPOSICAO_CHOICES,
        default='CONTENCAO_ATIVA',
        verbose_name="Tipo de Exposição"
    )
    status_notificacao = models.CharField(
        max_length=30,
        choices=STATUS_NOTIFICACAO_CHOICES,
        default='PENDENTE',
        verbose_name="Status de Notificação / Recolha"
    )
    notificado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Notificado em"
    )
    recolhido_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Recolhido em"
    )
    observacoes = models.TextField(
        blank=True,
        default='',
        verbose_name="Observações do Caso"
    )

    class Meta:
        verbose_name = "Item de Recall por Cliente"
        verbose_name_plural = "Itens de Recall por Cliente"
        ordering = ['cliente__nome', 'cilindro__numero_serie_ogiva']

    def __str__(self):
        return f"Recall #{self.campanha.codigo_campanha} - {self.cliente.nome} - Cilindro {self.cilindro.numero_serie_ogiva} [{self.get_status_notificacao_display()}]"
