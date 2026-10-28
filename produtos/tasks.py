import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

from core.models import Tenant
from core.tenancy import tenant_context
from core.eventos import publicar
from produtos.models import Cilindro

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def alertar_vencimento_reteste_task(self, tenant_id=None):
    """
    Job diário de monitoramento preventivo de vencimento de testes hidrostáticos (Sprint 8B - Tarefa 10).
    Varre os cilindros ativos nos horizontes de 30, 60 e 90 dias e cilindros já vencidos.
    Cilindros vencidos são terminantemente impedidos de receber envase pelas regras da FSM.
    """
    hoje = timezone.localdate()
    d30 = hoje + timedelta(days=30)
    d60 = hoje + timedelta(days=60)
    d90 = hoje + timedelta(days=90)

    tenants_qs = Tenant.objects.filter(ativo=True)
    if tenant_id:
        tenants_qs = tenants_qs.filter(id=tenant_id)

    relatorio = {}

    for tenant in tenants_qs:
        with tenant_context(tenant):
            cilindros_ativos = Cilindro.unscoped.filter(
                tenant=tenant
            ).exclude(
                status__in=['BAIXADO', 'EXTRAVIADO']
            )

            vencidos = cilindros_ativos.filter(data_proximo_reteste__lt=hoje).count()
            vencendo_30 = cilindros_ativos.filter(data_proximo_reteste__gte=hoje, data_proximo_reteste__lte=d30).count()
            vencendo_60 = cilindros_ativos.filter(data_proximo_reteste__gt=d30, data_proximo_reteste__lte=d60).count()
            vencendo_90 = cilindros_ativos.filter(data_proximo_reteste__gt=d60, data_proximo_reteste__lte=d90).count()

            dados_tenant = {
                'tenant_nome': tenant.nome,
                'vencidos': vencidos,
                'vencendo_30_dias': vencendo_30,
                'vencendo_60_dias': vencendo_60,
                'vencendo_90_dias': vencendo_90,
                'total_monitorado': cilindros_ativos.count()
            }
            relatorio[str(tenant.id)] = dados_tenant

            if vencidos > 0 or vencendo_30 > 0:
                logger.warning(
                    f"[Alerta Reteste] Tenant {tenant.nome}: {vencidos} cilindros com reteste VENCIDO "
                    f"e {vencendo_30} a vencer nos próximos 30 dias."
                )

            publicar('alerta_vencimento_reteste_gerado', {
                'tenant': tenant,
                'data_referencia': str(hoje),
                'vencidos': vencidos,
                'vencendo_30_dias': vencendo_30,
                'vencendo_60_dias': vencendo_60,
                'vencendo_90_dias': vencendo_90,
            })

    return relatorio
