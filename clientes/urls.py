from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClienteViewSet, ClienteTemplateView,
    ContratoComodatoViewSet,
    FechamentoFaturaEstadiaViewSet, ExtravioCilindroViewSet
)

router = DefaultRouter()
router.register(r'api/contratos', ContratoComodatoViewSet, basename='contrato-comodato')
router.register(r'api/faturas-estadia', FechamentoFaturaEstadiaViewSet, basename='fatura-estadia')
router.register(r'api/extravios', ExtravioCilindroViewSet, basename='extravio-cilindro')
router.register(r'api', ClienteViewSet, basename='cliente-api')

app_name = 'clientes'

urlpatterns = [
    # Rota para a view HTML do frontend
    path('', ClienteTemplateView.as_view(), name='index'),
    
    # Rotas da API (ex: /clientes/api/)
    path('', include(router.urls)),
]

