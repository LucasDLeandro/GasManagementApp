from decimal import Decimal
from datetime import timedelta
import uuid
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import Cliente
from produtos.models import GasQuimico, ModeloCilindro, SkuRecarga, Cilindro, LoteEnvase, EnvaseCilindro, MovimentacaoCilindro
from produtos.services import registrar_envase_cilindro, registrar_entrega_cilindro, registrar_recolha_cilindro

User = get_user_model()

class AnvisaRecallSprint4Tests(TestCase):
    """
    Suíte de Testes Automatizados da SPRINT 4:
    - Rastreabilidade Farmacêutica ANVISA (RDC nº 658/2022, IN nº 129/2022, RDC nº 870/2024, RDC nº 887/2024 e Resolução CFF nº 731/2022).
    - Trava de Envase (compatibilidade química, validade do lote, teste hidrostático).
    - Trava de Expedição/Entrega para gases medicinais (bloqueio de cilindro sem lote ou com lote vencido).
    - Histórico Perpétuo de Envase (EnvaseCilindro) e limpeza do envase_atual na recolha.
    - Motor e API de Auditoria & Recall ANVISA em 1 Clique (JSON e exportação CSV).
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            cnpj='44.555.666/0001-77',
            razao_social='Oxigênio Hospitalar Brasil Ltda',
            nome_fantasia='Oxigênio Hospitalar'
        )
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(
            username='farmaceutico.resp',
            password='senha_segura_123',
            tipo_usuario='GERENTE'
        )
        Membership.objects.create(user=self.user, tenant=self.tenant, papel='GERENTE')
        self.client.force_authenticate(user=self.user)

        self.hoje = timezone.now().date()
        self.agora = timezone.now()

        # Gases: 1 Medicinal (exige_lote_anvisa=True) e 1 Industrial (exige_lote_anvisa=False)
        self.gas_o2_med, _ = GasQuimico.objects.get_or_create(
            sigla='O2-MED-SP4',
            defaults={
                'nome': 'Oxigênio Medicinal Comprimido',
                'categoria': 'MEDICINAL',
                'numero_onu': '1072',
                'classe_risco': '2.2',
                'cor_padrao_abnt': 'Verde Emblema',
                'exige_lote_anvisa': True
            }
        )

        self.gas_n2_ind, _ = GasQuimico.objects.get_or_create(
            sigla='N2-IND-SP4',
            defaults={
                'nome': 'Nitrogênio Industrial',
                'categoria': 'INDUSTRIAL',
                'numero_onu': '1066',
                'classe_risco': '2.2',
                'cor_padrao_abnt': 'Cinza Médio',
                'exige_lote_anvisa': False
            }
        )

        self.modelo_50l = ModeloCilindro.objects.create(
            descricao='Cilindro Aço 50L',
            material='ACO',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('60.00'),
            padrao_valvula_abnt='ABNT 218-1',
            periodicidade_reteste_anos=5
        )

        self.cliente_hospital = Cliente.objects.create(
            tipo_cliente='PJ',
            cnpj='55.666.777/0001-88',
            nome='Hospital Geral de Trauma',
            endereco='Av. Brasil Central, 1000',
            telefone='6139998877',
            estado='DF',
            cidade='Brasília'
        )

        # Lotes de Envase
        self.lote_valido = LoteEnvase.objects.create(
            gas=self.gas_o2_med,
            codigo_lote='LOTE-MED-2026-VAL',
            data_envase=self.hoje - timedelta(days=5),
            data_validade=self.hoje + timedelta(days=360),
            pureza_percentual=Decimal('99.70'),
            responsavel_tecnico='Dra. Vanessa Santos CRF-DF 8841'
        )

        self.lote_vencido = LoteEnvase.objects.create(
            gas=self.gas_o2_med,
            codigo_lote='LOTE-MED-2025-EXP',
            data_envase=self.hoje - timedelta(days=400),
            data_validade=self.hoje - timedelta(days=20),
            pureza_percentual=Decimal('98.50'),
            responsavel_tecnico='Dr. Roberto Lima CRQ-04 9912'
        )

        self.lote_n2 = LoteEnvase.objects.create(
            gas=self.gas_n2_ind,
            codigo_lote='LOTE-N2-2026-01',
            data_envase=self.hoje - timedelta(days=5),
            data_validade=self.hoje + timedelta(days=360),
            pureza_percentual=Decimal('99.90'),
            responsavel_tecnico='Eng. Carlos Silva CRQ-04 5543'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_bloqueio_envase_cilindro_reteste_vencido(self):
        """
        1. Cilindro com teste hidrostático INMETRO expirado não pode ser envasado.
        """
        cil = Cilindro.objects.create(
            codigo_qr='QR-TEST-RET-VENC',
            numero_serie_ogiva='SN-RET-VENC',
            fabricante='Cilbras',
            ano_fabricacao=2015,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365 * 6),
            data_proximo_reteste=self.hoje - timedelta(days=10), # Vencido há 10 dias
            status='VAZIO_TRIAGEM'
        )

        with self.assertRaises(ValidationError) as ctx:
            registrar_envase_cilindro(
                cilindro_id=cil.id,
                lote_id=self.lote_valido.id,
                pressao_bar=200,
                usuario=self.user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn('teste hidrostático venceu', str(ctx.exception))

    def test_bloqueio_envase_incompatibilidade_quimica(self):
        """
        2. Bloqueia envasar lote de gás incompatível com o gás dedicado do cilindro (ex: N2 em O2).
        """
        cil_o2 = Cilindro.objects.create(
            codigo_qr='QR-TEST-INCOMPAT',
            numero_serie_ogiva='SN-INCOMPAT',
            fabricante='Mannesmann',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )

        with self.assertRaises(ValidationError) as ctx:
            registrar_envase_cilindro(
                cilindro_id=cil_o2.id,
                lote_id=self.lote_n2.id, # Lote de Nitrogênio
                pressao_bar=200,
                usuario=self.user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn('Incompatibilidade química', str(ctx.exception))

    def test_bloqueio_envase_lote_vencido(self):
        """
        3. Bloqueia envasar com lote de validade expirada (Trava ANVISA).
        """
        cil = Cilindro.objects.create(
            codigo_qr='QR-TEST-LOTE-EXP',
            numero_serie_ogiva='SN-LOTE-EXP',
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )

        with self.assertRaises(ValidationError) as ctx:
            registrar_envase_cilindro(
                cilindro_id=cil.id,
                lote_id=self.lote_vencido.id,
                pressao_bar=200,
                usuario=self.user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn('está vencido desde', str(ctx.exception))

    def test_sucesso_envase_cilindro_e_ledger(self):
        """
        4. Envase com sucesso:
        - Cria EnvaseCilindro com pressão e operador.
        - Cilindro passa para CHEIO_DISPONIVEL e aponta para envase_atual.
        - MovimentacaoCilindro registrada com tipo ENVASE e código do lote.
        """
        cil = Cilindro.objects.create(
            codigo_qr='QR-TEST-OK-ENV',
            numero_serie_ogiva='SN-OK-ENV',
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )

        cil_ret, env_ret, mov_ret = registrar_envase_cilindro(
            cilindro_id=cil.id,
            lote_id=self.lote_valido.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=self.agora,
            client_uuid=uuid.uuid4(),
            observacoes="Aprovado em CQ"
        )

        cil.refresh_from_db()
        self.assertEqual(cil.status, 'CHEIO_DISPONIVEL')
        self.assertIsNotNone(cil.envase_atual)
        self.assertEqual(cil.envase_atual.lote, self.lote_valido)
        self.assertEqual(cil.envase_atual.pressao_final_bar, 200)

        # Valida histórico perpétuo
        self.assertEqual(cil.historico_envases.count(), 1)
        self.assertEqual(self.lote_valido.cilindros_envasados.count(), 1)

        # Valida Ledger
        self.assertEqual(mov_ret.tipo, 'ENVASE')
        self.assertEqual(mov_ret.lote_envase, self.lote_valido.codigo_lote)

    def test_bloqueio_entrega_medicinal_sem_lote_ativo(self):
        """
        5. Gás medicinal (exige_lote_anvisa=True) não pode ser entregue se não tiver envase ativo.
        """
        cil_sem_lote = Cilindro.objects.create(
            codigo_qr='QR-MED-SEM-LOTE',
            numero_serie_ogiva='SN-MED-SEM-LOTE',
            fabricante='Mannesmann',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='CHEIO_DISPONIVEL',
            envase_atual=None # Sem envase ativo
        )

        with self.assertRaises(ValidationError) as ctx:
            registrar_entrega_cilindro(
                cilindro_id=cil_sem_lote.id,
                cliente=self.cliente_hospital,
                usuario=self.user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn('não possui registro de envase ativo', str(ctx.exception))

    def test_bloqueio_entrega_medicinal_com_lote_vencido(self):
        """
        6. Cilindro medicinal com lote vencido não pode ser entregue ao cliente.
        """
        cil = Cilindro.objects.create(
            codigo_qr='QR-MED-EXPIRADO',
            numero_serie_ogiva='SN-MED-EXPIRADO',
            fabricante='Cilbras',
            ano_fabricacao=2020,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='CHEIO_DISPONIVEL'
        )

        # Força associação com lote vencido (simulando cilindro esquecido no estoque)
        env = EnvaseCilindro.objects.create(
            cilindro=cil,
            lote=self.lote_vencido,
            pressao_final_bar=200,
            envasado_em=self.agora - timedelta(days=30),
            operador=self.user
        )
        cil.envase_atual = env
        cil.save(update_fields=['envase_atual'])

        with self.assertRaises(ValidationError) as ctx:
            registrar_entrega_cilindro(
                cilindro_id=cil.id,
                cliente=self.cliente_hospital,
                usuario=self.user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn('vencido desde', str(ctx.exception))

    def test_sucesso_entrega_e_recolha_limpa_envase_atual(self):
        """
        7. Entrega medicinal com lote válido tem sucesso.
        Ao recolher o cilindro vazio, envase_atual é limpo no cilindro, mas o histórico permanece.
        """
        cil = Cilindro.objects.create(
            codigo_qr='QR-CICLO-COMPLETO',
            numero_serie_ogiva='SN-CICLO-01',
            fabricante='Cilbras',
            ano_fabricacao=2022,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )

        # 1. Envasa
        registrar_envase_cilindro(
            cilindro_id=cil.id,
            lote_id=self.lote_valido.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=2),
            client_uuid=uuid.uuid4()
        )

        # 2. Entrega no hospital
        cil_entregue, mov_entrega = registrar_entrega_cilindro(
            cilindro_id=cil.id,
            cliente=self.cliente_hospital,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=1),
            client_uuid=uuid.uuid4()
        )
        self.assertEqual(cil_entregue.status, 'EM_POSSE_CLIENTE')
        self.assertEqual(mov_entrega.lote_envase, self.lote_valido.codigo_lote)

        # 3. Recolhe vazio
        cil_recolhido, mov_recolha = registrar_recolha_cilindro(
            cilindro_id=cil.id,
            cliente=self.cliente_hospital,
            usuario=self.user,
            ocorrido_em=self.agora,
            client_uuid=uuid.uuid4(),
            observacao="Cilindro consumido no CTI"
        )
        self.assertEqual(cil_recolhido.status, 'VAZIO_TRIAGEM')
        self.assertIsNone(cil_recolhido.envase_atual) # Conteúdo foi consumido!
        # Histórico preservado:
        self.assertEqual(cil.historico_envases.count(), 1)

    def test_api_recall_rastreabilidade_arvore_e_metricas(self):
        """
        8. Valida o motor de Recall ANVISA em 1 Clique (/produtos/api/lotes-anvisa/recall/):
        - Localiza cilindro no pátio e cilindro no hospital.
        - Retorna métricas, cliente afetado com telefone e endereço.
        """
        # Cilindro 1 no pátio
        cil_patio = Cilindro.objects.create(
            codigo_qr='QR-RECALL-PATIO',
            numero_serie_ogiva='SN-REC-01',
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )
        registrar_envase_cilindro(
            cilindro_id=cil_patio.id,
            lote_id=self.lote_valido.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=3),
            client_uuid=uuid.uuid4()
        )

        # Cilindro 2 no hospital
        cil_hosp = Cilindro.objects.create(
            codigo_qr='QR-RECALL-HOSP',
            numero_serie_ogiva='SN-REC-02',
            fabricante='Mannesmann',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )
        registrar_envase_cilindro(
            cilindro_id=cil_hosp.id,
            lote_id=self.lote_valido.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=3),
            client_uuid=uuid.uuid4()
        )
        registrar_entrega_cilindro(
            cilindro_id=cil_hosp.id,
            cliente=self.cliente_hospital,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=1),
            client_uuid=uuid.uuid4()
        )

        # Cilindro 3: Envasado no passado com este lote, mas já recolhido vazio (envase inativo)
        cil_historico = Cilindro.objects.create(
            codigo_qr='QR-RECALL-HIST',
            numero_serie_ogiva='SN-REC-03',
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )
        registrar_envase_cilindro(
            cilindro_id=cil_historico.id,
            lote_id=self.lote_valido.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=10),
            client_uuid=uuid.uuid4()
        )
        registrar_entrega_cilindro(
            cilindro_id=cil_historico.id,
            cliente=self.cliente_hospital,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=8),
            client_uuid=uuid.uuid4()
        )
        registrar_recolha_cilindro(
            cilindro_id=cil_historico.id,
            cliente=self.cliente_hospital,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=2),
            client_uuid=uuid.uuid4()
        )
        self.assertFalse(cil_historico.envase_atual == self.lote_valido.cilindros_envasados.filter(cilindro=cil_historico).first())

        url = f'/produtos/api/lotes-anvisa/recall/?codigo_lote={self.lote_valido.codigo_lote}'
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        data = res.data
        self.assertEqual(data['lote']['codigo_lote'], self.lote_valido.codigo_lote)
        # Total histórico envasado: 3 cilindros
        self.assertEqual(data['metricas']['total_envasados'], 3)
        # Mas apenas 1 está ativamente no cliente e 1 no pátio:
        self.assertEqual(data['metricas']['total_em_clientes'], 1)
        self.assertEqual(data['metricas']['total_no_patio'], 1)
        self.assertEqual(data['metricas']['total_historico_encerrado'], 1)
        self.assertTrue(data['metricas']['alerta_recall_ativo'])

        # Verifica dados do cliente afetado
        item_hosp = next(c for c in data['cilindros'] if c['codigo_qr'] == 'QR-RECALL-HOSP')
        self.assertEqual(item_hosp['local_tipo'], 'CLIENTE')
        self.assertTrue(item_hosp['is_envase_ativo'])
        self.assertEqual(item_hosp['cliente']['nome'], 'Hospital Geral de Trauma')
        self.assertEqual(item_hosp['cliente']['telefone'], '6139998877')

        # Verifica cilindro de histórico encerrado
        item_hist = next(c for c in data['cilindros'] if c['codigo_qr'] == 'QR-RECALL-HIST')
        self.assertFalse(item_hist['is_envase_ativo'])

    def test_api_recall_exportacao_csv(self):
        """
        9. Valida a exportação CSV do Dossiê de Rastreabilidade e Recall:
        - Retorna arquivo CSV com cabeçalho delimitado por ponto e vírgula.
        - Contém as informações do lote, coluna Envase Ativo? e dados do cliente hospitalar.
        """
        cil = Cilindro.objects.create(
            codigo_qr='QR-CSV-EXP',
            numero_serie_ogiva='SN-CSV-01',
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2_med,
            tara_real_kg=Decimal('60.00'),
            data_ultimo_reteste=self.hoje - timedelta(days=365),
            data_proximo_reteste=self.hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )
        registrar_envase_cilindro(
            cilindro_id=cil.id,
            lote_id=self.lote_valido.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=2),
            client_uuid=uuid.uuid4()
        )
        registrar_entrega_cilindro(
            cilindro_id=cil.id,
            cliente=self.cliente_hospital,
            usuario=self.user,
            ocorrido_em=self.agora - timedelta(days=1),
            client_uuid=uuid.uuid4()
        )

        url_csv = f'/produtos/api/lotes-anvisa/recall/?codigo_lote={self.lote_valido.codigo_lote}&export=csv'
        res = self.client.get(url_csv)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="Dossie_Rastreabilidade_Recall_Lote_', res['Content-Disposition'])

        conteudo = res.content.decode('utf-8')
        self.assertIn(self.lote_valido.codigo_lote, conteudo)
        self.assertIn('Hospital Geral de Trauma', conteudo)
        self.assertIn('6139998877', conteudo)
        self.assertIn('QR-CSV-EXP', conteudo)
        self.assertIn('Sim (Ativo)', conteudo)
