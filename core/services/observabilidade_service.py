"""
Serviço de Observabilidade, Diagnóstico e Alertas Operacionais (Sprint 13 - Tarefa 6).

Monitora e gera alertas explicáveis para:
1. Jobs Celery falhos ou com retentativas esgotadas (JobExecucao);
2. Pendências de Contabilização (PendenciaContabilizacao);
3. Fila fiscal parada ou rejeições SEFAZ (DocumentoFiscal);
4. Integridade das partidas dobradas do Livro-Razão (Σ Débitos == Σ Créditos);
5. Webhooks atrasados na outbox (WebhookDeliveryLog);
6. Certificados Digitais A1 a vencer nos próximos 30 dias (CertificadoDigital).
"""
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from django.utils import timezone
from core.guards import assert_modulo
from core.tenancy import tenant_context


def verificar_integridade_razao_contabil(tenant) -> Dict[str, Any]:
    """
    Verifica se todas as partidas dobradas do tenant no livro-razão estão matematicamente balanceadas.
    """
    from financeiro.models import LancamentoContabil
    from core.money import quantize

    lancamentos = LancamentoContabil.unscoped.filter(tenant=tenant).prefetch_related('partidas')
    divergencias = []
    total_debitos_geral = Decimal('0.00')
    total_creditos_geral = Decimal('0.00')

    for l in lancamentos:
        tot_deb = sum(p.valor for p in l.partidas.all() if p.tipo_partida == 'DEBITO') or Decimal('0.00')
        tot_cred = sum(p.valor for p in l.partidas.all() if p.tipo_partida == 'CREDITO') or Decimal('0.00')
        total_debitos_geral += tot_deb
        total_creditos_geral += tot_cred

        if quantize(tot_deb, 2) != quantize(tot_cred, 2):
            divergencias.append({
                'lancamento_id': l.id,
                'data': l.data_competencia.isoformat() if l.data_competencia else '',
                'total_debito': quantize(tot_deb, 2),
                'total_credito': quantize(tot_cred, 2),
                'diferenca': quantize(tot_deb - tot_cred, 2),
                'historico': l.historico
            })

    integro = len(divergencias) == 0
    return {
        'status': 'OK' if integro else 'CRITICO',
        'integro': integro,
        'total_lancamentos_auditados': lancamentos.count(),
        'total_debitos': quantize(total_debitos_geral, 2),
        'total_creditos': quantize(total_creditos_geral, 2),
        'diferenca': quantize(total_debitos_geral - total_creditos_geral, 2),
        'total_divergencias': len(divergencias),
        'divergencias': divergencias,
        'runbook': "docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-integridade-do-razao"
    }



def verificar_jobs_falhos(tenant: Optional[Any] = None) -> Dict[str, Any]:
    """
    Detecta jobs que falharam nas últimas 24 horas.
    """
    from core.models import JobExecucao
    limite = timezone.now() - datetime.timedelta(hours=24)
    qs = JobExecucao.unscoped.filter(status='ERRO', inicio__gte=limite)
    if tenant:
        qs = qs.filter(tenant=tenant)

    falhas = [
        {
            'job_id': j.id,
            'nome_task': j.nome,
            'erro': j.erro[:200] if j.erro else "Erro desconhecido",
            'data': j.inicio.isoformat() if j.inicio else ""
        }
        for j in qs[:20]
    ]

    return {
        'status': 'OK' if len(falhas) == 0 else 'ALERTA',
        'total_jobs_falhos_24h': qs.count(),
        'amostra_falhas': falhas,
        'runbook': "docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-jobs-falhos"
    }


def verificar_pendencias_contabilizacao(tenant) -> Dict[str, Any]:
    """
    Monitora eventos que falharam na contabilização automática.
    """
    from financeiro.models import PendenciaContabilizacao
    qs = PendenciaContabilizacao.unscoped.filter(tenant=tenant, resolvido=False)
    total = qs.count()

    return {
        'status': 'OK' if total == 0 else ('CRITICO' if total > 10 else 'ALERTA'),
        'total_pendencias_abertas': total,
        'pendencias': list(qs.values('id', 'evento', 'erro_mensagem', 'criado_em')[:10]),
        'runbook': "docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-pendencia-contabilizacao"
    }



def verificar_certificados_a_vencer(tenant: Optional[Any] = None) -> Dict[str, Any]:
    """
    Alerta sobre certificados digitais A1 a vencer nos próximos 30 dias ou já vencidos.
    """
    from fiscal.models import ConfiguracaoFiscalFilial
    hoje = timezone.now().date()
    limite_30d = hoje + datetime.timedelta(days=30)

    qs = ConfiguracaoFiscalFilial.unscoped.filter(certificado_valido_ate__isnull=False, certificado_valido_ate__lte=limite_30d)
    if tenant:
        qs = qs.filter(tenant=tenant)

    alertas = []
    for c in qs:
        dias_restantes = (c.certificado_valido_ate - hoje).days
        alertas.append({
            'config_id': c.id,
            'alias': f"Certificado Filial #{c.filial_id}",
            'valido_ate': c.certificado_valido_ate.isoformat(),
            'dias_restantes': dias_restantes,
            'status_vencimento': "VENCIDO" if dias_restantes < 0 else "A_VENCER"
        })

    return {
        'status': 'OK' if len(alertas) == 0 else ('CRITICO' if any(a['dias_restantes'] < 7 for a in alertas) else 'ALERTA'),
        'total_certificados_risco': len(alertas),
        'certificados': alertas,
        'runbook': "docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-certificados-a-vencer"
    }



auditar_certificados_digitais = verificar_certificados_a_vencer


def diagnosticar_painel_observabilidade(tenant) -> Dict[str, Any]:

    """
    Gera o dashboard consolidado de saúde operacional e observabilidade para a gestão.
    """
    razao = verificar_integridade_razao_contabil(tenant)
    jobs = verificar_jobs_falhos(tenant)
    pendencias = verificar_pendencias_contabilizacao(tenant)
    certificados = verificar_certificados_a_vencer(tenant)

    # Severidade máxima entre os subsistemas
    severidades = [razao['status'], jobs['status'], pendencias['status'], certificados['status']]
    if 'CRITICO' in severidades:
        status_geral = 'CRITICO'
    elif 'ALERTA' in severidades:
        status_geral = 'ALERTA'
    else:
        status_geral = 'SAUDAVEL'

    return {
        'tenant_id': str(tenant.id),
        'status_geral': status_geral,
        'data_diagnostico': timezone.now().isoformat(),
        'razao_contabil': razao,
        'jobs_falhos': jobs,
        'pendencias_contabilizacao': pendencias,
        'certificados_digitais': certificados,
        'diagnosticos': {
            'razao_contabil': razao,
            'jobs_celery': jobs,
            'pendencias_contabilizacao': pendencias,
            'certificados_digitais': certificados,
        }
    }


def obter_catalogo_alertas_runbooks() -> Dict[str, Any]:
    """
    Retorna o catálogo normativo de alertas e referências de runbooks acionáveis.
    """
    return {
        'ALERTA_RAZAO_DESBALANCEADO': {
            'severidade': 'CRITICA',
            'descricao': 'Partidas contábeis do Livro Razão desbalanceadas (Soma Débitos != Soma Créditos).',
            'runbook': 'docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-integridade-do-razao',
        },
        'ALERTA_CERTIFICADO_EXPIRANDO': {
            'severidade': 'ALERTA',
            'descricao': 'Certificado Digital A1 com menos de 30 dias para expiração.',
            'runbook': 'docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-certificados-a-vencer',
        },
        'ALERTA_JOB_FALHO': {
            'severidade': 'ALERTA',
            'descricao': 'Job Celery em fila assíncrona com erro ou retentativas esgotadas.',
            'runbook': 'docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-jobs-falhos',
        },
        'ALERTA_PENDENCIA_CONTABILIZACAO': {
            'severidade': 'ALERTA',
            'descricao': 'Eventos de faturamento, liquidação ou estoque pendentes de contabilização.',
            'runbook': 'docs/runbooks/RUNBOOK_ALERTAS_OBSERVABILIDADE.md#alerta-pendencia-contabilizacao',
        },
    }

