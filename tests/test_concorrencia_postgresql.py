import datetime
import json
import tempfile
import threading
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import LogAuditoriaDados, Membership, Tenant
from core.tenancy import reset_current_tenant, set_current_tenant, tenant_context
from fiscal.models import ConfiguracaoFiscalFilial, Filial
from fiscal.services.numeracao_service import reservar_proximo_numero
from produtos.models import (
    BaixaPatrimonial,
    Cilindro,
    GasQuimico,
    ItemEnvioReteste,
    ModeloCilindro,
    MovimentacaoCilindro,
    TanqueCriogenico,
)
from produtos.services.baixa import baixar_cilindro_patrimonial
from produtos.services.granel import registrar_perda_purga
from produtos.services.reteste import enviar_cilindros_para_reteste

User = get_user_model()


@unittest.skipIf(
    connection.vendor == "sqlite",
    "Testes reais de concorrência com select_for_update e Barrier exigem PostgreSQL.",
)
class TestConcorrenciaRealPostgresql(TransactionTestCase):
    """
    Valida travas reais de concorrência (select_for_update) em duas threads paralelas
    sincronizadas por threading.Barrier(2) no PostgreSQL.
    """

    def setUp(self):
        super().setUp()
        suf = uuid.uuid4().hex[:6]
        self.tenant = Tenant.objects.create(
            cnpj=f"44.555.{suf[:3]}/0001-88",
            razao_social=f"Gases Concorrencia {suf} Ltda",
            nome_fantasia=f"Conc {suf}",
            modulo_patrimonio_ativo=True,
            modulo_envase_ativo=True,
            modulo_fiscal_ativo=True,
            status_assinatura="ATIVO",
        )
        self.user = User.objects.create_user(
            username=f"conc_user_{suf}",
            email=f"conc_{suf}@baros.com.br",
            password="Password123!",
        )
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            papel="ADMIN",
            ativo=True,
        )
        self.gas, _ = GasQuimico.objects.get_or_create(
            sigla=f"O2-{suf[:4]}",
            defaults={"nome": f"Oxigênio {suf}", "categoria": "INDUSTRIAL"},
        )
        with tenant_context(self.tenant):
            self.modelo = ModeloCilindro.objects.create(
                tenant=self.tenant,
                descricao="Cilindro 50L Aço",
                volume_hidraulico_litros=Decimal("50.00"),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal("55.00"),
                periodicidade_reteste_anos=5,
            )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def _run_barrier_threads(self, worker_fn, count=2):
        barrier = threading.Barrier(count)
        threads = [
            threading.Thread(target=worker_fn, args=(i, barrier))
            for i in range(count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            self.assertFalse(t.is_alive(), "Thread concorrente travou ou excedeu timeout.")

    def test_01_baixa_patrimonial_concorrente_mesmo_cilindro(self):
        hoje = timezone.localdate()
        with tenant_context(self.tenant):
            cilindro = Cilindro.objects.create(
                tenant=self.tenant,
                codigo_qr=f"QR-BAIXA-{uuid.uuid4().hex[:6]}",
                numero_serie_ogiva=f"SR-BAIXA-{uuid.uuid4().hex[:6]}",
                modelo=self.modelo,
                gas_dedicado=self.gas,
                fabricante="MAT",
                ano_fabricacao=2022,
                tara_real_kg=Decimal("55.000"),
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje,
                data_proximo_reteste=hoje + datetime.timedelta(days=1800),
            )

        sucessos = []
        erros_validacao = []
        outros_erros = []
        lock = threading.Lock()

        def worker(idx, barrier):
            connection.close()
            token = set_current_tenant(self.tenant)
            try:
                barrier.wait(timeout=10)
                _, baixa = baixar_cilindro_patrimonial(
                    cilindro_id=cilindro.id,
                    tipo="INUTILIZACAO_TECNICA",
                    motivo=f"Baixa concorrente thread {idx}",
                    documento_ref=f"DOC-{idx}",
                    usuario=self.user,
                )
                with lock:
                    sucessos.append(baixa.id)
            except ValidationError as exc:
                with lock:
                    erros_validacao.append(str(exc))
            except Exception as exc:
                with lock:
                    outros_erros.append(repr(exc))
            finally:
                reset_current_tenant(token)
                connection.close()

        self._run_barrier_threads(worker, 2)

        self.assertEqual(outros_erros, [], f"Erros inesperados: {outros_erros}")
        self.assertEqual(len(sucessos), 1, f"Esperado 1 sucesso, obtido {sucessos}")
        self.assertEqual(len(erros_validacao), 1, f"Esperada 1 rejeição, obtido {erros_validacao}")

        cilindro.refresh_from_db()
        self.assertEqual(cilindro.status, "BAIXADO")
        self.assertEqual(BaixaPatrimonial.unscoped.filter(cilindro=cilindro).count(), 1)

    def test_02_reserva_concorrente_numeracao_nfe(self):
        with tenant_context(self.tenant):
            filial = Filial.objects.create(
                tenant=self.tenant,
                nome="Filial Concorrência",
                cnpj="12345678000195",
                inscricao_estadual="110042490114",
                uf="SP",
                municipio_ibge="3550308",
                matriz=True,
            )
            config = ConfiguracaoFiscalFilial.objects.create(
                tenant=self.tenant,
                filial=filial,
                proximo_numero_nfe=1,
            )

        numeros = []
        erros = []
        lock = threading.Lock()

        def worker(idx, barrier):
            connection.close()
            token = set_current_tenant(self.tenant)
            try:
                barrier.wait(timeout=10)
                num, _ = reservar_proximo_numero(self.tenant, filial.id, modelo="NFE_55")
                with lock:
                    numeros.append(num)
            except Exception as exc:
                with lock:
                    erros.append(repr(exc))
            finally:
                reset_current_tenant(token)
                connection.close()

        self._run_barrier_threads(worker, 2)

        self.assertEqual(erros, [], f"Erros inesperados: {erros}")
        self.assertEqual(sorted(numeros), [1, 2])
        config.refresh_from_db()
        self.assertEqual(config.proximo_numero_nfe, 3)

    def test_03_envio_concorrente_reteste_mesmo_cilindro(self):
        hoje = timezone.localdate()
        with tenant_context(self.tenant):
            cilindro = Cilindro.objects.create(
                tenant=self.tenant,
                codigo_qr=f"QR-RET-{uuid.uuid4().hex[:6]}",
                numero_serie_ogiva=f"SR-RET-{uuid.uuid4().hex[:6]}",
                modelo=self.modelo,
                gas_dedicado=self.gas,
                fabricante="MAT",
                ano_fabricacao=2021,
                tara_real_kg=Decimal("55.000"),
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje - datetime.timedelta(days=1100),
                data_proximo_reteste=hoje - datetime.timedelta(days=5),
            )

        sucessos = []
        erros_validacao = []
        outros_erros = []
        lock = threading.Lock()

        def worker(idx, barrier):
            connection.close()
            token = set_current_tenant(self.tenant)
            try:
                barrier.wait(timeout=10)
                envio, _ = enviar_cilindros_para_reteste(
                    tenant=self.tenant,
                    oficina_nome="Oficina Central",
                    oficina_cnpj="11.222.333/0001-44",
                    documento_envio=f"ROM-{idx}",
                    cilindro_ids=[cilindro.id],
                    usuario=self.user,
                )
                with lock:
                    sucessos.append(envio.id)
            except ValidationError as exc:
                with lock:
                    erros_validacao.append(str(exc))
            except Exception as exc:
                with lock:
                    outros_erros.append(repr(exc))
            finally:
                reset_current_tenant(token)
                connection.close()

        self._run_barrier_threads(worker, 2)

        self.assertEqual(outros_erros, [], f"Erros inesperados: {outros_erros}")
        self.assertEqual(len(sucessos), 1, f"Esperado 1 envio, obtido {sucessos}")
        self.assertEqual(len(erros_validacao), 1, f"Esperada 1 rejeição, obtido {erros_validacao}")

        cilindro.refresh_from_db()
        self.assertEqual(cilindro.status, "EM_REQUALIFICACAO")
        self.assertEqual(ItemEnvioReteste.unscoped.filter(cilindro=cilindro).count(), 1)

    def test_04_saida_concorrente_estoque_granel(self):
        with tenant_context(self.tenant):
            tanque = TanqueCriogenico.objects.create(
                tenant=self.tenant,
                codigo=f"TQ-{uuid.uuid4().hex[:6]}",
                gas=self.gas,
                capacidade_kg=Decimal("10000.000"),
                saldo_atual_kg=Decimal("500.000"),
                saldo_valor_atual=Decimal("2500.00"),
                custo_medio_kg_atual=Decimal("5.0000"),
            )

        sucessos = []
        erros = []
        lock = threading.Lock()

        def worker(idx, barrier):
            connection.close()
            token = set_current_tenant(self.tenant)
            try:
                barrier.wait(timeout=10)
                registrar_perda_purga(
                    tenant=self.tenant,
                    tanque_id=tanque.id,
                    quantidade_kg=Decimal("100.000"),
                )
                with lock:
                    sucessos.append(idx)
            except Exception as exc:
                with lock:
                    erros.append(repr(exc))
            finally:
                reset_current_tenant(token)
                connection.close()

        self._run_barrier_threads(worker, 2)

        self.assertEqual(erros, [], f"Erros inesperados: {erros}")
        self.assertEqual(len(sucessos), 2)
        tanque.refresh_from_db()
        self.assertEqual(tanque.saldo_atual_kg, Decimal("300.000"))
        self.assertEqual(tanque.saldo_valor_atual, Decimal("1500.00"))


class TestLoaddataRawSemEfeitosColaterais(TransactionTestCase):
    """Garante que loaddata (raw=True) não dispara signals nem duplica registros."""

    def test_loaddata_nao_dispara_signals_duplicados(self):
        suf = uuid.uuid4().hex[:6]
        tenant = Tenant.objects.create(
            cnpj=f"55.666.{suf[:3]}/0001-11",
            razao_social=f"Fixture Test {suf} Ltda",
            nome_fantasia=f"Fix {suf}",
            status_assinatura="ATIVO",
        )
        gas = GasQuimico.objects.create(
            sigla=f"N2-{suf[:4]}",
            nome=f"Nitrogênio {suf}",
            categoria="INDUSTRIAL",
        )
        with tenant_context(tenant):
            modelo = ModeloCilindro.objects.create(
                tenant=tenant,
                descricao="Modelo Fixture 40L",
                volume_hidraulico_litros=Decimal("40.00"),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal("48.00"),
                periodicidade_reteste_anos=5,
            )
            hoje = timezone.localdate()
            cil = Cilindro.objects.create(
                tenant=tenant,
                codigo_qr=f"QR-FIX-{suf}",
                numero_serie_ogiva=f"SR-FIX-{suf}",
                modelo=modelo,
                gas_dedicado=gas,
                fabricante="MAT",
                ano_fabricacao=2023,
                tara_real_kg=Decimal("48.000"),
                status="VAZIO_TRIAGEM",
                data_ultimo_reteste=hoje,
                data_proximo_reteste=hoje + datetime.timedelta(days=1800),
            )
            cil_pk = cil.pk

        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_path = Path(tmpdir) / "cilindro_fixture.json"
            with open(fixture_path, "w", encoding="utf-8") as fh:
                call_command("dumpdata", "produtos.Cilindro", pks=str(cil_pk), all=True, stdout=fh)

            # Remove o registro para reimportar via loaddata
            Cilindro.unscoped.filter(pk=cil_pk).delete()
            auditoria_antes = LogAuditoriaDados.unscoped.count()
            mov_antes = MovimentacaoCilindro.unscoped.count()

            call_command("loaddata", str(fixture_path), verbosity=0)

            self.assertEqual(Cilindro.unscoped.filter(pk=cil_pk).count(), 1)
            self.assertEqual(LogAuditoriaDados.unscoped.count(), auditoria_antes)
            self.assertEqual(MovimentacaoCilindro.unscoped.count(), mov_antes)
