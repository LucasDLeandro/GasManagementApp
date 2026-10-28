"""
Seletor de Dados Financeiros do Portal B2B (Sprint 12B).

Regras de negócio:
- Exige módulo 'financeiro' ativo no plano do Tenant; se inativo, lança ModuloInativoError.
- Usuários com papel FINANCEIRO sem MFA validada são bloqueados na camada de permissão.
- Retorna parcelas a receber (abertas e liquidadas), 2ª via de boleto/PIX e faturas de estadia.
"""
from decimal import Decimal
from typing import Any, Dict, List
from django.db import models
from django.utils import timezone

from core.guards import assert_modulo
from financeiro.models import ParcelaFinanceira, TituloFinanceiro
from clientes.models import FechamentoFaturaEstadia


def get_parcelas_cliente(tenant, cliente) -> Dict[str, Any]:
    """
    Retorna parcelas financeiras abertas e quitadas do cliente, com suporte a 2ª via e PIX.
    """
    assert_modulo(tenant, 'financeiro')
    hoje = timezone.now().date()

    parcelas_qs = ParcelaFinanceira.unscoped.filter(
        tenant=tenant,
        titulo__cliente=cliente
    ).select_related('titulo').order_by('data_vencimento')

    abertas = []
    pagas = []
    total_aberto = Decimal('0.00')

    for p in parcelas_qs:
        esta_vencida = bool(p.status in ('PENDENTE', 'PAGA_PARCIAL') and p.data_vencimento < hoje)
        item = {
            'id': p.id,
            'titulo_id': p.titulo_id,
            'numero_documento': p.titulo.numero_documento if p.titulo else '',
            'numero_parcela': f"{p.numero_parcela}/{p.total_parcelas}",
            'data_vencimento': p.data_vencimento.isoformat(),
            'valor_nominal': str(p.valor_nominal),
            'saldo_em_aberto': str(p.saldo_em_aberto),
            'status': p.status,
            'esta_vencida': esta_vencida,
            'linha_digitavel': p.linha_digitavel or '',
            'codigo_barras': p.codigo_barras or '',
            'tem_pix': bool(p.payload_pix),
            'payload_pix': p.payload_pix or '',
            'tem_boleto_2via': bool(p.url_segunda_via_boleto or p.linha_digitavel),
            'url_boleto_2via': p.url_segunda_via_boleto or '',
        }
        if p.status == 'LIQUIDADA':
            pagas.append(item)
        else:
            abertas.append(item)
            total_aberto += p.saldo_em_aberto

    return {
        'abertas': abertas,
        'pagas': pagas,
        'total_aberto': str(total_aberto),
        'quantidade_abertas': len(abertas),
    }


def get_faturas_estadia_cliente(tenant, cliente) -> List[Dict[str, Any]]:
    """
    Retorna as faturas de cobrança de estadia/locação do cliente (FechamentoFaturaEstadia).
    """
    assert_modulo(tenant, 'financeiro')

    faturas = FechamentoFaturaEstadia.unscoped.filter(
        tenant=tenant,
        cliente=cliente
    ).order_by('-periodo_fim')

    return [
        {
            'id': f.id,
            'periodo_inicio': f.periodo_inicio.isoformat() if f.periodo_inicio else None,
            'periodo_fim': f.periodo_fim.isoformat() if f.periodo_fim else None,
            'valor_total': str(f.valor_total),
            'status': getattr(f, 'status', 'GERADA'),
            'criado_em': f.criado_em.isoformat() if hasattr(f, 'criado_em') and f.criado_em else None,
        }
        for f in faturas
    ]
