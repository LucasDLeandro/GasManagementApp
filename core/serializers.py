from rest_framework import serializers
from .models import WebhookEndpoint, WebhookDeliveryLog, validar_url_webhook_segura

class WebhookEndpointSerializer(serializers.ModelSerializer):
    secret_mascarado = serializers.SerializerMethodField()

    class Meta:
        model = WebhookEndpoint
        fields = [
            'id',
            'url',
            'secret',
            'secret_mascarado',
            'eventos',
            'ativo',
            'descricao',
            'criado_em',
            'atualizado_em'
        ]
        read_only_fields = ['id', 'criado_em', 'atualizado_em', 'secret_mascarado']
        extra_kwargs = {
            'secret': {'write_only': True, 'required': False}
        }

    def get_secret_mascarado(self, obj):
        return '••••••••••••••••••••••••••••••••'

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Exibição única de segredo apenas quando recém-criado ou rotacionado
        if getattr(instance, '_raw_secret', None):
            ret['secret_exclusivo'] = instance._raw_secret
        return ret

    def validate_url(self, value):
        validar_url_webhook_segura(value)
        return value


class WebhookDeliveryLogSerializer(serializers.ModelSerializer):
    endpoint_url = serializers.CharField(source='endpoint.url', read_only=True)

    class Meta:
        model = WebhookDeliveryLog
        fields = [
            'id',
            'endpoint',
            'endpoint_url',
            'evento',
            'payload',
            'status',
            'status_code',
            'sucesso',
            'resposta_body',
            'latencia_ms',
            'tentativas',
            'enviado_em'
        ]
        read_only_fields = ['id', 'enviado_em']

