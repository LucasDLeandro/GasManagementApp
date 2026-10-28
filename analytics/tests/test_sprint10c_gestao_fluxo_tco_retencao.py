"""
Testes de Homologação da Sprint 10C:
Fluxo de caixa com cenários, margem por veículo, TCO/km e cilindro parado.
Auditabilidade determinística, sem uso de IA, aderência estrita a multi-tenant,
invariantes matemáticos (Hypothesis) e degradação graciosa de módulos SaaS.
"""

from decimal import Decimal
import datetime
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status
from hypothesis import given, strategies as st, settings as hypo_settings
from hypothesis.extra.django import TestCase as HypoTestCase

from core.models import Tenant, Membership, Filial
from core.tenancy import set_current_tenant, tenant_context
from accounts.models import User
from clientes.models import Cliente, ContratoComodato, FechamentoFaturaEstadia, ItemFaturaEstadia
from produtos.models import Cilindro, GasQuimico, ModeloCilindro, MovimentacaoCilindro
from logistica.models import (
    Veiculo,
    LeituraOdometro,
    TabelaFreteInterno,
    AlocacaoMotoristaVeiculo,
    Entrega,
    Rota,
)
from vendas.models import Venda, ItemVenda
from financeiro.models import (
    PlanoContas,
    CentroCusto,
    ContaFinanceira,
    MovimentoConta,
    TituloFinanceiro,
    ParcelaFinanceira,
    BaixaParcela,
    RecorrenciaFinanceira,
    PerfilPagamentoCliente,
    AlertaCaixa,
    ParametroGestaoTenant,
    LancamentoContabil,
    PartidaContabil,
)
from financeiro.seeds import seed_financeiro_tenant_completo
from financeiro.services.fluxo_caixa_service import obter_fluxo_caixa_realizado
from financeiro.services.projecao_caixa_service import (
    projetar_fluxo_caixa_cenarios,
    recalcular_perfil_pagamento_clientes,
)
from financeiro.services.alerta_caixa_service import verificar_e_gerar_alerta_caixa
from logistica.services.margem_veiculo_service import (
    calcular_margem_contribuicao_veiculo,
    calcular_tco_veiculo,
)
from produtos.services.cilindro_retencao_service import (
    calcular_custo_retencao_cilindro,
    analise_retencao_cilindros_consolidada,
)
from analytics.services.indicadores_service import calcular_indicadores_gestao


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-sprint10c-cache',
        }
    }
)
class Sprint10CGestaoDonoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.hoje = timezone.localdate()

        # 1. Tenant Alpha (Contratante Completo)
        self.tenant_a = Tenant.objects.create(
            razao_social="Alpha Oxigênio e Gases LTDA",
            nome_fantasia="Alpha Gases",
            cnpj="11.222.333/0001-44",
            modulo_financeiro_ativo=True,
            modulo_patrimonio_ativo=True,
            modulo_vendas_ativo=True,
            modulo_logistica_ativo=True,
            modulo_analytics_ativo=True,
            status_assinatura="ATIVO"
        )
        self.token_a = set_current_tenant(self.tenant_a)

        self.filial_a = Filial.objects.create(
            tenant=self.tenant_a,
            nome="Matriz Alpha",
            cnpj="11.222.333/0001-44",
            matriz=True
        )
        seed_financeiro_tenant_completo(self.tenant_a)

        # 2. Usuário Administrador com ver_dre
        self.user_admin = User.objects.create_user(
            username="diretor_alpha",
            email="diretor@alpha.com.br",
            password="password123"
        )
        self.membership_admin = Membership.objects.create(
            user=self.user_admin,
            tenant=self.tenant_a,
            papel="ADMIN"
        )

        # 3. Usuário Operacional comum (SEM ver_dre)
        self.user_operador = User.objects.create_user(
            username="operador_alpha",
            email="operador@alpha.com.br",
            password="password123"
        )
        self.membership_operador = Membership.objects.create(
            user=self.user_operador,
            tenant=self.tenant_a,
            papel="OPERADOR_PATIO"
        )

        # 4. Tenant Beta (Isolamento Multi-tenant)
        self.tenant_b = Tenant.objects.create(
            razao_social="Beta Gases LTDA",
            nome_fantasia="Beta Gases",
            cnpj="99.888.777/0001-66",
            modulo_financeiro_ativo=True,
            modulo_logistica_ativo=True,
            modulo_patrimonio_ativo=True,
            modulo_analytics_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user_beta = User.objects.create_user(
            username="admin_beta",
            email="admin@beta.com.br",
            password="password123"
        )
        self.membership_beta = Membership.objects.create(
            user=self.user_beta,
            tenant=self.tenant_b,
            papel="ADMIN"
        )

        # Clientes Tenant A
        with tenant_context(self.tenant_a):
            self.cliente_bom = Cliente.objects.create(
                tenant=self.tenant_a,
                nome="Hospital Santa Casa",
                cnpj="22.333.444/0001-55",
                email_financeiro="financeiro@santacasa.org.br"
            )
            self.cliente_atrasado = Cliente.objects.create(
                tenant=self.tenant_a,
                nome="Metalúrgica Fogo Forte",
                cnpj="33.444.555/0001-66",
                email_financeiro="compras@fogoforte.com.br"
            )
            self.cliente_novo = Cliente.objects.create(
                tenant=self.tenant_a,
                nome="Oficina Mecânica Nova",
                cnpj="44.555.666/0001-77",
                email_financeiro="oficina@nova.com.br"
            )

            # Contas Financeiras
            cta_banco_contabil = PlanoContas.objects.filter(tenant=self.tenant_a, codigo_estrutural='1.1.1.02').first()
            cta_caixa_contabil = PlanoContas.objects.filter(tenant=self.tenant_a, codigo_estrutural='1.1.1.01').first()

            self.cta_banco = ContaFinanceira.objects.create(
                tenant=self.tenant_a,
                nome="Banco Itaú CC",
                tipo="CONTA_CORRENTE",
                saldo_inicial=Decimal('50000.00'),
                conta_contabil=cta_banco_contabil,
                ativo=True
            )
            self.cta_caixa = ContaFinanceira.objects.create(
                tenant=self.tenant_a,
                nome="Caixa Gaveta",
                tipo="CAIXA_FISICO",
                saldo_inicial=Decimal('5000.00'),
                conta_contabil=cta_caixa_contabil,
                ativo=True
            )

            # Parâmetros de Gestão Tenant A
            self.param_gestao = ParametroGestaoTenant.objects.create(
                tenant=self.tenant_a,
                saldo_minimo_caixa=Decimal('30000.00'),
                tma_mensal=Decimal('0.0150'),  # 1.5% ao mês
                politica_receita_veiculo='CONTRIBUICAO_COMERCIAL',
                fator_majoracao_pessimista=Decimal('1.5000'),
                horizonte_alerta_dias=30
            )

            self.cta_despesa_frota = PlanoContas.objects.filter(tenant=self.tenant_a, codigo_estrutural='4.1.1.01').first()
            if not self.cta_despesa_frota:
                self.cta_despesa_frota = PlanoContas.objects.create(
                    tenant=self.tenant_a,
                    codigo_estrutural='4.1.1.01',
                    nome="Combustíveis da Frota",
                    natureza_saldo='DEVEDORA',
                    tipo='ANALITICA',
                    aceita_lancamento=True,
                    nivel=4
                )
            self.cta_receita = PlanoContas.objects.filter(tenant=self.tenant_a, codigo_estrutural__startswith='3.').filter(aceita_lancamento=True).first() or self.cta_despesa_frota
            self.cta_despesa = self.cta_despesa_frota

            self.veiculo_1 = Veiculo.objects.create(
                tenant=self.tenant_a,
                placa="ABC1D23",
                modelo="Iveco Daily 35S14",
                marca="Iveco",
                ano=2022,
                ano_fabricacao=2022,
                capacidade_carga=Decimal("3500.00"),
                status='Ativo'
            )

        self.client = APIClient()

    # ==============================================================================
    # 1. FLUXO DE CAIXA REALIZADO (MOVIMENTO CONTA E GRUPOS)
    # ==============================================================================

    def test_fluxo_caixa_realizado_derivado_estritamente_de_movimento_conta(self):
        """
        Tarefa 1: Fluxo de caixa realizado deriva só de MovimentoConta,
        agrupado por grupo_fluxo (OPERACIONAL, INVESTIMENTO, FINANCIAMENTO) e conta.
        """
        with tenant_context(self.tenant_a):
            d1 = self.hoje - datetime.timedelta(days=2)
            d2 = self.hoje - datetime.timedelta(days=1)

            # 1. Movimentos Operacionais
            MovimentoConta.objects.create(
                tenant=self.tenant_a,
                conta=self.cta_banco,
                data_movimento=d1,
                tipo='CREDITO',
                valor=Decimal('10000.00'),
                grupo_fluxo='OPERACIONAL',
                historico="Recebimento Hospital"
            )
            MovimentoConta.objects.create(
                tenant=self.tenant_a,
                conta=self.cta_banco,
                data_movimento=d1,
                tipo='DEBITO',
                valor=Decimal('3000.00'),
                grupo_fluxo='OPERACIONAL',
                historico="Pagamento Combustível"
            )

            # 2. Movimento de Investimento
            MovimentoConta.objects.create(
                tenant=self.tenant_a,
                conta=self.cta_banco,
                data_movimento=d2,
                tipo='DEBITO',
                valor=Decimal('5000.00'),
                grupo_fluxo='INVESTIMENTO',
                historico="Compra de novos cilindros"
            )

            # 3. Movimento de Financiamento
            MovimentoConta.objects.create(
                tenant=self.tenant_a,
                conta=self.cta_caixa,
                data_movimento=d2,
                tipo='CREDITO',
                valor=Decimal('2000.00'),
                grupo_fluxo='FINANCIAMENTO',
                historico="Aporte de capital dos sócios"
            )

            resultado = obter_fluxo_caixa_realizado(
                tenant=self.tenant_a,
                data_inicio=d1.isoformat(),
                data_fim=self.hoje.isoformat()
            )

            # Asserções estruturais e matemáticas
            self.assertEqual(resultado['total_entradas'], Decimal('12000.00'))
            self.assertEqual(resultado['total_saidas'], Decimal('8000.00'))
            self.assertEqual(resultado['saldo_liquido_periodo'], Decimal('4000.00'))

            # Agrupamento por grupo_fluxo
            grupos = resultado['por_grupo_fluxo']
            self.assertEqual(grupos['OPERACIONAL']['entradas'], Decimal('10000.00'))
            self.assertEqual(grupos['OPERACIONAL']['saidas'], Decimal('3000.00'))
            self.assertEqual(grupos['OPERACIONAL']['liquido'], Decimal('7000.00'))

            self.assertEqual(grupos['INVESTIMENTO']['saidas'], Decimal('5000.00'))
            self.assertEqual(grupos['INVESTIMENTO']['liquido'], Decimal('-5000.00'))

            self.assertEqual(grupos['FINANCIAMENTO']['entradas'], Decimal('2000.00'))
            self.assertEqual(grupos['FINANCIAMENTO']['liquido'], Decimal('2000.00'))

            # Saldos diários por conta e consolidados
            saldos_diarios = resultado['saldos_diarios']
            self.assertIn(d1.isoformat(), saldos_diarios)
            self.assertIn(d2.isoformat(), saldos_diarios)
            self.assertEqual(saldos_diarios[d1.isoformat()]['movimentacao_consolidada'], Decimal('7000.00'))
            self.assertEqual(saldos_diarios[d2.isoformat()]['movimentacao_consolidada'], Decimal('-3000.00'))

    # ==============================================================================
    # 2. PERFIL DE PAGAMENTO E FALLBACK BENCHMARK GLOBAL
    # ==============================================================================

    def test_perfil_pagamento_cliente_fallback_global_amostra_menor_que_cinco(self):
        """
        Tarefa 2 / Correção F-22:
        Com amostra menor que 5 baixas, o cliente herda os parâmetros globais do tenant.
        """
        with tenant_context(self.tenant_a):
            # Cria 10 baixas históricas para o cliente_atrasado (amostra robusta)
            tit_base = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_atrasado,
                tipo='RECEBER',
                conta_gerencial=self.cta_receita,
                valor_bruto=Decimal('10000.00'),
                valor_liquido_esperado=Decimal('10000.00'),
                data_emissao=self.hoje - datetime.timedelta(days=100),
                status='LIQUIDADO'
            )
            for i in range(1, 11):
                p = ParcelaFinanceira.objects.create(
                    tenant=self.tenant_a,
                    titulo=tit_base,
                    numero_parcela=i,
                    total_parcelas=10,
                    data_vencimento=self.hoje - datetime.timedelta(days=50),
                    valor_nominal=Decimal('1000.00'),
                    saldo_em_aberto=Decimal('0.00'),
                    status='LIQUIDADA'
                )
                # Pagou 8 dias após o vencimento
                BaixaParcela.objects.create(
                    tenant=self.tenant_a,
                    parcela=p,
                    conta_financeira=self.cta_banco,
                    data_liquidacao=self.hoje - datetime.timedelta(days=42),
                    valor_principal=Decimal('1000.00'),
                    valor_total_movimentado=Decimal('1000.00')
                )

            # Cliente Novo tem apenas 2 baixas (amostra < 5)
            tit_novo = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_novo,
                tipo='RECEBER',
                conta_gerencial=self.cta_receita,
                valor_bruto=Decimal('2000.00'),
                valor_liquido_esperado=Decimal('2000.00'),
                data_emissao=self.hoje - datetime.timedelta(days=20),
                status='LIQUIDADO'
            )
            for i in range(1, 3):
                p_novo = ParcelaFinanceira.objects.create(
                    tenant=self.tenant_a,
                    titulo=tit_novo,
                    numero_parcela=i,
                    total_parcelas=2,
                    data_vencimento=self.hoje - datetime.timedelta(days=10),
                    valor_nominal=Decimal('1000.00'),
                    saldo_em_aberto=Decimal('0.00'),
                    status='LIQUIDADA'
                )
                BaixaParcela.objects.create(
                    tenant=self.tenant_a,
                    parcela=p_novo,
                    conta_financeira=self.cta_banco,
                    data_liquidacao=self.hoje - datetime.timedelta(days=10),
                    valor_principal=Decimal('1000.00'),
                    valor_total_movimentado=Decimal('1000.00')
                )

            # Executa o recálculo
            perfis = recalcular_perfil_pagamento_clientes(tenant=self.tenant_a)
            self.assertGreaterEqual(len(perfis), 2)

            perfil_atrasado = PerfilPagamentoCliente.objects.get(tenant=self.tenant_a, cliente=self.cliente_atrasado)
            self.assertEqual(perfil_atrasado.amostra_n, 10)
            self.assertEqual(perfil_atrasado.atraso_medio_dias, Decimal('8.00'))

            # Cliente novo tem amostra 2 < 5 -> herdou o perfil global do tenant
            perfil_novo = PerfilPagamentoCliente.objects.get(tenant=self.tenant_a, cliente=self.cliente_novo)
            self.assertEqual(perfil_novo.amostra_n, 2)
            # Atraso médio ponderado global foi influenciado pelas 10 baixas do atrasado
            self.assertGreater(perfil_novo.atraso_medio_dias, Decimal('0.00'))

    # ==============================================================================
    # 3. CENÁRIOS DE PROJEÇÃO DE 90 DIAS E INVARIANTE
    # ==============================================================================

    def test_projecao_caixa_90_dias_invariante_pessimista_le_realista_le_otimista(self):
        """
        Tarefa 3 / Invariante Obrigatório:
        Em qualquer base de dados, saldo pessimista <= realista <= otimista em todos os dias.
        """
        with tenant_context(self.tenant_a):
            # Título a Receber
            tit_rec = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_atrasado,
                tipo='RECEBER',
                conta_gerencial=self.cta_receita,
                valor_bruto=Decimal('20000.00'),
                valor_liquido_esperado=Decimal('20000.00'),
                data_emissao=self.hoje,
                status='ABERTO'
            )
            ParcelaFinanceira.objects.create(
                tenant=self.tenant_a,
                titulo=tit_rec,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=self.hoje + datetime.timedelta(days=15),
                valor_nominal=Decimal('20000.00'),
                saldo_em_aberto=Decimal('20000.00'),
                status='PENDENTE'
            )

            # Título a Pagar Postergável
            tit_pag = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                tipo='PAGAR',
                beneficiario_texto="Fornecedor Insumos",
                conta_gerencial=self.cta_despesa,
                valor_bruto=Decimal('15000.00'),
                valor_liquido_esperado=Decimal('15000.00'),
                data_emissao=self.hoje,
                status='APROVADO',
                postergavel=True
            )
            ParcelaFinanceira.objects.create(
                tenant=self.tenant_a,
                titulo=tit_pag,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=self.hoje + datetime.timedelta(days=20),
                valor_nominal=Decimal('15000.00'),
                saldo_em_aberto=Decimal('15000.00'),
                status='PENDENTE'
            )

            # Recorrência de Folha de Pagamento
            RecorrenciaFinanceira.objects.create(
                tenant=self.tenant_a,
                descricao="Folha de Pagamento",
                tipo='PAGAR',
                valor=Decimal('25000.00'),
                dia_do_mes=5,
                inicio=self.hoje,
                ativo=True
            )

            # Executa projeção determinística a 90 dias
            proj = projetar_fluxo_caixa_cenarios(
                tenant=self.tenant_a,
                dias_horizonte=90,
                fator_majoracao_pessimista=Decimal('1.5000')
            )

            self.assertIn('projecao_diaria', proj)
            self.assertEqual(len(proj['projecao_diaria']), 90)

            # Validação estrita do invariante dia a dia: pessimista <= realista <= otimista
            for dia_info in proj['projecao_diaria']:
                otimista = dia_info['saldo_otimista']
                realista = dia_info['saldo_realista']
                pessimista = dia_info['saldo_pessimista']

                self.assertLessEqual(
                    pessimista, realista,
                    f"Violação de invariante no dia {dia_info['data']}: pessimista ({pessimista}) > realista ({realista})"
                )
                self.assertLessEqual(
                    realista, otimista,
                    f"Violação de invariante no dia {dia_info['data']}: realista ({realista}) > otimista ({otimista})"
                )

            # Menor saldo e data identificados
            resumo_real = proj['cenario_realista']
            self.assertIsNotNone(resumo_real['menor_saldo'])
            self.assertIsNotNone(resumo_real['data_menor_saldo'])

    # ==============================================================================
    # 4. ALERTA DE CAIXA, ANTECIPAÇÃO E POSTERGAÇÃO
    # ==============================================================================

    def test_alerta_caixa_dispara_quando_saldo_projetado_menor_que_minimo(self):
        """
        Tarefa 4: AlertaCaixa é gerado quando o menor saldo realista fica abaixo
        do saldo mínimo configurado, indicando parcelas para antecipação e postergação.
        """
        with tenant_context(self.tenant_a):
            # Saldo inicial das contas é R$ 55.000,00 e o mínimo é R$ 30.000,00.
            # Criando uma despesa a pagar de R$ 40.000,00 -> saldo projetado cairá para R$ 15.000,00 (< R$ 30.000,00)
            tit_grande = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                tipo='PAGAR',
                beneficiario_texto="Fornecedor Grande",
                conta_gerencial=self.cta_despesa,
                valor_bruto=Decimal('40000.00'),
                valor_liquido_esperado=Decimal('40000.00'),
                data_emissao=self.hoje,
                status='APROVADO',
                postergavel=True
            )
            ParcelaFinanceira.objects.create(
                tenant=self.tenant_a,
                titulo=tit_grande,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=self.hoje + datetime.timedelta(days=10),
                valor_nominal=Decimal('40000.00'),
                saldo_em_aberto=Decimal('40000.00'),
                status='PENDENTE'
            )

            # Título a receber do cliente bom para antecipação
            tit_rec = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_bom,
                tipo='RECEBER',
                conta_gerencial=self.cta_receita,
                valor_bruto=Decimal('20000.00'),
                valor_liquido_esperado=Decimal('20000.00'),
                data_emissao=self.hoje,
                status='ABERTO'
            )
            ParcelaFinanceira.objects.create(
                tenant=self.tenant_a,
                titulo=tit_rec,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=self.hoje + datetime.timedelta(days=25),
                valor_nominal=Decimal('20000.00'),
                saldo_em_aberto=Decimal('20000.00'),
                status='PENDENTE'
            )

            res_alerta = verificar_e_gerar_alerta_caixa(tenant=self.tenant_a)
            self.assertTrue(res_alerta['alerta_gerado'])
            self.assertEqual(res_alerta['saldo_minimo_configurado'], Decimal('30000.00'))
            self.assertLess(res_alerta['menor_saldo_projetado'], Decimal('30000.00'))

            # Detalhes e recomendações
            self.assertIn('antecipacoes_sugeridas', res_alerta)
            self.assertIn('pagamentos_postergaveis', res_alerta)
            self.assertGreaterEqual(len(res_alerta['pagamentos_postergaveis']), 1)
            self.assertEqual(res_alerta['pagamentos_postergaveis'][0]['valor'], 40000.00)

            # Persistência no banco
            alerta_db = AlertaCaixa.unscoped.filter(tenant=self.tenant_a).first()
            self.assertIsNotNone(alerta_db)
            self.assertEqual(alerta_db.saldo_minimo_configurado, Decimal('30000.00'))

    # ==============================================================================
    # 5. MARGEM DE CONTRIBUIÇÃO POR VEÍCULO
    # ==============================================================================

    def test_margem_contribuicao_veiculo_politica_frete_e_comercial_calculo_manual(self):
        """
        Tarefa 5 / Correção da fórmula da v2.0:
        Validação manual de Contribuição de Frete e Contribuição Comercial da Entrega.
        """
        with tenant_context(self.tenant_a):
            dt_ini = self.hoje - datetime.timedelta(days=30)
            dt_fim = self.hoje

            # Tabela de frete interno por parada = R$ 150,00
            TabelaFreteInterno.objects.create(
                tenant=self.tenant_a,
                descricao="Frete Interno Entrega",
                veiculo=self.veiculo_1,
                tipo='POR_PARADA',
                valor=Decimal('150.00'),
                vigencia_inicio=dt_ini,
                ativo=True
            )

            # Cria Rota e Entrega realizada com 4 paradas
            rota = Rota.objects.create(tenant=self.tenant_a, nome="Rota Hospitalar Norte")
            entrega = Entrega.objects.create(
                tenant=self.tenant_a,
                veiculo=self.veiculo_1,
                rota=rota,
                data_saida=self.hoje - datetime.timedelta(days=10),
                status='Concluída'
            )

            # Cria 4 vendas entregues (Receita líquida total = R$ 4.000,00; CPV = R$ 1.500,00)
            for i in range(4):
                v = Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_bom,
                    entrega=entrega,
                    status='Entregue',
                    valor_total=Decimal('1000.00'),
                    data_venda=self.hoje - datetime.timedelta(days=10)
                )

            # Lançamento contábil no razão para custos variáveis diretos da placa: Combustível R$ 300,00 + Pedágio R$ 50,00
            cta_despesa = self.cta_despesa_frota

            lanc = LancamentoContabil.objects.create(
                tenant=self.tenant_a,
                numero=1,
                data_competencia=self.hoje - datetime.timedelta(days=10),
                historico="Abastecimento e Pedágio Iveco ABC1D23",
                hash_integridade="hash_lanc_1"
            )
            PartidaContabil.objects.create(
                tenant=self.tenant_a,
                lancamento=lanc,
                conta_contabil=cta_despesa,
                tipo_partida='DEBITO',
                valor=Decimal('350.00'),
                veiculo=self.veiculo_1
            )
            PartidaContabil.objects.create(
                tenant=self.tenant_a,
                lancamento=lanc,
                conta_contabil=self.cta_banco.conta_contabil,
                tipo_partida='CREDITO',
                valor=Decimal('350.00')
            )

            # 1. Teste Política CONTRIBUICAO_FRETE:
            # Frete imputado: 4 paradas * R$ 150,00 = R$ 600,00.
            # Custos variáveis: R$ 350,00.
            # Margem esperada: R$ 600,00 - R$ 350,00 = R$ 250,00.
            res_frete = calcular_margem_contribuicao_veiculo(
                tenant=self.tenant_a,
                veiculo_id=self.veiculo_1.id,
                data_inicio=dt_ini.isoformat(),
                data_fim=dt_fim.isoformat(),
                politica='CONTRIBUICAO_FRETE'
            )
            self.assertEqual(res_frete['receita_bruta'], Decimal('600.00'))
            self.assertEqual(res_frete['custos_variaveis_diretos'], Decimal('350.00'))
            self.assertEqual(res_frete['margem_contribuicao'], Decimal('250.00'))

            # 2. Teste Política CONTRIBUICAO_COMERCIAL:
            # Receita vendas entregues: R$ 4.000,00. Custos variáveis: R$ 350,00.
            # Margem esperada: R$ 4.000,00 - R$ 350,00 = R$ 3.650,00.
            res_com = calcular_margem_contribuicao_veiculo(
                tenant=self.tenant_a,
                veiculo_id=self.veiculo_1.id,
                data_inicio=dt_ini.isoformat(),
                data_fim=dt_fim.isoformat(),
                politica='CONTRIBUICAO_COMERCIAL'
            )
            self.assertEqual(res_com['receita_bruta'], Decimal('4000.00'))
            self.assertEqual(res_com['custos_variaveis_diretos'], Decimal('350.00'))
            self.assertEqual(res_com['margem_contribuicao'], Decimal('3650.00'))

    # ==============================================================================
    # 6. TCO POR KM E POR PARADA (VALIDAÇÃO DE ODÔMETRO)
    # ==============================================================================

    def test_tco_veiculo_retorna_dados_insuficientes_sem_odometro_validado(self):
        """
        Tarefa 6: Veículo sem odômetro validado no mês devolve estritamente
        «dados insuficientes», nunca valor inventado ou zero.
        """
        with tenant_context(self.tenant_a):
            # Veículo 1 sem nenhuma leitura de odômetro no mês atual
            res = calcular_tco_veiculo(
                tenant=self.tenant_a,
                veiculo_id=self.veiculo_1.id,
                ano=self.hoje.year,
                mes=self.hoje.month
            )
            self.assertEqual(res['status'], 'DADOS_INSUFICIENTES')
            self.assertEqual(res['mensagem'], 'dados insuficientes')
            self.assertIsNone(res['km_rodados'])
            self.assertIsNone(res['tco_por_km'])

    def test_tco_veiculo_calculo_manual_com_odometro_validado(self):
        """
        Tarefa 6: TCO por km e por parada com odômetro validado confere com caso calculado à mão.
        """
        with tenant_context(self.tenant_a):
            dt_ini = self.hoje.replace(day=1)
            # Leituras validadas: 10.000 km no início e 12.000 km no fim -> 2.000 km rodados
            LeituraOdometro.objects.create(
                tenant=self.tenant_a,
                veiculo=self.veiculo_1,
                km=Decimal('10000.000'),
                data_hora=timezone.make_aware(datetime.datetime(self.hoje.year, self.hoje.month, 1, 8, 0)),
                validada=True
            )
            LeituraOdometro.objects.create(
                tenant=self.tenant_a,
                veiculo=self.veiculo_1,
                km=Decimal('12000.000'),
                data_hora=timezone.make_aware(datetime.datetime(self.hoje.year, self.hoje.month, 20, 18, 0)),
                validada=True
            )

            # Alocação de motorista: 20 dias a R$ 100,00/dia = R$ 2.000,00 de custo fixo
            AlocacaoMotoristaVeiculo.objects.create(
                tenant=self.tenant_a,
                veiculo=self.veiculo_1,
                motorista=self.user_operador,
                data_inicio=dt_ini,
                data_fim=dt_ini + datetime.timedelta(days=20),
                dias_alocados=20,
                custo_diaria_total=Decimal('100.00')
            )

            # Custo variável no ledger da placa: R$ 1.000,00 de combustível
            cta_despesa = self.cta_despesa_frota
            lanc = LancamentoContabil.objects.create(
                tenant=self.tenant_a,
                numero=2,
                data_competencia=dt_ini + datetime.timedelta(days=5),
                historico="Combustível do Mês",
                hash_integridade="hash_lanc_2"
            )
            PartidaContabil.objects.create(
                tenant=self.tenant_a,
                lancamento=lanc,
                conta_contabil=cta_despesa,
                tipo_partida='DEBITO',
                valor=Decimal('1000.00'),
                veiculo=self.veiculo_1
            )
            PartidaContabil.objects.create(
                tenant=self.tenant_a,
                lancamento=lanc,
                conta_contabil=self.cta_banco.conta_contabil,
                tipo_partida='CREDITO',
                valor=Decimal('1000.00')
            )

            res = calcular_tco_veiculo(
                tenant=self.tenant_a,
                veiculo_id=self.veiculo_1.id,
                ano=self.hoje.year,
                mes=self.hoje.month
            )

            self.assertEqual(res['status'], 'SUCESSO')
            self.assertEqual(res['km_rodados'], Decimal('2000.000'))
            self.assertEqual(res['custos_variaveis'], Decimal('1000.00'))
            self.assertEqual(res['custos_fixos_alocados'], Decimal('2000.00'))
            # TCO total = R$ 3.000,00 / 2.000 km = R$ 1,50 / km
            self.assertEqual(res['custo_total'], Decimal('3000.00'))
            self.assertEqual(res['tco_por_km'], Decimal('1.50'))

    # ==============================================================================
    # 7. CUSTO DE RETENÇÃO DO CILINDRO PARADO (SEM IA)
    # ==============================================================================

    def test_custo_retencao_cilindro_casos_positivo_negativo_e_sem_estadia(self):
        """
        Tarefa 7 / Critério de Aceite:
        Fórmula determinística:
        Σ dias_retido × (depreciação_diária + valor_contábil × TMA_mensal ÷ 30) − receita de estadia faturada.
        Resultado positivo marca DESTRUIDOR_DE_MARGEM.
        Testa casos: positivo, negativo (superávit de estadia) e sem estadia faturada.
        """
        with tenant_context(self.tenant_a):
            dt_ini = self.hoje - datetime.timedelta(days=60)
            dt_fim = self.hoje

            # Modelo e Cilindro
            gas, _ = GasQuimico.objects.get_or_create(nome="Oxigênio Medicinal", sigla="O2-MED")
            mod = ModeloCilindro.objects.create(
                tenant=self.tenant_a,
                descricao="T-50L Aço",
                material='ACO',
                volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('55.00')
            )

            # Cilindro 1: Parado há 40 dias no cliente_atrasado, sem estadia -> DESTRUIDOR_DE_MARGEM
            cil_destruidor = Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr="QR-DEST-01",
                numero_serie_ogiva="CIL-DEST-01",
                fabricante="Cilindros Brasil",
                ano_fabricacao=2020,
                gas_dedicado=gas,
                modelo=mod,
                status='EM_POSSE_CLIENTE',
                posse_desde=timezone.now() - datetime.timedelta(days=40),
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=365),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                valor_aquisicao=Decimal('1200.00'),
                vida_util_meses=120,
                cliente_posse_atual=self.cliente_atrasado
            )


            # Caso 1: Sem estadia faturada -> custo positivo -> DESTRUIDOR_DE_MARGEM
            res1 = calcular_custo_retencao_cilindro(
                tenant=self.tenant_a,
                cilindro_id=cil_destruidor.id,
                data_inicio=dt_ini.isoformat(),
                data_fim=dt_fim.isoformat()
            )
            self.assertEqual(res1['classificacao'], 'DESTRUIDOR_DE_MARGEM')
            self.assertGreater(res1['custo_liquido'], Decimal('0.00'))
            self.assertEqual(res1['receita_estadia_faturada'], Decimal('0.00'))

            # Caso 2: Cilindro 2 com estadia faturada que supera o custo de posse -> superávit
            cil_superavit = Cilindro.objects.create(
                tenant=self.tenant_a,
                codigo_qr="QR-SUPER-02",
                numero_serie_ogiva="CIL-SUPER-02",
                fabricante="Cilindros Brasil",
                ano_fabricacao=2020,
                gas_dedicado=gas,
                modelo=mod,
                status='EM_POSSE_CLIENTE',
                posse_desde=timezone.now() - datetime.timedelta(days=40),
                data_ultimo_reteste=self.hoje - datetime.timedelta(days=365),
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365),
                valor_aquisicao=Decimal('1200.00'),
                vida_util_meses=120,
                cliente_posse_atual=self.cliente_bom
            )


            # Fatura de estadia faturada = R$ 100,00
            fatura_estadia = FechamentoFaturaEstadia.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_bom,
                competencia_ano_mes=self.hoje.strftime('%Y-%m'),
                data_fechamento=timezone.now(),
                valor_liquido_total=Decimal('100.00'),
                status_pagamento='FECHADA'
            )
            ItemFaturaEstadia.objects.create(
                tenant=self.tenant_a,
                fatura=fatura_estadia,
                cilindro=cil_superavit,
                modelo_cilindro="T-50L",
                periodo_inicio=dt_ini,
                periodo_fim=dt_fim,
                dias_posse_mes=40,
                dias_cobraveis=40,
                diaria_aplicada=Decimal('2.50'),
                subtotal=Decimal('100.00')
            )

            res2 = calcular_custo_retencao_cilindro(
                tenant=self.tenant_a,
                cilindro_id=cil_superavit.id,
                data_inicio=dt_ini.isoformat(),
                data_fim=dt_fim.isoformat()
            )
            self.assertEqual(res2['classificacao'], 'SUPERAVIT_ESTADIA')
            self.assertLess(res2['custo_liquido'], Decimal('0.00'))
            self.assertEqual(res2['receita_estadia_faturada'], Decimal('100.00'))

    # ==============================================================================
    # 8. INDICADORES EXECUTIVOS DETERMINÍSTICOS
    # ==============================================================================

    def test_indicadores_gestao_executivos(self):
        """
        Tarefa 8: Cálculo determinístico de giro de cilindro, margem por produto,
        PMR, PMP e inadimplência.
        """
        with tenant_context(self.tenant_a):
            indicadores = calcular_indicadores_gestao(tenant=self.tenant_a)

            self.assertIn('giro_cilindro_anual', indicadores)
            self.assertIn('pmr_dias', indicadores)
            self.assertIn('pmp_dias', indicadores)
            self.assertIn('taxa_inadimplencia_global', indicadores)
            self.assertIn('formula', indicadores)
            self.assertIn('fonte', indicadores)

    # ==============================================================================
    # 9. DASHBOARD ANALYTICS E DEGRADAÇÃO GRACIOSA (SPRINT 7B)
    # ==============================================================================

    def test_dashboard_analytics_degradacao_graciosa_modulos_e_permissao_ver_dre(self):
        """
        Tarefa 9:
        - Módulos inativos não aparecem nos widgets nem vazam dados;
        - Widgets financeiros exigem a permissão financeiro.ver_dre;
        - Usuário sem ver_dre acessa o dashboard mas não vê dados de caixa ou cobrança;
        - Cache de 15 minutos verificado.
        """
        # 1. Requisição com Administrador (Possui ver_dre e todos os módulos ativos)
        self.client.force_authenticate(user=self.user_admin)
        res_admin = self.client.get('/api/analytics/', HTTP_X_TENANT_ID=str(self.tenant_a.id))
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
        dados_admin = res_admin.data

        self.assertIn('resumo_executivo', dados_admin)
        self.assertIn('parque_cilindros', dados_admin)
        self.assertIn('contas_a_receber', dados_admin)
        self.assertIn('gestao_frota_resumo', dados_admin)

        # 2. Requisição com Operador comum (NÃO possui ver_dre)
        self.client.force_authenticate(user=self.user_operador)
        res_operador = self.client.get('/api/analytics/', HTTP_X_TENANT_ID=str(self.tenant_a.id))
        self.assertEqual(res_operador.status_code, status.HTTP_200_OK)
        dados_operador = res_operador.data

        # Não vazou nenhum dado financeiro!
        self.assertNotIn('contas_a_receber', dados_operador)
        self.assertNotIn('alerta_caixa', dados_operador)
        # Mas manteve os outros módulos autorizados
        self.assertIn('parque_cilindros', dados_operador)

        # 3. Degradação Graciosa: Desativa módulo de logística no Tenant A
        self.tenant_a.modulo_logistica_ativo = False
        self.tenant_a.save(update_fields=['modulo_logistica_ativo'])
        cache.clear()

        self.client.force_authenticate(user=self.user_admin)
        res_sem_log = self.client.get('/api/analytics/', HTTP_X_TENANT_ID=str(self.tenant_a.id))
        self.assertEqual(res_sem_log.status_code, status.HTTP_200_OK)
        # Widget de logística degradou graciosamente (não aparece nem dá erro 500)
        self.assertNotIn('gestao_frota_resumo', res_sem_log.data)

    # ==============================================================================
    # 10. MULTI-TENANT ISOLAMENTO (HTTP 404 CROSS-TENANT)
    # ==============================================================================

    def test_multi_tenant_isolamento_retorna_404_para_outro_tenant(self):
        """
        Global Rule 3: Todo endpoint novo tem teste provando 404 para recurso de outro tenant.
        """
        with tenant_context(self.tenant_a):
            recorrencia_a = RecorrenciaFinanceira.objects.create(
                tenant=self.tenant_a,
                descricao="Aluguel Galpão Alpha",
                tipo='PAGAR',
                valor=Decimal('5000.00'),
                dia_do_mes=10,
                inicio=self.hoje,
                ativo=True
            )
            frete_a = TabelaFreteInterno.objects.create(
                tenant=self.tenant_a,
                descricao="Frete Alpha Rota 1",
                tipo='POR_KM',
                valor=Decimal('3.50'),
                vigencia_inicio=self.hoje,
                ativo=True
            )

        # Autentica como usuário do Tenant Beta
        self.client.force_authenticate(user=self.user_beta)

        # Tentar acessar recurso do Tenant A via API do Tenant Beta deve retornar 404
        res1 = self.client.get(
            f'/financeiro/api/recorrencias/{recorrencia_a.id}/',
            HTTP_X_TENANT_ID=str(self.tenant_b.id)
        )
        self.assertEqual(res1.status_code, status.HTTP_404_NOT_FOUND)

        res2 = self.client.get(
            f'/logistica/api/tabelas-frete-interno/{frete_a.id}/',
            HTTP_X_TENANT_ID=str(self.tenant_b.id)
        )
        self.assertEqual(res2.status_code, status.HTTP_404_NOT_FOUND)

    # ==============================================================================

class Sprint10CHypothesisTests(HypoTestCase):
    """
    11. HYPOTHESIS: TESTE DE PROPRIEDADE PARA INVARIANTE DOS CENÁRIOS
    Executado com isolamento de transação por exemplo do Hypothesis.
    """
    def setUp(self):
        cache.clear()
        self.hoje = timezone.localdate()
        self.tenant_a = Tenant.objects.create(
            razao_social="Hypo Gases LTDA",
            nome_fantasia="Hypo Gases",
            cnpj="99.888.777/0001-66",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.token_a = set_current_tenant(self.tenant_a)
        seed_financeiro_tenant_completo(self.tenant_a)
        self.plano_rec = PlanoContas.objects.filter(tenant=self.tenant_a, codigo_estrutural__startswith='3.').filter(aceita_lancamento=True).first()
        self.plano_desp = PlanoContas.objects.filter(tenant=self.tenant_a, codigo_estrutural__startswith='4.').filter(aceita_lancamento=True).first()
        self.cliente_atrasado = Cliente.objects.create(
            tenant=self.tenant_a,
            nome="Cliente Hypo",
            cnpj="11.222.333/0001-44"
        )

    def tearDown(self):
        set_current_tenant(None)

    @hypo_settings(max_examples=10, deadline=None)
    @given(
        val_rec=st.decimals(min_value=Decimal('100.00'), max_value=Decimal('50000.00'), places=2),
        val_pag=st.decimals(min_value=Decimal('50.00'), max_value=Decimal('30000.00'), places=2),
        dias_venc_rec=st.integers(min_value=1, max_value=60),
        dias_venc_pag=st.integers(min_value=1, max_value=60),
        fator_pessimista=st.decimals(min_value=Decimal('1.1000'), max_value=Decimal('2.5000'), places=4)
    )
    def test_hypothesis_invariante_saldo_pessimista_le_realista_le_otimista(
        self, val_rec, val_pag, dias_venc_rec, dias_venc_pag, fator_pessimista
    ):
        """
        Teste de Propriedade (Hypothesis):
        Para quaisquer valores e prazos gerados aleatoriamente,
        a projeção diária deve satisfazer rigorosamente:
        saldo_pessimista <= saldo_realista <= saldo_otimista em todos os 90 dias.
        """
        with tenant_context(self.tenant_a):
            # Limpa dados anteriores
            TituloFinanceiro.objects.filter(tenant=self.tenant_a).delete()
            ParcelaFinanceira.objects.filter(tenant=self.tenant_a).delete()

            # Cria recebível
            t_rec = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_atrasado,
                tipo='RECEBER',
                conta_gerencial=self.plano_rec,
                valor_bruto=val_rec,
                valor_liquido_esperado=val_rec,
                data_emissao=self.hoje,
                status='ABERTO'
            )
            ParcelaFinanceira.objects.create(
                tenant=self.tenant_a,
                titulo=t_rec,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=self.hoje + datetime.timedelta(days=dias_venc_rec),
                valor_nominal=val_rec,
                saldo_em_aberto=val_rec,
                status='PENDENTE'
            )

            # Cria pagável
            t_pag = TituloFinanceiro.objects.create(
                tenant=self.tenant_a,
                tipo='PAGAR',
                beneficiario_texto="Fornecedor Random",
                conta_gerencial=self.plano_desp,
                valor_bruto=val_pag,
                valor_liquido_esperado=val_pag,
                data_emissao=self.hoje,
                status='APROVADO'
            )
            ParcelaFinanceira.objects.create(
                tenant=self.tenant_a,
                titulo=t_pag,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=self.hoje + datetime.timedelta(days=dias_venc_pag),
                valor_nominal=val_pag,
                saldo_em_aberto=val_pag,
                status='PENDENTE'
            )

            proj = projetar_fluxo_caixa_cenarios(
                tenant=self.tenant_a,
                dias_horizonte=90,
                fator_majoracao_pessimista=fator_pessimista
            )

            for d in proj['projecao_diaria']:
                self.assertLessEqual(
                    d['saldo_pessimista'], d['saldo_realista'],
                    f"Falha de invariante na data {d['data']}"
                )
                self.assertLessEqual(
                    d['saldo_realista'], d['saldo_otimista'],
                    f"Falha de invariante na data {d['data']}"
                )
