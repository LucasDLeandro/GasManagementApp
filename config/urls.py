"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from core.views import (
    pwa_manifest_view,
    pwa_service_worker_view,
    WebhookEndpointViewSet,
    WebhookDeliveryLogViewSet,
    ERPFaturasExportAPIView,
    ERPEntregasExportAPIView,
    BuscaGlobalAPIView,
    IntegracoesView,
    PerfilRegulatorioView,
)
from produtos.views import (
    SincronizarMovimentacoesOfflineAPIView,
    PassaporteSanitarioPublicoView,
    PassaporteLaudoPublicoView,
)
from logistica.views import AppCampoView

api_router = DefaultRouter()
api_router.register(r'webhooks', WebhookEndpointViewSet, basename='webhook-endpoint')
api_router.register(r'webhook-logs', WebhookDeliveryLogViewSet, basename='webhook-log')

urlpatterns = [
    # Passaporte Sanitário Público do Cilindro (Consulta via QR Code sem login)
    path('v/cilindro/<str:identificador>/', PassaporteSanitarioPublicoView.as_view(), name='passaporte_sanitario_publico'),
    path('v/cilindro/<str:identificador>/laudo/', PassaporteLaudoPublicoView.as_view(), name='passaporte_laudo_publico'),

    # PWA Service Worker e Web App Manifest no Root Scope
    path('manifest.json', pwa_manifest_view, name='pwa_manifest'),
    path('sw.js', pwa_service_worker_view, name='pwa_service_worker'),
    path('favicon.ico', RedirectView.as_view(url='/static/img/icon-192.png', permanent=False), name='favicon'),

    # Sincronização em Lote Offline (PWA Campo & Pátio - Sprint 6)
    path('api/movimentacoes/sync-offline/', SincronizarMovimentacoesOfflineAPIView.as_view(), name='sync_offline_movimentacoes'),

    # Endpoints Canônicos de Exportação ERP e Webhooks (Sprint 6 & Fase 5)
    path('api/erp/faturas/', ERPFaturasExportAPIView.as_view(), name='erp_export_faturas'),
    path('api/erp/entregas/', ERPEntregasExportAPIView.as_view(), name='erp_export_entregas'),
    path('api/busca-global/', BuscaGlobalAPIView.as_view(), name='api_busca_global'),
    path('api/', include(api_router.urls)),

    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/inicio/', permanent=False), name='root'),
    path('integracoes/', IntegracoesView.as_view(), name='integracoes_root'),
    path('perfil-regulatorio/', PerfilRegulatorioView.as_view(), name='perfil_regulatorio_root'),
    path('campo/', AppCampoView.as_view(), name='app_campo'),
    path('login/', RedirectView.as_view(url='/accounts/login/', permanent=False)),
    path('accounts/', include('accounts.urls')),
    path('inicio/', include('core.urls')),
    path('clientes/', include('clientes.urls')),
    path('produtos/', include('produtos.urls', namespace='produtos')),
    path('vendas/', include('vendas.urls', namespace='vendas')),
    path('logistica/', include('logistica.urls', namespace='logistica')),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponseForbidden, Http404, FileResponse
from core.tenancy import get_current_tenant
from core.permissions import resolve_request_membership

def protected_media_assinatura_view(request, path):
    """
    Protege o acesso aos arquivos de assinatura em MEDIA_ROOT (D8).
    Exige autenticação e validação estrita de Tenant.
    """
    if not (request.user and request.user.is_authenticated):
        return HttpResponseForbidden("Acesso restrito: autenticação obrigatória.")

    from logistica.models import ComprovanteEntrega
    comprovante = ComprovanteEntrega.unscoped.filter(assinatura_imagem__icontains=path).first()
    if not comprovante or not comprovante.assinatura_imagem:
        raise Http404("Comprovante de assinatura não encontrado.")

    if not request.user.is_superuser:
        current_tenant = get_current_tenant()
        if not current_tenant:
            membership = resolve_request_membership(request)
            if membership:
                current_tenant = membership.tenant

        if not current_tenant or comprovante.tenant_id != current_tenant.id:
            return HttpResponseForbidden("Acesso negado: comprovante pertence a outra empresa.")

    return FileResponse(comprovante.assinatura_imagem.open('rb'), content_type='image/png')

urlpatterns.insert(0, path('media/comprovantes_assinaturas/<path:path>', protected_media_assinatura_view, name='protected_media_assinatura'))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
