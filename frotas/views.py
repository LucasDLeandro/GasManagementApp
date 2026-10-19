from rest_framework import viewsets
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Veiculo, ManutencaoFrota, AlertaFrota
from .serializers import VeiculoSerializer, ManutencaoFrotaSerializer, AlertaFrotaSerializer

class FrotasTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'frotas/index.html'

class VeiculoViewSet(viewsets.ModelViewSet):
    queryset = Veiculo.objects.all()
    serializer_class = VeiculoSerializer

class ManutencaoFrotaViewSet(viewsets.ModelViewSet):
    queryset = ManutencaoFrota.objects.all()
    serializer_class = ManutencaoFrotaSerializer

class AlertaFrotaViewSet(viewsets.ModelViewSet):
    queryset = AlertaFrota.objects.all()
    serializer_class = AlertaFrotaSerializer
