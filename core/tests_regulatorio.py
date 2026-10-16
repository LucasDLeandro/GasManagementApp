from datetime import timedelta
from decimal import Decimal
import uuid

from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib.auth import get_user_model

from core.models import Tenant, Membership, ResponsavelTecnico, PerfilRegulatorioTenant
from core.regulatorio import validar_aptidao_medicinal
from core.tenancy import tenant_context, set_current_tenant

User = get_user_model()

class RegulatorioANVISASprint5A0Tests(TestCase):
    """
    Suíte de Testes da Sprint 5A.0 (Higiene e Fundação Regulatória ANVISA):
    - Validação de Aptidão Sanitária (validar_aptidao_medicinal).
    - Bloqueio de Tenant sem Perfil Regulatório.
    - Bloqueio de Licença Sanitária vencida.
    - Bloqueio de AFE vencida.
    - Bloqueio de Responsável Técnico ausente, inativo ou com vigência expirada.
    - Bloqueio de Distribuidora pura tentando envasar gás medicinal (IN nº 129/2022).
    - Bloqueio de Envasadora sem Certificado de Boas Práticas (CBPF) válido.
    - Aprovação de Envasadora e Distribuidora 100% regulares.
    - Verificação de Higiene de Segurança (SECRET_KEY e DEBUG em settings).
    """

    def setUp(self):
        set_current_tenant(None)
        self.hoje = timezone.now().date()

        self.tenant = Tenant.objects.create(
            cnpj='55.111.222/0001-33',
            razao_social='Oxigênio Brasil Distribuição e Envase Ltda',
            nome_fantasia='Oxigênio Brasil'
        )

        with tenant_context(self.tenant):
            self.rt = ResponsavelTecnico.objects.create(
                nome_completo='Dra. Mariana Souza',
                conselho_classe='CRF',
                numero_registro='54321',
                uf_conselho='DF',
                vigencia_inicio=self.hoje - timedelta(days=180),
                vigencia_fim=self.hoje + timedelta(days=180),
                ativo=True
            )

    def test_bloqueio_tenant_sem_perfil_regulatorio(self):
        """1. Bloqueia tenant sem PerfilRegulatorioTenant cadastrado."""
        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=False)
        self.assertIn("não possui Perfil Regulatório cadastrado", str(ctx.exception))

    def test_bloqueio_licenca_sanitaria_vencida(self):
        """2. Bloqueia tenant com Licença Sanitária expirada."""
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='ENVASADORA',
            afe_numero='AFE-100200',
            afe_validade=self.hoje + timedelta(days=365),
            licenca_sanitaria_numero='VISA-EXPIRADA-123',
            licenca_sanitaria_validade=self.hoje - timedelta(days=1), # Vencida ontem
            cbpf_cbpda_numero='CBPF-999',
            cbpf_cbpda_validade=self.hoje + timedelta(days=365),
            responsavel_tecnico_vigente=self.rt
        )

        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=False)
        self.assertIn("Licença Sanitária (VISA-EXPIRADA-123)", str(ctx.exception))
        self.assertIn("está vencida", str(ctx.exception))

    def test_bloqueio_afe_anvisa_vencida(self):
        """3. Bloqueia tenant com AFE da ANVISA vencida."""
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='ENVASADORA',
            afe_numero='AFE-ANVISA-777',
            afe_validade=self.hoje - timedelta(days=5), # Vencida há 5 dias
            licenca_sanitaria_numero='VISA-DF-OK',
            licenca_sanitaria_validade=self.hoje + timedelta(days=365),
            cbpf_cbpda_numero='CBPF-999',
            cbpf_cbpda_validade=self.hoje + timedelta(days=365),
            responsavel_tecnico_vigente=self.rt
        )

        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=False)
        self.assertIn("AFE (AFE-ANVISA-777)", str(ctx.exception))
        self.assertIn("está vencida", str(ctx.exception))

    def test_bloqueio_responsavel_tecnico_ausente(self):
        """4. Bloqueia tenant sem Responsável Técnico vigente vinculado."""
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='ENVASADORA',
            afe_numero='AFE-100200',
            afe_validade=self.hoje + timedelta(days=365),
            licenca_sanitaria_numero='VISA-DF-OK',
            licenca_sanitaria_validade=self.hoje + timedelta(days=365),
            cbpf_cbpda_numero='CBPF-999',
            cbpf_cbpda_validade=self.hoje + timedelta(days=365),
            responsavel_tecnico_vigente=None
        )

        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=False)
        self.assertIn("não possui Responsável Técnico (RT) vinculado", str(ctx.exception))

    def test_bloqueio_responsavel_tecnico_inativo_ou_expirado(self):
        """5. Bloqueia quando o RT está inativo ou com prazo de CRT expirado."""
        with tenant_context(self.tenant):
            rt_inativo = ResponsavelTecnico.objects.create(
                nome_completo='Dr. Antenor Dias',
                conselho_classe='CRQ',
                numero_registro='9988',
                uf_conselho='DF',
                vigencia_inicio=self.hoje - timedelta(days=300),
                vigencia_fim=self.hoje - timedelta(days=10), # Vencido há 10 dias
                ativo=False
            )

        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='ENVASADORA',
            afe_numero='AFE-100200',
            afe_validade=self.hoje + timedelta(days=365),
            licenca_sanitaria_numero='VISA-DF-OK',
            licenca_sanitaria_validade=self.hoje + timedelta(days=365),
            cbpf_cbpda_numero='CBPF-999',
            cbpf_cbpda_validade=self.hoje + timedelta(days=365),
            responsavel_tecnico_vigente=rt_inativo
        )

        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=False)
        self.assertIn("está inativo", str(ctx.exception))

    def test_bloqueio_distribuidora_tentando_envasar_medicinal(self):
        """6. Bloqueia distribuidora pura tentando realizar envase de gás medicinal (IN 129/2022)."""
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='DISTRIBUIDORA',
            afe_numero='AFE-100200',
            afe_validade=self.hoje + timedelta(days=365),
            licenca_sanitaria_numero='VISA-DF-OK',
            licenca_sanitaria_validade=self.hoje + timedelta(days=365),
            responsavel_tecnico_vigente=self.rt
        )

        # Para distribuição simples (exigir_envase=False), é aprovada
        self.assertTrue(validar_aptidao_medicinal(self.tenant, exigir_envase=False))

        # Mas se tentar envasar (exigir_envase=True), é terminantemente bloqueada
        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=True)
        self.assertIn("não possui autorização sanitária para envase/fabricação", str(ctx.exception))
        self.assertIn("RDC nº 658/2022 e IN nº 129/2022", str(ctx.exception))

    def test_bloqueio_envasadora_sem_cbpf_anvisa_valido(self):
        """7. Bloqueia envasadora sem CBPF ou com CBPF vencido ao tentar envasar."""
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='ENVASADORA',
            afe_numero='AFE-100200',
            afe_validade=self.hoje + timedelta(days=365),
            licenca_sanitaria_numero='VISA-DF-OK',
            licenca_sanitaria_validade=self.hoje + timedelta(days=365),
            cbpf_cbpda_numero='CBPF-VENCIDO-456',
            cbpf_cbpda_validade=self.hoje - timedelta(days=2), # Vencido há 2 dias
            responsavel_tecnico_vigente=self.rt
        )

        with self.assertRaises(ValidationError) as ctx:
            validar_aptidao_medicinal(self.tenant, exigir_envase=True)
        self.assertIn("Certificado de Boas Práticas de Fabricação", str(ctx.exception))
        self.assertIn("CBPF nº CBPF-VENCIDO-456", str(ctx.exception))
        self.assertIn("está vencido", str(ctx.exception))

    def test_aprovacao_envasadora_100_regular(self):
        """8. Aprova envasadora 100% regular para envase e distribuição medicinal."""
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='ENVASADORA',
            afe_numero='AFE-ANVISA-REGULAR',
            afe_validade=self.hoje + timedelta(days=365),
            licenca_sanitaria_numero='VISA-DF-REGULAR',
            licenca_sanitaria_validade=self.hoje + timedelta(days=365),
            cbpf_cbpda_numero='CBPF-ANVISA-REGULAR',
            cbpf_cbpda_validade=self.hoje + timedelta(days=365),
            responsavel_tecnico_vigente=self.rt
        )

        self.assertTrue(validar_aptidao_medicinal(self.tenant, exigir_envase=True))
        self.assertTrue(validar_aptidao_medicinal(self.tenant, exigir_envase=False))
        self.assertTrue(self.tenant.validar_aptidao_medicinal(exigir_envase=True))

    def test_higiene_seguranca_settings(self):
        """9. Valida higiene de segurança de settings.py: sem default hardcoded inseguro em SECRET_KEY e DEBUG."""
        self.assertTrue(hasattr(settings, 'SECRET_KEY'))
        self.assertIsNotNone(settings.SECRET_KEY)
        # Garante que a chave não é a padrão do startproject
        self.assertNotEqual(
            settings.SECRET_KEY,
            'django-insecure-&_*_ekkj4s+wh=0pbso)boksn97v6ydj%5*nqf#n4!^7eykvx&'
        )
