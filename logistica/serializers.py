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
    veiculo_capacidade = serializers.DecimalField(source='veiculo.capacidade_carga', max_digits=10, decimal_places=2, read_only=True)
    rota_nome = serializers.CharField(source='rota.nome', read_only=True)
    motorista_nome = serializers.CharField(source='motorista.username', read_only=True)
    peso_total_carregado = serializers.FloatField(read_only=True)
    capacidade_disponivel = serializers.FloatField(read_only=True)
    percentual_lotacao = serializers.FloatField(read_only=True)
    # Para detalhar os pedidos atrelados
    vendas = serializers.SerializerMethodField()

    class Meta:
        model = Entrega
        fields = '__all__'

    def get_vendas(self, obj):
        # Retorna informações simplificadas das vendas (paradas) na rota
        from vendas.serializers import VendaSerializer # Pode causar import circular, faremos dict simples
        vendas = obj.vendas.all()
        return [
            {
                "id": v.id,
                "cliente_nome": v.cliente.nome,
                "status": v.status,
                "valor_total": float(v.valor_total)
            } for v in vendas
        ]
