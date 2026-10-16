import uuid
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
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
    MovimentacaoCilindro,
    AuditoriaBloqueioSanitario,
    RecallCampanha,
    ItemRecallCliente,
)
from produtos.services import (
    registrar_envase_cilindro,
    registrar_entrega_cilindro,
    registrar_recolha_cilindro,
    alocar_cilindro_rota,
    acionar_bloqueio_sanitario,
    liberar_bloqueio_sanitario,
    atualizar_qualidade_lote,
    abrir_campanha_recall,
    homologar_campanha_recall,
    obter_dossie_recall_lote,
)

User = get_user_model()


class Sprint5A4RecallEBloqueioSanitarioTests(TestCase):
    """
    Suíte de Testes Automatizados da SPRINT 5A.4:
    1. Flag Ortogonal bloqueio_sanitario e Regras de Reteste Vencido.
    2. Bloqueio de envase, rota e entrega ao cliente (mas PERMISSÃO irrestrita de recolha/retorno de casco vazio).
    3. Controle e auditoria de bloqueio/desbloqueio exclusivo pelo RESPONSAVEL_TECNICO.
    4. Qualidade do Lote (QUARENTENA, APROVADO, REPROVADO) e bloqueio sanitário automático ao reprovar.
    5. Separação Estrita de Recall: Contenção Operacional (Risco Ativo) vs. Dossiê de Exposição Histórica (Zero Falso Positivo).
    6. Campanhas Formais de Recall (RecallCampanha e ItemRecallCliente) e Homologação pelo RT.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            cnpj='66.777.888/0001-99',
            razao_social='Oxigênio & Gases Especiais do Brasil S.A.',
            nome_fantasia='OxiBrasil'
        )
        self.token = set_current_tenant(self.tenant)

        # Usuários e Membros
        self.rt_user = User.objects.create_user(
            username='farmaceutica.chefia',
            password='senha_rt_forte_123',
            first_name='Dra. Clara',
            last_name='Menezes'
        )
        Membership.objects.create(
            user=self.rt_user,
            tenant=self.tenant,
            papel='RESPONSAVEL_TECNICO'
        )

        self.rt_registro = ResponsavelTecnico.objects.create(
            user=self.rt_user,
            nome_completo='Dra. Clara Menezes',
            conselho_classe='CRF',
            numero_registro='54321',
            uf_conselho='SP',
            vigencia_inicio=timezone.now().date() - timedelta(days=100),
            ativo=True
        )

        self.operador_user = User.objects.create_user(
            username='operador.patio1',
            password='senha_operador_123',
            first_name='Carlos',
            last_name='Silva'
        )
        Membership.objects.create(
            user=self.operador_user,
            tenant=self.tenant,
            papel='OPERADOR_PATIO'
        )

        self.vendedor_user = User.objects.create_user(
            username='vendedor.comercial',
            password='senha_vendedor_123'
        )
        Membership.objects.create(
            user=self.vendedor_user,
            tenant=self.tenant,
            papel='VENDEDOR'
        )

        self.hoje = timezone.now().date()
        self.agora = timezone.now()

        # Gases
        self.gas_med, _ = GasQuimico.objects.get_or_create(
            sigla='O2-MED-5A4',
            defaults={
                'nome': 'Oxigênio Medicinal Gasoso',
                'categoria': 'MEDICINAL',
                'numero_onu': '1072',
                'classe_risco': '2.2',
                'cor_padrao_abnt': 'Verde Emblema',
                'exige_lote_anvisa': True
            }
        )

        self.modelo_50l = ModeloCilindro.objects.create(
            descricao='Cilindro Aço 50L Medicinal',
            material='ACO',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('58.50'),
            padrao_valvula_abnt='ABNT 218-1',
            periodicidade_reteste_anos=5
        )

        # Clientes
        self.hospital_x = Cliente.objects.create(
            tipo_cliente='PJ',
            cnpj='11.222.333/0001-44',
            nome='Hospital Regional Darcy Vargas',
            endereco='Rua das Flores, 120',
            cidade='São Paulo',
            estado='SP',
            telefone='1133334444'
        )
        self.hospital_y = Cliente.objects.create(
            tipo_cliente='PJ',
            cnpj='22.333.444/0001-55',
            nome='Hospital Infantil Menino Jesus',
            endereco='Av. Paulista, 2000',
            cidade='São Paulo',
            estado='SP',
            telefone='1133335555'
        )

        # Lotes
        self.lote_a = LoteEnvase.objects.create(
            gas=self.gas_med,
            codigo_lote='LOTE-MED-A-2026',
            data_envase=self.hoje - timedelta(days=20),
            data_validade=self.hoje + timedelta(days=360),
            pureza_percentual=Decimal('99.60'),
            responsavel_tecnico='Dra. Clara Menezes (CRF 54321)',
            responsavel_tecnico_fk=self.rt_registro,
            status_qualidade='APROVADO'
        )

        self.lote_b = LoteEnvase.objects.create(
            gas=self.gas_med,
            codigo_lote='LOTE-MED-B-2026',
            data_envase=self.hoje - timedelta(days=5),
            data_validade=self.hoje + timedelta(days=360),
            pureza_percentual=Decimal('99.80'),
            responsavel_tecnico='Dra. Clara Menezes (CRF 54321)',
            responsavel_tecnico_fk=self.rt_registro,
            status_qualidade='APROVADO'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def _criar_cilindro(self, codigo_qr, numero_serie, status='VAZIO_TRIAGEM', reteste_vencido=False, bloqueio_sanitario=False):
        dt_prox = self.hoje - timedelta(days=10) if reteste_vencido else self.hoje + timedelta(days=365)
        return Cilindro.objects.create(
            codigo_qr=codigo_qr,
            numero_serie_ogiva=numero_serie,
            fabricante='Cilindros Brasil S/A',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_med,
            tara_real_kg=Decimal('58.20'),
            data_ultimo_reteste=self.hoje - timedelta(days=365 * 4),
            data_proximo_reteste=dt_prox,
            status=status,
            bloqueio_sanitario=bloqueio_sanitario,
            motivo_bloqueio_sanitario="Motivo teste" if bloqueio_sanitario else None
        )

    # ==========================================================================
    # 1. TESTES DE BLOQUEIO SANITÁRIO ORTOGONAL E RETESTE VENCIDO
    # ==========================================================================

    def test_bloqueio_sanitario_impede_envase_rota_e_entrega(self):
        """
        Garante que um cilindro com bloqueio_sanitario=True tem barrados:
        - Envase na rampa;
        - Reserva para rota;
        - Entrega no cliente.
        """
        cilindro = self._criar_cilindro('QR-BLQ-01', 'SERIE-BLQ-01', status='VAZIO_TRIAGEM', bloqueio_sanitario=True)

        # 1. Envase barrado
        with self.assertRaises(ValidationError) as ctx:
            registrar_envase_cilindro(
                cilindro_id=cilindro.id,
                lote_id=self.lote_a.id,
                pressao_final_bar=200,
                usuario=self.operador_user
            )
        self.assertIn("Bloqueio Sanitário ANVISA", str(ctx.exception))

        # Libera bloqueio temporariamente para envasar
        cilindro.bloqueio_sanitario = False
        cilindro.save()
        registrar_envase_cilindro(
            cilindro_id=cilindro.id,
            lote_id=self.lote_a.id,
            pressao_final_bar=200,
            usuario=self.operador_user
        )
        cilindro.refresh_from_db()
        self.assertEqual(cilindro.status, 'CHEIO_DISPONIVEL')

        # Aciona bloqueio sanitário pelo RT
        acionar_bloqueio_sanitario(
            cilindro_id=cilindro.id,
            motivo="Válvula sob suspeita de micro-vazamento",
            usuario=self.rt_user
        )
        cilindro.refresh_from_db()
        self.assertTrue(cilindro.bloqueio_sanitario)
        # Ortogonalidade: status físico permanece CHEIO_DISPONIVEL
        self.assertEqual(cilindro.status, 'CHEIO_DISPONIVEL')

        # 2. Reserva de rota barrada
        with self.assertRaises(ValidationError) as ctx:
            alocar_cilindro_rota(
                cilindro_id=cilindro.id,
                entrega=None,
                usuario=self.operador_user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn("Bloqueio Sanitário ANVISA", str(ctx.exception))

        # 3. Entrega direta ao cliente barrada
        with self.assertRaises(ValidationError) as ctx:
            registrar_entrega_cilindro(
                cilindro_id=cilindro.id,
                cliente=self.hospital_x,
                usuario=self.operador_user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn("Bloqueio Sanitário ANVISA", str(ctx.exception))

    def test_bloqueio_sanitario_e_reteste_vencido_permitem_recolha_de_casco(self):
        """
        Regra de Ouro Sanitária: Cilindros bloqueados ou com teste hidrostático vencido
        em posse do cliente NUNCA podem ter sua recolha impedida. A fábrica deve recolhê-los!
        """
        # Cilindro entregue no cliente
        cilindro = self._criar_cilindro('QR-REC-01', 'SERIE-REC-01', status='VAZIO_TRIAGEM')
        registrar_envase_cilindro(
            cilindro_id=cilindro.id,
            lote_id=self.lote_a.id,
            pressao_final_bar=200,
            usuario=self.operador_user
        )
        registrar_entrega_cilindro(
            cilindro_id=cilindro.id,
            cliente=self.hospital_x,
            usuario=self.operador_user,
            ocorrido_em=self.agora,
            client_uuid=uuid.uuid4()
        )
        cilindro.refresh_from_db()
        self.assertEqual(cilindro.status, 'EM_POSSE_CLIENTE')

        # Aciona bloqueio sanitário enquanto o cilindro está no cliente
        acionar_bloqueio_sanitario(
            cilindro_id=cilindro.id,
            motivo="Recall em hospital - recolha preventiva",
            usuario=self.rt_user
        )
        cilindro.refresh_from_db()
        self.assertTrue(cilindro.bloqueio_sanitario)

        # Simula também teste hidrostático vencido no cliente
        cilindro.data_proximo_reteste = self.hoje - timedelta(days=5)
        cilindro.save(update_fields=['data_proximo_reteste'])
        cilindro.refresh_from_db()
        self.assertTrue(cilindro.bloqueio_sanitario)
        self.assertTrue(cilindro.reteste_vencido)

        # Recolha para retorno à fábrica DEVE ter sucesso pleno!
        cil_recolhido, mov = registrar_recolha_cilindro(
            cilindro_id=cilindro.id,
            cliente=self.hospital_x,
            usuario=self.operador_user,
            ocorrido_em=self.agora,
            client_uuid=uuid.uuid4(),
            observacao="Recolha de cilindro em recall/vencido"
        )
        self.assertEqual(cil_recolhido.status, 'VAZIO_TRIAGEM')
        self.assertIsNone(cil_recolhido.cliente_posse_atual)
        self.assertIsNone(cil_recolhido.envase_atual)
        self.assertEqual(mov.tipo, 'RECOLHA_CLIENTE')

    # ==========================================================================
    # 2. TESTES DE AUTORIZAÇÃO RBAC E AUDITORIA DE BLOQUEIO SANITÁRIO
    # ==========================================================================

    def test_bloqueio_sanitario_exclusivo_responsavel_tecnico(self):
        """
        Bloqueio e liberação sanitária exigem papel RESPONSAVEL_TECNICO e geram auditoria.
        """
        cilindro = self._criar_cilindro('QR-AUD-01', 'SERIE-AUD-01')

        # Operador de pátio tenta bloquear -> Falha 403
        with self.assertRaises(PermissionError):
            acionar_bloqueio_sanitario(
                cilindro_id=cilindro.id,
                motivo="Tentativa não autorizada",
                usuario=self.operador_user
            )

        # RT bloqueia -> Sucesso e registro em AuditoriaBloqueioSanitario
        cil, aud = acionar_bloqueio_sanitario(
            cilindro_id=cilindro.id,
            motivo="Desvio de pressão constatado em manômetro",
            usuario=self.rt_user
        )
        self.assertTrue(cil.bloqueio_sanitario)
        self.assertEqual(aud.acao, 'BLOQUEIO')
        self.assertEqual(aud.responsavel, self.rt_user)
        self.assertEqual(aud.responsavel_tecnico, self.rt_registro)
        self.assertEqual(aud.rt_nome_snapshot, 'Dra. Clara Menezes')

        # Vendedor tenta liberar -> Falha 403
        with self.assertRaises(PermissionError):
            liberar_bloqueio_sanitario(
                cilindro_id=cilindro.id,
                justificativa="Quero vender esse cilindro",
                usuario=self.vendedor_user
            )

        # RT libera com justificativa técnica -> Sucesso e registro em Auditoria
        cil_liberado, aud_lib = liberar_bloqueio_sanitario(
            cilindro_id=cilindro.id,
            justificativa="Manômetro aferido e purga executada com laudo aprovado",
            usuario=self.rt_user
        )
        self.assertFalse(cil_liberado.bloqueio_sanitario)
        self.assertEqual(aud_lib.acao, 'DESBLOQUEIO')
        self.assertEqual(cilindro.auditorias_bloqueio.count(), 2)

    def test_endpoint_bloqueio_sanitario_drf(self):
        """
        Testa o endpoint POST /produtos/api/cilindros/{id}/bloqueio-sanitario/ via API DRF.
        """
        cilindro = self._criar_cilindro('QR-DRF-01', 'SERIE-DRF-01')
        url = f'/produtos/api/cilindros/{cilindro.id}/bloqueio-sanitario/'

        # 1. Usuário sem papel de RT recebe 403
        self.client.force_authenticate(user=self.operador_user)
        res = self.client.post(url, {'acao': 'BLOQUEIO', 'motivo': 'Bloqueio teste'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Usuário RT executa bloqueio com sucesso
        self.client.force_authenticate(user=self.rt_user)
        res = self.client.post(url, {'acao': 'BLOQUEIO', 'motivo': 'Quarentena preventiva ANVISA'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['cilindro']['bloqueio_sanitario'])
        self.assertEqual(res.data['auditoria']['acao'], 'BLOQUEIO')

        # 3. Consulta histórico de auditoria
        res_aud = self.client.get(f'/produtos/api/cilindros/{cilindro.id}/auditorias-bloqueio/')
        self.assertEqual(res_aud.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_aud.data), 1)

    # ==========================================================================
    # 3. TESTES DE QUALIDADE DO LOTE (QUARENTENA, APROVADO, REPROVADO)
    # ==========================================================================

    def test_lote_em_quarentena_impede_reserva_e_entrega(self):
        """
        Lotes com status_qualidade='QUARENTENA' não podem ser reservados para rota nem entregues.
        """
        lote_quarentena = LoteEnvase.objects.create(
            gas=self.gas_med,
            codigo_lote='LOTE-QUARENTENA-01',
            data_envase=self.hoje,
            data_validade=self.hoje + timedelta(days=360),
            status_qualidade='QUARENTENA'
        )
        cilindro = self._criar_cilindro('QR-QUA-01', 'SERIE-QUA-01')
        registrar_envase_cilindro(
            cilindro_id=cilindro.id,
            lote_id=lote_quarentena.id,
            pressao_final_bar=200,
            usuario=self.operador_user
        )

        with self.assertRaises(ValidationError) as ctx:
            alocar_cilindro_rota(
                cilindro_id=cilindro.id,
                entrega=None,
                usuario=self.operador_user,
                ocorrido_em=self.agora,
                client_uuid=uuid.uuid4()
            )
        self.assertIn("Bloqueio de Qualidade", str(ctx.exception))

    def test_reprovar_lote_aciona_bloqueio_sanitario_automatico_nos_cilindros(self):
        """
        Ao reprovar um lote (exclusivo do RT), todos os cilindros que possuem carga ativa
        daquele lote sofrem bloqueio sanitário automático com trilha de auditoria.
        """
        cil1 = self._criar_cilindro('QR-REP-01', 'SERIE-REP-01')
        cil2 = self._criar_cilindro('QR-REP-02', 'SERIE-REP-02')

        registrar_envase_cilindro(cilindro_id=cil1.id, lote_id=self.lote_a.id, pressao_final_bar=200, usuario=self.operador_user)
        registrar_envase_cilindro(cilindro_id=cil2.id, lote_id=self.lote_a.id, pressao_final_bar=200, usuario=self.operador_user)

        self.assertFalse(cil1.bloqueio_sanitario)
        self.assertFalse(cil2.bloqueio_sanitario)

        # RT reprova o lote via serviço
        atualizar_qualidade_lote(
            lote_id=self.lote_a.id,
            novo_status='REPROVADO',
            justificativa='Presença de impurezas acima do limite farmacopeico',
            usuario=self.rt_user
        )

        cil1.refresh_from_db()
        cil2.refresh_from_db()
        self.assertTrue(cil1.bloqueio_sanitario)
        self.assertTrue(cil2.bloqueio_sanitario)
        self.assertIn("REPROVADO pelo RT", cil1.motivo_bloqueio_sanitario)
        self.assertEqual(cil1.auditorias_bloqueio.count(), 1)

    # ==========================================================================
    # 4. TESTE DO CRITÉRIO DE ACEITE DEFINITIVO (RECALL HISTÓRICO VS CONTENÇÃO)
    # ==========================================================================

    def test_criterio_aceite_zero_falso_positivo_reenvase(self):
        """
        CRITÉRIO DE ACEITE (Definition of Done) DA SPRINT 5A.4:
        Provando que um cilindro envasado com Lote A, entregue ao Hospital X, recolhido
        vazio e reenvasado posteriormente com Lote B e entregue ao Hospital Y:
        - Aparece no DOSSIÊ DE EXPOSIÇÃO HISTÓRICA do Lote A para o Hospital X.
        - NÃO aparece como pendente de recolhimento na CONTENÇÃO OPERACIONAL do Lote A (zero falso positivo).
        """
        # Cilindro 1: O cilindro viajante
        cilindro_1 = self._criar_cilindro('QR-RECALL-C1', 'SERIE-C1-HIST')

        # 1. Envasado com Lote A
        registrar_envase_cilindro(
            cilindro_id=cilindro_1.id,
            lote_id=self.lote_a.id,
            pressao_final_bar=200,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=25)
        )

        # 2. Entregue ao Hospital X
        registrar_entrega_cilindro(
            cilindro_id=cilindro_1.id,
            cliente=self.hospital_x,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=24),
            client_uuid=uuid.uuid4(),
            documento_fiscal_ref='NF-00101'
        )

        # 3. Recolhido vazio do Hospital X (Full-for-Empty)
        registrar_recolha_cilindro(
            cilindro_id=cilindro_1.id,
            cliente=self.hospital_x,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=15),
            client_uuid=uuid.uuid4(),
            observacao="Cilindro consumido pelo hospital e recolhido vazio"
        )

        # 4. Reenvasado com Lote B!
        registrar_envase_cilindro(
            cilindro_id=cilindro_1.id,
            lote_id=self.lote_b.id,
            pressao_final_bar=200,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=5)
        )

        # 5. Entregue ao Hospital Y com Lote B
        registrar_entrega_cilindro(
            cilindro_id=cilindro_1.id,
            cliente=self.hospital_y,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=4),
            client_uuid=uuid.uuid4(),
            documento_fiscal_ref='NF-00202'
        )

        # Cilindro 2: Ativo com Lote A ainda em posse do Hospital X
        cilindro_2 = self._criar_cilindro('QR-RECALL-C2', 'SERIE-C2-ATIVO')
        registrar_envase_cilindro(
            cilindro_id=cilindro_2.id,
            lote_id=self.lote_a.id,
            pressao_final_bar=200,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=10)
        )
        registrar_entrega_cilindro(
            cilindro_id=cilindro_2.id,
            cliente=self.hospital_x,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=9),
            client_uuid=uuid.uuid4(),
            documento_fiscal_ref='NF-00150'
        )

        # Cilindro 3: Ativo com Lote A no Pátio da fábrica
        cilindro_3 = self._criar_cilindro('QR-RECALL-C3', 'SERIE-C3-PATIO')
        registrar_envase_cilindro(
            cilindro_id=cilindro_3.id,
            lote_id=self.lote_a.id,
            pressao_final_bar=200,
            usuario=self.operador_user,
            ocorrido_em=self.agora - timedelta(days=2)
        )

        # ======================================================================
        # EXECUÇÃO DO MOTOR DE RECALL PARA O LOTE A
        # ======================================================================
        dossie = obter_dossie_recall_lote(self.lote_a.codigo_lote, tenant_id=self.tenant.id)
        self.assertIsNotNone(dossie)

        contencao = dossie['contencao_operacional']
        exposicao = dossie['exposicao_historica']

        # 1. Validação da Contenção Operacional (Risco Ativo):
        ids_contencao = [c['cilindro_id'] for c in contencao]
        # Cilindro 2 DEVE estar na contenção (está com Lote A no Hospital X)
        self.assertIn(cilindro_2.id, ids_contencao)
        # Cilindro 3 DEVE estar na contenção (está com Lote A no pátio)
        self.assertIn(cilindro_3.id, ids_contencao)

        # >>> PROVA DE ZERO FALSO POSITIVO <<<
        # Cilindro 1 NÃO PODE estar na Contenção do Lote A porque sua carga física atual é LOTE B!
        self.assertNotIn(
            cilindro_1.id,
            ids_contencao,
            "FALHA GRAVE: Cilindro reenvasado com outro lote apareceu indevidamente como risco ativo de recolha!"
        )

        # 2. Validação do Dossiê de Exposição Histórica:
        entregas_c1 = [e for e in exposicao if e['cilindro_id'] == cilindro_1.id]
        self.assertEqual(
            len(entregas_c1),
            1,
            "O Cilindro 1 DEVE constar no histórico de exposição do Hospital X ao Lote A!"
        )
        self.assertEqual(entregas_c1[0]['cliente']['nome'], self.hospital_x.nome)
        self.assertEqual(entregas_c1[0]['documento_fiscal_ref'], 'NF-00101')
        self.assertFalse(entregas_c1[0]['is_envase_ativo'])
        self.assertEqual(entregas_c1[0]['situacao_casco'], 'CONSUMIDO_OU_REENVASADO')

        # 3. Validação via endpoint da API DRF
        self.client.force_authenticate(user=self.rt_user)
        response = self.client.get(f'/produtos/api/lotes-anvisa/recall/?codigo_lote={self.lote_a.codigo_lote}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res_data = response.data

        self.assertIn('contencao_operacional', res_data)
        self.assertIn('exposicao_historica', res_data)
        self.assertEqual(res_data['metricas']['total_contencao_ativa'], 2)
        self.assertEqual(res_data['metricas']['total_entregas_historicas'], 2)

    # ==========================================================================
    # 5. TESTES DE CAMPANHA FORMAL DE RECALL (RecallCampanha e ItemRecallCliente)
    # ==========================================================================

    def test_ciclo_completo_campanha_recall_e_homologacao(self):
        """
        Valida a abertura e homologação formal de uma Campanha de Recall pelo RT.
        """
        cilindro = self._criar_cilindro('QR-CMP-01', 'SERIE-CMP-01')
        registrar_envase_cilindro(cilindro_id=cilindro.id, lote_id=self.lote_a.id, pressao_final_bar=200, usuario=self.operador_user)
        registrar_entrega_cilindro(cilindro_id=cilindro.id, cliente=self.hospital_x, usuario=self.operador_user, client_uuid=uuid.uuid4())

        self.client.force_authenticate(user=self.rt_user)
        payload = {
            'lote_id': self.lote_a.id,
            'codigo_campanha': 'REC-ANVISA-2026-001',
            'motivo': 'Desvio de especificação detectado no contra-laudo de estabilidade',
            'texto_notificacao': 'Prezado cliente, solicitamos cessar imediatamente o consumo do lote.'
        }
        res = self.client.post('/produtos/api/campanhas-recall/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        campanha_id = res.data['id']
        self.assertEqual(res.data['status'], 'ABERTO')

        # Homologação pelo RT
        res_homolog = self.client.post(f'/produtos/api/campanhas-recall/{campanha_id}/homologar/')
        self.assertEqual(res_homolog.status_code, status.HTTP_200_OK)
        self.assertEqual(res_homolog.data['status'], 'HOMOLOGADO_RT')
        self.assertEqual(res_homolog.data['rt_nome_snapshot'], 'Dra. Clara Menezes')

        # Consulta do Dossiê via Campanha
        res_dossie = self.client.get(f'/produtos/api/campanhas-recall/{campanha_id}/dossie/')
        self.assertEqual(res_dossie.status_code, status.HTTP_200_OK)
        self.assertIn('contencao_operacional', res_dossie.data)
