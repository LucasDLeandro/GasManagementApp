import os
import uuid
from datetime import date, timedelta
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

# Habilita produtos.services a carregar submódulos em produtos/services/
__path__ = [os.path.join(os.path.dirname(__file__), 'services')]


from .models import (
    Cilindro,
    MovimentacaoCilindro,
    LoteEnvase,
    EnvaseCilindro,
    InspecaoPreEnvase,
    RecebimentoCilindroCheio,
    ReclassificacaoCilindro,
    GasQuimico,
    AuditoriaBloqueioSanitario,
    RecallCampanha,
    ItemRecallCliente
)

# ==============================================================================
# MÁQUINA DE ESTADOS FINITA (FSM) DE CILINDROS
# ==============================================================================

TRANSIÇÕES_PERMITIDAS_CILINDRO = {
    'VAZIO_TRIAGEM': {
        'EM_ENVASE',          # Início do processo de enchimento
        'CHEIO_DISPONIVEL',   # Conclusão do envase (ou envase direto)
        'EM_RETESTE',         # Envio para requalificação / manutenção (legado)
        'EM_REQUALIFICACAO',  # Envio para reteste hidrostático externo (Sprint 8B)
        'BAIXADO',            # Condenação na inspeção inicial / triagem
    },
    'EM_ENVASE': {
        'CHEIO_DISPONIVEL',   # Envase concluído e aprovado
        'VAZIO_TRIAGEM',      # Descarte / aborto de envase
        'BAIXADO',            # Reprovação catastrófica no envase
    },
    'CHEIO_DISPONIVEL': {
        'RESERVADO_ROTA',     # Alocado para romaneio / veículo de entrega
        'EM_POSSE_CLIENTE',   # Entrega no cliente (balcão ou expedição)
        'VAZIO_TRIAGEM',      # Despressurização / esvaziamento para manutenção
        'BAIXADO',            # Avaria grave no pátio
    },
    'RESERVADO_ROTA': {
        'EM_POSSE_CLIENTE',   # Entregue com sucesso no cliente
        'CHEIO_DISPONIVEL',   # Retorno de rota sem entrega (devolução ao pátio)
        'VAZIO_TRIAGEM',      # Sinistro com vazamento
        'BAIXADO',            # Sinistro destrutivo em trânsito
    },
    'EM_POSSE_CLIENTE': {
        'VAZIO_TRIAGEM',      # Recolhido vazio pelo motorista (Full-for-Empty)
        'CHEIO_DISPONIVEL',   # Devolução de cilindro cheio não consumido
        'BAIXADO',            # Cilindro perdido / indenizado como sucata / extraviado
        'EXTRAVIADO',         # Extravio patrimonial
    },
    'EM_RETESTE': {
        'VAZIO_TRIAGEM',      # Aprovado no teste hidrostático (revalidado por 5 anos)
        'BAIXADO',            # Reprovado / condenado no teste hidrostático INMETRO
    },
    'EM_REQUALIFICACAO': {
        'VAZIO_TRIAGEM',      # Aprovado no reteste hidrostático
        'BAIXADO',            # Reprovado / condenado no ensaio
    },
    'EXTRAVIADO': {
        'BAIXADO',            # Baixa definitiva de extravio
        'VAZIO_TRIAGEM',      # Recuperação de cilindro extraviado
    },
    'BAIXADO': set(),         # ESTADO TERMINAL: Proibida qualquer reativação direta
}

def validar_transicao_status_cilindro(cilindro, novo_status, permitir_estorno_baixa=False):
    """
    Valida a transição de status do Cilindro de acordo com a FSM.
    Garante que o estado BAIXADO é estritamente terminal e impede transições ilegais,
    exceto mediante estorno operacional autorizado (permitir_estorno_baixa=True).
    """
    status_atual = cilindro.status
    if status_atual == novo_status:
        return True

    if status_atual == 'BAIXADO' and not permitir_estorno_baixa:
        raise ValidationError(
            f"Transição Ilegal de Estado: O cilindro {cilindro.numero_serie_ogiva} está BAIXADO/CONDENADO "
            f"(estado terminal) e não pode ser reativado para '{novo_status}'."
        )

    transicoes_permitidas = TRANSIÇÕES_PERMITIDAS_CILINDRO.get(status_atual, set())
    if novo_status not in transicoes_permitidas and not (status_atual == 'BAIXADO' and permitir_estorno_baixa):
        raise ValidationError(
            f"Transição Ilegal de Estado: O cilindro {cilindro.numero_serie_ogiva} não pode transitar "
            f"de '{status_atual}' para '{novo_status}'. Transições permitidas: {sorted(list(transicoes_permitidas))}."
        )
    return True


def registrar_envase_cilindro(
    *,
    cilindro=None,
    cilindro_id=None,
    lote=None,
    lote_id=None,
    pressao_bar=None,
    pressao_final_bar=None,
    usuario=None,
    operador=None,
    ocorrido_em=None,
    client_uuid=None,
    observacoes="",
    observacoes_envase="",
    valvula_integra=True,
    pressao_residual_positiva=True,
    pintura_cor_padrao_ok=True,
    rotulo_identificacao_ok=True,
    observacoes_inspecao=""
):
    """
    Registra o envase de um cilindro com um lote químico específico.
    Garante:
    1. Idempotência por client_uuid.
    2. select_for_update() concorrente.
    3. FSM: validação de transição para CHEIO_DISPONIVEL.
    4. Bloqueio de cilindro com teste hidrostático (INMETRO) vencido.
    5. Bloqueio por bloqueio sanitário ativo no cilindro.
    6. Checklist obrigatório de inspeção pré-envase (IN nº 129/2022). Se reprovado, redireciona para inspeção/reteste.
    7. Validação estrita de compatibilidade química (lote.gas == cilindro.gas_dedicado).
    8. Validação de validade do lote químico (lote não vencido).
    9. Atualização atômica para status 'CHEIO_DISPONIVEL' e apontamento para envase_atual.
    10. Registro imutável no ledger (tipo='ENVASE', envase_cilindro=envase).
    """
    if cilindro is not None and cilindro_id is None:
        cilindro_id = cilindro.id
    if lote is not None and lote_id is None:
        lote_id = lote.id
    if pressao_final_bar is not None and pressao_bar is None:
        pressao_bar = pressao_final_bar
    if operador is not None and usuario is None:
        usuario = operador
    if client_uuid is None:
        client_uuid = uuid.uuid4()
    if ocorrido_em is None:
        ocorrido_em = timezone.now()
    if observacoes_envase and not observacoes:
        observacoes = observacoes_envase

    # 1. Idempotência
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        envase = getattr(existing_mov.cilindro, 'envase_atual', None)
        return existing_mov.cilindro, envase, existing_mov

    # 2. Trava de linha transacional
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)
    lote = LoteEnvase.objects.get(id=lote_id)

    # 3. Validação de transição FSM
    validar_transicao_status_cilindro(cilindro, 'CHEIO_DISPONIVEL')

    # 4. Trava de segurança INMETRO
    if cilindro.reteste_vencido:
        raise ValidationError(
            f"Bloqueio de Segurança INMETRO: O cilindro {cilindro.numero_serie_ogiva} não pode ser envasado "
            f"pois seu teste hidrostático venceu em {cilindro.data_proximo_reteste.strftime('%d/%m/%Y')}."
        )

    # 5. Trava Sanitária ANVISA ativa no cilindro
    if cilindro.bloqueio_sanitario:
        raise ValidationError(
            f"Bloqueio Sanitário ANVISA: O cilindro {cilindro.numero_serie_ogiva} está com bloqueio sanitário ativo: "
            f"{cilindro.motivo_bloqueio_sanitario or 'Quarentena/Reprovação física'}."
        )

    # 6. Checklist de Inspeção Física Pré-Envase (IN nº 129/2022)
    inspecao_aprovada = bool(valvula_integra and pressao_residual_positiva and pintura_cor_padrao_ok and rotulo_identificacao_ok)
    inspecao = InspecaoPreEnvase.objects.create(
        cilindro=cilindro,
        operador=usuario,
        valvula_integra=valvula_integra,
        pressao_residual_positiva=pressao_residual_positiva,
        pintura_cor_padrao_ok=pintura_cor_padrao_ok,
        rotulo_identificacao_ok=rotulo_identificacao_ok,
        aprovado=inspecao_aprovada,
        observacoes=observacoes_inspecao,
        realizado_em=ocorrido_em
    )

    if not inspecao_aprovada:
        cilindro.status = 'EM_RETESTE'
        cilindro.bloqueio_sanitario = True
        cilindro.motivo_bloqueio_sanitario = (
            f"Reprovado na inspeção física pré-envase (IN 129/2022): {observacoes_inspecao or 'item físico não conforme'}."
        )
        cilindro.save(update_fields=['status', 'bloqueio_sanitario', 'motivo_bloqueio_sanitario'])
        raise ValidationError(
            f"Bloqueio Pré-Envase (IN nº 129/2022): O cilindro {cilindro.numero_serie_ogiva} foi reprovado "
            f"na inspeção física pré-envase e encaminhado para manutenção/inspeção."
        )

    with transaction.atomic():
        # 7. Compatibilidade química
        if lote.gas_id != cilindro.gas_dedicado_id:
            raise ValidationError(
                f"Incompatibilidade química: O lote {lote.codigo_lote} ({lote.gas.nome}) "
                f"não pode ser envasado no cilindro {cilindro.numero_serie_ogiva} dedicado a {cilindro.gas_dedicado.nome}."
            )

        # 8. Validade do lote
        if lote.esta_vencido:
            raise ValidationError(
                f"Bloqueio Sanitário ANVISA: O lote {lote.codigo_lote} está vencido desde {lote.data_validade.strftime('%d/%m/%Y')}."
            )

        if cilindro.cliente_posse_atual is not None:
            raise ValidationError(
                f"O cilindro {cilindro.numero_serie_ogiva} não pode ser envasado pois ainda consta em posse do cliente {cilindro.cliente_posse_atual.nome}."
            )

        # 9. Criação do registro de envase histórico imutável
        envase = EnvaseCilindro.objects.create(
            cilindro=cilindro,
            lote=lote,
            pressao_final_bar=pressao_bar,
            envasado_em=ocorrido_em,
            operador=usuario,
            observacoes=observacoes
        )

        # 10. Projeção de estado do ativo
        status_anterior = cilindro.status
        cilindro.status = 'CHEIO_DISPONIVEL'
        cilindro.envase_atual = envase
        cilindro.recebimento_externo_atual = None
        cilindro.bloqueio_sanitario = False
        cilindro.motivo_bloqueio_sanitario = None
        cilindro.save(update_fields=['status', 'envase_atual', 'recebimento_externo_atual', 'bloqueio_sanitario', 'motivo_bloqueio_sanitario'])

        # 11. Registro no ledger imutável vinculando o EnvaseCilindro
        movimentacao = MovimentacaoCilindro.objects.create(
            cilindro=cilindro,
            tipo='ENVASE',
            status_anterior=status_anterior,
            status_novo='CHEIO_DISPONIVEL',
            lote_envase=lote.codigo_lote,
            envase_cilindro=envase,
            recebimento_externo=None,
            ocorrido_em=ocorrido_em,
            registrado_por=usuario,
            client_uuid=client_uuid,
            observacao=f"Envasado com lote {lote.codigo_lote} a {pressao_bar} bar."
        )

    return cilindro, envase, movimentacao


@transaction.atomic
def registrar_entrega_cilindro(
    *,
    cilindro=None,
    cilindro_id=None,
    cliente=None,
    entrega=None,
    usuario=None,
    responsavel=None,
    ocorrido_em=None,
    client_uuid=None,
    documento_fiscal_ref=None
):
    """
    Registra a entrega de um cilindro cheio no cliente com trava de linha (select_for_update).
    Garante:
    1. Idempotência por client_uuid.
    2. FSM: validação de transição para EM_POSSE_CLIENTE.
    3. Bloqueio automático por reteste INMETRO vencido.
    4. Validação estrita de envase ativo associado (cilindro cheio exige envase_cilindro).
    5. Bloqueio sanitário ANVISA: gases medicinais exigem lote de envase não vencido.
    6. Atualização atômica do estado e registro no ledger imutável vinculando envase_cilindro e documento_fiscal_ref.
    """
    if cilindro is not None and cilindro_id is None:
        cilindro_id = cilindro.id
    if responsavel is not None and usuario is None:
        usuario = responsavel
    if client_uuid is None:
        client_uuid = uuid.uuid4()
    if ocorrido_em is None:
        ocorrido_em = timezone.now()

    # 1. Idempotência
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        return existing_mov.cilindro, existing_mov

    # 2. Trava de linha transacional
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)

    # 3. Validação de transição FSM
    validar_transicao_status_cilindro(cilindro, 'EM_POSSE_CLIENTE')

    # 4. Trava de segurança: Reteste hidrostático
    if cilindro.reteste_vencido:
        raise ValidationError(
            f"Bloqueio de Segurança: O cilindro {cilindro.numero_serie_ogiva} não pode ser entregue "
            f"pois seu teste hidrostático venceu em {cilindro.data_proximo_reteste.strftime('%d/%m/%Y')}."
        )

    # 4.1 Trava Sanitária ANVISA: Bloqueio Sanitário ativo
    if cilindro.bloqueio_sanitario:
        raise ValidationError(
            f"Bloqueio Sanitário ANVISA: O cilindro {cilindro.numero_serie_ogiva} está com bloqueio sanitário ativo: "
            f"{cilindro.motivo_bloqueio_sanitario or 'Quarentena/Reprovação física'}."
        )

    # 5. Exigência estrita de envase ativo para entrega de cilindro cheio
    if not cilindro.carga_atual:
        raise ValidationError(
            f"Bloqueio de Integridade: O cilindro cheio {cilindro.numero_serie_ogiva} "
            f"não possui registro de envase ativo associado para entrega."
        )

    # 5.1 Trava de Qualidade de Lote (IN 129/2022)
    if cilindro.envase_atual and cilindro.envase_atual.lote.status_qualidade != 'APROVADO':
        raise ValidationError(
            f"Bloqueio de Qualidade: O lote {cilindro.envase_atual.lote.codigo_lote} está com status "
            f"'{cilindro.envase_atual.lote.get_status_qualidade_display()}' e não pode ser entregue ao cliente."
        )

    # 6. Trava Sanitária ANVISA para gases medicinais
    if cilindro.gas_dedicado.exige_lote_anvisa:
        if cilindro.envase_atual and cilindro.envase_atual.lote.esta_vencido:
            raise ValidationError(
                f"Bloqueio Sanitário ANVISA: O cilindro medicinal {cilindro.numero_serie_ogiva} "
                f"está com o lote {cilindro.envase_atual.lote.codigo_lote} vencido desde "
                f"{cilindro.envase_atual.lote.data_validade.strftime('%d/%m/%Y')}."
            )
        elif cilindro.recebimento_externo_atual and cilindro.recebimento_externo_atual.esta_vencido:
            raise ValidationError(
                f"Bloqueio Sanitário ANVISA: O cilindro medicinal {cilindro.numero_serie_ogiva} "
                f"está com o lote de fornecedor {cilindro.recebimento_externo_atual.lote_fornecedor} vencido desde "
                f"{cilindro.recebimento_externo_atual.data_validade.strftime('%d/%m/%Y')}."
            )

    status_anterior = cilindro.status
    cilindro.status = 'EM_POSSE_CLIENTE'
    cilindro.cliente_posse_atual = cliente
    cilindro.posse_desde = ocorrido_em
    cilindro.save(update_fields=['status', 'cliente_posse_atual', 'posse_desde'])

    lote_codigo = (
        cilindro.envase_atual.lote.codigo_lote if cilindro.envase_atual
        else (cilindro.recebimento_externo_atual.lote_fornecedor if cilindro.recebimento_externo_atual else None)
    )

    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='ENTREGA_CLIENTE',
        status_anterior=status_anterior,
        status_novo='EM_POSSE_CLIENTE',
        cliente=cliente,
        entrega=entrega,
        lote_envase=lote_codigo,
        envase_cilindro=cilindro.envase_atual,
        recebimento_externo=cilindro.recebimento_externo_atual,
        documento_fiscal_ref=documento_fiscal_ref,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid
    )

    # Sprint 5B.1: Recálculo incremental de diárias a partir da data da movimentação
    try:
        import zoneinfo
        from clientes.services import recalcular_diarias_posse
        tz_sp = zoneinfo.ZoneInfo('America/Sao_Paulo')
        dt_inicio = ocorrido_em.astimezone(tz_sp).date() if hasattr(ocorrido_em, 'astimezone') else timezone.now().astimezone(tz_sp).date()
        recalcular_diarias_posse(
            tenant_id=cilindro.tenant_id,
            data_inicio=dt_inicio,
            cliente_id=cliente.id if cliente else None
        )
    except Exception:
        pass

    return cilindro, movimentacao


@transaction.atomic
def registrar_recolha_cilindro(
    *,
    cilindro=None,
    cilindro_id=None,
    cliente=None,
    entrega=None,
    usuario=None,
    responsavel=None,
    ocorrido_em=None,
    client_uuid=None,
    observacao="",
    documento_fiscal_ref=None
):
    """
    Registra a recolha de um cilindro vazio que estava em posse do cliente.
    Garante FSM (transição para VAZIO_TRIAGEM), limpeza do envase_atual e registro no ledger sem envase (casco vazio).
    """
    if cilindro is not None and cilindro_id is None:
        cilindro_id = cilindro.id
    if responsavel is not None and usuario is None:
        usuario = responsavel
    if client_uuid is None:
        client_uuid = uuid.uuid4()
    if ocorrido_em is None:
        ocorrido_em = timezone.now()

    # 1. Idempotência
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        return existing_mov.cilindro, existing_mov

    # 2. Trava de linha transacional
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)

    # 3. Validação de transição FSM
    validar_transicao_status_cilindro(cilindro, 'VAZIO_TRIAGEM')

    status_anterior = cilindro.status
    cilindro.status = 'VAZIO_TRIAGEM'
    cilindro.cliente_posse_atual = None
    cilindro.posse_desde = None
    cilindro.envase_atual = None
    cilindro.recebimento_externo_atual = None
    cilindro.save(update_fields=['status', 'cliente_posse_atual', 'posse_desde', 'envase_atual', 'recebimento_externo_atual'])

    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='RECOLHA_CLIENTE',
        status_anterior=status_anterior,
        status_novo='VAZIO_TRIAGEM',
        cliente=cliente,
        entrega=entrega,
        envase_cilindro=None,
        documento_fiscal_ref=documento_fiscal_ref,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=observacao
    )

    # Sprint 5B.1: Recálculo incremental de diárias a partir da data da movimentação
    try:
        import zoneinfo
        from clientes.services import recalcular_diarias_posse
        tz_sp = zoneinfo.ZoneInfo('America/Sao_Paulo')
        dt_inicio = ocorrido_em.astimezone(tz_sp).date() if hasattr(ocorrido_em, 'astimezone') else timezone.now().astimezone(tz_sp).date()
        recalcular_diarias_posse(
            tenant_id=cilindro.tenant_id,
            data_inicio=dt_inicio,
            cliente_id=cliente.id if cliente else None
        )
    except Exception:
        pass

    return cilindro, movimentacao


@transaction.atomic
def enviar_para_reteste(*, cilindro_id, usuario, ocorrido_em, client_uuid, observacao=""):
    """
    Registra o envio de um cilindro para oficina ou prestador de teste hidrostático / manutenção.
    """
    # 1. Idempotência
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        return existing_mov.cilindro, existing_mov

    # 2. Trava de linha transacional
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)

    # 3. Validação de transição FSM
    validar_transicao_status_cilindro(cilindro, 'EM_RETESTE')

    if cilindro.cliente_posse_atual is not None:
        raise ValidationError(
            f"O cilindro {cilindro.numero_serie_ogiva} não pode ser enviado para reteste "
            f"pois ainda consta em posse do cliente {cilindro.cliente_posse_atual.nome}."
        )

    status_anterior = cilindro.status
    cilindro.status = 'EM_RETESTE'
    cilindro.save(update_fields=['status'])

    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='ENVIO_RETESTE',
        status_anterior=status_anterior,
        status_novo='EM_RETESTE',
        envase_cilindro=None,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=observacao
    )

    return cilindro, movimentacao


@transaction.atomic
def retornar_de_reteste(
    *,
    cilindro_id,
    nova_data_reteste,
    nova_data_proximo_reteste=None,
    nova_validade_anos=None,
    nova_tara_kg=None,
    usuario,
    ocorrido_em=None,
    client_uuid=None,
    observacao=""
):
    """
    Registra o retorno aprovado de um cilindro do teste hidrostático com atualização de datas normativas e tara.
    """
    if client_uuid is None:
        client_uuid = uuid.uuid4()
    if ocorrido_em is None:
        ocorrido_em = timezone.now()

    # 1. Idempotência
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        return existing_mov.cilindro, existing_mov

    # 2. Trava de linha transacional
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)

    # 3. Validação de transição FSM
    validar_transicao_status_cilindro(cilindro, 'VAZIO_TRIAGEM')

    if not nova_data_proximo_reteste:
        anos = nova_validade_anos or cilindro.modelo.periodicidade_reteste_anos
        try:
            nova_data_proximo_reteste = nova_data_reteste.replace(year=nova_data_reteste.year + anos)
        except ValueError:
            nova_data_proximo_reteste = nova_data_reteste + timedelta(days=anos * 365)

    status_anterior = cilindro.status
    cilindro.data_ultimo_reteste = nova_data_reteste
    cilindro.data_proximo_reteste = nova_data_proximo_reteste
    cilindro.status = 'VAZIO_TRIAGEM'
    update_fields = ['data_ultimo_reteste', 'data_proximo_reteste', 'status']

    if nova_tara_kg is not None:
        cilindro.tara_real_kg = nova_tara_kg
        update_fields.append('tara_real_kg')

    cilindro.save(update_fields=update_fields)

    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='RETORNO_RETESTE',
        status_anterior=status_anterior,
        status_novo='VAZIO_TRIAGEM',
        envase_cilindro=None,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=observacao or f"Retorno aprovado do reteste hidrostático. Próximo reteste: {nova_data_proximo_reteste.strftime('%d/%m/%Y')}."
    )

    return cilindro, movimentacao


@transaction.atomic
def estornar_movimentacao_ledger(*, movimentacao_id, usuario, justificativa):
    """
    Realiza o estorno auditado de uma movimentação do ledger imutável (Fase 1).
    Proíbe UPDATE/DELETE direto e anexa uma contra-partida (ESTORNO) apontando para estorna_movimentacao.
    Restaura atômica e seguramente a projeção do estado operacional do cilindro.
    Restrito a ADMIN, GERENTE e RESPONSAVEL_TECNICO.
    """
    if not usuario or not usuario.is_authenticated:
        raise PermissionError("Usuário não autenticado.")
    
    # Validação de perfil (ADMIN, GERENTE ou RT)
    from core.models import Membership
    membership = Membership.objects.filter(user=usuario, ativo=True).first()
    papel = membership.papel if membership else ('ADMIN' if usuario.is_superuser else None)
    if papel not in ('ADMIN', 'GERENTE', 'RESPONSAVEL_TECNICO') and not usuario.is_superuser:
        raise PermissionError("Apenas Administradores, Gerentes e Responsáveis Técnicos podem estornar movimentações no Ledger.")

    if not justificativa or not str(justificativa).strip():
        raise ValidationError("Justificativa técnica detalhada é obrigatória para estorno no Ledger.")

    mov = MovimentacaoCilindro.objects.select_for_update().get(id=movimentacao_id)

    if hasattr(mov, 'estornada_por') and mov.estornada_por is not None:
        raise ValidationError(f"A movimentação #{mov.id} já foi estornada anteriormente pela movimentação #{mov.estornada_por.id}.")

    if mov.tipo == 'ESTORNO':
        raise ValidationError("Não é permitido estornar uma movimentação que já é do tipo ESTORNO.")

    cilindro = Cilindro.objects.select_for_update().get(id=mov.cilindro_id)

    # Reversão de estado no cilindro
    status_anterior_reverso = mov.status_anterior
    cilindro.status = status_anterior_reverso

    if mov.tipo in ('ENTREGA_CLIENTE', 'SAIDA_ENTREGA'):
        cilindro.cliente_posse_atual = None
        cilindro.posse_desde = None
    elif mov.tipo in ('RECOLHA_CLIENTE', 'RETORNO_VAZIO'):
        cilindro.cliente_posse_atual = mov.cliente
        cilindro.posse_desde = mov.ocorrido_em
    elif mov.tipo == 'ENVASE':
        cilindro.envase_atual = None
    elif mov.tipo == 'RECEBIMENTO_FORNECEDOR':
        cilindro.recebimento_externo_atual = None

    cilindro.save()

    # Criação do registro de estorno no ledger imutável
    estorno_mov = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='ESTORNO',
        status_anterior=mov.status_novo,
        status_novo=status_anterior_reverso,
        cliente=mov.cliente,
        entrega=mov.entrega,
        ocorrido_em=timezone.now(),
        registrado_por=usuario,
        client_uuid=uuid.uuid4(),
        estorna_movimentacao=mov,
        lote_envase=mov.lote_envase,
        envase_cilindro=mov.envase_cilindro,
        recebimento_externo=mov.recebimento_externo,
        documento_fiscal_ref=mov.documento_fiscal_ref,
        observacao=f"Estorno da movimentação #{mov.id} ({mov.get_tipo_display()}): {justificativa.strip()}"
    )

    return cilindro, estorno_mov


@transaction.atomic
def alocar_cilindro_rota(*, cilindro_id, entrega, usuario, ocorrido_em, client_uuid, observacao=""):
    """
    Aloca um cilindro cheio para rota de entrega (CHEIO_DISPONIVEL -> RESERVADO_ROTA).
    """
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        return existing_mov.cilindro, existing_mov

    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)

    validar_transicao_status_cilindro(cilindro, 'RESERVADO_ROTA')

    # Trava Sanitária ANVISA: Bloqueio sanitário ativo impede expedição/rota
    if cilindro.bloqueio_sanitario:
        raise ValidationError(
            f"Bloqueio Sanitário ANVISA: O cilindro {cilindro.numero_serie_ogiva} está com bloqueio sanitário ativo: "
            f"{cilindro.motivo_bloqueio_sanitario or 'Quarentena/Reprovação física'}."
        )

    # Trava INMETRO: Reteste vencido impede expedição/rota
    if cilindro.reteste_vencido:
        raise ValidationError(
            f"Bloqueio de Segurança INMETRO: O cilindro {cilindro.numero_serie_ogiva} não pode ser reservado para rota "
            f"pois seu teste hidrostático venceu em {cilindro.data_proximo_reteste.strftime('%d/%m/%Y')}."
        )

    if not cilindro.carga_atual:
        raise ValidationError(
            f"Bloqueio Operacional: Cilindro {cilindro.numero_serie_ogiva} não possui envase ou recebimento de carga ativo para envio em rota."
        )

    # Trava de Qualidade de Lote (IN 129/2022): Lotes não aprovados não podem sair para entrega
    if cilindro.envase_atual and cilindro.envase_atual.lote.status_qualidade != 'APROVADO':
        raise ValidationError(
            f"Bloqueio de Qualidade: O lote {cilindro.envase_atual.lote.codigo_lote} está com status "
            f"'{cilindro.envase_atual.lote.get_status_qualidade_display()}' e não pode ser reservado para rota."
        )

    lote_codigo = (
        cilindro.envase_atual.lote.codigo_lote if cilindro.envase_atual
        else (cilindro.recebimento_externo_atual.lote_fornecedor if cilindro.recebimento_externo_atual else None)
    )

    status_anterior = cilindro.status
    cilindro.status = 'RESERVADO_ROTA'
    cilindro.save(update_fields=['status'])

    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='SAIDA_ROTA',
        status_anterior=status_anterior,
        status_novo='RESERVADO_ROTA',
        entrega=entrega,
        envase_cilindro=cilindro.envase_atual,
        recebimento_externo=cilindro.recebimento_externo_atual,
        lote_envase=lote_codigo,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=observacao
    )

    return cilindro, movimentacao


@transaction.atomic
def baixar_cilindro(*, cilindro_id, motivo, usuario, ocorrido_em, client_uuid):
    """
    Condena e dá baixa patrimonial definitiva em um cilindro (estado terminal BAIXADO).
    """
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        return existing_mov.cilindro, existing_mov

    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)

    validar_transicao_status_cilindro(cilindro, 'BAIXADO')

    status_anterior = cilindro.status
    cilindro.status = 'BAIXADO'
    cilindro.cliente_posse_atual = None
    cilindro.posse_desde = None
    cilindro.envase_atual = None
    cilindro.recebimento_externo_atual = None
    cilindro.save(update_fields=['status', 'cliente_posse_atual', 'posse_desde', 'envase_atual', 'recebimento_externo_atual'])

    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='BAIXA',
        status_anterior=status_anterior,
        status_novo='BAIXADO',
        envase_cilindro=None,
        recebimento_externo=None,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=motivo
    )

    return cilindro, movimentacao


@transaction.atomic
def receber_cilindro_cheio_fornecedor(
    *,
    cilindro=None,
    cilindro_id=None,
    fornecedor_nome=None,
    fornecedor_cnpj=None,
    nota_fiscal=None,
    lote_fornecedor=None,
    data_envase_origem=None,
    data_validade=None,
    pressao_bar=200,
    pressao_recebimento_bar=None,
    laudo_pdf=None,
    usuario=None,
    responsavel_recebimento=None,
    responsavel_tecnico=None,
    ocorrido_em=None,
    client_uuid=None,
    observacoes=""
):
    """
    Registra a entrada de cilindro já envasado vindo de fornecedor externo (RDC 887/2024 - Distribuidoras).
    Habilita a posterior entrega rastreável para distribuidoras que não envasam.
    """
    if cilindro is not None and cilindro_id is None:
        cilindro_id = cilindro.id
    if responsavel_recebimento is not None and usuario is None:
        usuario = responsavel_recebimento
    if pressao_recebimento_bar is not None:
        pressao_bar = pressao_recebimento_bar
    if client_uuid is None:
        client_uuid = uuid.uuid4()
    if ocorrido_em is None:
        ocorrido_em = timezone.now()

    # Normalização de datas (suporta str, date e datetime)
    if isinstance(data_validade, str):
        from datetime import datetime as dt
        try:
            data_validade = dt.strptime(data_validade.split('T')[0].strip(), '%Y-%m-%d').date()
        except ValueError:
            try:
                data_validade = dt.strptime(data_validade.strip(), '%d/%m/%Y').date()
            except ValueError:
                raise ValidationError("Formato de data_validade inválido. Utilize AAAA-MM-DD ou DD/MM/AAAA.")
    elif hasattr(data_validade, 'date'):
        data_validade = data_validade.date()

    if isinstance(data_envase_origem, str):
        from datetime import datetime as dt
        try:
            data_envase_origem = dt.strptime(data_envase_origem.split('T')[0].strip(), '%Y-%m-%d').date()
        except ValueError:
            try:
                data_envase_origem = dt.strptime(data_envase_origem.strip(), '%d/%m/%Y').date()
            except ValueError:
                pass
    elif hasattr(data_envase_origem, 'date'):
        data_envase_origem = data_envase_origem.date()

    # 1. Idempotência
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        recebimento = getattr(existing_mov.cilindro, 'recebimento_externo_atual', None)
        return existing_mov.cilindro, recebimento, existing_mov

    # 2. Trava de concorrência
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)

    # 3. FSM
    validar_transicao_status_cilindro(cilindro, 'CHEIO_DISPONIVEL')

    # 4. Trava INMETRO
    if cilindro.reteste_vencido:
        raise ValidationError(
            f"Bloqueio de Segurança INMETRO: O cilindro {cilindro.numero_serie_ogiva} não pode ser recebido "
            f"pois seu teste hidrostático venceu em {cilindro.data_proximo_reteste.strftime('%d/%m/%Y')}."
        )

    # 5. Trava Sanitária
    if cilindro.bloqueio_sanitario:
        raise ValidationError(
            f"Bloqueio Sanitário ANVISA: O cilindro {cilindro.numero_serie_ogiva} está com bloqueio sanitário ativo: "
            f"{cilindro.motivo_bloqueio_sanitario}."
        )

    # 6. Validade do lote do fornecedor
    if data_validade < timezone.now().date():
        raise ValidationError(
            f"Bloqueio Sanitário ANVISA: O lote do fornecedor {lote_fornecedor} está vencido desde {data_validade.strftime('%d/%m/%Y')}."
        )

    if cilindro.cliente_posse_atual is not None:
        raise ValidationError(
            f"O cilindro {cilindro.numero_serie_ogiva} não pode ser recebido pois consta em posse do cliente {cilindro.cliente_posse_atual.nome}."
        )

    # 7. Snapshot do RT
    rt_nome = responsavel_tecnico.nome_completo if responsavel_tecnico else None
    rt_reg = f"{responsavel_tecnico.conselho_classe}-{responsavel_tecnico.uf_conselho} {responsavel_tecnico.numero_registro}" if responsavel_tecnico else None

    # 8. Criar RecebimentoCilindroCheio
    recebimento = RecebimentoCilindroCheio.objects.create(
        cilindro=cilindro,
        fornecedor_nome=fornecedor_nome,
        fornecedor_cnpj=fornecedor_cnpj,
        nota_fiscal=nota_fiscal,
        lote_fornecedor=lote_fornecedor,
        data_envase_origem=data_envase_origem,
        data_validade=data_validade,
        pressao_recebimento_bar=pressao_bar,
        laudo_pdf=laudo_pdf,
        responsavel_recebimento=usuario,
        responsavel_tecnico=responsavel_tecnico,
        rt_nome_snapshot=rt_nome,
        rt_registro_snapshot=rt_reg,
        recebido_em=ocorrido_em,
        observacoes=observacoes
    )

    # 9. Atualizar estado do ativo
    status_anterior = cilindro.status
    cilindro.status = 'CHEIO_DISPONIVEL'
    cilindro.recebimento_externo_atual = recebimento
    cilindro.envase_atual = None
    cilindro.save(update_fields=['status', 'recebimento_externo_atual', 'envase_atual'])

    # 10. Ledger
    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='RECEBIMENTO_FORNECEDOR',
        status_anterior=status_anterior,
        status_novo='CHEIO_DISPONIVEL',
        recebimento_externo=recebimento,
        envase_cilindro=None,
        lote_envase=lote_fornecedor,
        documento_fiscal_ref=nota_fiscal,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=f"Recebimento de cilindro cheio do fornecedor {fornecedor_nome} (NF {nota_fiscal}, Lote {lote_fornecedor})."
    )

    return cilindro, recebimento, movimentacao


@transaction.atomic
def reclassificar_cilindro_gas(
    *,
    cilindro=None,
    cilindro_id=None,
    novo_gas=None,
    novo_gas_id=None,
    descontaminacao_purga_executada=False,
    troca_valvula_executada=False,
    pintura_adequada_abnt=False,
    adequacao_pintura_executada=False,
    nova_cor_padrao="",
    laudo_descontaminacao_pdf=None,
    laudo_descontaminacao=None,
    validade_estanqueidade=None,
    exigiu_novo_reteste=False,
    reteste_vinculado=None,
    reteste_vinculado_id=None,
    usuario=None,
    responsavel_tecnico=None,
    homologado_por_rt=None,
    ocorrido_em=None,
    client_uuid=None,
    observacoes=""
):
    """
    Realiza a reclassificação auditada de gás de um cilindro (Sprint 8B - Tarefa 8).
    Exige cumprimento das 3 etapas físicas (descontaminação/purga, troca de válvula e pintura),
    laudo técnico de descontaminação, teste de estanqueidade vigente e, caso exigido,
    comprovação de novo reteste hidrostático aprovado e vinculado.
    Se o novo gás for medicinal, exige homologação exclusiva do Responsável Técnico (CRF/CRQ).
    """
    if cilindro is not None and cilindro_id is None:
        cilindro_id = cilindro.id
    if novo_gas is not None and novo_gas_id is None:
        novo_gas_id = novo_gas.id
    if adequacao_pintura_executada and not pintura_adequada_abnt:
        pintura_adequada_abnt = adequacao_pintura_executada
    if homologado_por_rt is not None and responsavel_tecnico is None:
        responsavel_tecnico = homologado_por_rt
    if reteste_vinculado_id and not reteste_vinculado:
        from produtos.models import HistoricoRetesteHidrostatico
        reteste_vinculado = HistoricoRetesteHidrostatico.objects.get(id=reteste_vinculado_id)
    if client_uuid is None:
        client_uuid = uuid.uuid4()
    if ocorrido_em is None:
        ocorrido_em = timezone.now()

    arquivo_laudo = laudo_descontaminacao or laudo_descontaminacao_pdf

    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov:
        rec = ReclassificacaoCilindro.objects.filter(cilindro_id=cilindro_id).order_by('-realizado_em').first()
        return existing_mov.cilindro, rec, existing_mov

    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)
    gas_antigo = cilindro.gas_dedicado
    novo_gas = GasQuimico.objects.get(id=novo_gas_id)

    if gas_antigo.id == novo_gas.id:
        raise ValidationError(f"O cilindro {cilindro.numero_serie_ogiva} já está dedicado ao gás {novo_gas.sigla}.")

    if cilindro.status != 'VAZIO_TRIAGEM':
        raise ValidationError(
            f"O cilindro {cilindro.numero_serie_ogiva} deve estar em 'VAZIO_TRIAGEM' para reclassificação (status atual: {cilindro.status})."
        )

    if not (descontaminacao_purga_executada and troca_valvula_executada and pintura_adequada_abnt):
        raise ValidationError(
            "Reclassificação rejeitada: É obrigatório comprovar descontaminação e purga térmica/vácuo, "
            "substituição de válvula e adequação de pintura/cor padrão ABNT."
        )

    # Validação obrigatória de laudo técnico de descontaminação (Tarefa 8)
    if not arquivo_laudo:
        raise ValidationError(
            "Reclassificação bloqueada: O laudo/certificado de descontaminação é obrigatório para liberação do cilindro."
        )

    # Validação de ensaio de estanqueidade com validade vigente (Tarefa 8)
    hoje = timezone.localdate()
    if not validade_estanqueidade or validade_estanqueidade < hoje:
        raise ValidationError(
            "Reclassificação bloqueada: O ensaio de estanqueidade deve estar informado e com validade vigente."
        )

    # Validação de novo reteste vinculado caso exigido (Tarefa 8)
    if exigiu_novo_reteste:
        if not reteste_vinculado:
            raise ValidationError(
                "Reclassificação bloqueada: Esta operação exigiu novo reteste hidrostático, mas nenhum reteste foi vinculado."
            )
        if reteste_vinculado.cilindro_id != cilindro.id:
            raise ValidationError(
                f"Reclassificação bloqueada: O reteste vinculado (Cilindro #{reteste_vinculado.cilindro_id}) "
                f"não pertence a este cilindro ({cilindro.numero_serie_ogiva})."
            )
        if reteste_vinculado.resultado != 'APROVADO':
            raise ValidationError(
                f"Reclassificação bloqueada: O reteste vinculado deve estar APROVADO (resultado atual: {reteste_vinculado.resultado})."
            )

    # Exigência sanitária: aprovação exclusiva do Responsável Técnico se envolver gás medicinal
    is_medicinal = bool(novo_gas.exige_lote_anvisa or novo_gas.categoria == 'MEDICINAL')
    if is_medicinal:
        from core.models import Membership
        membership = Membership.objects.filter(user=usuario, tenant_id=cilindro.tenant_id, ativo=True).first()
        is_rt = bool((membership and membership.papel == 'RESPONSAVEL_TECNICO') or (usuario and usuario.is_superuser))
        if not is_rt:
            raise PermissionError(
                "Exigência Sanitária ANVISA: A reclassificação para gás medicinal exige aprovação "
                "e homologação exclusiva de um Responsável Técnico (CRF/CRQ)."
            )

    rt_nome = responsavel_tecnico.nome_completo if responsavel_tecnico else None
    rt_reg = f"{responsavel_tecnico.conselho_classe}-{responsavel_tecnico.uf_conselho} {responsavel_tecnico.numero_registro}" if responsavel_tecnico else None

    # Criar registro auditado
    reclassificacao = ReclassificacaoCilindro.objects.create(
        tenant=cilindro.tenant,
        cilindro=cilindro,
        gas_origem=gas_antigo,
        gas_destino=novo_gas,
        descontaminacao_purga_executada=descontaminacao_purga_executada,
        troca_valvula_executada=troca_valvula_executada,
        pintura_adequada_abnt=pintura_adequada_abnt,
        laudo_descontaminacao_pdf=arquivo_laudo,
        laudo_descontaminacao=arquivo_laudo,
        exigiu_novo_reteste=exigiu_novo_reteste,
        reteste_vinculado=reteste_vinculado,
        validade_estanqueidade=validade_estanqueidade,
        homologado_por_rt=responsavel_tecnico,
        rt_nome_snapshot=rt_nome,
        rt_registro_snapshot=rt_reg,
        executado_por=usuario,
        realizado_em=ocorrido_em,
        observacoes=observacoes
    )

    # Atualizar cilindro
    cilindro.gas_dedicado = novo_gas
    cilindro.envase_atual = None
    cilindro.recebimento_externo_atual = None
    cilindro.save(update_fields=['gas_dedicado', 'envase_atual', 'recebimento_externo_atual'])

    # Registrar no ledger
    movimentacao = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='RECLASSIFICACAO',
        status_anterior='VAZIO_TRIAGEM',
        status_novo='VAZIO_TRIAGEM',
        envase_cilindro=None,
        recebimento_externo=None,
        ocorrido_em=ocorrido_em,
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=f"Reclassificação de {gas_antigo.sigla} para {novo_gas.sigla}: laudo, estanqueidade e pintura homologados."
    )

    return cilindro, reclassificacao, movimentacao


# ==============================================================================
# 5. CONTENÇÃO, BLOQUEIO SANITÁRIO E GESTÃO DE RECALL
# ==============================================================================

def _verificar_permissao_rt(usuario, tenant_id=None):
    """
    Valida se o usuário possui autorização de Responsável Técnico (CRF/CRQ).
    Permitido apenas para usuários com Membership.papel == 'RESPONSAVEL_TECNICO' ou superusuários.
    """
    if not usuario:
        raise PermissionError("Usuário não fornecido.")
    if usuario.is_superuser:
        return True
    from core.models import Membership
    qs = Membership.objects.filter(user=usuario, ativo=True)
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    membership = qs.first()
    if membership and membership.papel == 'RESPONSAVEL_TECNICO':
        return True
    raise PermissionError("Ação restrita: Esta operação é privativa do Responsável Técnico (CRF/CRQ).")


def _obter_responsavel_tecnico(usuario, tenant_id=None, responsavel_tecnico=None):
    """
    Localiza o registro de Responsável Técnico formal associado ao usuário ou ao Tenant.
    """
    if responsavel_tecnico:
        return responsavel_tecnico
    from core.models import ResponsavelTecnico
    qs = ResponsavelTecnico.objects.filter(ativo=True)
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    if usuario and not usuario.is_superuser:
        rt_user = qs.filter(user=usuario).first()
        if rt_user:
            return rt_user
    return qs.first()


@transaction.atomic
def acionar_bloqueio_sanitario(
    *,
    cilindro=None,
    cilindro_id=None,
    motivo,
    usuario,
    responsavel_tecnico=None
):
    """
    Aciona o bloqueio sanitário ortogonal de um cilindro.
    Ação exclusiva do Responsável Técnico (CRF/CRQ) com gravação em trilha de auditoria imutável.
    Não altera o status operacional (pátio, rota ou cliente) do cilindro.
    """
    if cilindro is not None and cilindro_id is None:
        cilindro_id = cilindro.id
    if not motivo or not str(motivo).strip():
        raise ValidationError("Justificativa técnica é obrigatória para o bloqueio sanitário.")

    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)
    _verificar_permissao_rt(usuario, tenant_id=cilindro.tenant_id)

    rt = _obter_responsavel_tecnico(usuario, tenant_id=cilindro.tenant_id, responsavel_tecnico=responsavel_tecnico)
    rt_nome = rt.nome_completo if rt else (usuario.get_full_name() or usuario.username)
    rt_reg = f"{rt.conselho_classe}-{rt.uf_conselho} {rt.numero_registro}" if rt else "RT-SISTEMA"

    cilindro.bloqueio_sanitario = True
    cilindro.motivo_bloqueio_sanitario = motivo.strip()
    cilindro.save(update_fields=['bloqueio_sanitario', 'motivo_bloqueio_sanitario'])

    auditoria = AuditoriaBloqueioSanitario.objects.create(
        cilindro=cilindro,
        acao='BLOQUEIO',
        motivo=motivo.strip(),
        responsavel=usuario,
        responsavel_tecnico=rt,
        rt_nome_snapshot=rt_nome,
        rt_registro_snapshot=rt_reg
    )

    return cilindro, auditoria


@transaction.atomic
def liberar_bloqueio_sanitario(
    *,
    cilindro=None,
    cilindro_id=None,
    justificativa,
    usuario,
    responsavel_tecnico=None
):
    """
    Libera o bloqueio sanitário de um cilindro após quarentena, teste ou purga.
    Ação privativa do Responsável Técnico (CRF/CRQ) com justificativa registrada em auditoria.
    """
    if cilindro is not None and cilindro_id is None:
        cilindro_id = cilindro.id
    if not justificativa or not str(justificativa).strip():
        raise ValidationError("Justificativa técnica é obrigatória para a liberação sanitária.")

    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)
    _verificar_permissao_rt(usuario, tenant_id=cilindro.tenant_id)

    rt = _obter_responsavel_tecnico(usuario, tenant_id=cilindro.tenant_id, responsavel_tecnico=responsavel_tecnico)
    rt_nome = rt.nome_completo if rt else (usuario.get_full_name() or usuario.username)
    rt_reg = f"{rt.conselho_classe}-{rt.uf_conselho} {rt.numero_registro}" if rt else "RT-SISTEMA"

    cilindro.bloqueio_sanitario = False
    cilindro.motivo_bloqueio_sanitario = None
    cilindro.save(update_fields=['bloqueio_sanitario', 'motivo_bloqueio_sanitario'])

    auditoria = AuditoriaBloqueioSanitario.objects.create(
        cilindro=cilindro,
        acao='DESBLOQUEIO',
        motivo=justificativa.strip(),
        responsavel=usuario,
        responsavel_tecnico=rt,
        rt_nome_snapshot=rt_nome,
        rt_registro_snapshot=rt_reg
    )

    return cilindro, auditoria


@transaction.atomic
def atualizar_qualidade_lote(
    *,
    lote=None,
    lote_id=None,
    novo_status,
    justificativa="",
    usuario,
    responsavel_tecnico=None
):
    """
    Atualiza o status de controle de qualidade de um lote de envase (QUARENTENA, APROVADO, REPROVADO).
    Ação exclusiva do RT.
    Se o lote for REPROVADO, aciona automaticamente bloqueio sanitário em todos os cilindros
    cujo envase ativo pertença a esse lote.
    """
    if lote is not None and lote_id is None:
        lote_id = lote.id

    lote = LoteEnvase.objects.select_for_update().get(id=lote_id)
    _verificar_permissao_rt(usuario, tenant_id=lote.tenant_id)

    status_validos = [c[0] for c in LoteEnvase.STATUS_QUALIDADE_CHOICES]
    if novo_status not in status_validos:
        raise ValidationError(f"Status de qualidade inválido: '{novo_status}'. Válidos: {status_validos}")

    lote.status_qualidade = novo_status
    lote.save(update_fields=['status_qualidade'])

    # Se for REPROVADO, efetua bloqueio sanitário automático dos cilindros ativos desse lote
    if novo_status == 'REPROVADO':
        cilindros_ativos = Cilindro.objects.filter(
            envase_atual__lote=lote
        ).select_for_update()

        motivo_bloqueio = (
            f"Lote {lote.codigo_lote} REPROVADO pelo RT. "
            f"Justificativa: {justificativa or 'Desvio de conformidade físico-química'}"
        )

        for cil in cilindros_ativos:
            cil.bloqueio_sanitario = True
            cil.motivo_bloqueio_sanitario = motivo_bloqueio
            cil.save(update_fields=['bloqueio_sanitario', 'motivo_bloqueio_sanitario'])

            rt = _obter_responsavel_tecnico(usuario, tenant_id=cil.tenant_id, responsavel_tecnico=responsavel_tecnico)
            rt_nome = rt.nome_completo if rt else (usuario.get_full_name() or usuario.username)
            rt_reg = f"{rt.conselho_classe}-{rt.uf_conselho} {rt.numero_registro}" if rt else "RT-SISTEMA"

            AuditoriaBloqueioSanitario.objects.create(
                cilindro=cil,
                acao='BLOQUEIO',
                motivo=motivo_bloqueio,
                responsavel=usuario,
                responsavel_tecnico=rt,
                rt_nome_snapshot=rt_nome,
                rt_registro_snapshot=rt_reg
            )

    return lote


@transaction.atomic
def abrir_campanha_recall(
    *,
    lote=None,
    lote_id=None,
    codigo_campanha,
    motivo,
    texto_notificacao,
    usuario,
    responsavel_tecnico=None
):
    """
    Abre uma Campanha formal de Recall Sanitário para um Lote de Envase.
    Gera automaticamente os itens de recall divididos entre:
    1. Contenção Ativa: cilindros com carga ativa do lote em posse de clientes.
    2. Exposição Passada: clientes que receberam o lote no histórico, mesmo que já devolvido/consumido.
    """
    if lote is not None and lote_id is None:
        lote_id = lote.id

    lote = LoteEnvase.objects.get(id=lote_id)
    _verificar_permissao_rt(usuario, tenant_id=lote.tenant_id)

    campanha = RecallCampanha.objects.create(
        lote=lote,
        codigo_campanha=codigo_campanha.strip(),
        motivo=motivo.strip(),
        texto_notificacao=texto_notificacao.strip(),
        criado_por=usuario,
        status='ABERTO'
    )

    # 1. Cilindros com risco ativo atualmente em posse de clientes (Contenção Ativa)
    cilindros_em_clientes = Cilindro.objects.filter(
        envase_atual__lote=lote,
        status='EM_POSSE_CLIENTE',
        cliente_posse_atual__isnull=False
    ).select_related('cliente_posse_atual', 'envase_atual')

    cilindros_processados = set()
    for cil in cilindros_em_clientes:
        ItemRecallCliente.objects.create(
            campanha=campanha,
            cliente=cil.cliente_posse_atual,
            cilindro=cil,
            envase_cilindro=cil.envase_atual,
            tipo_exposicao='CONTENCAO_ATIVA',
            status_notificacao='PENDENTE'
        )
        cilindros_processados.add(cil.id)

    # 2. Histórico de entregas do ledger (Exposição Passada)
    entregas_historicas = MovimentacaoCilindro.objects.filter(
        tipo='ENTREGA_CLIENTE',
        envase_cilindro__lote=lote
    ).select_related('cliente', 'cilindro', 'envase_cilindro')

    for mov in entregas_historicas:
        if mov.cilindro_id not in cilindros_processados:
            ItemRecallCliente.objects.create(
                campanha=campanha,
                cliente=mov.cliente,
                cilindro=mov.cilindro,
                envase_cilindro=mov.envase_cilindro,
                tipo_exposicao='EXPOSICAO_PASSADA',
                status_notificacao='PENDENTE'
            )
            cilindros_processados.add(mov.cilindro_id)

    return campanha


@transaction.atomic
def homologar_campanha_recall(
    *,
    campanha=None,
    campanha_id=None,
    usuario,
    responsavel_tecnico=None
):
    """
    Homologa formalmente a campanha de recall pelo RT antes do disparo das notificações aos clientes.
    """
    if campanha is not None and campanha_id is None:
        campanha_id = campanha.id

    campanha = RecallCampanha.objects.select_for_update().get(id=campanha_id)
    _verificar_permissao_rt(usuario, tenant_id=campanha.tenant_id)

    rt = _obter_responsavel_tecnico(usuario, tenant_id=campanha.tenant_id, responsavel_tecnico=responsavel_tecnico)
    rt_nome = rt.nome_completo if rt else (usuario.get_full_name() or usuario.username)
    rt_reg = f"{rt.conselho_classe}-{rt.uf_conselho} {rt.numero_registro}" if rt else "RT-SISTEMA"

    campanha.status = 'HOMOLOGADO_RT'
    campanha.homologado_em = timezone.now()
    campanha.homologado_por_rt = rt
    campanha.rt_nome_snapshot = rt_nome
    campanha.rt_registro_snapshot = rt_reg
    campanha.save(update_fields=['status', 'homologado_em', 'homologado_por_rt', 'rt_nome_snapshot', 'rt_registro_snapshot'])

    return campanha


def obter_dossie_recall_lote(lote_codigo_ou_id, tenant_id=None):
    """
    Gera o Dossiê Completo de Rastreabilidade e Recall Sanitário, separando com precisão:
    1. Contenção Operacional (Risco Ativo): Cilindros fisicamente carregados com o lote alvo
       (em posse de hospitais, em trânsito ou no pátio com ação imediata necessária).
    2. Dossiê de Exposição Histórica: Todas as entregas passadas no Ledger vinculadas àquele lote,
       incluindo cascos já devolvidos vazios e reenvasados com outros lotes (zero falso positivo na contenção).
    """
    qs = LoteEnvase.objects.select_related('gas', 'responsavel_tecnico_fk')
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    if isinstance(lote_codigo_ou_id, int) or (isinstance(lote_codigo_ou_id, str) and lote_codigo_ou_id.isdigit()):
        lote = qs.filter(id=int(lote_codigo_ou_id)).first()
    else:
        lote = qs.filter(codigo_lote__iexact=str(lote_codigo_ou_id).strip()).first()

    if not lote:
        return None

    # 1. Contenção Operacional (Cilindros com carga física ativa pertencente a este lote)
    cilindros_ativos = Cilindro.objects.filter(
        envase_atual__lote=lote
    ).select_related(
        'gas_dedicado',
        'cliente_posse_atual',
        'modelo',
        'envase_atual__operador'
    ).order_by('-posse_desde')

    contencao_operacional = []
    for cil in cilindros_ativos:
        cliente = cil.cliente_posse_atual
        if cil.status == 'EM_POSSE_CLIENTE' and cliente:
            local_tipo = 'CLIENTE'
            local_descricao = f"Em posse do cliente: {cliente.nome}"
            acao = "RECOLHA_IMEDIATA_CLIENTE"
            cliente_info = {
                'id': cliente.id,
                'nome': cliente.nome,
                'cnpj': cliente.cnpj,
                'telefone': cliente.telefone,
                'endereco': f"{cliente.endereco}, {cliente.cidade} - {cliente.estado}"
            }
            posse_desde_str = cil.posse_desde.strftime('%d/%m/%Y %H:%M') if cil.posse_desde else 'N/A'
        elif cil.status == 'CHEIO_DISPONIVEL':
            local_tipo = 'PATIO'
            local_descricao = "Pátio Central (Cheio Disponível)"
            acao = "BLOQUEIO_SANIDAD_PATIO"
            cliente_info = None
            posse_desde_str = 'N/A'
        elif cil.status == 'RESERVADO_ROTA':
            local_tipo = 'ROTA'
            local_descricao = "Em Trânsito / Rota de Entrega"
            acao = "ABORTAR_ROTA_RETORNAR"
            cliente_info = None
            posse_desde_str = 'N/A'
        elif cil.status == 'VAZIO_TRIAGEM':
            local_tipo = 'PATIO_VAZIO'
            local_descricao = "Pátio (Vazio em Triagem)"
            acao = "ISOLAMENTO_PURGA"
            cliente_info = None
            posse_desde_str = 'N/A'
        elif cil.status == 'EM_RETESTE':
            local_tipo = 'RETESTE'
            local_descricao = "Oficina / Reteste Hidrostático"
            acao = "AVALIAR_MANUTENCAO"
            cliente_info = None
            posse_desde_str = 'N/A'
        else:
            local_tipo = 'OUTRO'
            local_descricao = cil.get_status_display()
            acao = "INSPECAO"
            cliente_info = None
            posse_desde_str = 'N/A'

        env = cil.envase_atual
        contencao_operacional.append({
            'cilindro_id': cil.id,
            'codigo_qr': cil.codigo_qr,
            'numero_serie_ogiva': cil.numero_serie_ogiva,
            'modelo': cil.modelo.descricao,
            'pressao_final_bar': env.pressao_final_bar if env else None,
            'envasado_em': env.envasado_em.strftime('%d/%m/%Y %H:%M') if env else 'N/A',
            'operador': env.operador.get_full_name() or env.operador.username if env and env.operador else 'N/A',
            'status_atual': cil.status,
            'status_atual_display': cil.get_status_display(),
            'bloqueio_sanitario': cil.bloqueio_sanitario,
            'motivo_bloqueio_sanitario': cil.motivo_bloqueio_sanitario,
            'is_envase_ativo': True,
            'local_tipo': local_tipo,
            'local_descricao': local_descricao,
            'acao_necessaria': acao,
            'cliente': cliente_info,
            'posse_desde': posse_desde_str
        })

    # 2. Dossiê de Exposição Histórica (Todas as entregas realizadas do lote via Ledger)
    entregas_ledger = MovimentacaoCilindro.objects.filter(
        tipo='ENTREGA_CLIENTE',
        envase_cilindro__lote=lote
    ).select_related(
        'cliente',
        'cilindro',
        'cilindro__modelo',
        'cilindro__envase_atual__lote',
        'envase_cilindro',
        'registrado_por'
    ).order_by('-ocorrido_em')

    exposicao_historica = []
    clientes_expostos_set = set()
    for mov in entregas_ledger:
        cli = mov.cliente
        cil = mov.cilindro
        if cli:
            clientes_expostos_set.add(cli.id)

        is_ativo_neste = bool(cil.envase_atual_id == mov.envase_cilindro_id)
        lote_atual = cil.envase_atual.lote.codigo_lote if cil.envase_atual else None

        exposicao_historica.append({
            'movimentacao_id': mov.id,
            'cilindro_id': cil.id,
            'codigo_qr': cil.codigo_qr,
            'numero_serie_ogiva': cil.numero_serie_ogiva,
            'modelo': cil.modelo.descricao,
            'cliente': {
                'id': cli.id if cli else None,
                'nome': cli.nome if cli else 'N/A',
                'cnpj': cli.cnpj if cli else 'N/A',
                'telefone': cli.telefone if cli else 'N/A',
                'endereco': f"{cli.endereco}, {cli.cidade} - {cli.estado}" if cli else 'N/A'
            },
            'data_entrega': mov.ocorrido_em.strftime('%d/%m/%Y %H:%M'),
            'documento_fiscal_ref': mov.documento_fiscal_ref or 'N/A',
            'operador': mov.registrado_por.get_full_name() or mov.registrado_por.username if mov.registrado_por else 'N/A',
            'status_atual_cilindro': cil.status,
            'status_atual_display': cil.get_status_display(),
            'is_envase_ativo': is_ativo_neste,
            'situacao_casco': 'COM_CARGA_LOTE_ALVO' if is_ativo_neste else 'CONSUMIDO_OU_REENVASADO',
            'lote_atual_cilindro': lote_atual
        })

    # 3. Lista completa de envases históricos para total compatibilidade retroativa
    todos_envases = lote.cilindros_envasados.select_related(
        'cilindro__gas_dedicado',
        'cilindro__cliente_posse_atual',
        'cilindro__modelo',
        'operador'
    ).order_by('-envasado_em')

    cilindros_data = []
    for env in todos_envases:
        cil = env.cilindro
        cliente = cil.cliente_posse_atual
        is_envase_ativo = (cil.envase_atual_id == env.id)

        if cil.status == 'EM_POSSE_CLIENTE' and cliente:
            local_tipo = 'CLIENTE'
            local_descricao = f"Em posse do cliente: {cliente.nome}"
            cliente_info = {
                'id': cliente.id,
                'nome': cliente.nome,
                'cnpj': cliente.cnpj,
                'telefone': cliente.telefone,
                'endereco': f"{cliente.endereco}, {cliente.cidade} - {cliente.estado}"
            }
            posse_desde_str = cil.posse_desde.strftime('%d/%m/%Y %H:%M') if cil.posse_desde else 'N/A'
        elif cil.status == 'CHEIO_DISPONIVEL':
            local_tipo = 'PATIO'
            local_descricao = "Pátio Central (Cheio Disponível)"
            cliente_info = None
            posse_desde_str = 'N/A'
        elif cil.status == 'RESERVADO_ROTA':
            local_tipo = 'ROTA'
            local_descricao = "Em Trânsito / Rota de Entrega"
            cliente_info = None
            posse_desde_str = 'N/A'
        elif cil.status == 'VAZIO_TRIAGEM':
            local_tipo = 'PATIO_VAZIO'
            local_descricao = "Pátio (Vazio em Triagem)"
            cliente_info = None
            posse_desde_str = 'N/A'
        elif cil.status == 'EM_RETESTE':
            local_tipo = 'RETESTE'
            local_descricao = "Oficina / Reteste Hidrostático"
            cliente_info = None
            posse_desde_str = 'N/A'
        else:
            local_tipo = 'OUTRO'
            local_descricao = cil.get_status_display()
            cliente_info = None
            posse_desde_str = 'N/A'

        cilindros_data.append({
            'envase_id': env.id,
            'cilindro_id': cil.id,
            'codigo_qr': cil.codigo_qr,
            'numero_serie_ogiva': cil.numero_serie_ogiva,
            'modelo': cil.modelo.descricao,
            'pressao_final_bar': env.pressao_final_bar,
            'envasado_em': env.envasado_em.strftime('%d/%m/%Y %H:%M'),
            'operador': env.operador.get_full_name() or env.operador.username,
            'status_atual': cil.status,
            'status_atual_display': cil.get_status_display(),
            'is_envase_ativo': is_envase_ativo,
            'local_tipo': local_tipo,
            'local_descricao': local_descricao,
            'cliente': cliente_info,
            'posse_desde': posse_desde_str
        })

    total_envasados = len(cilindros_data)
    total_em_clientes = sum(1 for c in contencao_operacional if c['local_tipo'] == 'CLIENTE')
    total_no_patio = sum(1 for c in contencao_operacional if 'PATIO' in c['local_tipo'])
    total_em_rota = sum(1 for c in contencao_operacional if c['local_tipo'] == 'ROTA')
    total_historico_encerrado = total_envasados - len(contencao_operacional)
    alerta_recall_ativo = (total_em_clientes > 0 or total_em_rota > 0)

    metricas = {
        'total_envasados': total_envasados,
        'total_contencao_ativa': len(contencao_operacional),
        'total_em_clientes': total_em_clientes,
        'total_no_patio': total_no_patio,
        'total_em_rota': total_em_rota,
        'total_ativos': len(contencao_operacional),
        'total_historico_encerrado': total_historico_encerrado,
        'total_entregas_historicas': len(exposicao_historica),
        'total_clientes_expostos': len(clientes_expostos_set),
        'alerta_recall_ativo': alerta_recall_ativo
    }

    lote_info = {
        'id': lote.id,
        'codigo_lote': lote.codigo_lote,
        'status_qualidade': lote.status_qualidade,
        'status_qualidade_display': lote.get_status_qualidade_display(),
        'gas_nome': lote.gas.nome,
        'gas_sigla': lote.gas.sigla,
        'categoria': lote.gas.categoria,
        'numero_onu': lote.gas.numero_onu,
        'classe_risco': lote.gas.classe_risco,
        'cor_padrao_abnt': lote.gas.cor_padrao_abnt,
        'data_envase': lote.data_envase.strftime('%d/%m/%Y'),
        'data_validade': lote.data_validade.strftime('%d/%m/%Y'),
        'pureza_percentual': float(lote.pureza_percentual),
        'responsavel_tecnico': lote.responsavel_tecnico,
        'rt_nome_snapshot': lote.rt_nome_snapshot,
        'esta_vencido': lote.esta_vencido,
        'normas_vigentes': "RDC nº 658/2022, IN nº 129/2022, RDC nº 870/2024, RDC nº 887/2024 (ANVISA) e Resolução CFF nº 731/2022",
        'laudo_url': lote.laudo_pdf.url if lote.laudo_pdf else None,
    }

    return {
        'lote': lote_info,
        'lote_obj': lote,
        'metricas': metricas,
        'contencao_operacional': contencao_operacional,
        'exposicao_historica': exposicao_historica,
        'cilindros': cilindros_data
    }


# ==============================================================================
# SINCRONIZAÇÃO EM LOTE OFFLINE (PWA FIELD OPERATION - SPRINT 6)
# ==============================================================================

def sincronizar_movimentacoes_offline(tenant_id, itens_sync, usuario):
    """
    Sincroniza em lote operações realizadas offline por motoristas e operadores de pátio (PWA).
    Garante:
    1. Idempotência estrita via `client_uuid`:
       Se o client_uuid já existir em MovimentacaoCilindro (unscoped), retorna sucesso
       com 'ja_processado' e o ID da movimentação já existente, sem duplicar registros no Ledger.
    2. Validações de segurança e sanitárias:
       - Para entregas ('ENTREGA_CLIENTE' ou 'entregar'):
         - Bloqueia cilindro com reteste vencido.
         - Bloqueia cilindro com bloqueio sanitário ativo.
         - Exige carga ativa aprovada e não vencida.
       - Para recolhas ('RECOLHA_CLIENTE' ou 'recolher'):
         - Permite recolha de casco divergente (cilindro diferente do entregue ou de outro cliente).
         - Permite recolha de cilindro com reteste vencido ou com bloqueio sanitário ativo (retorno para fábrica).
    3. Suporte a comprovante de entrega eletrônico com assinatura digital e hash SHA-256.
    """
    import base64
    from django.core.files.base import ContentFile
    from clientes.models import Cliente
    from logistica.models import Entrega, ComprovanteEntrega

    resultados = []
    total = len(itens_sync)
    processados = 0
    ja_existentes = 0
    erros = 0
    comprovantes_lote = {}

    for item in itens_sync:
        client_uuid_raw = item.get('client_uuid')
        if not client_uuid_raw:
            resultados.append({
                'client_uuid': None,
                'status': 'erro',
                'mensagem': 'Campo obrigatório "client_uuid" ausente no item de sincronização.'
            })
            erros += 1
            continue

        try:
            item_uuid = uuid.UUID(str(client_uuid_raw))
        except (ValueError, TypeError):
            resultados.append({
                'client_uuid': str(client_uuid_raw),
                'status': 'erro',
                'mensagem': f'Formato de "client_uuid" inválido: {client_uuid_raw}.'
            })
            erros += 1
            continue

        # 1. IDEMPOTÊNCIA ESTRITA
        existing_mov = MovimentacaoCilindro.unscoped.filter(
            tenant_id=tenant_id,
            client_uuid=item_uuid
        ).first()

        if existing_mov:
            resultados.append({
                'client_uuid': str(item_uuid),
                'status': 'ja_processado',
                'mensagem': 'Movimentação já processada anteriormente (idempotência preservada).',
                'movimentacao_id': existing_mov.id,
                'tipo': existing_mov.tipo,
                'cilindro_id': existing_mov.cilindro_id
            })
            ja_existentes += 1
            continue

        # 2. Processamento do item com savepoint individual
        try:
            with transaction.atomic():
                codigo_qr = item.get('codigo_qr')
                cilindro_id = item.get('cilindro_id')
                tipo_acao = str(item.get('tipo', '')).upper()
                cliente_id = item.get('cliente_id')
                entrega_id = item.get('entrega_id')
                ocorrido_em_raw = item.get('ocorrido_em')
                observacao = item.get('observacao', '')
                doc_fiscal = item.get('documento_fiscal_ref')

                # Parsing de data/hora
                if ocorrido_em_raw:
                    try:
                        from dateutil.parser import parse as parse_dt
                        ocorrido_em = parse_dt(str(ocorrido_em_raw))
                    except Exception:
                        ocorrido_em = timezone.now()
                else:
                    ocorrido_em = timezone.now()

                # Busca o cilindro
                cilindro = None
                if codigo_qr:
                    cilindro = Cilindro.unscoped.filter(tenant_id=tenant_id, codigo_qr=codigo_qr).first()
                elif cilindro_id:
                    cilindro = Cilindro.unscoped.filter(tenant_id=tenant_id, id=cilindro_id).first()

                if not cilindro:
                    raise ValidationError(f"Cilindro com QR '{codigo_qr}' ou ID '{cilindro_id}' não encontrado.")

                # Busca Cliente e Entrega
                cliente = Cliente.unscoped.filter(tenant_id=tenant_id, id=cliente_id).first() if cliente_id else None
                entrega = Entrega.unscoped.filter(tenant_id=tenant_id, id=entrega_id).first() if entrega_id else None

                if entrega and not cliente and entrega.vendas.exists():
                    cliente = entrega.vendas.first().cliente

                movimentacao = None

                # Ações de Entrega
                if tipo_acao in ['ENTREGA_CLIENTE', 'ENTREGAR', 'ENTREGA']:
                    if not cliente:
                        raise ValidationError("Cliente de destino obrigatório para efetuar entrega de cilindro.")

                    if cilindro.reteste_vencido:
                        raise ValidationError(
                            f"Bloqueio de Segurança: O cilindro {cilindro.numero_serie_ogiva} não pode ser entregue "
                            f"pois seu teste hidrostático venceu em {cilindro.data_proximo_reteste.strftime('%d/%m/%Y')}."
                        )

                    if cilindro.bloqueio_sanitario:
                        raise ValidationError(
                            f"Bloqueio Sanitário ANVISA: O cilindro {cilindro.numero_serie_ogiva} está com bloqueio sanitário ativo: "
                            f"{cilindro.motivo_bloqueio_sanitario or 'Quarentena/Reprovação física'}."
                        )

                    cil, movimentacao = registrar_entrega_cilindro(
                        cilindro_id=cilindro.id,
                        cliente=cliente,
                        entrega=entrega,
                        usuario=usuario,
                        ocorrido_em=ocorrido_em,
                        client_uuid=item_uuid,
                        documento_fiscal_ref=doc_fiscal
                    )


                    # Comprovante de entrega com assinatura eletrônica (1 Comprovante <-> N Movimentações - D8)
                    recebedor_nome = item.get('recebedor_nome')
                    recebedor_doc = item.get('recebedor_documento')
                    assinatura_base64 = item.get('assinatura_base64')
                    lat = item.get('latitude')
                    lng = item.get('longitude')
                    comp_key = item.get('comprovante_uuid') or (f"{entrega.id}_{cliente.id}_{recebedor_doc}" if (entrega and cliente and recebedor_doc) else None)

                    if recebedor_nome and entrega and (assinatura_base64 or item.get('assinatura_imagem')):
                        comprovante = comprovantes_lote.get(comp_key) if comp_key else None
                        if not comprovante:
                            doc_file = None
                            if assinatura_base64:
                                if ',' in assinatura_base64:
                                    assinatura_base64 = assinatura_base64.split(',', 1)[1]
                                img_data = base64.b64decode(assinatura_base64)
                                doc_file = ContentFile(img_data, name=f"assinatura_{item_uuid}.png")
                            elif item.get('assinatura_imagem'):
                                doc_file = item.get('assinatura_imagem')

                            if doc_file:
                                comprovante = ComprovanteEntrega.objects.create(
                                    tenant_id=tenant_id,
                                    entrega=entrega,
                                    movimentacao=movimentacao,
                                    recebedor_nome=recebedor_nome,
                                    recebedor_documento=recebedor_doc or 'N/A',
                                    assinatura_imagem=doc_file,
                                    timestamp_captura=ocorrido_em,
                                    latitude=lat,
                                    longitude=lng
                                )
                                comprovante.movimentacoes.add(movimentacao)
                                if comp_key:
                                    comprovantes_lote[comp_key] = comprovante
                        else:
                            comprovante.movimentacoes.add(movimentacao)

                    msg = f"Cilindro {cil.numero_serie_ogiva} ({cil.gas_dedicado.sigla}) entregue com sucesso em {cliente.nome}."

                # Ações de Recolha (Full-for-Empty / Casco divergente permitido)
                elif tipo_acao in ['RECOLHA_CLIENTE', 'RECOLHER', 'RECOLHA']:
                    cil, movimentacao = registrar_recolha_cilindro(
                        cilindro_id=cilindro.id,
                        cliente=cliente or cilindro.cliente_posse_atual,
                        entrega=entrega,
                        usuario=usuario,
                        ocorrido_em=ocorrido_em,
                        client_uuid=item_uuid,
                        observacao=observacao,
                        documento_fiscal_ref=doc_fiscal
                    )

                    # Se a recolha compartilhar o comprovante da parada, vincula a movimentação
                    comp_key = item.get('comprovante_uuid') or (f"{entrega.id}_{cliente.id}_{item.get('recebedor_documento')}" if (entrega and cliente and item.get('recebedor_documento')) else None)
                    if comp_key and comp_key in comprovantes_lote and movimentacao:
                        comprovantes_lote[comp_key].movimentacoes.add(movimentacao)

                    msg = f"Cilindro {cil.numero_serie_ogiva} recolhido vazio com sucesso."

                # Ações de Triagem de Pátio
                elif tipo_acao in ['TRIAGEM', 'VAZIO_TRIAGEM']:
                    if cilindro.status != 'VAZIO_TRIAGEM':
                        validar_transicao_status_cilindro(cilindro, 'VAZIO_TRIAGEM')
                        status_ant = cilindro.status
                        cilindro.status = 'VAZIO_TRIAGEM'
                        cilindro.save(update_fields=['status'])
                        movimentacao = MovimentacaoCilindro.objects.create(
                            tenant_id=tenant_id,
                            cilindro=cilindro,
                            tipo='RETORNO_VAZIO',
                            status_anterior=status_ant,
                            status_novo='VAZIO_TRIAGEM',
                            ocorrido_em=ocorrido_em,
                            registrado_por=usuario,
                            client_uuid=item_uuid,
                            observacao=observacao or "Triagem de pátio offline"
                        )
                    msg = f"Cilindro {cilindro.numero_serie_ogiva} conferido em triagem de pátio."
                else:
                    raise ValidationError(f"Tipo de movimentação '{tipo_acao}' não reconhecido.")

                resultados.append({
                    'client_uuid': str(item_uuid),
                    'status': 'sucesso',
                    'mensagem': msg,
                    'movimentacao_id': movimentacao.id if movimentacao else None,
                    'cilindro_id': cilindro.id
                })
                processados += 1

        except Exception as exc:
            resultados.append({
                'client_uuid': str(item_uuid),
                'status': 'erro',
                'mensagem': str(exc)
            })
            erros += 1

    return {
        'total': total,
        'processados': processados,
        'ja_existentes': ja_existentes,
        'erros': erros,
        'detalhes': resultados
    }


# ==============================================================================
# 6. ESTAÇÃO DE RAMPA EM BATELADA (IN 129/2022) E ENTRADA FORNECEDOR (RDC 887)
# ==============================================================================

def validar_cilindro_para_rampa(cilindro_ou_id_ou_qr, lote_id, tenant_id=None):
    """
    Valida em tempo real se um cilindro bipado pode ser acoplado à rampa de envase
    com o lote químico selecionado (IN 129/2022).
    Retorna uma tupla (valido: bool, motivo_invalido: str, cilindro: Cilindro, lote: LoteEnvase).
    """
    lote_qs = LoteEnvase.objects.select_related('gas')
    if tenant_id:
        lote_qs = lote_qs.filter(tenant_id=tenant_id)
    
    lote = lote_qs.filter(id=lote_id).first()
    if not lote:
        return False, "Lote de envase não encontrado.", None, None

    if lote.esta_vencido:
        return False, f"Lote {lote.codigo_lote} está vencido desde {lote.data_validade.strftime('%d/%m/%Y')}.", None, lote

    if lote.status_qualidade == 'REPROVADO':
        return False, f"Lote {lote.codigo_lote} está REPROVADO pelo RT e não pode ser envasado.", None, lote

    cil_qs = Cilindro.objects.select_related('gas_dedicado', 'modelo', 'cliente_posse_atual')
    if tenant_id:
        cil_qs = cil_qs.filter(tenant_id=tenant_id)

    if isinstance(cilindro_ou_id_ou_qr, Cilindro):
        cilindro = cilindro_ou_id_ou_qr
    elif isinstance(cilindro_ou_id_ou_qr, int) or (isinstance(cilindro_ou_id_ou_qr, str) and cilindro_ou_id_ou_qr.isdigit()):
        cilindro = cil_qs.filter(id=int(cilindro_ou_id_ou_qr)).first()
    else:
        termo = str(cilindro_ou_id_ou_qr).strip()
        cilindro = cil_qs.filter(
            models.Q(codigo_qr__iexact=termo) | models.Q(numero_serie_ogiva__iexact=termo)
        ).first()

    if not cilindro:
        return False, f"Cilindro '{cilindro_ou_id_ou_qr}' não encontrado no cadastro deste tenant.", None, lote

    # Validação 1: Reteste Hidrostático INMETRO
    if cilindro.reteste_vencido:
        return False, (
            f"Reteste hidrostático VENCIDO em {cilindro.data_proximo_reteste.strftime('%d/%m/%Y')}. "
            f"O cilindro {cilindro.numero_serie_ogiva} deve ser enviado para requalificação."
        ), cilindro, lote

    # Validação 2: Bloqueio Sanitário ANVISA
    if cilindro.bloqueio_sanitario:
        return False, (
            f"Bloqueio sanitário ativo no cilindro {cilindro.numero_serie_ogiva}: "
            f"{cilindro.motivo_bloqueio_sanitario or 'Quarentena pendente'}."
        ), cilindro, lote

    # Validação 3: Compatibilidade Química de Gás (ABNT NBR 12176)
    if cilindro.gas_dedicado_id != lote.gas_id:
        return False, (
            f"Incompatibilidade de Gás: Cilindro dedicado a {cilindro.gas_dedicado.sigla} ({cilindro.gas_dedicado.nome}) "
            f"não pode receber lote de {lote.gas.sigla} ({lote.gas.nome})."
        ), cilindro, lote

    # Validação 4: Posse Externa em Cliente
    if cilindro.cliente_posse_atual is not None:
        return False, (
            f"Cilindro {cilindro.numero_serie_ogiva} consta em posse externa do cliente "
            f"{cilindro.cliente_posse_atual.nome} e precisa ser recolhido antes do envase."
        ), cilindro, lote

    # Validação 5: Status FSM
    if cilindro.status not in ('VAZIO_TRIAGEM', 'EM_ENVASE'):
        return False, (
            f"Status incompatível: Cilindro {cilindro.numero_serie_ogiva} está como "
            f"'{cilindro.get_status_display()}' (esperado: Vazio em Triagem ou Em Envase)."
        ), cilindro, lote

    return True, "Cilindro apto para acoplamento na rampa de envase.", cilindro, lote


@transaction.atomic
def registrar_envase_batelada(
    *,
    lote_id,
    pressao_final_bar,
    itens,
    usuario,
    observacoes_batelada=""
):
    """
    Executa atomicamente a conclusão de uma batelada inteira de cilindros na rampa (IN 129/2022).
    Garante:
    - Trava transacional no lote químico e em todos os cilindros participantes.
    - Validação de checklist de cada item (se qualquer item estiver não-conforme, aborta a batelada).
    - Execução do envase atômico com emissão de inspeção e ledger para cada cilindro.
    """
    if not itens:
        raise ValidationError("A batelada de envase não contém cilindros acoplados.")

    lote = LoteEnvase.objects.select_for_update().get(id=lote_id)

    if lote.esta_vencido:
        raise ValidationError(f"O lote {lote.codigo_lote} está vencido desde {lote.data_validade.strftime('%d/%m/%Y')}.")

    if lote.status_qualidade == 'REPROVADO':
        raise ValidationError(f"O lote {lote.codigo_lote} está reprovado pelo RT e não pode ser envasado.")

    envases_criados = []
    movimentacoes_criadas = []
    agora = timezone.now()

    for idx, item in enumerate(itens, start=1):
        cilindro_id = item.get('cilindro_id')
        codigo_qr = item.get('codigo_qr')

        cil_qs = Cilindro.objects.select_for_update()
        if cilindro_id:
            cilindro = cil_qs.get(id=cilindro_id)
        elif codigo_qr:
            cilindro = cil_qs.get(codigo_qr__iexact=str(codigo_qr).strip())
        else:
            raise ValidationError(f"Item #{idx}: Identificador do cilindro não informado.")

        valvula_integra = bool(item.get('valvula_integra', True))
        pressao_residual_positiva = bool(item.get('pressao_residual_positiva', True))
        pintura_cor_padrao_ok = bool(item.get('pintura_cor_padrao_ok', True))
        rotulo_identificacao_ok = bool(item.get('rotulo_identificacao_ok', True))
        observacoes_inspecao = item.get('observacoes_inspecao', '')

        # Se algum item físico da IN 129 estiver não conforme, aborta a conclusão atômica
        if not (valvula_integra and pressao_residual_positiva and pintura_cor_padrao_ok and rotulo_identificacao_ok):
            raise ValidationError(
                f"Batelada Abortada: O cilindro {cilindro.numero_serie_ogiva} (Item #{idx}) apresentou não conformidade "
                f"no checklist IN 129/2022 e não pode ser envasado."
            )

        cil, envase, mov = registrar_envase_cilindro(
            cilindro=cilindro,
            lote=lote,
            pressao_final_bar=int(pressao_final_bar),
            usuario=usuario,
            valvula_integra=valvula_integra,
            pressao_residual_positiva=pressao_residual_positiva,
            pintura_cor_padrao_ok=pintura_cor_padrao_ok,
            rotulo_identificacao_ok=rotulo_identificacao_ok,
            observacoes_inspecao=observacoes_inspecao,
            observacoes_envase=observacoes_batelada,
            ocorrido_em=agora
        )
        envases_criados.append(envase)
        movimentacoes_criadas.append(mov)

    return lote, envases_criados, movimentacoes_criadas


@transaction.atomic
def receber_cilindros_fornecedor_batelada(
    *,
    cilindro_ids,
    fornecedor_nome,
    fornecedor_cnpj,
    nota_fiscal,
    lote_fornecedor,
    data_envase_origem,
    data_validade,
    pressao_recebimento_bar=200,
    laudo_pdf=None,
    usuario=None,
    responsavel_tecnico=None,
    observacoes=""
):
    """
    Registra a entrada atômica de múltiplos cilindros cheios vindos de fornecedor externo (RDC 887/2024).
    """
    if not cilindro_ids:
        raise ValidationError("Nenhum cilindro informado para o recebimento de fornecedor.")

    recebimentos = []
    movimentacoes = []
    agora = timezone.now()

    for cil_id in cilindro_ids:
        cil, rec, mov = receber_cilindro_cheio_fornecedor(
            cilindro_id=cil_id,
            fornecedor_nome=fornecedor_nome,
            fornecedor_cnpj=fornecedor_cnpj,
            nota_fiscal=nota_fiscal,
            lote_fornecedor=lote_fornecedor,
            data_envase_origem=data_envase_origem,
            data_validade=data_validade,
            pressao_recebimento_bar=pressao_recebimento_bar,
            laudo_pdf=laudo_pdf,
            usuario=usuario,
            responsavel_tecnico=responsavel_tecnico,
            ocorrido_em=agora,
            observacoes=observacoes
        )
        recebimentos.append(rec)
        movimentacoes.append(mov)

    return recebimentos, movimentacoes


# ==============================================================================
# SERVIÇOS DE PATRIMÔNIO, RETESTE E BAIXA (SPRINTS 8A E 8B)
# ==============================================================================
from produtos.services.indenizacao import calcular_indenizacao
from produtos.services.baixa import (
    baixar_cilindro_patrimonial,
    estornar_baixa,
    registrar_extravio,
)
from produtos.services.reteste import (
    enviar_cilindros_para_reteste,
    registrar_retorno_reteste,
    retificar_reteste,
)
