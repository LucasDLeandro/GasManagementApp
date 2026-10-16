import uuid
from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
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
    EnvaseCilindro
)
from produtos.services import (
    registrar_entrega_cilindro,
    registrar_recolha_cilindro,
    enviar_para_reteste,
    retornar_de_reteste
)

User = get_user_model()

class LedgerImutavelTests(TestCase):
    """
    Testes automatizados da Sprint 2:
    1. Prova que edições normais em Cilindro NÃO alteram posse_desde nem o histórico do ledger.
    2. Prova que o Ledger MovimentacaoCilindro bloqueia terminantemente UPDATE e DELETE (PermissionError).
    3. Prova que tentar entregar cilindro com teste hidrostático vencido lança ValidationError.
    4. Prova de idempotência por client_uuid.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Distribuidora Central de Gases Ltda',
            nome_fantasia='Central Gases'
        )
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(
            username='operador_patio',
            password='senha_segura_123',
            tipo_usuario='OPERADOR_PATIO'
        )
        Membership.objects.create(user=self.user, tenant=self.tenant, papel='OPERADOR_PATIO')

        self.cliente = Cliente.objects.create(
            cnpj='55.666.777/0001-88',
            nome='Hospital Metropolitano',
            endereco='Av. Brasil, 1500',
            telefone='11999998888',
            estado='SP',
            cidade='São Paulo',
            proprietario='Diretoria Clínica'
        )

        self.gas_oxigenio = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2-MED',
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
            codigo_qr='QR-OX-001',
            numero_serie_ogiva='BR-2020-0984',
            fabricante='Cilbras',
            ano_fabricacao=2020,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_oxigenio,
            tara_real_kg=Decimal('59.80'),
            propriedade='PROPRIO',
            data_ultimo_reteste=hoje - timedelta(days=365),
            data_proximo_reteste=hoje + timedelta(days=365 * 4),
            status='CHEIO_DISPONIVEL'
        )

        self.lote = LoteEnvase.objects.create(
            gas=self.gas_oxigenio,
            codigo_lote='LOTE-LEDGER-001',
            data_envase=hoje - timedelta(days=10),
            data_validade=hoje + timedelta(days=365),
            pureza_percentual=Decimal('99.60'),
            responsavel_tecnico='Resp Técnico'
        )
        self.envase = EnvaseCilindro.objects.create(
            cilindro=self.cilindro,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now() - timedelta(days=10),
            operador=self.user
        )
        self.cilindro.envase_atual = self.envase
        self.cilindro.save(update_fields=['envase_atual'])

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_editar_cilindro_nao_altera_posse_desde_nem_ledger(self):
        """
        1. Prova que editar qualquer campo cadastral do Cilindro NÃO altera posse_desde
           nem gera alterações espúrias no histórico do ledger.
        """
        data_entrega = timezone.now() - timedelta(days=45)
        client_uuid = uuid.uuid4()

        # Realiza a entrega formal via camada de serviço
        cilindro, mov = registrar_entrega_cilindro(
            cilindro_id=self.cilindro.id,
            cliente=self.cliente,
            usuario=self.user,
            ocorrido_em=data_entrega,
            client_uuid=client_uuid
        )

        self.assertEqual(cilindro.status, 'EM_POSSE_CLIENTE')
        self.assertEqual(cilindro.cliente_posse_atual, self.cliente)
        self.assertEqual(cilindro.posse_desde, data_entrega)
        self.assertEqual(MovimentacaoCilindro.objects.count(), 1)

        # Agora realiza alterações cadastrais normais no Cilindro (ex: peso, fabricante, observações)
        cilindro.tara_real_kg = Decimal('61.20')
        cilindro.fabricante = 'Cilbras Indústria Atualizada'
        cilindro.save()

        # Recarrega do banco e valida que a posse_desde permanece intacta
        cilindro.refresh_from_db()
        self.assertEqual(cilindro.posse_desde, data_entrega)
        self.assertEqual(cilindro.cliente_posse_atual, self.cliente)
        self.assertEqual(cilindro.tara_real_kg, Decimal('61.20'))
        self.assertEqual(MovimentacaoCilindro.objects.count(), 1)

    def test_ledger_imutavel_bloqueia_update_e_delete(self):
        """
        2. Prova que a tabela MovimentacaoCilindro é um Ledger APPEND-ONLY:
           - Instância .save() em update lança PermissionError.
           - Instância .delete() lança PermissionError.
           - QuerySet .update() e .delete() lançam PermissionError (tanto no objects quanto no unscoped).
        """
        data_entrega = timezone.now()
        client_uuid = uuid.uuid4()

        _, mov = registrar_entrega_cilindro(
            cilindro_id=self.cilindro.id,
            cliente=self.cliente,
            usuario=self.user,
            ocorrido_em=data_entrega,
            client_uuid=client_uuid
        )

        # 1. Tentativa de salvar alteração na instância existente
        with self.assertRaises(PermissionError):
            mov.observacao = "Tentativa maliciosa de alterar o histórico"
            mov.save()

        # 2. Tentativa de deletar a instância existente
        with self.assertRaises(PermissionError):
            mov.delete()

        # 3. Tentativa de update via QuerySet com TenantManager
        with self.assertRaises(PermissionError):
            MovimentacaoCilindro.objects.filter(id=mov.id).update(observacao="Fraude")

        # 4. Tentativa de delete via QuerySet com TenantManager
        with self.assertRaises(PermissionError):
            MovimentacaoCilindro.objects.filter(id=mov.id).delete()

        # 5. Tentativa de burlar via unscoped
        with self.assertRaises(PermissionError):
            MovimentacaoCilindro.unscoped.filter(id=mov.id).update(observacao="Fraude Unscoped")

        with self.assertRaises(PermissionError):
            MovimentacaoCilindro.unscoped.filter(id=mov.id).delete()

    def test_bloqueio_entrega_cilindro_reteste_vencido(self):
        """
        3. Prova que tentar entregar um cilindro com data_proximo_reteste no passado lança ValidationError.
        """
        hoje = timezone.now().date()
        cilindro_vencido = Cilindro.objects.create(
            codigo_qr='QR-OX-VENCIDO',
            numero_serie_ogiva='BR-2015-0012',
            fabricante='Mannesmann',
            ano_fabricacao=2015,
            modelo=self.modelo_50l,
            gas_dedicado=self.gas_oxigenio,
            tara_real_kg=Decimal('60.10'),
            propriedade='PROPRIO',
            data_ultimo_reteste=hoje - timedelta(days=365 * 6),
            data_proximo_reteste=hoje - timedelta(days=30),  # Vencido há 30 dias
            status='CHEIO_DISPONIVEL'
        )

        self.assertTrue(cilindro_vencido.reteste_vencido)

        client_uuid = uuid.uuid4()
        with self.assertRaises(ValidationError) as ctx:
            registrar_entrega_cilindro(
                cilindro_id=cilindro_vencido.id,
                cliente=self.cliente,
                usuario=self.user,
                ocorrido_em=timezone.now(),
                client_uuid=client_uuid
            )

        self.assertIn("teste hidrostático venceu", str(ctx.exception))

        # O status do cilindro não deve ter sido alterado
        cilindro_vencido.refresh_from_db()
        self.assertEqual(cilindro_vencido.status, 'CHEIO_DISPONIVEL')
        self.assertIsNone(cilindro_vencido.cliente_posse_atual)

    def test_idempotencia_por_client_uuid(self):
        """
        4. Prova de idempotência por client_uuid:
           Enviar o mesmo client_uuid duas vezes retorna a mesma movimentação sem duplicar registros.
        """
        uuid_unico = uuid.uuid4()
        agora = timezone.now()

        # Primeira chamada
        cil_1, mov_1 = registrar_entrega_cilindro(
            cilindro_id=self.cilindro.id,
            cliente=self.cliente,
            usuario=self.user,
            ocorrido_em=agora,
            client_uuid=uuid_unico
        )

        # Segunda chamada com o mesmo client_uuid (ex: retry de conexão/timeout de rede)
        cil_2, mov_2 = registrar_entrega_cilindro(
            cilindro_id=self.cilindro.id,
            cliente=self.cliente,
            usuario=self.user,
            ocorrido_em=agora,
            client_uuid=uuid_unico
        )

        self.assertEqual(mov_1.id, mov_2.id)
        self.assertEqual(MovimentacaoCilindro.objects.filter(client_uuid=uuid_unico).count(), 1)
