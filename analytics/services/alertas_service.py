"""
Serviço Central de Gestão e Geração de Alertas de Oportunidade Comercial (Sprint 12C - Tarefa 4, 5 e 8).

Regras de negócio:
- Idempotência estrita por (tenant, chave_idempotencia), sendo chave_idempotencia = f"{cliente_id}:{gas_id or 'all'}:{tipo}:{data_ref}".
- Cooldown estrito de 30 dias para alertas com status DESCARTADO (não re-dispara o mesmo tipo de alerta para aquele cliente/gás).
- Integração de demanda/recompra e sobrevivência de permanência de cilindros (Kaplan-Meier).
- Transições de status atômicas com select_for_update().
- Regra de ouro (Tarefa 8): os alertas sugerem oportunidades comerciais; nunca bloqueiam venda, preço ou crédito.
"""
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from core.tenancy import tenant_context
from clientes.models import Cliente
from produtos.models import GasQuimico, Cilindro
from analytics.models import AlertaOportunidadeComercial
from analytics.selectors.recompra import (
    obter_pares_cliente_gas_ativos,
)
from analytics.selectors.permanencia_cilindros import (
    obter_tempos_permanencia_cilindros,
    obter_cilindros_em_posse_cliente,
)
from analytics.services.previsao_recompra_service import avaliar_recompra_cliente_gas
from analytics.services.kaplan_meier import avaliar_risco_nao_retorno_cilindro

DIAS_COOLDOWN_DESCARTADO = 30


def verificar_cooldown_descartado(
    tenant,
    cliente: Cliente,
    tipo: str,
    gas: Optional[GasQuimico] = None,
    data_ref: Optional[datetime.date] = None,
    dias_cooldown: int = DIAS_COOLDOWN_DESCARTADO
) -> bool:
    """
    Retorna True se existir um alerta descartado recente para (cliente, gas, tipo)
    dentro do período de cooldown (padrão: 30 dias).
    """
    hoje = data_ref or timezone.now().date()
    limite_cooldown = hoje - datetime.timedelta(days=dias_cooldown)

    filtro = {
        'tenant': tenant,
        'cliente': cliente,
        'tipo': tipo,
        'status': AlertaOportunidadeComercial.STATUS_DESCARTADO,
    }
    if gas:
        filtro['gas'] = gas
    else:
        filtro['gas__isnull'] = True

    # Verifica tanto data de resolução quanto data de criação
    alertas_descartados = AlertaOportunidadeComercial.unscoped.filter(**filtro)
    for a in alertas_descartados:
        data_evento = a.resolvido_em.date() if a.resolvido_em else a.criado_em.date()
        if data_evento >= limite_cooldown:
            return True

    return False


def gerar_alertas_demand_churn(
    tenant,
    data_ref: Optional[datetime.date] = None,
    k: float = 2.0
) -> List[AlertaOportunidadeComercial]:
    """
    Executa a varredura completa de previsão de demanda, risco de churn e
    sobrevivência de cilindros para todos os clientes do tenant.
    Idempotente por (cliente, gas, tipo, data_ref) e respeita cooldown de 30 dias.
    """
    assert_modulo(tenant, 'analytics')
    assert_tenant_writable(tenant)

    hoje = data_ref or timezone.now().date()
    alertas_gerados: List[AlertaOportunidadeComercial] = []

    with tenant_context(tenant):
        # 1. AVALIAÇÃO DE RECOMPRA E CHURN POR CLIENTE E GÁS
        pares_cliente_gas = obter_pares_cliente_gas_ativos(tenant)

        for cliente, gas in pares_cliente_gas:
            alerta_info = avaliar_recompra_cliente_gas(
                cliente=cliente,
                gas=gas,
                data_ref=hoje,
                k=k,
                tenant=tenant
            )

            if not alerta_info:
                continue

            tipo_alerta = alerta_info['tipo']

            # Verifica cooldown de 30 dias para alertas descartados
            if verificar_cooldown_descartado(tenant, cliente, tipo_alerta, gas=gas, data_ref=hoje):
                continue

            chave_idempotencia = f"{cliente.id}:{gas.id}:{tipo_alerta}:{hoje.isoformat()}"

            with transaction.atomic():
                alerta, _ = AlertaOportunidadeComercial.objects.update_or_create(
                    tenant=tenant,
                    chave_idempotencia=chave_idempotencia,
                    defaults={
                        'cliente': cliente,
                        'gas': gas,
                        'tipo': tipo_alerta,
                        'score': alerta_info['score'],
                        'evidencia_json': alerta_info['evidencia_json'],
                        'data_ref': hoje,
                        'status': AlertaOportunidadeComercial.STATUS_NOVO,
                    }
                )
                alertas_gerados.append(alerta)

        # 2. AVALIAÇÃO DE SOBREVIVÊNCIA DE CILINDROS (KAPLAN-MEIER)
        observacoes_tenant = obter_tempos_permanencia_cilindros(tenant=tenant, cliente=None, data_ref=hoje)
        clientes_com_posse = Cliente.unscoped.filter(
            tenant=tenant,
            cilindros_em_posse__isnull=False
        ).distinct()

        for cliente in clientes_com_posse:
            cilindros_posse = obter_cilindros_em_posse_cliente(tenant=tenant, cliente=cliente, data_ref=hoje)
            if not cilindros_posse:
                continue

            observacoes_cliente = obter_tempos_permanencia_cilindros(tenant=tenant, cliente=cliente, data_ref=hoje)

            # Analisa o cilindro com a maior retenção atual
            cilindro_max = max(cilindros_posse, key=lambda x: x['dias_estadia'])
            duracao_max = cilindro_max['dias_estadia']
            gas_cilindro = cilindro_max['gas']

            resultado_km = avaliar_risco_nao_retorno_cilindro(
                duracao_atual_dias=duracao_max,
                observacoes_cliente=observacoes_cliente,
                observacoes_tenant=observacoes_tenant,
                prazo_esperado_dias=30
            )

            if resultado_km['gerar_alerta']:
                tipo_km = AlertaOportunidadeComercial.TIPO_CILINDRO_NAO_RETORNA
                gas_id_str = gas_cilindro.id if gas_cilindro else 'all'

                if not verificar_cooldown_descartado(tenant, cliente, tipo_km, gas=gas_cilindro, data_ref=hoje):
                    chave_idemp = f"{cliente.id}:{gas_id_str}:{tipo_km}:{hoje.isoformat()}"

                    evidencia_km = {
                        'cliente_id': cliente.id,
                        'cliente_nome': cliente.nome,
                        'cilindro_id': cilindro_max['cilindro_id'],
                        'cilindro_numero_serie': cilindro_max['numero_serie_ogiva'],
                        'gas_id': gas_cilindro.id if gas_cilindro else None,
                        'gas_nome': gas_cilindro.nome if gas_cilindro else 'Multigás',
                        'data_referencia': hoje.isoformat(),
                        'dias_estadia_atual': duracao_max,
                        'prazo_esperado_dias': resultado_km['prazo_esperado_dias'],
                        'probabilidade_permanencia_pct': resultado_km['probabilidade_permanencia_pct'],
                        'mediana_retorno_dias': resultado_km['mediana_tempo_retorno_dias'],
                        'usou_fallback_tenant': resultado_km['usou_fallback_tenant'],
                        'total_cilindros_em_posse': len(cilindros_posse),
                        'score_risco': resultado_km['score_risco'],
                        'explicacao': resultado_km['explicacao'],
                        'tabela_resumo_km': resultado_km['tabela_resumo'],
                    }

                    score_dec = quantize(Decimal(str(resultado_km['score_risco'])), 4)

                    with transaction.atomic():
                        alerta_cil, _ = AlertaOportunidadeComercial.objects.update_or_create(
                            tenant=tenant,
                            chave_idempotencia=chave_idemp,
                            defaults={
                                'cliente': cliente,
                                'gas': gas_cilindro,
                                'tipo': tipo_km,
                                'score': score_dec,
                                'evidencia_json': evidencia_km,
                                'data_ref': hoje,
                                'status': AlertaOportunidadeComercial.STATUS_NOVO,
                            }
                        )
                        alertas_gerados.append(alerta_cil)

    return alertas_gerados


def atualizar_status_alerta(
    alerta_id: int,
    novo_status: str,
    responsavel=None,
    feedback: str = '',
    tenant=None
) -> AlertaOportunidadeComercial:
    """
    Atualiza atomicamente o status de um alerta com select_for_update().
    Permite transição para: NOVO, EM_CONTATO, CONVERTIDO, DESCARTADO.
    """
    if novo_status not in dict(AlertaOportunidadeComercial.STATUS_CHOICES):
        raise ValidationError(f"Status '{novo_status}' inválido para AlertaOportunidadeComercial.")

    with transaction.atomic():
        qs = AlertaOportunidadeComercial.unscoped.select_for_update()
        if tenant:
            qs = qs.filter(tenant=tenant)
        alerta = qs.filter(id=alerta_id).first()

        if not alerta:
            raise ValidationError(f"Alerta {alerta_id} não encontrado.")

        if tenant:
            assert_tenant_writable(tenant)

        alerta.status = novo_status
        if responsavel:
            alerta.responsavel = responsavel
        if feedback:
            alerta.feedback = feedback

        if novo_status in (AlertaOportunidadeComercial.STATUS_CONVERTIDO, AlertaOportunidadeComercial.STATUS_DESCARTADO):
            alerta.resolvido_em = timezone.now()
        else:
            alerta.resolvido_em = None

        alerta.save(update_fields=['status', 'responsavel', 'feedback', 'resolvido_em'])
        return alerta
