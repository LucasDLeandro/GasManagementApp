"""
Configuração central do Portal B2B (Sprint 12B).

Todos os parâmetros têm default seguro e podem ser sobrescritos em config/settings.py
com o prefixo ``B2B_``. Mantê-los aqui evita números mágicos espalhados pelo código.
"""
from django.conf import settings

# Prefixo de URL do portal: tudo que começa com ele usa URLConf, cookie e sessão próprios.
PORTAL_PREFIX = '/portal-b2b/'

# Prefixo das chaves de sessão do portal. O middleware de sessão rejeita, em cada lado,
# cookies que carreguem a chave do outro (isolamento entre sistema interno e portal).
SESSION_KEY_PREFIX = 'b2b_'


def _get(nome: str, padrao):
    return getattr(settings, nome, padrao)


def cookie_sessao() -> str:
    return _get('B2B_SESSION_COOKIE_NAME', 'b2b_sessionid')


def sessao_inatividade_segundos() -> int:
    return int(_get('B2B_SESSION_IDLE_SECONDS', 30 * 60))


def cookie_seguro() -> bool:
    return bool(_get('B2B_SESSION_COOKIE_SECURE', not settings.DEBUG))


def convite_validade_horas() -> int:
    return int(_get('B2B_INVITE_VALID_HOURS', 72))


def download_validade_segundos() -> int:
    """Validade das URLs assinadas de download: poucos minutos."""
    return int(_get('B2B_DOWNLOAD_URL_TTL_SECONDS', 5 * 60))


def termo_versao() -> str:
    return str(_get('B2B_TERMO_VERSAO', '2026-10'))


def max_falhas_login() -> int:
    return int(_get('B2B_MAX_FALHAS_LOGIN', 5))


def bloqueio_minutos() -> int:
    return int(_get('B2B_BLOQUEIO_MINUTOS', 15))


def senha_tamanho_minimo() -> int:
    return int(_get('B2B_SENHA_MIN_CARACTERES', 10))


def reteste_alerta_dias() -> int:
    """Janela (dias) em que o vencimento de reteste passa a ser sinalizado (decisão registrada)."""
    return int(_get('B2B_RETESTE_ALERTA_DIAS', 30))


def reposicao_max_itens() -> int:
    return int(_get('B2B_REPOSICAO_MAX_ITENS', 20))


def reposicao_max_quantidade() -> int:
    return int(_get('B2B_REPOSICAO_MAX_QUANTIDADE', 100))


def throttle_rates() -> dict:
    """Limites no formato (requisições, janela em segundos)."""
    padrao = {
        'usuario': (120, 60),       # consultas autenticadas por usuário
        'ip': (240, 60),            # consultas por IP (inclui anônimos)
        'login_ip': (10, 60),       # tentativas de login por IP
        'login_usuario': (10, 300), # tentativas de login por nome de usuário
        'mfa_usuario': (10, 300),   # tentativas de TOTP por usuário
        'convite_ip': (20, 300),    # aceite de convites por IP
        'download_usuario': (30, 60),
        'escrita_usuario': (30, 60),
    }
    padrao.update(_get('B2B_THROTTLE_RATES', {}))
    return padrao


def base_url() -> str:
    return str(_get('B2B_PORTAL_BASE_URL', 'http://localhost:8000')).rstrip('/')


# Faixas de notificação (dias). Reteste: faixas em dias restantes; estadia: marcos em dias
# excedentes à carência; boleto: antecedência máxima do vencimento.
NOTIF_RETESTE_FAIXAS = (30, 15, 7, 0)
NOTIF_ESTADIA_MARCOS = (0, 15, 30, 60, 90)
NOTIF_BOLETO_ANTECEDENCIA_DIAS = 3
