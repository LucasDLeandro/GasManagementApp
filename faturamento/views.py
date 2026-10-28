import json
import logging
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from core.mixins import TenantViewSetMixin
from core.permissions import RequiresModuleFiscal, RequiresModuleFinanceiro
from faturamento.models import ConfiguracaoFiscalTenant, NotaFiscal, FaturaCobranca
from faturamento.serializers import (
    ConfiguracaoFiscalTenantSerializer,
    NotaFiscalSerializer,
    FaturaCobrancaSerializer,
)
from faturamento.services import validar_assinatura_webhook
from faturamento.tasks import emitir_nfe_task
from vendas.models import Venda

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class WebhookGatewayPagamentoView(APIView):
    """
    Webhook para receber notificações de pagamentos assíncronos (PIX, Boleto, Cartão).
    Exige autenticação HMAC-SHA256 via cabeçalho 'X-Signature' ou 'X-Hub-Signature'.
    Fail-Closed: Qualquer divergência de hash rejeita imediatamente com HTTP 403.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        sig_header = (
            request.headers.get('X-Signature') or
            request.headers.get('X-Hub-Signature') or
            request.META.get('HTTP_X_SIGNATURE') or
            request.META.get('HTTP_X_HUB_SIGNATURE')
        )
        secret = getattr(settings, 'GATEWAY_WEBHOOK_SECRET', '')

        if not validar_assinatura_webhook(request.body, sig_header, secret):
            logger.warning("[WebhookGatewayPagamentoView] Assinatura HMAC inválida ou ausente.")
            return Response(
                {"erro": "Acesso negado: Assinatura HMAC inválida ou ausente."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            payload = request.data

        gateway_id = payload.get('gateway_id') or payload.get('id')
        evento = payload.get('evento') or payload.get('event')
        status_cobranca = str(payload.get('status', '')).upper()

        logger.info(f"[WebhookGatewayPagamentoView] Evento {evento} recebido para Gateway ID {gateway_id}.")

        # Busca a cobrança de forma unscoped (pois o webhook não possui contexto de tenant na sessão)
        fatura = None
        if gateway_id:
            fatura = FaturaCobranca.unscoped.filter(gateway_id=gateway_id).first()
        if not fatura and payload.get('uuid'):
            fatura = FaturaCobranca.unscoped.filter(uuid=payload.get('uuid')).first()

        if not fatura:
            logger.warning(f"[WebhookGatewayPagamentoView] Fatura não localizada para gateway_id={gateway_id}")
            return Response(
                {"aviso": "Fatura de cobrança não encontrada.", "gateway_id": gateway_id},
                status=status.HTTP_404_NOT_FOUND
            )

        # Atualiza status da cobrança
        if status_cobranca in ['PAGA', 'PAID', 'LIQUIDADA', 'CONFIRMED'] or evento in ['payment.succeeded', 'invoice.paid']:
            fatura.status = 'PAGA'
            fatura.data_pagamento = timezone.now()
            fatura.save(update_fields=['status', 'data_pagamento', 'atualizado_em'])

            # Se vinculada a uma venda a prazo/pendente, atualiza status se aplicável
            if fatura.venda and fatura.venda.status == 'Pendente':
                fatura.venda.status = 'Em Separação'
                fatura.venda.save(update_fields=['status', 'data_atualizacao'])

        elif status_cobranca in ['VENCIDA', 'EXPIRED']:
            fatura.status = 'VENCIDA'
            fatura.save(update_fields=['status', 'atualizado_em'])
        elif status_cobranca in ['CANCELADA', 'CANCELED']:
            fatura.status = 'CANCELADA'
            fatura.save(update_fields=['status', 'atualizado_em'])

        return Response(
            {
                "sucesso": True,
                "fatura_uuid": str(fatura.uuid),
                "status": fatura.status
            },
            status=status.HTTP_200_OK
        )


@method_decorator(csrf_exempt, name='dispatch')
class WebhookNFeView(APIView):
    """
    Webhook para callbacks da API fiscal (Focus NFe / SEFAZ).
    Exige autenticação HMAC-SHA256 via cabeçalho 'X-Signature' ou 'X-Hub-Signature'.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        sig_header = (
            request.headers.get('X-Signature') or
            request.headers.get('X-Hub-Signature') or
            request.META.get('HTTP_X_SIGNATURE') or
            request.META.get('HTTP_X_HUB_SIGNATURE')
        )
        secret = getattr(settings, 'NFE_WEBHOOK_SECRET', '')

        if not validar_assinatura_webhook(request.body, sig_header, secret):
            logger.warning("[WebhookNFeView] Assinatura HMAC inválida ou ausente.")
            return Response(
                {"erro": "Acesso negado: Assinatura HMAC inválida ou ausente."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            payload = request.data

        chave_nfe = payload.get('chave_nfe') or payload.get('chave_acesso')
        status_sefaz = str(payload.get('status', '')).lower()

        logger.info(f"[WebhookNFeView] Callback SEFAZ recebido para chave {chave_nfe}: status={status_sefaz}")

        nota = None
        if chave_nfe:
            nota = NotaFiscal.unscoped.filter(chave_acesso=chave_nfe).first()
        if not nota and payload.get('uuid'):
            nota = NotaFiscal.unscoped.filter(uuid=payload.get('uuid')).first()

        if not nota:
            return Response(
                {"aviso": "NotaFiscal não encontrada.", "chave_nfe": chave_nfe},
                status=status.HTTP_404_NOT_FOUND
            )

        if status_sefaz in ['autorizado', 'autorizada']:
            nota.status = 'AUTORIZADA'
            nota.xml_url = payload.get('caminho_xml_nota_fiscal') or nota.xml_url
            nota.danfe_url = payload.get('caminho_danfe') or nota.danfe_url
            nota.data_emissao = timezone.now()
            nota.motivo_rejeicao = None
            nota.save(update_fields=['status', 'xml_url', 'danfe_url', 'data_emissao', 'motivo_rejeicao', 'atualizado_em'])
        elif status_sefaz in ['cancelado', 'cancelada']:
            nota.status = 'CANCELADA'
            nota.save(update_fields=['status', 'atualizado_em'])
        else:
            nota.status = 'REJEITADA'
            nota.motivo_rejeicao = str(payload.get('mensagem_sefaz') or payload.get('erros') or status_sefaz)
            nota.save(update_fields=['status', 'motivo_rejeicao', 'atualizado_em'])

        return Response(
            {
                "sucesso": True,
                "nfe_uuid": str(nota.uuid),
                "status": nota.status
            },
            status=status.HTTP_200_OK
        )


class FaturaCobrancaPublicaView(APIView):
    """
    Consulta e checkout público de cobrança via UUIDv4 (Fail-Closed).
    Não expõe dados de outros tenants nem utiliza ID numérico sequencial.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, fatura_uuid, *args, **kwargs):
        fatura = FaturaCobranca.unscoped.filter(uuid=fatura_uuid).select_related('venda__cliente', 'estadia__cliente', 'tenant').first()
        if not fatura:
            return Response({"erro": "Cobrança não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        cliente_nome = "Cliente"
        if fatura.venda and fatura.venda.cliente:
            cliente_nome = fatura.venda.cliente.nome
        elif fatura.estadia and fatura.estadia.cliente:
            cliente_nome = fatura.estadia.cliente.nome

        return Response({
            "uuid": str(fatura.uuid),
            "status": fatura.status,
            "valor": str(fatura.valor),
            "cliente": cliente_nome,
            "data_vencimento": str(fatura.data_vencimento),
            "qr_code_pix": fatura.qr_code_pix,
            "linha_digitavel": fatura.linha_digitavel,
            "link_pagamento": fatura.link_pagamento,
            "emissor": fatura.tenant.nome_fantasia,
        })


class SolicitarEmissaoNFeAPIView(TenantViewSetMixin, APIView):
    """
    Dispara assincronamente a task Celery emitir_nfe_task para uma Venda ou Fatura de Estadia.
    """
    permission_classes = [permissions.IsAuthenticated, RequiresModuleFiscal]

    def post(self, request, *args, **kwargs):
        entidade_id = request.data.get('entidade_id')
        tipo_entidade = request.data.get('tipo_entidade', 'VENDA').upper()

        if not entidade_id:
            return Response(
                {"erro": "Campo 'entidade_id' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if tipo_entidade not in ['VENDA', 'ESTADIA']:
            return Response(
                {"erro": "Tipo de entidade deve ser 'VENDA' ou 'ESTADIA'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response({"erro": "Tenant não configurado na requisição."}, status=status.HTTP_400_BAD_REQUEST)

        # Enfileira na fila assíncrona Celery
        task = emitir_nfe_task.delay(str(tenant.id), entidade_id, tipo_entidade)

        return Response(
            {
                "sucesso": True,
                "mensagem": "Emissão de NF-e enfileirada no Celery com sucesso.",
                "task_id": task.id,
                "tipo_entidade": tipo_entidade,
                "entidade_id": entidade_id
            },
            status=status.HTTP_202_ACCEPTED
        )


class NotaFiscalViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Listagem e detalhes de NF-e com isolamento estrito por Tenant.
    """
    serializer_class = NotaFiscalSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return NotaFiscal.objects.none()
        return NotaFiscal.unscoped.filter(tenant=tenant).select_related('venda__cliente', 'fatura_estadia__cliente')


class FaturaCobrancaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Gerenciamento de títulos de cobrança financeira por Tenant.
    """
    serializer_class = FaturaCobrancaSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleFinanceiro]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return FaturaCobranca.objects.none()
        return FaturaCobranca.unscoped.filter(tenant=tenant).select_related('venda', 'estadia')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class ConfiguracaoFiscalTenantViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Configuração fiscal e certificado A1 por Tenant.
    """
    serializer_class = ConfiguracaoFiscalTenantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ConfiguracaoFiscalTenant.objects.none()
        return ConfiguracaoFiscalTenant.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)
