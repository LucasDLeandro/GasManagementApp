import uuid
import datetime
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import status

from core.models import Tenant, Membership, ResponsavelTecnico
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import Cliente
from produtos.models import (
    GasQuimico,
    ModeloCilindro,
    Cilindro,
    LoteEnvase,
    EnvaseCilindro,
    MovimentacaoCilindro
)
from produtos.services import (
    registrar_envase_cilindro,
    registrar_entrega_cilindro,
    enviar_para_reteste,
    acionar_bloqueio_sanitario,
)

User = get_user_model()


class Fase1AdaptiveShellAndAtivos360Tests(TestCase):
    """
    Suíte de Testes Automatizados da FASE 1:
    1. Tenant Switcher: Alternância de empresa na sessão sem quebra de contexto e segurança Fail-Closed.
    2. Home Adaptativa: Renderização da Fila de Ação Imediata baseada no papel ativo do usuário.
    3. Ativo 360° e Drawer:
       - Endpoint de Timeline do Ledger Imutável.
       - Registro de Retorno de Reteste (datas e tara real).
       - Estorno Auditado no Ledger com reversão de estado.
       - Passaporte de Conformidade Público com selo SHA-256.
    """

    def setUp(self):
        # 1. Criação de dois Tenants para testes de multi-tenancy e switcher
        self.tenant_a = Tenant.objects.create(
            cnpj='11.111.111/0001-11',
            razao_social='GasTech Matriz Ltda',
            nome_fantasia='GasTech SP'
        )
        self.tenant_b = Tenant.objects.create(
            cnpj='22.222.222/0001-22',
            razao_social='GasTech Filial Sul Ltda',
            nome_fantasia='GasTech Curitiba'
        )
        self.tenant_c = Tenant.objects.create(
            cnpj='33.333.333/0001-33',
            razao_social='Empresa Inacessivel Ltda',
            nome_fantasia='Inacessivel'
        )

        self.token = set_current_tenant(self.tenant_a)

        # 2. Usuários e Memberships
        # Usuário RT com acesso a Tenant A e Tenant B
        self.user_rt = User.objects.create_user(
            username='rt_multitenant',
            email='rt@gastech.com.br',
            password='Password123!',
            first_name='Dra. Camila',
            last_name='RT'
        )
        self.membership_a_rt = Membership.objects.create(
            user=self.user_rt,
            tenant=self.tenant_a,
            papel='RESPONSAVEL_TECNICO',
            ativo=True
        )
        self.membership_b_rt = Membership.objects.create(
            user=self.user_rt,
            tenant=self.tenant_b,
            papel='RESPONSAVEL_TECNICO',
            ativo=True
        )
        self.rt_record = ResponsavelTecnico.objects.create(
            user=self.user_rt,
            tenant=self.tenant_a,
            nome_completo='Dra. Camila RT',
            numero_registro='CRF-SP 12345',
            conselho_classe='CRF',
            uf_conselho='SP',
            vigencia_inicio=timezone.now().date(),
            ativo=True
        )

        # Usuário Admin
        self.user_admin = User.objects.create_user(
            username='admin_user',
            password='Password123!',
            first_name='Carlos',
            last_name='Admin'
        )
        self.membership_admin = Membership.objects.create(
            user=self.user_admin,
            tenant=self.tenant_a,
            papel='ADMIN',
            ativo=True
        )

        # Usuário Operador de Pátio
        self.user_patio = User.objects.create_user(
            username='operador_patio',
            password='Password123!',
            first_name='Pedro',
            last_name='Pátio'
        )
        self.membership_patio = Membership.objects.create(
            user=self.user_patio,
            tenant=self.tenant_a,
            papel='OPERADOR_PATIO',
            ativo=True
        )

        # 3. Modelos de Gás e Cilindros
        self.gas_med = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2-MED',
            categoria='MEDICINAL',
            exige_lote_anvisa=True,
            cor_padrao_abnt='BRANCO'
        )
        self.gas_ind = GasQuimico.objects.create(
            nome='Oxigênio Industrial',
            sigla='O2-IND',
            categoria='INDUSTRIAL',
            exige_lote_anvisa=False,
            cor_padrao_abnt='VERDE'
        )

        self.modelo_50l = ModeloCilindro.objects.create(
            descricao='Cilindro Aço 50L 200bar',
            volume_hidraulico_litros=50.0,
            pressao_servico_bar=200,
            tara_nominal_kg=50.0,
            material='ACO',
            periodicidade_reteste_anos=5
        )

        self.hoje = timezone.now().date()
        self.cilindro = Cilindro.objects.create(
            codigo_qr='CIL-FASE1-01',
            numero_serie_ogiva='OGV-998877',
            fabricante='Cilindros Brasil',
            ano_fabricacao=2020,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_med,
            tara_real_kg=52.50,
            propriedade='DISTRIBUIDORA',
            data_ultimo_reteste=self.hoje - datetime.timedelta(days=365 * 3),
            data_proximo_reteste=self.hoje + datetime.timedelta(days=365 * 2),
            status='VAZIO_TRIAGEM'
        )

        self.cliente = Cliente.objects.create(
            nome='Hospital São Camilo',
            cnpj='12.345.678/0001-90',
            endereco='Av. Paulista, 1000',
            cidade='São Paulo',
            estado='SP'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    # ==============================================================================
    # 1. TESTES DO TENANT SWITCHER E CONTEXTO DE SESSÃO
    # ==============================================================================

    def test_tenant_switcher_sucesso(self):
        """
        Usuário com múltiplos memberships altera o tenant ativo via POST /inicio/trocar-tenant/.
        A sessão persiste o novo tenant e as requisições subsequentes operam sob o novo tenant.
        """
        client = Client()
        client.force_login(self.user_rt)

        # 1. Acesso inicial -> resolve para tenant_a (primeiro membership)
        res_inicio = client.get('/inicio/')
        self.assertEqual(res_inicio.status_code, 200)
        self.assertEqual(res_inicio.context['current_tenant'].id, self.tenant_a.id)

        # 2. Efetua troca de tenant para Tenant B via POST
        res_troca = client.post('/inicio/trocar-tenant/', {
            'tenant_id': str(self.tenant_b.id)
        }, HTTP_ACCEPT='application/json')

        self.assertEqual(res_troca.status_code, 200)
        data = res_troca.json()
        self.assertTrue(data['sucesso'])
        self.assertEqual(data['tenant_id'], str(self.tenant_b.id))

        # 3. Requisição subsequente sem header deve carregar o contexto do Tenant B
        res_pos = client.get('/inicio/')
        self.assertEqual(res_pos.status_code, 200)
        self.assertEqual(res_pos.context['current_tenant'].id, self.tenant_b.id)

    def test_tenant_switcher_negado_tenant_sem_acesso(self):
        """
        Tentativa de alternar para tenant sem membership ou inexistente retorna 403 e mantém sessão intacta.
        """
        client = Client()
        client.force_login(self.user_rt)

        res_troca = client.post('/inicio/trocar-tenant/', {
            'tenant_id': str(self.tenant_c.id)
        }, HTTP_ACCEPT='application/json')

        self.assertEqual(res_troca.status_code, 403)
        data = res_troca.json()
        self.assertFalse(data['sucesso'])

        # Sessão permanece no Tenant A
        res_pos = client.get('/inicio/')
        self.assertEqual(res_pos.context['current_tenant'].id, self.tenant_a.id)

    # ==============================================================================
    # 2. TESTES DA HOME ADAPTATIVA E FILA DE AÇÃO IMEDIATA POR PAPEL
    # ==============================================================================

    def test_fila_acao_responsavel_tecnico(self):
        """
        HomeView do Responsável Técnico deve exibir quarentenas ANVISA e bloqueios sanitários.
        """
        # Cria lote em quarentena
        LoteEnvase.objects.create(
            gas=self.gas_med,
            codigo_lote='LT-QUARENTENA-01',
            status_qualidade='QUARENTENA',
            data_envase=self.hoje,
            data_validade=self.hoje + datetime.timedelta(days=365),
            pureza_percentual=99.8,
            responsavel_tecnico='Dra. Camila RT'
        )

        # Aciona bloqueio sanitário no cilindro
        acionar_bloqueio_sanitario(
            cilindro=self.cilindro,
            motivo="Válvula com suspeita de impureza",
            usuario=self.user_rt
        )

        client = Client()
        client.force_login(self.user_rt)
        res = client.get('/inicio/')

        self.assertEqual(res.status_code, 200)
        fila = res.context.get('fila_acao_imediata', [])
        self.assertTrue(len(fila) >= 2)

        titulos = [item['titulo'] for item in fila]
        self.assertIn('Lotes Aguardando Homologação', titulos)
        self.assertIn('Cilindros com Bloqueio Sanitário', titulos)

    def test_fila_acao_operador_patio(self):
        """
        HomeView do Operador de Pátio deve priorizar cilindros vazios em triagem.
        """
        client = Client()
        client.force_login(self.user_patio)
        res = client.get('/inicio/')

        self.assertEqual(res.status_code, 200)
        fila = res.context.get('fila_acao_imediata', [])
        self.assertTrue(len(fila) >= 1)

        titulos = [item['titulo'] for item in fila]
        self.assertIn('Cilindros Vazios em Triagem', titulos)

    # ==============================================================================
    # 3. TESTES DO ATIVO 360°, DRAWER E AÇÕES CONTEXTUAIS
    # ==============================================================================

    def test_timeline_ledger_endpoint(self):
        """
        GET /produtos/api/cilindros/{id}/timeline/ retorna o histórico completo de movimentações.
        """
        # Cria lote e envase
        lote = LoteEnvase.objects.create(
            gas=self.gas_med,
            codigo_lote='LT-TL-01',
            status_qualidade='APROVADO',
            data_envase=self.hoje,
            data_validade=self.hoje + datetime.timedelta(days=365),
            pureza_percentual=99.5,
            responsavel_tecnico='Dra. Camila'
        )
        registrar_envase_cilindro(
            cilindro=self.cilindro,
            lote=lote,
            pressao_bar=200,
            usuario=self.user_patio
        )

        client = Client()
        client.force_login(self.user_admin)
        res = client.get(f'/produtos/api/cilindros/{self.cilindro.id}/timeline/')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        timeline = res.json()
        self.assertTrue(len(timeline) >= 1)
        primeira_mov = timeline[0]
        self.assertEqual(primeira_mov['tipo'], 'ENVASE')
        self.assertEqual(primeira_mov['tipo_display'], 'Envase')
        self.assertFalse(primeira_mov['estornada'])

    def test_retorno_reteste_endpoint(self):
        """
        POST /produtos/api/cilindros/{id}/retorno-reteste/ atualiza validade hidrostática e tara real.
        """
        # Envia cilindro para reteste
        enviar_para_reteste(
            cilindro_id=self.cilindro.id,
            usuario=self.user_admin,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4(),
            observacao="Envio para reteste"
        )
        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.status, 'EM_RETESTE')

        client = Client()
        client.force_login(self.user_admin)

        nova_data = (self.hoje + datetime.timedelta(days=1)).isoformat()
        res = client.post(
            f'/produtos/api/cilindros/{self.cilindro.id}/retorno-reteste/',
            {
                'nova_data_reteste': nova_data,
                'nova_tara_kg': '53.10',
                'observacao': 'Laudo Requalificadora 8891'
            },
            content_type='application/json'
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.status, 'VAZIO_TRIAGEM')
        self.assertEqual(float(self.cilindro.tara_real_kg), 53.10)
        self.assertEqual(self.cilindro.data_ultimo_reteste.isoformat(), nova_data)

        # Valida que gerou movimentação RETORNO_RETESTE no ledger
        ultima_mov = self.cilindro.movimentacoes.order_by('-registrado_em').first()
        self.assertEqual(ultima_mov.tipo, 'RETORNO_RETESTE')

    def test_estorno_auditado_ledger_endpoint(self):
        """
        POST /produtos/api/cilindros/{id}/estorno/ reverte movimentação incorreta e restaura o estado do ativo.
        """
        # 1. Envasa o cilindro (transição para CHEIO_DISPONIVEL)
        lote = LoteEnvase.objects.create(
            gas=self.gas_med,
            codigo_lote='LT-EST-01',
            status_qualidade='APROVADO',
            data_envase=self.hoje,
            data_validade=self.hoje + datetime.timedelta(days=365),
            pureza_percentual=99.5,
            responsavel_tecnico='Dra. Camila'
        )
        _, _, mov_envase = registrar_envase_cilindro(
            cilindro=self.cilindro,
            lote=lote,
            pressao_bar=200,
            usuario=self.user_patio
        )
        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.status, 'CHEIO_DISPONIVEL')
        self.assertIsNotNone(self.cilindro.envase_atual)

        # 2. Executa estorno da movimentação de envase
        client = Client()
        client.force_login(self.user_admin)

        res = client.post(
            f'/produtos/api/cilindros/{self.cilindro.id}/estorno/',
            {
                'movimentacao_id': mov_envase.id,
                'justificativa': 'Erro operacional: operador bipou cilindro incorreto na rampa.'
            },
            content_type='application/json'
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.cilindro.refresh_from_db()

        # O cilindro volta para VAZIO_TRIAGEM e limpa o envase_atual
        self.assertEqual(self.cilindro.status, 'VAZIO_TRIAGEM')
        self.assertIsNone(self.cilindro.envase_atual)

        # No ledger, a movimentação de envase está marcada como estornada
        mov_envase.refresh_from_db()
        self.assertTrue(hasattr(mov_envase, 'estornada_por'))
        self.assertIsNotNone(mov_envase.estornada_por)
        self.assertEqual(mov_envase.estornada_por.tipo, 'ESTORNO')

        # 3. Tentativa de estornar novamente a mesma movimentação deve ser bloqueada
        res_duplo = client.post(
            f'/produtos/api/cilindros/{self.cilindro.id}/estorno/',
            {
                'movimentacao_id': mov_envase.id,
                'justificativa': 'Tentativa duplicada'
            },
            content_type='application/json'
        )
        self.assertEqual(res_duplo.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('já foi estornada', res_duplo.json()['error'])

    def test_passaporte_conformidade_publico(self):
        """
        GET /produtos/passaporte/{codigo_qr}/ exibe a ficha técnica e o selo de autenticidade SHA-256.
        """
        client = Client()
        res = client.get(f'/produtos/passaporte/{self.cilindro.codigo_qr}/')

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.cilindro.codigo_qr)
        self.assertContains(res, self.cilindro.numero_serie_ogiva)
        self.assertContains(res, 'Passaporte de Conformidade Regulatória')
        self.assertIsNotNone(res.context.get('hash_autenticidade'))
        self.assertEqual(len(res.context['hash_autenticidade']), 64)  # Hash SHA-256
