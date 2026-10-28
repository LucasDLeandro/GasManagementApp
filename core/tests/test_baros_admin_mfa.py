"""
Login do /baros-admin/ com MFA TOTP obrigatório (Plano de Correção, tarefa 0.3.1).

Garante que nenhum superusuário entra no backoffice sem um código TOTP verificado:
nem quando ainda não cadastrou o autenticador, nem com DEBUG desligado.
"""
import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.models import LogAuditoriaSaaS

SENHA = 'Senha-Forte-Backoffice-123'


def _codigo(device: TOTPDevice) -> str:
    return str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift)).zfill(device.digits)


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        username='dono.baros', email='dono@baros.test', password=SENHA,
    )


@pytest.fixture
def client(settings):
    # A brecha antiga dependia de DEBUG; os testes rodam como em produção.
    settings.DEBUG = False
    return Client()


def _login(client, otp_token=''):
    return client.post('/baros-admin/login/', {
        'username': 'dono.baros', 'password': SENHA, 'otp_token': otp_token,
    })


class TestLoginSemAutenticadorCadastrado:
    def test_qualquer_codigo_nao_autentica(self, client, superuser):
        resp = _login(client, otp_token='123456')

        assert resp.status_code == 302
        assert resp.url == '/baros-admin/mfa/cadastro/'
        assert '_auth_user_id' not in client.session
        assert client.get('/baros-admin/').status_code == 302

    def test_sem_codigo_tambem_vai_para_cadastro(self, client, superuser):
        resp = _login(client)

        assert resp.url == '/baros-admin/mfa/cadastro/'
        assert '_auth_user_id' not in client.session

    def test_cadastro_exige_senha_validada_antes(self, client, superuser):
        resp = client.get('/baros-admin/mfa/cadastro/')

        assert resp.status_code == 302
        assert resp.url == '/baros-admin/login/'

    def test_cadastro_mostra_qr_e_rejeita_codigo_errado(self, client, superuser):
        _login(client)

        pagina = client.get('/baros-admin/mfa/cadastro/')
        assert pagina.status_code == 200
        assert b'<svg' in pagina.content

        resp = client.post('/baros-admin/mfa/cadastro/', {'otp_token': '000000'})
        assert resp.status_code == 200
        assert '_auth_user_id' not in client.session
        assert not TOTPDevice.objects.filter(user=superuser, confirmed=True).exists()

    def test_cadastro_com_codigo_valido_confirma_e_entra(self, client, superuser):
        _login(client)
        client.get('/baros-admin/mfa/cadastro/')
        device = TOTPDevice.objects.get(user=superuser, confirmed=False)

        resp = client.post('/baros-admin/mfa/cadastro/', {'otp_token': _codigo(device)})

        assert resp.status_code == 302
        assert resp.url == '/baros-admin/'
        device.refresh_from_db()
        assert device.confirmed
        assert client.session['baros_admin_mfa_verified'] is True
        assert LogAuditoriaSaaS.objects.filter(usuario=superuser, acao='MFA_CADASTRADO').exists()

    def test_cadastro_expira_em_10_minutos(self, client, superuser):
        _login(client)
        sessao = client.session
        sessao['baros_admin_mfa_pendente']['desde'] = time.time() - 601
        sessao.save()

        resp = client.get('/baros-admin/mfa/cadastro/')

        assert resp.status_code == 302
        assert resp.url == '/baros-admin/login/'


class TestLoginComAutenticadorCadastrado:
    @pytest.fixture
    def device(self, superuser):
        return TOTPDevice.objects.create(user=superuser, name='Baros Admin', confirmed=True)

    def test_codigo_valido_entra(self, client, superuser, device):
        resp = _login(client, otp_token=_codigo(device))

        assert resp.status_code == 302
        assert resp.url == '/baros-admin/'
        assert client.session['baros_admin_mfa_verified'] is True

    def test_codigo_invalido_nao_entra(self, client, superuser, device):
        resp = _login(client, otp_token='000000')

        assert resp.status_code == 200
        assert '_auth_user_id' not in client.session

    def test_sem_codigo_nao_entra(self, client, superuser, device):
        resp = _login(client)

        assert resp.status_code == 200
        assert '_auth_user_id' not in client.session
