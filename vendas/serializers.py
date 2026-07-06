from rest_framework import serializers
from django.db import transaction
from .models import Venda, ItemVenda
from clientes.serializers import ClienteSerializer
from produtos.models import Produto

class ItemVendaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.ReadOnlyField(source='produto.nome')

    class Meta:
        model = ItemVenda
        fields = ['id', 'produto', 'produto_nome', 'forma_faturamento', 'quantidade', 'peso_unitario', 'valor_unitario', 'valor_total']
        read_only_fields = ['valor_total']


class VendaSerializer(serializers.ModelSerializer):
    itens = ItemVendaSerializer(many=True)
    cliente_nome = serializers.ReadOnlyField(source='cliente.nome')
    cliente_cnpj = serializers.ReadOnlyField(source='cliente.cnpj')
    vendedor_nome = serializers.ReadOnlyField(source='vendedor.username')

    class Meta:
        model = Venda
        fields = ['id', 'cliente', 'cliente_nome', 'cliente_cnpj', 'vendedor', 'vendedor_nome', 'entrega', 'status', 'valor_total', 'prazo_entrega', 'data_entrega_efetiva', 'data_venda', 'data_atualizacao', 'itens']
        read_only_fields = ['valor_total', 'data_venda', 'data_atualizacao']

    @transaction.atomic
    def create(self, validated_data):
        itens_data = validated_data.pop('itens')
        venda = Venda.objects.create(**validated_data)
        
        valor_total_venda = 0
        for item_data in itens_data:
            # Pega o produto
            produto = item_data['produto']
            quantidade = item_data['quantidade']
            
            # Baixa de estoque
            produto.estoque -= quantidade
            produto.save()
            
            # Cria o item
            item = ItemVenda.objects.create(venda=venda, **item_data)
            valor_total_venda += item.valor_total
            
        venda.valor_total = valor_total_venda
        venda.save()
        return venda

    @transaction.atomic
    def update(self, instance, validated_data):
        # Permitir atualizar status, entrega via API
        if 'status' in validated_data:
            instance.status = validated_data['status']
        if 'entrega' in validated_data:
            instance.entrega = validated_data['entrega']
        instance.save()
        return instance
