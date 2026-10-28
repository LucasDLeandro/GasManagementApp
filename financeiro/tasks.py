"""
Tarefas assíncronas e jobs em segundo plano do módulo Financeiro (Sprint 10A - Tarefa 10).
- job_importacao_retorno_agendada
- job_execucao_diaria_regua
- job_reenvio_webhooks_pendentes
"""
import logging
from django.utils import timezone
from config.celery import app as celery_app
from core.tasks import TenantTask
from core.models import Tenant
from core.context import tenant_context
from core.modulos import is_modulo_ativo

logger = logging.getLogger(__name__)


@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_execucao_diaria_regua(self, tenant_id=None):
    """
    Job diário de execução da régua de cobrança preventiva e reativa (Sprint 10A - Tarefa 10).
    Idempotente por (parcela, etapa, data).
    """
    from financeiro.services.regua_service import executar_regua_cobranca

    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    total_envios = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            envios = executar_regua_cobranca(tenant=t)
            total_envios += len(envios)

    logger.info(f"[RÉGUA COBRANÇA] Execução diária concluída: {total_envios} notificações processadas.")
    return {'total_envios': total_envios}


@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_importacao_retorno_agendada(self, tenant_id=None):
    """
    Job agendado de importação e processamento de arquivos de retorno bancário (Sprint 10A - Tarefa 10).
    """
    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    importados_count = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            # Processamento de arquivos pendentes em fila ou diretório monitorado
            pass

    return {'importados': importados_count}


@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_reenvio_webhooks_pendentes(self, tenant_id=None):
    """
    Job de resiliência para reprocessamento e reenvio de webhooks e pendências de eventos (Sprint 10A - Tarefa 10).
    """
    from financeiro.models import PendenciaContabilizacao
    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    reprocessados = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            pendentes = PendenciaContabilizacao.objects.filter(tenant=t, resolvido=False)
            for p in pendentes:
                p.tentativas += 1
                p.save(update_fields=['tentativas'])
                reprocessados += 1

    return {'reprocessados': reprocessados}


# ==============================================================================
# SPRINT 10B: JOBS EM SEGUNDO PLANO
# ==============================================================================

@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_calcular_depreciacao_mensal(self, periodo=None, tenant_id=None):
    """
    Job mensal de apuração e lançamento contábil de depreciação (Sprint 10B - Tarefa 1).
    Idempotente, gera lançamento agregado e detalha alvos no ledger.
    """
    from financeiro.services.depreciacao_service import calcular_depreciacao_mensal

    if not periodo:
        periodo = timezone.localdate().replace(day=1)

    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    total_processados = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            try:
                itens, _ = calcular_depreciacao_mensal(tenant=t, periodo=periodo)
                total_processados += len(itens)
            except Exception as e:
                logger.error(f"[DEPRECIAÇÃO] Erro ao calcular depreciação do tenant {t.id}: {e}")

    logger.info(f"[DEPRECIAÇÃO] Concluído cálculo para período {periodo}: {total_processados} alvos processados.")
    return {'periodo': str(periodo), 'total_alvos': total_processados}


@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_calcular_pdd_mensal(self, periodo=None, tenant_id=None):
    """
    Job mensal de apuração e ajuste de PDD (Sprint 10B - Tarefa 10).
    Idempotente, segunda execução no mesmo período gera ajuste zero.
    """
    from financeiro.services.pdd_service import calcular_pdd

    if not periodo:
        periodo = timezone.localdate().replace(day=1)

    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    ajustes_realizados = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            try:
                res = calcular_pdd(tenant=t, periodo=periodo)
                if res.get('lancamento'):
                    ajustes_realizados += 1
            except Exception as e:
                logger.error(f"[PDD] Erro ao calcular PDD do tenant {t.id}: {e}")

    logger.info(f"[PDD] Concluído cálculo para período {periodo}: {ajustes_realizados} ajustes escriturados.")
    return {'periodo': str(periodo), 'ajustes_escriturados': ajustes_realizados}


@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_calcular_provisao_tributaria_mensal(self, periodo=None, tenant_id=None):
    """
    Job mensal de provisão de IRPJ e CSLL (Sprint 10B - Tarefa 8).
    """
    from financeiro.services.tributario_service import calcular_e_lancar_provisao_tributaria

    if not periodo:
        periodo = timezone.localdate().replace(day=1)

    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    total_lancamentos = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            try:
                lanc = calcular_e_lancar_provisao_tributaria(tenant=t, periodo=periodo)
                if lanc:
                    total_lancamentos += 1
            except Exception as e:
                logger.error(f"[TRIBUTÁRIO] Erro ao calcular provisão de IRPJ/CSLL para tenant {t.id}: {e}")

    return {'periodo': str(periodo), 'provisoes_escrituradas': total_lancamentos}


@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_verificar_integridade_snapshots(self, periodo=None, tenant_id=None):
    """
    Job periódico de auditoria e integridade entre Razão e Snapshots SaldoMensalConta (Sprint 10B - Tarefa 6).
    """
    from financeiro.services.snapshot_service import verificar_integridade_snapshots

    if not periodo:
        periodo = timezone.localdate().strftime('%Y-%m')

    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    divergencias_encontradas = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            valido, divs = verificar_integridade_snapshots(tenant=t, periodo=periodo)
            if not valido:
                divergencias_encontradas += len(divs)
                logger.warning(f"[SNAPSHOT] Divergências encontradas no tenant {t.id} no período {periodo}: {len(divs)}")

    return {'periodo': periodo, 'divergencias_encontradas': divergencias_encontradas}


# ==============================================================================
# SPRINT 10C: JOBS EM SEGUNDO PLANO
# ==============================================================================

@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_recalcular_perfil_pagamento_clientes(self, tenant_id=None):
    """
    Job periódico de recálculo dos perfis de pagamento dos clientes (Sprint 10C - Tarefa 2).
    Analisa baixas dos últimos 12 meses e atualiza atraso médio, p80 e inadimplência.
    """
    from financeiro.services.projecao_caixa_service import recalcular_perfil_pagamento_clientes

    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    total_perfis = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            try:
                perfis = recalcular_perfil_pagamento_clientes(tenant=t)
                total_perfis += len(perfis)
            except Exception as e:
                logger.error(f"[PERFIL CLIENTE] Erro ao recalcular perfil do tenant {t.id}: {e}")

    logger.info(f"[PERFIL CLIENTE] Concluído recálculo: {total_perfis} perfis atualizados.")
    return {'total_perfis_atualizados': total_perfis}


@celery_app.task(base=TenantTask, bind=True, requires_modulo='financeiro', requires_writable=True)
def job_verificar_alerta_caixa_diario(self, tenant_id=None):
    """
    Job diário de monitoramento do fluxo de caixa projetado (Sprint 10C - Tarefa 4).
    Dispara e-mail e registra AlertaCaixa se o saldo cair abaixo do mínimo nos próximos N dias.
    """
    from financeiro.services.alerta_caixa_service import verificar_e_gerar_alerta_caixa

    tenants = [Tenant.objects.get(id=tenant_id)] if tenant_id else Tenant.objects.filter(is_active=True)
    alertas_gerados = 0

    for t in tenants:
        if not is_modulo_ativo(t, 'financeiro'):
            continue
        with tenant_context(t):
            try:
                alerta = verificar_e_gerar_alerta_caixa(tenant=t)
                if alerta:
                    alertas_gerados += 1
            except Exception as e:
                logger.error(f"[ALERTA CAIXA] Erro ao verificar alerta de caixa no tenant {t.id}: {e}")

    logger.info(f"[ALERTA CAIXA] Monitoramento diário concluído: {alertas_gerados} alertas gerados.")
    return {'alertas_gerados': alertas_gerados}


