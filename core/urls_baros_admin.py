from django.urls import path

from core.views_baros_admin import (
    BarosAdminBreakGlassEncerrarView,
    BarosAdminBreakGlassIniciarView,
    BarosAdminDashboardView,
    BarosAdminFaturaStatusView,
    BarosAdminFaturasView,
    BarosAdminLoginView,
    BarosAdminLogoutView,
    BarosAdminMfaCadastroView,
    BarosAdminOnboardingView,
    BarosAdminPlanosView,
    BarosAdminTenantsView,
    BarosAdminToggleModuloView,
    BarosAdminTransicionarAssinaturaView,
)

urlpatterns = [
    path('', BarosAdminDashboardView.as_view(), name='baros_admin_dashboard'),
    path('login/', BarosAdminLoginView.as_view(), name='baros_admin_login'),
    path('logout/', BarosAdminLogoutView.as_view(), name='baros_admin_logout'),
    path('mfa/cadastro/', BarosAdminMfaCadastroView.as_view(), name='baros_admin_mfa_cadastro'),
    path('tenants/', BarosAdminTenantsView.as_view(), name='baros_admin_tenants'),
    path('tenants/<uuid:tenant_id>/toggle-modulo/', BarosAdminToggleModuloView.as_view(), name='baros_admin_toggle_modulo'),
    path('tenants/<uuid:tenant_id>/transicionar-assinatura/', BarosAdminTransicionarAssinaturaView.as_view(), name='baros_admin_transicionar_assinatura'),
    path('tenants/<uuid:tenant_id>/break-glass/iniciar/', BarosAdminBreakGlassIniciarView.as_view(), name='baros_admin_break_glass_iniciar'),
    path('break-glass/<uuid:acesso_id>/encerrar/', BarosAdminBreakGlassEncerrarView.as_view(), name='baros_admin_break_glass_encerrar'),
    path('onboarding/', BarosAdminOnboardingView.as_view(), name='baros_admin_onboarding'),
    path('planos/', BarosAdminPlanosView.as_view(), name='baros_admin_planos'),
    path('faturas/', BarosAdminFaturasView.as_view(), name='baros_admin_faturas'),
    path('faturas/<uuid:fatura_id>/status/', BarosAdminFaturaStatusView.as_view(), name='baros_admin_fatura_status'),
]
