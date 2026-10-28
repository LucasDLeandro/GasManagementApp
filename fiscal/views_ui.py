from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from core.modulos import is_modulo_ativo
from fiscal.models import (
    DocumentoFiscal,
    RegraTributaria,
    ConfiguracaoFiscalFilial,
    TarefaInutilizacaoNumeracao,
)
from fiscal.services.certificado_service import verificar_vencimento_certificados


class FiscalDashboardView(LoginRequiredMixin, View):
    """
    Painel de Gestão e Monitoramento Fiscal (Sprint 11A - Task 11).
    Apresenta lista de documentos fiscais com status, motivo de rejeição,
    ações de reenvio, cancelamento e download de XML / DANFE.
    """
    template_name = 'fiscal/index.html'

    def get(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            raise PermissionDenied("Nenhum tenant ativo associado à sessão.")

        if not is_modulo_ativo(tenant, 'fiscal') and not request.user.is_superuser:
            raise PermissionDenied("O módulo Fiscal não está contratado ou ativo para esta empresa.")

        # Documentos fiscais recentes
        qs = DocumentoFiscal.objects.filter(tenant=tenant).select_related('filial').order_by('-criado_em')

        status_filtro = request.GET.get('status')
        if status_filtro:
            qs = qs.filter(status=status_filtro.upper())

        modelo_filtro = request.GET.get('modelo')
        if modelo_filtro:
            qs = qs.filter(modelo=modelo_filtro.upper())

        documentos = qs[:50]

        # Métricas resumidas
        total_docs = DocumentoFiscal.objects.filter(tenant=tenant).count()
        total_autorizados = DocumentoFiscal.objects.filter(tenant=tenant, status='AUTORIZADO').count()
        total_rejeitados = DocumentoFiscal.objects.filter(tenant=tenant, status='REJEITADO').count()
        total_cancelados = DocumentoFiscal.objects.filter(tenant=tenant, status='CANCELADO').count()

        # Alertas de certificado digital
        todos_alertas = verificar_vencimento_certificados(dias=30)
        alertas_tenant = [a for a in todos_alertas if a['tenant_id'] == str(tenant.id)]

        # Regras Tributárias
        total_regras = RegraTributaria.objects.filter(tenant=tenant).count()
        regras_aprovadas = RegraTributaria.objects.filter(tenant=tenant, aprovada_por__isnull=False).count()

        # Inutilizações pendentes
        inutilizacoes_pendentes = TarefaInutilizacaoNumeracao.objects.filter(tenant=tenant, status='PENDENTE').count()

        context = {
            'documentos': documentos,
            'total_docs': total_docs,
            'total_autorizados': total_autorizados,
            'total_rejeitados': total_rejeitados,
            'total_cancelados': total_cancelados,
            'alertas_certificados': alertas_tenant,
            'total_regras': total_regras,
            'regras_aprovadas': regras_aprovadas,
            'inutilizacoes_pendentes': inutilizacoes_pendentes,
            'status_filtro': status_filtro or '',
            'modelo_filtro': modelo_filtro or '',
        }
        return render(request, self.template_name, context)
