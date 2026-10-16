from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from core.tenancy import TenantAwareModel, TenantQuerySet, TenantManager

class Cliente(TenantAwareModel):
    TIPO_CLIENTE_CHOICES = [
        ('PJ', 'Pessoa Jurídica (Privada)'),
        ('GOV', 'Governamental'),
    ]

    tipo_cliente = models.CharField(max_length=10, choices=TIPO_CLIENTE_CHOICES, default='PJ', verbose_name="Tipo de Cliente")
    cnpj = models.CharField(max_length=18, verbose_name="CNPJ")
    nome = models.CharField(max_length=255, verbose_name="Razão Social / Nome")
    nome_fantasia = models.CharField(max_length=255, blank=True, null=True, verbose_name="Nome Fantasia")
    endereco = models.TextField(verbose_name="Logradouro / Endereço")
    numero = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número")
    bairro = models.CharField(max_length=100, blank=True, null=True, verbose_name="Bairro")
    complemento = models.CharField(max_length=100, blank=True, null=True, verbose_name="Complemento")
    cidade = models.CharField(max_length=255, verbose_name="Cidade")
    estado = models.CharField(max_length=2, verbose_name="Estado (UF)")
    cep = models.CharField(max_length=10, blank=True, null=True, verbose_name="CEP")
    telefone = models.CharField(max_length=20, verbose_name="Telefone")
    email_financeiro = models.EmailField(max_length=255, blank=True, null=True, verbose_name="E-mail Financeiro")
    proprietario = models.CharField(max_length=255, verbose_name="Responsável / Proprietário")
    is_medicinal = models.BooleanField(default=False, verbose_name="Cliente de Gás Medicinal")
    cnes_licenca_sanitaria = models.CharField(max_length=50, blank=True, null=True, verbose_name="CNES / Licença Sanitária")
    cliente_matriz = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='filiais',
        verbose_name="Cliente Matriz"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'cnpj'], name='unique_tenant_cliente_cnpj')
        ]

    def __str__(self):
        return f"{self.nome} - {self.cnpj}"

    @property
    def contrato_comodato(self):
        """
        Retorna o contrato de comodato/estadia ativo do cliente.
        Preserva compatibilidade com código que acessava o antigo OneToOneField.
        """
        hoje = timezone.now().date()
        contrato_vigente = self.contratos_comodato.filter(
            models.Q(vigencia_fim__isnull=True) | models.Q(vigencia_fim__gte=hoje),
            vigencia_inicio__lte=hoje
        ).order_by('-vigencia_inicio').first()

        if not contrato_vigente:
            # Fallback para o mais recente registrado
            contrato_vigente = self.contratos_comodato.order_by('-vigencia_inicio').first()
        return contrato_vigente


class ContratoComodato(TenantAwareModel):
    CRITERIO_FRANQUIA_CHOICES = [
        ('FIFO', 'FIFO (Primeiro a Entrar, Primeiro a Isentar)'),
        ('LIFO', 'LIFO (Último a Entrar, Primeiro a Isentar)'),
    ]

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='contratos_comodato',
        verbose_name="Cliente"
    )
    vigencia_inicio = models.DateField(
        default=timezone.now,
        verbose_name="Início da Vigência"
    )
    vigencia_fim = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fim da Vigência"
    )
    criterio_franquia = models.CharField(
        max_length=10,
        choices=CRITERIO_FRANQUIA_CHOICES,
        default='FIFO',
        verbose_name="Critério de Franquia"
    )
    agrupar_franquia_filiais = models.BooleanField(
        default=True,
        verbose_name="Agrupar Franquia entre Filiais"
    )
    dias_limite_extravio = models.PositiveIntegerField(
        default=180,
        verbose_name="Dias Limite para Extravio"
    )

    # Defaults / fallback caso o modelo do cilindro não possua FranquiaModeloContrato específica
    franquia_cilindros_isentos = models.PositiveIntegerField(
        default=0,
        verbose_name="Franquia de Cilindros Isentos (Padrão)"
    )
    dias_carencia_giro = models.PositiveIntegerField(
        default=30,
        verbose_name="Dias de Carência de Giro (Padrão)"
    )
    valor_diaria_excedente = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('3.50'),
        verbose_name="Valor Diária Excedente (R$) (Padrão)"
    )
    custo_reposicao_casco = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1800.00'),
        verbose_name="Custo de Reposição do Casco (R$) (Padrão)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato de Comodato e Estadia"
        verbose_name_plural = "Contratos de Comodato e Estadia"
        ordering = ['-vigencia_inicio']

    def __str__(self):
        return (
            f"Contrato Comodato - {self.cliente.nome} "
            f"({self.vigencia_inicio.strftime('%d/%m/%Y')} a "
            f"{self.vigencia_fim.strftime('%d/%m/%Y') if self.vigencia_fim else 'Indeterminado'}) "
            f"[{self.criterio_franquia}]"
        )

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.cliente_id:
            try:
                self.tenant_id = self.cliente.tenant_id
            except Exception:
                pass
        super().save(*args, **kwargs)


class FranquiaModeloContrato(TenantAwareModel):
    """
    Parametrização de franquia, carência de giro e taxas diárias por Modelo de Cilindro
    vinculado ao contrato versionado do cliente (Seção 3.1 - Sprint 5B.1).
    """
    contrato = models.ForeignKey(
        ContratoComodato,
        on_delete=models.CASCADE,
        related_name='franquias_modelo',
        verbose_name="Contrato de Comodato"
    )
    modelo = models.ForeignKey(
        'produtos.ModeloCilindro',
        on_delete=models.PROTECT,
        related_name='franquias_contrato',
        verbose_name="Modelo do Cilindro"
    )
    franquia_cilindros_isentos = models.PositiveIntegerField(
        default=0,
        verbose_name="Franquia de Cilindros Isentos"
    )
    dias_carencia_giro = models.PositiveIntegerField(
        default=30,
        verbose_name="Dias de Carência de Giro (dias)"
    )
    taxa_diaria = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('3.50'),
        verbose_name="Taxa Diária Excedente (R$)"
    )
    valor_reposicao_extravio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1800.00'),
        verbose_name="Valor de Reposição por Extravio (R$)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Franquia por Modelo (Contrato)"
        verbose_name_plural = "Franquias por Modelos (Contratos)"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'contrato', 'modelo'],
                name='unique_tenant_contrato_modelo_franquia'
            )
        ]

    def __str__(self):
        return (
            f"Franquia {self.modelo.descricao} no {self.contrato}: "
            f"Isentos: {self.franquia_cilindros_isentos}, Carência: {self.dias_carencia_giro}d, "
            f"Taxa: R$ {self.taxa_diaria}/dia"
        )

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.contrato_id:
            try:
                self.tenant_id = self.contrato.tenant_id
            except Exception:
                pass
        super().save(*args, **kwargs)


class DiaCilindro(TenantAwareModel):
    """
    Tabela derivada e auditável que consolida a posição de posse diária de cada cilindro
    reconstruída exclusivamente a partir do Ledger imutável (MovimentacaoCilindro)
    conforme Seção 3.1 do Plano Consolidado v5.
    """
    CLASSE_COBRANCA_CHOICES = [
        ('ISENTO_CARENCIA', 'Isento por Carência Individual de Giro'),
        ('ISENTO_FRANQUIA', 'Isento pela Franquia Contratual do Modelo'),
        ('ISENTO_RESERVA', 'Isento por Reserva Técnica Homologada'),
        ('NAO_COBRAVEL_PROPRIEDADE', 'Não Cobrável por Propriedade (Cliente/Terceiro)'),
        ('COBRAVEL', 'Cobrável (Taxa Diária de Estadia Excedente)'),
    ]

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='diarias_posse',
        verbose_name="Cliente"
    )
    cilindro = models.ForeignKey(
        'produtos.Cilindro',
        on_delete=models.CASCADE,
        related_name='diarias_posse',
        verbose_name="Cilindro"
    )
    data_referencia = models.DateField(
        db_index=True,
        verbose_name="Data de Referência (D)"
    )
    data_entrega = models.DateField(
        verbose_name="Data de Início da Posse Contínua"
    )
    idade_posse_dias = models.PositiveIntegerField(
        verbose_name="Idade da Posse em Dias"
    )
    classe_cobranca = models.CharField(
        max_length=35,
        choices=CLASSE_COBRANCA_CHOICES,
        verbose_name="Classe de Cobrança"
    )
    valor_diaria = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor da Diária (R$)"
    )
    contrato_versao = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name="Versão do Contrato"
    )
    algoritmo_versao = models.CharField(
        max_length=20,
        default='5B.1',
        verbose_name="Versão do Algoritmo"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Diária de Cilindro (Posse/Estadia)"
        verbose_name_plural = "Diárias de Cilindros (Posse/Estadia)"
        ordering = ['data_referencia', 'cliente', 'cilindro']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'cliente', 'cilindro', 'data_referencia'],
                name='unique_tenant_cliente_cilindro_data_ref'
            )
        ]
        indexes = [
            models.Index(fields=['tenant', 'data_referencia', 'cliente']),
            models.Index(fields=['tenant', 'classe_cobranca']),
        ]

    def __str__(self):
        return (
            f"DiaCilindro {self.cilindro.numero_serie_ogiva} em {self.data_referencia.strftime('%d/%m/%Y')} "
            f"({self.cliente.nome}): {self.classe_cobranca} - R$ {self.valor_diaria} (Idade: {self.idade_posse_dias}d)"
        )

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            if self.cliente_id:
                self.tenant_id = self.cliente.tenant_id
            elif self.cilindro_id:
                self.tenant_id = self.cilindro.tenant_id
        super().save(*args, **kwargs)


class FechamentoFaturaQuerySet(TenantQuerySet):
    def update(self, **kwargs):
        raise ValidationError("Atualizações em lote de faturas de estadia são terminantemente proibidas para garantir imutabilidade fiscal.")

    def delete(self):
        raise ValidationError("Exclusões em lote de faturas de estadia são proibidas.")


class FechamentoFaturaManager(TenantManager.from_queryset(FechamentoFaturaQuerySet)):
    pass


class ItemFaturaQuerySet(TenantQuerySet):
    def update(self, **kwargs):
        raise ValidationError("Atualizações em lote de itens de fatura de estadia são terminantemente proibidas.")

    def delete(self):
        raise ValidationError("Exclusões em lote de itens de fatura de estadia são proibidas.")


class ItemFaturaManager(TenantManager.from_queryset(ItemFaturaQuerySet)):
    pass


class FechamentoFaturaEstadia(TenantAwareModel):
    """
    Snapshot imutável de fechamento financeiro de fatura de estadia/locação por competência (mês/ano).
    Conforme ADR-001 e Sprint 5B.2: uma vez fechada (status FECHADA ou PAGA), a fatura torna-se
    rigorosamente imutável contra alterações de valores e exclusão.
    """
    STATUS_CHOICES = [
        ('ABERTA', 'Aberta / Em Medição'),
        ('FECHADA', 'Fechada (Aguardando Pagamento)'),
        ('PAGA', 'Paga / Conciliada'),
        ('CANCELADA', 'Cancelada'),
    ]

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name='faturas_estadia',
        verbose_name="Cliente"
    )
    competencia_ano_mes = models.CharField(
        max_length=7,
        db_index=True,
        verbose_name="Competência (AAAA-MM)"
    )
    data_fechamento = models.DateTimeField(
        default=timezone.now,
        verbose_name="Data de Fechamento"
    )
    valor_bruto_diarias = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor Bruto das Diárias (R$)"
    )
    valor_desconto_carencia = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Desconto por Carência (R$)"
    )
    valor_desconto_franquia = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Desconto por Franquia (R$)"
    )
    valor_ajustes_retroativos = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Ajustes Retroativos (R$)"
    )
    valor_reposicao_extravios = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Reposição por Extravio (R$)"
    )
    valor_liquido_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor Líquido Total (R$)"
    )
    status_pagamento = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='FECHADA',
        verbose_name="Status do Pagamento"
    )
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='faturas_estadia_fechadas',
        verbose_name="Fechado por"
    )
    observacoes = models.TextField(
        blank=True,
        default='',
        verbose_name="Observações"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = FechamentoFaturaManager()

    class Meta:
        verbose_name = "Fechamento de Fatura de Estadia"
        verbose_name_plural = "Fechamentos de Faturas de Estadia"
        ordering = ['-competencia_ano_mes', 'cliente']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'cliente', 'competencia_ano_mes'],
                name='unique_tenant_cliente_competencia_fatura'
            )
        ]
        indexes = [
            models.Index(fields=['tenant', 'competencia_ano_mes']),
            models.Index(fields=['tenant', 'status_pagamento']),
        ]

    def __str__(self):
        return f"Fatura {self.competencia_ano_mes} - {self.cliente.nome} ({self.status_pagamento}): R$ {self.valor_liquido_total}"

    def delete(self, *args, **kwargs):
        if self.status_pagamento in ['FECHADA', 'PAGA']:
            raise ValidationError("Fatura fechada é imutável e não pode ser excluída.")
        super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.cliente_id:
            self.tenant_id = self.cliente.tenant_id

        if not self._state.adding and self.pk:
            orig = FechamentoFaturaEstadia.objects.filter(pk=self.pk).values(
                'status_pagamento', 'valor_liquido_total', 'valor_bruto_diarias',
                'valor_ajustes_retroativos', 'valor_reposicao_extravios', 'competencia_ano_mes',
                'cliente_id', 'tenant_id'
            ).first()
            if orig and orig['status_pagamento'] in ['FECHADA', 'PAGA']:
                if (orig['competencia_ano_mes'] != self.competencia_ano_mes or
                    orig['cliente_id'] != self.cliente_id or
                    orig['tenant_id'] != self.tenant_id or
                    orig['valor_bruto_diarias'] != self.valor_bruto_diarias or
                    orig['valor_ajustes_retroativos'] != self.valor_ajustes_retroativos or
                    orig['valor_reposicao_extravios'] != self.valor_reposicao_extravios or
                    orig['valor_liquido_total'] != self.valor_liquido_total):
                    raise ValidationError("Fatura fechada é imutável. Valores e competência não podem ser alterados.")
        super().save(*args, **kwargs)


class ItemFaturaEstadia(TenantAwareModel):
    """
    Linha analítica da fatura de estadia, discriminando por cilindro os dias
    em posse no mês e a respectiva classificação/cobrança.
    """
    fatura = models.ForeignKey(
        FechamentoFaturaEstadia,
        on_delete=models.PROTECT,
        related_name='itens',
        verbose_name="Fatura de Fechamento"
    )
    cilindro = models.ForeignKey(
        'produtos.Cilindro',
        on_delete=models.PROTECT,
        related_name='itens_fatura_estadia',
        verbose_name="Cilindro"
    )
    modelo_cilindro = models.CharField(
        max_length=60,
        verbose_name="Modelo do Cilindro"
    )
    periodo_inicio = models.DateField(
        verbose_name="Início do Período no Mês"
    )
    periodo_fim = models.DateField(
        verbose_name="Fim do Período no Mês"
    )
    dias_posse_mes = models.PositiveIntegerField(
        default=0,
        verbose_name="Dias em Posse no Mês"
    )
    dias_carencia = models.PositiveIntegerField(
        default=0,
        verbose_name="Dias Isentos por Carência"
    )
    dias_franquia = models.PositiveIntegerField(
        default=0,
        verbose_name="Dias Isentos por Franquia"
    )
    dias_reserva_tecnica = models.PositiveIntegerField(
        default=0,
        verbose_name="Dias Isentos por Reserva Técnica"
    )
    dias_cobraveis = models.PositiveIntegerField(
        default=0,
        verbose_name="Dias Cobráveis"
    )
    diaria_aplicada = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Diária Aplicada (R$)"
    )
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Subtotal (R$)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = ItemFaturaManager()

    class Meta:
        verbose_name = "Item de Fatura de Estadia"
        verbose_name_plural = "Itens de Fatura de Estadia"
        ordering = ['fatura', 'modelo_cilindro', 'cilindro']

    def __str__(self):
        return (
            f"Item {self.cilindro.numero_serie_ogiva} ({self.modelo_cilindro}): "
            f"{self.dias_cobraveis}d cobráveis x R$ {self.diaria_aplicada} = R$ {self.subtotal}"
        )

    def delete(self, *args, **kwargs):
        raise ValidationError("Itens de fatura de estadia são imutáveis e não podem ser excluídos.")

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk:
            raise ValidationError("Itens de fatura de estadia são estritamente imutáveis.")
        if not self.tenant_id and self.fatura_id:
            self.tenant_id = self.fatura.tenant_id
        super().save(*args, **kwargs)


class AjusteCompetenciaEstadia(TenantAwareModel):
    """
    Registra ajustes financeiros (crédito ou débito) gerados por movimentações retroativas
    (ex.: recolha/estorno pós-fechamento via sync offline tardio).
    Conforme Caso de Ouro #7 / ADR-001: a fatura fechada NUNCA é alterada; o ajuste
    é gerado e abatido/acrescido no próximo FechamentoFaturaEstadia aberto do cliente.
    """
    TIPO_CHOICES = [
        ('CREDITO', 'Crédito ao Cliente (Redução de Valor)'),
        ('DEBITO', 'Débito ao Cliente (Acréscimo de Valor)'),
    ]

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='ajustes_estadia',
        verbose_name="Cliente"
    )
    fatura_origem = models.ForeignKey(
        FechamentoFaturaEstadia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ajustes_gerados',
        verbose_name="Fatura de Origem Fechada"
    )
    fatura_compensacao = models.ForeignKey(
        FechamentoFaturaEstadia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ajustes_compensados',
        verbose_name="Fatura Onde Foi Compensado"
    )
    competencia_afetada = models.CharField(
        max_length=7,
        db_index=True,
        verbose_name="Competência Afetada (AAAA-MM)"
    )
    tipo_ajuste = models.CharField(
        max_length=10,
        choices=TIPO_CHOICES,
        verbose_name="Tipo de Ajuste"
    )
    valor_ajuste = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Valor do Ajuste (R$)"
    )
    motivo = models.TextField(
        verbose_name="Motivo do Ajuste"
    )
    movimentacao_ref = models.ForeignKey(
        'produtos.MovimentacaoCilindro',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ajustes_estadia_gerados',
        verbose_name="Movimentação de Referência"
    )
    compensado = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Compensado em Fatura Posterior"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ajuste de Competência de Estadia"
        verbose_name_plural = "Ajustes de Competência de Estadia"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Ajuste {self.tipo_ajuste} R$ {self.valor_ajuste} ({self.competencia_afetada}) - {self.cliente.nome}"

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.cliente_id:
            self.tenant_id = self.cliente.tenant_id
        super().save(*args, **kwargs)


class ExtravioCilindroRegistro(TenantAwareModel):
    """
    Registro formal de extravio e reposição patrimonial de cilindro (Caso de Ouro #9).
    Restrito a GERENTE ou ADMIN.
    """
    cilindro = models.ForeignKey(
        'produtos.Cilindro',
        on_delete=models.PROTECT,
        related_name='registros_extravio',
        verbose_name="Cilindro Extraviado"
    )
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name='extravios_registrados',
        verbose_name="Cliente Responsável"
    )
    data_extravio = models.DateField(
        verbose_name="Data do Extravio Declarado"
    )
    dias_em_posse_sem_giro = models.PositiveIntegerField(
        default=0,
        verbose_name="Dias em Posse sem Giro"
    )
    valor_reposicao = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Valor de Reposição Patrimonial (R$)"
    )
    justificativa = models.TextField(
        verbose_name="Justificativa do Extravio"
    )
    declarado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='extravios_declarados',
        verbose_name="Declarado por"
    )
    fatura_cobranca = models.ForeignKey(
        FechamentoFaturaEstadia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_extravio',
        verbose_name="Fatura de Cobrança"
    )
    cobrado = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Cobrado em Fatura"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Registro de Extravio de Cilindro"
        verbose_name_plural = "Registros de Extravio de Cilindros"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Extravio {self.cilindro.numero_serie_ogiva} - {self.cliente.nome}: R$ {self.valor_reposicao}"

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            if self.cliente_id:
                self.tenant_id = self.cliente.tenant_id
            elif self.cilindro_id:
                self.tenant_id = self.cilindro.tenant_id
        super().save(*args, **kwargs)

