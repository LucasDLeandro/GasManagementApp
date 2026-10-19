import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import models

from logistica.models import (
    Abastecimento,
    Veiculo,
    PrecoCombustivelReferencia,
    ConfiguracaoCombustivelFrota
)


def obter_configuracao_combustivel(tenant):
    """
    Retorna ou cria a configuração de parâmetros de combustível do tenant.
    """
    if not tenant:
        return None
    config, _ = ConfiguracaoCombustivelFrota.objects.get_or_create(
        tenant=tenant,
        defaults={
            'uf_padrao': 'GO',
            'municipio_padrao': '',
            'tolerancia_preco_pct': Decimal('15.00'),
            'dias_alerta_preco_defasado': 14,
            'tolerancia_consumo_pct': Decimal('25.00'),
            'usar_preco_referencia_sugerido': True
        }
    )
    return config


def calcular_valores_abastecimento(litros=None, valor_litro=None, valor_total=None):
    """
    Valida e calcula de forma bidirecional os valores de litros, valor por litro e valor total.
    Tolerância de R$ 0,05 de arredondamento quando os 3 forem informados.
    Se apenas 2 forem informados, calcula o terceiro.
    """
    # Converte para Decimal seguro
    d_litros = Decimal(str(litros)) if litros is not None and str(litros).strip() != '' else None
    d_litro = Decimal(str(valor_litro)) if valor_litro is not None and str(valor_litro).strip() != '' else None
    d_total = Decimal(str(valor_total)) if valor_total is not None and str(valor_total).strip() != '' else None

    if d_litros is not None and d_litros <= Decimal('0'):
        raise ValidationError({'litros': ["A quantidade de litros deve ser maior que zero."]})
    if d_litro is not None and d_litro <= Decimal('0'):
        raise ValidationError({'valor_litro': ["O valor por litro deve ser maior que zero."]})
    if d_total is not None and d_total <= Decimal('0'):
        raise ValidationError({'valor_total': ["O valor total deve ser maior que zero."]})

    if d_litros is not None and d_litro is not None and d_total is not None:
        calculado = (d_litros * d_litro).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        diff = abs(calculado - d_total)
        if diff > Decimal('0.10'):
            raise ValidationError({
                'valor_total': [f"Inconsistência nos valores informados: {d_litros} L × R$ {d_litro} = R$ {calculado}, divergindo de R$ {d_total}."]
            })
        return d_litros.quantize(Decimal('0.001')), d_litro.quantize(Decimal('0.0001')), d_total.quantize(Decimal('0.01'))

    elif d_litros is not None and d_litro is not None:
        d_total = (d_litros * d_litro).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    elif d_total is not None and d_litros is not None:
        d_litro = (d_total / d_litros).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    elif d_total is not None and d_litro is not None:
        d_litros = (d_total / d_litro).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    else:
        raise ValidationError("É obrigatório informar ao menos dois dos seguintes campos: Litros, Valor por Litro ou Valor Total.")

    return d_litros, d_litro, d_total


def validar_odometro_abastecimento(veiculo, odometro_km, abastecimento_id=None):
    """
    Valida se o odômetro é compatível com o histórico do veículo.
    Não pode ser menor que o odômetro atual do veículo nem de abastecimentos anteriores.
    """
    if odometro_km is None or odometro_km < 0:
        raise ValidationError({'odometro_km': ["Odômetro inválido. Deve ser um número inteiro positivo."]})

    odometro_atual = veiculo.odometro_atual_km or 0

    # Busca o maior odômetro registrado anteriormente para este veículo
    qs_anterior = Abastecimento.unscoped.filter(veiculo=veiculo)
    if abastecimento_id:
        qs_anterior = qs_anterior.exclude(id=abastecimento_id)
    
    maior_anterior = qs_anterior.order_by('-odometro_km').values_list('odometro_km', flat=True).first()
    maior_referencia = max(odometro_atual, maior_anterior or 0)

    if maior_referencia > 0 and odometro_km < maior_referencia:
        raise ValidationError({
            'odometro_km': [
                f"Odômetro informado ({odometro_km} km) não pode ser inferior ao "
                f"último odômetro registrado ({maior_referencia} km) para o veículo {veiculo.placa}."
            ]
        })

    return True


def validar_capacidade_tanque(veiculo, litros):
    """
    Valida o volume abastecido contra a capacidade do tanque do veículo.
    - Se > 130%: Bloqueio com ValidationError
    - Se > 100%: Retorna string de aviso para alerta
    """
    if not veiculo.capacidade_tanque_l or veiculo.capacidade_tanque_l <= Decimal('0'):
        return None

    cap = veiculo.capacidade_tanque_l
    limite_bloqueio = (cap * Decimal('1.30')).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

    if litros > limite_bloqueio:
        raise ValidationError({
            'litros': [
                f"Volume abastecido ({litros} L) excede a capacidade física máxima do tanque "
                f"({cap} L) em mais de 30% (limite seguro: {limite_bloqueio} L)."
            ]
        })

    if litros > cap:
        return f"Volume informado ({litros} L) excede a capacidade nominal do tanque ({cap} L)."

    return None


def calcular_consumo_abastecimento(abastecimento):
    """
    Calcula o consumo real (km/l) e o custo por km pelo método tanque cheio a tanque cheio.
    Retorna: (km_rodados, consumo_km_l, custo_por_km)
    """
    veiculo = abastecimento.veiculo
    odometro_atual = abastecimento.odometro_km

    # Arla 32 é um aditivo redutor de emissões; não entra no cálculo de km/l do combustível
    if abastecimento.tipo_combustivel == 'Arla 32':
        return None, None, None

    # Busca o abastecimento imediatamente anterior deste veículo (excluindo Arla 32)
    qs_anteriores = Abastecimento.unscoped.filter(
        veiculo=veiculo
    ).exclude(
        tipo_combustivel='Arla 32'
    )
    if abastecimento.id:
        qs_anteriores = qs_anteriores.exclude(id=abastecimento.id)

    # Ordena por data_hora decrescente e odometro decrescente
    anterior_imediato = qs_anteriores.filter(
        odometro_km__lte=odometro_atual
    ).order_by('-odometro_km', '-data_hora').first()

    km_rodados = None
    if anterior_imediato:
        km_rodados = max(0, odometro_atual - anterior_imediato.odometro_km)

    # Se este abastecimento NÃO foi tanque cheio, não fecha ciclo de medição de km/l
    if not abastecimento.tanque_cheio:
        custo_km = None
        if km_rodados and km_rodados > 0:
            custo_km = (abastecimento.valor_total / Decimal(km_rodados)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        return km_rodados, None, custo_km

    # Se este abastecimento FOI tanque cheio, busca o último abastecimento ANTERIOR que também foi tanque cheio
    ultimo_tanque_cheio = qs_anteriores.filter(
        tanque_cheio=True,
        odometro_km__lt=odometro_atual
    ).order_by('-odometro_km', '-data_hora').first()

    if not ultimo_tanque_cheio:
        # É o primeiro tanque cheio registrado; serve como marco inicial (baseline)
        return km_rodados, None, None

    km_ciclo = odometro_atual - ultimo_tanque_cheio.odometro_km
    if km_ciclo <= 0:
        return 0, None, None

    # Soma todos os litros e valores abastecidos entre o último tanque cheio e o atual (inclusive parciais)
    parciais = qs_anteriores.filter(
        odometro_km__gt=ultimo_tanque_cheio.odometro_km,
        odometro_km__lt=odometro_atual
    )

    litros_totais = abastecimento.litros + sum(p.litros for p in parciais)
    valor_total_ciclo = abastecimento.valor_total + sum(p.valor_total for p in parciais)

    if litros_totais <= Decimal('0'):
        return km_ciclo, None, None

    consumo_km_l = (Decimal(km_ciclo) / litros_totais).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    custo_por_km = (valor_total_ciclo / Decimal(km_ciclo)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

    return km_ciclo, consumo_km_l, custo_por_km


def obter_preco_referencia_aplicavel(tenant, produto, uf=None, municipio=None):
    """
    Busca o preço de referência seguindo a hierarquia de fallback:
    1º) Município específico (se informado)
    2º) Média do Estado (UF)
    3º) Entrada manual mais recente do tenant
    """
    qs = PrecoCombustivelReferencia.objects.filter(
        tenant=tenant,
        produto=produto
    )

    # 1. Tenta Município
    if municipio:
        ref_mun = qs.filter(municipio__iexact=municipio.strip()).order_by('-data_final').first()
        if ref_mun:
            return ref_mun

    # 2. Tenta UF (Média Estadual ANP)
    if uf:
        ref_uf = qs.filter(uf__iexact=uf.strip()).order_by('-data_final').first()
        if ref_uf:
            return ref_uf

    # 3. Fallback: Qualquer registro mais recente do produto no tenant
    return qs.order_by('-data_final').first()


def avaliar_alertas_abastecimento(abastecimento, config=None):
    """
    Motor de detecção de anomalias e geração de alertas para o abastecimento.
    Retorna: (status_validacao, lista_de_alertas)
    """
    alertas = []
    veiculo = abastecimento.veiculo
    tenant = abastecimento.tenant

    if not config:
        config = obter_configuracao_combustivel(tenant)

    tol_preco_pct = config.tolerancia_preco_pct if config else Decimal('15.00')
    tol_consumo_pct = config.tolerancia_consumo_pct if config else Decimal('25.00')

    # 1. Alerta de Preço vs Referência ANP
    uf_busca = abastecimento.posto_uf or (config.uf_padrao if config else 'GO')
    mun_busca = abastecimento.posto_cidade or (config.municipio_padrao if config else '')
    preco_ref = obter_preco_referencia_aplicavel(tenant, abastecimento.tipo_combustivel, uf=uf_busca, municipio=mun_busca)

    if preco_ref and preco_ref.preco_medio > Decimal('0'):
        limite_superior = preco_ref.preco_medio * (Decimal('1.0') + (tol_preco_pct / Decimal('100.0')))
        if abastecimento.valor_litro > limite_superior:
            diff_pct = ((abastecimento.valor_litro - preco_ref.preco_medio) / preco_ref.preco_medio * Decimal('100.0')).quantize(Decimal('0.1'))
            alertas.append(
                f"Preço por litro pago (R$ {abastecimento.valor_litro:.4f}) está {diff_pct}% acima "
                f"da referência {preco_ref.fonte} ({preco_ref.municipio or preco_ref.uf}: R$ {preco_ref.preco_medio:.4f})."
            )

    # 2. Alerta de Consumo vs Referencial do Veículo
    if abastecimento.consumo_km_l and veiculo.consumo_referencia_km_l and veiculo.consumo_referencia_km_l > Decimal('0'):
        ref_cons = veiculo.consumo_referencia_km_l
        desvio_pct = (abs(abastecimento.consumo_km_l - ref_cons) / ref_cons * Decimal('100.0')).quantize(Decimal('0.1'))
        if desvio_pct > tol_consumo_pct:
            if abastecimento.consumo_km_l < ref_cons:
                alertas.append(
                    f"Consumo apurado ({abastecimento.consumo_km_l} km/l) está {desvio_pct}% abaixo "
                    f"do referencial cadastrado do veículo ({ref_cons} km/l)."
                )
            else:
                alertas.append(
                    f"Consumo apurado ({abastecimento.consumo_km_l} km/l) é {desvio_pct}% superior "
                    f"ao referencial ({ref_cons} km/l). Verificar possível omissão de abastecimento intermediário."
                )

    # 3. Alerta de Capacidade do Tanque
    if veiculo.capacidade_tanque_l and veiculo.capacidade_tanque_l > Decimal('0'):
        if abastecimento.litros > veiculo.capacidade_tanque_l:
            alertas.append(
                f"Volume abastecido ({abastecimento.litros} L) excede a capacidade nominal do tanque ({veiculo.capacidade_tanque_l} L)."
            )

    # 4. Alerta de Combustível Incompatível com o Veículo
    if abastecimento.tipo_combustivel != 'Arla 32' and veiculo.combustivel_padrao:
        # Se veículo for Flex, permite Gasolina ou Etanol
        if veiculo.combustivel_padrao == 'Flex':
            compativel = abastecimento.tipo_combustivel in ['Gasolina Comum', 'Etanol', 'Flex']
        else:
            compativel = abastecimento.tipo_combustivel == veiculo.combustivel_padrao

        if not compativel:
            alertas.append(
                f"Combustível utilizado ({abastecimento.tipo_combustivel}) difere do padrão "
                f"homologado para este veículo ({veiculo.combustivel_padrao})."
            )

    # 5. Alerta de Abastecimentos Consecutivos Muito Próximos (< 1h ou < 10 km)
    if abastecimento.odometro_km:
        qs_prox = Abastecimento.unscoped.filter(
            veiculo=veiculo
        ).exclude(id=abastecimento.id if abastecimento.id else None)
        
        anterior = qs_prox.filter(odometro_km__lte=abastecimento.odometro_km).order_by('-odometro_km', '-data_hora').first()
        if anterior:
            diff_km = abastecimento.odometro_km - anterior.odometro_km
            diff_tempo = abs((abastecimento.data_hora - anterior.data_hora).total_seconds()) if abastecimento.data_hora and anterior.data_hora else None
            
            if (diff_km < 10) or (diff_tempo is not None and diff_tempo < 3600):
                alertas.append("Abastecimento registrado com intervalo excessivamente curto em relação ao abastecimento anterior.")

    # 6. Alerta de Ausência de Comprovante
    if not abastecimento.comprovante:
        alertas.append("Abastecimento registrado sem anexo de comprovante ou foto do cupom fiscal.")

    # Determinação do Status de Validação
    if any("acima" in a and "%" in a and float(a.split("%")[0].split()[-1]) > 30.0 for a in alertas):
        status_val = 'Revisar'
    elif len(alertas) > 0:
        status_val = 'Alerta'
    else:
        status_val = 'Normal'

    return status_val, alertas


def processar_abastecimento(abastecimento):
    """
    Executa o ciclo completo de validação, cálculo e atualização de ativo para um abastecimento.
    """
    veiculo = abastecimento.veiculo

    # 1. Consistência de valores
    litros, valor_litro, valor_total = calcular_valores_abastecimento(
        litros=abastecimento.litros,
        valor_litro=abastecimento.valor_litro,
        valor_total=abastecimento.valor_total
    )
    abastecimento.litros = litros
    abastecimento.valor_litro = valor_litro
    abastecimento.valor_total = valor_total

    # 2. Validação de odômetro
    validar_odometro_abastecimento(veiculo, abastecimento.odometro_km, abastecimento_id=abastecimento.id)

    # 3. Validação de capacidade
    validar_capacidade_tanque(veiculo, abastecimento.litros)

    # 4. Cálculo de consumo e custo/km
    km_rodados, consumo_km_l, custo_km = calcular_consumo_abastecimento(abastecimento)
    abastecimento.km_rodados_desde_anterior = km_rodados
    abastecimento.consumo_km_l = consumo_km_l
    abastecimento.custo_por_km = custo_km

    # 5. Avaliação de alertas
    status_val, alertas = avaliar_alertas_abastecimento(abastecimento)
    abastecimento.status_validacao = status_val
    abastecimento.alertas = alertas

    # 6. Atualiza odômetro atual do veículo se este for superior
    if abastecimento.odometro_km > (veiculo.odometro_atual_km or 0):
        veiculo.odometro_atual_km = abastecimento.odometro_km
        veiculo.save(update_fields=['odometro_atual_km'])

    return abastecimento
