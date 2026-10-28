import hashlib
import uuid
from decimal import Decimal
from datetime import timedelta, date
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from core.tenancy import TenantAwareModel
from core.money import quantize

def veiculo_foto_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    return f"veiculos/{tenant_id}/fotos/{random_name}.{ext}"

def veiculo_miniatura_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    return f"veiculos/{tenant_id}/miniaturas/{random_name}.{ext}"

def veiculo_documento_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'pdf'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    return f"veiculos/{tenant_id}/documentos/{random_name}.{ext}"

def abastecimento_comprovante_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    ano_mes = timezone.now().strftime('%Y/%m')
    return f"abastecimentos/{tenant_id}/{ano_mes}/{random_name}.{ext}"

def os_anexo_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'pdf'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    return f"ordens_servico/{tenant_id}/{instance.os_id or 'geral'}/{random_name}.{ext}"

def checklist_foto_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    return f"checklists/{tenant_id}/{random_name}.{ext}"

def validacao_evidencia_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    val_id = str(instance.validacao_id) if instance.validacao_id else 'temp'
    return f"validacoes/{tenant_id}/{val_id}/{random_name}.{ext}"

def custo_viagem_comprovante_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'pdf'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    return f"custos_viagem/{tenant_id}/{random_name}.{ext}"


class Veiculo(TenantAwareModel):
    STATUS_CHOICES = [
        ('Ativo', 'Ativo'),
        ('Em Manutenção', 'Em Manutenção'),
        ('Sinistrado', 'Sinistrado'),
        ('Inativo', 'Inativo'),
    ]

    STATUS_ATIVO_CHOICES = [
        ('Ativo', 'Ativo'),
        ('Em Manutenção', 'Em Manutenção'),
        ('Sinistrado', 'Sinistrado'),
        ('Reserva', 'Reserva'),
        ('Baixado', 'Baixado'),
    ]

    LOCALIZACAO_CHOICES = [
        ('Base', 'Base'),
        ('Oficina', 'Oficina'),
        ('Em Rota', 'Em Rota'),
    ]

    COMBUSTIVEL_CHOICES = [
        ('Diesel S10', 'Diesel S10'),
        ('Diesel S500', 'Diesel S500'),
        ('Gasolina', 'Gasolina'),
        ('Etanol', 'Etanol'),
        ('Flex', 'Flex'),
        ('GNV', 'GNV'),
        ('Elétrico', 'Elétrico'),
    ]

    FIPE_TIPO_CHOICES = [
        ('caminhoes', 'Caminhões e Micro-ônibus'),
        ('carros', 'Carros e Utilitários'),
        ('motos', 'Motos'),
    ]

    # Identificação Básica
    placa = models.CharField(max_length=10, verbose_name="Placa")
    modelo = models.CharField(max_length=100, verbose_name="Modelo")
    marca = models.CharField(max_length=100, verbose_name="Marca")
    ano = models.IntegerField(verbose_name="Ano")
    capacidade_carga = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Capacidade de Carga (kg)")
    capacidade_carga_kg = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Capacidade de Carga Líquida (kg)")
    tara_veiculo_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Tara do Veículo (kg)")
    rntrc_antt = models.CharField(max_length=30, null=True, blank=True, verbose_name="RNTRC ANTT")
    rntrc = models.CharField(max_length=30, blank=True, default='', verbose_name="RNTRC")
    civ_validade = models.DateField(null=True, blank=True, verbose_name="Validade CIV (Certificado de Inspeção Veicular)")
    cipp_validade = models.DateField(null=True, blank=True, verbose_name="Validade CIPP (Certificado de Inspeção para Produtos Perigosos)")
    motorista_padrao = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='veiculos_padrao', verbose_name="Motorista Padrão")
    filial = models.ForeignKey('core.Filial', on_delete=models.PROTECT, null=True, blank=True, related_name='veiculos', verbose_name="Filial")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Ativo')
    localizacao_atual = models.CharField(max_length=50, choices=LOCALIZACAO_CHOICES, default='Base')

    # Dados Cadastrais Expandidos de Ativo
    chassi = models.CharField(max_length=30, null=True, blank=True, verbose_name="Chassi")
    renavam = models.CharField(max_length=30, null=True, blank=True, verbose_name="RENAVAM")
    ano_fabricacao = models.IntegerField(null=True, blank=True, verbose_name="Ano de Fabricação")
    ano_modelo = models.IntegerField(null=True, blank=True, verbose_name="Ano do Modelo")
    cor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Cor")
    combustivel_padrao = models.CharField(max_length=30, choices=COMBUSTIVEL_CHOICES, default='Diesel S10', null=True, blank=True, verbose_name="Combustível Padrão")
    capacidade_tanque_l = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Capacidade do Tanque (L)")
    consumo_referencia_km_l = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Consumo Referência (km/l)")
    
    # Sprint 9C (Regra 2: 3 casas decimais para quantidades físicas / volumétricas)
    capacidade_tanque_litros = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Capacidade do Tanque (Litros)")
    consumo_referencia_kml = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Consumo Referência (km/l)")
    tipo_combustivel = models.CharField(max_length=30, choices=COMBUSTIVEL_CHOICES, default='Diesel S10', null=True, blank=True, verbose_name="Tipo de Combustível")
    
    tipo_carroceria = models.CharField(max_length=100, null=True, blank=True, verbose_name="Tipo de Carroceria")
    eixos = models.PositiveSmallIntegerField(null=True, blank=True, default=2, verbose_name="Eixos")
    pbt_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Peso Bruto Total - PBT (kg)")
    odometro_atual_km = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Odômetro Atual (km)")
    data_aquisicao = models.DateField(null=True, blank=True, verbose_name="Data de Aquisição")
    valor_aquisicao = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Valor de Aquisição (R$)")
    status_ativo = models.CharField(max_length=25, choices=STATUS_ATIVO_CHOICES, default='Ativo', verbose_name="Status Operacional do Ativo")
    ativo_imobilizado = models.OneToOneField(
        'produtos.AtivoImobilizado',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='veiculo',
        verbose_name="Ativo Imobilizado Vinculado"
    )
    observacoes = models.TextField(null=True, blank=True, verbose_name="Observações Gerais")

    # Integração FIPE
    fipe_tipo = models.CharField(max_length=20, choices=FIPE_TIPO_CHOICES, null=True, blank=True, verbose_name="Tipo FIPE")
    fipe_marca_codigo = models.CharField(max_length=20, null=True, blank=True, verbose_name="Cód. Marca FIPE")
    fipe_modelo_codigo = models.CharField(max_length=20, null=True, blank=True, verbose_name="Cód. Modelo FIPE")
    fipe_ano_codigo = models.CharField(max_length=20, null=True, blank=True, verbose_name="Cód. Ano FIPE")
    fipe_codigo = models.CharField(max_length=20, null=True, blank=True, verbose_name="Código FIPE")
    fipe_marca_nome = models.CharField(max_length=100, null=True, blank=True, verbose_name="Nome da Marca FIPE")
    fipe_modelo_nome = models.CharField(max_length=150, null=True, blank=True, verbose_name="Nome do Modelo FIPE")
    fipe_valor = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Valor de Tabela FIPE (R$)")
    fipe_mes_referencia = models.CharField(max_length=50, null=True, blank=True, verbose_name="Mês de Referência FIPE")
    fipe_atualizado_em = models.DateTimeField(null=True, blank=True, verbose_name="Data Atualização FIPE")
    valor_adicionais = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Valor de Equipamentos / Adicionais (R$)")

    class Meta:
        verbose_name = "Veículo"
        verbose_name_plural = "Veículos"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'placa'], name='unique_tenant_veiculo_placa'),
            models.UniqueConstraint(
                fields=['tenant', 'chassi'],
                condition=models.Q(chassi__isnull=False) & ~models.Q(chassi=''),
                name='unique_tenant_veiculo_chassi'
            ),
        ]

    def __str__(self):
        return f"{self.placa} - {self.modelo}"

    def save(self, *args, **kwargs):
        # Sincronização de campos legados (Regra 9 - Retrocompatibilidade)
        if self.capacidade_tanque_litros is not None and self.capacidade_tanque_l is None:
            self.capacidade_tanque_l = quantize(self.capacidade_tanque_litros, 2)
        elif self.capacidade_tanque_l is not None and self.capacidade_tanque_litros is None:
            self.capacidade_tanque_litros = quantize(self.capacidade_tanque_l, 3)

        if self.consumo_referencia_kml is not None and self.consumo_referencia_km_l is None:
            self.consumo_referencia_km_l = quantize(self.consumo_referencia_kml, 2)
        elif self.consumo_referencia_km_l is not None and self.consumo_referencia_kml is None:
            self.consumo_referencia_kml = quantize(self.consumo_referencia_km_l, 3)

        if self.tipo_combustivel and not self.combustivel_padrao:
            self.combustivel_padrao = self.tipo_combustivel
        elif self.combustivel_padrao and not self.tipo_combustivel:
            self.tipo_combustivel = self.combustivel_padrao

        # Sincronização Sprint 12A
        if not self.capacidade_carga_kg and self.capacidade_carga:
            self.capacidade_carga_kg = self.capacidade_carga
        elif self.capacidade_carga_kg and not self.capacidade_carga:
            self.capacidade_carga = self.capacidade_carga_kg

        if not self.rntrc and self.rntrc_antt:
            self.rntrc = self.rntrc_antt
        elif self.rntrc and not self.rntrc_antt:
            self.rntrc_antt = self.rntrc

        super().save(*args, **kwargs)

    @property
    def valor_mercado_estimado(self):
        fipe = self.fipe_valor or Decimal('0.00')
        adic = self.valor_adicionais or Decimal('0.00')
        return quantize(fipe + adic, 2)

    @property
    def foto_principal(self):
        foto = self.fotos.filter(principal=True).first()
        if not foto:
            foto = self.fotos.first()
        return foto

    @property
    def tem_os_imobilizante_aberta(self):
        """Indica se o veículo possui alguma OS ativa que imobilize o veículo na oficina."""
        if hasattr(self, '_tem_os_imobilizante'):
            return bool(self._tem_os_imobilizante)
        if hasattr(self, 'ordens_servico'):
            return self.ordens_servico.filter(
                imobiliza_veiculo=True,
                status__in=['Aberta', 'Orçada', 'Aprovada', 'Em Execução']
            ).exists()
        return False


class LeituraOdometro(TenantAwareModel):
    """
    Registro histórico e auditável de leituras de odômetro por veículo (Sprint 9C - Tarefa 1).
    Permite validar monotonicidade (odômetro não pode regredir) e apurar consumo real.
    """
    ORIGEM_CHOICES = [
        ('ROTA', 'Rota de Campo'),
        ('ABASTECIMENTO', 'Abastecimento'),
        ('MANUTENCAO', 'Ordem de Manutenção'),
    ]

    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.CASCADE,
        related_name='leituras_odometro',
        verbose_name="Veículo"
    )
    km = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        verbose_name="Quilometragem (km)"
    )
    data_hora = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Data/Hora da Leitura"
    )
    origem = models.CharField(
        max_length=20,
        choices=ORIGEM_CHOICES,
        default='ROTA',
        verbose_name="Origem da Leitura"
    )
    validada = models.BooleanField(
        default=True,
        verbose_name="Leitura Validada"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Leitura de Odômetro"
        verbose_name_plural = "Leituras de Odômetro"
        ordering = ['-data_hora', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'veiculo', 'data_hora', 'origem'],
                name='uniq_leitura_odometro'
            )
        ]

    def __str__(self):
        return f"{self.veiculo.placa} - {self.km} km ({self.origem} em {self.data_hora})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.validada and self.km:
            if not self.veiculo.odometro_atual_km or self.km > self.veiculo.odometro_atual_km:
                self.veiculo.odometro_atual_km = quantize(self.km, 2)
                self.veiculo.save(update_fields=['odometro_atual_km'])


class VeiculoFoto(TenantAwareModel):
    TIPO_CHOICES = [
        ('Frente', 'Frente'),
        ('Traseira', 'Traseira'),
        ('Lateral Esquerda', 'Lateral Esquerda'),
        ('Lateral Direita', 'Lateral Direita'),
        ('Painel/Odômetro', 'Painel/Odômetro'),
        ('Documento', 'Documento'),
        ('Avaria', 'Avaria'),
        ('Outra', 'Outra'),
    ]

    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='fotos', verbose_name="Veículo")
    imagem = models.ImageField(upload_to=veiculo_foto_upload_path, verbose_name="Foto do Veículo")
    miniatura = models.ImageField(upload_to=veiculo_miniatura_upload_path, null=True, blank=True, verbose_name="Miniatura")
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, default='Outra', verbose_name="Tipo da Foto")
    principal = models.BooleanField(default=False, verbose_name="Foto Principal")
    tirada_em = models.DateTimeField(null=True, blank=True, default=timezone.now, verbose_name="Tirada em")
    enviada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Enviada por")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Foto do Veículo"
        verbose_name_plural = "Fotos do Veículo"
        ordering = ['-principal', '-criado_em']

    def clean(self):
        super().clean()
        if self.imagem:
            # Limite de 5 MB
            if hasattr(self.imagem, 'size') and self.imagem.size > 5 * 1024 * 1024:
                raise ValidationError("O tamanho máximo da foto permitido é de 5 MB.")
            # Validação real de arquivo de imagem via Pillow
            try:
                from PIL import Image
                if hasattr(self.imagem, 'seek'):
                    self.imagem.seek(0)
                img = Image.open(self.imagem)
                img.verify()
                if img.format not in ['JPEG', 'PNG', 'WEBP']:
                    raise ValidationError(f"Formato de imagem inválido: {img.format}. Formatos suportados: JPEG, PNG, WEBP.")
                if hasattr(self.imagem, 'seek'):
                    self.imagem.seek(0)
            except Exception as e:
                if isinstance(e, ValidationError):
                    raise
                raise ValidationError(f"Arquivo de imagem inválido ou corrompido: {str(e)}")

    def save(self, *args, **kwargs):
        self.clean()
        # Se marcada como principal, desmarca outras fotos deste veículo no mesmo tenant
        if self.principal and self.veiculo_id:
            VeiculoFoto.objects.filter(veiculo_id=self.veiculo_id, principal=True).exclude(pk=self.pk).update(principal=False)

        # Gerar miniatura proporcional de 320px com Pillow se ainda não gerada
        if self.imagem and not self.miniatura:
            try:
                from PIL import Image
                import io
                from django.core.files.base import ContentFile
                if hasattr(self.imagem, 'seek'):
                    self.imagem.seek(0)
                img = Image.open(self.imagem)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')

                max_width = 320
                if img.width > max_width:
                    w_percent = (max_width / float(img.width))
                    h_size = int((float(img.height) * float(w_percent)))
                    img = img.resize((max_width, h_size), Image.Resampling.LANCZOS)

                thumb_io = io.BytesIO()
                img.save(thumb_io, format='JPEG', quality=85)
                thumb_filename = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
                self.miniatura.save(thumb_filename, ContentFile(thumb_io.getvalue()), save=False)
            except Exception:
                pass

        super().save(*args, **kwargs)


class VeiculoDocumento(TenantAwareModel):
    TIPO_DOCUMENTO_CHOICES = [
        ('CRLV', 'CRLV'),
        ('Seguro Obrigatório', 'Seguro Obrigatório'),
        ('RNTRC', 'RNTRC'),
        ('CIPP/CIV', 'CIPP/CIV (produtos perigosos)'),
        ('Licença Ambiental', 'Licença Ambiental'),
        ('Laudo/Inspeção', 'Laudo/Inspeção'),
        ('Outro', 'Outro'),
    ]

    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='documentos', verbose_name="Veículo")
    tipo = models.CharField(max_length=50, choices=TIPO_DOCUMENTO_CHOICES, verbose_name="Tipo de Documento")
    numero = models.CharField(max_length=100, null=True, blank=True, verbose_name="Número do Documento")
    emissao = models.DateField(null=True, blank=True, verbose_name="Data de Emissão")
    vencimento = models.DateField(null=True, blank=True, verbose_name="Data de Vencimento")
    arquivo = models.FileField(upload_to=veiculo_documento_upload_path, null=True, blank=True, verbose_name="Arquivo Digitalizado")
    observacoes = models.TextField(null=True, blank=True, verbose_name="Observações")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Enviado por")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Documento do Veículo"
        verbose_name_plural = "Documentos do Veículo"
        ordering = ['vencimento', 'tipo']

    def clean(self):
        super().clean()
        if self.arquivo:
            if hasattr(self.arquivo, 'size') and self.arquivo.size > 5 * 1024 * 1024:
                raise ValidationError("O tamanho máximo do arquivo de documento permitido é de 5 MB.")
            ext = self.arquivo.name.split('.')[-1].lower() if '.' in self.arquivo.name else ''
            if ext not in ['pdf', 'jpg', 'jpeg', 'png']:
                raise ValidationError("Formato de arquivo não suportado. Extensões permitidas: PDF, JPG, PNG.")

    @property
    def situacao(self):
        if not self.vencimento:
            return 'Sem Vencimento'
        hoje = timezone.localdate()
        dias_aviso = 30
        if self.vencimento < hoje:
            return 'Vencido'
        elif self.vencimento <= hoje + timezone.timedelta(days=dias_aviso):
            dias_restantes = (self.vencimento - hoje).days
            return f"Vence em até {dias_restantes} dias"
        return 'Em dia'

    @property
    def dias_para_vencer(self):
        if not self.vencimento:
            return None
        hoje = timezone.localdate()
        return (self.vencimento - hoje).days


class DocumentoObrigatorioVeiculo(TenantAwareModel):
    """
    Configuração por Tenant dos tipos de documentos obrigatórios para que um veículo
    esteja apto à operação logística.
    Nota de Conformidade: O padrão sugerido pelo sistema é CRLV + RNTRC + CIPP/CIV,
    mas a lista oficial e particularidades regionais devem ser confirmadas com o
    Responsável Técnico e setor de conformidade regulatória da distribuidora.
    """
    tipo = models.CharField(max_length=50, verbose_name="Tipo de Documento Obrigatório")
    ativo = models.BooleanField(default=True, verbose_name="Obrigatório Ativo")
    dias_aviso_vencimento = models.PositiveIntegerField(default=30, verbose_name="Dias para Aviso de Vencimento")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Documento Obrigatório de Veículo"
        verbose_name_plural = "Documentos Obrigatórios de Veículos"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'tipo'], name='unique_tenant_documento_obrigatorio')
        ]

    def __str__(self):
        return f"{self.tipo} ({'Ativo' if self.ativo else 'Inativo'})"


class VeiculoValorFipe(TenantAwareModel):
    """
    Histórico mensal de snapshots do valor FIPE do veículo para cálculo de depreciação e
    evolução patrimonial sem custos recorrentes de API externa.
    """
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='historico_fipe', verbose_name="Veículo")
    mes_referencia = models.CharField(max_length=50, verbose_name="Mês de Referência")
    valor = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Valor FIPE (R$)")
    registrado_em = models.DateTimeField(auto_now_add=True, verbose_name="Registrado em")

    class Meta:
        verbose_name = "Histórico de Valor FIPE"
        verbose_name_plural = "Históricos de Valor FIPE"
        ordering = ['-registrado_em']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'veiculo', 'mes_referencia'], name='unique_tenant_veiculo_mes_fipe')
        ]

    def __str__(self):
        return f"{self.veiculo.placa} - {self.mes_referencia}: R$ {self.valor}"


class LogExcecaoOperacionalVeiculo(TenantAwareModel):
    """
    Registro imutável de auditoria quando um Gestor (Admin ou Gerente) autoriza a operação
    de um veículo com pendência operacional/documental em uma entrega.
    """
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='logs_excecao', verbose_name="Veículo")
    entrega = models.ForeignKey('Entrega', on_delete=models.SET_NULL, null=True, blank=True, related_name='logs_excecao_veiculo', verbose_name="Entrega")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Gestor Autorizador")
    data_hora = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora da Liberação")
    motivos_bloqueio = models.JSONField(default=list, verbose_name="Motivos Originais do Bloqueio")
    justificativa = models.TextField(verbose_name="Justificativa Operacional do Gestor")

    class Meta:
        verbose_name = "Log de Exceção Operacional de Veículo"
        verbose_name_plural = "Logs de Exceções Operacionais de Veículos"
        ordering = ['-data_hora']

    def __str__(self):
        return f"Exceção {self.veiculo.placa} por {self.usuario.username} em {self.data_hora.strftime('%d/%m/%Y %H:%M')}"


class Rota(TenantAwareModel):
    nome = models.CharField(max_length=150, verbose_name="Nome da Rota")
    origem = models.CharField(max_length=200, verbose_name="Origem")
    destino = models.CharField(max_length=200, verbose_name="Destino")
    distancia_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Distância (km)")
    tempo_estimado_horas = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Tempo Estimado (h)")
    tempo_estimado_min = models.PositiveIntegerField(null=True, blank=True, verbose_name="Tempo Estimado (min)")
    observacoes_rota = models.TextField(null=True, blank=True, verbose_name="Observações da Rota")
    ativa = models.BooleanField(default=True, verbose_name="Ativa")

    class Meta:
        verbose_name = "Rota"
        verbose_name_plural = "Rotas"

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if self.tempo_estimado_min and not self.tempo_estimado_horas:
            self.tempo_estimado_horas = (Decimal(str(self.tempo_estimado_min)) / Decimal('60.0')).quantize(Decimal('0.01'))
        elif self.tempo_estimado_horas and not self.tempo_estimado_min:
            self.tempo_estimado_min = int(self.tempo_estimado_horas * 60)
        super().save(*args, **kwargs)

class ManutencaoFrota(TenantAwareModel):
    STATUS_MANUTENCAO = [
        ('Agendada', 'Agendada'),
        ('Em Progresso', 'Em Progresso'),
        ('Concluída', 'Concluída'),
    ]

    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='manutencoes')
    data_manutencao = models.DateField(verbose_name="Data da Manutenção")
    descricao = models.TextField(verbose_name="Descrição do Serviço")
    custo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Custo Total (R$)")
    status = models.CharField(max_length=20, choices=STATUS_MANUTENCAO, default='Agendada')

    class Meta:
        verbose_name = "Manutenção de Frota"
        verbose_name_plural = "Manutenções de Frota"

    def __str__(self):
        return f"Manutenção {self.veiculo.placa} em {self.data_manutencao}"

class TabelaFrete(TenantAwareModel):
    TIPO_COBRANCA = [
        ('Fixo', 'Valor Fixo por Rota'),
        ('Distancia', 'Por Km Rodado'),
        ('Peso', 'Por Peso (kg)'),
    ]

    rota = models.ForeignKey(Rota, on_delete=models.CASCADE, null=True, blank=True, related_name='fretes', help_text="Selecione a rota caso seja valor fixo por rota.")
    tipo_cobranca = models.CharField(max_length=20, choices=TIPO_COBRANCA, default='Fixo')
    valor = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor de Cobrança (R$)")

    class Meta:
        verbose_name = "Tabela de Frete"
        verbose_name_plural = "Tabelas de Frete"

    def __str__(self):
        if self.rota:
            return f"Frete para {self.rota.nome} - R$ {self.valor}"
        return f"Frete por {self.tipo_cobranca} - R$ {self.valor}"


class Entrega(TenantAwareModel):
    STATUS_ENTREGA = [
        ('Agendada', 'Agendada'),
        ('Em Produção', 'Em Produção'),
        ('Em Rota', 'Em Rota'),
        ('Concluída', 'Concluída'),
        ('Cancelada', 'Cancelada'),
    ]

    veiculo = models.ForeignKey(Veiculo, on_delete=models.SET_NULL, null=True, blank=True, related_name='entregas', verbose_name="Veículo")
    rota = models.ForeignKey(Rota, on_delete=models.SET_NULL, null=True, blank=True, related_name='entregas', verbose_name="Rota")
    motorista = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='entregas_motorista', verbose_name="Motorista")
    data_saida = models.DateTimeField(null=True, blank=True, verbose_name="Data de Saída")
    status = models.CharField(max_length=20, choices=STATUS_ENTREGA, default='Agendada')
    token_rastreio = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name="Token de Rastreio Público")
    filial = models.ForeignKey('core.Filial', on_delete=models.PROTECT, null=True, blank=True, related_name='entregas', verbose_name="Filial")
    
    class Meta:
        verbose_name = "Entrega"
        verbose_name_plural = "Entregas"

    def __str__(self):
        rota_nome = self.rota.nome if self.rota else 'Sem Rota'
        return f"Entrega #{self.id} - {rota_nome} ({self.status})"

    @property
    def nome_motorista(self):
        if self.motorista:
            return self.motorista.get_full_name() or self.motorista.username
        return "Motorista Designado"

    @property
    def placa_mascarada(self):
        if not self.veiculo or not self.veiculo.placa:
            return "Veículo em Trânsito"
        p = self.veiculo.placa.replace("-", "").strip()
        if len(p) >= 7:
            return f"{p[:3]}-***{p[-1]}"
        elif len(p) >= 4:
            return f"{p[:3]}-*"
        return "***-****"

    def clean(self):
        super().clean()
        if not self.pk:
            return
        if self.status == 'Em Rota' and self.veiculo and self.veiculo.capacidade_carga and float(self.veiculo.capacidade_carga) > 0:
            if float(self.peso_total_carregado) > float(self.veiculo.capacidade_carga):
                raise ValidationError(
                    f"Trava de Segurança ANTT: Não é permitido iniciar rota com veículo em sobrecarga! "
                    f"Peso atual de {self.peso_total_carregado:.2f} kg excede a capacidade máxima de "
                    f"{float(self.veiculo.capacidade_carga):.2f} kg do veículo {self.veiculo.placa}."
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        if self.status == 'Concluída':
            try:
                from .services.rentabilidade import consolidar_custo_viagem
                consolidar_custo_viagem(self, congelar=True)
            except Exception:
                pass
            try:
                from fiscal.services.transporte_service import encerrar_mdfe_entrega
                encerrar_mdfe_entrega(self)
            except Exception:
                pass

    @property
    def possui_peso_estimado(self):
        """
        Retorna True se algum cilindro ou item da entrega estiver utilizando peso estimado
        (sem tara real aferida ou sem massa de gás padrão/especificada no SKU/Modelo).
        """
        if not self.pk:
            return True
        movimentacoes = self.movimentacoes_cilindros.select_related('cilindro__modelo', 'cilindro__gas_dedicado').all()
        if not movimentacoes.exists():
            return True
        for mov in movimentacoes:
            cil = mov.cilindro
            if cil.tara_real_kg is None:
                return True
            if mov.tipo in ['ENTREGA_CLIENTE', 'SAIDA_ROTA']:
                sku = cil.gas_dedicado.skus_recarga.filter(modelo_cilindro=cil.modelo).first() if cil.gas_dedicado else None
                massa = None
                if sku and sku.massa_gas_kg:
                    massa = sku.massa_gas_kg
                elif cil.modelo and cil.modelo.massa_gas_padrao_kg:
                    massa = cil.modelo.massa_gas_padrao_kg
                if massa is None:
                    return True
        return False

    @property
    def peso_total_carregado(self):
        if not self.pk:
            return 0.0
        # 1. Se há movimentações reais de cilindros (Full-for-Empty), calcula peso real com precisão física
        movimentacoes = self.movimentacoes_cilindros.select_related('cilindro__modelo', 'cilindro__gas_dedicado').all()
        if movimentacoes.exists():
            peso = 0.0
            for mov in movimentacoes:
                cil = mov.cilindro
                tara = float(cil.tara_real_kg) if cil.tara_real_kg is not None else float(cil.modelo.tara_nominal_kg or 0)
                if mov.tipo in ['ENTREGA_CLIENTE', 'SAIDA_ROTA']:
                    # Cheio: Tara Real + Massa do Gás (do SKU ou padrão do Modelo)
                    sku = cil.gas_dedicado.skus_recarga.filter(modelo_cilindro=cil.modelo).first() if cil.gas_dedicado else None
                    if sku and sku.massa_gas_kg:
                        massa_gas = float(sku.massa_gas_kg)
                    elif cil.modelo and cil.modelo.massa_gas_padrao_kg:
                        massa_gas = float(cil.modelo.massa_gas_padrao_kg)
                    else:
                        massa_gas = 10.0
                    peso += tara + massa_gas
                elif mov.tipo == 'RECOLHA_CLIENTE':
                    # Vazio: Apenas Tara Real
                    peso += tara
            return round(peso, 2)

        # 2. Fallback legado para vendas sem bipagem individual
        peso = 0
        for venda in self.vendas.exclude(status='Cancelada'):
            for item in venda.itens.all():
                peso_un = item.peso_unitario if item.peso_unitario else 1
                peso += float(item.quantidade) * float(peso_un)
        return round(peso, 2)

    @property
    def capacidade_disponivel(self):
        if not self.veiculo or not self.veiculo.capacidade_carga:
            return 0
        disp = float(self.veiculo.capacidade_carga) - self.peso_total_carregado
        return disp if disp > 0 else 0

    @property
    def percentual_lotacao(self):
        if not self.veiculo or not self.veiculo.capacidade_carga or self.veiculo.capacidade_carga == 0:
            return 0
        perc = (self.peso_total_carregado / float(self.veiculo.capacidade_carga)) * 100
        return round(perc, 1)

def default_motivos_exigem_foto():
    return ['Avaria no manuseio', 'Vazamento', 'Roubo/Extravio']


class CoordenadaRastreamento(TenantAwareModel):
    """
    Telemetria e tracking contínuo de coordenadas GPS transmitidas pelo PWA de Campo.
    Permite exibição em tempo real na Torre de Controle e no link público de rastreio ao cliente.
    """
    entrega = models.ForeignKey(
        Entrega,
        on_delete=models.CASCADE,
        related_name='coordenadas_rastreamento',
        verbose_name="Entrega"
    )
    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='coordenadas_rastreamento',
        verbose_name="Veículo"
    )
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        verbose_name="Latitude"
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        verbose_name="Longitude"
    )
    velocidade = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Velocidade (km/h)"
    )
    precisao_m = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precisão do GPS (m)"
    )
    sequencia = models.PositiveIntegerField(
        default=1,
        verbose_name="Sequência do Ponto na Rota"
    )
    client_uuid = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        verbose_name="UUID do Cliente Offline"
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Data/Hora da Captura GPS (Legado)"
    )
    capturado_em = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Data/Hora da Captura GPS"
    )
    recebido_em = models.DateTimeField(
        default=timezone.now,
        verbose_name="Data/Hora de Recepção no Servidor"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Coordenada de Rastreamento"
        verbose_name_plural = "Coordenadas de Rastreamento"
        ordering = ['capturado_em']
        indexes = [
            models.Index(fields=['tenant', 'entrega', 'capturado_em'], name='idx_coord_tenant_ent_cap')
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'entrega', 'sequencia', 'client_uuid'],
                condition=~models.Q(client_uuid=''),
                name='uniq_coord_sync_idempotente'
            )
        ]

    def save(self, *args, **kwargs):
        if not self.capturado_em and self.timestamp:
            self.capturado_em = self.timestamp
        elif self.capturado_em and not self.timestamp:
            self.timestamp = self.capturado_em
        if not self.veiculo and self.entrega and self.entrega.veiculo:
            self.veiculo = self.entrega.veiculo
        super().save(*args, **kwargs)

    def __str__(self):
        return f"GPS Entrega #{self.entrega_id} ({self.latitude}, {self.longitude}) @ {self.capturado_em}"


class ConfiguracaoValidacaoCarga(TenantAwareModel):
    """
    Configurações e alçadas de validação de carga por empresa (Tenant).
    """
    limite_ajuste_sem_aprovacao_un = models.PositiveIntegerField(
        default=1,
        verbose_name="Limite de Ajuste sem Aprovação (Unidades)",
        help_text="Ajustes com divergência absoluta acima deste limite exigem aprovação do gestor."
    )
    limite_valor_sem_aprovacao = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('100.00'),
        verbose_name="Limite de Valor de Impacto sem Aprovação (R$)",
        help_text="Ajustes com valor total em módulo acima deste limite exigem aprovação do gestor."
    )
    motivos_exigem_foto = models.JSONField(
        default=default_motivos_exigem_foto,
        blank=True,
        verbose_name="Motivos que Exigem Foto Comprobatória"
    )

    class Meta:
        verbose_name = "Configuração de Validação de Carga"
        verbose_name_plural = "Configurações de Validação de Carga"

    @classmethod
    def get_para_tenant(cls, tenant=None):
        from core.tenancy import get_current_tenant
        t = tenant or get_current_tenant()
        if not t:
            return cls(
                limite_ajuste_sem_aprovacao_un=1,
                limite_valor_sem_aprovacao=Decimal('100.00'),
                motivos_exigem_foto=['Avaria no manuseio', 'Vazamento', 'Roubo/Extravio']
            )
        config = cls.objects.filter(tenant=t).first()
        if not config:
            config = cls.objects.create(
                tenant=t,
                limite_ajuste_sem_aprovacao_un=1,
                limite_valor_sem_aprovacao=Decimal('100.00'),
                motivos_exigem_foto=['Avaria no manuseio', 'Vazamento', 'Roubo/Extravio']
            )
        return config


class ValidacaoCarga(TenantAwareModel):
    MOTIVO_CHOICES = [
        ('Avaria no manuseio', 'Avaria no manuseio'),
        ('Produto devolvido', 'Produto devolvido'),
        ('Cliente recusou', 'Cliente recusou'),
        ('Erro de separação', 'Erro de separação'),
        ('Cilindro vazio/errado', 'Cilindro vazio/errado'),
        ('Vazamento', 'Vazamento'),
        ('Roubo/Extravio', 'Roubo/Extravio'),
        ('Outro', 'Outro'),
    ]

    CATEGORIA_ITEM_CHOICES = [
        ('Cheio', 'Cheio'),
        ('Vazio (retorno)', 'Vazio (retorno)'),
        ('Casco novo', 'Casco novo'),
        ('Outro', 'Outro'),
    ]

    STATUS_CHOICES = [
        ('Registrada', 'Registrada'),
        ('Pendente de Aprovação', 'Pendente de Aprovação'),
        ('Aprovada', 'Aprovada'),
        ('Rejeitada', 'Rejeitada'),
    ]

    entrega = models.ForeignKey(Entrega, on_delete=models.CASCADE, related_name='validacoes', null=True, blank=True)
    venda = models.ForeignKey('vendas.Venda', on_delete=models.CASCADE, related_name='validacoes')
    produto = models.ForeignKey('produtos.Produto', on_delete=models.CASCADE)
    quantidade_alterada = models.IntegerField(default=0, verbose_name="Qtd Alterada (+ ou -)")
    etapa_logistica = models.CharField(max_length=50, default='Separação / Envase', verbose_name="Etapa Logística")
    justificativa = models.TextField(verbose_name="Justificativa")
    data_hora = models.DateTimeField(auto_now_add=True)

    # Novos campos SPRINT L4
    motivo = models.CharField(max_length=50, choices=MOTIVO_CHOICES, default='Outro', verbose_name="Motivo")
    categoria_item = models.CharField(max_length=30, choices=CATEGORIA_ITEM_CHOICES, default='Cheio', verbose_name="Categoria do Item")
    quantidade_esperada = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Quantidade Esperada")
    quantidade_conferida = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Quantidade Conferida")
    diferenca = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Diferença Calculada")
    valor_impacto = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor de Impacto (R$)")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Registrada', verbose_name="Status")
    exige_aprovacao = models.BooleanField(default=False, verbose_name="Exige Aprovação")
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='validacoes_aprovadas', verbose_name="Aprovado por")
    aprovado_em = models.DateTimeField(null=True, blank=True, verbose_name="Aprovado em")
    observacao_aprovacao = models.TextField(blank=True, null=True, verbose_name="Observação da Aprovação")
    dispositivo_ip = models.CharField(max_length=100, blank=True, null=True, verbose_name="Dispositivo / IP")
    valida_anterior = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='correcoes', verbose_name="Validação Anterior (Correção)")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='validacoes_criadas', verbose_name="Criado por")
    sugere_sinistro = models.BooleanField(default=False, verbose_name="Sugere Abertura de Sinistro")

    class Meta:
        verbose_name = "Validação de Carga"
        verbose_name_plural = "Validações de Carga"
        ordering = ['-data_hora']

    def __str__(self):
        return f"Validação Venda #{self.venda_id} - {self.diferenca}x {self.produto.nome} ({self.status})"

    def clean(self):
        super().clean()
        if self.quantidade_conferida is not None and self.quantidade_conferida < 0:
            raise ValidationError({'quantidade_conferida': "A quantidade conferida não pode ser negativa."})

        if self.entrega and self.entrega.status in ['Concluída', 'Cancelada']:
            raise ValidationError("Não é permitido validar carga de entrega já concluída ou cancelada.")

        # Justificativa mínima para 'Outro' (ao menos 15 caracteres)
        if self.motivo == 'Outro' and (not self.justificativa or len(self.justificativa.strip()) < 15):
            raise ValidationError({'justificativa': "Para o motivo 'Outro', a justificativa deve conter no mínimo 15 caracteres."})

    def save(self, *args, **kwargs):
        # Sincroniza diferenca e quantidade_alterada
        if self.quantidade_conferida is not None and self.quantidade_esperada is not None:
            self.diferenca = Decimal(str(self.quantidade_conferida)) - Decimal(str(self.quantidade_esperada))
            self.quantidade_alterada = int(self.diferenca)

        # Regra de sugestão de sinistro
        if self.motivo in ['Roubo/Extravio', 'Vazamento']:
            self.sugere_sinistro = True

        # Validação de Imutabilidade
        if self.pk:
            orig = ValidacaoCarga.unscoped.filter(pk=self.pk).first()
            if orig:
                if orig.status in ['Aprovada', 'Rejeitada']:
                    raise ValidationError("Validação finalizada é imutável e não pode ser editada. Emita uma nova validação apontando para a anterior.")
                
                # Se estava Pendente ou Registrada, só pode alterar status e dados de aprovação
                campos_bloqueados = [
                    'entrega_id', 'venda_id', 'produto_id', 'motivo', 'categoria_item',
                    'quantidade_esperada', 'quantidade_conferida', 'diferenca', 'valor_impacto',
                    'valida_anterior_id'
                ]
                for campo in campos_bloqueados:
                    if getattr(self, campo) != getattr(orig, campo):
                        raise ValidationError(f"O campo '{campo}' não pode ser alterado após o registro da validação. Registros são imutáveis.")

        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Validações de carga são registros auditáveis e imutáveis e não podem ser excluídas.")


class ValidacaoCargaEvidencia(TenantAwareModel):
    """
    Evidência fotográfica ou documental vinculada a uma validação de carga.
    """
    validacao = models.ForeignKey(ValidacaoCarga, on_delete=models.CASCADE, related_name='evidencias', verbose_name="Validação de Carga")
    arquivo = models.FileField(upload_to=validacao_evidencia_upload_path, verbose_name="Arquivo / Foto")
    tirada_em = models.DateTimeField(default=timezone.now, verbose_name="Tirada em")
    descricao = models.CharField(max_length=255, blank=True, default='', verbose_name="Descrição")

    class Meta:
        verbose_name = "Evidência de Validação de Carga"
        verbose_name_plural = "Evidências de Validação de Carga"
        ordering = ['-tirada_em']

    def clean(self):
        super().clean()
        if self.arquivo:
            if hasattr(self.arquivo, 'size') and self.arquivo.size > 15 * 1024 * 1024:
                raise ValidationError("O tamanho máximo da foto/evidência permitido é de 15 MB.")
            ext = self.arquivo.name.split('.')[-1].lower() if '.' in self.arquivo.name else ''
            if ext not in ['jpg', 'jpeg', 'png', 'webp', 'pdf']:
                raise ValidationError(f"Formato de arquivo .{ext} inválido. Extensões permitidas: JPG, PNG, WEBP, PDF.")

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.validacao_id:
            try:
                self.tenant_id = self.validacao.tenant_id
            except Exception:
                pass
        self.clean()
        super().save(*args, **kwargs)


# ==============================================================================
# COMPROVANTE ELETRÔNICO DE ENTREGA E ASSINATURA DIGITAL (SPRINT 6)
# ==============================================================================

class ComprovanteEntrega(TenantAwareModel):
    """
    Comprovante eletrônico bilateral de entrega de cilindros ao cliente.
    Captura assinatura digitalizada, dados do recebedor, geolocalização e hash SHA-256
    vinculado de forma estrita e imutável à movimentação do ledger.
    """
    entrega = models.ForeignKey(
        Entrega,
        on_delete=models.CASCADE,
        related_name='comprovantes',
        verbose_name="Romaneio / Entrega"
    )
    movimentacao = models.ForeignKey(
        'produtos.MovimentacaoCilindro',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comprovantes',
        verbose_name="Movimentação do Cilindro (Legado)"
    )
    movimentacoes = models.ManyToManyField(
        'produtos.MovimentacaoCilindro',
        related_name='comprovantes_vinculados',
        blank=True,
        verbose_name="Movimentações dos Cilindros Vinculadas"
    )
    recebedor_nome = models.CharField(max_length=255, verbose_name="Nome Completo do Recebedor")
    recebedor_documento = models.CharField(max_length=50, verbose_name="Documento do Recebedor (CPF/RG)")
    assinatura_imagem = models.FileField(upload_to='comprovantes_assinaturas/', verbose_name="Assinatura Digitalizada")
    timestamp_captura = models.DateTimeField(default=timezone.now, verbose_name="Data/Hora da Captura")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="Latitude")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="Longitude")
    hash_integridade_sha256 = models.CharField(max_length=64, verbose_name="Hash SHA-256 de Integridade")

    class Meta:
        verbose_name = "Comprovante de Entrega Eletrônico"
        verbose_name_plural = "Comprovantes de Entregas Eletrônicos"
        ordering = ['-timestamp_captura']

    def __str__(self):
        return f"Comprovante Entrega #{self.entrega_id} - {self.recebedor_nome} ({self.timestamp_captura.strftime('%d/%m/%Y %H:%M')})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Comprovante de entrega é imutável e não pode ser alterado após registro.")
        if not self.hash_integridade_sha256:
            raw_data = f"{self.tenant_id}|{self.entrega_id}|{self.movimentacao_id}|{self.recebedor_nome}|{self.recebedor_documento}|{self.timestamp_captura.isoformat() if self.timestamp_captura else ''}|{self.latitude}|{self.longitude}"
            hasher = hashlib.sha256(raw_data.encode('utf-8'))
            if self.assinatura_imagem:
                try:
                    self.assinatura_imagem.open('rb')
                    hasher.update(self.assinatura_imagem.read())
                    self.assinatura_imagem.seek(0)
                except Exception:
                    pass
            self.hash_integridade_sha256 = hasher.hexdigest()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Comprovante de entrega é imutável e não pode ser excluído.")


class PrecoCombustivelReferencia(TenantAwareModel):
    """
    Tabela de preços médios e referenciais de combustíveis por UF/Município.
    Fonte primária: Levantamento de Preços de Combustíveis (LPC) da ANP (Dados Abertos - CC-BY)
    ou cadastros manuais com registro de auditoria.
    """
    FONTE_CHOICES = [
        ('ANP', 'ANP (Dados Abertos)'),
        ('Manual', 'Entrada Manual'),
    ]
    PRODUTO_CHOICES = [
        ('Diesel S10', 'Diesel S10'),
        ('Diesel S500', 'Diesel S500'),
        ('Gasolina Comum', 'Gasolina Comum'),
        ('Etanol', 'Etanol'),
        ('GNV', 'GNV'),
        ('GLP', 'GLP (Gás Liquefeito de Petróleo)'),
    ]

    fonte = models.CharField(max_length=20, choices=FONTE_CHOICES, default='ANP', verbose_name="Fonte do Dado")
    produto = models.CharField(max_length=50, choices=PRODUTO_CHOICES, verbose_name="Produto / Combustível")
    uf = models.CharField(max_length=2, verbose_name="UF")
    municipio = models.CharField(max_length=100, null=True, blank=True, default='', verbose_name="Município")
    data_inicial = models.DateField(verbose_name="Data Inicial da Semana/Período")
    data_final = models.DateField(verbose_name="Data Final da Semana/Período")
    preco_medio = models.DecimalField(max_digits=8, decimal_places=4, verbose_name="Preço Médio (R$)")
    preco_minimo = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True, verbose_name="Preço Mínimo (R$)")
    preco_maximo = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True, verbose_name="Preço Máximo (R$)")
    desvio_padrao = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True, verbose_name="Desvio Padrão (R$)")
    n_postos = models.PositiveIntegerField(null=True, blank=True, verbose_name="Número de Postos Pesquisados")
    importado_em = models.DateTimeField(auto_now_add=True, verbose_name="Importado em")

    class Meta:
        verbose_name = "Preço de Referência de Combustível"
        verbose_name_plural = "Preços de Referência de Combustíveis"
        ordering = ['-data_final', 'produto']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'fonte', 'produto', 'uf', 'municipio', 'data_inicial'],
                name='unique_ref_preco_combustivel'
            )
        ]
        indexes = [
            models.Index(fields=['produto', 'uf', 'municipio', 'data_final']),
        ]

    def __str__(self):
        local = f"{self.municipio}/{self.uf}" if self.municipio else self.uf
        return f"{self.produto} ({local}) - R$ {self.preco_medio} [{self.data_inicial.strftime('%d/%m')} a {self.data_final.strftime('%d/%m/%Y')}]"

    @property
    def esta_defasado(self):
        """Indica se a referência de preço tem mais de N dias em relação à data atual."""
        hoje = timezone.localdate()
        return (hoje - self.data_final).days > 14


class ConfiguracaoCombustivelFrota(TenantAwareModel):
    """
    Configurações e parâmetros de tolerância de combustível e abastecimento por empresa (tenant).
    """
    uf_padrao = models.CharField(max_length=2, default='GO', verbose_name="UF Padrão da Frota")
    municipio_padrao = models.CharField(max_length=100, blank=True, default='', verbose_name="Município Padrão da Frota")
    tolerancia_preco_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('15.00'), verbose_name="Tolerância de Preço vs ANP (%)")
    dias_alerta_preco_defasado = models.PositiveIntegerField(default=14, verbose_name="Dias para Alerta de Preço Defasado")
    tolerancia_consumo_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('25.00'), verbose_name="Tolerância de Desvio de Consumo (%)")
    usar_preco_referencia_sugerido = models.BooleanField(default=True, verbose_name="Sugerir Preço de Referência ANP no Cadastro")

    class Meta:
        verbose_name = "Configuração de Combustível da Frota"
        verbose_name_plural = "Configurações de Combustível da Frota"

    def __str__(self):
        return f"Config Combustível - {self.tenant.nome_fantasia or self.tenant.razao_social}"


class Abastecimento(TenantAwareModel):
    """
    Registro detalhado de abastecimento por veículo, motorista e rota, com cálculo
    de consumo real (km/l), custo por km e motor de detecção de anomalias operacionais.
    """
    TIPO_COMBUSTIVEL_CHOICES = [
        ('Diesel S10', 'Diesel S10'),
        ('Diesel S500', 'Diesel S500'),
        ('Gasolina Comum', 'Gasolina Comum'),
        ('Etanol', 'Etanol'),
        ('GNV', 'GNV'),
        ('Arla 32', 'Arla 32 (Agente Redutor)'),
    ]

    FORMA_PAGAMENTO_CHOICES = [
        ('Cartão frota', 'Cartão Frota / Ticket Log'),
        ('Dinheiro', 'Dinheiro'),
        ('Faturado', 'Faturado / Boleto'),
        ('PIX', 'PIX'),
        ('Outro', 'Outro'),
    ]

    STATUS_VALIDACAO_CHOICES = [
        ('Normal', 'Normal'),
        ('Alerta', 'Alerta'),
        ('Revisar', 'Revisar'),
    ]

    ORIGEM_CHOICES = [
        ('Painel', 'Painel Web Gestão'),
        ('PWA', 'PWA de Campo (Motorista)'),
    ]

    client_uuid = models.UUIDField(null=True, blank=True, db_index=True, verbose_name="UUID do Cliente Offline (Idempotência)")
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='abastecimentos', verbose_name="Veículo")
    motorista = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='abastecimentos_realizados', verbose_name="Motorista")
    entrega = models.ForeignKey(Entrega, on_delete=models.SET_NULL, null=True, blank=True, related_name='abastecimentos', verbose_name="Romaneio / Entrega")
    data_hora = models.DateTimeField(default=timezone.now, verbose_name="Data e Hora do Abastecimento")
    odometro_km = models.PositiveIntegerField(verbose_name="Odômetro no Momento (km)")
    tipo_combustivel = models.CharField(max_length=30, choices=TIPO_COMBUSTIVEL_CHOICES, verbose_name="Tipo de Combustível")
    litros = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Litros Abastecidos")
    valor_litro = models.DecimalField(max_digits=10, decimal_places=4, verbose_name="Valor por Litro (R$)")
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Valor Total (R$)")
    tanque_cheio = models.BooleanField(default=True, verbose_name="Completou o Tanque (Tanque Cheio)")
    
    posto_nome = models.CharField(max_length=150, blank=True, default='', verbose_name="Nome / Bandeira do Posto")
    posto_cidade = models.CharField(max_length=100, blank=True, default='', verbose_name="Cidade do Posto")
    posto_uf = models.CharField(max_length=2, blank=True, default='', verbose_name="UF do Posto")
    forma_pagamento = models.CharField(max_length=30, choices=FORMA_PAGAMENTO_CHOICES, default='Cartão frota', verbose_name="Forma de Pagamento")
    numero_cupom = models.CharField(max_length=50, blank=True, default='', verbose_name="Nº Cupom / Nota Fiscal")
    comprovante = models.FileField(upload_to=abastecimento_comprovante_upload_path, null=True, blank=True, verbose_name="Comprovante / Foto Cupom")
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default='Painel', verbose_name="Origem do Lançamento")
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações")

    # Cálculos operacionais consolidados
    km_rodados_desde_anterior = models.IntegerField(null=True, blank=True, verbose_name="Km Rodados Desde o Último")
    consumo_km_l = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Consumo Calculado (km/l)")
    custo_por_km = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True, verbose_name="Custo por Km (R$/km)")

    # Auditoria e Motor de Alertas
    status_validacao = models.CharField(max_length=20, choices=STATUS_VALIDACAO_CHOICES, default='Normal', verbose_name="Status da Validação")
    alertas = models.JSONField(default=list, blank=True, verbose_name="Alertas e Anomalias Detectadas")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Abastecimento"
        verbose_name_plural = "Abastecimentos"
        ordering = ['-data_hora', '-odometro_km']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'client_uuid'],
                condition=models.Q(client_uuid__isnull=False),
                name='unique_tenant_abastecimento_client_uuid'
            )
        ]
        indexes = [
            models.Index(fields=['veiculo', 'data_hora']),
            models.Index(fields=['veiculo', 'odometro_km']),
        ]

    def __str__(self):
        return f"{self.veiculo.placa} - {self.tipo_combustivel}: {self.litros}L (R$ {self.valor_total}) em {self.data_hora.strftime('%d/%m/%Y')}"


# ==============================================================================
# SPRINT L3: MANUTENÇÃO PREVENTIVA E CORRETIVA
# ==============================================================================

class Fornecedor(TenantAwareModel):
    """
    Fornecedor, oficina mecânica ou prestador de serviço de manutenção de frotas.
    """
    nome = models.CharField(max_length=150, verbose_name="Nome / Razão Social")
    documento = models.CharField(max_length=30, blank=True, default='', verbose_name="CNPJ / CPF")
    telefone = models.CharField(max_length=30, blank=True, default='', verbose_name="Telefone")
    email = models.EmailField(blank=True, default='', verbose_name="E-mail")
    cidade = models.CharField(max_length=100, blank=True, default='', verbose_name="Cidade")
    uf = models.CharField(max_length=2, blank=True, default='', verbose_name="UF")
    especialidades = models.CharField(max_length=255, blank=True, default='', verbose_name="Especialidades")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Fornecedor / Oficina"
        verbose_name_plural = "Fornecedores e Oficinas"
        ordering = ['nome']

    def __str__(self):
        local = f" ({self.cidade}/{self.uf})" if self.cidade else ""
        return f"{self.nome}{local}"


class PlanoManutencao(TenantAwareModel):
    """
    Plano de manutenção preventiva configurado por veículo com gatilhos de quilometragem e/ou tempo.
    Regra: Vence o que ocorrer primeiro (km ou dias).
    """
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='planos_manutencao', verbose_name="Veículo")
    descricao = models.CharField(max_length=150, verbose_name="Descrição do Plano")
    gatilho_km = models.PositiveIntegerField(null=True, blank=True, verbose_name="Gatilho por Quilometragem (km)")
    gatilho_dias = models.PositiveIntegerField(null=True, blank=True, verbose_name="Gatilho por Tempo (dias)")
    antecedencia_alerta_km = models.PositiveIntegerField(default=1000, verbose_name="Antecedência de Alerta (km)")
    antecedencia_alerta_dias = models.PositiveIntegerField(default=15, verbose_name="Antecedência de Alerta (dias)")
    custo_estimado = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo Estimado (R$)")
    fornecedor_preferido = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='planos_preferidos', verbose_name="Fornecedor Preferido")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    ultima_execucao_data = models.DateField(null=True, blank=True, verbose_name="Última Execução (Data)")
    ultima_execucao_km = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Última Execução (km)")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Plano de Manutenção Preventiva"
        verbose_name_plural = "Planos de Manutenção Preventiva"
        ordering = ['veiculo', 'descricao']

    def clean(self):
        super().clean()
        if not self.gatilho_km and not self.gatilho_dias:
            raise ValidationError("Informe ao menos um gatilho para o plano: quilometragem (gatilho_km) ou tempo em dias (gatilho_dias).")

    def __str__(self):
        return f"{self.veiculo.placa} - {self.descricao}"

    @property
    def proximo_vencimento_km(self):
        if self.gatilho_km is not None:
            base_km = self.ultima_execucao_km or Decimal('0.00')
            return Decimal(str(base_km)) + Decimal(str(self.gatilho_km))
        return None

    @property
    def proximo_vencimento_data(self):
        if self.gatilho_dias is not None and self.ultima_execucao_data:
            return self.ultima_execucao_data + timezone.timedelta(days=self.gatilho_dias)
        return None

    def calcular_status_vencimento(self, odometro_atual=None, data_referencia=None):
        """
        Calcula o status do plano: 'Vencido', 'Alerta', 'Em dia'.
        Regra: vence o que ocorrer primeiro (km ou tempo).
        """
        if not self.ativo:
            return {'status': 'Inativo', 'motivo': 'Plano inativo', 'vencido': False, 'alerta': False}

        if data_referencia is None:
            data_referencia = timezone.localdate()
        if odometro_atual is None:
            odometro_atual = getattr(self.veiculo, 'odometro_atual_km', Decimal('0.00')) or Decimal('0.00')
        odometro_atual = Decimal(str(odometro_atual))

        vencido_km = False
        alerta_km = False
        km_restantes = None
        prox_km = self.proximo_vencimento_km
        if self.gatilho_km is not None and prox_km is not None:
            km_restantes = prox_km - odometro_atual
            if odometro_atual >= prox_km:
                vencido_km = True
            elif km_restantes <= (self.antecedencia_alerta_km or 0):
                alerta_km = True

        vencido_dias = False
        alerta_dias = False
        dias_restantes = None
        prox_data = self.proximo_vencimento_data
        if self.gatilho_dias is not None and self.ultima_execucao_data:
            dias_restantes = (prox_data - data_referencia).days
            if data_referencia >= prox_data:
                vencido_dias = True
            elif dias_restantes <= (self.antecedencia_alerta_dias or 0):
                alerta_dias = True
        elif self.gatilho_dias is not None and not self.ultima_execucao_data:
            vencido_dias = True

        if vencido_km or vencido_dias:
            motivos = []
            if vencido_km:
                motivos.append(f"Km atingido ({odometro_atual:.0f} km >= {prox_km:.0f} km)")
            if vencido_dias:
                data_str = prox_data.strftime('%d/%m/%Y') if (self.gatilho_dias and self.ultima_execucao_data) else 'Sem registro prévio'
                motivos.append(f"Prazo expirado ({data_str})")
            return {
                'status': 'Vencido',
                'motivo': " | ".join(motivos),
                'vencido': True,
                'alerta': False,
                'km_restantes': float(km_restantes) if km_restantes is not None else None,
                'dias_restantes': dias_restantes,
                'proximo_km': float(prox_km) if prox_km is not None else None,
                'proxima_data': prox_data.strftime('%Y-%m-%d') if (self.gatilho_dias and self.ultima_execucao_data) else None
            }

        if alerta_km or alerta_dias:
            motivos = []
            if alerta_km:
                motivos.append(f"Restam {km_restantes:.0f} km")
            if alerta_dias:
                motivos.append(f"Restam {dias_restantes} dias")
            return {
                'status': 'Alerta',
                'motivo': " | ".join(motivos),
                'vencido': False,
                'alerta': True,
                'km_restantes': float(km_restantes) if km_restantes is not None else None,
                'dias_restantes': dias_restantes,
                'proximo_km': float(prox_km) if prox_km is not None else None,
                'proxima_data': prox_data.strftime('%Y-%m-%d') if (self.gatilho_dias and self.ultima_execucao_data) else None
            }

        return {
            'status': 'Em dia',
            'motivo': 'Dentro dos parâmetros operacionais',
            'vencido': False,
            'alerta': False,
            'km_restantes': float(km_restantes) if km_restantes is not None else None,
            'dias_restantes': dias_restantes,
            'proximo_km': float(prox_km) if prox_km is not None else None,
            'proxima_data': prox_data.strftime('%Y-%m-%d') if (self.gatilho_dias and self.ultima_execucao_data) else None
        }


class OrdemServico(TenantAwareModel):
    """
    Ordem de Serviço (OS) para manutenções preventivas, corretivas, preditivas ou recall.
    Possui validação estrita de transições de status no backend e cálculo automático de custos.
    """
    TIPO_CHOICES = [
        ('Preventiva', 'Preventiva'),
        ('Corretiva', 'Corretiva'),
        ('Preditiva', 'Preditiva'),
        ('Recall', 'Recall'),
    ]

    ORIGEM_CHOICES = [
        ('Plano', 'Plano Preventivo'),
        ('Checklist', 'Checklist de Saída'),
        ('Motorista', 'Motorista (Defeito)'),
        ('Sinistro', 'Sinistro / Acidente'),
        ('Manual', 'Lançamento Manual'),
    ]

    PRIORIDADE_CHOICES = [
        ('Crítica', 'Crítica'),
        ('Alta', 'Alta'),
        ('Normal', 'Normal'),
    ]

    STATUS_CHOICES = [
        ('Aberta', 'Aberta'),
        ('Orçada', 'Orçada'),
        ('Aprovada', 'Aprovada'),
        ('Em Execução', 'Em Execução'),
        ('Concluída', 'Concluída'),
        ('Cancelada', 'Cancelada'),
    ]

    numero = models.CharField(max_length=30, blank=True, db_index=True, verbose_name="Número da OS")
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='ordens_servico', verbose_name="Veículo")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='Preventiva', verbose_name="Tipo de Manutenção")
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default='Manual', verbose_name="Origem da Solicitação")
    plano = models.ForeignKey(PlanoManutencao, on_delete=models.SET_NULL, null=True, blank=True, related_name='ordens_servico', verbose_name="Plano de Origem")
    sinistro_origem = models.ForeignKey('Sinistro', on_delete=models.SET_NULL, null=True, blank=True, related_name='ordens_servico_geradas', verbose_name="Sinistro de Origem")
    prioridade = models.CharField(max_length=20, choices=PRIORIDADE_CHOICES, default='Normal', verbose_name="Prioridade")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Aberta', verbose_name="Status da OS")
    imobiliza_veiculo = models.BooleanField(default=False, verbose_name="Imobiliza Veículo (Não Apto)")
    descricao_problema = models.TextField(verbose_name="Descrição do Problema / Serviço Solicitado")
    diagnostico = models.TextField(blank=True, default='', verbose_name="Diagnóstico Técnico / Parecer da Oficina")
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='ordens_servico', verbose_name="Oficina / Fornecedor")
    odometro_entrada = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Odômetro de Entrada (km)")
    odometro_saida = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Odômetro de Saída (km)")
    data_abertura = models.DateTimeField(default=timezone.now, verbose_name="Data de Abertura")
    data_entrada = models.DateTimeField(null=True, blank=True, verbose_name="Data de Entrada na Oficina")
    data_prevista = models.DateField(null=True, blank=True, verbose_name="Data Prevista de Conclusão")
    data_conclusao = models.DateTimeField(null=True, blank=True, verbose_name="Data de Conclusão Efetiva")
    custo_pecas = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo Peças (R$)")
    custo_mao_de_obra = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo Mão de Obra (R$)")
    custo_terceiros = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo Terceiros (R$)")
    custo_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Custo Total (R$)")
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='os_aprovadas', verbose_name="Aprovado por")
    aprovado_em = models.DateTimeField(null=True, blank=True, verbose_name="Aprovado em")
    garantia_ate = models.DateField(null=True, blank=True, verbose_name="Garantia até")
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações")
    historico_status = models.JSONField(default=list, blank=True, verbose_name="Histórico de Status")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Ordem de Serviço"
        verbose_name_plural = "Ordens de Serviço"
        ordering = ['-data_abertura']
        indexes = [
            models.Index(fields=['veiculo', 'status']),
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tipo', 'status']),
        ]

    def __str__(self):
        return f"{self.numero or 'OS (Nova)'} - {self.veiculo.placa} ({self.status})"

    def clean(self):
        super().clean()
        # Validação de transições de status se a OS já existir no banco
        if self.pk:
            antiga = OrdemServico.unscoped.filter(pk=self.pk).first()
            if antiga and antiga.status != self.status:
                transicoes_validas = {
                    'Aberta': ['Orçada', 'Aprovada', 'Cancelada'],
                    'Orçada': ['Aprovada', 'Cancelada'],
                    'Aprovada': ['Em Execução', 'Cancelada'],
                    'Em Execução': ['Concluída', 'Cancelada'],
                    'Concluída': [],
                    'Cancelada': [],
                }
                permitidas = transicoes_validas.get(antiga.status, [])
                if self.status not in permitidas:
                    raise ValidationError({
                        'status': f"Transição de status inválida: não é permitido alterar de '{antiga.status}' para '{self.status}'."
                    })

        # Validações estritas para conclusão da OS
        if self.status == 'Concluída':
            if self.odometro_saida is None:
                raise ValidationError({
                    'odometro_saida': "A conclusão da Ordem de Serviço exige o preenchimento obrigatório do odômetro de saída."
                })
            if self.odometro_entrada is not None and self.odometro_saida < self.odometro_entrada:
                raise ValidationError({
                    'odometro_saida': f"O odômetro de saída ({self.odometro_saida} km) não pode ser inferior ao odômetro de entrada ({self.odometro_entrada} km)."
                })
            if self.custo_total is None or self.custo_total < Decimal('0.00'):
                raise ValidationError({
                    'custo_total': "A conclusão da Ordem de Serviço exige a apuração e validação dos custos da manutenção."
                })

    def save(self, *args, **kwargs):
        # Validação preliminar
        self.clean()

        # Geração do sequencial por empresa se não houver
        if not self.numero and self.tenant_id:
            ano = timezone.now().year
            seq = OrdemServico.unscoped.filter(tenant_id=self.tenant_id, data_abertura__year=ano).count() + 1
            self.numero = f"OS-{ano}-{seq:04d}"

        # Se houver itens associados, custo total é composto pelos itens + terceiros
        if self.pk and self.itens.exists():
            pecas = self.itens.filter(tipo='Peça').aggregate(total=models.Sum('valor_total'))['total'] or Decimal('0.00')
            servicos = self.itens.filter(tipo='Serviço').aggregate(total=models.Sum('valor_total'))['total'] or Decimal('0.00')
            self.custo_pecas = pecas
            self.custo_mao_de_obra = servicos
            self.custo_total = pecas + servicos + (self.custo_terceiros or Decimal('0.00'))
        else:
            custo_calc = (self.custo_pecas or Decimal('0.00')) + (self.custo_mao_de_obra or Decimal('0.00')) + (self.custo_terceiros or Decimal('0.00'))
            if custo_calc > Decimal('0.00') or self.custo_total is None or self.custo_total <= Decimal('0.00'):
                self.custo_total = custo_calc

        # Rastreamento de histórico de status
        if self.pk:
            antiga = OrdemServico.unscoped.filter(pk=self.pk).first()
            if antiga and antiga.status != self.status:
                historico = list(self.historico_status or [])
                historico.append({
                    'de': antiga.status,
                    'para': self.status,
                    'data_hora': timezone.now().isoformat(),
                    'aprovado_por': self.aprovado_por.username if self.aprovado_por else None
                })
                self.historico_status = historico
        elif not self.historico_status:
            self.historico_status = [{
                'de': None,
                'para': self.status,
                'data_hora': timezone.now().isoformat(),
                'aprovado_por': None
            }]

        # Se status for Concluída:
        if self.status == 'Concluída':
            if not self.data_conclusao:
                self.data_conclusao = timezone.now()

            # Atualiza odômetro do veículo se saída for maior
            if self.odometro_saida and self.veiculo_id:
                veiculo = self.veiculo
                if (veiculo.odometro_atual_km or Decimal('0.00')) < self.odometro_saida:
                    veiculo.odometro_atual_km = self.odometro_saida
                    veiculo.save(update_fields=['odometro_atual_km'])

            # Se vinculada a plano preventivo, atualiza última execução e recalcula
            if self.plano_id:
                plano = self.plano
                plano.ultima_execucao_data = self.data_conclusao.date()
                plano.ultima_execucao_km = self.odometro_saida or self.veiculo.odometro_atual_km
                plano.save(update_fields=['ultima_execucao_data', 'ultima_execucao_km', 'atualizado_em'])

        # Se status for Aprovada:
        if self.status == 'Aprovada' and not self.aprovado_em:
            self.aprovado_em = timezone.now()

        super().save(*args, **kwargs)


class OSItem(TenantAwareModel):
    """
    Item detalhado de uma Ordem de Serviço (Peça aplicada ou Serviço executado).
    """
    TIPO_ITEM_CHOICES = [
        ('Peça', 'Peça / Material'),
        ('Serviço', 'Mão de Obra / Serviço'),
    ]

    os = models.ForeignKey(OrdemServico, on_delete=models.CASCADE, related_name='itens', verbose_name="Ordem de Serviço")
    tipo = models.CharField(max_length=20, choices=TIPO_ITEM_CHOICES, default='Peça', verbose_name="Tipo de Item")
    descricao = models.CharField(max_length=200, verbose_name="Descrição do Item / Serviço")
    quantidade = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('1.00'), verbose_name="Quantidade")
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Unitário (R$)")
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Total (R$)")
    garantia_dias = models.PositiveIntegerField(default=90, verbose_name="Garantia (dias)")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Item da Ordem de Serviço"
        verbose_name_plural = "Itens da Ordem de Serviço"
        ordering = ['id']

    def save(self, *args, **kwargs):
        self.valor_total = (self.quantidade or Decimal('0.00')) * (self.valor_unitario or Decimal('0.00'))
        super().save(*args, **kwargs)
        # Recalcula custos da OS
        if self.os_id:
            os_obj = self.os
            pecas = os_obj.itens.filter(tipo='Peça').aggregate(total=models.Sum('valor_total'))['total'] or Decimal('0.00')
            servicos = os_obj.itens.filter(tipo='Serviço').aggregate(total=models.Sum('valor_total'))['total'] or Decimal('0.00')
            os_obj.custo_pecas = pecas
            os_obj.custo_mao_de_obra = servicos
            os_obj.custo_total = pecas + servicos + (os_obj.custo_terceiros or Decimal('0.00'))
            OrdemServico.objects.filter(pk=os_obj.pk).update(
                custo_pecas=os_obj.custo_pecas,
                custo_mao_de_obra=os_obj.custo_mao_de_obra,
                custo_total=os_obj.custo_total
            )

    def delete(self, *args, **kwargs):
        os_id = self.os_id
        super().delete(*args, **kwargs)
        if os_id:
            os_obj = OrdemServico.objects.filter(pk=os_id).first()
            if os_obj:
                pecas = os_obj.itens.filter(tipo='Peça').aggregate(total=models.Sum('valor_total'))['total'] or Decimal('0.00')
                servicos = os_obj.itens.filter(tipo='Serviço').aggregate(total=models.Sum('valor_total'))['total'] or Decimal('0.00')
                os_obj.custo_pecas = pecas
                os_obj.custo_mao_de_obra = servicos
                os_obj.custo_total = pecas + servicos + (os_obj.custo_terceiros or Decimal('0.00'))
                OrdemServico.objects.filter(pk=os_obj.pk).update(
                    custo_pecas=os_obj.custo_pecas,
                    custo_mao_de_obra=os_obj.custo_mao_de_obra,
                    custo_total=os_obj.custo_total
                )


class OSAnexo(TenantAwareModel):
    """
    Anexo digitalizado de uma Ordem de Serviço (Orçamento, Nota Fiscal, Fotos Antes/Depois).
    """
    TIPO_ANEXO_CHOICES = [
        ('Orçamento', 'Orçamento'),
        ('Nota Fiscal', 'Nota Fiscal'),
        ('Foto Antes', 'Foto Antes do Reparo'),
        ('Foto Depois', 'Foto Depois do Reparo'),
        ('Outro', 'Outro'),
    ]

    os = models.ForeignKey(OrdemServico, on_delete=models.CASCADE, related_name='anexos', verbose_name="Ordem de Serviço")
    tipo = models.CharField(max_length=30, choices=TIPO_ANEXO_CHOICES, default='Orçamento', verbose_name="Tipo do Anexo")
    arquivo = models.FileField(upload_to=os_anexo_upload_path, verbose_name="Arquivo Digitalizado")
    descricao = models.CharField(max_length=255, blank=True, default='', verbose_name="Descrição / Observação")
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Enviado por")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Anexo da Ordem de Serviço"
        verbose_name_plural = "Anexos da Ordem de Serviço"
        ordering = ['-criado_em']

    def clean(self):
        super().clean()
        if self.arquivo:
            if hasattr(self.arquivo, 'size') and self.arquivo.size > 10 * 1024 * 1024:
                raise ValidationError("O tamanho máximo do anexo permitido é de 10 MB.")
            ext = self.arquivo.name.split('.')[-1].lower() if '.' in self.arquivo.name else ''
            if ext not in ['pdf', 'jpg', 'jpeg', 'png', 'webp']:
                raise ValidationError("Extensão não permitida. Formatos válidos: PDF, JPG, PNG, WEBP.")


class ChecklistModelo(TenantAwareModel):
    """
    Modelo de checklist pré-operacional configurável por empresa.
    """
    nome = models.CharField(max_length=150, verbose_name="Nome do Modelo")
    itens = models.JSONField(default=list, verbose_name="Itens Configuráveis")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    obrigatorio_antes_saida = models.BooleanField(default=True, verbose_name="Obrigatório Antes da Saída")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Modelo de Checklist"
        verbose_name_plural = "Modelos de Checklist"
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.itens:
            self.itens = [
                {"codigo": "pneus", "nome": "Pneus e Calibragem", "descricao": "Verificar pressão, desgaste e sulcos dos pneus e estepe", "impeditivo": True},
                {"codigo": "freios", "nome": "Sistema de Freios", "descricao": "Freio de serviço, freio estacionamento e nível de fluído", "impeditivo": True},
                {"codigo": "luzes", "nome": "Luzes e Sinalização", "descricao": "Faróis alto/baixo, lanternas, setas, pisca e luz de freio", "impeditivo": True},
                {"codigo": "vazamentos", "nome": "Vazamentos Visíveis", "descricao": "Sem poças de óleo, água ou combustível sob o veículo", "impeditivo": True},
                {"codigo": "extintor", "nome": "Extintor de Incêndio", "descricao": "Pressão no verde e lacre de segurança intacto", "impeditivo": True},
                {"codigo": "kit_emergencia", "nome": "Kit Emergência / Triângulo", "descricao": "Triângulo, macaco hidráulico e chave de roda presentes", "impeditivo": False},
                {"codigo": "cintas", "nome": "Cintas e Amarração de Carga", "descricao": "Cintas, catracas e travas dos botijões/cilindros", "impeditivo": True},
                {"codigo": "documentos", "nome": "Documentos do Veículo", "descricao": "CRLV, CIPP/CIV e licenças de transporte presentes", "impeditivo": True},
            ]
        super().save(*args, **kwargs)


class ChecklistExecucao(TenantAwareModel):
    """
    Execução de checklist pré-saída realizada pelo motorista antes de iniciar a rota.
    Item crítico/impeditivo 'Não OK' gera automaticamente Ordem de Serviço corretiva e
    bloqueia o veículo (marca veículo como não apto a operar).
    """
    ORIGEM_CHOICES = [
        ('PWA', 'PWA de Campo'),
        ('Painel', 'Painel de Gestão'),
    ]

    client_uuid = models.UUIDField(null=True, blank=True, db_index=True, verbose_name="UUID Offline (Idempotência)")
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='checklists_executados', verbose_name="Veículo")
    motorista = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='checklists_motorista', verbose_name="Motorista")
    entrega = models.ForeignKey(Entrega, on_delete=models.SET_NULL, null=True, blank=True, related_name='checklists', verbose_name="Entrega / Rota Vinculada")
    data_hora = models.DateTimeField(default=timezone.now, verbose_name="Data e Hora")
    odometro = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Odômetro Registrado (km)")
    respostas = models.JSONField(default=dict, verbose_name="Respostas do Checklist")
    aprovado = models.BooleanField(default=True, verbose_name="Aprovado")
    tem_itens_impeditivos = models.BooleanField(default=False, verbose_name="Possui Itens Impeditivos Reprovados")
    os_gerada = models.ForeignKey(OrdemServico, on_delete=models.SET_NULL, null=True, blank=True, related_name='checklists_origem', verbose_name="OS Corretiva Gerada")
    foto = models.FileField(upload_to=checklist_foto_upload_path, null=True, blank=True, verbose_name="Foto / Evidência")
    observacoes = models.TextField(blank=True, default='', verbose_name="Observações Gerais")
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default='PWA', verbose_name="Origem")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Checklist Realizado"
        verbose_name_plural = "Checklists Realizados"
        ordering = ['-data_hora']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'client_uuid'],
                condition=models.Q(client_uuid__isnull=False),
                name='unique_tenant_checklist_client_uuid'
            )
        ]

    def __str__(self):
        status_str = "APROVADO" if self.aprovado else "REPROVADO"
        return f"Checklist {self.veiculo.placa} ({status_str}) - {self.data_hora.strftime('%d/%m/%Y %H:%M')}"

    def save(self, *args, **kwargs):
        # Processa respostas do checklist
        itens_reprovados = []
        tem_impeditivo = False

        if isinstance(self.respostas, dict):
            for k, v in self.respostas.items():
                if isinstance(v, dict):
                    status_item = v.get('status', 'OK')
                    is_impeditivo = bool(v.get('impeditivo', True))
                    if status_item == 'Não OK':
                        nome_item = v.get('nome') or k
                        obs_item = v.get('obs') or ''
                        itens_reprovados.append(f"{nome_item}: {obs_item}".strip(': '))
                        if is_impeditivo:
                            tem_impeditivo = True
        elif isinstance(self.respostas, list):
            for v in self.respostas:
                if isinstance(v, dict):
                    status_item = v.get('status', 'OK')
                    is_impeditivo = bool(v.get('impeditivo', True))
                    if status_item == 'Não OK':
                        nome_item = v.get('nome') or v.get('codigo', 'Item')
                        obs_item = v.get('obs') or ''
                        itens_reprovados.append(f"{nome_item}: {obs_item}".strip(': '))
                        if is_impeditivo:
                            tem_impeditivo = True

        if itens_reprovados:
            self.aprovado = False
            self.tem_itens_impeditivos = tem_impeditivo
        else:
            self.aprovado = True
            self.tem_itens_impeditivos = False

        # Atualiza odômetro do veículo se informado
        if self.odometro and self.veiculo_id:
            veiculo = self.veiculo
            if (veiculo.odometro_atual_km or Decimal('0.00')) < self.odometro:
                veiculo.odometro_atual_km = self.odometro
                veiculo.save(update_fields=['odometro_atual_km'])

        # Se houver itens reprovados e ainda não gerou OS, cria OS Corretiva automaticamente
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and itens_reprovados and not self.os_gerada_id and not getattr(self, '_skip_os_generation', False):
            defeitos_texto = "\n".join([f"- {it}" for it in itens_reprovados])
            desc = f"Defeitos identificados no Checklist Pré-Saída em {self.data_hora.strftime('%d/%m/%Y %H:%M')}:\n{defeitos_texto}"
            if self.observacoes:
                desc += f"\nObservações do motorista: {self.observacoes}"

            os_corretiva = OrdemServico.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                tipo='Corretiva',
                origem='Checklist',
                prioridade='Crítica' if self.tem_itens_impeditivos else 'Alta',
                status='Aberta',
                imobiliza_veiculo=self.tem_itens_impeditivos,
                descricao_problema=desc,
                odometro_entrada=self.odometro
            )
            self.os_gerada = os_corretiva
            ChecklistExecucao.objects.filter(pk=self.pk).update(os_gerada=os_corretiva)


# ==============================================================================
# SPRINT L5: SEGUROS E SINISTROS (APÓLICES, COBERTURAS, SINISTROS E ANEXOS)
# ==============================================================================

def apolice_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'pdf'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    return f"apolices/{tenant_id}/{random_name}.{ext}"


def sinistro_anexo_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
    random_name = uuid.uuid4().hex
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    sinistro_id = str(instance.sinistro_id) if instance.sinistro_id else 'temp'
    return f"sinistros/{tenant_id}/{sinistro_id}/{random_name}.{ext}"


class ApoliceSeguro(TenantAwareModel):
    TIPO_CHOICES = [
        ('Frota/Casco+RCF', 'Frota / Casco + RCF'),
        ('Carga RCTR-C', 'Carga RCTR-C (Transportador)'),
        ('Desvio de Carga RC-DC', 'Desvio de Carga RC-DC'),
        ('Outro', 'Outro'),
    ]

    COBRE_PERIGOSO_CHOICES = [
        ('SIM', 'Sim'),
        ('NAO', 'Não'),
        ('NAO_VERIFICADO', 'Não verificado'),
    ]

    seguradora = models.CharField(max_length=150, verbose_name="Seguradora")
    corretor = models.CharField(max_length=150, blank=True, null=True, verbose_name="Corretor de Seguros")
    telefone_assistencia_24h = models.CharField(max_length=50, blank=True, null=True, verbose_name="Telefone Assistência 24h")
    numero_apolice = models.CharField(max_length=80, verbose_name="Número da Apólice")
    tipo = models.CharField(max_length=50, choices=TIPO_CHOICES, default='Frota/Casco+RCF', verbose_name="Tipo de Apólice")
    vigencia_inicio = models.DateField(verbose_name="Início da Vigência")
    vigencia_fim = models.DateField(verbose_name="Fim da Vigência")
    premio_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Prêmio Total (R$)")
    forma_pagamento = models.CharField(max_length=80, blank=True, null=True, verbose_name="Forma de Pagamento")
    parcelas = models.PositiveSmallIntegerField(default=1, verbose_name="Quantidade de Parcelas")
    arquivo_pdf = models.FileField(upload_to=apolice_upload_path, null=True, blank=True, verbose_name="Arquivo da Apólice (PDF)")
    prazo_comunicacao_sinistro_horas = models.PositiveIntegerField(default=24, verbose_name="Prazo de Comunicação de Sinistro (h)")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações Gerais")
    ativa = models.BooleanField(default=True, verbose_name="Apólice Ativa")

    # Campos específicos de Carga
    limite_maximo_por_viagem = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Limite Máximo de Garantia por Viagem (R$)")
    produtos_riscos_excluidos = models.TextField(blank=True, null=True, verbose_name="Produtos e Riscos Excluídos")
    cobre_produto_perigoso = models.CharField(max_length=20, choices=COBRE_PERIGOSO_CHOICES, default='NAO_VERIFICADO', verbose_name="Cobre Produto Perigoso / GLP")

    class Meta:
        verbose_name = "Apólice de Seguro"
        verbose_name_plural = "Apólices de Seguro"
        ordering = ['-vigencia_fim']

    def __str__(self):
        return f"{self.seguradora} - {self.numero_apolice} ({self.tipo})"

    @property
    def dias_para_vencimento(self):
        hoje = timezone.localdate()
        return (self.vigencia_fim - hoje).days

    @property
    def status_vigencia(self):
        if not self.ativa:
            return "Inativa"
        dias = self.dias_para_vencimento
        if dias < 0:
            return "Vencida"
        elif dias <= 15:
            return "Vence em 15 dias"
        elif dias <= 30:
            return "Vence em 30 dias"
        elif dias <= 60:
            return "Vence em 60 dias"
        return "Vigente"

    @property
    def dias_para_vencer(self):
        return self.dias_para_vencimento

    @property
    def alerta_renovacao_60dias(self):
        return 0 <= self.dias_para_vencimento <= 60

    @property
    def alerta_renovacao_30dias(self):
        return 0 <= self.dias_para_vencimento <= 30

    @property
    def alerta_renovacao_15dias(self):
        return 0 <= self.dias_para_vencimento <= 15

    @property
    def semaforo_vigencia(self):
        st = self.status_vigencia
        if st in ('Vencida', 'Inativa'):
            return 'red'
        elif st in ('Vence em 15 dias', 'Vence em 30 dias'):
            return 'orange'
        elif st == 'Vence em 60 dias':
            return 'yellow'
        return 'green'


class ApoliceCobertura(TenantAwareModel):
    COBERTURA_CHOICES = [
        ('Casco', 'Casco'),
        ('RCF-Danos Materiais', 'RCF - Danos Materiais'),
        ('RCF-Danos Corporais', 'RCF - Danos Corporais'),
        ('APP', 'Acidentes Pessoais a Passageiros (APP)'),
        ('Vidros', 'Vidros e Faróis'),
        ('Carro Reserva', 'Carro Reserva'),
        ('Guincho/Assistência', 'Guincho e Assistência 24h'),
        ('Outra', 'Outra Cobertura'),
    ]

    apolice = models.ForeignKey(ApoliceSeguro, on_delete=models.CASCADE, related_name='coberturas', verbose_name="Apólice")
    cobertura = models.CharField(max_length=50, choices=COBERTURA_CHOICES, verbose_name="Tipo de Cobertura")
    limite = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Limite Máximo de Indenização (R$)")
    franquia_valor = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor da Franquia (R$)")
    franquia_percentual = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Franquia (%)")

    class Meta:
        verbose_name = "Cobertura da Apólice"
        verbose_name_plural = "Coberturas da Apólice"

    def __str__(self):
        return f"{self.cobertura} - {self.apolice.numero_apolice}"


class ApoliceVeiculo(TenantAwareModel):
    TIPO_VALOR_CHOICES = [
        ('Percentual FIPE', 'Percentual FIPE'),
        ('Valor Determinado', 'Valor Determinado'),
    ]

    apolice = models.ForeignKey(ApoliceSeguro, on_delete=models.CASCADE, related_name='veiculos_segurados', verbose_name="Apólice")
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='apolices_vinculadas', verbose_name="Veículo")
    valor_segurado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Valor Segurado (R$)")
    tipo_valor = models.CharField(max_length=30, choices=TIPO_VALOR_CHOICES, default='Percentual FIPE', verbose_name="Tipo de Valor")

    class Meta:
        verbose_name = "Veículo Segurado"
        verbose_name_plural = "Veículos Segurados"
        constraints = [
            models.UniqueConstraint(fields=['apolice', 'veiculo'], name='unique_apolice_veiculo')
        ]

    def __str__(self):
        return f"{self.veiculo.placa} -> Apólice {self.apolice.numero_apolice}"


class ConfiguracaoSeguros(TenantAwareModel):
    exigir_apolice_ativa_para_operar = models.BooleanField(default=False, verbose_name="Exigir apólice ativa para operar veículo")
    alerta_renovacao_dias = models.PositiveIntegerField(default=30, verbose_name="Dias de antecedência para alerta de renovação")

    class Meta:
        verbose_name = "Configuração de Seguros"
        verbose_name_plural = "Configurações de Seguros"

    @classmethod
    def get_para_tenant(cls, tenant):
        cfg, _ = cls.objects.get_or_create(tenant=tenant)
        return cfg


class Sinistro(TenantAwareModel):
    TIPO_CHOICES = [
        ('Colisão', 'Colisão / Abalroamento'),
        ('Tombamento', 'Tombamento'),
        ('Roubo/Furto de Veículo', 'Roubo / Furto de Veículo'),
        ('Roubo de Carga', 'Roubo de Carga'),
        ('Avaria de Carga', 'Avaria de Carga'),
        ('Incêndio', 'Incêndio'),
        ('Vazamento de Produto', 'Vazamento de Produto Perigoso'),
        ('Dano a Terceiro', 'Dano a Terceiro'),
        ('Outro', 'Outro'),
    ]

    STATUS_CHOICES = [
        ('Rascunho', 'Rascunho (PWA/Campo)'),
        ('Registrado', 'Registrado'),
        ('Comunicado à Seguradora', 'Comunicado à Seguradora'),
        ('Em Análise', 'Em Análise'),
        ('Em Vistoria', 'Em Vistoria'),
        ('Aprovado', 'Aprovado / Autorizado'),
        ('Negado', 'Negado pela Seguradora'),
        ('Indenizado', 'Indenizado / Liquidado'),
        ('Encerrado', 'Encerrado'),
    ]

    numero = models.CharField(max_length=40, blank=True, db_index=True, verbose_name="Número do Sinistro")
    client_uuid = models.CharField(max_length=64, null=True, blank=True, db_index=True, verbose_name="UUID do Cliente Offline")
    tipo = models.CharField(max_length=40, choices=TIPO_CHOICES, verbose_name="Tipo de Sinistro")
    data_hora = models.DateTimeField(default=timezone.now, verbose_name="Data e Hora do Ocorrido")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="Latitude GPS")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="Longitude GPS")
    endereco = models.CharField(max_length=255, blank=True, null=True, verbose_name="Endereço / Local do Sinistro")
    veiculo = models.ForeignKey(Veiculo, on_delete=models.SET_NULL, null=True, blank=True, related_name='sinistros', verbose_name="Veículo Envolvido")
    motorista = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='sinistros_motorista', verbose_name="Motorista Condutor")
    entrega = models.ForeignKey(Entrega, on_delete=models.SET_NULL, null=True, blank=True, related_name='sinistros', verbose_name="Entrega / Romaneio Associado")
    apolice = models.ForeignKey(ApoliceSeguro, on_delete=models.SET_NULL, null=True, blank=True, related_name='sinistros', verbose_name="Apólice de Seguro Acionada")
    terceiros = models.JSONField(default=dict, blank=True, verbose_name="Dados de Terceiros Envolvidos (LGPD)")
    houve_vitimas = models.BooleanField(default=False, verbose_name="Houve Vítimas / Feridos")
    boletim_ocorrencia_numero = models.CharField(max_length=60, blank=True, null=True, verbose_name="Número do Boletim de Ocorrência (BO)")
    descricao = models.TextField(verbose_name="Descrição Detalhada do Ocorrido")
    status = models.CharField(max_length=35, choices=STATUS_CHOICES, default='Registrado', verbose_name="Status do Sinistro")
    protocolo_seguradora = models.CharField(max_length=80, blank=True, null=True, verbose_name="Protocolo do Sinistro na Seguradora")
    data_comunicacao_seguradora = models.DateTimeField(null=True, blank=True, verbose_name="Data de Comunicação à Seguradora")
    prazo_limite_comunicacao = models.DateTimeField(null=True, blank=True, verbose_name="Prazo Limite para Comunicação")
    valor_prejuizo_estimado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Prejuízo Bruto Estimado (R$)")
    valor_franquia = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor da Franquia Paga (R$)")
    valor_indenizacao = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Indenização Recebida (R$)")
    prejuizo_liquido = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Prejuízo Líquido Final (R$)")
    os_vinculada = models.ForeignKey(OrdemServico, on_delete=models.SET_NULL, null=True, blank=True, related_name='sinistros_vinculados', verbose_name="OS de Manutenção / Reparo Vinculada")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='sinistros_criados', verbose_name="Criado por")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sinistro"
        verbose_name_plural = "Sinistros"
        ordering = ['-data_hora']

    def __str__(self):
        return f"Sinistro {self.numero} ({self.tipo}) - {self.status}"

    def calcular_prejuizo_liquido(self):
        custo_os = self.os_vinculada.custo_total if self.os_vinculada else Decimal('0.00')
        custo_itens_carga = sum((it.valor_total for it in self.itens_carga.all()), Decimal('0.00')) if self.pk else Decimal('0.00')
        self.prejuizo_liquido = max(
            Decimal('0.00'),
            self.valor_prejuizo_estimado + custo_os + custo_itens_carga + self.valor_franquia - self.valor_indenizacao
        )
        return self.prejuizo_liquido

    def calcular_prazo_limite(self):
        if self.data_hora:
            horas = 24
            if self.apolice and self.apolice.prazo_comunicacao_sinistro_horas:
                horas = self.apolice.prazo_comunicacao_sinistro_horas
            self.prazo_limite_comunicacao = self.data_hora + timedelta(hours=horas)
        return self.prazo_limite_comunicacao

    @property
    def ajuste_estoque_realizado(self):
        if not self.itens_carga.exists():
            return False
        return not self.itens_carga.filter(ajuste_estoque_realizado=False).exists()

    @property
    def comparacao_fipe(self):
        comp = self.comparativo_perda_total_fipe()
        if not comp:
            return None
        return {
            'valor_fipe': Decimal(str(comp['valor_referencia_fipe'])),
            'valor_indenizacao': Decimal(str(comp['valor_indenizacao'])),
            'divergente': comp['alerta_divergencia_alta'],
            'alerta': 'Atenção: Indenização diverge mais de 15% do valor FIPE do veículo.' if comp['alerta_divergencia_alta'] else ''
        }

    @property
    def prazo_comunicacao_expirado(self):
        if self.status in ('Comunicado à Seguradora', 'Em Análise', 'Em Vistoria', 'Aprovado', 'Indenizado', 'Encerrado'):
            return False
        if not self.prazo_limite_comunicacao:
            return False
        return timezone.now() > self.prazo_limite_comunicacao

    @property
    def prazo_comunicacao_urgente(self):
        if self.prazo_comunicacao_expirado:
            return True
        if self.status in ('Comunicado à Seguradora', 'Em Análise', 'Em Vistoria', 'Aprovado', 'Indenizado', 'Encerrado'):
            return False
        if not self.prazo_limite_comunicacao:
            return False
        tempo_restante = (self.prazo_limite_comunicacao - timezone.now()).total_seconds() / 3600.0
        return 0 < tempo_restante <= 4.0

    def comparativo_perda_total_fipe(self):
        if not self.veiculo:
            return None
        val_ref = self.veiculo.fipe_valor
        if not val_ref or val_ref <= Decimal('0.00'):
            hist_fipe = None
            if hasattr(self.veiculo, 'historico_fipe'):
                hist_fipe = self.veiculo.historico_fipe.order_by('-mes_referencia').first()
            elif hasattr(self.veiculo, 'valores_fipe'):
                hist_fipe = self.veiculo.valores_fipe.order_by('-mes_referencia').first()
            if hist_fipe:
                val_ref = hist_fipe.valor
        if not val_ref or val_ref <= Decimal('0.00'):
            val_ref = self.veiculo.valor_aquisicao
        if not val_ref or val_ref <= Decimal('0.00'):
            return None
        divergencia = abs(self.valor_indenizacao - val_ref)
        pct = (divergencia / val_ref) * 100
        return {
            'valor_referencia_fipe': float(val_ref),
            'valor_indenizacao': float(self.valor_indenizacao),
            'divergente': bool(pct > 15.0 and self.valor_indenizacao > Decimal('0.00')),
            'alerta': 'Atenção: Indenização diverge mais de 15% do valor FIPE do veículo.' if pct > 15.0 else '',
            'divergencia_reais': float(divergencia),
            'divergencia_percentual': round(float(pct), 2),
            'alerta_divergencia_alta': bool(pct > 15.0 and self.valor_indenizacao > Decimal('0.00'))
        }

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        tenant_id = self.tenant_id

        if not self.numero and tenant_id:
            ano = timezone.now().year
            count = Sinistro.objects.filter(tenant_id=tenant_id, criado_em__year=ano).count() + 1
            self.numero = f"SIN-{ano}-{count:04d}"

        if not self.prazo_limite_comunicacao and self.data_hora:
            self.calcular_prazo_limite()

        self.calcular_prejuizo_liquido()

        super().save(*args, **kwargs)


class SinistroEvento(TenantAwareModel):
    """
    Linha do tempo imutável de eventos e transições do sinistro.
    """
    sinistro = models.ForeignKey(Sinistro, on_delete=models.CASCADE, related_name='eventos', verbose_name="Sinistro")
    data_hora = models.DateTimeField(default=timezone.now, verbose_name="Data e Hora do Evento")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Autor")
    tipo = models.CharField(max_length=50, verbose_name="Tipo de Evento")
    status_anterior = models.CharField(max_length=35, blank=True, null=True, verbose_name="Status Anterior")
    status_novo = models.CharField(max_length=35, blank=True, null=True, verbose_name="Status Novo")
    descricao = models.TextField(verbose_name="Descrição do Evento")

    class Meta:
        verbose_name = "Evento de Linha do Tempo do Sinistro"
        verbose_name_plural = "Eventos de Linha do Tempo do Sinistro"
        ordering = ['data_hora']

    def __str__(self):
        return f"{self.sinistro.numero} - {self.tipo} ({self.data_hora.strftime('%d/%m/%Y %H:%M')})"

    def clean(self):
        super().clean()
        if self.pk is not None:
            raise ValidationError("Eventos da linha do tempo são registros de auditoria estritamente imutáveis e não podem ser editados.")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Eventos da linha do tempo são registros de auditoria estritamente imutáveis e não podem ser editados.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Eventos da linha do tempo não podem ser excluídos.")


class SinistroAnexo(TenantAwareModel):
    TIPO_CHOICES = [
        ('Foto Local', 'Foto do Local / Cena'),
        ('Foto Veículo', 'Foto do Veículo Avariado'),
        ('Foto Carga', 'Foto da Carga Avariada'),
        ('Boletim de Ocorrência', 'Boletim de Ocorrência (BO)'),
        ('Orçamento', 'Orçamento / Orçamentação Técnica'),
        ('Laudo Técnico', 'Laudo Técnico / Vistoria Pericial'),
        ('Comprovante Seguradora', 'Comprovante / Protocolo Seguradora'),
        ('Outro', 'Outro Documento'),
    ]

    sinistro = models.ForeignKey(Sinistro, on_delete=models.CASCADE, related_name='anexos', verbose_name="Sinistro")
    tipo = models.CharField(max_length=40, choices=TIPO_CHOICES, default='Foto Local', verbose_name="Tipo de Anexo")
    arquivo = models.FileField(upload_to=sinistro_anexo_upload_path, verbose_name="Arquivo")
    descricao = models.CharField(max_length=255, blank=True, null=True, verbose_name="Descrição")
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Enviado por")

    class Meta:
        verbose_name = "Anexo de Sinistro"
        verbose_name_plural = "Anexos de Sinistros"
        ordering = ['-criado_em']

    def __str__(self):
        return f"{self.tipo} - {self.sinistro.numero}"


class SinistroItemCarga(TenantAwareModel):
    sinistro = models.ForeignKey(Sinistro, on_delete=models.CASCADE, related_name='itens_carga', verbose_name="Sinistro")
    produto = models.ForeignKey('produtos.Produto', on_delete=models.PROTECT, verbose_name="Produto")
    quantidade = models.PositiveIntegerField(default=1, verbose_name="Quantidade Perdida / Avariada")
    categoria = models.CharField(max_length=20, choices=[('Cheio', 'Cheio'), ('Vazio', 'Vazio'), ('Casco', 'Casco')], default='Cheio', verbose_name="Categoria do Item")
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Unitário (R$)")
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Total da Perda (R$)")
    ajuste_estoque_realizado = models.BooleanField(default=False, verbose_name="Ajuste de Estoque Realizado")

    class Meta:
        verbose_name = "Item de Carga do Sinistro"
        verbose_name_plural = "Itens de Carga dos Sinistros"

    def __str__(self):
        return f"{self.quantidade}x {self.produto.nome} ({self.categoria}) - {self.sinistro.numero}"

    def save(self, *args, **kwargs):
        if not self.valor_unitario and self.produto and self.produto.preco:
            self.valor_unitario = Decimal(str(self.produto.preco))
        self.valor_total = self.quantidade * (self.valor_unitario or Decimal('0.00'))
        super().save(*args, **kwargs)


# ==============================================================================
# SPRINT L6: FRETE, RENTABILIDADE E CUSTO TOTAL (TCO)
# ==============================================================================

class ConfiguracaoRentabilidade(TenantAwareModel):
    """
    Parâmetros e premissas financeiras de rentabilidade e TCO por empresa (Tenant).
    """
    METODO_RATEIO_SEGURO_CHOICES = [
        ('Km Rodado', 'Por Km Rodado (Prêmio Anual ÷ Km Anual Estimado)'),
        ('Dias de Operacao', 'Por Dias de Operação (Prêmio Anual ÷ 365)'),
    ]

    metodo_rateio_seguro = models.CharField(
        max_length=30,
        choices=METODO_RATEIO_SEGURO_CHOICES,
        default='Km Rodado',
        verbose_name="Método de Rateio do Seguro"
    )
    vida_util_anos = models.PositiveIntegerField(
        default=5,
        verbose_name="Vida Útil Padrão dos Veículos (anos)"
    )
    percentual_residual = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('20.00'),
        verbose_name="Valor Residual Estimado (%)"
    )
    usar_estimativa_combustivel = models.BooleanField(
        default=True,
        verbose_name="Calcular estimativa prévia de combustível antes da saída"
    )
    km_anual_estimado_veiculo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('60000.00'),
        verbose_name="Quilometragem Média Anual Estimada (km/ano)"
    )
    media_lotacao_alerta_minima = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('50.00'),
        verbose_name="Lotação Mínima para Alerta (%)"
    )
    viagens_baixa_ocupacao_alerta = models.PositiveIntegerField(
        default=3,
        verbose_name="Qtd de Viagens com Baixa Ocupação para Alerta"
    )

    class Meta:
        verbose_name = "Configuração de Rentabilidade e Custos"
        verbose_name_plural = "Configurações de Rentabilidade e Custos"

    def __str__(self):
        return f"Config Rentabilidade - Tenant #{self.tenant_id}"

    @classmethod
    def get_para_tenant(cls, tenant):
        cfg, _ = cls.objects.get_or_create(tenant=tenant)
        return cfg


class CustoViagem(TenantAwareModel):
    """
    Consolidação de custos reais, custos estimados e margem de rentabilidade
    por viagem/romaneio de entrega (SPRINT L6).
    """
    entrega = models.OneToOneField(
        Entrega,
        on_delete=models.CASCADE,
        related_name='custo_viagem',
        verbose_name="Entrega / Romaneio"
    )
    combustivel_real = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Custo Real de Combustível (R$)"
    )
    combustivel_estimado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Custo Estimado de Combustível (R$)"
    )
    combustivel_estimado_fonte_preco = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name="Fonte do Preço de Referência"
    )
    combustivel_estimado_data_preco = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data do Preço de Referência"
    )
    combustivel_estimado_consumo_usado = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Consumo Referência Usado (km/l)"
    )
    combustivel_estimado_preco_litro = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="Preço do Litro Usado (R$)"
    )
    pedagios = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Pedágios (R$)"
    )
    diarias_motorista = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Diárias de Motorista (R$)"
    )
    comissao_motorista = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Comissão de Motorista (R$)"
    )
    outros_custos = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Outros Custos (R$)"
    )
    rateio_manutencao = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Rateio Manutenção (R$)"
    )
    rateio_depreciacao = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Rateio Depreciação (R$)"
    )
    rateio_seguro = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Rateio Seguro (R$)"
    )
    custo_total_real = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Custo Total Real da Viagem (R$)"
    )
    km_planejado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Km Planejado"
    )
    km_real = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Km Real Efetivo"
    )
    receita_frete = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Receita de Frete (R$)"
    )
    valor_carga_transportada = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor da Carga Transportada (R$)"
    )
    margem_bruta = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Margem Bruta (R$)"
    )
    margem_percentual = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Margem Percentual (%)"
    )
    snapshot_congelado = models.BooleanField(
        default=False,
        verbose_name="Snapshot Congelado (Concluído)"
    )
    dados_incompletos = models.BooleanField(
        default=False,
        verbose_name="Possui Dados Incompletos"
    )
    motivo_dados_incompletos = models.TextField(
        blank=True,
        default='',
        verbose_name="Motivo dos Dados Incompletos"
    )
    alerta_averbacao = models.BooleanField(
        default=False,
        verbose_name="Alerta de Limite de Averbação de Carga"
    )
    motivo_alerta_averbacao = models.TextField(
        blank=True,
        default='',
        verbose_name="Motivo do Alerta de Averbação"
    )
    alerta_baixa_ocupacao = models.BooleanField(
        default=False,
        verbose_name="Alerta de Baixa Ocupação Histórica"
    )
    motivo_baixa_ocupacao = models.TextField(
        blank=True,
        default='',
        verbose_name="Motivo de Baixa Ocupação"
    )
    ocupacao_viagem_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Ocupação da Carga na Viagem (%)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Custo de Viagem"
        verbose_name_plural = "Custos de Viagens"
        ordering = ['-criado_em']

    def __str__(self):
        status_txt = "Congelado" if self.snapshot_congelado else "Estimado/Aberto"
        return f"Custo Viagem #{self.entrega_id} (R$ {self.custo_total_real}) [{status_txt}]"

    def recalcular_itens_avulsos(self):
        """
        Soma itens avulsos cadastrados por tipo e atualiza os totais parciais.
        """
        itens = self.itens_avulsos.all()
        ped = Decimal('0.00')
        dia = Decimal('0.00')
        com = Decimal('0.00')
        out = Decimal('0.00')
        for item in itens:
            val = item.valor or Decimal('0.00')
            if item.tipo == 'Pedágio':
                ped += val
            elif item.tipo == 'Diária':
                dia += val
            elif item.tipo == 'Comissão':
                com += val
            else:
                out += val
        self.pedagios = ped
        self.diarias_motorista = dia
        self.comissao_motorista = com
        self.outros_custos = out
        self.calcular_totais()

    def calcular_totais(self):
        """
        Calcula o custo total real, a margem bruta e a margem percentual.
        Não altera campos se o snapshot estiver congelado.
        """
        from decimal import ROUND_HALF_UP
        self.custo_total_real = (
            (self.combustivel_real or Decimal('0.00')) +
            (self.pedagios or Decimal('0.00')) +
            (self.diarias_motorista or Decimal('0.00')) +
            (self.comissao_motorista or Decimal('0.00')) +
            (self.outros_custos or Decimal('0.00')) +
            (self.rateio_manutencao or Decimal('0.00')) +
            (self.rateio_depreciacao or Decimal('0.00')) +
            (self.rateio_seguro or Decimal('0.00'))
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        self.margem_bruta = ((self.receita_frete or Decimal('0.00')) - self.custo_total_real).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if self.receita_frete and self.receita_frete > Decimal('0.00'):
            self.margem_percentual = ((self.margem_bruta / self.receita_frete) * Decimal('100.0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            self.margem_percentual = None


class CustoViagemItem(TenantAwareModel):
    """
    Lançamento avulso de despesa da viagem (pedágios, diárias, comissão, etc.)
    com suporte opcional a comprovante fotográfico/PDF.
    """
    TIPO_CHOICES = [
        ('Pedágio', 'Pedágio'),
        ('Diária', 'Diária de Motorista'),
        ('Comissão', 'Comissão'),
        ('Alimentação', 'Alimentação'),
        ('Descarga/Chapa', 'Descarga / Chapa'),
        ('Outro', 'Outro'),
    ]

    custo_viagem = models.ForeignKey(
        CustoViagem,
        on_delete=models.CASCADE,
        related_name='itens_avulsos',
        verbose_name="Custo da Viagem"
    )
    tipo = models.CharField(
        max_length=30,
        choices=TIPO_CHOICES,
        default='Pedágio',
        verbose_name="Tipo de Despesa"
    )
    valor = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor (R$)"
    )
    descricao = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name="Descrição / Observação"
    )
    comprovante = models.FileField(
        upload_to=custo_viagem_comprovante_upload_path,
        null=True,
        blank=True,
        verbose_name="Comprovante / Recibo"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item de Custo de Viagem"
        verbose_name_plural = "Itens de Custo de Viagem"
        ordering = ['-criado_em']

    def __str__(self):
        return f"{self.tipo} - R$ {self.valor} (Viagem #{self.custo_viagem.entrega_id})"

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.custo_viagem_id:
            try:
                self.tenant_id = self.custo_viagem.tenant_id
            except Exception:
                pass
        super().save(*args, **kwargs)
        if not self.custo_viagem.snapshot_congelado:
            self.custo_viagem.recalcular_itens_avulsos()
            self.custo_viagem.save()

    def delete(self, *args, **kwargs):
        custo = self.custo_viagem
        super().delete(*args, **kwargs)
        if custo and not custo.snapshot_congelado:
            custo.recalcular_itens_avulsos()
            custo.save()


# ==============================================================================
# SPRINT 10C: MARGEM POR VEÍCULO, FRETE INTERNO E TCO (CORREÇÃO F-23)
# ==============================================================================

class TabelaFreteInterno(TenantAwareModel):
    """
    Tabela de precificação interna de frete imputado por veículo ou geral (Sprint 10C - Tarefa 5).
    Utilizada na política de contribuição de frete do veículo quando não há frete destacado.
    """
    TIPO_CHOICES = [
        ('POR_KM', 'Por Km Rodado'),
        ('POR_PARADA', 'Por Parada / Entrega Realizada'),
    ]

    descricao = models.CharField(max_length=120, verbose_name="Descrição da Tabela de Frete Interno")
    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='tabelas_frete_interno',
        verbose_name="Veículo Específico (Opcional, se nulo aplica-se a toda frota)"
    )
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        default='POR_KM',
        verbose_name="Tipo de Cobrança Interna"
    )
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Unitário Interno (R$)"
    )
    vigencia_inicio = models.DateField(default=timezone.localdate, verbose_name="Início da Vigência")
    vigencia_fim = models.DateField(null=True, blank=True, verbose_name="Fim da Vigência (Opcional)")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Tabela de Frete Interno"
        verbose_name_plural = "Tabelas de Frete Interno"
        ordering = ['-vigencia_inicio', 'descricao']

    def __str__(self):
        alvo = self.veiculo.placa if self.veiculo else "Frota Geral"
        return f"{self.descricao} [{alvo}]: R$ {self.valor} ({self.get_tipo_display()})"


class AlocacaoMotoristaVeiculo(TenantAwareModel):
    """
    Registro e alocação de equipe (motorista e ajudante) por veículo e período (Sprint 10C - Tarefa 6).
    Permite rateio auditável de custos fixos de mão de obra para apuração do TCO.
    """
    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.CASCADE,
        related_name='alocacoes_equipe',
        verbose_name="Veículo"
    )
    motorista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='alocacoes_como_motorista',
        verbose_name="Motorista"
    )
    ajudante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='alocacoes_como_ajudante',
        verbose_name="Ajudante de Carga (Opcional)"
    )
    data_inicio = models.DateField(verbose_name="Data Início da Alocação")
    data_fim = models.DateField(verbose_name="Data Fim da Alocação")
    dias_alocados = models.PositiveIntegerField(default=1, verbose_name="Dias Efetivos Alocados no Período")
    custo_diaria_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Custo Diário Total da Equipe com Encargos (R$)"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Alocação de Motorista no Veículo"
        verbose_name_plural = "Alocações de Motoristas em Veículos"
        ordering = ['-data_inicio', 'veiculo']

    def __str__(self):
        return f"Alocação {self.veiculo.placa} ({self.motorista.get_full_name() or self.motorista.username}): {self.dias_alocados} dias"


# ==============================================================================
# SPRINT 12A: TORRE DE CONTROLE, CARGA PERIGOSA, GPS OFFLINE E RASTREIO PÚBLICO
# ==============================================================================

class CapacidadeVeiculoTipoCilindro(TenantAwareModel):
    """
    Capacidade máxima de transporte do veículo estratificada por modelo/tipo de cilindro (Sprint 12A - Tarefa 1).
    Evita carregamento excessivo de recipientes específicos mesmo que o PBT não seja excedido.
    """
    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.CASCADE,
        related_name='capacidades_por_tipo',
        verbose_name="Veículo"
    )
    tipo_cilindro = models.ForeignKey(
        'produtos.ModeloCilindro',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='capacidades_veiculos',
        verbose_name="Modelo / Tipo de Cilindro"
    )
    tipo_cilindro_codigo = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name="Código / Nome do Tipo de Cilindro"
    )
    quantidade_maxima = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantidade Máxima Permitida (Unidades)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Capacidade por Tipo de Cilindro"
        verbose_name_plural = "Capacidades por Tipo de Cilindro"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'veiculo', 'tipo_cilindro'],
                name='unique_capacidade_veiculo_tipo'
            )
        ]

    def __str__(self):
        tipo_str = self.tipo_cilindro.descricao if self.tipo_cilindro else (self.tipo_cilindro_codigo or "Geral")
        return f"{self.veiculo.placa} - {tipo_str}: máx {self.quantidade_maxima} un"


class Motorista(TenantAwareModel):
    """
    Cadastro regulatório e dados de habilitação/capacitação de motoristas (Sprint 12A - Tarefa 1).
    Controla validade de CNH, categoria e curso MOPP para transporte de produtos perigosos.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='motorista_perfis',
        verbose_name="Usuário de Sistema Vinculado"
    )
    nome = models.CharField(max_length=150, verbose_name="Nome Completo do Motorista")
    cpf = models.CharField(max_length=14, blank=True, default='', verbose_name="CPF")
    cnh_numero = models.CharField(max_length=20, blank=True, default='', verbose_name="Número do Registro CNH")
    cnh_categoria = models.CharField(max_length=5, default='D', verbose_name="Categoria da CNH (ex: C, D, E)")
    cnh_validade = models.DateField(null=True, blank=True, verbose_name="Data de Validade da CNH")
    mopp_validade = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data de Validade do Curso MOPP (Movimentação de Produtos Perigosos)"
    )
    ativo = models.BooleanField(default=True, verbose_name="Motorista Ativo")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Motorista"
        verbose_name_plural = "Motoristas"
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'cpf'],
                condition=~models.Q(cpf=''),
                name='unique_tenant_motorista_cpf'
            )
        ]

    def __str__(self):
        return f"{self.nome} (CNH {self.cnh_categoria} - Val: {self.cnh_validade or 'N/I'})"

    @property
    def cnh_vencida(self) -> bool:
        if not self.cnh_validade:
            return True
        return self.cnh_validade < timezone.localdate()

    @property
    def mopp_vencido(self) -> bool:
        if not self.mopp_validade:
            return True
        return self.mopp_validade < timezone.localdate()


class RegraIncompatibilidadeCarga(TenantAwareModel):
    """
    Matriz de incompatibilidade química entre classes de risco ANTT (Sprint 12A - Tarefa 2 / Res. 5.998/22 e NBR 14619).
    Ex: 2.1 (Gases Inflamáveis) x 5.1 (Gases Oxidantes/Oxigênio) -> BLOQUEAR.
    """
    ACAO_CHOICES = [
        ('BLOQUEAR', 'Bloquear Expedição / Saída'),
        ('AVISAR', 'Avisar e Exigir Ciência'),
    ]

    classe_a = models.CharField(max_length=10, db_index=True, verbose_name="Classe de Risco A (ex: 2.1)")
    classe_b = models.CharField(max_length=10, db_index=True, verbose_name="Classe de Risco B (ex: 5.1 ou 2.3)")
    acao = models.CharField(max_length=10, choices=ACAO_CHOICES, default='BLOQUEAR', verbose_name="Ação a Aplicar")
    norma_referencia = models.CharField(
        max_length=150,
        default='Resolução ANTT nº 5.998/2022 e ABNT NBR 14619',
        verbose_name="Norma Regulamentadora de Referência"
    )
    mensagem = models.TextField(blank=True, default='', verbose_name="Instrução Operacional / Justificativa Técnica")
    ativo = models.BooleanField(default=True, verbose_name="Regra Ativa")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Regra de Incompatibilidade de Carga"
        verbose_name_plural = "Regras de Incompatibilidade de Carga"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'classe_a', 'classe_b'],
                name='unique_tenant_incompatibilidade_carga'
            )
        ]

    def __str__(self):
        return f"Incompatibilidade: {self.classe_a} x {self.classe_b} -> {self.acao}"


class LiberacaoCarga(TenantAwareModel):
    """
    Registro formal e auditado de liberação excepcional de saída em rota com pendências de validação (Sprint 12A - Tarefa 2).
    Exige permissão específica 'logistica.liberar_carga_bloqueada' e motivo formal obrigatório.
    """
    entrega = models.ForeignKey(
        Entrega,
        on_delete=models.CASCADE,
        related_name='liberacoes_carga',
        verbose_name="Entrega Liberada"
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='cargas_liberadas',
        verbose_name="Responsável / Gestor Aprovador"
    )
    motivo = models.TextField(verbose_name="Motivo Formal Obrigatório da Liberação")
    erros_ignorados = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Erros e Alertas Técnicos Ignorados na Liberação"
    )
    data_liberacao = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora da Liberação")

    class Meta:
        verbose_name = "Liberação de Carga Bloqueada"
        verbose_name_plural = "Liberações de Cargas Bloqueadas"
        ordering = ['-data_liberacao']
        permissions = [
            ("liberar_carga_bloqueada", "Pode liberar saída de rota com carga ou documentação bloqueada"),
        ]

    def __str__(self):
        return f"Liberação Entrega #{self.entrega_id} por {self.responsavel.username} em {self.data_liberacao.strftime('%d/%m/%Y %H:%M')}"


class ParadaEntrega(TenantAwareModel):
    """
    Parada individualizada no trajeto da entrega (Sprint 12A - Tarefas 3 e 4).
    Controla ordem de atendimento, janelas de horário, estado de execução no PWA e reordenação.
    """
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('A_CAMINHO', 'A Caminho'),
        ('CHEGOU', 'Chegou ao Local'),
        ('ENTREGUE', 'Entregue com Sucesso'),
        ('FALHA', 'Falha na Entrega'),
    ]

    entrega = models.ForeignKey(
        Entrega,
        on_delete=models.CASCADE,
        related_name='paradas_entrega',
        verbose_name="Entrega"
    )
    venda = models.ForeignKey(
        'vendas.Venda',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='paradas_logistica',
        verbose_name="Venda / Pedido"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.PROTECT,
        related_name='paradas_logistica',
        verbose_name="Cliente Destinatário"
    )
    ordem = models.PositiveIntegerField(default=1, verbose_name="Ordem de Atendimento")
    travada = models.BooleanField(
        default=False,
        verbose_name="Ordem Travada Manualmente",
        help_text="Se travada, o algoritmo de roteirização não altera a posição desta parada."
    )
    janela_inicio = models.TimeField(null=True, blank=True, verbose_name="Início da Janela de Atendimento")
    janela_fim = models.TimeField(null=True, blank=True, verbose_name="Fim da Janela de Atendimento")
    tempo_servico_min = models.PositiveIntegerField(default=15, verbose_name="Tempo Estimado de Serviço / Descarga (min)")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDENTE',
        db_index=True,
        verbose_name="Estado da Parada no PWA"
    )
    motivo_falha = models.TextField(blank=True, default='', verbose_name="Motivo Obrigatório em Caso de Falha")
    eta_estimado = models.DateTimeField(null=True, blank=True, verbose_name="ETA Estimado de Chegada")
    chegada_em = models.DateTimeField(null=True, blank=True, verbose_name="Horário Efetivo de Chegada")
    concluida_em = models.DateTimeField(null=True, blank=True, verbose_name="Horário de Conclusão / Baixa")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Parada de Entrega"
        verbose_name_plural = "Paradas de Entrega"
        ordering = ['entrega', 'ordem']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'entrega', 'ordem'],
                name='unique_parada_ordem_por_entrega'
            )
        ]

    def __str__(self):
        return f"Parada #{self.ordem} - Entrega #{self.entrega_id} ({self.cliente.nome}) [{self.status}]"


class TokenRastreio(TenantAwareModel):
    """
    Token público seguro e efêmero para link de rastreamento de última milha do cliente (Sprint 12A - Tarefa 7 / Correção F-34).
    Expira poucas horas após a parada e obedece regras estritas de privacidade e mascaramento.
    """
    entrega = models.ForeignKey(
        Entrega,
        on_delete=models.CASCADE,
        related_name='tokens_rastreio',
        verbose_name="Entrega"
    )
    parada = models.ForeignKey(
        ParadaEntrega,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='tokens_rastreio',
        verbose_name="Parada Específica do Destinatário"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True, verbose_name="Token de Rastreio Público")
    expira_em = models.DateTimeField(db_index=True, verbose_name="Data/Hora de Expiração do Link")
    revogado = models.BooleanField(default=False, verbose_name="Token Revogado")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Token de Rastreio Público"
        verbose_name_plural = "Tokens de Rastreio Público"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Token {self.token} - Entrega #{self.entrega_id} (Exp: {self.expira_em.strftime('%d/%m/%Y %H:%M')})"

    @property
    def esta_valido(self) -> bool:
        if self.revogado:
            return False
        return timezone.now() <= self.expira_em


class TrajetoEntrega(TenantAwareModel):
    """
    Polilinha simplificada e consolidada do trajeto percorrido pela entrega (Sprint 12A - Tarefa 6).
    Substitui pontos detalhados após 90 dias, mantendo consultas ultra-rápidas (< 300 ms).
    """
    entrega = models.OneToOneField(
        Entrega,
        on_delete=models.CASCADE,
        related_name='trajeto_simplificado',
        verbose_name="Entrega"
    )
    polilinha = models.TextField(verbose_name="Polilinha Codificada / Coordenadas GeoJSON Consolidadas")
    distancia_total_km = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Distância Total Percorrida (km)"
    )
    pontos_contagem = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantidade de Pontos GPS Processados"
    )
    gerado_em = models.DateTimeField(auto_now=True, verbose_name="Gerado / Atualizado em")

    class Meta:
        verbose_name = "Trajeto Consolidado de Entrega"
        verbose_name_plural = "Trajetos Consolidados de Entregas"

    def __str__(self):
        return f"Trajeto Entrega #{self.entrega_id} ({self.distancia_total_km} km, {self.pontos_contagem} pts)"





