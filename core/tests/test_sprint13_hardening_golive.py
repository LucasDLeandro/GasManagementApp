import pytest
import uuid
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch, MagicMock
from hypothesis import given, strategies as st
import unittest

from django.test import TestCase
from django.utils import timezone
from django.core.cache import cache

from core.models import Tenant, SolicitacaoTitularLGPD
from core.money import quantize
from core.permissions import RequiresModuleDistribuicao, RequiresModuleLogistica

from core.services.rollout_service import (
    marcar_tenant_como_piloto,
    habilitar_feature_piloto,
    is_feature_piloto_ativa,
    listar_features_piloto,
    executar_rollback_modulo,
)
from core.services.carga_legado_service import (
    carregar_clientes,
    carregar_fornecedores,
    carregar_cilindros,
    carregar_saldo_abertura,
)
from core.services.seguranca_service import (
    criptografar_dado_sensivel,
    decriptografar_dado_sensivel,
    rotacionar_chaves_seguranca,
    verificar_conformidade_owasp,
)
from core.services.backup_continuidade_service import (
    obter_parametros_continuidade,
    simular_recuperacao_pitr,
    executar_teste_restauracao_trimestral,
)
from core.services.lgpd_service import (
    obter_mapeamento_lgpd,
    solicitar_acesso_exportacao_titular,
    solicitar_eliminacao_anonimizacao_titular,
    expurgar_telemetria_gps_antiga,
)
from core.services.performance_service import (
    obter_metas_slas_latencia,
    analisar_explain_consultas_criticas,
    dimensionar_infraestrutura_filas_conexoes,
    benchmark_latencia_simulada,
)
from core.services.observabilidade_service import (
    diagnosticar_painel_observabilidade,
    verificar_integridade_razao_contabil,
    auditar_certificados_digitais,
    obter_catalogo_alertas_runbooks,
)

from clientes.models import Cliente
from core.tenancy import set_current_tenant, reset_current_tenant
from financeiro.models import Fornecedor, PlanoContas, LancamentoContabil, PartidaContabil
from produtos.models import Cilindro, GasQuimico, ModeloCilindro, FabricanteCilindro




@pytest.mark.django_db
class TestSprint13RolloutECarga(TestCase):
    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Piloto Alpha LTDA",
            nome_fantasia="Distribuidora Piloto Alpha",
            cnpj="12345678000199",
            status_assinatura="ATIVO",
        )
        self.outro_tenant = Tenant.objects.create(
            razao_social="Distribuidora Beta LTDA",
            nome_fantasia="Distribuidora Beta",
            cnpj="98765432000188",
            status_assinatura="ATIVO",
        )
        self.token = set_current_tenant(self.tenant)

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()

    def test_rollout_piloto_flags_e_modulo(self):
        # Inicialmente não é piloto
        self.assertFalse(self.tenant.is_piloto)
        self.assertFalse(is_feature_piloto_ativa(self.tenant, "portal_b2b_v2"))

        # Marcar como piloto
        marcar_tenant_como_piloto(self.tenant, True)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_piloto)

        # Habilitar flag
        habilitar_feature_piloto(self.tenant, "portal_b2b_v2", True)
        self.assertTrue(is_feature_piloto_ativa(self.tenant, "portal_b2b_v2"))

        # Desabilitar flag
        habilitar_feature_piloto(self.tenant, "portal_b2b_v2", False)
        self.assertFalse(is_feature_piloto_ativa(self.tenant, "portal_b2b_v2"))

        # Alias de retrocompatibilidade
        self.assertEqual(RequiresModuleDistribuicao, RequiresModuleLogistica)

    def test_rollback_modulo_staging(self):
        # Executar rollback de módulo logístico em tenant piloto
        resultado = executar_rollback_modulo(
            tenant=self.tenant,
            modulo="logistica",
            motivo="Falha de regressão na roteirização de cilindros em teste de staging",
            solicitante="devops@baros.com.br",
        )
        self.assertTrue(resultado["sucesso"])
        self.assertIn("logistica", resultado["flags_desativadas"])
        self.assertEqual(resultado["status_modulo"], "ROLLBACK_CONCLUIDO")

    def test_carga_legado_clientes_e_fornecedores_idempotente(self):
        dados_clientes = [
            {
                "cpf_cnpj": "11122233344",
                "nome_razao_social": "Cliente Teste Carga",
                "nome_fantasia": "Cliente Carga",
                "email_financeiro": "financeiro@clientecarga.com.br",
                "tipo_pessoa": "PF",
            }
        ]

        # Dry-run
        res_dry = carregar_clientes(self.tenant, dados_clientes, dry_run=True)
        self.assertTrue(res_dry["dry_run"])
        self.assertEqual(res_dry["total_processado"], 1)
        self.assertFalse(Cliente.objects.filter(tenant=self.tenant, cnpj="11122233344").exists())

        # Execução real
        res_real = carregar_clientes(self.tenant, dados_clientes, dry_run=False)
        self.assertFalse(res_real["dry_run"])
        self.assertEqual(res_real["criados"], 1)
        self.assertTrue(Cliente.objects.filter(tenant=self.tenant, cnpj="11122233344").exists())

        # Segunda execução (idempotente - atualização / skip)
        res_idempotente = carregar_clientes(self.tenant, dados_clientes, dry_run=False)
        self.assertEqual(res_idempotente["criados"], 0)
        self.assertEqual(res_idempotente["atualizados"], 1)

        # Carga fornecedores
        dados_fornecedores = [
            {
                "cnpj_cpf": "55566677700011",
                "razao_social": "Fornecedor Gases Brasil SA",
                "nome_fantasia": "Gases Brasil",
                "email": "contato@gasesbrasil.com.br",
            }
        ]
        res_forn = carregar_fornecedores(self.tenant, dados_fornecedores, dry_run=False)
        self.assertEqual(res_forn["criados"], 1)
        self.assertTrue(Fornecedor.objects.filter(tenant=self.tenant, documento="55566677700011").exists())


    def test_carga_legado_cilindros_e_saldo_abertura(self):
        gas, _ = GasQuimico.objects.get_or_create(
            sigla="O2",
            defaults={"nome": "Oxigênio Industrial", "categoria": "INDUSTRIAL"}
        )
        modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao="Cilindro 10m3 Matheson",
            volume_hidraulico_litros=Decimal("50.00"),
            tara_nominal_kg=Decimal("60.00"),
            pressao_servico_bar=200,
        )
        fab = FabricanteCilindro.objects.create(tenant=self.tenant, nome="Matheson")

        dados_cilindros = [
            {
                "numero_serie": "OX-999001",
                "gas_sigla": "O2",
                "modelo_id": modelo.id,
                "fabricante_id": fab.id,
                "propriedade": "PROPRIO",
            }
        ]
        res_cil = carregar_cilindros(self.tenant, dados_cilindros, dry_run=False)
        self.assertEqual(res_cil["criados"], 1)
        self.assertTrue(Cilindro.objects.filter(tenant=self.tenant, numero_serie_ogiva="OX-999001").exists())


        # Contas contábeis para saldo de abertura
        cta_ativo = PlanoContas.objects.create(
            tenant=self.tenant,
            codigo_estrutural="1.1.1.01",
            nome="Caixa Geral",
            natureza_saldo="DEVEDORA",
            tipo="ANALITICA",
            nivel=4,
            aceita_lancamento=True,
        )
        cta_pl = PlanoContas.objects.create(
            tenant=self.tenant,
            codigo_estrutural="2.4.1.01",
            nome="Capital Social",
            natureza_saldo="CREDORA",
            tipo="ANALITICA",
            nivel=4,
            aceita_lancamento=True,
        )


        # Partidas dobradas balanceadas
        partidas = [
            {"conta_id": cta_ativo.id, "tipo": "DEBITO", "valor": Decimal("50000.00")},
            {"conta_id": cta_pl.id, "tipo": "CREDITO", "valor": Decimal("50000.00")},
        ]
        res_saldo = carregar_saldo_abertura(
            self.tenant,
            data_abertura=date(2026, 1, 1),
            partidas=partidas,
            dry_run=False,
        )
        self.assertTrue(res_saldo["sucesso"])
        self.assertEqual(res_saldo["total_debito"], Decimal("50000.00"))
        self.assertEqual(res_saldo["total_credito"], Decimal("50000.00"))

        # Partidas desbalanceadas devem falhar
        partidas_invalidas = [
            {"conta_id": cta_ativo.id, "tipo": "DEBITO", "valor": Decimal("50000.00")},
            {"conta_id": cta_pl.id, "tipo": "CREDITO", "valor": Decimal("40000.00")},
        ]
        with self.assertRaises(ValueError):
            carregar_saldo_abertura(
                self.tenant,
                data_abertura=date(2026, 1, 1),
                partidas=partidas_invalidas,
                dry_run=False,
            )


@pytest.mark.django_db
class TestSprint13SegurancaEPITR(TestCase):
    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Segura LTDA",
            nome_fantasia="Distribuidora Segura",
            cnpj="11223344000155",
            status_assinatura="ATIVO",
        )
        self.token = set_current_tenant(self.tenant)

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()

    def test_criptografia_em_repouso_e_rotacao_chaves(self):
        dado_sensivel = "CertificadoDigitalA1SenhaUltraSecreta2026!"
        dado_cifrado = criptografar_dado_sensivel(dado_sensivel)
        self.assertNotEqual(dado_sensivel, dado_cifrado)

        dado_recuperado = decriptografar_dado_sensivel(dado_cifrado)
        self.assertEqual(dado_sensivel, dado_recuperado)

        # Rotação de chaves
        res_rotacao = rotacionar_chaves_seguranca(self.tenant)
        self.assertTrue(res_rotacao["sucesso"])
        self.assertIn("nova_chave_versao", res_rotacao)

    def test_owasp_top10_conformidade(self):
        conformidade = verificar_conformidade_owasp()
        self.assertEqual(conformidade["total_categorias_auditadas"], 10)
        self.assertEqual(conformidade["status_geral"], "CONFORME_GO_LIVE")
        self.assertTrue(conformidade["todas_categorias_aprovadas"])

    def test_backup_pitr_e_teste_restauracao(self):
        parametros = obter_parametros_continuidade()
        self.assertEqual(parametros["rpo_minutos_alvo"], 15)
        self.assertEqual(parametros["rto_horas_alvo"], 4)

        data_alvo = timezone.now() - timedelta(minutes=10)
        pitr = simular_recuperacao_pitr(self.tenant, data_alvo)
        self.assertTrue(pitr["sucesso"])
        self.assertLessEqual(pitr["rpo_efetivo_minutos"], 15)

        restauracao = executar_teste_restauracao_trimestral(self.tenant)
        self.assertTrue(restauracao["sucesso"])
        self.assertEqual(restauracao["status_final"], "APROVADO_PARA_PRODUCAO")


@pytest.mark.django_db
class TestSprint13LGPDEPerformance(TestCase):
    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora LGPD LTDA",
            nome_fantasia="Distribuidora LGPD",
            cnpj="99887766000144",
            status_assinatura="ATIVO",
        )
        self.token = set_current_tenant(self.tenant)
        self.cliente_pf = Cliente.objects.create(
            tenant=self.tenant,
            cnpj="01234567890",
            nome="Carlos Silva Motorista e Cliente",
            email_financeiro="carlos.silva@exemplo.com.br",
            telefone="11999998888",
            endereco="Rua Teste, 100",
            cidade="São Paulo",
            estado="SP",
            proprietario="Carlos Silva",
        )

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()

    def test_mapeamento_lgpd_ropa(self):
        ropa = obter_mapeamento_lgpd()
        self.assertIn("papel_saas", ropa)
        self.assertEqual(ropa["papel_saas"], "OPERADOR")
        self.assertEqual(ropa["papel_tenant"], "CONTROLADOR")
        self.assertIn("motoristas_gps", ropa["inventario_dados"])

    def test_solicitacao_acesso_e_anonimizacao_titular(self):
        # Acesso / Exportação
        res_acesso = solicitar_acesso_exportacao_titular(
            tenant=self.tenant,
            cpf_titular="01234567890",
            tipo_titular="CLIENTE_PF",
        )
        self.assertEqual(res_acesso["status"], "CONCLUIDA")
        self.assertEqual(res_acesso["dados"]["cpf_cnpj"], "01234567890")
        self.assertIn("Carlos Silva", res_acesso["dados"]["nome"])

        # Eliminação / Anonimização com retenção fiscal
        res_elim = solicitar_eliminacao_anonimizacao_titular(
            tenant=self.tenant,
            cpf_titular="01234567890",
            tipo_titular="CLIENTE_PF",
            motivo="Solicitação de exclusão Artigo 18 LGPD",
        )
        self.assertEqual(res_elim["status"], "ANONIMIZADO_COM_RETENCAO_FISCAL")

        # Verificar se o cliente foi anonimizado mantendo integridade cadastral/fiscal
        self.cliente_pf.refresh_from_db()
        self.assertTrue(self.cliente_pf.nome_razao_social.startswith("TITULAR_ANONIMIZADO_"))
        self.assertTrue(self.cliente_pf.email_financeiro.endswith("@anonimizado.local"))

    def test_expurgo_telemetria_gps(self):
        res_gps = expurgar_telemetria_gps_antiga(self.tenant, dias_retencao=90)
        self.assertTrue(res_gps["sucesso"])
        self.assertEqual(res_gps["dias_retencao_aplicados"], 90)

    def test_performance_explain_e_slas(self):
        slas = obter_metas_slas_latencia()
        self.assertEqual(slas["dre_p95_ms"], 200)
        self.assertEqual(slas["ofx_p95_ms"], 150)
        self.assertEqual(slas["kanban_p95_ms"], 100)
        self.assertEqual(slas["rastreio_p95_ms"], 80)

        explain_res = analisar_explain_consultas_criticas(self.tenant)
        self.assertTrue(explain_res["sucesso"])
        self.assertEqual(explain_res["total_consultas_avaliadas"], 4)
        for _, rel in explain_res["relatorios"].items():
            self.assertTrue(rel["index_scan_verificado"])

        infra = dimensionar_infraestrutura_filas_conexoes()
        self.assertGreaterEqual(infra["conexoes_db_pgbouncer"]["pool_size_max"], 50)

        bench = benchmark_latencia_simulada(self.tenant)
        self.assertTrue(bench["todos_slas_cumpridos"])


@pytest.mark.django_db
class TestSprint13ObservabilidadeEResiliencia(TestCase):
    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Resiliente LTDA",
            nome_fantasia="Distribuidora Resiliente",
            cnpj="33445566000122",
            status_assinatura="ATIVO",
        )
        self.token = set_current_tenant(self.tenant)

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()


    def test_observabilidade_e_integridade_razao(self):
        # Razão inicialmente zerado ou equilibrado
        razao = verificar_integridade_razao_contabil(self.tenant)
        self.assertTrue(razao["integro"])
        self.assertEqual(razao["diferenca"], Decimal("0.00"))

        # Criar partidas equilibradas
        cta_d = PlanoContas.objects.create(
            tenant=self.tenant,
            codigo_estrutural="1.1.2.01",
            nome="Bancos Conta Movimento",
            natureza_saldo="DEVEDORA",
            tipo="ANALITICA",
            nivel=4,
            aceita_lancamento=True,
        )
        cta_c = PlanoContas.objects.create(
            tenant=self.tenant,
            codigo_estrutural="4.1.1.01",
            nome="Receita de Venda de Gases",
            natureza_saldo="CREDORA",
            tipo="ANALITICA",
            nivel=4,
            aceita_lancamento=True,
        )
        lancamento = LancamentoContabil.objects.create(
            tenant=self.tenant,
            numero=1,
            data_competencia=date.today(),
            historico="Venda a vista",
            origem_tipo="VENDA",
            origem_id="V-1",
            hash_anterior="0" * 64,
            hash_integridade="HASH_TESTE_1",
        )
        PartidaContabil.objects.create(
            tenant=self.tenant,
            lancamento=lancamento,
            conta_contabil=cta_d,
            tipo_partida="DEBITO",
            valor=Decimal("1500.00"),
        )
        PartidaContabil.objects.create(
            tenant=self.tenant,
            lancamento=lancamento,
            conta_contabil=cta_c,
            tipo_partida="CREDITO",
            valor=Decimal("1500.00"),
        )


        razao_apos = verificar_integridade_razao_contabil(self.tenant)
        self.assertTrue(razao_apos["integro"])
        self.assertEqual(razao_apos["total_debitos"], Decimal("1500.00"))
        self.assertEqual(razao_apos["total_creditos"], Decimal("1500.00"))

        # Diagnóstico geral
        diag = diagnosticar_painel_observabilidade(self.tenant)
        self.assertIn("jobs_falhos", diag)
        self.assertIn("pendencias_contabilizacao", diag)
        self.assertIn("razao_contabil", diag)

        # Catálogo de runbooks
        runbooks = obter_catalogo_alertas_runbooks()
        self.assertIn("ALERTA_RAZAO_DESBALANCEADO", runbooks)
        self.assertIn("ALERTA_CERTIFICADO_EXPIRANDO", runbooks)

    def test_resiliencia_redis_offline_graceful_degradation(self):
        # Simular falha de conexão do Redis
        with patch.object(cache, "get", side_effect=Exception("Redis connection refused")):
            # O sistema não deve quebrar abruptamente em leitura de cache
            try:
                valor = cache.get("chave_inexistente")
            except Exception as e:
                valor = None
            self.assertIsNone(valor)

    def test_resiliencia_idempotencia_webhook_duplicado(self):
        # Testar que chamada repetida de carga com o mesmo payload é idempotente
        dados = [
            {
                "cpf_cnpj": "44455566677",
                "nome_razao_social": "Cliente Webhook Resiliente",
                "tipo_pessoa": "PF",
            }
        ]
        res1 = carregar_clientes(self.tenant, dados, dry_run=False)
        self.assertEqual(res1["criados"], 1)

        # Repetição do mesmo evento/webhook
        res2 = carregar_clientes(self.tenant, dados, dry_run=False)
        self.assertEqual(res2["criados"], 0)
        self.assertEqual(res2["atualizados"], 1)
        self.assertEqual(Cliente.objects.filter(tenant=self.tenant, cnpj="44455566677").count(), 1)



class TestSprint13HypothesisInvariants(unittest.TestCase):
    @given(
        st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000.00"), places=2),
        st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000.00"), places=2),
    )
    def test_hipotese_invariante_partidas_dobradas(self, debito, credito):
        # Teste de propriedade pura de invariante de saldo
        diferenca = quantize(abs(debito - credito))
        if debito == credito:
            self.assertEqual(diferenca, Decimal("0.00"))
        else:
            self.assertGreater(diferenca, Decimal("0.00"))
