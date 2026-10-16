from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import (
    Cliente, ContratoComodato, FranquiaModeloContrato,
    FechamentoFaturaEstadia, ItemFaturaEstadia,
    AjusteCompetenciaEstadia, ExtravioCilindroRegistro
)
from clientes.services import fechar_fatura_estadia_competencia
from produtos.models import GasQuimico, ModeloCilindro, Cilindro, MovimentacaoCilindro

User = get_user_model()


class PreviaFaturaEstadiaTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            razao_social="Distribuidora Prévia Ltda",
            nome_fantasia="Prévia Gás",
            cnpj="99999999000188"
        )
        self.token = set_current_tenant(self.tenant)

        self.user = User.objects.create_user(username="admin_previa", password="pwd")
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True
        )

        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome="Hospital das Clínicas",
            cnpj="12.345.678/0001-99",
            endereco="Av. Paulista, 1000",
            telefone="1199999999",
            estado="SP",
            cidade="São Paulo",
            proprietario="Dr. Silva"
        )

        self.gas = GasQuimico.objects.create(
            nome="Oxigênio Medicinal",
            sigla="O2M",
            categoria="MEDICINAL"
        )
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao="Cilindro T-50L",
            volume_hidraulico_litros=Decimal("50.00"),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal("60.00")
        )

        self.contrato = ContratoComodato.objects.create(
            tenant=self.tenant,
            cliente=self.cliente,
            vigencia_inicio=date(2026, 1, 1),
            criterio_franquia="FIFO"
        )
        FranquiaModeloContrato.objects.create(
            tenant=self.tenant,
            contrato=self.contrato,
            modelo=self.modelo,
            dias_carencia_giro=5,
            franquia_cilindros_isentos=2,
            taxa_diaria=Decimal("10.00")
        )

        self.cil = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-PREVIA-01",
            numero_serie_ogiva="OG-P01",
            fabricante="Cilbras",
            ano_fabricacao=2023,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("60.00"),
            data_ultimo_reteste=date(2025, 1, 1),
            data_proximo_reteste=date(2030, 1, 1),
            status="EM_POSSE_CLIENTE"
        )

        # Entrega no início do mês 2026-05
        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=self.cil,
            cliente=self.cliente,
            tipo="ENTREGA_CLIENTE",
            status_anterior="CHEIO_DISPONIVEL",
            status_novo="EM_POSSE_CLIENTE",
            ocorrido_em=timezone.datetime(2026, 5, 1, 10, 0, tzinfo=timezone.get_current_timezone()),
            is_legado=True,
            registrado_por=self.user
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        if hasattr(self, 'token'):
            reset_current_tenant(self.token)
        super().tearDown()

    def test_fechamento_modo_previa_nao_persiste_dados(self):
        """fechar_fatura_estadia_competencia com persistir=False não grava no banco"""
        qtd_faturas_antes = FechamentoFaturaEstadia.objects.count()
        qtd_itens_antes = ItemFaturaEstadia.objects.count()

        fatura = fechar_fatura_estadia_competencia(
            cliente=self.cliente,
            competencia_ano_mes="2026-05",
            usuario=self.user,
            tenant_id=self.tenant.id,
            persistir=False
        )

        self.assertEqual(fatura.status_pagamento, "PREVIA")
        self.assertIsNone(fatura.pk)
        self.assertTrue(hasattr(fatura, "itens_previa"))
        self.assertGreater(len(fatura.itens_previa), 0)

        # Banco de dados deve permanecer inalterado
        self.assertEqual(FechamentoFaturaEstadia.objects.count(), qtd_faturas_antes)
        self.assertEqual(ItemFaturaEstadia.objects.count(), qtd_itens_antes)

    def test_api_fechar_modo_previa(self):
        """API /clientes/api/faturas-estadia/fechar/ com persistir=False retorna HTTP 200 e status PREVIA"""
        url = "/clientes/api/faturas-estadia/fechar/"
        payload = {
            "cliente_id": self.cliente.id,
            "competencia_ano_mes": "2026-05",
            "persistir": False
        }
        resp = self.client.post(url, payload, format="json", HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status_pagamento"], "PREVIA")
        self.assertIsNone(resp.data["id"])
        self.assertGreater(len(resp.data["itens"]), 0)

        # Banco não gravou fatura
        self.assertEqual(FechamentoFaturaEstadia.objects.count(), 0)
