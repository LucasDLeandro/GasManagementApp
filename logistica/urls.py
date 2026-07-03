from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LogisticaTemplateView, VeiculoViewSet, RotaViewSet, ManutencaoFrotaViewSet, TabelaFreteViewSet

router = DefaultRouter()
router.register(r'veiculos', VeiculoViewSet, basename='veiculo')
router.register(r'rotas', RotaViewSet, basename='rota')
router.register(r'manutencoes', ManutencaoFrotaViewSet, basename='manutencao')
router.register(r'fretes', TabelaFreteViewSet, basename='frete')

app_name = 'logistica'

urlpatterns = [
    path('', LogisticaTemplateView.as_view(), name='index'),
    path('api/', include(router.urls)),
]
