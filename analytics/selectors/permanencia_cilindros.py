"""
Seletor de Permanência e Retorno de Cilindros (Sprint 12C - Tarefa 3).

Reconstrói durações de permanência dos cilindros:
- Eventos completos (retornados ao distribuidor): evento = 1
- Eventos censurados (cilindros ainda retidos no cliente): evento = 0
Fornece dados estruturados para a estimativa de sobrevivência de Kaplan-Meier por cliente e por tenant.
"""
import datetime
from typing import Any, Dict, List, Optional
from django.utils import timezone

from core.tenancy import TenantAwareModel
from clientes.models import Cliente
from produtos.models import Cilindro, MovimentacaoCilindro

TIPOS_ENTREGA = ['ENTREGA_CLIENTE', 'REMESSA_COMODATO', 'ENTREGA']
TIPOS_RETORNO = ['RETIRADA_CLIENTE', 'COLETA', 'RETORNO', 'RECEBIMENTO_PORTARIA', 'RECEBIMENTO_VAZIO']


def obter_tempos_permanencia_cilindros(
    tenant,
    cliente: Optional[Cliente] = None,
    data_ref: Optional[datetime.date] = None
) -> List[Dict[str, Any]]:
    """
    Retorna a base de observações de permanência de cilindros:
    - duracao_dias: tempo de estadia (inteiro >= 0)
    - evento: 1 se retornou (evento observado), 0 se ainda está com o cliente (censura à direita)
    - cilindro_id: identificador do cilindro
    """
    hoje = data_ref or timezone.now().date()

    filtro_mov = {'tenant': tenant}
    if cliente:
        filtro_mov['cliente'] = cliente

    # Busca movimentações de entrega e retorno
    movimentacoes = MovimentacaoCilindro.unscoped.filter(
        **filtro_mov,
        tipo__in=TIPOS_ENTREGA + TIPOS_RETORNO
    ).select_related('cilindro', 'cliente').order_by('cilindro_id', 'registrado_em', 'id')

    # Agrupa por cilindro para parear entrega -> retorno
    historico_permanencias: List[Dict[str, Any]] = []
    cilindro_entregas_abertas: Dict[int, datetime.date] = {}

    for m in movimentacoes:
        dt_mov = m.registrado_em.date() if m.registrado_em else hoje
        cid = m.cilindro_id

        if m.tipo in TIPOS_ENTREGA:
            cilindro_entregas_abertas[cid] = dt_mov
        elif m.tipo in TIPOS_RETORNO:
            if cid in cilindro_entregas_abertas:
                dt_ini = cilindro_entregas_abertas.pop(cid)
                duracao = max(0, (dt_mov - dt_ini).days)
                historico_permanencias.append({
                    'cilindro_id': cid,
                    'duracao_dias': duracao,
                    'evento': 1,  # Retornou
                    'data_entrega': dt_ini,
                    'data_retorno': dt_mov
                })

    # Para cilindros que continuam atualmente em posse do cliente (dados censurados)
    filtro_cil = {'tenant': tenant, 'status': 'EM_POSSE_CLIENTE'}
    if cliente:
        filtro_cil['cliente_posse_atual'] = cliente
    else:
        filtro_cil['cliente_posse_atual__isnull'] = False

    cilindros_em_posse = Cilindro.unscoped.filter(**filtro_cil).select_related('cliente_posse_atual')

    for c in cilindros_em_posse:
        dt_inicio = None
        if c.id in cilindro_entregas_abertas:
            dt_inicio = cilindro_entregas_abertas[c.id]
        elif hasattr(c, 'posse_desde') and c.posse_desde:
            dt_inicio = c.posse_desde.date() if isinstance(c.posse_desde, datetime.datetime) else c.posse_desde
        elif hasattr(c, 'data_envio_cliente') and c.data_envio_cliente:
            dt_inicio = c.data_envio_cliente

        if dt_inicio:
            duracao_atual = max(0, (hoje - dt_inicio).days)
            historico_permanencias.append({
                'cilindro_id': c.id,
                'duracao_dias': duracao_atual,
                'evento': 0,  # Censurado (ainda retido)
                'data_entrega': dt_inicio,
                'data_retorno': None
            })

    return historico_permanencias


def obter_cilindros_em_posse_cliente(
    tenant,
    cliente: Cliente,
    data_ref: Optional[datetime.date] = None
) -> List[Dict[str, Any]]:
    """
    Lista cilindros em posse atual do cliente com dias calculados de estadia até data_ref.
    """
    hoje = data_ref or timezone.now().date()

    cilindros = Cilindro.unscoped.filter(
        tenant=tenant,
        cliente_posse_atual=cliente,
        status='EM_POSSE_CLIENTE'
    ).select_related('modelo', 'gas_dedicado')

    resultado = []
    for c in cilindros:
        # Busca última entrega
        ultima_entrega = MovimentacaoCilindro.unscoped.filter(
            tenant=tenant,
            cilindro=c,
            cliente=cliente,
            tipo__in=TIPOS_ENTREGA
        ).order_by('-registrado_em', '-id').first()

        dt_inicio = None
        if ultima_entrega and ultima_entrega.registrado_em:
            dt_inicio = ultima_entrega.registrado_em.date()
        elif hasattr(c, 'posse_desde') and c.posse_desde:
            dt_inicio = c.posse_desde.date() if isinstance(c.posse_desde, datetime.datetime) else c.posse_desde
        elif hasattr(c, 'data_envio_cliente') and c.data_envio_cliente:
            dt_inicio = c.data_envio_cliente

        dt_inicio = dt_inicio or hoje
        dias_estadia = max(0, (hoje - dt_inicio).days)

        resultado.append({
            'cilindro': c,
            'cilindro_id': c.id,
            'numero_serie_ogiva': c.numero_serie_ogiva,
            'gas': c.gas_dedicado,
            'data_entrega': dt_inicio,
            'dias_estadia': dias_estadia,
        })

    return resultado
