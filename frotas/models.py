from django.db import models
from django.utils import timezone

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

    # Dados de Licenciamento
    renavam = models.CharField(max_length=20, null=True, blank=True, verbose_name="RENAVAM")
    chassi = models.CharField(max_length=50, null=True, blank=True, verbose_name="Chassi")
    ano_licenciamento = models.IntegerField(null=True, blank=True, verbose_name="Ano Último Licenciamento")
    debitos = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Débitos (R$)")

    # Controle de Manutenção
    km_atual = models.IntegerField(default=0, verbose_name="Quilometragem Atual")
    intervalo_revisao_km = models.IntegerField(default=10000, verbose_name="Intervalo de Revisão (Km)")
    intervalo_revisao_meses = models.IntegerField(default=6, verbose_name="Intervalo de Revisão (Meses)")

    def __str__(self):
        return f"{self.placa} - {self.modelo}"

class ManutencaoFrota(models.Model):
    STATUS_MANUTENCAO = [
        ('Agendada', 'Agendada'),
        ('Em Progresso', 'Em Progresso'),
        ('Concluída', 'Concluída'),
    ]

    TIPO_MANUTENCAO = [
        ('Preventiva', 'Preventiva'),
        ('Corretiva', 'Corretiva'),
    ]

    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='manutencoes')
    data_manutencao = models.DateField(verbose_name="Data da Manutenção")
    tipo_manutencao = models.CharField(max_length=20, choices=TIPO_MANUTENCAO, default='Preventiva')
    km_atual = models.IntegerField(null=True, blank=True, verbose_name="Km no momento da Manutenção")
    descricao = models.TextField(verbose_name="Descrição do Serviço")
    custo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Custo Total (R$)")
    status = models.CharField(max_length=20, choices=STATUS_MANUTENCAO, default='Agendada')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__original_status = self.status

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        
        super().save(*args, **kwargs)
        
        # Agendamento automático se for Preventiva e foi Concluída agora
        if not is_new and self.tipo_manutencao == 'Preventiva' and self.status == 'Concluída' and self.__original_status != 'Concluída':
            # Pega o veículo
            veiculo = self.veiculo
            # Atualiza o KM do veículo se o KM da manutenção for maior
            if self.km_atual and self.km_atual > veiculo.km_atual:
                veiculo.km_atual = self.km_atual
                veiculo.save(update_fields=['km_atual'])

            # Calcula próxima preventiva
            proxima_data = None
            from dateutil.relativedelta import relativedelta
            if self.data_manutencao and veiculo.intervalo_revisao_meses:
                proxima_data = self.data_manutencao + relativedelta(months=veiculo.intervalo_revisao_meses)
            
            proximo_km = None
            if self.km_atual and veiculo.intervalo_revisao_km:
                proximo_km = self.km_atual + veiculo.intervalo_revisao_km

            # Cria nova Manutencao Preventiva Agendada (apenas se data estiver preenchida pra servir como base)
            if proxima_data:
                nova_manutencao = ManutencaoFrota.objects.create(
                    veiculo=veiculo,
                    data_manutencao=proxima_data,
                    tipo_manutencao='Preventiva',
                    km_atual=proximo_km,  # Salva o km estimado de quando deverá ocorrer
                    descricao='Revisão Preventiva Automática',
                    status='Agendada'
                )
                
                # Gera alerta
                AlertaFrota.objects.create(
                    veiculo=veiculo,
                    mensagem=f'Manutenção preventiva agendada para {proxima_data.strftime("%d/%m/%Y")}.',
                    nivel='Info'
                )

        self.__original_status = self.status

    def __str__(self):
        return f"Manutenção {self.tipo_manutencao} - {self.veiculo.placa} em {self.data_manutencao}"

class PecaManutencao(models.Model):
    manutencao = models.ForeignKey(ManutencaoFrota, on_delete=models.CASCADE, related_name='pecas')
    marca = models.CharField(max_length=100, null=True, blank=True, verbose_name="Marca da Peça")
    codigo = models.CharField(max_length=100, null=True, blank=True, verbose_name="Código da Peça")
    tipo_peca = models.CharField(max_length=150, verbose_name="Tipo de Peça (Ex: Óleo, Lonas, etc)")
    valor = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor da Peça (R$)")
    proxima_troca_km = models.IntegerField(null=True, blank=True, verbose_name="Próxima Troca (Km)")
    proxima_troca_data = models.DateField(null=True, blank=True, verbose_name="Próxima Troca (Data)")

    def __str__(self):
        return f"{self.tipo_peca} - {self.manutencao.veiculo.placa}"

class AlertaFrota(models.Model):
    NIVEL_ALERTA = [
        ('Info', 'Informação'),
        ('Aviso', 'Atenção / Agendamento Próximo'),
        ('Critico', 'Crítico / Vencido'),
    ]

    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='alertas')
    mensagem = models.CharField(max_length=255, verbose_name="Mensagem do Alerta")
    nivel = models.CharField(max_length=20, choices=NIVEL_ALERTA, default='Info')
    data_criacao = models.DateTimeField(auto_now_add=True)
    resolvido = models.BooleanField(default=False)

    def __str__(self):
        return f"[{self.nivel}] {self.veiculo.placa}: {self.mensagem}"
