import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Tenant, Filial, Membership
from core.tenancy import set_current_tenant
from core.money import quantize
from clientes.models import Cliente
from produtos.models import (
    Produto,
    SkuRecarga,
    GasQuimico,
    ModeloCilindro,
    Cilindro,
    LoteEnvase,
    TabelaIndenizacaoCilindro,
    ClasseRiscoGas,
)
from vendas.models import Venda, ItemVenda
from logistica.models import Entrega, Veiculo, Rota
from financeiro.models import TituloFinanceiro, PlanoContas
from financeiro.seeds import seed_financeiro_tenant_completo

from fiscal.models import (
    ConfiguracaoFiscalFilial,
    RegraTributaria,
    RegraTributariaTributo,
    DocumentoFiscal,
    DocumentoFiscalItem,
    ItemDocumentoTributo,
    DocumentoFiscalEvento,
    MovimentoComodatoFiscal,
    ConfiguracaoMDFe,
    DocumentoFiscalEntrada,
    ApuracaoImposto,
    OrdemRecargaTerceiro,
    ItemOrdemRecargaTerceiro,
)
from fiscal.adapters.fake_emissor import FakeEmissor
from fiscal.services.seeds_fiscal_gases import seed_regras_tributarias_gases
from fiscal.services.comodato_fiscal_service import (
    obter_valor_bem_cilindro,
    gerar_nfe_remessa_comodato,
    gerar_nfe_retorno_comodato,
    relatorio_divergencias_comodato,
)
from fiscal.services.locacao_fiscal_service import gerar_fatura_locacao
from fiscal.services.nfe_venda_service import montar_nfe, validar_pre_emissao
from fiscal.services.transporte_service import (
    emitir_cte_transporte,
    montar_e_emitir_mdfe,
    encerrar_mdfe_entrega,
    verificar_mdfes_abertos_alerta,
)
from fiscal.services.importacao_xml_service import importar_xml_nfe_compra
from fiscal.services.apuracao_service import (
    calcular_apuracao_imposto,
    fechar_apuracao_e_gerar_guia,
)
from fiscal.services.recarga_terceiro_service import (
    criar_ordem_recarga,
    avancar_status_ordem,
    faturar_ordem_recarga,
)

User = get_user_model()


class BaseFiscalGasesTestCase(TestCase):
    """Setup base para testes de operações fiscais próprias de gases (Sprint 11B)."""

    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Oxigênio & Gases Especiais Alfa Ltda",
            nome_fantasia="Alfa Gases",
            cnpj="12345678000195",
            status_assinatura='ATIVO',
            modulo_fiscal_ativo=True,
            modulo_vendas_ativo=True,
            modulo_financeiro_ativo=True,
            modulo_logistica_ativo=True,
            presta_servico_transporte=False,  # Padrão: Venda CIF frota própria (não transportadora)
            tratamento_locacao='FATURA_SEM_DOCUMENTO_FISCAL'
        )
        set_current_tenant(self.tenant)
        seed_financeiro_tenant_completo(self.tenant)

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
            username='admin_fiscal_11b',
            email='admin@alfa11b.com',
            password='Password123!'
        )
        Membership.objects.create(
            user=self.user_admin,
            tenant=self.tenant,
            papel='ADMIN',
            ativo=True
        )

        self.config_fiscal = ConfiguracaoFiscalFilial.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            regime_tributario='SIMPLES_NACIONAL',
            crt='1',
            ambiente='HOMOLOGACAO',
            serie_nfe=1,
            proximo_numero_nfe=1,
            serie_mdfe=1,
            proximo_numero_mdfe=1,
            serie_cte=1,
            proximo_numero_cte=1,
            certificado_valido_ate=timezone.localdate() + timedelta(days=90)
        )

        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome="Hospital Metropolitano",
            cnpj="28581699000140",
            ie="110042490114",
            indicador_ie="1",
            municipio_ibge="3550308",
            estado="SP",
            endereco="Av. Paulista, 1000"
        )

        self.gas_o2 = GasQuimico.objects.create(
            nome="Oxigênio Medicinal",
            sigla="O2-MED",
            categoria="MEDICINAL",
            numero_onu="1072",
            classe_risco="2.2"
        )

        self.modelo_t50 = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao="Cilindro Aço 50 Litros",
            material="ACO",
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('55.00')
        )

        self.cilindro_1 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-CIL-001",
            numero_serie_ogiva="ALFA-001",
            fabricante="Cilbras",
            ano_fabricacao=2022,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.20'),
            valor_aquisicao=Decimal('850.00'),
            data_ultimo_reteste=timezone.localdate() - timedelta(days=100),
            data_proximo_reteste=timezone.localdate() + timedelta(days=1000),
            status='CHEIO_DISPONIVEL'
        )

        # Classe de Risco ANTT
        self.classe_risco_o2 = ClasseRiscoGas.objects.create(
            tenant=self.tenant,
            gas=self.gas_o2,
            numero_onu="1072",
            classe_risco="2.2",
            subclasse="5.1",
            numero_risco="25",
            descricao_transporte="OXIGÊNIO COMPRIMIDO"
        )

        # Veículo e Rota
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="ABC1D23",
            modelo="Mercedes Sprinter",
            marca="Mercedes-Benz",
            ano=2021,
            capacidade_carga=Decimal('2500.00'),
            tara_veiculo_kg=Decimal('2200.00'),
            rntrc_antt="123456789",
            filial=self.filial
        )

        seed_financeiro_tenant_completo(self.tenant)


class TestComodatoFiscal(BaseFiscalGasesTestCase):
    """Testes de emissão de comodato, retorno e relatório de divergências (Tasks 1, 2 e 3)."""

    def test_valor_bem_resolucao_prioridades(self):
        # 1. Fallback sem tabela e sem valor_aquisicao -> 500.00
        cil_sem_valor = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-TEST-002",
            numero_serie_ogiva="SERIE-002",
            fabricante="Cilbras",
            ano_fabricacao=2020,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            valor_aquisicao=Decimal('0.00'),
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + timedelta(days=365)
        )
        val = obter_valor_bem_cilindro(cil_sem_valor, self.tenant)
        self.assertEqual(val, Decimal('500.00'))

        # 2. Resolução por valor_aquisicao
        val_aq = obter_valor_bem_cilindro(self.cilindro_1, self.tenant)
        self.assertEqual(val_aq, Decimal('850.00'))

        # 3. Resolução por TabelaIndenizacaoCilindro (sobrepõe valor_aquisicao)
        TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant,
            tipo_cilindro=self.modelo_t50,
            gas=self.gas_o2,
            valor=Decimal('1200.00'),
            vigencia_inicio=timezone.localdate() - timedelta(days=10)
        )
        val_tab = obter_valor_bem_cilindro(self.cilindro_1, self.tenant)
        self.assertEqual(val_tab, Decimal('1200.00'))

    def test_fluxo_completo_comodato_remessa_e_retorno(self):
        # Remessa em Comodato
        doc_remessa = gerar_nfe_remessa_comodato(
            tenant=self.tenant,
            filial=self.filial,
            cliente=self.cliente,
            cilindros=[self.cilindro_1]
        )
        self.assertEqual(doc_remessa.tipo_operacao, 'REMESSA_COMODATO')
        self.assertEqual(doc_remessa.status, 'RASCUNHO')
        self.assertEqual(doc_remessa.itens.count(), 1)
        self.assertEqual(doc_remessa.itens.first().cfop, '5908')

        # Verifica criação do movimento
        mov_remessa = MovimentoComodatoFiscal.objects.filter(
            tenant=self.tenant,
            cilindro=self.cilindro_1,
            tipo='REMESSA'
        ).first()
        self.assertIsNotNone(mov_remessa)
        self.assertEqual(mov_remessa.cliente, self.cliente)

        # Retorno de Comodato
        doc_retorno = gerar_nfe_retorno_comodato(
            tenant=self.tenant,
            filial=self.filial,
            cliente=self.cliente,
            cilindros=[self.cilindro_1]
        )
        self.assertEqual(doc_retorno.tipo_operacao, 'RETORNO_COMODATO')
        self.assertEqual(doc_retorno.itens.first().cfop, '1909')

        mov_retorno = MovimentoComodatoFiscal.objects.filter(
            tenant=self.tenant,
            cilindro=self.cilindro_1,
            tipo='RETORNO'
        ).first()
        self.assertIsNotNone(mov_retorno)

    def test_relatorio_divergencias_comodato(self):
        # Caso 1: Cilindro no cliente sem NF-e de remessa aberta (SEM_NOTA_REMESSA)
        self.cilindro_1.status = 'EM_POSSE_CLIENTE'
        self.cilindro_1.cliente_posse_atual = self.cliente
        self.cilindro_1.posse_desde = timezone.now() - timedelta(days=5)
        self.cilindro_1.save()

        divs = relatorio_divergencias_comodato(self.tenant, self.filial)
        self.assertEqual(len(divs), 1)
        self.assertEqual(divs[0]['tipo_divergencia'], 'SEM_NOTA_REMESSA')

        # Caso 2: Emite remessa com mais de 30 dias (ESTADIA_EXCEDIDA)
        doc_rem = DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            numero=10,
            serie=1,
            status='AUTORIZADO',
            origem_id='10'
        )
        mov = MovimentoComodatoFiscal.objects.create(
            tenant=self.tenant,
            cilindro=self.cilindro_1,
            cliente=self.cliente,
            filial=self.filial,
            documento_fiscal=doc_rem,
            tipo='REMESSA',
            data_movimento=timezone.now() - timedelta(days=40),
            valor_bem=Decimal('850.00')
        )
        divs2 = relatorio_divergencias_comodato(self.tenant, self.filial, prazo_dias_padrao=30)
        self.assertEqual(len(divs2), 1)
        self.assertEqual(divs2[0]['tipo_divergencia'], 'ESTADIA_EXCEDIDA')

        # Caso 3: Cilindro volta fisicamente ao pátio mas a nota continua aberta (PENDENTE_RETORNO_FISCAL)
        self.cilindro_1.status = 'VAZIO_TRIAGEM'
        self.cilindro_1.cliente_posse_atual = None
        self.cilindro_1.save()

        divs3 = relatorio_divergencias_comodato(self.tenant, self.filial)
        self.assertEqual(len(divs3), 1)
        self.assertEqual(divs3[0]['tipo_divergencia'], 'PENDENTE_RETORNO_FISCAL')


class TestFaturaLocacaoTributaria(BaseFiscalGasesTestCase):
    """Testes de conformidade tributária na Fatura de Locação (Task 4 - STF SV 31)."""

    def test_fatura_locacao_nao_contem_icms_nem_iss(self):
        itens = [
            {
                'descricao': 'Locação 5 Cilindros Oxigênio 50L (Competência 10/2026)',
                'quantidade': 5,
                'dias': 30,
                'valor_diaria': Decimal('2.00')
            }
        ]
        fatura = gerar_fatura_locacao(
            tenant=self.tenant,
            filial=self.filial,
            cliente=self.cliente,
            periodo_inicio=date(2026, 10, 1),
            periodo_fim=date(2026, 10, 31),
            itens_locacao=itens,
            numero_contrato="CTR-LOC-2026"
        )
        self.assertEqual(fatura.modelo, 'FATURA_LOCACAO')
        self.assertEqual(fatura.status, 'AUTORIZADO')
        self.assertEqual(fatura.valor_total, Decimal('300.00'))  # 5 * 2.00 * 30 = 300.00

        item = fatura.itens.first()
        tributos = {t.tributo: t for t in item.tributos.all()}

        # Súmula Vinculante 31: ICMS e ISS = 0
        self.assertEqual(tributos['ICMS'].valor, Decimal('0.00'))
        self.assertEqual(tributos['ICMS'].aliquota, Decimal('0.0000'))
        self.assertEqual(tributos['ISS'].valor, Decimal('0.00'))
        self.assertEqual(tributos['ISS'].aliquota, Decimal('0.0000'))

        # Simples Nacional: PIS e COFINS = 0
        self.assertEqual(tributos['PIS'].valor, Decimal('0.00'))
        self.assertEqual(tributos['COFINS'].valor, Decimal('0.00'))

    def test_fatura_locacao_regime_normal_calcula_pis_cofins(self):
        self.config_fiscal.regime_tributario = 'REGIME_NORMAL'
        self.config_fiscal.save()

        itens = [
            {'descricao': 'Diárias de Estadia', 'quantidade': 1, 'dias': 10, 'valor_diaria': Decimal('100.00')}
        ]
        fatura = gerar_fatura_locacao(
            tenant=self.tenant,
            filial=self.filial,
            cliente=self.cliente,
            periodo_inicio=date(2026, 10, 1),
            periodo_fim=date(2026, 10, 10),
            itens_locacao=itens
        )
        item = fatura.itens.first()
        tributos = {t.tributo: t for t in item.tributos.all()}

        # PIS (0.65% sobre 1000.00 = 6.50) e COFINS (3.00% sobre 1000.00 = 30.00)
        self.assertEqual(tributos['PIS'].valor, Decimal('6.50'))
        self.assertEqual(tributos['COFINS'].valor, Decimal('30.00'))

        # Confere se título financeiro a receber foi gerado
        titulo = TituloFinanceiro.objects.filter(origem_id=str(fatura.id)).first()
        self.assertIsNotNone(titulo)
        self.assertEqual(titulo.valor_nominal, Decimal('1000.00'))


class TestRastroMedicinal(BaseFiscalGasesTestCase):
    """Testes de validação de gás medicinal, laudo de CQ e grupos <med> e <rastro> (Task 5)."""

    def setUp(self):
        super().setUp()
        self.sku_med = SkuRecarga.objects.create(
            tenant=self.tenant,
            gas=self.gas_o2,
            modelo_cilindro=self.modelo_t50,
            nome_comercial="Recarga O2 Medicinal 10m³",
            quantidade_carga=Decimal('10.00'),
            massa_gas_kg=Decimal('13.30'),
            preco_base=Decimal('200.00'),
            ncm='28044000',
            medicinal=True,
            registro_anvisa='1023456789012',
            exige_rastro=True
        )

        self.lote_aprovado = LoteEnvase.objects.create(
            tenant=self.tenant,
            gas=self.gas_o2,
            codigo_lote="LOTE-MED-2026-01",
            status_qualidade='APROVADO',
            data_envase=timezone.localdate() - timedelta(days=2),
            data_validade=timezone.localdate() + timedelta(days=730),
            pureza_percentual=Decimal('99.80'),
            responsavel_tecnico="Dra. Mariana Farmacêutica CRF-SP 12345"
        )

        self.lote_quarentena = LoteEnvase.objects.create(
            tenant=self.tenant,
            gas=self.gas_o2,
            codigo_lote="LOTE-MED-QUARENTENA",
            status_qualidade='QUARENTENA',
            data_envase=timezone.localdate(),
            data_validade=timezone.localdate() + timedelta(days=730),
            pureza_percentual=Decimal('99.50'),
            responsavel_tecnico="Dr. Carlos Químico"
        )

        # Regra aprovada
        self.regra_sp = RegraTributaria.objects.create(
            tenant=self.tenant,
            descricao="Venda Interna SP",
            vigencia_inicio=timezone.localdate() - timedelta(days=1),
            tipo_operacao='VENDA',
            ncm='28044000',
            cfop='5102',
            aprovada_por=self.user_admin,
            aprovada_em=timezone.now()
        )
        RegraTributariaTributo.objects.create(
            tenant=self.tenant,
            regra=self.regra_sp,
            tributo='ICMS',
            cst_csosn='102',
            aliquota=Decimal('0.0000')
        )

    def test_lote_sem_laudo_cq_liberado_bloqueia_emissao(self):
        venda = Venda.objects.create(
            tenant=self.tenant, filial=self.filial, cliente=self.cliente, valor_total=Decimal('200.00')
        )
        item = ItemVenda.objects.create(
            tenant=self.tenant, venda=venda, sku=self.sku_med, quantidade=1, valor_unitario=Decimal('200.00')
        )
        # Associa lote em quarentena
        item.lote_envase = self.lote_quarentena
        venda.itens_override = [item]

        with self.assertRaises(ValidationError) as ctx:
            montar_nfe(venda, self.config_fiscal, numero=1, serie=1)
        self.assertIn("não possui laudo de CQ liberado/aprovado", str(ctx.exception))

    def test_medicinal_bloqueia_sem_registro_anvisa(self):
        self.sku_med.registro_anvisa = ''
        self.sku_med.save()

        venda = Venda.objects.create(
            tenant=self.tenant, filial=self.filial, cliente=self.cliente, valor_total=Decimal('200.00')
        )
        item = ItemVenda.objects.create(
            tenant=self.tenant, venda=venda, sku=self.sku_med, quantidade=1, valor_unitario=Decimal('200.00')
        )
        item.lote_envase = self.lote_aprovado
        venda.itens_override = [item]

        with self.assertRaises(ValidationError) as ctx:
            montar_nfe(venda, self.config_fiscal, numero=1, serie=1)
        self.assertIn("Registro ANVISA", str(ctx.exception))

    def test_item_com_dois_lotes_gera_dois_grupos_rastro(self):
        lote_aprovado_2 = LoteEnvase.objects.create(
            tenant=self.tenant,
            gas=self.gas_o2,
            codigo_lote="LOTE-MED-2026-02",
            status_qualidade='APROVADO',
            data_envase=timezone.localdate() - timedelta(days=1),
            data_validade=timezone.localdate() + timedelta(days=730),
            responsavel_tecnico="Dra. Mariana Farmacêutica"
        )

        venda = Venda.objects.create(
            tenant=self.tenant, filial=self.filial, cliente=self.cliente, valor_total=Decimal('400.00')
        )
        item = ItemVenda.objects.create(
            tenant=self.tenant, venda=venda, sku=self.sku_med, quantidade=2, valor_unitario=Decimal('200.00')
        )
        # Injeta múltiplos lotes (fracionamento de lote)
        item.lotes_info = [
            {'lote': self.lote_aprovado, 'quantidade': Decimal('1.000')},
            {'lote': lote_aprovado_2, 'quantidade': Decimal('1.000')}
        ]
        venda.itens_override = [item]

        payload = montar_nfe(venda, self.config_fiscal, numero=1, serie=1)
        self.assertEqual(len(payload['itens']), 1)
        item_pl = payload['itens'][0]

        # Grupo <med>
        self.assertEqual(item_pl['grupo_med']['cProdANVISA'], '1023456789012')
        # Grupos <rastro>
        self.assertEqual(len(item_pl['grupos_rastro']), 2)
        self.assertEqual(item_pl['grupos_rastro'][0]['nLote'], 'LOTE-MED-2026-01')
        self.assertEqual(item_pl['grupos_rastro'][1]['nLote'], 'LOTE-MED-2026-02')

        # Pré-validação passa sem erros
        validar_pre_emissao(payload)


class TestTransporteCTeEMDFe(BaseFiscalGasesTestCase):
    """Testes de emissão restrita de CT-e (Correção F-27) e MDF-e de transporte (Tasks 7 e 8)."""

    def test_venda_cif_frota_propria_nao_gera_cte(self):
        # Tenant com presta_servico_transporte = False
        self.tenant.presta_servico_transporte = False
        self.tenant.save()

        with self.assertRaises(ValidationError) as ctx:
            emitir_cte_transporte(
                tenant=self.tenant,
                filial=self.filial,
                tomador_cliente=self.cliente,
                remetente=self.cliente,
                destinatario=self.cliente,
                valor_frete=Decimal('150.00')
            )
        self.assertIn("Correção F-27", str(ctx.exception))
        self.assertIn("presta_servico_transporte=False", str(ctx.exception))

    def test_transportadora_emite_cte_sucesso(self):
        self.tenant.presta_servico_transporte = True
        self.tenant.save()

        fake = FakeEmissor()
        cte_doc = emitir_cte_transporte(
            tenant=self.tenant,
            filial=self.filial,
            tomador_cliente=self.cliente,
            remetente=self.cliente,
            destinatario=self.cliente,
            valor_frete=Decimal('250.00'),
            emissor_port=fake
        )
        self.assertEqual(cte_doc.modelo, 'CTE_57')
        self.assertEqual(cte_doc.status, 'AUTORIZADO')
        self.assertTrue(cte_doc.chave_acesso.endswith('570010000000018') or len(cte_doc.chave_acesso) == 44)

    def test_mdfe_emissao_com_produtos_perigosos_e_encerramento(self):
        fake = FakeEmissor()
        rota = Rota.objects.create(tenant=self.tenant, nome="Rota Hospitais SP", origem="Matriz SP", destino="Grande SP")
        entrega = Entrega.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            rota=rota,
            veiculo=self.veiculo,
            status='Em Rota'
        )

        mdfe_doc = montar_e_emitir_mdfe(entrega, emissor_port=fake)
        self.assertEqual(mdfe_doc.modelo, 'MDFE_58')
        self.assertEqual(mdfe_doc.status, 'AUTORIZADO')

        # Encerramento do MDF-e na entrega
        evento = encerrar_mdfe_entrega(entrega, emissor_port=fake)
        self.assertIsNotNone(evento)
        self.assertEqual(evento.tipo_evento, 'ENCERRAMENTO')
        self.assertEqual(evento.status, 'AUTORIZADO')

    def test_mdfe_aberto_vencido_gera_alerta(self):
        doc = DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            modelo='MDFE_58',
            tipo_operacao='MDFE_CARGA',
            status='AUTORIZADO',
            numero=88,
            serie=1,
            data_autorizacao=timezone.now() - timedelta(hours=30),
            origem_id='88'
        )
        alertas = verificar_mdfes_abertos_alerta(self.tenant, self.filial, prazo_horas=24)
        self.assertTrue(any(a['documento_id'] == doc.id for a in alertas))


class TestImportacaoXMLCompra(BaseFiscalGasesTestCase):
    """Testes de importação de XML de compra com garantia de idempotência (Task 9)."""

    XML_NFE_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
    <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
        <NFe>
            <infNFe Id="NFe35261099887766000155550010000007891000000015">
                <ide>
                    <nNF>789</nNF>
                    <serie>1</serie>
                    <dhEmi>2026-10-15T10:00:00-03:00</dhEmi>
                </ide>
                <emit>
                    <CNPJ>99887766000155</CNPJ>
                    <xNome>Fabricante Global de Gases S.A.</xNome>
                </emit>
                <total>
                    <ICMSTot>
                        <vProd>10000.00</vProd>
                        <vFrete>500.00</vFrete>
                        <vICMS>1800.00</vICMS>
                        <vPIS>165.00</vPIS>
                        <vCOFINS>760.00</vCOFINS>
                        <vIPI>500.00</vIPI>
                        <vNF>10500.00</vNF>
                    </ICMSTot>
                </total>
                <det nItem="1">
                    <prod>
                        <cProd>O2-LIQ-01</cProd>
                        <xProd>Oxigênio Líquido Criogênico Medicinal Granel</xProd>
                        <NCM>28044000</NCM>
                        <CFOP>5101</CFOP>
                        <qCom>5000.000</qCom>
                        <vUnCom>2.00</vUnCom>
                        <vProd>10000.00</vProd>
                    </prod>
                </det>
            </infNFe>
        </NFe>
    </nfeProc>
    """

    def test_importacao_xml_sucesso_com_creditos_e_titulo_pagar(self):
        doc_ent, criado = importar_xml_nfe_compra(
            tenant=self.tenant,
            filial=self.filial,
            xml_content=self.XML_NFE_SAMPLE
        )
        self.assertTrue(criado)
        self.assertEqual(doc_ent.chave_acesso, '35261099887766000155550010000007891000000015')
        self.assertEqual(doc_ent.numero, 789)
        self.assertEqual(doc_ent.valor_total, Decimal('10500.00'))
        self.assertEqual(doc_ent.credito_icms, Decimal('1800.00'))
        self.assertEqual(doc_ent.credito_pis, Decimal('165.00'))
        self.assertEqual(doc_ent.credito_cofins, Decimal('760.00'))
        self.assertEqual(doc_ent.tipo_entrada, 'GAS_GRANEL')

        # Verifica se título financeiro a pagar foi gerado
        self.assertIsNotNone(doc_ent.titulo_pagar)
        self.assertEqual(doc_ent.titulo_pagar.valor_nominal, Decimal('10500.00'))
        self.assertEqual(doc_ent.titulo_pagar.tipo, 'PAGAR')

    def test_importacao_duplicada_pela_mesma_chave_nao_duplica_nem_cria_novo_titulo(self):
        # 1ª Importação
        doc1, criado1 = importar_xml_nfe_compra(self.tenant, self.filial, self.XML_NFE_SAMPLE)
        self.assertTrue(criado1)

        titulos_antes = TituloFinanceiro.objects.filter(tenant=self.tenant, tipo='PAGAR').count()

        # 2ª Importação com o mesmo XML (clique duplo ou reenvio)
        doc2, criado2 = importar_xml_nfe_compra(self.tenant, self.filial, self.XML_NFE_SAMPLE)
        self.assertFalse(criado2)
        self.assertEqual(doc1.id, doc2.id)

        titulos_depois = TituloFinanceiro.objects.filter(tenant=self.tenant, tipo='PAGAR').count()
        self.assertEqual(titulos_antes, titulos_depois)  # Prova que não duplicou título

    def test_importacao_xml_invalido_e_ncm_cilindros_cascos(self):
        # XML inválido sem chave/infNFe
        with self.assertRaises(ValidationError) as ctx:
            importar_xml_nfe_compra(self.tenant, self.filial, "<invalido>teste</invalido>")
        self.assertIn("infNFe> não localizado", str(ctx.exception))

        # XML de cilindros cascos (NCM 73110000)
        xml_cilindros = """<?xml version="1.0" encoding="UTF-8"?>
        <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
            <NFe>
                <infNFe Id="NFe35261099887766000155550010000009991000000099">
                    <ide><nNF>999</nNF><serie>1</serie><dhEmi>2026-10-18T10:00:00-03:00</dhEmi></ide>
                    <emit><CNPJ>99887766000155</CNPJ><xNome>Cilindros Brasil S.A.</xNome></emit>
                    <total><ICMSTot><vProd>5000.00</vProd><vNF>5000.00</vNF><vICMS>900.00</vICMS><vPIS>82.50</vPIS><vCOFINS>380.00</vCOFINS><vIPI>250.00</vIPI></ICMSTot></total>
                    <det nItem="1">
                        <prod><cProd>CIL-50L</cProd><xProd>Cilindro Aço 50L Vazio</xProd><NCM>73110000</NCM><CFOP>5101</CFOP><qCom>10.000</qCom><vUnCom>500.00</vUnCom><vProd>5000.00</vProd></prod>
                    </det>
                </infNFe>
            </NFe>
        </nfeProc>"""
        doc, criado = importar_xml_nfe_compra(self.tenant, self.filial, xml_cilindros)
        self.assertTrue(criado)
        self.assertEqual(doc.tipo_entrada, 'CILINDROS_CASCOS')
        self.assertEqual(doc.credito_ipi, Decimal('250.00'))


class TestApuracaoGerencialImposto(BaseFiscalGasesTestCase):
    """Testes de apuração gerencial de impostos e geração de guia (Task 10)."""

    def test_apuracao_calcula_debitos_creditos_e_saldo_anterior(self):
        # 1. Cria saída com ICMS debitado
        doc_saida = DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            modelo='NFE_55',
            tipo_operacao='VENDA',
            status='AUTORIZADO',
            numero=100,
            serie=1,
            origem_id='100',
            valor_total=Decimal('1000.00')
        )
        item_s = DocumentoFiscalItem.objects.create(
            tenant=self.tenant,
            documento=doc_saida,
            numero_item=1,
            descricao="Carga O2",
            ncm='28044000',
            cfop='5102',
            quantidade=Decimal('1'),
            valor_unitario=Decimal('1000.00'),
            valor_total=Decimal('1000.00')
        )
        ItemDocumentoTributo.objects.create(
            tenant=self.tenant,
            item=item_s,
            tributo='ICMS',
            base=Decimal('1000.00'),
            aliquota=Decimal('0.1800'),
            valor=Decimal('180.00'),  # Débito de 180.00
            cst='00'
        )

        # 2. Cria entrada com ICMS creditado (100.00)
        DocumentoFiscalEntrada.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            chave_acesso='35261011111111111111550010000000011000000010',
            numero=1,
            data_emissao=date(2026, 10, 5),
            fornecedor_nome="Fornecedor Teste",
            fornecedor_cnpj="99887766000155",
            valor_total=Decimal('1000.00'),
            credito_icms=Decimal('100.00'),
            status='IMPORTADO'
        )

        apuracao = calcular_apuracao_imposto(self.tenant, self.filial, periodo='2026-10', tributo='ICMS')
        self.assertEqual(apuracao.debitos, Decimal('180.00'))
        self.assertEqual(apuracao.creditos, Decimal('100.00'))
        self.assertEqual(apuracao.saldo_apurado, Decimal('80.00'))  # 180 - 100 = 80 a recolher

        # 3. Fecha apuração gerando guia a pagar
        fechada = fechar_apuracao_e_gerar_guia(apuracao, data_vencimento=date(2026, 11, 20), usuario=self.user_admin)
        self.assertEqual(fechada.status, 'GUIA_GERADA')
        self.assertIsNotNone(fechada.titulo_pagar)
        self.assertEqual(fechada.titulo_pagar.valor_nominal, Decimal('80.00'))

        # Fechar novamente é idempotente
        fechada_2 = fechar_apuracao_e_gerar_guia(fechada, data_vencimento=date(2026, 11, 20), usuario=self.user_admin)
        self.assertEqual(fechada_2.id, fechada.id)

    def test_apuracao_validacao_periodo_e_saldo_credor_anterior(self):
        # Validação de período inválido
        with self.assertRaises(ValidationError):
            calcular_apuracao_imposto(self.tenant, self.filial, periodo='202610', tributo='ICMS')

        # Cria apuração com saldo credor no mês anterior (2026-09)
        ApuracaoImposto.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            periodo='2026-09',
            tributo='ICMS',
            debitos=Decimal('50.00'),
            creditos=Decimal('150.00'),
            saldo_apurado=Decimal('-100.00'),  # Saldo credor de 100.00 a transportar
            status='FECHADO'
        )

        # Apuração de 2026-10 com débito de 120 e crédito de 0
        doc_saida = DocumentoFiscal.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            modelo='NFE_55',
            tipo_operacao='VENDA',
            status='AUTORIZADO',
            numero=105,
            serie=1,
            origem_id='105',
            valor_total=Decimal('1000.00')
        )
        item_s = DocumentoFiscalItem.objects.create(
            tenant=self.tenant,
            documento=doc_saida,
            numero_item=1,
            descricao="Carga O2",
            ncm='28044000',
            cfop='5102',
            quantidade=Decimal('1'),
            valor_unitario=Decimal('1000.00'),
            valor_total=Decimal('1000.00')
        )
        ItemDocumentoTributo.objects.create(
            tenant=self.tenant,
            item=item_s,
            tributo='ICMS',
            base=Decimal('1000.00'),
            aliquota=Decimal('0.1200'),
            valor=Decimal('120.00'),
            cst='00'
        )

        apuracao_out = calcular_apuracao_imposto(self.tenant, self.filial, periodo='2026-10', tributo='ICMS')
        self.assertEqual(apuracao_out.saldo_credor_anterior, Decimal('100.00'))
        # 120 (débito) - 0 (crédito) - 100 (saldo credor ant) = 20 a recolher
        self.assertEqual(apuracao_out.saldo_apurado, Decimal('20.00'))

    def test_apuracao_pis_cofins_e_ipi(self):
        DocumentoFiscalEntrada.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            chave_acesso='35261011111111111111550010000000099000000099',
            numero=99,
            data_emissao=date(2026, 10, 5),
            fornecedor_nome="Fornecedor Insumos",
            fornecedor_cnpj="99887766000155",
            valor_total=Decimal('1000.00'),
            credito_pis=Decimal('16.50'),
            credito_cofins=Decimal('76.00'),
            credito_ipi=Decimal('50.00'),
            status='IMPORTADO'
        )
        ap_pis = calcular_apuracao_imposto(self.tenant, self.filial, periodo='2026-10', tributo='PIS')
        self.assertEqual(ap_pis.creditos, Decimal('16.50'))
        ap_cof = calcular_apuracao_imposto(self.tenant, self.filial, periodo='2026-10', tributo='COFINS')
        self.assertEqual(ap_cof.creditos, Decimal('76.00'))
        ap_ipi = calcular_apuracao_imposto(self.tenant, self.filial, periodo='2026-10', tributo='IPI')
        self.assertEqual(ap_ipi.creditos, Decimal('50.00'))


class TestRecargaTerceiros(BaseFiscalGasesTestCase):
    """Testes de ciclo de ordem de recarga para terceiros (Task 11)."""

    def test_ciclo_ordem_recarga_e_faturamento(self):
        fake = FakeEmissor()
        itens = [
            {
                'numero_serie_cilindro': 'CLIENTE-CIL-99',
                'gas': self.gas_o2,
                'volume_m3': Decimal('10.000'),
                'valor_servico': Decimal('150.00')
            }
        ]
        ordem = criar_ordem_recarga(
            tenant=self.tenant,
            filial=self.filial,
            cliente=self.cliente,
            numero_ordem="ORD-2026-001",
            itens_recarga=itens
        )
        self.assertEqual(ordem.status, 'RECEBIDO')
        self.assertEqual(ordem.custo_servico, Decimal('150.00'))

        # Transição de status
        avancar_status_ordem(ordem, 'EM_ENVASE')
        self.assertEqual(ordem.status, 'EM_ENVASE')
        avancar_status_ordem(ordem, 'ENVASADO')
        self.assertEqual(ordem.status, 'ENVASADO')

        # Faturamento com NF-e CFOP 5.124
        doc = faturar_ordem_recarga(ordem, emissor_port=fake)
        self.assertEqual(doc.tipo_operacao, 'RECARGA_TERCEIRO')
        self.assertEqual(doc.status, 'AUTORIZADO')
        self.assertEqual(doc.valor_total, Decimal('150.00'))
        self.assertEqual(ordem.status, 'FATURADO')
        self.assertEqual(ordem.documento_saida, doc)


class TestSeedsETributacaoGases(BaseFiscalGasesTestCase):
    """Testes de seeds da matriz tributária e governança (Task 1 / F-25)."""

    def test_seed_regras_tributarias_gases_entram_nao_aprovadas(self):
        # Executa seed de exemplos para UF SP
        regras_sp = seed_regras_tributarias_gases(self.tenant, uf='SP')
        self.assertGreaterEqual(len(regras_sp), 5)

        # Regras de exemplo entram NÃO aprovadas (exigem contador em produção)
        for regra in regras_sp:
            self.assertIsNone(regra.aprovada_por)
            self.assertEqual(regra.uf_origem, 'SP')

        # Idempotência do seed: executar novamente não duplica
        regras_sp_2 = seed_regras_tributarias_gases(self.tenant, uf='SP')
        self.assertEqual(len(regras_sp), len(regras_sp_2))


class TestMultiTenancySprint11B(BaseFiscalGasesTestCase):
    """Testes de isolamento multi-tenant dos novos recursos e endpoints (Global Rule 3)."""

    def setUp(self):
        super().setUp()
        self.tenant_b = Tenant.objects.create(
            razao_social="Beta Gases Eireli",
            nome_fantasia="Beta",
            cnpj="98765432000198",
            status_assinatura='ATIVO',
            modulo_fiscal_ativo=True
        )
        self.user_b = User.objects.create_user(
            username='user_beta_11b',
            email='beta@beta.com',
            password='Password123!'
        )
        Membership.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            papel='ADMIN',
            ativo=True
        )

        # Recurso do Tenant A
        self.mov_comodato_a = MovimentoComodatoFiscal.objects.create(
            tenant=self.tenant,
            cilindro=self.cilindro_1,
            cliente=self.cliente,
            filial=self.filial,
            tipo='REMESSA',
            valor_bem=Decimal('500.00')
        )
        self.cfg_mdfe_a = ConfiguracaoMDFe.objects.create(
            tenant=self.tenant,
            filial=self.filial,
            uf='SP'
        )

    def test_endpoints_retornam_404_para_outro_tenant(self):
        client = APIClient()
        client.force_authenticate(user=self.user_b)

        # Tentativa de acessar movimento comodato do Tenant A
        resp1 = client.get(f"/api/fiscal/movimentos-comodato/{self.mov_comodato_a.id}/")
        self.assertEqual(resp1.status_code, status.HTTP_404_NOT_FOUND)

        # Tentativa de acessar configuracao mdfe do Tenant A
        resp2 = client.get(f"/api/fiscal/configuracoes-mdfe/{self.cfg_mdfe_a.id}/")
        self.assertEqual(resp2.status_code, status.HTTP_404_NOT_FOUND)
