from django.http import JsonResponse, Http404
from django.views import View
from django.shortcuts import render
from django.utils import timezone
from django.core.cache import cache
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import PainelMonitor
from core.mixins import TenantViewSetMixin
from core.permissions import IsTenantAdminOrGerente
from core.serializers import PainelMonitorSerializer
from core.services.painel_monitor import (
    montar_dados_painel,
    regenerar_token_painel,
    revogar_painel,
    gerar_token_painel,
)


class PainelMonitorView(View):
    """
    Interface pública HTML do Monitor de TV (/painel/<str:token>/).
    Sem autenticação por sessão (token público resolve o tenant).
    """
    def get(self, request, token):
        painel = PainelMonitor.unscoped.select_related('tenant', 'filial').filter(
            token=token,
            ativo=True
        ).first()

        if not painel:
            raise Http404("Painel não encontrado ou inativo.")

        response = render(request, 'core/painel_monitor.html', {
            'painel': painel,
            'token': token,
        })
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response


class PainelMonitorDadosAPIView(View):
    """
    API pública JSON para atualização periódica do monitor (/painel/<str:token>/dados/).
    - Sem autenticação de sessão ou DRF
    - Rate limit (throttle) de 12 requisições por minuto por token
    - Atualização de ultimo_acesso_em com intervalo mínimo de 60 segundos
    - Header X-Robots-Tag: noindex, nofollow
    """
    def get(self, request, token):
        # 1. Rate Limiting por token (12 req/min)
        rl_key = f"rl_monitor_{token}"
        chamadas = cache.get(rl_key, 0)
        if chamadas >= 12:
            resp_429 = JsonResponse(
                {"erro": "Limite de requisições excedido (máximo 12 por minuto)."},
                status=429
            )
            resp_429['X-Robots-Tag'] = 'noindex, nofollow'
            return resp_429

        cache.set(rl_key, chamadas + 1, timeout=60)

        # 2. Resolução do painel (fail-closed, 404 para inexistente ou inativo - ANTES do cache)
        painel = PainelMonitor.unscoped.select_related('tenant', 'filial').filter(
            token=token,
            ativo=True
        ).first()

        if not painel:
            resp_404 = JsonResponse({"erro": "Painel não encontrado ou inativo."}, status=404)
            resp_404['X-Robots-Tag'] = 'noindex, nofollow'
            return resp_404

        # 3. Resposta rápida via cache por painel validado
        cache_key = f"cache_monitor_dados_{token}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            response = JsonResponse(cached_data)
            response['X-Robots-Tag'] = 'noindex, nofollow'
            return response

        # 4. Atualização throttled de ultimo_acesso_em (no máximo 1x a cada 60s)
        agora = timezone.now()
        if not painel.ultimo_acesso_em or (agora - painel.ultimo_acesso_em).total_seconds() >= 60:
            PainelMonitor.unscoped.filter(pk=painel.pk).update(ultimo_acesso_em=agora)
            painel.ultimo_acesso_em = agora

        # 5. Dados operacionais sem dados sensíveis
        dados = montar_dados_painel(painel)

        response = JsonResponse(dados)
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response


class PainelMonitorViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Endpoint administrativo em Configurações para gestão dos monitores (/inicio/api/paineis/).
    Acesso restrito a ADMIN e GERENTE do tenant.
    """
    serializer_class = PainelMonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrGerente]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return PainelMonitor.objects.none()
        return PainelMonitor.unscoped.filter(tenant=tenant).order_by('-criado_em')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(
            tenant=tenant,
            criado_por=self.request.user,
            token=gerar_token_painel()
        )

    @action(detail=True, methods=['post'])
    def revogar(self, request, pk=None):
        painel = self.get_object()
        revogar_painel(painel)
        serializer = self.get_serializer(painel)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def regenerar_token(self, request, pk=None):
        painel = self.get_object()
        regenerar_token_painel(painel)
        serializer = self.get_serializer(painel)
        return Response(serializer.data, status=status.HTTP_200_OK)
