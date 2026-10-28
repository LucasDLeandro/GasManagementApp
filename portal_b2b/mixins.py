"""
Mixins de Isolamento e Segurança do Portal B2B (Sprint 12B).

Implementa:
- B2BQuerysetMixin: duplo filtro fail-closed (tenant=request.tenant, cliente=request.user.vinculo_b2b.cliente)
  em todo get_queryset(), bloqueando IDOR e vazamentos cross-tenant.
- Gestão do ContextVar de Tenancy (set_current_tenant / reset_current_tenant).
- Cabeçalhos de segurança em todas as respostas HTTP (no-store, nosniff, DENY).
"""
import logging
from django.http import Http404
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from core.tenancy import get_current_tenant, set_current_tenant, reset_current_tenant
from core.guards import (
    assert_modulo,
    assert_tenant_writable,
    ModuloInativoError,
    AssinaturaInativaError,
)
from portal_b2b.ratelimit import verificar_rate_limit, RateLimitExcedido

logger = logging.getLogger(__name__)


class B2BSecurityHeadersMixin:
    """Aplica cabeçalhos de segurança exigidos para páginas e APIs do portal."""
    def finalize_response(self, request, response, *args, **kwargs):
        resp = super().finalize_response(request, response, *args, **kwargs)
        resp['X-Content-Type-Options'] = 'nosniff'
        resp['X-Frame-Options'] = 'DENY'
        resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp['Pragma'] = 'no-cache'
        return resp


class B2BQuerysetMixin(B2BSecurityHeadersMixin):
    """
    Mixin central para todas as Views e ViewSets do Portal B2B.

    Garante:
    1. Contexto do Tenant isolado via set_current_tenant no início e reset_current_tenant no final.
    2. Aplicação de guarda de módulo 'b2b' e verificação de tenant writable em escritas.
    3. Throttling por IP e por usuário.
    4. Duplo filtro estrito em get_queryset(): tenant=request.tenant E cliente=vinculo_b2b.cliente.
    """
    _view_tenant_token = None

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            if self._view_tenant_token is not None:
                token = self._view_tenant_token
                self._view_tenant_token = None
                reset_current_tenant(token)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return

        vinculo = getattr(user, 'vinculo_b2b', None)
        if not vinculo or not vinculo.ativo or vinculo.acesso_revogado_em is not None:
            return

        tenant = vinculo.tenant
        request.tenant = tenant
        request.cliente_b2b = vinculo.cliente
        request.vinculo_b2b = vinculo

        if get_current_tenant() != tenant:
            self._view_tenant_token = set_current_tenant(tenant)

        # Rate Limiting
        tipo_acao = 'escrita_usuario' if request.method not in permissions.SAFE_METHODS else 'usuario'
        try:
            verificar_rate_limit(request, tipo=tipo_acao, usuario_id=user.pk)
        except RateLimitExcedido as err:
            raise PermissionDenied({'detail': str(err), 'code': 'THROTTLED'}, code='THROTTLED')

        # Guardas de Módulo e Assinatura
        try:
            assert_modulo(tenant, 'b2b')
            if request.method not in permissions.SAFE_METHODS:
                assert_tenant_writable(tenant)
        except ModuloInativoError as err:
            raise PermissionDenied({'detail': str(err), 'code': 'MODULO_INATIVO'}, code='MODULO_INATIVO')
        except AssinaturaInativaError as err:
            raise PermissionDenied({'detail': str(err), 'code': 'ASSINATURA_INATIVA'}, code='ASSINATURA_INATIVA')

    def get_queryset(self):
        """
        Aplica fail-closed estrito:
        - Se não for usuário B2B ativo, retorna queryset vazio (.none()).
        - Filtra estritamente por tenant=request.tenant E cliente=vinculo_b2b.cliente.
        """
        user = getattr(self.request, 'user', None)
        if not (user and user.is_authenticated):
            return self.queryset.none() if hasattr(self, 'queryset') and self.queryset is not None else self.model.objects.none()

        vinculo = getattr(user, 'vinculo_b2b', None)
        if not vinculo or not vinculo.ativo:
            return self.queryset.none() if hasattr(self, 'queryset') and self.queryset is not None else self.model.objects.none()

        tenant = vinculo.tenant
        cliente = vinculo.cliente

        base_qs = super().get_queryset()

        # Determina os campos de cliente no modelo de destino
        model = base_qs.model
        filtros = {'tenant': tenant}

        field_names = {f.name for f in model._meta.get_fields()}

        if 'cliente_posse_atual' in field_names:
            filtros['cliente_posse_atual'] = cliente
        elif 'cliente' in field_names:
            filtros['cliente'] = cliente
        elif 'cliente_proprietario' in field_names:
            filtros['cliente_proprietario'] = cliente
        elif 'usuario_b2b' in field_names:
            filtros['usuario_b2b'] = vinculo

        return base_qs.filter(**filtros)
