"""
Seeds contábeis e cadastrais padronizados para o módulo Financeiro (Sprint 9A).
Totalmente idempotentes: executar múltiplas vezes não duplica registros nem corrompe vínculos.
"""

from decimal import Decimal
from django.db import transaction

from financeiro.models import PlanoContas, CentroCusto, CondicaoPagamento


PLANO_CONTAS_PADRAO = [
    # 1. ATIVO
    {
        'codigo_estrutural': '1',
        'nome': 'ATIVO',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'NAO_APLICAVEL'
    },
    {
        'codigo_estrutural': '1.1',
        'nome': 'Ativo Circulante',
        'pai_codigo': '1',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'NAO_APLICAVEL'
    },
    {
        'codigo_estrutural': '1.1.1',
        'nome': 'Disponibilidades',
        'pai_codigo': '1.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.1.01',
        'nome': 'Bancos Conta Movimento',
        'pai_codigo': '1.1.1',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.1.02',
        'nome': 'Aplicações de Liquidez Imediata',
        'pai_codigo': '1.1.1',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.1.1.03',
        'nome': 'Caixas de Rota / Motoristas',
        'pai_codigo': '1.1.1',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.2',
        'nome': 'Contas a Receber',
        'pai_codigo': '1.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.2.01',
        'nome': 'Clientes a Receber',
        'pai_codigo': '1.1.2',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.2.02',
        'nome': '(-) PDD - Provisão para Devedores Duvidosos',
        'pai_codigo': '1.1.2',
        'nivel': 4,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.3',
        'nome': 'Estoques',
        'pai_codigo': '1.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.3.01',
        'nome': 'Estoque Gás a Granel',
        'pai_codigo': '1.1.3',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.3.02',
        'nome': 'Estoque Produto Acabado (Cilindros Cheios)',
        'pai_codigo': '1.1.3',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.3.03',
        'nome': 'Mercadorias para Revenda',
        'pai_codigo': '1.1.3',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.3.04',
        'nome': 'Materiais, Válvulas e Acessórios',
        'pai_codigo': '1.1.3',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.4',
        'nome': 'Impostos a Recuperar',
        'pai_codigo': '1.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.4.01',
        'nome': 'ICMS a Recuperar',
        'pai_codigo': '1.1.4',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.4.02',
        'nome': 'PIS/COFINS a Recuperar',
        'pai_codigo': '1.1.4',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.5',
        'nome': 'Adiantamentos',
        'pai_codigo': '1.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.1.5.01',
        'nome': 'Adiantamentos a Fornecedores',
        'pai_codigo': '1.1.5',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '1.2',
        'nome': 'Ativo Não Circulante',
        'pai_codigo': '1',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'NAO_APLICAVEL'
    },
    {
        'codigo_estrutural': '1.2.1',
        'nome': 'Imobilizado',
        'pai_codigo': '1.2',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.2.1.01',
        'nome': 'Cilindros em Operação',
        'pai_codigo': '1.2.1',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.2.1.02',
        'nome': '(-) Depreciação Acumulada de Cilindros',
        'pai_codigo': '1.2.1',
        'nivel': 4,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.2.1.03',
        'nome': 'Veículos e Frotas',
        'pai_codigo': '1.2.1',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.2.1.04',
        'nome': '(-) Depreciação Acumulada de Veículos',
        'pai_codigo': '1.2.1',
        'nivel': 4,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.2.1.05',
        'nome': 'Tanques Criogênicos e Rampas',
        'pai_codigo': '1.2.1',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.2.1.06',
        'nome': '(-) Depreciação Acumulada de Tanques e Rampas',
        'pai_codigo': '1.2.1',
        'nivel': 4,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },
    {
        'codigo_estrutural': '1.2.1.07',
        'nome': 'Componentes Capitalizados de Reteste',
        'pai_codigo': '1.2.1',
        'nivel': 4,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'INVESTIMENTO'
    },

    # 2. PASSIVO E PATRIMÔNIO LÍQUIDO
    {
        'codigo_estrutural': '2',
        'nome': 'PASSIVO E PATRIMÔNIO LÍQUIDO',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'NAO_APLICAVEL'
    },
    {
        'codigo_estrutural': '2.1',
        'nome': 'Passivo Circulante',
        'pai_codigo': '2',
        'nivel': 2,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'NAO_APLICAVEL'
    },
    {
        'codigo_estrutural': '2.1.1',
        'nome': 'Fornecedores a Pagar',
        'pai_codigo': '2.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '2.1.2',
        'nome': 'Obrigações Fiscais e Retenções a Recolher',
        'pai_codigo': '2.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '2.1.3',
        'nome': 'Obrigações Trabalhistas e Provisões',
        'pai_codigo': '2.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '2.1.4',
        'nome': 'Adiantamentos de Clientes',
        'pai_codigo': '2.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '2.1.5',
        'nome': 'Cauções de Cilindros em Comodato',
        'pai_codigo': '2.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '2.1.6',
        'nome': 'Empréstimos e Financiamentos Curto Prazo',
        'pai_codigo': '2.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'FINANCIAMENTO'
    },
    {
        'codigo_estrutural': '2.2',
        'nome': 'Passivo Não Circulante',
        'pai_codigo': '2',
        'nivel': 2,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'NAO_APLICAVEL'
    },
    {
        'codigo_estrutural': '2.2.1',
        'nome': 'Financiamentos de Longo Prazo',
        'pai_codigo': '2.2',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'FINANCIAMENTO'
    },
    {
        'codigo_estrutural': '2.3',
        'nome': 'Patrimônio Líquido',
        'pai_codigo': '2',
        'nivel': 2,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'FINANCIAMENTO'
    },
    {
        'codigo_estrutural': '2.3.1',
        'nome': 'Capital Social Subscrito',
        'pai_codigo': '2.3',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'FINANCIAMENTO'
    },
    {
        'codigo_estrutural': '2.3.2',
        'nome': 'Reservas de Capital e Lucros',
        'pai_codigo': '2.3',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'FINANCIAMENTO'
    },
    {
        'codigo_estrutural': '2.3.3',
        'nome': 'Lucros ou Prejuízos Acumulados',
        'pai_codigo': '2.3',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': None,
        'grupo_fluxo': 'FINANCIAMENTO'
    },

    # 3. RECEITAS
    {
        'codigo_estrutural': '3',
        'nome': 'RECEITAS',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.1',
        'nome': 'Receita Operacional Bruta',
        'pai_codigo': '3',
        'nivel': 2,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': 'RECEITA_BRUTA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.1.1',
        'nome': 'Venda de Gases Medicinais',
        'pai_codigo': '3.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'RECEITA_BRUTA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.1.2',
        'nome': 'Venda de Gases Industriais e Especiais',
        'pai_codigo': '3.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'RECEITA_BRUTA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.1.3',
        'nome': 'Locação e Estadia de Cilindros',
        'pai_codigo': '3.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'RECEITA_BRUTA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.1.4',
        'nome': 'Frete e Serviços de Entrega Destacados',
        'pai_codigo': '3.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'RECEITA_BRUTA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.1.5',
        'nome': 'Revenda de Equipamentos e Acessórios',
        'pai_codigo': '3.1',
        'nivel': 3,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'RECEITA_BRUTA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.2',
        'nome': 'Deduções da Receita Bruta',
        'pai_codigo': '3',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': 'DEDUCOES_RECEITA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.2.1',
        'nome': 'ICMS sobre Vendas',
        'pai_codigo': '3.2',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEDUCOES_RECEITA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.2.2',
        'nome': 'PIS sobre Faturamento',
        'pai_codigo': '3.2',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEDUCOES_RECEITA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.2.3',
        'nome': 'COFINS sobre Faturamento',
        'pai_codigo': '3.2',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEDUCOES_RECEITA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.2.4',
        'nome': 'ISS sobre Serviços',
        'pai_codigo': '3.2',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEDUCOES_RECEITA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '3.2.5',
        'nome': 'Devoluções e Abatimentos de Vendas',
        'pai_codigo': '3.2',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEDUCOES_RECEITA',
        'grupo_fluxo': 'OPERACIONAL'
    },

    # 4. CPV/CSP
    {
        'codigo_estrutural': '4',
        'nome': 'CUSTOS DOS PRODUTOS E SERVIÇOS VENDIDOS (CPV/CSP)',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '4.1',
        'nome': 'CPV Gás e Operações de Envase',
        'pai_codigo': '4',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '4.1.1',
        'nome': 'Matéria-Prima: Gás a Granel Consumido',
        'pai_codigo': '4.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '4.1.2',
        'nome': 'Perdas Técnicas de Envase (Evaporação e Purga)',
        'pai_codigo': '4.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '4.1.3',
        'nome': 'Energia Elétrica da Rampa de Envase',
        'pai_codigo': '4.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '4.1.4',
        'nome': 'Custo com Retestes Periódicos (Despesa)',
        'pai_codigo': '4.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '4.1.5',
        'nome': 'Custo de Mercadorias Revendidas',
        'pai_codigo': '4.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '4.1.6',
        'nome': 'Mão de Obra Direta da Rampa',
        'pai_codigo': '4.1',
        'nivel': 3,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'CPV_CSP',
        'grupo_fluxo': 'OPERACIONAL'
    },

    # 5. OPEX
    {
        'codigo_estrutural': '5',
        'nome': 'DESPESAS OPERACIONAIS (OPEX)',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '5.1',
        'nome': 'Despesas com Logística e Frota',
        'pai_codigo': '5',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DESPESAS_LOGISTICA_FROTA',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '5.2',
        'nome': 'Despesas Comerciais e Vendas',
        'pai_codigo': '5',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DESPESAS_COMERCIAIS',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '5.3',
        'nome': 'Despesas Gerais e Administrativas',
        'pai_codigo': '5',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DESPESAS_ADMINISTRATIVAS',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '5.4',
        'nome': 'Despesas com PDD (Devedores Duvidosos)',
        'pai_codigo': '5',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'PERDAS_PDD',
        'grupo_fluxo': 'OPERACIONAL'
    },

    # 6. DEPRECIAÇÃO E AMORTIZAÇÃO
    {
        'codigo_estrutural': '6',
        'nome': 'DEPRECIAÇÃO E AMORTIZAÇÃO',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': 'DEPRECIACAO_AMORTIZACAO',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '6.1',
        'nome': 'Depreciação de Cilindros',
        'pai_codigo': '6',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEPRECIACAO_AMORTIZACAO',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '6.2',
        'nome': 'Depreciação de Veículos e Frotas',
        'pai_codigo': '6',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEPRECIACAO_AMORTIZACAO',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '6.3',
        'nome': 'Depreciação de Tanques e Rampas',
        'pai_codigo': '6',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'DEPRECIACAO_AMORTIZACAO',
        'grupo_fluxo': 'OPERACIONAL'
    },

    # 7. RESULTADO FINANCEIRO
    {
        'codigo_estrutural': '7',
        'nome': 'RESULTADO FINANCEIRO',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': 'RESULTADO_FINANCEIRO',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '7.1',
        'nome': 'Receitas Financeiras e Rendimentos',
        'pai_codigo': '7',
        'nivel': 2,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'RESULTADO_FINANCEIRO',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '7.2',
        'nome': 'Despesas Financeiras, Juros e Tarifas',
        'pai_codigo': '7',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'RESULTADO_FINANCEIRO',
        'grupo_fluxo': 'OPERACIONAL'
    },

    # 8. OUTRAS RECEITAS E DESPESAS OPERACIONAIS
    {
        'codigo_estrutural': '8',
        'nome': 'OUTRAS RECEITAS E DESPESAS OPERACIONAIS',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'CREDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': None,
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '8.1',
        'nome': 'Indenização por Extravio de Cilindros e Outras Receitas',
        'pai_codigo': '8',
        'nivel': 2,
        'natureza_saldo': 'CREDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'OUTRAS_RECEITAS_OPERACIONAIS',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '8.2',
        'nome': 'Resultado na Baixa e Alienação de Imobilizado',
        'pai_codigo': '8',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'OUTRAS_DESPESAS_OPERACIONAIS',
        'grupo_fluxo': 'INVESTIMENTO'
    },

    # 9. IMPOSTOS SOBRE O LUCRO
    {
        'codigo_estrutural': '9',
        'nome': 'IMPOSTOS SOBRE O LUCRO',
        'pai_codigo': None,
        'nivel': 1,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'SINTETICA',
        'aceita_lancamento': False,
        'tipo_dre': 'IMPOSTOS_SOBRE_LUCRO',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '9.1',
        'nome': 'Provisão para IRPJ',
        'pai_codigo': '9',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'IMPOSTOS_SOBRE_LUCRO',
        'grupo_fluxo': 'OPERACIONAL'
    },
    {
        'codigo_estrutural': '9.2',
        'nome': 'Provisão para CSLL',
        'pai_codigo': '9',
        'nivel': 2,
        'natureza_saldo': 'DEVEDORA',
        'tipo': 'ANALITICA',
        'aceita_lancamento': True,
        'tipo_dre': 'IMPOSTOS_SOBRE_LUCRO',
        'grupo_fluxo': 'OPERACIONAL'
    },
]

CENTROS_CUSTO_PADRAO = [
    {'codigo': 'CC-01', 'nome': 'Rampa de Envase'},
    {'codigo': 'CC-02', 'nome': 'Logística e Frota'},
    {'codigo': 'CC-03', 'nome': 'Comercial'},
    {'codigo': 'CC-04', 'nome': 'Administração'},
]

CONDICOES_PAGAMENTO_PADRAO = [
    {
        'nome': 'À Vista',
        'parcelas': [{'dias': 0, 'percentual': '100.0000'}]
    },
    {
        'nome': '30 Dias',
        'parcelas': [{'dias': 30, 'percentual': '100.0000'}]
    },
    {
        'nome': '30/60 Dias',
        'parcelas': [
            {'dias': 30, 'percentual': '50.0000'},
            {'dias': 60, 'percentual': '50.0000'}
        ]
    },
    {
        'nome': '30/60/90 Dias',
        'parcelas': [
            {'dias': 30, 'percentual': '33.3400'},
            {'dias': 60, 'percentual': '33.3300'},
            {'dias': 90, 'percentual': '33.3300'}
        ]
    },
]


@transaction.atomic
def seed_plano_contas_padrao(tenant):
    """
    Popula o plano de contas contábil padrão para o Tenant especificado (Sprint 9A - Tarefa 2 / Correção F-04).
    Totalmente idempotente: não duplica registros existentes.
    """
    tenant_id = getattr(tenant, 'id', tenant)
    cache_contas = {}

    for item in PLANO_CONTAS_PADRAO:
        cod = item['codigo_estrutural']
        pai_cod = item['pai_codigo']
        pai_obj = cache_contas.get(pai_cod) if pai_cod else None

        conta, _ = PlanoContas.unscoped.update_or_create(
            tenant_id=tenant_id,
            codigo_estrutural=cod,
            defaults={
                'nome': item['nome'],
                'pai': pai_obj,
                'nivel': item['nivel'],
                'natureza_saldo': item['natureza_saldo'],
                'tipo': item['tipo'],
                'aceita_lancamento': item['aceita_lancamento'],
                'tipo_dre': item['tipo_dre'],
                'grupo_fluxo': item['grupo_fluxo'],
                'ativo': True
            }
        )
        cache_contas[cod] = conta

    return cache_contas


@transaction.atomic
def seed_centros_custo_padrao(tenant):
    """
    Popula os centros de custo operacionais padrão para o Tenant especificado (Sprint 9A - Tarefa 3).
    Idempotente.
    """
    tenant_id = getattr(tenant, 'id', tenant)
    criados = []
    for cc in CENTROS_CUSTO_PADRAO:
        obj, _ = CentroCusto.unscoped.update_or_create(
            tenant_id=tenant_id,
            codigo=cc['codigo'],
            defaults={
                'nome': cc['nome'],
                'ativo': True
            }
        )
        criados.append(obj)
    return criados


@transaction.atomic
def seed_condicoes_pagamento_padrao(tenant):
    """
    Popula as condições de pagamento comerciais padrão para o Tenant especificado (Sprint 9A - Tarefa 4).
    Idempotente.
    """
    tenant_id = getattr(tenant, 'id', tenant)
    criadas = []
    for cp in CONDICOES_PAGAMENTO_PADRAO:
        obj, _ = CondicaoPagamento.unscoped.update_or_create(
            tenant_id=tenant_id,
            nome=cp['nome'],
            defaults={
                'parcelas_json': cp['parcelas'],
                'ativo': True
            }
        )
        criadas.append(obj)
    return criadas


@transaction.atomic
def seed_financeiro_tenant_completo(tenant):
    """Executa todos os seeds padrão do financeiro para um tenant."""
    seed_plano_contas_padrao(tenant)
    seed_centros_custo_padrao(tenant)
    seed_condicoes_pagamento_padrao(tenant)
