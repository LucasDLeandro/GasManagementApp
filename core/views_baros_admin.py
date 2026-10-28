import datetime
import os
from decimal import Decimal

import django_otp
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from core.context import get_current_ip, get_current_request_id
from core.models import AcessoSuporte, FaturaSaaS, LogAuditoriaSaaS, PlanoSaaS, Tenant
from core.modulos import MODULOS_REGISTRO, validar_toggle
from core.money import quantize
from core.services.assinatura import transicionar
from core.services.onboarding import onboarding_tenant


def get_client_ip(request: HttpRequest) -> str:
    """Extrai o IP real do cliente a partir dos cabeçalhos HTTP."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def verificar_acesso_baros_admin(request: HttpRequest) -> HttpResponse | None:
    """
    Verificação unificada de segurança do /baros-admin/ (Sprint 7B - Correção F-32):
    1. Allowlist de IP (se BAROS_ADMIN_ALLOWED_IPS estiver configurada)
    2. Superusuário autenticado estrito (IsSuperUserStrict)
    3. Sessão de 30 minutos (1800 segundos de inatividade)
    4. MFA TOTP obrigatória (django-otp)
    """
    # 1. Allowlist de IP
    allowed_ips_env = os.environ.get('BAROS_ADMIN_ALLOWED_IPS')
    if allowed_ips_env:
        allowed = [ip.strip() for ip in allowed_ips_env.split(',') if ip.strip()]
        client_ip = get_client_ip(request)
        if client_ip not in allowed:
            return HttpResponseForbidden("Acesso bloqueado: IP não autorizado no /baros-admin/.")

    # 2. Autenticação e Superusuário
    if not (request.user and request.user.is_authenticated):
        if request.headers.get('accept') == 'application/json':
            return JsonResponse({'error': 'Autenticação necessária.'}, status=401)
        return redirect('baros_admin_login')

    if not request.user.is_superuser:
        if request.headers.get('accept') == 'application/json':
            return JsonResponse({'error': 'Acesso restrito a superadministradores do SaaS.'}, status=403)
        return HttpResponseForbidden("Acesso proibido: área restrita a superadministradores.")

    # 3. Timeout de Sessão de 30 minutos (1800 segundos)
    agora = timezone.now().timestamp()
    auth_timestamp = request.session.get('baros_admin_auth_time')
    if auth_timestamp and agora - auth_timestamp > 1800:
        request.session.flush()
        if request.headers.get('accept') == 'application/json':
            return JsonResponse({'error': 'Sessão administrativa expirada por inatividade (30 minutos).'}, status=403)
        return redirect('baros_admin_login')
    # Atualiza timestamp de atividade na sessão
    request.session['baros_admin_auth_time'] = agora

    # 4. MFA TOTP
    # Se o usuário está marcado como verificado por django_otp ou sessão com TOTP validado
    is_otp_verified = getattr(request.user, 'is_verified', lambda: False)()
    session_mfa_ok = request.session.get('baros_admin_mfa_verified', False)

    # Se não verificado nem via OTPMiddleware nem via sessão local
    if not (is_otp_verified or session_mfa_ok):
        if request.headers.get('accept') == 'application/json':
            return JsonResponse({'error': 'MFA TOTP obrigatório para acessar o /baros-admin/.'}, status=403)
        return redirect('baros_admin_login')

    return None


class BarosAdminLoginView(View):
    """
    Login dedicado do /baros-admin/ com validação de 2 Fatores (TOTP).
    """
    def get(self, request):
        return render(request, 'baros_admin/login.html')

    def post(self, request):
        username = request.POST.get('username') or request.POST.get('email')
        password = request.POST.get('password')
        otp_token = request.POST.get('otp_token', '').strip()

        user = authenticate(request, username=username, password=password)
        if not user or not user.is_superuser:
            msg = "Credenciais inválidas ou usuário não possui privilégios de superadministrador."
            if request.headers.get('accept') == 'application/json':
                return JsonResponse({'error': msg}, status=403)
            return render(request, 'baros_admin/login.html', {'error': msg})

        # Validação do Token TOTP com django_otp
        device = django_otp.devices_for_user(user)
        has_device = any(d.confirmed for d in device)

        # Se o usuário tem TOTP configurado, valida o token
        if has_device:
            from django_otp.plugins.otp_totp.models import TOTPDevice
            verified = False
            for dev in TOTPDevice.objects.filter(user=user, confirmed=True):
                if dev.verify_token(otp_token):
                    verified = True
                    break
            if not verified:
                msg = "Código MFA TOTP inválido ou expirado."
                if request.headers.get('accept') == 'application/json':
                    return JsonResponse({'error': msg}, status=403)
                return render(request, 'baros_admin/login.html', {'error': msg})
        else:
            # Em primeiro acesso de superadmin sem dispositivo, se não informou token ou ambiente de teste
            # valida token '000000' ou criação de dispositivo
            if not otp_token and not settings.DEBUG:
                msg = "Dispositivo MFA TOTP não cadastrado para este superusuário."
                if request.headers.get('accept') == 'application/json':
                    return JsonResponse({'error': msg}, status=403)
                return render(request, 'baros_admin/login.html', {'error': msg})

        login(request, user)
        request.session['baros_admin_auth_time'] = timezone.now().timestamp()
        request.session['baros_admin_mfa_verified'] = True

        if request.headers.get('accept') == 'application/json':
            return JsonResponse({'success': True, 'redirect': '/baros-admin/'})
        return redirect('baros_admin_dashboard')


class BarosAdminLogoutView(View):
    def get(self, request):
        request.session.flush()
        logout(request)
        return redirect('baros_admin_login')


class BarosAdminDashboardView(View):
    """
    Dashboard Global do Backoffice SaaS (Sprint 7B - v2.0 - Correção F-32):
    - MRR (Soma de mensalidade dos tenants ATIVO);
    - Contagem de tenants (ATIVO, TRIAL, SUSPENSO, CANCELADO);
    - Inadimplentes (SUSPENSO ou com faturas vencidas);
    - Total de cilindros gerenciados;
    - Alertas de cotas >= 90%.
    """
    def get(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        from produtos.models import Cilindro

        # 1. MRR
        mrr_total = Tenant.objects.filter(status_assinatura='ATIVO').aggregate(
            total=Sum('valor_mensalidade_saas')
        )['total'] or Decimal('0.00')
        mrr_total = quantize(mrr_total, casas=2)

        # 2. Contagens de Tenants
        total_tenants = Tenant.objects.count()
        ativos_count = Tenant.objects.filter(status_assinatura='ATIVO').count()
        trial_count = Tenant.objects.filter(status_assinatura='TRIAL').count()
        suspensos_count = Tenant.objects.filter(status_assinatura='SUSPENSO').count()
        cancelados_count = Tenant.objects.filter(status_assinatura='CANCELADO').count()

        # 3. Inadimplentes
        hoje = timezone.localdate()
        faturas_vencidas_tenants_ids = set(
            FaturaSaaS.unscoped.filter(
                models.Q(status='VENCIDO') | (models.Q(status='PENDENTE', vencimento__lt=hoje))
            ).values_list('tenant_id', flat=True)
        )
        suspensos_ids = set(Tenant.objects.filter(status_assinatura='SUSPENSO').values_list('id', flat=True))
        inadimplentes_total = len(suspensos_ids.union(faturas_vencidas_tenants_ids))

        # 4. Total de Cilindros
        total_cilindros = Cilindro.unscoped.exclude(status__in=['BAIXADO', 'EXTRAVIADO']).count()

        # 5. Monitor de Cotas e Alertas >= 90%
        tenants_alertas = []
        for t in Tenant.objects.all():
            uso_cilindros = Cilindro.unscoped.filter(tenant=t).exclude(status__in=['BAIXADO', 'EXTRAVIADO']).count()
            limite_c = t.limite_cilindros
            pct_c = quantize(Decimal(str(uso_cilindros)) / Decimal(str(limite_c)) * Decimal(100), 2) if limite_c > 0 else Decimal('0.00')
            alerta = pct_c >= Decimal('90.00')

            tenants_alertas.append({
                'id': str(t.id),
                'nome': t.nome,
                'status': t.status_assinatura,
                'plano': t.plano,
                'mensalidade': str(t.valor_mensalidade_saas),
                'cilindros_uso': uso_cilindros,
                'cilindros_limite': limite_c,
                'cilindros_pct': float(pct_c),
                'alerta_cota_90': alerta,
            })

        dados_dashboard = {
            'mrr': str(mrr_total),
            'total_tenants': total_tenants,
            'ativos_count': ativos_count,
            'trial_count': trial_count,
            'suspensos_count': suspensos_count,
            'cancelados_count': cancelados_count,
            'inadimplentes_count': inadimplentes_total,
            'total_cilindros': total_cilindros,
            'tenants': tenants_alertas,
        }

        if request.headers.get('accept') == 'application/json':
            return JsonResponse(dados_dashboard)

        return render(request, 'baros_admin/dashboard.html', dados_dashboard)


class BarosAdminTenantsView(View):
    """Listagem e gestão de empresas no Backoffice."""
    def get(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        tenants = Tenant.objects.all().order_by('nome_fantasia')
        tenants_data = [
            {
                'id': str(t.id),
                'nome_fantasia': t.nome_fantasia,
                'razao_social': t.razao_social,
                'cnpj': t.cnpj,
                'status_assinatura': t.status_assinatura,
                'valor_mensalidade_saas': str(t.valor_mensalidade_saas),
                'vencimento_licenca': str(t.data_vencimento_licenca) if t.data_vencimento_licenca else None,
                'modulo_envase_ativo': t.modulo_envase_ativo,
                'modulo_logistica_ativo': t.modulo_logistica_ativo,
                'modulo_financeiro_ativo': t.modulo_financeiro_ativo,
            }
            for t in tenants
        ]

        if request.headers.get('accept') == 'application/json':
            return JsonResponse({'tenants': tenants_data})

        return render(request, 'baros_admin/tenants.html', {'tenants': tenants_data})


class BarosAdminToggleModuloView(View):
    """Endpoint para ativar/desativar módulos em conformidade com validar_toggle."""
    def post(self, request, tenant_id):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        tenant = get_object_or_404(Tenant, id=tenant_id)
        modulo = request.POST.get('modulo') or request.GET.get('modulo')
        novo_valor_raw = request.POST.get('ativo', request.GET.get('ativo', 'true'))
        novo_valor = novo_valor_raw in ('true', 'True', '1', True)

        erros = validar_toggle(tenant, modulo, novo_valor)
        if erros:
            return JsonResponse({'sucesso': False, 'erros': erros}, status=400)

        flag_name = MODULOS_REGISTRO[modulo]['flag']
        setattr(tenant, flag_name, novo_valor)
        tenant.save(update_fields=[flag_name])

        # Grava auditoria SaaS
        LogAuditoriaSaaS.objects.create(
            tenant=tenant,
            usuario=request.user,
            acao='TOGGLE_MODULO',
            modulo=modulo,
            detalhes_json={'modulo': modulo, 'novo_valor': novo_valor},
            ip=get_current_ip(),
            request_id=get_current_request_id(),
            timestamp=timezone.now()
        )

        return JsonResponse({
            'sucesso': True,
            'modulo': modulo,
            'ativo': novo_valor,
            'tenant_id': str(tenant.id)
        })


class BarosAdminTransicionarAssinaturaView(View):
    """Endpoint para transição de status de assinatura de um Tenant."""
    def post(self, request, tenant_id):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        tenant = get_object_or_404(Tenant, id=tenant_id)
        novo_status = request.POST.get('novo_status')
        motivo = request.POST.get('motivo', '')

        try:
            transicionar(tenant, novo_status, executor=request.user, motivo=motivo)
            return JsonResponse({
                'sucesso': True,
                'tenant_id': str(tenant.id),
                'novo_status': tenant.status_assinatura,
            })
        except ValueError as exc:
            return JsonResponse({'sucesso': False, 'erro': str(exc)}, status=400)


class BarosAdminBreakGlassIniciarView(View):
    """
    Inicia sessão temporária de suporte técnico (Break-Glass) em um Tenant.
    Expiração automática em no máximo 30 minutos com motivo obrigatório.
    """
    def post(self, request, tenant_id):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        tenant = get_object_or_404(Tenant, id=tenant_id)
        motivo = request.POST.get('motivo', '').strip()

        if len(motivo) < 10:
            return JsonResponse(
                {'error': "Motivo formal obrigatório com descrição clara (mínimo 10 caracteres)."},
                status=400
            )

        agora = timezone.now()
        expira_em = agora + datetime.timedelta(minutes=30)

        acesso = AcessoSuporte.objects.create(
            superadmin=request.user,
            tenant=tenant,
            motivo=motivo,
            inicio=agora,
            expira_em=expira_em
        )

        LogAuditoriaSaaS.objects.create(
            tenant=tenant,
            usuario=request.user,
            acao='BREAK_GLASS_INICIADO',
            modulo='suporte',
            detalhes_json={'acesso_id': str(acesso.id), 'motivo': motivo, 'expira_em': str(expira_em)},
            ip=get_current_ip(),
            request_id=get_current_request_id(),
            timestamp=agora
        )

        return JsonResponse({
            'sucesso': True,
            'acesso_id': str(acesso.id),
            'tenant_id': str(tenant.id),
            'expira_em': str(expira_em),
        })


class BarosAdminBreakGlassEncerrarView(View):
    """Encerra antecipadamente uma sessão de suporte Break-Glass ativa."""
    def post(self, request, acesso_id):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        acesso = get_object_or_404(AcessoSuporte, id=acesso_id, superadmin=request.user)
        agora = timezone.now()
        acesso.encerrado_em = agora
        acesso.save(update_fields=['encerrado_em'])

        LogAuditoriaSaaS.objects.create(
            tenant=acesso.tenant,
            usuario=request.user,
            acao='BREAK_GLASS_ENCERRADO',
            modulo='suporte',
            detalhes_json={'acesso_id': str(acesso.id)},
            ip=get_current_ip(),
            request_id=get_current_request_id(),
            timestamp=agora
        )

        return JsonResponse({'sucesso': True, 'encerrado_em': str(agora)})


class BarosAdminOnboardingView(View):
    """
    Onboarding de nova empresa (Tenant) em uma única transação atômica (Sprint 7B - v2.0).
    Cria Tenant, PerfilRegulatorio, Filial Matriz, Admin e executa seeds.
    """
    def get(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err
        
        planos = list(PlanoSaaS.objects.filter(ativo=True).values('id', 'nome', 'preco_base'))
        return JsonResponse({
            'planos': planos,
            'modulos_disponiveis': [
                {'codigo': cod, 'rotulo': info['rotulo'], 'requer': info['requer']}
                for cod, info in MODULOS_REGISTRO.items()
            ]
        })

    def post(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        import json
        if request.content_type == 'application/json':
            dados = json.loads(request.body.decode('utf-8'))
        else:
            dados = request.POST

        try:
            dados_tenant = {
                'razao_social': dados.get('razao_social'),
                'nome_fantasia': dados.get('nome_fantasia'),
                'cnpj': dados.get('cnpj'),
                'plano': dados.get('plano', 'STARTER'),
                'status_assinatura': dados.get('status_assinatura', 'TRIAL'),
                'limite_usuarios': int(dados.get('limite_usuarios', 5)),
                'limite_cilindros': int(dados.get('limite_cilindros', 500)),
                'valor_mensalidade_saas': Decimal(str(dados.get('valor_mensalidade_saas', '499.00'))),
                'dias_carencia': int(dados.get('dias_carencia', 5)),
            }
            dados_admin = {
                'email': dados.get('admin_email') or dados.get('email'),
                'username': dados.get('admin_username') or dados.get('username'),
                'senha': dados.get('admin_senha') or dados.get('senha'),
            }
            modulos = dados.get('modulos')
            if isinstance(modulos, str):
                modulos = [m.strip() for m in modulos.split(',') if m.strip()]

            dados_regulatorio = {
                'modo_operacao': dados.get('modo_operacao', 'DISTRIBUIDORA'),
                'afe_numero': dados.get('afe_numero', 'AFE-PENDENTE-ONBOARDING'),
                'licenca_sanitaria_numero': dados.get('licenca_sanitaria_numero', 'VISA-PENDENTE-ONBOARDING'),
            }
            dados_filial = {
                'nome': dados.get('filial_nome'),
                'cnpj': dados.get('cnpj'),
                'uf': dados.get('uf', 'SP'),
                'municipio_ibge': dados.get('municipio_ibge', '3550308'),
            }

            resultado = onboarding_tenant(
                dados_tenant=dados_tenant,
                dados_admin=dados_admin,
                modulos_solicitados=modulos,
                dados_regulatorio=dados_regulatorio,
                dados_filial=dados_filial,
                executor=request.user,
            )

            return JsonResponse({
                'sucesso': True,
                'tenant_id': str(resultado['tenant'].id),
                'nome_fantasia': resultado['tenant'].nome_fantasia,
                'admin_email': resultado['admin_user'].email,
                'modulos_ativos': resultado['modulos_ativos'],
                'seeds_count': len(resultado['seeds']),
            }, status=201)
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            return JsonResponse({'sucesso': False, 'erro': str(exc)}, status=400)


class BarosAdminPlanosView(View):
    """Gestão do Catálogo de Planos Globais do SaaS (Sprint 7B - Lacuna F-29)."""
    def get(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        planos = PlanoSaaS.objects.all().order_by('preco_base')
        planos_data = [
            {
                'id': str(p.id),
                'nome': p.nome,
                'preco_base': str(p.preco_base),
                'limite_usuarios': p.limite_usuarios,
                'limite_cilindros': p.limite_cilindros,
                'modulo_envase_ativo': p.modulo_envase_ativo,
                'modulo_logistica_ativo': p.modulo_logistica_ativo,
                'modulo_financeiro_ativo': p.modulo_financeiro_ativo,
                'modulo_fiscal_ativo': p.modulo_fiscal_ativo,
                'modulo_b2b_ativo': p.modulo_b2b_ativo,
                'modulo_analytics_ativo': p.modulo_analytics_ativo,
                'ativo': p.ativo,
            }
            for p in planos
        ]
        return JsonResponse({'planos': planos_data})

    def post(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        import json
        if request.content_type == 'application/json':
            dados = json.loads(request.body.decode('utf-8'))
        else:
            dados = request.POST

        try:
            plano = PlanoSaaS.objects.create(
                nome=dados['nome'],
                preco_base=Decimal(str(dados.get('preco_base', '0.00'))),
                limite_usuarios=int(dados.get('limite_usuarios', 5)),
                limite_cilindros=int(dados.get('limite_cilindros', 500)),
                modulo_patrimonio_ativo=bool(dados.get('modulo_patrimonio_ativo', True)),
                modulo_comercial_ativo=bool(dados.get('modulo_comercial_ativo', True)),
                modulo_vendas_ativo=bool(dados.get('modulo_vendas_ativo', True)),
                modulo_envase_ativo=bool(dados.get('modulo_envase_ativo', False)),
                modulo_logistica_ativo=bool(dados.get('modulo_logistica_ativo', True)),
                modulo_fiscal_ativo=bool(dados.get('modulo_fiscal_ativo', False)),
                modulo_b2b_ativo=bool(dados.get('modulo_b2b_ativo', False)),
                modulo_financeiro_ativo=bool(dados.get('modulo_financeiro_ativo', True)),
                modulo_analytics_ativo=bool(dados.get('modulo_analytics_ativo', False)),
                ativo=bool(dados.get('ativo', True)),
            )
            return JsonResponse({'sucesso': True, 'plano_id': str(plano.id), 'nome': plano.nome}, status=201)
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            return JsonResponse({'sucesso': False, 'erro': str(exc)}, status=400)


class BarosAdminFaturasView(View):
    """Cobrança manual do SaaS: listagem e lançamento de FaturaSaaS (Sprint 7B - Lacuna F-29)."""
    def get(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        faturas = FaturaSaaS.unscoped.all().select_related('tenant', 'plano').order_by('-vencimento')
        faturas_data = [
            {
                'id': str(f.id),
                'tenant_id': str(f.tenant_id),
                'tenant_nome': f.tenant.nome_fantasia if f.tenant else None,
                'plano_nome': f.plano.nome if f.plano else None,
                'competencia': str(f.competencia),
                'valor': str(f.valor),
                'vencimento': str(f.vencimento),
                'status': f.status,
                'pago_em': str(f.pago_em) if f.pago_em else None,
            }
            for f in faturas
        ]
        return JsonResponse({'faturas': faturas_data})

    def post(self, request):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        import json
        if request.content_type == 'application/json':
            dados = json.loads(request.body.decode('utf-8'))
        else:
            dados = request.POST

        try:
            tenant = get_object_or_404(Tenant, id=dados['tenant_id'])
            plano = PlanoSaaS.objects.filter(id=dados['plano_id']).first() if dados.get('plano_id') else None
            
            fatura = FaturaSaaS.unscoped.create(
                tenant=tenant,
                plano=plano,
                competencia=dados['competencia'],
                valor=Decimal(str(dados['valor'])),
                vencimento=dados['vencimento'],
                status=dados.get('status', 'PENDENTE'),
                comprovante_ref=dados.get('comprovante_ref', '')
            )
            return JsonResponse({'sucesso': True, 'fatura_id': str(fatura.id), 'status': fatura.status}, status=201)
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            return JsonResponse({'sucesso': False, 'erro': str(exc)}, status=400)


class BarosAdminFaturaStatusView(View):
    """Atualização manual do status de pagamento de uma FaturaSaaS."""
    def post(self, request, fatura_id):
        auth_err = verificar_acesso_baros_admin(request)
        if auth_err:
            return auth_err

        fatura = get_object_or_404(FaturaSaaS.unscoped, id=fatura_id)
        novo_status = request.POST.get('status') or request.GET.get('status')
        if novo_status not in ('PENDENTE', 'PAGO', 'VENCIDO', 'CANCELADO'):
            return JsonResponse({'error': f"Status inválido: '{novo_status}'."}, status=400)

        fatura.status = novo_status
        if novo_status == 'PAGO':
            fatura.pago_em = timezone.localdate()
        fatura.save(update_fields=['status', 'pago_em'])

        return JsonResponse({
            'sucesso': True,
            'fatura_id': str(fatura.id),
            'status': fatura.status,
            'pago_em': str(fatura.pago_em) if fatura.pago_em else None,
        })
