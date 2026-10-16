import uuid
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.contrib.auth import get_user_model

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant, tenant_context
from clientes.models import Cliente
from produtos.models import (
    GasQuimico,
    ModeloCilindro,
    Cilindro,
    MovimentacaoCilindro,
    LoteEnvase,
    EnvaseCilindro,
    VinculoLegadoInferido
)
from produtos.services import (
    registrar_envase_cilindro,
    registrar_entrega_cilindro,
    registrar_recolha_cilindro,
    enviar_para_reteste,
    retornar_de_reteste,
    alocar_cilindro_rota,
    baixar_cilindro,
    validar_transicao_status_cilindro
)

User = get_user_model()


class Sprint5A2ImutabilidadeLedgerFSMTests(TestCase):
    """
    Testes de Aceite da Sprint 5A.2:
    1. Imutabilidade Estrita de EnvaseCilindro (save, delete, update e delete em lote).
    2. Vínculo de Envase, documento_fiscal_ref e CheckConstraint condicional no Ledger.
    3. Proteção do Legado e Tabela Auxiliar VinculoLegadoInferido.
    4. Máquina de Estados Finita (FSM) com estado terminal BAIXADO e transições seguras.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Distribuidora Brasília de Gases Ltda',
            nome_fantasia='Brasília Gases'
        )
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(
            username='operador_sprint5a2',
            password='senha_segura_123',
            tipo_usuario='OPERADOR_PATIO'
        )
        Membership.objects.create(user=self.user, tenant=self.tenant, papel='OPERADOR_PATIO')

        self.cliente = Cliente.objects.create(
            cnpj='55.666.777/0001-88',
            nome='Hospital Santa Lúcia DF',
            endereco='SHLS 716 Conjunto C',
            telefone='6133450000',
            estado='DF',
            cidade='Brasília',
            proprietario='Diretoria Clínica'
        )

        self.gas_o2 = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2-MED-5A2',
            categoria='MEDICINAL',
            numero_onu='1072',
            classe_risco='2.2',
            cor_padrao_abnt='Verde',
            exige_lote_anvisa=True
        )

        self.modelo_50l = ModeloCilindro.objects.create(
            descricao='Cilindro Aço 50L / 10m³',
            material='ACO',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('60.00'),
            padrao_valvula_abnt='ABNT 218-1',
            periodicidade_reteste_anos=5
        )

        hoje = timezone.now().date()
        self.cilindro = Cilindro.objects.create(
            codigo_qr='QR-5A2-001',
            numero_serie_ogiva='SN-5A2-001',
            fabricante='Cilbras',
            ano_fabricacao=2021,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('59.80'),
            propriedade='PROPRIO',
            data_ultimo_reteste=hoje - timedelta(days=365),
            data_proximo_reteste=hoje + timedelta(days=365 * 4),
            status='VAZIO_TRIAGEM'
        )

        self.lote = LoteEnvase.objects.create(
            gas=self.gas_o2,
            codigo_lote='LOTE-5A2-O2-01',
            data_envase=hoje - timedelta(days=5),
            data_validade=hoje + timedelta(days=365),
            pureza_percentual=Decimal('99.65'),
            responsavel_tecnico='Dra. Camila Rocha CRF-DF 4589'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    # -------------------------------------------------------------------------
    # 1. IMUTABILIDADE ESTRITA DE ENVASECILINDRO
    # -------------------------------------------------------------------------

    def test_envase_cilindro_bloqueia_edicao_em_instancia(self):
        """Garante que instâncias existentes de EnvaseCilindro não podem ser alteradas via .save()."""
        envase = EnvaseCilindro.objects.create(
            cilindro=self.cilindro,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.user,
            observacoes="Envase inicial"
        )

        with self.assertRaises(ValidationError) as ctx:
            envase.pressao_final_bar = 210
            envase.save()

        self.assertIn("Histórico de envase imutável", str(ctx.exception))

    def test_envase_cilindro_bloqueia_delete_em_instancia(self):
        """Garante que instâncias de EnvaseCilindro não podem ser deletadas via .delete()."""
        envase = EnvaseCilindro.objects.create(
            cilindro=self.cilindro,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.user
        )

        with self.assertRaises(ValidationError) as ctx:
            envase.delete()

        self.assertIn("Histórico de envase imutável", str(ctx.exception))

    def test_envase_cilindro_bloqueia_update_e_delete_em_lote_no_queryset(self):
        """Garante que o QuerySet e Manager de EnvaseCilindro bloqueiam .update() e .delete() em lote."""
        envase = EnvaseCilindro.objects.create(
            cilindro=self.cilindro,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.user
        )

        # 1. TenantManager
        with self.assertRaises((ValidationError, PermissionError)):
            EnvaseCilindro.objects.filter(id=envase.id).update(pressao_final_bar=215)

        with self.assertRaises((ValidationError, PermissionError)):
            EnvaseCilindro.objects.filter(id=envase.id).delete()

        # 2. UnscopedManager
        with self.assertRaises((ValidationError, PermissionError)):
            EnvaseCilindro.unscoped.filter(id=envase.id).update(pressao_final_bar=215)

        with self.assertRaises((ValidationError, PermissionError)):
            EnvaseCilindro.unscoped.filter(id=envase.id).delete()

    # -------------------------------------------------------------------------
    # 2. VÍNCULO DE ENVASE E DOCUMENTO_FISCAL_REF NO LEDGER
    # -------------------------------------------------------------------------

    def test_registrar_envase_vincula_envase_cilindro_no_ledger(self):
        """Garante que registrar_envase_cilindro vincula o EnvaseCilindro na MovimentacaoCilindro."""
        cil, envase, mov = registrar_envase_cilindro(
            cilindro_id=self.cilindro.id,
            lote_id=self.lote.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4(),
            observacoes="Envase teste"
        )

        self.assertIsNotNone(mov.envase_cilindro)
        self.assertEqual(mov.envase_cilindro, envase)
        self.assertEqual(mov.lote_envase, self.lote.codigo_lote)
        self.assertEqual(cil.status, 'CHEIO_DISPONIVEL')
        self.assertEqual(cil.envase_atual, envase)

    def test_registrar_entrega_vincula_envase_e_documento_fiscal_ref(self):
        """Garante que registrar_entrega_cilindro propaga envase_cilindro e aceita documento_fiscal_ref."""
        _, envase, _ = registrar_envase_cilindro(
            cilindro_id=self.cilindro.id,
            lote_id=self.lote.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=timezone.now() - timedelta(days=2),
            client_uuid=uuid.uuid4()
        )

        nfe_chave = "NFE-53261011222333000144550010000001001234567890"
        cil, mov = registrar_entrega_cilindro(
            cilindro_id=self.cilindro.id,
            cliente=self.cliente,
            documento_fiscal_ref=nfe_chave,
            usuario=self.user,
            ocorrido_em=timezone.now() - timedelta(days=1),
            client_uuid=uuid.uuid4()
        )

        self.assertEqual(mov.envase_cilindro, envase)
        self.assertEqual(mov.documento_fiscal_ref, nfe_chave)
        self.assertEqual(cil.status, 'EM_POSSE_CLIENTE')
        self.assertEqual(cil.cliente_posse_atual, self.cliente)

    def test_bloqueio_entrega_cilindro_cheio_sem_envase_ativo_no_service(self):
        """Garante que registrar_entrega_cilindro rejeita entrega se o cilindro não tiver envase ativo."""
        self.cilindro.status = 'CHEIO_DISPONIVEL'
        self.cilindro.envase_atual = None
        self.cilindro.save(update_fields=['status', 'envase_atual'])

        with self.assertRaises(ValidationError) as ctx:
            registrar_entrega_cilindro(
                cilindro_id=self.cilindro.id,
                cliente=self.cliente,
                usuario=self.user,
                ocorrido_em=timezone.now(),
                client_uuid=uuid.uuid4()
            )

        self.assertIn("não possui registro de envase ativo associado para entrega", str(ctx.exception))

    def test_alocar_cilindro_rota_vincula_envase_corretamente(self):
        """Garante que alocar_cilindro_rota transiciona para RESERVADO_ROTA vinculando o envase."""
        _, envase, _ = registrar_envase_cilindro(
            cilindro_id=self.cilindro.id,
            lote_id=self.lote.id,
            pressao_bar=200,
            usuario=self.user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4()
        )

        cil, mov = alocar_cilindro_rota(
            cilindro_id=self.cilindro.id,
            entrega=None,
            usuario=self.user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4(),
            observacao="Alocação romaneio"
        )

        self.assertEqual(cil.status, 'RESERVADO_ROTA')
        self.assertEqual(mov.tipo, 'SAIDA_ROTA')
        self.assertEqual(mov.envase_cilindro, envase)

    # -------------------------------------------------------------------------
    # 3. CHECKCONSTRAINT CONDICIONAL NO BANCO DE DADOS
    # -------------------------------------------------------------------------

    def test_check_constraint_rejeita_movimentacao_cheia_sem_envase(self):
        """Garante que a CheckConstraint do banco impede inserção de ENTREGA_CLIENTE sem envase_cilindro."""
        with self.assertRaises(IntegrityError):
            MovimentacaoCilindro.objects.create(
                cilindro=self.cilindro,
                tipo='ENTREGA_CLIENTE',
                status_anterior='CHEIO_DISPONIVEL',
                status_novo='EM_POSSE_CLIENTE',
                cliente=self.cliente,
                envase_cilindro=None,  # Ilegal para movimentação de cilindro cheio
                is_legado=False,
                ocorrido_em=timezone.now(),
                registrado_por=self.user,
                client_uuid=uuid.uuid4()
            )

    def test_check_constraint_rejeita_movimentacao_vazia_com_envase(self):
        """Garante que a CheckConstraint do banco impede inserção de RECOLHA_CLIENTE com envase_cilindro."""
        envase = EnvaseCilindro.objects.create(
            cilindro=self.cilindro,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.user
        )

        with self.assertRaises(IntegrityError):
            MovimentacaoCilindro.objects.create(
                cilindro=self.cilindro,
                tipo='RECOLHA_CLIENTE',
                status_anterior='EM_POSSE_CLIENTE',
                status_novo='VAZIO_TRIAGEM',
                cliente=self.cliente,
                envase_cilindro=envase,  # Ilegal para movimentação de casco vazio
                is_legado=False,
                ocorrido_em=timezone.now(),
                registrado_por=self.user,
                client_uuid=uuid.uuid4()
            )

    def test_check_constraint_permite_registro_legado_sem_envase(self):
        """Garante que registros marcados como is_legado=True são protegidos pela constraint."""
        mov_legada = MovimentacaoCilindro.objects.create(
            cilindro=self.cilindro,
            tipo='ENTREGA_CLIENTE',
            status_anterior='CHEIO_DISPONIVEL',
            status_novo='EM_POSSE_CLIENTE',
            cliente=self.cliente,
            envase_cilindro=None,
            is_legado=True,  # Isento de violação
            ocorrido_em=timezone.now() - timedelta(days=200),
            registrado_por=self.user,
            client_uuid=uuid.uuid4()
        )
        self.assertIsNotNone(mov_legada.id)
        self.assertTrue(mov_legada.is_legado)

    def test_tabela_auxiliar_vinculo_legado_inferido(self):
        """Garante que inferências sobre dados legados são armazenadas na tabela auxiliar sem tocar o ledger."""
        mov_legada = MovimentacaoCilindro.objects.create(
            cilindro=self.cilindro,
            tipo='ENTREGA_CLIENTE',
            status_anterior='CHEIO_DISPONIVEL',
            status_novo='EM_POSSE_CLIENTE',
            cliente=self.cliente,
            envase_cilindro=None,
            is_legado=True,
            ocorrido_em=timezone.now() - timedelta(days=200),
            registrado_por=self.user,
            client_uuid=uuid.uuid4()
        )

        envase = EnvaseCilindro.objects.create(
            cilindro=self.cilindro,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now() - timedelta(days=205),
            operador=self.user
        )

        vinculo = VinculoLegadoInferido.objects.create(
            movimentacao=mov_legada,
            envase_cilindro=envase,
            justificativa="Inferido por proximidade cronológica de lote da Sprint 2"
        )

        self.assertEqual(vinculo.movimentacao, mov_legada)
        self.assertEqual(vinculo.envase_cilindro, envase)
        # O ledger oficial permanece intacto com envase_cilindro nulo
        mov_legada.refresh_from_db()
        self.assertIsNone(mov_legada.envase_cilindro)

    # -------------------------------------------------------------------------
    # 4. MÁQUINA DE ESTADOS FINITA (FSM) E ESTADO TERMINAL
    # -------------------------------------------------------------------------

    def test_fsm_transicao_ilegal_rejeitada(self):
        """Garante que transições não permitidas pela matriz da FSM lançam ValidationError."""
        # VAZIO_TRIAGEM -> EM_POSSE_CLIENTE não é permitido diretamente
        with self.assertRaises(ValidationError) as ctx:
            validar_transicao_status_cilindro(self.cilindro, 'EM_POSSE_CLIENTE')

        self.assertIn("Transição Ilegal de Estado", str(ctx.exception))

    def test_fsm_estado_baixado_e_estritamente_terminal(self):
        """Garante que uma vez que o cilindro atinge o status BAIXADO, nenhuma reativação é permitida."""
        cil, mov = baixar_cilindro(
            cilindro_id=self.cilindro.id,
            motivo="Condenação por trinca mecânica",
            usuario=self.user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4()
        )

        self.assertEqual(cil.status, 'BAIXADO')
        self.assertEqual(mov.tipo, 'BAIXA')
        self.assertIsNone(mov.envase_cilindro)

        # Tentativa de voltar para VAZIO_TRIAGEM
        with self.assertRaises(ValidationError) as ctx1:
            validar_transicao_status_cilindro(cil, 'VAZIO_TRIAGEM')
        self.assertIn("está BAIXADO/CONDENADO (estado terminal)", str(ctx1.exception))

        # Tentativa de envasar cilindro condenado
        with self.assertRaises(ValidationError) as ctx2:
            registrar_envase_cilindro(
                cilindro_id=cil.id,
                lote_id=self.lote.id,
                pressao_bar=200,
                usuario=self.user,
                ocorrido_em=timezone.now(),
                client_uuid=uuid.uuid4()
            )
        self.assertIn("está BAIXADO/CONDENADO (estado terminal)", str(ctx2.exception))
