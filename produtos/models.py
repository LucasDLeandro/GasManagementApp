from django.db import models

class Produto(models.Model):
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
        verbose_name = "Produto (Cilindro)"
        verbose_name_plural = "Produtos (Cilindros)"
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} - {self.capacidade}{self.unidade_medida} ({self.categoria})"

