from rest_framework import serializers
from .models import Veiculo, ManutencaoFrota, PecaManutencao, AlertaFrota

class VeiculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Veiculo
        fields = '__all__'

class PecaManutencaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PecaManutencao
        fields = ['id', 'marca', 'codigo', 'tipo_peca', 'valor', 'proxima_troca_km', 'proxima_troca_data']

class ManutencaoFrotaSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    pecas = PecaManutencaoSerializer(many=True, required=False)
    
    class Meta:
        model = ManutencaoFrota
        fields = '__all__'

    def create(self, validated_data):
        pecas_data = validated_data.pop('pecas', [])
        manutencao = ManutencaoFrota.objects.create(**validated_data)
        for peca_data in pecas_data:
            PecaManutencao.objects.create(manutencao=manutencao, **peca_data)
        return manutencao

    def update(self, instance, validated_data):
        pecas_data = validated_data.pop('pecas', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if pecas_data is not None:
            instance.pecas.all().delete()
            for peca_data in pecas_data:
                PecaManutencao.objects.create(manutencao=instance, **peca_data)
        
        return instance

class AlertaFrotaSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)

    class Meta:
        model = AlertaFrota
        fields = '__all__'
