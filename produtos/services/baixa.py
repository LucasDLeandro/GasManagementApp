import uuid
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from core.eventos import publicar
from core.models import LogAuditoriaDados
from produtos.models import Cilindro, BaixaPatrimonial, MovimentacaoCilindro
from produtos.services import validar_transicao_status_cilindro
from produtos.services.indenizacao import calcular_indenizacao


@transaction.atomic
def baixar_cilindro_patrimonial(
    *,
    cilindro_id,
    tipo,
    data_baixa=None,
    motivo="",
    documento_ref="",
    valor_recebido=Decimal('0.00'),
    usuario=None,
    client_uuid=None
):
    """
    Executa a baixa patrimonial auditável de um cilindro (Sprint 8B - Tarefa 5).
    Registra snapshot do valor contábil líquido no momento da baixa, apura o resultado
    (ganho ou perda) e publica o evento 'baixa_patrimonial' para integração contábil.
    """
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)
    assert_tenant_writable(cilindro.tenant)
    assert_modulo(cilindro.tenant, 'patrimonio')

    if client_uuid is None:
        client_uuid = uuid.uuid4()

    # Idempotência
    existing_mov = MovimentacaoCilindro.objects.filter(client_uuid=client_uuid).first()
    if existing_mov and existing_mov.tipo == 'BAIXA':
        baixa_existente = BaixaPatrimonial.objects.filter(cilindro=cilindro, documento_ref=documento_ref).first()
        if baixa_existente:
            return cilindro, baixa_existente

    validar_transicao_status_cilindro(cilindro, 'BAIXADO')

    data_efetiva = data_baixa or timezone.localdate()
    vcl_snapshot = quantize(Decimal(str(cilindro.valor_contabil_liquido_atual)), Decimal('0.01'))
    val_recebido = quantize(Decimal(str(valor_recebido)), Decimal('0.01'))
    resultado_apurado = quantize(val_recebido - vcl_snapshot, Decimal('0.01'))

    status_anterior = cilindro.status
    cilindro.status = 'BAIXADO'
    cilindro.cliente_posse_atual = None
    cilindro.posse_desde = None
    cilindro.envase_atual = None
    cilindro.recebimento_externo_atual = None
    cilindro.save(update_fields=[
        'status', 'cliente_posse_atual', 'posse_desde', 'envase_atual', 'recebimento_externo_atual'
    ])

    baixa = BaixaPatrimonial.objects.create(
        tenant=cilindro.tenant,
        cilindro=cilindro,
        tipo=tipo,
        data=data_efetiva,
        valor_contabil_baixa=vcl_snapshot,
        valor_recebido=val_recebido,
        resultado=resultado_apurado,
        documento_ref=documento_ref,
        usuario=usuario,
        motivo=motivo,
        status_anterior=status_anterior,
    )

    MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='BAIXA',
        status_anterior=status_anterior,
        status_novo='BAIXADO',
        envase_cilindro=None,
        recebimento_externo=None,
        ocorrido_em=timezone.now(),
        registrado_por=usuario,
        client_uuid=client_uuid,
        observacao=motivo or f"Baixa patrimonial do tipo {tipo}. Ref: {documento_ref}"
    )

    publicar('baixa_patrimonial', {
        'tenant': cilindro.tenant,
        'cilindro_id': cilindro.id,
        'baixa_id': baixa.id,
        'tipo': tipo,
        'valor_contabil_baixa': str(vcl_snapshot),
        'valor_recebido': str(val_recebido),
        'resultado': str(resultado_apurado),
        'data': str(data_efetiva)
    })

    return cilindro, baixa


@transaction.atomic
def estornar_baixa(*, baixa_id, motivo, usuario):
    """
    Estorna uma baixa patrimonial operacional mediante permissão estrita 'produtos.estornar_baixa'
    (Sprint 8B - Tarefa 6). Restaura o cilindro ao status anterior de forma totalmente auditada.
    """
    baixa = BaixaPatrimonial.objects.select_for_update().get(id=baixa_id)
    assert_tenant_writable(baixa.tenant)
    assert_modulo(baixa.tenant, 'patrimonio')

    if not (usuario and (usuario.has_perm('produtos.estornar_baixa') or getattr(usuario, 'is_superuser', False))):
        raise PermissionError(
            "Permissão negada: o usuário não possui a permissão 'produtos.estornar_baixa' "
            "exigida para estornar baixas patrimoniais de cilindros."
        )

    if baixa.estornada:
        raise ValidationError("Esta baixa patrimonial já foi estornada anteriormente.")

    cilindro = Cilindro.objects.select_for_update().get(id=baixa.cilindro_id)
    status_restaurado = baixa.status_anterior if baixa.status_anterior != 'BAIXADO' else 'VAZIO_TRIAGEM'
    validar_transicao_status_cilindro(cilindro, status_restaurado, permitir_estorno_baixa=True)

    status_anterior = cilindro.status
    cilindro.status = status_restaurado
    cilindro.save(update_fields=['status'])

    agora = timezone.now()
    baixa.estornada = True
    baixa.data_estorno = agora
    baixa.motivo_estorno = motivo
    baixa.usuario_estorno = usuario
    baixa.save(update_fields=['estornada', 'data_estorno', 'motivo_estorno', 'usuario_estorno'])

    mov = MovimentacaoCilindro.objects.create(
        cilindro=cilindro,
        tipo='ESTORNO',
        status_anterior=status_anterior,
        status_novo=status_restaurado,
        envase_cilindro=None,
        recebimento_externo=None,
        ocorrido_em=agora,
        registrado_por=usuario,
        client_uuid=uuid.uuid4(),
        observacao=f"Estorno de baixa patrimonial #{baixa.id}: {motivo}"
    )

    from django.contrib.contenttypes.models import ContentType
    ct_baixa = ContentType.objects.get_for_model(BaixaPatrimonial)
    LogAuditoriaDados.objects.create(
        tenant=baixa.tenant,
        usuario=usuario,
        content_type=ct_baixa,
        object_id=str(baixa.id),
        acao="ESTORNO",
        diff_json={
            "dados_antes": {"status": status_anterior, "estornada": False},
            "dados_depois": {"status": status_restaurado, "estornada": True, "motivo": motivo}
        }
    )

    publicar('baixa_estornada', {
        'tenant': baixa.tenant,
        'cilindro_id': cilindro.id,
        'baixa_id': baixa.id,
        'motivo': motivo,
        'status_restaurado': status_restaurado
    })

    return cilindro, baixa, mov


@transaction.atomic
def registrar_extravio(
    *,
    cilindro_id,
    cliente=None,
    data=None,
    motivo="Extravio de cilindro",
    documento_ref="",
    usuario=None,
    client_uuid=None
):
    """
    Registra o extravio de um cilindro patrimonial (Sprint 8B - Tarefa 7 / Correção F-05).
    Aplica cálculo de indenização, cria a baixa patrimonial do tipo EXTRAVIO
    e publica o evento 'extravio_registrado' para o financeiro.
    """
    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id)
    assert_tenant_writable(cilindro.tenant)
    assert_modulo(cilindro.tenant, 'patrimonio')

    data_ref = data or timezone.localdate()
    res_indenizacao = calcular_indenizacao(cilindro, data_ref)

    cil, baixa = baixar_cilindro_patrimonial(
        cilindro_id=cilindro.id,
        tipo='EXTRAVIO',
        data_baixa=data_ref,
        motivo=motivo,
        documento_ref=documento_ref,
        valor_recebido=res_indenizacao['valor_contratual'],
        usuario=usuario,
        client_uuid=client_uuid
    )

    publicar('extravio_registrado', {
        'tenant': cilindro.tenant,
        'cilindro_id': cilindro.id,
        'baixa_id': baixa.id,
        'cliente_id': getattr(cliente, 'id', None) or cilindro.cliente_posse_atual_id,
        'data': str(data_ref),
        'valor_indenizacao': str(res_indenizacao['valor_contratual']),
        'valor_contabil': str(res_indenizacao['valor_contabil_liquido']),
        'ganho_perda': str(res_indenizacao['ganho_perda']),
        'is_fallback_contabil': res_indenizacao.get('sinalizado_fallback', False)
    })

    return cil, baixa, res_indenizacao
