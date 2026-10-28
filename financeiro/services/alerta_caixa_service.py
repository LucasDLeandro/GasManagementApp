"""
Serviço Canônico de Alerta de Ruptura de Caixa e Antecipação/Postergação (Sprint 10C - Tarefa 4).
Monitora projeção no cenário realista e sugere ações de antecipação e postergação de obrigações.
"""

import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List

from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    AlertaCaixa,
    ParametroGestaoTenant,
    ParcelaFinanceira,
    PerfilPagamentoCliente,
)
from financeiro.services.projecao_caixa_service import projetar_fluxo_caixa_cenarios


@transaction.atomic
def verificar_e_gerar_alerta_caixa(tenant, horizonte_dias: Optional[int] = None) -> Dict[str, Any]:
    """
    Executa a verificação diária de caixa do Tenant no cenário realista (Tarefa 4).
    Se o saldo projetado ficar abaixo do saldo mínimo configurado dentro de N dias:
    1. Identifica parcelas candidatas à antecipação (maiores valores, melhores perfis de clientes);
    2. Identifica pagamentos postergáveis (postergavel=True) com o impacto de alívio;
    3. Registra AlertaCaixa e dispara e-mail de notificação aos gestores.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    param, _ = ParametroGestaoTenant.unscoped.get_or_create(
        tenant=tenant,
        defaults={
            'saldo_minimo_caixa': Decimal('10000.00'),
            'horizonte_alerta_dias': 30
        }
    )
    horizonte = horizonte_dias or param.horizonte_alerta_dias
    saldo_minimo = param.saldo_minimo_caixa

    projecao = projetar_fluxo_caixa_cenarios(tenant=tenant, dias=horizonte)
    res_realista = projecao['resumo_cenarios']['realista']
    menor_saldo = res_realista['menor_saldo']
    data_menor_saldo_str = res_realista['data_menor_saldo']
    data_menor_saldo = datetime.date.fromisoformat(data_menor_saldo_str)

    precisa_alerta = menor_saldo < saldo_minimo

    if not precisa_alerta:
        return {
            'alerta_gerado': False,
            'motivo': f"Saldo projetado realista mínimo (R$ {menor_saldo}) está acima do saldo mínimo de segurança (R$ {saldo_minimo}).",
            'menor_saldo_projetado': menor_saldo,
            'saldo_minimo_configurado': saldo_minimo
        }

    # 1. Candidatas à Antecipação (Títulos a Receber abertos nos próximos 60 dias)
    # Ordenadas por maior valor e menor taxa de inadimplência (melhor perfil do cliente)
    hoje = timezone.localdate()
    limite_venc = hoje + datetime.timedelta(days=60)

    perfis_dict = {
        p.cliente_id: p
        for p in PerfilPagamentoCliente.unscoped.filter(tenant=tenant)
    }

    parcelas_receber = (
        ParcelaFinanceira.unscoped
        .filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            saldo_em_aberto__gt=Decimal('0.00'),
            data_vencimento__gte=hoje,
            data_vencimento__lte=limite_venc,
            status__in=['ABERTO', 'PENDENTE', 'PARCIAL']
        )
        .select_related('titulo__cliente')
    )

    lista_antecipacao: List[Dict[str, Any]] = []
    for p in parcelas_receber:
        perfil = perfis_dict.get(p.titulo.cliente_id)
        taxa_inad = perfil.taxa_inadimplencia if perfil else Decimal('0.0500')
        atraso_m = perfil.atraso_medio_dias if perfil else Decimal('0.00')

        score_confiabilidade = Decimal('100.00') - quantize(taxa_inad * Decimal('100.00'), 2)

        lista_antecipacao.append({
            'parcela_id': p.id,
            'titulo_id': p.titulo_id,
            'cliente_id': p.titulo.cliente_id,
            'cliente_nome': p.titulo.cliente.nome if p.titulo.cliente else 'Cliente',
            'data_vencimento': p.data_vencimento.isoformat(),
            'valor_nominal': quantize(p.valor_nominal, 2),
            'saldo_em_aberto': quantize(p.saldo_em_aberto, 2),
            'taxa_inadimplencia': taxa_inad,
            'atraso_medio_dias': atraso_m,
            'score_confiabilidade': score_confiabilidade
        })

    # Ordena prioritariamente por maior saldo_em_aberto decrescente e menor taxa_inadimplencia crescente
    lista_antecipacao.sort(key=lambda x: (-x['saldo_em_aberto'], x['taxa_inadimplencia']))
    top_antecipacao = lista_antecipacao[:10]

    # 2. Pagamentos Postergáveis (Títulos a Pagar abertos com postergavel=True)
    parcelas_pagar_postergaveis = (
        ParcelaFinanceira.unscoped
        .filter(
            tenant=tenant,
            titulo__tipo='PAGAR',
            titulo__postergavel=True,
            saldo_em_aberto__gt=Decimal('0.00'),
            data_vencimento__gte=hoje,
            data_vencimento__lte=data_menor_saldo,
            status__in=['ABERTO', 'PENDENTE', 'PARCIAL']
        )
        .select_related('titulo', 'titulo__fornecedor')
    )

    lista_postergar: List[Dict[str, Any]] = []
    impacto_total_postergar = Decimal('0.00')

    for p in parcelas_pagar_postergaveis:
        val = quantize(p.saldo_em_aberto, 2)
        impacto_total_postergar = quantize(impacto_total_postergar + val, 2)
        beneficiario = p.titulo.fornecedor.nome if p.titulo.fornecedor else p.titulo.beneficiario_texto or 'Fornecedor'

        lista_postergar.append({
            'parcela_id': p.id,
            'titulo_id': p.titulo_id,
            'beneficiario': beneficiario,
            'data_vencimento': p.data_vencimento.isoformat(),
            'valor': float(val),
            'valor_saldo': float(val),
            'historico': p.titulo.historico
        })

    def _json_safe(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_json_safe(v) for v in obj]
        return obj

    detalhes = {
        'deficit_estimado': quantize(saldo_minimo - menor_saldo, 2),
        'antecipacoes_sugeridas': top_antecipacao,
        'pagamentos_postergaveis': lista_postergar,
        'impacto_alivio_postergacao': impacto_total_postergar
    }

    # 3. Cria registro do AlertaCaixa
    alerta = AlertaCaixa.unscoped.create(
        tenant=tenant,
        data_alerta=hoje,
        horizonte_dias=horizonte,
        saldo_minimo_configurado=saldo_minimo,
        menor_saldo_projetado=menor_saldo,
        data_menor_saldo=data_menor_saldo,
        detalhes_json=_json_safe(detalhes),
        resolvido=False
    )

    # 4. Disparo de e-mail ao gestor financeiro / administrador do tenant
    try:
        from core.models import Membership
        emails_gestores = list(
            Membership.objects.filter(
                tenant=tenant,
                papel__in=['ADMIN', 'DIRETOR'],
                ativo=True
            ).values_list('user__email', flat=True)
        )
        emails_validos = [e for e in emails_gestores if e and '@' in e]
        if emails_validos:
            assunto = f"[ALERTA DE CAIXA] Risco de Ruptura Projetada - {tenant.nome_fantasia}"
            corpo = (
                f"Olá,\n\n"
                f"O motor de projeção de fluxo de caixa identificou risco de quebra do saldo mínimo de segurança da empresa.\n\n"
                f"Saldo Mínimo Configurado: R$ {saldo_minimo}\n"
                f"Menor Saldo Projetado (Realista): R$ {menor_saldo} em {data_menor_saldo.strftime('%d/%m/%Y')}\n\n"
                f"Déficit Estimado: R$ {detalhes['deficit_estimado']}\n"
                f"Impacto Potencial de Postergação: R$ {impacto_total_postergar}\n\n"
                f"Acesse o painel financeiro para avaliar as parcelas sugeridas para antecipação ou postergação.\n"
            )
            send_mail(
                subject=assunto,
                message=corpo,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@baros.com.br'),
                recipient_list=emails_validos,
                fail_silently=True
            )
    except Exception:
        pass

    return {
        'alerta_gerado': True,
        'alerta_id': alerta.id,
        'menor_saldo_projetado': menor_saldo,
        'data_menor_saldo': data_menor_saldo.isoformat(),
        'saldo_minimo_configurado': saldo_minimo,
        'deficit_estimado': detalhes['deficit_estimado'],
        'antecipacoes_sugeridas': top_antecipacao,
        'pagamentos_postergaveis': lista_postergar,
        'impacto_total_postergar': impacto_total_postergar
    }
