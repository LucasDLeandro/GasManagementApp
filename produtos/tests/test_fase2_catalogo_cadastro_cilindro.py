"""
Bloco 2.0 da Fase 2: API de catálogo (gases, modelos, SKUs) e cadastro de cilindro.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from clientes.models import Cliente
from core.models import Membership, ResponsavelTecnico, Tenant
from core.tenancy import tenant_context
from produtos.models import Cilindro, GasQuimico, ModeloCilindro, MovimentacaoCilindro, SkuRecarga

User = get_user_model()


class CatalogoECadastroCilindroTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-81', razao_social='Gás Norte Ltda', nome_fantasia='Gás Norte', limite_cilindros=2,
        )
        self.outro = Tenant.objects.create(cnpj='22.333.444/0001-55', razao_social='Outra Ltda', nome_fantasia='Outra')
        self.gas_o2 = GasQuimico.objects.create(nome='Oxigênio Medicinal', sigla='O2-MED', categoria='MEDICINAL')
        self.gas_n2 = GasQuimico.objects.create(nome='Nitrogênio', sigla='N2', categoria='INDUSTRIAL')
        with tenant_context(self.tenant):
            self.modelo = ModeloCilindro.objects.create(
                descricao='Aço 50L 200bar', volume_hidraulico_litros=Decimal('50.00'),
                pressao_servico_bar=200, tara_nominal_kg=Decimal('62.00'), periodicidade_reteste_anos=5,
            )
            self.cliente = Cliente.objects.create(nome='Hospital Norte', cnpj='33.444.555/0001-66', tipo_cliente='PJ')
        with tenant_context(self.outro):
            self.modelo_outro = ModeloCilindro.objects.create(
                descricao='Modelo de outra empresa', volume_hidraulico_litros=Decimal('40.00'),
                pressao_servico_bar=150, tara_nominal_kg=Decimal('50.00'),
            )

        self.gerente = self._usuario('gerente.norte', 'GERENTE')
        self.motorista = self._usuario('motorista.norte', 'MOTORISTA')
        self.patio = self._usuario('patio.norte', 'OPERADOR_PATIO')
        self.client = APIClient()

    def _usuario(self, username, papel):
        user = User.objects.create_user(username=username, password='Senha-123456')
        Membership.objects.create(user=user, tenant=self.tenant, papel=papel, ativo=True)
        return user

    def _cilindro(self, **extra):
        dados = {'codigo_qr': 'qr-0001', 'numero_serie_ogiva': 's-123', 'fabricante': 'White Martins',
                 'modelo': self.modelo.id, 'gas_dedicado': self.gas_o2.id,
                 'ano_fabricacao': 2024, 'data_ultimo_reteste': '2024-01-15'}
        dados.update(extra)
        return dados

    # ------------------------------------------------------------ Catálogo
    def test_gases_globais_somente_leitura(self):
        self.client.force_authenticate(self.gerente)

        resp = self.client.get('/produtos/api/catalogo/gases/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({g['sigla'] for g in resp.json()}, {'O2-MED', 'N2'})
        self.assertEqual(self.client.post('/produtos/api/catalogo/gases/', {'nome': 'X', 'sigla': 'X'}).status_code, 405)

    def test_modelos_isolados_por_empresa(self):
        self.client.force_authenticate(self.gerente)

        resp = self.client.get('/produtos/api/catalogo/modelos/?page_size=50')
        dados = resp.json()
        ids = [m['id'] for m in (dados['results'] if isinstance(dados, dict) else dados)]
        self.assertIn(self.modelo.id, ids)
        self.assertNotIn(self.modelo_outro.id, ids)
        self.assertEqual(self.client.get(f'/produtos/api/catalogo/modelos/{self.modelo_outro.id}/').status_code, 404)

    def test_gerente_cria_sku_e_motorista_so_le(self):
        sku = {'gas': self.gas_o2.id, 'modelo_cilindro': self.modelo.id, 'nome_comercial': 'O2 Medicinal 10m³',
               'quantidade_carga': '10.00', 'unidade': 'm3', 'massa_gas_kg': '13.30', 'preco_base': '189.90',
               'ncm': '28044000', 'medicinal': True}

        self.client.force_authenticate(self.motorista)
        self.assertEqual(self.client.post('/produtos/api/catalogo/skus/', sku, format='json').status_code, 403)
        self.assertEqual(self.client.get('/produtos/api/catalogo/skus/').status_code, 200)

        self.client.force_authenticate(self.gerente)
        resp = self.client.post('/produtos/api/catalogo/skus/', sku, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        criado = SkuRecarga.unscoped.get(id=resp.json()['id'])
        self.assertEqual(criado.tenant, self.tenant)
        self.assertEqual(resp.json()['gas_sigla'], 'O2-MED')

    def test_sku_valida_ncm_medicinal_e_modelo_de_outra_empresa(self):
        self.client.force_authenticate(self.gerente)
        base = {'gas': self.gas_n2.id, 'modelo_cilindro': self.modelo.id, 'nome_comercial': 'N2 9m³',
                'quantidade_carga': '9', 'unidade': 'm3', 'massa_gas_kg': '10', 'preco_base': '120'}

        self.assertIn('ncm', self.client.post('/produtos/api/catalogo/skus/', {**base, 'ncm': '123'}, format='json').json())
        self.assertIn('medicinal', self.client.post('/produtos/api/catalogo/skus/', {**base, 'medicinal': True}, format='json').json())
        resp = self.client.post('/produtos/api/catalogo/skus/', {**base, 'modelo_cilindro': self.modelo_outro.id}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('modelo_cilindro', resp.json())

    def test_excluir_modelo_em_uso_responde_400(self):
        with tenant_context(self.tenant):
            SkuRecarga.objects.create(gas=self.gas_n2, modelo_cilindro=self.modelo, nome_comercial='N2',
                                      quantidade_carga=Decimal('9'), massa_gas_kg=Decimal('10'), preco_base=Decimal('100'))
        self.client.force_authenticate(self.gerente)

        resp = self.client.delete(f'/produtos/api/catalogo/modelos/{self.modelo.id}/')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('em uso', resp.json()['detail'])

    # ------------------------------------------------------------ Cadastro de cilindro
    def test_cadastro_cria_cilindro_vazio_e_entrada_no_ledger(self):
        self.client.force_authenticate(self.patio)

        resp = self.client.post('/produtos/api/cilindros/', self._cilindro(data_ultimo_reteste='2024-03-10'), format='json')

        self.assertEqual(resp.status_code, 201, resp.content)
        with tenant_context(self.tenant):
            cil = Cilindro.objects.get(id=resp.json()['id'])
            self.assertEqual(cil.codigo_qr, 'QR-0001')
            self.assertEqual(cil.status, 'VAZIO_TRIAGEM')
            self.assertEqual(cil.propriedade, 'PROPRIO')
            self.assertEqual(cil.pressao_servico_bar, 200)
            self.assertEqual(cil.data_proximo_reteste, datetime.date(2029, 3, 10))
            mov = MovimentacaoCilindro.objects.get(cilindro=cil)
            self.assertEqual(mov.tipo, 'ENTRADA_ESTOQUE')
            self.assertEqual(mov.status_novo, 'VAZIO_TRIAGEM')
            self.assertEqual(mov.registrado_por, self.patio)

    def test_cadastro_bloqueia_qr_e_serie_duplicados(self):
        self.client.force_authenticate(self.gerente)
        self.client.post('/produtos/api/cilindros/', self._cilindro(), format='json')

        resp = self.client.post('/produtos/api/cilindros/', self._cilindro(codigo_qr='QR-0001'), format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('codigo_qr', resp.json())
        self.assertIn('numero_serie_ogiva', resp.json())

    def test_cadastro_respeita_cota_mas_cilindro_do_cliente_e_isento(self):
        self.client.force_authenticate(self.gerente)
        for i in range(2):
            self.assertEqual(self.client.post('/produtos/api/cilindros/', self._cilindro(codigo_qr=f'Q{i}', numero_serie_ogiva=f'S{i}'), format='json').status_code, 201)

        excedeu = self.client.post('/produtos/api/cilindros/', self._cilindro(codigo_qr='Q9', numero_serie_ogiva='S9'), format='json')
        self.assertEqual(excedeu.status_code, 400)
        self.assertIn('Cota', excedeu.json()['detail'])

        do_cliente = self.client.post('/produtos/api/cilindros/', self._cilindro(
            codigo_qr='Q10', numero_serie_ogiva='S10', propriedade='CLIENTE', cliente_proprietario=self.cliente.id), format='json')
        self.assertEqual(do_cliente.status_code, 201, do_cliente.content)

    def test_cadastro_valida_cliente_pressao_e_papel(self):
        self.client.force_authenticate(self.gerente)
        sem_cliente = self.client.post('/produtos/api/cilindros/', self._cilindro(propriedade='CLIENTE'), format='json')
        self.assertIn('cliente_proprietario', sem_cliente.json())

        pressao = self.client.post('/produtos/api/cilindros/', self._cilindro(pressao_servico_bar=200, pressao_teste_bar=150), format='json')
        self.assertIn('pressao_teste_bar', pressao.json())

        modelo_alheio = self.client.post('/produtos/api/cilindros/', self._cilindro(modelo=self.modelo_outro.id), format='json')
        self.assertIn('modelo', modelo_alheio.json())

        self.client.force_authenticate(self.motorista)
        self.assertEqual(self.client.post('/produtos/api/cilindros/', self._cilindro(), format='json').status_code, 403)

    def test_pagina_mostra_catalogo_novo_e_botao_de_cadastro(self):
        self.client.force_login(self.gerente)

        html = self.client.get('/produtos/').content.decode()

        self.assertIn('id="btn-novo-cilindro"', html)
        self.assertIn('id="btn-novo-sku"', html)
        self.assertIn('produtos/js/catalogo.js', html)
        self.assertNotIn('id="modal-produto"', html)

    # ------------------------------------------------------------ 2.2: formulários redesenhados
    def test_recebimento_lista_rts_reais_e_nao_lotes(self):
        with tenant_context(self.tenant):
            rt = ResponsavelTecnico.objects.create(
                nome_completo='Dra. Ana Lima', conselho_classe='CRF', numero_registro='12345', uf_conselho='DF',
                vigencia_inicio=datetime.date(2026, 1, 1),
            )
            ResponsavelTecnico.objects.create(
                nome_completo='RT Inativo', conselho_classe='CRQ', numero_registro='999', uf_conselho='DF',
                vigencia_inicio=datetime.date(2020, 1, 1), ativo=False,
            )
        self.client.force_login(self.gerente)

        html = self.client.get('/produtos/').content.decode()

        self.assertIn(f'<option value="{rt.id}">Dra. Ana Lima (CRF 12345/DF)</option>', html)
        self.assertNotIn('RT Inativo', html)
        self.assertIn('id="stepper-recebimento"', html)

    def test_pagina_sem_dialogos_nativos_e_modais_novos(self):
        self.client.force_login(self.gerente)

        html = self.client.get('/produtos/').content.decode()

        for dialogo in ('modal-bloqueio-sanitario', 'modal-retorno-reteste', 'modal-reclassificar-gas', 'modal-estorno-ledger'):
            self.assertIn(f'id="{dialogo}" class="action-modal ds-dialog"', html)
        self.assertIn('id="reteste-variacao-tara"', html)

    def test_scripts_de_produtos_sem_alert_confirm_prompt(self):
        from pathlib import Path
        base = Path(__file__).resolve().parents[1] / 'static' / 'produtos' / 'js'
        for nome in ('cilindros_drawer.js', 'fase3_rampa_recebimento_lotes.js', 'catalogo.js', 'cadastro_cilindro.js'):
            codigo = (base / nome).read_text(encoding='utf-8')
            for proibido in ('alert(', 'confirm(', 'prompt('):
                self.assertNotIn(proibido, codigo.replace('Baros.confirmar(', ''), f'{proibido} em {nome}')

    def test_estacao_de_rampa_aparece_com_envase_e_inspecao_nasce_pendente(self):
        self.tenant.modulo_envase_ativo = True
        self.tenant.save(update_fields=['modulo_envase_ativo'])
        self.client.force_login(self.gerente)

        html = self.client.get('/produtos/').content.decode()

        self.assertIn('id="aba-conteudo-rampa" class="ds-hidden estacao"', html)
        self.assertIn('id="btn-rampa-conferir-todos"', html)
        from pathlib import Path
        js = (Path(__file__).resolve().parents[1] / 'static' / 'produtos' / 'js' / 'fase3_rampa_recebimento_lotes.js').read_text(encoding='utf-8')
        # IN 129: nada começa marcado como conforme ao acoplar o cilindro
        self.assertIn("this.ITENS_CHECKLIST.forEach(([campo]) => { item[campo] = false; });", js)
        self.assertNotIn('valvula_integra: true,', js)
