import uuid
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from core.eventos import publicar
from produtos.models import (
    Cilindro,
    EnvioReteste,
    ItemEnvioReteste,
    HistoricoRetesteHidrostatico,
    MovimentacaoCilindro
)
from produtos.services.ciclo_cilindro import validar_transicao_status_cilindro
from produtos.services.baixa import baixar_cilindro_patrimonial


@transaction.atomic
def enviar_cilindros_para_reteste(
    *,
    tenant,
    oficina_nome,
    oficina_cnpj,
    cilindro_ids,
    data_envio=None,
    usuario=None,
    observacoes=""
):
    """
    Registra o envio em lote de cilindros para requalificação / ensaio hidrostático (Sprint 8B - Tarefa 3).
    Valida que todos os cilindros estejam em VAZIO_TRIAGEM e em posse física da empresa.
    Transita o status para 'EM_REQUALIFICACAO'.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'patrimonio')

    if not cilindro_ids:
        raise ValidationError("Selecione ao menos um cilindro para envio ao reteste hidrostático.")

    data_remessa = data_envio or timezone.localdate()

    envio = EnvioReteste.objects.create(
        tenant=tenant,
        oficina_nome=oficina_nome,
        oficina_cnpj=oficina_cnpj,
        data_envio=data_remessa,
        observacoes=observacoes,
        criado_por=usuario
    )

    cilindros_remetidos = []
    cilindros_qs = Cilindro.objects.select_for_update().filter(id__in=cilindro_ids, tenant=tenant)

    if cilindros_qs.count() != len(cilindro_ids):
        raise ValidationError("Um ou mais cilindros informados não foram encontrados ou pertencem a outro tenant.")

    for cil in cilindros_qs:
        if cil.status != 'VAZIO_TRIAGEM':
            raise ValidationError(
                f"O cilindro {cil.numero_serie_ogiva} não pode ser enviado para reteste pois seu "
                f"status atual é '{cil.get_status_display()}' (exige-se 'Vazio em Triagem')."
            )

        if cil.cliente_posse_atual is not None:
            raise ValidationError(
                f"O cilindro {cil.numero_serie_ogiva} está em posse do cliente {cil.cliente_posse_atual} "
                f"e não pode ser despachado para reteste."
            )

        status_anterior = cil.status
        validar_transicao_status_cilindro(cil, 'EM_REQUALIFICACAO')

        cil.status = 'EM_REQUALIFICACAO'
        cil.save(update_fields=['status'])

        ItemEnvioReteste.objects.create(
            tenant=tenant,
            envio=envio,
            cilindro=cil,
            status_anterior=status_anterior
        )

        MovimentacaoCilindro.objects.create(
            cilindro=cil,
            tipo='ENVIO_RETESTE',
            status_anterior=status_anterior,
            status_novo='EM_REQUALIFICACAO',
            envase_cilindro=None,
            recebimento_externo=None,
            ocorrido_em=timezone.now(),
            registrado_por=usuario,
            client_uuid=uuid.uuid4(),
            observacao=f"Despacho para reteste hidrostático na oficina {oficina_nome} (Envio #{envio.id})"
        )

        cilindros_remetidos.append(cil)

    return envio, cilindros_remetidos


@transaction.atomic
def registrar_retorno_reteste(
    *,
    tenant,
    cilindro_id,
    numero_certificado,
    data_execucao,
    oficina_nome,
    oficina_cnpj,
    registro_inmetro,
    pressao_teste_bar=None,
    expansao_total_cm3=None,
    expansao_permanente_cm3=None,
    tara_real_kg=None,
    resultado='APROVADO',
    data_proximo_reteste=None,
    periodicidade_anos=None,
    custo_servico_reteste=Decimal('0.00'),
    motivo_reprovacao="",
    observacoes="",
    usuario=None,
    client_uuid=None,
    envio_id=None
):
    """
    Processa o retorno técnico do reteste hidrostático de um cilindro (Sprint 8B - Tarefa 4).
    Garante atomicidade, idempotência pelo número do certificado e publicação do evento de domínio.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'patrimonio')

    # Idempotência por número de certificado e tenant
    historico_existente = HistoricoRetesteHidrostatico.objects.filter(
        tenant=tenant,
        numero_certificado=numero_certificado
    ).first()
    if historico_existente:
        return historico_existente.cilindro, historico_existente

    cilindro = Cilindro.objects.select_for_update().get(id=cilindro_id, tenant=tenant)

    # Conversão segura de valores físicos e monetários
    exp_total = Decimal(str(expansao_total_cm3)) if expansao_total_cm3 is not None else None
    exp_perm = Decimal(str(expansao_permanente_cm3)) if expansao_permanente_cm3 is not None else None
    tara_medida = quantize(Decimal(str(tara_real_kg)), Decimal('0.001')) if tara_real_kg is not None else None
    custo_reteste = quantize(Decimal(str(custo_servico_reteste)), Decimal('0.01'))

    # Cálculo da expansão permanente percentual e checagem de limite normativo
    exp_pct = None
    if exp_total and exp_perm and exp_total > Decimal('0.000'):
        exp_pct = quantize((exp_perm / exp_total) * Decimal('100.0'), Decimal('0.0001'))
        if exp_pct > Decimal('10.0000') and resultado == 'APROVADO':
            raise ValidationError(
                f"Reprovação mandatória (ABNT NBR 12274): Expansão permanente percentual de {exp_pct}% "
                f"supera o limite máximo de 10.0000%. O resultado do ensaio deve ser REPROVADO_CONDENADO."
            )

    status_anterior = cilindro.status
    alerta_tara = ""

    if resultado == 'APROVADO':
        validar_transicao_status_cilindro(cilindro, 'VAZIO_TRIAGEM')

        # Cálculo da data do próximo reteste
        if not data_proximo_reteste:
            anos = periodicidade_anos or getattr(cilindro.modelo, 'periodicidade_reteste_anos', None) or 5
            try:
                data_proximo_reteste = data_execucao.replace(year=data_execucao.year + anos)
            except ValueError:
                data_proximo_reteste = data_execucao + timedelta(days=anos * 365)

        # Checagem de variação de tara (tolerância padrão de 5%)
        tara_referencia = cilindro.tara_real_kg
        if tara_medida is not None and tara_referencia is not None and tara_referencia > Decimal('0.000'):
            var_tara = abs(tara_medida - tara_referencia) / tara_referencia
            if var_tara > Decimal('0.05'):
                alerta_tara = (
                    f" [ALERTA DE TARA: Variação de {quantize(var_tara * Decimal('100.0'), Decimal('0.01'))}% "
                    f"entre tara medida ({tara_medida} kg) e tara anterior ({tara_referencia} kg)]."
                )

        cilindro.status = 'VAZIO_TRIAGEM'
        cilindro.data_ultimo_reteste = data_execucao
        cilindro.data_proximo_reteste = data_proximo_reteste
        if tara_medida is not None:
            cilindro.tara_real_kg = tara_medida
        cilindro.save(update_fields=['status', 'data_ultimo_reteste', 'data_proximo_reteste', 'tara_real_kg'])

        MovimentacaoCilindro.objects.create(
            cilindro=cilindro,
            tipo='RETORNO_RETESTE',
            status_anterior=status_anterior,
            status_novo='VAZIO_TRIAGEM',
            envase_cilindro=None,
            recebimento_externo=None,
            ocorrido_em=timezone.now(),
            registrado_por=usuario,
            client_uuid=client_uuid or uuid.uuid4(),
            observacao=(
                f"Retorno aprovado de reteste hidrostático (Cert. {numero_certificado} - {oficina_nome}). "
                f"Próximo vencimento: {data_proximo_reteste.strftime('%d/%m/%Y')}.{alerta_tara}"
            )
        )

    elif resultado == 'REPROVADO_CONDENADO':
        motivo_final = motivo_reprovacao or f"Condenado no ensaio hidrostático (Certificado {numero_certificado})"
        baixar_cilindro_patrimonial(
            cilindro_id=cilindro.id,
            tipo='INUTILIZACAO_TECNICA',
            data_baixa=data_execucao,
            motivo=motivo_final,
            documento_ref=numero_certificado,
            usuario=usuario,
            client_uuid=client_uuid
        )

        cilindro.bloqueio_sanitario = True
        cilindro.motivo_bloqueio_sanitario = f"Condenado no ensaio hidrostático ({numero_certificado})"
        cilindro.save(update_fields=['bloqueio_sanitario', 'motivo_bloqueio_sanitario'])

    obs_final = (observacoes + alerta_tara).strip()

    historico = HistoricoRetesteHidrostatico.objects.create(
        tenant=tenant,
        cilindro=cilindro,
        origem_registro='REGISTRO',
        data_execucao=data_execucao,
        numero_certificado=numero_certificado,
        oficina_nome=oficina_nome,
        oficina_cnpj=oficina_cnpj,
        registro_inmetro=registro_inmetro,
        pressao_teste_bar=Decimal(str(pressao_teste_bar)) if pressao_teste_bar is not None else None,
        expansao_total_cm3=exp_total,
        expansao_permanente_cm3=exp_perm,
        expansao_permanente_percentual=exp_pct,
        tara_real_kg=tara_medida,
        resultado=resultado,
        motivo_reprovacao=motivo_reprovacao,
        data_proximo_reteste=data_proximo_reteste,
        custo_servico_reteste=custo_reteste,
        observacoes=obs_final,
        usuario=usuario
    )

    # Vincula o item do envio caso exista
    item_envio = None
    if envio_id:
        item_envio = ItemEnvioReteste.objects.filter(envio_id=envio_id, cilindro=cilindro, retornado=False).first()
    if not item_envio:
        item_envio = ItemEnvioReteste.objects.filter(cilindro=cilindro, retornado=False).order_by('-criado_em').first()

    if item_envio:
        item_envio.retornado = True
        item_envio.reteste_vinculado = historico
        item_envio.save(update_fields=['retornado', 'reteste_vinculado'])

    publicar('reteste_concluido', {
        'tenant': tenant,
        'cilindro_id': cilindro.id,
        'reteste_id': historico.id,
        'numero_certificado': numero_certificado,
        'resultado': resultado,
        'custo_servico_reteste': str(custo_reteste),
        'politica_reteste': 'DESPESA_CPV'
    })

    return cilindro, historico


@transaction.atomic
def retificar_reteste(
    *,
    reteste_anterior_id,
    novos_dados,
    usuario
):
    """
    Emite uma retificação formal imutável sobre um histórico de reteste anterior (Sprint 8B - Tarefa 2).
    """
    reteste_antigo = HistoricoRetesteHidrostatico.objects.select_for_update().get(id=reteste_anterior_id)
    assert_tenant_writable(reteste_antigo.tenant)
    assert_modulo(reteste_antigo.tenant, 'patrimonio')

    novo_reteste = HistoricoRetesteHidrostatico(
        tenant=reteste_antigo.tenant,
        cilindro=reteste_antigo.cilindro,
        origem_registro='REGISTRO',
        retifica=reteste_antigo,
        data_execucao=novos_dados.get('data_execucao', reteste_antigo.data_execucao),
        numero_certificado=novos_dados.get('numero_certificado', reteste_antigo.numero_certificado),
        oficina_nome=novos_dados.get('oficina_nome', reteste_antigo.oficina_nome),
        oficina_cnpj=novos_dados.get('oficina_cnpj', reteste_antigo.oficina_cnpj),
        registro_inmetro=novos_dados.get('registro_inmetro', reteste_antigo.registro_inmetro),
        pressao_teste_bar=novos_dados.get('pressao_teste_bar', reteste_antigo.pressao_teste_bar),
        expansao_total_cm3=novos_dados.get('expansao_total_cm3', reteste_antigo.expansao_total_cm3),
        expansao_permanente_cm3=novos_dados.get('expansao_permanente_cm3', reteste_antigo.expansao_permanente_cm3),
        tara_real_kg=novos_dados.get('tara_real_kg', reteste_antigo.tara_real_kg),
        resultado=novos_dados.get('resultado', reteste_antigo.resultado),
        motivo_reprovacao=novos_dados.get('motivo_reprovacao', reteste_antigo.motivo_reprovacao),
        data_proximo_reteste=novos_dados.get('data_proximo_reteste', reteste_antigo.data_proximo_reteste),
        custo_servico_reteste=novos_dados.get('custo_servico_reteste', reteste_antigo.custo_servico_reteste),
        observacoes=novos_dados.get('observacoes', f"Retificação formal do reteste #{reteste_antigo.id}."),
        usuario=usuario
    )
    novo_reteste.save()

    return novo_reteste
