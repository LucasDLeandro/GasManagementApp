import datetime
import logging

from django.utils import timezone

try:
    from celery import Task
except ImportError:
    class Task:
        name = "dummy"

from core.context import tenant_context
from core.models import JobExecucao, Tenant

logger = logging.getLogger(__name__)


class TenantTask(Task):
    """
    Classe base de Task Celery Multi-Tenant com Observabilidade e Retentativa Exponencial (Sprint 7A).
    - Extrai e valida o contexto de Tenant;
    - Executa o corpo da task estritamente dentro de tenant_context(tenant);
    - Aplica retentativas automáticas com backoff exponencial (3 tentativas);
    - Persiste início, fim, duração e eventuais erros em JobExecucao.
    """
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    requires_writable = False
    requires_modulo = None

    def __call__(self, *args, **kwargs):
        # 1. Resolve o tenant_id
        tenant_param = kwargs.get('tenant_id') or kwargs.get('tenant')
        tenant = None

        if tenant_param:
            if isinstance(tenant_param, Tenant):
                tenant = tenant_param
            else:
                tenant = Tenant.objects.filter(id=tenant_param).first()

        # Garante vínculo com app celery se disponível
        if getattr(self, '_app', None) is None:
            try:
                from config.celery import app as celery_app
                if celery_app:
                    self.bind(celery_app)
            except (ImportError, AttributeError):
                pass

        # Se não há tenant específico passado como parâmetro, roda normalmente
        if not tenant:
            if getattr(self, 'request_stack', None) is not None:
                return super().__call__(*args, **kwargs)
            return self.run(*args, **kwargs)

        inicio = timezone.now()
        task_name = self.name or self.__class__.__name__

        payload = {
            'args': [str(a) for a in args],
            'kwargs': {k: str(v) for k, v in kwargs.items()}
        }

        job_exec = JobExecucao.unscoped.create(
            tenant=tenant,
            nome=task_name,
            status='INICIADO',
            inicio=inicio,
            payload_json=payload
        )

        with tenant_context(tenant):
            try:
                if getattr(self, 'requires_writable', False):
                    from core.guards import assert_tenant_writable
                    assert_tenant_writable(tenant)

                if getattr(self, 'requires_modulo', None):
                    from core.guards import assert_modulo
                    assert_modulo(tenant, self.requires_modulo)

                if getattr(self, 'request_stack', None) is not None:
                    res = super().__call__(*args, **kwargs)
                else:
                    res = self.run(*args, **kwargs)

                fim = timezone.now()
                duracao = int((fim - inicio).total_seconds() * 1000)
                job_exec.status = 'SUCESSO'
                job_exec.fim = fim
                job_exec.duracao_ms = duracao
                job_exec.save(update_fields=['status', 'fim', 'duracao_ms'])
                return res
            except Exception as exc:
                fim = timezone.now()
                duracao = int((fim - inicio).total_seconds() * 1000)
                job_exec.status = 'FALHA'
                job_exec.fim = fim
                job_exec.duracao_ms = duracao
                job_exec.erro = str(exc)
                job_exec.save(update_fields=['status', 'fim', 'duracao_ms', 'erro'])
                logger.error(f"[TenantTask {task_name}] Falha na execução para tenant {tenant.id}: {exc}")
                raise


def verificar_vencimentos_licenca():
    """
    Job diário idempotente de governança do SaaS (Sprint 7B - v2.0 - Correção F-38).
    - TRIAL vencido passa a SUSPENSO.
    - ATIVO vencido há mais de dias_carencia passa a SUSPENSO.
    - CANCELADO sem data_limite_exportacao define 90 dias a contar do cancelamento.
    Itera tenants com tenant_context(tenant) e executa de forma segura.
    """
    from core.services.assinatura import transicionar

    hoje = timezone.localdate()
    resultados = {
        'suspensos_trial': 0,
        'suspensos_carencia': 0,
        'exportacao_ajustada': 0,
    }

    tenants = Tenant.objects.all()
    for tenant in tenants:
        with tenant_context(tenant):
            # 1. TRIAL vencido
            if tenant.status_assinatura == 'TRIAL':
                if tenant.data_vencimento_licenca and tenant.data_vencimento_licenca < hoje:
                    transicionar(tenant, 'SUSPENSO', executor=None, motivo="Período de avaliação (TRIAL) expirado.")
                    resultados['suspensos_trial'] += 1

            # 2. ATIVO vencido há mais de dias_carencia
            elif tenant.status_assinatura == 'ATIVO':
                if tenant.data_vencimento_licenca:
                    limite_carencia = tenant.data_vencimento_licenca + datetime.timedelta(days=tenant.dias_carencia)
                    if limite_carencia < hoje:
                        transicionar(
                            tenant,
                            'SUSPENSO',
                            executor=None,
                            motivo=f"Licença vencida em {tenant.data_vencimento_licenca:%d/%m/%Y} e carência de {tenant.dias_carencia} dias esgotada."
                        )
                        resultados['suspensos_carencia'] += 1

            # 3. CANCELADO sem data_limite_exportacao
            elif tenant.status_assinatura == 'CANCELADO' and not tenant.data_limite_exportacao:
                base_date = tenant.data_cancelamento or hoje
                tenant.data_limite_exportacao = base_date + datetime.timedelta(days=90)
                tenant.save(update_fields=['data_limite_exportacao'])
                resultados['exportacao_ajustada'] += 1

    resultados['suspensos_count'] = resultados['suspensos_trial'] + resultados['suspensos_carencia']
    return resultados


try:
    from celery import shared_task
    verificar_vencimentos_licenca_task = shared_task(name="core.tasks.verificar_vencimentos_licenca")(verificar_vencimentos_licenca)
except (ImportError, AttributeError):
    verificar_vencimentos_licenca_task = None

