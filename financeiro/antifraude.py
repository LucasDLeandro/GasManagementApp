import csv
import io
import math
import uuid
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from core.money import quantize
from financeiro.models import (
    PreLancamentoDespesaCampo,
    PrecoReferenciaCombustivel,
)
from logistica.models import LeituraOdometro

# ==============================================================================
# CÓDIGOS ESTÁVEIS DE ANOMALIAS ANTIFRAUDE (Sprint 9C - Tarefa 3)
# ==============================================================================
ANOMALIA_LITROS_ACIMA_DO_TANQUE = 'LITROS_ACIMA_DO_TANQUE'
ANOMALIA_ODOMETRO_REGREDIU = 'ODOMETRO_REGREDIU'
ANOMALIA_CONSUMO_FORA_DA_FAIXA = 'CONSUMO_FORA_DA_FAIXA'
ANOMALIA_PRECO_FORA_DA_FAIXA = 'PRECO_FORA_DA_FAIXA'
ANOMALIA_DUPLICIDADE = 'DUPLICIDADE'
ANOMALIA_SEM_FOTO = 'SEM_FOTO'
ANOMALIA_LOCAL_DISTANTE_DA_ROTA = 'LOCAL_DISTANTE_DA_ROTA'
ANOMALIA_PRIMEIRO_REGISTRO = 'PRIMEIRO_REGISTRO'


def calcular_distancia_haversine_km(lat1, lon1, lat2, lon2) -> Decimal:
    """
    Calcula a distância geodésica em quilômetros entre dois pares de coordenadas decimais.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return Decimal('0.000')

    r = 6371.0  # Raio da Terra em km
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    distancia = r * c
    return quantize(Decimal(str(distancia)), 3)


def analisar_despesa_campo(
    despesa: PreLancamentoDespesaCampo = None,
    salvar: bool = True,
    *,
    tenant=None,
    veiculo=None,
    tipo='ABASTECIMENTO',
    motorista=None,
    entrega=None,
    data_hora=None,
    odometro_informado=None,
    litros=None,
    preco_litro=None,
    valor_informado=None,
    forma_pagamento='CARTAO_FROTA',
    tem_foto=None,
    foto_cupom=None,
    latitude=None,
    longitude=None,
    latitude_despesa=None,
    longitude_despesa=None,
    uf_posto=None,
    client_uuid=None,
) -> tuple[bool, list[str]]:
    """
    Motor de detecção de anomalias e fraude em despesas de campo (Sprint 9C - Tarefa 3 / F-05).
    Avalia integridade física, odômetro, consumo médio, preços de referência ANP e duplicidade.
    Retorna (possui_alerta: bool, motivos_alerta: list[str]).
    """
    if despesa is None:
        from types import SimpleNamespace
        lat = latitude if latitude is not None else latitude_despesa
        lon = longitude if longitude is not None else longitude_despesa
        has_photo = tem_foto if tem_foto is not None else bool(foto_cupom)
        calc_preco = preco_litro
        if calc_preco is None and valor_informado and litros and Decimal(str(litros)) > Decimal('0.000'):
            calc_preco = quantize(Decimal(str(valor_informado)) / Decimal(str(litros)), 3)

        despesa = SimpleNamespace(
            tenant=tenant,
            veiculo=veiculo,
            tipo=tipo,
            motorista=motorista,
            entrega=entrega,
            data_hora=data_hora or timezone.now(),
            odometro_informado=odometro_informado,
            litros=litros,
            preco_litro_calculado=calc_preco,
            forma_pagamento=forma_pagamento,
            foto_cupom="foto.jpg" if has_photo else None,
            latitude=lat,
            longitude=lon,
            client_uuid=client_uuid or uuid.uuid4(),
            pk=None
        )
        salvar = False

    motivos = []
    veiculo = despesa.veiculo
    tenant = despesa.tenant

    # 1. Validação de Foto do Cupom / Nota Fiscal
    if not despesa.foto_cupom:
        motivos.append(ANOMALIA_SEM_FOTO)

    # 2. Anomalias Específicas de Abastecimento
    if despesa.tipo == 'ABASTECIMENTO':
        # (a) Capacidade do Tanque (LITROS_ACIMA_DO_TANQUE): litros > capacidade * 1.05
        capacidade = veiculo.capacidade_tanque_litros or veiculo.capacidade_tanque_l
        if capacidade and despesa.litros:
            limite_capacidade = quantize(capacidade * Decimal('1.05'), 3)
            if despesa.litros > limite_capacidade:
                motivos.append(ANOMALIA_LITROS_ACIMA_DO_TANQUE)

        # (b) Monotonicidade e Consumo de Combustível (ODOMETRO_REGREDIU / CONSUMO_FORA_DA_FAIXA)
        if despesa.odometro_informado is not None:
            # Busca leitura anterior mais recente validada
            ultima_leitura = LeituraOdometro.objects.filter(
                tenant=tenant,
                veiculo=veiculo,
                data_hora__lte=despesa.data_hora,
                validada=True
            ).exclude(
                km=despesa.odometro_informado,
                data_hora=despesa.data_hora
            ).order_by('-data_hora', '-id').first()

            km_base = ultima_leitura.km if ultima_leitura else getattr(veiculo, 'odometro_atual_km', None)
            tem_registro_anterior = (ultima_leitura is not None) or (
                getattr(veiculo, 'odometro_atual_km', None) is not None and veiculo.odometro_atual_km > Decimal('0.000')
            )

            if not tem_registro_anterior:
                # Primeiro registro do veículo no sistema
                motivos.append(ANOMALIA_PRIMEIRO_REGISTRO)
            elif km_base is not None:
                if despesa.odometro_informado < km_base:
                    motivos.append(ANOMALIA_ODOMETRO_REGREDIU)
                else:
                    # Calcula km/L real se houver litros informados
                    km_rodado = despesa.odometro_informado - km_base
                    if km_rodado > Decimal('0.000') and despesa.litros and despesa.litros > Decimal('0.000'):
                        consumo_real = quantize(km_rodado / despesa.litros, 3)
                        consumo_ref = veiculo.consumo_referencia_kml or getattr(veiculo, 'consumo_referencia_km_l', None)

                        if consumo_ref and consumo_ref > Decimal('0.000'):
                            # Faixa de tolerância de ±20% da referência
                            limite_inferior = quantize(consumo_ref * Decimal('0.80'), 3)
                            limite_superior = quantize(consumo_ref * Decimal('1.20'), 3)

                            if consumo_real < limite_inferior or consumo_real > limite_superior:
                                motivos.append(ANOMALIA_CONSUMO_FORA_DA_FAIXA)

        # (c) Preço Fora da Faixa de Referência (PRECO_FORA_DA_FAIXA)
        if despesa.preco_litro_calculado and despesa.preco_litro_calculado > Decimal('0.000'):
            tipo_comb = veiculo.tipo_combustivel or veiculo.combustivel_padrao or 'Diesel S10'
            preco_ref = PrecoReferenciaCombustivel.objects.filter(
                tenant=tenant,
                combustivel__iexact=tipo_comb
            ).order_by('-semana', '-id').first()

            if preco_ref and preco_ref.preco_medio > Decimal('0.000'):
                min_permitido = preco_ref.preco_minimo or quantize(preco_ref.preco_medio * Decimal('0.85'), 3)
                max_permitido = preco_ref.preco_maximo or quantize(preco_ref.preco_medio * Decimal('1.15'), 3)

                if despesa.preco_litro_calculado < min_permitido or despesa.preco_litro_calculado > max_permitido:
                    motivos.append(ANOMALIA_PRECO_FORA_DA_FAIXA)

    # 3. Verificação de Duplicidade Temporal no mesmo Veículo (DUPLICIDADE)
    janela_inicio = despesa.data_hora - timedelta(minutes=60)
    janela_fim = despesa.data_hora + timedelta(minutes=60)

    duplicado = PreLancamentoDespesaCampo.objects.filter(
        tenant=tenant,
        veiculo=veiculo,
        tipo=despesa.tipo,
        data_hora__range=(janela_inicio, janela_fim)
    ).exclude(client_uuid=despesa.client_uuid).exists()

    if duplicado:
        motivos.append(ANOMALIA_DUPLICIDADE)

    # 4. Localização Distante da Rota (LOCAL_DISTANTE_DA_ROTA)
    if despesa.latitude is not None and despesa.longitude is not None and despesa.entrega:
        ent = despesa.entrega
        lat_ref = getattr(ent, 'latitude', None)
        lon_ref = getattr(ent, 'longitude', None)
        if lat_ref is None and hasattr(ent, 'cliente') and ent.cliente:
            lat_ref = getattr(ent.cliente, 'latitude', None)
            lon_ref = getattr(ent.cliente, 'longitude', None)
        if lat_ref is None and hasattr(ent, 'coordenadas_rastreamento'):
            coord = ent.coordenadas_rastreamento.order_by('-timestamp').first()
            if coord:
                lat_ref = coord.latitude
                lon_ref = coord.longitude

        if lat_ref is not None and lon_ref is not None:
            distancia_km = calcular_distancia_haversine_km(despesa.latitude, despesa.longitude, lat_ref, lon_ref)
            if distancia_km > Decimal('15.000'):
                motivos.append(ANOMALIA_LOCAL_DISTANTE_DA_ROTA)

    # Determinação do alerta de auditoria:
    # PRIMEIRO_REGISTRO é informativo; qualquer outra anomalia marca alerta_auditoria = True.
    tem_alerta = any(m != ANOMALIA_PRIMEIRO_REGISTRO for m in motivos)

    despesa.alerta_auditoria = tem_alerta
    despesa.motivos_alerta_json = motivos

    if salvar and despesa.pk:
        despesa.save(update_fields=['alerta_auditoria', 'motivos_alerta_json', 'atualizado_em'])

    return tem_alerta, motivos


def importar_precos_referencia_csv(tenant, csv_content: str) -> list[PrecoReferenciaCombustivel]:
    """
    Importa tabela de preços médios de referência de combustíveis por município e semana a partir de CSV.
    Estrutura esperada: uf,municipio,combustivel,semana,preco_medio[,preco_minimo,preco_maximo]
    """
    if isinstance(csv_content, bytes):
        csv_content = csv_content.decode('utf-8-sig')

    stream = io.StringIO(csv_content.strip())
    reader = csv.DictReader(stream)

    registros = []
    for row in reader:
        uf = row.get('uf', '').strip().upper()
        municipio = row.get('municipio', '').strip()
        combustivel = row.get('combustivel', '').strip()
        semana = row.get('semana', '').strip()

        if not (uf and municipio and combustivel and semana):
            continue

        p_medio = quantize(Decimal(str(row.get('preco_medio') or row.get('preco', '0.000'))), 3)
        p_min = quantize(Decimal(str(row['preco_minimo'])), 3) if row.get('preco_minimo') else None
        p_max = quantize(Decimal(str(row['preco_maximo'])), 3) if row.get('preco_maximo') else None

        obj, _ = PrecoReferenciaCombustivel.objects.update_or_create(
            tenant=tenant,
            uf=uf,
            municipio=municipio,
            combustivel=combustivel,
            semana=semana,
            defaults={
                'preco_medio': p_medio,
                'preco_minimo': p_min,
                'preco_maximo': p_max
            }
        )
        registros.append(obj)

    return registros
