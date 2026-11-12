/**
 * painel_monitor.js - Interface Dinâmica do Monitor de TV (Sprint 01B.01)
 *
 * Diretrizes de Segurança e Desempenho:
 * - Proibição de injeção insegura no DOM (uso exclusivo de textContent e DOM API)
 * - Atualização automática a cada 30 segundos via fetch assíncrono
 * - Relógio com precisão de segundos
 * - Detecção de perda de conexão após 2 minutos sem sincronização
 * - Suporte à Fullscreen API e Wake Lock (prevenção de suspensão da tela da TV)
 */

(function () {
  "use strict";

  const token = document.body.dataset.token;
  if (!token) {
    console.error("Token de acesso não localizado no contexto da página.");
    return;
  }

  const API_URL = "/painel/" + encodeURIComponent(token) + "/dados/";
  const INTERVALO_FETCH_MS = 30000; // 30 segundos
  const TIMEOUT_DESCONEXAO_MS = 120000; // 2 minutos

  let ultimoSucessoTimestamp = null;
  let ultimoSucessoHorarioFormatado = "--:--";
  let wakeLockSentinel = null;

  // Elementos do DOM
  const elemRelogio = document.getElementById("monitor-relogio");
  const elemSync = document.getElementById("monitor-sync");
  const elemBanner = document.getElementById("banner-desconexao");
  const elemTextoDesconexao = document.getElementById("texto-desconexao");
  const btnFullscreen = document.getElementById("btn-fullscreen");

  const elemTitulo = document.getElementById("monitor-titulo");
  const elemEmpresa = document.getElementById("monitor-empresa");

  // Colunas da Esteira
  const colASeparar = document.getElementById("cards-a-separar");
  const colEmSeparacao = document.getElementById("cards-em-separacao");
  const colFaturada = document.getElementById("cards-faturada");
  const colEmRota = document.getElementById("cards-em-rota");

  const badgeASeparar = document.getElementById("badge-total-a-separar");
  const badgeEmSeparacao = document.getElementById("badge-total-em-separacao");
  const badgeFaturada = document.getElementById("badge-total-faturada");
  const badgeEmRota = document.getElementById("badge-total-em-rota");
  const badgeConcluidosHoje = document.getElementById("contagem-concluidos-hoje");

  // Indicadores
  const metricaCheios = document.getElementById("metrica-cheios");
  const metricaPedidos = document.getElementById("metrica-pedidos");
  const metricaSaldo = document.getElementById("metrica-saldo");
  const containerPatioGases = document.getElementById("patio-gases-lista");
  const metricaVazios = document.getElementById("metrica-vazios");

  const cardFabrica = document.getElementById("card-fabrica");
  const metricaQuarentena = document.getElementById("metrica-quarentena");
  const metricaInspecoes = document.getElementById("metrica-inspecoes");
  const containerTanques = document.getElementById("tanques-lista");

  // Alertas Rodapé
  const faixaAlertas = document.getElementById("faixa-alertas");
  const textoAlertaReteste = document.getElementById("texto-alerta-reteste");
  const containerAlertaSanitario = document.getElementById("alerta-sanitario-container");
  const textoAlertaSanitario = document.getElementById("texto-alerta-sanitario");
  const containerAlertaRecall = document.getElementById("alerta-recall-container");
  const textoAlertaRecall = document.getElementById("texto-alerta-recall");

  // ---------------------------------------------------------------------------
  // 1. Relógio e Contador de Sincronização
  // ---------------------------------------------------------------------------
  function atualizarRelogio() {
    const agora = new Date();
    const horas = String(agora.getHours()).padStart(2, "0");
    const minutos = String(agora.getMinutes()).padStart(2, "0");
    const segundos = String(agora.getSeconds()).padStart(2, "0");
    if (elemRelogio) {
      elemRelogio.textContent = horas + ":" + minutos + ":" + segundos;
    }

    // Monitora tempo desde última sincronização com sucesso
    if (ultimoSucessoTimestamp) {
      const msDecorrido = agora.getTime() - ultimoSucessoTimestamp;
      const segDecorrido = Math.floor(msDecorrido / 1000);

      if (elemSync) {
        elemSync.textContent = "Atualizado há " + segDecorrido + "s";
      }

      if (msDecorrido > TIMEOUT_DESCONEXAO_MS) {
        if (elemBanner) {
          elemBanner.classList.remove("monitor-oculto");
        }
        if (elemTextoDesconexao) {
          elemTextoDesconexao.textContent =
            "SEM CONEXÃO — dados de " + ultimoSucessoHorarioFormatado;
        }
      } else {
        if (elemBanner) {
          elemBanner.classList.add("monitor-oculto");
        }
      }
    }
  }

  setInterval(atualizarRelogio, 1000);
  atualizarRelogio();

  // ---------------------------------------------------------------------------
  // 2. Renderização de Cartões com textContent
  // ---------------------------------------------------------------------------
  function renderizarCartaoPedido(item) {
    const card = document.createElement("div");
    card.classList.add("card-pedido");

    if (item.bloqueado) {
      card.classList.add("card-pedido-bloqueado");
    } else if (item.nivel_alerta === "critico") {
      card.classList.add("card-pedido-critico");
    } else if (item.nivel_alerta === "alerta") {
      card.classList.add("card-pedido-alerta");
    }

    // Cabeçalho do Card (Número e Tempo)
    const cabecalho = document.createElement("div");
    cabecalho.classList.add("card-cabecalho");

    const numero = document.createElement("span");
    numero.classList.add("card-numero");
    numero.textContent = item.numero || "";
    cabecalho.appendChild(numero);

    if (item.bloqueado) {
      const selo = document.createElement("span");
      selo.classList.add("card-bloqueado-badge");
      selo.textContent = "BLOQUEADO";
      cabecalho.appendChild(selo);
    } else {
      const tempo = document.createElement("span");
      tempo.classList.add("card-tempo");
      if (item.nivel_alerta === "critico") {
        tempo.classList.add("card-tempo-critico");
      } else if (item.nivel_alerta === "alerta") {
        tempo.classList.add("card-tempo-alerta");
      } else {
        tempo.classList.add("card-tempo-normal");
      }
      tempo.textContent = item.minutos_na_etapa + " min";
      cabecalho.appendChild(tempo);
    }
    card.appendChild(cabecalho);

    // Cliente ou Localização
    const cliente = document.createElement("div");
    cliente.classList.add("card-cliente");
    cliente.textContent = item.cliente || "";
    card.appendChild(cliente);

    // Resumo de Itens
    if (Array.isArray(item.itens) && item.itens.length > 0) {
      const itensWrap = document.createElement("div");
      itensWrap.classList.add("card-itens-resumo");
      item.itens.slice(0, 3).forEach(function (it) {
        const span = document.createElement("span");
        span.textContent = it.quantidade + "x " + it.gas;
        itensWrap.appendChild(span);
      });
      if (item.itens.length > 3) {
        const extra = document.createElement("span");
        extra.textContent = "+" + (item.itens.length - 3) + " itens";
        itensWrap.appendChild(extra);
      }
      card.appendChild(itensWrap);
    }

    return card;
  }

  function preencherColuna(container, badge, itens) {
    if (!container) return;

    // Limpa nós existentes
    while (container.firstChild) {
      container.removeChild(container.firstChild);
    }

    const lista = Array.isArray(itens) ? itens : [];
    if (badge) {
      badge.textContent = String(lista.length);
    }

    const limiteExibicao = 5;
    const visiveis = lista.slice(0, limiteExibicao);
    visiveis.forEach(function (item) {
      const cardEl = renderizarCartaoPedido(item);
      container.appendChild(cardEl);
    });

    if (lista.length > limiteExibicao) {
      const excedente = lista.length - limiteExibicao;
      const aviso = document.createElement("div");
      aviso.classList.add("card-overflow-info");
      aviso.textContent = "+" + excedente + " pedidos na fila";
      container.appendChild(aviso);
    }
  }

  // ---------------------------------------------------------------------------
  // 3. Atualização Periódica de Dados via Fetch
  // ---------------------------------------------------------------------------
  function carregarDados() {
    fetch(API_URL, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    })
      .then(function (res) {
        if (!res.ok) {
          throw new Error("HTTP " + res.status);
        }
        return res.json();
      })
      .then(function (dados) {
        const agora = new Date();
        ultimoSucessoTimestamp = agora.getTime();
        ultimoSucessoHorarioFormatado =
          String(agora.getHours()).padStart(2, "0") +
          ":" +
          String(agora.getMinutes()).padStart(2, "0");

        if (elemBanner) {
          elemBanner.classList.add("monitor-oculto");
        }

        // Cabeçalho
        if (elemTitulo && dados.nome) {
          elemTitulo.textContent = dados.nome;
        }
        if (elemEmpresa && dados.empresa) {
          elemEmpresa.textContent = "• " + dados.empresa;
        }

        // 1. Esteira
        if (dados.esteira) {
          preencherColuna(colASeparar, badgeASeparar, dados.esteira.a_separar);
          preencherColuna(colEmSeparacao, badgeEmSeparacao, dados.esteira.em_separacao);
          preencherColuna(colFaturada, badgeFaturada, dados.esteira.faturada);
          preencherColuna(colEmRota, badgeEmRota, dados.esteira.em_rota);
          if (badgeConcluidosHoje) {
            badgeConcluidosHoje.textContent = String(dados.esteira.concluidos_hoje || 0);
          }
        }

        // 2. Pátio e Demanda
        if (dados.patio_demanda) {
          if (metricaCheios) {
            metricaCheios.textContent = String(dados.patio_demanda.cheios_disponiveis || 0);
          }
          if (metricaPedidos) {
            metricaPedidos.textContent = String(dados.patio_demanda.quantidade_pedida || 0);
          }
          if (metricaSaldo) {
            const saldoVal = dados.patio_demanda.saldo || 0;
            metricaSaldo.textContent = (saldoVal > 0 ? "+" : "") + saldoVal;
            metricaSaldo.className = "metrica-numero";
            if (saldoVal < 0) {
              metricaSaldo.classList.add("metrica-numero-critico");
            } else if (saldoVal === 0) {
              metricaSaldo.classList.add("metrica-numero-alerta");
            } else {
              metricaSaldo.classList.add("metrica-numero-ok");
            }
          }

          if (containerPatioGases) {
            while (containerPatioGases.firstChild) {
              containerPatioGases.removeChild(containerPatioGases.firstChild);
            }
            if (Array.isArray(dados.patio_demanda.gases)) {
              dados.patio_demanda.gases.forEach(function (g) {
                const pill = document.createElement("span");
                pill.classList.add("patio-gas-pill");
                if (g.em_falta) {
                  pill.classList.add("patio-gas-pill-falta");
                }
                const sinal = g.saldo > 0 ? "+" : "";
                pill.textContent =
                  g.gas +
                  ": " +
                  g.cheios_disponiveis +
                  "/" +
                  g.quantidade_pedida +
                  " (" +
                  sinal +
                  g.saldo +
                  ")";
                containerPatioGases.appendChild(pill);
              });
            }
          }
        }

        // 3. Retornos
        if (dados.retornos) {
          if (metricaVazios) {
            metricaVazios.textContent = String(dados.retornos.vazios_triagem || 0);
          }
        }

        // 4. Alertas do Pátio
        let temAlertaGlobal = false;
        if (dados.alertas) {
          const reteste = dados.alertas.reteste_vencido_patio || 0;
          if (reteste > 0) {
            temAlertaGlobal = true;
            if (textoAlertaReteste) {
              textoAlertaReteste.textContent =
                reteste + " cilindro(s) no pátio com reteste vencido!";
            }
          } else {
            if (textoAlertaReteste) {
              textoAlertaReteste.textContent = "Nenhum reteste vencido no pátio.";
            }
          }

          const bloqueios = dados.alertas.bloqueios_sanitarios || 0;
          if (bloqueios > 0) {
            temAlertaGlobal = true;
            if (containerAlertaSanitario) {
              containerAlertaSanitario.classList.remove("monitor-oculto");
            }
            if (textoAlertaSanitario) {
              textoAlertaSanitario.textContent =
                bloqueios + " bloqueio(s) sanitário(s) ativo(s)!";
            }
          } else {
            if (containerAlertaSanitario) {
              containerAlertaSanitario.classList.add("monitor-oculto");
            }
          }

          const recalls = dados.alertas.recalls_abertos || 0;
          if (recalls > 0) {
            temAlertaGlobal = true;
            if (containerAlertaRecall) {
              containerAlertaRecall.classList.remove("monitor-oculto");
            }
            if (textoAlertaRecall) {
              textoAlertaRecall.textContent =
                recalls + " campanha(s) de recall em andamento!";
            }
          } else {
            if (containerAlertaRecall) {
              containerAlertaRecall.classList.add("monitor-oculto");
            }
          }
        }

        if (faixaAlertas) {
          if (temAlertaGlobal) {
            faixaAlertas.classList.remove("monitor-oculto");
          } else {
            faixaAlertas.classList.add("monitor-oculto");
          }
        }

        // 5. Fábrica / Envase
        if (dados.fabrica) {
          if (cardFabrica) {
            cardFabrica.classList.remove("monitor-oculto");
          }
          if (metricaQuarentena) {
            metricaQuarentena.textContent = String(dados.fabrica.lotes_quarentena || 0);
          }
          if (metricaInspecoes) {
            metricaInspecoes.textContent = String(dados.fabrica.inspecoes_pendentes || 0);
          }

          if (containerTanques) {
            while (containerTanques.firstChild) {
              containerTanques.removeChild(containerTanques.firstChild);
            }
            if (Array.isArray(dados.fabrica.tanques)) {
              dados.fabrica.tanques.forEach(function (t) {
                const itemT = document.createElement("div");
                itemT.classList.add("metrica-sub");
                itemT.textContent = t.gas + ": " + t.percentual_nivel + "%";
                containerTanques.appendChild(itemT);
              });
            }
          }
        } else {
          if (cardFabrica) {
            cardFabrica.classList.add("monitor-oculto");
          }
        }
      })
      .catch(function (err) {
        console.warn("Falha na sincronização do monitor:", err);
      });
  }

  // Carga inicial e agendamento
  carregarDados();
  setInterval(carregarDados, INTERVALO_FETCH_MS);

  // ---------------------------------------------------------------------------
  // 4. Fullscreen e Wake Lock
  // ---------------------------------------------------------------------------
  function alternarTelaCheia() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(function (err) {
        console.warn("Não foi possível ativar tela cheia:", err);
      });
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    }
  }

  if (btnFullscreen) {
    btnFullscreen.addEventListener("click", alternarTelaCheia);
  }

  // Previne suspensão da tela via Screen Wake Lock API
  async function ativarWakeLock() {
    if ("wakeLock" in navigator) {
      try {
        wakeLockSentinel = await navigator.wakeLock.request("screen");
        wakeLockSentinel.addEventListener("release", function () {
          wakeLockSentinel = null;
        });
      } catch (err) {
        console.warn("Wake lock não disponível:", err);
      }
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && !wakeLockSentinel) {
      ativarWakeLock();
    }
  });

  ativarWakeLock();
})();
