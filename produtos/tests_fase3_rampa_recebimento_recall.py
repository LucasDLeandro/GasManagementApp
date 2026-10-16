from decimal import Decimal
from datetime import timedelta
import uuid
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership, ResponsavelTecnico
from core.tenancy import set_current_tenant
from clientes.models import Cliente
from produtos.models import (
    GasQuimico,
    ModeloCilindro,
    Cilindro,
    LoteEnvase,
    EnvaseCilindro,
    InspecaoPreEnvase,
    RecebimentoCilindroCheio,
    MovimentacaoCilindro,
    AuditoriaBloqueioSanitario,
    RecallCampanha,
    ItemRecallCliente,
)
from produtos.services import (
    registrar_envase_cilindro,
    registrar_entrega_cilindro,
    registrar_recolha_cilindro,
    validar_cilindro_para_rampa,
    registrar_envase_batelada,
    receber_cilindros_fornecedor_batelada,
    atualizar_qualidade_lote,
    obter_dossie_recall_lote,
)

User = get_user_model()


class Fase3RampaRecebimentoRecallTests(TestCase):
    """
    Suíte de Testes Automatizados da FASE 3:
    1. Estação de Rampa de Envase em Batelada (Manifold Batch Grid - IN 129/2022).
    2. Central de Recebimento de Cilindros Cheios de Fornecedor (RDC 887/2024).
    3. Central de Lotes, Homologação e Quarentena Sanitária em Cascata.
    4. Recall ANVISA com Separação Estrita de Contenção Operacional vs Dossiê de Exposição Histórica.
    5. Acompanhamento de Confirmações de Notificação e Recolhimento por Cliente.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Gases Medicinais do Sudeste Ltda',
            nome_fantasia='Gases Sudeste'
        )
        self.token = set_current_tenant(self.tenant)

        self.hoje = timezone.now().date()
        self.agora = timezone.now()

        # Usuário RT (Responsável Técnico)
        self.user_rt = User.objects.create_user(
            username='farmaceutico.rt',
            password='senha_rt_123',
            tipo_usuario='RESPONSAVEL_TECNICO'
        )
        Membership.objects.create(user=self.user_rt, tenant=self.tenant, papel='RESPONSAVEL_TECNICO')

        # Registro formal de Responsável Técnico
        self.rt_registro = ResponsavelTecnico.objects.create(
            user=self.user_rt,
            nome_completo='Dr. Carlos Alberto RT',
            conselho_classe='CRF',
            numero_registro='54321',
            uf_conselho='SP',
            vigencia_inicio=self.hoje - timedelta(days=365),
            ativo=True
        )

        # Usuário Operador de Pátio
        self.user_op = User.objects.create_user(
            username='operador.patio',
            password='senha_op_123',
            tipo_usuario='ADMIN'
        )
        Membership.objects.create(user=self.user_op, tenant=self.tenant, papel='OPERADOR_PATIO')

        # Gases: Oxigênio Medicinal e Nitrogênio Industrial
        self.gas_o2, _ = GasQuimico.objects.get_or_create(
            sigla='O2-MED-F3',
            defaults={
                'nome': 'Oxigênio Medicinal',
                'categoria': 'MEDICINAL',
                'numero_onu': '1072',
                'classe_risco': '2.2',
                'cor_padrao_abnt': '#15803d',
                'exige_lote_anvisa': True
            }
        )

        self.gas_n2, _ = GasQuimico.objects.get_or_create(
            sigla='N2-IND-F3',
            defaults={
                'nome': 'Nitrogênio Industrial',
                'categoria': 'INDUSTRIAL',
                'numero_onu': '1066',
                'classe_risco': '2.2',
                'cor_padrao_abnt': '#475569',
                'exige_lote_anvisa': False
            }
        )

        self.modelo_50l = ModeloCilindro.objects.create(
            descricao='Cilindro T-50 Aço',
            material='ACO',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('55.00'),
            padrao_valvula_abnt='ABNT 218-1'
        )

        # Lote de Oxigênio Ativo
        self.lote_o2 = LoteEnvase.objects.create(
            gas=self.gas_o2,
            codigo_lote='LOT-O2-F3-001',
            status_qualidade='APROVADO',
            data_envase=self.hoje,
            data_validade=self.hoje + timedelta(days=365),
            pureza_percentual=Decimal('99.50'),
            responsavel_tecnico='Dr. Carlos Alberto RT (CRF-SP 54321)',
            responsavel_tecnico_fk=self.rt_registro,
            rt_nome_snapshot='Dr. Carlos Alberto RT',
            rt_conselho_snapshot='CRF',
            rt_registro_snapshot='CRF-SP 54321'
        )

        # Cilindros de teste
        self.cil1 = Cilindro.objects.create(
            codigo_qr='CIL-F3-001',
            numero_serie_ogiva='OGV-F3-001',
            fabricante='MATESA',
            ano_fabricacao=2022,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.20'),
            propriedade='DISTRIBUIDORA',
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=1460),
            status='VAZIO_TRIAGEM'
        )

        self.cil2 = Cilindro.objects.create(
            codigo_qr='CIL-F3-002',
            numero_serie_ogiva='OGV-F3-002',
            fabricante='MATESA',
            ano_fabricacao=2022,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('55.40'),
            propriedade='DISTRIBUIDORA',
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=1460),
            status='VAZIO_TRIAGEM'
        )

        # Cilindro 3: Reteste vencido
        self.cil_vencido = Cilindro.objects.create(
            codigo_qr='CIL-F3-VENC',
            numero_serie_ogiva='OGV-F3-VENC',
            fabricante='MATESA',
            ano_fabricacao=2015,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            data_ultimo_reteste=self.hoje - timedelta(days=2000),
            data_proximo_reteste=self.hoje - timedelta(days=10),
            status='VAZIO_TRIAGEM'
        )

        # Cilindro 4: Bloqueio Sanitário ativo
        self.cil_bloqueado = Cilindro.objects.create(
            codigo_qr='CIL-F3-BLOQ',
            numero_serie_ogiva='OGV-F3-BLOQ',
            fabricante='MATESA',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=1460),
            status='VAZIO_TRIAGEM',
            bloqueio_sanitario=True,
            motivo_bloqueio_sanitario='Contaminação por óleo na válvula'
        )

        # Cilindro 5: Gás incompatível (Nitrogênio)
        self.cil_gas_errado = Cilindro.objects.create(
            codigo_qr='CIL-F3-N2',
            numero_serie_ogiva='OGV-F3-N2',
            fabricante='MATESA',
            ano_fabricacao=2023,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_n2,
            data_ultimo_reteste=self.hoje - timedelta(days=100),
            data_proximo_reteste=self.hoje + timedelta(days=1700),
            status='VAZIO_TRIAGEM'
        )

        # Cliente Hospitalar
        self.hospital = Cliente.objects.create(
            nome='Hospital Santa Casa Central',
            cnpj='22.333.444/0001-55',
            endereco='Av. Paulista, 1000',
            cidade='São Paulo',
            estado='SP',
            telefone='11999998888',
            proprietario='Diretoria Hospitalar'
        )

    # ==============================================================================
    # 1. TESTES DA ESTAÇÃO DE RAMPA EM BATELADA (IN 129/2022)
    # ==============================================================================

    def test_validacao_tempo_real_rampa_sucesso_e_rejeicoes(self):
        """Valida que a estação de rampa rejeita cilindros vencidos, bloqueados e incompatíveis."""
        self.client.force_authenticate(user=self.user_op)

        # Caso 1: Sucesso com cilindro apto
        valido, motivo, cil, lote = validar_cilindro_para_rampa(self.cil1.codigo_qr, self.lote_o2.id)
        self.assertTrue(valido)
        self.assertEqual(cil.id, self.cil1.id)

        # Caso 2: Rejeição por teste hidrostático vencido
        valido, motivo, cil, _ = validar_cilindro_para_rampa(self.cil_vencido.codigo_qr, self.lote_o2.id)
        self.assertFalse(valido)
        self.assertIn("Reteste hidrostático VENCIDO", motivo)

        # Caso 3: Rejeição por Bloqueio Sanitário ativo
        valido, motivo, cil, _ = validar_cilindro_para_rampa(self.cil_bloqueado.codigo_qr, self.lote_o2.id)
        self.assertFalse(valido)
        self.assertIn("Bloqueio sanitário ativo", motivo)

        # Caso 4: Rejeição por Incompatibilidade Química de Gás
        valido, motivo, cil, _ = validar_cilindro_para_rampa(self.cil_gas_errado.codigo_qr, self.lote_o2.id)
        self.assertFalse(valido)
        self.assertIn("Incompatibilidade de Gás", motivo)

        # Validação via API Endpoint
        res_ok = self.client.post('/produtos/api/envases/validar-cilindro/', {
            'codigo_qr': self.cil1.codigo_qr,
            'lote_id': self.lote_o2.id
        }, format='json')
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)
        self.assertTrue(res_ok.data['valido'])

        res_err = self.client.post('/produtos/api/envases/validar-cilindro/', {
            'codigo_qr': self.cil_vencido.codigo_qr,
            'lote_id': self.lote_o2.id
        }, format='json')
        self.assertEqual(res_err.status_code, status.HTTP_200_OK)
        self.assertFalse(res_err.data['valido'])
        self.assertIn("VENCIDO", res_err.data['motivo'])

    def test_conclusao_atomica_batelada_envase_checklist_in129_sucesso(self):
        """Conclui atomicamente uma batelada na rampa com checklist IN 129 aprovado."""
        self.client.force_authenticate(user=self.user_op)

        payload = {
            'lote_id': self.lote_o2.id,
            'pressao_final_bar': 200,
            'itens': [
                {
                    'cilindro_id': self.cil1.id,
                    'valvula_integra': True,
                    'pressao_residual_positiva': True,
                    'pintura_cor_padrao_ok': True,
                    'rotulo_identificacao_ok': True,
                    'observacoes_inspecao': 'Checklist conforme'
                },
                {
                    'cilindro_id': self.cil2.id,
                    'valvula_integra': True,
                    'pressao_residual_positiva': True,
                    'pintura_cor_padrao_ok': True,
                    'rotulo_identificacao_ok': True,
                    'observacoes_inspecao': 'Checklist conforme'
                }
            ],
            'observacoes_batelada': 'Batelada Manifold #1'
        }

        res = self.client.post('/produtos/api/envases/batelada/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['sucesso'])
        self.assertEqual(res.data['total_envasados'], 2)

        # Verifica estado dos cilindros
        self.cil1.refresh_from_db()
        self.cil2.refresh_from_db()
        self.assertEqual(self.cil1.status, 'CHEIO_DISPONIVEL')
        self.assertEqual(self.cil2.status, 'CHEIO_DISPONIVEL')
        self.assertIsNotNone(self.cil1.envase_atual)
        self.assertIsNotNone(self.cil2.envase_atual)
        self.assertEqual(self.cil1.envase_atual.lote_id, self.lote_o2.id)

        # Verifica criação dos checklists IN 129
        inspecoes = InspecaoPreEnvase.objects.filter(cilindro__in=[self.cil1, self.cil2])
        self.assertEqual(inspecoes.count(), 2)
        self.assertTrue(all(i.aprovado for i in inspecoes))

        # Verifica Ledger imutável
        movs = MovimentacaoCilindro.objects.filter(cilindro__in=[self.cil1, self.cil2], tipo='ENVASE')
        self.assertEqual(movs.count(), 2)

    def test_reversao_atomica_batelada_quando_checklist_reprovado(self):
        """Se qualquer cilindro tiver falha no checklist IN 129, a batelada inteira deve sofrer rollback."""
        self.client.force_authenticate(user=self.user_op)

        payload = {
            'lote_id': self.lote_o2.id,
            'pressao_final_bar': 200,
            'itens': [
                {
                    'cilindro_id': self.cil1.id,
                    'valvula_integra': True,
                    'pressao_residual_positiva': True,
                    'pintura_cor_padrao_ok': True,
                    'rotulo_identificacao_ok': True
                },
                {
                    'cilindro_id': self.cil2.id,
                    'valvula_integra': False,  # NÃO CONFORME!
                    'pressao_residual_positiva': True,
                    'pintura_cor_padrao_ok': True,
                    'rotulo_identificacao_ok': True
                }
            ]
        }

        res = self.client.post('/produtos/api/envases/batelada/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Batelada Abortada", res.data['error'])

        # Nenhum cilindro pode ter sido envasado (Rollback completo)
        self.cil1.refresh_from_db()
        self.cil2.refresh_from_db()
        self.assertEqual(self.cil1.status, 'VAZIO_TRIAGEM')
        self.assertEqual(self.cil2.status, 'VAZIO_TRIAGEM')
        self.assertIsNone(self.cil1.envase_atual)
        self.assertIsNone(self.cil2.envase_atual)

    def test_emissao_etiquetas_colarinho_batelada(self):
        """Valida emissão das etiquetas de colarinho regulamentares ABNT NBR 12176."""
        self.client.force_authenticate(user=self.user_op)

        # Envasa cilindro
        cil, envase, _ = registrar_envase_cilindro(
            cilindro=self.cil1,
            lote=self.lote_o2,
            pressao_final_bar=200,
            usuario=self.user_op
        )

        res = self.client.get(f'/produtos/api/envases/etiquetas-colarinho/?lote_id={self.lote_o2.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        etiquetas = res.data
        self.assertEqual(len(etiquetas), 1)

        tag = etiquetas[0]
        self.assertEqual(tag['lote_codigo'], self.lote_o2.codigo_lote)
        self.assertEqual(tag['gas_sigla'], 'O2-MED-F3')
        self.assertEqual(tag['pressao_final_bar'], 200)
        self.assertEqual(tag['rt_nome'], 'Dr. Carlos Alberto RT')
        self.assertIn('ABNT NBR 12176', tag['normas'])

    # ==============================================================================
    # 2. TESTES DA CENTRAL DE RECEBIMENTO DE FORNECEDOR (RDC 887/2024)
    # ==============================================================================

    def test_recebimento_fornecedor_individual_e_batelada_com_laudo(self):
        """Registra entrada de fornecedor externo (RDC 887/2024) com arquivo de laudo e RT conferente."""
        self.client.force_authenticate(user=self.user_op)

        laudo_fake = SimpleUploadedFile(
            "laudo_fornecedor.pdf",
            b"%PDF-1.4 Fake PDF Content for Analytical Certificate",
            content_type="application/pdf"
        )

        # Recebimento em Batelada sob mesma NF
        data = {
            'fornecedor_nome': 'White Martins Gases Industriais Ltda',
            'fornecedor_cnpj': '35.820.448/0001-30',
            'nota_fiscal': 'NF-987654',
            'lote_fornecedor': 'LOTE-WM-2026-X1',
            'data_envase_origem': str(self.hoje),
            'data_validade': str(self.hoje + timedelta(days=730)),
            'pressao_recebimento_bar': 200,
            'responsavel_tecnico_id': self.rt_registro.id,
            'laudo_pdf': laudo_fake,
            'cilindros': f"{self.cil1.id},{self.cil2.id}"
        }

        res = self.client.post('/produtos/api/recebimentos-fornecedor/registrar/', data, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['sucesso'])
        self.assertEqual(res.data['total_recebidos'], 2)

        self.cil1.refresh_from_db()
        self.cil2.refresh_from_db()
        self.assertEqual(self.cil1.status, 'CHEIO_DISPONIVEL')
        self.assertEqual(self.cil2.status, 'CHEIO_DISPONIVEL')
        self.assertIsNotNone(self.cil1.recebimento_externo_atual)
        self.assertEqual(self.cil1.recebimento_externo_atual.lote_fornecedor, 'LOTE-WM-2026-X1')

        # Ledger imutável com tipo RECEBIMENTO_FORNECEDOR
        movs = MovimentacaoCilindro.objects.filter(tipo='RECEBIMENTO_FORNECEDOR', cilindro__in=[self.cil1, self.cil2])
        self.assertEqual(movs.count(), 2)

    def test_recebimento_fornecedor_rejeita_lote_vencido(self):
        """Rejeita recebimento se o lote do fornecedor estiver com validade expirada."""
        self.client.force_authenticate(user=self.user_op)

        data = {
            'fornecedor_nome': 'Envasadora Externa',
            'fornecedor_cnpj': '35.820.448/0001-30',
            'nota_fiscal': 'NF-1111',
            'lote_fornecedor': 'LOTE-VENCIDO',
            'data_envase_origem': str(self.hoje - timedelta(days=800)),
            'data_validade': str(self.hoje - timedelta(days=10)),  # VENCIDO!
            'cilindro_id': self.cil1.id
        }

        res = self.client.post('/produtos/api/recebimentos-fornecedor/registrar/', data)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vencido", res.data['error'].lower())

    # ==============================================================================
    # 3. TESTES DA GESTÃO DE LOTES E BLOQUEIO EM CASCATA PELO RT
    # ==============================================================================

    def test_rt_homologacao_e_reprovacao_lote_com_bloqueio_sanitario_cascata(self):
        """RT reprova lote químico, disparando bloqueio sanitário auditado em todos os cilindros com carga ativa."""
        # 1. Envasa cilindro 1 com lote
        registrar_envase_cilindro(
            cilindro=self.cil1,
            lote=self.lote_o2,
            pressao_final_bar=200,
            usuario=self.user_op
        )
        self.cil1.refresh_from_db()
        self.assertFalse(self.cil1.bloqueio_sanitario)

        # 2. Usuário operador tenta reprovar lote -> Bloqueado (403 restrito a RT)
        self.client.force_authenticate(user=self.user_op)
        res_op = self.client.post(f'/produtos/api/lotes/{self.lote_o2.id}/qualidade/', {
            'novo_status': 'REPROVADO',
            'justificativa': 'Tentativa sem perfil RT'
        })
        self.assertEqual(res_op.status_code, status.HTTP_403_FORBIDDEN)

        # 3. RT homologador reprova o lote formalmente
        self.client.force_authenticate(user=self.user_rt)
        res_rt = self.client.post(f'/produtos/api/lotes/{self.lote_o2.id}/qualidade/', {
            'novo_status': 'REPROVADO',
            'justificativa': 'Desvio de pureza físico-química: pureza abaixo de 99.0% na retenção'
        })
        self.assertEqual(res_rt.status_code, status.HTTP_200_OK)
        self.assertEqual(res_rt.data['status_qualidade'], 'REPROVADO')

        # 4. Verifica que o cilindro cheio no pátio sofreu Bloqueio Sanitário Automático
        self.cil1.refresh_from_db()
        self.assertTrue(self.cil1.bloqueio_sanitario)
        self.assertIn("REPROVADO pelo RT", self.cil1.motivo_bloqueio_sanitario)

        # 5. Trilha imutável de AuditoriaBloqueioSanitario
        auditoria = AuditoriaBloqueioSanitario.objects.filter(cilindro=self.cil1).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.acao, 'BLOQUEIO')
        self.assertEqual(auditoria.responsavel, self.user_rt)

    # ==============================================================================
    # 4. TESTES DE RECALL ANVISA: CONTENÇÃO vs EXPOSIÇÃO HISTÓRICA & CONFIRMAÇÕES
    # ==============================================================================

    def test_recall_separacao_contencao_ativa_vs_exposicao_passada_e_confirmacoes(self):
        """
        Dossiê de Recall ANVISA:
        - Cilindro 1: Entregue no Hospital Santa Casa (ainda com carga ativa do lote alvo -> Contenção Ativa).
        - Cilindro 2: Entregue no Hospital, devolvido vazio e reenvasado com outro lote (Exposição Passada).
        - Criação de RecallCampanha pelo RT, homologação formal e confirmação de recolha.
        """
        # 1. Envasa ambos os cilindros com lote_o2
        registrar_envase_cilindro(cilindro=self.cil1, lote=self.lote_o2, pressao_final_bar=200, usuario=self.user_op)
        registrar_envase_cilindro(cilindro=self.cil2, lote=self.lote_o2, pressao_final_bar=200, usuario=self.user_op)

        # 2. Entrega ambos ao hospital
        registrar_entrega_cilindro(cilindro=self.cil1, cliente=self.hospital, usuario=self.user_op)
        registrar_entrega_cilindro(cilindro=self.cil2, cliente=self.hospital, usuario=self.user_op)

        # 3. Cilindro 2 é recolhido vazio pelo motorista e reenvasado com lote de Nitrogênio
        registrar_recolha_cilindro(cilindro=self.cil2, cliente=self.hospital, usuario=self.user_op)

        # Consulta dossiê de recall
        dossie = obter_dossie_recall_lote(self.lote_o2.codigo_lote, tenant_id=self.tenant.id)
        self.assertIsNotNone(dossie)

        contencao = dossie['contencao_operacional']
        exposicao = dossie['exposicao_historica']

        # Contenção ativa deve conter apenas o cilindro 1 (cilindro 2 já não contém mais o gás)
        self.assertEqual(len(contencao), 1)
        self.assertEqual(contencao[0]['cilindro_id'], self.cil1.id)
        self.assertEqual(contencao[0]['local_tipo'], 'CLIENTE')

        # Exposição histórica contém as 2 entregas registradas no Ledger
        self.assertEqual(len(exposicao), 2)

        # 4. Criação da Campanha Formal de Recall
        self.client.force_authenticate(user=self.user_rt)
        res_camp = self.client.post('/produtos/api/campanhas-recall/', {
            'lote_id': self.lote_o2.id,
            'codigo_campanha': 'REC-ANVISA-2026-001',
            'motivo': 'Desvio de conformidade físico-química',
            'texto_notificacao': 'Prezado hospital, recolha cautelar imediata do lote.'
        }, format='json')
        self.assertEqual(res_camp.status_code, status.HTTP_201_CREATED)
        campanha_id = res_camp.data['id']
        self.assertEqual(res_camp.data['status'], 'ABERTO')

        # 5. Homologação formal pelo RT
        res_homolog = self.client.post(f'/produtos/api/campanhas-recall/{campanha_id}/homologar/')
        self.assertEqual(res_homolog.status_code, status.HTTP_200_OK)
        self.assertEqual(res_homolog.data['status'], 'HOMOLOGADO_RT')
        self.assertIsNotNone(res_homolog.data['homologado_em'])

        # 6. Acompanhamento de itens de recolha por cliente
        res_itens = self.client.get(f'/produtos/api/itens-recall/?campanha_id={campanha_id}')
        self.assertEqual(res_itens.status_code, status.HTTP_200_OK)
        raw_itens = res_itens.data
        itens = raw_itens.get('results', raw_itens) if isinstance(raw_itens, dict) else raw_itens
        self.assertGreaterEqual(len(itens), 1)

        item_contencao = next(i for i in itens if i['tipo_exposicao'] == 'CONTENCAO_ATIVA')
        self.assertEqual(item_contencao['status_notificacao'], 'PENDENTE')

        # 7. Confirmação de recolhimento do cilindro
        res_conf = self.client.post(f'/produtos/api/itens-recall/{item_contencao["id"]}/confirmar-recolhimento/', {
            'status_notificacao': 'RECOLHIDO',
            'observacoes': 'Casco físico recolhido pela equipe de logística às 14:00'
        }, format='json')
        self.assertEqual(res_conf.status_code, status.HTTP_200_OK)
        self.assertEqual(res_conf.data['status_notificacao'], 'RECOLHIDO')
        self.assertIsNotNone(res_conf.data['recolhido_em'])
