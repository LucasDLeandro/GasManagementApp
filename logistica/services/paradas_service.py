"""
Serviço de execução de paradas no PWA de campo e recálculo dinâmico de ETA (Sprint 12A - Tarefa 4).
Controla estados A_CAMINHO, CHEGOU, ENTREGUE, FALHA (com motivo obrigatório) e alimenta odômetro.
"""
from decimal import Decimal
from typing import Optional, Dict, Any

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from logistica.models import (
    Entrega,
    ParadaEntrega,
    LeituraOdometro,
    Veiculo,
)


@transaction.atomic
def atualizar_status_parada(
    parada_id: int,
    novo_status: str,
    motivo_falha: str = '',
    odometro_km: Optional[Decimal] = None,
    usuario=None
) -> ParadaEntrega:
    """
    Atualiza o estado operacional da parada no aplicativo de campo do motorista.
    - Estados: A_CAMINHO, CHEGOU, ENTREGUE, FALHA.
    - Exige motivo obrigatório caso o status seja FALHA.
    - Se odometro_km for informado, registra leitura em LeituraOdometro e atualiza Veiculo.
    - Ao concluir uma parada (ENTREGUE ou FALHA), recalcula os ETAs das paradas subsequentes.
    """
    parada = ParadaEntrega.objects.select_related('entrega', 'entrega__veiculo', 'entrega__tenant').filter(id=parada_id).first()
    if not parada:
        raise ValidationError(f"Parada #{parada_id} não encontrada.")

    entrega = parada.entrega
    assert_tenant_writable(entrega.tenant)

    status_validos = [s[0] for s in ParadaEntrega.STATUS_CHOICES]
    if novo_status not in status_validos:
        raise ValidationError(f"Status '{novo_status}' inválido. Escolha entre: {', '.join(status_validos)}.")

    agora = timezone.now()

    if novo_status == 'FALHA':
        motivo_limpo = (motivo_falha or '').strip()
        if len(motivo_limpo) < 5:
            raise ValidationError("O motivo da falha na entrega é obrigatório e deve ter no mínimo 5 caracteres.")
        parada.motivo_falha = motivo_limpo
        parada.concluida_em = agora
    elif novo_status == 'CHEGOU':
        parada.chegada_em = agora
    elif novo_status == 'ENTREGUE':
        parada.concluida_em = agora
    elif novo_status == 'A_CAMINHO':
        if not parada.chegada_em:
            pass

    parada.status = novo_status
    parada.save()

    # Registro de Odômetro se fornecido
    if odometro_km is not None and entrega.veiculo:
        odometro_val = quantize(Decimal(str(odometro_km)), 3)
        LeituraOdometro.objects.create(
            tenant=entrega.tenant,
            veiculo=entrega.veiculo,
            km=odometro_val,
            data_hora=agora,
            origem='ROTA',
            validada=True
        )
        entrega.veiculo.odometro_atual_km = quantize(odometro_val, 2)
        entrega.veiculo.save(update_fields=['odometro_atual_km'])

    # Recálculo de ETA para paradas pendentes subsequentes
    if novo_status in ('ENTREGUE', 'FALHA'):
        recalcular_etas_subsequentes(entrega, parada_concluida=parada)

    # Se todas as paradas foram finalizadas (ENTREGUE ou FALHA), conclui a Entrega
    paradas_restantes = ParadaEntrega.objects.filter(
        entrega=entrega,
        status__in=['PENDENTE', 'A_CAMINHO', 'CHEGOU']
    ).count()

    if paradas_restantes == 0 and entrega.status == 'Em Rota':
        entrega.status = 'Concluída'
        entrega.save(update_fields=['status'])

    return parada


def recalcular_etas_subsequentes(entrega: Entrega, parada_concluida: ParadaEntrega):
    """
    Ajusta dinamicamente a previsão de chegada das próximas paradas após conclusão da parada atual.
    """
    paradas_futuras = ParadaEntrega.objects.filter(
        entrega=entrega,
        ordem__gt=parada_concluida.ordem,
        status='PENDENTE'
    ).order_by('ordem')

    hora_base = parada_concluida.concluida_em or timezone.now()
    minutos_acumulados = 0

    for pf in paradas_futuras:
        minutos_acumulados += 20  # Estimativa de trânsito + descarga
        pf.eta_estimado = hora_base + timezone.timedelta(minutes=minutos_acumulados)
        pf.save(update_fields=['eta_estimado'])
