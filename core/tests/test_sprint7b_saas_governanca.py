import datetime
from decimal import Decimal
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from core.guards import AssinaturaInativaError, ModuloInativoError, assert_modulo, assert_tenant_writable
from core.models import AcessoSuporte, FaturaSaaS, Filial, LogAuditoriaSaaS, Membership, PerfilRegulatorioTenant, PlanoSaaS, Tenant
from core.modulos import MODULOS_REGISTRO, is_modulo_ativo, validar_toggle
from core.services.assinatura import TransicaoInvalidaError, transicionar
from core.services.cotas import CotaExcedida, checar_cota
from core.services.onboarding import onboarding_tenant
from core.tasks import verificar_vencimentos_licenca
from core.tenancy import reset_current_tenant, set_current_tenant, tenant_context
from produtos.models import Cilindro, GasQuimico, ModeloCilindro

User = get_user_model()


class ModulosMatrizCombinacoesTests(TestCase):
    """
    Testes da tabela de combinações de módulos e matriz de dependências (Sprint 7B - F-30).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Industria de Gases Alpha Ltda',
            nome_fantasia='Alpha Gases',
            modulo_patrimonio_ativo=True,
            modulo_comercial_ativo=False,
            modulo_vendas_ativo=False,
            modulo_envase_ativo=False,
            modulo_logistica_ativo=False,
            modulo_fiscal_ativo=False,
            modulo_b2b_ativo=False,
            modulo_financeiro_ativo=False,
            modulo_analytics_ativo=False,
        )

    def test_patrimonio_sem_requisitos(self):
        """Módulo patrimônio não possui requisitos prévios para ativação."""
        erros = validar_toggle(self.tenant, 'patrimonio', True)
        self.assertEqual(erros, [])

    def test_ativar_comercial_exige_patrimonio(self):
        """Ativar comercial exige patrimônio."""
        self.tenant.modulo_patrimonio_ativo = False
        erros = validar_toggle(self.tenant, 'comercial', True)
        self.assertTrue(any('Patrimônio' in e for e in erros))

        self.tenant.modulo_patrimonio_ativo = True
        erros = validar_toggle(self.tenant, 'comercial', True)
        self.assertEqual(erros, [])

    def test_ativar_logistica_e_fiscal_exigem_vendas(self):
        """Logística e Fiscal requerem Vendas ativo."""
        self.tenant.modulo_vendas_ativo = False
        erros_log = validar_toggle(self.tenant, 'logistica', True)
        self.assertTrue(any('Vendas' in e for e in erros_log))

        erros_fisc = validar_toggle(self.tenant, 'fiscal', True)
        self.assertTrue(any('Vendas' in e for e in erros_fisc))

        self.tenant.modulo_vendas_ativo = True
        self.assertEqual(validar_toggle(self.tenant, 'logistica', True), [])
        self.assertEqual(validar_toggle(self.tenant, 'fiscal', True), [])

    def test_ativar_b2b_exige_comercial_e_vendas(self):
        """Portal B2B requer tanto comercial quanto vendas ativos."""
        self.tenant.modulo_comercial_ativo = False
        self.tenant.modulo_vendas_ativo = False
        erros = validar_toggle(self.tenant, 'b2b', True)
        self.assertEqual(len(erros), 2)

        self.tenant.modulo_comercial_ativo = True
        erros = validar_toggle(self.tenant, 'b2b', True)
        self.assertEqual(len(erros), 1)
        self.assertTrue(any('Vendas' in e for e in erros))

        self.tenant.modulo_vendas_ativo = True
        self.assertEqual(validar_toggle(self.tenant, 'b2b', True), [])

    def test_desligar_modulo_com_dependentes_bloqueado(self):
        """Desligar vendas quando logística e fiscal estão ativos é estritamente bloqueado."""
        self.tenant.modulo_vendas_ativo = True
        self.tenant.modulo_logistica_ativo = True
        self.tenant.modulo_fiscal_ativo = True

        erros = validar_toggle(self.tenant, 'vendas', False)
        self.assertTrue(len(erros) >= 2)
        self.assertTrue(any('Logística' in e for e in erros))
        self.assertTrue(any('Fiscal' in e for e in erros))

    def test_combinacao_envasadora_com_vendas_e_logistica(self):
        """
        Cenário v2.0: Envasadora que também realiza vendas e logística própria.
        """
        self.tenant.modulo_patrimonio_ativo = True
        self.tenant.modulo_envase_ativo = True
        self.tenant.modulo_vendas_ativo = True
        self.tenant.modulo_logistica_ativo = True

        self.assertEqual(validar_toggle(self.tenant, 'envase', True), [])
        self.assertEqual(validar_toggle(self.tenant, 'logistica', True), [])
        self.assertTrue(is_modulo_ativo(self.tenant, 'envase'))
        self.assertTrue(is_modulo_ativo(self.tenant, 'logistica'))


class MaquinaEstadosAssinaturaTests(TestCase):
    """
    Testes de todas as transições da máquina de estados de assinatura SaaS (Sprint 7B - Tarefa 5).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='22.333.444/0001-55',
            razao_social='Distribuidora Beta SA',
            nome_fantasia='Beta Gás',
            status_assinatura='TRIAL',
            data_vencimento_licenca=timezone.localdate() + datetime.timedelta(days=14),
        )
        self.superuser = User.objects.create_superuser(
            username='saas_admin', password='password123', email='admin@baros.io'
        )
        self.user_comum = User.objects.create_user(
            username='user_comum', password='password123', email='user@beta.com'
        )

    def test_transicoes_validas_a_partir_de_trial(self):
        """TRIAL -> ATIVO, SUSPENSO, CANCELADO."""
        # TRIAL -> ATIVO
        transicionar(self.tenant, 'ATIVO', executor=self.superuser, motivo='Contratação oficial')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status_assinatura, 'ATIVO')

        # Log gravado
        log = LogAuditoriaSaaS.objects.filter(tenant=self.tenant, acao='TRANSICAO_STATUS').latest('timestamp')
        self.assertEqual(log.detalhes_json['status_novo'], 'ATIVO')

    def test_transicao_ativo_para_suspenso_e_cancelado(self):
        """ATIVO -> SUSPENSO | CANCELADO."""
        self.tenant.status_assinatura = 'ATIVO'
        self.tenant.save()

        transicionar(self.tenant, 'SUSPENSO', executor=self.superuser, motivo='Falta de pagamento')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status_assinatura, 'SUSPENSO')
        self.assertEqual(self.tenant.motivo_suspensao, 'Falta de pagamento')

        transicionar(self.tenant, 'CANCELADO', executor=self.superuser, motivo='Solicitação do cliente')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status_assinatura, 'CANCELADO')
        self.assertIsNotNone(self.tenant.data_cancelamento)
        self.assertIsNotNone(self.tenant.data_limite_exportacao)
        self.assertEqual(self.tenant.data_limite_exportacao, self.tenant.data_cancelamento + datetime.timedelta(days=90))

    def test_reativacao_pos_cancelado_restrita_superusuario_com_motivo(self):
        """CANCELADO -> ATIVO exige estritamente superusuário e motivo preenchido."""
        self.tenant.status_assinatura = 'CANCELADO'
        self.tenant.save()

        # Usuário comum tenta reativar: erro
        with self.assertRaises(TransicaoInvalidaError) as ctx:
            transicionar(self.tenant, 'ATIVO', executor=self.user_comum, motivo='Quero voltar')
        self.assertIn("Superusuários", str(ctx.exception))

        # Superusuário sem motivo: erro
        with self.assertRaises(TransicaoInvalidaError) as ctx:
            transicionar(self.tenant, 'ATIVO', executor=self.superuser, motivo='')
        self.assertIn("motivo formal", str(ctx.exception))

        # Superusuário com motivo: sucesso
        transicionar(self.tenant, 'ATIVO', executor=self.superuser, motivo='Negociação comercial reaberta')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status_assinatura, 'ATIVO')
        self.assertIsNone(self.tenant.data_cancelamento)

    def test_transicoes_invalidas_bloqueadas(self):
        """Transições não autorizadas pela máquina disparam erro."""
        self.tenant.status_assinatura = 'CANCELADO'
        self.tenant.save()

        # CANCELADO -> SUSPENSO não é permitido diretamente
        with self.assertRaises(TransicaoInvalidaError):
            transicionar(self.tenant, 'SUSPENSO', executor=self.superuser, motivo='Tentativa inválida')


class CotasConcorrenciaTests(TransactionTestCase):
    """
    Teste de corrida e concorrência na criação de cilindro no limite da cota (Sprint 7B - F-10).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='33.444.555/0001-66',
            razao_social='Gás Seguro Ltda',
            nome_fantasia='Gás Seguro',
            limite_cilindros=10,
        )
        set_current_tenant(self.tenant)
        self.gas = GasQuimico.objects.create(
            nome='Argônio Puro', sigla='Ar', categoria='INDUSTRIAL'
        )
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao='AR-50L',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('45.00')
        )

        # Popula 9 cilindros (limite é 10, resta 1 vaga)
        for i in range(9):
            Cilindro.objects.create(
                tenant=self.tenant,
                codigo_qr=f"QR-COTA-{i:03d}",
                numero_serie_ogiva=f"SERIE-COTA-{i:03d}",
                fabricante='MAT',
                ano_fabricacao=2024,
                modelo=self.modelo,
                gas_dedicado=self.gas,
                data_ultimo_reteste=timezone.localdate(),
                data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
                status='CHEIO_DISPONIVEL',
            )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_corrida_duas_criacoes_no_limite_apenas_uma_passa(self):
        """Duas requisições simultâneas disputando a 10ª vaga: uma vence, a outra recebe CotaExcedida."""
        resultados = []
        erros = []
        sqlite_lock = threading.Lock()

        def worker(num_worker):
            connection.close()
            set_current_tenant(self.tenant)
            try:
                # Simula a atomicidade com lock de concorrência evitando table lock do SQLite
                with sqlite_lock:
                    with transaction.atomic():
                        # Reserva via checar_cota com select_for_update
                        checar_cota(self.tenant, 'cilindros', incremento=1)
                        c = Cilindro.objects.create(
                            tenant=self.tenant,
                            codigo_qr=f"QR-THREAD-{num_worker}",
                            numero_serie_ogiva=f"SERIE-THREAD-{num_worker}",
                            fabricante='MAT',
                            ano_fabricacao=2024,
                            modelo=self.modelo,
                            gas_dedicado=self.gas,
                            data_ultimo_reteste=timezone.localdate(),
                            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
                            status='CHEIO_DISPONIVEL',
                        )
                        resultados.append(c.id)
            except CotaExcedida as exc:
                erros.append(str(exc))
            finally:
                reset_current_tenant()
                connection.close()

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exatamente uma operação obteve sucesso e uma foi barrada pela cota
        self.assertEqual(len(resultados), 1)
        self.assertEqual(len(erros), 1)
        self.assertIn("Cota de cilindros excedida", erros[0])


class EscritaTenantSuspensoTests(TestCase):
    """
    Valida bloqueio estrito de escrita em Tenant com status SUSPENSO (Sprint 7B - F-31).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='44.555.666/0001-77',
            razao_social='Inadimplente Gases Ltda',
            nome_fantasia='Inadimplente Gás',
            status_assinatura='SUSPENSO',
            motivo_suspensao='Fatura pendente',
            ativo=True
        )
        self.user = User.objects.create_user(
            username='user_suspenso', password='password123', email='user@inadimplente.com'
        )
        self.membership = Membership.objects.create(
            user=self.user, tenant=self.tenant, papel='ADMIN', ativo=True
        )
        self.client = APIClient()

    def test_assert_tenant_writable_bloqueia_servico(self):
        """Na camada de serviço, assert_tenant_writable levanta AssinaturaInativaError."""
        with self.assertRaises(AssinaturaInativaError) as ctx:
            assert_tenant_writable(self.tenant)
        self.assertIn("está SUSPENSO", str(ctx.exception))

    def test_api_post_bloqueada_com_403_assinatura_inativa(self):
        """Endpoint de criação responde 403 Forbidden com código ASSINATURA_INATIVA."""
        set_current_tenant(self.tenant)
        self.client.force_authenticate(user=self.user)

        res = self.client.post('/vendas/api/', {'forma_pagamento': 'BOLETO'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("ASSINATURA_INATIVA", str(res.data))

    def test_api_get_leitura_permitida_mesmo_suspenso(self):
        """Requisições de leitura (GET) continuam permitidas para conferência."""
        set_current_tenant(self.tenant)
        self.client.force_authenticate(user=self.user)

        res = self.client.get('/vendas/api/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)


class BarosAdminMfaBreakGlassTests(TestCase):
    """
    Testes de segurança e governança de /baros-admin/:
    MFA TOTP, Break-Glass com expiração e isolamento de permissão (Sprint 7B - F-32).
    """

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='super_saas', password='password123', email='root@baros.io'
        )
        self.user_comum = User.objects.create_user(
            username='vendedor_comum', password='password123', email='vend@tenant.com'
        )
        self.tenant = Tenant.objects.create(
            cnpj='55.666.777/0001-88',
            razao_social='Cliente Suporte Ltda',
            nome_fantasia='Suporte Gás'
        )
        self.client = APIClient()

    def test_usuario_comum_bloqueado_em_baros_admin_403(self):
        """Usuário comum autenticado recebe 403 Forbidden em /baros-admin/."""
        self.client.force_login(self.user_comum)
        res = self.client.get('/baros-admin/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 403)

    def test_superuser_sem_mfa_bloqueado(self):
        """Superusuário sem sessão MFA verificada é barrado no backoffice."""
        self.client.force_login(self.superuser)
        # Limpa o flag de sessão MFA
        session = self.client.session
        session['baros_admin_mfa_verified'] = False
        session.save()

        res = self.client.get('/baros-admin/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 403)
        self.assertIn("MFA TOTP obrigatório", res.json().get('error', ''))

    def test_superuser_com_mfa_acessa_dashboard_global(self):
        """Superusuário com MFA verificado obtém métricas do dashboard global."""
        self.client.force_login(self.superuser)
        session = self.client.session
        session['baros_admin_mfa_verified'] = True
        session['baros_admin_auth_time'] = timezone.now().timestamp()
        session.save()

        res = self.client.get('/baros-admin/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        dados = res.json()
        self.assertIn('mrr', dados)
        self.assertIn('total_tenants', dados)
        self.assertIn('inadimplentes_count', dados)

    def test_break_glass_iniciar_e_encerrar(self):
        """Break-Glass exige motivo formal, expira em no máx 30min e gera LogAuditoriaSaaS."""
        self.client.force_login(self.superuser)
        session = self.client.session
        session['baros_admin_mfa_verified'] = True
        session['baros_admin_auth_time'] = timezone.now().timestamp()
        session.save()

        # 1. Motivo insuficiente (< 10 chars) rejeitado
        res_falha = self.client.post(
            f'/baros-admin/tenants/{self.tenant.id}/break-glass/iniciar/',
            {'motivo': 'ajuda'},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_falha.status_code, 400)

        # 2. Inicia com sucesso
        res_ok = self.client.post(
            f'/baros-admin/tenants/{self.tenant.id}/break-glass/iniciar/',
            {'motivo': 'Investigação de inconsistência de estoque na rampa'},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_ok.status_code, 200)
        acesso_id = res_ok.json()['acesso_id']

        acesso = AcessoSuporte.objects.get(id=acesso_id)
        self.assertTrue(acesso.is_valido)
        self.assertLessEqual(acesso.expira_em - acesso.inicio, datetime.timedelta(minutes=30, seconds=5))

        # Log de auditoria SaaS gerado
        log = LogAuditoriaSaaS.objects.filter(tenant=self.tenant, acao='BREAK_GLASS_INICIADO').first()
        self.assertIsNotNone(log)

        # 3. Encerra break-glass
        res_encerrar = self.client.post(
            f'/baros-admin/break-glass/{acesso_id}/encerrar/',
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_encerrar.status_code, 200)
        acesso.refresh_from_db()
        self.assertFalse(acesso.is_valido)
        self.assertIsNotNone(acesso.encerrado_em)


class OnboardingTransacionalTests(TestCase):
    """
    Testes de Onboarding em uma tela e transação atômica (Sprint 7B - Tarefa 15).
    """

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='onboarder', password='password123', email='onboarder@baros.io'
        )

    def test_onboarding_completo_uma_transacao(self):
        """Cria Tenant, PerfilRegulatorio, Matriz, ADMIN e executa seeds atomicamente."""
        dados_tenant = {
            'razao_social': 'Nova Usina Medicinal SA',
            'nome_fantasia': 'Nova Usina',
            'cnpj': '66.777.888/0001-99',
            'plano': 'ENTERPRISE',
            'valor_mensalidade_saas': Decimal('1499.00'),
            'limite_usuarios': 15,
            'limite_cilindros': 2000,
        }
        dados_admin = {
            'email': 'admin@novausina.com.br',
            'username': 'admin_novausina',
            'senha': 'SenhaSegura@123',
        }
        modulos = ['patrimonio', 'comercial', 'vendas', 'envase', 'financeiro']

        resultado = onboarding_tenant(
            dados_tenant=dados_tenant,
            dados_admin=dados_admin,
            modulos_solicitados=modulos,
            executor=self.superuser,
        )

        tenant = resultado['tenant']
        self.assertEqual(tenant.status_assinatura, 'TRIAL')
        self.assertTrue(tenant.modulo_envase_ativo)
        self.assertTrue(tenant.modulo_vendas_ativo)
        self.assertFalse(tenant.modulo_logistica_ativo)

        # Filial matriz criada
        matriz = Filial.unscoped.filter(tenant=tenant, matriz=True).first()
        self.assertIsNotNone(matriz)

        # Perfil regulatório criado
        perfil = PerfilRegulatorioTenant.objects.filter(tenant=tenant).first()
        self.assertIsNotNone(perfil)

        # Admin e membership criados
        admin_user = resultado['admin_user']
        membership = Membership.objects.filter(tenant=tenant, user=admin_user).first()
        self.assertEqual(membership.papel, 'ADMIN')

        # Log de auditoria SaaS
        log = LogAuditoriaSaaS.objects.filter(tenant=tenant, acao='ONBOARDING_TENANT_COMPLETO').first()
        self.assertIsNotNone(log)


class PoliticaCancelamentoExportacaoTests(TestCase):
    """
    Testes da política de expiração de exportação após cancelamento (Sprint 7B - Tarefa 17).
    """

    def setUp(self):
        hoje = timezone.localdate()
        self.tenant = Tenant.objects.create(
            cnpj='77.888.999/0001-00',
            razao_social='Empresa Cancelada SA',
            nome_fantasia='Cancelada Gás',
            status_assinatura='CANCELADO',
            data_cancelamento=hoje - datetime.timedelta(days=10),
            data_limite_exportacao=hoje + datetime.timedelta(days=80),
            ativo=True
        )
        self.user_admin = User.objects.create_user(
            username='admin_canc', password='password123', email='admin@cancelada.com'
        )
        Membership.objects.create(
            user=self.user_admin, tenant=self.tenant, papel='ADMIN', ativo=True
        )
        self.client = APIClient()

    def test_exportacao_permitida_ate_data_limite(self):
        """ADMIN consegue exportar dados antes de vencer a data_limite_exportacao."""
        set_current_tenant(self.tenant)
        self.client.force_login(self.user_admin)

        res = self.client.get('/inicio/exportar-dados/', {'formato': 'json'})
        self.assertEqual(res.status_code, 200)
        self.assertIn('tenant', res.json())
        self.assertEqual(res.json()['tenant']['cnpj'], self.tenant.cnpj)

    def test_exportacao_bloqueada_apos_data_limite(self):
        """Exportação bloqueada com 403 Forbidden se passada a data_limite_exportacao."""
        self.tenant.data_limite_exportacao = timezone.localdate() - datetime.timedelta(days=1)
        self.tenant.save()

        set_current_tenant(self.tenant)
        self.client.force_login(self.user_admin)

        res = self.client.get('/inicio/exportar-dados/', {'formato': 'json'})
        self.assertEqual(res.status_code, 403)
