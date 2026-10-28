import logging
from celery import shared_task
from core.models import Tenant
from core.tenancy import tenant_context
from logistica.services.routing import otimizar_ordem_paradas

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def otimizar_ordem_paradas_task(self, tenant_id, entrega_id):
    """
    Task Celery assíncrona para cálculo de roteirização e ordenação ótima de paradas.
    Garante execução non-blocking ao chamar serviços de mapas e geocodificação.
    """
    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        logger.error(f"[otimizar_ordem_paradas_task] Tenant {tenant_id} não encontrado.")
        return {"sucesso": False, "erro": "Tenant não encontrado"}

    with tenant_context(tenant):
        try:
            resultado = otimizar_ordem_paradas(entrega_id)
            return resultado
        except Exception as exc:
            logger.warning(f"[otimizar_ordem_paradas_task] Erro na roteirização ({exc}). Agendando retry...")
            raise self.retry(countdown=30, exc=exc)
