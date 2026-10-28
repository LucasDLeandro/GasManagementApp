"""
Configuração de rotas do Portal B2B do Cliente Final (Sprint 12B).

Mapeia:
- Rotas de API sob /portal-b2b/api/ (compatível com Sprint 9 e expandido para Sprint 12B)
- Rotas Web Mobile-First sob /portal-b2b/ (dashboard, login, mfa, convite, termo, download)
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from portal_b2b.views import (
    B2BVendaViewSet,
    B2BFaturaViewSet,
    B2BCilindroViewSet,
    B2BReposicaoViewSet,
    B2BEquipeViewSet,
    B2BPerfilView,
    B2BFinanceiroAPIView,
    B2BFiscalAPIView,
    B2BEntregasAPIView,
    B2BNotificacoesAPIView,
    B2BDownloadView,
    B2BLoginView,
    B2BLogoutView,
    B2BMFAView,
    B2BTermoView,
    B2BConviteAceiteView,
    B2BDashboardView,
)

app_name = 'portal_b2b'

router = DefaultRouter()
router.register(r'vendas', B2BVendaViewSet, basename='b2b-venda')
router.register(r'faturas', B2BFaturaViewSet, basename='b2b-fatura')
router.register(r'cilindros', B2BCilindroViewSet, basename='b2b-cilindro')
router.register(r'reposicao', B2BReposicaoViewSet, basename='b2b-reposicao')
router.register(r'equipe', B2BEquipeViewSet, basename='b2b-equipe')

urlpatterns = [
    # Rotas de API REST (/portal-b2b/api/...)
    path('api/perfil/', B2BPerfilView.as_view(), name='b2b-perfil'),
    path('api/financeiro/', B2BFinanceiroAPIView.as_view(), name='b2b-financeiro'),
    path('api/fiscal/', B2BFiscalAPIView.as_view(), name='b2b-fiscal'),
    path('api/entregas/', B2BEntregasAPIView.as_view(), name='b2b-entregas'),
    path('api/notificacoes/', B2BNotificacoesAPIView.as_view(), name='b2b-notificacoes'),
    path('api/download/<str:token>/', B2BDownloadView.as_view(), name='b2b-download-api'),
    path('api/', include(router.urls)),

    # Rotas Web Mobile-First (/portal-b2b/...)
    path('login/', B2BLoginView.as_view(), name='login'),
    path('logout/', B2BLogoutView.as_view(), name='logout'),
    path('mfa/', B2BMFAView.as_view(), name='mfa'),
    path('termo/', B2BTermoView.as_view(), name='termo'),
    path('convite/<str:token>/', B2BConviteAceiteView.as_view(), name='convite'),
    path('download/<str:token>/', B2BDownloadView.as_view(), name='download'),
    path('', B2BDashboardView.as_view(), name='dashboard'),
]
