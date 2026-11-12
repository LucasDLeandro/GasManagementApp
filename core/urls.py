from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from rest_framework.routers import DefaultRouter
from .views import (
    DashboardStatsAPIView,
    HomeView,
    TrocarTenantView,
    IntegracoesView,
    PerfilRegulatorioView,
    ExportacaoDadosTenantView,
)
from .views_painel import PainelMonitorViewSet

app_name = 'core'

router = DefaultRouter()
router.register(r'api/paineis', PainelMonitorViewSet, basename='painel-monitor')

urlpatterns = [
    path('', HomeView.as_view(), name='inicio'),
    path('integracoes/', IntegracoesView.as_view(), name='integracoes'),
    path('perfil-regulatorio/', PerfilRegulatorioView.as_view(), name='perfil_regulatorio'),
    path('trocar-tenant/', TrocarTenantView.as_view(), name='trocar_tenant'),
    path('api/stats/', DashboardStatsAPIView.as_view(), name='api_stats'),
    path('exportar-dados/', ExportacaoDadosTenantView.as_view(), name='exportar_dados'),
] + router.urls
