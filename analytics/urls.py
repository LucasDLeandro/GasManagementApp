from django.urls import path, include
from rest_framework.routers import DefaultRouter

from analytics.views import (
    AnalyticsViewSet,
    AlertaOportunidadeComercialViewSet,
    FunilAlertasTemplateView,
)

app_name = 'analytics'

router = DefaultRouter()
router.register(r'alertas', AlertaOportunidadeComercialViewSet, basename='alertas-oportunidade')
router.register(r'', AnalyticsViewSet, basename='analytics')

urlpatterns = [
    path('funil-alertas/', FunilAlertasTemplateView.as_view(), name='funil-alertas'),
    path('', include(router.urls)),
]
