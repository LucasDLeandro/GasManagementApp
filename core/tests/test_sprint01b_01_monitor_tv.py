"""
Testes automatizados da Sprint 01B.01 — Monitor de TV (Tarefa 01B.2).
Valida:
1. Resolução pública por token seguro (secrets.token_urlsafe(32)), retorno 404 para token inválido ou inativo.
2. Isolamento multi-tenant estrito (token da empresa A nunca mostra dados da empresa B).
3. Ausência total de dados financeiros (R$, limites, dívidas) e dados de contato (telefone, e-mail, CNPJ, endereço completo).
4. Mascaramento de clientes quando mostrar_nomes_clientes=False (apenas número do pedido e bairro/cidade).
5. Throttle por token (12 req/min) retornando HTTP 429.
6. Respeito aos módulos ativos (Fábrica só com 'envase'; Esteira só com 'distribuicao').
7. Cálculo de tempo na etapa pelo histórico de status da 01B.00 com cores de alerta.
8. Desempenho sem N+1 (<= 15 queries) e cache de 15 segundos.
9. RBAC de gestão de painéis (somente ADMIN e GERENTE em Configurações).
10. Revogação e regeneração de token.
11. Segurança de frontend (zero innerHTML dinâmico, zero estilos inline, uso de textContent).
"""
import uuid
import datetime
from decimal import Decimal
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient

from core.models import Tenant, Membership
from core.tenancy import tenant_context
from clientes.models import Cliente
from vendas.models import Venda
from logistica.models import Entrega, Veiculo
from produtos.models import GasQuimico, ModeloCilindro, SkuRecarga, Cilindro, TanqueCriogenico

User = get_user_model()


class MonitorTVTests(TestCase):
    def setUp(self):
        cache.clear()
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
        self.user_admin = User.objects.create_user(
            username='admin.alfa',
            password='password123',
            email='admin@alfa.com'
        )
        Membership.objects.create(
            user=self.user_admin,
            tenant=self.tenant_a,
            papel='ADMIN',
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

        self.user_motorista = User.objects.create_user(
            username='motorista.alfa',
            password='password123',
            email='motorista@alfa.com'
        )
        Membership.objects.create(
            user=self.user_motorista,
            tenant=self.tenant_a,
            papel='MOTORISTA',
            ativo=True
        )

        with tenant_context(self.tenant_a):
            self.cliente_a = Cliente.objects.create(
                tenant=self.tenant_a,
                nome='Hospital São Lucas',
                nome_fantasia='Hospital São Lucas',
                cnpj='11.222.333/0001-44',
                email_financeiro='contato@saolucas.com.br',
                telefone='(11) 98765-4321',
                cidade='São Paulo',
                bairro='Cerqueira César'
            )
            self.gas_o2 = GasQuimico.objects.create(
                nome='Oxigênio Medicinal',
                sigla='O2-MED',
                categoria='MEDICINAL'
            )
            self.modelo_10m3 = ModeloCilindro.objects.create(
                tenant=self.tenant_a,
                descricao='Cilindro 50L Aço',
                volume_hidraulico_litros=Decimal('50.0'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('50.0')
            )
            self.sku_o2 = SkuRecarga.objects.create(
                tenant=self.tenant_a,
                gas=self.gas_o2,
                modelo_cilindro=self.modelo_10m3,
                nome_comercial='Cilindro O2 10m³',
                quantidade_carga=Decimal('10.0'),
                massa_gas_kg=Decimal('13.3'),
                preco_base=Decimal('150.00')
            )

        with tenant_context(self.tenant_b):
            self.cliente_b = Cliente.objects.create(
                tenant=self.tenant_b,
                nome='Clínica Beta',
                nome_fantasia='Clínica Beta',
                cnpj='99.888.777/0001-66',
                email_financeiro='contato@beta.com.br',
                telefone='(21) 99999-8888',
                cidade='Rio de Janeiro',
                bairro='Copacabana'
            )

    # --------------------------------------------------------------------------
    # 1. TOKEN INVÁLIDO OU PAINEL INATIVO -> 404
    # --------------------------------------------------------------------------

    def test_01_token_invalido_ou_painel_inativo_retorna_404(self):
        """Token inexistente ou painel inativo responde 404 em HTML e JSON (nunca 403)."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        client = APIClient()

        # Token inexistente
        resp_fake_html = client.get('/painel/token-inexistente-12345/')
        self.assertEqual(resp_fake_html.status_code, 404)

        resp_fake_json = client.get('/painel/token-inexistente-12345/dados/')
        self.assertEqual(resp_fake_json.status_code, 404)

        # Painel desativado
        token_inativo = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="Painel Desativado",
                token=token_inativo,
                ativo=False
            )

        resp_inativo_html = client.get(f'/painel/{token_inativo}/')
        self.assertEqual(resp_inativo_html.status_code, 404)

        resp_inativo_json = client.get(f'/painel/{token_inativo}/dados/')
        self.assertEqual(resp_inativo_json.status_code, 404)

    # --------------------------------------------------------------------------
    # 2. ISOLAMENTO MULTI-TENANT: EMPRESA A NUNCA VÊ EMPRESA B
    # --------------------------------------------------------------------------

    def test_02_isolamento_multitenant_token_empresa_a_nao_mostra_dados_empresa_b(self):
        """Monitor com token da empresa A nunca exibe dados da empresa B."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token_a = gerar_token_painel()
        with tenant_context(self.tenant_a):
            painel_a = PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Alfa",
                token=token_a,
                ativo=True
            )
            venda_a = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )

        with tenant_context(self.tenant_b):
            venda_b = Venda.objects.create(
                tenant=self.tenant_b,
                cliente=self.cliente_b,
                status='Pendente'
            )

        client = APIClient()
        resp = client.get(f'/painel/{token_a}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        # O pedido da empresa A está presente
        ids_a_separar = [item['id'] for item in dados['esteira']['a_separar']]
        self.assertIn(venda_a.id, ids_a_separar)
        # O pedido da empresa B NUNCA deve estar presente
        self.assertNotIn(venda_b.id, ids_a_separar)
        # O nome do cliente da empresa B não deve aparecer
        self.assertNotIn('Clínica Beta', str(dados))

    # --------------------------------------------------------------------------
    # 3. AUSÊNCIA TOTAL DE DADOS FINANCEIROS E DE CONTATO (LGPD / PRIVACIDADE)
    # --------------------------------------------------------------------------

    def test_03_ausencia_total_de_dados_financeiros_e_contato_varredura_recursiva(self):
        """O JSON do painel não pode conter R$, valores monetários, telefones, e-mails nem CNPJs."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Monitor",
                token=token,
                ativo=True
            )
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente',
                valor_total=Decimal('1500.50'),
                observacoes="Cobrar cliente via boleto bancário"
            )

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        termos_proibidos = [
            'r$', 'reais', 'valor', 'preco', 'preço', 'faturamento',
            'saldo_devedor', 'cnpj', 'cpf', 'telefone', 'email', 'e-mail',
            'endereco', 'endereço', 'logradouro', 'cep', 'motivo'
        ]

        def verificar_recursivo(obj, caminho=''):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    k_lower = str(k).lower()
                    for termo in termos_proibidos:
                        # Exceção permitida: se a chave contiver apenas contadores como 'contagem' ou 'percentual'
                        self.assertNotIn(
                            termo,
                            k_lower,
                            f"Chave proibida encontrada: '{k}' em {caminho}"
                        )
                    verificar_recursivo(v, f"{caminho}.{k}")
            elif isinstance(obj, list):
                for i, elem in enumerate(obj):
                    verificar_recursivo(elem, f"{caminho}[{i}]")
            elif isinstance(obj, str):
                v_lower = obj.lower()
                for termo in ['r$', 'reais', '1500.50', '1500,50', 'contato@saolucas', '98765-4321', '11.222.333/0001-44']:
                    self.assertNotIn(
                        termo,
                        v_lower,
                        f"Dado sensível vazado no valor: '{obj}' em {caminho}"
                    )

        verificar_recursivo(dados)

    # --------------------------------------------------------------------------
    # 4. MASCARAMENTO DE CLIENTES QUANDO MOSTRAR_NOMES_CLIENTES=FALSE
    # --------------------------------------------------------------------------

    def test_04_mostrar_nomes_clientes_false_mascara_para_bairro_cidade(self):
        """Quando mostrar_nomes_clientes=False, exibe apenas bairro/cidade e omite o nome."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Externa",
                token=token,
                ativo=True,
                mostrar_nomes_clientes=False
            )
            Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()

        item = dados['esteira']['a_separar'][0]
        self.assertNotIn('Hospital São Lucas', item['cliente'])
        self.assertIn('Cerqueira César', item['cliente'])
        self.assertIn('São Paulo', item['cliente'])

    # --------------------------------------------------------------------------
    # 5. THROTTLE POR TOKEN (12 REQ/MIN) -> 429
    # --------------------------------------------------------------------------

    def test_05_rate_limit_throttle_por_token_retorna_429(self):
        """Mais de 12 requisições por minuto com o mesmo token retorna HTTP 429."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Rate Limit",
                token=token,
                ativo=True
            )

        client = APIClient()
        # Faz 12 chamadas com sucesso (limpando cache de dados mas mantendo rate limit)
        for i in range(12):
            cache.delete(f"cache_monitor_dados_{token}")
            resp = client.get(f'/painel/{token}/dados/')
            self.assertEqual(resp.status_code, 200, f"Chamada {i+1} deveria ser 200")

        # 13ª chamada deve ser barrada por throttle
        resp_bloqueada = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp_bloqueada.status_code, 429)
        self.assertIn('Limite', resp_bloqueada.json().get('erro', ''))

    # --------------------------------------------------------------------------
    # 6. SEÇÕES RESPEITAM MÓDULOS ATIVOS
    # --------------------------------------------------------------------------

    def test_06_secoes_respeitam_modulos_fabrica_e_esteira(self):
        """Seção 'fabrica' só aparece se módulo 'envase' estiver ativo."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Modulos",
                token=token,
                ativo=True,
                secoes={'fabrica': True, 'esteira': True}
            )

        client = APIClient()

        # Sem módulo envase
        self.tenant_a.modulos_ativos = ['distribuicao']
        self.tenant_a.save()
        cache.clear()

        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()
        self.assertNotIn('fabrica', dados)
        self.assertIn('esteira', dados)

        # Com módulo envase ativo
        self.tenant_a.modulos_ativos = ['distribuicao', 'envase']
        self.tenant_a.save()
        cache.clear()

        resp2 = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp2.status_code, 200)
        dados2 = resp2.json()
        self.assertIn('fabrica', dados2)

    # --------------------------------------------------------------------------
    # 7. TEMPO NA ETAPA COM HISTÓRICO DA 01B.00 E NÍVEIS DE ALERTA
    # --------------------------------------------------------------------------

    def test_07_tempo_na_etapa_calculado_com_historico_01b00_e_cores_alerta(self):
        """Calcula minutos_na_etapa pelo desde_quando_no_status e atribui normal/alerta/critico."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel
        from vendas.services.status import transicionar_venda

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Alertas",
                token=token,
                ativo=True,
                tempo_alerta_min=30,
                tempo_critico_min=60
            )

            # Venda normal (< 30 min)
            venda_normal = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )

            # Venda em alerta (passou de 30 min)
            venda_alerta = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )
            # Simula entrada há 45 min atrás no histórico
            hist_alerta = venda_alerta.historico_status.first()
            if hist_alerta:
                hist_alerta.alterado_em = timezone.now() - datetime.timedelta(minutes=45)
                hist_alerta.save(update_fields=['alterado_em'])

            # Venda crítica (passou de 60 min)
            venda_critica = Venda.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_a,
                status='Pendente'
            )
            hist_critica = venda_critica.historico_status.first()
            if hist_critica:
                hist_critica.alterado_em = timezone.now() - datetime.timedelta(minutes=75)
                hist_critica.save(update_fields=['alterado_em'])

        client = APIClient()
        resp = client.get(f'/painel/{token}/dados/')
        self.assertEqual(resp.status_code, 200)
        itens = resp.json()['esteira']['a_separar']

        mapa_status = {item['id']: item for item in itens}
        self.assertEqual(mapa_status[venda_normal.id]['nivel_alerta'], 'normal')
        self.assertEqual(mapa_status[venda_alerta.id]['nivel_alerta'], 'alerta')
        self.assertEqual(mapa_status[venda_critica.id]['nivel_alerta'], 'critico')

    # --------------------------------------------------------------------------
    # 8. SEM N+1 (MÁXIMO 15 QUERIES) E CACHE DE 15 SEGUNDOS
    # --------------------------------------------------------------------------

    def test_08_sem_n_mais_um_e_cache_15s(self):
        """Garante no máximo 15 consultas por atualização e 0 queries na requisição em cache."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token = gerar_token_painel()
        with tenant_context(self.tenant_a):
            PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Performance",
                token=token,
                ativo=True
            )
            # Cria 15 pedidos espalhados em vários status
            for i in range(15):
                st = ['Pendente', 'Em Separação', 'Faturada', 'Em Rota'][i % 4]
                Venda.objects.create(
                    tenant=self.tenant_a,
                    cliente=self.cliente_a,
                    status=st
                )

        client = APIClient()

        # 1. Primeira consulta: sem N+1, <= 15 queries
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            resp = client.get(f'/painel/{token}/dados/')
            self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(ctx), 15, f"Esperado <= 15 queries, foram executadas {len(ctx)}")

        # 2. Segunda consulta imediata: consome cache de 15s (0 queries de aplicação no banco)
        with CaptureQueriesContext(connection) as ctx_cache:
            resp_cache = client.get(f'/painel/{token}/dados/')
            self.assertEqual(resp_cache.status_code, 200)
        queries_app = [q for q in ctx_cache if 'SAVEPOINT' not in q['sql'].upper()]
        self.assertEqual(len(queries_app), 0, f"Consultas de banco inesperadas durante hit de cache: {queries_app}")

    # --------------------------------------------------------------------------
    # 9. RBAC DE GESTÃO DE PAINÉIS (CONFIGURAÇÕES: SÓ ADMIN E GERENTE)
    # --------------------------------------------------------------------------

    def test_09_gestao_paineis_rbac_apenas_admin_e_gerente(self):
        """Apenas ADMIN e GERENTE gerenciam painéis; outros papéis recebem 403."""
        client = APIClient()

        # ADMIN -> 200 / 201
        client.force_authenticate(user=self.user_admin)
        resp_admin = client.post(
            '/inicio/api/paineis/',
            {'nome': 'Painel Galpão Admin'},
            format='json'
        )
        self.assertIn(resp_admin.status_code, [200, 201])
        painel_id = resp_admin.json()['id']

        # GERENTE -> 200
        client.force_authenticate(user=self.user_gerente)
        resp_gerente = client.get('/inicio/api/paineis/')
        self.assertEqual(resp_gerente.status_code, 200)

        # VENDEDOR -> 403
        client.force_authenticate(user=self.user_vendedor)
        resp_vendedor = client.get('/inicio/api/paineis/')
        self.assertEqual(resp_vendedor.status_code, 403)

        # MOTORISTA -> 403
        client.force_authenticate(user=self.user_motorista)
        resp_motorista = client.post(
            '/inicio/api/paineis/',
            {'nome': 'Tentativa Motorista'},
            format='json'
        )
        self.assertEqual(resp_motorista.status_code, 403)

    # --------------------------------------------------------------------------
    # 10. REVOGAÇÃO E REGENERAÇÃO DE TOKEN
    # --------------------------------------------------------------------------

    def test_10_revogacao_e_regeneracao_de_token(self):
        """Revogar desativa o painel (404); regenerar gera token de 32 bytes e invalida anterior."""
        from core.models import PainelMonitor
        from core.services.painel_monitor import gerar_token_painel

        token_orig = gerar_token_painel()
        with tenant_context(self.tenant_a):
            painel = PainelMonitor.objects.create(
                tenant=self.tenant_a,
                nome="TV Ciclo Vida",
                token=token_orig,
                ativo=True
            )

        client = APIClient()
        client.force_authenticate(user=self.user_admin)

        # 1. Regenerar token
        resp_regen = client.post(f'/inicio/api/paineis/{painel.id}/regenerar_token/')
        self.assertEqual(resp_regen.status_code, 200)
        novo_token = resp_regen.json()['token']
        self.assertNotEqual(novo_token, token_orig)
        self.assertGreaterEqual(len(novo_token), 32)

        # Token antigo agora dá 404
        client_anonimo = APIClient()
        resp_antigo = client_anonimo.get(f'/painel/{token_orig}/dados/')
        self.assertEqual(resp_antigo.status_code, 404)

        # Novo token responde 200
        resp_novo = client_anonimo.get(f'/painel/{novo_token}/dados/')
        self.assertEqual(resp_novo.status_code, 200)

        # 2. Revogar painel (desativar)
        resp_revogar = client.post(f'/inicio/api/paineis/{painel.id}/revogar/')
        self.assertEqual(resp_revogar.status_code, 200)
        self.assertFalse(resp_revogar.json()['ativo'])

        # Novo token agora também dá 404 pois está inativo
        resp_revogado = client_anonimo.get(f'/painel/{novo_token}/dados/')
        self.assertEqual(resp_revogado.status_code, 404)

    # --------------------------------------------------------------------------
    # 11. SEGURANÇA DE FRONTEND: SEM INNERHTML DINÂMICO E SEM ESTILOS INLINE
    # --------------------------------------------------------------------------

    def test_11_seguranca_frontend_static_scan_sem_innerhtml_e_sem_estilos_inline(self):
        """Varredura estática garantindo zero innerHTML com dados dinâmicos e zero estilos inline."""
        import os
        from django.conf import settings

        caminho_js = os.path.join(settings.BASE_DIR, 'core', 'static', 'core', 'js', 'painel_monitor.js')
        caminho_html = os.path.join(settings.BASE_DIR, 'core', 'templates', 'core', 'painel_monitor.html')

        self.assertTrue(os.path.exists(caminho_js), f"Arquivo JS {caminho_js} deve existir.")
        self.assertTrue(os.path.exists(caminho_html), f"Arquivo HTML {caminho_html} deve existir.")

        with open(caminho_js, 'r', encoding='utf-8') as f:
            conteudo_js = f.read()

        # Proibido innerHTML no JS de renderização
        self.assertNotIn('innerHTML', conteudo_js, "Proibido uso de innerHTML em painel_monitor.js (use textContent)")
        self.assertIn('textContent', conteudo_js, "Deve utilizar textContent para dados de cadastro no DOM")

        with open(caminho_html, 'r', encoding='utf-8') as f:
            conteudo_html = f.read()

        # Proibido style="..." inline no HTML do monitor
        import re
        matches_style = re.findall(r'style\s*=\s*["\'][^"\']+["\']', conteudo_html, flags=re.IGNORECASE)
        self.assertEqual(len(matches_style), 0, f"Estilos inline proibidos encontrados no HTML: {matches_style}")
