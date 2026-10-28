"""
Serviço Canônico de Demonstração do Resultado do Exercício - DRE por Competência (Sprint 10B - Tarefas 7 e 13).
Produz as 12 linhas da v2.0 a partir dos snapshots SaldoMensalConta (p95 < 2s com 1M partidas),
com tratamento estrito para subdivisões 8.1 (antes do EBITDA) e 8.2 (fora do EBITDA),
além de rodapé obrigatório e comparativos com período anterior e orçamento.
"""

import datetime
from decimal import Decimal
from typing import Optional, Union

from django.core.exceptions import ValidationError
from django.db.models import Sum, Q

from core.guards import assert_modulo
from core.money import quantize
from financeiro.models import (
    SaldoMensalConta,
    PlanoContas,
    Orcamento,
    OrcamentoMensalConta,
)


def extrair_meses_no_intervalo(periodo_ini: datetime.date, periodo_fim: datetime.date) -> list[str]:
    """Retorna lista ordenada de strings 'YYYY-MM' compreendidas no intervalo de datas."""
    meses = []
    ano = periodo_ini.year
    mes = periodo_ini.month
    while True:
        mes_str = f"{ano:04d}-{mes:02d}"
        meses.append(mes_str)
        if ano == periodo_fim.year and mes == periodo_fim.month:
            break
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1
    return meses


def dre(
    *,
    tenant,
    periodo_ini: Union[str, datetime.date],
    periodo_fim: Union[str, datetime.date],
    filial=None,
    centro_custo=None,
    produto_gas=None,
    comparar_com: Optional[str] = None
) -> dict:
    """
    Gera a Demonstração do Resultado do Exercício estruturada em 12 linhas (Sprint 10B - Tarefa 7).
    """
    assert_modulo(tenant, 'financeiro')

    import calendar

    if isinstance(periodo_ini, str):
        if len(periodo_ini) == 7:
            periodo_ini = datetime.date.fromisoformat(f"{periodo_ini}-01")
        else:
            periodo_ini = datetime.date.fromisoformat(periodo_ini)
    if isinstance(periodo_fim, str):
        if len(periodo_fim) == 7:
            ano_f, mes_f = map(int, periodo_fim.split('-'))
            ult_dia = calendar.monthrange(ano_f, mes_f)[1]
            periodo_fim = datetime.date(ano_f, mes_f, ult_dia)
        else:
            periodo_fim = datetime.date.fromisoformat(periodo_fim)

    if periodo_ini > periodo_fim:
        raise ValidationError("A data inicial não pode ser superior à data final do DRE.")

    meses = extrair_meses_no_intervalo(periodo_ini, periodo_fim)

    # 1. Consulta analítica de alta performance sobre os snapshots SaldoMensalConta
    qs = SaldoMensalConta.unscoped.filter(
        tenant=tenant,
        ano_mes__in=meses
    ).select_related('conta')

    if filial:
        qs = qs.filter(filial=filial)
    if centro_custo:
        qs = qs.filter(centro_custo=centro_custo)
    if produto_gas:
        qs = qs.filter(produto_gas=produto_gas)

    # Totalizadores por tipo_dre e contas analíticas
    totais_por_conta = {}
    for s in qs:
        cta = s.conta
        c_id = cta.id
        if c_id not in totais_por_conta:
            totais_por_conta[c_id] = {
                'conta': cta,
                'debitos': Decimal('0.00'),
                'creditos': Decimal('0.00'),
            }
        totais_por_conta[c_id]['debitos'] = quantize(totais_por_conta[c_id]['debitos'] + s.debitos, 2)
        totais_por_conta[c_id]['creditos'] = quantize(totais_por_conta[c_id]['creditos'] + s.creditos, 2)

    # 2. Classificação dos valores nas 12 linhas estruturadas
    receita_medicinal = Decimal('0.00')
    receita_industrial = Decimal('0.00')
    receita_locacao = Decimal('0.00')
    receita_frete = Decimal('0.00')
    receita_revenda = Decimal('0.00')

    deducoes_receita = Decimal('0.00')
    cpv_csp = Decimal('0.00')

    despesas_logistica = Decimal('0.00')
    despesas_comerciais = Decimal('0.00')
    despesas_admin = Decimal('0.00')
    perdas_pdd = Decimal('0.00')
    outras_operacionais_81 = Decimal('0.00')  # Subdivisão 8.1 (entra antes do EBITDA)
    resultado_alienacao_82 = Decimal('0.00')  # Subdivisão 8.2 (entra depois da depreciação e FORA do EBITDA)

    depreciacao = Decimal('0.00')
    receitas_financeiras = Decimal('0.00')
    despesas_financeiras = Decimal('0.00')
    impostos_lucro = Decimal('0.00')

    for dados in totais_por_conta.values():
        cta = dados['conta']
        deb = dados['debitos']
        cred = dados['creditos']
        # Saldo líquido da conta no período
        if cta.natureza_saldo == 'CREDORA':
            saldo_liq = quantize(cred - deb, 2)
        else:
            saldo_liq = quantize(deb - cred, 2)

        tipo_dre = cta.tipo_dre
        cod = cta.codigo_estrutural
        nome_lower = cta.nome.lower()

        if tipo_dre == 'RECEITA_BRUTA':
            if 'medicinal' in nome_lower or cod.startswith('3.1.1'):
                receita_medicinal = quantize(receita_medicinal + saldo_liq, 2)
            elif 'industrial' in nome_lower or cod.startswith('3.1.2'):
                receita_industrial = quantize(receita_industrial + saldo_liq, 2)
            elif 'loca' in nome_lower or cod.startswith('3.1.3'):
                receita_locacao = quantize(receita_locacao + saldo_liq, 2)
            elif 'frete' in nome_lower or cod.startswith('3.1.4'):
                receita_frete = quantize(receita_frete + saldo_liq, 2)
            else:
                receita_revenda = quantize(receita_revenda + saldo_liq, 2)

        elif tipo_dre == 'DEDUCOES_RECEITA':
            deducoes_receita = quantize(deducoes_receita + saldo_liq, 2)

        elif tipo_dre == 'CPV_CSP':
            cpv_csp = quantize(cpv_csp + saldo_liq, 2)

        elif tipo_dre == 'DESPESAS_LOGISTICA_FROTA':
            despesas_logistica = quantize(despesas_logistica + saldo_liq, 2)

        elif tipo_dre == 'DESPESAS_COMERCIAIS':
            despesas_comerciais = quantize(despesas_comerciais + saldo_liq, 2)

        elif tipo_dre == 'DESPESAS_ADMINISTRATIVAS':
            despesas_admin = quantize(despesas_admin + saldo_liq, 2)

        elif tipo_dre == 'PERDAS_PDD':
            perdas_pdd = quantize(perdas_pdd + saldo_liq, 2)

        elif cod.startswith('8.1') or tipo_dre == 'OUTRAS_RECEITAS_OPERACIONAIS':
            # 8.1 Outras receitas operacionais (diminui despesa / entra antes do EBITDA)
            outras_operacionais_81 = quantize(outras_operacionais_81 + saldo_liq, 2)

        elif cod.startswith('8.2') or tipo_dre == 'OUTRAS_DESPESAS_OPERACIONAIS':
            # 8.2 Resultado na alienação/baixa de imobilizado (entra depois da depreciação e FORA do EBITDA)
            # Natureza devedora da conta 8.2: débito = perda, crédito = ganho
            # Saldo positivo indica perda líquida, negativo indica ganho líquido
            resultado_alienacao_82 = quantize(resultado_alienacao_82 + (deb - cred), 2)

        elif tipo_dre == 'DEPRECIACAO_AMORTIZACAO':
            depreciacao = quantize(depreciacao + saldo_liq, 2)

        elif tipo_dre == 'RESULTADO_FINANCEIRO':
            if cta.natureza_saldo == 'CREDORA':
                receitas_financeiras = quantize(receitas_financeiras + saldo_liq, 2)
            else:
                despesas_financeiras = quantize(despesas_financeiras + saldo_liq, 2)

        elif tipo_dre == 'IMPOSTOS_SOBRE_LUCRO':
            impostos_lucro = quantize(impostos_lucro + saldo_liq, 2)

    # 3. Consolidação Matemática dos Totais e Margens
    receita_bruta = quantize(
        receita_medicinal + receita_industrial + receita_locacao + receita_frete + receita_revenda,
        2
    )
    receita_liquida = quantize(receita_bruta - deducoes_receita, 2)
    lucro_bruto = quantize(receita_liquida - cpv_csp, 2)
    margem_bruta_pct = quantize((lucro_bruto / receita_liquida * Decimal('100.00')) if receita_liquida > Decimal('0.00') else Decimal('0.0000'), 4)

    # OPEX: soma das despesas operacionais menos outras receitas operacionais (8.1)
    opex_bruto = quantize(despesas_logistica + despesas_comerciais + despesas_admin + perdas_pdd, 2)
    opex_liquido = quantize(opex_bruto - outras_operacionais_81, 2)

    # EBITDA: Lucro Bruto - OPEX (sem depreciação e sem 8.2)
    ebitda = quantize(lucro_bruto - opex_liquido, 2)

    # EBIT: EBITDA - Depreciação - Perda na Baixa de Imobilizado (8.2)
    # (Se resultado_alienacao_82 for positivo representa perda, portanto deduz; se negativo representa ganho)
    ebit = quantize(ebitda - depreciacao - resultado_alienacao_82, 2)

    # Resultado Financeiro Líquido (Receitas - Despesas)
    resultado_financeiro = quantize(receitas_financeiras - despesas_financeiras, 2)

    # Resultado Líquido do Exercício
    resultado_liquido = quantize(ebit + resultado_financeiro - impostos_lucro, 2)

    # Rodapé obrigatório de deduções estimadas quando não houver notas fiscais
    tem_doc_fiscal = False
    try:
        from vendas.models import Venda
        tem_doc_fiscal = Venda.unscoped.filter(
            tenant=tenant,
            data_venda__gte=periodo_ini,
            data_venda__lte=periodo_fim,
            chave_nfe__isnull=False
        ).exclude(chave_nfe='').exists()
    except Exception:
        tem_doc_fiscal = False

    rodape_alerta = not tem_doc_fiscal
    rodape_texto = "Deduções estimadas a partir de alíquota efetiva (sem documentos fiscais vinculados)." if rodape_alerta else None

    rodape = {
        'texto': rodape_texto,
        'aviso_legal': rodape_texto or '',
        'alerta_deducoes_estimadas': rodape_alerta,
    }

    linhas_realizado = {
        '1_receita_bruta': {
            'valor': receita_bruta,
            'detalhes': {
                'medicinal': receita_medicinal,
                'industrial': receita_industrial,
                'locacao': receita_locacao,
                'frete': receita_frete,
                'revenda': receita_revenda,
            }
        },
        '01_receita_bruta': {
            'valor': receita_bruta,
            'detalhes': {
                'medicinal': receita_medicinal,
                'industrial': receita_industrial,
                'locacao': receita_locacao,
                'frete': receita_frete,
                'revenda': receita_revenda,
            }
        },
        '2_deducoes_receita': {'valor': deducoes_receita},
        '02_deducoes_receita': {'valor': deducoes_receita},
        '3_receita_liquida': {'valor': receita_liquida},
        '03_receita_liquida': {'valor': receita_liquida},
        '4_cpv_csp': {'valor': cpv_csp},
        '04_cpv_csp': {'valor': cpv_csp},
        '5_lucro_bruto': {'valor': lucro_bruto, 'margem_pct': margem_bruta_pct},
        '05_lucro_bruto': {'valor': lucro_bruto, 'margem_pct': margem_bruta_pct},
        '6_opex': {
            'valor': opex_liquido,
            'detalhes': {
                'logistica_frota': despesas_logistica,
                'comercial': despesas_comerciais,
                'administrativa': despesas_admin,
                'perdas_pdd': perdas_pdd,
                'outras_operacionais_81': outras_operacionais_81,
            }
        },
        '06_opex': {
            'valor': opex_liquido,
            'detalhes': {
                'logistica_frota': despesas_logistica,
                'comercial': despesas_comerciais,
                'administrativa': despesas_admin,
                'perdas_pdd': perdas_pdd,
                'outras_operacionais_81': outras_operacionais_81,
            }
        },
        '7_ebitda': {'valor': ebitda},
        '07_ebitda': {'valor': ebitda},
        '8_depreciacao': {'valor': depreciacao},
        '08_depreciacao': {'valor': depreciacao},
        '8_2_resultado_baixa_imobilizado': {'valor': resultado_alienacao_82},
        '08_2_resultado_baixa_imobilizado': {'valor': resultado_alienacao_82},
        '9_ebit': {'valor': ebit},
        '09_ebit': {'valor': ebit},
        '10_resultado_financeiro': {
            'valor': resultado_financeiro,
            'receitas': receitas_financeiras,
            'despesas': despesas_financeiras
        },
        '11_irpj_csll': {'valor': impostos_lucro},
        '12_resultado_liquido': {'valor': resultado_liquido},
    }

    resposta = {
        'periodo_ini': periodo_ini.isoformat(),
        'periodo_fim': periodo_fim.isoformat(),
        'meses': meses,
        'filial_id': getattr(filial, 'id', filial),
        'centro_custo_id': getattr(centro_custo, 'id', centro_custo),
        'produto_gas_id': getattr(produto_gas, 'id', produto_gas),
        'linhas': linhas_realizado,
        'rodape': rodape,
        'comparativo': None
    }

    # 4. Tratamento do Comparativo (Orçamento ou Período Anterior)
    if comparar_com == 'ORCAMENTO':
        # Busca orçamentos aprovados para o ano do período
        ano_exercicio = periodo_ini.year
        orc = Orcamento.unscoped.filter(tenant=tenant, ano=ano_exercicio, status='APROVADO').first()
        if orc:
            num_meses = [int(m.split('-')[1]) for m in meses]
            itens_orc = OrcamentoMensalConta.unscoped.filter(
                tenant=tenant,
                orcamento=orc,
                mes__in=num_meses
            ).select_related('conta')

            orc_rec_bruta = Decimal('0.00')
            orc_deducoes = Decimal('0.00')
            orc_cpv = Decimal('0.00')
            orc_opex = Decimal('0.00')
            orc_depreciacao = Decimal('0.00')
            orc_res_fin = Decimal('0.00')
            orc_tributos = Decimal('0.00')

            for io in itens_orc:
                td = io.conta.tipo_dre
                val = io.valor
                if td == 'RECEITA_BRUTA':
                    orc_rec_bruta += val
                elif td == 'DEDUCOES_RECEITA':
                    orc_deducoes += val
                elif td == 'CPV_CSP':
                    orc_cpv += val
                elif td in ['DESPESAS_LOGISTICA_FROTA', 'DESPESAS_COMERCIAIS', 'DESPESAS_ADMINISTRATIVAS', 'PERDAS_PDD']:
                    orc_opex += val
                elif td == 'DEPRECIACAO_AMORTIZACAO':
                    orc_depreciacao += val
                elif td == 'RESULTADO_FINANCEIRO':
                    orc_res_fin += val
                elif td == 'IMPOSTOS_SOBRE_LUCRO':
                    orc_tributos += val

            orc_rec_liq = quantize(orc_rec_bruta - orc_deducoes, 2)
            orc_lucro_bruto = quantize(orc_rec_liq - orc_cpv, 2)
            orc_ebitda = quantize(orc_lucro_bruto - orc_opex, 2)
            orc_ebit = quantize(orc_ebitda - orc_depreciacao, 2)
            orc_res_liq = quantize(orc_ebit + orc_res_fin - orc_tributos, 2)

            def calcular_var(real, orcado):
                diff = quantize(real - orcado, 2)
                pct = quantize((diff / orcado * Decimal('100.00')) if orcado != Decimal('0.00') else Decimal('0.0000'), 4)
                return {'orcado': orcado, 'realizado': real, 'variacao_rs': diff, 'variacao_pct': pct}

            resposta['comparativo'] = {
                'tipo': 'ORCAMENTO',
                'orcamento_id': orc.id,
                'linhas': {
                    'receita_bruta': calcular_var(receita_bruta, orc_rec_bruta),
                    'receita_liquida': calcular_var(receita_liquida, orc_rec_liq),
                    'lucro_bruto': calcular_var(lucro_bruto, orc_lucro_bruto),
                    'ebitda': calcular_var(ebitda, orc_ebitda),
                    'ebit': calcular_var(ebit, orc_ebit),
                    'resultado_liquido': calcular_var(resultado_liquido, orc_res_liq),
                }
            }

    elif comparar_com == 'PERIODO_ANTERIOR':
        # Período anterior com a mesma quantidade de dias/meses deslocado 1 ano atrás
        delta_anos = 1
        p_ini_ant = datetime.date(periodo_ini.year - delta_anos, periodo_ini.month, periodo_ini.day)
        try:
            p_fim_ant = datetime.date(periodo_fim.year - delta_anos, periodo_fim.month, periodo_fim.day)
        except ValueError:
            p_fim_ant = datetime.date(periodo_fim.year - delta_anos, periodo_fim.month, 28)

        dre_anterior = dre(
            tenant=tenant,
            periodo_ini=p_ini_ant,
            periodo_fim=p_fim_ant,
            filial=filial,
            centro_custo=centro_custo,
            produto_gas=produto_gas,
            comparar_com=None
        )
        l_ant = dre_anterior['linhas']

        def calcular_var_ant(real_atual, real_ant):
            diff = quantize(real_atual - real_ant, 2)
            pct = quantize((diff / real_ant * Decimal('100.00')) if real_ant != Decimal('0.00') else Decimal('0.0000'), 4)
            return {'anterior': real_ant, 'atual': real_atual, 'variacao_rs': diff, 'variacao_pct': pct}

        resposta['comparativo'] = {
            'tipo': 'PERIODO_ANTERIOR',
            'periodo_anterior': {'ini': p_ini_ant.isoformat(), 'fim': p_fim_ant.isoformat()},
            'linhas': {
                'receita_bruta': calcular_var_ant(receita_bruta, l_ant['1_receita_bruta']['valor']),
                'receita_liquida': calcular_var_ant(receita_liquida, l_ant['3_receita_liquida']['valor']),
                'lucro_bruto': calcular_var_ant(lucro_bruto, l_ant['5_lucro_bruto']['valor']),
                'ebitda': calcular_var_ant(ebitda, l_ant['7_ebitda']['valor']),
                'ebit': calcular_var_ant(ebit, l_ant['9_ebit']['valor']),
                'resultado_liquido': calcular_var_ant(resultado_liquido, l_ant['12_resultado_liquido']['valor']),
            }
        }

    return resposta
