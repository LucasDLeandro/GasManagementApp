from django.http import Http404
from rest_framework.exceptions import PermissionDenied
from core.models import Tenant, Membership
from core.tenancy import get_current_tenant, set_current_tenant, reset_current_tenant, TenantNotSet

class TenantViewSetMixin:
    """
    Mixin para ViewSets e APIViews do Django REST Framework para garantir que
    consultas e criações fiquem estritamente restritas ao Tenant da requisição.

    - Sobrescreve initial() para resolver request.tenant e request.membership após autenticação,
      validando que o usuário possui Membership ativo naquele tenant.
    - Se X-Tenant-ID for informado e o usuário não possuir vínculo ativo (e não for superuser),
      lança Http404 para fail-closed opaco total.
    - Utiliza dispatch() com try ... finally para gerenciar o ciclo de vida do ContextVar,
      garantindo que se um novo token foi registrado nesta view, ele é resetado ao final.
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

        if user and user.is_authenticated:
            tenant_id_header = request.headers.get('X-Tenant-ID') or request.META.get('HTTP_X_TENANT_ID')
            tenant = None
            membership = None

            if tenant_id_header:
                if user.is_superuser:
                    tenant = Tenant.objects.filter(id=tenant_id_header, ativo=True).first()
                else:
                    membership = Membership.objects.filter(
                        user=user,
                        tenant_id=tenant_id_header,
                        ativo=True,
                        tenant__ativo=True
                    ).select_related('tenant').first()
                    if membership:
                        tenant = membership.tenant

                if not tenant:
                    raise Http404("Tenant não encontrado ou inexistente para o usuário.")
            else:
                membership = Membership.objects.filter(
                    user=user,
                    ativo=True,
                    tenant__ativo=True
                ).select_related('tenant').first()
                if membership:
                    tenant = membership.tenant
                elif user.is_superuser:
                    tenant = Tenant.objects.filter(ativo=True).first()

                if not tenant and not user.is_superuser:
                    raise Http404("Nenhum tenant ativo associado ao usuário.")

            request.tenant = tenant
            request.membership = membership

            if get_current_tenant() != tenant:
                self._view_tenant_token = set_current_tenant(tenant)

    def get_queryset(self):
        tenant = get_current_tenant()
        if not tenant:
            raise TenantNotSet("Acesso negado: nenhum Tenant ativo no contexto da requisição.")
        
        model = getattr(self, 'model', None)
        if not model and hasattr(self, 'queryset') and self.queryset is not None:
            model = self.queryset.model
        elif not model and hasattr(self, 'get_serializer_class'):
            try:
                model = self.get_serializer_class().Meta.model
            except Exception:
                pass

        if model and hasattr(model, 'objects'):
            return model.objects.all()
        
        return super().get_queryset().filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if not tenant:
            raise PermissionDenied("Não é possível salvar registros sem uma empresa (Tenant) associada.")
        serializer.save(tenant=tenant)
