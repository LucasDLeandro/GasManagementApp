from rest_framework import serializers
from django.utils import timezone
from .models import (
    Cliente, ContratoComodato, FranquiaModeloContrato, FechamentoFaturaEstadia, ItemFaturaEstadia,
    AjusteCompetenciaEstadia, ExtravioCilindroRegistro
)
from produtos.models import ModeloCilindro


class ClienteSerializer(serializers.ModelSerializer):
    cliente_matriz_nome = serializers.CharField(source='cliente_matriz.nome', read_only=True, default=None)
    cilindros_em_posse_count = serializers.SerializerMethodField()
    tem_contrato_ativo = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = '__all__'

    def get_cilindros_em_posse_count(self, obj):
        if hasattr(obj, 'annotated_cilindros_count'):
            return obj.annotated_cilindros_count
        return obj.cilindros_em_posse.filter(status='EM_POSSE_CLIENTE').count()

    def get_tem_contrato_ativo(self, obj):
        if hasattr(obj, 'annotated_tem_contrato'):
            return bool(obj.annotated_tem_contrato)
        return bool(obj.contrato_comodato)


class ItemFaturaEstadiaSerializer(serializers.ModelSerializer):
    cilindro_numero_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cilindro_codigo_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)

    class Meta:
        model = ItemFaturaEstadia
        fields = [
            'id', 'cilindro', 'cilindro_numero_serie', 'cilindro_codigo_qr',
            'modelo_cilindro', 'periodo_inicio', 'periodo_fim',
            'dias_posse_mes', 'dias_carencia', 'dias_franquia',
            'dias_reserva_tecnica', 'dias_cobraveis', 'diaria_aplicada',
            'subtotal', 'criado_em'
        ]


class AjusteCompetenciaEstadiaSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)

    class Meta:
        model = AjusteCompetenciaEstadia
        fields = [
            'id', 'cliente', 'cliente_nome', 'fatura_origem', 'fatura_compensacao',
            'competencia_afetada', 'tipo_ajuste', 'valor_ajuste', 'motivo',
            'compensado', 'criado_em'
        ]


class ExtravioCilindroRegistroSerializer(serializers.ModelSerializer):
    cilindro_numero_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    declarado_por_nome = serializers.CharField(source='declarado_por.username', read_only=True)

    class Meta:
        model = ExtravioCilindroRegistro
        fields = [
            'id', 'cilindro', 'cilindro_numero_serie', 'cliente', 'cliente_nome',
            'data_extravio', 'dias_em_posse_sem_giro', 'valor_reposicao',
            'justificativa', 'declarado_por', 'declarado_por_nome',
            'fatura_cobranca', 'cobrado', 'criado_em'
        ]


class FechamentoFaturaEstadiaSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    cliente_cnpj = serializers.CharField(source='cliente.cnpj', read_only=True)
    fechado_por_nome = serializers.CharField(source='fechado_por.username', read_only=True)
    itens = serializers.SerializerMethodField()
    ajustes_compensados = serializers.SerializerMethodField()
    registros_extravio = serializers.SerializerMethodField()

    class Meta:
        model = FechamentoFaturaEstadia
        fields = [
            'id', 'cliente', 'cliente_nome', 'cliente_cnpj', 'competencia_ano_mes',
            'data_fechamento', 'valor_bruto_diarias', 'valor_desconto_carencia',
            'valor_desconto_franquia', 'valor_ajustes_retroativos',
            'valor_reposicao_extravios', 'valor_liquido_total', 'status_pagamento',
            'fechado_por', 'fechado_por_nome', 'observacoes', 'itens',
            'ajustes_compensados', 'registros_extravio', 'criado_em', 'atualizado_em'
        ]

    def get_itens(self, obj):
        if hasattr(obj, 'itens_previa') and obj.itens_previa:
            return ItemFaturaEstadiaSerializer(obj.itens_previa, many=True).data
        if obj.pk:
            return ItemFaturaEstadiaSerializer(obj.itens.all(), many=True).data
        return []

    def get_ajustes_compensados(self, obj):
        if obj.pk:
            return AjusteCompetenciaEstadiaSerializer(obj.ajustes_compensados.all(), many=True).data
        return []

    def get_registros_extravio(self, obj):
        if obj.pk:
            return ExtravioCilindroRegistroSerializer(obj.registros_extravio.all(), many=True).data
        return []


class FecharFaturaInputSerializer(serializers.Serializer):
    cliente_id = serializers.IntegerField(required=True)
    competencia_ano_mes = serializers.CharField(max_length=7, required=True)
    persistir = serializers.BooleanField(required=False, default=True)


class DeclararExtravioInputSerializer(serializers.Serializer):
    cilindro_id = serializers.IntegerField(required=True)
    data_extravio = serializers.DateField(required=False, default=None)
    justificativa = serializers.CharField(required=True)


class FranquiaModeloContratoSerializer(serializers.ModelSerializer):
    modelo_descricao = serializers.CharField(source='modelo.descricao', read_only=True)

    class Meta:
        model = FranquiaModeloContrato
        fields = [
            'id', 'contrato', 'modelo', 'modelo_descricao',
            'franquia_cilindros_isentos', 'dias_carencia_giro',
            'taxa_diaria', 'valor_reposicao_extravio', 'criado_em'
        ]
        extra_kwargs = {
            'contrato': {'required': False}
        }


class ContratoComodatoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    franquias_modelo = FranquiaModeloContratoSerializer(many=True, required=False)
    ativo_hoje = serializers.SerializerMethodField()

    class Meta:
        model = ContratoComodato
        fields = [
            'id', 'cliente', 'cliente_nome', 'vigencia_inicio', 'vigencia_fim',
            'criterio_franquia', 'agrupar_franquia_filiais', 'dias_limite_extravio',
            'franquia_cilindros_isentos', 'dias_carencia_giro', 'valor_diaria_excedente',
            'custo_reposicao_casco', 'franquias_modelo', 'ativo_hoje', 'criado_em', 'atualizado_em'
        ]

    def get_ativo_hoje(self, obj):
        hoje = timezone.now().date()
        if obj.vigencia_inicio > hoje:
            return False
        if obj.vigencia_fim and obj.vigencia_fim < hoje:
            return False
        return True

    def create(self, validated_data):
        franquias_data = validated_data.pop('franquias_modelo', [])
        contrato = ContratoComodato.objects.create(**validated_data)
        for f_data in franquias_data:
            f_data.pop('contrato', None)
            FranquiaModeloContrato.objects.create(
                contrato=contrato,
                tenant=contrato.tenant,
                **f_data
            )
        return contrato

    def update(self, instance, validated_data):
        franquias_data = validated_data.pop('franquias_modelo', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if franquias_data is not None:
            modelos_enviados = []
            for f_data in franquias_data:
                f_data.pop('contrato', None)
                modelo = f_data.get('modelo')
                if modelo:
                    modelos_enviados.append(modelo.id if hasattr(modelo, 'id') else modelo)
                    FranquiaModeloContrato.objects.update_or_create(
                        contrato=instance,
                        modelo=modelo,
                        defaults={
                            'tenant': instance.tenant,
                            'franquia_cilindros_isentos': f_data.get('franquia_cilindros_isentos', 0),
                            'dias_carencia_giro': f_data.get('dias_carencia_giro', 30),
                            'taxa_diaria': f_data.get('taxa_diaria', instance.valor_diaria_excedente),
                            'valor_reposicao_extravio': f_data.get('valor_reposicao_extravio', instance.custo_reposicao_casco),
                        }
                    )
            instance.franquias_modelo.exclude(modelo_id__in=modelos_enviados).delete()

        return instance


class SimularDrillDownInputSerializer(serializers.Serializer):
    cliente_id = serializers.IntegerField(required=True)
    competencia_ano_mes = serializers.CharField(max_length=7, required=True)


