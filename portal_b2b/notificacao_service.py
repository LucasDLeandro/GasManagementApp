"""
Serviço de Notificações Proativas do Portal B2B (Sprint 12B).

Regras de negócio:
- Notificações ativas de:
  1. Vencimento de reteste hidrostático de cilindro (<= 30 dias ou vencido);
  2. Estadia crescente (cilindros retidos há longo tempo);
  3. Boleto / parcela a vencer (antecedência configurada de até 3 dias).
- Respeito estrito à LGPD: canais externos (EMAIL, WHATSAPP) exigem consentimento ativo
  (ConsentimentoContato com revogado_em IS NULL). Sem consentimento, o alerta é registrado
  estritamente no canal interno 'PORTAL'.
- Idempotente pela chave única (tenant, canal, chave).
"""
from datetime import timedelta
from typing import Any, Dict, List
from django.utils import timezone

from core.modulos import is_modulo_ativo
from core.tenancy import tenant_context
from produtos.models import Cilindro
from financeiro.models import ParcelaFinanceira, ConsentimentoContato
from portal_b2b.conf import reteste_alerta_dias, NOTIF_BOLETO_ANTECEDENCIA_DIAS
from portal_b2b.models import NotificacaoB2B
from portal_b2b.selectors.cilindros import get_cilindros_em_posse


def cliente_tem_consentimento_canal(tenant, cliente, canal: str) -> bool:
    """Verifica se o cliente autorizou ativamente comunicações no canal especificado."""
    return ConsentimentoContato.unscoped.filter(
        tenant=tenant,
        cliente=cliente,
        canal=canal,
        revogado_em__isnull=True
    ).exists()


def gerar_notificacoes_reteste(tenant, cliente) -> List[NotificacaoB2B]:
    """Varre cilindros em posse e gera alertas de reteste vencendo/vencido."""
    with tenant_context(tenant):
        cilindros = get_cilindros_em_posse(tenant, cliente)
        notificacoes_geradas = []

        for c in cilindros:
            if c['status_reteste'] in ('RETESTE_VENCENDO', 'RETESTE_VENCIDO'):
                chave_evento = f"reteste:{c['id']}:{c['data_proximo_reteste']}"
                titulo = f"Reteste Hidrostático: Cilindro {c['numero_serie_ogiva']}"
                if c['status_reteste'] == 'RETESTE_VENCIDO':
                    msg = f"O cilindro {c['numero_serie_ogiva']} ({c['gas']}) está com o reteste hidrostático vencido desde {c['data_proximo_reteste']}."
                else:
                    msg = f"O cilindro {c['numero_serie_ogiva']} ({c['gas']}) vencerá o reteste em {c['dias_para_reteste']} dias ({c['data_proximo_reteste']})."

                notif = _criar_notificacao_com_consentimento(
                    tenant=tenant,
                    cliente=cliente,
                    tipo='RETESTE_VENCENDO',
                    chave=chave_evento,
                    titulo=titulo,
                    mensagem=msg,
                    recurso_tipo='Cilindro',
                    recurso_id=str(c['id'])
                )
                if notif:
                    notificacoes_geradas.append(notif)

        return notificacoes_geradas


def gerar_notificacoes_boletos(tenant, cliente) -> List[NotificacaoB2B]:
    """Varre parcelas financeiras a vencer nos próximos dias e gera notificações."""
    if not is_modulo_ativo(tenant, 'financeiro'):
        return []

    with tenant_context(tenant):
        hoje = timezone.now().date()
        limite = hoje + timedelta(days=NOTIF_BOLETO_ANTECEDENCIA_DIAS)

        parcelas = ParcelaFinanceira.unscoped.filter(
            tenant=tenant,
            titulo__cliente=cliente,
            status__in=['PENDENTE', 'PAGA_PARCIAL'],
            data_vencimento__gte=hoje,
            data_vencimento__lte=limite
        ).select_related('titulo')

        notificacoes_geradas = []
        for p in parcelas:
            chave_evento = f"boleto:{p.id}:{p.data_vencimento.isoformat()}"
            titulo = f"Boleto a vencer em {p.data_vencimento.strftime('%d/%m/%Y')}"
            msg = f"A parcela {p.numero_parcela}/{p.total_parcelas} no valor de R$ {p.saldo_em_aberto} vencerá em breve."

            notif = _criar_notificacao_com_consentimento(
                tenant=tenant,
                cliente=cliente,
                tipo='BOLETO_A_VENCER',
                chave=chave_evento,
                titulo=titulo,
                mensagem=msg,
                recurso_tipo='ParcelaFinanceira',
                recurso_id=str(p.id)
            )
            if notif:
                notificacoes_geradas.append(notif)

        return notificacoes_geradas


def _criar_notificacao_com_consentimento(
    tenant,
    cliente,
    tipo: str,
    chave: str,
    titulo: str,
    mensagem: str,
    recurso_tipo: str = '',
    recurso_id: str = ''
) -> NotificacaoB2B:
    """
    Cria a notificação no canal PORTAL e, se houver consentimento LGPD ativo,
    cria também para canal externo (EMAIL).
    """
    with tenant_context(tenant):
        notif_portal, _ = NotificacaoB2B.unscoped.get_or_create(
            tenant=tenant,
            canal='PORTAL',
            chave=chave,
            defaults={
                'cliente': cliente,
                'tipo': tipo,
                'status': 'REGISTRADA',
                'titulo': titulo,
                'mensagem': mensagem,
                'recurso_tipo': recurso_tipo,
                'recurso_id': recurso_id,
            }
        )

        # Se cliente autorizou e-mail explicitamente via LGPD
        if cliente_tem_consentimento_canal(tenant, cliente, 'EMAIL'):
            destinatario = cliente.email_financeiro or ''
            if destinatario:
                NotificacaoB2B.unscoped.get_or_create(
                    tenant=tenant,
                    canal='EMAIL',
                    chave=chave,
                    defaults={
                        'cliente': cliente,
                        'tipo': tipo,
                        'status': 'ENFILEIRADA',
                        'destinatario': destinatario,
                        'titulo': titulo,
                        'mensagem': mensagem,
                        'recurso_tipo': recurso_tipo,
                        'recurso_id': recurso_id,
                    }
                )

        return notif_portal
