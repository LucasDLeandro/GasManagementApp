from rest_framework import serializers
from .models import Veiculo, Rota, ManutencaoFrota, TabelaFrete

class VeiculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Veiculo
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
