"""
Serviço de Régua de Cobrança e Gestão de Consentimento LGPD (Sprint 10A - Tarefa 8).
Execução diária com respeito estrito a opt-in/opt-out, janela de horário (08:00-20:00), limites e supressão de pagas.
"""
import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from financeiro.models import (
    ReguaCobranca,
    EnvioCobranca,
    ConsentimentoContato,
    ParcelaFinanceira,
)


def dentro_da_janela_comercial(dt: Optional[datetime.datetime] = None) -> bool:
    """Verifica se o horário atual está dentro da janela de comunicação legal (08:00 às 20:00)."""
    agora = dt or timezone.localtime()
    hora = agora.hour
    return 8 <= hora < 20


@transaction.atomic
def registrar_consentimento(
    *,
    tenant,
    cliente_id: int,
    canal: str,  # 'EMAIL' ou 'WHATSAPP'
    origem: str = 'CONTRATO_ADESAO'
) -> ConsentimentoContato:
    """Registra ou reativa consentimento explícito LGPD para envio de cobrança."""
    assert_tenant_writable(tenant)
    obj, created = ConsentimentoContato.objects.update_or_create(
        tenant=tenant,
        cliente_id=cliente_id,
        canal=canal,
        defaults={
            'consentiu_em': timezone.now(),
            'origem': origem,
            'revogado_em': None,
        }
    )
    return obj


@transaction.atomic
def revogar_consentimento(
    *,
    tenant,
    cliente_id: int,
    canal: str
) -> ConsentimentoContato:
    """Efetua o opt-out imediato do cliente para o canal informado."""
    assert_tenant_writable(tenant)
    obj = ConsentimentoContato.objects.filter(
        tenant=tenant,
        cliente_id=cliente_id,
        canal=canal
    ).first()
    if obj:
        obj.revogado_em = timezone.now()
        obj.save(update_fields=['revogado_em'])
    return obj


def formatar_template(template: str, parcela: ParcelaFinanceira) -> str:
    """Substitui variáveis de contexto no modelo de texto da mensagem."""
    cliente = parcela.titulo.cliente
    nome_cli = cliente.nome if cliente else "Prezado(a) Cliente"
    venc_str = parcela.data_vencimento.strftime("%d/%m/%Y")
    val_str = f"R$ {parcela.saldo_em_aberto}"
    linha_dig = parcela.linha_digitavel or "Disponível no link"
    pix_code = parcela.payload_pix or "Consulte a 2ª via"
    link_2via = parcela.url_segunda_via_boleto or "https://portal.exemplo.com.br"

    substituicoes = {
        '{cliente_nome}': nome_cli,
        '{valor}': val_str,
        '{vencimento}': venc_str,
        '{linha_digitavel}': linha_dig,
        '{pix_copia_cola}': pix_code,
        '{link_segunda_via}': link_2via,
    }

    texto = template
    for tag, val in substituicoes.items():
        texto = texto.replace(tag, str(val))
    return texto


@transaction.atomic
def executar_regua_cobranca(
    *,
    tenant,
    data_referencia: Optional[datetime.date] = None,
    ignorar_janela_horario: bool = False
) -> List[EnvioCobranca]:
    """
    Executa o lote diário da régua de cobrança para o tenant (Sprint 10A - Tarefas 8 e 10).
    Verifica etapas ativas, consentimento LGPD, supressão de parcelas pagas, limites diários e idempotência.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    hoje = data_referencia or timezone.localdate()

    # 1. Checagem de Janela de Horário Legal (08:00 - 20:00)
    if not ignorar_janela_horario and not dentro_da_janela_comercial():
        return []

    etapas = ReguaCobranca.objects.filter(tenant=tenant, ativo=True).order_by('dias_offset')
    envios_realizados = []

    # Cache de envios hoje por cliente para limitar a 2 contatos/dia
    inicio_dia = timezone.make_aware(datetime.datetime.combine(hoje, datetime.time.min))
    fim_dia = timezone.make_aware(datetime.datetime.combine(hoje, datetime.time.max))

    for etapa in etapas:
        # Data de vencimento alvo desta etapa:
        # Se dias_offset = -3 (D-3), procuramos vencimento em hoje + 3 dias.
        # Se dias_offset = +3 (D+3), procuramos vencimento em hoje - 3 dias.
        target_vencimento = hoje - datetime.timedelta(days=etapa.dias_offset)

        candidatos = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            data_vencimento=target_vencimento
        ).select_related('titulo', 'titulo__cliente')

        for parcela in candidatos:
            cliente = parcela.titulo.cliente
            if not cliente:
                continue

            idempotency_key = f"regua_{etapa.id}_parc_{parcela.id}_{hoje.isoformat()}"
            if EnvioCobranca.objects.filter(tenant=tenant, idempotency_key=idempotency_key).exists():
                continue

            # 2. Supressão se a parcela estiver PAGA ou com saldo zerado
            if parcela.status == 'PAGA' or parcela.saldo_em_aberto <= Decimal('0.00'):
                continue

            # 2.1 Supressão por Promessa de Pagamento ATIVA (Sprint 11C - Tarefa 2)
            from financeiro.models import PromessaPagamento
            if PromessaPagamento.objects.filter(
                tenant=tenant,
                cliente=cliente,
                status='ATIVA',
                data_promessa__gte=hoje,
                parcelas=parcela
            ).exists():
                continue

            # 3. Pré-condição estrita: Consentimento LGPD ativo para o canal
            consentimento_ativo = ConsentimentoContato.objects.filter(
                tenant=tenant,
                cliente=cliente,
                canal=etapa.canal,
                revogado_em__isnull=True
            ).exists()

            destinatario = cliente.email if etapa.canal == 'EMAIL' else cliente.telefone

            if not consentimento_ativo:
                envio_bloq = EnvioCobranca.objects.create(
                    tenant=tenant,
                    parcela=parcela,
                    regua=etapa,
                    canal=etapa.canal,
                    destinatario=destinatario or "N/D",
                    status='BLOQUEADO',
                    idempotency_key=idempotency_key,
                    detalhes="Bloqueado: Ausência de consentimento de contato (LGPD) ou opt-out registrado."
                )
                envios_realizados.append(envio_bloq)
                continue

            # 4. Limite de envios por dia (máximo 2 envios por cliente/dia)
            total_envios_cliente_hoje = EnvioCobranca.objects.filter(
                tenant=tenant,
                parcela__titulo__cliente=cliente,
                data_envio__range=[inicio_dia, fim_dia],
                status='SUCESSO'
            ).count()

            if total_envios_cliente_hoje >= 2:
                envio_bloq = EnvioCobranca.objects.create(
                    tenant=tenant,
                    parcela=parcela,
                    regua=etapa,
                    canal=etapa.canal,
                    destinatario=destinatario or "N/D",
                    status='BLOQUEADO',
                    idempotency_key=idempotency_key,
                    detalhes="Bloqueado: Limite máximo diário de 2 mensagens por cliente atingido."
                )
                envios_realizados.append(envio_bloq)
                continue

            # 5. Formatação do template e disparo simulado/real
            corpo_formatado = formatar_template(etapa.template_corpo, parcela)
            assunto_formatado = formatar_template(etapa.template_assunto, parcela) if etapa.canal == 'EMAIL' else ''

            envio_ok = EnvioCobranca.objects.create(
                tenant=tenant,
                parcela=parcela,
                regua=etapa,
                canal=etapa.canal,
                destinatario=destinatario or "cliente@exemplo.com",
                status='SUCESSO',
                idempotency_key=idempotency_key,
                detalhes=f"Disparado com sucesso. Assunto: {assunto_formatado} | Conteúdo: {corpo_formatado[:100]}..."
            )
            envios_realizados.append(envio_ok)

    return envios_realizados
