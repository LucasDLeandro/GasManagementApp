import uuid
from decimal import Decimal
from django.utils import timezone
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from logistica.models import Veiculo, Rota, Entrega, ComprovanteEntrega
from produtos.models import Produto, GasQuimico, ModeloCilindro, SkuRecarga, Cilindro, MovimentacaoCilindro, LoteEnvase, EnvaseCilindro
from clientes.models import Cliente
from vendas.models import Venda, ItemVenda

User = get_user_model()


class Fase4CampoAnttPwaTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            razao_social="Oxigás Brasil Logística Ltda",
            nome_fantasia="Oxigás Logística",
            cnpj="99888777000166"
        )
        self.token = set_current_tenant(self.tenant)

        # Usuários
        self.driver_user = User.objects.create_user(username="motorista_fase4", password="password123")
        self.driver_membership = Membership.objects.create(
            user=self.driver_user,
            tenant=self.tenant,
            papel="MOTORISTA",
            ativo=True
        )

        self.admin_user = User.objects.create_user(username="admin_fase4", password="password123", is_superuser=True)
        self.admin_membership = Membership.objects.create(
            user=self.admin_user,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True
        )

        # Dados Mestre
        self.gas = GasQuimico.objects.create(
            nome="Oxigênio Medicinal",
            sigla="O2-MED",
            categoria="Medicinal",
            numero_onu="UN 1072",
            classe_risco="2.2 (5.1)"
        )

        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao="Cilindro T-50L Medicinal",
            volume_hidraulico_litros=Decimal("50.00"),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal("55.00"),
            massa_gas_padrao_kg=Decimal("12.50")
        )

        self.sku = SkuRecarga.objects.create(
            tenant=self.tenant,
            gas=self.gas,
            modelo_cilindro=self.modelo,
            nome_comercial="Recarga O2 Medicinal 10m3",
            quantidade_carga=Decimal("10.00"),
            massa_gas_kg=Decimal("12.50"),
            preco_base=Decimal("180.00")
        )

        self.lote = LoteEnvase.objects.create(
            tenant=self.tenant,
            gas=self.gas,
            codigo_lote="LOT-MED-2026-F4",
            data_envase=timezone.now().date(),
            data_validade=timezone.now().date() + timezone.timedelta(days=365),
            status_qualidade="APROVADO",
            responsavel_tecnico="Dra. Mariana RT (CRQ 04412345)",
            pureza_percentual=Decimal("99.80")
        )

        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="ANTT-4444",
            modelo="Caminhão Toco 1620",
            marca="Mercedes-Benz",
            ano=2023,
            capacidade_carga=Decimal("100.00"),  # Capacidade pequena para testar sobrecarga (100 kg)
            status="Ativo"
        )

        self.rota = Rota.objects.create(
            tenant=self.tenant,
            nome="Rota Hospitalar Norte",
            origem="Base Distribuição",
            destino="Hospitais Regionais",
            distancia_km=Decimal("45.00"),
            tempo_estimado_horas=Decimal("2.50")
        )

        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome="Hospital Metropolitano Regional",
            cnpj="12345678000199",
            endereco="Av. Principal, 1000, Centro",
            cidade="São Paulo",
            estado="SP",
            telefone="11999998888",
            proprietario="Dr. Silva"
        )

        self.entrega = Entrega.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            rota=self.rota,
            motorista=self.driver_user,
            status="Agendada"
        )

        self.venda = Venda.objects.create(
            tenant=self.tenant,
            cliente=self.cliente,
            entrega=self.entrega,
            status="Em Rota",
            valor_total=Decimal("360.00")
        )

        self.produto_legado = Produto.objects.create(
            tenant=self.tenant,
            nome="Cilindro O2 Medicinal 10m3",
            categoria="Medicinal",
            capacidade=Decimal("10.00"),
            unidade_medida="m³",
            preco=Decimal("180.00"),
            estoque=10
        )

        self.item_venda = ItemVenda.objects.create(
            venda=self.venda,
            produto=self.produto_legado,
            quantidade=2,
            valor_unitario=Decimal("180.00"),
            valor_total=Decimal("360.00")
        )

        # Criação de cilindros
        hoje = timezone.now().date()
        self.cil1 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-F4-CIL-01",
            numero_serie_ogiva="OGIVA-001",
            fabricante="Mat Cilindros",
            ano_fabricacao=2021,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("50.00"),
            data_ultimo_reteste=hoje - timezone.timedelta(days=365),
            data_proximo_reteste=hoje + timezone.timedelta(days=365),
            status="RESERVADO_ROTA"
        )

        self.cil2 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-F4-CIL-02",
            numero_serie_ogiva="OGIVA-002",
            fabricante="Mat Cilindros",
            ano_fabricacao=2021,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("50.00"),
            data_ultimo_reteste=hoje - timezone.timedelta(days=365),
            data_proximo_reteste=hoje + timezone.timedelta(days=365),
            status="RESERVADO_ROTA"
        )

        # Cilindro com teste hidrostático vencido
        self.cil_vencido = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-F4-VENCIDO",
            numero_serie_ogiva="OGIVA-VENCIDA",
            fabricante="Mat Cilindros",
            ano_fabricacao=2015,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("50.00"),
            data_ultimo_reteste=hoje - timezone.timedelta(days=2000),
            data_proximo_reteste=hoje - timezone.timedelta(days=10),
            status="RESERVADO_ROTA"
        )

        # Cilindro com bloqueio sanitário
        self.cil_bloqueado = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-F4-BLOQUEADO",
            numero_serie_ogiva="OGIVA-BLOQ",
            fabricante="Mat Cilindros",
            ano_fabricacao=2020,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            tara_real_kg=Decimal("50.00"),
            data_ultimo_reteste=hoje - timezone.timedelta(days=365),
            data_proximo_reteste=hoje + timezone.timedelta(days=365),
            bloqueio_sanitario=True,
            motivo_bloqueio_sanitario="Suspeita de contaminação por óleo - RDC 658",
            status="RESERVADO_ROTA"
        )

        # Cria envase válido para os cilindros cheios
        self.envase1 = EnvaseCilindro.objects.create(
            tenant=self.tenant,
            cilindro=self.cil1,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.driver_user
        )
        self.cil1.envase_atual = self.envase1
        self.cil1.save(update_fields=['envase_atual'])

        self.envase2 = EnvaseCilindro.objects.create(
            tenant=self.tenant,
            cilindro=self.cil2,
            lote=self.lote,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.driver_user
        )
        self.cil2.envase_atual = self.envase2
        self.cil2.save(update_fields=['envase_atual'])

        # Registra saída de carga no romaneio
        # cil1: 50 + 12.5 = 62.5 kg
        # cil2: 50 + 12.5 = 62.5 kg
        # Total = 125 kg (excede capacidade do veículo de 100 kg!)
        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=self.cil1,
            tipo="SAIDA_ROTA",
            status_anterior="CHEIO_DISPONIVEL",
            status_novo="RESERVADO_ROTA",
            entrega=self.entrega,
            envase_cilindro=self.envase1,
            registrado_por=self.driver_user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4()
        )
        MovimentacaoCilindro.objects.create(
            tenant=self.tenant,
            cilindro=self.cil2,
            tipo="SAIDA_ROTA",
            status_anterior="CHEIO_DISPONIVEL",
            status_novo="RESERVADO_ROTA",
            entrega=self.entrega,
            envase_cilindro=self.envase2,
            registrado_por=self.driver_user,
            ocorrido_em=timezone.now(),
            client_uuid=uuid.uuid4()
        )

        self.client = APIClient()

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_antt_overload_lockout_blocks_route_start(self):
        """
        Garante que um veículo com carga acima de 100% da capacidade é travado
        pela regra ANTT ao tentar transicionar status para 'Em Rota'.
        """
        # Peso carregado: 62.5 + 62.5 = 125.0 kg; Capacidade: 100 kg (125% de lotação)
        self.assertEqual(self.entrega.peso_total_carregado, 125.0)
        self.assertEqual(self.entrega.percentual_lotacao, 125.0)
        self.assertTrue(self.entrega.percentual_lotacao > 100)

        # Tentativa de salvar como 'Em Rota' deve levantar ValidationError (Trava ANTT)
        self.entrega.status = "Em Rota"
        with self.assertRaises(ValidationError) as ctx:
            self.entrega.clean()
        self.assertIn("Trava de Segurança ANTT", str(ctx.exception))

        # Teste via REST API PATCH
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.patch(
            f"/logistica/api/entregas/{self.entrega.id}/",
            {"status": "Em Rota"},
            format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Trava de Segurança ANTT", str(res.data))

        # Agora aumenta a capacidade do veículo para 200 kg e verifica liberação
        self.veiculo.capacidade_carga = Decimal("200.00")
        self.veiculo.save()

        # Recarrega e atualiza
        self.entrega.refresh_from_db()
        self.assertEqual(self.entrega.percentual_lotacao, 62.5)  # 125 / 200 = 62.5% (< 80% verde)

        res_ok = self.client.patch(
            f"/logistica/api/entregas/{self.entrega.id}/",
            {"status": "Em Rota"},
            format="json"
        )
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)
        self.entrega.refresh_from_db()
        self.assertEqual(self.entrega.status, "Em Rota")

    def test_emissao_tres_documentos_antt_pdf(self):
        """
        Valida a emissão dos 3 documentos obrigatórios de transporte perigoso em 1 clique:
        1. romaneio-antt-pdf (Romaneio Bilateral ANTT)
        2. ficha-emergencia-pdf (Ficha de Emergência NBR 7503)
        3. envelope-transporte-pdf (Envelope de Transporte ANTT)
        """
        self.client.force_authenticate(user=self.admin_user)

        # 1. Romaneio ANTT PDF
        res1 = self.client.get(f"/logistica/api/entregas/{self.entrega.id}/romaneio-antt-pdf/")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1["Content-Type"], "application/pdf")
        self.assertTrue(res1.content.startswith(b"%PDF"))

        # 2. Ficha de Emergência NBR 7503 PDF
        res2 = self.client.get(f"/logistica/api/entregas/{self.entrega.id}/ficha-emergencia-pdf/")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2["Content-Type"], "application/pdf")
        self.assertTrue(res2.content.startswith(b"%PDF"))

        # 3. Envelope de Transporte ANTT PDF
        res3 = self.client.get(f"/logistica/api/entregas/{self.entrega.id}/envelope-transporte-pdf/")
        self.assertEqual(res3.status_code, status.HTTP_200_OK)
        self.assertEqual(res3["Content-Type"], "application/pdf")
        self.assertTrue(res3.content.startswith(b"%PDF"))

    def test_pacote_rota_preflight_sync_api(self):
        """
        Valida o endpoint de pacote da rota offline para o IndexedDB do App de Campo.
        """
        self.client.force_authenticate(user=self.driver_user)

        # GET pacote-rota da entrega
        res = self.client.get(f"/logistica/api/entregas/{self.entrega.id}/pacote-rota/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        self.assertEqual(data["entrega_id"], self.entrega.id)
        self.assertEqual(data["veiculo"]["placa"], "ANTT-4444")
        self.assertTrue(len(data["paradas"]) >= 1)
        self.assertEqual(data["paradas"][0]["cliente_nome"], "Hospital Metropolitano Regional")
        self.assertIn("saldos_comodato", data)
        self.assertTrue(len(data["cilindros_caminhao"]) >= 2)

        # GET minha-rota-ativa
        res_ativa = self.client.get("/logistica/api/entregas/minha-rota-ativa/")
        self.assertEqual(res_ativa.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ativa.data["entrega_id"], self.entrega.id)

    def test_sincronizacao_offline_lote_comprovante_d8_e_idempotencia(self):
        """
        Valida que o endpoint de sincronização em lote:
        - Recebe N entregas cheias e M recolhas vazias da mesma parada.
        - Cria 1 ÚNICO ComprovanteEntrega vinculado a todas as N+M movimentações (D8).
        - Aceita cascos recolhidos permissivamente.
        - É 100% idempotente (reenvio não duplica registros nem saldo de comodato).
        """
        self.client.force_authenticate(user=self.driver_user)

        comprovante_uuid = str(uuid.uuid4())
        client_uuid_1 = str(uuid.uuid4())
        client_uuid_2 = str(uuid.uuid4())
        client_uuid_recolha = str(uuid.uuid4())
        agora = timezone.now().isoformat()

        # Cria casco em posse do cliente para ser recolhido
        casco_cliente = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr="QR-CASCO-RECOLHA-01",
            numero_serie_ogiva="OGIVA-REC-01",
            fabricante="Mat Cilindros",
            ano_fabricacao=2018,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            status="EM_POSSE_CLIENTE",
            cliente_posse_atual=self.cliente,
            data_ultimo_reteste=timezone.now().date() - timezone.timedelta(days=2000),
            data_proximo_reteste=timezone.now().date() - timezone.timedelta(days=50) # Vencido, aceito na recolha
        )

        lote_sync = {
            "itens": [
                {
                    "client_uuid": client_uuid_1,
                    "tipo": "ENTREGA_CLIENTE",
                    "codigo_qr": self.cil1.codigo_qr,
                    "cilindro_id": self.cil1.id,
                    "cliente_id": self.cliente.id,
                    "entrega_id": self.entrega.id,
                    "ocorrido_em": agora,
                    "recebedor_nome": "Dra. Juliana Mendes",
                    "recebedor_documento": "123.456.789-00",
                    "assinatura_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    "latitude": -23.55052,
                    "longitude": -46.63330,
                    "documento_fiscal_ref": comprovante_uuid
                },
                {
                    "client_uuid": client_uuid_2,
                    "tipo": "ENTREGA_CLIENTE",
                    "codigo_qr": self.cil2.codigo_qr,
                    "cilindro_id": self.cil2.id,
                    "cliente_id": self.cliente.id,
                    "entrega_id": self.entrega.id,
                    "ocorrido_em": agora,
                    "recebedor_nome": "Dra. Juliana Mendes",
                    "recebedor_documento": "123.456.789-00",
                    "assinatura_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    "latitude": -23.55052,
                    "longitude": -46.63330,
                    "documento_fiscal_ref": comprovante_uuid
                },
                {
                    "client_uuid": client_uuid_recolha,
                    "tipo": "RECOLHA_CLIENTE",
                    "codigo_qr": casco_cliente.codigo_qr,
                    "cilindro_id": casco_cliente.id,
                    "cliente_id": self.cliente.id,
                    "entrega_id": self.entrega.id,
                    "ocorrido_em": agora,
                    "observacao": "Divergente / Encaminhar à Triagem",
                    "recebedor_nome": "Dra. Juliana Mendes",
                    "recebedor_documento": "123.456.789-00",
                    "assinatura_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    "latitude": -23.55052,
                    "longitude": -46.63330,
                    "documento_fiscal_ref": comprovante_uuid
                }
            ]
        }

        # 1ª Transmissão: Processamento em lote
        res = self.client.post("/api/movimentacoes/sync-offline/", lote_sync, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["processados"], 3)
        self.assertEqual(data["erros"], 0)

        # Valida que foi criado EXATAMENTE 1 ComprovanteEntrega para as 3 movimentações (D8)
        comprovantes = ComprovanteEntrega.objects.filter(entrega=self.entrega)
        self.assertEqual(comprovantes.count(), 1)
        comprovante = comprovantes.first()
        self.assertEqual(comprovante.recebedor_nome, "Dra. Juliana Mendes")
        self.assertEqual(comprovante.recebedor_documento, "123.456.789-00")
        self.assertEqual(comprovante.movimentacoes.count(), 3)

        # Valida projeção de estado dos cilindros
        self.cil1.refresh_from_db()
        self.cil2.refresh_from_db()
        casco_cliente.refresh_from_db()

        self.assertEqual(self.cil1.status, "EM_POSSE_CLIENTE")
        self.assertEqual(self.cil1.cliente_posse_atual, self.cliente)
        self.assertEqual(self.cil2.status, "EM_POSSE_CLIENTE")
        self.assertEqual(self.cil2.cliente_posse_atual, self.cliente)
        self.assertEqual(casco_cliente.status, "VAZIO_TRIAGEM")
        self.assertIsNone(casco_cliente.cliente_posse_atual)

        # 2ª Transmissão (Idempotência com os mesmos client_uuid)
        res_reteste = self.client.post("/api/movimentacoes/sync-offline/", lote_sync, format="json")
        self.assertEqual(res_reteste.status_code, status.HTTP_200_OK)
        data_reteste = res_reteste.data

        # Todos devem retornar 'ja_processado'
        for item in data_reteste["detalhes"]:
            self.assertEqual(item["status"], "ja_processado")

        # Não deve haver duplicação de comprovantes nem de movimentações
        self.assertEqual(ComprovanteEntrega.objects.filter(entrega=self.entrega).count(), 1)
        self.assertEqual(MovimentacaoCilindro.objects.filter(client_uuid=client_uuid_1).count(), 1)

    def test_app_campo_view_and_motorista_auto_redirect(self):
        """
        Valida que:
        - A rota /campo/ responde 200 para usuário autenticado.
        - A HomeView (/inicio/) redireciona automaticamente usuários com papel MOTORISTA para /campo/.
        """
        # 1. Acesso direto a /campo/
        self.client.force_login(self.driver_user)
        res_campo = self.client.get("/campo/")
        self.assertEqual(res_campo.status_code, status.HTTP_200_OK)
        self.assertContains(res_campo, "Minha Rota de Campo")
        self.assertContains(res_campo, "Modo Sol")
        self.assertContains(res_campo, "Baixar Rota para Operação Offline")

        # 2. Redirecionamento automático da Home para motorista
        res_home = self.client.get("/inicio/")
        self.assertEqual(res_home.status_code, status.HTTP_302_FOUND)
        self.assertEqual(res_home.url, "/campo/")

        # 3. Superusuário ou Admin não são redirecionados forçosamente
        self.client.force_login(self.admin_user)
        res_admin_home = self.client.get("/inicio/")
        self.assertEqual(res_admin_home.status_code, status.HTTP_200_OK)
