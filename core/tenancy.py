import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from django.db import models

_current_tenant: ContextVar = ContextVar("current_tenant", default=None)

class TenantNotSet(Exception):
    """
    Lançada quando uma operação sobre TenantAwareModel é executada sem um Tenant ativo no contexto.
    Garante o isolamento 'Fail-Closed'.
    """
    pass

def get_current_tenant():
    """Retorna o tenant atualmente ativo no contexto da thread/requisição."""
    return _current_tenant.get()

def set_current_tenant(tenant):
    """Define o tenant ativo no contexto atual e retorna o token de reset."""
    return _current_tenant.set(tenant)

def reset_current_tenant(token=None):
    """Restaura o contexto do tenant anterior através do token."""
    if token is not None:
        _current_tenant.reset(token)
    else:
        _current_tenant.set(None)

@contextmanager
def tenant_context(tenant):
    """Context manager para executar blocos de código com um Tenant específico."""
    token = _current_tenant.set(tenant)
    try:
        yield tenant
    finally:
        _current_tenant.reset(token)

class TenantQuerySet(models.QuerySet):
    def create(self, **kwargs):
        tenant = get_current_tenant()
        if tenant and 'tenant' not in kwargs:
            kwargs['tenant'] = tenant
        return super().create(**kwargs)

class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant is None:
            raise TenantNotSet(
                "Isolamento Fail-Closed: Nenhuma consulta pode ser realizada em um modelo "
                "TenantAwareModel sem um Tenant ativo no contexto atual. Use tenant_context(tenant) "
                "ou .unscoped se a operação for administrativa/interna."
            )
        return super().get_queryset().filter(tenant=tenant)

def get_default_tenant_pk():
    """Retorna o PK do tenant padrão para migrações e backfill."""
    try:
        from core.models import Tenant
        tenant = Tenant.objects.filter(cnpj='00.000.000/0001-00').first()
        if tenant:
            return tenant.id
        tenant = Tenant.objects.first()
        if tenant:
            return tenant.id
    except Exception:
        pass
    return uuid.UUID('00000000-0000-0000-0000-000000000001')

class TenantAwareModel(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.PROTECT,
        db_index=True,
        default=get_default_tenant_pk,
        verbose_name="Empresa (Tenant)"
    )

    objects = TenantManager()
    unscoped = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        current_tenant = get_current_tenant()
        if current_tenant:
            # Se há um tenant ativo no contexto e o tenant_id é o default ou vazio, atribui o tenant ativo
            if not self.tenant_id or self.tenant_id == get_default_tenant_pk():
                self.tenant = current_tenant
        elif not self.tenant_id:
            raise TenantNotSet(
                f"Não é possível salvar a instância de {self.__class__.__name__} sem um Tenant ativo no contexto."
            )
        super().save(*args, **kwargs)
