from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.utils import timezone
import datetime

from vendas.models import Venda
from core.mixins import TenantViewSetMixin
from clientes.models import Cliente
from logistica.models import Veiculo
from produtos.models import Produto, Cilindro, LoteEnvase, EnvaseCilindro
from core.tenancy import get_current_tenant
from core.permissions import resolve_request_membership
from clientes.services import calcular_radar_comodato_tenant

class DashboardStatsAPIView(TenantViewSetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoje = timezone.now().date()
        inicio_mes = hoje.replace(day=1)

        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if not tenant:
            membership = resolve_request_membership(request)
            tenant = membership.tenant if membership else None

        tem_distribuicao = getattr(tenant, 'tem_modulo_distribuicao', True) if tenant else True
        tem_envase = getattr(tenant, 'tem_modulo_envase', False) if tenant else False
        modo_operacao = getattr(tenant, 'modo_operacao', 'DISTRIBUIDORA') if tenant else 'DISTRIBUIDORA'

        # 1. KPIs Universais de Patrimônio & Conformidade
        frota_total = Cilindro.objects.count()
        alertas_reteste = Cilindro.objects.filter(
            data_proximo_reteste__lte=hoje + datetime.timedelta(days=30)
        ).count()

        # 2. Módulo Envase & Rampa
        lotes_ativos = 0
        volume_envasado_mes = 0
        cilindros_em_triagem_rampa = 0
        lotes_quarentena = 0
        lotes_recentes = []

        if tem_envase:
            lotes_ativos = LoteEnvase.objects.filter(status_qualidade__in=['QUARENTENA', 'APROVADO']).count()
            volume_envasado_mes = EnvaseCilindro.objects.filter(envasado_em__date__gte=inicio_mes).count()
            cilindros_em_triagem_rampa = Cilindro.objects.filter(status='VAZIO_TRIAGEM').count()
            lotes_quarentena = LoteEnvase.objects.filter(status_qualidade='QUARENTENA').count()
            lotes_qs = LoteEnvase.objects.select_related('gas', 'responsavel_tecnico_fk').order_by('-data_envase')[:5]
            for l in lotes_qs:
                lotes_recentes.append({
                    'id': l.id,
                    'codigo_lote': l.codigo_lote,
                    'gas_nome': l.gas.nome if l.gas else '-',
                    'gas_sigla': l.gas.sigla if l.gas else '-',
                    'data_envase': l.data_envase.strftime('%d/%m/%Y') if l.data_envase else '-',
                    'pureza': float(l.pureza_percentual or 0),
                    'status_qualidade': l.status_qualidade,
                    'cilindros_count': l.cilindros_envasados.count(),
                    'rt_nome': l.rt_nome_snapshot or (l.responsavel_tecnico_fk.nome_completo if l.responsavel_tecnico_fk else l.responsavel_tecnico)
                })

        # 3. Módulo Distribuição, Logística & Estadia
        faturamento_mes = 0.0
        entregas_pendentes = 0
        clientes_ativos = 0
        frota_manutencao = 0
        estoque_baixo = 0
        cilindros_sem_giro = 0
        receita_locacao = 0.0
        risco_patrimonial = 0.0
        radar_faixas = {'dias_0_a_29': 0, 'dias_30_a_59': 0, 'dias_60_a_89': 0, 'dias_90_mais': 0}
        radar_itens = []
        vendas_semana = []
        labels_semana = []

        if tem_distribuicao:
            vendas_mes = Venda.objects.filter(data_venda__gte=inicio_mes).exclude(status='Cancelada')
            faturamento_mes = float(vendas_mes.aggregate(total=Sum('valor_total'))['total'] or 0)
            entregas_pendentes = Venda.objects.filter(status__in=['Em Separação', 'Em Rota']).count()
            clientes_ativos = Cliente.objects.count()
            frota_manutencao = Veiculo.objects.filter(status='Em Manutenção').count()
            estoque_baixo = Produto.objects.filter(estoque__lte=10).count()

            radar = calcular_radar_comodato_tenant()
            cilindros_sem_giro = radar['cilindros_sem_giro_30_mais']
            receita_locacao = radar['receita_locacao_acumulada']
            risco_patrimonial = radar['risco_patrimonial_total']
            radar_faixas = radar['faixas']
            radar_itens = radar['itens']

            for i in range(6, -1, -1):
                dia = hoje - datetime.timedelta(days=i)
                labels_semana.append(dia.strftime('%d/%m'))
                vendas_dia = Venda.objects.filter(data_venda__date=dia).exclude(status='Cancelada').aggregate(total=Sum('valor_total'))['total'] or 0
                vendas_semana.append(float(vendas_dia))

        # 4. Gráfico Donut de Status
        status_counts = dict(Cilindro.objects.values_list('status').annotate(total=Count('id')))
        if tem_distribuicao:
            donut_labels = [
                'Cheios no Pátio',
                'Em Comodato (Clientes)',
                'Em Rota',
                'Vazios em Triagem',
                'Em Reteste / Manutenção'
            ]
            donut_series = [
                status_counts.get('CHEIO_DISPONIVEL', 0),
                status_counts.get('EM_POSSE_CLIENTE', 0),
                status_counts.get('RESERVADO_ROTA', 0),
                status_counts.get('VAZIO_TRIAGEM', 0),
                status_counts.get('EM_RETESTE', 0),
            ]
        else:
            donut_labels = [
                'Cheios no Pátio',
                'Vazios na Triagem / Rampa',
                'Em Reteste / Manutenção'
            ]
            donut_series = [
                status_counts.get('CHEIO_DISPONIVEL', 0),
                status_counts.get('VAZIO_TRIAGEM', 0),
                status_counts.get('EM_RETESTE', 0),
            ]

        data = {
            'tem_modulo_distribuicao': tem_distribuicao,
            'tem_modulo_envase': tem_envase,
            'modo_operacao': modo_operacao,

            # KPIs Universais
            'frota_total': frota_total,
            'alertas_reteste_inmetro': alertas_reteste,

            # KPIs Módulo Envase
            'lotes_ativos': lotes_ativos,
            'volume_envasado_mes': volume_envasado_mes,
            'cilindros_vazios_triagem': cilindros_em_triagem_rampa,
            'lotes_quarentena': lotes_quarentena,
            'lotes_recentes': lotes_recentes,

            # KPIs Módulo Distribuição
            'cilindros_sem_giro_30_mais': cilindros_sem_giro,
            'receita_locacao_acumulada': receita_locacao,
            'taxa_estadia_estimativa': receita_locacao,
            'taxa_estadia_label': "Taxa de Estadia / Locação de Cilindros Excedentes",
            'risco_patrimonial_total': risco_patrimonial,
            'donut_labels': donut_labels,
            'donut_series': donut_series,
            'radar_faixas': radar_faixas,
            'radar_itens': radar_itens,
            'faturamento_mes': faturamento_mes,
            'entregas_pendentes': entregas_pendentes,
            'clientes_ativos': clientes_ativos,
            'frota_manutencao': frota_manutencao,
            'estoque_baixo': estoque_baixo,
            'grafico_labels': labels_semana,
            'grafico_dados': vendas_semana
        }
        return Response(data)


# ==============================================================================
# PWA SERVICE WORKER & MANIFEST (SPRINT 6)
# ==============================================================================

def pwa_manifest_view(request):
    """Serve o manifest.json na raiz para compatibilidade total de PWA."""
    manifest_path = settings.BASE_DIR / 'static' / 'manifest.json'
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        content = '{"name": "Baros", "short_name": "Baros", "start_url": "/inicio/", "display": "standalone"}'
    return HttpResponse(content, content_type='application/manifest+json')


def pwa_service_worker_view(request):
    """Serve o sw.js com scope='/' no root do domínio."""
    sw_path = settings.BASE_DIR / 'static' / 'sw.js'
    try:
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        content = '// Service Worker fallback'
    response = HttpResponse(content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


# ==============================================================================
# WEBHOOKS & EXPORTAÇÃO CANÔNICA ERP (SPRINT 6)
# ==============================================================================

import secrets
import csv
from io import StringIO
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from .models import WebhookEndpoint, WebhookDeliveryLog
from .serializers import WebhookEndpointSerializer, WebhookDeliveryLogSerializer
from clientes.models import FechamentoFaturaEstadia
from logistica.models import Entrega
from core.permissions import IsTenantAdminOrGerente, IsTenantMember
from core.tenancy import get_current_tenant

class WebhookEndpointViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Gestão de Endpoints de Webhooks externos para notificação de ERPs/TMS.
    Permissões estritas: Apenas Administradores e Gerentes (D6/D7).
    Garante exibição única do segredo HMAC na criação e rotação.
    """
    queryset = WebhookEndpoint.unscoped.all()
    serializer_class = WebhookEndpointSerializer
    permission_classes = [IsTenantAdminOrGerente]

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if not tenant:
            raise PermissionDenied("Não é possível salvar registros sem uma empresa (Tenant) associada.")
        
        secret = serializer.validated_data.get('secret')
        if not secret:
            secret = secrets.token_hex(32)
        
        instance = serializer.save(tenant=tenant, secret=secret)
        # Anexa secret em memória temporária para exibição única na resposta
        instance._raw_secret = secret

    @action(detail=True, methods=['post'], url_path='rotacionar-secret')
    def rotacionar_secret(self, request, pk=None):
        """Gera novo segredo criptográfico HMAC-SHA256 e o exibe uma única vez (D7)."""
        endpoint = self.get_object()
        novo_secret = secrets.token_hex(32)
        endpoint.secret = novo_secret
        endpoint.save(update_fields=['secret', 'atualizado_em'])
        return Response({
            'sucesso': True,
            'mensagem': 'Segredo HMAC rotacionado com sucesso.',
            'secret_exclusivo': novo_secret,
            'aviso': 'Guarde esta chave agora. Por segurança, ela nunca mais será exibida em leituras futuras.'
        })

    @action(detail=True, methods=['post'], url_path='testar')
    def testar(self, request, pk=None):
        """Dispara evento de teste 'ping.teste' assinado com HMAC-SHA256 respeitando anti-SSRF."""
        endpoint = self.get_object()
        from core.webhooks import disparar_webhooks_tenant
        logs = disparar_webhooks_tenant(
            tenant=endpoint.tenant,
            evento='ping.teste',
            payload={
                'mensagem': 'Teste de integridade e assinatura HMAC-SHA256.',
                'endpoint_id': endpoint.id,
                'timestamp': timezone.now().isoformat()
            },
            endpoint_especifico=endpoint
        )
        log = logs[0] if logs else None
        return Response({
            'sucesso': log.sucesso if log else False,
            'status_code': log.status_code if log else None,
            'latencia_ms': log.latencia_ms if log else None,
            'resposta': log.resposta_body if log else 'Nenhum log gerado'
        })

    @action(detail=True, methods=['get'], url_path='logs')
    def logs(self, request, pk=None):
        """Retorna histórico de entregas exclusivo deste endpoint."""
        endpoint = self.get_object()
        logs_qs = endpoint.logs.order_by('-enviado_em')[:50]
        serializer = WebhookDeliveryLogSerializer(logs_qs, many=True)
        return Response(serializer.data)


class WebhookDeliveryLogViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Consulta e reenvio de entregas de webhooks (Transactional Outbox D7).
    Acesso restrito a Administradores e Gerentes.
    """
    queryset = WebhookDeliveryLog.unscoped.all()
    serializer_class = WebhookDeliveryLogSerializer
    permission_classes = [IsTenantAdminOrGerente]

    def get_queryset(self):
        qs = super().get_queryset().select_related('endpoint')
        endpoint_id = self.request.query_params.get('endpoint')
        if endpoint_id:
            qs = qs.filter(endpoint_id=endpoint_id)
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())
        return qs.order_by('-enviado_em')

    @action(detail=True, methods=['post'], url_path='reenviar')
    def reenviar(self, request, pk=None):
        """Reprocessa manualmente o envio de um item da Outbox com falha (D7)."""
        log = self.get_object()
        from core.webhooks import processar_envio_webhook_log
        log.status = 'PENDENTE'
        log.save(update_fields=['status'])
        resultado = processar_envio_webhook_log(log.id)
        if not resultado:
            log.refresh_from_db()
        else:
            log = resultado
        return Response({
            'sucesso': log.sucesso,
            'status': log.status,
            'status_code': log.status_code,
            'latencia_ms': log.latencia_ms,
            'resposta': log.resposta_body,
            'tentativas': log.tentativas
        })


class ERPFaturasExportAPIView(TenantViewSetMixin, APIView):
    """
    Endpoint canônico REST paginado para exportação de fechamentos de faturas
    de estadia e demurrage para ERPs externos (Sprint 6 & Fase 5 - D6/D9).
    Suporta filtros por período, cursor incremental 'updated_since' e download JSON/CSV.
    """
    permission_classes = [IsTenantAdminOrGerente]

    def perform_content_negotiation(self, request, force=False):
        if request.query_params.get('format') == 'csv' or request.query_params.get('export') == 'csv':
            from rest_framework.renderers import BaseRenderer
            class PassthroughCSVRenderer(BaseRenderer):
                media_type = 'text/csv'
                format = 'csv'
                def render(self, data, accepted_media_type=None, renderer_context=None):
                    return data
            return (PassthroughCSVRenderer(), 'text/csv')
        return super().perform_content_negotiation(request, force=force)

    def get(self, request):
        faturas = FechamentoFaturaEstadia.objects.select_related('cliente', 'fechado_por').order_by('-data_fechamento')
        
        # Filtros opcionais
        competencia = request.query_params.get('competencia')
        if competencia:
            faturas = faturas.filter(competencia_ano_mes=competencia)

        cliente_id = request.query_params.get('cliente')
        if cliente_id:
            faturas = faturas.filter(cliente_id=cliente_id)

        data_inicio = request.query_params.get('data_inicio')
        if data_inicio:
            try:
                dt_ini = datetime.date.fromisoformat(data_inicio)
                faturas = faturas.filter(data_fechamento__date__gte=dt_ini)
            except Exception:
                pass

        data_fim = request.query_params.get('data_fim')
        if data_fim:
            try:
                dt_fim = datetime.date.fromisoformat(data_fim)
                faturas = faturas.filter(data_fechamento__date__lte=dt_fim)
            except Exception:
                pass

        # Suporte a cursor incremental updated_since (D9)
        updated_since = request.query_params.get('updated_since')
        if updated_since:
            try:
                clean_dt = updated_since.strip().replace(' ', '+').replace('Z', '+00:00')
                dt = datetime.datetime.fromisoformat(clean_dt)
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                faturas = faturas.filter(data_fechamento__gte=dt)
            except Exception:
                pass

        # Exportação em CSV
        if request.query_params.get('format') == 'csv' or request.query_params.get('export') == 'csv':
            buffer = StringIO()
            buffer.write('\ufeff')  # BOM para Excel
            writer = csv.writer(buffer, delimiter=';')
            writer.writerow([
                'ID Fatura', 'Competência', 'Cliente', 'CNPJ', 'Código ERP',
                'Bruto Diárias (R$)', 'Desc. Carência (R$)', 'Desc. Franquia (R$)',
                'Ajustes Retroativos (R$)', 'Reposição Extravios (R$)', 'Líquido Total (R$)',
                'Status Pagamento', 'Data Fechamento', 'Fechado Por', 'Total Cilindros'
            ])
            for f in faturas:
                writer.writerow([
                    f.id,
                    f.competencia_ano_mes,
                    f.cliente.nome,
                    f.cliente.cnpj,
                    getattr(f.cliente, 'codigo_externo', '') or '',
                    f"{float(f.valor_bruto_diarias):.2f}",
                    f"{float(f.valor_desconto_carencia):.2f}",
                    f"{float(f.valor_desconto_franquia):.2f}",
                    f"{float(f.valor_ajustes_retroativos):.2f}",
                    f"{float(f.valor_reposicao_extravios):.2f}",
                    f"{float(f.valor_liquido_total):.2f}",
                    f.status_pagamento,
                    f.data_fechamento.strftime('%d/%m/%Y %H:%M:%S') if f.data_fechamento else '',
                    f.fechado_por.username if f.fechado_por else '',
                    f.itens.count()
                ])
            response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="faturas_estadia_erp.csv"'
            return response

        total_count = faturas.count()

        # Paginação configurável eliminando corte fixo de [:100] (D9)
        try:
            page_size = int(request.query_params.get('page_size', 50))
            if page_size <= 0:
                page_size = 50
        except ValueError:
            page_size = 50

        try:
            page_num = int(request.query_params.get('page', 1))
            if page_num <= 0:
                page_num = 1
        except ValueError:
            page_num = 1

        start = (page_num - 1) * page_size
        end = start + page_size
        faturas_page = faturas[start:end]

        dados = []
        for f in faturas_page:
            dados.append({
                'fatura_id': f.id,
                'competencia': f.competencia_ano_mes,
                'cliente': {
                    'id': f.cliente.id,
                    'nome': f.cliente.nome,
                    'cnpj': f.cliente.cnpj,
                    'codigo_erp': f.cliente.codigo_externo if hasattr(f.cliente, 'codigo_externo') else None
                },
                'valores': {
                    'bruto_diarias': float(f.valor_bruto_diarias),
                    'desconto_carencia': float(f.valor_desconto_carencia),
                    'desconto_franquia': float(f.valor_desconto_franquia),
                    'ajustes_retroativos': float(f.valor_ajustes_retroativos),
                    'reposicao_extravios': float(f.valor_reposicao_extravios),
                    'liquido_total': float(f.valor_liquido_total)
                },
                'status_pagamento': f.status_pagamento,
                'data_fechamento': f.data_fechamento.isoformat(),
                'fechado_por': f.fechado_por.username if f.fechado_por else None,
                'total_itens': f.itens.count()
            })

        return Response({
            'total': total_count,
            'page': page_num,
            'page_size': page_size,
            'faturas': dados
        })


class ERPEntregasExportAPIView(TenantViewSetMixin, APIView):
    """
    Endpoint canônico REST paginado para exportação de Romaneios e Entregas concluídas
    para ERPs externos (Sprint 6 & Fase 5 - D6/D9).
    Suporta filtros por período, status, cursor incremental 'updated_since' e download JSON/CSV.
    """
    permission_classes = [IsTenantAdminOrGerente]

    def perform_content_negotiation(self, request, force=False):
        if request.query_params.get('format') == 'csv' or request.query_params.get('export') == 'csv':
            from rest_framework.renderers import BaseRenderer
            class PassthroughCSVRenderer(BaseRenderer):
                media_type = 'text/csv'
                format = 'csv'
                def render(self, data, accepted_media_type=None, renderer_context=None):
                    return data
            return (PassthroughCSVRenderer(), 'text/csv')
        return super().perform_content_negotiation(request, force=force)

    def get(self, request):
        entregas = Entrega.objects.select_related('veiculo', 'motorista', 'rota').order_by('-data_saida')
        
        status_param = request.query_params.get('status')
        if status_param:
            entregas = entregas.filter(status=status_param)

        data_inicio = request.query_params.get('data_inicio')
        if data_inicio:
            try:
                dt_ini = datetime.date.fromisoformat(data_inicio)
                entregas = entregas.filter(data_saida__date__gte=dt_ini)
            except Exception:
                pass

        data_fim = request.query_params.get('data_fim')
        if data_fim:
            try:
                dt_fim = datetime.date.fromisoformat(data_fim)
                entregas = entregas.filter(data_saida__date__lte=dt_fim)
            except Exception:
                pass

        # Suporte a cursor incremental updated_since (D9)
        updated_since = request.query_params.get('updated_since')
        if updated_since:
            try:
                clean_dt = updated_since.strip().replace(' ', '+').replace('Z', '+00:00')
                dt = datetime.datetime.fromisoformat(clean_dt)
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                entregas = entregas.filter(data_saida__gte=dt)
            except Exception:
                pass

        # Exportação em CSV
        if request.query_params.get('format') == 'csv' or request.query_params.get('export') == 'csv':
            buffer = StringIO()
            buffer.write('\ufeff')
            writer = csv.writer(buffer, delimiter=';')
            writer.writerow([
                'ID Entrega', 'Status', 'Placa Veículo', 'Modelo Veículo', 'Capacidade (kg)',
                'Motorista', 'Rota', 'Peso Carregado (kg)', 'Lotação (%)',
                'Cilindros Entregues', 'Cilindros Recolhidos', 'Comprovantes Digitais',
                'Data Saída'
            ])
            for e in entregas:
                movs = e.movimentacoes_cilindros.select_related('cilindro', 'cliente').all()
                entregues = movs.filter(tipo__in=['ENTREGA_CLIENTE', 'SAIDA_ROTA']).count()
                recolhidos = movs.filter(tipo='RECOLHA_CLIENTE').count()
                writer.writerow([
                    e.id,
                    e.status,
                    e.veiculo.placa if e.veiculo else '',
                    e.veiculo.modelo if e.veiculo else '',
                    f"{float(e.veiculo.capacidade_carga):.2f}" if (e.veiculo and e.veiculo.capacidade_carga) else '0.00',
                    e.motorista.get_full_name() or e.motorista.username if e.motorista else '',
                    e.rota.nome if e.rota else '',
                    f"{float(e.peso_total_carregado):.2f}",
                    f"{e.percentual_lotacao:.1f}%",
                    entregues,
                    recolhidos,
                    e.comprovantes.count(),
                    e.data_saida.strftime('%d/%m/%Y %H:%M:%S') if e.data_saida else ''
                ])
            response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="entregas_romaneios_erp.csv"'
            return response

        total_count = entregas.count()

        # Paginação configurável eliminando corte fixo de [:100] (D9)
        try:
            page_size = int(request.query_params.get('page_size', 50))
            if page_size <= 0:
                page_size = 50
        except ValueError:
            page_size = 50

        try:
            page_num = int(request.query_params.get('page', 1))
            if page_num <= 0:
                page_num = 1
        except ValueError:
            page_num = 1

        start = (page_num - 1) * page_size
        end = start + page_size
        entregas_page = entregas[start:end]

        dados = []
        for e in entregas_page:
            movs = e.movimentacoes_cilindros.select_related('cilindro', 'cliente').all()
            entregues = movs.filter(tipo__in=['ENTREGA_CLIENTE', 'SAIDA_ROTA']).count()
            recolhidos = movs.filter(tipo='RECOLHA_CLIENTE').count()

            dados.append({
                'entrega_id': e.id,
                'status': e.status,
                'veiculo': {
                    'placa': e.veiculo.placa if e.veiculo else None,
                    'modelo': e.veiculo.modelo if e.veiculo else None,
                    'capacidade_carga_kg': float(e.veiculo.capacidade_carga) if e.veiculo and e.veiculo.capacidade_carga else 0.0
                },
                'motorista': e.motorista.get_full_name() or e.motorista.username if e.motorista else None,
                'rota': e.rota.nome if e.rota else None,
                'peso_total_kg': float(e.peso_total_carregado),
                'percentual_lotacao': e.percentual_lotacao,
                'total_cilindros_entregues': entregues,
                'total_cilindros_recolhidos': recolhidos,
                'total_comprovantes': e.comprovantes.count()
            })

        return Response({
            'total': total_count,
            'page': page_num,
            'page_size': page_size,
            'entregas': dados
        })


class BuscaGlobalAPIView(TenantViewSetMixin, APIView):
    """
    Endpoint de pesquisa unificada para a Barra de Comando Global (Ctrl+K).
    Permite busca rápida com debounce em Cilindros, Lotes Químicos, Clientes e Veículos.
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if not q or len(q) < 1:
            return Response({'results': [], 'total': 0})

        from django.db.models import Q
        from produtos.models import Cilindro, LoteEnvase
        from clientes.models import Cliente
        from logistica.models import Veiculo

        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if not tenant:
            return Response({'results': [], 'total': 0})

        resultados = []

        # 1. Cilindros (Série da Ogiva ou Código QR)
        cilindros = Cilindro.objects.filter(tenant=tenant).select_related('gas_dedicado', 'modelo').filter(
            Q(numero_serie_ogiva__icontains=q) | Q(codigo_qr__icontains=q)
        )[:6]
        for c in cilindros:
            gas_str = c.gas_dedicado.nome if c.gas_dedicado else 'Gás não definido'
            resultados.append({
                'tipo': 'cilindro',
                'badge': 'Cilindro',
                'titulo': f"{c.numero_serie_ogiva} ({c.codigo_qr})",
                'subtitulo': f"{gas_str} • Status: {c.get_status_display()}",
                'url': f"/produtos/?busca={c.codigo_qr}&cilindro_id={c.id}",
                'extra_id': str(c.id),
                'codigo_qr': c.codigo_qr
            })

        # 2. Lotes Químicos (Código do Lote)
        lotes = LoteEnvase.objects.filter(tenant=tenant).select_related('gas').filter(
            codigo_lote__icontains=q
        )[:6]
        for l in lotes:
            gas_str = l.gas.nome if l.gas else 'Gás'
            resultados.append({
                'tipo': 'lote',
                'badge': 'Lote Químico',
                'titulo': f"Lote {l.codigo_lote}",
                'subtitulo': f"{gas_str} • Pureza: {l.pureza_percentual}% • {l.get_status_qualidade_display()}",
                'url': f"/produtos/anvisa/recall/?lote={l.codigo_lote}",
                'extra_id': str(l.id)
            })

        # 3. Clientes (Razão Social ou CNPJ)
        clientes = Cliente.objects.filter(tenant=tenant).filter(
            Q(nome__icontains=q) | Q(cnpj__icontains=q)
        )[:6]
        for cl in clientes:
            local = f"{cl.cidade}/{cl.estado}" if cl.cidade else "Localidade N/I"
            resultados.append({
                'tipo': 'cliente',
                'badge': 'Cliente',
                'titulo': cl.nome,
                'subtitulo': f"CNPJ: {cl.cnpj} • {local}",
                'url': f"/clientes/?busca={cl.cnpj}&cliente_id={cl.id}",
                'extra_id': str(cl.id)
            })

        # 4. Veículos (Placa ou Modelo)
        veiculos = Veiculo.objects.filter(tenant=tenant).filter(
            Q(placa__icontains=q) | Q(modelo__icontains=q)
        )[:6]
        for v in veiculos:
            resultados.append({
                'tipo': 'veiculo',
                'badge': 'Veículo',
                'titulo': f"{v.placa} ({v.modelo})",
                'subtitulo': f"Capacidade: {v.capacidade_carga} kg • Status: {v.status}",
                'url': f"/logistica/?veiculo_id={v.id}",
                'extra_id': str(v.id)
            })

        return Response({
            'q': q,
            'total': len(resultados),
            'results': resultados
        })


class IntegracoesView(LoginRequiredMixin, TemplateView):
    """
    Console Administrativo de Integrações ERP, Gestão de Webhooks HMAC e Exportação Canônica (D7/D9).
    Acesso restrito a ADMIN e GERENTE.
    """
    template_name = 'core/integracoes.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        membership = getattr(request, 'membership', None)
        papel = membership.papel if (membership and membership.ativo) else None
        if not (request.user.is_superuser or papel in ('ADMIN', 'GERENTE')):
            from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
            raise DjangoPermissionDenied("Acesso restrito à gestão da empresa (Administrador ou Gerente).")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from core.models import WebhookEndpoint, WebhookDeliveryLog
        tenant = get_current_tenant() or getattr(self.request, 'tenant', None)
        
        context['endpoints'] = WebhookEndpoint.objects.filter(tenant=tenant).order_by('-criado_em') if tenant else []
        context['recent_logs'] = WebhookDeliveryLog.objects.filter(tenant=tenant).select_related('endpoint').order_by('-enviado_em')[:50] if tenant else []
        return context


class PerfilRegulatorioView(LoginRequiredMixin, TemplateView):
    """
    Console Administrativo do Perfil Regulatório ANVISA & Gestão de RTs (Fase Final).
    Permite configurar AFE, Licença Sanitária, CBPF/CBPDA e cadastrar farmacêuticos/químicos (RTs).
    Acesso restrito a ADMIN e GERENTE.
    """
    template_name = 'core/perfil_regulatorio.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        membership = getattr(request, 'membership', None)
        papel = membership.papel if (membership and membership.ativo) else None
        if not (request.user.is_superuser or papel in ('ADMIN', 'GERENTE')):
            from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
            raise DjangoPermissionDenied("Acesso restrito à gestão da empresa (Administrador ou Gerente).")
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def calcular_badge(data_validade, nome):
        hoje = timezone.now().date()
        if not data_validade:
            return {
                'status': 'ausente',
                'badge_class': 'badge-danger',
                'badge_text': 'Ausente / Não Informado',
                'alerta': True,
                'msg': f"{nome} não informado(a).",
                'dias': None
            }
        if data_validade < hoje:
            dias = (hoje - data_validade).days
            return {
                'status': 'vencido',
                'badge_class': 'badge-danger',
                'badge_text': f"Vencido há {dias} dia(s)",
                'alerta': True,
                'msg': f"{nome} expirou em {data_validade.strftime('%d/%m/%Y')}.",
                'dias': -dias
            }
        dias_restantes = (data_validade - hoje).days
        if dias_restantes <= 30:
            return {
                'status': 'alerta',
                'badge_class': 'badge-warning',
                'badge_text': f"Vence em {dias_restantes} dia(s)",
                'alerta': False,
                'msg': f"{nome} vence em breve ({data_validade.strftime('%d/%m/%Y')}).",
                'dias': dias_restantes
            }
        return {
            'status': 'vigente',
            'badge_class': 'badge-success',
            'badge_text': 'Vigente',
            'alerta': False,
            'msg': f"{nome} regular até {data_validade.strftime('%d/%m/%Y')}.",
            'dias': dias_restantes
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from core.models import PerfilRegulatorioTenant, ResponsavelTecnico
        tenant = get_current_tenant() or getattr(self.request, 'tenant', None)
        if not tenant:
            membership = getattr(self.request, 'membership', None)
            if membership:
                tenant = membership.tenant

        perfil, _ = PerfilRegulatorioTenant.objects.get_or_create(
            tenant=tenant,
            defaults={
                'modo_operacao': 'ENVASADORA',
                'afe_numero': 'AFE-PENDENTE',
                'licenca_sanitaria_numero': 'VISA-PENDENTE',
                'licenca_sanitaria_validade': timezone.now().date() + datetime.timedelta(days=365),
            }
        )

        afe_badge = self.calcular_badge(perfil.afe_validade, 'AFE ANVISA') if perfil.afe_numero else {'badge_class': 'badge-info', 'badge_text': 'Não Informada', 'alerta': False}
        licenca_badge = self.calcular_badge(perfil.licenca_sanitaria_validade, 'Licença Sanitária (VISA)')
        cbpf_badge = self.calcular_badge(perfil.cbpf_cbpda_validade, 'CBPF/CBPDA ANVISA') if perfil.cbpf_cbpda_numero else {'badge_class': 'badge-info', 'badge_text': 'Não Informado', 'alerta': (perfil.modo_operacao != 'DISTRIBUIDORA')}

        rts = ResponsavelTecnico.objects.filter(tenant=tenant).order_by('-ativo', 'nome_completo')
        rts_com_status = []
        for r in rts:
            rts_com_status.append({
                'rt': r,
                'esta_vigente': r.esta_vigente,
                'badge_vigencia': self.calcular_badge(r.vigencia_fim, f"Vigência de {r.nome_completo}") if r.vigencia_fim else {'badge_class': 'badge-success' if r.ativo else 'badge-danger', 'badge_text': 'Vigente' if r.ativo else 'Inativo'}
            })

        mensagens_alerta = []
        if licenca_badge.get('alerta'):
            mensagens_alerta.append("Licença Sanitária (VISA) vencida ou ausente.")
        if perfil.afe_validade and afe_badge.get('alerta'):
            mensagens_alerta.append("Autorização de Funcionamento ANVISA (AFE) vencida.")
        if perfil.modo_operacao != 'DISTRIBUIDORA':
            if not perfil.cbpf_cbpda_numero or not perfil.cbpf_cbpda_validade:
                mensagens_alerta.append("CBPF da ANVISA não informado (obrigatório para envasadoras de gases medicinais).")
            elif cbpf_badge.get('alerta'):
                mensagens_alerta.append("Certificado de BPF (CBPF ANVISA) expirado.")
        if not perfil.responsavel_tecnico_vigente:
            mensagens_alerta.append("Nenhum Responsável Técnico (RT) ativo vinculado como titular.")
        elif not perfil.responsavel_tecnico_vigente.esta_vigente:
            mensagens_alerta.append(f"O Responsável Técnico titular ({perfil.responsavel_tecnico_vigente.nome_completo}) está com vigência expirada ou inativo.")

        context.update({
            'tenant': tenant,
            'perfil': perfil,
            'afe_badge': afe_badge,
            'licenca_badge': licenca_badge,
            'cbpf_badge': cbpf_badge,
            'rts_com_status': rts_com_status,
            'tem_alerta_critico': len(mensagens_alerta) > 0,
            'mensagens_alerta': mensagens_alerta,
        })
        return context

    def post(self, request, *args, **kwargs):
        from core.models import PerfilRegulatorioTenant, ResponsavelTecnico
        from core.tenancy import tenant_context
        tenant = get_current_tenant() or getattr(request, 'tenant', None)
        if not tenant:
            membership = getattr(request, 'membership', None)
            if membership:
                tenant = membership.tenant

        action = request.POST.get('action', 'salvar_perfil')
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')

        try:
            if action == 'salvar_perfil':
                perfil = PerfilRegulatorioTenant.objects.filter(tenant=tenant).first()
                if not perfil:
                    perfil = PerfilRegulatorioTenant(tenant=tenant)

                perfil.modo_operacao = request.POST.get('modo_operacao', perfil.modo_operacao)
                perfil.afe_numero = request.POST.get('afe_numero', '').strip()
                afe_val = request.POST.get('afe_validade')
                perfil.afe_validade = datetime.date.fromisoformat(afe_val) if afe_val else None

                perfil.licenca_sanitaria_numero = request.POST.get('licenca_sanitaria_numero', '').strip()
                lic_val = request.POST.get('licenca_sanitaria_validade')
                perfil.licenca_sanitaria_validade = datetime.date.fromisoformat(lic_val) if lic_val else None

                perfil.cbpf_cbpda_numero = request.POST.get('cbpf_cbpda_numero', '').strip()
                cbpf_val = request.POST.get('cbpf_cbpda_validade')
                perfil.cbpf_cbpda_validade = datetime.date.fromisoformat(cbpf_val) if cbpf_val else None

                rt_vigente_id = request.POST.get('responsavel_tecnico_vigente')
                if rt_vigente_id:
                    perfil.responsavel_tecnico_vigente = ResponsavelTecnico.objects.filter(tenant=tenant, id=rt_vigente_id).first()
                else:
                    perfil.responsavel_tecnico_vigente = None

                perfil.save()
                if is_ajax:
                    return JsonResponse({'sucesso': True, 'mensagem': 'Perfil Regulatório atualizado com sucesso!'})

            elif action == 'salvar_rt':
                rt_id = request.POST.get('rt_id')
                nome = request.POST.get('nome_completo', '').strip()
                conselho = request.POST.get('conselho_classe', 'CRF')
                numero = request.POST.get('numero_registro', '').strip()
                uf = request.POST.get('uf_conselho', 'SP').strip().upper()
                vig_ini = request.POST.get('vigencia_inicio')
                vig_fim = request.POST.get('vigencia_fim')
                ativo = request.POST.get('ativo') in ('true', 'True', '1', 'on')

                if not nome or not numero or not vig_ini:
                    if is_ajax:
                        return JsonResponse({'sucesso': False, 'erro': 'Nome, Número de Registro e Início da Vigência são obrigatórios.'}, status=400)

                with tenant_context(tenant):
                    if rt_id:
                        rt = ResponsavelTecnico.objects.filter(tenant=tenant, id=rt_id).first()
                        if not rt:
                            if is_ajax:
                                return JsonResponse({'sucesso': False, 'erro': 'RT não encontrado.'}, status=404)
                    else:
                        rt = ResponsavelTecnico(tenant=tenant)

                    rt.nome_completo = nome
                    rt.conselho_classe = conselho
                    rt.numero_registro = numero
                    rt.uf_conselho = uf
                    rt.vigencia_inicio = datetime.date.fromisoformat(vig_ini)
                    rt.vigencia_fim = datetime.date.fromisoformat(vig_fim) if vig_fim else None
                    rt.ativo = ativo
                    rt.save()

                if is_ajax:
                    return JsonResponse({
                        'sucesso': True,
                        'mensagem': 'Responsável Técnico salvo com sucesso!',
                        'rt': {
                            'id': rt.id,
                            'nome': rt.nome_completo,
                            'conselho': f"{rt.conselho_classe}-{rt.uf_conselho} {rt.numero_registro}",
                            'esta_vigente': rt.esta_vigente,
                        }
                    })

            elif action == 'definir_rt_vigente':
                rt_id = request.POST.get('rt_id')
                perfil = PerfilRegulatorioTenant.objects.filter(tenant=tenant).first()
                if perfil and rt_id:
                    rt = ResponsavelTecnico.objects.filter(tenant=tenant, id=rt_id).first()
                    perfil.responsavel_tecnico_vigente = rt
                    perfil.save()
                    if is_ajax:
                        return JsonResponse({'sucesso': True, 'mensagem': f'RT {rt.nome_completo} definido como titular!'})

        except Exception as e:
            if is_ajax:
                return JsonResponse({'sucesso': False, 'erro': str(e)}, status=400)

        return HttpResponseRedirect(request.path)




# ==============================================================================
# TENANT SWITCHER & HOME ADAPTATIVA (FASE 1)
# ==============================================================================
from django.views import View
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseRedirect
from core.models import Tenant, Membership
from produtos.models import LoteEnvase, RecallCampanha


class TrocarTenantView(LoginRequiredMixin, View):
    """
    Alterna a empresa (Tenant) ativa da sessão web do usuário logado.
    Valida se o usuário é superuser ou possui Membership ativo no tenant alvo.
    """
    def post(self, request):
        if not request.user.is_superuser:
            return JsonResponse({
                'sucesso': False,
                'erro': 'Acesso restrito a administradores do sistema.'
            }, status=403)

        tenant_id = request.POST.get('tenant_id') or request.GET.get('tenant_id')
        if not tenant_id:
            try:
                import json
                body_data = json.loads(request.body.decode('utf-8'))
                tenant_id = body_data.get('tenant_id')
            except Exception:
                pass

        if not tenant_id:
            return JsonResponse({'sucesso': False, 'erro': 'Parâmetro tenant_id não informado.'}, status=400)

        user = request.user
        tenant = Tenant.objects.filter(id=tenant_id, ativo=True).first()

        if not tenant:
            return JsonResponse({'sucesso': False, 'erro': 'Você não tem permissão para acessar esta empresa ou ela está inativa.'}, status=403)

        request.session['active_tenant_id'] = str(tenant.id)
        request.session.modified = True

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
            return JsonResponse({'sucesso': True, 'tenant_id': str(tenant.id), 'tenant_nome': tenant.nome_fantasia})

        redirect_url = request.META.get('HTTP_REFERER') or '/inicio/'
        return HttpResponseRedirect(redirect_url)


class HomeView(LoginRequiredMixin, TemplateView):
    """
    Home adaptativa com Fila de Ação Imediata personalizada pelo papel do usuário (Fase 1).
    Redireciona automaticamente MOTORISTA para a interface PWA de campo (/campo/).
    """
    template_name = 'core/home.html'

    def get(self, request, *args, **kwargs):
        membership = getattr(request, 'membership', None)
        if membership and membership.papel == 'MOTORISTA' and not request.user.is_superuser:
            return HttpResponseRedirect('/campo/')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        membership = getattr(self.request, 'membership', None)
        tenant = getattr(self.request, 'tenant', None) or get_current_tenant()
        if not tenant and membership:
            tenant = membership.tenant

        tem_distribuicao = getattr(tenant, 'tem_modulo_distribuicao', True) if tenant else True
        tem_envase = getattr(tenant, 'tem_modulo_envase', False) if tenant else False
        modo_operacao = getattr(tenant, 'modo_operacao', 'DISTRIBUIDORA') if tenant else 'DISTRIBUIDORA'

        context['tem_modulo_distribuicao'] = tem_distribuicao
        context['tem_modulo_envase'] = tem_envase
        context['modo_operacao'] = modo_operacao

        papel = membership.papel if membership else ('ADMIN' if user.is_superuser else None)
        hoje = timezone.now().date()

        fila_itens = []

        # 1. ADMIN ou GERENTE
        if papel in ('ADMIN', 'GERENTE') or user.is_superuser:
            # Extravios potenciais (> 180 dias retidos em clientes) - apenas módulo distribuição
            if tem_distribuicao:
                limite_extravio = timezone.now() - datetime.timedelta(days=180)
                extravios_count = Cilindro.objects.filter(
                    status='EM_POSSE_CLIENTE',
                    posse_desde__lte=limite_extravio
                ).count()
                if extravios_count > 0:
                    fila_itens.append({
                        'prioridade': 'danger',
                        'badge': 'Risco Patrimonial',
                        'count': extravios_count,
                        'titulo': 'Cilindros com Retenção > 180 dias',
                        'descricao': 'Ativos em clientes há mais de 6 meses sem giro. Candidatos à declaração de extravio e cobrança de reposição.',
                        'link': '/produtos/?filtro=extravio_candidato',
                        'botao_texto': 'Revisar Cascos'
                    })

            # Alertas de Reteste INMETRO (Universal)
            reteste_vencidos = Cilindro.objects.filter(
                data_proximo_reteste__lte=hoje + datetime.timedelta(days=30)
            ).count()
            if reteste_vencidos > 0:
                fila_itens.append({
                    'prioridade': 'warning',
                    'badge': 'Conformidade',
                    'count': reteste_vencidos,
                    'titulo': 'Retestes INMETRO Vencendo / Vencidos',
                    'descricao': 'Cilindros que precisam de teste hidrostático para continuar aptos a envase e expedição.',
                    'link': '/produtos/?reteste_vencido=true',
                    'botao_texto': 'Ver Cilindros'
                })

        # 2. RESPONSÁVEL TÉCNICO (RT)
        if papel == 'RESPONSAVEL_TECNICO' or user.is_superuser:
            # Lotes em quarentena aguardando laudo
            lotes_quarentena = LoteEnvase.objects.filter(status_qualidade='QUARENTENA').count()
            if lotes_quarentena > 0:
                fila_itens.append({
                    'prioridade': 'quarantine',
                    'badge': 'Quarentena ANVISA',
                    'count': lotes_quarentena,
                    'titulo': 'Lotes Aguardando Homologação',
                    'descricao': 'Lotes químicos produzidos que requerem análise de controle de qualidade e liberação formal do RT.',
                    'link': '/produtos/anvisa/recall/',
                    'botao_texto': 'Analisar Lotes'
                })

            # Cilindros com bloqueio sanitário ativo
            cilindros_bloqueados = Cilindro.objects.filter(bloqueio_sanitario=True).count()
            if cilindros_bloqueados > 0:
                fila_itens.append({
                    'prioridade': 'danger',
                    'badge': 'Bloqueio Sanitário',
                    'count': cilindros_bloqueados,
                    'titulo': 'Cilindros com Bloqueio Sanitário',
                    'descricao': 'Ativos isolados por contaminação, suspeita técnica ou recall pendente de liberação ou purga.',
                    'link': '/produtos/?bloqueio_sanitario=true',
                    'botao_texto': 'Auditar Bloqueios'
                })

            # Campanhas de Recall Abertas
            recalls_abertos = RecallCampanha.objects.filter(status__in=['ABERTO', 'HOMOLOGADO_RT']).count()
            if recalls_abertos > 0:
                fila_itens.append({
                    'prioridade': 'danger',
                    'badge': 'Alerta Máximo',
                    'count': recalls_abertos,
                    'titulo': 'Campanhas de Recall Sanitário',
                    'descricao': 'Processos de contenção e rastreabilidade ativa de lotes em andamento.',
                    'link': '/produtos/anvisa/recall/',
                    'botao_texto': 'Acompanhar Recall'
                })

        # 3. OPERADOR DE PÁTIO
        if papel in ('OPERADOR_PATIO', 'ADMIN') or user.is_superuser:
            # Vazios em Triagem
            vazios_triagem = Cilindro.objects.filter(status='VAZIO_TRIAGEM').count()
            if vazios_triagem > 0:
                fila_itens.append({
                    'prioridade': 'info',
                    'badge': 'Operação de Pátio',
                    'count': vazios_triagem,
                    'titulo': 'Cilindros Vazios em Triagem',
                    'descricao': 'Cascos recolhidos aguardando inspeção pré-envase (IN 129/2022) ou requalificação.',
                    'link': '/produtos/?status=VAZIO_TRIAGEM',
                    'botao_texto': 'Iniciar Triagem'
                })

        # 4. MOTORISTA (apenas módulo distribuição)
        if tem_distribuicao and (papel in ('MOTORISTA', 'ADMIN') or user.is_superuser):
            # Entregas pendentes
            entregas_motorista = Entrega.objects.filter(status__in=['Em Separação', 'Em Rota'])
            if papel == 'MOTORISTA' and not user.is_superuser:
                entregas_motorista = entregas_motorista.filter(motorista=user)
            entregas_count = entregas_motorista.count()
            if entregas_count > 0:
                fila_itens.append({
                    'prioridade': 'info',
                    'badge': 'Logística de Campo',
                    'count': entregas_count,
                    'titulo': 'Romaneios / Rotas Ativas',
                    'descricao': 'Cargas liberadas ou em trânsito para execução de entregas e recolhas de cilindros.',
                    'link': '/campo/',
                    'botao_texto': 'Abrir App de Campo'
                })

        # 5. VENDEDOR (apenas módulo distribuição)
        if tem_distribuicao and (papel in ('VENDEDOR', 'ADMIN') or user.is_superuser):
            vendas_pendentes = Venda.objects.filter(status__in=['Pendente', 'Em Separação']).count()
            if vendas_pendentes > 0:
                fila_itens.append({
                    'prioridade': 'warning',
                    'badge': 'Comercial',
                    'count': vendas_pendentes,
                    'titulo': 'Pedidos Aguardando Expedição',
                    'descricao': 'Pedidos fechados que necessitam de separação de cascos e alocação de frota.',
                    'link': '/vendas/',
                    'botao_texto': 'Ver Pedidos'
                })

        context['fila_acao_imediata'] = fila_itens
        return context


class ExportacaoDadosTenantView(View):
    """
    Exportação de dados do Tenant (Sprint 7B - v2.0 - Tarefa 17).
    Permite que o Administrador da empresa exporte os dados operacionais em JSON ou CSV,
    mesmo após o cancelamento, até a data_limite_exportacao (default 90 dias).
    """
    def get(self, request):
        user = request.user
        if not (user and user.is_authenticated):
            return HttpResponseForbidden("Autenticação obrigatória.")

        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if not tenant:
            membership = resolve_request_membership(request)
            tenant = membership.tenant if membership else None

        if not tenant:
            return HttpResponseForbidden("Tenant não identificado.")

        # Verifica se é ADMIN ou superuser
        membership = resolve_request_membership(request)
        is_admin = bool(user.is_superuser or (membership and membership.ativo and membership.papel == 'ADMIN'))
        if not is_admin:
            return HttpResponseForbidden("Apenas o Administrador da empresa pode exportar dados.")

        # Se cancelado, verifica prazo limite de exportação
        if tenant.status_assinatura == 'CANCELADO':
            hoje = timezone.localdate()
            if tenant.data_limite_exportacao and hoje > tenant.data_limite_exportacao:
                return HttpResponseForbidden("Prazo limite de exportação de dados pós-cancelamento expirado.")

        formato = request.GET.get('formato', 'json').lower()

        from core.models import Filial
        from produtos.models import Cilindro
        from clientes.models import Cliente
        from vendas.models import Venda

        dados = {
            'tenant': {
                'id': str(tenant.id),
                'razao_social': tenant.razao_social,
                'nome_fantasia': tenant.nome_fantasia,
                'cnpj': tenant.cnpj,
                'status_assinatura': tenant.status_assinatura,
                'data_cancelamento': str(tenant.data_cancelamento) if tenant.data_cancelamento else None,
                'data_limite_exportacao': str(tenant.data_limite_exportacao) if tenant.data_limite_exportacao else None,
            },
            'filiais': list(Filial.objects.filter(tenant=tenant).values('id', 'nome', 'cnpj', 'matriz')),
            'cilindros': list(Cilindro.unscoped.filter(tenant=tenant).values('id', 'codigo_qr', 'numero_serie_ogiva', 'status', 'propriedade')[:500]),
            'clientes': list(Cliente.unscoped.filter(tenant=tenant).values('id', 'nome', 'cnpj', 'tipo_cliente')[:500]),
            'vendas': list(Venda.unscoped.filter(tenant=tenant).values('id', 'status', 'valor_total', 'data_venda')[:500]),
        }

        if formato == 'csv':
            import csv
            import io
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(['Tipo', 'ID', 'Identificador/Nome', 'Status/Valor'])
            for f in dados['filiais']:
                writer.writerow(['Filial', str(f['id']), f['nome'], f['cnpj']])
            for c in dados['cilindros']:
                writer.writerow(['Cilindro', str(c['id']), c['numero_serie_ogiva'], c['status']])
            for cl in dados['clientes']:
                writer.writerow(['Cliente', str(cl['id']), cl['nome'], cl['tipo_cliente']])
            for v in dados['vendas']:
                writer.writerow(['Venda', str(v['id']), str(v['data_venda']), str(v['valor_total'])])

            response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="export_dados_{tenant.cnpj}.csv"'
            return response

        return JsonResponse(dados)


