import datetime
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.modulos import MODULOS_REGISTRO, validar_toggle
from core.seeds import executar_seeds
from core.services.filial import obter_ou_criar_filial_matriz


def onboarding_tenant(
    dados_tenant: dict[str, Any],
    dados_admin: dict[str, Any],
    modulos_solicitados: list[str] | None = None,
    dados_regulatorio: dict[str, Any] | None = None,
    dados_filial: dict[str, Any] | None = None,
    executor: Any = None,
) -> dict[str, Any]:
    """
    Onboarding transacional atômico de uma nova empresa (Tenant) no SaaS Baros (Sprint 7B - v2.0).

    Passos executados em uma única transação:
    1. Validação de toggles de módulos via matriz de dependências (validar_toggle).
    2. Criação do Tenant com flags validados e status TRIAL (ou especificado).
    3. Criação do PerfilRegulatorioTenant associado (ANVISA/VISA).
    4. Criação da Filial Matriz (obter_ou_criar_filial_matriz).
    5. Criação do usuário administrador (ADMIN) vinculado via Membership.
    6. Execução de seeds idempotentes de inicialização dos módulos ativos.
    7. Registro em LogAuditoriaSaaS.
    """
    from core.models import (
        LogAuditoriaSaaS,
        Membership,
        PerfilRegulatorioTenant,
        Tenant,
    )

    User = get_user_model()

    # Define módulos iniciais
    modulos_ativos_iniciais = set(modulos_solicitados or ['patrimonio', 'comercial', 'vendas', 'logistica', 'financeiro'])

    # Validação prévia de coerência das dependências
    # Cria um objeto mock para testar a validação antes de persistir
    class MockTenant:
        def __init__(self, ativos: set[str]):
            for mod_cod, info in MODULOS_REGISTRO.items():
                setattr(self, info['flag'], mod_cod in ativos)

    mock = MockTenant(modulos_ativos_iniciais)
    erros_validacao: list[str] = []
    for mod in modulos_ativos_iniciais:
        errs = validar_toggle(mock, mod, True)
        if errs:
            erros_validacao.extend(errs)

    if erros_validacao:
        raise ValueError("Falha na validação dos módulos solicitados: " + "; ".join(erros_validacao))

    with transaction.atomic():
        # 1. Cria Tenant
        flags_kwargs = {
            MODULOS_REGISTRO[cod]['flag']: (cod in modulos_ativos_iniciais)
            for cod in MODULOS_REGISTRO
        }

        hoje = timezone.localdate()
        vencimento_trial = dados_tenant.get('data_vencimento_licenca') or (hoje + datetime.timedelta(days=14))

        tenant = Tenant.objects.create(
            razao_social=dados_tenant['razao_social'],
            nome_fantasia=dados_tenant['nome_fantasia'],
            cnpj=dados_tenant['cnpj'],
            plano=dados_tenant.get('plano', 'STARTER'),
            status_assinatura=dados_tenant.get('status_assinatura', 'TRIAL'),
            data_vencimento_licenca=vencimento_trial,
            limite_usuarios=dados_tenant.get('limite_usuarios', 5),
            limite_cilindros=dados_tenant.get('limite_cilindros', 500),
            valor_mensalidade_saas=dados_tenant.get('valor_mensalidade_saas', Decimal('499.00')),
            dias_carencia=dados_tenant.get('dias_carencia', 5),
            ativo=True,
            **flags_kwargs
        )

        # 2. Cria Perfil Regulatório (ANVISA)
        reg_info = dados_regulatorio or {}
        perfil_reg = PerfilRegulatorioTenant.objects.create(
            tenant=tenant,
            modo_operacao=reg_info.get('modo_operacao', 'DISTRIBUIDORA'),
            afe_numero=reg_info.get('afe_numero', 'AFE-PENDENTE-ONBOARDING'),
            afe_validade=reg_info.get('afe_validade') or (hoje + datetime.timedelta(days=365)),
            licenca_sanitaria_numero=reg_info.get('licenca_sanitaria_numero', 'VISA-PENDENTE-ONBOARDING'),
            licenca_sanitaria_validade=reg_info.get('licenca_sanitaria_validade') or (hoje + datetime.timedelta(days=365)),
            cbpf_cbpda_numero=reg_info.get('cbpf_cbpda_numero', ''),
        )

        # 3. Cria Filial Matriz
        fil_info = dados_filial or {}
        matriz = obter_ou_criar_filial_matriz(tenant=tenant)
        if fil_info:
            atualizou = False
            for campo in ['uf', 'municipio_ibge', 'inscricao_estadual']:
                if fil_info.get(campo):
                    setattr(matriz, campo, fil_info[campo])
                    atualizou = True
            if atualizou:
                matriz.save()

        # 4. Cria usuário Administrador (ADMIN)
        email_admin = dados_admin['email']
        username_admin = dados_admin.get('username') or email_admin.split('@')[0]
        user_admin, _user_created = User.objects.get_or_create(
            email=email_admin,
            defaults={
                'username': username_admin,
                'is_active': True,
            }
        )
        if dados_admin.get('senha'):
            user_admin.set_password(dados_admin['senha'])
        else:
            user_admin.set_unusable_password()

        if hasattr(user_admin, 'deve_trocar_senha'):
            user_admin.deve_trocar_senha = True
        user_admin.save()

        # Vincula como ADMIN do tenant
        Membership.objects.create(
            user=user_admin,
            tenant=tenant,
            papel='ADMIN',
            ativo=True
        )

        # 5. Executa seeds dos módulos habilitados
        seeds_executados = executar_seeds(tenant)

        # 6. Grava Auditoria SaaS
        LogAuditoriaSaaS.objects.create(
            tenant=tenant,
            usuario=executor if (executor and getattr(executor, 'is_authenticated', False)) else None,
            acao='ONBOARDING_TENANT_COMPLETO',
            modulo='core',
            detalhes_json={
                'tenant_id': str(tenant.id),
                'cnpj': tenant.cnpj,
                'admin_email': email_admin,
                'modulos': list(modulos_ativos_iniciais),
                'seeds_count': len(seeds_executados),
            },
            timestamp=timezone.now()
        )

        return {
            'tenant': tenant,
            'perfil_regulatorio': perfil_reg,
            'filial_matriz': matriz,
            'admin_user': user_admin,
            'modulos_ativos': list(modulos_ativos_iniciais),
            'seeds': seeds_executados,
        }
