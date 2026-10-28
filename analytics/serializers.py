"""
Serializers para Alertas Comerciais Preditivos e Funil (Sprint 12C).
"""
from decimal import Decimal
from rest_framework import serializers

from analytics.models import AlertaOportunidadeComercial


class AlertaOportunidadeComercialSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    gas_nome = serializers.CharField(source='gas.nome', read_only=True)
    responsavel_nome = serializers.CharField(source='responsavel.username', read_only=True)

    class Meta:
        model = AlertaOportunidadeComercial
        fields = [
            'id',
            'cliente',
            'cliente_nome',
            'gas',
            'gas_nome',
            'tipo',
            'tipo_display',
            'score',
            'evidencia_json',
            'status',
            'status_display',
            'responsavel',
            'responsavel_nome',
            'data_ref',
            'chave_idempotencia',
            'criado_em',
            'resolvido_em',
            'feedback',
        ]
        read_only_fields = [
            'id',
            'tipo_display',
            'status_display',
            'cliente_nome',
            'gas_nome',
            'responsavel_nome',
            'chave_idempotencia',
            'criado_em',
            'resolvido_em',
        ]


class AtualizarStatusAlertaSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=AlertaOportunidadeComercial.STATUS_CHOICES)
    feedback = serializers.CharField(required=False, allow_blank=True, default='')


class BacktestRequestSerializer(serializers.Serializer):
    dias_horizonte = serializers.IntegerField(default=30, min_value=1, max_value=365)
    k = serializers.FloatField(default=2.0, min_value=0.5, max_value=5.0)
    data_limite = serializers.DateField(required=False, allow_null=True, default=None)
