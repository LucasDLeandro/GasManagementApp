from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProdutoViewSet, ProdutoTemplateView

router = DefaultRouter()
router.register(r'api', ProdutoViewSet, basename='produto-api')

app_name = 'produtos'

urlpatterns = [
    # Rota para a view HTML do frontend
    path('', ProdutoTemplateView.as_view(), name='index'),
    
    # Rotas da API (ex: /produtos/api/)
    path('', include(router.urls)),
]
