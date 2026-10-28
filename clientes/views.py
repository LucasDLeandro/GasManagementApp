from rest_framework import viewsets
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, F, Q
from django.utils import timezone
from vendas.models import Venda
from core.mixins import TenantViewSetMixin
from core.permissions import IsTenantAdminOrGerente, RequiresModuleComercial
from produtos.models import Cilindro

from .models import Cliente, ContratoComodato
from .serializers import ClienteSerializer


def _obter_tenant_id_request(request):
    if hasattr(request, 'tenant') and request.tenant:
        return request.tenant.id
    tenant = get_current_tenant()
    if tenant:
        return tenant.id if hasattr(tenant, 'id') else tenant
    return getattr(request, 'tenant_id', None)


class ClienteViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    API endpoint that allows clientes to be viewed or edited with Tenant isolation.
    """
    queryset = Cliente.unscoped.all()
    serializer_class = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') == '1':
            return None
        return super().paginate_queryset(queryset)

    def get_queryset(self):
        queryset = super().get_queryset()
        tipo_param = self.request.query_params.get('tipo', None)
        if tipo_param:
            queryset = queryset.filter(tipo_cliente=tipo_param)

        search = self.request.query_params.get('search', None)
        if search:
            search = search.strip()
            queryset = queryset.filter(
                Q(nome__icontains=search) |
                Q(nome_fantasia__icontains=search) |
                Q(cnpj__icontains=search)
            )
        return queryset

    @action(detail=False, methods=['get'])
    def dashboard_metrics(self, request):
        tenant_id = _obter_tenant_id_request(request)
        if tenant_id:
            tenant = getattr(request, 'tenant', None) or get_current_tenant()
            total_clientes = Cliente.unscoped.filter(tenant_id=tenant_id).count()
            total_pj = Cliente.unscoped.filter(tenant_id=tenant_id, tipo_cliente='PJ').count()
            total_gov = Cliente.unscoped.filter(tenant_id=tenant_id, tipo_cliente='GOV').count()
            vendas_qs = Venda.unscoped.filter(tenant_id=tenant_id)
            cilindros_em_posse = Cilindro.unscoped.filter(tenant_id=tenant_id, status='EM_POSSE_CLIENTE').count()
            hoje = timezone.now().date()
            contratos_ativos = ContratoComodato.unscoped.filter(
                tenant_id=tenant_id
            ).filter(
                Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=hoje),
                vigencia_inicio__lte=hoje
            ).count()
            try:
                from .services import calcular_radar_comodato_tenant
                radar_data = calcular_radar_comodato_tenant(tenant)
                receita_estimada_mes = radar_data.get('receita_locacao_acumulada', 0.0)
            except Exception:
                receita_estimada_mes = 0.0
        else:
            total_clientes = Cliente.objects.count()
            total_pj = Cliente.objects.filter(tipo_cliente='PJ').count()
            total_gov = Cliente.objects.filter(tipo_cliente='GOV').count()
            vendas_qs = Venda.objects.all()
            cilindros_em_posse = Cilindro.objects.filter(status='EM_POSSE_CLIENTE').count()
            contratos_ativos = ContratoComodato.objects.count()
            receita_estimada_mes = 0.0

        top_clientes = vendas_qs.values(cnpj=F('cliente__cnpj'), nome=F('cliente__nome'))\
                                .annotate(total_comprado=Sum('valor_total'))\
                                .order_by('-total_comprado')[:5]

        return Response({
            'total_clientes': total_clientes,
            'total_pj': total_pj,
            'total_gov': total_gov,
            'cilindros_em_posse': cilindros_em_posse,
            'contratos_ativos': contratos_ativos,
            'receita_estimada_mes': receita_estimada_mes,
            'top_clientes': list(top_clientes)
        })


class ClienteTemplateView(LoginRequiredMixin, TemplateView):
    """
    View to render the Cliente frontend page with modal.
    """
    template_name = 'clientes/index.html'


import calendar
from datetime import date, timedelta
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from django.core.exceptions import ValidationError, PermissionDenied
from core.permissions import IsTenantAdminOrGerente
from produtos.models import Cilindro, ModeloCilindro
from .models import (
    ContratoComodato, FranquiaModeloContrato, DiaCilindro,
    FechamentoFaturaEstadia, ItemFaturaEstadia, AjusteCompetenciaEstadia, ExtravioCilindroRegistro
)
from .serializers import (
    ContratoComodatoSerializer, FranquiaModeloContratoSerializer,
    FechamentoFaturaEstadiaSerializer, FecharFaturaInputSerializer,
    DeclararExtravioInputSerializer, ExtravioCilindroRegistroSerializer,
    SimularDrillDownInputSerializer
)
from .services import (
    fechar_fatura_estadia_competencia,
    declarar_cilindro_extraviado,
    identificar_cilindros_limite_extravio,
    obter_contrato_vigente_cliente,
    obter_parametros_modelo_contrato,
    calcular_diarias_cliente_data,
    gerar_espelho_medicao_csv,
    gerar_espelho_medicao_pdf,
    gerar_exportacao_canonica_erp,
    FUSO_HORARIO_PADRAO
)
from core.tenancy import get_current_tenant




class ContratoComodatoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD de Contratos de Comodato/Estadia Versionados e Parametrização de Franquias (Fase 2).
    """
    queryset = ContratoComodato.unscoped.all()
    serializer_class = ContratoComodatoSerializer
    permission_classes = [IsAuthenticated, RequiresModuleComercial]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), RequiresModuleComercial(), IsTenantAdminOrGerente()]
        return [IsAuthenticated(), RequiresModuleComercial()]

    def get_queryset(self):
        qs = super().get_queryset()
        cliente_id = self.request.query_params.get('cliente_id')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)
        return qs.order_by('-vigencia_inicio')

    @action(detail=False, methods=['get'], url_path='modelos-disponiveis')
    def modelos_disponiveis(self, request):
        tenant_id = _obter_tenant_id_request(request)
        modelos = ModeloCilindro.unscoped.filter(tenant_id=tenant_id).values(
            'id', 'descricao', 'tara_nominal_kg', 'volume_hidraulico_litros'
        )
        return Response(list(modelos))


def _montar_drill_down(fatura, cliente, competencia, tenant_id):
    """
    Monta a estrutura de dados de drill-down analítico em árvore de 3 níveis:
    Total Fatura -> Grupo de Modelo -> Cilindro Individual -> Calendário Diário (DiaCilindro).
    Inclui comparativo com a competência anterior e ajustes/extravios vinculados.
    """
    ano, mes = map(int, competencia.split('-'))
    if mes == 1:
        ano_ant = ano - 1
        mes_ant = 12
    else:
        ano_ant = ano
        mes_ant = mes - 1
    comp_anterior = f"{ano_ant:04d}-{mes_ant:02d}"

    fatura_anterior = FechamentoFaturaEstadia.unscoped.filter(
        tenant_id=tenant_id,
        cliente=cliente,
        competencia_ano_mes=comp_anterior
    ).first()

    valor_anterior = float(fatura_anterior.valor_liquido_total) if fatura_anterior else 0.0
    valor_atual = float(fatura.valor_liquido_total)
    delta = valor_atual - valor_anterior
    pct_var = round(((delta / valor_anterior) * 100), 1) if valor_anterior > 0 else (100.0 if valor_atual > 0 else 0.0)

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano, mes, ultimo_dia)

    dias_registrados = list(
        DiaCilindro.unscoped.filter(
            tenant_id=tenant_id,
            cliente=cliente,
            data_referencia__gte=data_inicio,
            data_referencia__lte=data_fim
        ).select_related('cilindro', 'cilindro__modelo').order_by('data_referencia')
    )
    if not dias_registrados:
        for d in range((data_fim - data_inicio).days + 1):
            dia_calc = data_inicio + timedelta(days=d)
            res_dia = calcular_diarias_cliente_data(cliente, dia_calc, tenant_id=tenant_id, persistir=False)
            for r in res_dia:
                dias_registrados.append(DiaCilindro(
                    tenant_id=tenant_id,
                    cliente=cliente,
                    cilindro=r['cilindro'],
                    data_referencia=r['data_referencia'],
                    data_entrega=r['data_entrega'],
                    idade_posse_dias=r['idade_posse_dias'],
                    classe_cobranca=r['classe_cobranca'],
                    valor_diaria=r['valor_diaria'],
                    contrato_versao=r['contrato_versao'],
                    algoritmo_versao=r['algoritmo_versao'],
                ))

    dias_por_cilindro_map = {}
    for dc in dias_registrados:
        dias_por_cilindro_map.setdefault(dc.cilindro_id, []).append(dc)

    itens = getattr(fatura, 'itens_previa', None) or list(fatura.itens.all())

    arvore_modelos_dict = {}
    for item in itens:
        mod_desc = item.modelo_cilindro or "Padrão"
        if mod_desc not in arvore_modelos_dict:
            arvore_modelos_dict[mod_desc] = {
                'modelo': mod_desc,
                'total_cilindros': 0,
                'total_dias_posse': 0,
                'total_dias_carencia': 0,
                'total_dias_franquia': 0,
                'total_dias_cobraveis': 0,
                'subtotal': 0.0,
                'cilindros': []
            }
        grupo = arvore_modelos_dict[mod_desc]
        grupo['total_cilindros'] += 1
        grupo['total_dias_posse'] += item.dias_posse_mes
        grupo['total_dias_carencia'] += item.dias_carencia
        grupo['total_dias_franquia'] += item.dias_franquia
        grupo['total_dias_cobraveis'] += item.dias_cobraveis
        grupo['subtotal'] += float(item.subtotal)

        cil_dias = dias_por_cilindro_map.get(item.cilindro_id, [])
        dias_detalhes = [
            {
                'data': d.data_referencia.strftime('%d/%m'),
                'data_iso': d.data_referencia.strftime('%Y-%m-%d'),
                'dia_mes': d.data_referencia.day,
                'idade_posse_dias': d.idade_posse_dias,
                'classe_cobranca': d.classe_cobranca,
                'valor_diaria': float(d.valor_diaria),
            }
            for d in sorted(cil_dias, key=lambda x: x.data_referencia)
        ]

        grupo['cilindros'].append({
            'cilindro_id': item.cilindro_id,
            'numero_serie': item.cilindro.numero_serie_ogiva if item.cilindro else '',
            'codigo_qr': item.cilindro.codigo_qr if item.cilindro else '',
            'periodo_inicio': item.periodo_inicio.strftime('%d/%m/%Y'),
            'periodo_fim': item.periodo_fim.strftime('%d/%m/%Y'),
            'dias_posse_mes': item.dias_posse_mes,
            'dias_carencia': item.dias_carencia,
            'dias_franquia': item.dias_franquia,
            'dias_reserva_tecnica': item.dias_reserva_tecnica,
            'dias_cobraveis': item.dias_cobraveis,
            'diaria_aplicada': float(item.diaria_aplicada),
            'subtotal': float(item.subtotal),
            'calendario_dias': dias_detalhes
        })

    ajustes_list = [
        {
            'id': a.id,
            'tipo': a.tipo_ajuste,
            'valor': float(a.valor_ajuste),
            'motivo': a.motivo,
            'competencia_afetada': a.competencia_afetada
        }
        for a in AjusteCompetenciaEstadia.unscoped.filter(
            tenant_id=tenant_id, cliente=cliente, compensado=(fatura.status_pagamento in ['FECHADA', 'PAGA'])
        )
    ]
    extravios_list = [
        {
            'id': e.id,
            'cilindro_serie': e.cilindro.numero_serie_ogiva,
            'data_extravio': e.data_extravio.strftime('%d/%m/%Y'),
            'valor': float(e.valor_reposicao),
            'justificativa': e.justificativa
        }
        for e in ExtravioCilindroRegistro.unscoped.filter(
            tenant_id=tenant_id, cliente=cliente, cobrado=(fatura.status_pagamento in ['FECHADA', 'PAGA'])
        )
    ]

    return {
        'fatura_id': fatura.id if fatura.pk else None,
        'status_pagamento': fatura.status_pagamento,
        'competencia': competencia,
        'cliente_id': cliente.id,
        'cliente_nome': cliente.nome,
        'cliente_cnpj': cliente.cnpj,
        'resumo_financeiro': {
            'valor_bruto_diarias': float(fatura.valor_bruto_diarias),
            'valor_desconto_carencia': float(fatura.valor_desconto_carencia),
            'valor_desconto_franquia': float(fatura.valor_desconto_franquia),
            'valor_ajustes_retroativos': float(fatura.valor_ajustes_retroativos),
            'valor_reposicao_extravios': float(fatura.valor_reposicao_extravios),
            'valor_liquido_total': float(fatura.valor_liquido_total),
        },
        'comparativo_mes_anterior': {
            'competencia_anterior': comp_anterior,
            'valor_anterior': valor_anterior,
            'diferenca': delta,
            'variacao_percentual': pct_var,
        },
        'arvore_modelos': list(arvore_modelos_dict.values()),
        'ajustes_retroativos': ajustes_list,
        'extravios_pendentes': extravios_list
    }


class FechamentoFaturaEstadiaViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API para visualização, simulação drill-down e fechamento formal de faturas de estadia (Fase 2).
    """
    queryset = FechamentoFaturaEstadia.unscoped.all()
    serializer_class = FechamentoFaturaEstadiaSerializer
    permission_classes = [IsAuthenticated, RequiresModuleComercial]

    def get_queryset(self):
        qs = super().get_queryset()
        cliente_id = self.request.query_params.get('cliente_id')
        competencia = self.request.query_params.get('competencia')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)
        if competencia:
            qs = qs.filter(competencia_ano_mes=competencia)
        return qs.order_by('-competencia_ano_mes')

    @action(detail=False, methods=['post'], url_path='simular-drill-down', permission_classes=[IsAuthenticated, RequiresModuleComercial, IsTenantAdminOrGerente])
    def simular_drill_down(self, request):
        """
        Passo 1 & 2 do Stepper: Simula o fechamento (persistir=False) e retorna a árvore completa de drill-down.
        """
        serializer = SimularDrillDownInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cliente_id = serializer.validated_data['cliente_id']
        competencia = serializer.validated_data['competencia_ano_mes']

        tenant_id = _obter_tenant_id_request(request)
        cliente = Cliente.unscoped.filter(tenant_id=tenant_id, id=cliente_id).first()
        if not cliente:
            return Response({'detail': 'Cliente não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            fatura_previa = fechar_fatura_estadia_competencia(
                cliente=cliente,
                competencia_ano_mes=competencia,
                usuario=request.user,
                tenant_id=tenant_id,
                persistir=False
            )
            dados_drill_down = _montar_drill_down(fatura_previa, cliente, competencia, tenant_id)
            return Response(dados_drill_down, status=status.HTTP_200_OK)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='drill-down')
    def drill_down(self, request, pk=None):
        """
        Retorna o drill-down analítico de uma fatura já fechada.
        """
        fatura = self.get_object()
        tenant_id = _obter_tenant_id_request(request)
        dados = _montar_drill_down(fatura, fatura.cliente, fatura.competencia_ano_mes, tenant_id)
        return Response(dados, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated, RequiresModuleComercial, IsTenantAdminOrGerente])
    def fechar(self, request):
        """
        Passo 3 do Stepper: Executa o fechamento formal, gravando o snapshot imutável e disparando o Outbox.
        """
        serializer = FecharFaturaInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cliente_id = serializer.validated_data['cliente_id']
        competencia = serializer.validated_data['competencia_ano_mes']
        persistir = serializer.validated_data.get('persistir', True)

        tenant_id = _obter_tenant_id_request(request)
        cliente = Cliente.unscoped.filter(tenant_id=tenant_id, id=cliente_id).first()
        if not cliente:
            return Response({'detail': 'Cliente não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            fatura = fechar_fatura_estadia_competencia(
                cliente=cliente,
                competencia_ano_mes=competencia,
                usuario=request.user,
                tenant_id=tenant_id,
                persistir=persistir
            )
            status_code = status.HTTP_201_CREATED if persistir else status.HTTP_200_OK
            return Response(FechamentoFaturaEstadiaSerializer(fatura).data, status=status_code)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='espelho-pdf')
    def espelho_pdf(self, request, pk=None):
        fatura = self.get_object()
        pdf_bytes = gerar_espelho_medicao_pdf(fatura)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"espelho_estadia_{fatura.competencia_ano_mes}_{fatura.cliente_id}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=['get'], url_path='espelho-csv')
    def espelho_csv(self, request, pk=None):
        fatura = self.get_object()
        csv_content = gerar_espelho_medicao_csv(fatura)
        response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
        filename = f"espelho_estadia_{fatura.competencia_ano_mes}_{fatura.cliente_id}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=['get'], url_path='exportacao-canonica')
    def exportacao_canonica(self, request):
        competencia = request.query_params.get('competencia')
        formato = request.query_params.get('formato', 'json').lower()
        if not competencia:
            return Response({'detail': 'Parâmetro query ?competencia=AAAA-MM é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        tenant_id = _obter_tenant_id_request(request)
        try:
            resultado = gerar_exportacao_canonica_erp(
                tenant_id=tenant_id,
                competencia_ano_mes=competencia,
                formato=formato
            )
            if formato == 'json':
                return Response(resultado)
            else:
                response = HttpResponse(resultado, content_type='text/csv; charset=utf-8')
                response['Content-Disposition'] = f'attachment; filename="export_erp_estadia_{competencia}.csv"'
                return response
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ExtravioCilindroViewSet(TenantViewSetMixin, viewsets.ViewSet):
    """
    API para identificação de alertas de extravio, radar preventivo de carência e registro de indenização patrimonial (Fase 2).
    """
    permission_classes = [IsAuthenticated, RequiresModuleComercial]

    @action(detail=False, methods=['get'], url_path='alertas')
    def alertas(self, request):
        tenant_id = _obter_tenant_id_request(request)
        cliente_id = request.query_params.get('cliente_id')
        cliente = None
        if cliente_id:
            cliente = Cliente.unscoped.filter(tenant_id=tenant_id, id=cliente_id).first()

        alertas = identificar_cilindros_limite_extravio(tenant_id=tenant_id, cliente=cliente)
        return Response(alertas)

    @action(detail=False, methods=['get'], url_path='radar-carencia')
    def radar_carencia(self, request):
        """
        Radar Preventivo de Carência (Fase 2):
        Identifica cilindros em posse cujo término da carência individual de giro
        ocorrerá nos próximos 5 dias (0 <= carencia_dias - idade_posse_dias <= 5).
        Permite ação comercial proativa antes da cobrança de diária excedente.
        """
        tenant_id = _obter_tenant_id_request(request)
        hoje = timezone.now().astimezone(FUSO_HORARIO_PADRAO).date()
        clientes_qs = Cliente.unscoped.filter(tenant_id=tenant_id)

        cilindros_alerta = []
        for cli in clientes_qs:
            contrato = obter_contrato_vigente_cliente(cli, hoje)
            cilindros = list(
                Cilindro.unscoped.filter(
                    cliente_posse_atual=cli,
                    status='EM_POSSE_CLIENTE'
                ).select_related('modelo', 'gas_dedicado')
            )

            for cil in cilindros:
                params = obter_parametros_modelo_contrato(contrato, cil.modelo)
                carencia_dias = params['carencia_dias']
                if cil.posse_desde:
                    dt_entrega = cil.posse_desde.astimezone(FUSO_HORARIO_PADRAO).date()
                else:
                    dt_entrega = hoje
                idade_posse = max(0, (hoje - dt_entrega).days)
                dias_restantes = carencia_dias - idade_posse

                if 0 <= dias_restantes <= 5:
                    cilindros_alerta.append({
                        'cilindro_id': cil.id,
                        'numero_serie': cil.numero_serie_ogiva,
                        'codigo_qr': cil.codigo_qr,
                        'cliente_id': cli.id,
                        'cliente_nome': cli.nome,
                        'cliente_cnpj': cli.cnpj,
                        'data_entrega': dt_entrega.strftime('%d/%m/%Y'),
                        'idade_posse_dias': idade_posse,
                        'carencia_dias': carencia_dias,
                        'dias_restantes_carencia': dias_restantes,
                        'taxa_diaria_prevista': float(params['taxa_diaria']),
                        'modelo_descricao': cil.modelo.descricao if cil.modelo else "N/A",
                        'gas': cil.gas_dedicado.nome if cil.gas_dedicado else "N/A",
                    })

        cilindros_alerta.sort(key=lambda x: x['dias_restantes_carencia'])
        return Response(cilindros_alerta)

    @action(detail=False, methods=['post'], url_path='declarar', permission_classes=[IsAuthenticated, IsTenantAdminOrGerente])
    def declarar(self, request):
        serializer = DeclararExtravioInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cilindro_id = serializer.validated_data['cilindro_id']
        data_extravio = serializer.validated_data.get('data_extravio')
        justificativa = serializer.validated_data['justificativa']

        tenant_id = _obter_tenant_id_request(request)
        cilindro = Cilindro.unscoped.filter(tenant_id=tenant_id, id=cilindro_id).first()
        if not cilindro:
            return Response({'detail': 'Cilindro não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            registro = declarar_cilindro_extraviado(
                cilindro=cilindro,
                usuario=request.user,
                data_extravio=data_extravio,
                justificativa=justificativa
            )
            return Response(ExtravioCilindroRegistroSerializer(registro).data, status=status.HTTP_201_CREATED)
        except (ValidationError, PermissionDenied) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

