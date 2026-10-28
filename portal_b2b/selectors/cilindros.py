"""
Seletor de Cilindros em Posse e Histórico de Comodato (Sprint 12B).

Regras de negócio:
- Retorna apenas cilindros com posse física atual pelo cliente final (cliente_posse_atual).
- Calcula os dias de estadia com base na data da última movimentação de entrega/remessa.
- Sinaliza alerta de vencimento de reteste hidrostático:
  * <= 0 dias: RETESTE_VENCIDO
  * <= 30 dias (reteste_alerta_dias): RETESTE_VENCENDO
  * > 30 dias: EM_DIA
- Integração com MovimentoComodatoFiscal (se módulo fiscal ativo).
"""
from datetime import date
from typing import Any, Dict, List, Optional
from django.utils import timezone

from core.modulos import is_modulo_ativo
from produtos.models import Cilindro, MovimentacaoCilindro
from portal_b2b.conf import reteste_alerta_dias


def get_cilindros_em_posse(tenant, cliente) -> List[Dict[str, Any]]:
    """
    Lista todos os cilindros em posse física do cliente com status de reteste e dias de estadia.
    """
    hoje = timezone.now().date()
    alerta_dias = reteste_alerta_dias()

    cilindros = Cilindro.unscoped.filter(
        tenant=tenant,
        cliente_posse_atual=cliente
    ).select_related('modelo', 'gas_dedicado', 'envase_atual__lote').order_by('codigo_qr')

    resultado = []
    for c in cilindros:
        # 1. Dias para vencimento do reteste
        dias_reteste: Optional[int] = None
        status_reteste = 'SEM_DATA'
        if c.data_proximo_reteste:
            dias_reteste = (c.data_proximo_reteste - hoje).days
            if dias_reteste < 0:
                status_reteste = 'RETESTE_VENCIDO'
            elif dias_reteste <= alerta_dias:
                status_reteste = 'RETESTE_VENCENDO'
            else:
                status_reteste = 'EM_DIA'

        # 2. Dias de estadia (busca movimentação de entrega mais recente para este cliente)
        mov_entrega = MovimentacaoCilindro.unscoped.filter(
            tenant=tenant,
            cilindro=c,
            cliente=cliente,
            tipo__in=['ENTREGA_CLIENTE', 'REMESSA_COMODATO', 'ENTREGA']
        ).order_by('-registrado_em', '-id').first()

        dias_estadia = 0
        data_entrega = None
        if mov_entrega:
            data_entrega = mov_entrega.registrado_em.date()
            dias_estadia = max(0, (hoje - data_entrega).days)
        elif hasattr(c, 'data_envio_cliente') and c.data_envio_cliente:
            dias_estadia = max(0, (hoje - c.data_envio_cliente).days)
            data_entrega = c.data_envio_cliente

        resultado.append({
            'id': c.id,
            'codigo_qr': c.codigo_qr,
            'numero_serie_ogiva': c.numero_serie_ogiva,
            'gas': c.gas_dedicado.nome if c.gas_dedicado else '',
            'gas_sigla': c.gas_dedicado.sigla if c.gas_dedicado else '',
            'modelo': getattr(c.modelo, 'descricao', getattr(c.modelo, 'nome', '')) if c.modelo else '',
            'volume_litros': str(getattr(c.modelo, 'volume_hidraulico_litros', getattr(c.modelo, 'volume_litros', ''))) if c.modelo else '',
            'data_proximo_reteste': c.data_proximo_reteste.isoformat() if c.data_proximo_reteste else None,
            'dias_para_reteste': dias_reteste,
            'status_reteste': status_reteste,
            'dias_estadia': dias_estadia,
            'data_entrega': data_entrega.isoformat() if data_entrega else None,
            'lote_atual': c.envase_atual.lote.codigo_lote if (c.envase_atual and c.envase_atual.lote) else None,
            'tem_laudo_disponivel': bool(c.envase_atual and c.envase_atual.lote),
        })

    return resultado


def get_historico_comodato_fiscal(tenant, cliente) -> List[Dict[str, Any]]:
    """
    Lista o histórico de comodato fiscal (se o módulo fiscal estiver ativo no tenant).
    """
    if not is_modulo_ativo(tenant, 'fiscal'):
        return []

    try:
        from fiscal.models import MovimentoComodatoFiscal
        movs = MovimentoComodatoFiscal.unscoped.filter(
            tenant=tenant,
            cliente=cliente
        ).select_related('cilindro', 'documento_fiscal').order_by('-data_movimento')

        return [
            {
                'id': m.id,
                'cilindro_codigo': m.cilindro.codigo_qr,
                'cilindro_serie': m.cilindro.numero_serie_ogiva,
                'tipo': m.tipo,
                'tipo_display': m.get_tipo_display() if hasattr(m, 'get_tipo_display') else m.tipo,
                'data_movimento': m.data_movimento.isoformat() if m.data_movimento else None,
                'nfe_chave': m.documento_fiscal.chave_acesso if m.documento_fiscal else None,
                'nfe_numero': m.documento_fiscal.numero if m.documento_fiscal else None,
            }
            for m in movs
        ]
    except Exception:
        return []
