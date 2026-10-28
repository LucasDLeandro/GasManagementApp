"""
Limitação de taxa (throttling) do Portal B2B por usuário e por IP (Sprint 12B).

Janela fixa sobre o cache do Django. Usada tanto pelas views DRF (throttles.py) quanto
pelas páginas HTML (login, MFA, aceite de convite), garantindo uma única implementação.
"""
import hashlib
import time
from dataclasses import dataclass

from django.core.cache import cache

from portal_b2b import conf


@dataclass(frozen=True)
class ResultadoLimite:
    permitido: bool
    restantes: int
    reiniciar_em: int  # segundos até a janela reiniciar


def _chave(escopo: str, identificador: str) -> str:
    h = hashlib.sha256(str(identificador).encode('utf-8')).hexdigest()[:32]
    return f"b2b:rl:{escopo}:{h}"


def consumir(escopo: str, identificador: str) -> ResultadoLimite:
    """Registra uma requisição na janela do escopo e informa se ainda está dentro do limite."""
    limite, janela = conf.throttle_rates()[escopo]
    chave = _chave(escopo, identificador)
    agora = int(time.time())

    # Janela fixa alinhada ao relógio: reinício determinístico e sem estado extra.
    inicio_janela = agora - (agora % janela)
    chave_janela = f"{chave}:{inicio_janela}"
    cache.add(chave_janela, 0, timeout=janela + 1)
    try:
        total = cache.incr(chave_janela)
    except ValueError:  # expirou entre add e incr
        cache.set(chave_janela, 1, timeout=janela + 1)
        total = 1

    reiniciar_em = max(1, inicio_janela + janela - agora)
    return ResultadoLimite(
        permitido=total <= limite,
        restantes=max(0, limite - total),
        reiniciar_em=reiniciar_em,
    )


def excedido(escopo: str, identificador: str) -> ResultadoLimite:
    """Alias semântico para uso em views HTML: consome e devolve o resultado."""
    return consumir(escopo, identificador)


def resetar(escopo: str, identificador: str) -> None:
    """Remove contadores da janela corrente (usado após autenticação bem-sucedida)."""
    _, janela = conf.throttle_rates()[escopo]
    agora = int(time.time())
    inicio_janela = agora - (agora % janela)
    cache.delete(f"{_chave(escopo, identificador)}:{inicio_janela}")


def ip_do_cliente(request) -> str:
    """
    IP de origem. Só confia em X-Forwarded-For quando o deploy declara proxy reverso confiável
    (B2B_TRUST_X_FORWARDED_FOR=True); caso contrário, um cliente poderia forjar o cabeçalho
    para escapar do throttling por IP.
    """
    from django.conf import settings
    if getattr(settings, 'B2B_TRUST_X_FORWARDED_FOR', False):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or '0.0.0.0'


class RateLimitExcedido(Exception):
    """Exceção levantada quando um cliente ou IP excede a taxa máxima permitida."""
    pass


def verificar_rate_limit(request, tipo: str = 'usuario', usuario_id=None) -> None:
    """Verifica e consome limite de taxa. Levanta RateLimitExcedido se ultrapassar."""
    from django.conf import settings
    # Em ambiente de testes, não bloqueia execuções automáticas
    if getattr(settings, 'TESTING', False) or getattr(request, '_dont_enforce_ratelimit', False):
        return

    identificador = str(usuario_id) if usuario_id else ip_do_cliente(request)
    escopo = tipo if tipo in conf.throttle_rates() else 'usuario'
    resultado = consumir(escopo, identificador)
    if not resultado.permitido:
        raise RateLimitExcedido(
            f"Limite de requisições excedido para {escopo}. Tente novamente em {resultado.reiniciar_em} segundos."
        )
