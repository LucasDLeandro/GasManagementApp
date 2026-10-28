import datetime
from decimal import Decimal
import threading
import uuid
import pytest

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, DatabaseError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from hypothesis import given, strategies as st, settings, HealthCheck
from hypothesis.extra.django import TestCase as HypothesisTestCase
from rest_framework import status
from rest_framework.test import APIClient

from core.money import quantize
from core.models import Filial, Membership, Tenant
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from financeiro.models import (
    PlanoContas,
    CentroCusto,
    Fornecedor,
    CondicaoPagamento,
    PeriodoContabil,
    ContaFinanceira,
    MovimentoConta,
    LancamentoContabil,
    PartidaContabil,
)
from financeiro.seeds import (
    seed_financeiro_tenant_completo,
    seed_plano_contas_padrao,
    seed_centros_custo_padrao,
    seed_condicoes_pagamento_padrao,
)
from financeiro.services.conta import (
    saldo_em,
    criar_conta_financeira,
    registrar_movimento_conta,
    transferir_entre_contas,
)
from financeiro.services.periodo import (
    checar_periodo_aberto,
    fechar_periodo,
    reabrir_periodo,
)
from financeiro.services.razao import (
    lancar,
    estornar,
    verificar_integridade_razao,
)
from financeiro.selectors.balancete import obter_balancete_verificacao
from financeiro.selectors.razao import consultar_razao_conta

User = get_user_model()


class BaseFinanceiroTestCase(TestCase):
    """Setup base com tenant ativo, filiais e plano de contas pré-populado."""

    def setUp(self):
        super().setUp()
        cnpj_unico = f"11.222.{uuid.uuid4().hex[:3]}/0001-44"
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Alfa Oxigênio Ltda",
            nome_fantasia="Alfa Gases",
            cnpj=cnpj_unico,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user = User.objects.create_user(
            username=f"gestor_{uuid.uuid4().hex[:6]}",
            email="financeiro@alfagases.com.br",
            password="secret_password"
        )
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True
        )
        self.token = set_current_tenant(self.tenant)

        # Executa seeds padrão
        seed_financeiro_tenant_completo(self.tenant)

        # Contas analíticas de teste
        self.conta_caixa = PlanoContas.objects.get(codigo_estrutural='1.1.1.01')
        self.conta_banco = PlanoContas.objects.get(codigo_estrutural='1.1.1.02')
        self.conta_clientes = PlanoContas.objects.get(codigo_estrutural='1.1.2.01')
        self.conta_receita_med = PlanoContas.objects.get(codigo_estrutural='3.1.1')
        self.conta_receita_ind = PlanoContas.objects.get(codigo_estrutural='3.1.2')
        self.conta_fornecedores = PlanoContas.objects.get(codigo_estrutural='2.1.1')
        self.conta_desp_adm = PlanoContas.objects.get(codigo_estrutural='5.3')

        # Centro de custo de teste
        self.cc_adm = CentroCusto.objects.get(codigo='CC-04')

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()


class SeedIdempotenciaTests(BaseFinanceiroTestCase):
    """Validação da idempotência dos seeds padrão contábeis (Tarefas 2, 3 e 4)."""

    def test_seeds_nao_duplicam_ao_rodar_multiplas_vezes(self):
        total_contas_antes = PlanoContas.objects.filter(tenant=self.tenant).count()
        total_cc_antes = CentroCusto.objects.filter(tenant=self.tenant).count()
        total_cp_antes = CondicaoPagamento.objects.filter(tenant=self.tenant).count()

        # Roda segunda vez
        seed_financeiro_tenant_completo(self.tenant)

        assert PlanoContas.objects.filter(tenant=self.tenant).count() == total_contas_antes
        assert CentroCusto.objects.filter(tenant=self.tenant).count() == total_cc_antes
        assert CondicaoPagamento.objects.filter(tenant=self.tenant).count() == total_cp_antes


class RazaoServicoTests(BaseFinanceiroTestCase):
    """Testes do serviço único de escrita do Razão (financeiro/services/razao.py)."""

    def test_lancamento_balanceado_sucesso(self):
        partidas = [
            {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('500.00')},
            {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('500.00')},
        ]
        dt = timezone.localdate()
        lancamento, criadas = lancar(
            tenant=self.tenant,
            data_competencia=dt,
            historico="Recebimento à vista de venda de oxigênio medicinal",
            partidas=partidas,
            usuario=self.user
        )

        assert lancamento.numero == 1
        assert len(criadas) == 2
        assert lancamento.hash_integridade != ""
        assert lancamento.hash_anterior == "0" * 64

    def test_lancamento_desbalanceado_rejeitado(self):
        partidas = [
            {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('500.00')},
            {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('499.99')},
        ]
        with self.assertRaises(ValidationError) as ctx:
            lancar(
                tenant=self.tenant,
                data_competencia=timezone.localdate(),
                historico="Desbalanceado",
                partidas=partidas,
                usuario=self.user
            )
        assert "desbalanceado" in str(ctx.exception).lower()

    def test_lancamento_em_conta_sintetica_rejeitado(self):
        conta_sintetica = PlanoContas.objects.get(codigo_estrutural='1.1')
        partidas = [
            {'conta_id': conta_sintetica.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('100.00')},
            {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('100.00')},
        ]
        with self.assertRaises(ValidationError) as ctx:
            lancar(
                tenant=self.tenant,
                data_competencia=timezone.localdate(),
                historico="Tentativa em conta sintética",
                partidas=partidas,
                usuario=self.user
            )
        assert "sintética" in str(ctx.exception).lower() or "não aceita" in str(ctx.exception).lower()

    def test_lancamento_valor_negativo_ou_zero_rejeitado(self):
        partidas = [
            {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('-100.00')},
            {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('-100.00')},
        ]
        with self.assertRaises(ValidationError) as ctx:
            lancar(
                tenant=self.tenant,
                data_competencia=timezone.localdate(),
                historico="Valor negativo",
                partidas=partidas,
                usuario=self.user
            )
        assert "maior que zero" in str(ctx.exception).lower() or "positivo" in str(ctx.exception).lower()

    def test_lancamento_em_periodo_fechado_rejeitado(self):
        data_fechada = datetime.date(2026, 1, 15)
        fechar_periodo(tenant=self.tenant, ano=2026, mes=1, usuario=self.user)

        partidas = [
            {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('200.00')},
            {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('200.00')},
        ]
        with self.assertRaises(ValidationError) as ctx:
            lancar(
                tenant=self.tenant,
                data_competencia=data_fechada,
                historico="Tentativa em período fechado",
                partidas=partidas,
                usuario=self.user
            )
        assert "fechado" in str(ctx.exception).lower()

    def test_cadeia_hashes_encadeada_sequencialmente(self):
        dt = timezone.localdate()
        l1, _ = lancar(
            tenant=self.tenant,
            data_competencia=dt,
            historico="Lançamento 1",
            partidas=[
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('100.00')},
                {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('100.00')},
            ],
            usuario=self.user
        )
        l2, _ = lancar(
            tenant=self.tenant,
            data_competencia=dt,
            historico="Lançamento 2",
            partidas=[
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('200.00')},
                {'conta_id': self.conta_receita_ind.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('200.00')},
            ],
            usuario=self.user
        )

        assert l2.hash_anterior == l1.hash_integridade
        assert l2.numero == l1.numero + 1

        # Validação do job de integridade
        valido, erros = verificar_integridade_razao(self.tenant)
        assert valido is True
        assert len(erros) == 0

    def test_estorno_em_periodo_aberto(self):
        dt = timezone.localdate()
        l1, _ = lancar(
            tenant=self.tenant,
            data_competencia=dt,
            historico="Venda original",
            partidas=[
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('350.00')},
                {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('350.00')},
            ],
            usuario=self.user
        )

        estorno, p_estorno = estornar(
            lancamento_id=l1.id,
            motivo="Cancelamento de NFe pelo cliente",
            usuario=self.user
        )

        assert estorno.lancamento_estornado_id == l1.id
        assert estorno.data_competencia == l1.data_competencia
        # Partidas devem ser invertidas
        assert len(p_estorno) == 2
        p_banco = next(p for p in p_estorno if p.conta_contabil_id == self.conta_banco.id)
        p_receita = next(p for p in p_estorno if p.conta_contabil_id == self.conta_receita_med.id)
        assert p_banco.tipo_partida == 'CREDITO'
        assert p_receita.tipo_partida == 'DEBITO'

    def test_estorno_periodo_fechado_cai_no_periodo_corrente(self):
        # Lançamento em período passado
        data_passada = datetime.date(2025, 12, 10)
        l_antigo, _ = lancar(
            tenant=self.tenant,
            data_competencia=data_passada,
            historico="Lançamento ano passado",
            partidas=[
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('150.00')},
                {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('150.00')},
            ],
            usuario=self.user
        )

        # Fecha dezembro de 2025
        fechar_periodo(tenant=self.tenant, ano=2025, mes=12, usuario=self.user)

        # Estorna agora: deve cair no período aberto corrente (localdate())
        estorno, _ = estornar(
            lancamento_id=l_antigo.id,
            motivo="Estorno com período 2025/12 já encerrado",
            usuario=self.user
        )

        hoje = timezone.localdate()
        assert estorno.data_competencia == hoje
        assert estorno.lancamento_estornado_id == l_antigo.id
        assert f"Estorno do lançamento #{l_antigo.numero}" in estorno.historico


class PeriodoContabilRegrasTests(BaseFinanceiroTestCase):
    """Validações das regras de trava de períodos contábeis (F-17)."""

    def test_apenas_ultimo_periodo_fechado_pode_ser_reaberto(self):
        # Fecha mês 1 e mês 2
        fechar_periodo(tenant=self.tenant, ano=2026, mes=1, usuario=self.user)
        fechar_periodo(tenant=self.tenant, ano=2026, mes=2, usuario=self.user)

        # Tentativa de reabrir mês 1 enquanto mês 2 está fechado deve falhar
        with self.assertRaises(ValidationError) as ctx:
            reabrir_periodo(
                tenant=self.tenant,
                ano=2026,
                mes=1,
                motivo="Ajuste tardio",
                usuario=self.user
            )
        assert "último período fechado" in str(ctx.exception).lower()

        # Reabrir mês 2 (o mais recente) tem sucesso
        p2 = reabrir_periodo(
            tenant=self.tenant,
            ano=2026,
            mes=2,
            motivo="Necessidade de conciliação residual",
            usuario=self.user
        )
        assert p2.status == 'ABERTO'
        assert p2.motivo_reabertura == "Necessidade de conciliação residual"

        # Agora mês 1 é o mais recente fechado e pode ser reaberto
        p1 = reabrir_periodo(
            tenant=self.tenant,
            ano=2026,
            mes=1,
            motivo="Reabertura sequencial permitida",
            usuario=self.user
        )
        assert p1.status == 'ABERTO'

    def test_validacoes_periodo_contabil_excecoes(self):
        # Mês inválido
        with self.assertRaises(ValidationError):
            fechar_periodo(tenant=self.tenant, ano=2026, mes=13, usuario=self.user)

        with self.assertRaises(ValidationError):
            fechar_periodo(tenant=self.tenant, ano=2026, mes=0, usuario=self.user)

        # Já fechado
        fechar_periodo(tenant=self.tenant, ano=2026, mes=5, usuario=self.user)
        with self.assertRaises(ValidationError):
            fechar_periodo(tenant=self.tenant, ano=2026, mes=5, usuario=self.user)

        # Reabrir sem motivo
        with self.assertRaises(ValidationError):
            reabrir_periodo(tenant=self.tenant, ano=2026, mes=5, motivo="", usuario=self.user)

        # Reabrir período que já está aberto
        with self.assertRaises(ValidationError):
            reabrir_periodo(tenant=self.tenant, ano=2026, mes=6, motivo="Motivo qualquer", usuario=self.user)


class ContaFinanceiraMovimentoTests(BaseFinanceiroTestCase):
    """Validações de ContaFinanceira e saldo derivado estritamente de MovimentoConta (F-16)."""

    def setUp(self):
        super().setUp()
        self.conta_itau = criar_conta_financeira(
            tenant=self.tenant,
            nome="Itaú Operacional Matriz",
            tipo="CONTA_CORRENTE",
            conta_contabil=self.conta_banco,
            saldo_inicial=Decimal('1000.00'),
            data_saldo_inicial=datetime.date(2026, 1, 1),
            banco_codigo="341",
            agencia="1234",
            conta="56789-0"
        )
        self.conta_caixa_rota = criar_conta_financeira(
            tenant=self.tenant,
            nome="Caixa Rota Motorista 01",
            tipo="CAIXA_ROTA_MOTORISTA",
            conta_contabil=self.conta_caixa,
            saldo_inicial=Decimal('200.00'),
            data_saldo_inicial=datetime.date(2026, 1, 1)
        )

    def test_saldo_derivado_corretamente(self):
        hoje = timezone.localdate()

        # Entrada de 500
        registrar_movimento_conta(
            tenant=self.tenant,
            conta=self.conta_itau,
            data_movimento=hoje,
            tipo="ENTRADA",
            valor=Decimal('500.00')
        )

        # Saída de 150
        registrar_movimento_conta(
            tenant=self.tenant,
            conta=self.conta_itau,
            data_movimento=hoje,
            tipo="SAIDA",
            valor=Decimal('150.00')
        )

        # Tarifa de 15
        registrar_movimento_conta(
            tenant=self.tenant,
            conta=self.conta_itau,
            data_movimento=hoje,
            tipo="TARIFA",
            valor=Decimal('15.00')
        )

        # Saldo esperado = 1000 + 500 - 150 - 15 = 1335.00
        saldo_calculado = saldo_em(self.conta_itau, hoje)
        assert saldo_calculado == Decimal('1335.00')

    def test_transferencia_entre_contas_gera_dois_movimentos_e_um_lancamento(self):
        hoje = timezone.localdate()
        lancamento, mov_saida, mov_entrada = transferir_entre_contas(
            tenant=self.tenant,
            conta_origem_id=self.conta_itau.id,
            conta_destino_id=self.conta_caixa_rota.id,
            valor=Decimal('300.00'),
            data_transferencia=hoje,
            historico="Suprimento de fundo fixo para motorista de rota",
            usuario=self.user
        )

        assert mov_saida.tipo == 'TRANSFERENCIA_SAIDA'
        assert mov_saida.valor == Decimal('300.00')
        assert mov_entrada.tipo == 'TRANSFERENCIA_ENTRADA'
        assert mov_entrada.valor == Decimal('300.00')

        # Saldo origem = 1000 - 300 = 700.00
        assert saldo_em(self.conta_itau, hoje) == Decimal('700.00')
        # Saldo destino = 200 + 300 = 500.00
        assert saldo_em(self.conta_caixa_rota, hoje) == Decimal('500.00')

        # Lançamento contábil no Razão
        assert lancamento is not None
        assert lancamento.partidas.count() == 2

    def test_transferencia_mesma_conta_rejeitada(self):
        with self.assertRaises(ValidationError) as ctx:
            transferir_entre_contas(
                tenant=self.tenant,
                conta_origem_id=self.conta_itau.id,
                conta_destino_id=self.conta_itau.id,
                valor=Decimal('50.00'),
                usuario=self.user
            )
        assert "distintas" in str(ctx.exception)

    def test_transferencia_saldo_insuficiente_rejeitada(self):
        with self.assertRaises(ValidationError) as ctx:
            transferir_entre_contas(
                tenant=self.tenant,
                conta_origem_id=self.conta_itau.id,
                conta_destino_id=self.conta_caixa_rota.id,
                valor=Decimal('999999.00'),
                usuario=self.user
            )
        assert "Saldo insuficiente" in str(ctx.exception)

    def test_criar_conta_financeira_com_conta_sintetica_rejeitada(self):
        conta_sintetica = PlanoContas.objects.get(codigo_estrutural='1.1')
        with self.assertRaises(ValidationError) as ctx:
            criar_conta_financeira(
                tenant=self.tenant,
                nome="Conta Inválida",
                tipo="CONTA_CORRENTE",
                conta_contabil=conta_sintetica
            )
        assert "analítica" in str(ctx.exception).lower()

    def test_movimento_valor_invalido_rejeitado(self):
        with self.assertRaises(ValidationError):
            registrar_movimento_conta(
                tenant=self.tenant,
                conta=self.conta_itau,
                tipo="ENTRADA",
                valor=Decimal('0.00')
            )


class BalanceteVerificacaoTests(BaseFinanceiroTestCase):
    """Testes do seletor de Balancete de Verificação (Item 11)."""

    def test_balancete_fecha_em_zero(self):
        hoje = timezone.localdate()
        # Realiza 3 lançamentos balanceados
        lancar(
            tenant=self.tenant,
            data_competencia=hoje,
            historico="Venda 1",
            partidas=[
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('1000.00')},
                {'conta_id': self.conta_receita_med.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('1000.00')},
            ],
            usuario=self.user
        )
        lancar(
            tenant=self.tenant,
            data_competencia=hoje,
            historico="Pagamento Fornecedor",
            partidas=[
                {'conta_id': self.conta_fornecedores.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('400.00')},
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('400.00')},
            ],
            usuario=self.user
        )
        lancar(
            tenant=self.tenant,
            data_competencia=hoje,
            historico="Despesa Administrativa",
            partidas=[
                {'conta_id': self.conta_desp_adm.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('150.00')},
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('150.00')},
            ],
            usuario=self.user
        )

        balancete = obter_balancete_verificacao(
            tenant=self.tenant,
            data_inicio=hoje.replace(day=1).isoformat(),
            data_fim=hoje.isoformat()
        )

        assert balancete['fechamento_correto'] is True
        assert balancete['diferenca'] == Decimal('0.00')
        assert balancete['totais']['total_debitos_analiticos'] == balancete['totais']['total_creditos_analiticos']


class DatabaseTriggerImutabilidadeTests(TransactionTestCase):
    """
    Testes de Imutabilidade no Banco via Triggers (CORREÇÃO F-18).
    Utiliza TransactionTestCase para validar execução direta no nível do banco.
    """

    def setUp(self):
        super().setUp()
        cnpj_beta = f"99.888.{uuid.uuid4().hex[:3]}/0001-66"
        self.tenant = Tenant.objects.create(
            razao_social="Beta Gases Especiais S/A",
            nome_fantasia="Beta Gases",
            cnpj=cnpj_beta,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user = User.objects.create_user(
            username=f"contabil_{uuid.uuid4().hex[:6]}",
            email="contabil@betagases.com.br",
            password="pwd"
        )
        self.token = set_current_tenant(self.tenant)
        seed_financeiro_tenant_completo(self.tenant)
        self.conta_banco = PlanoContas.objects.get(codigo_estrutural='1.1.1.02')
        self.conta_rec = PlanoContas.objects.get(codigo_estrutural='3.1.1')

        # Assegura triggers ativos
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS prevent_update_lancamento
                    BEFORE UPDATE ON financeiro_lancamentocontabil
                    FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'Lançamentos contábeis são estritamente imutáveis no banco de dados.'); END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS prevent_delete_lancamento
                    BEFORE DELETE ON financeiro_lancamentocontabil
                    FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'Lançamentos contábeis são estritamente imutáveis no banco de dados.'); END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS prevent_update_partida
                    BEFORE UPDATE ON financeiro_partidacontabil
                    FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'Partidas contábeis são estritamente imutáveis no banco de dados.'); END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS prevent_delete_partida
                    BEFORE DELETE ON financeiro_partidacontabil
                    FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'Partidas contábeis são estritamente imutáveis no banco de dados.'); END;
                """)

    def tearDown(self):
        # Desabilita triggers temporariamente para que o runner do Django consiga flushar as tabelas
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_lancamento;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_delete_lancamento;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_partida;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_delete_partida;")
            elif connection.vendor == 'postgresql':
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_delete_lancamento ON financeiro_lancamentocontabil;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_delete_partida ON financeiro_partidacontabil;")
        reset_current_tenant(self.token)
        super().tearDown()

    def test_triggers_bloqueiam_update_e_delete_em_lancamento_e_partida(self):
        lanc, partidas = lancar(
            tenant=self.tenant,
            data_competencia=timezone.localdate(),
            historico="Registro para teste de trigger",
            partidas=[
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('250.00')},
                {'conta_id': self.conta_rec.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('250.00')},
            ],
            usuario=self.user
        )
        partida = partidas[0]

        # 1. Tentativa de UPDATE direto via cursor em LancamentoContabil
        with connection.cursor() as cursor:
            with self.assertRaises(DatabaseError):
                cursor.execute(
                    "UPDATE financeiro_lancamentocontabil SET historico = 'Hacked' WHERE id = %s",
                    [lanc.id]
                )

        # 2. Tentativa de DELETE direto via cursor em PartidaContabil
        with connection.cursor() as cursor:
            with self.assertRaises(DatabaseError):
                cursor.execute(
                    "DELETE FROM financeiro_partidacontabil WHERE id = %s",
                    [partida.id]
                )

        # 3. Tentativa de DELETE direto em LancamentoContabil
        with connection.cursor() as cursor:
            with self.assertRaises(DatabaseError):
                cursor.execute(
                    "DELETE FROM financeiro_lancamentocontabil WHERE id = %s",
                    [lanc.id]
                )

    def test_job_integridade_detecta_divergencia_se_hash_for_adulterado(self):
        lanc, _ = lancar(
            tenant=self.tenant,
            data_competencia=timezone.localdate(),
            historico="Registro normal",
            partidas=[
                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('100.00')},
                {'conta_id': self.conta_rec.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('100.00')},
            ],
            usuario=self.user
        )

        # Verifica integridade inicial
        valido, _ = verificar_integridade_razao(self.tenant)
        assert valido is True

        # Se forçarmos uma alteração ignorando o trigger (simulando corrupção física)
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute("PRAGMA ignore_check_constraints = 1;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_lancamento;")
                cursor.execute("UPDATE financeiro_lancamentocontabil SET hash_integridade = 'bad_hash' WHERE id = %s", [lanc.id])
            elif connection.vendor == 'postgresql':
                cursor.execute("ALTER TABLE financeiro_lancamentocontabil DISABLE TRIGGER USER;")
                cursor.execute("UPDATE financeiro_lancamentocontabil SET hash_integridade = 'bad_hash' WHERE id = %s", [lanc.id])

        # Job de integridade DEVE detectar o erro
        valido_depois, erros = verificar_integridade_razao(self.tenant)
        assert valido_depois is False
        assert len(erros) > 0
        assert erros[0]['erro'] == 'ADULTERACAO_HASH_INTEGRIDADE'


class ConcorrenciaLancamentosTests(TransactionTestCase):
    """Teste de concorrência: dois lançamentos simultâneos sob lock (Rule 8)."""

    def setUp(self):
        super().setUp()
        cnpj_gama = f"88.777.{uuid.uuid4().hex[:3]}/0001-55"
        self.tenant = Tenant.objects.create(
            razao_social="Gama Indústria de Gases Ltda",
            nome_fantasia="Gama Gases",
            cnpj=cnpj_gama,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user = User.objects.create_user(
            username=f"gama_{uuid.uuid4().hex[:6]}",
            email="gama@empresa.com",
            password="pwd"
        )
        self.token = set_current_tenant(self.tenant)
        seed_financeiro_tenant_completo(self.tenant)
        self.conta_banco = PlanoContas.objects.get(codigo_estrutural='1.1.1.02')
        self.conta_rec = PlanoContas.objects.get(codigo_estrutural='3.1.2')

    def tearDown(self):
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_lancamento;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_delete_lancamento;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_update_partida;")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_delete_partida;")
        reset_current_tenant(self.token)
        super().tearDown()

    def test_concorrencia_dois_lancamentos_simultaneos(self):
        resultados = []
        erros = []
        sqlite_lock = threading.Lock()

        def worker(idx):
            with tenant_context(self.tenant):
                try:
                    if connection.vendor == 'sqlite':
                        with sqlite_lock:
                            lanc, _ = lancar(
                                tenant=self.tenant,
                                data_competencia=timezone.localdate(),
                                historico=f"Lançamento concorrente {idx}",
                                partidas=[
                                    {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('50.00')},
                                    {'conta_id': self.conta_rec.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('50.00')},
                                ],
                                usuario=self.user
                            )
                    else:
                        lanc, _ = lancar(
                            tenant=self.tenant,
                            data_competencia=timezone.localdate(),
                            historico=f"Lançamento concorrente {idx}",
                            partidas=[
                                {'conta_id': self.conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': Decimal('50.00')},
                                {'conta_id': self.conta_rec.id, 'tipo_partida': 'CREDITO', 'valor': Decimal('50.00')},
                            ],
                            usuario=self.user
                        )
                    resultados.append(lanc)
                except Exception as e:
                    erros.append(e)
                finally:
                    connection.close()

        threads = [
            threading.Thread(target=worker, args=(1,)),
            threading.Thread(target=worker, args=(2,))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(erros) == 0, f"Erros na concorrência: {erros}"
        assert len(resultados) == 2

        numeros = sorted([r.numero for r in resultados])
        assert numeros == [1, 2], f"Números não sequenciais: {numeros}"

        # Verifica que a cadeia de hashes continuou consistente
        valido, integridade_erros = verificar_integridade_razao(self.tenant)
        assert valido is True, f"Cadeia inconsistente: {integridade_erros}"


class MultiTenantBoundaryAPITests(TestCase):
    """Validação da barreira multi-tenant: 404 para recursos de outro tenant (Rule 3)."""

    def setUp(self):
        super().setUp()
        # Tenant A
        self.tenant_a = Tenant.objects.create(
            razao_social="Empresa A Ltda",
            nome_fantasia="Empresa A",
            cnpj=f"11.111.{uuid.uuid4().hex[:3]}/0001-11",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user_a = User.objects.create_user(username=f"user_a_{uuid.uuid4().hex[:5]}", email="a@a.com", password="pwd")
        Membership.objects.create(user=self.user_a, tenant=self.tenant_a, papel="ADMIN", ativo=True)

        # Tenant B
        self.tenant_b = Tenant.objects.create(
            razao_social="Empresa B Ltda",
            nome_fantasia="Empresa B",
            cnpj=f"22.222.{uuid.uuid4().hex[:3]}/0001-22",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user_b = User.objects.create_user(username=f"user_b_{uuid.uuid4().hex[:5]}", email="b@b.com", password="pwd")
        Membership.objects.create(user=self.user_b, tenant=self.tenant_b, papel="ADMIN", ativo=True)

        seed_financeiro_tenant_completo(self.tenant_a)
        seed_financeiro_tenant_completo(self.tenant_b)

        # Cria uma conta financeira no Tenant B
        with tenant_context(self.tenant_b):
            conta_banco_b = PlanoContas.objects.get(codigo_estrutural='1.1.1.02')
            self.conta_b = criar_conta_financeira(
                tenant=self.tenant_b,
                nome="Conta Exclusiva Tenant B",
                tipo="CONTA_CORRENTE",
                conta_contabil=conta_banco_b,
                saldo_inicial=Decimal('500.00'),
                data_saldo_inicial=datetime.date(2026, 1, 1)
            )

        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.user_a)
        self.client_a.credentials(HTTP_X_TENANT_ID=str(self.tenant_a.id))

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_tenant_a_recebe_404_ao_tentar_acessar_recurso_do_tenant_b(self):
        # Tenta acessar a conta do Tenant B autenticado como Tenant A
        res = self.client_a.get(f'/financeiro/api/contas-financeiras/{self.conta_b.id}/')
        assert res.status_code == status.HTTP_404_NOT_FOUND


class InvarianteBalanceteHypothesisTests(HypothesisTestCase):
    """
    Teste de propriedade (Hypothesis) para invariantes (Rule 8):
    Qualquer sequência de lançamentos balanceados mantém o balancete zerado.
    Executado dentro de TestCase para isolamento transacional limpo via ROLLBACK.
    """
    def setUp(self):
        super().setUp()
        cnpj_hypo = f"33.444.{uuid.uuid4().hex[:3]}/0001-77"
        self.tenant = Tenant.objects.create(
            razao_social="Hypothesis Testes S/A",
            nome_fantasia="Hypothesis Gases",
            cnpj=cnpj_hypo,
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.user = User.objects.create_user(username=f"hypo_{uuid.uuid4().hex[:6]}", email="h@h.com", password="pwd")
        seed_financeiro_tenant_completo(self.tenant)

    @settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    @given(
        valores=st.lists(
            st.decimals(min_value=Decimal('0.01'), max_value=Decimal('99999.99'), places=2),
            min_size=1,
            max_size=5
        )
    )
    def test_invariante_balancete_sempre_zerado_hypothesis(self, valores):
        with tenant_context(self.tenant):
            conta_banco = PlanoContas.objects.get(codigo_estrutural='1.1.1.02')
            conta_rec = PlanoContas.objects.get(codigo_estrutural='3.1.1')
            hoje = timezone.localdate()
            for idx, val in enumerate(valores):
                lancar(
                    tenant=self.tenant,
                    data_competencia=hoje,
                    historico=f"Lançamento Hypothesis {idx}",
                    partidas=[
                        {'conta_id': conta_banco.id, 'tipo_partida': 'DEBITO', 'valor': val},
                        {'conta_id': conta_rec.id, 'tipo_partida': 'CREDITO', 'valor': val},
                    ],
                    usuario=self.user
                )

            balancete = obter_balancete_verificacao(
                tenant=self.tenant,
                data_inicio=hoje.replace(day=1).isoformat(),
                data_fim=hoje.isoformat()
            )

            assert balancete['fechamento_correto'] is True
            assert balancete['diferenca'] == Decimal('0.00')



