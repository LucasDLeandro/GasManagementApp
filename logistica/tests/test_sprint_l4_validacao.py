import io
from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from PIL import Image

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from logistica.models import (
    Veiculo,
    Rota,
    Entrega,
    ValidacaoCarga,
    ValidacaoCargaEvidencia,
    ConfiguracaoValidacaoCarga
)
from logistica.services.validacao_carga import (
    criar_validacao_carga,
    aprovar_validacao_carga,
    rejeitar_validacao_carga,
    obter_relatorio_divergencias
)
from produtos.models import Produto, GasQuimico, ModeloCilindro, SkuRecarga
from clientes.models import Cliente
from vendas.models import Venda, ItemVenda

User = get_user_model()


def gerar_imagem_teste(nome="foto_teste.jpg", formato="JPEG"):
    file_obj = io.BytesIO()
    img = Image.new("RGB", (100, 100), color=(0, 128, 255))
    img.save(file_obj, format=formato)
    file_obj.seek(0)
    return SimpleUploadedFile(nome, file_obj.read(), content_type=f"image/{formato.lower()}")


class SprintL4ValidacaoCargaTestCase(TestCase):
    def setUp(self):
        # 1. Tenants para isolamento
        self.tenant_a = Tenant.objects.create(
            razao_social="GasTech Solucoes Ltda",
            nome_fantasia="GasTech A",
            cnpj="11111111000101"
        )
        self.tenant_b = Tenant.objects.create(
            razao_social="Outra Distribuidora Ltda",
            nome_fantasia="Distribuidora B",
            cnpj="22222222000102"
        )

        self.token = set_current_tenant(self.tenant_a)

        # 2. Usuários e Papéis
        self.user_motorista = User.objects.create_user(
            username="motorista_l4",
            email="motorista@gastech.com",
            password="password123"
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_motorista,
            papel="MOTORISTA",
            ativo=True
        )

        self.user_gestor = User.objects.create_user(
            username="gestor_l4",
            email="gestor@gastech.com",
            password="password123"
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_gestor,
            papel="GERENTE",
            ativo=True
        )

        self.user_b = User.objects.create_user(
            username="gestor_b",
            email="gestor@outra.com",
            password="password123"
        )
        Membership.objects.create(
            tenant=self.tenant_b,
            user=self.user_b,
            papel="GERENTE",
            ativo=True
        )

        # 3. Produto e Dados Operacionais
        self.gas = GasQuimico.objects.create(
            nome="Oxigênio Medicinal",
            sigla="O2",
            categoria="Medicinal",
            numero_onu="UN 1072",
            classe_risco="2.2"
        )
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant_a,
            descricao="Cilindro O2 50L",
            volume_hidraulico_litros=Decimal("50.00"),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal("50.00"),
            massa_gas_padrao_kg=Decimal("10.00")
        )
        self.sku = SkuRecarga.objects.create(
            tenant=self.tenant_a,
            gas=self.gas,
            modelo_cilindro=self.modelo,
            nome_comercial="Recarga O2 10m3",
            quantidade_carga=Decimal("10.00"),
            massa_gas_kg=Decimal("10.00"),
            preco_base=Decimal("100.00")
        )
        self.produto = Produto.objects.create(
            tenant=self.tenant_a,
            nome="Cilindro O2 10m3",
            categoria="Medicinal",
            capacidade=Decimal("10.00"),
            unidade_medida="m³",
            preco=Decimal("100.00"),
            estoque=50
        )

        # 4. Veículo e Rota
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant_a,
            placa="L4-VAL100",
            modelo="Caminhão Médio",
            marca="Mercedes-Benz",
            ano=2022,
            capacidade_carga=Decimal("300.00"),  # 300 kg máx
            status="Disponível"
        )
        self.rota = Rota.objects.create(
            tenant=self.tenant_a,
            nome="Rota Hospitalar Norte",
            origem="Base Central",
            destino="Zona Norte",
            distancia_km=Decimal("45.00"),
            tempo_estimado_horas=Decimal("2.00")
        )
        self.entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo,
            rota=self.rota,
            motorista=self.user_motorista,
            status="Em Rota"
        )

        # 5. Cliente e Venda
        self.cliente = Cliente.objects.create(
            tenant=self.tenant_a,
            nome="Hospital Samaritano",
            cnpj="12345678000100",
            endereco="Av. Central, 100",
            cidade="São Paulo",
            estado="SP",
            telefone="11999998888",
            proprietario="Dr. Carlos"
        )
        self.venda = Venda.objects.create(
            tenant=self.tenant_a,
            cliente=self.cliente,
            entrega=self.entrega,
            status="Em Rota",
            valor_total=Decimal("500.00")
        )
        self.item_venda = ItemVenda.objects.create(
            venda=self.venda,
            produto=self.produto,
            sku=self.sku,
            quantidade=5,
            valor_unitario=Decimal("100.00"),
            valor_total=Decimal("500.00"),
            peso_unitario=Decimal("60.00")  # 5 * 60kg = 300kg (lotação 100%)
        )

        # 6. Configuração Padrão de Validação
        self.config = ConfiguracaoValidacaoCarga.get_para_tenant(self.tenant_a)
        self.config.limite_ajuste_sem_aprovacao_un = 1
        self.config.limite_valor_sem_aprovacao = Decimal("150.00")
        self.config.motivos_exigem_foto = "Avaria no manuseio,Vazamento,Roubo/Extravio"
        self.config.save()

        self.client = APIClient()

    def tearDown(self):
        if hasattr(self, 'token'):
            reset_current_tenant(self.token)
        super().tearDown()

    # --------------------------------------------------------------------------
    # 1. SINAL E CÁLCULO DA DIFERENÇA
    # --------------------------------------------------------------------------
    def test_sinal_e_calculo_da_diferenca(self):
        """
        Diferença = quantidade_conferida - quantidade_esperada.
        Valor impacto = diferenca * preco do produto.
        """
        # Redução: esperava 5, conferiu 4 => diferenca = -1, impacto = -100.00
        val_neg = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=4,
            quantidade_esperada=5,
            motivo="Erro de separação",
            categoria_item="Cheio",
            justificativa="Faltou 1 cilindro no romaneio físico.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )
        self.assertEqual(val_neg.diferenca, Decimal("-1.00"))
        self.assertEqual(val_neg.valor_impacto, Decimal("-100.00"))

        # Sobra: esperava 2, conferiu 3 => diferenca = +1, impacto = +100.00
        val_pos = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=3,
            quantidade_esperada=2,
            motivo="Outro",
            categoria_item="Cheio",
            justificativa="Sobra de 1 cilindro carregado a mais na plataforma.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )
        self.assertEqual(val_pos.diferenca, Decimal("1.00"))
        self.assertEqual(val_pos.valor_impacto, Decimal("100.00"))

    # --------------------------------------------------------------------------
    # 2. ALÇADA: DENTRO E FORA DO LIMITE
    # --------------------------------------------------------------------------
    def test_ajuste_dentro_da_alcada_auto_aprova_e_aplica_efeitos(self):
        """
        Ajuste dentro dos limites (<= 1 un e <= R$ 150) é auto-aprovado
        e aplica imediatamente os efeitos em estoque e pedido.
        """
        estoque_inicial = self.produto.estoque
        val = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=4,
            quantidade_esperada=5,
            motivo="Produto devolvido",
            categoria_item="Cheio",
            justificativa="Cliente devolveu 1 cilindro sem violação.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )

        self.assertFalse(val.exige_aprovacao)
        self.assertEqual(val.status, "Aprovada")

        # Efeitos aplicados
        self.item_venda.refresh_from_db()
        self.venda.refresh_from_db()
        self.produto.refresh_from_db()

        self.assertEqual(self.item_venda.quantidade, 4)
        self.assertEqual(self.venda.valor_total, Decimal("400.00"))
        # Produto devolvido retorna ao estoque
        self.assertEqual(self.produto.estoque, estoque_inicial + 1)

    def test_ajuste_fora_da_alcada_fica_pendente_sem_efeitos_ate_gestor_aprovar(self):
        """
        Ajuste fora dos limites (> 1 un ou > R$ 150) fica 'Pendente de Aprovação'
        e NÃO produz efeitos até a deliberação do gestor.
        """
        val = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=2,
            quantidade_esperada=5,  # diferenca = -3 un, R$ -300
            motivo="Erro de separação",
            categoria_item="Cheio",
            justificativa="Faltaram 3 cilindros na carga despachada.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )

        self.assertTrue(val.exige_aprovacao)
        self.assertEqual(val.status, "Pendente de Aprovação")

        # Verifica que os efeitos NÃO foram aplicados ainda
        self.item_venda.refresh_from_db()
        self.venda.refresh_from_db()
        self.assertEqual(self.item_venda.quantidade, 5)
        self.assertEqual(self.venda.valor_total, Decimal("500.00"))

        # Gestor aprova a validação
        aprovar_validacao_carga(val, aprovador=self.user_gestor, observacao="Aprovado ajuste após conferência.")
        val.refresh_from_db()
        self.assertEqual(val.status, "Aprovada")
        self.assertEqual(val.aprovado_por, self.user_gestor)
        self.assertIsNotNone(val.aprovado_em)

        # Agora os efeitos foram aplicados
        self.item_venda.refresh_from_db()
        self.venda.refresh_from_db()
        self.assertEqual(self.item_venda.quantidade, 2)
        self.assertEqual(self.venda.valor_total, Decimal("200.00"))

    # --------------------------------------------------------------------------
    # 3. IMPOSSIBILIDADE DE AUTO-APROVAÇÃO
    # --------------------------------------------------------------------------
    def test_impossibilidade_de_auto_aprovacao(self):
        """
        O usuário que registrou a validação não pode aprovar a própria divergência.
        """
        val = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=2,
            quantidade_esperada=5,
            motivo="Erro de separação",
            categoria_item="Cheio",
            justificativa="Faltaram 3 cilindros na carga.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )

        with self.assertRaises(ValidationError) as ctx:
            aprovar_validacao_carga(val, aprovador=self.user_motorista)
        self.assertIn("segregação de funções", str(ctx.exception))

        # Teste via endpoint HTTP da API
        self.client.force_authenticate(user=self.user_motorista)
        resp = self.client.post(
            f"/logistica/api/validacoes/{val.id}/aprovar/",
            {"observacao": "Tentando auto aprovar"}
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("segregação de funções", str(resp.data.get("error", "")))

    # --------------------------------------------------------------------------
    # 4. REJEIÇÃO POR GESTOR
    # --------------------------------------------------------------------------
    def test_rejeicao_por_gestor_nao_produz_efeitos(self):
        """
        Validação rejeitada pelo gestor não altera pedido nem estoque.
        """
        val = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=2,
            quantidade_esperada=5,
            motivo="Erro de separação",
            categoria_item="Cheio",
            justificativa="Faltaram 3 cilindros.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )

        rejeitar_validacao_carga(val, rejeitador=self.user_gestor, observacao="Rejeitado: conferência refeita na base.")
        val.refresh_from_db()
        self.assertEqual(val.status, "Rejeitada")
        self.assertEqual(val.aprovado_por, self.user_gestor)

        self.item_venda.refresh_from_db()
        self.venda.refresh_from_db()
        self.assertEqual(self.item_venda.quantidade, 5)
        self.assertEqual(self.venda.valor_total, Decimal("500.00"))

    # --------------------------------------------------------------------------
    # 5. IMUTABILIDADE DO REGISTRO
    # --------------------------------------------------------------------------
    def test_imutabilidade_bloqueio_update_e_delete(self):
        """
        Validação confirmada não pode ser editada nem excluída diretamente.
        Correção exige criação de novo registro com valida_anterior FK.
        """
        val = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=4,
            quantidade_esperada=5,
            motivo="Produto devolvido",
            categoria_item="Cheio",
            justificativa="1 cilindro devolvido.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )

        # 1. Tentativa de update direto no model
        val.quantidade_conferida = Decimal("3.00")
        with self.assertRaises(ValidationError) as ctx:
            val.save()
        self.assertIn("imutável", str(ctx.exception).lower())

        # 2. Tentativa de delete no model
        val.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            val.delete()
        self.assertIn("não podem ser excluídas", str(ctx.exception).lower())

        # 3. Tentativa via API (PUT / PATCH / DELETE)
        self.client.force_authenticate(user=self.user_gestor)
        resp_put = self.client.put(f"/logistica/api/validacoes/{val.id}/", {"quantidade_conferida": 3})
        self.assertEqual(resp_put.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        resp_del = self.client.delete(f"/logistica/api/validacoes/{val.id}/")
        self.assertEqual(resp_del.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # 4. Correção legítima: nova validação apontando para valida_anterior
        val_correcao = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=3,
            quantidade_esperada=4,
            motivo="Erro de separação",
            categoria_item="Cheio",
            justificativa="Correção da validação anterior: mais 1 cilindro não conferido.",
            criado_por=self.user_gestor,
            entrega=self.entrega,
            valida_anterior=val
        )
        self.assertEqual(val_correcao.valida_anterior, val)

    # --------------------------------------------------------------------------
    # 6. FOTO OBRIGATÓRIA POR MOTIVO
    # --------------------------------------------------------------------------
    def test_foto_obrigatoria_por_motivo_configurado(self):
        """
        Motivos configurados (Avaria no manuseio, Vazamento, Roubo/Extravio)
        exigem foto de evidência obrigatória.
        """
        # Tentativa sem foto para "Avaria no manuseio"
        with self.assertRaises(ValidationError) as ctx:
            criar_validacao_carga(
                venda=self.venda,
                produto=self.produto,
                quantidade_conferida=4,
                quantidade_esperada=5,
                motivo="Avaria no manuseio",
                categoria_item="Cheio",
                justificativa="Cilindro com amassado na carcaça.",
                criado_por=self.user_motorista,
                entrega=self.entrega,
                fotos=[]
            )
        self.assertIn("envio obrigatório de ao menos uma foto", str(ctx.exception).lower())

        # Com foto de evidência
        foto = gerar_imagem_teste()
        val = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=4,
            quantidade_esperada=5,
            motivo="Avaria no manuseio",
            categoria_item="Cheio",
            justificativa="Cilindro com amassado na carcaça.",
            criado_por=self.user_motorista,
            entrega=self.entrega,
            fotos=[foto]
        )
        self.assertEqual(val.evidencias.count(), 1)
        self.assertFalse(val.sugere_sinistro)

        # Motivo Vazamento sugere abertura de Sinistro
        val_vazamento = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=4,
            quantidade_esperada=5,
            motivo="Vazamento",
            categoria_item="Cheio",
            justificativa="Vazamento de gás detectado na conexão.",
            criado_por=self.user_motorista,
            entrega=self.entrega,
            fotos=[foto]
        )
        self.assertTrue(val_vazamento.sugere_sinistro)

    # --------------------------------------------------------------------------
    # 7. RECÁLCULO DE PESO / LOTAÇÃO E TRAVA ANTT DE SOBRECARGA
    # --------------------------------------------------------------------------
    def test_recalculo_peso_e_bloqueio_antt_apos_ajuste_positivo(self):
        """
        Ajuste positivo que faça o peso total exceder a capacidade máxima do veículo
        deve acionar a trava ANTT e bloquear o ajuste.
        """
        # Veículo tem 300kg máx. Item atual tem 5 un x 60kg = 300kg (100% lotação).
        # Tentativa de ajuste para 6 unidades (passaria para 360kg > 300kg).
        with self.assertRaises(ValidationError) as ctx:
            criar_validacao_carga(
                venda=self.venda,
                produto=self.produto,
                quantidade_conferida=6,
                quantidade_esperada=5,
                motivo="Outro",
                categoria_item="Cheio",
                justificativa="Embarcou 1 cilindro a mais.",
                criado_por=self.user_motorista,
                entrega=self.entrega
            )
        self.assertIn("Capacidade de carga do veículo excedida", str(ctx.exception))

        # Com autorização de sobrecarga por perfil autorizado com justificativa técnica >= 10 chars
        val_autorizada = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=6,
            quantidade_esperada=5,
            motivo="Outro",
            categoria_item="Cheio",
            justificativa="Embarcou 1 cilindro a mais.",
            criado_por=self.user_gestor,
            entrega=self.entrega,
            autorizar_sobrecarga=True,
            justificativa_sobrecarga="Aprovado pelo supervisor com remanejamento de eixos."
        )
        self.assertEqual(val_autorizada.status, "Aprovada")
        self.item_venda.refresh_from_db()
        self.assertEqual(self.item_venda.quantidade, 6)

    # --------------------------------------------------------------------------
    # 8. ATOMICIDADE (TUDO OU NADA)
    # --------------------------------------------------------------------------
    def test_atomicidade_transacao_reverte_em_caso_de_falha(self):
        """
        Se houver falha durante a execução dos efeitos, nenhuma tabela
        fica com dados inconsistentes ou parcialmente aplicados.
        """
        qtd_inicial = self.item_venda.quantidade
        valor_inicial = self.venda.valor_total
        estoque_inicial = self.produto.estoque

        # Tentativa de conferir quantidade maior que gera sobrecarga
        try:
            criar_validacao_carga(
                venda=self.venda,
                produto=self.produto,
                quantidade_conferida=8,
                quantidade_esperada=5,
                motivo="Outro",
                categoria_item="Cheio",
                justificativa="Tentativa inválida com sobrecarga violando ANTT.",
                criado_por=self.user_motorista,
                entrega=self.entrega
            )
        except ValidationError:
            pass

        self.item_venda.refresh_from_db()
        self.venda.refresh_from_db()
        self.produto.refresh_from_db()

        self.assertEqual(self.item_venda.quantidade, qtd_inicial)
        self.assertEqual(self.venda.valor_total, valor_inicial)
        self.assertEqual(self.produto.estoque, estoque_inicial)

    # --------------------------------------------------------------------------
    # 9. BLOQUEIO EM ENTREGA ENCERRADA E QUANTIDADE NEGATIVA
    # --------------------------------------------------------------------------
    def test_bloqueio_entrega_encerrada_e_quantidade_negativa(self):
        """
        Bloqueia validação se quantidade conferida for negativa ou se a entrega
        estiver Concluída ou Cancelada.
        """
        # Quantidade negativa
        with self.assertRaises(ValidationError) as ctx:
            criar_validacao_carga(
                venda=self.venda,
                produto=self.produto,
                quantidade_conferida=-1,
                quantidade_esperada=5,
                motivo="Outro",
                categoria_item="Cheio",
                justificativa="Quantidade negativa não permitida.",
                criado_por=self.user_motorista,
                entrega=self.entrega
            )
        self.assertIn("não pode ser negativa", str(ctx.exception))

        # Entrega Concluída
        self.entrega.status = "Concluída"
        self.entrega.save()

        with self.assertRaises(ValidationError) as ctx:
            criar_validacao_carga(
                venda=self.venda,
                produto=self.produto,
                quantidade_conferida=4,
                quantidade_esperada=5,
                motivo="Outro",
                categoria_item="Cheio",
                justificativa="Entrega já encerrada.",
                criado_por=self.user_motorista,
                entrega=self.entrega
            )
        self.assertIn("concluída ou cancelada", str(ctx.exception).lower())

    # --------------------------------------------------------------------------
    # 10. RELATÓRIO DE DIVERGÊNCIAS E RECORRÊNCIA
    # --------------------------------------------------------------------------
    def test_relatorio_divergencias_com_dados_conhecidos(self):
        """
        Valida as métricas do relatório de divergências:
        taxa por motorista, perdas em R$, motivos frequentes e alerta de recorrência.
        """
        # Cria 3 divergências para compor o relatório
        foto = gerar_imagem_teste()
        val1 = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=4,
            quantidade_esperada=5,
            motivo="Avaria no manuseio",
            categoria_item="Cheio",
            justificativa="Válvula torta por impacto.",
            criado_por=self.user_motorista,
            entrega=self.entrega,
            fotos=[foto]
        )
        val2 = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=3,
            quantidade_esperada=4,
            motivo="Avaria no manuseio",
            categoria_item="Cheio",
            justificativa="Queda na movimentação.",
            criado_por=self.user_motorista,
            entrega=self.entrega,
            fotos=[foto]
        )
        val3 = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=2,
            quantidade_esperada=3,
            motivo="Avaria no manuseio",
            categoria_item="Cheio",
            justificativa="Terceira avaria registrada.",
            criado_por=self.user_motorista,
            entrega=self.entrega,
            fotos=[foto]
        )

        dados_relatorio = obter_relatorio_divergencias(self.tenant_a)

        self.assertEqual(dados_relatorio["total_validacoes"], 3)
        self.assertEqual(dados_relatorio["total_com_divergencia"], 3)
        self.assertEqual(dados_relatorio["perdas_totais_reais"], 300.0)
        self.assertTrue(len(dados_relatorio["alertas_recorrencia"]) > 0)
        self.assertEqual(dados_relatorio["alertas_recorrencia"][0]["motivo"], "Avaria no manuseio")

        # Teste via endpoint HTTP
        self.client.force_authenticate(user=self.user_gestor)
        resp = self.client.get("/logistica/api/validacoes/relatorio-divergencias/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["total_validacoes"], 3)
        self.assertEqual(resp.data["perdas_totais_reais"], 300.0)

    # --------------------------------------------------------------------------
    # 11. ISOLAMENTO MULTI-TENANT
    # --------------------------------------------------------------------------
    def test_isolamento_por_empresa(self):
        """
        Garante isolamento estrito entre Tenant A e Tenant B.
        Tenant B não enxerga validações ou configurações do Tenant A.
        """
        val_a = criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=4,
            quantidade_esperada=5,
            motivo="Erro de separação",
            categoria_item="Cheio",
            justificativa="Validação do Tenant A.",
            criado_por=self.user_motorista,
            entrega=self.entrega
        )

        # Autentica usuário do Tenant B
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.get("/logistica/api/validacoes/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results") if isinstance(resp.data, dict) and "results" in resp.data else resp.data
        ids_retornados = [item["id"] for item in (results or [])]
        self.assertNotIn(val_a.id, ids_retornados)

    # --------------------------------------------------------------------------
    # 12. CONFERÊNCIA DE SAÍDA E RETORNO (API ENDPOINTS)
    # --------------------------------------------------------------------------
    def test_endpoints_conferencia_saida_e_retorno(self):
        """
        Testa endpoints de conferência de saída e retorno de viagem.
        """
        self.client.force_authenticate(user=self.user_gestor)

        # 1. Conferência na Saída (GET)
        resp_saida_get = self.client.get(f"/logistica/api/entregas/{self.entrega.id}/conferencia-saida/")
        self.assertEqual(resp_saida_get.status_code, status.HTTP_200_OK)
        self.assertIn("itens_esperados", resp_saida_get.data)

        # 2. Conferência na Saída (POST com 100% conferido)
        resp_saida_post = self.client.post(
            f"/logistica/api/entregas/{self.entrega.id}/conferencia-saida/",
            {
                "itens": [{
                    "venda_id": self.venda.id,
                    "produto_id": self.produto.id,
                    "quantidade_esperada": 5,
                    "quantidade_conferida": 5,
                    "motivo": "Outro",
                    "justificativa": "Tudo conferido 100%."
                }],
                "iniciar_rota": False
            },
            format="json"
        )
        self.assertEqual(resp_saida_post.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_saida_post.data.get("saida_liberada"))

        # 3. Conferência de Retorno (GET & POST)
        resp_ret_get = self.client.get(f"/logistica/api/entregas/{self.entrega.id}/conferencia-retorno/")
        self.assertEqual(resp_ret_get.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_ret_get.data.get("total_despachado"), 5)

        # Sem entrega registrada, há pendência de 5 cilindros
        resp_ret_post = self.client.post(
            f"/logistica/api/entregas/{self.entrega.id}/conferencia-retorno/",
            {"observacao": "Retorno com pendência inicial."}
        )
        self.assertEqual(resp_ret_post.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_ret_post.data.get("status"), "Pendência de Ajuste")

        # Justifica a devolução de carga gerando validação
        criar_validacao_carga(
            venda=self.venda,
            produto=self.produto,
            quantidade_conferida=0,
            quantidade_esperada=5,
            motivo="Produto devolvido",
            categoria_item="Cheio",
            justificativa="Retorno justificado por devolução integral do cliente.",
            criado_por=self.user_gestor,
            entrega=self.entrega
        )
        resp_ret_post2 = self.client.post(
            f"/logistica/api/entregas/{self.entrega.id}/conferencia-retorno/",
            {"observacao": "Retorno 100% justificado."}
        )
        self.assertEqual(resp_ret_post2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_ret_post2.data.get("status"), "Em Conformidade")
