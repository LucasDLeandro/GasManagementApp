"""
Serviço Canônico de Exportações Contábeis e Fiscais em CSV e XLSX (Sprint 10B - Tarefa 12).
Gera relatórios de Balancete, Razão, DRE e ExportacaoContabil em layout genérico para o contador externo.
"""

import csv
import io
import datetime
from decimal import Decimal
from typing import Optional, Union

from django.core.exceptions import ValidationError

from core.guards import assert_modulo
from core.money import quantize
from financeiro.models import (
    PlanoContas,
    PartidaContabil,
    LancamentoContabil,
    CentroCusto,
)
from financeiro.selectors.balancete import obter_balancete_verificacao
from financeiro.services.dre_service import dre


def exportar_balancete_csv(
    tenant,
    data_inicio: Union[str, datetime.date],
    data_fim: Union[str, datetime.date],
    filial=None
) -> str:
    """Exporta o Balancete de Verificação de 8 colunas no formato CSV."""
    assert_modulo(tenant, 'financeiro')
    dt_ini = data_inicio.isoformat() if isinstance(data_inicio, datetime.date) else data_inicio
    dt_fim = data_fim.isoformat() if isinstance(data_fim, datetime.date) else data_fim

    bal = obter_balancete_verificacao(tenant=tenant, data_inicio=dt_ini, data_fim=dt_fim, filial=filial)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'codigo_estrutural',
        'nome_conta',
        'tipo',
        'natureza',
        'saldo_anterior',
        'debitos_periodo',
        'creditos_periodo',
        'saldo_final',
        'indicador_saldo'
    ])

    linhas = bal.get('linhas') or bal.get('contas') or []
    for c in linhas:
        deb = c.get('debitos_periodo') if 'debitos_periodo' in c else c.get('total_debitos', Decimal('0.00'))
        cred = c.get('creditos_periodo') if 'creditos_periodo' in c else c.get('total_creditos', Decimal('0.00'))
        indicador = c.get('indicador_saldo') or ('D' if c.get('saldo_final', 0) >= 0 else 'C')
        writer.writerow([
            c['codigo_estrutural'],
            c['nome'],
            c['tipo'],
            c['natureza_saldo'],
            str(c.get('saldo_anterior', Decimal('0.00'))),
            str(deb),
            str(cred),
            str(c.get('saldo_final', Decimal('0.00'))),
            indicador
        ])

    return output.getvalue()


def exportar_razao_csv(
    tenant,
    conta_id: int,
    data_inicio: Union[str, datetime.date],
    data_fim: Union[str, datetime.date]
) -> str:
    """Exporta a ficha analítica do Livro Razão de uma conta contábil em CSV."""
    assert_modulo(tenant, 'financeiro')
    conta = PlanoContas.unscoped.get(tenant=tenant, id=conta_id)

    if isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)
    if isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    partidas = PartidaContabil.unscoped.filter(
        tenant=tenant,
        conta_contabil=conta,
        lancamento__data_competencia__gte=data_inicio,
        lancamento__data_competencia__lte=data_fim
    ).select_related('lancamento', 'centro_custo').order_by('lancamento__data_competencia', 'lancamento__numero')

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'data_competencia',
        'numero_lancamento',
        'historico',
        'tipo_partida',
        'valor',
        'centro_custo',
        'origem_tipo'
    ])

    for p in partidas:
        cc_nome = p.centro_custo.codigo if p.centro_custo else ''
        writer.writerow([
            p.lancamento.data_competencia.isoformat(),
            p.lancamento.numero,
            p.lancamento.historico,
            p.tipo_partida,
            str(p.valor),
            cc_nome,
            p.lancamento.origem_tipo
        ])

    return output.getvalue()


def exportar_dre_csv(
    tenant,
    periodo_ini: Union[str, datetime.date],
    periodo_fim: Union[str, datetime.date],
    filial=None,
    centro_custo=None,
    produto_gas=None
) -> str:
    """Exporta as 12 linhas da DRE estruturada em CSV."""
    assert_modulo(tenant, 'financeiro')
    res = dre(
        tenant=tenant,
        periodo_ini=periodo_ini,
        periodo_fim=periodo_fim,
        filial=filial,
        centro_custo=centro_custo,
        produto_gas=produto_gas
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['LinhaDRE', 'Descricao', 'Valor'])

    labels = {
        '01_receita_bruta': '1. Receita Operacional Bruta',
        '02_deducoes_receita': '2. Deduções da Receita Bruta',
        '03_receita_liquida': '3. Receita Operacional Líquida',
        '04_cpv_csp': '4. Custos dos Produtos e Serviços Vendidos (CPV/CSP)',
        '05_lucro_bruto': '5. Lucro Bruto',
        '06_opex': '6. Despesas Operacionais (OPEX)',
        '07_ebitda': '7. EBITDA',
        '08_depreciacao': '8. Depreciação e Amortização',
        '08_2_resultado_baixa_imobilizado': '8.2 Resultado na Baixa de Imobilizado',
        '09_ebit': '9. EBIT (Resultado Operacional)',
        '10_resultado_financeiro': '10. Resultado Financeiro Líquido',
        '11_irpj_csll': '11. Provisão para IRPJ e CSLL',
        '12_resultado_liquido': '12. Lucro Líquido do Exercício',
    }

    for chave, item in res['linhas'].items():
        lbl = labels.get(chave, chave)
        writer.writerow([chave, lbl, str(item['valor'])])

    if res.get('rodape'):
        rodape_txt = res['rodape'].get('aviso_legal', '') if isinstance(res['rodape'], dict) else str(res['rodape'])
        if rodape_txt:
            writer.writerow([])
            writer.writerow(['NOTA', rodape_txt, ''])

    return output.getvalue()


def exportar_contabil_generico_csv(
    tenant,
    data_inicio: Union[str, datetime.date],
    data_fim: Union[str, datetime.date]
) -> str:
    """
    Exportação contábil no layout genérico (data, conta débito, conta crédito, valor, histórico, centro de custo)
    utilizado para importação direta em sistemas de escrituração de escritórios de contabilidade (Sprint 10B - Tarefa 12).
    """
    assert_modulo(tenant, 'financeiro')
    if isinstance(data_inicio, str):
        data_inicio = datetime.date.fromisoformat(data_inicio)
    if isinstance(data_fim, str):
        data_fim = datetime.date.fromisoformat(data_fim)

    lancamentos = (
        LancamentoContabil.unscoped
        .filter(
            tenant=tenant,
            data_competencia__gte=data_inicio,
            data_competencia__lte=data_fim
        )
        .prefetch_related('partidas__conta_contabil', 'partidas__centro_custo')
        .order_by('data_competencia', 'numero')
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=',')
    writer.writerow([
        'data',
        'conta_debito',
        'conta_credito',
        'valor',
        'historico',
        'centro_custo'
    ])

    for lanc in lancamentos:
        partidas_deb = [p for p in lanc.partidas.all() if p.tipo_partida == 'DEBITO']
        partidas_cred = [p for p in lanc.partidas.all() if p.tipo_partida == 'CREDITO']

        # Caso canônico simples 1D para 1C
        if len(partidas_deb) == 1 and len(partidas_cred) == 1:
            p_deb = partidas_deb[0]
            p_cred = partidas_cred[0]
            cc_cod = (p_deb.centro_custo or p_cred.centro_custo).codigo if (p_deb.centro_custo or p_cred.centro_custo) else ''
            writer.writerow([
                lanc.data_competencia.strftime('%d/%m/%Y'),
                p_deb.conta_contabil.codigo_estrutural,
                p_cred.conta_contabil.codigo_estrutural,
                str(p_deb.valor),
                lanc.historico,
                cc_cod
            ])
        else:
            # Partidas compostas (vários D para 1C ou vários C para 1D ou vários para vários)
            # Desmembra cada linha contra a principal ou conta de trânsito
            for p_deb in partidas_deb:
                cc_cod = p_deb.centro_custo.codigo if p_deb.centro_custo else ''
                c_contra = partidas_cred[0].conta_contabil.codigo_estrutural if partidas_cred else ''
                writer.writerow([
                    lanc.data_competencia.strftime('%d/%m/%Y'),
                    p_deb.conta_contabil.codigo_estrutural,
                    c_contra,
                    str(p_deb.valor),
                    lanc.historico,
                    cc_cod
                ])

    return output.getvalue()
