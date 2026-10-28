# Manual de Treinamento e Operação por Perfil de Usuário

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data:** 2026-10-27  
**Classificação:** Treinamento & Capacitação Operacional  

---

## 1. Perfil: Gestor Geral / Diretoria (Diretor & C-Level)

### 1.1. Principais Responsabilidades
- Monitoramento de indicadores estratégicos em tempo real (Visão Cockpit).
- Acompanhamento do DRE por competência e margem de contribuição.
- Projeção de fluxo de caixa em 3 cenários (Otimista, Realista e Pessimista a 90 dias).
- Governança de cilindros parados e identificação de clientes destruidores de margem (TMA).

### 1.2. Principais Funcionalidades no Sistema
1. **DRE por Competência:** Acessar menu *Controladoria > DRE Gerencial*. Filtrar por mês ou trimestre. O sistema consolida as 12 linhas padronizadas, comparando realizado vs. orçado.
2. **Torre de Controle de Frota:** Acessar *Logística > Torre de Controle*. Monitorar o mapa com as rotas em andamento, status de entregas e paradas em atraso.
3. **Cockpit de Inadimplência e Crédito:** Acessar *Financeiro > Análise de Crédito*. Visualizar exposição consolidada por cliente, índice de PDD e curva de recompra atrasada.

---

## 2. Perfil: Financeiro & Controladoria (Gestor & Operador Financeiro)

### 2.1. Principais Responsabilidades
- Contas a pagar e receber com alçadas de aprovação.
- Conciliação bancária de extrato OFX e retornos de cobrança registrada (PIX e Boleto).
- Fechamento cego de caixa de rotas e apuração de quebra de caixa.
- Apuração mensal de estadia de cilindros em comodato e cálculo de depreciação de imobilizado.

### 2.2. Passo a Passo das Rotinas Diárias
1. **Conciliação Bancária:**
   - Acessar *Financeiro > Conciliação Bancária*.
   - Fazer upload do arquivo `.ofx` fornecido pelo banco.
   - O motor processa as 5 regras de conciliação. Itens com score $\ge 90$ são baixados automaticamente. Itens sugeridos (score 75 a 85) exigem clique em "Confirmar Associação".
2. **Régua de Cobrança e Inadimplência:**
   - Títulos vencidos disparam automaticamente mensagens via WhatsApp/E-mail dentro da janela permitida (08:00 às 20:00).
   - Acordo ou repactuação: acessar *Financeiro > Promessas de Pagamento*, inserir a data acordada. A promessa suspende o bloqueio comercial até a data pactuada.
3. **Cobrança de Estadia de Cilindros:**
   - No 1º dia útil do mês, acessar *Financeiro > Faturamento de Estadia*.
   - Executar o cálculo em lote. O sistema apura cilindros com dias retidos além da franquia e gera faturas/títulos a receber com contrapartida contábil na conta de locação.

---

## 3. Perfil: Comercial & Vendas (Vendedor & Faturista)

### 3.1. Principais Responsabilidades
- Digitação e emissão de pedidos de venda de gases industriais e medicinais.
- Gestão de contratos de comodato e locação de cilindros e tanques.
- Consulta de limites de crédito e acompanhamento de alertas de recompra atrasada.

### 3.2. Passo a Passo das Rotinas Diárias
1. **Emissão de Pedido de Venda:**
   - Acessar *Comercial > Novo Pedido*.
   - Selecionar o cliente; o sistema carrega a tabela de preços do contrato.
   - Adicionar os SKUs de recarga (especificando tipo de gás e volume).
   - Ao avançar, o sistema valida automaticamente o limite de crédito e atrasos:
     - Se o cliente for hospitalar e houver atraso, o sistema emite `ALERTA_ASSISTENCIAL`, permitindo o envio sem bloquear fornecimento essencial de saúde.
     - Se for cliente comum inadimplente, o pedido entra como `BLOQUEADO_FINANCEIRO`.
2. **Acompanhamento de Churn e Recompra:**
   - Acessar *Comercial > Previsão de Demanda*.
   - O painel exibe clientes com probabilidade de esgotamento de gás nos próximos 3 a 7 dias, permitindo contato comercial proativo.

---

## 4. Perfil: Logística & Motorista de Campo (Expedição & Condutor)

### 4.1. Principais Responsabilidades
- Conferência de carga e separação de cilindros cheios e vazios.
- Inspeção de compatibilidade química da carga (produtos perigosos).
- Execução de rota externa de entregas via PWA móvel (inclusive offline).
- Coleta de canhotos digitais e conferência de vasilhames devolvidos.

### 4.2. Passo a Passo das Rotinas Diárias
1. **Início de Viagem (PWA do Motorista):**
   - Abrir o aplicativo no celular ou coletor de dados.
   - Clicar em "Iniciar Rota". O aplicativo faz a carga local dos clientes e endereços no IndexedDB.
   - O aplicativo solicita permissão de GPS e passa a registrar coordenadas periodicamente.
2. **No Ponto de Entrega (Cliente):**
   - Clicar no cliente correspondente na lista de paradas.
   - Efetuar a leitura do código de barras/Datamatrix dos cilindros cheios entregues e dos vazios recolhidos.
   - Se o cliente efetuar pagamento em dinheiro ou PIX direto, lançar o recebimento no "Caixa de Rota".
   - Colher assinatura na tela ou foto do comprovante físico. Clicar em "Concluir Entrega".
   - Se a área estiver sem sinal de internet (offline), os dados ficam armazenados com segurança no aparelho e são transmitidos automaticamente assim que a conexão retornar.
3. **Retorno à Base (Fechamento de Viagem):**
   - Entregar os cilindros recolhidos na rampa para triagem e quarentena de reteste.
   - Realizar o fechamento cego de caixa na tesouraria, entregando valores em espécie e comprovantes de rota.
