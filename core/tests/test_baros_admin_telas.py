"""
Telas do Backoffice Baros (Plano de Correção, Fase 1).

Cobre: páginas renderizam para superusuário com MFA, bloqueio para quem não é,
compatibilidade das respostas JSON e as ações novas (editar plano, faturas em lote,
auditoria de status de fatura, abrir o app após o break-glass).
"""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from core.models import AcessoSuporte, FaturaSaaS, LogAuditoriaSaaS, PlanoSaaS, Tenant

User = get_user_model()


def _tenant(cnpj, nome, status='ATIVO', mensalidade='799.00'):
    return Tenant.objects.create(
        cnpj=cnpj, razao_social=f'{nome} Ltda', nome_fantasia=nome, status_assinatura=status,
        valor_mensalidade_saas=Decimal(mensalidade), limite_usuarios=5, limite_cilindros=10, ativo=True,
    )


@pytest.fixture
def tenant(db):
    return _tenant('11.222.333/0001-81', 'GasTech')


@pytest.fixture
def admin_client(db):
    """Cliente logado como superusuário com a sessão do backoffice já validada por MFA."""
    user = User.objects.create_superuser(username='dono', email='dono@baros.test', password='Senha-Forte-123')
    client = Client()
    client.force_login(user)
    sessao = client.session
    sessao['baros_admin_mfa_verified'] = True
    sessao['baros_admin_auth_time'] = timezone.now().timestamp()
    sessao.save()
    client.user = user
    return client


@pytest.mark.parametrize('url', [
    '/baros-admin/',
    '/baros-admin/tenants/',
    '/baros-admin/tenants/?q=Gas&status=ATIVO',
    '/baros-admin/onboarding/',
    '/baros-admin/planos/',
    '/baros-admin/faturas/',
    '/baros-admin/faturas/?status=EM_ATRASO',
    '/baros-admin/suporte/',
    '/baros-admin/auditoria/',
])
def test_paginas_renderizam(admin_client, tenant, url):
    resp = admin_client.get(url)

    assert resp.status_code == 200
    assert b'bo-shell' in resp.content


def test_detalhe_da_empresa(admin_client, tenant):
    resp = admin_client.get(f'/baros-admin/tenants/{tenant.id}/')

    assert resp.status_code == 200
    conteudo = resp.content.decode()
    assert 'GasTech' in conteudo
    assert 'data-acao="toggle-modulo"' in conteudo
    # ATIVO só pode ir para SUSPENSO ou CANCELADO
    assert 'data-status="SUSPENSO"' in conteudo and 'data-status="CANCELADO"' in conteudo
    assert 'data-status="ATIVO"' not in conteudo


def test_usuario_comum_nao_acessa(db, tenant):
    comum = User.objects.create_user(username='comum', password='Senha-123456')
    client = Client()
    client.force_login(comum)

    assert client.get('/baros-admin/tenants/').status_code == 403
    assert client.get(f'/baros-admin/tenants/{tenant.id}/').status_code == 403


def test_listagens_continuam_respondendo_json(admin_client, tenant):
    for url, chave in [('/baros-admin/tenants/', 'tenants'), ('/baros-admin/planos/', 'planos'),
                       ('/baros-admin/faturas/', 'faturas'), ('/baros-admin/onboarding/', 'planos')]:
        resp = admin_client.get(url, HTTP_ACCEPT='application/json')
        assert resp.status_code == 200
        assert chave in resp.json()


def test_criar_plano_respeita_falso_em_formulario(admin_client):
    resp = admin_client.post('/baros-admin/planos/', {
        'nome': 'Básico', 'preco_base': '299.00', 'limite_usuarios': '3', 'limite_cilindros': '200',
        'modulo_logistica_ativo': 'false', 'modulo_fiscal_ativo': 'true',
    })

    assert resp.status_code == 201
    plano = PlanoSaaS.objects.get(nome='Básico')
    assert plano.modulo_logistica_ativo is False
    assert plano.modulo_fiscal_ativo is True


def test_editar_plano_grava_e_audita(admin_client):
    plano = PlanoSaaS.objects.create(nome='Pro', preco_base=Decimal('900.00'))

    resp = admin_client.post(
        f'/baros-admin/planos/{plano.id}/editar/',
        data={'preco_base': '990.50', 'limite_cilindros': 1500, 'modulo_b2b_ativo': True, 'ativo': False},
        content_type='application/json',
    )

    assert resp.status_code == 200
    plano.refresh_from_db()
    assert plano.preco_base == Decimal('990.50')
    assert plano.limite_cilindros == 1500
    assert plano.modulo_b2b_ativo is True
    assert plano.ativo is False
    assert LogAuditoriaSaaS.objects.filter(acao='PLANO_SAAS_EDITADO').exists()


def test_faturas_em_lote_so_para_ativas_e_sem_duplicar(admin_client, tenant):
    _tenant('22.333.444/0001-55', 'Trialzinha', status='TRIAL')
    _tenant('33.444.555/0001-66', 'Suspensa', status='SUSPENSO')
    dados = {'competencia': '2026-11', 'vencimento': '2026-11-10'}

    primeira = admin_client.post('/baros-admin/faturas/gerar-lote/', data=dados, content_type='application/json')
    segunda = admin_client.post('/baros-admin/faturas/gerar-lote/', data=dados, content_type='application/json')

    assert primeira.json()['criadas'] == 1
    assert segunda.json()['criadas'] == 0
    fatura = FaturaSaaS.unscoped.get()
    assert fatura.tenant == tenant
    assert fatura.valor == Decimal('799.00')
    assert fatura.competencia == datetime.date(2026, 11, 1)


def test_faturas_em_lote_valida_datas(admin_client):
    resp = admin_client.post('/baros-admin/faturas/gerar-lote/', data={'competencia': 'nov'}, content_type='application/json')

    assert resp.status_code == 400


def test_status_da_fatura_fica_auditado(admin_client, tenant):
    fatura = FaturaSaaS.unscoped.create(
        tenant=tenant, competencia=datetime.date(2026, 10, 1), valor=Decimal('799.00'),
        vencimento=datetime.date(2026, 10, 10),
    )

    resp = admin_client.post(f'/baros-admin/faturas/{fatura.id}/status/', {'status': 'PAGO'})

    assert resp.status_code == 200
    assert LogAuditoriaSaaS.objects.filter(acao='FATURA_SAAS_STATUS', tenant=tenant).exists()


def test_break_glass_abre_o_app_na_empresa(admin_client, tenant):
    resp = admin_client.post(
        f'/baros-admin/tenants/{tenant.id}/break-glass/iniciar/',
        {'motivo': 'Cliente pediu ajuda no fechamento de estadia', 'abrir_app': '1'},
    )

    assert resp.status_code == 200
    assert resp.json()['redirect'] == '/inicio/'
    assert admin_client.session['active_tenant_id'] == str(tenant.id)
    assert AcessoSuporte.objects.filter(tenant=tenant, superadmin=admin_client.user).exists()


def test_onboarding_cria_empresa_pelo_formulario_json(admin_client):
    resp = admin_client.post('/baros-admin/onboarding/', data={
        'razao_social': 'Oxi Norte Ltda', 'nome_fantasia': 'Oxi Norte', 'cnpj': '45.723.174/0001-10',
        'modo_operacao': 'DISTRIBUIDORA', 'filial_nome': 'Matriz', 'uf': 'AM', 'municipio_ibge': '1302603',
        'plano': 'PRO', 'status_assinatura': 'TRIAL', 'valor_mensalidade_saas': '650.00',
        'dias_carencia': '5', 'limite_usuarios': '8', 'limite_cilindros': '800',
        'modulos': ['patrimonio', 'comercial', 'vendas'],
        'admin_email': 'admin@oxinorte.test', 'admin_senha': 'Provisoria-123',
    }, content_type='application/json')

    assert resp.status_code == 201, resp.content
    novo = Tenant.objects.get(nome_fantasia='Oxi Norte')
    assert novo.limite_cilindros == 800
    assert novo.modulo_vendas_ativo is True
    assert novo.modulo_logistica_ativo is False
