from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, PessoalTemplateView, LoginView, CustomLoginAPIView, PerfilUsuarioTemplateView

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

app_name = 'accounts'

urlpatterns = [
    path('pessoal/', PessoalTemplateView.as_view(), name='pessoal_index'),
    path('login/', LoginView.as_view(), name='login'),
    path('meu-perfil/', PerfilUsuarioTemplateView.as_view(), name='meu_perfil'),
    path('api/login/', CustomLoginAPIView.as_view(), name='api_login'),
    path('api/', include(router.urls)),
]