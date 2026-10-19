import os
import re
import time
import logging
from decimal import Decimal
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

FIPE_BASE_URL = "https://fipe.parallelum.com.br/api/v2"
FIPE_TIMEOUT = 5.0
FIPE_RETRIES = 2

# Cache TTLs
CACHE_TTL_MARCAS = 60 * 60 * 24 * 7      # 7 dias
CACHE_TTL_MODELOS = 60 * 60 * 24 * 7     # 7 dias
CACHE_TTL_ANOS = 60 * 60 * 24 * 7        # 7 dias
CACHE_TTL_VALOR = 60 * 60 * 24 * 30      # 30 dias

TIPO_MAP = {
    'caminhoes': 'trucks',
    'trucks': 'trucks',
    'carros': 'cars',
    'cars': 'cars',
    'motos': 'motorcycles',
    'motorcycles': 'motorcycles'
}

def normalizar_tipo(tipo):
    if not tipo:
        return 'trucks'
    tipo_clean = str(tipo).strip().lower()
    return TIPO_MAP.get(tipo_clean, 'trucks')

def get_fipe_headers():
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Baros/1.0 (Logistica)'
    }
    token = os.getenv('FIPE_API_TOKEN', '').strip()
    if token:
        headers['X-Subscription-Token'] = token
    return headers

def parse_fipe_valor(valor_str):
    """Converte 'R$ 123.456,78' em Decimal('123456.78')."""
    if not valor_str:
        return None
    if isinstance(valor_str, (int, float, Decimal)):
        return Decimal(str(valor_str))
    
    clean = re.sub(r'[^\d,]', '', str(valor_str)).replace(',', '.')
    try:
        return Decimal(clean)
    except Exception:
        return None

def _fipe_request_get(url):
    """
    Executa GET na API FIPE com timeout, retry limitado e tratamento de 429.
    Retorna uma tupla (sucesso: bool, dados: any, mensagem_erro: str).
    """
    headers = get_fipe_headers()
    tentativa = 0
    ultimo_erro = None

    while tentativa <= FIPE_RETRIES:
        try:
            resp = requests.get(url, headers=headers, timeout=FIPE_TIMEOUT)
            if resp.status_code == 200:
                try:
                    return True, resp.json(), ""
                except Exception as e:
                    return False, None, f"Erro ao decodificar resposta JSON da FIPE: {str(e)}"
            elif resp.status_code == 429:
                return False, None, "Limite diário da API FIPE atingido. Tente novamente mais tarde ou insira os dados manualmente."
            elif resp.status_code == 404:
                return False, None, "Registro não encontrado na base de dados da FIPE."
            else:
                ultimo_erro = f"API FIPE retornou status HTTP {resp.status_code}."
        except requests.exceptions.Timeout:
            ultimo_erro = "Tempo limite de conexão com a API FIPE esgotado (timeout)."
        except requests.exceptions.RequestException as e:
            ultimo_erro = f"Falha de rede ao consultar a API FIPE: {str(e)}"
        
        tentativa += 1
        if tentativa <= FIPE_RETRIES:
            time.sleep(0.3 * tentativa)

    logger.warning(f"Falha na consulta FIPE ({url}): {ultimo_erro}")
    return False, None, ultimo_erro or "Serviço da Tabela FIPE temporariamente indisponível."


def obter_marcas_fipe(tipo='caminhoes'):
    """
    Retorna a lista de marcas disponíveis para o tipo de veículo.
    Utiliza cache de 7 dias.
    """
    tipo_fipe = normalizar_tipo(tipo)
    cache_key = f"fipe_marcas_{tipo_fipe}"
    cached = cache.get(cache_key)
    if cached is not None:
        return True, cached, ""

    url = f"{FIPE_BASE_URL}/{tipo_fipe}/brands"
    sucesso, dados, erro = _fipe_request_get(url)
    if sucesso and isinstance(dados, list):
        cache.set(cache_key, dados, CACHE_TTL_MARCAS)
        return True, dados, ""
    return False, dados or [], erro


def obter_modelos_fipe(tipo, marca_codigo):
    """
    Retorna os modelos de uma marca específica.
    Utiliza cache de 7 dias.
    """
    tipo_fipe = normalizar_tipo(tipo)
    cache_key = f"fipe_modelos_{tipo_fipe}_{marca_codigo}"
    cached = cache.get(cache_key)
    if cached is not None:
        return True, cached, ""

    url = f"{FIPE_BASE_URL}/{tipo_fipe}/brands/{marca_codigo}/models"
    sucesso, dados, erro = _fipe_request_get(url)
    if sucesso and isinstance(dados, list):
        cache.set(cache_key, dados, CACHE_TTL_MODELOS)
        return True, dados, ""
    return False, dados or [], erro


def obter_anos_fipe(tipo, marca_codigo, modelo_codigo):
    """
    Retorna os anos/versões disponíveis para um modelo.
    Utiliza cache de 7 dias.
    """
    tipo_fipe = normalizar_tipo(tipo)
    cache_key = f"fipe_anos_{tipo_fipe}_{marca_codigo}_{modelo_codigo}"
    cached = cache.get(cache_key)
    if cached is not None:
        return True, cached, ""

    url = f"{FIPE_BASE_URL}/{tipo_fipe}/brands/{marca_codigo}/models/{modelo_codigo}/years"
    sucesso, dados, erro = _fipe_request_get(url)
    if sucesso and isinstance(dados, list):
        cache.set(cache_key, dados, CACHE_TTL_ANOS)
        return True, dados, ""
    return False, dados or [], erro


def obter_valor_fipe(tipo, marca_codigo, modelo_codigo, ano_codigo):
    """
    Retorna os detalhes e valor de mercado de um veículo específico por marca, modelo e ano.
    Utiliza cache de 30 dias.
    """
    tipo_fipe = normalizar_tipo(tipo)
    cache_key = f"fipe_valor_{tipo_fipe}_{marca_codigo}_{modelo_codigo}_{ano_codigo}"
    cached = cache.get(cache_key)
    if cached is not None:
        return True, cached, ""

    url = f"{FIPE_BASE_URL}/{tipo_fipe}/brands/{marca_codigo}/models/{modelo_codigo}/years/{ano_codigo}"
    sucesso, dados, erro = _fipe_request_get(url)
    if sucesso and isinstance(dados, dict):
        dados['valor_decimal'] = parse_fipe_valor(dados.get('price'))
        cache.set(cache_key, dados, CACHE_TTL_VALOR)
        return True, dados, ""
    return False, None, erro


def obter_valor_por_codigo_fipe(tipo, fipe_codigo, ano_codigo=None):
    """
    Consulta o valor diretamente pelo Código FIPE do veículo.
    Se ano_codigo não for informado, busca o primeiro ano disponível.
    """
    tipo_fipe = normalizar_tipo(tipo)
    codigo_clean = re.sub(r'[^\w]', '', str(fipe_codigo))
    
    if not ano_codigo:
        url_anos = f"{FIPE_BASE_URL}/{tipo_fipe}/{codigo_clean}/years"
        sucesso, anos, erro = _fipe_request_get(url_anos)
        if not sucesso or not anos:
            return False, None, erro or "Nenhum ano encontrado para este código FIPE."
        ano_codigo = anos[0].get('code')

    cache_key = f"fipe_cod_{tipo_fipe}_{codigo_clean}_{ano_codigo}"
    cached = cache.get(cache_key)
    if cached is not None:
        return True, cached, ""

    url_valor = f"{FIPE_BASE_URL}/{tipo_fipe}/{codigo_clean}/years/{ano_codigo}"
    sucesso, dados, erro = _fipe_request_get(url_valor)
    if sucesso and isinstance(dados, dict):
        dados['valor_decimal'] = parse_fipe_valor(dados.get('price'))
        cache.set(cache_key, dados, CACHE_TTL_VALOR)
        return True, dados, ""
    return False, None, erro
