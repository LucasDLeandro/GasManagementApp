"""
Sprint 01.00 — Lotes e CQ: liberação do lote pelo RT com registro e regras.
"""
import datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Membership, ResponsavelTecnico, Tenant
from core.tenancy import tenant_context
from produtos.models import (
    Cilindro,
    GasQuimico,
    LoteEnvase,
    ModeloCilindro,
    MovimentacaoCilindro,
    EnvaseCilindro,
    HistoricoQualidadeLote,
    AuditoriaBloqueioSanitario,
)
from produtos.admin import HistoricoQualidadeLoteAdmin
from django.contrib.admin.sites import AdminSite
from django.db.models import ProtectedError
from django.test.utils import CaptureQueriesContext
from django.db import connection
from produtos.services.ciclo_cilindro import registrar_envase_cilindro

User = get_user_model()


class LotesCQRegrasETests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-81',
            razao_social='Gás Norte Ltda',
            nome_fantasia='Gás Norte',
            modulo_envase_ativo=True,
        )
        self.outro_tenant = Tenant.objects.create(
            cnpj='22.333.444/0001-55',
            razao_social='Outra Empresa Ltda',
            nome_fantasia='Outra Empresa',
            modulo_envase_ativo=True,
        )

        self.gas_o2 = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2-MED',
            categoria='MEDICINAL'
        )

        hoje = datetime.date(2026, 11, 10)

        # Usuários e papéis
        self.rt_usuario = self._usuario('rt.silva', 'RESPONSAVEL_TECNICO', tenant=self.tenant)
        self.rt_sem_vinculo = self._usuario('rt.semvinculo', 'RESPONSAVEL_TECNICO', tenant=self.tenant)
        self.gerente = self._usuario('gerente.norte', 'GERENTE', tenant=self.tenant)
        self.operador = self._usuario('operador.norte', 'OPERADOR_PATIO', tenant=self.tenant)
        self.vendedor = self._usuario('vendedor.norte', 'VENDEDOR', tenant=self.tenant)
        self.superusuario = User.objects.create_superuser('admin.baros', 'admin@baros.test', 'Senha-123456')

        # Vínculo formal do RT ativo e criação de lote e cilindros
        with tenant_context(self.tenant):
            self.rt_registro = ResponsavelTecnico.objects.create(
                tenant=self.tenant,
                user=self.rt_usuario,
                nome_completo='Dr. Lucas Silva',
                conselho_classe='CRF',
                numero_registro='12345',
                uf_conselho='DF',
                vigencia_inicio=hoje - datetime.timedelta(days=30),
                ativo=True
            )
            self.modelo = ModeloCilindro.objects.create(
                descricao='Aço 50L 200bar',
                volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('62.00'),
                periodicidade_reteste_anos=5,
            )
            self.lote_quarentena = LoteEnvase.objects.create(
                codigo_lote='LOTE-TEST-QUAR',
                gas=self.gas_o2,
                status_qualidade='QUARENTENA',
                data_envase=hoje,
                data_validade=hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal('99.50'),
                responsavel_tecnico='RT Inicial'
            )
            self.lote_aprovado = LoteEnvase.objects.create(
                codigo_lote='LOTE-TEST-APROV',
                gas=self.gas_o2,
                status_qualidade='APROVADO',
                data_envase=hoje,
                data_validade=hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal('99.60'),
                responsavel_tecnico='RT Inicial'
            )
            self.lote_reprovado = LoteEnvase.objects.create(
                codigo_lote='LOTE-TEST-REPROV',
                gas=self.gas_o2,
                status_qualidade='REPROVADO',
                data_envase=hoje,
                data_validade=hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal('98.00'),
                responsavel_tecnico='RT Inicial'
            )

        with tenant_context(self.outro_tenant):
            self.lote_outro_tenant = LoteEnvase.objects.create(
                codigo_lote='LOTE-OUTRA-EMP',
                gas=self.gas_o2,
                status_qualidade='QUARENTENA',
                data_envase=hoje,
                data_validade=hoje + datetime.timedelta(days=365),
                pureza_percentual=Decimal('99.50'),
                responsavel_tecnico='RT Outro'
            )

        self.client = APIClient()

    def _usuario(self, username, papel, tenant):
        user = User.objects.create_user(username=username, password='Senha-123456')
        Membership.objects.create(user=user, tenant=tenant, papel=papel, ativo=True)
        return user

    # --------------------------------------------------------------------------
    # 1. Testes que devem falhar ANTES da implementação
    # --------------------------------------------------------------------------
    def test_transicao_reprovado_para_aprovado_deve_retornar_400(self):
        """REPROVADO -> APROVADO deve responder 400 (reprovado é final)."""
        self.client.force_authenticate(self.rt_usuario)
        resp = self.client.post(
            f'/produtos/api/lotes/{self.lote_reprovado.id}/qualidade/',
            {'novo_status': 'APROVADO', 'justificativa': 'Tentando reverter reprovação'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.lote_reprovado.refresh_from_db()
        self.assertEqual(self.lote_reprovado.status_qualidade, 'REPROVADO')

    def test_reprovar_com_justificativa_vazia_ou_curta_deve_retornar_400(self):
        """Reprovar com justificativa vazia ou < 10 caracteres deve responder 400."""
        self.client.force_authenticate(self.rt_usuario)
        # Justificativa vazia
        resp_vazia = self.client.post(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
            {'novo_status': 'REPROVADO', 'justificativa': ''},
            format='json'
        )
        self.assertEqual(resp_vazia.status_code, status.HTTP_400_BAD_REQUEST)

        # Justificativa curta (5 chars)
        resp_curta = self.client.post(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
            {'novo_status': 'REPROVADO', 'justificativa': '12345'},
            format='json'
        )
        self.assertEqual(resp_curta.status_code, status.HTTP_400_BAD_REQUEST)
        self.lote_quarentena.refresh_from_db()
        self.assertEqual(self.lote_quarentena.status_qualidade, 'QUARENTENA')

    def test_estatico_central_lotes_cq_sem_inner_html_com_interpolacao_e_sem_onclick(self):
        """Teste estático: CentralLotesCQ não pode usar innerHTML com ${ e não pode ter onclick= em template string."""
        js_path = Path(settings.BASE_DIR) / 'produtos' / 'static' / 'produtos' / 'js' / 'fase3_rampa_recebimento_lotes.js'
        self.assertTrue(js_path.exists(), f"Arquivo não encontrado: {js_path}")
        conteudo = js_path.read_text(encoding='utf-8')

        # Isola o bloco do CentralLotesCQ
        inicio = conteudo.find('const CentralLotesCQ =')
        fim = conteudo.find('// Inicialização automática das abas', inicio)
        if fim == -1:
            fim = len(conteudo)
        bloco_lotes = conteudo[inicio:fim]

        self.assertNotIn("innerHTML = `", bloco_lotes, "CentralLotesCQ não deve atribuir template string em innerHTML")
        self.assertNotIn("onclick=", bloco_lotes, "CentralLotesCQ não deve usar onclick= inline em template string")

    def test_superusuario_sem_vinculo_rt_recebe_403(self):
        """Superusuário sem vínculo ativo com ResponsavelTecnico recebe 403."""
        self.client.force_authenticate(self.superusuario)
        resp = self.client.post(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
            {'novo_status': 'APROVADO'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Liberação restrita ao Responsável Técnico", str(resp.json()))

    def test_rt_sem_vinculo_rt_recebe_403(self):
        """Usuário com papel RESPONSAVEL_TECNICO mas sem registro ResponsavelTecnico recebe 403."""
        self.client.force_authenticate(self.rt_sem_vinculo)
        resp = self.client.post(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
            {'novo_status': 'APROVADO'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Liberação restrita ao Responsável Técnico", str(resp.json()))

    def test_aprovar_cria_linha_historico_com_rt_e_registro_snapshot(self):
        """Aprovar cria registro imutável em HistoricoQualidadeLote com RT e registro do snapshot."""
        self.client.force_authenticate(self.rt_usuario)
        resp = self.client.post(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
            {'novo_status': 'APROVADO', 'justificativa': 'Laudo físico-químico conforme'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.lote_quarentena.refresh_from_db()
        self.assertEqual(self.lote_quarentena.status_qualidade, 'APROVADO')

        hist = HistoricoQualidadeLote.unscoped.filter(lote=self.lote_quarentena).first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.status_anterior, 'QUARENTENA')
        self.assertEqual(hist.status_novo, 'APROVADO')
        self.assertEqual(hist.justificativa, 'Laudo físico-químico conforme')
        self.assertEqual(hist.usuario, self.rt_usuario)
        self.assertEqual(hist.responsavel_tecnico, self.rt_registro)
        self.assertEqual(hist.rt_nome_snapshot, 'Dr. Lucas Silva')
        self.assertEqual(hist.rt_registro_snapshot, 'CRF-DF 12345')

    def test_reprovar_cria_historico_e_bloqueia_cilindros_ativos(self):
        """Reprovar lote cria histórico e bloqueia sanitariamente cilindros ativos com snapshot do RT."""
        with tenant_context(self.tenant):
            cilindro = Cilindro.objects.create(
                codigo_qr='QR-BLOQ-TEST-1',
                numero_serie_ogiva='OG-999',
                fabricante='MAT',
                ano_fabricacao=2024,
                modelo=self.modelo,
                gas_dedicado=self.gas_o2,
                data_ultimo_reteste=datetime.date(2026, 1, 1),
                data_proximo_reteste=datetime.date(2031, 1, 1),
            )
            envase = EnvaseCilindro.objects.create(
                cilindro=cilindro,
                lote=self.lote_aprovado,
                pressao_final_bar=200,
                envasado_em=timezone.now(),
                operador=self.rt_usuario,
            )
            cilindro.envase_atual = envase
            cilindro.status = 'CHEIO_DISPONIVEL'
            cilindro.save()

        self.client.force_authenticate(self.rt_usuario)
        justificativa = "Contaminação por óleo detectada no ensaio físico-químico"
        resp = self.client.post(
            f'/produtos/api/lotes/{self.lote_aprovado.id}/qualidade/',
            {'novo_status': 'REPROVADO', 'justificativa': justificativa},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.lote_aprovado.refresh_from_db()
        self.assertEqual(self.lote_aprovado.status_qualidade, 'REPROVADO')

        # Verifica bloqueio do cilindro
        cilindro.refresh_from_db()
        self.assertTrue(cilindro.bloqueio_sanitario)
        self.assertIn(justificativa, cilindro.motivo_bloqueio_sanitario)

        # Verifica auditoria sanitária com snapshot
        audit = AuditoriaBloqueioSanitario.unscoped.filter(cilindro=cilindro, acao='BLOQUEIO').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.rt_nome_snapshot, 'Dr. Lucas Silva')
        self.assertEqual(audit.rt_registro_snapshot, 'CRF-DF 12345')

    def test_permissoes_gerente_e_operador_recebem_403_e_transicoes_vazias(self):
        """Gerente e Operador recebem 403 na liberação e transicoes_permitidas vazia no serializer."""
        for user in [self.gerente, self.operador]:
            self.client.force_authenticate(user)
            resp = self.client.post(
                f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
                {'novo_status': 'APROVADO'},
                format='json'
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

            # Na listagem, transicoes_permitidas deve vir vazia
            resp_list = self.client.get('/produtos/api/lotes/')
            self.assertEqual(resp_list.status_code, status.HTTP_200_OK)
            dados = resp_list.json()
            itens = dados['results'] if isinstance(dados, dict) and 'results' in dados else dados
            for item in itens:
                self.assertEqual(item['transicoes_permitidas'], [])

    def test_rt_recebe_transicoes_certas_para_cada_status(self):
        """RT recebe transições permitidas para cada status."""
        self.client.force_authenticate(self.rt_usuario)
        resp_list = self.client.get('/produtos/api/lotes/')
        self.assertEqual(resp_list.status_code, status.HTTP_200_OK)
        dados = resp_list.json()
        itens = dados['results'] if isinstance(dados, dict) and 'results' in dados else dados

        mapa_transicoes = {l['codigo_lote']: l['transicoes_permitidas'] for l in itens}
        self.assertEqual(set(mapa_transicoes['LOTE-TEST-QUAR']), {'APROVADO', 'REPROVADO'})
        self.assertEqual(mapa_transicoes['LOTE-TEST-APROV'], ['REPROVADO'])
        self.assertEqual(mapa_transicoes['LOTE-TEST-REPROV'], [])

    def test_lote_de_outra_empresa_retorna_404_na_acao_e_no_historico(self):
        """Acesso a lote de outra empresa retorna 404 na action de qualidade e no histórico."""
        self.client.force_authenticate(self.rt_usuario)
        resp_qual = self.client.post(
            f'/produtos/api/lotes/{self.lote_outro_tenant.id}/qualidade/',
            {'novo_status': 'APROVADO'},
            format='json'
        )
        self.assertEqual(resp_qual.status_code, status.HTTP_404_NOT_FOUND)

        resp_hist = self.client.get(f'/produtos/api/lotes/{self.lote_outro_tenant.id}/historico-qualidade/')
        self.assertEqual(resp_hist.status_code, status.HTTP_404_NOT_FOUND)

    def test_historico_qualidade_imutabilidade_instancia_e_admin(self):
        """Histórico de qualidade não pode ser alterado ou excluído na instância nem no admin."""
        with tenant_context(self.tenant):
            hist = HistoricoQualidadeLote.objects.create(
                tenant=self.tenant,
                lote=self.lote_quarentena,
                status_anterior='QUARENTENA',
                status_novo='APROVADO',
                justificativa='Aprovado inicial',
                usuario=self.rt_usuario,
                responsavel_tecnico=self.rt_registro,
                rt_nome_snapshot='Dr. Lucas Silva',
                rt_registro_snapshot='CRF-DF 12345',
            )

        with self.assertRaises(ValidationError):
            hist.justificativa = "Tentando adulterar justificativa"
            hist.save()

        with self.assertRaises(ValidationError):
            hist.delete()

        admin_inst = HistoricoQualidadeLoteAdmin(HistoricoQualidadeLote, AdminSite())
        self.assertFalse(admin_inst.has_add_permission(None))
        self.assertFalse(admin_inst.has_change_permission(None))
        self.assertFalse(admin_inst.has_delete_permission(None))

    def test_lotes_antigos_sem_historico_mostram_texto_padrao(self):
        """Lotes sem histórico mostram 'Sem registro (anterior ao histórico)'."""
        self.client.force_authenticate(self.rt_usuario)
        resp = self.client.get(f'/produtos/api/lotes/{self.lote_quarentena.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        dados = resp.json()
        self.assertEqual(dados['ultima_liberacao']['rt'], 'Sem registro (anterior ao histórico)')
        self.assertEqual(dados['ultima_liberacao']['registro'], '—')
        self.assertIsNone(dados['ultima_liberacao']['data'])

    def test_listagem_lotes_sem_n_mais_um(self):
        """Listagem de lotes executa número fixo de queries (sem N+1 de RT ou histórico)."""
        hoje = datetime.date(2026, 11, 10)
        with tenant_context(self.tenant):
            for i in range(10):
                LoteEnvase.objects.create(
                    codigo_lote=f'LOTE-BATCH-{i}',
                    gas=self.gas_o2,
                    status_qualidade='APROVADO',
                    data_envase=hoje,
                    data_validade=hoje + datetime.timedelta(days=365),
                    pureza_percentual=Decimal('99.50'),
                    responsavel_tecnico='RT Test'
                )

        self.client.force_authenticate(self.rt_usuario)
        with CaptureQueriesContext(connection) as queries:
            resp = self.client.get('/produtos/api/lotes/?page_size=50')
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Deve executar número pequeno e constante de queries (ex: <= 10), sem N+1
        self.assertLessEqual(len(queries), 10, f"Muitas queries executadas: {len(queries)}")

    def test_historico_qualidade_action_retorna_lista_ordenada(self):
        """Action GET /historico-qualidade/ retorna histórico ordenado decrescente por criado_em."""
        self.client.force_authenticate(self.rt_usuario)
        # Faz 2 transições: QUARENTENA -> APROVADO -> REPROVADO
        self.client.post(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
            {'novo_status': 'APROVADO', 'justificativa': 'Aprovado após testes'},
            format='json'
        )
        self.client.post(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/qualidade/',
            {'novo_status': 'REPROVADO', 'justificativa': 'Desvio detectado posteriormente'},
            format='json'
        )

        resp = self.client.get(f'/produtos/api/lotes/{self.lote_quarentena.id}/historico-qualidade/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        dados = resp.json()
        self.assertEqual(len(dados), 2)
        # Mais recente primeiro
        self.assertEqual(dados[0]['status_novo'], 'REPROVADO')
        self.assertEqual(dados[1]['status_novo'], 'APROVADO')
        self.assertEqual(dados[0]['rt_nome_snapshot'], 'Dr. Lucas Silva')

    def test_render_pagina_produtos_aba_lotes_com_rt_e_gerente(self):
        """Aba Lotes é renderizada com IDs corretos, KPIs do Design System e drawer sem estilos inline."""
        self.client.force_login(self.rt_usuario)
        resp_rt = self.client.get('/produtos/')
        self.assertEqual(resp_rt.status_code, 200)
        html_rt = resp_rt.content.decode()

        self.assertIn('id="aba-conteudo-lotes"', html_rt)
        self.assertIn('id="cq-kpi-aprovados"', html_rt)
        self.assertIn('id="cq-kpi-quarentena"', html_rt)
        self.assertIn('id="cq-kpi-reprovados"', html_rt)
        self.assertIn('id="tbody-lotes-cq"', html_rt)
        self.assertIn('id="drawer-historico-lote"', html_rt)
        self.assertIn('id="btn-fechar-drawer-historico"', html_rt)

        # Gerente também renderiza a estrutura (os botões são controlados por transicoes_permitidas)
        self.client.force_login(self.gerente)
        resp_ger = self.client.get('/produtos/')
        self.assertEqual(resp_ger.status_code, 200)
        html_ger = resp_ger.content.decode()
        self.assertIn('id="tbody-lotes-cq"', html_ger)

    # --------------------------------------------------------------------------
    # 7. Testes de segurança e restrição de edição/exclusão (Revisão Sprint 01.00)
    # --------------------------------------------------------------------------
    def test_vendedor_patch_lote_retorna_403(self):
        """Vendedor não pode alterar lote (apenas ADMIN, GERENTE ou RT)."""
        self.client.force_authenticate(self.vendedor)
        resp = self.client.patch(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/',
            {'pureza_percentual': '99.90'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_pureza_em_lote_aprovado_retorna_400(self):
        """Lote em APROVADO ou REPROVADO não pode ser alterado via PATCH/PUT."""
        self.client.force_authenticate(self.gerente)
        resp = self.client.patch(
            f'/produtos/api/lotes/{self.lote_aprovado.id}/',
            {'pureza_percentual': '99.99'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        conteudo = str(resp.json())
        self.assertIn("Lote liberado não pode ser alterado", conteudo)

    def test_delete_lote_retorna_405(self):
        """Exclusão de lote é proibida (DELETE responde 405 Method Not Allowed)."""
        self.client.force_authenticate(self.rt_usuario)
        resp = self.client.delete(f'/produtos/api/lotes/{self.lote_quarentena.id}/')
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_historico_qualidade_on_delete_protect(self):
        """FK lote em HistoricoQualidadeLote possui on_delete=PROTECT impedindo delete em cascata."""
        with tenant_context(self.tenant):
            HistoricoQualidadeLote.objects.create(
                tenant=self.tenant,
                lote=self.lote_quarentena,
                status_anterior='QUARENTENA',
                status_novo='APROVADO',
                usuario=self.rt_usuario,
                responsavel_tecnico=self.rt_registro,
                rt_nome_snapshot='Dr. Lucas Silva',
                rt_registro_snapshot='CRF-DF 12345',
                justificativa='Aprovado para teste de proteção'
            )
            with self.assertRaises(ProtectedError):
                self.lote_quarentena.delete()

    def test_serializer_snapshots_rt_e_codigo_lote_read_only_apos_criacao(self):
        """Snapshots do RT e codigo_lote após criado são somente leitura no serializer."""
        self.client.force_authenticate(self.gerente)
        codigo_original = self.lote_quarentena.codigo_lote
        resp = self.client.patch(
            f'/produtos/api/lotes/{self.lote_quarentena.id}/',
            {
                'codigo_lote': 'NOVO-CODIGO-HACK',
                'rt_nome_snapshot': 'Invasor Falso',
                'rt_registro_snapshot': 'CRQ-XX 99999',
                'responsavel_tecnico': 'Outro RT',
                'pureza_percentual': '99.75'
            },
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.lote_quarentena.refresh_from_db()
        self.assertEqual(self.lote_quarentena.codigo_lote, codigo_original)
        self.assertNotEqual(self.lote_quarentena.rt_nome_snapshot, 'Invasor Falso')
        self.assertNotEqual(self.lote_quarentena.rt_registro_snapshot, 'CRQ-XX 99999')
        self.assertEqual(self.lote_quarentena.pureza_percentual, Decimal('99.75'))



