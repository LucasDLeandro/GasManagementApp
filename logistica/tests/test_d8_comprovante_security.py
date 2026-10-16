import hashlib
import io
from decimal import Decimal
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant
from produtos.models import GasQuimico, ModeloCilindro, Cilindro, MovimentacaoCilindro
from logistica.models import Veiculo, Rota, Entrega, ComprovanteEntrega

User = get_user_model()


class ComprovanteSecurityD8TestCase(APITestCase):
    """
    Testes de integridade e segurança de assinaturas e comprovantes (D8 - Fase 0):
    1. Cardinalidade 1 comprovante ↔ N movimentações.
    2. Inclusão dos bytes da imagem PNG no hash SHA-256 canônico.
    3. Proteção rigorosa de acesso aos arquivos de assinatura em MEDIA_ROOT.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='44.555.666/0001-77',
            razao_social='Oxigênio & Vida Hospitalar Ltda',
            nome_fantasia='OxiVida'
        )
        self.token = set_current_tenant(self.tenant)

        self.tenant_outro = Tenant.objects.create(
            cnpj='88.999.000/0001-22',
            razao_social='Concorrente Gás SA',
            nome_fantasia='Concorrente'
        )

        self.motorista = User.objects.create_user(username='mot_d8', password='pwd')
        Membership.objects.create(user=self.motorista, tenant=self.tenant, papel='MOTORISTA')

        self.outro_usuario = User.objects.create_user(username='espiao', password='pwd')
        Membership.objects.create(user=self.outro_usuario, tenant=self.tenant_outro, papel='GERENTE')

        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa='SEC-2026',
            modelo='Iveco Daily',
            marca='Iveco',
            ano=2025,
            capacidade_carga=Decimal('1500.00')
        )
        self.rota = Rota.objects.create(
            tenant=self.tenant,
            nome='Rota Hospitalar Sul',
            origem='Base',
            destino='Hospital',
            distancia_km=Decimal('10.00'),
            tempo_estimado_horas=Decimal('0.50')
        )
        self.entrega = Entrega.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            rota=self.rota,
            motorista=self.motorista,
            data_saida=timezone.now(),
            status='Em Rota'
        )

        self.gas = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2M',
            categoria='MEDICINAL'
        )
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao='Cilindro T-50',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('62.50')
        )

        # 3 cilindros para entrega na mesma parada
        self.cilindros = []
        self.movimentacoes = []
        for i in range(3):
            cil = Cilindro.objects.create(
                tenant=self.tenant,
                codigo_qr=f'QR-D8-{i}',
                numero_serie_ogiva=f'OG-D8-{i}',
                fabricante='Cilbras',
                ano_fabricacao=2023,
                modelo=self.modelo,
                gas_dedicado=self.gas,
                tara_real_kg=Decimal('63.00'),
                data_ultimo_reteste=timezone.now().date(),
                data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1800),
                status='RESERVADO_ROTA'
            )
            self.cilindros.append(cil)
            mov = MovimentacaoCilindro.objects.create(
                tenant=self.tenant,
                cilindro=cil,
                entrega=self.entrega,
                tipo='RECOLHA_CLIENTE',
                status_anterior='EM_POSSE_CLIENTE',
                status_novo='VAZIO_TRIAGEM',
                registrado_por=self.motorista,
                ocorrido_em=timezone.now()
            )
            self.movimentacoes.append(mov)

        # Imagem PNG válida
        img = Image.new('RGB', (100, 40), color=(0, 0, 0))
        img_io = io.BytesIO()
        img.save(img_io, format='PNG')
        self.img_bytes = img_io.getvalue()
        self.doc_file = ContentFile(self.img_bytes, name='assinatura_teste.png')

    def test_cardinalidade_1_comprovante_n_movimentacoes(self):
        """
        Valida que 1 comprovante de entrega pode ser vinculado a N movimentações da mesma entrega.
        """
        comprovante = ComprovanteEntrega.objects.create(
            tenant=self.tenant,
            entrega=self.entrega,
            recebedor_nome='Dr. Roberto Silva',
            recebedor_documento='12345678900',
            assinatura_imagem=self.doc_file,
            latitude=Decimal('-15.7942000'),
            longitude=Decimal('-47.8821000')
        )
        comprovante.movimentacoes.set(self.movimentacoes)

        self.assertEqual(comprovante.movimentacoes.count(), 3)
        for mov in self.movimentacoes:
            self.assertIn(comprovante, mov.comprovantes_vinculados.all())

    def test_hash_sha256_inclui_bytes_da_imagem_assinatura(self):
        """
        Valida que os bytes da imagem da assinatura são incluídos no cálculo do hash SHA-256 canônico.
        """
        comprovante = ComprovanteEntrega.objects.create(
            tenant=self.tenant,
            entrega=self.entrega,
            recebedor_nome='Enfermeira Chefe Maria',
            recebedor_documento='98765432100',
            assinatura_imagem=self.doc_file,
            latitude=Decimal('-15.7942000'),
            longitude=Decimal('-47.8821000')
        )

        # Calcula o hash esperado incorporando os bytes da imagem
        raw_data = f"{comprovante.tenant_id}|{comprovante.entrega_id}|{comprovante.movimentacao_id}|{comprovante.recebedor_nome}|{comprovante.recebedor_documento}|{comprovante.timestamp_captura.isoformat()}|{comprovante.latitude}|{comprovante.longitude}"
        hasher = hashlib.sha256(raw_data.encode('utf-8'))
        hasher.update(self.img_bytes)
        expected_hash = hasher.hexdigest()

        self.assertEqual(comprovante.hash_integridade_sha256, expected_hash)

    def test_protecao_acesso_arquivo_assinatura_em_media_root(self):
        """
        Valida que requisições aos arquivos de assinatura em MEDIA_ROOT exigem autenticação
        e bloqueiam usuários de outros tenants (D8).
        """
        comprovante = ComprovanteEntrega.objects.create(
            tenant=self.tenant,
            entrega=self.entrega,
            recebedor_nome='Recebedor Autorizado',
            recebedor_documento='11122233344',
            assinatura_imagem=self.doc_file
        )

        arquivo_relativo = comprovante.assinatura_imagem.name # ex: 'comprovantes_assinaturas/assinatura_teste.png'
        url_direta = f"/media/{arquivo_relativo}"

        # 1. Acesso anônimo deve ser negado com 403 Forbidden
        self.client.logout()
        resp_anon = self.client.get(url_direta)
        self.assertEqual(resp_anon.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Acesso por usuário de outro tenant deve ser negado com 403 Forbidden
        self.client.force_authenticate(user=self.outro_usuario)
        resp_outro = self.client.get(url_direta)
        self.assertEqual(resp_outro.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Acesso por usuário do mesmo tenant deve ser autorizado (HTTP 200)
        self.client.force_authenticate(user=self.motorista)
        resp_auth = self.client.get(url_direta)
        self.assertEqual(resp_auth.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_auth['Content-Type'], 'image/png')
