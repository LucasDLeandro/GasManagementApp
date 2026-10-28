from django.db import transaction
from django.core.exceptions import ValidationError
from core.guards import assert_tenant_writable
from fiscal.models import ConfiguracaoFiscalFilial, DocumentoFiscal, TarefaInutilizacaoNumeracao


@transaction.atomic
def reservar_proximo_numero(tenant, filial_id, modelo: str = 'NFE_55', serie: int = None) -> tuple[int, int]:
    """
    Reserva de forma estritamente atômica e sequencial o próximo número do documento fiscal (Task 6).
    Utiliza select_for_update() na ConfiguracaoFiscalFilial para impedir condições de corrida
    e duplicidade de numeração sob alta concorrência.
    Retorna uma tupla (numero_reservado, serie).
    """
    assert_tenant_writable(tenant)

    config = (
        ConfiguracaoFiscalFilial.objects
        .select_for_update()
        .filter(tenant=tenant, filial_id=filial_id)
        .first()
    )

    if not config:
        raise ValidationError(
            f"Configuração fiscal não encontrada para a filial {filial_id} no Tenant '{tenant.nome}'."
        )

    if modelo == 'NFE_55':
        numero = config.proximo_numero_nfe
        serie_res = serie if serie is not None else config.serie_nfe
        config.proximo_numero_nfe += 1
        config.save(update_fields=['proximo_numero_nfe', 'atualizado_em'])
    elif modelo == 'MDFE_58':
        numero = config.proximo_numero_mdfe
        serie_res = serie if serie is not None else config.serie_mdfe
        config.proximo_numero_mdfe += 1
        config.save(update_fields=['proximo_numero_mdfe', 'atualizado_em'])
    elif modelo == 'CTE_57':
        numero = config.proximo_numero_cte
        serie_res = serie if serie is not None else config.serie_cte
        config.proximo_numero_cte += 1
        config.save(update_fields=['proximo_numero_cte', 'atualizado_em'])
    else:
        numero = config.proximo_numero_nfe
        serie_res = serie if serie is not None else config.serie_nfe
        config.proximo_numero_nfe += 1
        config.save(update_fields=['proximo_numero_nfe', 'atualizado_em'])

    return numero, serie_res


@transaction.atomic
def registrar_lacuna_inutilizacao(
    tenant,
    filial_id,
    modelo: str,
    serie: int,
    numero_inicial: int,
    numero_final: int,
    motivo: str
) -> TarefaInutilizacaoNumeracao:
    """
    Registra uma tarefa de inutilização para um número ou intervalo de numeração
    perdido, rejeitado ou saltado (Task 6 / SEFAZ).
    Exige justificativa com no mínimo 15 caracteres conforme a NT SEFAZ.
    """
    assert_tenant_writable(tenant)

    motivo_limpo = str(motivo or '').strip()
    if len(motivo_limpo) < 15:
        raise ValidationError("A justificativa de inutilização perante a SEFAZ deve conter no mínimo 15 caracteres.")

    if numero_inicial > numero_final:
        raise ValidationError("Número inicial não pode ser superior ao número final na inutilização.")

    tarefa = TarefaInutilizacaoNumeracao.objects.create(
        tenant=tenant,
        filial_id=filial_id,
        modelo=modelo,
        serie=serie,
        numero_inicial=numero_inicial,
        numero_final=numero_final,
        motivo=motivo_limpo,
        status='PENDENTE'
    )
    return tarefa


@transaction.atomic
def detectar_lacunas_numeracao(tenant, filial_id, modelo: str = 'NFE_55', serie: int = None) -> list[TarefaInutilizacaoNumeracao]:
    """
    Auditoria periódica (job diário) para detecção de lacunas de numeração (Task 6).
    Compara os números emitidos e inutilizados contra o contador sequencial atual.
    Gera tarefas de inutilização para qualquer intervalo saltado sem registro na SEFAZ.
    """
    assert_tenant_writable(tenant)

    config = ConfiguracaoFiscalFilial.objects.filter(tenant=tenant, filial_id=filial_id).first()
    if not config:
        return []

    if modelo == 'NFE_55':
        serie_alvo = serie if serie is not None else config.serie_nfe
        ultimo_esperado = config.proximo_numero_nfe - 1
    elif modelo == 'MDFE_58':
        serie_alvo = serie if serie is not None else config.serie_mdfe
        ultimo_esperado = config.proximo_numero_mdfe - 1
    elif modelo == 'CTE_57':
        serie_alvo = serie if serie is not None else config.serie_cte
        ultimo_esperado = config.proximo_numero_cte - 1
    else:
        serie_alvo = serie if serie is not None else config.serie_nfe
        ultimo_esperado = config.proximo_numero_nfe - 1

    if ultimo_esperado < 1:
        return []

    # Números com documentos fiscais existentes
    numeros_emitidos = set(
        DocumentoFiscal.objects.filter(
            tenant=tenant,
            filial_id=filial_id,
            modelo=modelo,
            serie=serie_alvo
        ).values_list('numero', flat=True)
    )

    # Números já cobertos por tarefas de inutilização
    numeros_inutilizados = set()
    for tar in TarefaInutilizacaoNumeracao.objects.filter(
        tenant=tenant,
        filial_id=filial_id,
        modelo=modelo,
        serie=serie_alvo
    ):
        for n in range(tar.numero_inicial, tar.numero_final + 1):
            numeros_inutilizados.add(n)

    numeros_conhecidos = numeros_emitidos | numeros_inutilizados

    # Identifica saltos no intervalo [1, ultimo_esperado]
    lacunas = []
    inicio_lacuna = None

    for n in range(1, ultimo_esperado + 1):
        if n not in numeros_conhecidos:
            if inicio_lacuna is None:
                inicio_lacuna = n
        else:
            if inicio_lacuna is not None:
                lacunas.append((inicio_lacuna, n - 1))
                inicio_lacuna = None

    if inicio_lacuna is not None:
        lacunas.append((inicio_lacuna, ultimo_esperado))

    tarefas_criadas = []
    for ini, fim in lacunas:
        tarefa = TarefaInutilizacaoNumeracao.objects.create(
            tenant=tenant,
            filial_id=filial_id,
            modelo=modelo,
            serie=serie_alvo,
            numero_inicial=ini,
            numero_final=fim,
            motivo=f"Salto de numeração detectado na auditoria diária ({ini} a {fim}).",
            status='PENDENTE'
        )
        tarefas_criadas.append(tarefa)

    return tarefas_criadas
