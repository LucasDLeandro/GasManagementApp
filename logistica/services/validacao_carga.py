import os
from decimal import Decimal
from datetime import timedelta
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from core.tenancy import get_current_tenant
from logistica.models import (
    ValidacaoCarga,
    ValidacaoCargaEvidencia,
    ConfiguracaoValidacaoCarga,
    Entrega
)
from vendas.models import ItemVenda, Venda
from produtos.models import Produto
from logistica.services import validar_capacidade_veiculo_entrega


def criar_validacao_carga(
    venda,
    produto,
    quantidade_conferida,
    motivo,
    categoria_item='Cheio',
    quantidade_esperada=None,
    justificativa='',
    etapa_logistica='Separação / Envase',
    entrega=None,
    criado_por=None,
    dispositivo_ip=None,
    valida_anterior=None,
    evidencias=None,
    fotos=None,
    autorizar_sobrecarga=False,
    justificativa_sobrecarga='',
    tenant=None
):
    """
    Registra uma validação de conferência de carga com cálculo automático de diferença,
    impacto financeiro, alçadas de aprovação e anexação segura de evidências.
    """
    tenant = tenant or get_current_tenant()
    evidencias = evidencias or fotos

    # Validação de Entrega concluída/cancelada
    if entrega and entrega.status in ['Concluída', 'Cancelada']:
        raise ValidationError("Não é permitido validar carga de entrega já concluída ou cancelada.")

    # Quantidade conferida não pode ser negativa
    qtd_conferida = Decimal(str(quantidade_conferida))
    if qtd_conferida < 0:
        raise ValidationError("A quantidade conferida não pode ser negativa.")

    # Se quantidade esperada não foi fornecida, busca no ItemVenda
    if quantidade_esperada is None:
        item = ItemVenda.objects.filter(venda=venda, produto=produto).first()
        qtd_esperada = Decimal(str(item.quantidade)) if item else Decimal('0.00')
    else:
        qtd_esperada = Decimal(str(quantidade_esperada))

    if qtd_esperada < 0:
        raise ValidationError("A quantidade esperada não pode ser negativa.")

    diferenca = qtd_conferida - qtd_esperada

    # Obtém preço unitário do item/produto para cálculo de valor de impacto
    item_venda = ItemVenda.objects.filter(venda=venda, produto=produto).first()
    preco_un = Decimal('0.00')
    if item_venda:
        preco_un = item_venda.preco_unitario_congelado or item_venda.valor_unitario or (produto.preco if produto else Decimal('0.00'))
    elif produto and produto.preco:
        preco_un = Decimal(str(produto.preco))

    valor_impacto = diferenca * preco_un

    # Carrega configurações de alçada do Tenant
    config = ConfiguracaoValidacaoCarga.get_para_tenant(tenant)

    # Validação de foto obrigatória para os motivos configurados
    motivos_foto = config.motivos_exigem_foto or ['Avaria no manuseio', 'Vazamento', 'Roubo/Extravio']
    tem_evidencias = bool(evidencias and len(evidencias) > 0)
    if motivo in motivos_foto and not tem_evidencias:
        raise ValidationError(f"O motivo '{motivo}' exige o envio obrigatório de ao menos uma foto/evidência comprobatória.")

    # Avaliação de Alçada de Aprovação
    excede_unidades = abs(diferenca) > config.limite_ajuste_sem_aprovacao_un
    excede_valor = abs(valor_impacto) > config.limite_valor_sem_aprovacao
    exige_aprovacao = excede_unidades or excede_valor

    if exige_aprovacao:
        status_inicial = 'Pendente de Aprovação'
        aprovado_por = None
        aprovado_em = None
        obs_aprovacao = None
    else:
        status_inicial = 'Aprovada'
        aprovado_por = criado_por
        aprovado_em = timezone.now()
        obs_aprovacao = "Aprovado automaticamente dentro dos limites de alçada."

    sugere_sinistro = motivo in ['Roubo/Extravio', 'Vazamento']

    with transaction.atomic():
        validacao = ValidacaoCarga(
            tenant=tenant,
            entrega=entrega or (venda.entrega if hasattr(venda, 'entrega') else None),
            venda=venda,
            produto=produto,
            quantidade_alterada=int(diferenca),
            etapa_logistica=etapa_logistica,
            justificativa=justificativa,
            motivo=motivo,
            categoria_item=categoria_item,
            quantidade_esperada=qtd_esperada,
            quantidade_conferida=qtd_conferida,
            diferenca=diferenca,
            valor_impacto=valor_impacto,
            status=status_inicial,
            exige_aprovacao=exige_aprovacao,
            aprovado_por=aprovado_por,
            aprovado_em=aprovado_em,
            observacao_aprovacao=obs_aprovacao,
            dispositivo_ip=dispositivo_ip,
            valida_anterior=valida_anterior,
            criado_por=criado_por,
            sugere_sinistro=sugere_sinistro
        )
        validacao.save()

        # Salva arquivos de evidência
        if evidencias:
            for ev_file in evidencias:
                ValidacaoCargaEvidencia.objects.create(
                    tenant=tenant,
                    validacao=validacao,
                    arquivo=ev_file,
                    descricao=f"Evidência motivo: {motivo}"
                )

        # Se já foi aprovada automaticamente, aplica os efeitos na mesma transação atômica
        if validacao.status == 'Aprovada':
            aplicar_efeitos_validacao(
                validacao,
                usuario_executor=criado_por,
                autorizar_sobrecarga=autorizar_sobrecarga,
                justificativa_sobrecarga=justificativa_sobrecarga
            )

    return validacao


def aprovar_validacao_carga(validacao, aprovador, observacao='', autorizar_sobrecarga=False, justificativa_sobrecarga=''):
    """
    Aprova uma validação de carga pendente, validando a regra de não auto-aprovação
    e aplicando todos os efeitos em transação atômica.
    """
    if validacao.status != 'Pendente de Aprovação':
        raise ValidationError(f"Apenas validações com status 'Pendente de Aprovação' podem ser aprovadas. Status atual: {validacao.status}.")

    # Regra de não auto-aprovação
    if validacao.criado_por and aprovador and validacao.criado_por_id == aprovador.id:
        raise ValidationError("O usuário criador da validação não possui permissão para aprovar o próprio ajuste (regra de segregação de funções).")

    with transaction.atomic():
        # Aplica os efeitos primeiro (estoque, peso/ANTT, pedido)
        aplicar_efeitos_validacao(
            validacao,
            usuario_executor=aprovador,
            autorizar_sobrecarga=autorizar_sobrecarga,
            justificativa_sobrecarga=justificativa_sobrecarga
        )

        validacao.status = 'Aprovada'
        validacao.aprovado_por = aprovador
        validacao.aprovado_em = timezone.now()
        validacao.observacao_aprovacao = observacao or "Validação aprovada pelo gestor."
        validacao.save(update_fields=['status', 'aprovado_por', 'aprovado_em', 'observacao_aprovacao'])

    return validacao


def rejeitar_validacao_carga(validacao, rejeitador, observacao=''):
    """
    Rejeita uma validação de carga pendente, sem aplicar alterações de estoque ou valor.
    """
    if validacao.status != 'Pendente de Aprovação':
        raise ValidationError(f"Apenas validações com status 'Pendente de Aprovação' podem ser rejeitadas. Status atual: {validacao.status}.")

    if validacao.criado_por and rejeitador and validacao.criado_por_id == rejeitador.id:
        raise ValidationError("O usuário criador da validação não pode deliberar sobre o próprio registro.")

    with transaction.atomic():
        validacao.status = 'Rejeitada'
        validacao.aprovado_por = rejeitador
        validacao.aprovado_em = timezone.now()
        validacao.observacao_aprovacao = observacao or "Validação rejeitada pelo gestor."
        validacao.save(update_fields=['status', 'aprovado_por', 'aprovado_em', 'observacao_aprovacao'])

    return validacao


def aplicar_efeitos_validacao(validacao, usuario_executor=None, autorizar_sobrecarga=False, justificativa_sobrecarga=''):
    """
    Aplica os efeitos da validação confirmada de forma atômica:
    1. Atualiza quantidade do item no pedido de venda e recalcula total.
    2. Valida capacidade de carga do veículo / ANTT em caso de ajuste positivo.
    3. Ajusta o estoque físico conforme a categoria (Cheio, Vazio, Casco) e motivo.
    """
    # 1. Atualizar item da venda
    item = ItemVenda.objects.filter(venda=validacao.venda, produto=validacao.produto).first()
    if item:
        nova_quantidade = item.quantidade + int(validacao.diferenca)
        if nova_quantidade < 0:
            raise ValidationError(f"A quantidade do item no pedido não pode ficar negativa ({nova_quantidade}).")
        item.quantidade = nova_quantidade
        item.save()
        validacao.venda.calcular_total()

    # 2. Recalcular peso da entrega e revalidar capacidade ANTT
    if validacao.entrega:
        entrega = validacao.entrega
        if validacao.diferenca > 0 and entrega.veiculo and entrega.veiculo.capacidade_carga:
            cap_max = float(entrega.veiculo.capacidade_carga)
            peso_atual = float(entrega.peso_total_carregado)
            if peso_atual > cap_max:
                if autorizar_sobrecarga:
                    if not justificativa_sobrecarga or len(justificativa_sobrecarga.strip()) < 10:
                        raise ValidationError("A liberação de sobrecarga ANTT exige justificativa técnica obrigatória de no mínimo 10 caracteres.")
                    from core.models import Membership
                    is_autorizado = bool(
                        usuario_executor and (
                            usuario_executor.is_staff or
                            usuario_executor.is_superuser or
                            usuario_executor.has_perm('logistica.change_entrega') or
                            Membership.objects.filter(tenant=validacao.tenant, user=usuario_executor, papel__in=['ADMIN', 'GERENTE'], ativo=True).exists()
                        )
                    )
                    if not is_autorizado:
                        raise ValidationError("Usuário não possui autorização gerencial para aprovar sobrecarga veicular ANTT.")
                else:
                    excesso = round(peso_atual - cap_max, 2)
                    raise ValidationError(
                        f"Capacidade de carga do veículo excedida! O peso total de {peso_atual:.2f} kg excede "
                        f"a capacidade máxima de {cap_max:.2f} kg do veículo {entrega.veiculo.placa} em {excesso:.2f} kg."
                    )

    # 3. Ajuste de estoque separando Cheio, Vazio e Casco
    produto = validacao.produto
    if produto:
        diferenca_int = int(validacao.diferenca)
        if validacao.categoria_item in ['Cheio', 'Outro']:
            if validacao.motivo in ['Avaria no manuseio', 'Vazamento', 'Roubo/Extravio']:
                # Baixa/Perda por dano ou extravio
                produto.estoque = max(0, produto.estoque - abs(diferenca_int))
                produto.save(update_fields=['estoque'])
            elif validacao.motivo == 'Produto devolvido':
                # Retorna ao estoque cheio
                produto.estoque += abs(diferenca_int)
                produto.save(update_fields=['estoque'])
            elif validacao.motivo in ['Erro de separação', 'Cliente recusou']:
                # Produto não embarcado ou devolvido permanece no estoque
                if diferenca_int < 0:
                    produto.estoque += abs(diferenca_int)
                else:
                    produto.estoque = max(0, produto.estoque - diferenca_int)
                produto.save(update_fields=['estoque'])
        elif validacao.categoria_item == 'Vazio (retorno)':
            # Vasilhame vazio recolhido registrado
            pass
        elif validacao.categoria_item == 'Casco novo':
            # Casco novo registrado
            pass


def obter_relatorio_divergencias(tenant, data_inicio=None, data_fim=None):
    """
    Consolida métricas e estatísticas de divergências de carga para análise gerencial:
    - Taxa de divergência por separador, motorista, rota e produto
    - Perdas financeiras no período
    - Motivos mais frequentes
    - Alertas de recorrência (mesmo motivo repetido N vezes nos últimos X dias)
    """
    qs = ValidacaoCarga.objects.filter(tenant=tenant)
    if data_inicio:
        qs = qs.filter(data_hora__date__gte=data_inicio)
    if data_fim:
        qs = qs.filter(data_hora__date__lte=data_fim)

    total_validacoes = qs.count()
    total_aprovadas = qs.filter(status='Aprovada').count()
    total_pendentes = qs.filter(status='Pendente de Aprovação').count()
    total_rejeitadas = qs.filter(status='Rejeitada').count()

    # Perdas financeiras (ajustes negativos que representam perda de produto/faturamento)
    perdas_qs = qs.filter(diferenca__lt=0)
    perdas_totais = sum(abs(v.valor_impacto) for v in perdas_qs)

    # Por Separador / Criador
    por_separador = []
    separador_agrupado = {}
    for v in qs.select_related('criado_por'):
        nome = v.criado_por.get_full_name() or v.criado_por.username if v.criado_por else "Sistema / Desconhecido"
        separador_agrupado.setdefault(nome, {'total': 0, 'valor': Decimal('0.00'), 'aprovadas': 0})
        separador_agrupado[nome]['total'] += 1
        separador_agrupado[nome]['valor'] += abs(v.valor_impacto)
        if v.status == 'Aprovada':
            separador_agrupado[nome]['aprovadas'] += 1

    for nome, dados in separador_agrupado.items():
        taxa = round((dados['total'] / total_validacoes * 100), 1) if total_validacoes > 0 else 0
        por_separador.append({
            'separador': nome,
            'total_ocorrencias': dados['total'],
            'taxa_percentual': taxa,
            'valor_impacto': float(dados['valor'])
        })
    por_separador.sort(key=lambda x: x['total_ocorrencias'], reverse=True)

    # Por Motorista
    por_motorista = []
    motorista_agrupado = {}
    for v in qs.select_related('entrega__motorista'):
        mot = v.entrega.motorista if (v.entrega and v.entrega.motorista) else None
        nome = mot.get_full_name() or mot.username if mot else "Sem Motorista Vinculado"
        motorista_agrupado.setdefault(nome, {'total': 0, 'valor': Decimal('0.00')})
        motorista_agrupado[nome]['total'] += 1
        motorista_agrupado[nome]['valor'] += abs(v.valor_impacto)

    for nome, dados in motorista_agrupado.items():
        taxa = round((dados['total'] / total_validacoes * 100), 1) if total_validacoes > 0 else 0
        por_motorista.append({
            'motorista': nome,
            'total_ocorrencias': dados['total'],
            'taxa_percentual': taxa,
            'valor_impacto': float(dados['valor'])
        })
    por_motorista.sort(key=lambda x: x['total_ocorrencias'], reverse=True)

    # Por Rota
    por_rota = []
    rota_agrupada = {}
    for v in qs.select_related('entrega__rota'):
        rota_nome = v.entrega.rota.nome if (v.entrega and v.entrega.rota) else "Rota Padrão / Avulsa"
        rota_agrupada.setdefault(rota_nome, {'total': 0, 'valor': Decimal('0.00')})
        rota_agrupada[rota_nome]['total'] += 1
        rota_agrupada[rota_nome]['valor'] += abs(v.valor_impacto)

    for nome, dados in rota_agrupada.items():
        taxa = round((dados['total'] / total_validacoes * 100), 1) if total_validacoes > 0 else 0
        por_rota.append({
            'rota': nome,
            'total_ocorrencias': dados['total'],
            'taxa_percentual': taxa,
            'valor_impacto': float(dados['valor'])
        })
    por_rota.sort(key=lambda x: x['total_ocorrencias'], reverse=True)

    # Por Produto
    por_produto = []
    produto_agrupado = {}
    for v in qs.select_related('produto'):
        prod_nome = v.produto.nome if v.produto else "Produto Desconhecido"
        produto_agrupado.setdefault(prod_nome, {'total': 0, 'qtd_divergente': Decimal('0.00'), 'valor': Decimal('0.00')})
        produto_agrupado[prod_nome]['total'] += 1
        produto_agrupado[prod_nome]['qtd_divergente'] += abs(v.diferenca)
        produto_agrupado[prod_nome]['valor'] += abs(v.valor_impacto)

    for nome, dados in produto_agrupado.items():
        taxa = round((dados['total'] / total_validacoes * 100), 1) if total_validacoes > 0 else 0
        por_produto.append({
            'produto': nome,
            'total_ocorrencias': dados['total'],
            'quantidade_divergente': float(dados['qtd_divergente']),
            'taxa_percentual': taxa,
            'valor_impacto': float(dados['valor'])
        })
    por_produto.sort(key=lambda x: x['total_ocorrencias'], reverse=True)

    # Motivos mais frequentes
    motivos_contagem = {}
    for v in qs:
        m = v.motivo or 'Outro'
        motivos_contagem.setdefault(m, {'contagem': 0, 'valor': Decimal('0.00')})
        motivos_contagem[m]['contagem'] += 1
        motivos_contagem[m]['valor'] += abs(v.valor_impacto)

    motivos_frequentes = [
        {
            'motivo': m,
            'contagem': dados['contagem'],
            'percentual': round((dados['contagem'] / total_validacoes * 100), 1) if total_validacoes > 0 else 0,
            'valor_impacto': float(dados['valor'])
        }
        for m, dados in motivos_contagem.items()
    ]
    motivos_frequentes.sort(key=lambda x: x['contagem'], reverse=True)

    # Alertas de Recorrência (mesmo motivo repetido 3 ou mais vezes nos últimos 15 dias)
    limite_data = timezone.now() - timedelta(days=15)
    recorrencias_qs = ValidacaoCarga.objects.filter(
        tenant=tenant,
        data_hora__gte=limite_data
    ).values('motivo', 'produto__nome').annotate(
        total_repeticoes=models.Count('id'),
        perda_acumulada=models.Sum('valor_impacto')
    ).filter(total_repeticoes__gte=3)

    alertas_recorrencia = []
    for r in recorrencias_qs:
        alertas_recorrencia.append({
            'motivo': r['motivo'],
            'produto': r['produto__nome'] or 'Geral',
            'ocorrencias_15_dias': r['total_repeticoes'],
            'perda_acumulada': float(abs(r['perda_acumulada'] or 0)),
            'nivel_alerta': 'Crítico' if r['total_repeticoes'] >= 5 else 'Atenção',
            'mensagem': f"Motivo '{r['motivo']}' ocorreu {r['total_repeticoes']}x nos últimos 15 dias no produto {r['produto__nome'] or 'Geral'}."
        })

    return {
        'total_validacoes': total_validacoes,
        'total_com_divergencia': total_validacoes,
        'total_aprovadas': total_aprovadas,
        'total_pendentes': total_pendentes,
        'total_rejeitadas': total_rejeitadas,
        'perdas_financeiras_reais': float(perdas_totais),
        'perdas_totais_reais': float(perdas_totais),
        'por_separador': por_separador,
        'por_motorista': por_motorista,
        'por_rota': por_rota,
        'por_produto': por_produto,
        'motivos_frequentes': motivos_frequentes,
        'alertas_recorrencia': alertas_recorrencia
    }
