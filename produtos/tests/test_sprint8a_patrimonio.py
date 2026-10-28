import datetime
from decimal import Decimal
import os

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from hypothesis import given, strategies as st, settings, HealthCheck
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Filial, Membership, Tenant
from core.money import quantize
from core.services.cotas import CotaExcedida, checar_cota
from core.tenancy import reset_current_tenant, set_current_tenant, tenant_context
from core.validators import validar_chave_nfe
from produtos.depreciacao import (
    depreciacao_acumulada,
    meses_depreciados,
    quota_mensal,
    valor_contabil_liquido,
)
from produtos.models import (
    AtivoImobilizado,
    Cilindro,
    ClasseAtivo,
    FabricanteCilindro,
    GasQuimico,
    LoteAquisicaoCilindros,
    ModeloCilindro,
    TabelaIndenizacaoCilindro,
)
from produtos.services.indenizacao import calcular_indenizacao

User = get_user_model()

CHAVE_NFE_VALIDA = '35261011222333000144550010000000011123456783'


class TestDepreciacaoFuncoesPuras(TestCase):
    """
    Testes das funções puras de depreciação linear (Sprint 8A - Tarefa 8).
    """

    def test_quota_mensal_calculo_correto(self):
        # Aquisição R$ 1.000, residual R$ 100, vida 60 meses -> base 900 / 60 = 15.00
        quota = quota_mensal(Decimal('1000.00'), Decimal('100.00'), 60)
        self.assertEqual(quota, Decimal('15.00'))

    def test_quota_mensal_zero_se_residual_maior_ou_vida_invalida(self):
        self.assertEqual(quota_mensal(Decimal('500.00'), Decimal('600.00'), 60), Decimal('0.00'))
        self.assertEqual(quota_mensal(Decimal('500.00'), Decimal('100.00'), 0), Decimal('0.00'))

    def test_meses_depreciados_inicia_mes_seguinte(self):
        inicio = datetime.date(2024, 1, 15)
        # Mesmo mês: 0
        self.assertEqual(meses_depreciados(inicio, datetime.date(2024, 1, 31)), 0)
        # Mês seguinte: 1
        self.assertEqual(meses_depreciados(inicio, datetime.date(2024, 2, 10)), 1)
        # 1 ano depois: 12
        self.assertEqual(meses_depreciados(inicio, datetime.date(2025, 1, 15)), 12)

    def test_valor_contabil_liquido_atinge_residual_e_nao_ultrapassa(self):
        valor = Decimal('1200.00')
        residual = Decimal('200.00')
        vida = 10  # 10 meses
        inicio = datetime.date(2024, 1, 1)

        # Após 5 meses: depreciou 5 * 100 = 500 -> VCL = 700.00
        vcl_5 = valor_contabil_liquido(valor, residual, vida, inicio, datetime.date(2024, 6, 1))
        self.assertEqual(vcl_5, Decimal('700.00'))

        # Após 10 meses: depreciou tudo -> VCL = residual = 200.00
        vcl_10 = valor_contabil_liquido(valor, residual, vida, inicio, datetime.date(2024, 11, 1))
        self.assertEqual(vcl_10, Decimal('200.00'))

        # Após 24 meses: VCL continua exatamente no residual (nunca abaixo)
        vcl_24 = valor_contabil_liquido(valor, residual, vida, inicio, datetime.date(2026, 1, 1))
        self.assertEqual(vcl_24, Decimal('200.00'))


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    valor=st.decimals(min_value=Decimal('100.00'), max_value=Decimal('100000.00'), places=2),
    pct_res=st.decimals(min_value=Decimal('0.01'), max_value=Decimal('0.50'), places=2),
    vida=st.integers(min_value=1, max_value=360),
    meses_passados=st.integers(min_value=0, max_value=500),
)
def test_invariante_vcl_nunca_abaixo_residual_hypothesis(valor, pct_res, vida, meses_passados):
    """Teste de propriedade (Hypothesis): VCL >= residual sob quaisquer parâmetros."""
    residual = quantize(valor * pct_res, 2)
    inicio = datetime.date(2020, 1, 1)
    ano_ref = 2020 + (meses_passados // 12)
    mes_ref = 1 + (meses_passados % 12)
    data_ref = datetime.date(ano_ref, mes_ref, 1)

    vcl = valor_contabil_liquido(valor, residual, vida, inicio, data_ref)
    assert vcl >= residual
    assert vcl <= valor


class TestCamposTecnicosEValidadorNFe(TestCase):
    """
    Testes dos campos técnicos do Cilindro e do Validador de NF-e (Sprint 8A - Tarefas 2 e 4).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44', razao_social='Gás Seguro Ltda', nome_fantasia='Gás Seguro'
        )
        set_current_tenant(self.tenant)
        self.gas = GasQuimico.objects.create(nome='Oxigênio Industrial', sigla='O2', categoria='INDUSTRIAL')
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant, descricao='O2-50L', volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200, tara_nominal_kg=Decimal('45.00')
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_chave_nfe_valida_passa_validador(self):
        self.assertEqual(validar_chave_nfe(CHAVE_NFE_VALIDA), CHAVE_NFE_VALIDA)

    def test_chave_nfe_com_tamanho_invalido_rejeitada(self):
        with self.assertRaises(ValidationError) as ctx:
            validar_chave_nfe('123456789')
        self.assertIn('44 dígitos', str(ctx.exception))

    def test_chave_nfe_com_dv_incorreto_rejeitada(self):
        # Altera o último dígito de '3' para '9'
        chave_adulterada = CHAVE_NFE_VALIDA[:-1] + '9'
        with self.assertRaises(ValidationError) as ctx:
            validar_chave_nfe(chave_adulterada)
        self.assertIn('dígito verificador incorreto', str(ctx.exception))

    def test_pressao_teste_menor_que_servico_gera_validation_error(self):
        cilindro = Cilindro(
            tenant=self.tenant,
            codigo_qr='QR-PRESSAO-01',
            numero_serie_ogiva='SERIE-P01',
            fabricante='MAT',
            ano_fabricacao=2024,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            pressao_servico_bar=200,
            pressao_teste_bar=150,  # 150 < 200 -> Inválido!
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
            propriedade='CLIENTE'  # evita disparo de cota no clean
        )
        with self.assertRaises(ValidationError) as ctx:
            cilindro.clean()
        self.assertIn('pressao_teste_bar', ctx.exception.message_dict)

    def test_pressao_teste_maior_ou_igual_servico_valido(self):
        cilindro = Cilindro(
            tenant=self.tenant,
            codigo_qr='QR-PRESSAO-02',
            numero_serie_ogiva='SERIE-P02',
            fabricante='MAT',
            ano_fabricacao=2024,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            pressao_servico_bar=200,
            pressao_teste_bar=300,  # 300 >= 200 -> Válido!
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
            propriedade='CLIENTE'
        )
        cilindro.clean()  # não deve levantar erro


class TestPropriedadeCilindroECotas(TestCase):
    """
    Testes de propriedade, isenção de cota para CLIENTE e cálculo CAPEX (Sprint 8A - Tarefa 7).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='22.333.444/0001-55', razao_social='Distribuidora Beta SA',
            nome_fantasia='Beta Gás', limite_cilindros=3
        )
        set_current_tenant(self.tenant)
        self.gas = GasQuimico.objects.create(nome='Nitrogênio', sigla='N2', categoria='INDUSTRIAL')
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant, descricao='N2-50L', volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200, tara_nominal_kg=Decimal('48.00')
        )
        self.classe = ClasseAtivo.objects.create(
            tenant=self.tenant, codigo='CIL-PADRAO', nome='Cilindros Padrão',
            tipo='CILINDRO', vida_util_meses_padrao=60, percentual_residual_padrao=Decimal('0.1000')
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_cilindro_cliente_nao_consome_cota(self):
        """Cilindros de propriedade do cliente não contam na cota contratual de limite_cilindros."""
        # Cria 3 cilindros CLIENTE (limite é 3)
        for i in range(3):
            Cilindro.objects.create(
                tenant=self.tenant,
                codigo_qr=f"QR-CLI-{i}",
                numero_serie_ogiva=f"SERIE-CLI-{i}",
                fabricante='MAT',
                ano_fabricacao=2024,
                modelo=self.modelo,
                gas_dedicado=self.gas,
                propriedade='CLIENTE',
                data_ultimo_reteste=timezone.localdate(),
                data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
                status='CHEIO_DISPONIVEL'
            )

        # Uso da cota para cilindros próprios continua 0!
        res_cota = checar_cota(self.tenant, 'cilindros', incremento=1)
        self.assertEqual(res_cota['uso_atual'], 0)
        self.assertEqual(res_cota['novo_total'], 1)

    def test_cilindro_proprio_consome_cota_e_bloqueia_no_limite(self):
        """Cilindros próprios consomem a cota contratual."""
        for i in range(3):
            Cilindro.objects.create(
                tenant=self.tenant,
                codigo_qr=f"QR-PROP-{i}",
                numero_serie_ogiva=f"SERIE-PROP-{i}",
                fabricante='MAT',
                ano_fabricacao=2024,
                modelo=self.modelo,
                gas_dedicado=self.gas,
                propriedade='PROPRIO',
                data_ultimo_reteste=timezone.localdate(),
                data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
                status='CHEIO_DISPONIVEL'
            )

        # 4º cilindro próprio deve ser barrado com CotaExcedida
        with self.assertRaises(CotaExcedida):
            checar_cota(self.tenant, 'cilindros', incremento=1)

    def test_cilindro_proprio_deprecia_e_cliente_nao_deprecia(self):
        """Apenas cilindros PROPRIO calculam depreciação gerencial."""
        hoje = timezone.localdate()
        cilindro_proprio = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-PROP-DEP',
            numero_serie_ogiva='SERIE-DEP-01',
            fabricante='MAT',
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            propriedade='PROPRIO',
            valor_aquisicao=Decimal('1200.00'),
            valor_residual=Decimal('200.00'),
            vida_util_meses=50,
            data_aquisicao=hoje - datetime.timedelta(days=90),
            data_inicio_depreciacao=hoje - datetime.timedelta(days=90),
            data_ultimo_reteste=hoje,
            data_proximo_reteste=hoje + datetime.timedelta(days=1800),
        )

        # Quota mensal: (1200 - 200) / 50 = 20.00
        self.assertEqual(cilindro_proprio.depreciacao_mensal_rs, Decimal('20.00'))
        self.assertTrue(cilindro_proprio.valor_contabil_liquido_atual < Decimal('1200.00'))

        # Cilindro CLIENTE: depreciação é sempre 0.00
        cilindro_cliente = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-CLI-DEP',
            numero_serie_ogiva='SERIE-DEP-02',
            fabricante='MAT',
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            propriedade='CLIENTE',
            valor_aquisicao=Decimal('1200.00'),
            vida_util_meses=50,
            data_ultimo_reteste=hoje,
            data_proximo_reteste=hoje + datetime.timedelta(days=1800),
        )
        self.assertEqual(cilindro_cliente.depreciacao_mensal_rs, Decimal('0.00'))
        self.assertEqual(cilindro_cliente.valor_contabil_liquido_atual, Decimal('0.00'))


class TestIndenizacaoEServicos(TestCase):
    """
    Testes do serviço de cálculo de indenização patrimonial (Sprint 8A - Tarefa 9).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='33.444.555/0001-66', razao_social='Usina Gamma Ltda', nome_fantasia='Gamma Gás'
        )
        set_current_tenant(self.tenant)
        self.gas = GasQuimico.objects.create(nome='Argônio', sigla='Ar', categoria='INDUSTRIAL')
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant, descricao='AR-50L', volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200, tara_nominal_kg=Decimal('45.00')
        )
        self.cilindro = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-IND-01',
            numero_serie_ogiva='SERIE-IND-01',
            fabricante='MAT',
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            propriedade='PROPRIO',
            valor_aquisicao=Decimal('1500.00'),
            valor_residual=Decimal('300.00'),
            vida_util_meses=60,
            data_aquisicao=timezone.localdate() - datetime.timedelta(days=180),
            data_inicio_depreciacao=timezone.localdate() - datetime.timedelta(days=180),
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_calcular_indenizacao_com_tabela_contratual(self):
        # Cadastra tabela contratual vigente de R$ 2.000,00
        tabela = TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant,
            tipo_cilindro=self.modelo,
            gas=self.gas,
            valor=Decimal('2000.00'),
            vigencia_inicio=timezone.localdate() - datetime.timedelta(days=30)
        )

        res = calcular_indenizacao(self.cilindro)
        self.assertEqual(res['origem'], 'TABELA_CONTRATUAL')
        self.assertFalse(res['sinalizado_fallback'])
        self.assertEqual(res['valor_contratual'], Decimal('2000.00'))
        self.assertEqual(res['tabela_indenizacao_id'], str(tabela.id))
        # Ganho = 2000 - VCL
        self.assertEqual(res['ganho_perda'], quantize(Decimal('2000.00') - res['valor_contabil_liquido'], 2))

    def test_calcular_indenizacao_fallback_contabil_sinalizado(self):
        # Sem tabela cadastrada -> fallback para o valor contábil líquido, com flag sinalizado_fallback=True
        res = calcular_indenizacao(self.cilindro)
        self.assertEqual(res['origem'], 'VALOR_CONTABIL_FALLBACK')
        self.assertTrue(res['sinalizado_fallback'])
        self.assertEqual(res['valor_contratual'], res['valor_contabil_liquido'])
        self.assertEqual(res['ganho_perda'], Decimal('0.00'))


class TestIsolamentoTenantEndpointsPatrimonio(TestCase):
    """
    Testes de isolamento Multi-Tenant em todos os novos endpoints de patrimônio (Sprint 8A - Tarefa 11 e Regra 3).
    """

    def setUp(self):
        self.tenant_a = Tenant.objects.create(
            cnpj='44.555.666/0001-77', razao_social='Tenant A Ltda', nome_fantasia='A Gás', modulo_patrimonio_ativo=True
        )
        self.tenant_b = Tenant.objects.create(
            cnpj='55.666.777/0001-88', razao_social='Tenant B Ltda', nome_fantasia='B Gás', modulo_patrimonio_ativo=True
        )

        self.user_a = User.objects.create_user(username='user_a', password='password123', email='a@tenant.com')
        Membership.objects.create(user=self.user_a, tenant=self.tenant_a, papel='ADMIN', ativo=True)

        set_current_tenant(self.tenant_b)
        self.classe_b = ClasseAtivo.objects.create(
            tenant=self.tenant_b, codigo='CLS-B', nome='Classe B', tipo='CILINDRO'
        )
        self.fabricante_b = FabricanteCilindro.objects.create(
            tenant=self.tenant_b, nome='FABRICANTE-B'
        )
        self.ativo_b = AtivoImobilizado.objects.create(
            tenant=self.tenant_b, classe=self.classe_b, numero_patrimonio='PAT-B-001',
            descricao='Empilhadeira B', data_aquisicao=timezone.localdate(),
            valor_aquisicao=Decimal('85000.00'), vida_util_meses=120
        )
        self.lote_b = LoteAquisicaoCilindros.objects.create(
            tenant=self.tenant_b, classe=self.classe_b, fornecedor_nome='Fornecedor B',
            data_aquisicao=timezone.localdate(), quantidade=50, valor_total=Decimal('50000.00'),
            valor_unitario=Decimal('1000.00')
        )
        reset_current_tenant()

        self.client = APIClient()

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_recursos_tenant_b_retornam_404_para_usuario_tenant_a(self):
        """Usuário do Tenant A não tem visibilidade nem acesso aos recursos de patrimônio do Tenant B."""
        set_current_tenant(self.tenant_a)
        self.client.force_login(self.user_a)

        # 1. Classe de Ativo
        res_classe = self.client.get(f'/produtos/api/patrimonio/classes/{self.classe_b.id}/')
        self.assertEqual(res_classe.status_code, status.HTTP_404_NOT_FOUND)

        # 2. Fabricante de Cilindro
        res_fab = self.client.get(f'/produtos/api/patrimonio/fabricantes/{self.fabricante_b.id}/')
        self.assertEqual(res_fab.status_code, status.HTTP_404_NOT_FOUND)

        # 3. Ativo Imobilizado
        res_ativo = self.client.get(f'/produtos/api/patrimonio/ativos/{self.ativo_b.id}/')
        self.assertEqual(res_ativo.status_code, status.HTTP_404_NOT_FOUND)

        # 4. Lote de Aquisição
        res_lote = self.client.get(f'/produtos/api/patrimonio/lotes/{self.lote_b.id}/')
        self.assertEqual(res_lote.status_code, status.HTTP_404_NOT_FOUND)


class TestHerancaLoteEClasseNoCilindro(TestCase):
    """
    Testes de herança de lote de aquisição, classe e sincronização de fabricante legado (Sprint 8A - Tarefas 1, 5 e 6).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='66.777.888/0001-99', razao_social='Delta Usina SA', nome_fantasia='Delta'
        )
        set_current_tenant(self.tenant)
        self.gas = GasQuimico.objects.create(nome='Acetileno', sigla='AC', categoria='INDUSTRIAL')
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant, descricao='AC-40L', volume_hidraulico_litros=Decimal('40.00'),
            pressao_servico_bar=25, tara_nominal_kg=Decimal('60.00')
        )
        self.classe = ClasseAtivo.objects.create(
            tenant=self.tenant, codigo='ACETILENO-PADRAO', nome='Cilindros de Acetileno',
            tipo='CILINDRO', vida_util_meses_padrao=180, percentual_residual_padrao=Decimal('0.1500')
        )
        self.fabricante = FabricanteCilindro.objects.create(
            tenant=self.tenant, nome='CILBRAS', pais_origem='BR'
        )
        self.lote = LoteAquisicaoCilindros.objects.create(
            tenant=self.tenant, classe=self.classe, fornecedor_nome='Cilbras Equipamentos Ltda',
            data_aquisicao=datetime.date(2024, 3, 1), quantidade=10, valor_total=Decimal('15000.00'),
            valor_unitario=Decimal('1500.00'), chave_nfe=CHAVE_NFE_VALIDA
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_cilindro_herda_lote_classe_e_sincroniza_fabricante(self):
        """Cilindro herda valor unitário do lote, classe, vida útil e residual automaticamente."""
        cilindro = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-HERANCA-01',
            numero_serie_ogiva='SERIE-HER-01',
            fabricante='TEMP',  # será sobrescrito pelo fabricante_catalogo
            fabricante_catalogo=self.fabricante,
            ano_fabricacao=2024,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            lote_aquisicao=self.lote,
            propriedade='PROPRIO',
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
        )

        # 1. Fabricante legado sincronizado
        self.assertEqual(cilindro.fabricante, 'CILBRAS')

        # 2. Herança de valores do lote
        self.assertEqual(cilindro.valor_aquisicao, Decimal('1500.00'))
        self.assertEqual(cilindro.data_aquisicao, datetime.date(2024, 3, 1))
        self.assertEqual(cilindro.classe_ativo, self.classe)
        self.assertEqual(cilindro.fornecedor_aquisicao, 'Cilbras Equipamentos Ltda')
        self.assertEqual(cilindro.chave_nfe_aquisicao, CHAVE_NFE_VALIDA)

        # 3. Herança da classe de ativo
        self.assertEqual(cilindro.vida_util_meses, 180)
        # Residual: 15% de 1500 = 225.00
        self.assertEqual(cilindro.valor_residual, Decimal('225.00'))
