"""
Sprint 01.01 — Ativos 360°: filtros que funcionam, contadores e drawer seguro.
Testes unitários, estáticos, de integração e de contagem de queries.
"""
import datetime
from decimal import Decimal
from pathlib import Path
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Membership, Tenant
from core.tenancy import tenant_context
from produtos.models import Cilindro, GasQuimico, ModeloCilindro

User = get_user_model()


class AtivosDrawerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-81',
            razao_social='Gás Norte Ltda',
            nome_fantasia='Gás Norte',
            modulo_envase_ativo=True,
        )
        self.outro_tenant = Tenant.objects.create(
            cnpj='22.333.444/0001-55',
            razao_social='Outra Empresa Ltda',
            nome_fantasia='Outra Empresa',
            modulo_envase_ativo=True,
        )

        self.gas_o2 = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2-MED',
            categoria='MEDICINAL'
        )

        self.hoje = timezone.localdate()

        self.gerente = self._usuario('gerente.ativos', 'GERENTE', tenant=self.tenant)
        self.vendedor = self._usuario('vendedor.ativos', 'VENDEDOR', tenant=self.tenant)
        self.superusuario = User.objects.create_superuser('admin.ativos', 'admin@baros.test', 'Senha-123456')

        with tenant_context(self.tenant):
            self.modelo = ModeloCilindro.objects.create(
                descricao='Aço 50L 200bar',
                volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('62.00'),
                periodicidade_reteste_anos=5,
            )

        self.client = APIClient()

    def _usuario(self, username, papel, tenant):
        user = User.objects.create_user(username=username, password='Senha-123456')
        Membership.objects.create(user=user, tenant=tenant, papel=papel, ativo=True)
        return user

    def _criar_cilindro(self, tenant=None, **kwargs):
        defaults = {
            'tenant': tenant or self.tenant,
            'ano_fabricacao': 2020,
            'data_ultimo_reteste': datetime.date(2020, 1, 1),
            'data_proximo_reteste': self.hoje + datetime.timedelta(days=365),
            'gas_dedicado': self.gas_o2,
            'modelo': self.modelo,
            'status': 'CHEIO_DISPONIVEL',
        }
        defaults.update(kwargs)
        return Cilindro.objects.create(**defaults)

    # --------------------------------------------------------------------------
    # 1. Testes que devem falhar ANTES da implementação
    # --------------------------------------------------------------------------
    def test_estatico_cilindros_drawer_nao_contem_innerhtml_com_interpolacao(self):
        """
        Teste estático de segurança contra XSS:
        cilindros_drawer.js NÃO pode conter atribuição a innerHTML com interpolação de template string `${...}`
        nem innerHTML atribuindo template string `.innerHTML = `...`.
        """
        js_path = Path(settings.BASE_DIR) / 'produtos' / 'static' / 'produtos' / 'js' / 'cilindros_drawer.js'
        self.assertTrue(js_path.exists(), f"Arquivo não encontrado: {js_path}")
        conteudo = js_path.read_text(encoding='utf-8')

        # Não deve ter innerHTML = `
        self.assertNotIn(
            "innerHTML = `",
            conteudo,
            "cilindros_drawer.js não deve conter 'innerHTML = `' (template string direta)"
        )

        padrao_xss = re.compile(r'innerHTML\s*=\s*`[^`]*\$\{', re.MULTILINE)
        matches = padrao_xss.findall(conteudo)
        self.assertEqual(
            len(matches),
            0,
            f"Encontradas {len(matches)} ocorrências inseguras de innerHTML com template string em cilindros_drawer.js"
        )

    def test_filtro_reteste_ate_dias_unificado_com_home(self):
        """
        reteste_ate_dias=30 devolve vencidos e os que vencem em 30 dias (excluindo BAIXADO),
        e a contagem bate com o critério da Home.
        """
        from produtos.services.reteste import filtro_reteste_proximo_ou_vencido

        with tenant_context(self.tenant):
            # Cilindro 1: vencido há 10 dias
            c1 = self._criar_cilindro(
                codigo_qr='CIL-VENC-1',
                numero_serie_ogiva='SR-VENC-1',
                data_proximo_reteste=self.hoje - datetime.timedelta(days=10)
            )
            # Cilindro 2: vencendo em 15 dias
            c2 = self._criar_cilindro(
                codigo_qr='CIL-VENC-2',
                numero_serie_ogiva='SR-VENC-2',
                data_proximo_reteste=self.hoje + datetime.timedelta(days=15)
            )
            # Cilindro 3: vencendo em 45 dias (> 30 dias, fora do filtro de 30)
            c3 = self._criar_cilindro(
                codigo_qr='CIL-OK-3',
                numero_serie_ogiva='SR-OK-3',
                data_proximo_reteste=self.hoje + datetime.timedelta(days=45)
            )
            # Cilindro 4: vencido há 5 dias, mas BAIXADO (não deve contar nem aparecer)
            c4 = self._criar_cilindro(
                codigo_qr='CIL-BAIX-4',
                numero_serie_ogiva='SR-BAIX-4',
                status='BAIXADO',
                data_proximo_reteste=self.hoje - datetime.timedelta(days=5)
            )
            # Cilindro 5: reteste regular no ano que vem (> 30 dias)
            c5 = self._criar_cilindro(
                codigo_qr='CIL-LONGE-5',
                numero_serie_ogiva='SR-LONGE-5',
                data_proximo_reteste=self.hoje + datetime.timedelta(days=365)
            )

        # 1. Validação via função de critério compartilhado
        with tenant_context(self.tenant):
            filtro = filtro_reteste_proximo_ou_vencido(dias=30, data_referencia=self.hoje)
            qs_filtrada = Cilindro.objects.filter(filtro)
            self.assertEqual(qs_filtrada.count(), 2)
            pks_retornadas = set(qs_filtrada.values_list('codigo_qr', flat=True))
            self.assertEqual(pks_retornadas, {'CIL-VENC-1', 'CIL-VENC-2'})

        # 2. Validação via API do ViewSet com reteste_ate_dias=30
        self.client.force_authenticate(self.gerente)
        resp = self.client.get('/produtos/api/cilindros/?reteste_ate_dias=30')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        dados = resp.json()
        resultados = dados.get('results', dados) if isinstance(dados, dict) else dados
        self.assertEqual(len(resultados), 2)
        qrs_api = {item['codigo_qr'] for item in resultados}
        self.assertEqual(qrs_api, {'CIL-VENC-1', 'CIL-VENC-2'})

    def test_action_resumo_contagens_e_isolamento_tenant(self):
        """
        Action GET /produtos/api/cilindros/resumo/ retorna contagens agregadas da frota,
        respeita o isolamento multi-tenant e executa em no máximo 3 consultas SQL.
        """
        with tenant_context(self.tenant):
            self._criar_cilindro(codigo_qr='C-CHEIO', numero_serie_ogiva='S1', status='CHEIO_DISPONIVEL')
            self._criar_cilindro(codigo_qr='C-CLIENTE', numero_serie_ogiva='S2', status='EM_POSSE_CLIENTE')
            self._criar_cilindro(codigo_qr='C-TRIAGEM', numero_serie_ogiva='S3', status='VAZIO_TRIAGEM')
            self._criar_cilindro(codigo_qr='C-ROTA', numero_serie_ogiva='S4', status='RESERVADO_ROTA')
            self._criar_cilindro(codigo_qr='C-RETESTE', numero_serie_ogiva='S5', status='EM_RETESTE')
            self._criar_cilindro(codigo_qr='C-BLOQ', numero_serie_ogiva='S6', status='CHEIO_DISPONIVEL', bloqueio_sanitario=True)
            self._criar_cilindro(
                codigo_qr='C-VENCIDO', numero_serie_ogiva='S7', status='CHEIO_DISPONIVEL',
                data_proximo_reteste=self.hoje - datetime.timedelta(days=5)
            )
            self._criar_cilindro(
                codigo_qr='C-VENC-30D', numero_serie_ogiva='S8', status='CHEIO_DISPONIVEL',
                data_proximo_reteste=self.hoje + datetime.timedelta(days=10)
            )
            # Baixado (não deve contar em reteste vencido nem 30 dias)
            self._criar_cilindro(
                codigo_qr='C-BAIX', numero_serie_ogiva='S9', status='BAIXADO',
                data_proximo_reteste=self.hoje - datetime.timedelta(days=20)
            )

        # Outro tenant com cilindros para verificar isolamento
        with tenant_context(self.outro_tenant):
            self._criar_cilindro(tenant=self.outro_tenant, codigo_qr='C-OUTRO-1', numero_serie_ogiva='SO1', status='CHEIO_DISPONIVEL')
            self._criar_cilindro(tenant=self.outro_tenant, codigo_qr='C-OUTRO-2', numero_serie_ogiva='SO2', status='CHEIO_DISPONIVEL', bloqueio_sanitario=True)

        self.client.force_authenticate(self.gerente)
        with CaptureQueriesContext(connection) as queries:
            resp = self.client.get('/produtos/api/cilindros/resumo/')
            self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Deve executar em no máximo 3 consultas SQL reais (desconsiderando SAVEPOINTs da transação de teste)
        consultas_reais = [
            q for q in queries
            if not q['sql'].startswith('SAVEPOINT') and not q['sql'].startswith('RELEASE')
        ]
        self.assertLessEqual(len(consultas_reais), 3, f"Muitas consultas no resumo: {len(consultas_reais)}")

        dados = resp.json()
        # Tenant A tem 9 cilindros no total
        self.assertEqual(dados['total'], 9)
        # CHEIO_DISPONIVEL: C-CHEIO, C-BLOQ, C-VENCIDO, C-VENC-30D -> 4
        self.assertEqual(dados['cheios_patio'], 4)
        self.assertEqual(dados['em_clientes'], 1)
        self.assertEqual(dados['vazios_triagem'], 1)
        self.assertEqual(dados['em_rota'], 1)
        self.assertEqual(dados['em_reteste'], 1)
        self.assertEqual(dados['bloqueados'], 1)
        # reteste_vencido: C-VENCIDO (< hoje, ativo) -> 1 (C-BAIX é ignorado)
        self.assertEqual(dados['reteste_vencido'], 1)
        # reteste_30_dias: C-VENCIDO e C-VENC-30D -> 2 (C-BAIX é ignorado)
        self.assertEqual(dados['reteste_30_dias'], 2)

        self.client.force_authenticate(self.gerente)
        with CaptureQueriesContext(connection) as queries:
            resp = self.client.get('/produtos/api/cilindros/resumo/')
            self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Deve executar em no máximo 3 consultas SQL reais (desconsiderando SAVEPOINTs da transação de teste)
        consultas_reais = [
            q for q in queries
            if not q['sql'].startswith('SAVEPOINT') and not q['sql'].startswith('RELEASE')
        ]
        self.assertLessEqual(len(consultas_reais), 3, f"Muitas consultas no resumo: {len(consultas_reais)}")

        dados = resp.json()
        # Tenant A tem 9 cilindros no total
        self.assertEqual(dados['total'], 9)
        # CHEIO_DISPONIVEL: C-CHEIO, C-BLOQ, C-VENCIDO, C-VENC-30D -> 4
        self.assertEqual(dados['cheios_patio'], 4)
        self.assertEqual(dados['em_clientes'], 1)
        self.assertEqual(dados['vazios_triagem'], 1)
        self.assertEqual(dados['em_rota'], 1)
        self.assertEqual(dados['em_reteste'], 1)
        self.assertEqual(dados['bloqueados'], 1)
        # reteste_vencido: C-VENCIDO (< hoje, ativo) -> 1 (C-BAIX é ignorado)
        self.assertEqual(dados['reteste_vencido'], 1)
        # reteste_30_dias: C-VENCIDO e C-VENC-30D -> 2 (C-BAIX é ignorado)
        self.assertEqual(dados['reteste_30_dias'], 2)

    def test_renderizacao_produtos_ativos_gerente(self):
        """
        Renderização de /produtos/ para usuário GERENTE exibe a estrutura da aba Ativos,
        incluindo contadores, busca, tabela e drawer, sem alert( em nenhum script inline.
        """
        self.client.force_login(self.gerente)
        resp = self.client.get('/produtos/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertIn('id="aba-conteudo-ativos"', html)
        self.assertIn('id="input-busca-cilindros"', html)
        self.assertIn('id="cilindros-tbody"', html)
        self.assertIn('id="cylinder-drawer"', html)
        self.assertIn('id="btn-close-drawer"', html)
        self.assertNotIn("alert(", html)

