import logging
from decimal import Decimal
from celery import shared_task
from django.utils import timezone
from django.db import models

from core.models import Tenant
from core.tenancy import tenant_context
from clientes.models import Cliente
from vendas.models import Venda, AlertaComercial

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def analisar_risco_churn_task(self, tenant_id=None):
    """
    Algoritmo Preditivo de Churn por quebra de frequência de giro de cilindros em comodato (Sprint 10).
    Executa de forma não-bloqueante via Celery Beat (madrugada).

    Lógica:
    1. Para cada cliente com comodato ativo:
    2. Calcula a diferença média de dias entre os últimos 5 pedidos de gás.
    3. Subtrai data_atual da data_ultimo_pedido.
    4. Se dias_sem_comprar > (media_historica_dias * 1.3) (atraso > 30% do padrão):
       Instancia ou atualiza um registro no model AlertaComercial(tipo='RISCO_CHURN', cliente=cliente).
    """
    hoje = timezone.now().date()
    tenants_qs = Tenant.objects.filter(ativo=True)
    if tenant_id:
        tenants_qs = tenants_qs.filter(id=tenant_id)

    total_analisados = 0
    total_criados = 0
    total_atualizados = 0

    for tenant in tenants_qs:
        with tenant_context(tenant):
            # Clientes com cilindros em comodato ativo ou contrato vigente
            clientes_comodato = Cliente.unscoped.filter(tenant=tenant).filter(
                models.Q(cilindros_em_posse__isnull=False) |
                models.Q(contratos_comodato__vigencia_fim__isnull=True) |
                models.Q(contratos_comodato__vigencia_fim__gte=hoje)
            ).distinct()

            for cliente in clientes_comodato:
                total_analisados += 1
                # Últimos 5 pedidos de gás válidos (excluindo cancelados)
                ultimas_vendas = list(
                    Venda.unscoped.filter(
                        tenant=tenant,
                        cliente=cliente
                    ).exclude(
                        status='Cancelada'
                    ).order_by('-data_venda')[:5]
                )

                if len(ultimas_vendas) < 2:
                    # Sem histórico suficiente para calcular intervalo entre compras
                    continue

                datas = [v.data_venda.date() for v in ultimas_vendas]
                diferencas = [(datas[i] - datas[i + 1]).days for i in range(len(datas) - 1)]
                diferencas_positivas = [d for d in diferencas if d > 0]

                if not diferencas_positivas:
                    # Pedidos efetuados no mesmo dia
                    continue

                media_historica_dias = Decimal(str(sum(diferencas_positivas) / len(diferencas_positivas)))
                data_ultimo_pedido = datas[0]
                dias_sem_comprar = (hoje - data_ultimo_pedido).days

                # Regra de ouro: atraso > 30% do padrão de consumo (dias_sem_comprar > media * 1.3)
                limite_churn = media_historica_dias * Decimal('1.3')

                if dias_sem_comprar > limite_churn:
                    percentual_atraso = (
                        (Decimal(str(dias_sem_comprar)) - media_historica_dias) / media_historica_dias
                    ) * Decimal('100.0')

                    descricao = (
                        f"Risco de Churn Identificado: Cliente {cliente.nome} está sem comprar há {dias_sem_comprar} dias. "
                        f"A média histórica entre pedidos é de {media_historica_dias:.1f} dias "
                        f"(atraso de {percentual_atraso:.1f}% em relação ao ciclo regular de giro de cascos)."
                    )

                    alerta_existente = AlertaComercial.unscoped.filter(
                        tenant=tenant,
                        cliente=cliente,
                        tipo='RISCO_CHURN',
                        resolvido=False
                    ).first()

                    if not alerta_existente:
                        AlertaComercial.objects.create(
                            tenant=tenant,
                            cliente=cliente,
                            tipo='RISCO_CHURN',
                            dias_sem_comprar=dias_sem_comprar,
                            media_historica_dias=round(media_historica_dias, 2),
                            percentual_atraso=round(percentual_atraso, 2),
                            descricao=descricao,
                            resolvido=False
                        )
                        total_criados += 1
                        logger.info("Alerta de Churn criado para cliente %s (tenant: %s)", cliente.nome, tenant.nome_fantasia)
                    else:
                        alerta_existente.dias_sem_comprar = dias_sem_comprar
                        alerta_existente.media_historica_dias = round(media_historica_dias, 2)
                        alerta_existente.percentual_atraso = round(percentual_atraso, 2)
                        alerta_existente.descricao = descricao
                        alerta_existente.save(update_fields=['dias_sem_comprar', 'media_historica_dias', 'percentual_atraso', 'descricao', 'atualizado_em'])
                        total_atualizados += 1

    resultado = {
        'status': 'SUCESSO',
        'clientes_analisados': total_analisados,
        'alertas_criados': total_criados,
        'alertas_atualizados': total_atualizados
    }
    logger.info("analisar_risco_churn_task concluída: %s", resultado)
    return resultado
