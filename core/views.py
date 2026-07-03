from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum
from django.utils import timezone
import datetime

from vendas.models import Venda
from clientes.models import Cliente
from logistica.models import Veiculo
from produtos.models import Produto

class DashboardStatsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoje = timezone.now().date()
        inicio_mes = hoje.replace(day=1)

        # Faturamento do mes
        vendas_mes = Venda.objects.filter(data_venda__gte=inicio_mes).exclude(status='Cancelada')
        faturamento_mes = vendas_mes.aggregate(total=Sum('valor_total'))['total'] or 0

        # Pendentes de entrega
        entregas_pendentes = Venda.objects.filter(status__in=['Em Separação', 'Em Rota']).count()

        # Total clientes
        clientes_ativos = Cliente.objects.count()

        # Veiculos
        frota_manutencao = Veiculo.objects.filter(status='Em Manutenção').count()

        # Estoque baixo (<= 10)
        estoque_baixo = Produto.objects.filter(estoque__lte=10).count()

        # Grafico: Vendas dos ultimos 7 dias
        vendas_semana = []
        labels_semana = []
        for i in range(6, -1, -1):
            dia = hoje - datetime.timedelta(days=i)
            labels_semana.append(dia.strftime('%d/%m'))
            vendas_dia = Venda.objects.filter(data_venda__date=dia).exclude(status='Cancelada').aggregate(total=Sum('valor_total'))['total'] or 0
            vendas_semana.append(float(vendas_dia))

        data = {
            'faturamento_mes': float(faturamento_mes),
            'entregas_pendentes': entregas_pendentes,
            'clientes_ativos': clientes_ativos,
            'frota_manutencao': frota_manutencao,
            'estoque_baixo': estoque_baixo,
            'grafico_labels': labels_semana,
            'grafico_dados': vendas_semana
        }
        return Response(data)
