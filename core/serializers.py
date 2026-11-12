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


class PainelMonitorSerializer(serializers.ModelSerializer):
    url_painel = serializers.SerializerMethodField()

    class Meta:
        from .models import PainelMonitor
        model = PainelMonitor
        fields = [
            'id',
            'nome',
            'filial',
            'token',
            'ativo',
            'mostrar_nomes_clientes',
            'tempo_alerta_min',
            'tempo_critico_min',
            'secoes',
            'ultimo_acesso_em',
            'criado_em',
            'url_painel',
        ]
        read_only_fields = ['id', 'token', 'ultimo_acesso_em', 'criado_em', 'url_painel']

    def get_url_painel(self, obj):
        request = self.context.get('request')
        relative_url = f"/painel/{obj.token}/"
        if request:
            return request.build_absolute_uri(relative_url)
        return relative_url



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

