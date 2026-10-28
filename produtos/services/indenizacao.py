import datetime
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Q
from django.utils import timezone

from core.money import quantize


def calcular_indenizacao(cilindro: Any, data: Optional[datetime.date] = None) -> dict[str, Any]:
    """
    Calcula os valores para processo de indenização por extravio ou dano de cilindro (Sprint 8A - Tarefa 9).
    Retorna o valor contratual (com fallback sinalizado para o valor contábil líquido caso não haja tabela vigente)
    e o ganho ou perda patrimonial (ganho_perda = valor_contratual - valor_contabil_liquido).
    """
    if cilindro is None:
        raise ValueError("Cilindro obrigatório para cálculo de indenização.")

    from produtos.models import TabelaIndenizacaoCilindro

    data_ref = data or timezone.localdate()
    tenant = getattr(cilindro, 'tenant', None)

    # 1. Busca parâmetro na TabelaIndenizacaoCilindro vigente
    tabela = None
    if tenant and hasattr(cilindro, 'modelo') and cilindro.modelo:
        qs_base = TabelaIndenizacaoCilindro.objects.filter(
            tenant=tenant,
            tipo_cilindro=cilindro.modelo,
            vigencia_inicio__lte=data_ref
        ).filter(
            Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=data_ref)
        )

        # Prioridade 1: Match exato com o gás químico dedicado do cilindro
        if getattr(cilindro, 'gas_dedicado', None):
            tabela = qs_base.filter(gas=cilindro.gas_dedicado).order_by('-vigencia_inicio').first()

        # Prioridade 2: Match genérico para o modelo do cilindro (sem restrição de gás)
        if not tabela:
            tabela = qs_base.filter(gas__isnull=True).order_by('-vigencia_inicio').first()

    # 2. Determina Valor Contábil Líquido (VCL)
    vcl_raw = getattr(cilindro, 'valor_contabil_liquido_atual', None)
    if vcl_raw is None:
        vcl_raw = getattr(cilindro, 'valor_aquisicao', None) or Decimal('0.00')
    valor_contabil_liquido = quantize(vcl_raw, 2)

    # 3. Determina Valor Contratual e Fallback
    if tabela and tabela.valor is not None:
        valor_contratual = quantize(tabela.valor, 2)
        origem = 'TABELA_CONTRATUAL'
        sinalizado_fallback = False
        tabela_id = str(tabela.id)
    else:
        # Fallback para o valor contábil líquido, sinalizado conforme requisito da v2.0
        valor_contratual = valor_contabil_liquido
        origem = 'VALOR_CONTABIL_FALLBACK'
        sinalizado_fallback = True
        tabela_id = None

    # 4. Cálculo de Ganho / Perda Patrimonial
    ganho_perda = quantize(valor_contratual - valor_contabil_liquido, 2)

    return {
        'cilindro_id': str(cilindro.id),
        'numero_serie_ogiva': getattr(cilindro, 'numero_serie_ogiva', ''),
        'codigo_qr': getattr(cilindro, 'codigo_qr', ''),
        'data_referencia': str(data_ref),
        'tabela_indenizacao_id': tabela_id,
        'origem': origem,
        'sinalizado_fallback': sinalizado_fallback,
        'valor_contratual': valor_contratual,
        'valor_contabil_liquido': valor_contabil_liquido,
        'ganho_perda': ganho_perda,
    }
