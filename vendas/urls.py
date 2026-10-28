from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VendaViewSet, VendaTemplateView, AlertaComercialViewSet

router = DefaultRouter()
router.register(r'api/alertas', AlertaComercialViewSet, basename='alerta-comercial')
router.register(r'api', VendaViewSet, basename='venda')

app_name = 'vendas'

urlpatterns = [
    path('', VendaTemplateView.as_view(), name='index'),
    path('', include(router.urls)),
]
