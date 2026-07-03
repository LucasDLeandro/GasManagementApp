from django.db import models

class Veiculo(models.Model):
    STATUS_CHOICES = [
        ('Ativo', 'Ativo'),
        ('Em Manutenção', 'Em Manutenção'),
        ('Inativo', 'Inativo'),
    ]

    placa = models.CharField(max_length=10, unique=True, verbose_name="Placa")
    modelo = models.CharField(max_length=100, verbose_name="Modelo")
    marca = models.CharField(max_length=100, verbose_name="Marca")
    ano = models.IntegerField(verbose_name="Ano")
    capacidade_carga = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Capacidade de Carga (kg)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Ativo')

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
