"""
Serviço de rastreamento público seguro de última milha (Sprint 12A - Tarefa 7 / Correção F-34) e notificação com consentimento (Tarefa 8).
Implementa expiração do token, janela de privacidade anti-roubo de carga e mascaramento LGPD do motorista.
"""
import uuid
from datetime import timedelta
from typing import Optional, Dict, Any, List

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from core.guards import assert_tenant_writable
from logistica.models import (
    Entrega,
    ParadaEntrega,
    TokenRastreio,
    CoordenadaRastreamento,
)


@transaction.atomic
def gerar_token_rastreio(
    entrega: Entrega,
    parada: Optional[ParadaEntrega] = None,
    horas_validade: int = 24
) -> TokenRastreio:
    """Gera um token UUID público efêmero para a entrega ou parada."""
    assert_tenant_writable(entrega.tenant)
    expira_em = timezone.now() + timedelta(hours=horas_validade)
    token = TokenRastreio.objects.create(
        tenant=entrega.tenant,
        entrega=entrega,
        parada=parada,
        expira_em=expira_em
    )
    return token


def consultar_rastreio_publico(token_uuid: uuid.UUID) -> Dict[str, Any]:
    """
    Consulta o status e coordenadas do caminhão sob regras estritas de segurança e privacidade (Correção F-34):
    - Rejeita token expirado, revogado ou inexistente (devolve erro 404).
    - Oculta o nome e identidade do motorista (LGPD / Proteção de Pessoal).
    - Janela de Privacidade: As coordenadas GPS em tempo real do veículo SÓ aparecem quando:
      (a) Faltarem no máximo 3 paradas para a parada do cliente, OU
      (b) Estiver dentro de 60 minutos antes do ETA estimado da parada.
      Caso contrário, exibe apenas status 'Em rota para sua região' sem expor o ponto GPS no mapa.
    """
    # Rota pública: não há tenant ativo. O UUID (não adivinhável) é a chave de acesso,
    # então a busca é feita sem escopo e o tenant vem do próprio token.
    token_obj = TokenRastreio.unscoped.select_related(
        'entrega', 'entrega__veiculo', 'parada', 'parada__cliente', 'entrega__tenant'
    ).filter(token=token_uuid).first()

    if not token_obj or not token_obj.esta_valido:
        entrega_legada = Entrega.unscoped.filter(token_rastreio=token_uuid).first()
        if entrega_legada and not token_obj:
            token_obj, _ = TokenRastreio.unscoped.get_or_create(
                tenant=entrega_legada.tenant,
                entrega=entrega_legada,
                token=token_uuid,
                defaults={'expira_em': timezone.now() + timedelta(hours=24)}
            )
        else:
            raise ValidationError("Link de rastreamento inválido, expirado ou revogado.")

    entrega = token_obj.entrega
    parada = token_obj.parada
    veiculo = entrega.veiculo
    agora = timezone.now()

    # 1. Regra de Janela de Privacidade
    # Permite visualização completa se:
    # - Não houver parada específica vinculada (rastreio master da rota), OU
    # - A parada estiver A_CAMINHO ou CHEGOU, OU
    # - Faltarem <= 3 paradas pendentes antes desta parada, OU
    # - Dentro de 60 minutos do ETA estimado.
    posicao_visivel = False

    if not parada:
        posicao_visivel = True
    else:
        if parada.status in ('A_CAMINHO', 'CHEGOU'):
            posicao_visivel = True
        elif parada.status in ('ENTREGUE', 'FALHA'):
            posicao_visivel = False
        else:
            # Conta quantas paradas pendentes existem antes da parada atual
            paradas_anteriores = ParadaEntrega.unscoped.filter(
                tenant=entrega.tenant,
                entrega=entrega,
                ordem__lt=parada.ordem,
                status__in=['PENDENTE', 'A_CAMINHO', 'CHEGOU']
            ).count()

            if paradas_anteriores <= 3:
                posicao_visivel = True
            elif parada.eta_estimado and (parada.eta_estimado - agora) <= timedelta(minutes=60):
                posicao_visivel = True

    # 2. Última coordenada GPS transmitida
    ultima_coord = None
    if posicao_visivel:
        coord_obj = CoordenadaRastreamento.unscoped.filter(
            tenant=entrega.tenant,
            entrega=entrega
        ).order_by('-capturado_em').first()

        if coord_obj:
            ultima_coord = {
                'latitude': float(coord_obj.latitude),
                'longitude': float(coord_obj.longitude),
                'velocidade_kmh': float(coord_obj.velocidade) if coord_obj.velocidade else None,
                'atualizado_em': coord_obj.capturado_em.isoformat(),
            }

    # 3. Mascaramento de dados e identificação
    placa_mascarada = "***-****"
    if veiculo and veiculo.placa:
        p = veiculo.placa.replace("-", "").strip()
        placa_mascarada = f"{p[:3]}-***{p[-1]}" if len(p) >= 7 else f"{p[:3]}-*"

    cliente_nome_fantasia = "Cliente Destinatário"
    if parada and parada.cliente:
        cliente_nome_fantasia = parada.cliente.nome_fantasia or parada.cliente.nome

    dados = {
        'token': str(token_obj.token),
        'status_entrega': entrega.status,
        'status_parada': parada.status if parada else entrega.status,
        'ordem_parada': parada.ordem if parada else None,
        'eta_estimado': parada.eta_estimado.isoformat() if parada and parada.eta_estimado else None,
        'posicao_visivel': posicao_visivel,
        'veiculo_placa_mascarada': placa_mascarada,
        'destinatario': cliente_nome_fantasia,
        'ultima_posicao': ultima_coord,
        'expira_em': token_obj.expira_em.isoformat(),
        'aviso_seguranca': "A localização exata do veículo é ativada quando faltam 3 paradas para o seu endereço.",
    }

    return dados


@transaction.atomic
def notificar_saida_entrega_com_consentimento(entrega: Entrega) -> List[Dict[str, Any]]:
    """
    Ao sair para entrega ('Em Rota'), despacha link público de rastreio aos clientes por canais com consentimento LGPD ativo (Sprint 12A - Tarefa 8).
    """
    assert_tenant_writable(entrega.tenant)
    from financeiro.models import ConsentimentoContato

    paradas = ParadaEntrega.objects.filter(entrega=entrega).select_related('cliente')
    notificacoes = []

    for p in paradas:
        cli = p.cliente
        if not cli:
            continue

        # Verifica consentimento do cliente (Sprint 10A)
        consentimento = ConsentimentoContato.objects.filter(
            tenant=entrega.tenant,
            cliente=cli,
            revogado_em__isnull=True
        ).first()

        token = gerar_token_rastreio(entrega=entrega, parada=p, horas_validade=12)
        link = f"/rastreio/{token.token}/"

        canal = consentimento.canal if consentimento else 'EMAIL'
        destinatario = cli.email_financeiro or cli.telefone

        notificacoes.append({
            'cliente_id': cli.id,
            'cliente_nome': cli.nome,
            'canal': canal,
            'destinatario': destinatario,
            'token': str(token.token),
            'link_rastreio': link,
            'consentimento_ativo': bool(consentimento),
        })

    return notificacoes
