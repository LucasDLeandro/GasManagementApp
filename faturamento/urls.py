from django.urls import path, include
from rest_framework.routers import DefaultRouter
from faturamento.views import (
    WebhookGatewayPagamentoView,
    WebhookNFeView,
    FaturaCobrancaPublicaView,
    SolicitarEmissaoNFeAPIView,
    NotaFiscalViewSet,
    FaturaCobrancaViewSet,
    ConfiguracaoFiscalTenantViewSet,
)

app_name = 'faturamento'

router = DefaultRouter()
router.register(r'notas-fiscais', NotaFiscalViewSet, basename='nota-fiscal')
router.register(r'cobrancas', FaturaCobrancaViewSet, basename='cobranca')
router.register(r'configuracao-fiscal', ConfiguracaoFiscalTenantViewSet, basename='configuracao-fiscal')

urlpatterns = [
    # Webhooks Externos Seguros (HMAC-SHA256)
    path('webhooks/gateway/', WebhookGatewayPagamentoView.as_view(), name='webhook_gateway_pagamento'),
    path('webhooks/nfe/', WebhookNFeView.as_view(), name='webhook_nfe'),

    # Consulta Pública Segura (UUIDv4)
    path('cobranca/<uuid:fatura_uuid>/', FaturaCobrancaPublicaView.as_view(), name='cobranca_publica'),

    # Emissão Assíncrona Celery
    path('nfe/solicitar-emissao/', SolicitarEmissaoNFeAPIView.as_view(), name='solicitar_emissao_nfe'),

    # API ViewSets Protegidos por Tenant
    path('api/', include(router.urls)),
]
