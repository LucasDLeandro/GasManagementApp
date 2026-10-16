import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from core.models import Tenant, Membership, ResponsavelTecnico, PerfilRegulatorioTenant
from core.regulatorio import validar_aptidao_medicinal
from core.tenancy import tenant_context, set_current_tenant
from produtos.models import (
    Cilindro,
    ModeloCilindro,
    GasQuimico,
    LoteEnvase,
    EnvaseCilindro,
)
from clientes.models import Cliente

User = get_user_model()


class FaseFinalConsolidacaoTests(TestCase):
    """
    Suíte Completa de Testes da Fase Final de Consolidação:
    1. Passaporte Sanitário Público (sem login, status apto/bloqueado, sem vazamento financeiro/clientes).
    2. Download seguro do Laudo Analítico (PDF) via QR Code hospitalar.
    3. Impressão de Etiquetas Térmicas (Casco 60x40mm e Colarinho IN 129/2022).
    4. Console de Perfil Regulatório ANVISA (RBAC, badges semânticos, gestão de RTs CRF/CRQ).
    5. Bloqueio de Operações Medicinais com Perfil Regulatório expirado.
    """

    def setUp(self):
        set_current_tenant(None)
        self.hoje = timezone.now().date()

        # 1. Tenant Principal
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Oxigênio Medicinal Paulistano Ltda',
            nome_fantasia='OxiPaulistano'
        )

        with tenant_context(self.tenant):
            # Usuários
            self.user_admin = User.objects.create_user(
                username='admin_reg',
                email='admin@oxipaulistano.com.br',
                password='senha_segura_123'
            )
            self.membership_admin = Membership.objects.create(
                user=self.user_admin,
                tenant=self.tenant,
                papel='ADMIN',
                ativo=True
            )

            self.user_gerente = User.objects.create_user(
                username='gerente_reg',
                email='gerente@oxipaulistano.com.br',
                password='senha_segura_123'
            )
            self.membership_gerente = Membership.objects.create(
                user=self.user_gerente,
                tenant=self.tenant,
                papel='GERENTE',
                ativo=True
            )

            self.user_operador = User.objects.create_user(
                username='operador_patio',
                email='operador@oxipaulistano.com.br',
                password='senha_segura_123'
            )
            self.membership_operador = Membership.objects.create(
                user=self.user_operador,
                tenant=self.tenant,
                papel='OPERADOR_PATIO',
                ativo=True
            )

            # Responsável Técnico
            self.rt = ResponsavelTecnico.objects.create(
                nome_completo='Dra. Vanessa Mendes',
                conselho_classe='CRF',
                numero_registro='78910',
                uf_conselho='SP',
                vigencia_inicio=self.hoje - timedelta(days=60),
                vigencia_fim=self.hoje + timedelta(days=300),
                ativo=True
            )

            # Perfil Regulatório
            self.perfil = PerfilRegulatorioTenant.objects.create(
                tenant=self.tenant,
                modo_operacao='ENVASADORA',
                afe_numero='AFE-7.44332.1',
                afe_validade=self.hoje + timedelta(days=365),
                licenca_sanitaria_numero='VISA-SP-998877',
                licenca_sanitaria_validade=self.hoje + timedelta(days=180),
                cbpf_cbpda_numero='CBPF-2026/099',
                cbpf_cbpda_validade=self.hoje + timedelta(days=365),
                responsavel_tecnico_vigente=self.rt
            )

            # Gás Medicinal ABNT
            self.gas_med = GasQuimico.objects.create(
                nome='Oxigênio Medicinal',
                sigla='OX_MED',
                categoria='MEDICINAL',
                numero_onu='1072',
                classe_risco='2.2',
                cor_padrao_abnt='Verde Esmeralda',
                exige_lote_anvisa=True
            )

            # Modelo de Cilindro
            self.modelo_cil = ModeloCilindro.objects.create(
                descricao='Cilindro Aço 50L Medicinal',
                material='ACO',
                volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('62.50'),
                periodicidade_reteste_anos=5
            )

            # Cliente (Para testar se dados privados vazam ou não)
            self.cliente_privado = Cliente.objects.create(
                nome='Hospital Santa Isabel Unidade Central',
                cnpj='33.444.555/0001-66',
                endereco='Av. Paulista, 1000',
                telefone='(11) 3333-4444',
                estado='SP',
                cidade='São Paulo',
                proprietario='Diretoria Hospitalar'
            )

            # Lote de Envase com Laudo PDF
            pdf_dummy = SimpleUploadedFile("laudo_lote_med_01.pdf", b"%PDF-1.4 Laudo Analitico Pureza 99.8%", content_type="application/pdf")
            self.lote = LoteEnvase.objects.create(
                codigo_lote='LOT-2026-MED-8899',
                gas=self.gas_med,
                data_envase=self.hoje,
                data_validade=self.hoje + timedelta(days=730),
                pureza_percentual=Decimal('99.80'),
                responsavel_tecnico=self.rt.nome_completo,
                responsavel_tecnico_fk=self.rt,
                status_qualidade='APROVADO',
                laudo_pdf=pdf_dummy
            )

            # Cilindro Conforme com Carga Ativa
            self.cilindro_apto = Cilindro.objects.create(
                codigo_qr='CIL-MED-0001',
                numero_serie_ogiva='OGV-998811',
                modelo=self.modelo_cil,
                gas_dedicado=self.gas_med,
                tara_real_kg=Decimal('62.80'),
                fabricante='Matheson',
                ano_fabricacao=2022,
                data_ultimo_reteste=self.hoje - timedelta(days=365),
                data_proximo_reteste=self.hoje + timedelta(days=1095),
                status='CHEIO_ARMAZENADO',
                bloqueio_sanitario=False,
                cliente_posse_atual=self.cliente_privado
            )

            self.envase = EnvaseCilindro.objects.create(
                cilindro=self.cilindro_apto,
                lote=self.lote,
                operador=self.user_admin,
                pressao_final_bar=200,
                envasado_em=timezone.now()
            )
            self.cilindro_apto.envase_atual = self.envase
            self.cilindro_apto.save()

            # Cilindro Bloqueado / Em Recall
            self.cilindro_bloqueado = Cilindro.objects.create(
                codigo_qr='CIL-MED-0002',
                numero_serie_ogiva='OGV-112233',
                modelo=self.modelo_cil,
                gas_dedicado=self.gas_med,
                tara_real_kg=Decimal('62.50'),
                fabricante='Cilbras',
                ano_fabricacao=2020,
                data_ultimo_reteste=self.hoje - timedelta(days=2000),
                data_proximo_reteste=self.hoje - timedelta(days=10), # Reteste vencido
                status='QUARENTENA_RECALL',
                bloqueio_sanitario=True,
                motivo_bloqueio_sanitario='Desvio de pureza no contra-laudo microbiológico'
            )

    # ==============================================================================
    # 1. PASSAPORTE SANITÁRIO PÚBLICO & ISOLAMENTO DE DADOS
    # ==============================================================================

    def test_passaporte_publico_sem_login_status_apto_e_isolamento(self):
        """Acesso anônimo ao Passaporte exibe conformidade verde e NUNCA expõe dados de clientes/financeiros."""
        client = Client()
        
        # Acesso via QR Code
        res_qr = client.get(f'/v/cilindro/{self.cilindro_apto.codigo_qr}/')
        self.assertEqual(res_qr.status_code, 200)

        # Acesso via Série da Ogiva
        res_serie = client.get(f'/v/cilindro/{self.cilindro_apto.numero_serie_ogiva}/')
        self.assertEqual(res_serie.status_code, 200)

        conteudo = res_qr.content.decode('utf-8')

        # 1. Status Sanitário Apto em Destaque
        self.assertIn("APTO PARA USO", conteudo)
        self.assertIn("sanitary-banner-apto", conteudo)

        # 2. Dados da Distribuidora/Envasadora e Licenças
        self.assertIn("Oxigênio Medicinal Paulistano Ltda", conteudo)
        self.assertIn("11.222.333/0001-44", conteudo)
        self.assertIn("AFE-7.44332.1", conteudo)
        self.assertIn("VISA-SP-998877", conteudo)

        # 3. Ficha Técnica do Casco
        self.assertIn("OGV-998811", conteudo)
        self.assertIn("Oxigênio Medicinal (OX_MED)", conteudo)
        self.assertIn("50", conteudo)
        self.assertIn("200 bar", conteudo)

        # 4. Dados do Lote e RT
        self.assertIn("LOT-2026-MED-8899", conteudo)
        self.assertIn("Dra. Vanessa Mendes", conteudo)
        self.assertIn("CRF-SP 78910", conteudo)

        # 5. Link Seguro para Laudo PDF
        self.assertIn(f"/v/cilindro/{self.cilindro_apto.codigo_qr}/laudo/", conteudo)

        # 6. BLINDAGEM: Jamais vazar clientes, contratos ou financeiro
        self.assertNotIn("Hospital Santa Isabel", conteudo)
        self.assertNotIn("Av. Paulista", conteudo)
        self.assertNotIn("33.444.555/0001-66", conteudo)
        self.assertNotIn("R$", conteudo)
        self.assertNotIn("Contrato", conteudo)

    def test_passaporte_publico_bloqueio_sanitario_e_reteste_vencido(self):
        """Passaporte de cilindro com pendências exibe faixa vermelha de bloqueio com os motivos listados."""
        client = Client()
        res = client.get(f'/v/cilindro/{self.cilindro_bloqueado.codigo_qr}/')
        self.assertEqual(res.status_code, 200)

        conteudo = res.content.decode('utf-8')
        self.assertIn("BLOQUEADO / EM RECALL — NÃO UTILIZAR", conteudo)
        self.assertIn("sanitary-banner-bloqueado", conteudo)
        self.assertIn("Desvio de pureza no contra-laudo microbiológico", conteudo)
        self.assertIn("Validade do ensaio hidrostático (INMETRO) expirada", conteudo)

    def test_passaporte_publico_download_laudo_seguro(self):
        """Auditor ou farmacêutico pode baixar o PDF do laudo do lote ativo sem login."""
        client = Client()
        res = client.get(f'/v/cilindro/{self.cilindro_apto.codigo_qr}/laudo/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        content = b"".join(res.streaming_content) if hasattr(res, 'streaming_content') else res.content
        self.assertIn(b"%PDF-1.4 Laudo Analitico Pureza 99.8%", content)

        # Cilindro sem carga ativa retorna 404
        res_sem_carga = client.get(f'/v/cilindro/{self.cilindro_bloqueado.codigo_qr}/laudo/')
        self.assertEqual(res_sem_carga.status_code, 404)

    # ==============================================================================
    # 2. IMPRESSÃO DE ETIQUETAS TÉRMICAS
    # ==============================================================================

    def test_etiqueta_casco_60x40_geracao(self):
        """Gera etiqueta térmica 60x40mm com QR Code e série da ogiva."""
        client = Client()
        client.force_login(self.user_admin)

        res = client.get(f'/produtos/cilindros/{self.cilindro_apto.id}/etiqueta-casco/')
        self.assertEqual(res.status_code, 200)

        conteudo = res.content.decode('utf-8')
        self.assertIn("data:image/png;base64,", conteudo)
        self.assertIn("OGV-998811", conteudo)
        self.assertIn("OxiPaulistano", conteudo)
        self.assertIn("OX_MED", conteudo)
        self.assertIn("60mm 40mm", conteudo)

    def test_etiqueta_colarinho_in129_geracao(self):
        """Gera etiqueta de colarinho/gargalo conforme IN 129/2022."""
        client = Client()
        client.force_login(self.user_admin)

        # Via Lote
        res_lote = client.get(f'/produtos/lotes/{self.lote.id}/etiqueta-colarinho/')
        self.assertEqual(res_lote.status_code, 200)
        conteudo_lote = res_lote.content.decode('utf-8')
        self.assertIn("LOT-2026-MED-8899", conteudo_lote)
        self.assertIn("Oxigênio Medicinal", conteudo_lote)
        self.assertIn("ONU: 1072", conteudo_lote)
        self.assertIn("Dra. Vanessa Mendes", conteudo_lote)
        self.assertIn("Gás Medicinal. Venda sob prescrição médica.", conteudo_lote)

        # Via Cilindro com envase ativo
        res_cil = client.get(f'/produtos/cilindros/{self.cilindro_apto.id}/etiqueta-colarinho/')
        self.assertEqual(res_cil.status_code, 200)
        self.assertIn("LOT-2026-MED-8899", res_cil.content.decode('utf-8'))

    # ==============================================================================
    # 3. INTERFACE DO PERFIL REGULATÓRIO & GESTÃO DE RTs
    # ==============================================================================

    def test_perfil_regulatorio_rbac(self):
        """Apenas ADMIN e GERENTE acessam o console de Perfil Regulatório."""
        client = Client()

        # Anônimo redireciona para login
        res_anon = client.get('/perfil-regulatorio/')
        self.assertEqual(res_anon.status_code, 302)

        # Operador de pátio recebe 403 Forbidden
        client.force_login(self.user_operador)
        res_op = client.get('/perfil-regulatorio/')
        self.assertEqual(res_op.status_code, 403)

        # Gerente e Admin recebem 200 OK
        client.force_login(self.user_gerente)
        res_ger = client.get('/perfil-regulatorio/')
        self.assertEqual(res_ger.status_code, 200)

        client.force_login(self.user_admin)
        res_adm = client.get('/perfil-regulatorio/')
        self.assertEqual(res_adm.status_code, 200)

    def test_perfil_regulatorio_edicao_e_gestao_rt(self):
        """Salva alterações do perfil regulatório e cadastra novo RT via POST AJAX."""
        client = Client()
        client.force_login(self.user_admin)

        # 1. Atualizar Perfil Regulatório
        res_post_perfil = client.post('/perfil-regulatorio/', {
            'action': 'salvar_perfil',
            'modo_operacao': 'MISTO',
            'afe_numero': 'AFE-NOVA-888',
            'afe_validade': (self.hoje + timedelta(days=500)).isoformat(),
            'licenca_sanitaria_numero': 'VISA-NOVA-555',
            'licenca_sanitaria_validade': (self.hoje + timedelta(days=200)).isoformat(),
            'cbpf_cbpda_numero': 'CBPF-NOVO-111',
            'cbpf_cbpda_validade': (self.hoje + timedelta(days=365)).isoformat(),
            'responsavel_tecnico_vigente': self.rt.id
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(res_post_perfil.status_code, 200)
        self.assertTrue(res_post_perfil.json().get('sucesso'))

        self.perfil.refresh_from_db()
        self.assertEqual(self.perfil.modo_operacao, 'MISTO')
        self.assertEqual(self.perfil.afe_numero, 'AFE-NOVA-888')

        # 2. Cadastrar novo Responsável Técnico (CRQ)
        res_post_rt = client.post('/perfil-regulatorio/', {
            'action': 'salvar_rt',
            'nome_completo': 'Dr. Marcos Oliveira Químico',
            'conselho_classe': 'CRQ',
            'numero_registro': '99441',
            'uf_conselho': 'SP',
            'vigencia_inicio': self.hoje.isoformat(),
            'vigencia_fim': (self.hoje + timedelta(days=365)).isoformat(),
            'ativo': 'true'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(res_post_rt.status_code, 200)
        self.assertTrue(res_post_rt.json().get('sucesso'))
        novo_rt_id = res_post_rt.json()['rt']['id']

        # 3. Definir o novo RT como titular vigente
        res_titular = client.post('/perfil-regulatorio/', {
            'action': 'definir_rt_vigente',
            'rt_id': novo_rt_id
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(res_titular.status_code, 200)
        self.perfil.refresh_from_db()
        self.assertEqual(self.perfil.responsavel_tecnico_vigente_id, novo_rt_id)

    # ==============================================================================
    # 4. BLOQUEIO DE OPERAÇÕES MEDICINAIS QUANDO PERFIL REGULATÓRIO VENCIDO
    # ==============================================================================

    def test_bloqueio_operacoes_medicinais_perfil_vencido(self):
        """O validador sanitário bloqueia operações quando licenças ou RT estão vencidos."""
        # 1. Com perfil em dia, validação passa com sucesso
        self.assertTrue(validar_aptidao_medicinal(self.tenant, exigir_envase=True))

        # 2. Licença Sanitária expirada bloqueia
        self.perfil.licenca_sanitaria_validade = self.hoje - timedelta(days=1)
        self.perfil.save()
        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=False)
        self.assertIn("está vencida", str(ctx.exception))

        # 3. RT inativo ou com vigência expirada bloqueia
        self.perfil.licenca_sanitaria_validade = self.hoje + timedelta(days=100)
        self.perfil.save()

        self.rt.ativo = False
        self.rt.save()
        with self.assertRaises(ValidationError) as ctx_rt:
            validar_aptidao_medicinal(self.tenant, exigir_envase=False)
        self.assertIn("inativo", str(ctx_rt.exception))
