from decimal import Decimal
import datetime
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, F, Q
from django.db.models.functions import TruncDate, Coalesce
from django.utils import timezone

from core.mixins import TenantViewSetMixin
from core.tenancy import get_current_tenant
from core.permissions import RequiresModuleVendas
from .models import Venda, ItemVenda, AlertaComercial
from .serializers import VendaSerializer, AlertaComercialSerializer

class VendaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Venda.unscoped.all()
    serializer_class = VendaSerializer
    permission_classes = [IsAuthenticated, RequiresModuleVendas]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtro por grupo_status (Fila Ativa, Concluídas, Canceladas)
        grupo_status = self.request.query_params.get('grupo_status', None)
        if grupo_status:
            grupo = grupo_status.strip().lower()
            if grupo == 'ativas':
                queryset = queryset.filter(status__in=['Pendente', 'Em Separação', 'Em Rota'])
            elif grupo == 'concluidas':
                queryset = queryset.filter(status__in=['Entregue', 'Finalizada'])
            elif grupo == 'canceladas':
                queryset = queryset.filter(status='Cancelada')

        status_param = self.request.query_params.get('status', None)
        if status_param:
            status_list = [s.strip() for s in status_param.split(',') if s.strip()]
            queryset = queryset.filter(status__in=status_list)
        
        entrega_isnull = self.request.query_params.get('entrega__isnull', None)
        if entrega_isnull is not None:
            is_null = str(entrega_isnull).lower() in ['true', '1', 't', 'y', 'yes']
            queryset = queryset.filter(entrega__isnull=is_null)

        search = self.request.query_params.get('search', None)
        if search:
            search = search.strip()
            queryset = queryset.filter(
                Q(id__icontains=search) |
                Q(cliente__nome__icontains=search) |
                Q(cliente__cnpj__icontains=search) |
                Q(documento_fiscal_ref__icontains=search)
            )

        return queryset.select_related('cliente', 'vendedor', 'entrega').prefetch_related('itens__produto', 'itens__sku')

    @action(detail=True, methods=['post'], url_path='liberar-bloqueio')
    def liberar_bloqueio(self, request, pk=None):
        """Libera venda com BLOQUEADO_FINANCEIRO exigindo permissão vendas.liberar_bloqueio_financeiro e motivo."""
        venda = self.get_object()
        motivo = request.data.get('motivo', '')
        from vendas.services.liberacao_service import liberar_bloqueio_venda
        from django.core.exceptions import ValidationError as DjangoValidationError, PermissionDenied as DjangoPermissionDenied
        try:
            liberacao = liberar_bloqueio_venda(venda=venda, usuario=request.user, motivo=motivo)
            return Response({
                'mensagem': 'Venda liberada com sucesso.',
                'venda_id': venda.id,
                'status': venda.status,
                'liberacao_id': liberacao.id
            }, status=status.HTTP_200_OK)
        except DjangoPermissionDenied as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def dashboard_metrics(self, request):
        now = timezone.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Garante filtro restrito ao tenant da requisição
        vendas_mes = self.get_queryset().filter(data_venda__gte=start_of_month)
        
        faturamento_total = vendas_mes.aggregate(Sum('valor_total'))['valor_total__sum'] or Decimal('0.00')
        total_vendas = vendas_mes.count()
        vendas_pendentes = vendas_mes.filter(status='Pendente').count()
        vendas_em_entrega = vendas_mes.filter(status__in=['Em Separação', 'Em Rota']).count()

        # Agrupar vendas por dia para o gráfico utilizando TruncDate
        dias_agg = (
            vendas_mes.annotate(dia_trunc=TruncDate('data_venda'))
            .values('dia_trunc')
            .annotate(total=Sum('valor_total'))
            .order_by('dia_trunc')
        )
        grafico_dados = []
        for d in dias_agg:
            dt = d['dia_trunc']
            dia_str = dt.strftime('%d/%m') if hasattr(dt, 'strftime') else str(dt)
            grafico_dados.append({
                'dia': dia_str,
                'total': float(d['total'] or 0)
            })

        ticket_medio = round((float(faturamento_total) / total_vendas), 2) if total_vendas > 0 else 0

        vendas_por_categoria = (
            vendas_mes.values(categoria=F('itens__produto__categoria'))
            .annotate(total_vendido=Sum('itens__valor_total'))
            .exclude(categoria__isnull=True)
        )
        
        # Top 3 produtos mais vendidos estritamente dentro das vendas do mês do tenant
        top_produtos = (
            ItemVenda.objects.filter(venda__in=vendas_mes)
            .values(nome=Coalesce('produto__nome', 'sku__nome_comercial'))
            .annotate(total_qtd=Sum('quantidade'))
            .order_by('-total_qtd')[:3]
        )

        return Response({
            'faturamento_total': float(faturamento_total),
            'total_vendas': total_vendas,
            'vendas_pendentes': vendas_pendentes,
            'vendas_em_entrega': vendas_em_entrega,
            'grafico': grafico_dados,
            'ticket_medio': ticket_medio,
            'vendas_por_categoria': list(vendas_por_categoria),
            'top_produtos': list(top_produtos)
        })

    @action(detail=True, methods=['post'])
    def alterar_status(self, request, pk=None):
        venda = self.get_object()
        from core.guards import assert_modulo, assert_tenant_writable
        from core.eventos import publicar
        assert_tenant_writable(venda.tenant)
        novo_status = request.data.get('status')
        if novo_status not in dict(Venda.STATUS_CHOICES):
            return Response({'error': 'Status inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        
        venda.status = novo_status

        # Se solicitar criação de entrega ou se estiver iniciando separação
        if request.data.get('gerar_entrega_logistica') and not venda.entrega:
            assert_modulo(venda.tenant, 'logistica')
            from logistica.models import Entrega
            nova_entrega = Entrega.objects.create(tenant=venda.tenant, status='Agendada')
            venda.entrega = nova_entrega

        venda.save()

        # Publica evento de domínio quando faturada/finalizada (Sprint 8C / Sprint 11A - Tarefa 9)
        if novo_status in ('Faturada', 'Finalizada'):
            custo_total_cpv = Decimal('0.00')
            try:
                from produtos.services.estoque_produto import baixar_estoque_venda_faturada
                custo_total_cpv = baixar_estoque_venda_faturada(venda)
            except Exception:
                pass

            # Sprint 11A - Tarefa 9: com modulo_fiscal_ativo, a venda só publica
            # venda_faturada quando a NF-e estiver AUTORIZADA, com os tributos reais.
            from core.modulos import is_modulo_ativo
            if not is_modulo_ativo(venda.tenant, 'fiscal'):
                publicar('venda_faturada', {
                    'tenant': venda.tenant,
                    'venda_id': str(venda.id),
                    'cliente_id': str(venda.cliente_id) if venda.cliente else None,
                    'valor_total': venda.valor_total,
                    'custo_total': custo_total_cpv,
                })

        return Response({
            'status': 'sucesso',
            'novo_status': venda.status,
            'entrega_id': venda.entrega_id if venda.entrega else None
        })

    @action(detail=True, methods=['post'])
    def enviar_para_logistica(self, request, pk=None):
        venda = self.get_object()
        from core.guards import assert_modulo, assert_tenant_writable
        assert_tenant_writable(venda.tenant)
        assert_modulo(venda.tenant, 'logistica')
        if not venda.entrega:
            from logistica.models import Entrega
            nova_entrega = Entrega.objects.create(tenant=venda.tenant, status='Agendada')
            venda.entrega = nova_entrega
        if venda.status == 'Pendente':
            venda.status = 'Em Separação'
        venda.save()
        return Response({
            'status': 'sucesso',
            'novo_status': venda.status,
            'entrega_id': venda.entrega_id
        })


from django.core.exceptions import PermissionDenied

class VendaTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'vendas/index.html'

    def dispatch(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if not (request.user.is_superuser or (tenant and tenant.modulo_vendas_ativo)):
            raise PermissionDenied("Acesso negado: Seu plano não contempla o Módulo de Vendas.")
        return super().dispatch(request, *args, **kwargs)


class AlertaComercialViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Visualização e gestão de Alertas Comerciais Preditivos (Risco de Churn).
    O painel de vendas consome AlertaComercial.objects.filter(resolvido=False).
    """
    queryset = AlertaComercial.unscoped.all()
    serializer_class = AlertaComercialSerializer
    permission_classes = [IsAuthenticated, RequiresModuleVendas]

    def get_queryset(self):
        queryset = super().get_queryset()
        apenas_pendentes = self.request.query_params.get('pendentes', 'true').lower() in ('1', 'true')
        if apenas_pendentes:
            queryset = queryset.filter(resolvido=False)
        return queryset.select_related('cliente', 'resolvido_por').order_by('-dias_sem_comprar', '-criado_em')

    @action(detail=True, methods=['post'], url_path='resolver')
    def resolver(self, request, pk=None):
        alerta = self.get_object()
        observacao = request.data.get('observacao', '')
        alerta.marcar_como_resolvido(usuario=request.user, observacao=observacao)
        return Response(AlertaComercialSerializer(alerta).data, status=status.HTTP_200_OK)

