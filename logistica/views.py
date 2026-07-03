from rest_framework import viewsets
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Veiculo, Rota, ManutencaoFrota, TabelaFrete
from .serializers import VeiculoSerializer, RotaSerializer, ManutencaoFrotaSerializer, TabelaFreteSerializer

class LogisticaTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'logistica/index.html'

class VeiculoViewSet(viewsets.ModelViewSet):
    queryset = Veiculo.objects.all()
    serializer_class = VeiculoSerializer

class RotaViewSet(viewsets.ModelViewSet):
    queryset = Rota.objects.all()
    serializer_class = RotaSerializer

class ManutencaoFrotaViewSet(viewsets.ModelViewSet):
    queryset = ManutencaoFrota.objects.all()
    serializer_class = ManutencaoFrotaSerializer

class TabelaFreteViewSet(viewsets.ModelViewSet):
    queryset = TabelaFrete.objects.all()
    serializer_class = TabelaFreteSerializer

# Trigger reload
