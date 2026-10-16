from rest_framework import serializers
from .models import Veiculo, Rota, ManutencaoFrota, TabelaFrete, ValidacaoCarga, Entrega
from vendas.models import ItemVenda

class VeiculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Veiculo
        fields = '__all__'

class ValidacaoCargaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source='produto.nome', read_only=True)
    venda_id = serializers.IntegerField(source='venda.id', read_only=True)

    class Meta:
        model = ValidacaoCarga
        fields = '__all__'

class RotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rota
        fields = '__all__'

class ManutencaoFrotaSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    
    class Meta:
        model = ManutencaoFrota
        fields = '__all__'

class TabelaFreteSerializer(serializers.ModelSerializer):
    rota_nome = serializers.CharField(source='rota.nome', read_only=True)

    class Meta:
        model = TabelaFrete
        fields = '__all__'

class EntregaSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)
    veiculo_capacidade = serializers.DecimalField(source='veiculo.capacidade_carga', max_digits=10, decimal_places=2, read_only=True)
    rota_nome = serializers.CharField(source='rota.nome', read_only=True)
    motorista_nome = serializers.CharField(source='motorista.get_full_name', read_only=True)
    peso_total_carregado = serializers.FloatField(read_only=True)
    capacidade_disponivel = serializers.FloatField(read_only=True)
    percentual_lotacao = serializers.FloatField(read_only=True)
    possui_peso_estimado = serializers.BooleanField(read_only=True)
    # Para detalhar os pedidos e paradas atrelados
    vendas = serializers.SerializerMethodField()

    class Meta:
        model = Entrega
        fields = '__all__'

    def get_vendas(self, obj):
        vendas = obj.vendas.select_related('cliente').prefetch_related('itens__produto').all()
        lista = []
        for v in vendas:
            itens_info = []
            for it in v.itens.all():
                itens_info.append({
                    'produto_nome': it.produto.nome if it.produto else 'Item',
                    'quantidade': it.quantidade
                })
            lista.append({
                "id": v.id,
                "cliente_id": v.cliente.id if v.cliente else None,
                "cliente_nome": v.cliente.nome if v.cliente else 'Cliente Não Informado',
                "cliente_cnpj": v.cliente.cnpj if v.cliente else '',
                "cliente_endereco": v.cliente.endereco if v.cliente else '',
                "cliente_telefone": v.cliente.telefone if v.cliente else '',
                "status": v.status,
                "valor_total": float(v.valor_total),
                "itens": itens_info
            })
        return lista


class ComprovanteEntregaSerializer(serializers.ModelSerializer):
    entrega_id = serializers.IntegerField(source='entrega.id', read_only=True)
    movimentacao_id = serializers.IntegerField(source='movimentacao.id', read_only=True)
    assinatura_url = serializers.SerializerMethodField()

    class Meta:
        from .models import ComprovanteEntrega
        model = ComprovanteEntrega
        fields = [
            'id',
            'entrega_id',
            'movimentacao_id',
            'recebedor_nome',
            'recebedor_documento',
            'assinatura_url',
            'timestamp_captura',
            'latitude',
            'longitude',
            'hash_integridade_sha256'
        ]
        read_only_fields = ['id', 'hash_integridade_sha256', 'timestamp_captura']

    def get_assinatura_url(self, obj):
        if obj.assinatura_imagem:
            return f"/logistica/api/comprovantes/{obj.id}/assinatura/"
        return None

