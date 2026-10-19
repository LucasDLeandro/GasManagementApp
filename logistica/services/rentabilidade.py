import csv
import io
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from django.utils import timezone
from django.db import models
from django.db.models import Sum, Avg, Count, Q

from logistica.models import (
    Entrega,
    Rota,
    Veiculo,
    TabelaFrete,
    Abastecimento,
    PrecoCombustivelReferencia,
    ConfiguracaoCombustivelFrota,
    OrdemServico,
    ApoliceSeguro,
    ApoliceVeiculo,
    Sinistro,
    ConfiguracaoRentabilidade,
    CustoViagem,
    CustoViagemItem,
)
from logistica.services.combustivel import obter_preco_referencia_aplicavel


def estimar_custo_combustivel_pre_saida(entrega):
    """
    Calcula a estimativa prévia de combustível para uma entrega/romaneio antes da saída:
    custo_combustivel_estimado = (km_planejado ÷ consumo) × preco_referencia.
    Consumo: consumo médio real do veículo (L2), com fallback para consumo_referencia_km_l.
    Preço: PrecoCombustivelReferencia (ANP/manual) com fallback para último abastecimento.
    Retorna dicionário detalhado indicando os dados e fontes utilizados.
    """
    veiculo = entrega.veiculo
    rota = entrega.rota
    tenant = entrega.tenant

    # 1. Quilometragem planejada
    km_planejado = None
    if rota and rota.distancia_km and rota.distancia_km > Decimal('0.00'):
        km_planejado = rota.distancia_km
    elif hasattr(entrega, 'custo_viagem') and entrega.custo_viagem and entrega.custo_viagem.km_planejado:
        km_planejado = entrega.custo_viagem.km_planejado

    # 2. Consumo médio (km/l)
    consumo_usado = None
    fonte_consumo = "Sem histórico"

    if veiculo:
        # Busca consumo médio real apurado no histórico de abastecimentos (L2)
        ab_avg = Abastecimento.objects.filter(
            veiculo=veiculo,
            consumo_km_l__isnull=False,
            consumo_km_l__gt=Decimal('0.00')
        ).aggregate(media=Avg('consumo_km_l'))['media']

        if ab_avg and ab_avg > Decimal('0.00'):
            consumo_usado = Decimal(str(round(ab_avg, 2)))
            fonte_consumo = "Média Histórica Real (L2)"
        elif veiculo.consumo_referencia_km_l and veiculo.consumo_referencia_km_l > Decimal('0.00'):
            consumo_usado = veiculo.consumo_referencia_km_l
            fonte_consumo = "Consumo Referência Cadastral"

    # 3. Preço de referência do combustível
    preco_litro = None
    fonte_preco = "Não informada"
    data_preco = None

    tipo_combustivel = veiculo.combustivel_padrao if veiculo and veiculo.combustivel_padrao else 'Diesel S10'

    # Busca em PrecoCombustivelReferencia
    ref_preco = obter_preco_referencia_aplicavel(
        tenant=tenant,
        produto=tipo_combustivel,
        uf=getattr(veiculo, 'posto_uf', None) or 'GO'
    )

    if ref_preco and ref_preco.preco_medio and ref_preco.preco_medio > Decimal('0.0000'):
        preco_litro = ref_preco.preco_medio
        fonte_preco = f"ANP LPC - {ref_preco.produto} ({ref_preco.uf or 'BR'})"
        data_preco = ref_preco.data_final
    else:
        # Fallback: Último abastecimento registrado no veículo ou no tenant
        ab_last = Abastecimento.objects.filter(
            tenant=tenant,
            tipo_combustivel=tipo_combustivel,
            valor_litro__gt=Decimal('0.0000')
        ).order_by('-data_hora').first()

        if ab_last:
            preco_litro = ab_last.valor_litro
            fonte_preco = f"Último Abastecimento Real ({ab_last.tipo_combustivel})"
            data_preco = ab_last.data_hora.date()

    # 4. Cálculo final do custo estimado
    litros_estimados = Decimal('0.00')
    custo_estimado = None
    if km_planejado and consumo_usado and consumo_usado > Decimal('0.00') and preco_litro:
        litros_estimados = (km_planejado / consumo_usado).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        custo_estimado = (litros_estimados * preco_litro).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'custo_estimado': custo_estimado,
        'litros_estimados': litros_estimados,
        'km_planejado': km_planejado,
        'consumo_usado': consumo_usado,
        'consumo_km_l': consumo_usado,
        'fonte_consumo': fonte_consumo,
        'preco_litro': preco_litro,
        'fonte_preco': fonte_preco,
        'data_preco': data_preco,
        'tipo_combustivel': tipo_combustivel,
        'dados_completos': bool(km_planejado and consumo_usado and preco_litro)
    }


class RateiosViagem(tuple):
    """
    Estrutura que suporta desempacotamento por tupla (manut, deprec, seguro),
    acesso por chave de dicionário rateios['rateio_manutencao'] e acesso por atributo.
    """
    def __new__(cls, rateio_manutencao, rateio_depreciacao, rateio_seguro):
        return super().__new__(cls, (rateio_manutencao, rateio_depreciacao, rateio_seguro))

    @property
    def rateio_manutencao(self):
        return self[0]

    @property
    def rateio_depreciacao(self):
        return self[1]

    @property
    def rateio_seguro(self):
        return self[2]

    def __getitem__(self, item):
        if isinstance(item, str):
            mapping = {
                'rateio_manutencao': self[0],
                'rateio_depreciacao': self[1],
                'rateio_seguro': self[2]
            }
            if item in mapping:
                return mapping[item]
            raise KeyError(item)
        return super().__getitem__(item)

    def get(self, key, default=None):
        mapping = {
            'rateio_manutencao': self[0],
            'rateio_depreciacao': self[1],
            'rateio_seguro': self[2]
        }
        return mapping.get(key, default)


def calcular_rateios_viagem(entrega, km=None):
    """
    Calcula os 3 rateios operacionais da viagem:
    1. Manutenção: (Custo Total OS do veículo ÷ Km total rodado) × Km da viagem.
    2. Depreciação: ((FIPE × (1 - residual%)) ÷ vida_útil_anos ÷ km_anual_estimado) × Km da viagem.
    3. Seguro: Conforme método configurado (Km Rodado ou Dias de Operação).
    """
    veiculo = entrega.veiculo
    tenant = entrega.tenant
    config = ConfiguracaoRentabilidade.get_para_tenant(tenant)

    d_km = Decimal(str(km or Decimal('0.00')))
    if not veiculo or d_km <= Decimal('0.00'):
        return RateiosViagem(Decimal('0.00'), Decimal('0.00'), Decimal('0.00'))

    # 1. Rateio de Manutenção
    rateio_manutencao = Decimal('0.00')
    total_custo_os = OrdemServico.objects.filter(
        veiculo=veiculo,
        status='Concluída'
    ).aggregate(tot=Sum('custo_total'))['tot'] or Decimal('0.00')

    km_acumulado = veiculo.odometro_atual_km or Decimal('0.00')
    if km_acumulado <= Decimal('0.00'):
        km_acumulado = Abastecimento.objects.filter(veiculo=veiculo).aggregate(tot=Sum('km_rodados_desde_anterior'))['tot'] or Decimal('0.00')

    if km_acumulado > Decimal('0.00') and total_custo_os > Decimal('0.00'):
        custo_manut_por_km = total_custo_os / km_acumulado
        rateio_manutencao = (custo_manut_por_km * d_km).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 2. Rateio de Depreciação
    rateio_depreciacao = Decimal('0.00')
    fipe_val = veiculo.fipe_valor or Decimal('0.00')
    if fipe_val <= Decimal('0.00') and hasattr(veiculo, 'valores_fipe'):
        ultimo_fipe = veiculo.valores_fipe.order_by('-mes_referencia').first()
        if ultimo_fipe:
            fipe_val = ultimo_fipe.valor or Decimal('0.00')
    if fipe_val <= Decimal('0.00') and veiculo.valor_aquisicao:
        fipe_val = veiculo.valor_aquisicao

    if fipe_val > Decimal('0.00'):
        vida_util_anos = Decimal(str(config.vida_util_anos or 5))
        residual_pct = (config.percentual_residual or Decimal('20.00')) / Decimal('100.0')
        valor_depreciavel = fipe_val * (Decimal('1.00') - residual_pct)
        depreciacao_anual = valor_depreciavel / vida_util_anos
        km_anual = config.km_anual_estimado_veiculo or Decimal('60000.00')

        if km_anual > Decimal('0.00'):
            deprec_por_km = depreciacao_anual / km_anual
            rateio_depreciacao = (deprec_por_km * d_km).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 3. Rateio de Seguro
    rateio_seguro = Decimal('0.00')
    # Busca apólice associada ao veículo ou apólice de frota ativa
    apolice_v = ApoliceVeiculo.objects.filter(
        veiculo=veiculo,
        apolice__ativa=True
    ).select_related('apolice').first()

    apolice = apolice_v.apolice if apolice_v else ApoliceSeguro.objects.filter(
        tenant=tenant,
        ativa=True,
        tipo__icontains='Frota'
    ).first()

    if apolice and apolice.premio_total and apolice.premio_total > Decimal('0.00'):
        qtd_veiculos = max(1, apolice.veiculos_segurados.count())
        premio_veiculo = apolice.premio_total / Decimal(str(qtd_veiculos))

        if config.metodo_rateio_seguro == 'Km Rodado':
            km_anual = config.km_anual_estimado_veiculo or Decimal('60000.00')
            if km_anual > Decimal('0.00'):
                custo_seguro_km = premio_veiculo / km_anual
                rateio_seguro = (custo_seguro_km * d_km).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            # Dias de Operação
            dias_vigencia = max(1, (apolice.vigencia_fim - apolice.vigencia_inicio).days)
            custo_seguro_dia = premio_veiculo / Decimal(str(dias_vigencia))
            # Pelo menos 1 dia por viagem
            rateio_seguro = (custo_seguro_dia * Decimal('1.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return RateiosViagem(rateio_manutencao, rateio_depreciacao, rateio_seguro)


def apurar_receita_frete_entrega(entrega):
    """
    Obtém a receita do frete praticada para a entrega a partir da TabelaFrete existente.
    Não recalcula regra de frete caso a entrega/custo já tenha receita definida.
    Se a venda já embute frete, preserva o valor negociado.
    """
    # 1. Se a entrega possui rota, busca tabela de frete da rota
    tf = None
    if entrega.rota:
        tf = TabelaFrete.objects.filter(tenant=entrega.tenant, rota=entrega.rota).first()
    if not tf:
        tf = TabelaFrete.objects.filter(tenant=entrega.tenant, rota__isnull=True).first()

    if not tf:
        return Decimal('0.00')

    if tf.tipo_cobranca == 'Fixo':
        return tf.valor or Decimal('0.00')
    elif tf.tipo_cobranca == 'Distancia':
        dist = entrega.rota.distancia_km if (entrega.rota and entrega.rota.distancia_km) else Decimal('0.00')
        return ((tf.valor or Decimal('0.00')) * dist).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    elif tf.tipo_cobranca == 'Peso':
        peso = Decimal(str(entrega.peso_total_carregado or 0.0))
        return ((tf.valor or Decimal('0.00')) * peso).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return Decimal('0.00')


def verificar_alerta_averbacao(entrega):
    """
    Compara o valor total da carga transportada na entrega com o limite máximo de averbação
    por viagem da apólice de seguro de carga vigente (RCTR-C / RC-DC da L5).
    Retorna: (tem_alerta: bool, motivo: str, valor_carga: Decimal)
    """
    valor_carga = sum(
        (v.valor_total for v in entrega.vendas.exclude(status='Cancelada')),
        Decimal('0.00')
    )

    apolice_carga = ApoliceSeguro.objects.filter(
        tenant=entrega.tenant,
        ativa=True,
        tipo__in=['Carga RCTR-C', 'Desvio de Carga RC-DC']
    ).first()

    if not apolice_carga:
        return (
            True,
            "Não há apólice ativa de seguro de carga (RCTR-C / RC-DC) cadastrada para cobrir esta viagem.",
            valor_carga
        )

    if apolice_carga.limite_maximo_por_viagem and valor_carga > apolice_carga.limite_maximo_por_viagem:
        diff = valor_carga - apolice_carga.limite_maximo_por_viagem
        return (
            True,
            f"Valor da carga (R$ {valor_carga:,.2f}) ultrapassa o limite de averbação / garantia máxima por viagem "
            f"(R$ {apolice_carga.limite_maximo_por_viagem:,.2f}) da apólice {apolice_carga.numero_apolice} em R$ {diff:,.2f}.",
            valor_carga
        )

    return False, "", valor_carga


def verificar_alerta_baixa_ocupacao(entrega):
    """
    Verifica se a rota da entrega apresenta histórico recorrente de baixa ocupação
    (média de lotação abaixo de 50% por N viagens seguidas).
    Retorna: (tem_alerta: bool, motivo: str)
    """
    if not entrega.rota:
        return False, ""

    config = ConfiguracaoRentabilidade.get_para_tenant(entrega.tenant)
    limite_viagens = config.viagens_baixa_ocupacao_alerta or 3
    lotacao_minima = config.media_lotacao_alerta_minima or Decimal('50.00')

    # Busca as últimas viagens concluídas na mesma rota
    ultimas_entregas = list(
        Entrega.objects.filter(
            tenant=entrega.tenant,
            rota=entrega.rota,
            status='Concluída'
        ).exclude(id=entrega.id).order_by('-data_saida', '-id')[:limite_viagens]
    )

    if len(ultimas_entregas) >= limite_viagens:
        soma_lot = sum(Decimal(str(e.percentual_lotacao or 0.0)) for e in ultimas_entregas)
        media_lot = (soma_lot / Decimal(str(len(ultimas_entregas)))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

        if media_lot < lotacao_minima:
            return (
                True,
                f"Alerta de Baixa Ocupação: As últimas {len(ultimas_entregas)} viagens nesta rota registraram "
                f"lotação média de {media_lot}% (abaixo de {int(lotacao_minima)}% / patamar econômico de {lotacao_minima}%). Sugere-se consolidação de cargas."
            )

    return False, ""


def consolidar_custo_viagem(entrega, forcar_recalculo=False, congelar=False):
    """
    Consolida todos os custos reais, estimados, rateios e margem da viagem/romaneio.
    Se o snapshot estiver congelado e não houver flag de forçar recálculo, preserva o estado imutável.
    Se congelar=True, marca o registro como snapshot final imutável.
    """
    custo, _ = CustoViagem.objects.get_or_create(
        tenant=entrega.tenant,
        entrega=entrega
    )

    if custo.snapshot_congelado and not forcar_recalculo:
        return custo

    # 1. Estimativa pré-saída
    est = estimar_custo_combustivel_pre_saida(entrega)
    custo.combustivel_estimado = est['custo_estimado'] or Decimal('0.00')
    custo.combustivel_estimado_fonte_preco = est['fonte_preco'] or ''
    custo.combustivel_estimado_data_preco = est['data_preco']
    custo.combustivel_estimado_consumo_usado = est['consumo_usado']
    custo.combustivel_estimado_preco_litro = est['preco_litro']
    custo.km_planejado = est['km_planejado']

    # 2. Ocupação e Alertas
    custo.ocupacao_viagem_pct = Decimal(str(entrega.percentual_lotacao or 0.0))
    alerta_av, mot_av, val_carga = verificar_alerta_averbacao(entrega)
    custo.alerta_averbacao = alerta_av
    custo.motivo_alerta_averbacao = mot_av
    custo.valor_carga_transportada = val_carga

    alerta_baixa, mot_baixa = verificar_alerta_baixa_ocupacao(entrega)
    custo.alerta_baixa_ocupacao = alerta_baixa
    custo.motivo_baixa_ocupacao = mot_baixa

    # 3. Receita de Frete
    if not custo.receita_frete or custo.receita_frete == Decimal('0.00'):
        custo.receita_frete = apurar_receita_frete_entrega(entrega)

    # 4. Km Real
    if not custo.km_real:
        # Tenta extrair dos abastecimentos vinculados à entrega
        km_abast = entrega.abastecimentos.filter(
            km_rodados_desde_anterior__isnull=False,
            km_rodados_desde_anterior__gt=0
        ).aggregate(tot=Sum('km_rodados_desde_anterior'))['tot']

        if km_abast and km_abast > 0:
            custo.km_real = Decimal(str(km_abast))
        elif custo.km_planejado:
            custo.km_real = custo.km_planejado

    # 5. Combustível Real
    if not custo.combustivel_real or custo.combustivel_real == Decimal('0.00'):
        if entrega.abastecimentos.exists():
            custo.combustivel_real = sum(
                (ab.valor_total for ab in entrega.abastecimentos.all()),
                Decimal('0.00')
            )
        elif custo.km_real and est['consumo_usado'] and est['consumo_usado'] > Decimal('0.00') and est['preco_litro']:
            # Rateio baseado no km real × preço
            litros_reais = custo.km_real / est['consumo_usado']
            custo.combustivel_real = (litros_reais * est['preco_litro']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 6. Rateios (Manutenção, Depreciação e Seguro)
    km_calc = custo.km_real or custo.km_planejado or Decimal('0.00')
    r_manut, r_deprec, r_seg = calcular_rateios_viagem(entrega, km=km_calc)
    custo.rateio_manutencao = r_manut
    custo.rateio_depreciacao = r_deprec
    custo.rateio_seguro = r_seg

    # 7. Itens avulsos (Pedágios, Diárias, etc.)
    custo.recalcular_itens_avulsos()

    # 8. Verificação de Dados Incompletos ("sem dados" vs zero enganoso)
    sem_km = (custo.km_real is None or custo.km_real <= Decimal('0.00')) and (custo.km_planejado is None or custo.km_planejado <= Decimal('0.00'))
    sem_abast = not entrega.abastecimentos.exists() and (custo.combustivel_real == Decimal('0.00'))
    if sem_km and sem_abast:
        custo.dados_incompletos = True
        custo.motivo_dados_incompletos = "Sem quilometragem registrada e sem abastecimentos para cálculo real de combustível."
    else:
        custo.dados_incompletos = False
        custo.motivo_dados_incompletos = ""

    # 9. Totais e Margens
    custo.calcular_totais()

    # 10. Snapshot de Conclusão
    if congelar or entrega.status == 'Concluída':
        custo.snapshot_congelado = True

    custo.save()
    return custo


def obter_indicadores_rentabilidade(tenant, data_inicio=None, data_fim=None, agrupar_por='rota'):
    """
    Consolida indicadores de rentabilidade por período com agrupamento dinâmico:
    agrupar_por: 'rota' | 'veiculo' | 'cliente' | 'motorista'.
    Retorna métricas consolidadas e itens agrupados.
    """
    qs = CustoViagem.objects.filter(tenant=tenant).select_related(
        'entrega',
        'entrega__rota',
        'entrega__veiculo',
        'entrega__motorista'
    ).prefetch_related('entrega__vendas', 'entrega__vendas__cliente')

    if data_inicio:
        qs = qs.filter(entrega__data_saida__date__gte=data_inicio)
    if data_fim:
        qs = qs.filter(entrega__data_saida__date__lte=data_fim)

    total_viagens = qs.count()
    receita_total = qs.aggregate(t=Sum('receita_frete'))['t'] or Decimal('0.00')
    custo_total = qs.aggregate(t=Sum('custo_total_real'))['t'] or Decimal('0.00')
    margem_total = receita_total - custo_total

    km_total = qs.aggregate(t=Sum('km_real'))['t'] or Decimal('0.00')
    custo_por_km = (custo_total / km_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if km_total > Decimal('0.00') else Decimal('0.00')
    custo_por_entrega = (custo_total / Decimal(str(total_viagens))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if total_viagens > 0 else Decimal('0.00')

    margem_pct = ((margem_total / receita_total) * Decimal('100.0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if receita_total > Decimal('0.00') else Decimal('0.00')
    ocupacao_media = qs.aggregate(m=Avg('ocupacao_viagem_pct'))['m'] or Decimal('0.00')
    ocupacao_media = Decimal(str(round(ocupacao_media, 1)))

    # Agrupamentos
    itens_map = {}

    for cv in qs:
        chave = None
        nome = "Não identificado"

        if agrupar_por == 'rota':
            if cv.entrega.rota:
                chave = cv.entrega.rota.id
                nome = cv.entrega.rota.nome
            else:
                chave = 0
                nome = "Sem Rota Definida"
        elif agrupar_por == 'veiculo':
            if cv.entrega.veiculo:
                chave = cv.entrega.veiculo.id
                nome = f"{cv.entrega.veiculo.placa} ({cv.entrega.veiculo.modelo})"
            else:
                chave = 0
                nome = "Sem Veículo"
        elif agrupar_por == 'motorista':
            if cv.entrega.motorista:
                chave = cv.entrega.motorista.id
                nome = cv.entrega.motorista.get_full_name() or cv.entrega.motorista.username
            else:
                chave = 0
                nome = "Sem Motorista"
        elif agrupar_por == 'cliente':
            # Pega o primeiro cliente vinculado às vendas da entrega
            venda = cv.entrega.vendas.first()
            if venda and venda.cliente:
                chave = venda.cliente.id
                nome = venda.cliente.nome
            else:
                chave = 0
                nome = "Cliente Indefinido"

        if chave not in itens_map:
            itens_map[chave] = {
                'id': chave,
                'nome': nome,
                'viagens': 0,
                'km_total': Decimal('0.00'),
                'receita': Decimal('0.00'),
                'custo': Decimal('0.00'),
                'margem': Decimal('0.00'),
                'margem_pct': Decimal('0.00'),
                'custo_km': Decimal('0.00'),
                'ocupacao_soma': Decimal('0.00'),
                'ocupacao_media': Decimal('0.00'),
                'combustivel_real': Decimal('0.00'),
                'pedagios': Decimal('0.00'),
                'rateio_manutencao': Decimal('0.00'),
                'rateio_depreciacao': Decimal('0.00'),
                'rateio_seguro': Decimal('0.00'),
            }

        it = itens_map[chave]
        it['viagens'] += 1
        it['km_total'] += (cv.km_real or Decimal('0.00'))
        it['receita'] += (cv.receita_frete or Decimal('0.00'))
        it['custo'] += (cv.custo_total_real or Decimal('0.00'))
        it['combustivel_real'] += (cv.combustivel_real or Decimal('0.00'))
        it['pedagios'] += (cv.pedagios or Decimal('0.00'))
        it['rateio_manutencao'] += (cv.rateio_manutencao or Decimal('0.00'))
        it['rateio_depreciacao'] += (cv.rateio_depreciacao or Decimal('0.00'))
        it['rateio_seguro'] += (cv.rateio_seguro or Decimal('0.00'))
        it['ocupacao_soma'] += (cv.ocupacao_viagem_pct or Decimal('0.00'))

    # Consolida percentuais do agrupamento
    lista_itens = []
    for it in itens_map.values():
        it['margem'] = it['receita'] - it['custo']
        if it['receita'] > Decimal('0.00'):
            it['margem_pct'] = ((it['margem'] / it['receita']) * Decimal('100.0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            it['margem_pct'] = Decimal('0.00')

        if it['km_total'] > Decimal('0.00'):
            it['custo_km'] = (it['custo'] / it['km_total']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            it['custo_km'] = Decimal('0.00')

        if it['viagens'] > 0:
            it['ocupacao_media'] = (it['ocupacao_soma'] / Decimal(str(it['viagens']))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

        # Converte decimais para float/string para serialização JSON
        lista_itens.append({
            'id': it['id'],
            'nome': it['nome'],
            'viagens': it['viagens'],
            'km_total': float(it['km_total']),
            'receita': float(it['receita']),
            'custo': float(it['custo']),
            'margem': float(it['margem']),
            'margem_pct': float(it['margem_pct']),
            'custo_km': float(it['custo_km']),
            'ocupacao_media': float(it['ocupacao_media']),
            'combustivel_real': float(it['combustivel_real']),
            'pedagios': float(it['pedagios']),
            'rateio_manutencao': float(it['rateio_manutencao']),
            'rateio_depreciacao': float(it['rateio_depreciacao']),
            'rateio_seguro': float(it['rateio_seguro']),
        })

    # Ordena itens por receita decrescente
    lista_itens.sort(key=lambda x: x['receita'], reverse=True)

    return {
        'total_viagens': total_viagens,
        'receita_total': float(receita_total),
        'custo_total': float(custo_total),
        'margem_bruta': float(margem_total),
        'margem_percentual': float(margem_pct),
        'custo_por_km': float(custo_por_km),
        'custo_por_entrega': float(custo_por_entrega),
        'ocupacao_media': float(ocupacao_media),
        'agrupar_por': agrupar_por,
        'itens': lista_itens
    }


def obter_tco_frota(tenant, data_inicio=None, data_fim=None):
    """
    Calcula o Custo Total de Propriedade (TCO) consolidado por veículo da frota:
    TCO = Combustível (L2) + Manutenção (L3) + Seguros (L5) + Sinistros Líquidos (L5) + Depreciação.
    Apresenta métricas por km e por mês, comparativo FIPE e alerta "Avaliar Substituição".
    """
    config = ConfiguracaoRentabilidade.get_para_tenant(tenant)
    veiculos = Veiculo.objects.filter(tenant=tenant)

    hoje = timezone.localdate()
    d_inicio = data_inicio or (hoje - timedelta(days=365))
    d_fim = data_fim or hoje
    dias_periodo = max(1, (d_fim - d_inicio).days)
    meses_periodo = max(Decimal('1.00'), Decimal(str(dias_periodo)) / Decimal('30.416'))

    tco_lista = []

    for v in veiculos:
        # 1. Combustível (L2)
        qs_ab = Abastecimento.objects.filter(
            veiculo=v,
            data_hora__date__gte=d_inicio,
            data_hora__date__lte=d_fim
        )
        custo_comb = qs_ab.aggregate(tot=Sum('valor_total'))['tot'] or Decimal('0.00')
        km_abast = qs_ab.aggregate(tot=Sum('km_rodados_desde_anterior'))['tot'] or Decimal('0.00')

        # 2. Manutenção (L3 - OS Concluídas)
        qs_os = OrdemServico.objects.filter(
            veiculo=v,
            status='Concluída',
            data_abertura__date__gte=d_inicio,
            data_abertura__date__lte=d_fim
        )
        custo_manut = qs_os.aggregate(tot=Sum('custo_total'))['tot'] or Decimal('0.00')

        # 3. Seguros (L5)
        custo_seguro = Decimal('0.00')
        apolice_v = ApoliceVeiculo.objects.filter(veiculo=v, apolice__ativa=True).select_related('apolice').first()
        apolice = apolice_v.apolice if apolice_v else ApoliceSeguro.objects.filter(tenant=tenant, ativa=True, tipo__icontains='Frota').first()
        if apolice and apolice.premio_total and apolice.premio_total > Decimal('0.00'):
            qtd_v = max(1, apolice.veiculos_segurados.count())
            premio_anual_v = apolice.premio_total / Decimal(str(qtd_v))
            custo_seguro = (premio_anual_v * (Decimal(str(dias_periodo)) / Decimal('365.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # 4. Sinistros Líquidos (L5)
        custo_sinistros = Sinistro.objects.filter(
            veiculo=v,
            data_hora__date__gte=d_inicio,
            data_hora__date__lte=d_fim
        ).aggregate(tot=Sum('prejuizo_liquido'))['tot'] or Decimal('0.00')

        # 5. Depreciação no Período
        custo_deprec = Decimal('0.00')
        fipe_val = v.fipe_valor or Decimal('0.00')
        if fipe_val <= Decimal('0.00') and hasattr(v, 'valores_fipe'):
            ultimo_fipe = v.valores_fipe.order_by('-mes_referencia').first()
            if ultimo_fipe:
                fipe_val = ultimo_fipe.valor or Decimal('0.00')
        if fipe_val <= Decimal('0.00') and v.valor_aquisicao:
            fipe_val = v.valor_aquisicao

        if fipe_val > Decimal('0.00'):
            vida_util = Decimal(str(config.vida_util_anos or 5))
            res_pct = (config.percentual_residual or Decimal('20.00')) / Decimal('100.0')
            valor_deprec = fipe_val * (Decimal('1.00') - res_pct)
            deprec_anual = valor_deprec / vida_util
            custo_deprec = (deprec_anual * (Decimal(str(dias_periodo)) / Decimal('365.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # TCO Total
        tco_total = (custo_comb + custo_manut + custo_seguro + custo_sinistros + custo_deprec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Quilometragem
        km_rodados = km_abast
        if km_rodados <= Decimal('0.00') and v.odometro_atual_km:
            km_rodados = v.odometro_atual_km

        custo_por_km = (tco_total / km_rodados).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if km_rodados > Decimal('0.00') else Decimal('0.00')
        tco_mensal = (tco_total / meses_periodo).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Alerta 'Avaliar Substituição' (se custos acumulados de manutenção e sinistro forem >= 40% do valor FIPE)
        alerta_substituicao = False
        motivo_substituicao = ""
        if fipe_val > Decimal('0.00'):
            pct_manut_fipe = ((custo_manut + custo_sinistros) / fipe_val) * Decimal('100.0')
            if pct_manut_fipe >= Decimal('40.00'):
                alerta_substituicao = True
                motivo_substituicao = (
                    f"Manutenção e sinistros do veículo atingiram {pct_manut_fipe:.1f}% do valor FIPE "
                    f"(R$ {fipe_val:,.2f}). Avaliar substituição ou renovação de frota."
                )

        tco_lista.append({
            'veiculo_id': v.id,
            'placa': v.placa,
            'modelo': f"{v.marca} {v.modelo}",
            'tipo_carroceria': v.tipo_carroceria or 'Caminhão Médio',
            'ano': v.ano,
            'km_rodados': float(km_rodados),
            'fipe_valor': float(fipe_val),
            'custo_combustivel': float(custo_comb),
            'custo_manutencao': float(custo_manut),
            'custo_seguro': float(custo_seguro),
            'custo_seguro_rateado': float(custo_seguro),
            'custo_sinistros': float(custo_sinistros),
            'custo_depreciacao': float(custo_deprec),
            'tco_total': float(tco_total),
            'custo_total_acumulado': float(tco_total),
            'tco_mensal': float(tco_mensal),
            'custo_mensal_medio': float(tco_mensal),
            'custo_por_km': float(custo_por_km),
            'alerta_substituicao': alerta_substituicao,
            'sugestao_substituicao': alerta_substituicao,
            'motivo_substituicao': motivo_substituicao,
            'percentual_manut_sobre_fipe': float(pct_manut_fipe) if fipe_val > Decimal('0.00') else 0.0,
        })

    # Ranking de Eficiência (menor custo por km entre veículos ativos)
    tco_lista.sort(key=lambda x: (x['custo_por_km'] if x['custo_por_km'] > 0 else 999999))
    for rank, item in enumerate(tco_lista, start=1):
        item['ranking_eficiencia'] = rank

    tot_comb = sum(v['custo_combustivel'] for v in tco_lista)
    tot_manut = sum(v['custo_manutencao'] for v in tco_lista)
    tot_seg = sum(v['custo_seguro'] for v in tco_lista)
    tot_sin = sum(v['custo_sinistros'] for v in tco_lista)
    tot_dep = sum(v['custo_depreciacao'] for v in tco_lista)
    tot_tco = sum(v['tco_total'] for v in tco_lista)

    def _calc_pct(part, total):
        return round((part / total * 100.0), 1) if total > 0 else 0.0

    composicao_geral = {
        'custo_combustivel': tot_comb,
        'combustivel_pct': _calc_pct(tot_comb, tot_tco),
        'custo_manutencao': tot_manut,
        'manutencao_pct': _calc_pct(tot_manut, tot_tco),
        'custo_seguro': tot_seg,
        'seguro_pct': _calc_pct(tot_seg, tot_tco),
        'custo_sinistros': tot_sin,
        'sinistros_pct': _calc_pct(tot_sin, tot_tco),
        'custo_depreciacao': tot_dep,
        'depreciacao_pct': _calc_pct(tot_dep, tot_tco),
        'tco_total': tot_tco,
        'total_combustivel': tot_comb,
        'total_manutencao': tot_manut,
        'total_seguro': tot_seg,
        'total_sinistros': tot_sin,
        'total_depreciacao': tot_dep,
    }

    return {
        'periodo': {
            'inicio': d_inicio.strftime('%Y-%m-%d'),
            'fim': d_fim.strftime('%Y-%m-%d'),
            'dias': dias_periodo
        },
        'composicao_geral': composicao_geral,
        'veiculos': tco_lista
    }


def gerar_csv_rentabilidade(dados_rentabilidade):
    """
    Gera conteúdo CSV formatado em UTF-8 com BOM e ponto e vírgula,
    pronto para download e compatível com Excel brasileiro.
    """
    output = io.StringIO()
    # UTF-8 BOM
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')

    # Cabeçalho do Relatório
    writer.writerow(['RELATÓRIO DE RENTABILIDADE E CUSTO TOTAL DE FRETES'])
    writer.writerow(['Agrupamento por', dados_rentabilidade.get('agrupar_por', 'rota').upper()])
    writer.writerow(['Total de Viagens', dados_rentabilidade.get('total_viagens', 0)])
    writer.writerow(['Receita Total (R$)', f"{dados_rentabilidade.get('receita_total', 0):.2f}".replace('.', ',')])
    writer.writerow(['Custo Total (R$)', f"{dados_rentabilidade.get('custo_total', 0):.2f}".replace('.', ',')])
    writer.writerow(['Margem Bruta (R$)', f"{dados_rentabilidade.get('margem_bruta', 0):.2f}".replace('.', ',')])
    writer.writerow(['Margem (%)', f"{dados_rentabilidade.get('margem_percentual', 0):.2f}%".replace('.', ',')])
    writer.writerow(['Custo Médio por Km (R$/km)', f"{dados_rentabilidade.get('custo_por_km', 0):.2f}".replace('.', ',')])
    writer.writerow(['Ocupação Média (%)', f"{dados_rentabilidade.get('ocupacao_media', 0):.1f}%".replace('.', ',')])
    writer.writerow([])

    # Cabeçalho da Tabela
    writer.writerow([
        'Identificador / Nome',
        'Viagens Realizadas',
        'Km Total (km)',
        'Ocupação Média (%)',
        'Receita Frete (R$)',
        'Combustível Real (R$)',
        'Pedágios (R$)',
        'Rateio Manutenção (R$)',
        'Rateio Depreciação (R$)',
        'Rateio Seguro (R$)',
        'Custo Total (R$)',
        'Margem Bruta (R$)',
        'Margem Percentual (%)',
        'Custo por Km (R$/km)'
    ])

    for it in dados_rentabilidade.get('itens', []):
        writer.writerow([
            it['nome'],
            it['viagens'],
            f"{it['km_total']:.1f}".replace('.', ','),
            f"{it['ocupacao_media']:.1f}%".replace('.', ','),
            f"{it['receita']:.2f}".replace('.', ','),
            f"{it['combustivel_real']:.2f}".replace('.', ','),
            f"{it['pedagios']:.2f}".replace('.', ','),
            f"{it['rateio_manutencao']:.2f}".replace('.', ','),
            f"{it['rateio_depreciacao']:.2f}".replace('.', ','),
            f"{it['rateio_seguro']:.2f}".replace('.', ','),
            f"{it['custo']:.2f}".replace('.', ','),
            f"{it['margem']:.2f}".replace('.', ','),
            f"{it['margem_pct']:.2f}%".replace('.', ','),
            f"{it['custo_km']:.2f}".replace('.', ',')
        ])

    return output.getvalue()
