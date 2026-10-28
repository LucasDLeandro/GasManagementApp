"""
Módulo de Autenticação, Identidade e Segurança do Portal B2B (Sprint 12B).

Implementa:
- PortalB2BBackend: autenticação dedicada para usuários do portal.
- Política de complexidade de senhas (mínimo 10 caracteres, maiúscula, minúscula, dígito).
- Bloqueio temporário após 5 falhas consecutivas (15 min).
- Convites por e-mail com hash SHA-256 e validade de 72 horas.
- Suporte a MFA TOTP (django-otp) obrigatório para o papel FINANCEIRO.
- Registro de auditoria em LogAcessoB2B para todos os eventos de autenticação.
"""
import re
import secrets
import hashlib
from datetime import timedelta
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
import django_otp

from clientes.models import UsuarioClienteB2B
from core.tenancy import tenant_context
from portal_b2b.conf import (
    max_falhas_login,
    bloqueio_minutos,
    senha_tamanho_minimo,
    convite_validade_horas,
    termo_versao,
)
from portal_b2b.models import LogAcessoB2B, ConviteB2B

User = get_user_model()


def get_client_ip(request) -> Optional[str]:
    if not request:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def registrar_log_acesso(
    evento: str,
    tenant,
    cliente=None,
    usuario_b2b=None,
    usuario_nome: str = '',
    recurso_tipo: str = '',
    recurso_id: str = '',
    request=None,
    ip: Optional[str] = None,
    user_agent: str = '',
    detalhes: Optional[dict] = None
):
    """Cria uma linha na trilha append-only de auditoria do portal B2B."""
    if request:
        ip = ip or get_client_ip(request)
        user_agent = user_agent or request.META.get('HTTP_USER_AGENT', '')[:255]

    LogAcessoB2B.unscoped.create(
        tenant=tenant,
        cliente=cliente or (usuario_b2b.cliente if usuario_b2b else None),
        usuario_b2b=usuario_b2b,
        usuario_nome=usuario_nome or (usuario_b2b.user.username if (usuario_b2b and usuario_b2b.user) else ''),
        evento=evento,
        recurso_tipo=recurso_tipo,
        recurso_id=str(recurso_id) if recurso_id else '',
        ip=ip,
        user_agent=user_agent[:255] if user_agent else '',
        detalhes=detalhes or {}
    )


def validar_politica_senha(senha: str) -> None:
    """
    Valida a política de senhas do Portal B2B:
    - Mínimo de 10 caracteres (configurável em conf.py).
    - Pelo menos uma letra maiúscula.
    - Pelo menos uma letra minúscula.
    - Pelo menos um número ou dígito.
    """
    min_len = senha_tamanho_minimo()
    erros = []
    if len(senha) < min_len:
        erros.append(f"A senha deve conter no mínimo {min_len} caracteres.")
    if not re.search(r'[A-Z]', senha):
        erros.append("A senha deve conter ao menos uma letra maiúscula.")
    if not re.search(r'[a-z]', senha):
        erros.append("A senha deve conter ao menos uma letra minúscula.")
    if not re.search(r'\d', senha):
        erros.append("A senha deve conter ao menos um número.")
    if erros:
        raise ValidationError(erros)


class PortalB2BBackend(ModelBackend):
    """
    Backend de autenticação exclusivo do Portal B2B.

    Autentica apenas usuários com vínculo ativo em UsuarioClienteB2B, controlando
    tentativas falhas consecutivas e bloqueio temporário por tempo.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or not password:
            return None

        # Busca pelo username ou pelo email
        user = User.objects.filter(models_q_username_or_email(username)).first()
        if not user:
            return None

        vinculo: Optional[UsuarioClienteB2B] = UsuarioClienteB2B.unscoped.filter(user=user).select_related('cliente', 'tenant').first()
        if not vinculo:
            # Não é usuário de cliente B2B: rejeita
            return None

        tenant = vinculo.tenant
        ip = get_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')[:255] if request else ''

        with tenant_context(tenant):
            # 1. Verifica revogação de acesso
            if vinculo.acesso_revogado_em is not None or not vinculo.ativo:
                registrar_log_acesso(
                    'ACESSO_NEGADO',
                    tenant=tenant,
                    cliente=vinculo.cliente,
                    usuario_b2b=vinculo,
                    usuario_nome=user.username,
                    request=request,
                    detalhes={'motivo': 'Acesso revogado ou inativo'}
                )
                return None

            # 2. Verifica bloqueio temporário por tentativas falhas
            if vinculo.esta_bloqueado:
                registrar_log_acesso(
                    'LOGIN_BLOQUEADO',
                    tenant=tenant,
                    cliente=vinculo.cliente,
                    usuario_b2b=vinculo,
                    usuario_nome=user.username,
                    request=request,
                    detalhes={'bloqueado_ate': vinculo.bloqueado_ate.isoformat()}
                )
                return None

            # 3. Valida credenciais de senha
            if not user.check_password(password):
                vinculo.tentativas_falhas += 1
                detalhes = {'tentativa': vinculo.tentativas_falhas}
                if vinculo.tentativas_falhas >= max_falhas_login():
                    vinculo.bloqueado_ate = timezone.now() + timedelta(minutes=bloqueio_minutos())
                    detalhes['bloqueado_minutos'] = bloqueio_minutos()
                    detalhes['bloqueado_ate'] = vinculo.bloqueado_ate.isoformat()
                vinculo.save(update_fields=['tentativas_falhas', 'bloqueado_ate', 'atualizado_em'])

                registrar_log_acesso(
                    'LOGIN_FALHA',
                    tenant=tenant,
                    cliente=vinculo.cliente,
                    usuario_b2b=vinculo,
                    usuario_nome=user.username,
                    request=request,
                    detalhes=detalhes
                )
                return None

            # 4. Verifica se o usuário pode autenticar (ativo no Django)
            if not self.user_can_authenticate(user):
                return None

            # 5. Sucesso: limpa tentativas falhas e registra último acesso
            vinculo.tentativas_falhas = 0
            vinculo.bloqueado_ate = None
            vinculo.ultimo_acesso = timezone.now()
            vinculo.save(update_fields=['tentativas_falhas', 'bloqueado_ate', 'ultimo_acesso', 'atualizado_em'])

            registrar_log_acesso(
                'LOGIN_OK',
                tenant=tenant,
                cliente=vinculo.cliente,
                usuario_b2b=vinculo,
                usuario_nome=user.username,
                request=request
            )
            return user

    def user_can_authenticate(self, user):
        if not super().user_can_authenticate(user):
            return False
        vinculo = UsuarioClienteB2B.unscoped.filter(user=user).first()
        if not vinculo or not vinculo.ativo or vinculo.acesso_revogado_em is not None:
            return False
        return True


def models_q_username_or_email(identificador: str):
    from django.db.models import Q
    return Q(username__iexact=identificador) | Q(email__iexact=identificador)


# ==============================================================================
# Convites e Ciclo de Vida de Senha
# ==============================================================================

def hash_token(token: str) -> str:
    """Calcula o hash SHA-256 do token em claro."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def gerar_convite_b2b(usuario_b2b: UsuarioClienteB2B, criado_por=None, request=None) -> Tuple[ConviteB2B, str]:
    """
    Gera um novo convite de ativação para o usuário B2B.
    Retorna a instância de ConviteB2B e o token em claro (que será enviado por e-mail).
    """
    with tenant_context(usuario_b2b.tenant):
        token_claro = secrets.token_urlsafe(32)
        token_sha = hash_token(token_claro)
        validade_horas = convite_validade_horas()
        expira_em = timezone.now() + timedelta(hours=validade_horas)

        convite = ConviteB2B.objects.create(
            tenant=usuario_b2b.tenant,
            usuario_b2b=usuario_b2b,
            email_destino=usuario_b2b.user.email or usuario_b2b.user.username,
            token_hash=token_sha,
            expira_em=expira_em,
            criado_por=criado_por
        )

        registrar_log_acesso(
            'CONVITE_EMITIDO',
            tenant=usuario_b2b.tenant,
            cliente=usuario_b2b.cliente,
            usuario_b2b=usuario_b2b,
            recurso_tipo='ConviteB2B',
            recurso_id=str(convite.pk),
            request=request,
            detalhes={'email': convite.email_destino, 'expira_em': expira_em.isoformat()}
        )
        return convite, token_claro


def aceitar_convite_b2b(
    token_claro: str,
    nova_senha: str,
    request=None
) -> UsuarioClienteB2B:
    """
    Valida e consome um convite de ativação, definindo a senha do usuário.
    Garante uso único e política estrita de complexidade de senha.
    """
    token_sha = hash_token(token_claro)
    convite = ConviteB2B.unscoped.filter(token_hash=token_sha).select_related('usuario_b2b', 'usuario_b2b__user', 'tenant').first()

    if not convite or not convite.esta_valido:
        raise ValidationError("Convite inválido, já utilizado ou expirado.")

    validar_politica_senha(nova_senha)

    usuario_b2b = convite.usuario_b2b
    user = usuario_b2b.user

    with tenant_context(convite.tenant):
        user.set_password(nova_senha)
        user.save(update_fields=['password'])

        agora = timezone.now()
        usuario_b2b.senha_alterada_em = agora
        usuario_b2b.tentativas_falhas = 0
        usuario_b2b.bloqueado_ate = None
        usuario_b2b.save(update_fields=['senha_alterada_em', 'tentativas_falhas', 'bloqueado_ate', 'atualizado_em'])

        convite.aceito_em = agora
        convite.save(update_fields=['aceito_em'])

        registrar_log_acesso(
            'CONVITE_ACEITO',
            tenant=convite.tenant,
            cliente=usuario_b2b.cliente,
            usuario_b2b=usuario_b2b,
            recurso_tipo='ConviteB2B',
            recurso_id=str(convite.pk),
            request=request
        )
        return usuario_b2b


# ==============================================================================
# MFA (TOTP) com django-otp
# ==============================================================================

def tem_mfa_configurada(user) -> bool:
    """Retorna True se o usuário possui dispositivo TOTP confirmado."""
    if not user or not user.is_authenticated:
        return False
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def configurar_totp(user, nome_dispositivo="Portal B2B") -> Tuple[TOTPDevice, str]:
    """
    Cria (ou reutiliza pendente de confirmação) dispositivo TOTP para o usuário.
    Retorna o dispositivo e o URI otpauth (para geração de QR Code).
    """
    # Remove dispositivos não confirmados prévios
    TOTPDevice.objects.filter(user=user, confirmed=False).delete()

    dispositivo = TOTPDevice.objects.create(
        user=user,
        name=nome_dispositivo,
        confirmed=False
    )
    return dispositivo, dispositivo.config_url


def confirmar_dispositivo_totp(user, token: str, request=None) -> bool:
    """Confirma um dispositivo TOTP recém-configurado via código informado."""
    dispositivo = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if not dispositivo:
        return False
    if dispositivo.verify_token(token):
        dispositivo.confirmed = True
        dispositivo.save(update_fields=['confirmed'])
        vinculo = UsuarioClienteB2B.unscoped.filter(user=user).first()
        if vinculo:
            with tenant_context(vinculo.tenant):
                registrar_log_acesso(
                    'MFA_CONFIGURADA',
                    tenant=vinculo.tenant,
                    cliente=vinculo.cliente,
                    usuario_b2b=vinculo,
                    request=request
                )
        return True
    return False


def verificar_totp(user, token: str, request=None) -> bool:
    """Verifica se o token TOTP informado é válido para os dispositivos confirmados do usuário."""
    if not user or not user.is_authenticated:
        return False
    vinculo = UsuarioClienteB2B.unscoped.filter(user=user).first()
    tenant = vinculo.tenant if vinculo else None

    for dev in TOTPDevice.objects.filter(user=user, confirmed=True):
        if dev.verify_token(token):
            if vinculo and tenant:
                with tenant_context(tenant):
                    registrar_log_acesso(
                        'MFA_OK',
                        tenant=tenant,
                        cliente=vinculo.cliente,
                        usuario_b2b=vinculo,
                        request=request
                    )
            return True

    if vinculo and tenant:
        with tenant_context(tenant):
            registrar_log_acesso(
                'MFA_FALHA',
                tenant=tenant,
                cliente=vinculo.cliente,
                usuario_b2b=vinculo,
                request=request
            )
    return False


# ==============================================================================
# Termo de Uso e Revogação
# ==============================================================================

def aceitar_termo_b2b(usuario_b2b: UsuarioClienteB2B, versao: Optional[str] = None, request=None) -> None:
    with tenant_context(usuario_b2b.tenant):
        versao_aplicada = versao or termo_versao()
        usuario_b2b.termo_aceito_em = timezone.now()
        usuario_b2b.termo_versao = versao_aplicada
        usuario_b2b.save(update_fields=['termo_aceito_em', 'termo_versao', 'atualizado_em'])

        registrar_log_acesso(
            'TERMO_ACEITO',
            tenant=usuario_b2b.tenant,
            cliente=usuario_b2b.cliente,
            usuario_b2b=usuario_b2b,
            request=request,
            detalhes={'versao': versao_aplicada}
        )


def revogar_acesso_b2b(usuario_b2b: UsuarioClienteB2B, revogado_por=None, request=None) -> None:
    with tenant_context(usuario_b2b.tenant):
        usuario_b2b.ativo = False
        usuario_b2b.acesso_revogado_em = timezone.now()
        usuario_b2b.revogado_por = revogado_por
        usuario_b2b.save(update_fields=['ativo', 'acesso_revogado_em', 'revogado_por', 'atualizado_em'])

        registrar_log_acesso(
            'ACESSO_REVOGADO',
            tenant=usuario_b2b.tenant,
            cliente=usuario_b2b.cliente,
            usuario_b2b=usuario_b2b,
            request=request,
            detalhes={'revogado_por': revogado_por.username if revogado_por else 'sistema'}
        )
