import io
import uuid
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership, PerfilRegulatorioTenant
from core.tenancy import tenant_context
from accounts.models import User
from clientes.models import Cliente, UsuarioClienteB2B
from vendas.models import Venda, ItemVenda
from produtos.models import (
    Cilindro,
    GasQuimico,
    ModeloCilindro,
    LoteEnvase,
    EnvaseCilindro,
    MovimentacaoCilindro,
    SkuRecarga,
)
from faturamento.models import FaturaCobranca


class Sprint9PortalB2BTests(TestCase):
    def setUp(self):
        # 1. Tenant A
        self.tenant_a = Tenant.objects.create(
            razao_social="Distribuidora Alfa Gases LTDA",
            nome_fantasia="Alfa Gases",
            cnpj="11.222.333/0001-44",
            plano="PRO"
        )
        self.perfil_a = PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant_a,
            modo_operacao='MISTO',
            afe_numero='AFE-123456',
            licenca_sanitaria_numero='LIC-998877',
            licenca_sanitaria_validade=timezone.now().date() + timezone.timedelta(days=365)
        )

        # 2. Tenant B (para teste de isolamento multitenant)
        self.tenant_b = Tenant.objects.create(
            razao_social="Beta Oxigênio LTDA",
            nome_fantasia="Beta Oxigênio",
            cnpj="99.888.777/0001-66",
            plano="BASIC"
        )

        # Dados dentro do Tenant A
        with tenant_context(self.tenant_a):
            # Clientes no Tenant A
            self.cliente_a1 = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="12.345.678/0001-99",
                nome="Hospital Geral Santa Clara",
                endereco="Av. Paulista, 1000",
                cidade="São Paulo",
                estado="SP",
                telefone="11988887777",
                proprietario="Dr. José Diretor",
                is_medicinal=True
            )
            self.cliente_a2 = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="23.456.789/0001-00",
                nome="Clínica Médica Vida Nova",
                endereco="Rua das Flores, 50",
                cidade="Campinas",
                estado="SP",
                telefone="19977776666",
                proprietario="Dra. Maria Gestora",
                is_medicinal=True
            )

            # Usuários do Sistema
            self.user_admin = User.objects.create_user(
                username="admin_alfa",
                email="admin@alfa.com.br",
                password="password123"
            )
            Membership.objects.create(
                user=self.user_admin,
                tenant=self.tenant_a,
                papel='ADMIN',
                ativo=True
            )

            # Usuário B2B para o Cliente A1 (Hospital Santa Clara)
            self.user_b2b_a1 = User.objects.create_user(
                username="compras_santaclara",
                email="compras@santaclara.org.br",
                password="password123",
                first_name="Carlos",
                last_name="Farmacêutico"
            )
            self.usuario_b2b_a1 = UsuarioClienteB2B.objects.create(
                user=self.user_b2b_a1,
                cliente=self.cliente_a1,
                cargo="Diretor de Farmácia e Suprimentos",
                telefone_contato="11988880000",
                ativo=True
            )

            # Usuário B2B Inativo para o Cliente A1
            self.user_b2b_inativo = User.objects.create_user(
                username="inativo_santaclara",
                email="inativo@santaclara.org.br",
                password="password123"
            )
            UsuarioClienteB2B.objects.create(
                user=self.user_b2b_inativo,
                cliente=self.cliente_a1,
                ativo=False
            )

            # Gás e Modelo
            self.gas_oxm = GasQuimico.objects.create(
                nome="Oxigênio Medicinal",
                sigla="OXM",
                categoria="MEDICINAL",
                numero_onu="1072",
                classe_risco="2.2",
                exige_lote_anvisa=True
            )
            self.modelo_t40 = ModeloCilindro.objects.create(
                descricao="T40 Padrão",
                material="ACO",
                volume_hidraulico_litros=Decimal('40.0'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('50.0'),
                periodicidade_reteste_anos=5
            )
            self.sku_oxm = SkuRecarga.objects.create(
                gas=self.gas_oxm,
                modelo_cilindro=self.modelo_t40,
                nome_comercial="Recarga O2 Medicinal 10m³",
                quantidade_carga=Decimal('10.0'),
                unidade='m3',
                massa_gas_kg=Decimal('14.2'),
                preco_base=Decimal('250.00')
            )

            # Lote de Envase Químico com RT
            self.lote_oxm = LoteEnvase.objects.create(
                gas=self.gas_oxm,
                codigo_lote="LOTE-OXM-2026-001",
                data_envase=timezone.now().date(),
                data_validade=timezone.now().date() + timezone.timedelta(days=730),
                pureza_percentual=Decimal('99.85'),
                responsavel_tecnico="Dr. Roberto Silva (CRF/SP 45.892)",
                status_qualidade='APROVADO'
            )

            # Cilindro 1 (Em posse do Cliente A1)
            self.cilindro_a1 = Cilindro.objects.create(
                codigo_qr="QR-CIL-A1-001",
                numero_serie_ogiva="SN-OXM-1001",
                fabricante="MAT",
                ano_fabricacao=2024,
                modelo=self.modelo_t40,
                gas_dedicado=self.gas_oxm,
                status='EM_POSSE_CLIENTE',
                cliente_posse_atual=self.cliente_a1,
                posse_desde=timezone.now(),
                data_ultimo_reteste=timezone.now().date() - timezone.timedelta(days=365),
                data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1460)
            )

            # Envase do Cilindro 1
            self.envase_cil_1 = EnvaseCilindro.objects.create(
                cilindro=self.cilindro_a1,
                lote=self.lote_oxm,
                pressao_final_bar=200,
                envasado_em=timezone.now() - timezone.timedelta(days=5),
                operador=self.user_admin,
                observacoes="Envase aprovado sem ressalvas"
            )
            self.cilindro_a1.envase_atual = self.envase_cil_1
            self.cilindro_a1.save(update_fields=['envase_atual'])

            # Movimentação no Ledger entregando ao Cliente A1
            self.mov_entrega_a1 = MovimentacaoCilindro.objects.create(
                cilindro=self.cilindro_a1,
                tipo='ENTREGA_CLIENTE',
                status_anterior='RESERVADO_ROTA',
                status_novo='EM_POSSE_CLIENTE',
                cliente=self.cliente_a1,
                ocorrido_em=timezone.now() - timezone.timedelta(days=2),
                registrado_por=self.user_admin,
                envase_cilindro=self.envase_cil_1,
                lote_envase=self.lote_oxm.codigo_lote,
                observacao="Entrega realizada com sucesso no Hospital Santa Clara"
            )

            # Cilindro 2 (Em posse do Cliente A2)
            self.cilindro_a2 = Cilindro.objects.create(
                codigo_qr="QR-CIL-A2-002",
                numero_serie_ogiva="SN-OXM-2002",
                fabricante="MAT",
                ano_fabricacao=2023,
                modelo=self.modelo_t40,
                gas_dedicado=self.gas_oxm,
                status='EM_POSSE_CLIENTE',
                cliente_posse_atual=self.cliente_a2,
                posse_desde=timezone.now(),
                data_ultimo_reteste=timezone.now().date() - timezone.timedelta(days=365),
                data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1460)
            )

            # Venda 1 (Cliente A1)
            self.venda_a1 = Venda.objects.create(
                cliente=self.cliente_a1,
                vendedor=self.user_admin,
                status='Entregue',
                tipo_operacao='RECARGA_TROCA',
                forma_pagamento='BOLETO',
                valor_total=Decimal('500.00'),
                documento_fiscal_ref='NF-9988'
            )
            ItemVenda.objects.create(
                venda=self.venda_a1,
                sku=self.sku_oxm,
                quantidade=2,
                valor_unitario=Decimal('250.00'),
                valor_total=Decimal('500.00')
            )

            # Fatura da Venda 1 (Cliente A1)
            self.fatura_a1 = FaturaCobranca.objects.create(
                cliente=self.cliente_a1,
                venda=self.venda_a1,
                valor=Decimal('500.00'),
                status='ABERTA',
                data_vencimento=timezone.now().date() + timezone.timedelta(days=15),
                linha_digitavel="34191.79001 01043.510047 91020.150008 8 91230000050000",
                qr_code_pix="00020126580014BR.GOV.BCB.PIX0136pix-teste-alfa5204000053039865405500.00"
            )

            # Venda 2 (Cliente A2 - Clínica Vida)
            self.venda_a2 = Venda.objects.create(
                cliente=self.cliente_a2,
                vendedor=self.user_admin,
                status='Entregue',
                tipo_operacao='RECARGA_TROCA',
                forma_pagamento='PIX',
                valor_total=Decimal('250.00'),
                documento_fiscal_ref='NF-9989'
            )
            self.fatura_a2 = FaturaCobranca.objects.create(
                cliente=self.cliente_a2,
                venda=self.venda_a2,
                valor=Decimal('250.00'),
                status='ABERTA',
                data_vencimento=timezone.now().date() + timezone.timedelta(days=10)
            )

        # Dados dentro do Tenant B
        with tenant_context(self.tenant_b):
            self.cliente_b = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="88.777.666/0001-55",
                nome="Hospital Regional Beta",
                endereco="Rua do Norte, 100",
                cidade="Ribeirão Preto",
                estado="SP",
                telefone="16988884444",
                proprietario="Dr. Beta"
            )
            self.user_b2b_b = User.objects.create_user(
                username="compras_beta",
                email="compras@beta.org.br",
                password="password123"
            )
            self.usuario_b2b_b = UsuarioClienteB2B.objects.create(
                user=self.user_b2b_b,
                cliente=self.cliente_b,
                ativo=True
            )
            self.venda_b = Venda.objects.create(
                cliente=self.cliente_b,
                status='Pendente',
                valor_total=Decimal('1000.00')
            )
            self.fatura_b = FaturaCobranca.objects.create(
                cliente=self.cliente_b,
                venda=self.venda_b,
                valor=Decimal('1000.00'),
                status='ABERTA',
                data_vencimento=timezone.now().date() + timezone.timedelta(days=30)
            )

        self.client = APIClient()

    def test_modelagem_usuario_cliente_b2b(self):
        """Valida que UsuarioClienteB2B herda de TenantAwareModel e isola o cliente."""
        self.assertEqual(self.usuario_b2b_a1.tenant, self.tenant_a)
        self.assertEqual(self.usuario_b2b_a1.cliente, self.cliente_a1)
        self.assertTrue(hasattr(self.user_b2b_a1, 'usuarioclienteb2b'))
        self.assertEqual(self.user_b2b_a1.usuarioclienteb2b, self.usuario_b2b_a1)
        self.assertIn("Hospital Geral Santa Clara", str(self.usuario_b2b_a1))

    def test_permissao_is_client_b2b_fail_closed(self):
        """Valida que IsClientB2B nega acesso por padrão a anônimos, usuários internos e usuários inativos."""
        # 1. Anônimo
        res_anon = self.client.get('/portal-b2b/api/vendas/')
        self.assertIn(res_anon.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # 2. Usuário interno (sem UsuarioClienteB2B)
        self.client.force_authenticate(user=self.user_admin)
        res_admin = self.client.get('/portal-b2b/api/vendas/')
        self.assertEqual(res_admin.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Usuário B2B inativo
        self.client.force_authenticate(user=self.user_b2b_inativo)
        res_inativo = self.client.get('/portal-b2b/api/vendas/')
        self.assertEqual(res_inativo.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Usuário B2B autêntico e ativo
        self.client.force_authenticate(user=self.user_b2b_a1)
        res_auth = self.client.get('/portal-b2b/api/vendas/')
        self.assertEqual(res_auth.status_code, status.HTTP_200_OK)

    def test_b2b_venda_viewset_strict_isolation(self):
        """Valida que B2BVendaViewSet retorna unicamente as vendas do cliente autenticado."""
        self.client.force_authenticate(user=self.user_b2b_a1)

        res = self.client.get('/portal-b2b/api/vendas/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        ids = [item['id'] for item in res.data['results'] if 'results' in res.data] if 'results' in res.data else [item['id'] for item in res.data]
        self.assertIn(self.venda_a1.id, ids)
        self.assertNotIn(self.venda_a2.id, ids)
        self.assertNotIn(self.venda_b.id, ids)

        # Tentativa de acesso direto à venda de outro cliente (mesmo tenant)
        res_detalhe_a2 = self.client.get(f'/portal-b2b/api/vendas/{self.venda_a2.id}/')
        self.assertEqual(res_detalhe_a2.status_code, status.HTTP_404_NOT_FOUND)

        # Tentativa de acesso direto à venda de outro tenant
        res_detalhe_b = self.client.get(f'/portal-b2b/api/vendas/{self.venda_b.id}/')
        self.assertEqual(res_detalhe_b.status_code, status.HTTP_404_NOT_FOUND)

    def test_b2b_fatura_viewset_strict_isolation(self):
        """Valida que B2BFaturaViewSet retorna unicamente as cobranças do cliente autenticado."""
        self.client.force_authenticate(user=self.user_b2b_a1)

        res = self.client.get('/portal-b2b/api/faturas/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        ids = [item['id'] for item in res.data['results'] if 'results' in res.data] if 'results' in res.data else [item['id'] for item in res.data]
        self.assertIn(self.fatura_a1.id, ids)
        self.assertNotIn(self.fatura_a2.id, ids)
        self.assertNotIn(self.fatura_b.id, ids)

        # Tentativa de acesso direto à fatura de outro cliente
        res_detalhe_a2 = self.client.get(f'/portal-b2b/api/faturas/{self.fatura_a2.id}/')
        self.assertEqual(res_detalhe_a2.status_code, status.HTTP_404_NOT_FOUND)

    def test_b2b_cilindro_viewset_strict_isolation(self):
        """Valida que B2BCilindroViewSet retorna apenas cilindros em comodato com este cliente."""
        self.client.force_authenticate(user=self.user_b2b_a1)

        res = self.client.get('/portal-b2b/api/cilindros/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        ids = [item['id'] for item in res.data['results'] if 'results' in res.data] if 'results' in res.data else [item['id'] for item in res.data]
        self.assertIn(self.cilindro_a1.id, ids)
        self.assertNotIn(self.cilindro_a2.id, ids)

        # Tentativa de consulta de cilindro em posse de outro cliente
        res_detalhe_a2 = self.client.get(f'/portal-b2b/api/cilindros/{self.cilindro_a2.id}/')
        self.assertEqual(res_detalhe_a2.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_laudo_quimico_compliance_anvisa(self):
        """
        Valida que @action laudo_quimico localiza a Movimentacao mais recente,
        cruza com EnvaseCilindro e LoteEnvase e serve o PDF assinado pelo RT.
        """
        self.client.force_authenticate(user=self.user_b2b_a1)

        url = f'/portal-b2b/api/cilindros/{self.cilindro_a1.id}/laudo-quimico/'
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('inline', res['Content-Disposition'])
        self.assertIn('laudo_lote_LOTE-OXM-2026-001.pdf', res['Content-Disposition'])

        # O conteúdo deve ser um PDF binário válido (inicia com %PDF-)
        content = b''.join(res.streaming_content) if res.streaming else res.content
        self.assertTrue(content.startswith(b'%PDF'))

    def test_download_laudo_quimico_arquivo_fisico_anexo(self):
        """Valida download de laudo quando o arquivo PDF está anexado em FileField do lote."""
        pdf_dummy = SimpleUploadedFile("laudo_oficial.pdf", b"%PDF-1.4 Fake Official PDF ANVISA", content_type="application/pdf")
        with tenant_context(self.tenant_a):
            self.lote_oxm.laudo_pdf = pdf_dummy
            self.lote_oxm.save(update_fields=['laudo_pdf'])

        self.client.force_authenticate(user=self.user_b2b_a1)
        url = f'/portal-b2b/api/cilindros/{self.cilindro_a1.id}/laudo-quimico/'
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')

    def test_download_laudo_cilindro_de_outro_cliente_bloqueado(self):
        """Valida que o cliente B2B não consegue baixar laudo de cilindro que pertence a outro cliente."""
        self.client.force_authenticate(user=self.user_b2b_a1)

        url_a2 = f'/portal-b2b/api/cilindros/{self.cilindro_a2.id}/laudo-quimico/'
        res = self.client.get(url_a2)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_b2b_perfil_cliente_view(self):
        """Valida endpoint /portal-b2b/api/perfil/ com dados consolidados de comodato e financeiro."""
        self.client.force_authenticate(user=self.user_b2b_a1)

        res = self.client.get('/portal-b2b/api/perfil/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['cliente_nome'], "Hospital Geral Santa Clara")
        self.assertEqual(res.data['cnpj'], "12.345.678/0001-99")
        self.assertEqual(res.data['total_cilindros_em_posse'], 1)
        self.assertEqual(res.data['total_faturas_abertas'], 1)
        self.assertEqual(Decimal(str(res.data['valor_total_aberto'])), Decimal('500.00'))
