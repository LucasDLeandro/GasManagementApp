from decimal import Decimal
from datetime import date
from django.utils import timezone
from fiscal.models import RegraTributaria, RegraTributariaTributo


def seed_regras_tributarias_gases(tenant, filial=None, uf: str = '') -> list[RegraTributaria]:
    """
    Cria regras tributárias de exemplo para operações fiscais de gases (Sprint 11B - Tarefa 1).
    IMPORTANTE: Conforme aviso de método, todos os exemplos entram como regras NÃO APROVADAS
    (aprovada_por=None), editáveis por UF, e só podem ser utilizadas em produção após
    homologação e aprovação formal do contador.
    """
    hoje = timezone.localdate()
    regras_criadas = []

    exemplos = [
        # 1. Comodato de Cilindros
        {
            'descricao': 'Remessa de Cilindro em Comodato (Exemplo v2.0)',
            'tipo_operacao': 'REMESSA_COMODATO',
            'ncm': '73110000',
            'cfop': '5908',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '41', 'aliquota': Decimal('0.0000')},  # Não tributada
                {'tributo': 'PIS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
                {'tributo': 'COFINS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
            ]
        },
        {
            'descricao': 'Retorno de Cilindro em Comodato (Exemplo v2.0)',
            'tipo_operacao': 'RETORNO_COMODATO',
            'ncm': '73110000',
            'cfop': '1909',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '41', 'aliquota': Decimal('0.0000')},
                {'tributo': 'PIS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
                {'tributo': 'COFINS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
            ]
        },
        # 2. Vasilhame / Sacaria
        {
            'descricao': 'Remessa de Vasilhame ou Sacaria (Exemplo v2.0)',
            'tipo_operacao': 'REMESSA_VASILHAME',
            'ncm': '73110000',
            'cfop': '5920',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '41', 'aliquota': Decimal('0.0000')},
                {'tributo': 'PIS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
                {'tributo': 'COFINS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
            ]
        },
        {
            'descricao': 'Retorno de Vasilhame ou Sacaria (Exemplo v2.0)',
            'tipo_operacao': 'RETORNO_VASILHAME',
            'ncm': '73110000',
            'cfop': '1921',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '41', 'aliquota': Decimal('0.0000')},
                {'tributo': 'PIS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
                {'tributo': 'COFINS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
            ]
        },
        # 3. Reteste / Manutenção / Conserto
        {
            'descricao': 'Remessa para Reteste ou Conserto (Exemplo v2.0)',
            'tipo_operacao': 'REMESSA_CONSERTO',
            'ncm': '73110000',
            'cfop': '5915',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '41', 'aliquota': Decimal('0.0000')},
                {'tributo': 'PIS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
                {'tributo': 'COFINS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
            ]
        },
        {
            'descricao': 'Retorno de Reteste ou Conserto (Exemplo v2.0)',
            'tipo_operacao': 'RETORNO_CONSERTO',
            'ncm': '73110000',
            'cfop': '1916',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '41', 'aliquota': Decimal('0.0000')},
                {'tributo': 'PIS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
                {'tributo': 'COFINS', 'cst_csosn': '08', 'aliquota': Decimal('0.0000')},
            ]
        },
        # 4. Devolução de Venda
        {
            'descricao': 'Devolução de Venda de Mercadoria (Exemplo v2.0)',
            'tipo_operacao': 'DEVOLUCAO_VENDA',
            'ncm': '',
            'cfop': '1202',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '102', 'aliquota': Decimal('0.0000')},
                {'tributo': 'PIS', 'cst_csosn': '49', 'aliquota': Decimal('0.0000')},
                {'tributo': 'COFINS', 'cst_csosn': '49', 'aliquota': Decimal('0.0000')},
            ]
        },
        # 5. Recarga de Terceiros (Industrialização por Encomenda)
        {
            'descricao': 'Industrialização / Envase de Cilindro de Cliente (Exemplo v2.0)',
            'tipo_operacao': 'RECARGA_TERCEIRO',
            'ncm': '',
            'cfop': '5124',
            'tributos': [
                {'tributo': 'ICMS', 'cst_csosn': '102', 'aliquota': Decimal('0.0000')},
                {'tributo': 'PIS', 'cst_csosn': '01', 'aliquota': Decimal('0.0065')},
                {'tributo': 'COFINS', 'cst_csosn': '01', 'aliquota': Decimal('0.0300')},
            ]
        },
    ]

    for ex in exemplos:
        regra, criada = RegraTributaria.objects.get_or_create(
            tenant=tenant,
            tipo_operacao=ex['tipo_operacao'],
            descricao=ex['descricao'],
            defaults={
                'vigencia_inicio': hoje,
                'ncm': ex['ncm'],
                'cfop': ex['cfop'],
                'uf_origem': uf or '',
                'uf_destino': '',
                'aprovada_por': None,  # Não aprovada por padrão (Exige aprovação do contador)
                'aprovada_em': None
            }
        )
        if criada:
            for trib in ex['tributos']:
                RegraTributariaTributo.objects.create(
                    tenant=tenant,
                    regra=regra,
                    tributo=trib['tributo'],
                    cst_csosn=trib['cst_csosn'],
                    aliquota=trib['aliquota'],
                    reducao_base_pct=Decimal('0.0000')
                )
        regras_criadas.append(regra)

    return regras_criadas
