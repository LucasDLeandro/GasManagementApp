from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import UserViewSet

app_name = 'accounts'

router = DefaultRouter()

router.register(r'users', UserViewSet, basename='users')

urlpatterns = [
    path('', include(router.urls)),
]