from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FrotasTemplateView, VeiculoViewSet, ManutencaoFrotaViewSet, AlertaFrotaViewSet

router = DefaultRouter()
router.register(r'veiculos', VeiculoViewSet, basename='veiculo')
router.register(r'manutencoes', ManutencaoFrotaViewSet, basename='manutencao')
router.register(r'alertas', AlertaFrotaViewSet, basename='alerta')

app_name = 'frotas'

urlpatterns = [
    path('', FrotasTemplateView.as_view(), name='index'),
    path('api/', include(router.urls)),
]
