from django.db import models
from django.conf import settings
from clientes.models import Cliente
from produtos.models import Produto

class Venda(models.Model):
    STATUS_CHOICES = [
        ('Pendente', 'Pendente'),
        ('Em Separação', 'Em Separação'),
        ('Em Rota', 'Em Rota de Entrega'),
        ('Entregue', 'Entregue'),
        ('Finalizada', 'Finalizada'),
        ('Cancelada', 'Cancelada'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='vendas', verbose_name="Cliente")
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='vendas', verbose_name="Vendedor")
    veiculo = models.ForeignKey('logistica.Veiculo', on_delete=models.SET_NULL, null=True, blank=True, related_name='entregas', verbose_name="Veículo")
    rota = models.ForeignKey('logistica.Rota', on_delete=models.SET_NULL, null=True, blank=True, related_name='entregas', verbose_name="Rota")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pendente', verbose_name="Status")
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Valor Total da Nota")
    prazo_entrega = models.DateField(null=True, blank=True, verbose_name="Prazo de Entrega")
    data_entrega_efetiva = models.DateField(null=True, blank=True, verbose_name="Data Efetiva de Entrega")
    data_venda = models.DateTimeField(auto_now_add=True, verbose_name="Data da Venda")
    data_atualizacao = models.DateTimeField(auto_now=True, verbose_name="Última Atualização")

    class Meta:
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"
        ordering = ['-data_venda']

    def __str__(self):
        return f"Venda #{self.id} - {self.cliente.nome} ({self.status})"

    def calcular_total(self):
        total = sum(item.valor_total for item in self.itens.all())
        self.valor_total = total
        self.save()


class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='itens_vendidos')
    quantidade = models.PositiveIntegerField(default=1, verbose_name="Quantidade")
    peso_unitario = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Peso/Capacidade Unitária")
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Unitário")
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Total do Item")

    class Meta:
        verbose_name = "Item da Venda"
        verbose_name_plural = "Itens da Venda"

    def __str__(self):
        return f"{self.quantidade}x {self.produto.nome} (Venda #{self.venda.id})"

    def save(self, *args, **kwargs):
        # Auto-calcular o valor total do item
        if self.quantidade and self.valor_unitario:
            self.valor_total = self.quantidade * self.valor_unitario
        super().save(*args, **kwargs)

