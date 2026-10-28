import datetime
from decimal import Decimal
from django.db import models
from django.db.models import Sum, Count, Avg
from django.db.models.functions import TruncMonth
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.core.cache import cache
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core.mixins import TenantViewSetMixin
from core.permissions import (
    IsTenantMember,
    RequiresModuleAnalytics,
    user_has_ver_dre,
)
from core.modulos import is_modulo_ativo
from vendas.models import Venda, ItemVenda, AlertaComercial
from produtos.models import Cilindro
from faturamento.models import FaturaCobranca
from financeiro.models import AlertaCaixa
from financeiro.services.fluxo_caixa_service import obter_fluxo_caixa_realizado
from financeiro.services.projecao_caixa_service import projetar_fluxo_caixa_cenarios
from logistica.services.margem_veiculo_service import (
    calcular_margem_contribuicao_veiculo,
    calcular_tco_veiculo,
)
from produtos.services.cilindro_retencao_service import (
    analise_retencao_cilindros_consolidada,
    calcular_custo_retencao_cilindro,
)
from analytics.models import AlertaOportunidadeComercial
from analytics.serializers import AlertaOportunidadeComercialSerializer
from analytics.services.indicadores_service import calcular_indicadores_gestao


class AnalyticsViewSet(TenantViewSetMixin, viewsets.ViewSet):
    """
    Motor de Analytics e Inteligência Operacional/Comercial (Sprint 10 & 10C).
    Otimização severa de queries: execução 100% no motor de agregação do banco de dados (ORM),
    sem alocação de QuerySets volumosos na memória do servidor.
    Todas as rotas GET são cacheadas por 15 minutos (60 * 15) no Redis.
    Degradação graciosa: cada widget só aparece se o módulo fonte estiver ativo (Sprint 7B).
    Widgets financeiros exigem permissão financeiro.ver_dre.
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantMember, RequiresModuleAnalytics]

    def list(self, request):
        """
        Dashboard consolidado de BI e Gestão com degradação graciosa por módulo ativo (Sprint 10C - Tarefa 9).
        Toda métrica detalha sua fórmula auditável e fonte de dados.
        Cache de 15 minutos isolado por tenant, usuário e permissão DRE.
        """
        tenant = getattr(request, 'tenant', None)
        user_id = getattr(request.user, 'id', 'anon')
        tenant_id = getattr(tenant, 'id', 'notenant')
        has_dre = user_has_ver_dre(request)
        cache_key = f"analytics_dashboard_{tenant_id}_{user_id}_{has_dre}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        widgets = {}

        # 1. Widget de Vendas / Comercial
        if is_modulo_ativo(tenant, 'vendas'):
            aggr_vendas = Venda.unscoped.filter(
                tenant=tenant
            ).exclude(
                status='Cancelada'
            ).aggregate(
                faturamento_total=Sum('valor_total'),
                ticket_medio=Avg('valor_total'),
                total_pedidos=Count('id')
            )
            widgets['resumo_executivo'] = {
                'faturamento_total': aggr_vendas['faturamento_total'] or Decimal('0.00'),
                'ticket_medio': aggr_vendas['ticket_medio'] or Decimal('0.00'),
                'total_pedidos': aggr_vendas['total_pedidos'] or 0,
                'formula': "Faturamento = Σ valor_total das vendas; Ticket Médio = Faturamento / Total de Pedidos",
                'fonte': "Tabela Vendas (excluindo vendas com status 'Cancelada')"
            }

        # 2. Widget de Patrimônio / Parque de Cilindros
        if is_modulo_ativo(tenant, 'patrimonio'):
            aggr_cilindros = Cilindro.unscoped.filter(tenant=tenant).aggregate(
                total_parque=Count('id'),
                em_posse_clientes=Count('id', filter=models.Q(status='EM_POSSE_CLIENTE')),
                disponivel_patio=Count('id', filter=models.Q(status='CHEIO_DISPONIVEL')),
                vazio_triagem=Count('id', filter=models.Q(status='VAZIO_TRIAGEM'))
            )
            aggr_cilindros['formula'] = "Contagem consolidada de cilindros agrupados por status operacional"
            aggr_cilindros['fonte'] = "Tabela Cilindro (Patrimônio Rastreável)"
            widgets['parque_cilindros'] = aggr_cilindros

            # Resumo de retenção de cilindro parado
            try:
                ret_resumo = analise_retencao_cilindros_consolidada(tenant=tenant)
                widgets['retencao_cilindros_resumo'] = {
                    'total_analisados': ret_resumo.get('total_analisados', 0),
                    'total_destruidores_margem': ret_resumo.get('total_destruidores_margem', 0),
                    'custo_liquido_total': ret_resumo.get('custo_liquido_total', Decimal('0.00')),
                    'formula': ret_resumo.get('formula'),
                    'fonte': ret_resumo.get('fonte')
                }
            except Exception:
                pass

        # 3. Widget Financeiro (Exige módulo financeiro E permissão ver_dre)
        if is_modulo_ativo(tenant, 'financeiro') and user_has_ver_dre(request):
            aggr_cobranca = FaturaCobranca.unscoped.filter(
                tenant=tenant,
                status__in=['ABERTA', 'VENCIDA']
            ).aggregate(
                total_inadimplencia_aberto=Sum('valor'),
                total_titulos_pendentes=Count('id')
            )
            widgets['contas_a_receber'] = {
                'total_aberto': aggr_cobranca['total_inadimplencia_aberto'] or Decimal('0.00'),
                'faturas_abertas': aggr_cobranca['total_titulos_pendentes'] or 0,
                'formula': "Σ valor das faturas com status 'ABERTA' ou 'VENCIDA'",
                'fonte': "Tabela FaturaCobranca"
            }

            # Resumo de Projeção e Alertas de Caixa
            alerta_recente = AlertaCaixa.unscoped.filter(tenant=tenant, resolvido=False).order_by('-data_alerta').first()
            if alerta_recente:
                widgets['alerta_caixa'] = {
                    'id': alerta_recente.id,
                    'data_alerta': alerta_recente.data_alerta,
                    'menor_saldo_projetado': alerta_recente.menor_saldo_projetado,
                    'data_menor_saldo': alerta_recente.data_menor_saldo,
                    'saldo_minimo_configurado': alerta_recente.saldo_minimo_configurado,
                    'formula': "Disparo quando menor_saldo_projetado (cenário realista) < saldo_minimo_caixa dentro do horizonte",
                    'fonte': "Tabela AlertaCaixa / Projeção de Fluxo de Caixa"
                }

        # 4. Widget Logística / Frotas
        if is_modulo_ativo(tenant, 'logistica'):
            widgets['gestao_frota_resumo'] = {
                'status': "ATIVO",
                'formula': "Margem = Receita Imputada/Comercial - Custos Variáveis; TCO = (Custos Variáveis + Fixos Alocados) / Km Rodados",
                'fonte': "Ledger (Dimensão Veículo), TabelaFreteInterno, LeituraOdometro, AlocacaoMotoristaVeiculo"
            }

        # 5. Widget de IA Preditiva / Churn (Requer vendas ou comercial)
        if is_modulo_ativo(tenant, 'vendas') or is_modulo_ativo(tenant, 'comercial'):
            total_churn_ativo = AlertaComercial.unscoped.filter(
                tenant=tenant,
                resolvido=False,
                tipo='RISCO_CHURN'
            ).count()
            widgets['ia_preditiva'] = {
                'alertas_churn_pendentes': total_churn_ativo,
                'formula': "Dias sem comprar > média histórica de reposição * 1.30",
                'fonte': "Tabela AlertaComercial (tipo 'RISCO_CHURN')"
            }

        cache.set(cache_key, widgets, 60 * 15)
        return Response(widgets)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='faturamento-mensal')
    def faturamento_mensal(self, request):
        """
        Agregação temporal obrigatória de faturamento por mês via TruncMonth e Sum.
        Zero instâncias carregadas em memória.
        """
        tenant = getattr(request, 'tenant', None)
        status_filtro = request.query_params.get('status')

        qs = Venda.unscoped.filter(tenant=tenant)
        if status_filtro:
            statuses = [s.strip() for s in status_filtro.split(',')]
            qs = qs.filter(status__in=statuses)
        else:
            qs = qs.filter(status__in=['Finalizada', 'Entregue'])

        faturamento = qs.annotate(
            mes=TruncMonth('data_venda')
        ).values('mes').annotate(
            total_vendas=Sum('valor_total'),
            total_pedidos=Count('id')
        ).order_by('mes')

        dados = [
            {
                'mes': item['mes'].strftime('%Y-%m') if item['mes'] else None,
                'total_vendas': item['total_vendas'] or Decimal('0.00'),
                'total_pedidos': item['total_pedidos']
            }
            for item in faturamento
        ]
        return Response(dados)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='vendas-por-gas')
    def vendas_por_gas(self, request):
        """
        Agrupamento de vendas por tipo de gás e SKU via agregação SQL do ORM.
        """
        tenant = getattr(request, 'tenant', None)
        dados = ItemVenda.unscoped.filter(
            venda__tenant=tenant
        ).exclude(
            venda__status='Cancelada'
        ).values(
            'sku__gas__nome', 'sku__gas__sigla'
        ).annotate(
            total_quantidade=Sum('quantidade'),
            total_faturado=Sum('valor_total')
        ).order_by('-total_faturado')

        resultado = [
            {
                'gas_nome': item['sku__gas__nome'] or 'Outros / Itens Diversos',
                'gas_sigla': item['sku__gas__sigla'] or '-',
                'total_quantidade': item['total_quantidade'] or 0,
                'total_faturado': item['total_faturado'] or Decimal('0.00')
            }
            for item in dados
        ]
        return Response(resultado)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='giro-cilindros')
    def giro_cilindros(self, request):
        """
        Contagem analítica de cilindros por status operacional (Pátio, Cliente, Rota, Triagem).
        """
        tenant = getattr(request, 'tenant', None)
        dados = Cilindro.unscoped.filter(tenant=tenant).values('status').annotate(
            total=Count('id')
        ).order_by('-total')
        return Response(list(dados))

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='kpis-gerais')
    def kpis_gerais(self, request):
        """
        KPIs executivos consolidados com consultas de agregação SQL pontuais.
        """
        tenant = getattr(request, 'tenant', None)
        aggr = Venda.unscoped.filter(tenant=tenant).exclude(status='Cancelada').aggregate(
            faturamento=Sum('valor_total'),
            ticket_medio=Avg('valor_total'),
            qtd_pedidos=Count('id')
        )
        return Response({
            'faturamento': aggr['faturamento'] or Decimal('0.00'),
            'ticket_medio': aggr['ticket_medio'] or Decimal('0.00'),
            'qtd_pedidos': aggr['qtd_pedidos'] or 0
        })

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='alertas-churn')
    def alertas_churn(self, request):
        """
        Retorna a lista analítica de alertas preditivos de Churn pendentes de contato comercial.
        """
        tenant = getattr(request, 'tenant', None)
        alertas = AlertaComercial.unscoped.filter(
            tenant=tenant,
            resolvido=False
        ).values(
            'id', 'cliente_id', 'cliente__nome', 'cliente__cnpj',
            'dias_sem_comprar', 'media_historica_dias', 'percentual_atraso',
            'descricao', 'criado_em'
        ).order_by('-dias_sem_comprar')
        return Response(list(alertas))

    # ==============================================================================
    # SPRINT 10C: AÇÕES DEDICADAS DE GESTÃO DO DONO
    # ==============================================================================

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='fluxo-caixa-realizado')
    def fluxo_caixa_realizado(self, request):
        """Fluxo de caixa realizado auditável por grupo e conta (Sprint 10C - Tarefa 1)."""
        tenant = getattr(request, 'tenant', None)
        if not is_modulo_ativo(tenant, 'financeiro'):
            raise PermissionDenied({'code': 'MODULO_INATIVO', 'detail': "Módulo financeiro inativo."})
        if not user_has_ver_dre(request):
            raise PermissionDenied({'detail': "Acesso restrito: permissão financeiro.ver_dre necessária."})

        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        conta_id = request.query_params.get('conta_id')
        conta_id_int = int(conta_id) if conta_id else None

        resultado = obter_fluxo_caixa_realizado(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim,
            conta_id=conta_id_int
        )
        return Response(resultado)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='projecao-cenarios')
    def projecao_cenarios(self, request):
        """Projeção de fluxo de caixa em 3 cenários determinísticos a 90 dias (Sprint 10C - Tarefa 3)."""
        tenant = getattr(request, 'tenant', None)
        if not is_modulo_ativo(tenant, 'financeiro'):
            raise PermissionDenied({'code': 'MODULO_INATIVO', 'detail': "Módulo financeiro inativo."})
        if not user_has_ver_dre(request):
            raise PermissionDenied({'detail': "Acesso restrito: permissão financeiro.ver_dre necessária."})

        dias = int(request.query_params.get('dias', 90))
        fator_str = request.query_params.get('fator_majoracao')
        fator = Decimal(fator_str) if fator_str else None

        resultado = projetar_fluxo_caixa_cenarios(
            tenant=tenant,
            dias_horizonte=dias,
            fator_majoracao_pessimista=fator
        )
        return Response(resultado)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='alertas-caixa')
    def alertas_caixa(self, request):
        """Lista histórico de alertas de ruptura de caixa projetada (Sprint 10C - Tarefa 4)."""
        tenant = getattr(request, 'tenant', None)
        if not is_modulo_ativo(tenant, 'financeiro'):
            raise PermissionDenied({'code': 'MODULO_INATIVO', 'detail': "Módulo financeiro inativo."})
        if not user_has_ver_dre(request):
            raise PermissionDenied({'detail': "Acesso restrito: permissão financeiro.ver_dre necessária."})

        qs = AlertaCaixa.unscoped.filter(tenant=tenant).values(
            'id', 'data_alerta', 'horizonte_dias', 'saldo_minimo_configurado',
            'menor_saldo_projetado', 'data_menor_saldo', 'resolvido', 'detalhes_json', 'criado_em'
        ).order_by('-criado_em')
        return Response(list(qs))

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='margem-veiculo')
    def margem_veiculo(self, request):
        """Margem de contribuição por veículo (Sprint 10C - Tarefa 5)."""
        tenant = getattr(request, 'tenant', None)
        if not is_modulo_ativo(tenant, 'logistica'):
            raise PermissionDenied({'code': 'MODULO_INATIVO', 'detail': "Módulo logística inativo."})

        veiculo_id = request.query_params.get('veiculo_id')
        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        politica = request.query_params.get('politica')

        if not (veiculo_id and data_inicio and data_fim):
            return Response(
                {'detail': "Parâmetros 'veiculo_id', 'data_inicio' e 'data_fim' são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        resultado = calcular_margem_contribuicao_veiculo(
            tenant=tenant,
            veiculo_id=int(veiculo_id),
            data_inicio=data_inicio,
            data_fim=data_fim,
            politica=politica
        )
        return Response(resultado)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='tco-veiculo')
    def tco_veiculo(self, request):
        """TCO por km e por parada com validação estrita de odômetro (Sprint 10C - Tarefa 6)."""
        tenant = getattr(request, 'tenant', None)
        if not is_modulo_ativo(tenant, 'logistica'):
            raise PermissionDenied({'code': 'MODULO_INATIVO', 'detail': "Módulo logística inativo."})

        veiculo_id = request.query_params.get('veiculo_id')
        ano = request.query_params.get('ano')
        mes = request.query_params.get('mes')

        if not (veiculo_id and ano and mes):
            return Response(
                {'detail': "Parâmetros 'veiculo_id', 'ano' e 'mes' são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        resultado = calcular_tco_veiculo(
            tenant=tenant,
            veiculo_id=int(veiculo_id),
            ano=int(ano),
            mes=int(mes)
        )
        return Response(resultado)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='cilindros-retencao')
    def cilindros_retencao(self, request):
        """Custo determinístico de retenção do cilindro parado (Sprint 10C - Tarefa 7)."""
        tenant = getattr(request, 'tenant', None)
        if not is_modulo_ativo(tenant, 'patrimonio'):
            raise PermissionDenied({'code': 'MODULO_INATIVO', 'detail': "Módulo patrimônio inativo."})

        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        cilindro_id = request.query_params.get('cilindro_id')

        if cilindro_id:
            resultado = calcular_custo_retencao_cilindro(
                tenant=tenant,
                cilindro_id=int(cilindro_id),
                data_inicio=data_inicio,
                data_fim=data_fim
            )
        else:
            resultado = analise_retencao_cilindros_consolidada(
                tenant=tenant,
                data_inicio=data_inicio,
                data_fim=data_fim
            )
        return Response(resultado)

    @method_decorator(cache_page(60 * 15))
    @method_decorator(vary_on_headers('X-Tenant-ID', 'Authorization'))
    @action(detail=False, methods=['get'], url_path='indicadores-gestao')
    def indicadores_gestao(self, request):
        """Indicadores executivos determinísticos da gestão do dono (Sprint 10C - Tarefa 8)."""
        tenant = getattr(request, 'tenant', None)
        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')

        resultado = calcular_indicadores_gestao(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim
        )
        return Response(resultado)


class AlertaOportunidadeComercialViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Gestão e Consulta de Alertas de Oportunidades Comerciais (Sprint 12C).
    Disponibiliza:
    - Listagem e detalhe de alertas com filtros por tipo, status e cliente;
    - Ação 'funil': métricas consolidadas e calibragem de k;
    - Ação 'backtest': simulação retrospectiva de assertividade;
    - Ação 'atualizar-status': transição atômica de status com feedback;
    - Ação 'gerar-alertas': disparo sob demanda da varredura analítica.
    """
    queryset = AlertaOportunidadeComercial.unscoped.all()
    serializer_class = AlertaOportunidadeComercialSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantMember, RequiresModuleAnalytics]

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return qs.none()
        qs = qs.filter(tenant=tenant)

        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        cliente_id = self.request.query_params.get('cliente_id')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)

        gas_id = self.request.query_params.get('gas_id')
        if gas_id:
            qs = qs.filter(gas_id=gas_id)

        return qs.select_related('cliente', 'gas', 'responsavel')

    @action(detail=False, methods=['get'], url_path='funil')
    def funil(self, request):
        """Retorna as métricas do funil comercial e calibragem por k."""
        from analytics.services.funil_service import calcular_metricas_funil
        tenant = request.tenant
        data_ini = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        metricas = calcular_metricas_funil(tenant=tenant, data_inicio=data_ini, data_fim=data_fim)
        return Response(metricas, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get', 'post'], url_path='backtest')
    def backtest(self, request):
        """Executa simulação histórica retrospectiva de assertividade dos alertas."""
        from analytics.services.backtest_service import executar_backtest
        from analytics.serializers import BacktestRequestSerializer

        data_payload = request.data if request.method == 'POST' else request.query_params
        serializer = BacktestRequestSerializer(data=data_payload)
        serializer.is_valid(raise_exception=True)

        params = serializer.validated_data
        resultado = executar_backtest(
            tenant=request.tenant,
            dias_horizonte=params.get('dias_horizonte', 30),
            k=params.get('k', 2.0),
            data_limite_simulacao=params.get('data_limite')
        )
        return Response(resultado, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='atualizar-status')
    def atualizar_status(self, request, pk=None):
        """Atualiza o status do alerta (NOVO -> EM_CONTATO -> CONVERTIDO / DESCARTADO)."""
        from analytics.services.alertas_service import atualizar_status_alerta
        from analytics.serializers import AtualizarStatusAlertaSerializer
        from core.guards import assert_tenant_writable

        assert_tenant_writable(request.tenant)
        serializer = AtualizarStatusAlertaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dados = serializer.validated_data
        alerta = atualizar_status_alerta(
            alerta_id=pk,
            novo_status=dados['status'],
            responsavel=request.user,
            feedback=dados.get('feedback', ''),
            tenant=request.tenant
        )
        return Response(AlertaOportunidadeComercialSerializer(alerta).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='gerar-alertas')
    def gerar_alertas(self, request):
        """Dispara a varredura sob demanda de geração de alertas para o tenant."""
        from analytics.services.alertas_service import gerar_alertas_demand_churn
        from core.guards import assert_tenant_writable

        assert_tenant_writable(request.tenant)
        k_param = float(request.data.get('k', 2.0))
        data_ref_param = request.data.get('data_ref')
        dt_ref = datetime.date.fromisoformat(data_ref_param) if data_ref_param else None

        alertas = gerar_alertas_demand_churn(
            tenant=request.tenant,
            data_ref=dt_ref,
            k=k_param
        )
        return Response({
            'total_alertas_gerados': len(alertas),
            'alertas': AlertaOportunidadeComercialSerializer(alertas, many=True).data
        }, status=status.HTTP_200_OK)


class FunilAlertasTemplateView(LoginRequiredMixin, TemplateView):
    """
    Interface Web Visual da Equipe Comercial para o Funil de Oportunidades (Sprint 12C - Tarefa 6).
    Exibe a evidência explicável de cada alerta com transparência auditável.
    """
    template_name = 'analytics/funil_alertas.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from core.permissions import resolve_request_membership
        from analytics.services.funil_service import calcular_metricas_funil

        membership = resolve_request_membership(self.request)
        tenant = membership.tenant if membership else getattr(self.request, 'tenant', None)

        if tenant and is_modulo_ativo(tenant, 'analytics'):
            ctx['funil'] = calcular_metricas_funil(tenant=tenant)
            ctx['alertas'] = AlertaOportunidadeComercial.unscoped.filter(
                tenant=tenant
            ).select_related('cliente', 'gas', 'responsavel').order_by('-score', '-criado_em')[:100]
        else:
            ctx['funil'] = {}
            ctx['alertas'] = []
            ctx['modulo_inativo'] = True

        return ctx

