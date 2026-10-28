import io
import zipfile
import threading
from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Tenant, Filial, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from core.money import quantize
from clientes.models import Cliente
from produtos.models import Produto, SkuRecarga, GasQuimico, ModeloCilindro
from vendas.models import Venda, ItemVenda
from financeiro.models import TituloFinanceiro, LancamentoContabil
from financeiro.seeds import seed_financeiro_tenant_completo

from fiscal.models import (
    ConfiguracaoFiscalFilial,
    RegraTributaria,
    RegraTributariaTributo,
    DocumentoFiscal,
    DocumentoFiscalItem,
    ItemDocumentoTributo,
    DocumentoFiscalEvento,
    TarefaInutilizacaoNumeracao,
)
from fiscal.crypto import encrypt_fiscal_secret, decrypt_fiscal_secret, sanitize_log_data
from fiscal.validators import (
    validar_cpf,
    validar_cpf_ou_cnpj,
    validar_inscricao_estadual,
    validar_ncm,
    validar_cest,
    validar_cfop,
)
from fiscal.adapters.fake_emissor import FakeEmissor
from fiscal.services.motor_tributario_service import (
    resolver_regra,
    calcular_tributos_item,
    RegraTributariaNaoEncontradaError,
    RegraTributariaAmbiguidadeError,
    RegraTributariaNaoAprovadaError,
)
from fiscal.services.numeracao_service import (
    reservar_proximo_numero,
    registrar_lacuna_inutilizacao,
    detectar_lacunas_numeracao,
)
from fiscal.services.nfe_venda_service import (
    montar_nfe,
    validar_pre_emissao,
    emitir_nfe_venda,
)
from fiscal.services.eventos_fiscal_service import (
    cancelar_nfe,
    carta_correcao_nfe,
    processar_inutilizacao,
)
from fiscal.services.certificado_service import (
    verificar_vencimento_certificados,
    gerar_lote_xmls_contador,
)

User = get_user_model()


class BaseFiscalTestCase(TestCase):
    """Setup base multi-tenant para testes da camada fiscal."""

    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Oxigênio Industrial Alfa Ltda",
            nome_fantasia="Alfa Gases",
            cnpj="12345678000195",
            status_assinatura='ATIVO',
            modulo_fiscal_ativo=True,
            modulo_vendas_ativo=True,
            modulo_financeiro_ativo=True
        )
        set_current_tenant(self.tenant)

        self.filial = Filial.objects.create(
            tenant=self.tenant,
            nome="Matriz São Paulo",
            cnpj="12345678000195",
            inscricao_estadual="110042490114",
            uf="SP",
            municipio_ibge="3550308",
            matriz=True
        )

        self.user_admin = User.objects.create_user(
            username='admin_fiscal',
            email='admin@alfa.com.br',
            password='Password123!',
            first_name='Admin',
            last_name='Fiscal'
        )
        self.membership_admin = Membership.objects.create(
            user=self.user_admin,
            tenant=self.tenant,
            papel='ADMIN',
            ativo=True
        )

        # Contador aprovador
        self.user_contador = User.objects.create_user(
            username='contador_crc',
            email='contador@alfa.com.br',
            password='Password123!',
            first_name='Roberto',
            last_name='Contador'
        )
        Membership.objects.create(
            user=self.user_contador,
            tenant=self.tenant,
            papel='GERENTE',
            ativo=True
        )

        # Configuração Fiscal da Filial
        self.config_fiscal = ConfiguracaoFiscalFilial.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            regime_tributario='SIMPLES_NACIONAL',
            crt='1',
            ambiente='HOMOLOGACAO',
            serie_nfe=1,
            proximo_numero_nfe=1,
            certificado_ref='cert_encrypted_path_dummy',
            certificado_valido_ate=timezone.localdate() + timedelta(days=60),
            prazo_cancelamento_horas=24
        )
        self.config_fiscal.set_credenciais({'api_key': 'key_secret_123', 'api_secret': 'sec_abc'})
        self.config_fiscal.save()

        # Cliente com atributos fiscais completos
        self.cliente_sp = Cliente.objects.create(
            tenant=self.tenant,
            nome="Hospital Samaritano SP",
            cnpj="28581699000140",
            ie="110042490114",
            indicador_ie="1",
            municipio_ibge="3550308",
            endereco="Rua Conselheiro Brotero",
            numero="1486",
            bairro="Higienópolis",
            cidade="São Paulo",
            estado="SP",
            cep="01232010"
        )

        # Gás, Casco e SKU precificado
        self.gas_o2 = GasQuimico.objects.create(
            nome="Oxigênio Medicinal",
            sigla="O2-MED",
            categoria="MEDICINAL"
        )
        self.modelo_t10 = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao="Cilindro T-10 Aço",
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('55.00')
        )
        self.sku_o2 = SkuRecarga.objects.create(
            tenant=self.tenant,
            gas=self.gas_o2,
            modelo_cilindro=self.modelo_t10,
            nome_comercial="Recarga O2 Medicinal 10m³",
            quantidade_carga=Decimal('10.00'),
            unidade='m3',
            massa_gas_kg=Decimal('13.30'),
            preco_base=Decimal('150.00'),
            ncm='28044000',
            cest='0100100',
            unidade_tributavel='m3',
            origem='0'
        )

        # Prepara plano de contas financeiro
        seed_financeiro_tenant_completo(self.tenant)

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()


class TestFakeEmissorContrato(BaseFiscalTestCase):
    """Testes de contrato da porta EmissorFiscalPort com o FakeEmissor."""

    def test_contrato_autorizacao_sucesso(self):
        emissor = FakeEmissor(comportamento='AUTORIZAR')
        payload = {'identificacao': {'numero': 1, 'serie': 1}}
        resp = emissor.emitir_nfe(payload)

        self.assertTrue(resp.sucesso)
        self.assertEqual(resp.status_sefaz, '100')
        self.assertEqual(len(resp.chave_acesso), 44)
        self.assertTrue(resp.protocolo.startswith('135'))
        self.assertIn('<nfeProc', resp.xml)
        self.assertIn('.pdf', resp.danfe_url)

    def test_contrato_rejeicao_com_acao_sugerida(self):
        emissor = FakeEmissor(comportamento='REJEITAR')
        resp = emissor.emitir_nfe({})

        self.assertFalse(resp.sucesso)
        self.assertEqual(resp.status, 'REJEITADO')
        self.assertEqual(resp.codigo_status_sefaz, '225')
        self.assertIn('Rejeição 225', resp.mensagem_erro)
        self.assertTrue(len(resp.acao_sugerida) > 0)

    def test_contrato_timeout(self):
        emissor = FakeEmissor(comportamento='TIMEOUT')
        with self.assertRaises(Exception):
            emissor.emitir_nfe({})

    def test_contrato_duplicidade(self):
        emissor = FakeEmissor(comportamento='DUPLICIDADE')
        resp = emissor.emitir_nfe({})

        self.assertFalse(resp.sucesso)
        self.assertEqual(resp.status, 'REJEITADO')
        self.assertEqual(resp.codigo_status_sefaz, '204')
        self.assertIn('Rejeição 204', resp.mensagem_erro)

    def test_contrato_cancelamento_cce_e_inutilizacao(self):
        emissor = FakeEmissor(comportamento='AUTORIZAR')

        resp_canc = emissor.cancelar('35261012345678000195550010000000011234567890', '135260000000001', 'Cancelamento de teste formal.')
        self.assertTrue(resp_canc.sucesso)
        self.assertEqual(resp_canc.status_sefaz, '135')

        resp_cce = emissor.carta_correcao('35261012345678000195550010000000011234567890', 1, 'Correção de endereço do destinatário sem alteração de valor.')
        self.assertTrue(resp_cce.sucesso)
        self.assertEqual(resp_cce.status_sefaz, '135')

        resp_inut = emissor.inutilizar(1, 10, 12, 'Quebra de sequencial de numeração.')
        self.assertTrue(resp_inut.sucesso)
        self.assertEqual(resp_inut.status_sefaz, '102')


class TestMotorTributario(BaseFiscalTestCase):
    """Testes do motor tributário (F-25): especificidade estrita, vigência, empate e reforma tributária."""

    def test_resolucao_regra_por_especificidade_hierarquica(self):
        hoje = timezone.localdate()

        # Regra 1: Apenas Operação (Score 1)
        r_generica = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra Geral de Venda",
            vigencia_inicio=hoje - timedelta(days=10),
            tipo_operacao='VENDA',
            cfop='5102'
        )

        # Regra 2: UFs + Operação (Score 6)
        r_ufs = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra Venda SP para SP",
            vigencia_inicio=hoje - timedelta(days=10),
            tipo_operacao='VENDA',
            uf_origem='SP',
            uf_destino='SP',
            cfop='5101'
        )

        # Regra 3: NCM + Operação (Score 11)
        r_ncm = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra Venda NCM 28044000",
            vigencia_inicio=hoje - timedelta(days=10),
            tipo_operacao='VENDA',
            ncm='28044000',
            cfop='5405'
        )

        # Regra 4: NCM + UFs + Operação (Score 16 - Mais específica)
        r_super = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra Específica Oxigênio SP->SP",
            vigencia_inicio=hoje - timedelta(days=10),
            tipo_operacao='VENDA',
            ncm='28044000',
            uf_origem='SP',
            uf_destino='SP',
            cfop='5101'
        )

        # 1. Com NCM e UFs -> Regra 4 vence
        resolvida = resolver_regra(self.tenant, item_ncm='28044000', operacao='VENDA', uf_origem='SP', uf_destino='SP')
        self.assertEqual(resolvida.id, r_super.id)

        # 2. Com NCM e outra UF (ex: RJ) -> Regra 3 (NCM sozinho) vence Regra Geral
        resolvida_rj = resolver_regra(self.tenant, item_ncm='28044000', operacao='VENDA', uf_origem='SP', uf_destino='RJ')
        self.assertEqual(resolvida_rj.id, r_ncm.id)

        # 3. Com outro NCM dentro de SP -> Regra 2 (UFs) vence Regra Geral
        resolvida_outro_ncm = resolver_regra(self.tenant, item_ncm='28041000', operacao='VENDA', uf_origem='SP', uf_destino='SP')
        self.assertEqual(resolvida_outro_ncm.id, r_ufs.id)

        # 4. Outro NCM para outra UF -> Regra Geral vence
        resolvida_outros = resolver_regra(self.tenant, item_ncm='28041000', operacao='VENDA', uf_origem='SP', uf_destino='RJ')
        self.assertEqual(resolvida_outros.id, r_generica.id)

    def test_empate_especificidade_gera_erro_claro(self):
        hoje = timezone.localdate()
        # Duas regras com o mesmo score para a mesma operação
        RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra A Venda NCM",
            vigencia_inicio=hoje - timedelta(days=5),
            tipo_operacao='VENDA',
            ncm='28044000',
            cfop='5101'
        )
        RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra B Venda NCM",
            vigencia_inicio=hoje - timedelta(days=1),
            tipo_operacao='VENDA',
            ncm='28044000',
            cfop='5102'
        )

        with self.assertRaises(RegraTributariaAmbiguidadeError):
            resolver_regra(self.tenant, item_ncm='28044000', operacao='VENDA', uf_origem='RJ', uf_destino='MG')

    def test_regra_fora_da_vigencia_gera_erro(self):
        hoje = timezone.localdate()
        # Regra que expirou ontem
        RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra Vencida",
            vigencia_inicio=hoje - timedelta(days=30),
            vigencia_fim=hoje - timedelta(days=1),
            tipo_operacao='VENDA',
            cfop='5102'
        )

        with self.assertRaises(RegraTributariaNaoEncontradaError):
            resolver_regra(self.tenant, item_ncm='28044000', operacao='VENDA', data_competencia=hoje)

    def test_producao_bloqueia_regra_sem_aprovacao_do_contador(self):
        hoje = timezone.localdate()
        regra = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra Não Homologada",
            vigencia_inicio=hoje,
            tipo_operacao='VENDA',
            cfop='5102',
            aprovada_por=None
        )

        # Em HOMOLOGACAO, permite uso
        r_homolog = resolver_regra(self.tenant, item_ncm='', operacao='VENDA', ambiente='HOMOLOGACAO')
        self.assertEqual(r_homolog.id, regra.id)

        # Em PRODUCAO, bloqueia com erro explícito
        with self.assertRaises(RegraTributariaNaoAprovadaError):
            resolver_regra(self.tenant, item_ncm='', operacao='VENDA', ambiente='PRODUCAO')

        # Após aprovação pelo contador, funciona em PRODUCAO
        regra.aprovada_por = self.user_contador
        regra.aprovada_em = timezone.now()
        regra.save()

        r_prod = resolver_regra(self.tenant, item_ncm='', operacao='VENDA', ambiente='PRODUCAO')
        self.assertEqual(r_prod.id, regra.id)

    def test_calculo_tributos_com_reforma_tributaria_e_zero_float(self):
        hoje = timezone.localdate()
        regra = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Regra Tributária Completa",
            vigencia_inicio=hoje,
            tipo_operacao='VENDA',
            cfop='5102'
        )
        # ICMS com redução de base de 20% e alíquota 18%
        RegraTributariaTributo.objects.create(
            tenant=self.tenant,
            regra=regra,
            tributo='ICMS',
            cst_csosn='00',
            reducao_base_pct=Decimal('20.0000'),
            aliquota=Decimal('18.0000')
        )
        # PIS 1.65%
        RegraTributariaTributo.objects.create(
            tenant=self.tenant,
            regra=regra,
            tributo='PIS',
            cst_csosn='01',
            aliquota=Decimal('1.6500')
        )
        # Reforma Tributária: IBS 10% e CBS 5.9%
        RegraTributariaTributo.objects.create(
            tenant=self.tenant,
            regra=regra,
            tributo='IBS',
            cst_csosn='01',
            aliquota=Decimal('10.0000')
        )
        RegraTributariaTributo.objects.create(
            tenant=self.tenant,
            regra=regra,
            tributo='CBS',
            cst_csosn='01',
            aliquota=Decimal('5.9000')
        )

        # Cálculo para 10 m³ a R$ 15,00 = R$ 150,00
        tributos = calcular_tributos_item(
            regra=regra,
            quantidade=Decimal('10.000'),
            valor_unitario=Decimal('15.00'),
            valor_total=Decimal('150.00')
        )

        mapa = {t['tributo']: t for t in tributos}

        # Base do ICMS reduzida em 20%: 150 * 0.8 = 120.00. Valor: 120 * 0.18 = 21.60
        self.assertEqual(mapa['ICMS']['base'], Decimal('120.00'))
        self.assertEqual(mapa['ICMS']['valor'], Decimal('21.60'))

        # PIS: 150 * 0.0165 = 2.475 -> ROUND_HALF_UP = 2.48
        self.assertEqual(mapa['PIS']['valor'], Decimal('2.48'))

        # IBS: 150 * 0.10 = 15.00
        self.assertEqual(mapa['IBS']['valor'], Decimal('15.00'))

        # CBS: 150 * 0.059 = 8.85
        self.assertEqual(mapa['CBS']['valor'], Decimal('8.85'))

        # Proibição de float
        with self.assertRaises(TypeError):
            calcular_tributos_item(regra, 10.0, Decimal('15.00'), Decimal('150.00'))


class TestNumeracaoConcorrenteELacunas(TransactionTestCase):
    """Testes de concorrência e detecção de lacunas de numeração (Task 6)."""

    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Empresa Teste Numeração Ltda",
            nome_fantasia="Filial Numeração",
            cnpj="33444555000181",
            status_assinatura='ATIVO',
            modulo_fiscal_ativo=True,
            modulo_vendas_ativo=True,
            modulo_financeiro_ativo=True
        )
        set_current_tenant(self.tenant)
        self.filial = Filial.objects.create(
            tenant=self.tenant,
            nome="Filial Numeração",
            cnpj="33444555000181",
            uf="SP",
            municipio_ibge="3509502",
            matriz=True
        )
        self.config_fiscal = ConfiguracaoFiscalFilial.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            serie_nfe=1,
            proximo_numero_nfe=1,
            ambiente='HOMOLOGACAO'
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_reserva_concorrente_sem_duplicidade(self):
        """Dispara múltiplas threads simultâneas para reservar números fiscais."""
        numeros_reservados = []
        threads = []
        lock = threading.Lock()
        from django.db import connection
        from core.tenancy import tenant_context

        def worker():
            with tenant_context(self.tenant):
                if connection.vendor == 'sqlite':
                    with lock:
                        num, _ = reservar_proximo_numero(self.tenant, self.filial.id, modelo='NFE_55')
                        numeros_reservados.append(num)
                else:
                    num, _ = reservar_proximo_numero(self.tenant, self.filial.id, modelo='NFE_55')
                    with lock:
                        numeros_reservados.append(num)

        for _ in range(10):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(numeros_reservados), 10)
        # Todos os 10 números devem ser únicos
        self.assertEqual(len(set(numeros_reservados)), 10)
        self.assertEqual(sorted(numeros_reservados), list(range(1, 11)))

    def test_detectar_lacunas_gera_tarefa_inutilizacao(self):
        """Simula salto de numeração e valida a criação de TarefaInutilizacaoNumeracao."""
        # Configura proximo_numero_nfe como 6 (espera documentos de 1 a 5)
        self.config_fiscal.proximo_numero_nfe = 6
        self.config_fiscal.save()

        # Cria apenas documentos 1 e 5 (números 2, 3 e 4 foram perdidos)
        DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            modelo='NFE_55',
            serie=1,
            numero=1,
            status='AUTORIZADO',
            origem_id='1'
        )
        DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            modelo='NFE_55',
            serie=1,
            numero=5,
            status='AUTORIZADO',
            origem_id='5'
        )

        tarefas = detectar_lacunas_numeracao(self.tenant, self.filial.id, modelo='NFE_55', serie=1)
        self.assertEqual(len(tarefas), 1)
        self.assertEqual(tarefas[0].numero_inicial, 2)
        self.assertEqual(tarefas[0].numero_final, 4)
        self.assertEqual(tarefas[0].status, 'PENDENTE')


class TestNfeVendaEmissaoEIdempotencia(BaseFiscalTestCase):
    """Testes de montagem pura, validações pré-emissão, emissão e idempotência da NF-e (Task 7)."""

    def setUp(self):
        super().setUp()
        # Regra aprovada para venda de O2 em SP
        self.regra_sp = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Venda Interna SP",
            vigencia_inicio=timezone.localdate() - timedelta(days=1),
            tipo_operacao='VENDA',
            ncm='28044000',
            uf_origem='SP',
            uf_destino='SP',
            cfop='5102',
            aprovada_por=self.user_contador,
            aprovada_em=timezone.now()
        )
        RegraTributariaTributo.objects.create(
            tenant=self.tenant,
            regra=self.regra_sp,
            tributo='ICMS',
            cst_csosn='102',
            aliquota=Decimal('0.0000')
        )

        # Cria Venda
        self.venda = Venda.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_sp,
            filial=self.filial,
            status='Pendente',
            valor_total=Decimal('300.00')
        )
        ItemVenda.objects.create(
            tenant=self.tenant,
            venda=self.venda,
            sku=self.sku_o2,
            quantidade=2,
            valor_unitario=Decimal('150.00'),
            valor_total=Decimal('300.00')
        )

    def test_montar_nfe_funcao_pura(self):
        payload = montar_nfe(self.venda, self.config_fiscal, numero=1, serie=1)
        self.assertEqual(payload['identificacao']['numero'], 1)
        self.assertEqual(payload['emitente']['cnpj'], '12345678000195')
        self.assertEqual(payload['destinatario']['documento'], '28581699000140')
        self.assertEqual(payload['totais']['valor_total_nfe'], Decimal('300.00'))
        self.assertEqual(len(payload['itens']), 1)
        self.assertEqual(payload['itens'][0]['cfop'], '5102')

    def test_pre_validacao_rejeita_incoerencia_cfop_com_ufs(self):
        payload = montar_nfe(self.venda, self.config_fiscal, numero=1, serie=1)
        # Altera CFOP para interestadual (6.102) em operação interna SP -> SP
        payload['itens'][0]['cfop'] = '6102'

        with self.assertRaises(ValidationError) as ctx:
            validar_pre_emissao(payload)
        self.assertIn("Incoerência de CFOP", str(ctx.exception))

    def test_emissao_nfe_sucesso_com_fake_emissor(self):
        emissor = FakeEmissor(comportamento='AUTORIZAR')
        doc = emitir_nfe_venda(venda=self.venda, emissor_port=emissor)

        self.assertEqual(doc.status, 'AUTORIZADO')
        self.assertEqual(doc.numero, 1)
        self.assertEqual(doc.serie, 1)
        self.assertEqual(len(doc.chave_acesso), 44)
        self.assertTrue(doc.protocolo.startswith('135'))
        self.assertIn(doc.chave_acesso, self.venda.documento_fiscal_ref)

    def test_idempotencia_duplo_clique_retorna_mesmo_documento(self):
        emissor = FakeEmissor(comportamento='AUTORIZAR')
        key = "idemp_clique_duplo_12345"

        doc1 = emitir_nfe_venda(venda=self.venda, emissor_port=emissor, idempotency_key=key)
        # Segunda chamada simultânea com a mesma chave
        doc2 = emitir_nfe_venda(venda=self.venda, emissor_port=emissor, idempotency_key=key)

        self.assertEqual(doc1.id, doc2.id)
        self.assertEqual(doc1.numero, doc2.numero)
        # Próximo número da filial avançou apenas 1 vez
        self.config_fiscal.refresh_from_db()
        self.assertEqual(self.config_fiscal.proximo_numero_nfe, 2)


class TestSequenciamentoComFinanceiro(BaseFiscalTestCase):
    """Testes de sequenciamento com o financeiro (Task 9): venda faturada após autorização da NF-e."""

    def setUp(self):
        super().setUp()
        self.regra_sp = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Venda SP Tributada",
            vigencia_inicio=timezone.localdate() - timedelta(days=1),
            tipo_operacao='VENDA',
            ncm='28044000',
            cfop='5102',
            aprovada_por=self.user_contador,
            aprovada_em=timezone.now()
        )
        # 10% de tributos reais
        RegraTributariaTributo.objects.create(
            tenant=self.tenant,
            regra=self.regra_sp,
            tributo='ICMS',
            cst_csosn='00',
            aliquota=Decimal('10.0000')
        )

        self.venda = Venda.objects.create(
            tenant=self.tenant,
            cliente=self.cliente_sp,
            filial=self.filial,
            status='Pendente',
            valor_total=Decimal('200.00')
        )
        ItemVenda.objects.create(
            tenant=self.tenant,
            venda=self.venda,
            sku=self.sku_o2,
            quantidade=2,
            valor_unitario=Decimal('100.00'),
            valor_total=Decimal('200.00')
        )

    def test_venda_faturada_com_fiscal_ativo_nao_gera_titulo_antes_da_nfe(self):
        """Ao mudar status da venda para Faturada com fiscal ativo, evento NÃO é disparado."""
        client = APIClient()
        client.force_authenticate(user=self.user_admin)

        resp = client.post(f"/vendas/api/{self.venda.id}/alterar_status/", {'status': 'Faturada'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Nenhum título a receber deve existir ainda
        titulos = TituloFinanceiro.objects.filter(tenant=self.tenant, origem_id=str(self.venda.id))
        self.assertEqual(titulos.count(), 0)

    def test_nfe_autorizada_publica_venda_com_tributos_reais(self):
        """Ao autorizar a NF-e, publica venda_faturada e gera título com deduções fiscais reais."""
        emissor = FakeEmissor(comportamento='AUTORIZAR')
        doc = emitir_nfe_venda(venda=self.venda, emissor_port=emissor)
        self.assertEqual(doc.status, 'AUTORIZADO')

        # Título financeiro criado pelo evento com valor bruto correto
        titulo = TituloFinanceiro.objects.filter(tenant=self.tenant, origem_id=str(self.venda.id)).first()
        self.assertIsNotNone(titulo)
        self.assertEqual(titulo.valor_bruto, Decimal('200.00'))

        # Lançamento contábil de deduções com os tributos reais (10% de 200 = R$ 20,00)
        lanc_deducoes = LancamentoContabil.objects.filter(
            tenant=self.tenant,
            origem_tipo='venda_faturada_deducoes',
            origem_id=str(self.venda.id)
        ).first()
        self.assertIsNotNone(lanc_deducoes)
        partida_deducao = lanc_deducoes.partidas.filter(tipo_partida='DEBITO').first()
        self.assertEqual(partida_deducao.valor, Decimal('20.00'))

    def test_nfe_rejeitada_nao_gera_titulo_financeiro(self):
        """Se a NF-e for rejeitada, nenhum título é gerado e numeração vira tarefa de inutilização."""
        emissor = FakeEmissor(comportamento='REJEITAR')
        doc = emitir_nfe_venda(venda=self.venda, emissor_port=emissor)
        self.assertEqual(doc.status, 'REJEITADO')

        # Nenhum título financeiro
        titulos = TituloFinanceiro.objects.filter(tenant=self.tenant, origem_id=str(self.venda.id))
        self.assertEqual(titulos.count(), 0)

        # Tarefa de inutilização gerada para o número consumido (Task 6)
        tarefa_inut = TarefaInutilizacaoNumeracao.objects.filter(
            tenant=self.tenant,
            numero_inicial=doc.numero,
            numero_final=doc.numero
        ).first()
        self.assertIsNotNone(tarefa_inut)


class TestSegurancaELogs(BaseFiscalTestCase):
    """Testes de segurança de credenciais, cifra Fernet, sanitização de logs e exportação XML (Task 2 e 10)."""

    def test_cifra_e_decifra_segredos(self):
        chave_secreta = "minha_chave_ultra_secreta_de_gateway_123"
        cifrado = encrypt_fiscal_secret(chave_secreta)
        self.assertNotEqual(cifrado, chave_secreta)

        decifrado = decrypt_fiscal_secret(cifrado)
        self.assertEqual(decifrado, chave_secreta)

    def test_sanitizacao_de_logs_sensíveis(self):
        dado_bruto = {
            'usuario': 'operador',
            'api_key': 'super_secret_key_12345',
            'api_secret': 'secret_password_abc',
            'payload': {
                'token': 'bearer_token_xyz',
                'numero_nf': 100
            }
        }
        sanitizado = sanitize_log_data(dado_bruto)
        self.assertEqual(sanitizado['api_key'], '***REDACTED***')
        self.assertEqual(sanitizado['api_secret'], '***REDACTED***')
        self.assertEqual(sanitizado['payload']['token'], '***REDACTED***')
        self.assertEqual(sanitizado['payload']['numero_nf'], 100)

    def test_alerta_vencimento_certificado_digital(self):
        # Filial A: vence em 20 dias (deve alertar)
        self.config_fiscal.certificado_valido_ate = timezone.localdate() + timedelta(days=20)
        self.config_fiscal.save()

        alertas = verificar_vencimento_certificados(dias=30)
        self.assertTrue(any(a['filial_id'] == self.filial.id for a in alertas))

        # Filial A: vence em 45 dias (não deve alertar para janela de 30 dias)
        self.config_fiscal.certificado_valido_ate = timezone.localdate() + timedelta(days=45)
        self.config_fiscal.save()

        alertas = verificar_vencimento_certificados(dias=30)
        self.assertFalse(any(a['filial_id'] == self.filial.id for a in alertas))

    def test_gerar_lote_xmls_contador_compactado(self):
        DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            numero=10,
            serie=1,
            status='AUTORIZADO',
            chave_acesso='35261012345678000195550010000000101234567890',
            xml_autorizado='<nfeProc><NFe><infNFe Id="35261010">Nota 10</infNFe></NFe></nfeProc>',
            origem_id='10'
        )
        DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            numero=11,
            serie=1,
            status='AUTORIZADO',
            chave_acesso='35261012345678000195550010000000111234567890',
            xml_autorizado='<nfeProc><NFe><infNFe Id="35261011">Nota 11</infNFe></NFe></nfeProc>',
            origem_id='11'
        )

        zip_bytes = gerar_lote_xmls_contador(self.tenant, filial_id=self.filial.id)
        self.assertTrue(len(zip_bytes) > 0)

        # Valida conteúdo do ZIP
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            nomes = zf.namelist()
            self.assertEqual(len(nomes), 2)
            self.assertIn('35261012345678000195550010000000101234567890.xml', nomes)


class TestMultiTenancyEndpointsFiscais(BaseFiscalTestCase):
    """Testes de isolamento multi-tenant nos endpoints da API fiscal (Global Rule 3)."""

    def setUp(self):
        super().setUp()
        self.tenant_b = Tenant.objects.create(
            razao_social="Gases Beta Ltda",
            nome_fantasia="Beta Gases",
            cnpj="98765432000198",
            status_assinatura='ATIVO',
            modulo_fiscal_ativo=True,
            modulo_vendas_ativo=True,
            modulo_financeiro_ativo=True
        )
        self.user_b = User.objects.create_user(
            username='user_beta',
            email='user@beta.com',
            password='Password123!'
        )
        Membership.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            papel='ADMIN',
            ativo=True
        )

        self.doc_tenant_a = DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            numero=99,
            serie=1,
            status='AUTORIZADO',
            origem_id='99'
        )

    def test_usuario_outro_tenant_recebe_404(self):
        client = APIClient()
        client.force_authenticate(user=self.user_b)

        # Tentativa de acessar documento do Tenant A pelo usuário do Tenant B
        resp = client.get(f"/api/fiscal/documentos/{self.doc_tenant_a.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # Tentativa de acessar configuração do Tenant A
        resp_cfg = client.get(f"/api/fiscal/configuracoes/{self.config_fiscal.id}/")
        self.assertEqual(resp_cfg.status_code, status.HTTP_404_NOT_FOUND)

    def test_credenciais_nao_sao_vazadas_em_resposta_da_api(self):
        client = APIClient()
        client.force_authenticate(user=self.user_admin)

        resp = client.get(f"/api/fiscal/configuracoes/{self.config_fiscal.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Segredos nunca aparecem na resposta
        self.assertNotIn('credenciais_gateway_cifradas', resp.data)
        self.assertNotIn('key_secret_123', str(resp.data))
        self.assertTrue(resp.data.get('tem_credenciais'))


class TestEventosFiscais(BaseFiscalTestCase):
    """Testes detalhados de ciclo de vida de eventos fiscais (cancelamento, CC-e e inutilização)."""

    def setUp(self):
        super().setUp()
        self.doc_autorizado = DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            numero=101,
            serie=1,
            status='AUTORIZADO',
            chave_acesso='35261012345678000195550010000001011000000018',
            protocolo='135260000000101',
            data_autorizacao=timezone.now(),
            origem_id='101'
        )

    def test_cancelar_nfe_sucesso(self):
        fake = FakeEmissor(modo='AUTORIZAR')
        evento = cancelar_nfe(
            documento=self.doc_autorizado,
            justificativa="Cliente solicitou cancelamento do pedido por erro de faturamento",
            emissor_port=fake
        )
        self.doc_autorizado.refresh_from_db()
        self.assertEqual(self.doc_autorizado.status, 'CANCELADO')
        self.assertEqual(evento.tipo_evento, 'CANCELAMENTO')
        self.assertEqual(evento.status, 'AUTORIZADO')
        self.assertIn("110111", evento.xml_evento)

    def test_cancelar_nfe_validacoes(self):
        fake = FakeEmissor(modo='AUTORIZAR')
        # 1. Justificativa muito curta (< 15 chars)
        with self.assertRaises(ValidationError) as ctx:
            cancelar_nfe(self.doc_autorizado, justificativa="Cancelamento", emissor_port=fake)
        self.assertIn("no mínimo 15 caracteres", str(ctx.exception))

        # 2. Documento com status não autorizado
        doc_rascunho = DocumentoFiscal.objects.create(
            tenant=self.tenant, filial=self.filial, numero=102, serie=1, status='RASCUNHO'
        )
        with self.assertRaises(ValidationError) as ctx:
            cancelar_nfe(doc_rascunho, justificativa="Cancelamento de rascunho de teste", emissor_port=fake)
        self.assertIn("Apenas documentos com status AUTORIZADO", str(ctx.exception))

        # 3. Prazo expirado (autorizada há 48h com prazo limite de 24h)
        self.doc_autorizado.data_autorizacao = timezone.now() - timedelta(hours=48)
        self.doc_autorizado.save(update_fields=['data_autorizacao'])
        with self.assertRaises(ValidationError) as ctx:
            cancelar_nfe(self.doc_autorizado, justificativa="Cancelamento de nota antiga fora do prazo", emissor_port=fake)
        self.assertIn("expirado", str(ctx.exception))

    def test_cancelar_nfe_rejeicao_sefaz(self):
        fake = FakeEmissor(modo='REJEITAR', codigo_rejeicao='218', motivo_rejeicao='NF-e já está cancelada na SEFAZ')
        with self.assertRaises(ValidationError) as ctx:
            cancelar_nfe(
                self.doc_autorizado,
                justificativa="Cancelamento para teste de rejeição sefaz",
                emissor_port=fake
            )
        self.assertIn("Cancelamento rejeitado pela SEFAZ", str(ctx.exception))

    def test_carta_correcao_sucesso_e_incremento_sequencial(self):
        fake = FakeEmissor(modo='AUTORIZAR')
        # CC-e 1
        cce1 = carta_correcao_nfe(
            documento=self.doc_autorizado,
            correcao="Correcao no endereco de entrega rua das flores 123",
            emissor_port=fake
        )
        self.assertEqual(cce1.sequencial, 1)
        self.assertEqual(cce1.status, 'AUTORIZADO')

        # CC-e 2
        cce2 = carta_correcao_nfe(
            documento=self.doc_autorizado,
            correcao="Correcao na observacao fiscal dados adicionais",
            emissor_port=fake
        )
        self.assertEqual(cce2.sequencial, 2)
        self.assertEqual(cce2.status, 'AUTORIZADO')

    def test_carta_correcao_validacoes(self):
        fake = FakeEmissor(modo='AUTORIZAR')
        with self.assertRaises(ValidationError) as ctx:
            carta_correcao_nfe(self.doc_autorizado, correcao="Curto", emissor_port=fake)
        self.assertIn("no mínimo 15 caracteres", str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            carta_correcao_nfe(self.doc_autorizado, correcao="X" * 1001, emissor_port=fake)
        self.assertIn("não pode exceder 1000", str(ctx.exception))

    def test_processar_inutilizacao_sucesso_e_rejeicao(self):
        tarefa = TarefaInutilizacaoNumeracao.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            modelo='NFE_55',
            serie=1,
            numero_inicial=50,
            numero_final=50,
            motivo="Quebra de sequencia numerica por falha de integracao",
            status='PENDENTE'
        )

        fake_sucesso = FakeEmissor(modo='AUTORIZAR')
        processar_inutilizacao(tarefa, emissor_port=fake_sucesso)
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.status, 'INUTILIZADO')
        self.assertTrue(tarefa.protocolo.startswith("13526"))

        # Teste de rejeição na inutilização
        tarefa2 = TarefaInutilizacaoNumeracao.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            modelo='NFE_55',
            serie=1,
            numero_inicial=60,
            numero_final=60,
            motivo="Falha de emissao quebra de numeracao teste",
            status='PENDENTE'
        )
        fake_erro = FakeEmissor(modo='REJEITAR', codigo_rejeicao='256', motivo_rejeicao='Faixa já inutilizada')
        processar_inutilizacao(tarefa2, emissor_port=fake_erro)
        tarefa2.refresh_from_db()
        self.assertEqual(tarefa2.status, 'ERRO')


class TestNumeracaoCasosAdicionais(BaseFiscalTestCase):
    """Testes adicionais de numeração para MDF-e, CT-e e validações."""

    def test_reservar_proximo_numero_mdfe_e_cte(self):
        num_mdfe, serie_mdfe = reservar_proximo_numero(self.tenant, self.filial.id, modelo='MDFE_58')
        self.assertEqual(num_mdfe, 1)
        self.assertEqual(serie_mdfe, 1)

        num_cte, serie_cte = reservar_proximo_numero(self.tenant, self.filial.id, modelo='CTE_57')
        self.assertEqual(num_cte, 1)
        self.assertEqual(serie_cte, 1)

        self.config_fiscal.refresh_from_db()
        self.assertEqual(self.config_fiscal.proximo_numero_mdfe, 2)
        self.assertEqual(self.config_fiscal.proximo_numero_cte, 2)

    def test_registrar_lacuna_inutilizacao_validacoes(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_lacuna_inutilizacao(
                self.tenant, self.filial.id, 'NFE_55', 1, 10, 10, motivo="Curto"
            )
        self.assertIn("no mínimo 15 caracteres", str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            registrar_lacuna_inutilizacao(
                self.tenant, self.filial.id, 'NFE_55', 1, 20, 10, motivo="Justificativa com mais de quinze caracteres"
            )
        self.assertIn("superior ao número final", str(ctx.exception))

    def test_detectar_lacunas_sem_config_ou_zerado(self):
        filial_sem_cfg = Filial.objects.create(
            tenant=self.tenant,
            nome="Filial Sem Cfg",
            cnpj="33444555000181",
            inscricao_estadual="123456789",
            uf="SP",
            municipio_ibge="3550308",
            matriz=False
        )
        res = detectar_lacunas_numeracao(self.tenant, filial_sem_cfg.id)
        self.assertEqual(res, [])


class TestNfeVendaCasosAdicionais(BaseFiscalTestCase):
    """Testes de funções auxiliares e regras de exceção da emissão de venda."""

    def test_montar_nfe_venda_sem_itens_levanta_validacao(self):
        venda_vazia = Venda.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            cliente=self.cliente_sp,
            status='Pendente',
            valor_total=Decimal('0.00')
        )
        with self.assertRaises(ValidationError) as ctx:
            montar_nfe(venda_vazia, self.config_fiscal, numero=1, serie=1)
        self.assertIn("ao menos um item", str(ctx.exception))

