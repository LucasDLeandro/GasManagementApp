from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from produtos.models import Cilindro, TabelaIndenizacaoCilindro
from fiscal.models import (
    DocumentoFiscal,
    DocumentoFiscalItem,
    MovimentoComodatoFiscal,
    ConfiguracaoFiscalFilial,
)
from fiscal.services.numeracao_service import reservar_proximo_numero
from fiscal.services.motor_tributario_service import resolver_regra, calcular_tributos_item


def obter_valor_bem_cilindro(cilindro: Cilindro, tenant) -> Decimal:
    """
    Resolve o valor patrimonial / reposição do cilindro para a nota fiscal de comodato (Task 2).
    Ordem de resolução com fallback seguro:
    1. TabelaIndenizacaoCilindro vigente para o Modelo e Gás específico;
    2. TabelaIndenizacaoCilindro vigente para o Modelo do cilindro (sem gás específico);
    3. valor_aquisicao cadastrado no Cilindro (se > 0);
    4. Fallback padrão configurável de R$ 500,00 por cilindro. Proibido valor zero.
    """
    hoje = timezone.localdate()
    # 1. Modelo + Gás
    if cilindro.gas_dedicado_id and cilindro.modelo_id:
        tab_gas = TabelaIndenizacaoCilindro.objects.filter(
            tenant=tenant,
            tipo_cilindro_id=cilindro.modelo_id,
            gas_id=cilindro.gas_dedicado_id,
            vigencia_inicio__lte=hoje
        ).order_by('-vigencia_inicio').first()
        if tab_gas and (not tab_gas.vigencia_fim or tab_gas.vigencia_fim >= hoje):
            return quantize(tab_gas.valor)

    # 2. Modelo (sem gás)
    if cilindro.modelo_id:
        tab_mod = TabelaIndenizacaoCilindro.objects.filter(
            tenant=tenant,
            tipo_cilindro_id=cilindro.modelo_id,
            gas__isnull=True,
            vigencia_inicio__lte=hoje
        ).order_by('-vigencia_inicio').first()
        if tab_mod and (not tab_mod.vigencia_fim or tab_mod.vigencia_fim >= hoje):
            return quantize(tab_mod.valor)

    # 3. Valor de Aquisição
    if cilindro.valor_aquisicao and cilindro.valor_aquisicao > Decimal('0.00'):
        return quantize(cilindro.valor_aquisicao)

    # 4. Fallback padrão seguro
    return Decimal('500.00')


@transaction.atomic
def gerar_nfe_remessa_comodato(
    tenant,
    filial,
    cliente,
    cilindros: list[Cilindro],
    contrato=None,
    emissor_port=None
) -> DocumentoFiscal:
    """
    Gera rascunho de NF-e de remessa de cilindros em comodato agrupada por cliente (Task 2).
    Utiliza CFOP 5.908 (interno) ou 6.908 (interestadual).
    Registra MovimentoComodatoFiscal do tipo REMESSA para cada cilindro expedido.
    """
    assert_tenant_writable(tenant)

    if not cilindros:
        raise ValidationError("É necessário informar ao menos um cilindro para remessa em comodato.")

    numero, serie = reservar_proximo_numero(tenant, filial.id, modelo='NFE_55')
    uf_origem = filial.uf or 'SP'
    uf_destino = cliente.estado or uf_origem

    valor_total = Decimal('0.00')
    itens_dados = []

    for idx, cil in enumerate(cilindros, start=1):
        valor_unit = obter_valor_bem_cilindro(cil, tenant)
        valor_total += valor_unit
        itens_dados.append({
            'cilindro': cil,
            'numero_item': idx,
            'descricao': f"Cilindro {cil.modelo.descricao} - N/S {cil.numero_serie_ogiva}",
            'ncm': '73110000',  # NCM Vasilhames e Recipientes para Gases Comprimidos
            'quantidade': Decimal('1.000'),
            'valor_unitario': valor_unit,
            'valor_total': valor_unit,
        })

    doc = DocumentoFiscal.objects.create(
        tenant=tenant,
        filial=filial,
        modelo='NFE_55',
        tipo_operacao='REMESSA_COMODATO',
        status='RASCUNHO',
        numero=numero,
        serie=serie,
        valor_total=quantize(valor_total),
        origem_tipo='COMODATO_EXPEDICAO',
        origem_id=str(contrato.id if contrato else cliente.id)
    )

    for item_info in itens_dados:
        cil = item_info['cilindro']
        item_doc = DocumentoFiscalItem.objects.create(
            tenant=tenant,
            documento=doc,
            numero_item=item_info['numero_item'],
            descricao=item_info['descricao'],
            ncm=item_info['ncm'],
            cfop='6908' if uf_origem != uf_destino else '5908',
            quantidade=item_info['quantidade'],
            valor_unitario=item_info['valor_unitario'],
            valor_total=item_info['valor_total']
        )

        # Registra MovimentoComodatoFiscal
        MovimentoComodatoFiscal.objects.create(
            tenant=tenant,
            cilindro=cil,
            cliente=cliente,
            filial=filial,
            documento_fiscal=doc,
            tipo='REMESSA',
            data_movimento=timezone.now(),
            valor_bem=item_info['valor_unitario'],
            observacao=f"Remessa em comodato NF-e #{numero}/{serie}"
        )

    return doc


@transaction.atomic
def gerar_nfe_retorno_comodato(
    tenant,
    filial,
    cliente,
    cilindros: list[Cilindro],
    chave_nfe_remessa: str = ''
) -> DocumentoFiscal:
    """
    Gera documento fiscal de entrada para o retorno de cilindros em comodato (Task 2).
    CFOP 1.909 (interno) ou 2.909 (interestadual).
    Registra MovimentoComodatoFiscal do tipo RETORNO baixando a posse fiscal.
    """
    assert_tenant_writable(tenant)

    if not cilindros:
        raise ValidationError("É necessário informar ao menos um cilindro para retorno de comodato.")

    numero, serie = reservar_proximo_numero(tenant, filial.id, modelo='NFE_55')
    uf_origem = cliente.estado or filial.uf or 'SP'
    uf_destino = filial.uf or 'SP'

    valor_total = Decimal('0.00')
    itens_dados = []

    for idx, cil in enumerate(cilindros, start=1):
        valor_unit = obter_valor_bem_cilindro(cil, tenant)
        valor_total += valor_unit
        itens_dados.append({
            'cilindro': cil,
            'numero_item': idx,
            'descricao': f"Retorno de Cilindro {cil.modelo.descricao} - N/S {cil.numero_serie_ogiva}",
            'ncm': '73110000',
            'quantidade': Decimal('1.000'),
            'valor_unitario': valor_unit,
            'valor_total': valor_unit,
        })

    doc = DocumentoFiscal.objects.create(
        tenant=tenant,
        filial=filial,
        modelo='NFE_55',
        tipo_operacao='RETORNO_COMODATO',
        status='RASCUNHO',
        numero=numero,
        serie=serie,
        valor_total=quantize(valor_total),
        origem_tipo='RETORNO_COMODATO',
        origem_id=str(cliente.id)
    )

    for item_info in itens_dados:
        cil = item_info['cilindro']
        DocumentoFiscalItem.objects.create(
            tenant=tenant,
            documento=doc,
            numero_item=item_info['numero_item'],
            descricao=item_info['descricao'],
            ncm=item_info['ncm'],
            cfop='2909' if uf_origem != uf_destino else '1909',
            quantidade=item_info['quantidade'],
            valor_unitario=item_info['valor_unitario'],
            valor_total=item_info['valor_total']
        )

        MovimentoComodatoFiscal.objects.create(
            tenant=tenant,
            cilindro=cil,
            cliente=cliente,
            filial=filial,
            documento_fiscal=doc,
            tipo='RETORNO',
            data_movimento=timezone.now(),
            valor_bem=item_info['valor_unitario'],
            chave_nfe=chave_nfe_remessa,
            observacao=f"Retorno de comodato NF-e #{numero}/{serie}"
        )

    return doc


def relatorio_divergencias_comodato(tenant, filial=None, prazo_dias_padrao: int = 30) -> list[dict]:
    """
    Relatório de conciliação entre posse física e posse fiscal de cilindros (Task 3).
    Divergências detectadas:
    1. SEM_NOTA_REMESSA: Cilindro em posse física do cliente sem NF-e de remessa aberta;
    2. ESTADIA_EXCEDIDA: Cilindro com remessa fiscal aberta há mais de 30 dias (ou prazo do contrato);
    3. PENDENTE_RETORNO_FISCAL: Cilindro retornado fisicamente ao pátio da empresa, mas com remessa fiscal sem baixa.
    """
    agora = timezone.now()
    qs_cilindros = Cilindro.objects.filter(tenant=tenant)
    divergencias = []

    for cil in qs_cilindros.select_related('modelo', 'cliente_posse_atual'):
        ultimo_mov = MovimentoComodatoFiscal.objects.filter(
            tenant=tenant,
            cilindro=cil
        ).order_by('-data_movimento').first()

        posse_fisica_cliente = (cil.status == 'EM_POSSE_CLIENTE' or cil.cliente_posse_atual_id is not None)
        posse_fiscal_aberta = (ultimo_mov is not None and ultimo_mov.tipo == 'REMESSA')

        # 1. Posse física com cliente sem nota de remessa
        if posse_fisica_cliente and not posse_fiscal_aberta:
            divergencias.append({
                'cilindro_id': cil.id,
                'numero_serie': cil.numero_serie_ogiva,
                'cliente': cil.cliente_posse_atual.nome if cil.cliente_posse_atual else 'Cliente não informado',
                'tipo_divergencia': 'SEM_NOTA_REMESSA',
                'descricao': f"Cilindro #{cil.numero_serie_ogiva} está fisicamente no cliente sem NF-e de remessa em comodato ativa.",
                'dias': (agora - cil.posse_desde).days if cil.posse_desde else 0
            })

        # 2. Posse fiscal aberta com estadia excedida
        elif posse_fiscal_aberta and posse_fisica_cliente:
            dias_aberto = (agora - ultimo_mov.data_movimento).days
            if dias_aberto > prazo_dias_padrao:
                divergencias.append({
                    'cilindro_id': cil.id,
                    'numero_serie': cil.numero_serie_ogiva,
                    'cliente': ultimo_mov.cliente.nome if ultimo_mov.cliente else 'Desconhecido',
                    'tipo_divergencia': 'ESTADIA_EXCEDIDA',
                    'descricao': f"Remessa em comodato emitida há {dias_aberto} dias (limite: {prazo_dias_padrao} dias) sem nota de retorno.",
                    'dias': dias_aberto,
                    'documento_remessa_id': ultimo_mov.documento_fiscal_id
                })

        # 3. Cilindro voltou fisicamente ao pátio mas a nota de remessa continua aberta
        elif not posse_fisica_cliente and posse_fiscal_aberta:
            divergencias.append({
                'cilindro_id': cil.id,
                'numero_serie': cil.numero_serie_ogiva,
                'cliente': ultimo_mov.cliente.nome if ultimo_mov.cliente else 'Desconhecido',
                'tipo_divergencia': 'PENDENTE_RETORNO_FISCAL',
                'descricao': f"Cilindro #{cil.numero_serie_ogiva} está no pátio ({cil.status}), porém a remessa fiscal para {ultimo_mov.cliente.nome} não possui retorno registrado.",
                'dias': (agora - ultimo_mov.data_movimento).days,
                'documento_remessa_id': ultimo_mov.documento_fiscal_id
            })

    return divergencias
