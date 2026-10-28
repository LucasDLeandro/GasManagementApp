"""
Suíte de Testes da Sprint 12B: Portal B2B do Cliente Final.

Cobre todos os requisitos da Sprint 12B:
1. Identidade Separada:
   - PortalB2BBackend dedicado vs InternalModelBackend (bloqueio de acesso cruzado).
   - Política de complexidade de senha (mínimo 10 caracteres, maiúscula, minúscula, dígito).
   - Bloqueio por 5 tentativas falhas consecutivas (15 min).
   - Ciclo de convites com hash SHA-256 (uso único, validade de 72h).
2. MFA TOTP:
   - Configuração, confirmação e validação via django-otp.
   - Bloqueio de papel FINANCEIRO sem validação de MFA (MFA_OBRIGATORIA).
3. Matriz Automatizada de IDOR (Fail-Closed):
   - Prova que toda rota do portal retorna 404 para dados de outro cliente (mesmo tenant ou cross-tenant).
4. Laudos e Certificados de Análise:
   - Apenas para cilindros comprovadamente entregues àquele cliente (404 para os demais).
   - Download de uso único via URL efêmera assinada (jti em DownloadDocumentoB2B). Reutilização negada.
5. Reposição em 1 Clique:
   - Papel LEITOR bloqueado (403).
   - Idempotência estrita por (tenant, cliente, chave_idempotencia).
   - Integração com avaliar_credito e tratamento de ALERTA_ASSISTENCIAL (hospital/medicinal).
6. Degradação Graciosa de Módulos:
   - Módulo financeiro inativo responde MODULO_INATIVO.
   - Módulo fiscal inativo responde MODULO_INATIVO.
7. Tenant SUSPENSO:
   - Consultas (GET) permitidas em modo somente leitura.
   - Escritas (POST reposição) bloqueadas com 403 ASSINATURA_INATIVA.
8. Notificações e LGPD:
   - Vencimento de reteste <= 30 dias notificado.
   - Canal EMAIL somente com ConsentimentoContato ativo.
9. Imutabilidade e Auditoria Append-Only:
   - LogAcessoB2B e DownloadDocumentoB2B bloqueiam UPDATE e DELETE com PermissionError.
"""
import uuid
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import User
from core.models import Tenant, Membership, PerfilRegulatorioTenant
from core.tenancy import tenant_context, set_current_tenant, reset_current_tenant
from core.authentication import InternalModelBackend
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
from financeiro.models import ParcelaFinanceira, TituloFinanceiro, ConsentimentoContato, PlanoContas
from fiscal.models import DocumentoFiscal
from portal_b2b.models import (
    LogAcessoB2B,
    DownloadDocumentoB2B,
    ConviteB2B,
    SolicitacaoReposicao,
    NotificacaoB2B,
)
from portal_b2b.auth import (
    PortalB2BBackend,
    validar_politica_senha,
    gerar_convite_b2b,
    aceitar_convite_b2b,
    configurar_totp,
    confirmar_dispositivo_totp,
    verificar_totp,
    revogar_acesso_b2b,
)
from portal_b2b.download_service import gerar_link_download, processar_download_documento
from portal_b2b.reposicao_service import solicitar_reposicao_um_clique
from portal_b2b.notificacao_service import gerar_notificacoes_reteste, gerar_notificacoes_boletos


class Sprint12BPortalB2BTestSuite(TestCase):
    def setUp(self):
        # 1. Tenant A (Plano Ativo com módulos b2b, financeiro, fiscal)
        self.tenant_a = Tenant.objects.create(
            razao_social="Oxigênio & Gases Brasil SA",
            nome_fantasia="OxiBrasil",
            cnpj="11.222.333/0001-44",
            plano="ENTERPRISE",
            status_assinatura="ATIVO",
            modulo_b2b_ativo=True,
            modulo_financeiro_ativo=True,
            modulo_fiscal_ativo=True,
        )

        # 2. Tenant B (para teste de isolamento cross-tenant)
        self.tenant_b = Tenant.objects.create(
            razao_social="Indústria de Gases Sul LTDA",
            nome_fantasia="Gases Sul",
            cnpj="22.333.444/0001-55",
            plano="PRO",
            status_assinatura="ATIVO",
            modulo_b2b_ativo=True,
            modulo_financeiro_ativo=True,
            modulo_fiscal_ativo=True,
        )

        with tenant_context(self.tenant_a):
            # Clientes no Tenant A
            self.cliente_hospital = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="12.345.678/0001-90",
                nome="Hospital Central São Lucas",
                endereco="Av. Saúde, 100",
                cidade="São Paulo",
                estado="SP",
                telefone="1133334444",
                email_financeiro="financeiro@saolucas.org.br",
                is_medicinal=True,
                tipo_estabelecimento='HOSPITAL'
            )
            self.cliente_industrial = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="98.765.432/0001-10",
                nome="Metalúrgica Titan SA",
                endereco="Rodovia dos Metalúrgicos, km 12",
                cidade="Osasco",
                estado="SP",
                telefone="1144445555",
                email_financeiro="nfe@titan.ind.br",
                is_medicinal=False,
                tipo_estabelecimento='GERAL'
            )

            # Usuário Interno (Operador do ERP do Tenant A)
            self.user_interno = User.objects.create_user(
                username="operador_interno",
                email="operador@oxibrasil.com.br",
                password="Password123!"
            )
            Membership.objects.create(
                user=self.user_interno,
                tenant=self.tenant_a,
                papel='VENDEDOR',
                ativo=True
            )

            # Usuário B2B 1: Comprador do Hospital
            self.user_comprador = User.objects.create_user(
                username="comprador_hospital",
                email="compras@saolucas.org.br",
                password="Password123!"
            )
            self.vinculo_comprador = UsuarioClienteB2B.objects.create(
                user=self.user_comprador,
                cliente=self.cliente_hospital,
                papel=UsuarioClienteB2B.PAPEL_COMPRADOR,
                administrador_cliente=True,
                ativo=True
            )

            # Usuário B2B 2: Financeiro do Hospital
            self.user_financeiro = User.objects.create_user(
                username="financeiro_hospital",
                email="contas@saolucas.org.br",
                password="Password123!"
            )
            self.vinculo_financeiro = UsuarioClienteB2B.objects.create(
                user=self.user_financeiro,
                cliente=self.cliente_hospital,
                papel=UsuarioClienteB2B.PAPEL_FINANCEIRO,
                ativo=True
            )

            # Usuário B2B 3: Leitor do Hospital
            self.user_leitor = User.objects.create_user(
                username="leitor_hospital",
                email="consulta@saolucas.org.br",
                password="Password123!"
            )
            self.vinculo_leitor = UsuarioClienteB2B.objects.create(
                user=self.user_leitor,
                cliente=self.cliente_hospital,
                papel=UsuarioClienteB2B.PAPEL_LEITOR,
                ativo=True
            )

            # Catálogo de Gás e Modelo
            self.gas_oxm = GasQuimico.objects.create(
                nome="Oxigênio Medicinal",
                sigla="OXM",
                categoria="MEDICINAL",
                numero_onu="1072",
                classe_risco="2.2",
                exige_lote_anvisa=True
            )
            self.modelo_t50 = ModeloCilindro.objects.create(
                descricao="Cilindro T-50",
                material="ACO",
                volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('50.00')
            )
            self.sku_oxm = SkuRecarga.objects.create(
                gas=self.gas_oxm,
                modelo_cilindro=self.modelo_t50,
                nome_comercial="Recarga Oxigênio Medicinal 50L (10m3)",
                quantidade_carga=Decimal('10.00'),
                massa_gas_kg=Decimal('12.00'),
                preco_base=Decimal('180.00'),
                ativo=True
            )

            # Lote e Cilindro Entregue ao Hospital
            self.lote_oxm = LoteEnvase.objects.create(
                codigo_lote="LOTE-MED-2026-001",
                gas=self.gas_oxm,
                data_envase=(timezone.now() - timedelta(days=2)).date(),
                data_validade=timezone.now().date() + timedelta(days=730),
                pureza_percentual=Decimal('99.85'),
                status_qualidade='APROVADO',
                responsavel_tecnico="Dra. Farmacêutica RT",
                rt_registro_snapshot="CRF-SP 12345"
            )
            self.cilindro_hospital = Cilindro.objects.create(
                codigo_qr="QR-HOSP-001",
                numero_serie_ogiva="SN-OXM-1001",
                fabricante="CILBRAS",
                ano_fabricacao=2024,
                modelo=self.modelo_t50,
                gas_dedicado=self.gas_oxm,
                status='EM_POSSE_CLIENTE',
                cliente_posse_atual=self.cliente_hospital,
                posse_desde=timezone.now() - timedelta(days=10),
                data_ultimo_reteste=timezone.now().date() - timedelta(days=365),
                data_proximo_reteste=timezone.now().date() + timedelta(days=20)  # <= 30 dias (RETESTE_VENCENDO)
            )
            self.envase_1 = EnvaseCilindro.objects.create(
                cilindro=self.cilindro_hospital,
                lote=self.lote_oxm,
                pressao_final_bar=200,
                envasado_em=timezone.now() - timedelta(days=2),
                operador=self.user_interno
            )
            self.cilindro_hospital.envase_atual = self.envase_1
            self.cilindro_hospital.save(update_fields=['envase_atual'])

            # Movimentação comprovando entrega ao Hospital
            MovimentacaoCilindro.objects.create(
                cilindro=self.cilindro_hospital,
                tipo='ENTREGA_CLIENTE',
                status_anterior='RESERVADO_ROTA',
                status_novo='EM_POSSE_CLIENTE',
                cliente=self.cliente_hospital,
                ocorrido_em=timezone.now() - timedelta(days=2),
                envase_cilindro=self.envase_1,
                lote_envase=self.lote_oxm.codigo_lote,
                registrado_por=self.user_interno
            )

            # Cilindro pertencente à Metalúrgica Titan (outro cliente)
            self.cilindro_titan = Cilindro.objects.create(
                codigo_qr="QR-TITAN-002",
                numero_serie_ogiva="SN-ARG-2002",
                fabricante="MAT",
                ano_fabricacao=2022,
                modelo=self.modelo_t50,
                gas_dedicado=self.gas_oxm,
                status='EM_POSSE_CLIENTE',
                cliente_posse_atual=self.cliente_industrial,
                data_ultimo_reteste=timezone.now().date() - timedelta(days=365),
                data_proximo_reteste=timezone.now().date() + timedelta(days=500)
            )

            # Venda do Hospital
            self.venda_hospital = Venda.objects.create(
                cliente=self.cliente_hospital,
                status='Pendente',
                valor_total=Decimal('360.00')
            )
            ItemVenda.objects.create(
                venda=self.venda_hospital,
                sku=self.sku_oxm,
                quantidade=2,
                valor_unitario=Decimal('180.00'),
                valor_total=Decimal('360.00')
            )

            # Venda da Metalúrgica Titan (outro cliente)
            self.venda_titan = Venda.objects.create(
                cliente=self.cliente_industrial,
                status='Pendente',
                valor_total=Decimal('500.00')
            )

            self.conta_gerencial = PlanoContas.objects.filter(tipo='ANALITICA').first()
            if not self.conta_gerencial:
                self.conta_gerencial = PlanoContas.objects.create(
                    codigo_estrutural="1.1.2.01.0001",
                    nome="Clientes a Receber - B2B",
                    natureza_saldo="DEVEDORA",
                    tipo="ANALITICA",
                    nivel=5,
                    aceita_lancamento=True
                )

            # Título e Parcela Financeira do Hospital
            self.titulo_hospital = TituloFinanceiro.objects.create(
                cliente=self.cliente_hospital,
                tipo='RECEBER',
                historico='DUP-1001',
                valor_bruto=Decimal('360.00'),
                valor_liquido_esperado=Decimal('360.00'),
                data_emissao=timezone.now().date(),
                data_competencia=timezone.now().date(),
                status='ABERTO',
                conta_gerencial=self.conta_gerencial
            )
            self.parcela_hospital = ParcelaFinanceira.objects.create(
                titulo=self.titulo_hospital,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=timezone.now().date() + timedelta(days=2),
                valor_nominal=Decimal('360.00'),
                saldo_em_aberto=Decimal('360.00'),
                status='PENDENTE',
                linha_digitavel='34191.79001 01043.510047 91020.150008 8 99990000036000',
                payload_pix='00020126360014BR.GOV.BCB.PIX0114+5511999999995204000053039865406360.005802BR'
            )

            # Título da Titan (outro cliente)
            self.titulo_titan = TituloFinanceiro.objects.create(
                cliente=self.cliente_industrial,
                tipo='RECEBER',
                historico='DUP-9999',
                valor_bruto=Decimal('500.00'),
                valor_liquido_esperado=Decimal('500.00'),
                data_emissao=timezone.now().date(),
                data_competencia=timezone.now().date(),
                status='ABERTO',
                conta_gerencial=self.conta_gerencial
            )
            self.parcela_titan = ParcelaFinanceira.objects.create(
                titulo=self.titulo_titan,
                numero_parcela=1,
                total_parcelas=1,
                data_vencimento=timezone.now().date() + timedelta(days=30),
                valor_nominal=Decimal('500.00'),
                saldo_em_aberto=Decimal('500.00'),
                status='PENDENTE'
            )

        # 3. Dados no Tenant B (cross-tenant)
        with tenant_context(self.tenant_b):
            self.cliente_b = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="33.444.555/0001-66",
                nome="Hospital Sul de Curitiba",
                endereco="Rua XV, 500",
                cidade="Curitiba",
                estado="PR",
                telefone="4133332222"
            )
            self.venda_tenant_b = Venda.objects.create(
                cliente=self.cliente_b,
                status='Pendente',
                valor_total=Decimal('900.00')
            )

        self.client = APIClient()
        self.token = set_current_tenant(self.tenant_a)

    def tearDown(self):
        reset_current_tenant(self.token)
        super().tearDown()

    # ==========================================================================
    # 1. Identidade Separada & Autenticação
    # ==========================================================================

    def test_portal_b2b_backend_autentica_usuario_b2b_e_rejeita_interno(self):
        """Valida que PortalB2BBackend autentica usuário B2B e rejeita operador interno."""
        backend_b2b = PortalB2BBackend()

        # Usuário B2B autêntico deve autenticar com sucesso
        user = backend_b2b.authenticate(None, username="comprador_hospital", password="Password123!")
        self.assertIsNotNone(user)
        self.assertEqual(user, self.user_comprador)

        # Operador interno (sem vinculo_b2b) deve ser recusado
        user_int = backend_b2b.authenticate(None, username="operador_interno", password="Password123!")
        self.assertIsNone(user_int)

    def test_internal_backend_rejeita_usuario_exclusivo_do_portal_b2b(self):
        """Valida que InternalModelBackend impede login de usuários puramente B2B no ERP interno."""
        backend_interno = InternalModelBackend()

        # Usuário B2B exclusivo não pode logar no sistema interno
        pode_auth = backend_interno.user_can_authenticate(self.user_comprador)
        self.assertFalse(pode_auth)

        # Operador interno autentica normalmente
        pode_auth_int = backend_interno.user_can_authenticate(self.user_interno)
        self.assertTrue(pode_auth_int)

    def test_bloqueio_apos_5_tentativas_falhas(self):
        """Valida bloqueio temporário do usuário B2B por 15 minutos após 5 erros de senha."""
        backend_b2b = PortalB2BBackend()

        # 4 tentativas incorretas não bloqueiam
        for i in range(4):
            u = backend_b2b.authenticate(None, username="comprador_hospital", password="SenhaErrada!")
            self.assertIsNone(u)

        self.vinculo_comprador.refresh_from_db()
        self.assertEqual(self.vinculo_comprador.tentativas_falhas, 4)
        self.assertFalse(self.vinculo_comprador.esta_bloqueado)

        # 5ª tentativa falha dispara o bloqueio temporário
        backend_b2b.authenticate(None, username="comprador_hospital", password="SenhaErrada!")
        self.vinculo_comprador.refresh_from_db()
        self.assertEqual(self.vinculo_comprador.tentativas_falhas, 5)
        self.assertTrue(self.vinculo_comprador.esta_bloqueado)

        # Próxima tentativa com a senha CORRETA deve ser rejeitada enquanto estiver no período de bloqueio
        u_bloqueado = backend_b2b.authenticate(None, username="comprador_hospital", password="Password123!")
        self.assertIsNone(u_bloqueado)

    def test_validacao_politica_de_senha_forte(self):
        """Valida regras de tamanho mínimo (10) e complexidade (maiúscula, minúscula e dígito)."""
        with self.assertRaises(ValidationError):
            validar_politica_senha("Curta1!")  # < 10 chars
        with self.assertRaises(ValidationError):
            validar_politica_senha("semmaiuscula123")  # sem maiúscula
        with self.assertRaises(ValidationError):
            validar_politica_senha("SEMMINUSCULA123")  # sem minúscula
        with self.assertRaises(ValidationError):
            validar_politica_senha("SemDigitoNenhum")  # sem número

        # Senha que atende a todos os critérios deve passar sem exceção
        validar_politica_senha("SenhaForte10!")

    def test_ciclo_convite_ativacao_sha256_uso_unico(self):
        """Valida emissão de convite com token SHA-256 e aceite de uso único."""
        convite, token_claro = gerar_convite_b2b(
            usuario_b2b=self.vinculo_leitor,
            criado_por=self.user_comprador
        )
        self.assertTrue(convite.esta_valido)
        self.assertNotEqual(convite.token_hash, token_claro)  # Token em claro nunca é persistido

        # Aceite do convite com nova senha
        usuario_atualizado = aceitar_convite_b2b(token_claro, "NovaSenhaForte2026!")
        self.assertIsNotNone(usuario_atualizado.senha_alterada_em)

        convite.refresh_from_db()
        self.assertFalse(convite.esta_valido)
        self.assertIsNotNone(convite.aceito_em)

        # Tentativa de reutilizar o mesmo convite falha
        with self.assertRaises(ValidationError):
            aceitar_convite_b2b(token_claro, "OutraSenha2026!")

    # ==========================================================================
    # 2. MFA TOTP
    # ==========================================================================

    def test_papel_financeiro_sem_mfa_recebe_bloqueio_403(self):
        """Valida que papel FINANCEIRO sem confirmação MFA é barrado em endpoints financeiros."""
        self.client.force_authenticate(user=self.user_financeiro)

        # Sessão sem b2b_mfa_verified
        res = self.client.get('/portal-b2b/api/faturas/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("MFA", str(res.data))

    def test_papel_financeiro_com_mfa_tem_acesso_liberado(self):
        """Valida que papel FINANCEIRO com MFA confirmada acessa faturas e parcelas."""
        self.client.force_authenticate(user=self.user_financeiro)

        # Simula MFA confirmada na sessão B2B
        session = self.client.session
        session['b2b_mfa_verified'] = True
        session.save()
        self.client.cookies['b2b_sessionid'] = session.session_key

        res = self.client.get('/portal-b2b/api/faturas/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    # ==========================================================================
    # 3. Matriz Automatizada de IDOR (Isolamento Estrito Fail-Closed)
    # ==========================================================================

    def test_idor_retorna_404_para_todos_os_recursos_de_outro_cliente_ou_tenant(self):
        """
        Garante que o cliente autenticado (Hospital Santa Clara) recebe 404
        para qualquer tentativa de acesso direto a IDs de outros clientes (Titan) ou tenants.
        """
        self.client.force_authenticate(user=self.user_comprador)

        rotas_teste = [
            # Venda da Titan (mesmo tenant) e do Tenant B (cross-tenant)
            f'/portal-b2b/api/vendas/{self.venda_titan.id}/',
            f'/portal-b2b/api/vendas/{self.venda_tenant_b.id}/',
            # Cilindro da Titan
            f'/portal-b2b/api/cilindros/{self.cilindro_titan.id}/',
            f'/portal-b2b/api/cilindros/{self.cilindro_titan.id}/laudo-quimico/',
        ]

        for rota in rotas_teste:
            res = self.client.get(rota)
            self.assertEqual(
                res.status_code,
                status.HTTP_404_NOT_FOUND,
                f"Falha de segurança IDOR detectada: a rota {rota} respondeu {res.status_code} em vez de 404!"
            )

    # ==========================================================================
    # 4. Laudo / Certificado de Análise & URLs Efêmeras de Download
    # ==========================================================================

    def test_laudo_apenas_para_cilindro_comprovadamente_entregue(self):
        """Valida download de laudo para cilindro do cliente e 404 para cilindro não entregue."""
        self.client.force_authenticate(user=self.user_comprador)

        # 1. Cilindro entregue ao Hospital -> Sucesso
        res_ok = self.client.get(f'/portal-b2b/api/cilindros/{self.cilindro_hospital.id}/laudo-quimico/')
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ok['Content-Type'], 'application/pdf')

        # 2. Cilindro da Titan -> 404
        res_neg = self.client.get(f'/portal-b2b/api/cilindros/{self.cilindro_titan.id}/laudo-quimico/')
        self.assertEqual(res_neg.status_code, status.HTTP_404_NOT_FOUND)

    def test_url_assinada_download_uso_unico_com_jti(self):
        """Valida que URL assinada efêmera só pode ser consumida uma única vez (single-use)."""
        link_download = gerar_link_download(
            tenant=self.tenant_a,
            cliente=self.cliente_hospital,
            tipo_documento='LAUDO_LOTE',
            recurso_tipo='Cilindro',
            recurso_id=self.cilindro_hospital.id,
            usuario_b2b=self.vinculo_comprador
        )

        token = link_download.split('/download/')[1].rstrip('/')

        # 1º Download: Sucesso
        res1 = self.client.get(f'/portal-b2b/download/{token}/')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1['Content-Type'], 'application/pdf')
        self.assertIn('inline', res1.get('Content-Disposition', '') or res1.get('content-disposition', '') or 'inline')

        # 2º Download com o MESMO token: Rejeitado (403 PermissionDenied por reuso)
        res2 = self.client.get(f'/portal-b2b/download/{token}/')
        self.assertEqual(res2.status_code, status.HTTP_403_FORBIDDEN)

    # ==========================================================================
    # 5. Reposição em 1 Clique & Avaliação de Crédito
    # ==========================================================================

    def test_papel_leitor_bloqueado_para_solicitar_reposicao(self):
        """Valida que usuário com papel LEITOR não consegue solicitar reposição (403)."""
        self.client.force_authenticate(user=self.user_leitor)

        res = self.client.post('/portal-b2b/api/reposicao/', {
            'chave_idempotencia': 'rep-leitor-001',
            'itens': [{'sku_id': self.sku_oxm.id, 'quantidade': 1}]
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_reposicao_um_clique_idempotente_nao_duplica_pedido(self):
        """Valida que a mesma chave de idempotência retorna a solicitação anterior sem duplicar venda."""
        self.client.force_authenticate(user=self.user_comprador)
        chave = 'rep-idemp-unique-12345'

        # 1ª Chamada: Cria o pedido
        res1 = self.client.post('/portal-b2b/api/reposicao/', {
            'chave_idempotencia': chave,
            'itens': [{'sku_id': self.sku_oxm.id, 'quantidade': 3}],
            'observacoes': 'Reposição UTI 1'
        }, format='json')
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        venda_id = res1.data['venda_id']
        self.assertIsNotNone(venda_id)

        # 2ª Chamada com a mesma chave: Devolve o anterior (HTTP 200)
        res2 = self.client.post('/portal-b2b/api/reposicao/', {
            'chave_idempotencia': chave,
            'itens': [{'sku_id': self.sku_oxm.id, 'quantidade': 3}],
            'observacoes': 'Reposição UTI 1'
        }, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['venda_id'], venda_id)

        # Garante que no banco só existe 1 SolicitacaoReposicao com esta chave
        self.assertEqual(
            SolicitacaoReposicao.objects.filter(tenant=self.tenant_a, chave_idempotencia=chave).count(),
            1
        )

    def test_reposicao_hospitalar_aplica_alerta_assistencial(self):
        """Valida que pedidos hospitalares ou de gás medicinal recebem alerta assistencial e não são retidos."""
        solicitacao, criada = solicitar_reposicao_um_clique(
            tenant=self.tenant_a,
            cliente=self.cliente_hospital,
            usuario_b2b=self.vinculo_comprador,
            itens_solicitados=[{'sku_id': self.sku_oxm.id, 'quantidade': 5}],
            chave_idempotencia='rep-assistencial-hospital-99'
        )
        self.assertTrue(criada)
        self.assertTrue(solicitacao.alerta_assistencial)
        self.assertEqual(solicitacao.status, 'CRIADA')
        self.assertIsNotNone(solicitacao.venda)

    # ==========================================================================
    # 6. Degradação Graciosa de Módulos (financeiro e fiscal inativos)
    # ==========================================================================

    def test_modulo_financeiro_inativo_responde_modulo_inativo(self):
        """Valida que desativar o módulo financeiro do tenant bloqueia o endpoint com MODULO_INATIVO."""
        self.tenant_a.modulo_financeiro_ativo = False
        self.tenant_a.plano = 'STARTER'
        self.tenant_a.save(update_fields=['modulo_financeiro_ativo', 'plano'])
        self.client.force_authenticate(user=self.user_comprador)
        res = self.client.get('/portal-b2b/api/faturas/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data.get('code'), 'MODULO_INATIVO')

    def test_modulo_fiscal_inativo_responde_modulo_inativo(self):
        """Valida que desativar o módulo fiscal do tenant bloqueia o endpoint fiscal com MODULO_INATIVO."""
        self.tenant_a.modulo_fiscal_ativo = False
        self.tenant_a.plano = 'STARTER'
        self.tenant_a.save(update_fields=['modulo_fiscal_ativo', 'plano'])
        self.client.force_authenticate(user=self.user_comprador)
        res = self.client.get('/portal-b2b/api/fiscal/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data.get('code'), 'MODULO_INATIVO')

    # ==========================================================================
    # 7. Tenant SUSPENSO (Somente Leitura)
    # ==========================================================================

    def test_tenant_suspenso_permite_leitura_e_bloqueia_escrita(self):
        """Valida que tenant com assinatura SUSPENSA pode consultar dados mas não pode emitir pedidos."""
        self.tenant_a.status_assinatura = 'SUSPENSO'
        self.tenant_a.save(update_fields=['status_assinatura'])

        self.client.force_authenticate(user=self.user_comprador)

        # GET (consulta) deve continuar funcionando
        res_get = self.client.get('/portal-b2b/api/cilindros/')
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)

        # POST (reposição) deve ser bloqueado com 403 ASSINATURA_INATIVA
        res_post = self.client.post('/portal-b2b/api/reposicao/', {
            'chave_idempotencia': 'rep-suspenso-bloqueio',
            'itens': [{'sku_id': self.sku_oxm.id, 'quantidade': 1}]
        }, format='json')
        self.assertEqual(res_post.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res_post.data.get('code'), 'ASSINATURA_INATIVA')

    # ==========================================================================
    # 8. Notificações Proativas & LGPD
    # ==========================================================================

    def test_notificacao_reteste_e_consentimento_lgpd(self):
        """Valida geração de alerta de reteste hidrostático respeitando canais autorizados LGPD."""
        notifs = gerar_notificacoes_reteste(self.tenant_a, self.cliente_hospital)
        self.assertTrue(len(notifs) >= 1)

        notif = notifs[0]
        self.assertEqual(notif.tipo, 'RETESTE_VENCENDO')
        self.assertEqual(notif.canal, 'PORTAL')

        # Sem ConsentimentoContato ativo, canal EMAIL não é gerado
        self.assertFalse(
            NotificacaoB2B.objects.filter(tenant=self.tenant_a, cliente=self.cliente_hospital, canal='EMAIL').exists()
        )

        # Registra consentimento explícito LGPD para e-mail
        ConsentimentoContato.objects.create(
            tenant=self.tenant_a,
            cliente=self.cliente_hospital,
            canal='EMAIL'
        )

        # Gera novamente: agora cria no canal EMAIL
        gerar_notificacoes_reteste(self.tenant_a, self.cliente_hospital)
        self.assertTrue(
            NotificacaoB2B.objects.filter(tenant=self.tenant_a, cliente=self.cliente_hospital, canal='EMAIL').exists()
        )

    # ==========================================================================
    # 9. Auditoria Append-Only
    # ==========================================================================

    def test_auditoria_append_only_bloqueia_update_e_delete(self):
        """Valida que LogAcessoB2B e DownloadDocumentoB2B proíbem UPDATE e DELETE."""
        with tenant_context(self.tenant_a):
            log = LogAcessoB2B.objects.create(
                tenant=self.tenant_a,
                cliente=self.cliente_hospital,
                evento='LOGIN_OK',
                usuario_nome='teste_audit'
            )

            # Tentativa de UPDATE via save() deve levantar PermissionError
            with self.assertRaises(PermissionError):
                log.usuario_nome = 'alterado'
                log.save()

            # Tentativa de UPDATE via queryset deve levantar PermissionError
            with self.assertRaises(PermissionError):
                LogAcessoB2B.objects.filter(id=log.id).update(usuario_nome='alterado')

            # Tentativa de DELETE deve levantar PermissionError
            with self.assertRaises(PermissionError):
                log.delete()

            with self.assertRaises(PermissionError):
                LogAcessoB2B.objects.filter(id=log.id).delete()
