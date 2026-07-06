from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from .views import DashboardStatsAPIView

app_name = 'core'

urlpatterns = [
    path('', login_required(TemplateView.as_view(template_name='core/home.html')), name='inicio'),
    path('api/stats/', DashboardStatsAPIView.as_view(), name='api_stats'),
]