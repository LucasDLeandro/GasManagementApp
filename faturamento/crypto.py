from django.conf import settings
from cryptography.fernet import Fernet

def get_fernet_instance() -> Fernet:
    """
    Retorna a instância configurada do Fernet para criptografia simétrica de alta segurança.
    """
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
    if not key:
        key = 'mvI3kOqWn0Rm4IAEw7MWZ8eWJZUJb7RU2moN0PGYqjo='
    if isinstance(key, str):
        key = key.encode('utf-8')
    return Fernet(key)

def encrypt_secret(raw_val: str) -> str:
    """
    Criptografa texto puro usando chave simétrica Fernet.
    """
    if not raw_val:
        return ""
    f = get_fernet_instance()
    return f.encrypt(raw_val.encode('utf-8')).decode('utf-8')

def decrypt_secret(cipher_val: str) -> str:
    """
    Descriptografa valor cifrado. Retorna o valor caso já seja texto plano (resiliência).
    """
    if not cipher_val:
        return ""
    try:
        f = get_fernet_instance()
        return f.decrypt(cipher_val.encode('utf-8')).decode('utf-8')
    except Exception:
        return cipher_val
