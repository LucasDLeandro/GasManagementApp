"""
Módulo de Integração com Dados Abertos da ANP (Agência Nacional do Petróleo, Gás Natural e Biocombustíveis).
Série Histórica do Levantamento de Preços de Combustíveis (LPC) - Licença Creative Commons CC-BY.

Documentação de Formato e Descoberta dos Arquivos da ANP:
1. Encoding típico: UTF-8 com BOM (utf-8-sig) ou ISO-8859-1 (latin-1).
2. Delimitador de colunas: Ponto e vírgula (;) ou vírgula (,).
3. Separador decimal de valores: Vírgula (ex: 5,89 ou 5,899).
4. Formato de datas: DD/MM/YYYY (ex: 15/10/2026).
5. Estrutura de microdados por posto revendedor:
   - "Regiao - Sigla": Região geográfica (CO, SE, S, NE, N)
   - "Estado - Sigla": UF (GO, DF, SP, etc.)
   - "Municipio": Nome do município
   - "Produto": Nome do produto (GASOLINA, ETANOL HIDRATADO, DIESEL S10, OLEO DIESEL, GNV, GLP)
   - "Data da Coleta": Data da pesquisa no posto
   - "Valor de Venda": Preço na bomba cobrado do consumidor
   - "Unidade de Medida": R$ / litro, R$ / m3, R$ / 13 kg
"""

import io
import re
import csv
import math
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError

from logistica.models import PrecoCombustivelReferencia

logger = logging.getLogger(__name__)

# URLs oficiais padrão (configuráveis via settings ou variáveis de ambiente)
DEFAULT_ANP_URLS = {
    'DIESEL_GNV': getattr(settings, 'ANP_URL_DIESEL_GNV', 'https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/ds-2026-02.csv'),
    'GASOLINA_ETANOL': getattr(settings, 'ANP_URL_GASOLINA_ETANOL', 'https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/ge-2026-02.csv'),
    'GLP': getattr(settings, 'ANP_URL_GLP', 'https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/glp-2026-02.csv'),
}

MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024  # Teto de 60 MB por download para evitar exaustão de memória


def normalizar_nome_produto_anp(nome_cru):
    """
    Normaliza a descrição do combustível retornada pela ANP para o choices interno do sistema.
    """
    if not nome_cru:
        return None
    
    # Remove acentos e converte para maiúsculas
    txt = nome_cru.strip().upper()
    txt = re.sub(r'[ÁÀÃÂ]', 'A', txt)
    txt = re.sub(r'[ÉÈÊ]', 'E', txt)
    txt = re.sub(r'[ÍÌÎ]', 'I', txt)
    txt = re.sub(r'[ÓÒÕÔ]', 'O', txt)
    txt = re.sub(r'[ÚÙÛ]', 'U', txt)
    txt = re.sub(r'[Ç]', 'C', txt)

    if 'DIESEL' in txt:
        if 'S10' in txt or 'S-10' in txt:
            return 'Diesel S10'
        return 'Diesel S500'
    elif 'GASOLINA' in txt:
        if 'ADITIVADA' in txt:
            return 'Gasolina Comum'  # Referência base
        return 'Gasolina Comum'
    elif 'ETANOL' in txt or 'ALCOOL' in txt:
        return 'Etanol'
    elif 'GNV' in txt or 'GAS NATURAL' in txt:
        return 'GNV'
    elif 'GLP' in txt or 'GAS LIQUEFEITO' in txt:
        return 'GLP'

    return None


def parse_decimal_brasileiro(valor_str):
    """
    Converte string numérica brasileira ('5,499' ou '5.499') para Decimal com segurança.
    """
    if not valor_str:
        return None
    limpo = str(valor_str).strip().replace('R$', '').replace(' ', '')
    if not limpo:
        return None
    # Substitui separador de milhar se houver e troca vírgula por ponto
    if ',' in limpo:
        limpo = limpo.replace('.', '').replace(',', '.')
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return None


def parse_data_anp(data_str):
    """
    Converte datas nos formatos comuns da ANP (DD/MM/YYYY ou YYYY-MM-DD).
    """
    if not data_str:
        return None
    d = str(data_str).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            pass
    return None


def baixar_csv_anp(url, max_bytes=MAX_DOWNLOAD_BYTES, timeout=15):
    """
    Realiza download resiliente do arquivo CSV da ANP com timeout, retries curtos e limite de tamanho.
    Retorna o conteúdo binário baixado.
    """
    tentativas = 0
    ultimo_erro = None

    while tentativas < 3:
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code == 200:
                conteudo = io.BytesIO()
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValidationError(f"Arquivo da ANP excedeu o limite máximo de segurança de {max_bytes // (1024*1024)} MB.")
                    conteudo.write(chunk)
                conteudo.seek(0)
                return conteudo.getvalue()
            else:
                ultimo_erro = f"HTTP {resp.status_code}"
        except requests.exceptions.RequestException as e:
            ultimo_erro = str(e)

        tentativas += 1

    raise ConnectionError(f"Falha ao descarregar base da ANP ({url}): {ultimo_erro}")


def processar_linhas_csv_anp(linhas_reader, uf_filtro=None, municipio_filtro=None, tenant=None, dry_run=False):
    """
    Processa um iterador de linhas CSV de microdados da ANP, agregando estatísticas por
    (Produto, UF, Município) e (Produto, UF - Média Estadual), persistindo em PrecoCombustivelReferencia.
    """
    stats = {
        'criados': 0,
        'atualizados': 0,
        'ignorados': 0,
        'linhas_processadas': 0,
        'erros': []
    }

    if not tenant:
        raise ValueError("Tenant obrigatório para escopo dos preços de referência.")

    # Agrupadores em memória: chave -> lista de preços e datas
    # chave: (produto, uf, municipio)
    dados_municipio = {}
    # chave: (produto, uf)
    dados_uf = {}

    for num_linha, row in enumerate(linhas_reader, start=2):
        stats['linhas_processadas'] += 1
        
        # Mapeia colunas por nomes flexíveis
        estado = (row.get('Estado - Sigla') or row.get('ESTADO') or row.get('UF') or '').strip().upper()
        municipio = (row.get('Municipio') or row.get('MUNICIPIO') or row.get('Cidade') or '').strip()
        produto_raw = (row.get('Produto') or row.get('PRODUTO') or row.get('Combustivel') or '').strip()
        valor_raw = row.get('Valor de Venda') or row.get('PRECO_MEDIO_REVENDA') or row.get('PRECO_MEDIO') or row.get('Valor')
        data_raw = row.get('Data da Coleta') or row.get('DATA_COLETA') or row.get('DATA_FINAL') or row.get('Data')

        if uf_filtro and estado != uf_filtro.strip().upper():
            stats['ignorados'] += 1
            continue
        if municipio_filtro and municipio.lower() != municipio_filtro.strip().lower():
            stats['ignorados'] += 1
            continue

        produto_normalizado = normalizar_nome_produto_anp(produto_raw)
        if not produto_normalizado or not estado:
            stats['ignorados'] += 1
            continue

        preco = parse_decimal_brasileiro(valor_raw)
        if not preco or preco <= Decimal('0'):
            stats['ignorados'] += 1
            continue

        data_coleta = parse_data_anp(data_raw) or timezone.localdate()

        # Agrega no Município
        if municipio:
            chave_mun = (produto_normalizado, estado, municipio.upper())
            if chave_mun not in dados_municipio:
                dados_municipio[chave_mun] = {'precos': [], 'datas': []}
            dados_municipio[chave_mun]['precos'].append(preco)
            dados_municipio[chave_mun]['datas'].append(data_coleta)

        # Agrega na Média Estadual
        chave_uf = (produto_normalizado, estado, '')
        if chave_uf not in dados_uf:
            dados_uf[chave_uf] = {'precos': [], 'datas': []}
        dados_uf[chave_uf]['precos'].append(preco)
        dados_uf[chave_uf]['datas'].append(data_coleta)

    # Consolida e persiste
    todas_chaves = list(dados_municipio.items()) + list(dados_uf.items())
    for (prod, uf_item, mun_item), info in todas_chaves:
        precos = info['precos']
        datas = info['datas']
        if not precos:
            continue

        n_postos = len(precos)
        preco_min = min(precos)
        preco_max = max(precos)
        preco_medio = (sum(precos) / Decimal(n_postos)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

        # Desvio padrão amostral
        desvio_padrao = Decimal('0.0000')
        if n_postos > 1:
            media_float = float(preco_medio)
            soma_quad = sum((float(p) - media_float) ** 2 for p in precos)
            dp_float = math.sqrt(soma_quad / (n_postos - 1))
            desvio_padrao = Decimal(str(dp_float)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

        data_inicial = min(datas)
        data_final = max(datas)

        if dry_run:
            stats['atualizados'] += 1
            continue

        try:
            obj, created = PrecoCombustivelReferencia.objects.update_or_create(
                tenant=tenant,
                fonte='ANP',
                produto=prod,
                uf=uf_item,
                municipio=mun_item,
                data_inicial=data_inicial,
                defaults={
                    'data_final': data_final,
                    'preco_medio': preco_medio,
                    'preco_minimo': preco_min,
                    'preco_maximo': preco_max,
                    'desvio_padrao': desvio_padrao,
                    'n_postos': n_postos,
                }
            )
            if created:
                stats['criados'] += 1
            else:
                stats['atualizados'] += 1
        except Exception as e:
            stats['erros'].append(f"Erro ao salvar {prod} ({mun_item}/{uf_item}): {str(e)}")

    return stats


def importar_precos_anp_de_conteudo(conteudo_bytes, uf_filtro=None, municipio_filtro=None, tenant=None, dry_run=False):
    """
    Decodifica com tolerância a encodings (UTF-8, Latin-1) e delimitadores (; ou ,) e processa o CSV.
    """
    texto = None
    for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
        try:
            texto = conteudo_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if not texto:
        raise ValueError("Não foi possível decodificar o arquivo CSV com encodings suportados (UTF-8, Latin-1).")

    # Identifica delimitador pela primeira linha de cabeçalho
    primeira_linha = texto.splitlines()[0] if texto.splitlines() else ''
    delimitador = ';' if ';' in primeira_linha else ','

    f = io.StringIO(texto)
    reader = csv.DictReader(f, delimiter=delimitador)
    return processar_linhas_csv_anp(reader, uf_filtro=uf_filtro, municipio_filtro=municipio_filtro, tenant=tenant, dry_run=dry_run)
