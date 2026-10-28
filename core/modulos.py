from typing import Any

MODULOS_REGISTRO: dict[str, dict[str, Any]] = {
    'patrimonio': {
        'codigo': 'patrimonio',
        'flag': 'modulo_patrimonio_ativo',
        'rotulo': 'Patrimônio de Cilindros',
        'requer': [],
        'recomenda': [],
        'descricao': 'Rastreabilidade individual de cilindros, lotes e certificados de conformidade.',
    },
    'comercial': {
        'codigo': 'comercial',
        'flag': 'modulo_comercial_ativo',
        'rotulo': 'Gestão Comercial e Clientes',
        'requer': ['patrimonio'],
        'recomenda': [],
        'descricao': 'Contratos de comodato, contas de clientes e precificação.',
    },
    'vendas': {
        'codigo': 'vendas',
        'flag': 'modulo_vendas_ativo',
        'rotulo': 'Vendas e Pedidos',
        'requer': ['patrimonio'],
        'recomenda': [],
        'descricao': 'Emissão de pedidos, faturamento e vendas no balcão ou entrega.',
    },
    'envase': {
        'codigo': 'envase',
        'flag': 'modulo_envase_ativo',
        'rotulo': 'Envase e Rampa de Produção',
        'requer': ['patrimonio'],
        'recomenda': [],
        'descricao': 'Rampa de envase, apontamento de produção e controle de pureza analítica.',
    },
    'logistica': {
        'codigo': 'logistica',
        'flag': 'modulo_logistica_ativo',
        'rotulo': 'Logística e Frotas',
        'requer': ['vendas'],
        'recomenda': [],
        'descricao': 'Roteirização de entregas, mapa de cargas e tracking veicular em tempo real.',
    },
    'fiscal': {
        'codigo': 'fiscal',
        'flag': 'modulo_fiscal_ativo',
        'rotulo': 'Hub Fiscal (NF-e/NFC-e)',
        'requer': ['vendas'],
        'recomenda': [],
        'descricao': 'Transmissão de NF-e/NFC-e, MDF-e, cálculo de impostos e DANFE.',
    },
    'b2b': {
        'codigo': 'b2b',
        'flag': 'modulo_b2b_ativo',
        'rotulo': 'Portal B2B Autoatendimento',
        'requer': ['comercial', 'vendas'],
        'recomenda': [],
        'descricao': 'Portal externo para autoatendimento de clientes, pedidos e 2ª via de faturas.',
    },
    'financeiro': {
        'codigo': 'financeiro',
        'flag': 'modulo_financeiro_ativo',
        'rotulo': 'Financeiro e Cobrança',
        'requer': [],
        'recomenda': ['comercial', 'vendas'],
        'descricao': 'Contas a pagar e receber, conciliação bancária, DRE e régua de cobrança.',
    },
    'analytics': {
        'codigo': 'analytics',
        'flag': 'modulo_analytics_ativo',
        'rotulo': 'Baros Analytics & IA',
        'requer': [],
        'recomenda': ['financeiro', 'logistica'],
        'descricao': 'Dashboard executivo, previsão de churn e análise de giro de cilindros.',
    },
}


def is_modulo_ativo(tenant: Any, codigo_modulo: str) -> bool:
    """Verifica se um módulo está ativo no tenant."""
    if not tenant:
        return False
    info = MODULOS_REGISTRO.get(codigo_modulo)
    if not info:
        return False

    # 1. Se tenant define lista modulos_ativos explicitamente (ex: em testes ou mock)
    mod_list = getattr(tenant, 'modulos_ativos', None)
    if isinstance(mod_list, (list, tuple, set)):
        return codigo_modulo in mod_list

    # 2. Flag explícita no tenant
    flag = getattr(tenant, info['flag'], False)
    if flag:
        return True

    # 3. Resolução por plano contratado (PRO / ENTERPRISE incluem B2B, fiscal, etc.)
    plano = str(getattr(tenant, 'plano', '')).upper()
    if plano in ('PRO', 'PROFISSIONAL', 'ENTERPRISE'):
        if codigo_modulo in ('patrimonio', 'comercial', 'vendas', 'envase', 'logistica', 'fiscal', 'b2b', 'financeiro'):
            return True
        if plano in ('ENTERPRISE',) and codigo_modulo == 'analytics':
            return True

    return False


def obter_modulos_ativos(tenant: Any) -> list[str]:
    """Retorna a lista de códigos dos módulos ativos no tenant."""
    if not tenant:
        return []
    return [cod for cod in MODULOS_REGISTRO.keys() if is_modulo_ativo(tenant, cod)]


def validar_toggle(tenant: Any, modulo: str, novo_valor: bool) -> list[str]:
    """
    Valida a ativação ou desativação de um módulo em conformidade com a matriz de dependências.
    Retorna lista vazia se a transição for válida, ou lista de mensagens legíveis de erro.
    """
    if modulo not in MODULOS_REGISTRO:
        return [f"Módulo desconhecido: '{modulo}'."]

    erros: list[str] = []
    mod_info = MODULOS_REGISTRO[modulo]
    rotulo = mod_info['rotulo']

    if novo_valor is True:
        # Ligar exige todos os 'requer' ativos
        for req in mod_info['requer']:
            if not is_modulo_ativo(tenant, req):
                req_rotulo = MODULOS_REGISTRO[req]['rotulo']
                erros.append(
                    f"Para ativar o módulo '{rotulo}' ({modulo}), é obrigatório que o módulo '{req_rotulo}' ({req}) esteja ativo."
                )
    else:
        # Desligar é bloqueado se existir módulo ativo que o requer
        for outro_cod, outro_info in MODULOS_REGISTRO.items():
            if outro_cod != modulo and is_modulo_ativo(tenant, outro_cod) and modulo in outro_info['requer']:
                erros.append(
                    f"Não é possível desativar o módulo '{rotulo}' ({modulo}), pois o módulo ativo '{outro_info['rotulo']}' ({outro_cod}) depende dele."
                )

    return erros
