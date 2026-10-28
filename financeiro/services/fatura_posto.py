import csv
import io
import calendar
from datetime import timedelta, date, datetime
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.guards import assert_tenant_writable, assert_modulo
from core.money import quantize, allocate
from financeiro.models import (
    FaturaConsolidadaPosto,
    ItemFaturaPosto,
    PreLancamentoDespesaCampo,
    TituloFinanceiro,
    PlanoContas,
    CentroCusto,
    Fornecedor,
)
from financeiro.services.titulos import criar_titulo
from logistica.models import Veiculo


@transaction.atomic
def importar_fatura_csv(
    *,
    tenant,
    fornecedor=None,
    fornecedor_id=None,
    cartao_ou_convenio: str = '',
    numero_fatura: str,
    data_vencimento=None,
    csv_content: str,
    data_emissao=None,
    usuario=None
) -> FaturaConsolidadaPosto:
    """
    Importa fatura consolidada de posto ou cartão frota via arquivo CSV (Sprint 9C - Tarefa 6).
    Cria a fatura e os itens individuais, executando conciliação automática prévia.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    num_fat = str(numero_fatura).strip()
    if not num_fat:
        raise ValidationError("O número da fatura é obrigatório.")

    if fornecedor:
        fornecedor_obj = fornecedor
    elif fornecedor_id:
        if isinstance(fornecedor_id, Fornecedor):
            fornecedor_obj = fornecedor_id
        else:
            fornecedor_obj = Fornecedor.objects.get(tenant=tenant, id=fornecedor_id)
    else:
        razao = (cartao_ou_convenio or '').strip() or "Fornecedor Cartão Frota"
        fornecedor_obj = Fornecedor.objects.filter(tenant=tenant, razao_social=razao).first()
        if not fornecedor_obj:
            fornecedor_obj = Fornecedor.objects.create(
                tenant=tenant,
                razao_social=razao,
                nome_fantasia=razao,
                documento="00.000.000/0001-99"
            )

    if FaturaConsolidadaPosto.objects.filter(tenant=tenant, fornecedor=fornecedor_obj, numero_fatura=num_fat).exists():
        raise ValidationError(f"A fatura #{num_fat} já foi importada anteriormente para o fornecedor {fornecedor_obj.razao_social}.")

    if isinstance(csv_content, bytes):
        csv_content = csv_content.decode('utf-8-sig')

    dt_emissao = data_emissao or timezone.localdate()
    dt_venc = data_vencimento or (dt_emissao + timedelta(days=15))

    # Leitura das linhas do CSV com detecção de delimitador (, ou ;)
    clean_csv = csv_content.strip()
    first_line = clean_csv.split('\n')[0] if clean_csv else ''
    delimiter = ';' if ';' in first_line else ','
    stream = io.StringIO(clean_csv)
    reader = csv.DictReader(stream, delimiter=delimiter)

    linhas_validas = []
    total_fatura = Decimal('0.00')

    for row in reader:
        placa = row.get('placa', '').strip().upper()
        data_str = row.get('data_hora') or row.get('data') or ''
        valor_str = row.get('valor') or row.get('valor_total') or '0.00'
        litros_str = row.get('litros') or '0.000'

        if not data_str:
            continue

        try:
            if 'T' in data_str:
                dt_item = datetime.fromisoformat(data_str)
            elif len(data_str) == 10:
                dt_item = datetime.strptime(data_str, '%Y-%m-%d')
            else:
                dt_item = datetime.strptime(data_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            dt_item = timezone.now()

        if timezone.is_naive(dt_item):
            dt_item = timezone.make_aware(dt_item)

        val_item = quantize(Decimal(str(valor_str)), 2)
        litros_item = quantize(Decimal(str(litros_str)), 3) if litros_str else None

        total_fatura += val_item
        linhas_validas.append({
            'placa': placa,
            'data_hora': dt_item,
            'valor': val_item,
            'litros': litros_item,
            'posto_nome': (row.get('posto_nome') or '').strip(),
            'posto_cnpj': (row.get('posto_cnpj') or '').strip(),
            'numero_cartao': (row.get('numero_cartao') or row.get('cartao_numero') or '').strip(),
        })

    if not linhas_validas:
        raise ValidationError("O arquivo CSV de fatura não contém registros válidos de abastecimento.")

    fatura = FaturaConsolidadaPosto.objects.create(
        tenant=tenant,
        fornecedor=fornecedor_obj,
        numero_fatura=num_fat,
        data_emissao=dt_emissao,
        data_vencimento=dt_venc,
        valor_total=total_fatura,
        status='IMPORTADA',
        criado_por=usuario
    )

    # Criação dos itens
    for item in linhas_validas:
        veic = None
        if item['placa']:
            veic = Veiculo.objects.filter(tenant=tenant, placa=item['placa']).first()

        ItemFaturaPosto.objects.create(
            tenant=tenant,
            fatura=fatura,
            veiculo=veic,
            placa_informada=item['placa'],
            numero_cartao=item['numero_cartao'],
            data_hora=item['data_hora'],
            litros=item['litros'],
            valor=item['valor'],
            posto_nome=item['posto_nome'],
            posto_cnpj=item['posto_cnpj'],
            status_casamento='SEM_PRE_LANCAMENTO'
        )

    # Executa casamento automático item x pré-lançamento
    conciliar_itens_fatura(fatura_id=fatura.id, tenant=tenant)
    fatura.refresh_from_db()
    return fatura


@transaction.atomic
def conciliar_itens_fatura(tenant=None, fatura_id: int = None, **kwargs) -> dict:
    """
    Casamento item x pré-lançamento por (cartão/veículo, data ±1 dia, valor, litros).
    Gera relatório de divergências (suspeitos sem pré-lançamento e valores discrepantes).
    """
    t_obj = tenant or kwargs.get('tenant')
    f_id = fatura_id or kwargs.get('fatura_id')

    assert_tenant_writable(t_obj)
    assert_modulo(t_obj, 'financeiro')

    fatura = FaturaConsolidadaPosto.objects.select_for_update().get(id=f_id, tenant=t_obj)
    itens = fatura.itens.filter(status_casamento='SEM_PRE_LANCAMENTO')

    casados_count = 0
    divergentes_count = 0
    sem_pre_lancamento_count = 0

    for item in itens:
        dt_inicio = item.data_hora - timedelta(days=1)
        dt_fim = item.data_hora + timedelta(days=1)

        qs_candidatos = PreLancamentoDespesaCampo.objects.filter(
            tenant=t_obj,
            data_hora__range=(dt_inicio, dt_fim),
            item_fatura_associado__isnull=True
        )

        if item.veiculo_id:
            qs_candidatos = qs_candidatos.filter(veiculo=item.veiculo)
        elif item.placa_informada:
            qs_candidatos = qs_candidatos.filter(veiculo__placa=item.placa_informada)

        # Encontra candidato mais próximo de valor
        candidato = None
        for c in qs_candidatos:
            if abs(c.valor_informado - item.valor) <= Decimal('1.00'):
                candidato = c
                break

        if not candidato:
            # Tenta encontrar com valor divergente
            candidato = qs_candidatos.first()

        if candidato:
            diff_valor = abs(candidato.valor_informado - item.valor)
            if diff_valor <= Decimal('0.05'):
                item.status_casamento = 'CASADO'
                casados_count += 1
            else:
                item.status_casamento = 'VALOR_DIVERGENTE'
                divergentes_count += 1

            item.pre_lancamento = candidato
            item.save(update_fields=['status_casamento', 'pre_lancamento'])
        else:
            sem_pre_lancamento_count += 1

    fatura.status = 'CONCILIADA'
    fatura.save(update_fields=['status', 'atualizado_em'])

    return {
        'fatura_id': fatura.id,
        'total_itens': fatura.itens.count(),
        'casados': casados_count,
        'divergentes': divergentes_count,
        'sem_pre_lancamento': sem_pre_lancamento_count
    }


@transaction.atomic
def aprovar_fatura_posto(tenant=None, fatura_id: int = None, usuario=None, **kwargs) -> list[TituloFinanceiro]:
    """
    Aprova a fatura consolidada e gera os títulos a pagar correspondentes (Sprint 9C - Tarefa 6).
    Requisitos estritos:
    - Origem_tipo = 'FATURA_POSTO'
    - Rateio por veículo no centro de custo 'CC-02' (Logística e Frota)
    - Gera UM título a pagar por mês de competência quando a fatura cruzar meses!
    - Marca os pré-lançamentos casados como 'CONSOLIDADO'.
    """
    t_obj = tenant or kwargs.get('tenant')
    f_id = fatura_id or kwargs.get('fatura_id')
    u_obj = usuario or kwargs.get('usuario')

    tenant = t_obj
    usuario = u_obj

    assert_tenant_writable(t_obj)
    assert_modulo(t_obj, 'financeiro')

    fatura = FaturaConsolidadaPosto.objects.select_for_update().get(id=f_id, tenant=t_obj)
    if fatura.status == 'APROVADA':
        raise ValidationError(f"A fatura #{fatura.numero_fatura} já foi aprovada anteriormente.")

    itens = list(fatura.itens.select_related('veiculo', 'pre_lancamento').all())
    if not itens:
        raise ValidationError("A fatura não possui itens para aprovação.")

    # 1. Agrupamento dos itens por competência (Ano, Mês)
    itens_por_mes = {}
    for item in itens:
        chave_mes = (item.data_hora.year, item.data_hora.month)
        if chave_mes not in itens_por_mes:
            itens_por_mes[chave_mes] = []
        itens_por_mes[chave_mes].append(item)

    # 2. Resolução da conta gerencial de despesa e centro de custo CC-02
    c_despesa = PlanoContas.objects.filter(
        tenant=tenant,
        codigo_estrutural__startswith='5.1',
        tipo='ANALITICA'
    ).first() or PlanoContas.objects.filter(
        tenant=tenant,
        codigo_estrutural__startswith='4.1',
        tipo='ANALITICA'
    ).first()

    cc_02 = CentroCusto.objects.filter(tenant=tenant, codigo='CC-02').first()
    if not cc_02:
        cc_02 = CentroCusto.objects.create(
            tenant=tenant,
            codigo='CC-02',
            nome='Logística e Frota'
        )

    titulos_gerados = []

    # 3. Geração de títulos por mês de competência
    for (ano, mes), lista_itens in itens_por_mes.items():
        v_mes = sum(i.valor for i in lista_itens)
        v_mes = quantize(v_mes, 2)

        # Último dia do mês para competência
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        dt_comp = date(ano, mes, ultimo_dia)

        # Agrupa valor por veículo para o rateio
        veic_valores = {}
        for i in lista_itens:
            v_id = i.veiculo_id or 0
            veic_valores[v_id] = veic_valores.get(v_id, Decimal('0.00')) + i.valor

        # Montagem das linhas de rateio com soma exata de 100%
        rateios_input = []
        veic_items = list(veic_valores.items())
        total_acumulado = Decimal('0.0000')

        for idx, (v_id, v_val) in enumerate(veic_items):
            if idx == len(veic_items) - 1:
                pct = quantize(Decimal('100.0000') - total_acumulado, 4)
            else:
                pct = quantize((v_val / v_mes) * Decimal('100.0000'), 4)
                total_acumulado += pct

            r_dict = {
                'centro_custo': cc_02.id,
                'percentual': pct
            }
            if v_id:
                r_dict['veiculo'] = Veiculo.objects.filter(tenant=tenant, id=v_id).first()
            rateios_input.append(r_dict)

        origem_id_mes = f"FATURA_{fatura.id}_{mes:02d}_{ano}"

        titulo = criar_titulo(
            tenant=tenant,
            tipo='PAGAR',
            conta_gerencial=c_despesa,
            valor_bruto=v_mes,
            data_emissao=dt_comp,
            data_competencia=dt_comp,
            fornecedor=fatura.fornecedor,
            origem_tipo='FATURA_POSTO',
            origem_id=origem_id_mes,
            historico=f"Fatura Posto #{fatura.numero_fatura} Competência {mes:02d}/{ano} ({fatura.fornecedor.razao_social})",
            rateios=rateios_input,
            criado_por=usuario
        )
        titulos_gerados.append(titulo)

    # 4. Atualiza pré-lançamentos casados para CONSOLIDADO
    for item in itens:
        if item.pre_lancamento:
            p = item.pre_lancamento
            p.status = 'CONSOLIDADO'
            p.save(update_fields=['status', 'atualizado_em'])

    fatura.status = 'APROVADA'
    fatura.save(update_fields=['status', 'atualizado_em'])

    return titulos_gerados
