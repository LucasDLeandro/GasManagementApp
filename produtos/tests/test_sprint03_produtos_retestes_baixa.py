import datetime
from decimal import Decimal
import os
import re

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status

from core.models import Membership, Tenant
from core.tenancy import set_current_tenant
from produtos.models import (
    BaixaPatrimonial,
    Cilindro,
    EnvioReteste,
    GasQuimico,
    HistoricoRetesteHidrostatico,
    ModeloCilindro,
)

User = get_user_model()


class BaseSprint03TestCase(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Gases Brasil Ltda',
            nome_fantasia='Brasil Gás',
            modulo_patrimonio_ativo=True,
            modulo_envase_ativo=True,
        )
        self.outro_tenant = Tenant.objects.create(
            cnpj='99.888.777/0001-66',
            razao_social='Outra Empresa Ltda',
            nome_fantasia='Outra Gás',
            modulo_patrimonio_ativo=True,
        )
        set_current_tenant(self.tenant)

        self.admin = User.objects.create_user(username='s3_admin', password='123', email='admin@s3.com')
        Membership.objects.create(user=self.admin, tenant=self.tenant, papel='ADMIN', ativo=True)

        self.gerente = User.objects.create_user(username='s3_gerente', password='123', email='gerente@s3.com')
        Membership.objects.create(user=self.gerente, tenant=self.tenant, papel='GERENTE', ativo=True)

        self.operador = User.objects.create_user(username='s3_operador', password='123', email='op@s3.com')
        Membership.objects.create(user=self.operador, tenant=self.tenant, papel='OPERADOR_PATIO', ativo=True)

        self.vendedor = User.objects.create_user(username='s3_vendedor', password='123', email='vend@s3.com')
        Membership.objects.create(user=self.vendedor, tenant=self.tenant, papel='VENDEDOR', ativo=True)

        self.gas = GasQuimico.objects.create(nome='Oxigênio', sigla='O2', categoria='MEDICINAL')
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao='Cilindro 50L Aço (3 anos)',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('55.00'),
            periodicidade_reteste_anos=3,
        )

        self.cilindro_vazio = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-S3-01',
            numero_serie_ogiva='SR-S3-01',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2020,
            tara_real_kg=Decimal('55.000'),
            status='VAZIO_TRIAGEM',
            data_ultimo_reteste=self.hoje - datetime.timedelta(days=1100),
            data_proximo_reteste=self.hoje - datetime.timedelta(days=5),
        )

        self.cilindro_cheio = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-S3-02',
            numero_serie_ogiva='SR-S3-02',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2020,
            status='CHEIO_DISPONIVEL',
            data_ultimo_reteste=self.hoje - datetime.timedelta(days=100),
            data_proximo_reteste=self.hoje + datetime.timedelta(days=900),
        )

        self.cilindro_bloqueado = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-S3-03',
            numero_serie_ogiva='SR-S3-03',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2020,
            status='VAZIO_TRIAGEM',
            bloqueio_sanitario=True,
            motivo_bloqueio_sanitario='Recall sanitário ativo',
            data_ultimo_reteste=self.hoje - datetime.timedelta(days=1100),
            data_proximo_reteste=self.hoje - datetime.timedelta(days=2),
        )

        set_current_tenant(self.outro_tenant)
        self.modelo_outro = ModeloCilindro.objects.create(
            tenant=self.outro_tenant,
            descricao='Modelo Outro',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('55.00'),
        )
        self.cilindro_outro = Cilindro.objects.create(
            tenant=self.outro_tenant,
            codigo_qr='QR-OUTRO-01',
            numero_serie_ogiva='SR-OUTRO-01',
            modelo=self.modelo_outro,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2021,
            status='VAZIO_TRIAGEM',
            data_ultimo_reteste=self.hoje,
            data_proximo_reteste=self.hoje + datetime.timedelta(days=1000),
        )
        set_current_tenant(self.tenant)


class TestEnvioERetornoReteste(BaseSprint03TestCase):
    """03.1: Envio em lote, retorno completo, expansão permanente e retificação."""

    def test_envio_recusa_cilindro_cheio_bloqueado_ou_outro_tenant(self):
        self.client.force_login(self.gerente)
        base_payload = {
            'oficina_nome': 'Requalificadora Sul',
            'oficina_cnpj': '11.222.333/0001-44',
            'documento_envio': 'ROM-2026-001',
        }

        # Cilindro cheio -> 400
        res_cheio = self.client.post(
            '/produtos/api/patrimonio/envios-reteste/',
            {**base_payload, 'cilindro_ids': [str(self.cilindro_cheio.id)]},
            format='json',
        )
        self.assertEqual(res_cheio.status_code, status.HTTP_400_BAD_REQUEST)

        # Cilindro com bloqueio sanitário -> 400
        res_bloq = self.client.post(
            '/produtos/api/patrimonio/envios-reteste/',
            {**base_payload, 'cilindro_ids': [str(self.cilindro_bloqueado.id)]},
            format='json',
        )
        self.assertEqual(res_bloq.status_code, status.HTTP_400_BAD_REQUEST)

        # Cilindro de outro tenant -> 400
        res_outro = self.client.post(
            '/produtos/api/patrimonio/envios-reteste/',
            {**base_payload, 'cilindro_ids': [str(self.cilindro_outro.id)]},
            format='json',
        )
        self.assertEqual(res_outro.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retorno_aprovado_atualiza_datas_conforme_modelo(self):
        self.client.force_login(self.gerente)
        res_envio = self.client.post(
            '/produtos/api/patrimonio/envios-reteste/',
            {
                'oficina_nome': 'Requalificadora Central',
                'oficina_cnpj': '11.222.333/0001-44',
                'documento_envio': 'ROM-100',
                'cilindro_ids': [str(self.cilindro_vazio.id)],
            },
            format='json',
        )
        self.assertEqual(res_envio.status_code, status.HTTP_201_CREATED, res_envio.content)
        envio_id = res_envio.data['id']

        self.cilindro_vazio.refresh_from_db()
        self.assertEqual(self.cilindro_vazio.status, 'EM_REQUALIFICACAO')

        pdf_fake = SimpleUploadedFile('laudo_teste.pdf', b'%PDF-1.4 fake content', content_type='application/pdf')
        res_ret = self.client.post(
            '/produtos/api/cilindros/registrar-retorno-reteste/',
            {
                'cilindro_id': str(self.cilindro_vazio.id),
                'envio_id': envio_id,
                'numero_certificado': 'CERT-S3-APROV-01',
                'data_execucao': str(self.hoje),
                'oficina_nome': 'Requalificadora Central',
                'oficina_cnpj': '11.222.333/0001-44',
                'registro_inmetro': 'INM-9999',
                'pressao_teste_bar': '300.00',
                'expansao_total_cm3': '100.000',
                'expansao_permanente_cm3': '5.000',
                'tara_real_kg': '55.200',
                'resultado': 'APROVADO',
                'laudo_pdf': pdf_fake,
            },
            format='multipart',
        )
        self.assertEqual(res_ret.status_code, status.HTTP_200_OK)

        self.cilindro_vazio.refresh_from_db()
        self.assertEqual(self.cilindro_vazio.status, 'VAZIO_TRIAGEM')
        self.assertEqual(self.cilindro_vazio.data_ultimo_reteste, self.hoje)
        # Periodicidade do modelo = 3 anos
        try:
            esperado = self.hoje.replace(year=self.hoje.year + 3)
        except ValueError:
            esperado = self.hoje + datetime.timedelta(days=3 * 365)
        self.assertEqual(self.cilindro_vazio.data_proximo_reteste, esperado)

        hist = HistoricoRetesteHidrostatico.objects.get(numero_certificado='CERT-S3-APROV-01')
        self.assertTrue(bool(hist.laudo_pdf))

        # Retificação
        res_retif = self.client.post(
            f'/produtos/api/patrimonio/retestes/{hist.id}/retificar/',
            {
                'observacoes': 'Correção do número de registro INMETRO no laudo',
                'registro_inmetro': 'INM-9999-REV',
            },
            format='json',
        )
        self.assertEqual(res_retif.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_retif.data['retifica'], hist.id)

    def test_retorno_reprovado_por_expansao(self):
        self.client.force_login(self.gerente)
        self.client.post(
            '/produtos/api/patrimonio/envios-reteste/',
            {
                'oficina_nome': 'Requalificadora Central',
                'oficina_cnpj': '11.222.333/0001-44',
                'cilindro_ids': [str(self.cilindro_vazio.id)],
            },
            format='json',
        )

        # Expansão 12% > 10% tentando APROVADO -> 400
        res_err = self.client.post(
            '/produtos/api/cilindros/registrar-retorno-reteste/',
            {
                'cilindro_id': str(self.cilindro_vazio.id),
                'numero_certificado': 'CERT-EXP-ERR',
                'data_execucao': str(self.hoje),
                'oficina_nome': 'Requalificadora Central',
                'oficina_cnpj': '11.222.333/0001-44',
                'registro_inmetro': 'INM-9999',
                'pressao_teste_bar': '300.00',
                'expansao_total_cm3': '100.000',
                'expansao_permanente_cm3': '12.000',
                'tara_real_kg': '55.000',
                'resultado': 'APROVADO',
            },
            format='json',
        )
        self.assertEqual(res_err.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('10.0000%', str(res_err.data))

        # Agora como REPROVADO_CONDENADO -> 200 e cilindro condenado/baixado
        res_cond = self.client.post(
            '/produtos/api/cilindros/registrar-retorno-reteste/',
            {
                'cilindro_id': str(self.cilindro_vazio.id),
                'numero_certificado': 'CERT-EXP-COND',
                'data_execucao': str(self.hoje),
                'oficina_nome': 'Requalificadora Central',
                'oficina_cnpj': '11.222.333/0001-44',
                'registro_inmetro': 'INM-9999',
                'pressao_teste_bar': '300.00',
                'expansao_total_cm3': '100.000',
                'expansao_permanente_cm3': '12.000',
                'tara_real_kg': '55.000',
                'resultado': 'REPROVADO_CONDENADO',
                'motivo_reprovacao': 'Expansão permanente acima de 10%',
            },
            format='json',
        )
        self.assertEqual(res_cond.status_code, status.HTTP_200_OK)
        self.cilindro_vazio.refresh_from_db()
        self.assertEqual(self.cilindro_vazio.status, 'BAIXADO')
        self.assertTrue(self.cilindro_vazio.bloqueio_sanitario)


class TestBaixaPatrimonialEEstorno(BaseSprint03TestCase):
    """03.2: Baixa patrimonial, RBAC de estorno e isolamento multi-tenant."""

    def test_baixa_cilindro_outro_tenant_responde_404(self):
        self.client.force_login(self.admin)
        res = self.client.post(
            '/produtos/api/patrimonio/baixas/',
            {
                'cilindro': str(self.cilindro_outro.id),
                'tipo': 'EXTRAVIO',
                'data': str(self.hoje),
                'motivo': 'Tentativa de baixa em cilindro de outra empresa',
                'documento_ref': 'BO-999',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_estorno_baixa_so_admin_e_gerente_e_restaura_status(self):
        # Gerente cria baixa
        self.client.force_login(self.gerente)
        res_baixa = self.client.post(
            '/produtos/api/patrimonio/baixas/',
            {
                'cilindro': str(self.cilindro_vazio.id),
                'tipo': 'SINISTRO',
                'data': str(self.hoje),
                'motivo': 'Queda acidental no pátio durante movimentação',
                'documento_ref': 'OCOR-001',
            },
            format='json',
        )
        self.assertEqual(res_baixa.status_code, status.HTTP_201_CREATED)
        baixa_id = res_baixa.data['id']

        self.cilindro_vazio.refresh_from_db()
        self.assertEqual(self.cilindro_vazio.status, 'BAIXADO')

        # Operador e Vendedor não podem estornar -> 403
        for user_op in (self.operador, self.vendedor):
            self.client.force_login(user_op)
            res_forb = self.client.post(
                f'/produtos/api/patrimonio/baixas/{baixa_id}/estornar/',
                {'motivo': 'Tentativa sem permissão de gestão'},
                format='json',
            )
            self.assertEqual(res_forb.status_code, status.HTTP_403_FORBIDDEN)

        # Gerente (via Membership, sem Django perm avulsa) estorna -> 200 e restaura status anterior
        self.client.force_login(self.gerente)
        res_est = self.client.post(
            f'/produtos/api/patrimonio/baixas/{baixa_id}/estornar/',
            {'motivo': 'Baixa registrada no cilindro errado durante conferência'},
            format='json',
        )
        self.assertEqual(res_est.status_code, status.HTTP_200_OK)
        self.assertTrue(res_est.data['estornada'])

        self.cilindro_vazio.refresh_from_db()
        self.assertEqual(self.cilindro_vazio.status, 'VAZIO_TRIAGEM')


class TestPaginasRetestesEPatrimonioBaixas(BaseSprint03TestCase):
    """03.1 & 03.2: Renderização das páginas com IDs principais e checagens estáticas."""

    def test_pagina_retestes_e_aba_baixas_renderizam_com_ids_principais(self):
        self.client.force_login(self.gerente)
        res_ret = self.client.get('/produtos/retestes/')
        self.assertEqual(res_ret.status_code, status.HTTP_200_OK)
        html_ret = res_ret.content.decode('utf-8')
        for elem_id in (
            'aba-vencimentos',
            'aba-envios',
            'modal-novo-envio',
            'modal-retorno-reteste-completo',
            'modal-retificacao-reteste',
            'modal-baixa-patrimonial',
        ):
            self.assertIn(elem_id, html_ret)

        res_pat = self.client.get('/produtos/patrimonio/')
        self.assertEqual(res_pat.status_code, status.HTTP_200_OK)
        html_pat = res_pat.content.decode('utf-8')
        self.assertIn('aba-baixas', html_pat)
        self.assertIn('corpo-tabela-baixas', html_pat)

    def test_pagina_retestes_bloqueada_se_modulo_inativo(self):
        self.tenant.modulo_patrimonio_ativo = False
        self.tenant.save(update_fields=['modulo_patrimonio_ativo'])
        self.client.force_login(self.gerente)
        res = self.client.get('/produtos/retestes/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_static_nenhum_template_base_dashboard_sobrescreve_block_content_e_design_system(self):
        from django.conf import settings

        base_dir = settings.BASE_DIR
        # 1. Nenhum template que estende base_dashboard.html pode sobrescrever {% block content %}
        for root, _, files in os.walk(base_dir):
            if 'venv' in root or '.git' in root:
                continue
            for fname in files:
                if not fname.endswith('.html'):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                    conteudo = fp.read()
                if re.search(r'{%\s*extends\s+[\'"]base_dashboard\.html[\'"]\s*%}', conteudo):
                    self.assertIsNone(
                        re.search(r'{%\s*block\s+content\s*%}', conteudo),
                        f'Template {fpath} estende base_dashboard.html e sobrescreve {{% block content %}}!'
                    )

        # 2. Templates novos da Sprint 03 sem style=""
        novos_html = [
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'retestes', 'index.html'),
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'retestes', '_aba_vencimentos.html'),
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'retestes', '_aba_envios.html'),
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'retestes', '_modal_novo_envio.html'),
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'retestes', '_modal_retorno_reteste.html'),
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'retestes', '_modal_retificacao.html'),
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'patrimonio', '_aba_baixas.html'),
            os.path.join(base_dir, 'produtos', 'templates', 'produtos', 'patrimonio', '_modal_baixa_patrimonial.html'),
        ]
        for h in novos_html:
            with open(h, 'r', encoding='utf-8') as fp:
                c = fp.read()
            self.assertNotIn('style="', c, f'Inline style encontrado em {h}')

        # 3. JS novo sem alert/confirm/prompt e sem innerHTML
        retestes_js = os.path.join(base_dir, 'produtos', 'static', 'produtos', 'js', 'retestes.js')
        with open(retestes_js, 'r', encoding='utf-8') as fp:
            js_code = fp.read()
        self.assertIsNone(re.search(r'\b(alert|confirm|prompt)\s*\(', js_code))
        self.assertNotIn('innerHTML', js_code)

