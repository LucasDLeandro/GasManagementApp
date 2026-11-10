# Sprint 01.00 — Lotes e CQ: liberação do lote pelo RT com registro e regras

Leia antes: `CLAUDE.md`, `docs/PROGRESSO.md` e `docs/sprints/00_REGRAS_GERAIS.md` (inteiro). Primeira sprint da sequência.
Leia também: `docs/DESIGN_SYSTEM.md`, a seção 5 de `docs/GUIA_MODULOS_BAROS.md` e o Recall (`produtos/static/produtos/js/recall.js`), que é a referência de tela pronta.
**Branch:** `sprint-01.00/lotes-cq` a partir de `fase-2/produtos`.

## Objetivo
O Responsável Técnico (RT) aprova ou reprova lotes de envase pela aba Lotes/CQ de `/produtos/` com confirmação, regras de transição no backend e registro de quem liberou, quando e com qual justificativa. Um RT real está testando o sistema: esta é a tela que ele mais usa.

## O que está errado (verificado em 10/11/2026)
1. **Sem máquina de estados.** `produtos/services/ciclo_cilindro.py::atualizar_qualidade_lote` aceita qualquer status a partir de qualquer status. Um lote `REPROVADO` volta a `APROVADO` sem justificativa (os cilindros continuam bloqueados, mas o lote aparece aprovado). Viola a regra 3.7.
2. **Reprovação sem motivo no backend.** O mínimo de 10 caracteres existe só no front (`reprovarLoteComJustificativa`); a API aceita justificativa vazia e grava um texto padrão no bloqueio.
3. **Aprovação sem confirmação e sem registro.** O botão "Aprovar" (`fase3_rampa_recebimento_lotes.js`, `onclick="CentralLotesCQ.alterarQualidade(id, 'APROVADO')"`) muda o status com um clique. `LoteEnvase` só guarda o RT do momento da criação; não há registro de quem aprovou/reprovou nem quando.
4. **Botões para todos os papéis.** Aprovar/Reprovar aparecem para qualquer usuário; o backend devolve 403 para quem não é RT (correto), mas a tela não explica.
5. **Erros engolidos e `except Exception`.** `CentralLotesCQ.carregar` só faz `console.error`. A action `qualidade` em `produtos/views.py` (`LoteEnvaseViewSet.atualizar_qualidade`) tem `except Exception` devolvendo `str(e)` (regra 3.9).
6. **XSS e estilo.** A linha da tabela é montada com `tr.innerHTML` contendo `codigo_lote`, `gas_nome`, `rt_nome_snapshot`, e `onclick` com `'${l.codigo_lote}'` (injeção). `_aba_lotes.html` tem 27 `style="`; botões com cores fixas (`#16a34a`, `#dc2626`). Usa `fetch` + `getAuthHeaders` em vez de `Baros.api`.

## O que já existe (não refazer)
- `_verificar_permissao_rt` (RT pelo `Membership.papel`, superusuário passa) e `_obter_responsavel_tecnico` em `ciclo_cilindro.py`.
- Bloqueio sanitário automático dos cilindros quando o lote é reprovado, com `AuditoriaBloqueioSanitario` (manter).
- Bloqueio de entrega/rota de cilindro cujo lote não está `APROVADO` (manter).
- Endpoint `POST /produtos/api/lotes/{id}/qualidade/` (`novo_status`, `justificativa`) e o download de laudo `api/lotes-anvisa/{id}/laudo/`.

## Escopo
### Backend
- Transições permitidas (constante `TRANSICOES_QUALIDADE_LOTE` no service), todas só para RT:
  - `QUARENTENA → APROVADO` (justificativa opcional);
  - `QUARENTENA → REPROVADO` e `APROVADO → REPROVADO` (justificativa obrigatória, ≥ 10 caracteres, validada no backend).
  - Qualquer outra transição → 400 com mensagem clara. `REPROVADO` é final (ver Decisões pendentes).
- Novo modelo imutável `HistoricoQualidadeLote` (`TenantAwareModel`): `lote`, `status_anterior`, `status_novo`, `justificativa`, `usuario`, `responsavel_tecnico` (FK), `rt_nome_snapshot`, `rt_registro_snapshot` (`CONSELHO-UF NUMERO`), `criado_em`. Uma linha por mudança, gravada pelo service. Sem edição nem exclusão (nem no admin).
- Serializer do lote: `ultima_liberacao` (status, RT, registro, data) e `transicoes_permitidas` para o usuário da requisição (lista vazia para quem não é RT). `status_qualidade` continua `read_only`.
- Action `GET /produtos/api/lotes/{id}/historico-qualidade/`.
- Trocar o `except Exception` da action por tratamento explícito (`PermissionError` → 403, `ValidationError` → 400 no formato DRF).
### Tela (aba Lotes/CQ)
- Cartões: em quarentena, aprovados, reprovados (contagem por agregação, sem N+1).
- Tabela montada com `createElement`/`textContent`; badge `badge-status-*` por status; coluna "Liberado por" (RT, registro e data da última liberação).
- Botões só das `transicoes_permitidas`. Para quem não é RT: texto "Liberação restrita ao RT".
- **Aprovar:** `Baros.confirmar` mostrando lote, gás, pureza, validade e se há laudo PDF; se não houver laudo, aviso em destaque (não bloqueia; ver S16).
- **Reprovar:** `Baros.confirmar({motivo: 10, perigo: true})`, mantendo o texto do bloqueio dos cilindros.
- Linha expansível ou drawer com o histórico de qualidade do lote.
- `Baros.api` no lugar de `fetch`; erro de carregamento mostra o estado de erro na tabela (não só no console).
- Zero `style="` em `_aba_lotes.html`; cores por variáveis do Design System.

## Decisões pendentes (não decida sozinho)
- Lote reprovado pode ser reaberto? Por ora **não** (REPROVADO é final). Registre no relatório para o dono decidir.
- Padrão do lote ao nascer (`APROVADO` com pureza 99,5) **não muda nesta sprint**: é o item 04.5, que aguarda o dono.

## Testes
- [ ] **Falha antes:** `REPROVADO → APROVADO` responde 400 (hoje responde 200).
- [ ] **Falha antes:** reprovar com justificativa vazia ou de 5 caracteres responde 400 (hoje responde 200).
- [ ] Aprovar cria uma linha em `HistoricoQualidadeLote` com RT e registro do snapshot; reprovar também, e bloqueia os cilindros como antes.
- [ ] Usuário GERENTE/OPERADOR recebe 403 e `transicoes_permitidas` vazia; RT recebe as transições certas para cada status.
- [ ] Lote de outra empresa: 404 na ação e no histórico.
- [ ] Teste estático: o bloco `CentralLotesCQ` não tem `innerHTML` com `${` e não tem `onclick=` em template string.

## Critérios de aceite
- [ ] Verificado no navegador com um usuário RT e com um GERENTE, numa **cópia** do banco com o módulo envase ligado (seção 6 das regras): aprovar pede confirmação, reprovar exige motivo, o histórico mostra quem liberou, o gerente não vê os botões. Temas claro, escuro e alto contraste; 375px.
- [ ] Definição de pronto (seção 9 das regras gerais).

## Fora do escopo
Aba Ativos e drawer (01.01), etiquetas (01.02), laboratório completo (S16), padrão do lote ao nascer (04.5).
