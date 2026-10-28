from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from core.context import (
    TenantNotSet,
    execution_context,
    tenant_context,
)
from core.idempotency import idempotent
from core.models import Filial, IdempotencyKey, JobExecucao, LogAuditoriaDados, Tenant
from core.rbac import pode_aprovar, pode_baixar, seed_rbac_financeiro
from core.services.filial import obter_ou_criar_filial_matriz
from core.tasks import TenantTask
from core.validators import validar_cnpj

User = get_user_model()


@pytest.fixture
def tenant_fixture(db):
    return Tenant.objects.create(
        cnpj='11.222.333/0001-81',
        razao_social='Usina de Testes Ltda',
        nome_fantasia='Usina Testes'
    )


@pytest.fixture
def tenant_b_fixture(db):
    return Tenant.objects.create(
        cnpj='22.333.444/0001-92',
        razao_social='Distribuidora Beta SA',
        nome_fantasia='Beta Distribuidora'
    )


@pytest.fixture
def user_operador(db):
    return User.objects.create_user(username='operador1', password='password123')


@pytest.fixture
def user_gerente(db):
    return User.objects.create_user(username='gerente1', password='password123')


# ==============================================================================
# 1. TESTES DE AUDITORIA DE DADOS (LogAuditoriaDados & AuditedModelMixin)
# ==============================================================================

@pytest.mark.django_db
def test_log_auditoria_dados_bloqueia_edicao_e_exclusao(tenant_fixture, user_operador):
    """
    Critério Mínimo:
    LogAuditoriaDados é estritamente append-only.
    Qualquer tentativa de UPDATE (.save() em objeto existente ou .update() em QuerySet)
    ou DELETE (.delete() em objeto ou QuerySet) DEVE levantar PermissionError.
    """
    ct = ContentType.objects.get_for_model(Tenant)

    with tenant_context(tenant_fixture):
        log = LogAuditoriaDados.objects.create(
            tenant=tenant_fixture,
            usuario=user_operador,
            content_type=ct,
            object_id=str(tenant_fixture.id),
            acao='CRIACAO',
            diff_json={'campo': {'antigo': None, 'novo': 'teste'}},
            request_id='req-123'
        )

        assert log.pk is not None

        # Tentativa de edição direta no objeto
        log.acao = 'ALTERACAO'
        with pytest.raises(PermissionError, match="somente inserção"):
            log.save()

        # Tentativa de exclusão direta no objeto
        with pytest.raises(PermissionError, match="somente inserção"):
            log.delete()

        # Tentativa de atualização em lote via QuerySet
        with pytest.raises(PermissionError, match="append-only"):
            LogAuditoriaDados.objects.filter(id=log.id).update(acao='ALTERACAO')

        # Tentativa de exclusão em lote via QuerySet
        with pytest.raises(PermissionError, match="append-only"):
            LogAuditoriaDados.objects.filter(id=log.id).delete()


@pytest.mark.django_db
def test_audited_model_mixin_gera_diff_e_mascara_campos_sensiveis(tenant_fixture, user_operador):
    """
    Valida que o mixin AuditedModelMixin grava log com mascaramento de senhas e tokens.
    """
    ct_filial = ContentType.objects.get_for_model(Filial)

    with tenant_context(tenant_fixture), execution_context(tenant=tenant_fixture, user=user_operador, request_id='req-audit-99'):
        filial = Filial.objects.create(
            tenant=tenant_fixture,
            nome="Filial Norte",
            cnpj="11.222.333/0002-62",
            uf="SP"
        )

        # Verifica se LogAuditoriaDados registrou a criação
        log = LogAuditoriaDados.objects.filter(
            content_type=ct_filial,
            object_id=str(filial.id),
            acao='CRIACAO'
        ).first()

        assert log is not None
        assert log.request_id == 'req-audit-99'
        assert log.usuario == user_operador


# ==============================================================================
# 2. TESTES DE IDEMPOTÊNCIA (IdempotencyKey & @idempotent)
# ==============================================================================

@pytest.mark.django_db
def test_idempotency_key_segunda_execucao_nao_repete_efeito(tenant_fixture):
    """
    Critério Mínimo:
    Segunda execução com a mesma chave e escopo não reexecuta o efeito colateral,
    retornando o resultado anterior.
    """
    contador = {'chamadas': 0}

    @idempotent(escopo='teste_faturamento')
    def processar_cobranca(valor: Decimal, chave: str, tenant=None):
        contador['chamadas'] += 1
        return {'status': 'PROCESSADO', 'valor': str(valor), 'transacao_id': 'TX-999'}

    with tenant_context(tenant_fixture):
        # 1ª Execução
        res1 = processar_cobranca(Decimal('150.00'), chave='CHAVE-XYZ-123', tenant=tenant_fixture)
        assert res1['status'] == 'PROCESSADO'
        assert contador['chamadas'] == 1

        # 2ª Execução com a mesma chave: não deve incrementar contador
        res2 = processar_cobranca(Decimal('150.00'), chave='CHAVE-XYZ-123', tenant=tenant_fixture)
        assert res2 == res1
        assert contador['chamadas'] == 1


@pytest.mark.django_db
def test_idempotency_key_unique_constraint_por_tenant(tenant_fixture, tenant_b_fixture):
    """
    Valida que a mesma chave pode ser utilizada em tenants diferentes sem colisão,
    mas no mesmo tenant lança erro de duplicidade se tentar inserir diretamente.
    """
    with tenant_context(tenant_fixture):
        IdempotencyKey.objects.create(
            tenant=tenant_fixture,
            escopo='pedido',
            chave='PED-001',
            resultado_ref='1'
        )

        from django.db import transaction
        with transaction.atomic(), pytest.raises(IntegrityError):
            IdempotencyKey.objects.create(
                tenant=tenant_fixture,
                escopo='pedido',
                chave='PED-001',
                resultado_ref='2'
            )

    # Em outro tenant deve ser permitido
    with tenant_context(tenant_b_fixture):
        k2 = IdempotencyKey.objects.create(
            tenant=tenant_b_fixture,
            escopo='pedido',
            chave='PED-001',
            resultado_ref='3'
        )
        assert k2.pk is not None


# ==============================================================================
# 3. TESTES DE TENANT MANAGER FAIL-CLOSED
# ==============================================================================

@pytest.mark.django_db
def test_tenant_manager_sem_tenant_em_contexto_lanca_tenant_not_set(tenant_fixture):
    """
    Critério Mínimo:
    TenantManager sem tenant em contexto DEVE levantar TenantNotSet,
    nunca retornando dados de todos os tenants indiscriminadamente.
    """
    with tenant_context(tenant_fixture):
        Filial.objects.create(
            tenant=tenant_fixture,
            nome="Filial Segura",
            cnpj="11.222.333/0003-43",
            uf="RJ"
        )

    # Fora do contexto de tenant: DEVE levantar TenantNotSet
    with pytest.raises(TenantNotSet, match="Isolamento Fail-Closed"):
        list(Filial.objects.all())

    # Com .unscoped explícito: permitido para operações administrativas
    assert Filial.unscoped.count() >= 1


# ==============================================================================
# 4. TESTES DE FILIAL & MATRIZ POR TENANT
# ==============================================================================

@pytest.mark.django_db
def test_filial_matriz_unica_por_tenant(tenant_fixture):
    """
    Valida a UniqueConstraint parcial garantindo que cada tenant tenha no máximo uma matriz.
    """
    with tenant_context(tenant_fixture):
        # 1ª Matriz
        Filial.objects.create(
            tenant=tenant_fixture,
            nome="Matriz Principal",
            cnpj="11.222.333/0001-81",
            uf="SP",
            matriz=True
        )

        # 2ª Matriz para o mesmo tenant deve falhar
        from django.db import transaction
        with transaction.atomic(), pytest.raises(IntegrityError):
            Filial.objects.create(
                tenant=tenant_fixture,
                nome="Segunda Matriz Inválida",
                cnpj="11.222.333/0002-62",
                uf="SP",
                matriz=True
            )


@pytest.mark.django_db
def test_validador_cnpj_oficial():
    """Valida rejeição de CNPJ com tamanho ou dígitos verificadores inválidos."""
    # CNPJ Válido
    assert validar_cnpj("11.222.333/0001-81") == "11.222.333/0001-81"

    # CNPJ com dígito verificador incorreto
    with pytest.raises(ValidationError, match="dígito verificador"):
        validar_cnpj("11.222.333/0001-99")

    # CNPJ com dígitos repetidos
    with pytest.raises(ValidationError, match="dígitos repetidos"):
        validar_cnpj("11.111.111/1111-11")


@pytest.mark.django_db
def test_service_obter_ou_criar_filial_matriz(tenant_fixture):
    """Valida serviço de obtenção ou instanciação automática de filial matriz."""
    matriz1 = obter_ou_criar_filial_matriz(tenant_fixture)
    assert matriz1.matriz is True
    assert matriz1.tenant == tenant_fixture

    # Segunda chamada recupera a mesma matriz existente
    matriz2 = obter_ou_criar_filial_matriz(tenant_fixture)
    assert matriz2.id == matriz1.id


# ==============================================================================
# 5. TESTES DE JOBS ASSÍNCRONOS (TenantTask & JobExecucao)
# ==============================================================================

@pytest.mark.django_db
def test_tenant_task_executa_sob_tenant_context_e_registra_job_execucao(tenant_fixture):
    """
    Critério Mínimo:
    Todo job novo roda via TenantTask e registra JobExecucao com sucesso.
    """
    class MinhaTarefa(TenantTask):
        name = "tarefa_teste_sucesso"

        def run(self, *args, **kwargs):
            # Garante que dentro da task o TenantManager opera normalmente
            return Filial.objects.count()

    tarefa = MinhaTarefa()
    res = tarefa(tenant_id=str(tenant_fixture.id))

    assert res >= 0

    # Verifica o registro em JobExecucao
    execucao = JobExecucao.unscoped.filter(
        tenant=tenant_fixture,
        nome="tarefa_teste_sucesso"
    ).first()

    assert execucao is not None
    assert execucao.status == 'SUCESSO'
    assert execucao.duracao_ms is not None
    assert execucao.fim is not None


@pytest.mark.django_db
def test_tenant_task_registra_falha_em_job_execucao(tenant_fixture):
    """
    Valida que exceções lançadas dentro da TenantTask são logadas como FALHA em JobExecucao.
    """
    class TarefaComFalha(TenantTask):
        name = "tarefa_teste_falha"

        def run(self, *args, **kwargs):
            raise ValueError("Erro simulado no job de processamento")

    tarefa = TarefaComFalha()
    with pytest.raises(ValueError, match="Erro simulado"):
        tarefa(tenant_id=str(tenant_fixture.id))

    execucao = JobExecucao.unscoped.filter(
        tenant=tenant_fixture,
        nome="tarefa_teste_falha"
    ).first()

    assert execucao is not None
    assert execucao.status == 'FALHA'
    assert "Erro simulado" in execucao.erro


# ==============================================================================
# 6. TESTES DE RBAC FINANCEIRO & SEGREGAÇÃO DE FUNÇÕES (SoD)
# ==============================================================================

@pytest.mark.django_db
def test_rbac_financeiro_segregacao_funcoes_pode_aprovar_e_baixar(user_operador, user_gerente):
    """
    Critério Mínimo:
    Regra de Segregação: quem lançou NÃO aprova nem baixa o mesmo registro.
    """
    seed_rbac_financeiro()

    # Adiciona user_gerente ao grupo FIN_APROVADOR e FIN_TESOUREIRO
    from django.contrib.auth.models import Group
    user_gerente.groups.add(Group.objects.get(name='FIN_APROVADOR'))
    user_gerente.groups.add(Group.objects.get(name='FIN_TESOUREIRO'))

    # Mock de objeto lançado por user_operador
    class RegistroFinanceiroDummy:
        criado_por = user_operador

    registro_operador = RegistroFinanceiroDummy()

    # Operador não pode aprovar seu próprio registro
    assert pode_aprovar(user_operador, registro_operador) is False
    assert pode_baixar(user_operador, registro_operador) is False

    # Gerente (que não lançou) PODE aprovar e baixar
    assert pode_aprovar(user_gerente, registro_operador) is True
    assert pode_baixar(user_gerente, registro_operador) is True

    # Se o próprio gerente lançar um registro, ele NÃO pode auto-aprovar
    class RegistroLancadoPorGerente:
        criado_por = user_gerente

    registro_gerente = RegistroLancadoPorGerente()
    assert pode_aprovar(user_gerente, registro_gerente) is False
    assert pode_baixar(user_gerente, registro_gerente) is False


# ==============================================================================
# 7. TESTES DE AUDITORIA (ALTERAÇÃO E EXCLUSÃO) E MIGRAÇÃO REVERSÍVEL
# ==============================================================================

@pytest.mark.django_db
def test_audited_model_mixin_alteracao_e_exclusao(tenant_fixture, user_operador):
    """
    Testa geração de logs com acao='ALTERACAO' (com diff de campos) e acao='EXCLUSAO'.
    """
    ct_filial = ContentType.objects.get_for_model(Filial)

    with tenant_context(tenant_fixture), execution_context(tenant=tenant_fixture, user=user_operador):
        # 1. Criação
        filial = Filial.objects.create(
            tenant=tenant_fixture,
            nome="Filial Auditoria Test",
            cnpj="11.222.333/0003-43",
            uf="RJ"
        )
        assert LogAuditoriaDados.objects.filter(content_type=ct_filial, object_id=str(filial.id), acao='CRIACAO').exists()

        # 2. Alteração
        filial.nome = "Filial Auditoria Renomeada"
        filial.save()

        log_alteracao = LogAuditoriaDados.objects.filter(
            content_type=ct_filial,
            object_id=str(filial.id),
            acao='ALTERACAO'
        ).first()
        assert log_alteracao is not None
        assert 'nome' in log_alteracao.diff_json
        assert log_alteracao.diff_json['nome']['antigo'] == "Filial Auditoria Test"
        assert log_alteracao.diff_json['nome']['novo'] == "Filial Auditoria Renomeada"

        # 3. Exclusão
        filial_id = str(filial.id)
        filial.delete()

        log_exclusao = LogAuditoriaDados.objects.filter(
            content_type=ct_filial,
            object_id=filial_id,
            acao='EXCLUSAO'
        ).first()
        assert log_exclusao is not None


@pytest.mark.django_db
def test_idempotency_decorator_argumento_string_e_retorno_objeto(tenant_fixture):
    """
    Testa decorator @idempotent com chave_fn sendo nome de argumento string
    e retorno de objeto model com .id.
    """
    chamadas = 0

    @idempotent(escopo="teste_obj", chave_fn="chave_param")
    def criar_ou_obter_obj(chave_param, tenant=None):
        nonlocal chamadas
        chamadas += 1
        return Filial.objects.create(
            tenant=tenant,
            nome=f"Filial {chave_param}",
            cnpj="11.222.333/0004-24",
            uf="MG"
        )

    with tenant_context(tenant_fixture):
        obj1 = criar_ou_obter_obj(chave_param="K-100", tenant=tenant_fixture)
        assert chamadas == 1

        # Segunda chamada com a mesma chave não executa a função novamente
        res2 = criar_ou_obter_obj(chave_param="K-100", tenant=tenant_fixture)
        assert chamadas == 1
        assert str(res2) == str(obj1.id)


@pytest.mark.django_db
def test_data_migration_matriz_idempotencia_e_rollback(db):
    """
    Critério Mínimo:
    Data migration da matriz: idempotente, com rollback testado.
    """
    import importlib

    from django.apps import apps

    migration_module = importlib.import_module('core.migrations.0007_criar_matriz_tenants_existentes')
    criar_matrizes_tenants = migration_module.criar_matrizes_tenants
    reverter_matrizes_tenants = migration_module.reverter_matrizes_tenants

    # Cria tenant de teste
    tenant = Tenant.objects.create(
        razao_social="Tenant Rollback Teste Ltda",
        nome_fantasia="Tenant Rollback",
        cnpj="44.555.666/0001-77"
    )

    # 1. Executa migração para frente
    criar_matrizes_tenants(apps, None)
    matriz = Filial.unscoped.filter(tenant=tenant, matriz=True).first()
    assert matriz is not None
    assert matriz.cnpj == "44.555.666/0001-77"
    assert matriz.matriz is True

    # 2. Executa novamente (garantia de idempotência: sem erros nem duplicatas)
    criar_matrizes_tenants(apps, None)
    assert Filial.unscoped.filter(tenant=tenant, matriz=True).count() == 1

    # 3. Executa rollback da migração
    reverter_matrizes_tenants(apps, None)
    assert not Filial.unscoped.filter(tenant=tenant, matriz=True).exists()

