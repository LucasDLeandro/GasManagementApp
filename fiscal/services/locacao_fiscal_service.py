from decimal import Decimal
from datetime import date
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from fiscal.models import (
    DocumentoFiscal,
    DocumentoFiscalItem,
    ItemDocumentoTributo,
    ConfiguracaoFiscalFilial,
)
from fiscal.services.numeracao_service import reservar_proximo_numero


@transaction.atomic
def gerar_fatura_locacao(
    tenant,
    filial,
    cliente,
    periodo_inicio: date,
    periodo_fim: date,
    itens_locacao: list[dict],
    numero_contrato: str = ''
) -> DocumentoFiscal:
    """
    Gera Fatura de Locação / Estadia de Cilindros (Task 4 - Modelo FATURA_LOCACAO).
    Tratamento Tributário (Súmula Vinculante 31 do STF):
    - Locação pura de bens móveis NÃO sofre incidência de ICMS nem ISS (base e alíquota 0%).
    - PIS e COFINS aplicam-se conforme o regime tributário da Filial:
        * SIMPLES_NACIONAL: PIS 0%, COFINS 0%
        * REGIME_NORMAL (Lucro Presumido): PIS 0,65%, COFINS 3,00%
        * REGIME_NORMAL (Lucro Real): PIS 1,65%, COFINS 7,60%
    - O Tenant parametriza tratamento_locacao:
        * FATURA_SEM_DOCUMENTO_FISCAL (Fatura numerada com validade jurídica)
        * NFSE_MUNICIPAL (emissão via NFS-e municipal se exigido pela prefeitura)
    - Integração contábil: alimenta a conta 3.1.3 (Receita de Locação e Estadia).
    """
    assert_tenant_writable(tenant)

    if not itens_locacao:
        raise ValidationError("A fatura de locação deve conter ao menos um item de cilindro/diária.")

    # Busca configuração fiscal da filial para identificar regime
    config_fiscal = ConfiguracaoFiscalFilial.objects.filter(tenant=tenant, filial=filial).first()
    regime = config_fiscal.regime_tributario if config_fiscal else 'SIMPLES_NACIONAL'

    # Alíquotas PIS/COFINS
    if regime == 'SIMPLES_NACIONAL':
        aliq_pis = Decimal('0.0000')
        aliq_cofins = Decimal('0.0000')
    elif regime == 'REGIME_NORMAL':
        # Default Lucro Presumido cumulativo
        aliq_pis = Decimal('0.0065')
        aliq_cofins = Decimal('0.0300')
    else:
        aliq_pis = Decimal('0.0000')
        aliq_cofins = Decimal('0.0000')

    valor_total_fatura = Decimal('0.00')
    for item in itens_locacao:
        dias = int(item.get('dias', 1))
        valor_diaria = Decimal(str(item.get('valor_diaria', '0.00')))
        qtd = Decimal(str(item.get('quantidade', '1')))
        subtotal = quantize(qtd * valor_diaria * Decimal(str(dias)))
        item['_subtotal'] = subtotal
        valor_total_fatura += subtotal

    numero, serie = reservar_proximo_numero(tenant, filial.id, modelo='FATURA_LOCACAO')

    doc = DocumentoFiscal.objects.create(
        tenant=tenant,
        filial=filial,
        modelo='FATURA_LOCACAO',
        tipo_operacao='FATURA_LOCACAO',
        status='AUTORIZADO',  # Fatura com validade direta
        numero=numero,
        serie=serie,
        valor_total=quantize(valor_total_fatura),
        origem_tipo='CONTRATO_LOCACAO',
        origem_id=numero_contrato or str(cliente.id),
        danfe_url=f"/fiscal/faturas-locacao/{tenant.id}/{numero}/pdf/"
    )

    total_pis = Decimal('0.00')
    total_cofins = Decimal('0.00')

    for idx, item in enumerate(itens_locacao, start=1):
        subtotal = item['_subtotal']
        doc_item = DocumentoFiscalItem.objects.create(
            tenant=tenant,
            documento=doc,
            numero_item=idx,
            descricao=item.get('descricao', f"Locação de Cilindros ({item.get('dias', 1)} dias)"),
            ncm='00000000',
            cfop='0000',
            quantidade=Decimal(str(item.get('quantidade', 1))),
            valor_unitario=Decimal(str(item.get('valor_diaria', 0))),
            valor_total=subtotal
        )

        # 1. ICMS: Isento / Não Tributado (Súmula Vinculante 31 STF)
        ItemDocumentoTributo.objects.create(
            tenant=tenant,
            item=doc_item,
            tributo='ICMS',
            base=Decimal('0.00'),
            aliquota=Decimal('0.0000'),
            valor=Decimal('0.00'),
            cst='41'
        )

        # 2. ISS: Isento / Não Incidente (Súmula Vinculante 31 STF)
        ItemDocumentoTributo.objects.create(
            tenant=tenant,
            item=doc_item,
            tributo='ISS',
            base=Decimal('0.00'),
            aliquota=Decimal('0.0000'),
            valor=Decimal('0.00'),
            cst='41'
        )

        # 3. PIS conforme regime
        v_pis = quantize(subtotal * aliq_pis)
        total_pis += v_pis
        ItemDocumentoTributo.objects.create(
            tenant=tenant,
            item=doc_item,
            tributo='PIS',
            base=subtotal if aliq_pis > 0 else Decimal('0.00'),
            aliquota=aliq_pis,
            valor=v_pis,
            cst='01' if aliq_pis > 0 else '08'
        )

        # 4. COFINS conforme regime
        v_cofins = quantize(subtotal * aliq_cofins)
        total_cofins += v_cofins
        ItemDocumentoTributo.objects.create(
            tenant=tenant,
            item=doc_item,
            tributo='COFINS',
            base=subtotal if aliq_cofins > 0 else Decimal('0.00'),
            aliquota=aliq_cofins,
            valor=v_cofins,
            cst='01' if aliq_cofins > 0 else '08'
        )

    # Integração Financeira (Conta 3.1.3 - Receita de Locação e Estadia de Cilindros)
    if getattr(tenant, 'modulo_financeiro_ativo', False):
        try:
            from financeiro.models import PlanoContas, TituloFinanceiro, ParcelaFinanceira
            conta_313 = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='3.1.3').first()
            if not conta_313:
                conta_313 = PlanoContas.objects.filter(tenant=tenant, tipo='ANALITICA', aceita_lancamento=True).first()
            if conta_313:
                v_tot = quantize(valor_total_fatura)
                titulo, _ = TituloFinanceiro.objects.get_or_create(
                    tenant=tenant,
                    origem_tipo='FATURA_ESTADIA',
                    origem_id=str(doc.id),
                    defaults={
                        'filial': filial,
                        'tipo': 'RECEBER',
                        'cliente': cliente,
                        'conta_gerencial': conta_313,
                        'valor_bruto': v_tot,
                        'valor_liquido_esperado': v_tot,
                        'data_emissao': timezone.localdate(),
                        'data_competencia': timezone.localdate(),
                        'historico': f"Fatura de Locação #{doc.numero} ({cliente.nome})",
                        'status': 'ABERTO'
                    }
                )
                ParcelaFinanceira.objects.get_or_create(
                    tenant=tenant,
                    titulo=titulo,
                    numero_parcela=1,
                    defaults={
                        'total_parcelas': 1,
                        'data_vencimento': timezone.localdate() + timezone.timedelta(days=15),
                        'valor_nominal': v_tot,
                        'saldo_em_aberto': v_tot,
                        'status': 'PENDENTE'
                    }
                )
        except Exception:
            pass

    return doc
