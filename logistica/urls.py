from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LogisticaTemplateView,
    AppCampoView,
    VeiculoViewSet,
    RotaViewSet,
    ManutencaoFrotaViewSet,
    TabelaFreteViewSet,
    ValidacaoCargaViewSet,
    EntregaViewSet,
    ComprovanteAssinaturaDownloadView
)

router = DefaultRouter()
router.register(r'veiculos', VeiculoViewSet, basename='veiculo')
router.register(r'rotas', RotaViewSet, basename='rota')
router.register(r'manutencoes', ManutencaoFrotaViewSet, basename='manutencao')
router.register(r'fretes', TabelaFreteViewSet, basename='frete')
router.register(r'validacoes', ValidacaoCargaViewSet, basename='validacao')
router.register(r'entregas', EntregaViewSet, basename='entrega')

app_name = 'logistica'

urlpatterns = [
    path('', LogisticaTemplateView.as_view(), name='index'),
    path('campo/', AppCampoView.as_view(), name='campo'),
    path('app/', AppCampoView.as_view(), name='app_campo'),
    path('api/comprovantes/<int:pk>/assinatura/', ComprovanteAssinaturaDownloadView.as_view(), name='download_assinatura_comprovante'),
    path('api/', include(router.urls)),
]

