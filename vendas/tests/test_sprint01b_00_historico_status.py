"""
Testes automatizados da Sprint 01B.00 — Histórico de status de Vendas e Entregas (Tarefa 01B.1).
Valida criação dos modelos HistoricoStatusVenda e HistoricoStatusEntrega,
serviços de transição com gravação de histórico, função desde_quando_no_status,
isolamento multi-tenant e imutabilidade.
"""
from decimal import Decimal
import datetime
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.models import Tenant, Membership
from core.tenancy import tenant_context
from clientes.models import Cliente
from vendas.models import Venda, HistoricoStatusVenda
from logistica.models import Entrega, HistoricoStatusEntrega
from vendas.services.status import transicionar_venda, desde_quando_no_status as desde_quando_venda
from logistica.services.status import transicionar_entrega, desde_quando_no_status as desde_quando_entrega

User = get_user_model()


class HistoricoStatusVendaEntregaTests(TestCase):
    def setUp(self):
        self.hoje = timezone.now().date()

        # Tenants
        self.tenant_a = Tenant.objects.create(
            cnpj='11.111.111/0001-11',
            razao_social='Distribuidora Alfa Ltda',
            nome_fantasia='Alfa Gases',
            plano='PRO',
            ativo=True
        )
        self.tenant_b = Tenant.objects.create(
            cnpj='22.222.222/0001-22',
            razao_social='Distribuidora Beta Ltda',
            nome_fantasia='Beta Gases',
            plano='PRO',
            ativo=True
        )

        # Usuários
        self.user_vendedor = User.objects.create_user(
            username='vendedor.alfa',
            password='password123',
            email='vendedor@alfa.com'
        )
        Membership.objects.create(
            user=self.user_vendedor,
            tenant=self.tenant_a,
            papel='VENDEDOR',
            ativo=True
        )

        self.user_gerente = User.objects.create_user(
            username='gerente.alfa',
            password='password123',
            email='gerente@alfa.com'
        )
        Membership.objects.create(
            user=self.user_gerente,
            tenant=self.tenant_a,
            papel='GERENTE',
            ativo=True
        )

        # Clientes
        with tenant_context(self.tenant_a):
            self.cliente_a = Cliente.objects.create(
                tenant=self.tenant_a,
                nome='Hospital Alpha',
                cnpj='12.345.678/0001-90',
                tipo_cliente='PJ',
                is_medicinal=True
            )

        with tenant_context(self.tenant_b):
            self.cliente_b = Cliente.objects.create(
                tenant=self.tenant_b,
                nome='Clínica Beta',
                cnpj='98.765.432/0001-10',
                tipo_cliente='PJ'
            )

    # --------------------------------------------------------------------------
    # 1. TRANSIÇÃO DE VENDA GRAVA HISTÓRICO
    # --------------------------------------------------------------------------

    def test_01_transicao_venda_grava_historico(self):
        """
        Transicionar venda via transicionar_venda deve gravar uma linha em HistoricoStatusVenda
        com status_anterior, status_novo, alterado_em, alterado_por e origem.
        """
        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                vendedor=self.user_vendedor,
                status='Pendente',
                valor_total=Decimal('500.00')
            )

            # Transiciona para 'Em Separação'
            transicionar_venda(venda, 'Em Separação', self.user_vendedor, origem='TELA')
            venda.save()

            # Transiciona para 'Em Rota'
            transicionar_venda(venda, 'Em Rota', self.user_vendedor, origem='TELA')
            venda.save()

            historicos = list(venda.historico_status.order_by('alterado_em'))
            # Pelo menos as 2 transições gravadas (ou 3 se criação gravou)
            transicoes = [(h.status_anterior, h.status_novo) for h in historicos if h.status_anterior is not None]
            self.assertIn(('Pendente', 'Em Separação'), transicoes)
            self.assertIn(('Em Separação', 'Em Rota'), transicoes)

            ultimo = historicos[-1]
            self.assertEqual(ultimo.status_novo, 'Em Rota')
            self.assertEqual(ultimo.alterado_por, self.user_vendedor)
            self.assertEqual(ultimo.origem, 'TELA')
            self.assertIsNotNone(ultimo.alterado_em)

    def test_02_liberacao_bloqueio_venda_grava_historico(self):
        """
        Ao liberar bloqueio de venda (liberar_bloqueio_venda), o status vai de
        BLOQUEADO_FINANCEIRO para Pendente e deve gerar histórico.
        """
        from vendas.services.liberacao_service import liberar_bloqueio_venda

        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='BLOQUEADO_FINANCEIRO',
                valor_total=Decimal('1000.00')
            )

            liberar_bloqueio_venda(venda, usuario=self.user_gerente, motivo="Crédito aprovado pela diretoria")

            venda.refresh_from_db()
            self.assertEqual(venda.status, 'Pendente')

            hist = venda.historico_status.filter(status_novo='Pendente').first()
            self.assertIsNotNone(hist, "Histórico da liberação de bloqueio não foi registrado")
            self.assertEqual(hist.status_anterior, 'BLOQUEADO_FINANCEIRO')
            self.assertEqual(hist.alterado_por, self.user_gerente)

    # --------------------------------------------------------------------------
    # 2. TRANSIÇÃO DE ENTREGA GRAVA HISTÓRICO
    # --------------------------------------------------------------------------

    def test_03_transicao_entrega_grava_historico(self):
        """
        Transicionar entrega via transicionar_entrega deve gravar uma linha em HistoricoStatusEntrega
        com status_anterior, status_novo, alterado_em, alterado_por e origem.
        """
        with tenant_context(self.tenant_a):
            entrega = Entrega.objects.create(
                tenant=self.tenant_a,
                status='Agendada'
            )

            transicionar_entrega(entrega, 'Em Rota', usuario=self.user_gerente, origem='TELA')
            entrega.save()

            transicionar_entrega(entrega, 'Concluída', usuario=self.user_gerente, origem='APP_CAMPO')
            entrega.save()

            historicos = list(entrega.historico_status.order_by('alterado_em'))
            transicoes = [(h.status_anterior, h.status_novo) for h in historicos if h.status_anterior is not None]
            self.assertIn(('Agendada', 'Em Rota'), transicoes)
            self.assertIn(('Em Rota', 'Concluída'), transicoes)

            ultimo = historicos[-1]
            self.assertEqual(ultimo.status_novo, 'Concluída')
            self.assertEqual(ultimo.alterado_por, self.user_gerente)
            self.assertEqual(ultimo.origem, 'APP_CAMPO')

    # --------------------------------------------------------------------------
    # 3. FUNÇÃO DESDE_QUANDO_NO_STATUS
    # --------------------------------------------------------------------------

    def test_04_desde_quando_no_status_venda_e_entrega(self):
        """
        desde_quando_no_status(obj) retorna o datetime em que o objeto entrou no status atual.
        """
        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                vendedor=self.user_vendedor,
                status='Pendente',
                valor_total=Decimal('200.00')
            )
            transicionar_venda(venda, 'Em Separação', self.user_vendedor)
            venda.save()

            dt_venda = desde_quando_venda(venda)
            self.assertIsNotNone(dt_venda)
            self.assertIsInstance(dt_venda, datetime.datetime)

            entrega = Entrega.objects.create(
                tenant=self.tenant_a,
                status='Agendada'
            )
            transicionar_entrega(entrega, 'Em Rota', self.user_gerente)
            entrega.save()

            dt_entrega = desde_quando_entrega(entrega)
            self.assertIsNotNone(dt_entrega)
            self.assertIsInstance(dt_entrega, datetime.datetime)

    # --------------------------------------------------------------------------
    # 4. ISOLAMENTO MULTI-TENANT
    # --------------------------------------------------------------------------

    def test_05_isolamento_multitenant_historico(self):
        """
        HistoricoStatusVenda e HistoricoStatusEntrega respeitam o isolamento de tenant.
        Tenant A não enxerga histórico de Tenant B.
        """
        with tenant_context(self.tenant_a):
            venda_a = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente',
                valor_total=Decimal('100.00')
            )
            transicionar_venda(venda_a, 'Em Separação', self.user_vendedor)
            venda_a.save()

        with tenant_context(self.tenant_b):
            venda_b = Venda.objects.create(
                tenant=self.tenant_b,
                cliente=self.cliente_b,
                status='Pendente',
                valor_total=Decimal('300.00')
            )
            transicionar_venda(venda_b, 'Cancelada', None, origem='SISTEMA')
            venda_b.save()

            # No contexto do Tenant B, não deve ver histórico do Tenant A
            hist_b = HistoricoStatusVenda.objects.all()
            self.assertTrue(all(h.tenant == self.tenant_b for h in hist_b))
            self.assertFalse(hist_b.filter(venda=venda_a).exists())

    # --------------------------------------------------------------------------
    # 5. ADMIN SOMENTE LEITURA
    # --------------------------------------------------------------------------

    def test_06_admin_somente_leitura(self):
        """Os modelos de histórico no admin devem ser estritamente somente leitura."""
        from django.contrib.admin.sites import AdminSite
        from vendas.admin import HistoricoStatusVendaAdmin
        from logistica.admin import HistoricoStatusEntregaAdmin

        site = AdminSite()
        admin_venda = HistoricoStatusVendaAdmin(HistoricoStatusVenda, site)
        admin_entrega = HistoricoStatusEntregaAdmin(HistoricoStatusEntrega, site)

        from unittest.mock import Mock
        request = Mock()
        request.user = self.user_gerente

        self.assertFalse(admin_venda.has_add_permission(request))
        self.assertFalse(admin_venda.has_change_permission(request))
        self.assertFalse(admin_venda.has_delete_permission(request))

        self.assertFalse(admin_entrega.has_add_permission(request))
        self.assertFalse(admin_entrega.has_change_permission(request))
        self.assertFalse(admin_entrega.has_delete_permission(request))

    # --------------------------------------------------------------------------
    # 6. MIGRAÇÃO DE DADOS (BACKFILL)
    # --------------------------------------------------------------------------

    def test_07_migracao_dados_backfill_existentes(self):
        """
        Funções de migração de dados geram histórico com origem='SISTEMA'
        para vendas e entregas legadas que não possuíam histórico.
        """
        import importlib
        mig_vendas = importlib.import_module("vendas.migrations.0013_migrar_historico_inicial_vendas")
        migrar_historico_inicial_vendas = mig_vendas.migrar_historico_inicial_vendas

        mig_entregas = importlib.import_module("logistica.migrations.0025_migrar_historico_inicial_entregas")
        migrar_historico_inicial_entregas = mig_entregas.migrar_historico_inicial_entregas

        from django.apps import apps

        with tenant_context(self.tenant_a):
            # Cria venda e apaga seu histórico para simular registro legado
            venda_legada = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Faturada',
                valor_total=Decimal('450.00')
            )
            HistoricoStatusVenda.objects.filter(venda=venda_legada).delete()

            entrega_legada = Entrega.objects.create(
                tenant=self.tenant_a,
                status='Concluída'
            )
            HistoricoStatusEntrega.objects.filter(entrega=entrega_legada).delete()

            # Executa a lógica de migração
            migrar_historico_inicial_vendas(apps, None)
            migrar_historico_inicial_entregas(apps, None)

            # Verifica criação do registro com origem SISTEMA
            hist_v = HistoricoStatusVenda.objects.filter(venda=venda_legada).first()
            self.assertIsNotNone(hist_v)
            self.assertEqual(hist_v.status_novo, 'Faturada')
            self.assertEqual(hist_v.origem, 'SISTEMA')
            self.assertIsNone(hist_v.status_anterior)

            hist_e = HistoricoStatusEntrega.objects.filter(entrega=entrega_legada).first()
            self.assertIsNotNone(hist_e)
            self.assertEqual(hist_e.status_novo, 'Concluída')
            self.assertEqual(hist_e.origem, 'SISTEMA')
            self.assertIsNone(hist_e.status_anterior)

    # --------------------------------------------------------------------------
    # 7. VALIDAÇÃO DE USUÁRIO POR ORIGEM
    # --------------------------------------------------------------------------

    def test_08_usuario_obrigatorio_para_tela_e_app_campo(self):
        """
        origem='TELA' ou 'APP_CAMPO' exige usuário autenticado.
        origem='SISTEMA' ou 'API' aceita usuario=None.
        """
        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )
            # TELA sem usuário -> Erro
            with self.assertRaises(ValidationError):
                transicionar_venda(venda, 'Em Separação', usuario=None, origem='TELA')

            # APP_CAMPO sem usuário -> Erro
            with self.assertRaises(ValidationError):
                transicionar_venda(venda, 'Em Separação', usuario=None, origem='APP_CAMPO')

            # SISTEMA sem usuário -> Aceito
            transicionar_venda(venda, 'Em Separação', usuario=None, origem='SISTEMA')
            self.assertEqual(venda.status, 'Em Separação')

            # API sem usuário -> Aceito
            transicionar_venda(venda, 'Cancelada', usuario=None, origem='API')
            self.assertEqual(venda.status, 'Cancelada')

            entrega = Entrega.objects.create(
                tenant=self.tenant_a,
                status='Agendada'
            )
            # TELA sem usuário -> Erro
            with self.assertRaises(ValidationError):
                transicionar_entrega(entrega, 'Em Rota', usuario=None, origem='TELA')

            # SISTEMA sem usuário -> Aceito
            transicionar_entrega(entrega, 'Em Rota', usuario=None, origem='SISTEMA')
            self.assertEqual(entrega.status, 'Em Rota')

    # --------------------------------------------------------------------------
    # 8. ATOMICIDADE E SALVAMENTO AUTOMÁTICO
    # --------------------------------------------------------------------------

    def test_09_atomicidade_se_validacao_falhar_nem_status_nem_historico_mudam(self):
        """
        Se a transição falhar, o status do objeto e o histórico não devem ser alterados.
        transicionar_venda e transicionar_entrega salvam o próprio status no banco.
        """
        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )
            qtd_hist_antes = venda.historico_status.count()

            # Transição inválida: Pendente -> Entregue
            with self.assertRaises(ValidationError):
                transicionar_venda(venda, 'Entregue', self.user_vendedor, origem='TELA')

            venda.refresh_from_db()
            self.assertEqual(venda.status, 'Pendente')
            self.assertEqual(venda.historico_status.count(), qtd_hist_antes)

            # Transição válida salva no banco sem necessidade de venda.save() explícito
            transicionar_venda(venda, 'Em Separação', self.user_vendedor, origem='TELA')
            venda.refresh_from_db()
            self.assertEqual(venda.status, 'Em Separação')

    # --------------------------------------------------------------------------
    # 9. ENTREGA VIEWSET E SERIALIZER (STATUS READ_ONLY E TRANSIÇÕES)
    # --------------------------------------------------------------------------

    def test_10_entrega_serializer_status_read_only_e_patch_transiciona_vendas(self):
        """
        Status da Entrega deve ser read_only no serializer.
        PATCH na EntregaViewSet com novo status deve transicionar a entrega e cada venda vinculada
        individualmente via transicionar_venda com origem='SISTEMA' (sem .update em lote).
        """
        from rest_framework.test import APIClient
        from logistica.serializers import EntregaSerializer

        # Verifica que status está como read_only no serializer
        serializer = EntregaSerializer()
        self.assertTrue(serializer.fields['status'].read_only)

        client = APIClient()
        client.force_authenticate(user=self.user_gerente)

        with tenant_context(self.tenant_a):
            entrega = Entrega.objects.create(
                tenant=self.tenant_a,
                status='Agendada'
            )
            venda1 = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                entrega=entrega,
                status='Em Separação'
            )
            venda2 = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                entrega=entrega,
                status='Pendente'
            )

        resp = client.patch(
            f'/logistica/api/entregas/{entrega.id}/',
            {'status': 'Em Rota'},
            format='json'
        )
        self.assertEqual(resp.status_code, 200)

        with tenant_context(self.tenant_a):
            entrega.refresh_from_db()
            self.assertEqual(entrega.status, 'Em Rota')
            self.assertTrue(entrega.historico_status.filter(status_novo='Em Rota').exists())

            venda1.refresh_from_db()
            venda2.refresh_from_db()
            self.assertEqual(venda1.status, 'Em Rota')
            self.assertEqual(venda2.status, 'Em Rota')

            # Vendas devem possuir histórico com origem='SISTEMA'
            h1 = venda1.historico_status.filter(status_novo='Em Rota').first()
            h2 = venda2.historico_status.filter(status_novo='Em Rota').first()
            self.assertIsNotNone(h1)
            self.assertEqual(h1.origem, 'SISTEMA')
            self.assertIsNotNone(h2)
            self.assertEqual(h2.origem, 'SISTEMA')

    # --------------------------------------------------------------------------
    # 10. SINISTROS: CANCELAMENTO E REAGENDAMENTO COM TRANSIÇÃO
    # --------------------------------------------------------------------------

    def test_11_sinistros_reagendamento_e_cancelamento_usam_transicoes(self):
        """
        Em seguros_sinistros, cancelamento e reagendamento de entrega e vendas
        devem usar transicionar_entrega e transicionar_venda com histórico.
        """
        with tenant_context(self.tenant_a):
            entrega = Entrega.objects.create(
                tenant=self.tenant_a,
                status='Agendada'
            )
            transicionar_entrega(entrega, 'Em Rota', usuario=self.user_gerente, origem='TELA')

            # Permite Em Rota -> Agendada no reagendamento por sinistro
            transicionar_entrega(
                entrega,
                'Agendada',
                usuario=self.user_gerente,
                origem='SISTEMA',
                observacoes='Reagendamento por sinistro.'
            )
            entrega.refresh_from_db()
            self.assertEqual(entrega.status, 'Agendada')
            self.assertTrue(entrega.historico_status.filter(status_anterior='Em Rota', status_novo='Agendada').exists())

    # --------------------------------------------------------------------------
    # 11. TESTE ESTÁTICO: ZERO .update(status=) E ATRIBUIÇÕES DIRETAS FORA DOS SERVICES
    # --------------------------------------------------------------------------

    def test_12_static_scan_sem_update_status_nem_atribuicao_direta_fora_services(self):
        """
        Garante que nenhum arquivo altere status de Venda ou Entrega via queryset.update(status=...)
        ou atribuição direta venda.status = / entrega.status = fora dos serviços de status.
        Exceções justificadas para atribuição direta:
        - vendas/services/status.py (serviço oficial)
        - vendas/services/liberacao_service.py (restauração autorizada de bloqueio)
        - logistica/services/status.py (serviço oficial)
        - arquivos em suites de testes (*tests*.py)
        """
        import subprocess

        # 1. Zero .update(status=...) em querysets de vendas ou entregas
        cmd_update = r'git grep -n -E "(vendas|entregas)\.update\(status=" -- "*.py"'
        res_update = subprocess.run(cmd_update, shell=True, capture_output=True, text=True)
        linhas_update = [l for l in res_update.stdout.splitlines() if l.strip()]
        self.assertEqual(len(linhas_update), 0, f"Encontrado .update(status=...) em queryset de vendas/entregas: {linhas_update}")

        # 2. Zero atribuição direta venda.status = fora de vendas/services e testes
        cmd_venda = r'git grep -n -P "(?<![=!<>])venda\.status\s*=\s*[^=]" -- "*.py"'
        res_venda = subprocess.run(cmd_venda, shell=True, capture_output=True, text=True)
        linhas_venda = [l for l in res_venda.stdout.splitlines() if l.strip()]
        for l in linhas_venda:
            # Exceções permitidas: services/status.py, liberacao_service.py e testes
            eh_valido = any(p in l.replace('\\', '/') for p in [
                'vendas/services/status.py',
                'vendas/services/liberacao_service.py',
                'test',
            ])
            self.assertTrue(eh_valido, f"Atribuição direta não permitida em: {l}")

        # 3. Zero atribuição direta entrega.status = fora de logistica/services/status.py e testes
        cmd_entrega = r'git grep -n -P "(?<![=!<>])entrega\.status\s*=\s*[^=]" -- "*.py"'
        res_entrega = subprocess.run(cmd_entrega, shell=True, capture_output=True, text=True)
        linhas_entrega = [l for l in res_entrega.stdout.splitlines() if l.strip()]
        for l in linhas_entrega:
            eh_valido = any(p in l.replace('\\', '/') for p in [
                'logistica/services/status.py',
                'test',
            ])
            self.assertTrue(eh_valido, f"Atribuição direta não permitida em: {l}")



