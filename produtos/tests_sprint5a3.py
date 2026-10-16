import uuid
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership, ResponsavelTecnico, PerfilRegulatorioTenant
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import Cliente
from produtos.models import (
    GasQuimico,
    ModeloCilindro,
    Cilindro,
    LoteEnvase,
    EnvaseCilindro,
    InspecaoPreEnvase,
    RecebimentoCilindroCheio,
    ReclassificacaoCilindro,
    MovimentacaoCilindro,
)
from produtos.services import (
    registrar_envase_cilindro,
    receber_cilindro_cheio_fornecedor,
    reclassificar_cilindro_gas,
    registrar_entrega_cilindro,
    registrar_recolha_cilindro,
)

User = get_user_model()


class Sprint5A3UnifiedRBACTests(TestCase):
    """
    Testes de Unificação do RBAC em Membership.papel (Sprint 5A.3):
    - Papéis: ADMIN, GERENTE, RESPONSAVEL_TECNICO, OPERADOR_PATIO, MOTORISTA, VENDEDOR.
    - Testes provando que apenas OPERADOR_PATIO, RESPONSAVEL_TECNICO e ADMIN operam a rampa de envase e triagem.
    - Testes provando que MOTORISTA e VENDEDOR são bloqueados na rampa.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Gases do Brasil S.A.',
            nome_fantasia='Gases Brasil'
        )
        self.token = set_current_tenant(self.tenant)

        # Usuários e Memberships por papel
        self.user_admin = User.objects.create_user(username='admin_user', password='pass_user_123')
        Membership.objects.create(user=self.user_admin, tenant=self.tenant, papel='ADMIN')

        self.user_rt = User.objects.create_user(username='rt_user', password='pass_user_123')
        Membership.objects.create(user=self.user_rt, tenant=self.tenant, papel='RESPONSAVEL_TECNICO')
        self.rt_obj = ResponsavelTecnico.objects.create(
            user=self.user_rt,
            tenant=self.tenant,
            nome_completo='Dr. Alberto Químico',
            conselho_classe='CRQ',
            numero_registro='123456',
            uf_conselho='SP',
            vigencia_inicio=timezone.now().date() - timedelta(days=30),
            ativo=True
        )

        self.user_operador = User.objects.create_user(username='operador_user', password='pass_user_123')
        Membership.objects.create(user=self.user_operador, tenant=self.tenant, papel='OPERADOR_PATIO')

        self.user_motorista = User.objects.create_user(username='motorista_user', password='pass_user_123')
        Membership.objects.create(user=self.user_motorista, tenant=self.tenant, papel='MOTORISTA')

        self.user_vendedor = User.objects.create_user(username='vendedor_user', password='pass_user_123')
        Membership.objects.create(user=self.user_vendedor, tenant=self.tenant, papel='VENDEDOR')

        self.gas_o2 = GasQuimico.objects.create(
            sigla='O2-IND', nome='Oxigênio Industrial', categoria='INDUSTRIAL',
            numero_onu='1072', classe_risco='2.2', cor_padrao_abnt='Preto'
        )
        self.modelo = ModeloCilindro.objects.create(
            descricao='T-50L', volume_hidraulico_litros=Decimal('50.0'),
            pressao_servico_bar=200, tara_nominal_kg=Decimal('48.5')
        )
        self.cilindro = Cilindro.objects.create(
            tenant=self.tenant, codigo_qr='CIL-RBAC-01', numero_serie_ogiva='OG-RBAC-01',
            fabricante='Cilbras', ano_fabricacao=2021, modelo=self.modelo,
            gas_dedicado=self.gas_o2, tara_real_kg=Decimal('48.6'),
            data_ultimo_reteste=timezone.now().date() - timedelta(days=100),
            data_proximo_reteste=timezone.now().date() + timedelta(days=1500),
            status='VAZIO_TRIAGEM'
        )
        self.lote = LoteEnvase.objects.create(
            tenant=self.tenant, gas=self.gas_o2, codigo_lote='LOTE-RBAC-01',
            data_envase=timezone.now().date(), data_validade=timezone.now().date() + timedelta(days=365),
            pureza_percentual=Decimal('99.5'), responsavel_tecnico='Dr. Alberto Químico'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_operador_patio_pode_operar_rampa_envase(self):
        client = APIClient()
        client.force_authenticate(user=self.user_operador)
        res = client.post('/produtos/api/envases/registrar/', {
            'cilindro_id': self.cilindro.id,
            'lote_id': self.lote.id,
            'pressao_final_bar': 200,
            'valvula_integra': True,
            'pressao_residual_positiva': True,
            'pintura_cor_padrao_ok': True,
            'rotulo_identificacao_ok': True
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_responsavel_tecnico_pode_operar_rampa_envase(self):
        client = APIClient()
        client.force_authenticate(user=self.user_rt)
        res = client.post('/produtos/api/envases/registrar/', {
            'cilindro_id': self.cilindro.id,
            'lote_id': self.lote.id,
            'pressao_final_bar': 200,
            'valvula_integra': True,
            'pressao_residual_positiva': True,
            'pintura_cor_padrao_ok': True,
            'rotulo_identificacao_ok': True
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_admin_pode_operar_rampa_envase(self):
        client = APIClient()
        client.force_authenticate(user=self.user_admin)
        res = client.post('/produtos/api/envases/registrar/', {
            'cilindro_id': self.cilindro.id,
            'lote_id': self.lote.id,
            'pressao_final_bar': 200,
            'valvula_integra': True,
            'pressao_residual_positiva': True,
            'pintura_cor_padrao_ok': True,
            'rotulo_identificacao_ok': True
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_motorista_bloqueado_ao_operar_rampa(self):
        client = APIClient()
        client.force_authenticate(user=self.user_motorista)
        res = client.post('/produtos/api/envases/registrar/', {
            'cilindro_id': self.cilindro.id,
            'lote_id': self.lote.id,
            'pressao_final_bar': 200
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_vendedor_bloqueado_ao_operar_rampa(self):
        client = APIClient()
        client.force_authenticate(user=self.user_vendedor)
        res = client.post('/produtos/api/envases/registrar/', {
            'cilindro_id': self.cilindro.id,
            'lote_id': self.lote.id,
            'pressao_final_bar': 200
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class Sprint5A3PreEnvaseChecklistTests(TestCase):
    """
    Testes do Checklist de Inspeção Pré-Envase (IN 129/2022) e Serviço de Envase:
    - Registro do checklist imutável InspecaoPreEnvase vinculado ao cilindro e operador.
    - Reprovação física (qualquer item Falso) -> cilindro movido para EM_RETESTE, bloqueio_sanitario=True e envase abortado.
    - Bloqueio se reteste hidrostático vencido.
    - Bloqueio se bloqueio_sanitario=True.
    - Snapshot de RT em LoteEnvase.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='22.333.444/0001-55',
            razao_social='Oxigênio & Nitrogênio Paulista Ltda',
            nome_fantasia='OxiPaulista'
        )
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(username='operador.patio', password='pass_user_123')
        Membership.objects.create(user=self.user, tenant=self.tenant, papel='OPERADOR_PATIO')

        self.user_rt = User.objects.create_user(username='rt.farmaceutica', password='pass_user_123')
        Membership.objects.create(user=self.user_rt, tenant=self.tenant, papel='RESPONSAVEL_TECNICO')
        self.rt_ativo = ResponsavelTecnico.objects.create(
            user=self.user_rt,
            tenant=self.tenant,
            nome_completo='Dra. Camila Farmacêutica',
            conselho_classe='CRF',
            numero_registro='98765-SP',
            uf_conselho='SP',
            vigencia_inicio=timezone.now().date() - timedelta(days=60),
            ativo=True
        )

        self.gas_med = GasQuimico.objects.create(
            sigla='O2-MED', nome='Oxigênio Medicinal', categoria='MEDICINAL',
            numero_onu='1072', classe_risco='2.2', cor_padrao_abnt='Verde Emblema',
            exige_lote_anvisa=True
        )
        self.modelo = ModeloCilindro.objects.create(
            descricao='Cilindro 40L', volume_hidraulico_litros=Decimal('40.0'),
            pressao_servico_bar=150, tara_nominal_kg=Decimal('42.0')
        )
        self.cilindro = Cilindro.objects.create(
            tenant=self.tenant, codigo_qr='CIL-PRE-01', numero_serie_ogiva='OG-PRE-01',
            fabricante='Mat', ano_fabricacao=2022, modelo=self.modelo,
            gas_dedicado=self.gas_med, tara_real_kg=Decimal('42.1'),
            data_ultimo_reteste=timezone.now().date() - timedelta(days=200),
            data_proximo_reteste=timezone.now().date() + timedelta(days=1000),
            status='VAZIO_TRIAGEM'
        )
        self.lote = LoteEnvase.objects.create(
            tenant=self.tenant, gas=self.gas_med, codigo_lote='LOTE-MED-01',
            data_envase=timezone.now().date(), data_validade=timezone.now().date() + timedelta(days=365),
            pureza_percentual=Decimal('99.6'), responsavel_tecnico='Dra. Camila Farmacêutica'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_envase_com_checklist_aprovado_sucesso(self):
        res = registrar_envase_cilindro(
            cilindro=self.cilindro,
            lote=self.lote,
            operador=self.user,
            pressao_final_bar=150,
            valvula_integra=True,
            pressao_residual_positiva=True,
            pintura_cor_padrao_ok=True,
            rotulo_identificacao_ok=True,
            observacoes_inspecao="Inspeção 100% OK",
            observacoes_envase="Rampa 1 Ok"
        )
        envase = res[1] if isinstance(res, tuple) else res
        self.assertIsNotNone(envase)
        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.status, 'CHEIO_DISPONIVEL')
        self.assertFalse(self.cilindro.bloqueio_sanitario)
        self.assertEqual(self.cilindro.envase_atual, envase)

        # Valida criação do registro de inspeção
        inspecao = InspecaoPreEnvase.objects.filter(cilindro=self.cilindro).first()
        self.assertIsNotNone(inspecao)
        self.assertTrue(inspecao.aprovado)
        self.assertEqual(inspecao.operador, self.user)

    def test_envase_com_checklist_reprovado_bloqueia_e_move_para_manutencao(self):
        # Reprova por válvula danificada
        with self.assertRaises(ValidationError) as ctx:
            registrar_envase_cilindro(
                cilindro=self.cilindro,
                lote=self.lote,
                operador=self.user,
                pressao_final_bar=150,
                valvula_integra=False,
                pressao_residual_positiva=True,
                pintura_cor_padrao_ok=True,
                rotulo_identificacao_ok=True,
                observacoes_inspecao="Válvula com rosca espanada"
            )
        self.assertIn("reprovado na inspeção física pré-envase", str(ctx.exception).lower())

        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.status, 'EM_RETESTE')
        self.assertTrue(self.cilindro.bloqueio_sanitario)
        self.assertIn("Reprovado na inspeção física pré-envase", self.cilindro.motivo_bloqueio_sanitario)
        self.assertIsNone(self.cilindro.envase_atual)

        # Inspeção gravada como aprovado=False
        inspecao = InspecaoPreEnvase.objects.filter(cilindro=self.cilindro).first()
        self.assertIsNotNone(inspecao)
        self.assertFalse(inspecao.aprovado)

    def test_inspecao_pre_envase_imutabilidade_estrita(self):
        inspecao = InspecaoPreEnvase.objects.create(
            tenant=self.tenant,
            cilindro=self.cilindro,
            operador=self.user,
            valvula_integra=True,
            pressao_residual_positiva=True,
            pintura_cor_padrao_ok=True,
            rotulo_identificacao_ok=True,
            aprovado=True
        )
        # Bloqueio de edição direta via save()
        inspecao.observacoes = "Tentativa de alteração"
        with self.assertRaises(ValidationError):
            inspecao.save()

        # Bloqueio de delete()
        with self.assertRaises(ValidationError):
            inspecao.delete()

        # Bloqueio de update() em lote
        with self.assertRaises(ValidationError):
            InspecaoPreEnvase.objects.filter(id=inspecao.id).update(aprovado=False)

    def test_bloqueio_envase_reteste_hidrostatico_vencido(self):
        self.cilindro.data_proximo_reteste = timezone.now().date() - timedelta(days=1)
        self.cilindro.save()

        with self.assertRaises(ValidationError) as ctx:
            registrar_envase_cilindro(
                cilindro=self.cilindro,
                lote=self.lote,
                operador=self.user,
                pressao_final_bar=150,
                valvula_integra=True,
                pressao_residual_positiva=True,
                pintura_cor_padrao_ok=True,
                rotulo_identificacao_ok=True
            )
        self.assertIn("teste hidrostático venceu", str(ctx.exception).lower())

    def test_bloqueio_envase_cilindro_com_bloqueio_sanitario(self):
        self.cilindro.bloqueio_sanitario = True
        self.cilindro.motivo_bloqueio_sanitario = "Contaminação detectada anteriormente"
        self.cilindro.save()

        with self.assertRaises(ValidationError) as ctx:
            registrar_envase_cilindro(
                cilindro=self.cilindro,
                lote=self.lote,
                operador=self.user,
                pressao_final_bar=150,
                valvula_integra=True,
                pressao_residual_positiva=True,
                pintura_cor_padrao_ok=True,
                rotulo_identificacao_ok=True
            )
        self.assertIn("bloqueio sanitário ativo", str(ctx.exception))

    def test_lote_envase_snapshot_responsavel_tecnico(self):
        # Cria lote vinculando o RT e valida snapshots automáticos
        lote_com_rt = LoteEnvase.objects.create(
            tenant=self.tenant,
            gas=self.gas_med,
            codigo_lote='LOTE-RT-SNAP-01',
            data_envase=timezone.now().date(),
            data_validade=timezone.now().date() + timedelta(days=365),
            pureza_percentual=Decimal('99.8'),
            responsavel_tecnico_fk=self.rt_ativo
        )
        self.assertEqual(lote_com_rt.rt_nome_snapshot, 'Dra. Camila Farmacêutica')
        self.assertEqual(lote_com_rt.rt_conselho_snapshot, 'CRF')
        self.assertEqual(lote_com_rt.rt_registro_snapshot, '98765-SP')


class Sprint5A3RecebimentoCilindroCheioTests(TestCase):
    """
    Testes de Distribuidoras que Não Envasam (RecebimentoCilindroCheio - RDC 887/2024):
    - Criação de RecebimentoCilindroCheio com auditoria e snapshot do RT.
    - Atualização do cilindro para CHEIO_DISPONIVEL com recebimento_externo_atual.
    - Imutabilidade de RecebimentoCilindroCheio (save e delete bloqueados).
    - Entrega ao cliente (registrar_entrega_cilindro) habilita cilindro cheio vindo de recebimento externo sem exigir EnvaseCilindro próprio.
    - Ledger registra RECEBIMENTO_FORNECEDOR e ENTREGA_CLIENTE mantendo coerência do CheckConstraint.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='33.444.555/0001-66',
            razao_social='Distribuidora Alfa de Gases Ltda',
            nome_fantasia='Alfa Distribuidora'
        )
        self.token = set_current_tenant(self.tenant)

        # Perfil como DISTRIBUIDORA
        PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant,
            modo_operacao='DISTRIBUIDORA',
            afe_numero='AFE-DIST-1234',
            licenca_sanitaria_numero='VISA-DIST-5678',
            licenca_sanitaria_validade=timezone.now().date() + timedelta(days=365)
        )

        self.user_rt = User.objects.create_user(username='rt.distribuidora', password='pass_user_123')
        Membership.objects.create(user=self.user_rt, tenant=self.tenant, papel='RESPONSAVEL_TECNICO')
        self.rt_ativo = ResponsavelTecnico.objects.create(
            user=self.user_rt,
            tenant=self.tenant,
            nome_completo='Dr. Marcelo RT',
            conselho_classe='CRQ',
            numero_registro='554433-SP',
            uf_conselho='SP',
            vigencia_inicio=timezone.now().date() - timedelta(days=100),
            ativo=True
        )

        self.user_operador = User.objects.create_user(username='operador.distribuidora', password='pass_user_123')
        Membership.objects.create(user=self.user_operador, tenant=self.tenant, papel='OPERADOR_PATIO')

        self.gas = GasQuimico.objects.create(
            sigla='AR-MED', nome='Ar Comprimido Medicinal', categoria='MEDICINAL',
            numero_onu='1002', classe_risco='2.2', cor_padrao_abnt='Amarelo e Verde',
            exige_lote_anvisa=True
        )
        self.modelo = ModeloCilindro.objects.create(
            descricao='Cilindro 50L', volume_hidraulico_litros=Decimal('50.0'),
            pressao_servico_bar=200, tara_nominal_kg=Decimal('50.0')
        )
        self.cilindro = Cilindro.objects.create(
            tenant=self.tenant, codigo_qr='CIL-DIST-01', numero_serie_ogiva='OG-DIST-01',
            fabricante='Cilindros BR', ano_fabricacao=2023, modelo=self.modelo,
            gas_dedicado=self.gas, tara_real_kg=Decimal('50.2'),
            data_ultimo_reteste=timezone.now().date() - timedelta(days=50),
            data_proximo_reteste=timezone.now().date() + timedelta(days=1500),
            status='VAZIO_TRIAGEM'
        )
        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome='Hospital São Camilo',
            cnpj='88.999.000/0001-11',
            telefone='11999998888',
            endereco='Av. Paulista 1000'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_recebimento_cilindro_cheio_fornecedor_sucesso(self):
        res = receber_cilindro_cheio_fornecedor(
            cilindro=self.cilindro,
            fornecedor_nome='White Martins Gases Industriais Ltda',
            fornecedor_cnpj='35.820.448/0001-30',
            nota_fiscal='NF-e 001294',
            lote_fornecedor='LOTE-WM-2026-X',
            data_envase_origem=timezone.now().date() - timedelta(days=5),
            data_validade=timezone.now().date() + timedelta(days=360),
            responsavel_recebimento=self.user_operador,
            pressao_recebimento_bar=195,
            responsavel_tecnico=self.rt_ativo,
            observacoes="Cilindro lacrado, laudo fornecedor conferido"
        )
        recebimento = res[1] if isinstance(res, tuple) else res
        self.assertIsNotNone(recebimento)
        self.cilindro.refresh_from_db()

        self.assertEqual(self.cilindro.status, 'CHEIO_DISPONIVEL')
        self.assertEqual(self.cilindro.recebimento_externo_atual, recebimento)
        self.assertIsNone(self.cilindro.envase_atual)
        self.assertEqual(recebimento.rt_nome_snapshot, 'Dr. Marcelo RT')
        self.assertIn('CRQ', recebimento.rt_registro_snapshot)
        self.assertIn('554433-SP', recebimento.rt_registro_snapshot)

        # Valida Ledger
        mov = MovimentacaoCilindro.objects.filter(
            cilindro=self.cilindro, tipo='RECEBIMENTO_FORNECEDOR'
        ).first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.recebimento_externo, recebimento)
        self.assertIsNone(mov.envase_cilindro)

    def test_recebimento_imutabilidade_estrita(self):
        res = receber_cilindro_cheio_fornecedor(
            cilindro=self.cilindro,
            fornecedor_nome='Fornecedor X',
            fornecedor_cnpj='11.111.111/0001-11',
            nota_fiscal='NF-100',
            lote_fornecedor='LOTE-X',
            data_envase_origem=timezone.now().date(),
            data_validade=timezone.now().date() + timedelta(days=180),
            responsavel_recebimento=self.user_operador,
            responsavel_tecnico=self.rt_ativo
        )
        recebimento = res[1] if isinstance(res, tuple) else res
        # Edição direta bloqueada
        recebimento.observacoes = "Alterando registro"
        with self.assertRaises(ValidationError):
            recebimento.save()

        # Delete bloqueado
        with self.assertRaises(ValidationError):
            recebimento.delete()

        # Queryset update bloqueado
        with self.assertRaises(ValidationError):
            RecebimentoCilindroCheio.objects.filter(id=recebimento.id).update(fornecedor_nome='Novo')

    def test_entrega_e_recolha_com_cilindro_recebido_externamente(self):
        res_rec = receber_cilindro_cheio_fornecedor(
            cilindro=self.cilindro,
            fornecedor_nome='White Martins',
            fornecedor_cnpj='35.820.448/0001-30',
            nota_fiscal='NF-999',
            lote_fornecedor='LOTE-WM-1',
            data_envase_origem=timezone.now().date(),
            data_validade=timezone.now().date() + timedelta(days=365),
            responsavel_recebimento=self.user_operador,
            responsavel_tecnico=self.rt_ativo
        )
        recebimento = res_rec[1] if isinstance(res_rec, tuple) else res_rec

        # Entrega ao cliente Hospital São Camilo
        res_ent = registrar_entrega_cilindro(
            cilindro=self.cilindro,
            cliente=self.cliente,
            responsavel=self.user_operador,
            documento_fiscal_ref='NFE-SAIDA-456'
        )
        mov_entrega = res_ent[1] if isinstance(res_ent, tuple) else res_ent
        self.assertIsNotNone(mov_entrega)
        self.assertEqual(mov_entrega.tipo, 'ENTREGA_CLIENTE')
        self.assertEqual(mov_entrega.recebimento_externo, recebimento)
        self.assertIsNone(mov_entrega.envase_cilindro)

        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.status, 'EM_POSSE_CLIENTE')
        self.assertEqual(self.cilindro.cliente_posse_atual, self.cliente)

        # Recolha do cilindro vazio
        res_rec_vazio = registrar_recolha_cilindro(
            cilindro=self.cilindro,
            cliente=self.cliente,
            responsavel=self.user_operador
        )
        mov_recolha = res_rec_vazio[1] if isinstance(res_rec_vazio, tuple) else res_rec_vazio
        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.status, 'VAZIO_TRIAGEM')
        self.assertIsNone(self.cilindro.recebimento_externo_atual)
        self.assertIsNone(self.cilindro.cliente_posse_atual)


class Sprint5A3ReclassificacaoEFiltrosCilindroTests(TestCase):
    """
    Testes de CilindroViewSet (Filtros), Reclassificação Auditada de Gás e Download Seguro de Laudos:
    - Filtros de CilindroViewSet por qr_code, status, reteste_vencido, bloqueio_sanitario e gas.
    - Reclassificação de Industrial para Medicinal com checagens obrigatórias e permissão de RT.
    - Tentativa de reclassificação para gás medicinal por usuário comum é bloqueada com 403 / PermissionError.
    - Download seguro de laudo PDF restrito por autenticação e isolamento multi-tenant.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='44.555.666/0001-77',
            razao_social='Gases Industriais & Medicinais Brasil Ltda',
            nome_fantasia='Gases Brasil Matriz'
        )
        self.token = set_current_tenant(self.tenant)

        self.user_rt = User.objects.create_user(username='farmaceutico.chefe', password='pass_user_123')
        Membership.objects.create(user=self.user_rt, tenant=self.tenant, papel='RESPONSAVEL_TECNICO')
        self.rt_ativo = ResponsavelTecnico.objects.create(
            user=self.user_rt,
            tenant=self.tenant,
            nome_completo='Dra. Beatriz RT',
            conselho_classe='CRF',
            numero_registro='112233-SP',
            uf_conselho='SP',
            vigencia_inicio=timezone.now().date() - timedelta(days=100),
            ativo=True
        )

        self.user_operador = User.objects.create_user(username='operador.rampa', password='pass_user_123')
        Membership.objects.create(user=self.user_operador, tenant=self.tenant, papel='OPERADOR_PATIO')

        self.gas_ind = GasQuimico.objects.create(
            sigla='N2-IND', nome='Nitrogênio Industrial', categoria='INDUSTRIAL',
            numero_onu='1066', classe_risco='2.2', cor_padrao_abnt='Cinza Médio'
        )
        self.gas_med = GasQuimico.objects.create(
            sigla='N2-MED', nome='Nitrogênio Medicinal', categoria='MEDICINAL',
            numero_onu='1066', classe_risco='2.2', cor_padrao_abnt='Branco',
            exige_lote_anvisa=True
        )
        self.modelo = ModeloCilindro.objects.create(
            descricao='Cilindro 50L Aço', volume_hidraulico_litros=Decimal('50.0'),
            pressao_servico_bar=200, tara_nominal_kg=Decimal('55.0')
        )
        self.cilindro = Cilindro.objects.create(
            tenant=self.tenant, codigo_qr='CIL-RECLASS-01', numero_serie_ogiva='OG-RECLASS-01',
            fabricante='Cilindros BR', ano_fabricacao=2020, modelo=self.modelo,
            gas_dedicado=self.gas_ind, tara_real_kg=Decimal('55.1'),
            data_ultimo_reteste=timezone.now().date() - timedelta(days=300),
            data_proximo_reteste=timezone.now().date() + timedelta(days=1000),
            status='VAZIO_TRIAGEM'
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_filtros_cilindro_viewset(self):
        # Cilindro 2: com reteste vencido e bloqueio sanitário
        cilindro_vencido = Cilindro.objects.create(
            tenant=self.tenant, codigo_qr='CIL-RETESTE-VENCIDO', numero_serie_ogiva='OG-VENC-01',
            fabricante='Cilindros BR', ano_fabricacao=2015, modelo=self.modelo,
            gas_dedicado=self.gas_ind, tara_real_kg=Decimal('55.1'),
            data_ultimo_reteste=timezone.now().date() - timedelta(days=2000),
            data_proximo_reteste=timezone.now().date() - timedelta(days=50),
            bloqueio_sanitario=True,
            status='EM_RETESTE'
        )

        client = APIClient()
        client.force_authenticate(user=self.user_rt)

        def _get_items(response):
            return response.data['results'] if isinstance(response.data, dict) and 'results' in response.data else response.data

        # Filtro por qr_code
        res = client.get('/produtos/api/cilindros/?qr_code=CIL-RECLASS-01')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = _get_items(res)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['codigo_qr'], 'CIL-RECLASS-01')

        # Filtro por bloqueio_sanitario=true
        res_bloq = client.get('/produtos/api/cilindros/?bloqueio_sanitario=true')
        self.assertEqual(res_bloq.status_code, status.HTTP_200_OK)
        items_bloq = _get_items(res_bloq)
        self.assertEqual(len(items_bloq), 1)
        self.assertEqual(items_bloq[0]['codigo_qr'], 'CIL-RETESTE-VENCIDO')

        # Filtro por reteste_vencido=true
        res_ret = client.get('/produtos/api/cilindros/?reteste_vencido=true')
        self.assertEqual(res_ret.status_code, status.HTTP_200_OK)
        items_ret = _get_items(res_ret)
        self.assertEqual(len(items_ret), 1)
        self.assertEqual(items_ret[0]['codigo_qr'], 'CIL-RETESTE-VENCIDO')

        # Filtro por gas
        res_gas = client.get(f'/produtos/api/cilindros/?gas={self.gas_ind.sigla}')
        self.assertEqual(res_gas.status_code, status.HTTP_200_OK)
        items_gas = _get_items(res_gas)
        self.assertEqual(len(items_gas), 2)

    def test_reclassificacao_para_medicinal_por_rt_sucesso(self):
        client = APIClient()
        client.force_authenticate(user=self.user_rt)

        res = client.post(f'/produtos/api/cilindros/{self.cilindro.id}/reclassificar/', {
            'novo_gas_id': self.gas_med.id,
            'descontaminacao_purga_executada': True,
            'troca_valvula_executada': True,
            'adequacao_pintura_executada': True,
            'nova_cor_padrao': 'Branco',
            'observacoes': 'Reclassificação industrial -> medicinal aprovada pelo RT'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.cilindro.refresh_from_db()
        self.assertEqual(self.cilindro.gas_dedicado, self.gas_med)

        reclass = ReclassificacaoCilindro.objects.filter(cilindro=self.cilindro).first()
        self.assertIsNotNone(reclass)
        self.assertEqual(reclass.gas_origem, self.gas_ind)
        self.assertEqual(reclass.gas_destino, self.gas_med)
        self.assertEqual(reclass.homologado_por_rt, self.rt_ativo)

    def test_reclassificacao_para_medicinal_por_operador_comum_bloqueada(self):
        client = APIClient()
        client.force_authenticate(user=self.user_operador)

        res = client.post(f'/produtos/api/cilindros/{self.cilindro.id}/reclassificar/', {
            'novo_gas_id': self.gas_med.id,
            'descontaminacao_purga_executada': True,
            'troca_valvula_executada': True,
            'adequacao_pintura_executada': True
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("exclusiva de um Responsável Técnico", res.data.get('error', ''))

    def test_reclassificacao_bloqueada_sem_descontaminacao(self):
        client = APIClient()
        client.force_authenticate(user=self.user_rt)

        res = client.post(f'/produtos/api/cilindros/{self.cilindro.id}/reclassificar/', {
            'novo_gas_id': self.gas_med.id,
            'descontaminacao_purga_executada': False,  # NÃO executada
            'troca_valvula_executada': True,
            'adequacao_pintura_executada': True
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("descontaminação e purga", res.data.get('error', ''))

    def test_download_laudo_pdf_autenticado_e_isolado(self):
        pdf_content = b"%PDF-1.4 Fake PDF Content for Test"
        fake_pdf = SimpleUploadedFile("laudo_anvisa_test.pdf", pdf_content, content_type="application/pdf")

        lote = LoteEnvase.objects.create(
            tenant=self.tenant,
            gas=self.gas_med,
            codigo_lote='LOTE-PDF-TEST-01',
            data_envase=timezone.now().date(),
            data_validade=timezone.now().date() + timedelta(days=365),
            pureza_percentual=Decimal('99.9'),
            responsavel_tecnico='Dra. Beatriz RT',
            laudo_pdf=fake_pdf
        )

        client = APIClient()
        # Não autenticado -> 401 ou 403
        res_unauth = client.get(f'/produtos/api/lotes-anvisa/{lote.id}/laudo/')
        self.assertIn(res_unauth.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

        # Autenticado no tenant correto -> 200 OK
        client.force_authenticate(user=self.user_rt)
        res_ok = client.get(f'/produtos/api/lotes-anvisa/{lote.id}/laudo/')
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ok['Content-Type'], 'application/pdf')

        # Usuário de outro tenant -> 404 (isolamento estrito)
        tenant_outro = Tenant.objects.create(
            cnpj='99.888.777/0001-99',
            razao_social='Outra Empresa Ltda',
            nome_fantasia='Outra Empresa'
        )
        user_outro = User.objects.create_user(username='user_outro', password='pass_user_123')
        Membership.objects.create(user=user_outro, tenant=tenant_outro, papel='ADMIN')

        client_outro = APIClient()
        client_outro.force_authenticate(user=user_outro)
        res_outro = client_outro.get(f'/produtos/api/lotes-anvisa/{lote.id}/laudo/')
        self.assertEqual(res_outro.status_code, status.HTTP_404_NOT_FOUND)
