import uuid
from decimal import Decimal
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.tenancy import get_current_tenant
from core.models import Membership
from logistica.models import (
    Veiculo,
    Entrega,
    OrdemServico,
    ApoliceSeguro,
    ApoliceCobertura,
    ApoliceVeiculo,
    ConfiguracaoSeguros,
    Sinistro,
    SinistroEvento,
    SinistroAnexo,
    SinistroItemCarga
)
from produtos.models import Produto


def criar_sinistro(
    tipo,
    descricao,
    data_hora=None,
    veiculo=None,
    motorista=None,
    entrega=None,
    apolice=None,
    latitude=None,
    longitude=None,
    endereco=None,
    terceiros=None,
    houve_vitimas=False,
    boletim_ocorrencia_numero='',
    valor_prejuizo_estimado=Decimal('0.00'),
    valor_franquia=Decimal('0.00'),
    status='Registrado',
    client_uuid=None,
    autor=None,
    tenant=None,
    itens_carga=None
):
    """
    Registra um sinistro de frota ou carga, inicializa a linha do tempo imutável,
    calcula prazos de comunicação com a seguradora e atualiza status do veículo quando aplicável.
    """
    tenant = tenant or get_current_tenant()
    data_hora = data_hora or timezone.now()

    # Idempotência para submissões offline do PWA
    if client_uuid:
        existente = Sinistro.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
        if existente:
            return existente

    # Se apólice não foi informada e há veículo, busca apólice ativa vinculada ao veículo
    if not apolice and veiculo:
        apolice_veic = ApoliceVeiculo.objects.filter(
            veiculo=veiculo,
            apolice__ativa=True,
            apolice__vigencia_fim__gte=data_hora.date()
        ).select_related('apolice').first()
        if apolice_veic:
            apolice = apolice_veic.apolice

    with transaction.atomic():
        sinistro = Sinistro(
            tenant=tenant,
            client_uuid=client_uuid,
            tipo=tipo,
            data_hora=data_hora,
            veiculo=veiculo,
            motorista=motorista or (autor if autor and autor.is_authenticated else None),
            entrega=entrega,
            apolice=apolice,
            latitude=latitude,
            longitude=longitude,
            endereco=endereco,
            terceiros=terceiros or {},
            houve_vitimas=houve_vitimas,
            boletim_ocorrencia_numero=boletim_ocorrencia_numero,
            descricao=descricao,
            status=status,
            valor_prejuizo_estimado=valor_prejuizo_estimado or Decimal('0.00'),
            valor_franquia=valor_franquia or Decimal('0.00'),
            criado_por=autor if autor and autor.is_authenticated else None
        )
        sinistro.save()

        # Criação do primeiro evento da linha do tempo
        nome_autor = (autor.get_full_name() or autor.username) if autor and autor.is_authenticated else "Sistema / PWA"
        SinistroEvento.objects.create(
            tenant=tenant,
            sinistro=sinistro,
            data_hora=timezone.now(),
            autor=autor if autor and autor.is_authenticated else None,
            tipo='Criação',
            status_anterior='',
            status_novo=sinistro.status,
            descricao=f"Sinistro {sinistro.numero} registrado pelo usuário {nome_autor}."
        )

        # Regra 2: Sinistro de veículo marca o veículo como Sinistrado (inapto)
        if tipo in ['Colisão', 'Tombamento', 'Incêndio', 'Roubo/Furto de Veículo', 'Vazamento de Produto'] and veiculo:
            veiculo.status = 'Sinistrado'
            veiculo.status_ativo = 'Sinistrado'
            veiculo.save(update_fields=['status', 'status_ativo'])

            SinistroEvento.objects.create(
                tenant=tenant,
                sinistro=sinistro,
                data_hora=timezone.now(),
                autor=autor if autor and autor.is_authenticated else None,
                tipo='Status Veículo',
                status_anterior='',
                status_novo='Sinistrado',
                descricao=f"Veículo {veiculo.placa} marcado como Sinistrado (inapto para operação) devido ao evento de {tipo}."
            )

        # Cadastro de itens de carga afetados se informados
        if itens_carga and isinstance(itens_carga, list):
            for it in itens_carga:
                prod_id = it.get('produto_id') or it.get('produto')
                prod = Produto.objects.filter(pk=prod_id, tenant=tenant).first()
                if prod:
                    qtd = int(it.get('quantidade', 1))
                    cat = it.get('categoria', 'Cheio')
                    preco = Decimal(str(it.get('valor_unitario') or prod.preco or '0.00'))
                    SinistroItemCarga.objects.create(
                        tenant=tenant,
                        sinistro=sinistro,
                        produto=prod,
                        quantidade=qtd,
                        categoria=cat,
                        valor_unitario=preco,
                        valor_total=qtd * preco
                    )

            sinistro.calcular_prejuizo_liquido()
            sinistro.save(update_fields=['prejuizo_liquido'])

    return sinistro


def transicionar_status_sinistro(
    sinistro,
    novo_status,
    autor,
    observacao='',
    protocolo=None,
    data_comunicacao=None,
    valor_indenizacao=None
):
    """
    Transiciona o status do sinistro, valida transições permitidas da máquina de estados,
    atualiza dados financeiros/protocolo e registra evento imutável na linha do tempo.
    """
    if sinistro.status == novo_status:
        return sinistro

    status_anterior = sinistro.status

    TRANSIÇÕES_PERMITIDAS = {
        'Rascunho': ['Registrado', 'Encerrado'],
        'Registrado': ['Comunicado à Seguradora', 'Em Análise', 'Encerrado'],
        'Comunicado à Seguradora': ['Em Análise', 'Em Vistoria', 'Negado', 'Encerrado'],
        'Em Análise': ['Em Vistoria', 'Aprovado', 'Negado'],
        'Em Vistoria': ['Em Análise', 'Aprovado', 'Negado'],
        'Aprovado': ['Indenizado', 'Encerrado'],
        'Negado': ['Em Análise', 'Encerrado'],
        'Indenizado': ['Encerrado'],
        'Encerrado': [],
    }

    permitidos = TRANSIÇÕES_PERMITIDAS.get(status_anterior, [])
    if novo_status not in permitidos:
        raise ValidationError(
            f"Transição de status inválida: não é permitido transicionar de '{status_anterior}' para '{novo_status}'. "
            f"Transições permitidas: {', '.join(permitidos) if permitidos else 'Nenhuma (status terminal)'}."
        )

    with transaction.atomic():
        sinistro.status = novo_status

        if protocolo:
            sinistro.protocolo_seguradora = protocolo

        if data_comunicacao:
            sinistro.data_comunicacao_seguradora = data_comunicacao
        elif novo_status == 'Comunicado à Seguradora' and not sinistro.data_comunicacao_seguradora:
            sinistro.data_comunicacao_seguradora = timezone.now()

        if valor_indenizacao is not None:
            sinistro.valor_indenizacao = Decimal(str(valor_indenizacao))

        sinistro.calcular_prejuizo_liquido()
        sinistro.save()

        # Registro na Linha do Tempo
        desc = observacao or f"Status do sinistro transicionado de '{status_anterior}' para '{novo_status}'."
        if protocolo:
            desc += f" Protocolo seguradora: {protocolo}."
        if valor_indenizacao:
            desc += f" Indenização acordada/recebida: R$ {Decimal(str(valor_indenizacao)):.2f}."

        SinistroEvento.objects.create(
            tenant=sinistro.tenant,
            sinistro=sinistro,
            data_hora=timezone.now(),
            autor=autor if autor and autor.is_authenticated else None,
            tipo='Mudança de Status',
            status_anterior=status_anterior,
            status_novo=novo_status,
            descricao=desc
        )

    return sinistro


def vincular_ou_criar_os_sinistro(
    sinistro,
    autor,
    descricao='',
    prioridade='Alta',
    imobiliza_veiculo=True,
    fornecedor=None
):
    """
    Cria e vincula uma Ordem de Serviço (OS) corretiva ao sinistro com 1 clique.
    Custos da OS vinculada entram automaticamente no cálculo de prejuízo do sinistro.
    """
    if not sinistro.veiculo:
        raise ValidationError("Não é possível gerar OS de manutenção para sinistro sem veículo associado.")

    with transaction.atomic():
        if sinistro.os_vinculada:
            os_obj = sinistro.os_vinculada
        else:
            desc_completa = descricao or (
                f"Reparos e vistorias corretivas decorrentes do Sinistro {sinistro.numero} "
                f"({sinistro.tipo}) em {sinistro.data_hora.strftime('%d/%m/%Y %H:%M')}.\n"
                f"Descrição da colisão/dano: {sinistro.descricao}"
            )

            os_obj = OrdemServico.objects.create(
                tenant=sinistro.tenant,
                veiculo=sinistro.veiculo,
                tipo='Corretiva',
                origem='Sinistro',
                sinistro_origem=sinistro,
                prioridade=prioridade,
                imobiliza_veiculo=imobiliza_veiculo,
                status='Aberta',
                descricao_problema=desc_completa,
                fornecedor=fornecedor,
                odometro_entrada=sinistro.veiculo.odometro_atual_km
            )

            sinistro.os_vinculada = os_obj

        sinistro.calcular_prejuizo_liquido()
        sinistro.save(update_fields=['os_vinculada', 'prejuizo_liquido'])

        SinistroEvento.objects.create(
            tenant=sinistro.tenant,
            sinistro=sinistro,
            data_hora=timezone.now(),
            autor=autor if autor and autor.is_authenticated else None,
            tipo='OS Vinculada',
            status_anterior='',
            status_novo=sinistro.status,
            descricao=f"Ordem de Serviço #{os_obj.numero} vinculada ao sinistro para orçamentação e reparo."
        )

    return sinistro, os_obj


def processar_ajuste_estoque_sinistro_carga(
    sinistro,
    autor,
    decisao_entrega='reentregar',
    justificativa=''
):
    """
    Gera ajuste físico de estoque para as perdas de carga do sinistro (Cheio, Vazio, Casco)
    e atualiza a entrega/venda associada conforme a decisão operacional (reentregar, cancelar, credito).
    Tudo em transação atômica.
    """
    itens_pendentes = sinistro.itens_carga.filter(ajuste_estoque_realizado=False)
    if not itens_pendentes.exists():
        raise ValidationError("Não há itens de carga pendentes de ajuste de estoque para este sinistro.")

    with transaction.atomic():
        for item in itens_pendentes:
            prod = item.produto
            # Baixa no estoque físico conforme categoria
            prod.estoque = max(0, prod.estoque - item.quantidade)
            prod.save(update_fields=['estoque'])

            item.ajuste_estoque_realizado = True
            item.save(update_fields=['ajuste_estoque_realizado'])

        # Decisão de contingência sobre a Entrega / Venda afetada
        if sinistro.entrega:
            entrega = sinistro.entrega
            if decisao_entrega == 'cancelar':
                entrega.status = 'Cancelada'
                entrega.save(update_fields=['status'])
                for v in entrega.vendas.exclude(status='Cancelada'):
                    v.status = 'Cancelada'
                    v.observacoes = (v.observacoes or '') + f"\n[Sinistro {sinistro.numero}]: Venda cancelada por perda integral da carga."
                    v.save(update_fields=['status', 'observacoes'])
            elif decisao_entrega == 'reentregar':
                entrega.status = 'Agendada'
                fields = ['status']
                obs_entrega = f"\n[Sinistro {sinistro.numero}]: Carga avariada abatida do estoque. Viagem reagendada para reposição."
                if hasattr(entrega, 'observacoes_logistica'):
                    entrega.observacoes_logistica = (getattr(entrega, 'observacoes_logistica', None) or '') + obs_entrega
                    fields.append('observacoes_logistica')
                elif hasattr(entrega, 'observacoes'):
                    entrega.observacoes = (getattr(entrega, 'observacoes', None) or '') + obs_entrega
                    fields.append('observacoes')
                entrega.save(update_fields=fields)
            elif decisao_entrega == 'credito':
                for v in entrega.vendas.exclude(status='Cancelada'):
                    obs_venda = f"\n[Crédito Sinistro {sinistro.numero}]: Registrado saldo credor ao cliente para abatimento financeiro."
                    v.observacoes = (v.observacoes or '') + obs_venda
                    v.save(update_fields=['observacoes'])

        # Recalcula prejuízo
        sinistro.calcular_prejuizo_liquido()
        sinistro.save(update_fields=['prejuizo_liquido'])

        # Registro na Linha do Tempo
        SinistroEvento.objects.create(
            tenant=sinistro.tenant,
            sinistro=sinistro,
            data_hora=timezone.now(),
            autor=autor if autor and autor.is_authenticated else None,
            tipo='Ajuste de Estoque',
            status_anterior='',
            status_novo=sinistro.status,
            descricao=(
                f"Baixa física de estoque realizada para {itens_pendentes.count()} item(ns) de carga. "
                f"Decisão de entrega: '{decisao_entrega}'. Justificativa: {justificativa or 'Conforme apuração do sinistro.'}"
            )
        )

    return sinistro


def liberar_veiculo_sinistrado(veiculo, gestor=None, observacao='', autor=None):
    """
    Retorna o veículo de 'Sinistrado' para 'Ativo' de forma explícita pelo gestor.
    Exige que não haja Ordem de Serviço (OS) imobilizante aberta.
    """
    gestor = gestor or autor
    if not gestor:
        raise ValidationError("Usuário gestor/autor é obrigatório para liberar veículo.")

    membership = Membership.objects.filter(tenant=veiculo.tenant, user=gestor, ativo=True).first()
    is_gestor = bool(gestor.is_superuser or (membership and membership.papel in ('ADMIN', 'GERENTE')))
    if not is_gestor:
        raise ValidationError("Apenas gestores com perfil ADMIN ou GERENTE possuem permissão para liberar veículo sinistrado.")

    # Verifica se há OS imobilizante aberta vinculada ao veículo
    os_imobilizante = OrdemServico.objects.filter(
        veiculo=veiculo,
        imobiliza_veiculo=True
    ).exclude(status__in=['Concluída', 'Cancelada']).first()
    if os_imobilizante:
        raise ValidationError(
            f"Não é possível liberar o veículo {veiculo.placa}: "
            f"existe a OS imobilizante #{os_imobilizante.numero} em andamento na oficina."
        )

    veiculo.status = 'Disponível'
    veiculo.status_ativo = 'Ativo'
    veiculo.save(update_fields=['status', 'status_ativo'])

    # Registra evento no sinistro ativo mais recente do veículo
    sinistro_recente = Sinistro.objects.filter(veiculo=veiculo).order_by('-data_hora').first()
    if sinistro_recente:
        SinistroEvento.objects.create(
            tenant=veiculo.tenant,
            sinistro=sinistro_recente,
            data_hora=timezone.now(),
            autor=gestor,
            tipo='Liberação Veículo',
            status_anterior='Sinistrado',
            status_novo='Ativo',
            descricao=f"Veículo {veiculo.placa} liberado para a frota ativa pelo gestor {gestor.get_full_name() or gestor.username}. Observação: {observacao or 'Inspeção e vistoria concluídas com êxito.'}"
        )

    return veiculo


def obter_indicadores_sinistralidade(tenant, data_inicio=None, data_fim=None):
    """
    Calcula indicadores consolidados de gestão de risco e sinistralidade:
    - Sinistros por status e tipo
    - Sinistralidade por 100.000 km rodados
    - Prejuízo estimado, franquias e prejuízo líquido
    - Tempo médio de resolução dos sinistros (dias)
    - Loss ratio (Sinistros / Prêmios) por apólice
    - Alertas de renovação de apólices e prazos de comunicação
    """
    qs_sinistros = Sinistro.objects.filter(tenant=tenant)
    qs_apolices = ApoliceSeguro.objects.filter(tenant=tenant)

    if data_inicio:
        qs_sinistros = qs_sinistros.filter(data_hora__date__gte=data_inicio)
        qs_apolices = qs_apolices.filter(vigencia_fim__gte=data_inicio)
    if data_fim:
        qs_sinistros = qs_sinistros.filter(data_hora__date__lte=data_fim)
        qs_apolices = qs_apolices.filter(vigencia_inicio__lte=data_fim)

    total_sinistros = qs_sinistros.count()
    total_prejuizo_estimado = sum((s.valor_prejuizo_estimado for s in qs_sinistros), Decimal('0.00'))
    total_franquia = sum((s.valor_franquia for s in qs_sinistros), Decimal('0.00'))
    total_indenizacoes = sum((s.valor_indenizacao for s in qs_sinistros), Decimal('0.00'))
    total_prejuizo_liquido = sum((s.prejuizo_liquido for s in qs_sinistros), Decimal('0.00'))

    # Tempo médio de resolução
    sinistros_resolvidos = qs_sinistros.filter(status__in=['Indenizado', 'Encerrado'])
    dias_totais_resolucao = 0
    count_resolvidos = 0
    for s in sinistros_resolvidos:
        diff_dias = (s.atualizado_em.date() - s.data_hora.date()).days
        dias_totais_resolucao += max(0, diff_dias)
        count_resolvidos += 1
    tempo_medio_resolucao_dias = round(dias_totais_resolucao / count_resolvidos, 1) if count_resolvidos > 0 else 0.0

    # Quilometragem total rodada no período para cálculo de sinistralidade por 100.000 km
    from logistica.models import Abastecimento, Entrega
    km_abastecimento = Decimal('0.00')
    abasts = Abastecimento.objects.filter(tenant=tenant)
    if data_inicio:
        abasts = abasts.filter(data_hora__date__gte=data_inicio)
    if data_fim:
        abasts = abasts.filter(data_hora__date__lte=data_fim)
    km_abastecimento = sum((a.km_percorridos for a in abasts if a.km_percorridos), Decimal('0.00'))

    # Fallback por distância planejada de entregas
    if km_abastecimento <= Decimal('0.00'):
        entregas_qs = Entrega.objects.filter(tenant=tenant, status='Concluída')
        km_abastecimento = sum((Decimal(str(e.rota.distancia_km)) for e in entregas_qs if e.rota and e.rota.distancia_km), Decimal('0.00'))

    km_total = float(km_abastecimento)
    taxa_sinistralidade_100k = round((total_sinistros * 100000.0 / km_total), 2) if km_total > 0 else 0.0

    # Relação Prêmio vs Indenizações (Loss Ratio)
    total_premios = sum((a.premio_total for a in qs_apolices), Decimal('0.00'))
    loss_ratio_pct = round((float(total_indenizacoes) / float(total_premios) * 100), 2) if total_premios > Decimal('0.00') else 0.0

    # Apólices por semáforo e alertas de renovação (60, 30, 15 dias)
    hoje = timezone.localdate()
    alertas_renovacao = []
    for ap in ApoliceSeguro.objects.filter(tenant=tenant, ativa=True):
        dias = ap.dias_para_vencimento
        if dias <= 60:
            alertas_renovacao.append({
                'apolice_id': ap.id,
                'seguradora': ap.seguradora,
                'numero_apolice': ap.numero_apolice,
                'tipo': ap.tipo,
                'dias_para_vencimento': dias,
                'status_vigencia': ap.status_vigencia,
                'semaforo': ap.semaforo_vigencia,
                'urgente': dias <= 30
            })

    # Alertas de comunicação de sinistro
    alertas_comunicacao = []
    for s in qs_sinistros.filter(status__in=['Rascunho', 'Registrado']):
        if s.prazo_comunicacao_urgente:
            alertas_comunicacao.append({
                'sinistro_id': s.id,
                'numero': s.numero,
                'tipo': s.tipo,
                'data_hora': s.data_hora.strftime('%d/%m/%Y %H:%M'),
                'expirado': s.prazo_comunicacao_expirado,
                'prazo_limite': s.prazo_limite_comunicacao.strftime('%d/%m/%Y %H:%M') if s.prazo_limite_comunicacao else 'N/D'
            })

    # Contagem por tipo e por status
    sinistros_por_tipo = {}
    for item in qs_sinistros.values('tipo').annotate(total=models.Count('id')):
        sinistros_por_tipo[item['tipo']] = item['total']

    sinistros_por_status = {}
    for item in qs_sinistros.values('status').annotate(total=models.Count('id')):
        sinistros_por_status[item['status']] = item['total']

    return {
        'total_sinistros': total_sinistros,
        'sinistros_por_status': sinistros_por_status,
        'sinistros_por_tipo': sinistros_por_tipo,
        'total_prejuizo_estimado': float(total_prejuizo_estimado),
        'total_franquia': float(total_franquia),
        'total_indenizacoes': float(total_indenizacoes),
        'total_indenizacoes_recebidas': Decimal(str(total_indenizacoes)),
        'total_prejuizo_liquido': float(total_prejuizo_liquido),
        'km_total_rodados': km_total,
        'taxa_sinistralidade_100k_km': taxa_sinistralidade_100k,
        'taxa_100k_km': taxa_sinistralidade_100k,
        'tempo_medio_resolucao_dias': tempo_medio_resolucao_dias,
        'total_premios_apolices': Decimal(str(total_premios)),
        'loss_ratio_percentual': loss_ratio_pct,
        'loss_ratio_global': loss_ratio_pct,
        'alertas_renovacao_apolices': alertas_renovacao,
        'alertas_comunicacao_sinistro': alertas_comunicacao
    }
