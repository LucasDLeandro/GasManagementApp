import copy
import re
from typing import Any, Dict, List, Union
from django.conf import settings
from cryptography.fernet import Fernet

SENSITIVE_FIELD_NAMES = {
    'senha',
    'password',
    'token',
    'secret',
    'api_token',
    'api_key',
    'certificado',
    'certificado_ref',
    'certificado_pfx',
    'senha_certificado',
    'private_key',
    'chave_privada',
    'credenciais',
    'credenciais_gateway_cifradas',
    'authorization',
}


def get_fiscal_fernet_instance() -> Fernet:
    """
    Retorna a instância configurada do Fernet para criptografia simétrica de dados fiscais sensíveis.
    A chave NUNCA é lida do banco de dados: vem exclusivamente de settings/ambiente (Task 2).
    """
    key = getattr(settings, 'FISCAL_ENCRYPTION_KEY', None)
    if not key:
        key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
    if not key:
        # Chave padrão de segurança para ambiente de teste / homologação
        key = 'mvI3kOqWn0Rm4IAEw7MWZ8eWJZUJb7RU2moN0PGYqjo='

    if isinstance(key, str):
        key = key.encode('utf-8')
    return Fernet(key)


def encrypt_fiscal_secret(raw_val: str) -> str:
    """Criptografa texto puro usando chave simétrica Fernet."""
    if not raw_val:
        return ""
    f = get_fiscal_fernet_instance()
    return f.encrypt(raw_val.encode('utf-8')).decode('utf-8')


def decrypt_fiscal_secret(cipher_val: str) -> str:
    """Descriptografa valor cifrado. Retorna o valor original caso já seja texto plano (resiliência)."""
    if not cipher_val:
        return ""
    try:
        f = get_fiscal_fernet_instance()
        return f.decrypt(cipher_val.encode('utf-8')).decode('utf-8')
    except Exception:
        return cipher_val


def sanitize_log_data(data: Any) -> Any:
    """
    Sanitiza recursivamente dicionários, listas e strings para garantir
    que senhas, chaves de API, certificados e segredos nunca apareçam em logs (Task 10).
    """
    if data is None:
        return None

    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in SENSITIVE_FIELD_NAMES):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = sanitize_log_data(v)
        return sanitized

    if isinstance(data, (list, tuple, set)):
        return [sanitize_log_data(item) for item in data]

    if isinstance(data, str):
        # Reduz eventuais certificados base64 ou tokens extensos
        if len(data) > 300 and ('MII' in data or 'token' in data.lower()):
            return "***REDACTED_LARGE_PAYLOAD***"
        return data

    return data
