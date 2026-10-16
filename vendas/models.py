from django.db import models
from django.conf import settings
from clientes.models import Cliente
from produtos.models import Produto
from core.tenancy import TenantAwareModel, get_current_tenant

class Venda(TenantAwareModel):
    STATUS_CHOICES = [
        ('Pendente', 'Pendente (Em Produção/Envase)'),
        ('Em Separação', 'Em Separação'),
        ('Em Rota', 'Em Rota de Entrega'),
        ('Entregue', 'Entregue'),
        ('Finalizada', 'Finalizada'),
        ('Cancelada', 'Cancelada'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='vendas', verbose_name="Cliente")
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='vendas', verbose_name="Vendedor")
    entrega = models.ForeignKey('logistica.Entrega', on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas', verbose_name="Entrega Associada")
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


class ItemVenda(TenantAwareModel):
    FORMA_FATURAMENTO_CHOICES = [
        ('cilindro', 'Por Cilindro'),
        ('medida', 'Por Medida (m³/kg)')
    ]

    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, null=True, blank=True, related_name='itens_vendidos', verbose_name="Produto (Legado)")
    sku = models.ForeignKey('produtos.SkuRecarga', on_delete=models.PROTECT, null=True, blank=True, related_name='itens_vendidos', verbose_name="SKU de Recarga")
    forma_faturamento = models.CharField(max_length=10, choices=FORMA_FATURAMENTO_CHOICES, default='cilindro', verbose_name="Forma de Faturamento")
    quantidade = models.PositiveIntegerField(default=1, verbose_name="Quantidade (Cilindros/Unid)")
    peso_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Peso/Capacidade Unitária")
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Valor Unitário")
    preco_unitario_congelado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Preço Unitário Congelado")
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Total do Item")

    class Meta:
        verbose_name = "Item da Venda"
        verbose_name_plural = "Itens da Venda"

    def __str__(self):
        nome = self.sku.nome_comercial if self.sku else (self.produto.nome if self.produto else 'Item')
        return f"{self.quantidade}x {nome} (Venda #{self.venda.id})"

    def save(self, *args, **kwargs):
        # Herda o tenant da venda se não estiver setado
        if not self.tenant_id and self.venda_id:
            try:
                self.tenant_id = self.venda.tenant_id
            except Exception:
                pass

        # Congela preço unitário caso não tenha sido informado
        if not self.preco_unitario_congelado:
            if self.valor_unitario:
                self.preco_unitario_congelado = self.valor_unitario
            elif self.sku:
                self.preco_unitario_congelado = self.sku.preco_base
            elif self.produto:
                self.preco_unitario_congelado = self.produto.preco

        if not self.valor_unitario and self.preco_unitario_congelado:
            self.valor_unitario = self.preco_unitario_congelado

        if not self.peso_unitario:
            if self.sku:
                self.peso_unitario = self.sku.quantidade_carga
            elif self.produto:
                self.peso_unitario = self.produto.capacidade
            else:
                self.peso_unitario = 0

        # Auto-calcular o valor total do item
        val_un = self.preco_unitario_congelado or self.valor_unitario or 0
        if self.quantidade and val_un:
            if self.forma_faturamento == 'medida' and self.peso_unitario:
                self.valor_total = self.quantidade * self.peso_unitario * val_un
            else:
                self.valor_total = self.quantidade * val_un

        super().save(*args, **kwargs)
