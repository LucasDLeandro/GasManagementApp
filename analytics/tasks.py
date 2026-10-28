"""
Tarefas Assíncronas Celery para Analytics e Alertas Preditivos (Sprint 12C - Tarefa 5).

Implementa:
- job_alertas_oportunidade_diario: varredura diária de demanda, risco de churn e retenção de cilindros;
- Herda de TenantTask garantindo fail-closed, log em JobExecucao e observabilidade;
- Idempotente por (cliente, gas, tipo, data_ref) e com cooldown de 30 dias para descartados.
"""
import datetime
import logging
from typing import Any, Dict, Optional

from config.celery import app as celery_app
from core.tasks import TenantTask
from core.models import Tenant
from core.tenancy import tenant_context
from core.modulos import is_modulo_ativo
from analytics.services.alertas_service import gerar_alertas_demand_churn

logger = logging.getLogger(__name__)


@celery_app.task(base=TenantTask, bind=True, requires_modulo='analytics', requires_writable=True)
def job_alertas_oportunidade_diario(
    self,
    tenant_id=None,
    data_ref: Optional[str] = None,
    k: float = 2.0
) -> Dict[str, Any]:
    """
    Job diário de inteligência comercial preditiva (Sprint 12C - Tarefa 5).
    Executa a análise estatística de recompra, risco de churn e permanência Kaplan-Meier.
    """
    dt_ref = datetime.date.fromisoformat(data_ref) if isinstance(data_ref, str) else (data_ref or None)

    tenants = (
        [Tenant.objects.get(id=tenant_id)]
        if tenant_id
        else Tenant.objects.filter(status_assinatura__in=['ATIVO', 'TRIAL'])
    )

    total_alertas_gerados = 0
    resultados_por_tenant = []

    for t in tenants:
        if not is_modulo_ativo(t, 'analytics'):
            continue

        with tenant_context(t):
            alertas = gerar_alertas_demand_churn(
                tenant=t,
                data_ref=dt_ref,
                k=k
            )
            qtd = len(alertas)
            total_alertas_gerados += qtd
            resultados_por_tenant.append({
                'tenant_id': str(t.id),
                'tenant_nome': t.nome_fantasia or t.razao_social,
                'alertas_gerados': qtd
            })

    logger.info(
        f"[ANALYTICS SPRINT 12C] Job diário concluído: {total_alertas_gerados} alertas gerados/atualizados."
    )
    return {
        'total_alertas_gerados': total_alertas_gerados,
        'detalhes': resultados_por_tenant
    }
