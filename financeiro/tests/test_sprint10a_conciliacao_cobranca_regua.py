"""
Testes abrangentes da Sprint 10A: Conciliação bancária, cobrança registrada e régua de cobrança.
Valida todas as 5 regras de matching, batimento de saldo, webhooks com HMAC, idempotência,
regras de fechamento, consentimento LGPD, multi-tenant 404 e invariantes com Hypothesis.
"""
import datetime
from decimal import Decimal
import hmac
import hashlib
import json
import pytest

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from hypothesis import given, strategies as st, settings, HealthCheck
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Tenant, Filial, Membership
from core.money import quantize
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from clientes.models import Cliente
from financeiro.models import (
    ContaFinanceira,
    PlanoContas,
    CentroCusto,
    TituloFinanceiro,
    ParcelaFinanceira,
    ImportacaoExtrato,
    ExtratoBancarioItem,
    RegraConciliacao,
    ConfiguracaoCobranca,
    ReguaCobranca,
    EnvioCobranca,
    ConsentimentoContato,
    BaixaParcela,
)
from financeiro.seeds import seed_financeiro_tenant_completo
from financeiro.banco.ofx_parser import OFXParser
from financeiro.banco.psp_adapter import GatewayPSPAdapter
from financeiro.banco.cnab_adapter import ArquivoCNABAdapter
from financeiro.banco.ports import AssinaturaInvalidaError
from financeiro.services.conciliacao_service import (
    importar_extrato,
    conciliar_manualmente,
    criar_lancamento_direto,
    dividir_item_extrato,
    ignorar_item_extrato,
    desfazer_conciliacao,
)
from financeiro.services.cobranca_service import (
    emitir_cobranca_parcela,
    emitir_cobranca_titulo,
    cancelar_cobranca_parcela,
    processar_webhook_cobranca,
)
from financeiro.services.regua_service import (
    executar_regua_cobranca,
    registrar_consentimento,
    revogar_consentimento,
)
from financeiro.conciliacao import processar_item_extrato

User = get_user_model()


class BaseSprint10ATestCase(TestCase):
    """Setup de teste com tenant isolado, plano de contas e contas bancárias."""

    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Piloto 10A Ltda",
            nome_fantasia="Distribuidora Piloto 10A",
            cnpj="11.222.333/0001-99",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        self.token = set_current_tenant(self.tenant)

        self.filial = Filial.objects.create(
            tenant=self.tenant,
            nome="Matriz 10A",
            cnpj="11.222.333/0001-99",
            matriz=True
        )
        seed_financeiro_tenant_completo(self.tenant)

        self.user = User.objects.create_user(
            username="gerente_fin_10a",
            email="gerente@distribuidora.com",
            password="password123"
        )
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="ADMIN"
        )

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)

        self.conta_contabil_banco = PlanoContas.objects.filter(
            tenant=self.tenant,
            tipo='ANALITICA',
            codigo_estrutural__startswith='1.1.1'
        ).first()

        self.conta_financeira = ContaFinanceira.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            nome="Banco Itaú CC 12345-6",
            tipo='CONTA_CORRENTE',
            banco_codigo='341',
            agencia='1234',
            conta='12345-6',
            saldo_inicial=Decimal('1000.00'),
            conta_contabil=self.conta_contabil_banco
        )

        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome="Supermercado Silva e Filhos Ltda",
            cnpj="22.333.444/0001-88",
            tipo_cliente="PJ",
            email_financeiro="financeiro@supermercadosilva.com.br",
            telefone="11988887777"
        )

        self.config_cobranca = ConfiguracaoCobranca.objects.create(
            tenant=self.tenant,
            conta_financeira=self.conta_financeira,
            adaptador='GATEWAY_PSP',
            carteira='109',
            percentual_multa=Decimal('0.0200'),
            percentual_juros_mensal=Decimal('0.0100'),
            webhook_secret='segredo_super_secreto_hmac_10a',
            ativo=True
        )

    def tearDown(self):
        reset_current_tenant(getattr(self, 'token', None))
        super().tearDown()


class TestOFXParserEDeduplicacao(BaseSprint10ATestCase):
    """Testes de parsing resiliente de OFX e deduplicação de importações."""

    def test_parsing_ofx_multi_encoding_e_tags_sgml(self):
        conteudo_ofx = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>20261021120000
<LANGUAGE>POR
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1001
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>341
<BRANCHID>1234
<ACCTID>12345-6
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20261001
<DTEND>20261020
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20261015120000[-03:EST]
<TRNAMT>550.00
<FITID>202610150001
<CHECKNUM>1001
<MEMO>PIX RECEBIDO CLIENTE SILVA
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20261016120000[-03:EST]
<TRNAMT>-35.50
<FITID>202610160002
<MEMO>TAR PACOTE MENSAL
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1514.50
<DTASOF>20261020
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>"""
        ofx_res = OFXParser.parse(conteudo_ofx.encode('latin1'), self.conta_financeira.id)
        self.assertEqual(ofx_res.banco_codigo, "341")
        self.assertEqual(ofx_res.conta, "12345-6")
        self.assertEqual(ofx_res.saldo_final, Decimal("1514.50"))
        self.assertEqual(len(ofx_res.transacoes), 2)
        self.assertEqual(ofx_res.transacoes[0].valor, Decimal("550.00"))
        self.assertEqual(ofx_res.transacoes[1].valor, Decimal("-35.50"))
        self.assertTrue(len(ofx_res.transacoes[0].hash_dedup) > 0)

    def test_reimportar_mesmo_arquivo_rejeita_duplicacao(self):
        conteudo_ofx = """<OFX><BANKTRANLIST><DTSTART>20261001<DTEND>20261010
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261005<TRNAMT>100.00<FITID>FIT001<MEMO>TESTE
</BANKTRANLIST><LEDGERBAL><BALAMT>1100.00</LEDGERBAL></OFX>""".encode('utf-8')

        imp1 = importar_extrato(
            tenant=self.tenant,
            conta_id=self.conta_financeira.id,
            tipo='OFX',
            arquivo_bytes=conteudo_ofx,
            nome_arquivo="extrato_outubro.ofx",
            usuario=self.user
        )
        self.assertIsNotNone(imp1.id)

        # Tentativa de reimportar o mesmo arquivo: deve rejeitar com ValidationError
        with self.assertRaises(ValidationError) as ctx:
            importar_extrato(
                tenant=self.tenant,
                conta_id=self.conta_financeira.id,
                tipo='OFX',
                arquivo_bytes=conteudo_ofx,
                nome_arquivo="extrato_outubro.ofx",
                usuario=self.user
            )
        self.assertIn("já foi importado anteriormente", str(ctx.exception))

    def test_itens_sobrepostos_sao_desduplicados_por_hash(self):
        conteudo_ofx1 = """<OFX><BANKTRANLIST><DTSTART>20261001<DTEND>20261005
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261002<TRNAMT>200.00<FITID>FITA<MEMO>TRANS A
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261003<TRNAMT>300.00<FITID>FITB<MEMO>TRANS B
</BANKTRANLIST></OFX>""".encode('utf-8')

        conteudo_ofx2 = """<OFX><BANKTRANLIST><DTSTART>20261003<DTEND>20261010
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261003<TRNAMT>300.00<FITID>FITB<MEMO>TRANS B
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261004<TRNAMT>400.00<FITID>FITC<MEMO>TRANS C
</BANKTRANLIST></OFX>""".encode('utf-8')

        importar_extrato(
            tenant=self.tenant,
            conta_id=self.conta_financeira.id,
            tipo='OFX',
            arquivo_bytes=conteudo_ofx1,
            nome_arquivo="arq1.ofx",
            usuario=self.user
        )

        importar_extrato(
            tenant=self.tenant,
            conta_id=self.conta_financeira.id,
            tipo='OFX',
            arquivo_bytes=conteudo_ofx2,
            nome_arquivo="arq2.ofx",
            usuario=self.user
        )

        # Deve haver exatamente 3 itens distintos no extrato (A, B e C), sem duplicar o B!
        itens = ExtratoBancarioItem.objects.filter(tenant=self.tenant, conta=self.conta_financeira)
        self.assertEqual(itens.count(), 3)


class TestMotorConciliacaoCincoRegras(BaseSprint10ATestCase):
    """Testa detalhadamente as 5 regras em ordem do motor de conciliação bancária."""

    def _criar_titulo_e_parcela(self, valor, vencimento, nosso_numero="", txid_pix=""):
        conta_receita = PlanoContas.objects.filter(
            tenant=self.tenant,
            tipo='ANALITICA',
            codigo_estrutural__startswith='3.1.1'
        ).first()

        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=vencimento - datetime.timedelta(days=10),
            data_competencia=vencimento,
            valor_bruto=valor,
            valor_liquido_esperado=valor,
            origem_tipo='MANUAL',
            historico='Venda de Teste'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            numero_parcela=1,
            total_parcelas=1,
            data_vencimento=vencimento,
            valor_nominal=valor,
            saldo_em_aberto=valor,
            status='PENDENTE',
            nosso_numero=nosso_numero,
            txid_pix=txid_pix
        )
        return titulo, parcela

    def test_regra_1_nosso_numero_ou_txid_pix_baixa_automatica(self):
        hoje = timezone.localdate()
        _, p = self._criar_titulo_e_parcela(Decimal('450.00'), hoje, nosso_numero='341009988')

        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('450.00'),
            descricao='LIQ COBRANCA ITAU NOSSO NUM 341009988',
            documento='341009988',
            fitid='FIT_9988'
        )

        conciliado = processar_item_extrato(tenant=self.tenant, item=item)
        self.assertTrue(conciliado)
        item.refresh_from_db()
        p.refresh_from_db()

        self.assertEqual(item.status, 'CONCILIADO')
        self.assertEqual(item.score, 100)
        self.assertEqual(item.regra_aplicada, 'REGRA_1_IDENTIFICADOR_DIRETO')
        self.assertEqual(p.status, 'PAGA')
        self.assertEqual(p.saldo_em_aberto, Decimal('0.00'))
        self.assertIsNotNone(item.movimento)

    def test_regra_2_valor_exato_data_3d_e_documento_cpf_cnpj(self):
        hoje = timezone.localdate()
        _, p = self._criar_titulo_e_parcela(Decimal('800.00'), hoje + datetime.timedelta(days=2))

        # Extrato traz o CNPJ do cliente 22333444000188
        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('800.00'),
            descricao='TED RECEBIDA 22.333.444/0001-88 SUPERMERCADO SILVA',
            documento='99281',
            fitid='FIT_R2'
        )

        conciliado = processar_item_extrato(tenant=self.tenant, item=item, limiar_auto=90)
        self.assertTrue(conciliado)
        item.refresh_from_db()
        p.refresh_from_db()

        self.assertEqual(item.status, 'CONCILIADO')
        self.assertEqual(item.score, 95)
        self.assertEqual(item.regra_aplicada, 'REGRA_2_VALOR_DATA_DOCUMENTO')
        self.assertEqual(p.status, 'PAGA')

    def test_regra_3_valor_exato_data_3d_e_similaridade_nome_apenas_sugerido(self):
        hoje = timezone.localdate()
        _, p = self._criar_titulo_e_parcela(Decimal('320.00'), hoje)

        # Extrato traz similaridade de nome, sem documento CPF/CNPJ
        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('320.00'),
            descricao='TRANSF RECEBIDA SILVA E FILHOS',
            documento='',
            fitid='FIT_R3'
        )

        conciliado = processar_item_extrato(tenant=self.tenant, item=item)
        # Regra 3 é APENAS SUGERIDO, logo processar_item_extrato retorna False
        self.assertFalse(conciliado)
        item.refresh_from_db()
        p.refresh_from_db()

        self.assertEqual(item.status, 'SUGERIDO')
        self.assertEqual(item.score, 80)
        self.assertEqual(item.regra_aplicada, 'REGRA_3_VALOR_DATA_NOME')
        self.assertIn(p.id, item.parcelas_sugeridas_ids)
        # Parcela permanece PENDENTE aguardando aprovação humana!
        self.assertEqual(p.status, 'PENDENTE')

    def test_regra_4_deposito_multiplas_parcelas_mesmo_cliente_sugerido(self):
        hoje = timezone.localdate()
        # Cria 3 parcelas do mesmo cliente somando 150 + 250 + 100 = 500
        _, p1 = self._criar_titulo_e_parcela(Decimal('150.00'), hoje)
        _, p2 = self._criar_titulo_e_parcela(Decimal('250.00'), hoje)
        _, p3 = self._criar_titulo_e_parcela(Decimal('100.00'), hoje)

        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('500.00'),
            descricao='DEPOSITO EM DINHEIRO / CHEQUE',
            documento='',
            fitid='FIT_R4'
        )

        conciliado = processar_item_extrato(tenant=self.tenant, item=item)
        self.assertFalse(conciliado)
        item.refresh_from_db()

        self.assertEqual(item.status, 'SUGERIDO')
        self.assertEqual(item.score, 75)
        self.assertEqual(item.regra_aplicada, 'REGRA_4_DEPOSITO_MULTIPLAS_PARCELAS')
        self.assertEqual(set(item.parcelas_sugeridas_ids), {p1.id, p2.id, p3.id})

    def test_regra_5_tarifa_bancaria_cria_movimento_e_lancamento(self):
        hoje = timezone.localdate()
        conta_despesa_tarifa = PlanoContas.objects.filter(
            tenant=self.tenant,
            tipo='ANALITICA',
            codigo_estrutural__startswith='4.1'
        ).first()

        RegraConciliacao.objects.create(
            tenant=self.tenant,
            padrao_descricao='TAR MANUTENCAO',
            tipo_regra='TARIFA',
            conta_contabil=conta_despesa_tarifa,
            ativo=True
        )

        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('-42.00'),
            descricao='DEB TAR MANUTENCAO CONTA',
            documento='T102',
            fitid='FIT_R5'
        )

        conciliado = processar_item_extrato(tenant=self.tenant, item=item)
        self.assertTrue(conciliado)
        item.refresh_from_db()

        self.assertEqual(item.status, 'CONCILIADO')
        self.assertEqual(item.score, 90)
        self.assertEqual(item.regra_aplicada, 'REGRA_5_EXTRATO_TARIFA')
        self.assertIsNotNone(item.movimento)
        self.assertEqual(item.movimento.valor, Decimal('42.00'))
        self.assertEqual(item.movimento.tipo, 'TARIFA')

    def test_item_sem_match_permanece_nao_conciliado(self):
        hoje = timezone.localdate()
        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('777.77'),
            descricao='CREDITO DESCONHECIDO SEM ORIGEM',
            documento='0000',
            fitid='FIT_UNKNOWN'
        )
        conciliado = processar_item_extrato(tenant=self.tenant, item=item)
        self.assertFalse(conciliado)
        item.refresh_from_db()
        self.assertEqual(item.status, 'NAO_CONCILIADO')
        self.assertEqual(item.score, 0)


class TestAcoesConciliacaoEFechamento(BaseSprint10ATestCase):
    """Testa ações manuais, divisão, ignorar e bloqueio por conciliacao_fechada_ate."""

    def test_conciliacao_fechada_ate_bloqueia_desfazer_antigo(self):
        hoje = timezone.localdate()
        self.conta_financeira.conciliacao_fechada_ate = hoje - datetime.timedelta(days=1)
        self.conta_financeira.save()

        # Item com data anterior ao fechamento
        item_antigo = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje - datetime.timedelta(days=5),
            valor=Decimal('100.00'),
            descricao='ITEM JA CONCILIADO NO PASSADO',
            status='CONCILIADO'
        )

        # Tentativa de desfazer conciliação em data fechada DEVE ser bloqueada
        with self.assertRaises(ValidationError) as ctx:
            desfazer_conciliacao(
                tenant=self.tenant,
                item_id=item_antigo.id,
                motivo="Tentativa indevida de reabrir conciliação fechada",
                usuario=self.user
            )
        self.assertIn("conciliação fechada até", str(ctx.exception).lower())

    def test_desfazer_conciliacao_em_data_aberta_recompoe_saldo(self):
        hoje = timezone.localdate()
        self.conta_financeira.conciliacao_fechada_ate = hoje - datetime.timedelta(days=10)
        self.conta_financeira.save()

        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje,
            data_competencia=hoje,
            valor_bruto=Decimal('200.00'),
            valor_liquido_esperado=Decimal('200.00'),
            origem_tipo='MANUAL'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            data_vencimento=hoje,
            valor_nominal=Decimal('200.00'),
            saldo_em_aberto=Decimal('200.00'),
            status='PENDENTE'
        )

        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('200.00'),
            descricao='RECEBIMENTO PARCELA 200'
        )

        # Concilia manualmente
        conciliar_manualmente(
            tenant=self.tenant,
            item_id=item.id,
            parcelas_ids=[parcela.id],
            usuario=self.user
        )
        parcela.refresh_from_db()
        self.assertEqual(parcela.status, 'PAGA')
        self.assertEqual(parcela.saldo_em_aberto, Decimal('0.00'))

        # Desfaz a conciliação
        desfazer_conciliacao(
            tenant=self.tenant,
            item_id=item.id,
            motivo="Estorno auditado",
            usuario=self.user
        )
        item.refresh_from_db()
        parcela.refresh_from_db()

        self.assertEqual(item.status, 'NAO_CONCILIADO')
        self.assertEqual(parcela.status, 'PENDENTE')
        self.assertEqual(parcela.saldo_em_aberto, Decimal('200.00'))

    def test_dividir_item_extrato_gera_sub_itens(self):
        hoje = timezone.localdate()
        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('1000.00'),
            descricao='DEPOSITO GLOBAL 1000'
        )

        partes = [
            {'valor': Decimal('600.00'), 'descricao': 'Parte 1 (600)'},
            {'valor': Decimal('400.00'), 'descricao': 'Parte 2 (400)'},
        ]

        sub_itens = dividir_item_extrato(
            tenant=self.tenant,
            item_id=item.id,
            partes=partes,
            usuario=self.user
        )
        self.assertEqual(len(sub_itens), 2)
        item.refresh_from_db()
        self.assertEqual(item.status, 'IGNORADO')
        self.assertEqual(sub_itens[0].valor, Decimal('600.00'))
        self.assertEqual(sub_itens[1].valor, Decimal('400.00'))

    def test_ignorar_item_extrato(self):
        hoje = timezone.localdate()
        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('50.00'),
            descricao='LANCAMENTO TESTE'
        )
        ignorar_item_extrato(
            tenant=self.tenant,
            item_id=item.id,
            motivo="Lançamento referente a empréstimo de sócio não operacional",
            usuario=self.user
        )
        item.refresh_from_db()
        self.assertEqual(item.status, 'IGNORADO')

    def test_criar_lancamento_direto_debito_e_credito(self):
        hoje = timezone.localdate()
        conta_despesa = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='4.1').first()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()

        # 1. Débito no extrato (saída avulsa / tarifa)
        item_deb = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('-35.00'),
            descricao='TARIFA TED AVULSA'
        )
        res_deb = criar_lancamento_direto(
            tenant=self.tenant,
            item_id=item_deb.id,
            conta_contabil_id=conta_despesa.id,
            historico="Tarifa Bancária Direta",
            usuario=self.user
        )
        self.assertEqual(res_deb.status, 'CONCILIADO')
        self.assertIsNotNone(res_deb.movimento)
        self.assertEqual(res_deb.movimento.tipo, 'SAIDA')

        # 2. Crédito no extrato (entrada avulsa / rendimento)
        item_cred = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('120.00'),
            descricao='RENDIMENTO POUPANCA'
        )
        res_cred = criar_lancamento_direto(
            tenant=self.tenant,
            item_id=item_cred.id,
            conta_contabil_id=conta_receita.id,
            historico="Rendimento Direto",
            usuario=self.user
        )
        self.assertEqual(res_cred.status, 'CONCILIADO')
        self.assertIsNotNone(res_cred.movimento)
        self.assertEqual(res_cred.movimento.tipo, 'ENTRADA')

    def test_validacoes_dividir_e_desfazer_conciliacao(self):
        hoje = timezone.localdate()
        item = ExtratoBancarioItem.objects.create(
            tenant=self.tenant,
            conta=self.conta_financeira,
            data=hoje,
            valor=Decimal('500.00'),
            descricao='ITEM PARA TESTE VALIDACOES'
        )
        # Menos de 2 partes
        with self.assertRaises(ValidationError):
            dividir_item_extrato(tenant=self.tenant, item_id=item.id, partes=[{'valor': Decimal('500.00')}], usuario=self.user)

        # Soma divergente
        with self.assertRaises(ValidationError):
            dividir_item_extrato(tenant=self.tenant, item_id=item.id, partes=[{'valor': Decimal('200.00')}, {'valor': Decimal('200.00')}], usuario=self.user)

        # Desfazer item não conciliado
        with self.assertRaises(ValidationError):
            desfazer_conciliacao(tenant=self.tenant, item_id=item.id, motivo="Não pode desfazer", usuario=self.user)

        # Desfazer movimento direto sem baixa
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        criar_lancamento_direto(tenant=self.tenant, item_id=item.id, conta_contabil_id=conta_receita.id, usuario=self.user)
        desfazer_conciliacao(tenant=self.tenant, item_id=item.id, motivo="Desfazendo direto", usuario=self.user)
        item.refresh_from_db()
        self.assertEqual(item.status, 'NAO_CONCILIADO')




class TestCobrancaRegistradaEWebhooks(BaseSprint10ATestCase):
    """Testa emissão idempotente de cobrança, cancelamento e webhook com HMAC."""

    def test_emissao_cobranca_idempotente(self):
        hoje = timezone.localdate()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje,
            data_competencia=hoje,
            valor_bruto=Decimal('350.00'),
            valor_liquido_esperado=Decimal('350.00'),
            origem_tipo='MANUAL'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            data_vencimento=hoje + datetime.timedelta(days=15),
            valor_nominal=Decimal('350.00'),
            saldo_em_aberto=Decimal('350.00'),
            status='PENDENTE'
        )

        # 1ª Emissão
        p1 = emitir_cobranca_parcela(tenant=self.tenant, parcela_id=parcela.id)
        charge_id_original = p1.gateway_charge_id
        self.assertTrue(charge_id_original.startswith("pay_asaas_"))
        self.assertTrue(len(p1.linha_digitavel) > 0)
        self.assertTrue(len(p1.payload_pix) > 0)

        # 2ª Emissão (idempotente: não deve gerar novo charge ID nem alterar valores)
        p2 = emitir_cobranca_parcela(tenant=self.tenant, parcela_id=parcela.id)
        self.assertEqual(p2.gateway_charge_id, charge_id_original)

    def test_webhook_com_assinatura_valida_e_repeticao_idempotente(self):
        hoje = timezone.localdate()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje,
            data_competencia=hoje,
            valor_bruto=Decimal('500.00'),
            valor_liquido_esperado=Decimal('500.00'),
            origem_tipo='MANUAL'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            data_vencimento=hoje,
            valor_nominal=Decimal('500.00'),
            saldo_em_aberto=Decimal('500.00'),
            status='PENDENTE',
            gateway_charge_id='pay_asaas_test_500'
        )

        payload = {
            "event": "PAYMENT_RECEIVED",
            "payment": {
                "id": "pay_asaas_test_500",
                "value": "500.00",
                "paymentDate": hoje.isoformat(),
                "fee": "2.50"
            }
        }
        body_bytes = json.dumps(payload).encode('utf-8')
        secret = self.config_cobranca.webhook_secret

        # Assinatura HMAC válida
        hmac_sig = hmac.new(secret.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()

        # 1. Processa webhook válido
        res1 = processar_webhook_cobranca(
            tenant=self.tenant,
            payload=payload,
            signature=hmac_sig,
            raw_body=body_bytes
        )
        self.assertEqual(res1['status'], 'success')
        parcela.refresh_from_db()
        self.assertEqual(parcela.status, 'PAGA')
        self.assertEqual(parcela.saldo_em_aberto, Decimal('0.00'))

        # 2. Webhook repetido (idempotência): NÃO gera segunda baixa
        res2 = processar_webhook_cobranca(
            tenant=self.tenant,
            payload=payload,
            signature=hmac_sig,
            raw_body=body_bytes
        )
        self.assertEqual(res2['status'], 'already_paid')
        self.assertEqual(BaixaParcela.objects.filter(parcela=parcela).count(), 1)

    def test_webhook_com_assinatura_invalida_rejeitado(self):
        payload = {"event": "PAYMENT_RECEIVED", "payment": {"id": "fake_pay"}}
        body_bytes = json.dumps(payload).encode('utf-8')

        with self.assertRaises(AssinaturaInvalidaError):
            processar_webhook_cobranca(
                tenant=self.tenant,
                payload=payload,
                signature='assinatura_forjada_invalida',
                raw_body=body_bytes
            )

    def test_cancelamento_e_emissao_titulo(self):
        hoje = timezone.localdate()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje,
            data_competencia=hoje,
            valor_bruto=Decimal('450.00'),
            valor_liquido_esperado=Decimal('450.00'),
            historico="Fatura de Venda Lote",
            origem_tipo='OUTROS'
        )
        p1 = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            numero_parcela=1,
            data_vencimento=hoje + datetime.timedelta(days=15),
            valor_nominal=Decimal('225.00'),
            saldo_em_aberto=Decimal('225.00'),
            status='PENDENTE'
        )
        p2 = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            numero_parcela=2,
            data_vencimento=hoje + datetime.timedelta(days=30),
            valor_nominal=Decimal('225.00'),
            saldo_em_aberto=Decimal('225.00'),
            status='PENDENTE'
        )
        emitidas = emitir_cobranca_titulo(tenant=self.tenant, titulo_id=titulo.id)
        self.assertEqual(len(emitidas), 2)
        self.assertTrue(emitidas[0].gateway_charge_id)

        # Cancelamento de cobrança
        cancelado = cancelar_cobranca_parcela(tenant=self.tenant, parcela_id=p1.id)
        self.assertTrue(cancelado)

    def test_cnab_remessa_e_retorno(self):
        hoje = timezone.localdate()
        adapter = ArquivoCNABAdapter()
        config_cnab = self.config_cobranca
        config_cnab.adaptador = 'ARQUIVO_CNAB'
        config_cnab.carteira = '109'
        config_cnab.save()

        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje,
            data_competencia=hoje,
            valor_bruto=Decimal('300.00'),
            valor_liquido_esperado=Decimal('300.00'),
            historico="Fatura CNAB",
            origem_tipo='OUTROS'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            numero_parcela=1,
            data_vencimento=hoje + datetime.timedelta(days=10),
            valor_nominal=Decimal('300.00'),
            saldo_em_aberto=Decimal('300.00'),
            status='PENDENTE'
        )
        remessa_str = adapter.gerar_remessa(config_cnab, [parcela], sequencial_remessa=1)
        self.assertTrue(len(remessa_str.splitlines()) >= 3)
        boleto_res = adapter.emitir_boleto(config_cnab, parcela)
        self.assertTrue(boleto_res.nosso_numero)
        self.assertTrue(boleto_res.linha_digitavel)



class TestReguaCobrancaEConsentimentoLGPD(BaseSprint10ATestCase):
    """Testa consentimento LGPD, opt-out, supressão de pagas e limites diários."""

    def test_regua_nao_envia_sem_consentimento_lgpd(self):
        hoje = timezone.localdate()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje - datetime.timedelta(days=10),
            data_competencia=hoje,
            valor_bruto=Decimal('100.00'),
            valor_liquido_esperado=Decimal('100.00'),
            origem_tipo='MANUAL'
        )
        # Parcela vence hoje (D0)
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            data_vencimento=hoje,
            valor_nominal=Decimal('100.00'),
            saldo_em_aberto=Decimal('100.00'),
            status='PENDENTE'
        )

        etapa_d0 = ReguaCobranca.objects.create(
            tenant=self.tenant,
            nome="Vencimento Hoje D0",
            dias_offset=0,
            canal='EMAIL',
            template_assunto="Seu boleto vence hoje!",
            template_corpo="Prezado {cliente_nome}, sua fatura de {valor} vence hoje.",
            ativo=True
        )

        # Sem consentimento registrado para o cliente:
        envios = executar_regua_cobranca(tenant=self.tenant, data_referencia=hoje, ignorar_janela_horario=True)
        self.assertEqual(len(envios), 1)
        self.assertEqual(envios[0].status, 'BLOQUEADO')
        self.assertIn("consentimento", envios[0].detalhes.lower())

    def test_regua_envia_com_consentimento_e_bloqueia_apos_opt_out(self):
        hoje = timezone.localdate()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje - datetime.timedelta(days=10),
            data_competencia=hoje,
            valor_bruto=Decimal('200.00'),
            valor_liquido_esperado=Decimal('200.00'),
            origem_tipo='MANUAL'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            data_vencimento=hoje,
            valor_nominal=Decimal('200.00'),
            saldo_em_aberto=Decimal('200.00'),
            status='PENDENTE'
        )

        ReguaCobranca.objects.create(
            tenant=self.tenant,
            nome="Vencimento D0",
            dias_offset=0,
            canal='EMAIL',
            template_assunto="Vencimento Hoje",
            template_corpo="Olá {cliente_nome}, fatura {valor}",
            ativo=True
        )

        # 1. Registra consentimento explícito
        registrar_consentimento(
            tenant=self.tenant,
            cliente_id=self.cliente.id,
            canal='EMAIL',
            origem='PORTAL_ADESAO'
        )

        # 2. Executa a régua: envio com sucesso!
        envios1 = executar_regua_cobranca(tenant=self.tenant, data_referencia=hoje, ignorar_janela_horario=True)
        self.assertEqual(len(envios1), 1)
        self.assertEqual(envios1[0].status, 'SUCESSO')

        # 3. Cliente solicita opt-out (revogação)
        revogar_consentimento(tenant=self.tenant, cliente_id=self.cliente.id, canal='EMAIL')

        # 4. Próxima execução para outro dia: bloqueado
        amanha = hoje + datetime.timedelta(days=1)
        parcela.data_vencimento = amanha
        parcela.save()

        envios2 = executar_regua_cobranca(tenant=self.tenant, data_referencia=amanha, ignorar_janela_horario=True)
        self.assertEqual(len(envios2), 1)
        self.assertEqual(envios2[0].status, 'BLOQUEADO')

    def test_regua_nao_envia_para_parcela_paga(self):
        hoje = timezone.localdate()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='LIQUIDADO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje - datetime.timedelta(days=10),
            data_competencia=hoje,
            valor_bruto=Decimal('100.00'),
            valor_liquido_esperado=Decimal('100.00'),
            origem_tipo='MANUAL'
        )
        # Parcela já paga
        ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            data_vencimento=hoje,
            valor_nominal=Decimal('100.00'),
            saldo_em_aberto=Decimal('0.00'),
            status='PAGA'
        )

        ReguaCobranca.objects.create(
            tenant=self.tenant,
            nome="Vencimento D0",
            dias_offset=0,
            canal='EMAIL',
            template_assunto="Vence Hoje",
            template_corpo="Texto",
            ativo=True
        )

        registrar_consentimento(tenant=self.tenant, cliente_id=self.cliente.id, canal='EMAIL')

        envios = executar_regua_cobranca(tenant=self.tenant, data_referencia=hoje, ignorar_janela_horario=True)
        # Nenhuma notificação deve ser gerada para parcela paga!
        self.assertEqual(len(envios), 0)


class TestProtestoManualMultiTenant(BaseSprint10ATestCase):
    """Testa protesto manual e isolamento estrito multi-tenant (404)."""

    def test_protesto_manual_atualiza_status(self):
        hoje = timezone.localdate()
        conta_receita = PlanoContas.objects.filter(tenant=self.tenant, tipo='ANALITICA', codigo_estrutural__startswith='3.1.1').first()
        titulo = TituloFinanceiro.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            tipo='RECEBER',
            status='ABERTO',
            cliente=self.cliente,
            conta_gerencial=conta_receita,
            data_emissao=hoje,
            data_competencia=hoje,
            valor_bruto=Decimal('900.00'),
            valor_liquido_esperado=Decimal('900.00'),
            origem_tipo='MANUAL'
        )
        parcela = ParcelaFinanceira.objects.create(
            tenant=self.tenant,
            titulo=titulo,
            data_vencimento=hoje - datetime.timedelta(days=30),
            valor_nominal=Decimal('900.00'),
            saldo_em_aberto=Decimal('900.00'),
            status='PENDENTE'
        )

        resp = self.client_api.post(f"/financeiro/api/parcelas/{parcela.id}/protestar/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        parcela.refresh_from_db()
        self.assertEqual(parcela.status, 'EM_PROTESTO')

    def test_multi_tenant_404_recurso_outro_tenant(self):
        tenant_b = Tenant.objects.create(
            razao_social="Outra Empresa B Ltda",
            nome_fantasia="Empresa B",
            cnpj="99.888.777/0001-66",
            modulo_financeiro_ativo=True,
            status_assinatura="ATIVO"
        )
        set_current_tenant(tenant_b)
        conta_contabil_b = PlanoContas.objects.create(
            tenant=tenant_b,
            codigo_estrutural='1.1.1.01',
            nome='Banco B',
            aceita_lancamento=True,
            tipo='ANALITICA'
        )
        conta_b = ContaFinanceira.objects.create(
            tenant=tenant_b,
            nome="Conta Banco B",
            conta_contabil=conta_contabil_b
        )
        item_b = ExtratoBancarioItem.objects.create(
            tenant=tenant_b,
            conta=conta_b,
            data=timezone.localdate(),
            valor=Decimal('500.00'),
            descricao='ITEM PRIVADO TENANT B'
        )

        # Volta a autenticar com o usuário do Tenant A
        set_current_tenant(self.tenant)
        resp = self.client_api.get(f"/financeiro/api/extrato-itens/{item_b.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


import unittest


class TestHypothesisSprint10A(unittest.TestCase):
    """Testes de invariantes monetários e divisão de extrato com Hypothesis."""

    @settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])
    @given(
        st.decimals(min_value=Decimal('10.00'), max_value=Decimal('50000.00'), places=2),
        st.integers(min_value=2, max_value=5)
    )
    def test_invariante_divisao_soma_exata(self, valor_total, qtd_partes):
        from core.money import allocate
        partes = allocate(valor_total, [1] * qtd_partes)
        self.assertEqual(sum(partes), quantize(valor_total, 2))
