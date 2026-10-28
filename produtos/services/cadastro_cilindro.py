"""
Cadastro manual de cilindro (Plano de Correção, tarefa 2.0.2).

Até aqui cilindros só entravam por carga legada ou pelo admin do Django. O cadastro:
- valida duplicidade de QR code e de série por fabricante com mensagens claras;
- respeita a cota do plano (Cilindro.clean -> checar_cota; cilindros CLIENTE são isentos);
- calcula o próximo reteste a partir do último e da periodicidade do modelo;
- nasce em VAZIO_TRIAGEM e grava ENTRADA_ESTOQUE no ledger, na mesma transação.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.services.cotas import CotaExcedida
from produtos.models import Cilindro, MovimentacaoCilindro

CAMPOS_CILINDRO = [
    'codigo_qr', 'numero_serie_ogiva', 'modelo', 'gas_dedicado', 'fabricante_catalogo', 'fabricante',
    'ano_fabricacao', 'norma_fabricacao', 'pressao_servico_bar', 'pressao_teste_bar', 'tipo_valvula_rosca',
    'tara_real_kg', 'data_ultimo_reteste', 'propriedade', 'cliente_proprietario', 'numero_patrimonio',
    'data_aquisicao', 'valor_aquisicao', 'chave_nfe_aquisicao', 'fornecedor_aquisicao', 'classe_ativo',
]


def _somar_anos(data, anos):
    try:
        return data.replace(year=data.year + anos)
    except ValueError:  # 29/02 em ano não bissexto
        return data.replace(year=data.year + anos, day=28)


@transaction.atomic
def cadastrar_cilindro(*, tenant, usuario, dados: dict) -> Cilindro:
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'patrimonio')

    valores = {campo: dados[campo] for campo in CAMPOS_CILINDRO if dados.get(campo) not in (None, '')}
    valores['codigo_qr'] = valores['codigo_qr'].strip().upper()
    valores['numero_serie_ogiva'] = valores['numero_serie_ogiva'].strip().upper()
    fabricante_catalogo = valores.get('fabricante_catalogo')
    if fabricante_catalogo:
        valores['fabricante'] = fabricante_catalogo.nome

    erros = {}
    if Cilindro.unscoped.filter(tenant=tenant, codigo_qr__iexact=valores['codigo_qr']).exists():
        erros['codigo_qr'] = 'Já existe um cilindro com este QR code.'
    if Cilindro.unscoped.filter(
        tenant=tenant,
        fabricante__iexact=valores.get('fabricante', ''),
        numero_serie_ogiva__iexact=valores['numero_serie_ogiva'],
    ).exists():
        erros['numero_serie_ogiva'] = 'Já existe um cilindro deste fabricante com esta série.'
    if erros:
        raise ValidationError(erros)

    modelo = valores['modelo']
    if 'pressao_servico_bar' not in valores and modelo.pressao_servico_bar:
        valores['pressao_servico_bar'] = modelo.pressao_servico_bar
    valores['data_proximo_reteste'] = _somar_anos(valores['data_ultimo_reteste'], modelo.periodicidade_reteste_anos or 5)

    cilindro = Cilindro(tenant=tenant, status='VAZIO_TRIAGEM', **valores)
    try:
        cilindro.full_clean(validate_unique=False)
    except CotaExcedida as exc:
        raise ValidationError({'__all__': str(exc)}) from exc
    cilindro.save()

    MovimentacaoCilindro.objects.create(
        tenant=tenant,
        cilindro=cilindro,
        tipo='ENTRADA_ESTOQUE',
        status_anterior='',
        status_novo='VAZIO_TRIAGEM',
        ocorrido_em=timezone.now(),
        registrado_por=usuario,
        observacao=(dados.get('observacao') or 'Cadastro manual de cilindro').strip(),
    )
    return cilindro
