from decimal import Decimal
from rest_framework import serializers
from django.db import transaction
from .models import Venda, ItemVenda
from clientes.serializers import ClienteSerializer
from produtos.models import Produto, SkuRecarga

class ItemVendaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.ReadOnlyField(source='produto.nome')
    sku_nome = serializers.ReadOnlyField(source='sku.nome_comercial')

    class Meta:
        model = ItemVenda
        fields = [
            'id', 'produto', 'produto_nome', 'sku', 'sku_nome',
            'forma_faturamento', 'quantidade', 'peso_unitario',
            'valor_unitario', 'preco_unitario_congelado', 'valor_total'
        ]
        read_only_fields = ['valor_total', 'preco_unitario_congelado']


class VendaSerializer(serializers.ModelSerializer):
    itens = ItemVendaSerializer(many=True)
    cliente_nome = serializers.ReadOnlyField(source='cliente.nome')
    cliente_cnpj = serializers.ReadOnlyField(source='cliente.cnpj')
    cliente_is_medicinal = serializers.ReadOnlyField(source='cliente.is_medicinal')
    vendedor_nome = serializers.ReadOnlyField(source='vendedor.username')
    entrega_status = serializers.ReadOnlyField(source='entrega.status')
    tipo_operacao_display = serializers.CharField(source='get_tipo_operacao_display', read_only=True)
    forma_pagamento_display = serializers.CharField(source='get_forma_pagamento_display', read_only=True)
    gerar_entrega_logistica = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Venda
        fields = [
            'id', 'cliente', 'cliente_nome', 'cliente_cnpj', 'cliente_is_medicinal',
            'vendedor', 'vendedor_nome', 'entrega', 'entrega_status',
            'status', 'tipo_operacao', 'tipo_operacao_display',
            'forma_pagamento', 'forma_pagamento_display', 'condicao_pagamento',
            'valor_desconto', 'documento_fiscal_ref', 'observacoes',
            'valor_total', 'prazo_entrega', 'data_entrega_efetiva',
            'data_venda', 'data_atualizacao', 'itens', 'gerar_entrega_logistica'
        ]
        read_only_fields = ['valor_total', 'data_venda', 'data_atualizacao']

    @transaction.atomic
    def create(self, validated_data):
        itens_data = validated_data.pop('itens', [])
        gerar_entrega = validated_data.pop('gerar_entrega_logistica', False)

        request = self.context.get('request')
        if not validated_data.get('vendedor') and request and getattr(request, 'user', None) and request.user.is_authenticated:
            validated_data['vendedor'] = request.user

        venda = Venda.objects.create(**validated_data)

        if gerar_entrega and not venda.entrega:
            from logistica.models import Entrega
            nova_entrega = Entrega.objects.create(
                tenant=venda.tenant,
                status='Agendada'
            )
            venda.entrega = nova_entrega
            venda.save(update_fields=['entrega'])
        
        for item_data in itens_data:
            produto = item_data.get('produto')
            quantidade = item_data.get('quantidade', 1)
            
            # Baixa de estoque se houver produto legado
            if produto and getattr(produto, 'estoque', None) is not None:
                produto.estoque -= quantidade
                produto.save(update_fields=['estoque'])
            
            ItemVenda.objects.create(venda=venda, **item_data)
            
        venda.calcular_total()
        return venda

    @transaction.atomic
    def update(self, instance, validated_data):
        itens_data = validated_data.pop('itens', None)
        gerar_entrega = validated_data.pop('gerar_entrega_logistica', False)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if gerar_entrega and not instance.entrega:
            from logistica.models import Entrega
            nova_entrega = Entrega.objects.create(
                tenant=instance.tenant,
                status='Agendada'
            )
            instance.entrega = nova_entrega

        instance.save()
        if itens_data is not None:
            instance.calcular_total()
        return instance
