from rest_framework import viewsets
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework.permissions import IsAuthenticated

from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, F
from vendas.models import Venda

from .models import Cliente
from .serializers import ClienteSerializer

class ClienteViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows clientes to be viewed or edited.
    """
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        tipo_param = self.request.query_params.get('tipo', None)
        if tipo_param:
            queryset = queryset.filter(tipo_cliente=tipo_param)
        return queryset

    @action(detail=False, methods=['get'])
    def dashboard_metrics(self, request):
        total_clientes = Cliente.objects.count()
        total_pj = Cliente.objects.filter(tipo_cliente='PJ').count()
        total_gov = Cliente.objects.filter(tipo_cliente='GOV').count()

        top_clientes = Venda.objects.values(cnpj=F('cliente__cnpj'), nome=F('cliente__nome'))\
                                    .annotate(total_comprado=Sum('valor_total'))\
                                    .order_by('-total_comprado')[:5]

        return Response({
            'total_clientes': total_clientes,
            'total_pj': total_pj,
            'total_gov': total_gov,
            'top_clientes': list(top_clientes)
        })


class ClienteTemplateView(TemplateView):
    """
    View to render the Cliente frontend page with modal.
    """
    template_name = 'clientes/index.html'
