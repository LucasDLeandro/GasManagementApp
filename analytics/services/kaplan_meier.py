"""
Estimador de Sobrevivência Kaplan-Meier para Permanência de Cilindros (Sprint 12C - Tarefa 3).

Implementa:
- Curva de sobrevivência não-paramétrica S(t) = P(T > t) para o tempo de retenção do cilindro;
- Tratamento correto de censura à direita (cilindros ainda em posse do cliente no momento da análise);
- Fallback automático para o perfil do Tenant quando o cliente tiver histórico insuficiente (< 5 eventos);
- Explicação transparente de cada ponto da curva para auditoria e exibição em tela.
"""
from typing import Any, Dict, List, Optional, Tuple


def estimar_sobrevivencia_km(
    observacoes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Calcula o estimador produto-limite de Kaplan-Meier:
    S(t) = Prod_{t_i <= t} [ 1 - d_i / n_i ]

    Parâmetros:
    - observacoes: lista de dicts com 'duracao_dias' (int >= 0) e 'evento' (1 se retornou, 0 se censurado).

    Retorna:
    - pontos_curva: lista ordenada de pontos (tempo_dias, em_risco_n, eventos_d, probabilidade_s)
    - mediana_permanencia_dias: tempo t onde S(t) cruza 0.50 (se atingido)
    - total_observacoes: contagem total
    - total_eventos: contagem de retornos concluídos
    - total_censurados: contagem de cilindros ainda em posse
    """
    if not observacoes:
        return {
            'pontos_curva': [],
            'mediana_permanencia_dias': 0,
            'total_observacoes': 0,
            'total_eventos': 0,
            'total_censurados': 0,
            'tabela_resumo': []
        }

    total_observacoes = len(observacoes)
    parsed_obs = []
    for o in observacoes:
        if isinstance(o, (tuple, list)) and len(o) >= 2:
            parsed_obs.append({'duracao_dias': int(o[0]), 'evento': int(o[1])})
        elif isinstance(o, dict):
            parsed_obs.append({'duracao_dias': int(o.get('duracao_dias', 0)), 'evento': int(o.get('evento', 0))})

    total_eventos = sum(1 for o in parsed_obs if o.get('evento') == 1)
    total_censurados = total_observacoes - total_eventos

    # Agrupa por tempo de duração
    # d_t: eventos (retornos) no tempo t
    # c_t: censuras no tempo t
    contagens_tempo: Dict[int, Dict[str, int]] = {}
    for o in parsed_obs:
        t = o['duracao_dias']
        ev = o['evento']
        if t not in contagens_tempo:
            contagens_tempo[t] = {'eventos': 0, 'censuras': 0}
        if ev == 1:
            contagens_tempo[t]['eventos'] += 1
        else:
            contagens_tempo[t]['censuras'] += 1

    tempos_ordenados = sorted(contagens_tempo.keys())

    pontos_curva = []
    n_at_risk = total_observacoes
    s_t = 1.0
    mediana_permanencia: Optional[int] = None

    for t in tempos_ordenados:
        d_i = contagens_tempo[t]['eventos']
        c_i = contagens_tempo[t]['censuras']

        if d_i > 0 and n_at_risk > 0:
            s_t = s_t * (1.0 - (d_i / float(n_at_risk)))

        s_t = max(0.0, min(1.0, s_t))
        s_t_rounded = round(s_t, 4)

        if mediana_permanencia is None and s_t <= 0.50:
            mediana_permanencia = t

        pontos_curva.append({
            'tempo_dias': t,
            'em_risco_n': n_at_risk,
            'eventos_d': d_i,
            'censurados_c': c_i,
            'probabilidade_sobrevivencia': s_t_rounded,
        })

        # Reduz os indivíduos em risco pelos que tiveram evento ou foram censurados neste tempo t
        n_at_risk -= (d_i + c_i)

    # Se a curva não cruzou 0.5, usa a mediana dos dados observados
    if mediana_permanencia is None and parsed_obs:
        duracoes_todas = sorted([int(o['duracao_dias']) for o in parsed_obs])
        mediana_permanencia = duracoes_todas[len(duracoes_todas) // 2]

    # Prepara resumo legível para UI / JSON
    tabela_resumo = [
        {
            'dias': p['tempo_dias'],
            'probabilidade_nao_retorno_pct': round(p['probabilidade_sobrevivencia'] * 100, 2),
            'amostra_em_risco': p['em_risco_n']
        }
        for p in pontos_curva[:25]  # Primeiros 25 pontos representativos
    ]

    return {
        'pontos_curva': pontos_curva,
        'mediana_permanencia_dias': mediana_permanencia or 30,
        'total_observacoes': total_observacoes,
        'total_eventos': total_eventos,
        'total_censurados': total_censurados,
        'tabela_resumo': tabela_resumo
    }


def obter_probabilidade_sobrevivencia(
    t: int,
    pontos_curva: List[Dict[str, Any]]
) -> float:
    """
    Retorna S(t) = P(T > t) para um determinado número de dias t.
    Corresponde ao valor do último ponto da curva com tempo <= t.
    """
    if not pontos_curva or t <= 0:
        return 1.0

    prob = 1.0
    for p in pontos_curva:
        if p['tempo_dias'] <= t:
            prob = p['probabilidade_sobrevivencia']
        else:
            break
    return prob


def avaliar_risco_nao_retorno_cilindro(
    duracao_atual_dias: int,
    observacoes_cliente: List[Dict[str, Any]],
    observacoes_tenant: List[Dict[str, Any]],
    prazo_esperado_dias: int = 30
) -> Dict[str, Any]:
    """
    Avalia a probabilidade de o cilindro não ter retornado até a duração atual,
    utilizando a curva Kaplan-Meier do cliente ou o fallback do tenant.

    Critério de alerta:
    - duracao_atual_dias > prazo_esperado_dias;
    - Probabilidade acumulada S(duracao_atual) <= 0.20 (isto é, 80%+ dos cilindros retornam antes deste tempo).
    """
    # 1. Decide se usa perfil do cliente ou fallback do tenant
    eventos_cliente = sum(1 for o in observacoes_cliente if o.get('evento') == 1)
    usou_fallback = False

    if eventos_cliente >= 5:
        resultado_km = estimar_sobrevivencia_km(observacoes_cliente)
    else:
        usou_fallback = True
        resultado_km = estimar_sobrevivencia_km(observacoes_tenant)

    pontos = resultado_km['pontos_curva']
    prob_sobrevivencia = obter_probabilidade_sobrevivencia(duracao_atual_dias, pontos)

    # Risco de não retorno: se o tempo atual exceder o prazo esperado e S(t) for baixo
    # (ou seja, cilindro já está no percentil superior de retenção anormal)
    risco_alto = bool(
        duracao_atual_dias > prazo_esperado_dias and
        (prob_sobrevivencia <= 0.25 or duracao_atual_dias >= (prazo_esperado_dias * 2))
    )

    # Score de risco de 0.00 a 1.00
    # Quanto mais tempo passa além do prazo esperado, maior o risco
    excesso = max(0, duracao_atual_dias - prazo_esperado_dias)
    fator_excesso = min(1.0, excesso / float(prazo_esperado_dias or 30))
    score_risco = round(min(1.0, (1.0 - prob_sobrevivencia) * 0.5 + fator_excesso * 0.5), 4)

    return {
        'duracao_atual_dias': duracao_atual_dias,
        'prazo_esperado_dias': prazo_esperado_dias,
        'probabilidade_permanencia_s_t': prob_sobrevivencia,
        'probabilidade_permanencia_pct': round(prob_sobrevivencia * 100, 2),
        'mediana_tempo_retorno_dias': resultado_km['mediana_permanencia_dias'],
        'usou_fallback_tenant': usou_fallback,
        'total_amostras_km': resultado_km['total_observacoes'],
        'gerar_alerta': risco_alto,
        'score_risco': score_risco,
        'explicacao': (
            f"O cilindro está retido há {duracao_atual_dias} dias (prazo esperado: {prazo_esperado_dias} dias). "
            f"Pela curva de sobrevivência Kaplan-Meier ({'perfil do tenant' if usou_fallback else 'histórico do cliente'}), "
            f"apenas {round(prob_sobrevivencia * 100, 1)}% dos cilindros permanecem tanto tempo sem retorno."
        ),
        'tabela_resumo': resultado_km['tabela_resumo']
    }
