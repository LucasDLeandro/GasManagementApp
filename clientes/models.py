from django.db import models

class Cliente(models.Model):
    TIPO_CLIENTE_CHOICES = [
        ('PJ', 'Pessoa Jurídica (Privada)'),
        ('GOV', 'Governamental'),
    ]

    tipo_cliente = models.CharField(max_length=10, choices=TIPO_CLIENTE_CHOICES, default='PJ', verbose_name="Tipo de Cliente")
    cnpj = models.CharField(max_length=18, unique=True, verbose_name="CNPJ")
    nome = models.CharField(max_length=255, verbose_name="Nome")
    endereco = models.TextField(verbose_name="Endereço")
    telefone = models.CharField(max_length=20, verbose_name="Telefone")
    estado = models.CharField(max_length=2, verbose_name="Estado")
    cidade = models.CharField(max_length=255, verbose_name="Cidade")
    proprietario = models.CharField(max_length=255, verbose_name="Proprietário")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} - {self.cnpj}"
