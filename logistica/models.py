from django.db import models
from django.conf import settings

class Veiculo(models.Model):
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

    placa = models.CharField(max_length=10, unique=True, verbose_name="Placa")
    modelo = models.CharField(max_length=100, verbose_name="Modelo")
    marca = models.CharField(max_length=100, verbose_name="Marca")
    ano = models.IntegerField(verbose_name="Ano")
    capacidade_carga = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Capacidade de Carga (kg)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Ativo')
    localizacao_atual = models.CharField(max_length=50, choices=LOCALIZACAO_CHOICES, default='Base')

    def __str__(self):
        return f"{self.placa} - {self.modelo}"

class Rota(models.Model):
    nome = models.CharField(max_length=150, verbose_name="Nome da Rota")
    origem = models.CharField(max_length=200, verbose_name="Origem")
    destino = models.CharField(max_length=200, verbose_name="Destino")
    distancia_km = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Distância (km)")
    tempo_estimado_horas = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Tempo Estimado (h)")

    def __str__(self):
        return self.nome

class ManutencaoFrota(models.Model):
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

    def __str__(self):
        return f"Manutenção {self.veiculo.placa} em {self.data_manutencao}"

class TabelaFrete(models.Model):
    TIPO_COBRANCA = [
        ('Fixo', 'Valor Fixo por Rota'),
        ('Distancia', 'Por Km Rodado'),
        ('Peso', 'Por Peso (kg)'),
    ]

    rota = models.ForeignKey(Rota, on_delete=models.CASCADE, null=True, blank=True, related_name='fretes', help_text="Selecione a rota caso seja valor fixo por rota.")
    tipo_cobranca = models.CharField(max_length=20, choices=TIPO_COBRANCA, default='Fixo')
    valor = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor de Cobrança (R$)")

    def __str__(self):
        if self.rota:
            return f"Frete para {self.rota.nome} - R$ {self.valor}"
        return f"Frete por {self.tipo_cobranca} - R$ {self.valor}"


class Entrega(models.Model):
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

    @property
    def peso_total_carregado(self):
        peso = 0
        for venda in self.vendas.exclude(status='Cancelada'):
            for item in venda.itens.all():
                if item.forma_faturamento == 'medida':
                    # If it's by measure (m3/kg), maybe the amount is directly related to weight, 
                    # but usually peso_unitario specifies the capacity.
                    # As requested, sum (quantidade * peso_unitario). If peso_unitario is 0, just fallback to quantidade (assuming 1kg per unit if not set)
                    peso_un = item.peso_unitario if item.peso_unitario else 1
                    peso += float(item.quantidade) * float(peso_un)
                else:
                    # Cilindro
                    peso_un = item.peso_unitario if item.peso_unitario else 1
                    peso += float(item.quantidade) * float(peso_un)
        return peso

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

class ValidacaoCarga(models.Model):
    entrega = models.ForeignKey(Entrega, on_delete=models.CASCADE, related_name='validacoes', null=True, blank=True)
    venda = models.ForeignKey('vendas.Venda', on_delete=models.CASCADE, related_name='validacoes')
    produto = models.ForeignKey('produtos.Produto', on_delete=models.CASCADE)
    quantidade_alterada = models.IntegerField(verbose_name="Qtd Alterada (+ ou -)")
    etapa_logistica = models.CharField(max_length=50, verbose_name="Etapa Logística")
    justificativa = models.TextField(verbose_name="Justificativa")
    data_hora = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Validação Venda #{self.venda.id} - {self.quantidade_alterada}x {self.produto.nome}"
