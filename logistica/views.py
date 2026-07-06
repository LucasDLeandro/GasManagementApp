from rest_framework import viewsets
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Veiculo, Rota, ManutencaoFrota, TabelaFrete, ValidacaoCarga, Entrega
from .serializers import VeiculoSerializer, RotaSerializer, ManutencaoFrotaSerializer, TabelaFreteSerializer, ValidacaoCargaSerializer, EntregaSerializer
from vendas.models import ItemVenda

class LogisticaTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'logistica/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        context['motoristas'] = User.objects.filter(is_active=True)
        return context

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

class ValidacaoCargaViewSet(viewsets.ModelViewSet):
    queryset = ValidacaoCarga.objects.all()
    serializer_class = ValidacaoCargaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        entrega_id = self.request.query_params.get('entrega', None)
        if entrega_id:
            qs = qs.filter(entrega_id=entrega_id)
        return qs

    def perform_create(self, serializer):
        validacao = serializer.save()
        item = ItemVenda.objects.filter(venda=validacao.venda, produto=validacao.produto).first()
        if item:
            item.quantidade += validacao.quantidade_alterada
            if item.quantidade < 0:
                item.quantidade = 0
            item.save()
            validacao.venda.calcular_total()

class EntregaViewSet(viewsets.ModelViewSet):
    queryset = Entrega.objects.all()
    serializer_class = EntregaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get('status', None)
        if status:
            statuses = status.split(',')
            qs = qs.filter(status__in=statuses)
        return qs

# Trigger reload
