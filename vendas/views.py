from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count
from django.utils import timezone
import datetime

from .models import Venda, ItemVenda
from .serializers import VendaSerializer
from django.db.models import Sum, Count, F

class VendaViewSet(viewsets.ModelViewSet):
    queryset = Venda.objects.all()
    serializer_class = VendaSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get('status', None)
        entrega_isnull = self.request.query_params.get('entrega__isnull', None)

        if status_param:
            # Permite filtrar múltiplos status separados por vírgula
            status_list = status_param.split(',')
            queryset = queryset.filter(status__in=status_list)
        
        if entrega_isnull is not None:
            is_null = str(entrega_isnull).lower() in ['true', '1', 't', 'y', 'yes']
            queryset = queryset.filter(entrega__isnull=is_null)

        return queryset

    @action(detail=False, methods=['get'])
    def dashboard_metrics(self, request):
        now = timezone.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        vendas_mes = Venda.objects.filter(data_venda__gte=start_of_month)
        
        faturamento_total = vendas_mes.aggregate(Sum('valor_total'))['valor_total__sum'] or 0
        total_vendas = vendas_mes.count()
        vendas_pendentes = vendas_mes.filter(status='Pendente').count()
        vendas_em_entrega = vendas_mes.filter(status__in=['Em Separação', 'Em Rota']).count()

        # Agrupar vendas por dia para o gráfico
        grafico_dados = vendas_mes.extra(select={'dia': 'date(data_venda)'}).values('dia').annotate(total=Sum('valor_total')).order_by('dia')

        # Novas Métricas
        ticket_medio = round((faturamento_total / total_vendas), 2) if total_vendas > 0 else 0

        vendas_por_categoria = vendas_mes.values(categoria=F('itens__produto__categoria')).annotate(total_vendido=Sum('itens__valor_total')).exclude(categoria__isnull=True)
        
        top_produtos = ItemVenda.objects.filter(venda__data_venda__gte=start_of_month)\
                                        .values(nome=F('produto__nome'))\
                                        .annotate(total_qtd=Sum('quantidade'))\
                                        .order_by('-total_qtd')[:3]

        return Response({
            'faturamento_total': faturamento_total,
            'total_vendas': total_vendas,
            'vendas_pendentes': vendas_pendentes,
            'vendas_em_entrega': vendas_em_entrega,
            'grafico': list(grafico_dados),
            'ticket_medio': ticket_medio,
            'vendas_por_categoria': list(vendas_por_categoria),
            'top_produtos': list(top_produtos)
        })

    @action(detail=True, methods=['post'])
    def alterar_status(self, request, pk=None):
        venda = self.get_object()
        novo_status = request.data.get('status')
        if novo_status not in dict(Venda.STATUS_CHOICES):
            return Response({'error': 'Status inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        
        venda.status = novo_status
        venda.save()
        return Response({'status': 'sucesso', 'novo_status': venda.status})


class VendaTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'vendas/index.html'
