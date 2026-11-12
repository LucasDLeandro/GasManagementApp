import datetime
from decimal import Decimal
import os
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Membership, Tenant
from core.money import quantize
from core.tenancy import reset_current_tenant, set_current_tenant
from produtos.models import (
    AtivoImobilizado,
    Cilindro,
    ClasseAtivo,
    FabricanteCilindro,
    GasQuimico,
    LoteAquisicaoCilindros,
    ModeloCilindro,
    TabelaIndenizacaoCilindro,
)
from produtos.serializers import CadastroCilindroSerializer

User = get_user_model()
CHAVE_NFE_VALIDA = '35261011222333000144550010000000011123456783'


class BasePatrimonioTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Gás Central Ltda',
            nome_fantasia='Central Gás',
            modulo_patrimonio_ativo=True,
            modulo_financeiro_ativo=True,
        )
        set_current_tenant(self.tenant)

        # Usuários com diferentes papéis
        self.admin = User.objects.create_user(username='admin_user', password='pass123', email='admin@teste.com')
        Membership.objects.create(user=self.admin, tenant=self.tenant, papel='ADMIN', ativo=True)

        self.gerente = User.objects.create_user(username='gerente_user', password='pass123', email='gerente@teste.com')
        Membership.objects.create(user=self.gerente, tenant=self.tenant, papel='GERENTE', ativo=True)

        self.vendedor = User.objects.create_user(username='vendedor_user', password='pass123', email='vendedor@teste.com')
        Membership.objects.create(user=self.vendedor, tenant=self.tenant, papel='VENDEDOR', ativo=True)

        self.operador = User.objects.create_user(username='operador_user', password='pass123', email='operador@teste.com')
        Membership.objects.create(user=self.operador, tenant=self.tenant, papel='OPERADOR_PATIO', ativo=True)

        # Dados base
        self.gas = GasQuimico.objects.create(nome='Oxigênio Medicinal', sigla='O2M', categoria='MEDICINAL')
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao='Cilindro 50L Aço',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('55.00'),
            periodicidade_reteste_anos=5,
        )
        self.classe = ClasseAtivo.objects.create(
            tenant=self.tenant,
            codigo='CIL-MED-50L',
            nome='Cilindros Medicinais 50L',
            tipo='CILINDRO',
            vida_util_meses_padrao=120,
            percentual_residual_padrao=Decimal('0.1000'),
        )
        self.fabricante = FabricanteCilindro.objects.create(
            tenant=self.tenant,
            nome='MAT S/A',
            pais_origem='BR',
            norma_fabricacao_padrao='ISO 9809-1',
        )
        self.lote = LoteAquisicaoCilindros.objects.create(
            tenant=self.tenant,
            classe=self.classe,
            fornecedor_nome='Fornecedor Matriz',
            fornecedor_documento='12.345.678/0001-90',
            chave_nfe=CHAVE_NFE_VALIDA,
            data_aquisicao=timezone.localdate(),
            quantidade=10,
            valor_total=Decimal('10000.00'),
            valor_unitario=Decimal('1000.00'),
        )

        self.client = APIClient()

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()


class TestPermissoesEscritaPatrimonio(BasePatrimonioTestCase):
    """02.1 Permissões de escrita por papel em cada endpoint."""

    def test_permissoes_escrita_bloqueia_vendedor_e_operador(self):
        endpoints = [
            ('/produtos/api/patrimonio/fabricantes/', {'nome': 'Novo Fab', 'pais_origem': 'BR'}),
            ('/produtos/api/patrimonio/classes/', {'codigo': 'CLS-NOVA', 'nome': 'Nova', 'tipo': 'CILINDRO', 'vida_util_meses_padrao': 120, 'percentual_residual_padrao': '0.10'}),
            ('/produtos/api/patrimonio/lotes/', {'classe': self.classe.id, 'fornecedor_nome': 'Forn', 'data_aquisicao': str(timezone.localdate()), 'quantidade': 5, 'valor_total': '5000.00', 'valor_unitario': '1000.00'}),
            ('/produtos/api/patrimonio/ativos/', {'classe': self.classe.id, 'numero_patrimonio': 'PAT-TEST', 'descricao': 'Ativo', 'data_aquisicao': str(timezone.localdate()), 'valor_aquisicao': '5000.00', 'vida_util_meses': 120}),
            ('/produtos/api/patrimonio/indenizacoes/', {'tipo_cilindro': self.modelo.id, 'gas': self.gas.id, 'valor': '1500.00', 'vigencia_inicio': str(timezone.localdate())}),
        ]

        for usuario in [self.vendedor, self.operador]:
            self.client.force_login(usuario)
            for url, payload in endpoints:
                # POST
                res_post = self.client.post(url, payload, format='json')
                self.assertEqual(
                    res_post.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"Usuário {usuario.username} conseguiu POST em {url}: {res_post.status_code}"
                )

    def test_permissoes_escrita_permite_admin_e_gerente(self):
        for usuario in [self.gerente, self.admin]:
            self.client.force_login(usuario)
            res = self.client.post('/produtos/api/patrimonio/fabricantes/', {
                'nome': f'Fab Permissao {usuario.username}',
                'pais_origem': 'BR',
            }, format='json')
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)


class TestExclusaoPatrimonioProtegida(BasePatrimonioTestCase):
    """02.1 & Ajuste 4: Exclusão de registros em uso ou com depreciação responde 400 com mensagem clara."""

    def test_exclusao_fabricante_em_uso_responde_400(self):
        # Vincula cilindro ao fabricante
        Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-FAB-01',
            numero_serie_ogiva='SR-FAB-01',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante_catalogo=self.fabricante,
            fabricante=self.fabricante.nome,
            ano_fabricacao=2023,
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
        )
        self.client.force_login(self.admin)
        res = self.client.delete(f'/produtos/api/patrimonio/fabricantes/{self.fabricante.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('não pode ser excluído', res.data.get('detail', ''))

    def test_exclusao_classe_em_uso_responde_400(self):
        self.client.force_login(self.admin)
        res = self.client.delete(f'/produtos/api/patrimonio/classes/{self.classe.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('não pode ser excluído', res.data.get('detail', ''))

    def test_exclusao_lote_com_cilindros_vinculados_responde_400(self):
        # Cria cilindro vinculado ao lote
        Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-LOTE-01',
            numero_serie_ogiva='SR-LOTE-01',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2023,
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
            lote_aquisicao=self.lote,
        )
        self.client.force_login(self.admin)
        res = self.client.delete(f'/produtos/api/patrimonio/lotes/{self.lote.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        # Mensagem deve orientar sobre baixa patrimonial ou informar cilindros vinculados
        mensagem = res.data.get('detail', '') or res.data.get('error', '')
        self.assertTrue(
            'baixa patrimonial' in mensagem.lower() or 'cilindros vinculados' in mensagem.lower() or 'em uso' in mensagem.lower(),
            f"Mensagem inesperada: {mensagem}"
        )

    def test_exclusao_ativo_com_depreciacao_calculada_responde_400(self):
        # Ativo adquirido há 6 meses com depreciação decorrente
        ativo = AtivoImobilizado.objects.create(
            tenant=self.tenant,
            classe=self.classe,
            numero_patrimonio='PAT-DEP-01',
            descricao='Tanque Estacionário',
            data_aquisicao=timezone.localdate() - datetime.timedelta(days=180),
            data_inicio_depreciacao=timezone.localdate() - datetime.timedelta(days=180),
            valor_aquisicao=Decimal('60000.00'),
            valor_residual=Decimal('6000.00'),
            vida_util_meses=60,
        )
        self.client.force_login(self.admin)
        res = self.client.delete(f'/produtos/api/patrimonio/ativos/{ativo.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        mensagem = res.data.get('detail', '') or res.data.get('error', '')
        self.assertIn('baixa patrimonial', mensagem.lower())


class TestTabelaIndenizacaoNovaVigenciaESimulador(BasePatrimonioTestCase):
    """02.2 & Ajuste 1: Regras da Tabela de Indenização (nova vigência, sobreposição e simulador)."""

    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.indenizacao = TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant,
            tipo_cilindro=self.modelo,
            gas=self.gas,
            valor=Decimal('1200.00'),
            vigencia_inicio=self.hoje - datetime.timedelta(days=60),
            vigencia_fim=None,
        )

    def test_alterar_valor_direto_por_patch_bloqueado(self):
        """Não pode alterar o valor da linha existente por PATCH (reescrever o passado)."""
        self.client.force_login(self.admin)
        res = self.client.patch(
            f'/produtos/api/patrimonio/indenizacoes/{self.indenizacao.id}/',
            {'valor': '1800.00'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nova_vigencia_preserva_anterior_e_cria_nova_linha(self):
        """Ação explícita nova-vigencia fecha a atual na véspera e cria novo registro."""
        self.client.force_login(self.admin)
        nova_data = self.hoje + datetime.timedelta(days=1)
        res = self.client.post(
            f'/produtos/api/patrimonio/indenizacoes/{self.indenizacao.id}/nova-vigencia/',
            {
                'valor': '1500.00',
                'vigencia_inicio': str(nova_data),
            },
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Confere vigência anterior encerrada na véspera
        self.indenizacao.refresh_from_db()
        self.assertEqual(self.indenizacao.vigencia_fim, nova_data - datetime.timedelta(days=1))
        self.assertEqual(self.indenizacao.valor, Decimal('1200.00'))

        # Confere nova vigência
        nova = TabelaIndenizacaoCilindro.objects.get(id=res.data['id'])
        self.assertEqual(nova.valor, Decimal('1500.00'))
        self.assertEqual(nova.vigencia_inicio, nova_data)
        self.assertIsNone(nova.vigencia_fim)

    def test_vigencias_sobrepostas_responde_400(self):
        """Não pode haver duas vigências sobrepostas para o mesmo tipo_cilindro + gas."""
        self.client.force_login(self.admin)
        # Tenta criar vigência começando no mesmo período da atual que está aberta
        res = self.client.post(
            '/produtos/api/patrimonio/indenizacoes/',
            {
                'tipo_cilindro': self.modelo.id,
                'gas': self.gas.id,
                'valor': '1600.00',
                'vigencia_inicio': str(self.hoje - datetime.timedelta(days=10)),
            },
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sobreposição', str(res.data).lower())

    def test_simulador_indenizacao_usa_vigencia_correta_para_data(self):
        cilindro = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-SIM-01',
            numero_serie_ogiva='SR-SIM-01',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2023,
            valor_aquisicao=Decimal('1000.00'),
            data_aquisicao=self.hoje,
            data_ultimo_reteste=self.hoje,
            data_proximo_reteste=self.hoje + datetime.timedelta(days=1800),
        )
        self.client.force_login(self.gerente)
        res = self.client.get(f'/produtos/api/patrimonio/indenizacoes/simular/?cilindro_id={cilindro.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['cilindro_id'], str(cilindro.id))
        self.assertEqual(Decimal(str(res.data['valor_contratual'])), Decimal('1200.00'))
        self.assertEqual(res.data['origem'], 'TABELA_CONTRATUAL')

    def test_nova_vigencia_retroativa_responde_400(self):
        """nova-vigencia só a partir de hoje: vigencia_inicio < hoje -> 400."""
        self.client.force_login(self.admin)
        data_retroativa = self.hoje - datetime.timedelta(days=5)
        res = self.client.post(
            f'/produtos/api/patrimonio/indenizacoes/{self.indenizacao.id}/nova-vigencia/',
            {
                'valor': '1500.00',
                'vigencia_inicio': str(data_retroativa),
            },
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('vigência retroativa não permitida', str(res.data).lower())

    def test_nova_vigencia_em_linha_ja_encerrada_responde_400(self):
        """nova-vigencia só sobre a linha vigente (sem vigencia_fim)."""
        self.client.force_login(self.admin)
        gas_extra = GasQuimico.objects.create(nome='Argônio', sigla='Ar', categoria='INDUSTRIAL')
        encerrada = TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant,
            tipo_cilindro=self.modelo,
            gas=gas_extra,
            valor=Decimal('1000.00'),
            vigencia_inicio=self.hoje - datetime.timedelta(days=60),
            vigencia_fim=self.hoje - datetime.timedelta(days=1),
        )
        res = self.client.post(
            f'/produtos/api/patrimonio/indenizacoes/{encerrada.id}/nova-vigencia/',
            {
                'valor': '1400.00',
                'vigencia_inicio': str(self.hoje),
            },
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nova_vigencia_sobreposta_com_linha_futura_responde_400_e_faz_rollback(self):
        """Antes de criar a nova linha, roda a mesma validação de sobreposição do serializer."""
        self.client.force_login(self.admin)
        TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant,
            tipo_cilindro=self.modelo,
            gas=self.gas,
            valor=Decimal('1900.00'),
            vigencia_inicio=self.hoje + datetime.timedelta(days=15),
            vigencia_fim=None,
        )
        res = self.client.post(
            f'/produtos/api/patrimonio/indenizacoes/{self.indenizacao.id}/nova-vigencia/',
            {
                'valor': '1500.00',
                'vigencia_inicio': str(self.hoje + datetime.timedelta(days=5)),
            },
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sobreposição', str(res.data).lower())
        self.indenizacao.refresh_from_db()
        self.assertIsNone(self.indenizacao.vigencia_fim)

    def test_exclusao_tabela_indenizacao_so_permite_vigencia_futura(self):
        """Exclusão só se vigencia_inicio > hoje; linha que já vigorou -> 400 orientando nova vigência."""
        self.client.force_login(self.admin)
        # Linha que já vigorou (hoje - 60) -> 400
        res_passada = self.client.delete(f'/produtos/api/patrimonio/indenizacoes/{self.indenizacao.id}/')
        self.assertEqual(res_passada.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('nova vigência', str(res_passada.data).lower())

        # Linha que entrou em vigor hoje -> 400
        gas_hoje = GasQuimico.objects.create(nome='Nitrogênio', sigla='N2', categoria='INDUSTRIAL')
        vigente_hoje = TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant,
            tipo_cilindro=self.modelo,
            gas=gas_hoje,
            valor=Decimal('1100.00'),
            vigencia_inicio=self.hoje,
            vigencia_fim=None,
        )
        res_hoje = self.client.delete(f'/produtos/api/patrimonio/indenizacoes/{vigente_hoje.id}/')
        self.assertEqual(res_hoje.status_code, status.HTTP_400_BAD_REQUEST)

        # Linha futura (vigencia_inicio > hoje) -> 204
        gas_futuro = GasQuimico.objects.create(nome='Dióxido de Carbono', sigla='CO2', categoria='INDUSTRIAL')
        futura = TabelaIndenizacaoCilindro.objects.create(
            tenant=self.tenant,
            tipo_cilindro=self.modelo,
            gas=gas_futuro,
            valor=Decimal('1300.00'),
            vigencia_inicio=self.hoje + datetime.timedelta(days=10),
            vigencia_fim=None,
        )
        res_fut = self.client.delete(f'/produtos/api/patrimonio/indenizacoes/{futura.id}/')
        self.assertEqual(res_fut.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TabelaIndenizacaoCilindro.objects.filter(id=futura.id).exists())


class TestLoteAquisicaoRegrasEValidacoes(BasePatrimonioTestCase):
    """02.2, 02.3 & Ajustes 2, 3 e 5: Validações do lote, edição travada e integração com cadastro de cilindro."""

    def test_chave_nfe_43_digitos_ou_com_letras_responde_400(self):
        self.client.force_login(self.admin)
        # 43 dígitos
        payload_43 = {
            'classe': self.classe.id,
            'fornecedor_nome': 'Fornecedor Teste',
            'chave_nfe': '3526101122233300014455001000000001112345678',  # 43 chars
            'data_aquisicao': str(timezone.localdate()),
            'quantidade': 5,
            'valor_total': '5000.00',
            'valor_unitario': '1000.00',
        }
        res_43 = self.client.post('/produtos/api/patrimonio/lotes/', payload_43, format='json')
        self.assertEqual(res_43.status_code, status.HTTP_400_BAD_REQUEST)

        # Com letras
        payload_letras = dict(payload_43)
        payload_letras['chave_nfe'] = '3526101122233300014455001000000001112345678A'
        res_letras = self.client.post('/produtos/api/patrimonio/lotes/', payload_letras, format='json')
        self.assertEqual(res_letras.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lote_com_cilindros_vinculados_trava_campos_financeiros_e_classe(self):
        """Ajuste 3: Lote com cilindros vinculados tem campos travados (400 ao alterar)."""
        Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-TRAVA-01',
            numero_serie_ogiva='SR-TRAVA-01',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2023,
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
            lote_aquisicao=self.lote,
        )
        self.client.force_login(self.admin)
        # Tenta alterar quantidade
        res = self.client.patch(f'/produtos/api/patrimonio/lotes/{self.lote.id}/', {'quantidade': 20}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('travado', str(res.data).lower())

        # Tenta alterar valor_unitario
        res_val = self.client.patch(f'/produtos/api/patrimonio/lotes/{self.lote.id}/', {'valor_unitario': '1200.00'}, format='json')
        self.assertEqual(res_val.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cadastro_cilindro_serializer_restringe_lote_ao_tenant(self):
        """Ajuste 2: Lote de outra empresa gera erro de validação."""
        tenant_outro = Tenant.objects.create(cnpj='99.888.777/0001-66', razao_social='Outra Ltda')
        set_current_tenant(tenant_outro)
        classe_outra = ClasseAtivo.objects.create(tenant=tenant_outro, codigo='OUTRA', nome='Outra')
        lote_outro = LoteAquisicaoCilindros.objects.create(
            tenant=tenant_outro, classe=classe_outra, fornecedor_nome='F', data_aquisicao=timezone.localdate(),
            quantidade=5, valor_total=Decimal('5000.00'), valor_unitario=Decimal('1000.00')
        )
        reset_current_tenant()
        set_current_tenant(self.tenant)

        dados = {
            'codigo_qr': 'QR-TENANT-CHECK',
            'numero_serie_ogiva': 'SR-TENANT-CHECK',
            'modelo': self.modelo.id,
            'gas_dedicado': self.gas.id,
            'fabricante': 'MAT',
            'ano_fabricacao': 2024,
            'data_ultimo_reteste': str(timezone.localdate()),
            'lote_aquisicao': lote_outro.id,
        }
        serializer = CadastroCilindroSerializer(data=dados, tenant=self.tenant)
        self.assertFalse(serializer.is_valid())
        self.assertIn('lote_aquisicao', serializer.errors)

    def test_cadastro_cilindro_alem_da_quantidade_do_lote_responde_400(self):
        """Ajuste 2: Cadastrar além de lote.quantidade responde 400 com mensagem clara."""
        lote_pequeno = LoteAquisicaoCilindros.objects.create(
            tenant=self.tenant, classe=self.classe, fornecedor_nome='F', data_aquisicao=timezone.localdate(),
            quantidade=1, valor_total=Decimal('1000.00'), valor_unitario=Decimal('1000.00')
        )
        # Cadastra 1 cilindro preenchendo o lote
        Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-LOT-P1',
            numero_serie_ogiva='SR-LOT-P1',
            modelo=self.modelo,
            gas_dedicado=self.gas,
            fabricante='MAT',
            ano_fabricacao=2023,
            data_ultimo_reteste=timezone.localdate(),
            data_proximo_reteste=timezone.localdate() + datetime.timedelta(days=1800),
            lote_aquisicao=lote_pequeno,
        )

        # Tenta cadastrar o segundo pelo serializer / API
        dados = {
            'codigo_qr': 'QR-LOT-P2',
            'numero_serie_ogiva': 'SR-LOT-P2',
            'modelo': self.modelo.id,
            'gas_dedicado': self.gas.id,
            'fabricante': 'MAT',
            'ano_fabricacao': 2024,
            'data_ultimo_reteste': str(timezone.localdate()),
            'lote_aquisicao': lote_pequeno.id,
        }
        serializer = CadastroCilindroSerializer(data=dados, tenant=self.tenant)
        self.assertFalse(serializer.is_valid())
        self.assertIn('lote_aquisicao', serializer.errors)
        self.assertIn('limite', str(serializer.errors['lote_aquisicao']).lower())


class TestPaginaPatrimonioEInterface(BasePatrimonioTestCase):
    """02.2: Renderização da página /produtos/patrimonio/, IDs de abas e proteção de visualização."""

    def test_pagina_patrimonio_renderiza_com_ids_das_abas_para_gerente(self):
        self.client.force_login(self.gerente)
        res = self.client.get('/produtos/patrimonio/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        conteudo = res.content.decode('utf-8')
        # Confere IDs das abas
        self.assertIn('id="aba-ativos"', conteudo)
        self.assertIn('id="aba-lotes"', conteudo)
        self.assertIn('id="aba-classes"', conteudo)
        self.assertIn('id="aba-fabricantes"', conteudo)
        self.assertIn('id="aba-indenizacao"', conteudo)

    def test_pagina_patrimonio_bloqueada_se_modulo_inativo(self):
        self.tenant.modulo_patrimonio_ativo = False
        self.tenant.save()
        self.client.force_login(self.gerente)
        res = self.client.get('/produtos/patrimonio/')
        self.assertIn(res.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND, status.HTTP_302_FOUND])

