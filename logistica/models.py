import hashlib
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from core.tenancy import TenantAwareModel

class Veiculo(TenantAwareModel):
    STATUS_CHOICES = [
        ('Ativo', 'Ativo'),
        ('Em Manutenção', 'Em Manutenção'),
        ('Inativo', 'Inativo'),
    ]

    LOCALIZACAO_CHOICES = [
        ('Base', 'Base'),
        ('Oficina', 'Oficina'),
        ('Em Rota', 'Em Rota'),
    ]

    placa = models.CharField(max_length=10, verbose_name="Placa")
    modelo = models.CharField(max_length=100, verbose_name="Modelo")
    marca = models.CharField(max_length=100, verbose_name="Marca")
    ano = models.IntegerField(verbose_name="Ano")
    capacidade_carga = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Capacidade de Carga (kg)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Ativo')
    localizacao_atual = models.CharField(max_length=50, choices=LOCALIZACAO_CHOICES, default='Base')

    class Meta:
        verbose_name = "Veículo"
        verbose_name_plural = "Veículos"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'placa'], name='unique_tenant_veiculo_placa')
        ]

    def __str__(self):
        return f"{self.placa} - {self.modelo}"

class Rota(TenantAwareModel):
    nome = models.CharField(max_length=150, verbose_name="Nome da Rota")
    origem = models.CharField(max_length=200, verbose_name="Origem")
    destino = models.CharField(max_length=200, verbose_name="Destino")
    distancia_km = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Distância (km)")
    tempo_estimado_horas = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Tempo Estimado (h)")

    class Meta:
        verbose_name = "Rota"
        verbose_name_plural = "Rotas"

    def __str__(self):
        return self.nome

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
    
    class Meta:
        verbose_name = "Entrega"
        verbose_name_plural = "Entregas"

    def __str__(self):
        rota_nome = self.rota.nome if self.rota else 'Sem Rota'
        return f"Entrega #{self.id} - {rota_nome} ({self.status})"

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

class ValidacaoCarga(TenantAwareModel):
    entrega = models.ForeignKey(Entrega, on_delete=models.CASCADE, related_name='validacoes', null=True, blank=True)
    venda = models.ForeignKey('vendas.Venda', on_delete=models.CASCADE, related_name='validacoes')
    produto = models.ForeignKey('produtos.Produto', on_delete=models.CASCADE)
    quantidade_alterada = models.IntegerField(verbose_name="Qtd Alterada (+ ou -)")
    etapa_logistica = models.CharField(max_length=50, verbose_name="Etapa Logística")
    justificativa = models.TextField(verbose_name="Justificativa")
    data_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Validação de Carga"
        verbose_name_plural = "Validações de Carga"

    def __str__(self):
        return f"Validação Venda #{self.venda.id} - {self.quantidade_alterada}x {self.produto.nome}"


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

