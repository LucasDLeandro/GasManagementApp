# Modelo de sprint (use para escrever as próximas)

Cada sprint resolve **um problema verificável**, cabe em 1 a 3 dias de agente e tem no máximo ~80 linhas. Se passar disso, divida em sub-sprints (`XX.00`, `XX.01`...). Reescreva a próxima sprint **logo antes** de ela começar, olhando o código daquele momento: o código muda a cada sprint.

```markdown
# Sprint XX.YY — Título curto

Leia antes: `CLAUDE.md`, `docs/PROGRESSO.md` e `docs/sprints/00_REGRAS_GERAIS.md` (inteiro). Depende da Sprint XX.YY.
Leia também: (só as seções que esta sprint usa).
**Branch:** `sprint-XX.YY/nome-curto` a partir de `<branch anterior>`.

## Objetivo
Uma ou duas frases: o que fica funcionando ao final, do ponto de vista de quem usa.

## O que está errado (verificado em DD/MM/AAAA)
1. Fato concreto com arquivo e linha, e como reproduzir (o que acontece hoje).
2. ...

## O que já existe (não refazer)
- Serviços, APIs e telas que a sprint deve reaproveitar.

## Escopo
### Bloco 1
- Instrução precisa. Regras de negócio com origem/destino/papel.

## Decisões pendentes
- O que o agente NÃO deve decidir sozinho: registra no relatório e segue com o resto.

## Testes
- [ ] **Falha antes:** teste que reproduz o problema 1 e falha no código atual (confira isso antes de corrigir).
- [ ] Sucesso, erro de validação, papel sem permissão, isolamento entre empresas.

## Critérios de aceite
- [ ] Verificado no navegador (papel X, tema escuro, 375px): o que clicar e o que deve aparecer.
- [ ] Definição de pronto (seção 9 das regras gerais).

## Fora do escopo
- O que fica para outra sprint.
```
