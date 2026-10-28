from decimal import Decimal
from datetime import date
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.money import quantize
from core.guards import assert_tenant_writable
from fiscal.models import (
    RegraTributaria,
    RegraTributariaTributo,
    ItemDocumentoTributo,
    DocumentoFiscalItem,
)


class RegraTributariaNaoEncontradaError(Exception):
    """Lançada quando nenhuma regra tributária atende aos critérios da operação e vigência."""
    pass


class RegraTributariaAmbiguidadeError(Exception):
    """Lançada quando há empate de especificidade entre duas ou mais regras vigentes."""
    pass


class RegraTributariaNaoAprovadaError(Exception):
    """Lançada quando se tenta utilizar uma regra tributária não aprovada em ambiente de PRODUÇÃO."""
    pass


def _calcular_score_especificidade(regra: RegraTributaria, item_ncm: str, uf_origem: str, uf_destino: str) -> int:
    """
    Calcula a pontuação de especificidade da regra conforme a hierarquia da Sprint 11A (Task 4):
    NCM + UFs + Operação vence NCM sozinho, que vence só UFs + Operação, que vence só Operação.
    """
    score = 0
    clean_ncm = str(item_ncm or '').strip()
    r_ncm = str(regra.ncm or '').strip()
    r_ufo = str(regra.uf_origem or '').strip().upper()
    r_ufd = str(regra.uf_destino or '').strip().upper()

    # NCM específico
    if r_ncm and r_ncm != '*':
        score += 10

    # UFs específicas
    if r_ufo and r_ufo != '*' and r_ufd and r_ufd != '*':
        score += 5
    elif (r_ufo and r_ufo != '*') or (r_ufd and r_ufd != '*'):
        score += 2

    # Tipo de operação
    if regra.tipo_operacao:
        score += 1

    return score


def resolver_regra(
    tenant,
    item_ncm: str,
    operacao: str,
    data_competencia: date = None,
    uf_origem: str = '',
    uf_destino: str = '',
    ambiente: str = 'HOMOLOGACAO'
) -> RegraTributaria:
    """
    Resolve a regra tributária por vigência e especificidade estrita (Task 4 / F-25).
    Hierarquia: (NCM + UFs + Operação) > (NCM + Operação) > (UFs + Operação) > (Operação).
    Empate ou ausência gera erro claro, nunca um palpite.
    Em PRODUÇÃO, somente regras formalmente aprovadas por um contador (aprovada_por) são aceitas.
    """
    if data_competencia is None:
        data_competencia = timezone.localdate()

    clean_ncm = str(item_ncm or '').strip()
    clean_ufo = str(uf_origem or '').strip().upper()
    clean_ufd = str(uf_destino or '').strip().upper()
    clean_op = str(operacao or '').strip().upper()

    # Filtra regras do tenant vigentes na data informada
    qs = RegraTributaria.objects.filter(
        tenant=tenant,
        tipo_operacao=clean_op,
        vigencia_inicio__lte=data_competencia,
    ).filter(
        models_q_fim(data_competencia)
    )

    # Coleta regras compatíveis
    regras_compativeis = []
    for r in qs:
        # Verifica NCM
        r_ncm = str(r.ncm or '').strip()
        if r_ncm and r_ncm != '*' and r_ncm != clean_ncm:
            continue

        # Verifica UF Origem
        r_ufo = str(r.uf_origem or '').strip().upper()
        if r_ufo and r_ufo != '*' and clean_ufo and r_ufo != clean_ufo:
            continue

        # Verifica UF Destino
        r_ufd = str(r.uf_destino or '').strip().upper()
        if r_ufd and r_ufd != '*' and clean_ufd and r_ufd != clean_ufd:
            continue

        score = _calcular_score_especificidade(r, clean_ncm, clean_ufo, clean_ufd)
        regras_compativeis.append((score, r))

    if not regras_compativeis:
        raise RegraTributariaNaoEncontradaError(
            f"Nenhuma regra tributária encontrada para Tenant '{tenant.nome}', "
            f"Operação '{clean_op}', NCM '{clean_ncm}', UFs '{clean_ufo}->{clean_ufd}' "
            f"na vigência {data_competencia}."
        )

    # Ordena pelo maior score
    regras_compativeis.sort(key=lambda x: x[0], reverse=True)
    maior_score = regras_compativeis[0][0]
    top_regras = [r for score, r in regras_compativeis if score == maior_score]

    if len(top_regras) > 1:
        descricoes = [f"'{r.descricao}' (id={r.id}, cfop={r.cfop})" for r in top_regras]
        raise RegraTributariaAmbiguidadeError(
            f"Ambiguidade de regras tributárias com a mesma especificidade (score={maior_score}): "
            f"{', '.join(descricoes)}. O sistema não faz suposições fiscais."
        )

    regra_escolhida = top_regras[0]

    # Validação de ambiente de PRODUÇÃO
    if ambiente == 'PRODUCAO' and not regra_escolhida.is_aprovada():
        raise RegraTributariaNaoAprovadaError(
            f"A regra tributária '{regra_escolhida.descricao}' (CFOP {regra_escolhida.cfop}) "
            f"não possui aprovação formal de um contador e não pode ser utilizada em ambiente de PRODUÇÃO."
        )

    return regra_escolhida


def models_q_fim(data_ref: date):
    from django.db.models import Q
    return Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=data_ref)


def calcular_tributos_item(
    regra: RegraTributaria,
    quantidade: Decimal,
    valor_unitario: Decimal,
    valor_total: Decimal,
    salvar_em_item: DocumentoFiscalItem = None
) -> list[dict]:
    """
    Calcula os tributos incidentes sobre um item com base na RegraTributaria (Task 4).
    Retorna lista de dicionários contendo os valores calculados por tributo.
    Se `salvar_em_item` for fornecido, grava os registros `ItemDocumentoTributo` no banco.
    Suporta ICMS, ICMS_ST, PIS, COFINS, IPI, ISS e a Reforma Tributária (IBS, CBS e IS).
    Toda a aritmética é executada em Decimal com quantize ROUND_HALF_UP (proibido float).
    """
    if isinstance(quantidade, float) or isinstance(valor_unitario, float) or isinstance(valor_total, float):
        raise TypeError("Proibido float no cálculo de tributos fiscais. Utilize Decimal.")

    qtd = quantize(Decimal(str(quantidade)), 3)
    v_total = quantize(Decimal(str(valor_total)), 2)

    tributos_calculados = []
    tributos_da_regra = regra.tributos.all()

    for trib in tributos_da_regra:
        # Cálculo da Base com eventual Redução de Base
        red_base = Decimal(str(trib.reducao_base_pct or '0.0000'))
        if red_base > Decimal('0.0000'):
            fator_reducao = Decimal('1.0000') - (red_base / Decimal('100.0000'))
            base_calculada = quantize(v_total * fator_reducao, 2)
        else:
            base_calculada = v_total

        aliq = Decimal(str(trib.aliquota or '0.0000'))
        if trib.modo_calculo == 'VALOR_PAUTA':
            # Valor fixo por unidade
            valor_trib = quantize(aliq * qtd, 2)
        else:
            # Percentual sobre a base
            valor_trib = quantize(base_calculada * (aliq / Decimal('100.0000')), 2)

        dado_trib = {
            'tributo': trib.tributo,
            'cst': trib.cst_csosn,
            'base': base_calculada,
            'aliquota': aliq,
            'valor': valor_trib,
            'codigo_beneficio': trib.codigo_beneficio
        }
        tributos_calculados.append(dado_trib)

        if salvar_em_item:
            ItemDocumentoTributo.objects.create(
                tenant=salvar_em_item.tenant,
                item=salvar_em_item,
                tributo=trib.tributo,
                cst=trib.cst_csosn,
                base=base_calculada,
                aliquota=aliq,
                valor=valor_trib
            )

    return tributos_calculados
