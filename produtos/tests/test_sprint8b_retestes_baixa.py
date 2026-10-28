import datetime
from decimal import Decimal
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.money import quantize
from core.models import Filial, Membership, Tenant, LogAuditoriaDados
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from produtos.models import (
    Cilindro,
    FabricanteCilindro,
    ClasseAtivo,
    GasQuimico,
    ModeloCilindro,
    HistoricoRetesteHidrostatico,
    EnvioReteste,
    ItemEnvioReteste,
    BaixaPatrimonial,
    ReclassificacaoCilindro,
    TabelaIndenizacaoCilindro,
)
from produtos.services import (
    enviar_cilindros_para_reteste,
    registrar_retorno_reteste,
    retificar_reteste,
    baixar_cilindro_patrimonial,
    estornar_baixa,
    registrar_extravio,
    reclassificar_cilindro_gas,
    registrar_envase_cilindro,
    validar_transicao_status_cilindro,
)
from produtos.tasks import alertar_vencimento_reteste_task

User = get_user_model()


class Sprint8BBaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()

        self.tenant_a = Tenant.objects.create(
            nome_fantasia="Oxigênio Alpha Ltda",
            razao_social="Alpha Gases Ltda",
            cnpj="11.222.333/0001-44",
            modulo_patrimonio_ativo=True,
            modulo_envase_ativo=True,
            status_assinatura='ATIVO'
        )
        self.tenant_b = Tenant.objects.create(
            nome_fantasia="Beta Gás Ltda",
            razao_social="Beta Gases Ltda",
            cnpj="22.333.444/0001-55",
            modulo_patrimonio_ativo=True,
            status_assinatura='ATIVO'
        )

        self.user_a = User.objects.create_user(
            username="operador_a",
            email="operador_a@alpha.com",
            password="password123"
        )
        self.user_b = User.objects.create_user(
            username="operador_b",
            email="operador_b@beta.com",
            password="password123"
        )

        Membership.objects.create(user=self.user_a, tenant=self.tenant_a, papel='ADMIN', ativo=True)
        Membership.objects.create(user=self.user_b, tenant=self.tenant_b, papel='ADMIN', ativo=True)

        set_current_tenant(self.tenant_a)

        self.gas_o2, _ = GasQuimico.objects.get_or_create(
            sigla="O2",
            defaults={"nome": "Oxigênio Industrial", "categoria": "INDUSTRIAL"}
        )
        self.gas_med, _ = GasQuimico.objects.get_or_create(
            sigla="O2-MED",
            defaults={"nome": "Oxigênio Medicinal", "categoria": "MEDICINAL", "exige_lote_anvisa": True}
        )

        self.modelo_t50 = ModeloCilindro.objects.create(
            tenant=self.tenant_a,
            descricao="Cilindro Aço 50L Alta Pressão",
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('50.00'),
            periodicidade_reteste_anos=5
        )

        self.fabricante = FabricanteCilindro.objects.create(
            tenant=self.tenant_a,
            nome="Mat de Testes SA",
            pais_origem="BR",
            norma_fabricacao_padrao="ABNT NBR 12790"
        )

        self.classe_cil = ClasseAtivo.objects.create(
            tenant=self.tenant_a,
            codigo="CIL-IND",
            nome="Cilindros Industriais",
            tipo="CILINDRO",
            vida_util_meses_padrao=120,
            percentual_residual_padrao=Decimal('0.1000')
        )

        self.cilindro_a = Cilindro.objects.create(
            tenant=self.tenant_a,
            codigo_qr="QR-S8B-001",
            numero_serie_ogiva="S8B-001",
            fabricante=self.fabricante.nome,
            fabricante_catalogo=self.fabricante,
            ano_fabricacao=2020,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            propriedade='PROPRIO',
            classe_ativo=self.classe_cil,
            valor_aquisicao=Decimal('1200.00'),
            valor_residual=Decimal('120.00'),
            vida_util_meses=120,
            data_aquisicao=self.hoje - datetime.timedelta(days=730),
            data_inicio_depreciacao=self.hoje - datetime.timedelta(days=730),
            data_ultimo_reteste=self.hoje - datetime.timedelta(days=730),
            data_proximo_reteste=self.hoje + datetime.timedelta(days=1095),
            tara_real_kg=Decimal('55.000'),
            status='VAZIO_TRIAGEM'
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()


class TestRetesteHidrostaticoEServicos(Sprint8BBaseTestCase):
    """
    Testes de Ensaio Hidrostático (ABNT NBR 12274), Limite de Expansão e Imutabilidade (Tarefas 1, 2, 4).
    """

    def test_reteste_aprovado_atualiza_datas_e_tara_e_retorna_vazio_triagem(self):
        # Transita para EM_REQUALIFICACAO primeiro
        self.cilindro_a.status = 'EM_REQUALIFICACAO'
        self.cilindro_a.save(update_fields=['status'])

        data_exec = self.hoje
        cil, hist = registrar_retorno_reteste(
            tenant=self.tenant_a,
            cilindro_id=self.cilindro_a.id,
            numero_certificado="CERT-2026-001",
            data_execucao=data_exec,
            oficina_nome="Requalificadora Central",
            oficina_cnpj="99.888.777/0001-66",
            registro_inmetro="INM-12345",
            pressao_teste_bar=Decimal('300.00'),
            expansao_total_cm3=Decimal('100.000'),
            expansao_permanente_cm3=Decimal('6.000'), # 6% <= 10%
            tara_real_kg=Decimal('54.800'),
            resultado='APROVADO',
            usuario=self.user_a
        )

        self.assertEqual(cil.status, 'VAZIO_TRIAGEM')
        self.assertEqual(cil.data_ultimo_reteste, data_exec)
        self.assertEqual(cil.data_proximo_reteste, data_exec.replace(year=data_exec.year + 5))
        self.assertEqual(cil.tara_real_kg, Decimal('54.800'))
        self.assertEqual(hist.expansao_permanente_percentual, Decimal('6.0000'))
        self.assertEqual(hist.resultado, 'APROVADO')

    def test_reteste_expansao_acima_limite_gera_validation_error_se_aprovado(self):
        # 12% > 10% (reprovação mandatória pela norma)
        with self.assertRaises(ValidationError) as ctx:
            registrar_retorno_reteste(
                tenant=self.tenant_a,
                cilindro_id=self.cilindro_a.id,
                numero_certificado="CERT-FAIL-001",
                data_execucao=self.hoje,
                oficina_nome="Requalificadora Central",
                oficina_cnpj="99.888.777/0001-66",
                registro_inmetro="INM-12345",
                expansao_total_cm3=Decimal('100.000'),
                expansao_permanente_cm3=Decimal('12.000'),
                resultado='APROVADO',
                usuario=self.user_a
            )
        self.assertIn("10.0000%", str(ctx.exception))

    def test_reteste_reprovado_condenado_baixa_cilindro_e_aplica_bloqueio_sanitario(self):
        cil, hist = registrar_retorno_reteste(
            tenant=self.tenant_a,
            cilindro_id=self.cilindro_a.id,
            numero_certificado="CERT-CONDENADO-001",
            data_execucao=self.hoje,
            oficina_nome="Requalificadora Central",
            oficina_cnpj="99.888.777/0001-66",
            registro_inmetro="INM-12345",
            expansao_total_cm3=Decimal('100.000'),
            expansao_permanente_cm3=Decimal('15.000'),
            resultado='REPROVADO_CONDENADO',
            motivo_reprovacao="Fissura longitudinal identificada e expansão permanente excessiva.",
            usuario=self.user_a
        )

        cil.refresh_from_db()
        self.assertEqual(cil.status, 'BAIXADO')
        self.assertTrue(cil.bloqueio_sanitario)
        self.assertIn("CERT-CONDENADO-001", cil.motivo_bloqueio_sanitario)

        baixa = BaixaPatrimonial.objects.filter(cilindro=cil).first()
        self.assertIsNotNone(baixa)
        self.assertEqual(baixa.tipo, 'INUTILIZACAO_TECNICA')
        self.assertEqual(baixa.documento_ref, 'CERT-CONDENADO-001')

    def test_reteste_tara_divergente_gera_alerta(self):
        # Cilindro tem tara_real_kg = 55.000 kg. Nova tara = 50.000 kg (variação ~9.09% > 5%)
        cil, hist = registrar_retorno_reteste(
            tenant=self.tenant_a,
            cilindro_id=self.cilindro_a.id,
            numero_certificado="CERT-TARA-001",
            data_execucao=self.hoje,
            oficina_nome="Requalificadora Central",
            oficina_cnpj="99.888.777/0001-66",
            registro_inmetro="INM-12345",
            expansao_total_cm3=Decimal('100.000'),
            expansao_permanente_cm3=Decimal('4.000'),
            tara_real_kg=Decimal('50.000'),
            resultado='APROVADO',
            usuario=self.user_a
        )
        self.assertIn("ALERTA DE TARA", hist.observacoes)

    def test_reteste_imutavel_nao_editavel_nem_excluivel(self):
        _, hist = registrar_retorno_reteste(
            tenant=self.tenant_a,
            cilindro_id=self.cilindro_a.id,
            numero_certificado="CERT-IMUTAVEL-001",
            data_execucao=self.hoje,
            oficina_nome="Requalificadora Central",
            oficina_cnpj="99.888.777/0001-66",
            registro_inmetro="INM-12345",
            resultado='APROVADO',
            usuario=self.user_a
        )

        with self.assertRaises(ValidationError):
            hist.observacoes = "Tentativa de alteração pós-laudo"
            hist.save()

        with self.assertRaises(ValidationError):
            hist.delete()

    def test_retificar_reteste_cria_novo_registro_apontando_anterior(self):
        _, hist_original = registrar_retorno_reteste(
            tenant=self.tenant_a,
            cilindro_id=self.cilindro_a.id,
            numero_certificado="CERT-RETIF-001",
            data_execucao=self.hoje,
            oficina_nome="Requalificadora Central",
            oficina_cnpj="99.888.777/0001-66",
            registro_inmetro="INM-12345",
            resultado='APROVADO',
            usuario=self.user_a
        )

        novo = retificar_reteste(
            reteste_anterior_id=hist_original.id,
            novos_dados={
                'numero_certificado': 'CERT-RETIF-001-REV1',
                'observacoes': 'Correção de digitação do número do laudo'
            },
            usuario=self.user_a
        )

        self.assertNotEqual(novo.id, hist_original.id)
        self.assertEqual(novo.retifica_id, hist_original.id)
        self.assertEqual(novo.numero_certificado, 'CERT-RETIF-001-REV1')

    def test_reprocessar_mesmo_certificado_idempotente_nao_duplica(self):
        _, hist1 = registrar_retorno_reteste(
            tenant=self.tenant_a,
            cilindro_id=self.cilindro_a.id,
            numero_certificado="CERT-IDEMPOTENTE-999",
            data_execucao=self.hoje,
            oficina_nome="Oficina Exemplo",
            oficina_cnpj="11.222.333/0001-99",
            registro_inmetro="INM-999",
            resultado='APROVADO',
            usuario=self.user_a
        )

        # Segunda chamada com o mesmo certificado
        _, hist2 = registrar_retorno_reteste(
            tenant=self.tenant_a,
            cilindro_id=self.cilindro_a.id,
            numero_certificado="CERT-IDEMPOTENTE-999",
            data_execucao=self.hoje,
            oficina_nome="Oficina Exemplo",
            oficina_cnpj="11.222.333/0001-99",
            registro_inmetro="INM-999",
            resultado='APROVADO',
            usuario=self.user_a
        )

        self.assertEqual(hist1.id, hist2.id)
        self.assertEqual(HistoricoRetesteHidrostatico.objects.filter(numero_certificado="CERT-IDEMPOTENTE-999").count(), 1)


class TestEnvioReteste(Sprint8BBaseTestCase):
    """
    Testes de Envio e Remessa de Cilindros para Reteste (Tarefa 3).
    """

    def test_envio_reteste_cilindros_vazios_sucesso(self):
        envio, cils = enviar_cilindros_para_reteste(
            tenant=self.tenant_a,
            oficina_nome="Oficina Alfa Retestes",
            oficina_cnpj="12.345.678/0001-90",
            cilindro_ids=[self.cilindro_a.id],
            usuario=self.user_a
        )

        self.assertEqual(envio.itens.count(), 1)
        self.cilindro_a.refresh_from_db()
        self.assertEqual(self.cilindro_a.status, 'EM_REQUALIFICACAO')

    def test_envio_reteste_cilindro_cheio_ou_em_posse_de_cliente_bloqueado(self):
        self.cilindro_a.status = 'CHEIO_DISPONIVEL'
        self.cilindro_a.save(update_fields=['status'])

        with self.assertRaises(ValidationError) as ctx:
            enviar_cilindros_para_reteste(
                tenant=self.tenant_a,
                oficina_nome="Oficina Alfa Retestes",
                oficina_cnpj="12.345.678/0001-90",
                cilindro_ids=[self.cilindro_a.id],
                usuario=self.user_a
            )
        self.assertIn("Vazio em Triagem", str(ctx.exception))


class TestBaixaPatrimonialEEstorno(Sprint8BBaseTestCase):
    """
    Testes de Baixa Patrimonial, Irreversibilidade e Estorno Autorizado (Tarefas 5, 6, 7).
    """

    def test_baixa_patrimonial_guarda_snapshot_valor_contabil_e_resultado(self):
        cil, baixa = baixar_cilindro_patrimonial(
            cilindro_id=self.cilindro_a.id,
            tipo='SINISTRO',
            motivo='Destruição em acidente com veículo',
            documento_ref='BO-2026-999',
            valor_recebido=Decimal('200.00'),
            usuario=self.user_a
        )

        cil.refresh_from_db()
        self.assertEqual(cil.status, 'BAIXADO')
        self.assertGreater(baixa.valor_contabil_baixa, Decimal('0.00'))
        self.assertEqual(baixa.valor_recebido, Decimal('200.00'))
        self.assertEqual(baixa.resultado, quantize(Decimal('200.00') - baixa.valor_contabil_baixa, Decimal('0.01')))

    def test_cilindro_baixado_impede_qualquer_saida_sem_estorno(self):
        self.cilindro_a.status = 'BAIXADO'
        self.cilindro_a.save(update_fields=['status'])

        with self.assertRaises(ValidationError) as ctx:
            validar_transicao_status_cilindro(self.cilindro_a, 'VAZIO_TRIAGEM')
        self.assertIn("estado terminal", str(ctx.exception))

    def test_estorno_baixa_sem_permissao_lanca_permission_error(self):
        user_sem_perm = User.objects.create_user(username="sem_perm", email="sem@test.com", password="pass")
        Membership.objects.create(user=user_sem_perm, tenant=self.tenant_a, papel='OPERADOR_PATIO', ativo=True)

        _, baixa = baixar_cilindro_patrimonial(
            cilindro_id=self.cilindro_a.id,
            tipo='EXTRAVIO',
            usuario=self.user_a
        )

        with self.assertRaises(PermissionError):
            estornar_baixa(baixa_id=baixa.id, motivo="Estorno indevido", usuario=user_sem_perm)

    def test_estorno_baixa_com_permissao_restaura_status_e_gera_auditoria(self):
        _, baixa = baixar_cilindro_patrimonial(
            cilindro_id=self.cilindro_a.id,
            tipo='EXTRAVIO',
            usuario=self.user_a
        )

        user_gestor = User.objects.create_user(username="gestor_patrimonio", email="gestor@test.com", password="pass")
        perm = Permission.objects.get(codename='estornar_baixa')
        user_gestor.user_permissions.add(perm)
        Membership.objects.create(user=user_gestor, tenant=self.tenant_a, papel='GERENTE', ativo=True)

        cil, baixa_estornada, mov = estornar_baixa(
            baixa_id=baixa.id,
            motivo="Cilindro localizado no depósito após inventário",
            usuario=user_gestor
        )

        cil.refresh_from_db()
        self.assertEqual(cil.status, 'VAZIO_TRIAGEM')
        self.assertTrue(baixa_estornada.estornada)
        self.assertIsNotNone(baixa_estornada.data_estorno)

        # Auditoria gravada
        audit = LogAuditoriaDados.objects.filter(object_id=str(baixa.id), acao="ESTORNO").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.acao, "ESTORNO")

        # Prova que não permite reestornar
        with self.assertRaises(ValidationError):
            estornar_baixa(baixa_id=baixa.id, motivo="Tentativa dupla", usuario=user_gestor)

    def test_registrar_extravio_calcula_indenizacao_e_publica_baixa(self):
        TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant_a,
            tipo_cilindro=self.modelo_t50,
            gas=self.gas_o2,
            valor=Decimal('1500.00'),
            vigencia_inicio=self.hoje - datetime.timedelta(days=100)
        )

        cil, baixa, ind = registrar_extravio(
            cilindro_id=self.cilindro_a.id,
            data=self.hoje,
            motivo="Não devolvido pelo cliente",
            documento_ref="NOTIF-123",
            usuario=self.user_a
        )

        cil.refresh_from_db()
        self.assertEqual(cil.status, 'BAIXADO')
        self.assertEqual(baixa.tipo, 'EXTRAVIO')
        self.assertEqual(baixa.valor_recebido, Decimal('1500.00'))
        self.assertEqual(ind['valor_contratual'], Decimal('1500.00'))


class TestReclassificacaoCilindroSprint8B(Sprint8BBaseTestCase):
    """
    Testes de Reclassificação Sanitária, Laudo, Estanqueidade e Reteste Vinculado (Tarefa 8).
    """

    def setUp(self):
        super().setUp()
        self.laudo_fake = SimpleUploadedFile("laudo_descontaminacao.pdf", b"%PDF-1.4 Fake PDF", content_type="application/pdf")

    def test_reclassificacao_sem_laudo_bloqueada(self):
        with self.assertRaises(ValidationError) as ctx:
            reclassificar_cilindro_gas(
                cilindro_id=self.cilindro_a.id,
                novo_gas_id=self.gas_med.id,
                descontaminacao_purga_executada=True,
                troca_valvula_executada=True,
                pintura_adequada_abnt=True,
                laudo_descontaminacao=None,
                validade_estanqueidade=self.hoje + datetime.timedelta(days=180),
                usuario=self.user_a
            )
        self.assertIn("laudo", str(ctx.exception).lower())

    def test_reclassificacao_sem_estanqueidade_vigente_bloqueada(self):
        with self.assertRaises(ValidationError) as ctx:
            reclassificar_cilindro_gas(
                cilindro_id=self.cilindro_a.id,
                novo_gas_id=self.gas_med.id,
                descontaminacao_purga_executada=True,
                troca_valvula_executada=True,
                pintura_adequada_abnt=True,
                laudo_descontaminacao=self.laudo_fake,
                validade_estanqueidade=self.hoje - datetime.timedelta(days=5), # Vencida
                usuario=self.user_a
            )
        self.assertIn("estanqueidade", str(ctx.exception).lower())

    def test_reclassificacao_exigiu_novo_reteste_sem_reteste_aprovado_bloqueada(self):
        # Exigiu novo reteste mas nenhum foi passado
        with self.assertRaises(ValidationError) as ctx:
            reclassificar_cilindro_gas(
                cilindro_id=self.cilindro_a.id,
                novo_gas_id=self.gas_med.id,
                descontaminacao_purga_executada=True,
                troca_valvula_executada=True,
                pintura_adequada_abnt=True,
                laudo_descontaminacao=self.laudo_fake,
                validade_estanqueidade=self.hoje + datetime.timedelta(days=180),
                exigiu_novo_reteste=True,
                reteste_vinculado=None,
                usuario=self.user_a
            )
        self.assertIn("reteste", str(ctx.exception).lower())

    def test_reclassificacao_completa_com_todos_requisitos_sucesso(self):
        rt_user = User.objects.create_user(username="rt_resp", email="rt@alpha.com", password="password123")
        Membership.objects.create(user=rt_user, tenant=self.tenant_a, papel='RESPONSAVEL_TECNICO', ativo=True)

        # Cria reteste aprovado vinculado
        reteste = HistoricoRetesteHidrostatico.objects.create(
            tenant=self.tenant_a,
            cilindro=self.cilindro_a,
            origem_registro='REGISTRO',
            data_execucao=self.hoje,
            numero_certificado="CERT-RECLASS-01",
            oficina_nome="Oficina Acreditada",
            oficina_cnpj="11.222.333/0001-22",
            registro_inmetro="INM-REC-01",
            resultado='APROVADO'
        )

        cil, rec, mov = reclassificar_cilindro_gas(
            cilindro_id=self.cilindro_a.id,
            novo_gas_id=self.gas_med.id,
            descontaminacao_purga_executada=True,
            troca_valvula_executada=True,
            pintura_adequada_abnt=True,
            laudo_descontaminacao=self.laudo_fake,
            validade_estanqueidade=self.hoje + datetime.timedelta(days=180),
            exigiu_novo_reteste=True,
            reteste_vinculado=reteste,
            usuario=rt_user
        )

        cil.refresh_from_db()
        self.assertEqual(cil.gas_dedicado_id, self.gas_med.id)
        self.assertEqual(rec.reteste_vinculado_id, reteste.id)
        self.assertTrue(rec.exigiu_novo_reteste)
        self.assertIsNotNone(rec.validade_estanqueidade)


class TestJobAlertarVencimentoReteste(Sprint8BBaseTestCase):
    """
    Testes do Job Diário de Monitoramento de Vencimentos e Bloqueio de Envase (Tarefa 10).
    """

    def test_job_alertar_vencimento_reteste_e_bloqueio_envase(self):
        # Cilindro 1: Vencido
        self.cilindro_a.data_proximo_reteste = self.hoje - datetime.timedelta(days=10)
        self.cilindro_a.save(update_fields=['data_proximo_reteste'])

        # Cilindro 2: Vencendo em 20 dias (faixa 30d)
        cil_20d = Cilindro.objects.create(
            tenant=self.tenant_a,
            codigo_qr="QR-S8B-20D",
            numero_serie_ogiva="S8B-20D",
            fabricante=self.fabricante.nome,
            ano_fabricacao=2021,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            propriedade='PROPRIO',
            data_ultimo_reteste=self.hoje - datetime.timedelta(days=1800),
            data_proximo_reteste=self.hoje + datetime.timedelta(days=20),
            status='VAZIO_TRIAGEM'
        )

        relatorio = alertar_vencimento_reteste_task(tenant_id=self.tenant_a.id)
        dados = relatorio[str(self.tenant_a.id)]
        self.assertGreaterEqual(dados['vencidos'], 1)
        self.assertGreaterEqual(dados['vencendo_30_dias'], 1)

        # Prova que tentar envasar cilindro com reteste vencido lança ValidationError
        with self.assertRaises(ValidationError) as ctx:
            from produtos.models import LoteEnvase
            lote = LoteEnvase.objects.create(
                tenant=self.tenant_a,
                codigo_lote="LOTE-TEST-001",
                gas=self.gas_o2,
                data_envase=self.hoje,
                data_validade=self.hoje + datetime.timedelta(days=365),
                responsavel_tecnico="CRQ 123456"
            )
            registrar_envase_cilindro(
                cilindro_id=self.cilindro_a.id,
                lote_id=lote.id,
                pressao_bar=200,
                usuario=self.user_a
            )
        self.assertIn("venceu", str(ctx.exception).lower())


class TestIsolamentoTenantSprint8B(Sprint8BBaseTestCase):
    """
    Testes de Isolamento Multi-tenant (Regra 3) provando 404 para recursos de outro tenant.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user_a)

        with tenant_context(self.tenant_b):
            self.gas_b, _ = GasQuimico.objects.get_or_create(
                sigla="GB",
                defaults={"nome": "Gás B", "categoria": "INDUSTRIAL"}
            )
            self.mod_b = ModeloCilindro.objects.create(
                tenant=self.tenant_b,
                descricao="Mod B",
                volume_hidraulico_litros=Decimal('10.00'),
                pressao_servico_bar=150,
                tara_nominal_kg=Decimal('15.00')
            )
            self.cil_b = Cilindro.objects.create(
                tenant=self.tenant_b,
                codigo_qr="QR-B-001",
                numero_serie_ogiva="B-001",
                fabricante="Fab B",
                ano_fabricacao=2021,
                modelo=self.mod_b,
                gas_dedicado=self.gas_b,
                data_ultimo_reteste=self.hoje,
                data_proximo_reteste=self.hoje + datetime.timedelta(days=1800),
                status='VAZIO_TRIAGEM'
            )
            self.reteste_b = HistoricoRetesteHidrostatico.objects.create(
                tenant=self.tenant_b,
                cilindro=self.cil_b,
                origem_registro='REGISTRO',
                data_execucao=self.hoje,
                numero_certificado="CERT-B-001",
                oficina_nome="Oficina B",
                oficina_cnpj="22.333.444/0001-99",
                registro_inmetro="INM-B",
                resultado='APROVADO'
            )
            self.envio_b = EnvioReteste.objects.create(
                tenant=self.tenant_b,
                oficina_nome="Oficina B",
                oficina_cnpj="22.333.444/0001-99",
                data_envio=self.hoje
            )
            self.baixa_b = BaixaPatrimonial.objects.create(
                tenant=self.tenant_b,
                cilindro=self.cil_b,
                tipo='EXTRAVIO',
                valor_contabil_baixa=Decimal('500.00')
            )

    def test_recursos_reteste_tenant_b_retornam_404_para_usuario_tenant_a(self):
        endpoints = [
            f'/produtos/api/patrimonio/retestes/{self.reteste_b.id}/',
            f'/produtos/api/patrimonio/envios-reteste/{self.envio_b.id}/',
            f'/produtos/api/patrimonio/baixas/{self.baixa_b.id}/',
        ]
        for url in endpoints:
            res = self.client.get(url)
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, f"URL {url} deveria retornar 404")
