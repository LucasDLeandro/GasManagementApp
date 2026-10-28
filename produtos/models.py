import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.money import quantize
from core.tenancy import TenantAwareModel, TenantQuerySet, TenantManager
from core.validators import validar_chave_nfe, validar_cnpj

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
    # Campos Fiscais e Regulatórios (Sprint 11A e 11B - Tarefas 3 e 5)
    ncm = models.CharField(max_length=8, blank=True, default='', verbose_name="NCM (8 dígitos)")
    cest = models.CharField(max_length=7, blank=True, default='', verbose_name="CEST (7 dígitos)")
    unidade_tributavel = models.CharField(max_length=10, blank=True, default='m3', verbose_name="Unidade Tributável")
    origem = models.CharField(max_length=1, default='0', verbose_name="Origem da Mercadoria (0 a 8)")
    grupo_fiscal = models.CharField(max_length=50, blank=True, default='', verbose_name="Grupo Fiscal")
    medicinal = models.BooleanField(default=False, verbose_name="Gás Medicinal")
    registro_anvisa = models.CharField(max_length=50, blank=True, default='', verbose_name="Registro ANVISA")
    exige_rastro = models.BooleanField(default=False, verbose_name="Exige Rastreabilidade de Lote")
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
    fator_conversao_m3_por_kg = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('0.7500'),
        verbose_name="Fator de Conversão m³/kg (NTP: 20 °C, 1 atm)",
        help_text="Volume em m³ gasoso gerado por 1 kg de gás a 20 °C e 1 atm (ABNT NBR 12274)."
    )
    densidade_liquido_kg_l = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="Densidade do Líquido Criogênico (kg/L no ponto de ebulição)",
        help_text="Massa em kg por litro de líquido criogênico no ponto de ebulição a 1 atm."
    )

    class Meta:
        verbose_name = "Gás Químico"
        verbose_name_plural = "Gases Químicos"
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} ({self.sigla}) - {self.get_categoria_display()}"


class ClasseRiscoGas(TenantAwareModel):
    """
    Classificação ANTT de Produtos Perigosos para Transporte e MDF-e (Sprint 11B - Tarefa 6 e 12A).
    Utilizado na montagem do Manifesto de Carga (MDF-e) e Romaneio ANTT (Res. 5.998/22).
    """
    gas = models.ForeignKey(
        GasQuimico,
        on_delete=models.PROTECT,
        related_name='classes_risco',
        verbose_name="Gás Químico"
    )
    numero_onu = models.CharField(max_length=4, verbose_name="Número ONU (4 dígitos)")
    classe_risco = models.CharField(max_length=10, verbose_name="Classe de Risco Principal (Ex: 2.2)")
    subclasse = models.CharField(max_length=10, blank=True, default='', verbose_name="Subclasse / Risco Subsidiário (Ex: 5.1)")
    numero_risco = models.CharField(max_length=10, blank=True, default='', verbose_name="Número de Risco (Painel de Segurança, Ex: 25)")
    grupo_embalagem = models.CharField(max_length=10, blank=True, default='', verbose_name="Grupo de Embalagem")
    rotulo_risco = models.CharField(max_length=100, blank=True, default='', verbose_name="Rótulo de Risco ANTT")
    descricao_transporte = models.CharField(max_length=255, verbose_name="Nome Apropriado para Embarque / Descrição de Transporte")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Classe de Risco de Gás (ANTT)"
        verbose_name_plural = "Classes de Risco de Gases (ANTT)"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'gas'], name='unique_tenant_classe_risco_gas')
        ]

    def __str__(self):
        return f"ONU {self.numero_onu} - {self.descricao_transporte} (Classe {self.classe_risco})"


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
    # Campos Fiscais e Regulatórios (Sprint 11A e 11B - Tarefas 3 e 5)
    ncm = models.CharField(max_length=8, blank=True, default='', verbose_name="NCM (8 dígitos)")
    cest = models.CharField(max_length=7, blank=True, default='', verbose_name="CEST (7 dígitos)")
    unidade_tributavel = models.CharField(max_length=10, blank=True, default='m3', verbose_name="Unidade Tributável")
    origem = models.CharField(max_length=1, default='0', verbose_name="Origem da Mercadoria (0 a 8)")
    grupo_fiscal = models.CharField(max_length=50, blank=True, default='', verbose_name="Grupo Fiscal")
    medicinal = models.BooleanField(default=False, verbose_name="Gás Medicinal")
    registro_anvisa = models.CharField(max_length=50, blank=True, default='', verbose_name="Registro ANVISA")
    exige_rastro = models.BooleanField(default=False, verbose_name="Exige Rastreabilidade de Lote")
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
    fechado = models.BooleanField(default=False, verbose_name="Lote Fechado / Produção Concluída")
    fechado_em = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora do Fechamento")
    tanque_origem = models.ForeignKey(
        'TanqueCriogenico',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='lotes_envasados',
        verbose_name="Tanque Criogênico de Origem"
    )
    massa_gas_total_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0.000'),
        verbose_name="Massa Total Envasada (kg)"
    )
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
# 2.1 PATRIMÔNIO, CATÁLOGO DE FABRICANTES E ATIVOS IMOBILIZADOS (SPRINT 8A)
# ==============================================================================

class FabricanteCilindro(TenantAwareModel):
    """
    Catálogo padronizado de fabricantes de cilindros por tenant (Sprint 8A - Tarefa 1).
    """
    nome = models.CharField(max_length=150, verbose_name="Nome do Fabricante")
    pais_origem = models.CharField(max_length=50, default="BR", verbose_name="País de Origem")
    norma_fabricacao_padrao = models.CharField(max_length=50, blank=True, default="", verbose_name="Norma de Fabricação Padrão")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fabricante de Cilindro"
        verbose_name_plural = "Fabricantes de Cilindros"
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'nome'], name='unique_tenant_fabricante_nome')
        ]

    def __str__(self):
        return self.nome


class ClasseAtivo(TenantAwareModel):
    """
    Classificação patrimonial e parâmetros fiscais/contábeis de depreciação (Sprint 8A - Tarefa 3).
    """
    TIPO_CHOICES = [
        ('CILINDRO', 'Cilindro / Vaso de Pressão'),
        ('VEICULO', 'Veículo / Frota'),
        ('TANQUE_CRIOGENICO', 'Tanque Criogênico'),
        ('RAMPA_ENVASE', 'Rampa de Envase'),
        ('OUTRO', 'Outro Imobilizado'),
    ]
    METODO_CHOICES = [
        ('LINEAR', 'Linear / Quotas Constantes'),
    ]

    codigo = models.CharField(max_length=30, verbose_name="Código da Classe")
    nome = models.CharField(max_length=100, verbose_name="Nome da Classe")
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, default='CILINDRO', verbose_name="Tipo de Ativo")
    vida_util_meses_padrao = models.PositiveIntegerField(default=120, verbose_name="Vida Útil Padrão (Meses)")
    percentual_residual_padrao = models.DecimalField(
        max_digits=6, decimal_places=4, default=Decimal('0.1000'), verbose_name="Percentual Residual Padrão"
    )
    metodo_depreciacao = models.CharField(max_length=20, choices=METODO_CHOICES, default='LINEAR', verbose_name="Método de Depreciação")
    codigo_conta_imobilizado = models.CharField(max_length=50, blank=True, default="", verbose_name="Código Conta Imobilizado")
    codigo_conta_depreciacao_acumulada = models.CharField(max_length=50, blank=True, default="", verbose_name="Código Conta Depreciação Acumulada")
    codigo_conta_despesa_depreciacao = models.CharField(max_length=50, blank=True, default="", verbose_name="Código Conta Despesa Depreciação")
    conta_imobilizado = models.ForeignKey(
        'financeiro.PlanoContas',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='classes_ativo_imobilizado',
        verbose_name="Conta Contábil do Imobilizado"
    )
    conta_depreciacao_acumulada = models.ForeignKey(
        'financeiro.PlanoContas',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='classes_ativo_depreciacao_acumulada',
        verbose_name="Conta Contábil de Depreciação Acumulada"
    )
    conta_despesa_depreciacao = models.ForeignKey(
        'financeiro.PlanoContas',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='classes_ativo_despesa_depreciacao',
        verbose_name="Conta Contábil de Despesa de Depreciação"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Classe de Ativo Imobilizado"
        verbose_name_plural = "Classes de Ativos Imobilizados"
        ordering = ['codigo']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'codigo'], name='unique_tenant_classe_ativo_codigo')
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nome}"

    def clean(self):
        super().clean()
        for field_name in ['conta_imobilizado', 'conta_depreciacao_acumulada', 'conta_despesa_depreciacao']:
            conta = getattr(self, field_name)
            if conta:
                if conta.tipo != 'ANALITICA' or not conta.aceita_lancamento:
                    raise ValidationError({
                        field_name: f"A conta {conta.codigo_estrutural} vinculada deve ser analítica e aceitar lançamentos contábeis."
                    })
                if conta.tenant_id != self.tenant_id:
                    raise ValidationError({
                        field_name: "A conta contábil deve pertencer ao mesmo Tenant da classe de ativo."
                    })

    def save(self, *args, **kwargs):
        # Sincronização bidirecional legada (Rule 9 até Sprint 13)
        if self.conta_imobilizado and not self.codigo_conta_imobilizado:
            self.codigo_conta_imobilizado = self.conta_imobilizado.codigo_estrutural
        elif self.codigo_conta_imobilizado and not self.conta_imobilizado_id:
            from financeiro.models import PlanoContas
            c = PlanoContas.unscoped.filter(tenant_id=self.tenant_id, codigo_estrutural=self.codigo_conta_imobilizado).first()
            if c:
                self.conta_imobilizado = c

        if self.conta_depreciacao_acumulada and not self.codigo_conta_depreciacao_acumulada:
            self.codigo_conta_depreciacao_acumulada = self.conta_depreciacao_acumulada.codigo_estrutural
        elif self.codigo_conta_depreciacao_acumulada and not self.conta_depreciacao_acumulada_id:
            from financeiro.models import PlanoContas
            c = PlanoContas.unscoped.filter(tenant_id=self.tenant_id, codigo_estrutural=self.codigo_conta_depreciacao_acumulada).first()
            if c:
                self.conta_depreciacao_acumulada = c

        if self.conta_despesa_depreciacao and not self.codigo_conta_despesa_depreciacao:
            self.codigo_conta_despesa_depreciacao = self.conta_despesa_depreciacao.codigo_estrutural
        elif self.codigo_conta_despesa_depreciacao and not self.conta_despesa_depreciacao_id:
            from financeiro.models import PlanoContas
            c = PlanoContas.unscoped.filter(tenant_id=self.tenant_id, codigo_estrutural=self.codigo_conta_despesa_depreciacao).first()
            if c:
                self.conta_despesa_depreciacao = c

        super().save(*args, **kwargs)


class LoteAquisicaoCilindros(TenantAwareModel):
    """
    Agrupador de compra em lote de cilindros com rateio uniforme de custo unitário (Sprint 8A - Tarefa 5).
    """
    classe = models.ForeignKey(ClasseAtivo, on_delete=models.PROTECT, related_name='lotes_aquisicao_cilindros', verbose_name="Classe de Ativo")
    fornecedor_nome = models.CharField(max_length=150, verbose_name="Nome do Fornecedor")
    fornecedor_documento = models.CharField(max_length=20, blank=True, default="", verbose_name="CNPJ/CPF do Fornecedor")
    chave_nfe = models.CharField(max_length=44, blank=True, null=True, validators=[validar_chave_nfe], verbose_name="Chave de Acesso NF-e")
    data_aquisicao = models.DateField(verbose_name="Data de Aquisição")
    quantidade = models.PositiveIntegerField(verbose_name="Quantidade de Cilindros")
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Total do Lote (R$)")
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Unitário por Cilindro (R$)")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lote de Aquisição de Cilindros"
        verbose_name_plural = "Lotes de Aquisição de Cilindros"
        ordering = ['-data_aquisicao']

    def __str__(self):
        return f"Lote {self.data_aquisicao} ({self.quantidade} un) - {self.fornecedor_nome}"

    def clean(self):
        super().clean()
        if self.quantidade and self.quantidade > 0 and self.valor_total is not None:
            calculado = quantize(self.valor_total / Decimal(str(self.quantidade)), 2)
            if not self.valor_unitario:
                self.valor_unitario = calculado


class AtivoImobilizado(TenantAwareModel):
    """
    Registro individual de ativo imobilizado geral (veículos, tanques, rampas, etc.) (Sprint 8A - Tarefa 4).
    """
    STATUS_CHOICES = [
        ('EM_USO', 'Em Uso Operacional'),
        ('BAIXADO', 'Baixado / Alienado'),
        ('VENDIDO', 'Vendido'),
    ]

    filial = models.ForeignKey('core.Filial', on_delete=models.PROTECT, null=True, blank=True, related_name='ativos_imobilizados', verbose_name="Filial")
    classe = models.ForeignKey(ClasseAtivo, on_delete=models.PROTECT, related_name='ativos_imobilizados', verbose_name="Classe de Ativo")
    numero_patrimonio = models.CharField(max_length=50, verbose_name="Número de Patrimônio / Plaqueta")
    descricao = models.CharField(max_length=255, verbose_name="Descrição do Ativo")
    data_aquisicao = models.DateField(verbose_name="Data de Aquisição")
    data_inicio_depreciacao = models.DateField(null=True, blank=True, verbose_name="Início da Depreciação")
    valor_aquisicao = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor de Aquisição (R$)")
    valor_residual = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Residual (R$)")
    vida_util_meses = models.PositiveIntegerField(verbose_name="Vida Útil (Meses)")
    fornecedor_nome = models.CharField(max_length=150, blank=True, default="", verbose_name="Nome do Fornecedor")
    fornecedor_documento = models.CharField(max_length=20, blank=True, default="", verbose_name="CNPJ/CPF do Fornecedor")
    chave_nfe_aquisicao = models.CharField(max_length=44, blank=True, null=True, validators=[validar_chave_nfe], verbose_name="Chave de Acesso NF-e de Aquisição")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EM_USO', verbose_name="Status Operacional")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ativo Imobilizado"
        verbose_name_plural = "Ativos Imobilizados"
        ordering = ['numero_patrimonio']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'numero_patrimonio'], name='unique_tenant_ativo_numero_patrimonio')
        ]

    def __str__(self):
        return f"[{self.numero_patrimonio}] {self.descricao}"

    @property
    def depreciacao_mensal_rs(self) -> Decimal:
        from produtos.depreciacao import quota_mensal
        return quota_mensal(self.valor_aquisicao, self.valor_residual, self.vida_util_meses)

    @property
    def depreciacao_diaria_rs(self) -> Decimal:
        return quantize(self.depreciacao_mensal_rs / Decimal('30.00'), 2)

    @property
    def valor_contabil_liquido_atual(self) -> Decimal:
        from produtos.depreciacao import valor_contabil_liquido
        data_inicio = self.data_inicio_depreciacao or self.data_aquisicao
        return valor_contabil_liquido(self.valor_aquisicao, self.valor_residual, self.vida_util_meses, data_inicio)


class TabelaIndenizacaoCilindro(TenantAwareModel):
    """
    Parâmetros contratuais de cobrança indenizatória para extravio/dano de cilindros (Sprint 8A - Tarefa 9).
    """
    tipo_cilindro = models.ForeignKey(ModeloCilindro, on_delete=models.CASCADE, related_name='tabelas_indenizacao', verbose_name="Modelo de Cilindro")
    gas = models.ForeignKey(GasQuimico, null=True, blank=True, on_delete=models.SET_NULL, related_name='tabelas_indenizacao', verbose_name="Gás Químico (Opcional)")
    valor = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Contratual de Indenização (R$)")
    vigencia_inicio = models.DateField(verbose_name="Início da Vigência")
    vigencia_fim = models.DateField(null=True, blank=True, verbose_name="Fim da Vigência")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tabela de Indenização de Cilindros"
        verbose_name_plural = "Tabelas de Indenização de Cilindros"
        ordering = ['-vigencia_inicio']

    def __str__(self):
        gas_str = f" / {self.gas.sigla}" if self.gas else ""
        return f"Indenização {self.tipo_cilindro.descricao}{gas_str}: R$ {self.valor}"


# ==============================================================================
# 3. ATIVOS RASTREADOS E LEDGER IMUTÁVEL
# ==============================================================================

class Cilindro(TenantAwareModel):
    """
    Ativo físico rastreado individualmente (vaso de pressão) por QR Code e Número de Série.
    Possui projeção do estado atual, datas de teste hidrostático e gestão de CAPEX/Depreciação.
    """
    STATUS_CHOICES = [
        ('CHEIO_DISPONIVEL', 'Cheio Disponível no Pátio'),
        ('RESERVADO_ROTA', 'Reservado / Em Rota'),
        ('EM_POSSE_CLIENTE', 'Em Posse do Cliente'),
        ('VAZIO_TRIAGEM', 'Vazio em Triagem'),
        ('EM_ENVASE', 'Em Envase'),
        ('EM_RETESTE', 'Em Reteste / Manutenção (Legado)'),
        ('EM_REQUALIFICACAO', 'Em Requalificação / Reteste Hidrostático'),
        ('BAIXADO', 'Baixado / Condenado'),
        ('EXTRAVIADO', 'Extraviado / Indenização Patrimonial'),
    ]

    PROPRIEDADE_CHOICES = [
        ('PROPRIO', 'Patrimônio Próprio'),
        ('CLIENTE', 'Propriedade do Cliente'),
        ('TERCEIRO', 'Terceiro / Intercâmbio'),
        ('COMODATO_RECEBIDO', 'Comodato Recebido'),
        ('DISTRIBUIDORA', 'Patrimônio da Distribuidora (Legado)'),
        ('PARCEIRO', 'Parceiro Comercial (Legado)'),
        ('TERCEIRO_INTERCAMBIO', 'Terceiro / Intercâmbio (Legado)'),
    ]

    codigo_qr = models.CharField(max_length=100, db_index=True, verbose_name="Código QR / Barcode")
    numero_serie_ogiva = models.CharField(max_length=100, verbose_name="Número de Série (Ogiva)")
    fabricante = models.CharField(max_length=100, verbose_name="Fabricante")
    ano_fabricacao = models.IntegerField(verbose_name="Ano de Fabricação")

    # Catálogo e Especificações Técnicas (Sprint 8A - Tarefas 1 e 2)
    fabricante_catalogo = models.ForeignKey(
        FabricanteCilindro,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cilindros',
        verbose_name="Fabricante (Catálogo)"
    )
    norma_fabricacao = models.CharField(max_length=50, blank=True, default="", verbose_name="Norma de Fabricação")
    pressao_servico_bar = models.IntegerField(null=True, blank=True, verbose_name="Pressão de Serviço (bar)")
    pressao_teste_bar = models.IntegerField(null=True, blank=True, verbose_name="Pressão de Teste Hidrostático (bar)")
    tipo_valvula_rosca = models.CharField(max_length=50, blank=True, default="", verbose_name="Tipo de Válvula / Rosca")

    modelo = models.ForeignKey(ModeloCilindro, on_delete=models.PROTECT, related_name='cilindros', verbose_name="Modelo do Cilindro")
    gas_dedicado = models.ForeignKey(GasQuimico, on_delete=models.PROTECT, related_name='cilindros', verbose_name="Gás Dedicado")

    tara_real_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name="Tara Real Aferida (kg)")
    propriedade = models.CharField(max_length=30, choices=PROPRIEDADE_CHOICES, default='DISTRIBUIDORA', verbose_name="Propriedade")
    cliente_proprietario = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, null=True, blank=True, related_name='cilindros_proprios', verbose_name="Cliente Proprietário")
    is_reserva_tecnica = models.BooleanField(default=False, verbose_name="Cilindro em Reserva Técnica")

    # Gestão de CAPEX e Ativo Imobilizado (Sprint 8A - Tarefa 6)
    numero_patrimonio = models.CharField(max_length=50, null=True, blank=True, db_index=True, verbose_name="Número de Patrimônio")
    data_aquisicao = models.DateField(null=True, blank=True, verbose_name="Data de Aquisição")
    data_inicio_depreciacao = models.DateField(null=True, blank=True, verbose_name="Início da Depreciação")
    valor_aquisicao = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Valor de Aquisição (R$)")
    valor_residual = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Valor Residual (R$)")
    vida_util_meses = models.PositiveIntegerField(null=True, blank=True, verbose_name="Vida Útil (Meses)")
    chave_nfe_aquisicao = models.CharField(max_length=44, blank=True, null=True, validators=[validar_chave_nfe], verbose_name="Chave de Acesso NF-e de Aquisição")
    fornecedor_aquisicao = models.CharField(max_length=150, blank=True, default="", verbose_name="Fornecedor de Aquisição")
    lote_aquisicao = models.ForeignKey(
        LoteAquisicaoCilindros,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='cilindros',
        verbose_name="Lote de Aquisição"
    )
    classe_ativo = models.ForeignKey(
        ClasseAtivo,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='cilindros',
        verbose_name="Classe de Ativo"
    )

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
            models.UniqueConstraint(
                fields=['tenant', 'numero_patrimonio'],
                condition=models.Q(numero_patrimonio__isnull=False) & ~models.Q(numero_patrimonio=''),
                name='unique_tenant_cilindro_numero_patrimonio'
            ),
        ]

    @property
    def is_proprio(self) -> bool:
        """Retorna True se o cilindro for patrimônio próprio do tenant (Sprint 8A - Tarefa 7)."""
        return self.propriedade in ['PROPRIO', 'DISTRIBUIDORA']

    @property
    def depreciacao_mensal_rs(self) -> Decimal:
        """Estimativa gerencial da quota mensal de depreciação linear (Sprint 8A - Tarefa 8)."""
        if not self.is_proprio or not self.valor_aquisicao or not self.vida_util_meses:
            return Decimal('0.00')
        from produtos.depreciacao import quota_mensal
        v_res = self.valor_residual if self.valor_residual is not None else Decimal('0.00')
        return quota_mensal(self.valor_aquisicao, v_res, self.vida_util_meses)

    @property
    def depreciacao_diaria_rs(self) -> Decimal:
        """Estimativa gerencial da depreciação diária (mensal ÷ 30) (Sprint 8A - Tarefa 8)."""
        return quantize(self.depreciacao_mensal_rs / Decimal('30.00'), 2)

    @property
    def valor_contabil_liquido_atual(self) -> Decimal:
        """Estimativa gerencial de leitura do Valor Contábil Líquido atual (Sprint 8A - Tarefa 8)."""
        if not self.is_proprio or not self.valor_aquisicao:
            return Decimal('0.00')
        from produtos.depreciacao import valor_contabil_liquido
        v_res = self.valor_residual if self.valor_residual is not None else Decimal('0.00')
        data_inicio = self.data_inicio_depreciacao or self.data_aquisicao
        return valor_contabil_liquido(self.valor_aquisicao, v_res, self.vida_util_meses, data_inicio)

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
        return self.is_proprio

    def clean(self):
        super().clean()
        # Validação técnica: pressao_teste_bar >= pressao_servico_bar (Sprint 8A - Tarefa 2)
        if self.pressao_teste_bar is not None and self.pressao_servico_bar is not None:
            if self.pressao_teste_bar < self.pressao_servico_bar:
                raise ValidationError({
                    'pressao_teste_bar': 'A pressão de teste hidrostático deve ser maior ou igual à pressão de serviço.'
                })

        # Validação CAPEX para cilindros PROPRIO (Sprint 8A - Tarefa 7)
        if self.is_proprio:
            if self.valor_aquisicao is not None and self.valor_residual is not None:
                if self.valor_residual > self.valor_aquisicao:
                    raise ValidationError({
                        'valor_residual': 'O valor residual não pode exceder o valor de aquisição.'
                    })

        # Validação de cota para novos cilindros (cilindros CLIENTE são isentos da cota) (Sprint 8A - Tarefas 7 e 10)
        if not self.pk and self.propriedade != 'CLIENTE':
            tenant = getattr(self, 'tenant', None)
            if tenant:
                from core.services.cotas import checar_cota
                checar_cota(tenant, 'cilindros', incremento=1)

    def save(self, *args, **kwargs):
        # 1. Sincronização legado fabricante <-> fabricante_catalogo (Sprint 8A - Tarefa 1)
        if self.fabricante_catalogo:
            self.fabricante = self.fabricante_catalogo.nome

        # 2. Herança de parâmetros do Lote de Aquisição (Sprint 8A - Tarefa 5)
        if self.lote_aquisicao:
            if not self.valor_aquisicao:
                self.valor_aquisicao = self.lote_aquisicao.valor_unitario
            if not self.data_aquisicao:
                self.data_aquisicao = self.lote_aquisicao.data_aquisicao
            if not self.classe_ativo:
                self.classe_ativo = self.lote_aquisicao.classe
            if not self.fornecedor_aquisicao:
                self.fornecedor_aquisicao = self.lote_aquisicao.fornecedor_nome
            if not self.chave_nfe_aquisicao:
                self.chave_nfe_aquisicao = self.lote_aquisicao.chave_nfe

        # 3. Herança de parâmetros da Classe de Ativo (Sprint 8A - Tarefas 3 e 6)
        if self.classe_ativo:
            if not self.vida_util_meses:
                self.vida_util_meses = self.classe_ativo.vida_util_meses_padrao
            if self.valor_aquisicao is not None and self.valor_residual is None:
                self.valor_residual = quantize(self.valor_aquisicao * self.classe_ativo.percentual_residual_padrao, 2)

        # 4. Início de depreciação padrão (mês da aquisição se não especificado)
        if self.valor_aquisicao and not self.data_inicio_depreciacao and self.data_aquisicao:
            self.data_inicio_depreciacao = self.data_aquisicao

        super().save(*args, **kwargs)

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
    peso_cheio_kg = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Peso Cheio Aferido na Rampa (kg)")
    tara_cilindro_kg = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Tara Aferida do Cilindro (kg)")
    massa_liquida_gas_kg = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Massa Líquida de Gás Envasada (kg)")
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
# 3.1 HISTÓRICO DE RETESTES HIDROSTÁTICOS, ENVIOS E BAIXA PATRIMONIAL (SPRINT 8B)
# ==============================================================================

class HistoricoRetesteQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Histórico de reteste é imutável: atualizações em lote são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Histórico de reteste é imutável: exclusões são proibidas.")


class HistoricoRetesteManager(TenantManager.from_queryset(HistoricoRetesteQuerySet)):
    pass


class UnscopedHistoricoRetesteQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ValidationError("Histórico de reteste é imutável: atualizações em lote são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Histórico de reteste é imutável: exclusões são proibidas.")


class UnscopedHistoricoRetesteManager(models.Manager.from_queryset(UnscopedHistoricoRetesteQuerySet)):
    pass


class HistoricoRetesteHidrostatico(TenantAwareModel):
    """
    Histórico perpétuo e auditável de ensaios e requalificações hidrostáticas (ABNT NBR 12274).
    Imutável: correções e ajustes de laudos exigem novo registro com apontamento em 'retifica'.
    """
    ORIGEM_CHOICES = [
        ('REGISTRO', 'Registro Formal'),
        ('LEGADO', 'Carga Legada'),
    ]
    RESULTADO_CHOICES = [
        ('APROVADO', 'Aprovado'),
        ('REPROVADO_CONDENADO', 'Reprovado / Condenado'),
    ]

    cilindro = models.ForeignKey(
        'Cilindro',
        on_delete=models.PROTECT,
        related_name='historico_retestes',
        verbose_name="Cilindro"
    )
    origem_registro = models.CharField(
        max_length=20,
        choices=ORIGEM_CHOICES,
        default='REGISTRO',
        verbose_name="Origem do Registro"
    )
    retifica = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='retificacoes',
        verbose_name="Retifica Registro Anterior"
    )
    data_execucao = models.DateField(verbose_name="Data de Execução do Ensaio")
    numero_certificado = models.CharField(max_length=100, blank=True, default='', verbose_name="Número do Certificado")
    oficina_nome = models.CharField(max_length=150, blank=True, default='', verbose_name="Oficina Executora / Requalificadora")
    oficina_cnpj = models.CharField(max_length=20, blank=True, default='', verbose_name="CNPJ da Oficina")
    registro_inmetro = models.CharField(max_length=100, blank=True, default='', verbose_name="Registro INMETRO da Oficina")
    pressao_teste_bar = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="Pressão de Teste Aplicada (bar)")
    expansao_total_cm3 = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Expansão Total (cm³)")
    expansao_permanente_cm3 = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Expansão Permanente (cm³)")
    expansao_permanente_percentual = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, verbose_name="Expansão Permanente (%)")
    limite_expansao_percentual_aplicado = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('10.0000'), verbose_name="Limite de Expansão Permitido (%)")
    tara_gravada_kg = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Tara Gravada na Ogiva (kg)")
    tara_real_kg = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Tara Real Aferida (kg)")
    variacao_tara_percentual = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, verbose_name="Variação de Tara (%)")
    resultado = models.CharField(max_length=30, choices=RESULTADO_CHOICES, verbose_name="Resultado do Ensaio")
    motivo_reprovacao = models.TextField(blank=True, default='', verbose_name="Motivo da Reprovação / Condenação")
    data_proximo_reteste = models.DateField(null=True, blank=True, verbose_name="Data do Próximo Reteste")
    custo_servico_reteste = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo do Serviço (R$)")
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações Técnicas")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='retestes_registrados',
        verbose_name="Registrado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = HistoricoRetesteManager()
    unscoped = UnscopedHistoricoRetesteManager()

    class Meta:
        verbose_name = "Histórico de Reteste Hidrostático"
        verbose_name_plural = "Históricos de Retestes Hidrostáticos"
        ordering = ['-data_execucao', '-criado_em']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(origem_registro='LEGADO') | (
                    models.Q(origem_registro='REGISTRO') &
                    ~models.Q(numero_certificado='') &
                    ~models.Q(oficina_nome='') &
                    ~models.Q(oficina_cnpj='') &
                    ~models.Q(registro_inmetro='')
                ),
                name='chk_reteste_registro_campos_obrigatorios'
            )
        ]

    def clean(self):
        super().clean()
        from core.money import quantize
        # Cálculo automático da expansão permanente percentual: (EP / ET) * 100
        if self.expansao_permanente_cm3 is not None and self.expansao_total_cm3 is not None:
            if self.expansao_total_cm3 > Decimal('0.000'):
                pct = (self.expansao_permanente_cm3 / self.expansao_total_cm3) * Decimal('100.0')
                self.expansao_permanente_percentual = quantize(pct, Decimal('0.0001'))
            else:
                self.expansao_permanente_percentual = Decimal('0.0000')

        # Cálculo da variação de tara
        if self.tara_real_kg is not None and self.tara_gravada_kg is not None and self.tara_gravada_kg > Decimal('0.000'):
            var_pct = ((self.tara_real_kg - self.tara_gravada_kg) / self.tara_gravada_kg) * Decimal('100.0')
            self.variacao_tara_percentual = quantize(var_pct, Decimal('0.0001'))

        # Validação do limite normativo de expansão (ABNT NBR 12274 / ISO 9809-1)
        if self.expansao_permanente_percentual is not None and self.limite_expansao_percentual_aplicado is not None:
            if self.expansao_permanente_percentual > self.limite_expansao_percentual_aplicado and self.resultado == 'APROVADO':
                raise ValidationError(
                    f"Reprovação mandatória (ABNT NBR 12274): A expansão permanente percentual "
                    f"({self.expansao_permanente_percentual}%) supera o limite normativo de "
                    f"{self.limite_expansao_percentual_aplicado}%. O ensaio deve ser REPROVADO_CONDENADO."
                )

        if self.origem_registro == 'REGISTRO':
            erros = {}
            if not self.numero_certificado:
                erros['numero_certificado'] = "Número do certificado é obrigatório para registros formais."
            if not self.oficina_nome:
                erros['oficina_nome'] = "Nome da oficina é obrigatório para registros formais."
            if not self.oficina_cnpj:
                erros['oficina_cnpj'] = "CNPJ da oficina é obrigatório para registros formais."
            if not self.registro_inmetro:
                erros['registro_inmetro'] = "Registro INMETRO é obrigatório para registros formais."
            if erros:
                raise ValidationError(erros)

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk:
            raise ValidationError("Registro de histórico de reteste é imutável: edições são proibidas. Crie um novo registro com 'retifica' apontando para este.")
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False) or getattr(self, '_allow_deletion', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Registro de histórico de reteste é imutável: exclusões são proibidas.")

    def __str__(self):
        cert = self.numero_certificado or "Sem Cert."
        return f"Reteste {self.cilindro.numero_serie_ogiva} ({self.data_execucao.strftime('%d/%m/%Y')} - Cert: {cert}) [{self.resultado}]"


class EnvioReteste(TenantAwareModel):
    """
    Registro de remessa e despacho de cilindros para requalificação / ensaio hidrostático externo (Sprint 8B - Tarefa 3).
    """
    oficina_nome = models.CharField(max_length=150, verbose_name="Oficina / Requalificadora")
    oficina_cnpj = models.CharField(max_length=20, validators=[validar_cnpj], verbose_name="CNPJ da Oficina")
    data_envio = models.DateField(default=timezone.localdate, verbose_name="Data de Envio")
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações do Envio")
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='envios_reteste_criados',
        verbose_name="Criado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    cilindros = models.ManyToManyField(
        'Cilindro',
        through='ItemEnvioReteste',
        related_name='envios_reteste',
        verbose_name="Cilindros Remetidos"
    )

    class Meta:
        verbose_name = "Envio para Reteste Hidrostático"
        verbose_name_plural = "Envios para Reteste Hidrostático"
        ordering = ['-data_envio', '-criado_em']

    def __str__(self):
        return f"Envio Reteste #{self.id} -> {self.oficina_nome} em {self.data_envio.strftime('%d/%m/%Y')}"


class ItemEnvioReteste(TenantAwareModel):
    """
    Item individual (cilindro) integrante de um lote de envio para reteste.
    """
    envio = models.ForeignKey(
        EnvioReteste,
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Envio de Reteste"
    )
    cilindro = models.ForeignKey(
        'Cilindro',
        on_delete=models.PROTECT,
        related_name='itens_envio_reteste',
        verbose_name="Cilindro"
    )
    status_anterior = models.CharField(max_length=30, default='VAZIO_TRIAGEM', verbose_name="Status Anterior")
    retornado = models.BooleanField(default=False, verbose_name="Retornado do Reteste")
    reteste_vinculado = models.ForeignKey(
        HistoricoRetesteHidrostatico,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='itens_envio_vinculados',
        verbose_name="Reteste de Retorno Vinculado"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Item de Envio para Reteste"
        verbose_name_plural = "Itens de Envio para Reteste"
        constraints = [
            models.UniqueConstraint(fields=['envio', 'cilindro'], name='unique_envio_reteste_cilindro')
        ]

    def __str__(self):
        return f"Item Envio #{self.envio_id} - Cilindro {self.cilindro.numero_serie_ogiva} ({'Retornado' if self.retornado else 'Em Aberto'})"


class BaixaPatrimonial(TenantAwareModel):
    """
    Registro auditável e irreversível de baixa patrimonial de cilindro (Sprint 8B - Tarefa 5 e 6).
    Estorno excepcional é restrito à permissão 'produtos.estornar_baixa'.
    """
    TIPO_CHOICES = [
        ('INUTILIZACAO_TECNICA', 'Inutilização Técnica / Condenação'),
        ('EXTRAVIO', 'Extravio / Perda de Ativo'),
        ('VENDA', 'Venda de Ativo Imobilizado'),
        ('SINISTRO', 'Sinistro / Destruição Acidental'),
    ]

    cilindro = models.ForeignKey(
        'Cilindro',
        on_delete=models.PROTECT,
        related_name='baixas_patrimoniais',
        verbose_name="Cilindro"
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, verbose_name="Tipo de Baixa")
    data = models.DateField(default=timezone.localdate, verbose_name="Data da Baixa")
    valor_contabil_baixa = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Contábil na Baixa (Snapshot R$)")
    valor_recebido = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Recebido / Indenizado (R$)")
    resultado = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Resultado Ganho/Perda (R$)")
    documento_ref = models.CharField(max_length=100, blank=True, default='', verbose_name="Documento de Referência / B.O. / NF")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='baixas_patrimoniais_realizadas',
        verbose_name="Registrado por"
    )
    motivo = models.TextField(blank=True, default='', verbose_name="Motivo da Baixa")
    status_anterior = models.CharField(max_length=30, default='VAZIO_TRIAGEM', verbose_name="Status Anterior do Cilindro")
    estornada = models.BooleanField(default=False, verbose_name="Baixa Estornada")
    data_estorno = models.DateTimeField(null=True, blank=True, verbose_name="Data do Estorno")
    motivo_estorno = models.TextField(blank=True, default='', verbose_name="Motivo do Estorno")
    usuario_estorno = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='baixas_patrimoniais_estornadas',
        verbose_name="Estornado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Baixa Patrimonial de Cilindro"
        verbose_name_plural = "Baixas Patrimoniais de Cilindros"
        ordering = ['-data', '-criado_em']
        permissions = [
            ("estornar_baixa", "Pode estornar baixa patrimonial de cilindro"),
        ]

    def __str__(self):
        est = " [ESTORNADA]" if self.estornada else ""
        return f"Baixa {self.get_tipo_display()} - Cilindro {self.cilindro.numero_serie_ogiva} em {self.data.strftime('%d/%m/%Y')}{est}"


# ==============================================================================
# 4. RECLASSIFICAÇÃO AUDITADA DE GÁS DE CILINDRO
# ==============================================================================

class ReclassificacaoQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Registro de reclassificação imutável: não pode ser alterado após criação.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Registro de reclassificação imutável: não pode ser excluído.")


class ReclassificacaoManager(TenantManager.from_queryset(ReclassificacaoQuerySet)):
    pass


class UnscopedReclassificacaoQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Registro de reclassificação imutável: não pode ser alterado após criação.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
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
    laudo_descontaminacao = models.FileField(
        upload_to='laudos_reclassificacao/',
        null=True,
        blank=True,
        verbose_name="Laudo / Certificado de Descontaminação"
    )
    exigiu_novo_reteste = models.BooleanField(
        default=False,
        verbose_name="Exigiu Novo Reteste Hidrostático"
    )
    reteste_vinculado = models.ForeignKey(
        'HistoricoRetesteHidrostatico',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='reclassificacoes_vinculadas',
        verbose_name="Reteste Vinculado"
    )
    validade_estanqueidade = models.DateField(
        null=True,
        blank=True,
        verbose_name="Validade do Teste de Estanqueidade"
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

    def clean(self):
        super().clean()
        if not self.laudo_descontaminacao and self.laudo_descontaminacao_pdf:
            self.laudo_descontaminacao = self.laudo_descontaminacao_pdf
        elif not self.laudo_descontaminacao_pdf and self.laudo_descontaminacao:
            self.laudo_descontaminacao_pdf = self.laudo_descontaminacao

        if self.exigiu_novo_reteste:
            if not self.reteste_vinculado:
                raise ValidationError("Reclassificação exige comprovação de novo reteste hidrostático vinculado.")
            if self.reteste_vinculado.cilindro_id != self.cilindro_id:
                raise ValidationError("O reteste vinculado deve pertencer ao mesmo cilindro da reclassificação.")
            if self.reteste_vinculado.resultado != 'APROVADO':
                raise ValidationError("O reteste vinculado para reclassificação deve estar APROVADO.")

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk:
            raise ValidationError("Registro de reclassificação imutável: não pode ser alterado após criação.")
        self.clean()
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


class AuditoriaDownloadLog(TenantAwareModel):
    """
    Log de auditoria e rastreabilidade para downloads de dossiês regulatórios ANVISA
    e laudos técnicos (Sprint 10 - Compliance ANVISA).
    Preserva o hash SHA-256 do arquivo emitido, carimbo de data/hora, IP do solicitante e identificação do usuário.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='downloads_auditados',
        verbose_name="Usuário Solicitante"
    )
    entidade_tipo = models.CharField(
        max_length=60,
        default='DOSSIE_LOTE_ANVISA',
        verbose_name="Tipo de Entidade Auditada"
    )
    entidade_id = models.CharField(
        max_length=100,
        verbose_name="Identificador da Entidade (ID/Código)"
    )
    hash_sha256 = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Hash SHA-256 de Integridade do PDF"
    )
    ip_origem = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="Endereço IP de Origem"
    )
    user_agent = models.TextField(
        blank=True,
        null=True,
        verbose_name="User-Agent do Navegador"
    )
    criado_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Data/Hora do Download"
    )

    class Meta:
        verbose_name = "Log de Auditoria de Download"
        verbose_name_plural = "Logs de Auditoria de Downloads"
        ordering = ['-criado_em']

    def __str__(self):
        usr = self.usuario.username if self.usuario else "Anônimo/Sistema"
        return f"Download {self.entidade_tipo} #{self.entidade_id} por {usr} em {self.criado_em.strftime('%d/%m/%Y %H:%M')}"


# ==============================================================================
# 3.2 GÁS A GRANEL, TANQUES CRIOGÊNICOS, ESTOQUE E CUSTO DE ENVASE (SPRINT 8C)
# ==============================================================================

class TanqueCriogenico(TenantAwareModel):
    """
    Ativo estacionário de armazenamento criogênico de gás líquido (Sprint 8C - Tarefa 2).
    Controla o balanço de massa perpétuo em kg e o custo médio ponderado móvel.
    """
    filial = models.ForeignKey(
        'core.Filial',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='tanques_criogenicos',
        verbose_name="Filial / Planta de Envase"
    )
    codigo = models.CharField(max_length=50, verbose_name="Código / Tag do Tanque")
    descricao = models.CharField(max_length=150, blank=True, default='', verbose_name="Descrição do Tanque")
    gas = models.ForeignKey(
        GasQuimico,
        on_delete=models.PROTECT,
        related_name='tanques',
        verbose_name="Gás Químico Armazenado"
    )
    capacidade_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Capacidade Nominal (kg)")
    saldo_atual_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0.000'),
        verbose_name="Saldo Atual de Gás em Estoque (kg)"
    )
    saldo_valor_atual = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Saldo em Valor (R$)"
    )
    custo_medio_kg_atual = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
        verbose_name="Custo Médio Ponderado Vigente (R$/kg)"
    )
    pressao_operacao_bar = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal('16.00'),
        verbose_name="Pressão Típica de Operação (bar)"
    )
    tolerancia_perda_pct = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0300'),
        verbose_name="Tolerância de Boil-off / Evaporação (%)",
        help_text="Percentual máximo de perda por evaporação aceito no período sem exigir justificativa técnica."
    )
    tolerancia_pesagem_pct = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0200'),
        verbose_name="Tolerância de Divergência NF x Balança (%)",
        help_text="Divergência entre peso NF e pesagem acima deste limite gera alerta operacional."
    )
    ativo_imobilizado = models.ForeignKey(
        'AtivoImobilizado',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tanques_associados',
        verbose_name="Ativo Imobilizado Vinculado"
    )
    ativo = models.BooleanField(default=True, verbose_name="Tanque Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Tanque Criogênico"
        verbose_name_plural = "Tanques Criogênicos"
        ordering = ['codigo']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'codigo'], name='uniq_tanque_tenant_codigo')
        ]

    def __str__(self):
        return f"{self.codigo} - {self.descricao or self.gas.nome} ({self.saldo_atual_kg} kg)"


class MedicaoTanque(TenantAwareModel):
    """
    Registro histórico de medição física de nível e pressão de um tanque criogênico (Sprint 8C - Tarefa 3).
    Pode ter origem manual (aferição por régua/diferencial) ou telemétrica.
    """
    ORIGEM_CHOICES = [
        ('MANUAL', 'Aferição Manual'),
        ('TELEMETRIA', 'Telemetria / Sensor Automático'),
    ]

    tanque = models.ForeignKey(
        TanqueCriogenico,
        on_delete=models.PROTECT,
        related_name='medicoes',
        verbose_name="Tanque Criogênico"
    )
    data_hora = models.DateTimeField(default=timezone.now, verbose_name="Data/Hora da Medição")
    massa_kg_medida = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Massa Aferida (kg)")
    pressao_bar = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal('0.00'), verbose_name="Pressão do Tanque (bar)")
    nivel_percentual = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name="Nível Medido (%)")
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default='MANUAL', verbose_name="Origem da Leitura")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='medicoes_tanque',
        verbose_name="Operador Responsável"
    )
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações Técnicas")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Medição de Tanque"
        verbose_name_plural = "Medições de Tanques"
        ordering = ['-data_hora']

    def __str__(self):
        return f"Medição {self.tanque.codigo} em {self.data_hora.strftime('%d/%m/%Y %H:%M')}: {self.massa_kg_medida} kg"


class EntradaGasGranel(TenantAwareModel):
    """
    Registro fiscal e físico de recebimento de gás criogênico a granel (Sprint 8C - Tarefa 4).
    Calcula o custo unitário efetivo por kg e apura divergências de pesagem entre NF e balança rodoviária.
    """
    tanque = models.ForeignKey(
        TanqueCriogenico,
        on_delete=models.PROTECT,
        related_name='entradas_granel',
        verbose_name="Tanque de Destino"
    )
    fornecedor_nome = models.CharField(max_length=200, verbose_name="Razão Social do Fornecedor")
    fornecedor_documento = models.CharField(max_length=30, verbose_name="CNPJ/CPF do Fornecedor")
    chave_nfe = models.CharField(
        max_length=44,
        validators=[validar_chave_nfe],
        verbose_name="Chave de Acesso da NF-e"
    )
    data_entrada = models.DateField(default=timezone.localdate, verbose_name="Data de Entrada")
    quantidade_kg_nf = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Quantidade Faturada na NF (kg)")
    quantidade_kg_recebida = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Quantidade Recebida / Pesagem Balança (kg)")
    custo_total_nf = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Total dos Produtos na NF (R$)")
    custo_frete = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo de Frete (R$)")
    impostos_recuperaveis = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Impostos Recuperáveis ICMS/PIS/COFINS (R$)")
    custo_unitario_kg_efetivo = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        verbose_name="Custo Unitário Efetivo (R$/kg)"
    )
    divergencia_peso_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0.000'),
        verbose_name="Divergência de Peso (kg)"
    )
    divergencia_peso_pct = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0000'),
        verbose_name="Divergência Percentual de Peso (%)"
    )
    alerta_divergencia = models.BooleanField(
        default=False,
        verbose_name="Alerta de Divergência Acima do Limite"
    )
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações Operacionais")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='entradas_gas_granel',
        verbose_name="Recebido por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Entrada de Gás a Granel"
        verbose_name_plural = "Entradas de Gás a Granel"
        ordering = ['-data_entrada', '-criado_em']

    def __str__(self):
        return f"Entrada #{self.id} - {self.tanque.codigo}: {self.quantidade_kg_recebida} kg (NF {self.chave_nfe[:8]}...)"


class MovimentoEstoqueGasQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Movimento de estoque de gás é imutável: atualizações em lote são estritamente proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Movimento de estoque de gás é imutável: exclusões são estritamente proibidas.")


class MovimentoEstoqueGasManager(TenantManager.from_queryset(MovimentoEstoqueGasQuerySet)):
    pass


class UnscopedMovimentoEstoqueGasQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Movimento de estoque de gás é imutável: atualizações em lote são estritamente proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Movimento de estoque de gás é imutável: exclusões são estritamente proibidas.")


class UnscopedMovimentoEstoqueGasManager(models.Manager.from_queryset(UnscopedMovimentoEstoqueGasQuerySet)):
    pass


class MovimentoEstoqueGas(TenantAwareModel):
    """
    Ledger financeiro e quantitativo perpétuo do estoque de gás a granel (Sprint 8C - Tarefa 5).
    Registra entradas, consumos e perdas sob custo médio móvel ponderado.
    Estritamente append-only e imutável.
    """
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada a Granel'),
        ('CONSUMO_ENVASE', 'Consumo na Rampa de Envase'),
        ('PERDA_EVAPORACAO', 'Perda por Evaporação (Boil-off)'),
        ('PERDA_PURGA', 'Perda por Purga de Rampa'),
        ('AJUSTE_INVENTARIO', 'Ajuste de Inventário / Medição'),
        ('TRANSFERENCIA', 'Transferência entre Tanques'),
    ]

    tanque = models.ForeignKey(
        TanqueCriogenico,
        on_delete=models.PROTECT,
        related_name='movimentos_estoque',
        verbose_name="Tanque Criogênico"
    )
    gas = models.ForeignKey(
        GasQuimico,
        on_delete=models.PROTECT,
        related_name='movimentos_estoque_gas',
        verbose_name="Gás Químico"
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, verbose_name="Tipo de Movimentação")
    quantidade_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Quantidade Movimentada com Sinal (kg)"
    )
    custo_unitario = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        verbose_name="Custo Unitário Aplicado (R$/kg)"
    )
    custo_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Custo Total da Movimentação (R$)"
    )
    saldo_quantidade_apos = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Saldo em Quantidade Após Movimento (kg)"
    )
    saldo_valor_apos = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Saldo em Valor Após Movimento (R$)"
    )
    custo_medio_apos = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        verbose_name="Custo Médio Ponderado Após Movimento (R$/kg)"
    )
    origem_tipo = models.CharField(max_length=50, blank=True, default='', verbose_name="Tipo de Origem")
    origem_id = models.CharField(max_length=50, blank=True, default='', verbose_name="ID da Origem")
    justificativa = models.TextField(blank=True, default='', verbose_name="Justificativa Operacional")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimentos_estoque_gas_gerados',
        verbose_name="Registrado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora do Lançamento")

    objects = MovimentoEstoqueGasManager()
    unscoped = UnscopedMovimentoEstoqueGasManager()

    class Meta:
        verbose_name = "Movimento de Estoque de Gás"
        verbose_name_plural = "Movimentos de Estoque de Gás"
        ordering = ['-criado_em']

    def __str__(self):
        sinal = "+" if self.quantidade_kg > 0 else ""
        return f"{self.get_tipo_display()} ({self.tanque.codigo}): {sinal}{self.quantidade_kg} kg @ R$ {self.custo_unitario}/kg"

    def save(self, *args, **kwargs):
        if not self._state.adding and not kwargs.pop('force', False):
            raise ValidationError("Movimento de estoque de gás é imutável: não pode ser alterado após criação.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Movimento de estoque de gás é imutável: exclusões são proibidas.")


class FechamentoPeriodoTanque(TenantAwareModel):
    """
    Fechamento do balanço de massa e apuração de perda por evaporação (boil-off) (Sprint 8C - Tarefa 6).
    Compara o saldo teórico com a medição física e gera o lançamento de perda.
    """
    tanque = models.ForeignKey(
        TanqueCriogenico,
        on_delete=models.PROTECT,
        related_name='fechamentos_periodo',
        verbose_name="Tanque Criogênico"
    )
    data_inicio = models.DateField(verbose_name="Data Inicial do Período")
    data_fim = models.DateField(verbose_name="Data Final do Período")
    saldo_inicial_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Saldo Inicial (kg)")
    total_entradas_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Total de Entradas Recebidas (kg)")
    total_consumo_envase_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Total Consumido em Envase (kg)")
    saldo_final_calculado_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Saldo Final Teórico Calculado (kg)")
    saldo_final_medido_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Saldo Final Medido Fisicamente (kg)")
    perda_evaporacao_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Perda por Evaporação / Boil-off (kg)")
    perda_evaporacao_pct = models.DecimalField(max_digits=6, decimal_places=4, verbose_name="Perda Percentual de Boil-off (%)")
    custo_perda = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Custo Total da Perda (R$)")
    excedeu_tolerancia = models.BooleanField(default=False, verbose_name="Perda Excedeu Tolerância Normativa")
    justificativa = models.TextField(blank=True, default='', verbose_name="Justificativa Técnica da Divergência")
    movimento_perda = models.ForeignKey(
        MovimentoEstoqueGas,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='fechamento_origem',
        verbose_name="Movimento de Estoque Gerado"
    )
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='fechamentos_tanque_executados',
        verbose_name="Fechado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora do Fechamento")

    class Meta:
        verbose_name = "Fechamento de Período de Tanque"
        verbose_name_plural = "Fechamentos de Períodos de Tanques"
        ordering = ['-data_fim', '-criado_em']

    def __str__(self):
        return f"Fechamento {self.tanque.codigo} ({self.data_inicio} a {self.data_fim}): Perda {self.perda_evaporacao_kg} kg"


class CustoEnergiaRampa(TenantAwareModel):
    """
    Parametrização e registro mensal de custos de energia elétrica da rampa de envase (Sprint 8C - Tarefa 7).
    """
    filial = models.ForeignKey(
        'core.Filial',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='custos_energia_rampa',
        verbose_name="Filial / Planta"
    )
    mes_ano = models.CharField(max_length=7, verbose_name="Mês/Ano de Competência (AAAA-MM)")
    kwh_consumido = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'), verbose_name="Consumo Elétrico da Rampa (kWh)")
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Total da Fatura (R$)")
    kwh_por_kg_padrao = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('0.1500'),
        verbose_name="Consumo Específico Padrão (kWh/kg)",
        help_text="Consumo elétrico estimado para compressão e bombeamento de 1 kg de gás."
    )
    custo_kwh_estimado = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('0.8500'),
        verbose_name="Custo Estimado do kWh (R$/kWh)"
    )
    reconciliado = models.BooleanField(default=False, verbose_name="Fatura Consolidada e Reconciliada")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Custo de Energia da Rampa"
        verbose_name_plural = "Custos de Energia da Rampa"
        ordering = ['-mes_ano']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'filial', 'mes_ano'], name='uniq_custo_energia_tenant_filial_mes')
        ]

    def __str__(self):
        return f"Energia Rampa {self.mes_ano}: R$ {self.valor_total} ({self.kwh_consumido} kWh)"


class CustoLoteEnvaseQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Custo de lote de envase é imutável: atualizações em lote são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Custo de lote de envase é imutável: exclusões são proibidas.")


class CustoLoteEnvaseManager(TenantManager.from_queryset(CustoLoteEnvaseQuerySet)):
    pass


class UnscopedCustoLoteEnvaseQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Custo de lote de envase é imutável: atualizações em lote são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Custo de lote de envase é imutável: exclusões são proibidas.")


class UnscopedCustoLoteEnvaseManager(models.Manager.from_queryset(UnscopedCustoLoteEnvaseQuerySet)):
    pass


class CustoLoteEnvase(TenantAwareModel):
    """
    Apurador do custo industrial do lote de envase (Sprint 8C - Tarefa 7 / Correção F-20).
    Apropria custo de gás a granel (custo médio móvel), perda rateada de rampa,
    energia elétrica e mão de obra de envase.
    Imutável: correção exige estorno formal e recálculo.
    """
    lote = models.OneToOneField(
        LoteEnvase,
        on_delete=models.PROTECT,
        related_name='custo_apurado',
        verbose_name="Lote de Envase"
    )
    tanque_origem = models.ForeignKey(
        TanqueCriogenico,
        on_delete=models.PROTECT,
        related_name='custos_lotes',
        verbose_name="Tanque de Origem do Gás"
    )
    massa_gas_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Massa Total de Gás Envasada (kg)")
    custo_gas = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Custo da Matéria-Prima / Gás (R$)")
    custo_perda_rateada = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo de Perda Rateada / Purga (R$)")
    custo_energia = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo Estimado de Energia Elétrica (R$)")
    custo_mao_de_obra = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo de Mão de Obra de Envase (R$)")
    custo_total = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Custo Industrial Total do Lote (R$)")
    quantidade_cilindros = models.PositiveIntegerField(default=1, verbose_name="Total de Cilindros Envasados")
    custo_por_cilindro = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Custo Médio Industrial por Cilindro (R$)")
    custo_por_kg = models.DecimalField(max_digits=14, decimal_places=4, verbose_name="Custo Médio Efetivo por kg (R$/kg)")
    estornado = models.BooleanField(default=False, verbose_name="Estornado")
    data_estorno = models.DateTimeField(null=True, blank=True, verbose_name="Data do Estorno")
    motivo_estorno = models.TextField(blank=True, default='', verbose_name="Motivo do Estorno")
    usuario_estorno = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='custos_lotes_estornados',
        verbose_name="Estornado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = CustoLoteEnvaseManager()
    unscoped = UnscopedCustoLoteEnvaseManager()

    class Meta:
        verbose_name = "Custo de Lote de Envase"
        verbose_name_plural = "Custos de Lotes de Envase"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Custo Lote {self.lote.codigo_lote}: R$ {self.custo_total} (R$ {self.custo_por_cilindro}/cil)"

    def save(self, *args, **kwargs):
        if not self._state.adding and not kwargs.pop('force', False):
            # Permite atualizar apenas na transição de estorno
            if not kwargs.get('update_fields') or 'estornado' not in kwargs.get('update_fields'):
                raise ValidationError("Custo de lote de envase é imutável: alterações não são permitidas após a criação.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Custo de lote de envase é imutável: exclusões são proibidas.")


class MovimentoEstoqueProdutoQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Movimento de estoque de produto acabado é imutável: atualizações em lote são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Movimento de estoque de produto acabado é imutável: exclusões são proibidas.")


class MovimentoEstoqueProdutoManager(TenantManager.from_queryset(MovimentoEstoqueProdutoQuerySet)):
    pass


class UnscopedMovimentoEstoqueProdutoQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Movimento de estoque de produto acabado é imutável: atualizações em lote são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Movimento de estoque de produto acabado é imutável: exclusões são proibidas.")


class UnscopedMovimentoEstoqueProdutoManager(models.Manager.from_queryset(UnscopedMovimentoEstoqueProdutoQuerySet)):
    pass


class MovimentoEstoqueProduto(TenantAwareModel):
    """
    Ledger financeiro e quantitativo do estoque de produtos acabados (Sprint 8C - Tarefa 8).
    Valorizado por filial e SKU/produto sob método do custo médio ponderado móvel.
    Imutável e append-only.
    """
    TIPO_CHOICES = [
        ('ENTRADA_PRODUCAO', 'Entrada por Envase / Produção'),
        ('ENTRADA_COMPRA', 'Entrada por Compra para Revenda'),
        ('SAIDA_VENDA', 'Saída por Venda Faturada'),
        ('PERDA', 'Perda / Avaria'),
        ('AJUSTE', 'Ajuste de Inventário'),
    ]

    filial = models.ForeignKey(
        'core.Filial',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimentos_estoque_produto',
        verbose_name="Filial / Depósito"
    )
    sku = models.ForeignKey(
        SkuRecarga,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimentos_estoque',
        verbose_name="SKU de Recarga"
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimentos_estoque',
        verbose_name="Produto (Legado)"
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, verbose_name="Tipo de Movimentação")
    quantidade = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Quantidade Movimentada com Sinal"
    )
    custo_unitario = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Custo Unitário Aplicado (R$)"
    )
    custo_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Custo Total da Movimentação (R$)"
    )
    saldo_quantidade_apos = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Saldo em Quantidade Após Movimento"
    )
    saldo_valor_apos = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Saldo em Valor Após Movimento (R$)"
    )
    custo_medio_apos = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Custo Médio Ponderado Unitário Após Movimento (R$)"
    )
    origem_tipo = models.CharField(max_length=50, blank=True, default='', verbose_name="Tipo de Origem")
    origem_id = models.CharField(max_length=50, blank=True, default='', verbose_name="ID da Origem")
    justificativa = models.TextField(blank=True, default='', verbose_name="Justificativa")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora do Lançamento")

    objects = MovimentoEstoqueProdutoManager()
    unscoped = UnscopedMovimentoEstoqueProdutoManager()

    class Meta:
        verbose_name = "Movimento de Estoque de Produto Acabado"
        verbose_name_plural = "Movimentos de Estoque de Produtos Acabados"
        ordering = ['-criado_em']

    def __str__(self):
        sinal = "+" if self.quantidade > 0 else ""
        item_nome = self.sku.nome_comercial if self.sku else (self.produto.nome if self.produto else "Item")
        return f"{self.get_tipo_display()} ({item_nome}): {sinal}{self.quantidade} @ R$ {self.custo_unitario}"

    def save(self, *args, **kwargs):
        if not self._state.adding and not kwargs.pop('force', False):
            raise ValidationError("Movimento de estoque de produto acabado é imutável: não pode ser alterado após criação.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Movimento de estoque de produto acabado é imutável: exclusões são proibidas.")


