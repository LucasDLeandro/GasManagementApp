from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from .views import (
    DashboardStatsAPIView,
    HomeView,
    TrocarTenantView,
    IntegracoesView,
    PerfilRegulatorioView,
    ExportacaoDadosTenantView,
)

app_name = 'core'

urlpatterns = [
    path('', HomeView.as_view(), name='inicio'),
    path('integracoes/', IntegracoesView.as_view(), name='integracoes'),
    path('perfil-regulatorio/', PerfilRegulatorioView.as_view(), name='perfil_regulatorio'),
    path('trocar-tenant/', TrocarTenantView.as_view(), name='trocar_tenant'),
    path('api/stats/', DashboardStatsAPIView.as_view(), name='api_stats'),
    path('exportar-dados/', ExportacaoDadosTenantView.as_view(), name='exportar_dados'),
]