"""
2.2.9: andamento da campanha de recall (ABERTO -> HOMOLOGADO_RT -> EM_NOTIFICACAO -> CONCLUIDO)
e a página de Recall redesenhada.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from clientes.models import Cliente
from core.models import Membership, Tenant
from core.tenancy import tenant_context
from produtos.models import Cilindro, GasQuimico, ItemRecallCliente, LoteEnvase, ModeloCilindro, RecallCampanha

User = get_user_model()


class RecallAndamentoTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(cnpj='11.222.333/0001-81', razao_social='Gás Norte Ltda', nome_fantasia='Gás Norte')
        gas = GasQuimico.objects.create(nome='Oxigênio Medicinal', sigla='O2-MED', categoria='MEDICINAL')
        self.rt = self._usuario('rt.norte', 'RESPONSAVEL_TECNICO')
        self.gerente = self._usuario('gerente.norte', 'GERENTE')
        hoje = datetime.date(2026, 10, 1)
        with tenant_context(self.tenant):
            modelo = ModeloCilindro.objects.create(descricao='Aço 50L', volume_hidraulico_litros=Decimal('50'),
                                                   pressao_servico_bar=200, tara_nominal_kg=Decimal('62'))
            self.lote = LoteEnvase.objects.create(codigo_lote='LOTE-O2-01', gas=gas, data_envase=hoje,
                                                  data_validade=hoje + datetime.timedelta(days=365), responsavel_tecnico='CRF 123')
            self.cliente = Cliente.objects.create(nome='<img src=x onerror=alert(1)> Hospital', cnpj='33.444.555/0001-66', tipo_cliente='PJ')
            self.campanha = RecallCampanha.objects.create(lote=self.lote, codigo_campanha='REC-01', motivo='Desvio de pureza',
                                                          texto_notificacao='Recolher o lote LOTE-O2-01',
                                                          criado_por=self.gerente)
            self.itens = []
            for i in range(2):
                cil = Cilindro.objects.create(codigo_qr=f'QR-{i}', numero_serie_ogiva=f'S-{i}', fabricante='MAT', ano_fabricacao=2024,
                                              modelo=modelo, gas_dedicado=gas, data_ultimo_reteste=hoje,
                                              data_proximo_reteste=hoje + datetime.timedelta(days=1800), propriedade='CLIENTE',
                                              cliente_proprietario=self.cliente)
                self.itens.append(ItemRecallCliente.objects.create(campanha=self.campanha, cliente=self.cliente, cilindro=cil,
                                                                   tipo_exposicao='CONTENCAO_ATIVA'))

        self.client = APIClient()

    def _usuario(self, username, papel):
        user = User.objects.create_user(username=username, password='Senha-123456')
        Membership.objects.create(user=user, tenant=self.tenant, papel=papel, ativo=True)
        return user

    def _andamento(self, item, status_):
        return self.client.post(f'/produtos/api/itens-recall/{item.id}/confirmar-recolhimento/',
                                {'status_notificacao': status_}, format='json')

    def _status(self):
        self.campanha.refresh_from_db()
        return self.campanha.status

    def test_nao_notifica_antes_da_homologacao(self):
        self.client.force_authenticate(self.gerente)

        resp = self._andamento(self.itens[0], 'NOTIFICADO')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('Homologue', resp.json()['error'])
        self.itens[0].refresh_from_db()
        self.assertEqual(self.itens[0].status_notificacao, 'PENDENTE')

    def test_fluxo_completo_ate_concluir(self):
        self.client.force_authenticate(self.rt)
        self.assertEqual(self.client.post(f'/produtos/api/campanhas-recall/{self.campanha.id}/homologar/').status_code, 200)
        self.assertEqual(self._status(), 'HOMOLOGADO_RT')

        self.client.force_authenticate(self.gerente)
        resp = self._andamento(self.itens[0], 'NOTIFICADO')
        self.assertEqual(resp.json()['campanha_status'], 'EM_NOTIFICACAO')
        self.itens[0].refresh_from_db()
        self.assertIsNotNone(self.itens[0].notificado_em)

        self._andamento(self.itens[0], 'RECOLHIDO')
        self.assertEqual(self._status(), 'EM_NOTIFICACAO')  # ainda falta o segundo item

        resp = self._andamento(self.itens[1], 'CONSUMIDO_DECLARADO')
        self.assertEqual(resp.json()['campanha_status'], 'CONCLUIDO')
        self.campanha.refresh_from_db()
        self.assertIsNotNone(self.campanha.concluido_em)
        self.itens[1].refresh_from_db()
        self.assertIsNotNone(self.itens[1].notificado_em)  # recolher/declarar implica notificação

        self.assertEqual(self._andamento(self.itens[0], 'PENDENTE').status_code, 400)  # concluída não aceita mudanças

    def test_homologar_so_campanha_aberta(self):
        self.client.force_authenticate(self.rt)
        self.client.post(f'/produtos/api/campanhas-recall/{self.campanha.id}/homologar/')

        resp = self.client.post(f'/produtos/api/campanhas-recall/{self.campanha.id}/homologar/')

        self.assertEqual(resp.status_code, 400)

    def test_status_da_campanha_nao_muda_por_patch(self):
        self.client.force_authenticate(self.gerente)

        resp = self.client.patch(f'/produtos/api/campanhas-recall/{self.campanha.id}/', {'status': 'CONCLUIDO'}, format='json')

        self.assertIn(resp.status_code, (200, 400))
        self.assertEqual(self._status(), 'ABERTO')

    def test_status_invalido(self):
        self.campanha.status = 'HOMOLOGADO_RT'
        self.campanha.save(update_fields=['status'])
        self.client.force_authenticate(self.gerente)

        self.assertEqual(self._andamento(self.itens[0], 'QUALQUER').status_code, 400)

    def test_pagina_de_recall_redesenhada_sem_script_embutido(self):
        self.client.force_login(self.gerente)

        html = self.client.get('/produtos/anvisa/recall/').content.decode()

        self.assertIn('produtos/js/recall.js', html)
        self.assertIn('data-recall-aba="campanhas"', html)
        self.assertNotIn('prompt(', html)
        self.assertNotIn('<style>', html)
        from pathlib import Path
        js = (Path(__file__).resolve().parents[1] / 'static' / 'produtos' / 'js' / 'recall.js').read_text(encoding='utf-8')
        for proibido in ('alert(', 'prompt(', '.innerHTML = `', 'innerHTML += '):
            self.assertNotIn(proibido, js)

    def test_abrir_campanha_exige_motivo_e_comunicado_descritivos(self):
        self.client.force_authenticate(self.rt)
        base = {'lote_id': self.lote.id, 'codigo_campanha': 'REC-02'}

        resp = self.client.post('/produtos/api/campanhas-recall/', {**base, 'motivo': 'curto', 'texto_notificacao': 'x'}, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('motivo', resp.json())
        self.assertIn('texto_notificacao', resp.json())
        self.assertFalse(RecallCampanha.unscoped.filter(codigo_campanha='REC-02').exists())

