/**
 * GasApp - App de Campo PWA (Fase 4)
 * Motorista Offline-First, Validação Assimétrica de Carga e Assinatura Eletrônica Simples
 */

document.addEventListener('DOMContentLoaded', async () => {
  // ---- 1. Estado da Aplicação ----
  let rotaPacote = null;
  let paradaAtiva = null;
  let cheiosParada = [];
  let vaziosParada = [];
  let gpsCoords = { latitude: null, longitude: null };

  // ---- 2. Modo Sol (High Contrast Sun Mode) ----
  const btnToggleSun = document.getElementById('btn-toggle-sun');
  function initTheme() {
    const savedTheme = localStorage.getItem('gasapp_theme');
    if (savedTheme === 'high-contrast-sun') {
      document.documentElement.setAttribute('data-theme', 'high-contrast-sun');
      if (btnToggleSun) btnToggleSun.innerHTML = '🌙 Modo Normal';
    } else {
      document.documentElement.removeAttribute('data-theme');
      if (btnToggleSun) btnToggleSun.innerHTML = '☀️ Modo Sol';
    }
  }
  initTheme();

  if (btnToggleSun) {
    btnToggleSun.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      if (current === 'high-contrast-sun') {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('gasapp_theme', 'default');
        btnToggleSun.innerHTML = '☀️ Modo Sol';
      } else {
        document.documentElement.setAttribute('data-theme', 'high-contrast-sun');
        localStorage.setItem('gasapp_theme', 'high-contrast-sun');
        btnToggleSun.innerHTML = '🌙 Modo Normal';
      }
    });
  }

  // ---- 3. Web Audio API e Vibração Háptica ----
  function playSuccessBeep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
      osc.start();
      osc.stop(ctx.currentTime + 0.15);
    } catch (e) {}
    if (navigator.vibrate) {
      navigator.vibrate(60);
    }
  }

  function playErrorBeep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(220, ctx.currentTime);
      osc.frequency.setValueAtTime(150, ctx.currentTime + 0.1);
      gain.gain.setValueAtTime(0.25, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } catch (e) {}
    if (navigator.vibrate) {
      navigator.vibrate([100, 50, 100]);
    }
  }

  // ---- 4. Banner Permanente de Rede e Fila Local ----
  async function atualizarBannerRede() {
    const dot = document.getElementById('network-status-dot');
    const text = document.getElementById('network-status-text');
    const btnSync = document.getElementById('btn-sync-status');

    let pendentes = [];
    let rejeitados = [];
    if (window.GasAppOffline) {
      try {
        pendentes = await window.GasAppOffline.listarPendentes();
        rejeitados = await window.GasAppOffline.listarRejeitados();
      } catch (e) {}
    }

    if (rejeitados.length > 0) {
      if (dot) dot.className = 'status-dot rejected';
      if (text) text.textContent = `${rejeitados.length} Rejeitados (Intervenção)`;
      if (btnSync) {
        btnSync.style.display = 'inline-flex';
        btnSync.className = 'btn-touch btn-touch-danger';
        btnSync.textContent = `Pendências (${rejeitados.length})`;
      }
    } else if (!navigator.onLine) {
      if (dot) dot.className = 'status-dot offline';
      if (text) text.textContent = pendentes.length > 0 ? `Modo Offline: ${pendentes.length} na fila` : 'Modo Offline Ativo';
      if (btnSync) btnSync.style.display = 'none';
    } else if (window.GasAppOffline && window.GasAppOffline.isSyncing) {
      if (dot) dot.className = 'status-dot';
      if (text) text.textContent = 'Sincronizando com o Servidor...';
      if (btnSync) btnSync.style.display = 'none';
    } else {
      if (dot) dot.className = 'status-dot';
      if (text) text.textContent = pendentes.length > 0 ? `Online (${pendentes.length} pendentes)` : 'Online';
      if (btnSync) btnSync.style.display = 'none';
    }
  }

  window.addEventListener('online', () => {
    atualizarBannerRede();
    if (window.GasAppOffline) window.GasAppOffline.sincronizarLote().then(atualizarBannerRede);
  });
  window.addEventListener('offline', atualizarBannerRede);
  setInterval(atualizarBannerRede, 4000);

  // ---- 5. Pre-flight Sync (Pacote da Rota no IndexedDB) ----
  const btnBaixarRota = document.getElementById('btn-baixar-rota');
  if (btnBaixarRota) {
    btnBaixarRota.addEventListener('click', async () => {
      await baixarPacoteRotaServidor();
    });
  }

  async function baixarPacoteRotaServidor() {
    if (!navigator.onLine) {
      Swal.fire('Sem Conexão', 'Conecte-se à internet para realizar o Pre-flight Sync da rota.', 'warning');
      return;
    }

    try {
      btnBaixarRota.disabled = true;
      btnBaixarRota.textContent = 'Baixando Pacote...';

      let token = localStorage.getItem('access_token');
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = 'Bearer ' + token;

      let res = await fetch('/logistica/api/entregas/minha-rota-ativa/', { 
        headers, 
        credentials: 'same-origin' 
      });

      // Se o token estiver expirado/inválido (401), remove do localStorage e tenta via Sessão
      if (res.status === 401 && token) {
        localStorage.removeItem('access_token');
        delete headers['Authorization'];
        res = await fetch('/logistica/api/entregas/minha-rota-ativa/', { 
          headers, 
          credentials: 'same-origin' 
        });
      }

      if (!res.ok) {
        if (res.status === 404) {
          const errData = await res.json().catch(() => null);
          const msg = (errData && (errData.mensagem || errData.error)) || 'Nenhuma rota ativa atribuída encontrada no momento.';
          throw new Error(msg);
        }
        if (res.status === 401 || res.status === 403) {
          throw new Error('Sessão expirada. Faça login novamente para sincronizar a rota.');
        }
        throw new Error(`Falha ao obter pacote da rota do servidor (HTTP ${res.status}).`);
      }

      const pacote = await res.json();
      await window.GasAppOffline.salvarPacoteRota(pacote);
      rotaPacote = pacote;
      renderizarRota();
      playSuccessBeep();
      Swal.fire({
        title: 'Pacote da Rota Baixado!',
        text: `${pacote.paradas.length} paradas e ${pacote.cilindros_caminhao.length} cilindros carregados offline.`,
        icon: 'success',
        timer: 2000,
        showConfirmButton: false
      });
    } catch (err) {
      playErrorBeep();
      Swal.fire('Pre-flight Sync', err.message, 'info');
    } finally {
      btnBaixarRota.disabled = false;
      btnBaixarRota.innerHTML = '📥 Baixar Rota Offline';
    }
  }

  // Carrega Pacote Inicial do IndexedDB se existir
  async function carregarPacoteInicial() {
    if (window.GasAppOffline) {
      try {
        const pacoteSalvo = await window.GasAppOffline.obterPacoteRota();
        if (pacoteSalvo) {
          rotaPacote = pacoteSalvo;
          renderizarRota();
          console.log('[App de Campo] Pacote da rota carregado do IndexedDB.');
        } else if (navigator.onLine) {
          await baixarPacoteRotaServidor();
        }
      } catch (err) {
        console.warn('[App de Campo] Falha ao carregar pacote offline:', err);
      }
    }
  }

  // ---- 6. Renderização da Rota e Paradas ----
  function renderizarRota() {
    if (!rotaPacote) return;

    // Cabeçalho da Carga
    document.getElementById('rota-titulo').textContent = `Entrega #${rotaPacote.entrega_id} - ${rotaPacote.rota_nome || 'Rota'}`;
    document.getElementById('rota-motorista').textContent = rotaPacote.motorista || 'Motorista';
    document.getElementById('rota-veiculo').textContent = `${rotaPacote.veiculo.placa} (${rotaPacote.veiculo.modelo || 'Veículo'})`;

    // Barra de Lotação D11
    const perc = rotaPacote.percentual_lotacao || 0;
    const percVisual = Math.min(perc, 100);
    const barra = document.getElementById('rota-barra-fill');
    const textoLotacao = document.getElementById('rota-lotacao-texto');

    let barColor = '#10b981';
    let statusText = 'Normal (<80%)';
    if (perc >= 100) {
      barColor = '#ef4444';
      statusText = 'SOBRECARGA (>100%)';
    } else if (perc >= 80) {
      barColor = '#f59e0b';
      statusText = 'Alerta Carga (80-99%)';
    }

    if (barra) {
      barra.style.width = percVisual + '%';
      barra.style.backgroundColor = barColor;
    }
    if (textoLotacao) {
      textoLotacao.innerHTML = `<strong>${perc}%</strong> (${statusText})`;
      textoLotacao.style.color = barColor;
    }

    // Selo Peso Estimado
    const seloDiv = document.getElementById('rota-selo-estimado');
    if (seloDiv) {
      seloDiv.innerHTML = rotaPacote.possui_peso_estimado
        ? '<span style="background:#fef3c7; color:#92400e; border:1px solid #f59e0b; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:700;">⚠️ Contém peso estimado</span>'
        : '<span style="background:#dcfce7; color:#166534; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:700;">⚖️ Peso Aferido</span>';
    }

    // Lista de Paradas
    const stopsList = document.getElementById('stops-list');
    stopsList.innerHTML = '';

    if (!rotaPacote.paradas || rotaPacote.paradas.length === 0) {
      stopsList.innerHTML = '<div style="text-align:center; padding:20px; color:var(--app-text-muted);">Nenhuma parada cadastrada nesta rota.</div>';
      return;
    }

    rotaPacote.paradas.forEach((p, idx) => {
      const saldo = (rotaPacote.saldos_comodato && rotaPacote.saldos_comodato[p.cliente_id]) || 0;
      const isCompleted = p.status === 'Concluída';
      const itensHtml = (p.itens || []).map(it => `<li>${it.quantidade}x ${it.produto}</li>`).join('');

      const card = document.createElement('div');
      card.className = `stop-card ${isCompleted ? 'completed' : ''}`;
      card.innerHTML = `
        <div class="stop-card-header">
          <div style="display:flex; align-items:center; gap:10px;">
            <div class="stop-order-badge" style="${isCompleted ? 'background:var(--app-success);' : ''}">${isCompleted ? '✓' : p.ordem}</div>
            <div>
              <strong style="font-size:16px;">${p.cliente_nome}</strong>
              <div style="font-size:12px; color:var(--app-text-muted);">CNPJ/CPF: ${p.cliente_cnpj || 'Não informado'}</div>
            </div>
          </div>
          <span class="stop-comodato-badge">Comodato: ${saldo} cascos</span>
        </div>

        <div style="font-size:13px; margin:8px 0; color:var(--app-text-muted);">
          📍 ${p.cliente_endereco || 'Endereço não cadastrado'}
        </div>

        <div style="font-size:13px; margin-bottom:12px;">
          <strong>Itens Previstos:</strong>
          <ul style="margin:4px 0 0 16px; padding:0;">${itensHtml}</ul>
        </div>

        <div style="display:flex; gap:8px;">
          ${p.cliente_endereco ? `<a href="https://maps.google.com/?q=${encodeURIComponent(p.cliente_endereco)}" target="_blank" class="btn-touch btn-touch-outline" style="flex:1; min-height:48px; font-size:14px; text-decoration:none;">🗺️ Navegar</a>` : ''}
          <button class="btn-touch ${isCompleted ? 'btn-touch-outline' : 'btn-touch-primary'}" style="flex:2; min-height:48px; font-size:15px;" onclick="window.abrirParada(${p.ordem})">
            ${isCompleted ? 'Revisar Parada' : '🚚 Atender Parada'}
          </button>
        </div>
      `;
      stopsList.appendChild(card);
    });
  }

  // ---- 7. Operação da Parada (Validação Assimétrica) ----
  let abaAtiva = 'entregar'; // 'entregar' ou 'recolher'

  window.abrirParada = function(ordem) {
    if (!rotaPacote || !rotaPacote.paradas) return;
    const parada = rotaPacote.paradas.find(p => p.ordem === ordem);
    if (!parada) return;

    paradaAtiva = parada;
    cheiosParada = [];
    vaziosParada = [];

    document.getElementById('view-rota').style.display = 'none';
    document.getElementById('view-parada').style.display = 'block';

    document.getElementById('parada-cliente-nome').textContent = parada.cliente_nome;
    const saldo = (rotaPacote.saldos_comodato && rotaPacote.saldos_comodato[parada.cliente_id]) || 0;
    document.getElementById('parada-cliente-saldo').textContent = `${saldo} cascos em comodato`;

    selecionarAbaOperacao('entregar');
    renderizarListasParada();
  };

  window.voltarParaRota = function() {
    document.getElementById('view-parada').style.display = 'none';
    document.getElementById('view-rota').style.display = 'block';
    paradaAtiva = null;
    renderizarRota();
  };

  const btnTabDeliver = document.getElementById('btn-tab-deliver');
  const btnTabCollect = document.getElementById('btn-tab-collect');

  if (btnTabDeliver) btnTabDeliver.addEventListener('click', () => selecionarAbaOperacao('entregar'));
  if (btnTabCollect) btnTabCollect.addEventListener('click', () => selecionarAbaOperacao('recolher'));

  function selecionarAbaOperacao(aba) {
    abaAtiva = aba;
    if (aba === 'entregar') {
      btnTabDeliver.classList.add('active', 'tab-deliver');
      btnTabCollect.classList.remove('active', 'tab-collect');
      document.getElementById('input-bip-codigo').placeholder = 'Bipar Cheio (Caminhão → Cliente)';
    } else {
      btnTabCollect.classList.add('active', 'tab-collect');
      btnTabDeliver.classList.remove('active', 'tab-deliver');
      document.getElementById('input-bip-codigo').placeholder = 'Bipar Vazio (Cliente → Caminhão)';
    }
  }

  // Formulário de Bipagem (Keyboard Wedge / Scanner / Digitação Assistida)
  const formBip = document.getElementById('form-bip');
  if (formBip) {
    formBip.addEventListener('submit', (e) => {
      e.preventDefault();
      const input = document.getElementById('input-bip-codigo');
      const codigo = (input.value || '').trim();
      if (!codigo) return;
      processarBip(codigo);
      input.value = '';
      input.focus();
    });
  }

  function processarBip(codigo) {
    if (!rotaPacote || !paradaAtiva) return;

    if (abaAtiva === 'entregar') {
      // VALIDAÇÃO ESTRITA: Caminhão → Cliente
      const cilindro = (rotaPacote.cilindros_caminhao || []).find(
        c => (c.codigo_qr && c.codigo_qr.toUpperCase() === codigo.toUpperCase()) ||
             (c.serie_ogiva && c.serie_ogiva.toUpperCase() === codigo.toUpperCase())
      );

      if (!cilindro) {
        playErrorBeep();
        exibirAlertaBloqueio('Cilindro Não Encontrado', `O código "${codigo}" não consta no pacote carregado deste caminhão.`);
        return;
      }

      // 1. Trava de Teste Hidrostático Vencido
      if (cilindro.reteste_vencido === true) {
        playErrorBeep();
        exibirAlertaBloqueio(
          '🚫 BLOQUEIO CRÍTICO INMETRO',
          `Cilindro ${cilindro.serie_ogiva} (${cilindro.gas}) com RETESTE HIDROSTÁTICO VENCIDO em ${cilindro.data_proximo_reteste || 'data expirada'}. Expedição terminantemente proibida!`
        );
        return;
      }

      // 2. Trava de Bloqueio Sanitário ANVISA
      if (cilindro.bloqueio_sanitario === true) {
        playErrorBeep();
        exibirAlertaBloqueio(
          '☣️ BLOQUEIO SANITÁRIO ANVISA',
          `Cilindro ${cilindro.serie_ogiva} isolado por quarentena sanitária: ${cilindro.motivo_bloqueio_sanitario || 'Motivo técnico registrado'}. Não entregue!`
        );
        return;
      }

      // 3. Trava de Lote Inválido ou Expirado
      if (cilindro.lote_valido === false) {
        playErrorBeep();
        exibirAlertaBloqueio(
          '⚠️ LOTE INVÁLIDO OU EXPIRADO',
          `Lote ${cilindro.lote} expirado ou não liberado pelo Responsável Técnico. Entrega bloqueada!`
        );
        return;
      }

      // Evita duplicatas na mesma parada
      if (cheiosParada.some(x => x.id === cilindro.id)) {
        playErrorBeep();
        Swal.fire('Item Já Bipado', 'Este cilindro já foi bipado para entrega nesta parada.', 'info');
        return;
      }

      cheiosParada.push(cilindro);
      playSuccessBeep();
      renderizarListasParada();

    } else {
      // VALIDAÇÃO PERMISSIVA: Cliente → Caminhão (Caso de Ouro #6)
      // Aceita qualquer casco vazio, mesmo vencido ou divergente
      let cilindroConhecido = (rotaPacote.cilindros_caminhao || []).find(
        c => (c.codigo_qr && c.codigo_qr.toUpperCase() === codigo.toUpperCase()) ||
             (c.serie_ogiva && c.serie_ogiva.toUpperCase() === codigo.toUpperCase())
      );

      const isDivergente = !cilindroConhecido;
      const retesteVencido = cilindroConhecido ? cilindroConhecido.reteste_vencido : false;

      const itemVazio = {
        id: cilindroConhecido ? cilindroConhecido.id : null,
        codigo_qr: codigo,
        serie_ogiva: cilindroConhecido ? cilindroConhecido.serie_ogiva : codigo,
        gas: cilindroConhecido ? cilindroConhecido.gas : 'GÁS RECOLHA',
        divergente: isDivergente || retesteVencido,
        reteste_vencido: retesteVencido
      };

      if (vaziosParada.some(x => x.codigo_qr.toUpperCase() === codigo.toUpperCase())) {
        playErrorBeep();
        Swal.fire('Item Já Bipado', 'Este vasilhame já consta na lista de recolha desta parada.', 'info');
        return;
      }

      vaziosParada.push(itemVazio);
      playSuccessBeep();
      renderizarListasParada();
    }
  }

  function exibirAlertaBloqueio(titulo, texto) {
    Swal.fire({
      icon: 'error',
      title: titulo,
      text: texto,
      confirmButtonText: 'Entendido / Não Entregar',
      confirmButtonColor: '#ef4444'
    });
  }

  function renderizarListasParada() {
    const listDeliver = document.getElementById('list-deliver-items');
    const listCollect = document.getElementById('list-collect-items');

    document.getElementById('count-deliver').textContent = cheiosParada.length;
    document.getElementById('count-collect').textContent = vaziosParada.length;

    // Cheios
    listDeliver.innerHTML = '';
    if (cheiosParada.length === 0) {
      listDeliver.innerHTML = '<div style="color:var(--app-text-muted); font-size:13px;">Nenhum cheio bipado para entrega ainda.</div>';
    } else {
      cheiosParada.forEach((c, idx) => {
        listDeliver.innerHTML += `
          <div class="cylinder-item">
            <div>
              <strong style="color:var(--app-success);">✓ ${c.serie_ogiva || c.codigo_qr}</strong>
              <div style="font-size:12px; color:var(--app-text-muted);">${c.gas} | Tara: ${c.tara_kg} kg | Lote: ${c.lote}</div>
            </div>
            <button class="btn-touch btn-touch-outline" style="min-height:40px; padding:6px 12px; font-size:13px; color:var(--app-danger); border-color:var(--app-danger);" onclick="window.removerCheio(${idx})">Remover</button>
          </div>
        `;
      });
    }

    // Vazios
    listCollect.innerHTML = '';
    if (vaziosParada.length === 0) {
      listCollect.innerHTML = '<div style="color:var(--app-text-muted); font-size:13px;">Nenhum vazio recolhido nesta parada ainda.</div>';
    } else {
      vaziosParada.forEach((c, idx) => {
        const badgeDivergente = c.divergente 
          ? '<span style="background:#fef3c7; color:#92400e; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:700; margin-left:6px;">⚠️ Divergente / Triagem</span>' 
          : '';
        listCollect.innerHTML += `
          <div class="cylinder-item ${c.divergente ? 'divergent' : ''}">
            <div>
              <strong style="color:var(--app-warning);">⬇️ ${c.serie_ogiva}</strong> ${badgeDivergente}
              <div style="font-size:12px; color:var(--app-text-muted);">${c.gas} (Recolhido Vazio)</div>
            </div>
            <button class="btn-touch btn-touch-outline" style="min-height:40px; padding:6px 12px; font-size:13px; color:var(--app-danger); border-color:var(--app-danger);" onclick="window.removerVazio(${idx})">Remover</button>
          </div>
        `;
      });
    }

    const btnFinalizar = document.getElementById('btn-finalizar-parada');
    if (btnFinalizar) {
      btnFinalizar.disabled = (cheiosParada.length === 0 && vaziosParada.length === 0);
    }
  }

  window.removerCheio = function(idx) {
    cheiosParada.splice(idx, 1);
    renderizarListasParada();
  };

  window.removerVazio = function(idx) {
    vaziosParada.splice(idx, 1);
    renderizarListasParada();
  };

  // ---- 8. Assinatura Touch e Comprovante por Parada (D8) ----
  const modalAssinatura = document.getElementById('modal-assinatura');
  const canvas = document.getElementById('signature-canvas');
  let ctx = null;
  let desenhando = false;
  let assinou = false;

  if (canvas) {
    ctx = canvas.getContext('2d');
    ajustarTamanhoCanvas();

    // Eventos Touch / Mouse com touch-action: none
    canvas.addEventListener('touchstart', (e) => {
      e.preventDefault();
      desenhando = true;
      assinou = true;
      const rect = canvas.getBoundingClientRect();
      const touch = e.touches[0];
      ctx.beginPath();
      ctx.moveTo(touch.clientX - rect.left, touch.clientY - rect.top);
    }, { passive: false });

    canvas.addEventListener('touchmove', (e) => {
      e.preventDefault();
      if (!desenhando) return;
      const rect = canvas.getBoundingClientRect();
      const touch = e.touches[0];
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.strokeStyle = '#000000';
      ctx.lineTo(touch.clientX - rect.left, touch.clientY - rect.top);
      ctx.stroke();
    }, { passive: false });

    canvas.addEventListener('touchend', (e) => {
      e.preventDefault();
      desenhando = false;
    });

    // Mouse fallback
    canvas.addEventListener('mousedown', (e) => {
      desenhando = true;
      assinou = true;
      const rect = canvas.getBoundingClientRect();
      ctx.beginPath();
      ctx.moveTo(e.clientX - rect.left, e.clientY - rect.top);
    });

    canvas.addEventListener('mousemove', (e) => {
      if (!desenhando) return;
      const rect = canvas.getBoundingClientRect();
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.strokeStyle = '#000000';
      ctx.lineTo(e.clientX - rect.left, e.clientY - rect.top);
      ctx.stroke();
    });

    canvas.addEventListener('mouseup', () => { desenhando = false; });
  }

  function ajustarTamanhoCanvas() {
    if (!canvas) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width || 400;
    canvas.height = 220;
    limparCanvas();
  }

  function limparCanvas() {
    if (!ctx) return;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    assinou = false;
  }

  const btnLimparAssinatura = document.getElementById('btn-limpar-assinatura');
  if (btnLimparAssinatura) {
    btnLimparAssinatura.addEventListener('click', limparCanvas);
  }

  // Abrir Modal de Comprovante
  const btnFinalizarParada = document.getElementById('btn-finalizar-parada');
  if (btnFinalizarParada) {
    btnFinalizarParada.addEventListener('click', () => {
      if (!paradaAtiva) return;

      document.getElementById('resumo-entregues').textContent = `${cheiosParada.length} cilindros cheios`;
      document.getElementById('resumo-recolhidos').textContent = `${vaziosParada.length} cilindros vazios`;

      modalAssinatura.classList.add('active');
      ajustarTamanhoCanvas();

      // Tentativa opcional de coleta de GPS com aviso LGPD
      capturarGPS();
    });
  }

  function capturarGPS() {
    const statusGPS = document.getElementById('gps-status-text');
    if (navigator.geolocation) {
      if (statusGPS) statusGPS.textContent = 'Coletando coordenadas GPS da entrega...';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          gpsCoords.latitude = pos.coords.latitude;
          gpsCoords.longitude = pos.coords.longitude;
          if (statusGPS) statusGPS.textContent = `GPS Fixado: ${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)}`;
        },
        (err) => {
          if (statusGPS) statusGPS.textContent = 'GPS não disponível no momento (opcional).';
        },
        { enableHighAccuracy: true, timeout: 5000 }
      );
    }
  }

  const btnFecharAssinatura = document.getElementById('btn-fechar-assinatura');
  if (btnFecharAssinatura) {
    btnFecharAssinatura.addEventListener('click', () => {
      modalAssinatura.classList.remove('active');
    });
  }

  // Confirmação do Comprovante da Parada (1 Comprovante ↔ N Movimentações)
  const formConfirmarComprovante = document.getElementById('form-confirmar-comprovante');
  if (formConfirmarComprovante) {
    formConfirmarComprovante.addEventListener('submit', async (e) => {
      e.preventDefault();

      const nomeRecebedor = (document.getElementById('input-recebedor-nome').value || '').trim();
      const docRecebedor = (document.getElementById('input-recebedor-doc').value || '').trim();

      if (!nomeRecebedor || !docRecebedor) {
        Swal.fire('Atenção', 'Informe o nome e o documento do recebedor.', 'warning');
        return;
      }

      if (!assinou) {
        Swal.fire('Assinatura Obrigatória', 'O recebedor deve assinar na tela para validação do comprovante.', 'warning');
        return;
      }

      const assinaturaBase64 = canvas.toDataURL('image/png');
      const comprovanteLoteUUID = crypto.randomUUID ? crypto.randomUUID() : 'lote_' + Date.now();
      const agora = new Date().toISOString();

      try {
        // Enfileira todos os cilindros cheios entregues
        for (const c of cheiosParada) {
          await window.GasAppOffline.enfileirarMovimentacao({
            client_uuid: crypto.randomUUID ? crypto.randomUUID() : undefined,
            tipo: 'ENTREGA_CLIENTE',
            codigo_qr: c.codigo_qr,
            cilindro_id: c.id,
            cliente_id: paradaAtiva.cliente_id,
            entrega_id: rotaPacote.entrega_id,
            ocorrido_em: agora,
            recebedor_nome: nomeRecebedor,
            recebedor_documento: docRecebedor,
            assinatura_base64: assinaturaBase64,
            latitude: gpsCoords.latitude,
            longitude: gpsCoords.longitude,
            documento_fiscal_ref: comprovanteLoteUUID
          });
        }

        // Enfileira todos os cilindros vazios recolhidos
        for (const c of vaziosParada) {
          await window.GasAppOffline.enfileirarMovimentacao({
            client_uuid: crypto.randomUUID ? crypto.randomUUID() : undefined,
            tipo: 'RECOLHA_CLIENTE',
            codigo_qr: c.codigo_qr,
            cilindro_id: c.id,
            cliente_id: paradaAtiva.cliente_id,
            entrega_id: rotaPacote.entrega_id,
            ocorrido_em: agora,
            observacao: c.divergente ? 'Divergente / Encaminhar à Triagem' : '',
            recebedor_nome: nomeRecebedor,
            recebedor_documento: docRecebedor,
            assinatura_base64: assinaturaBase64,
            latitude: gpsCoords.latitude,
            longitude: gpsCoords.longitude,
            documento_fiscal_ref: comprovanteLoteUUID
          });
        }

        // Atualiza parada como Concluída no pacote local
        paradaAtiva.status = 'Concluída';
        await window.GasAppOffline.salvarPacoteRota(rotaPacote);

        // EXPURGO LGPD IMEDIATO da tela
        limparCanvas();
        document.getElementById('input-recebedor-nome').value = '';
        document.getElementById('input-recebedor-doc').value = '';
        modalAssinatura.classList.remove('active');

        playSuccessBeep();
        Swal.fire({
          icon: 'success',
          title: 'Parada Finalizada com Sucesso!',
          text: `${cheiosParada.length} entregue(s) e ${vaziosParada.length} recolhido(s). Comprovante gerado com integridade SHA-256.`,
          timer: 2500,
          showConfirmButton: false
        });

        // Retorna para a rota
        voltarParaRota();

        // Se online, tenta sincronizar imediatamente
        if (navigator.onLine && window.GasAppOffline) {
          window.GasAppOffline.sincronizarLote().then(atualizarBannerRede);
        }
      } catch (err) {
        playErrorBeep();
        Swal.fire('Erro ao Finalizar Parada', err.message, 'error');
      }
    });
  }

  // ---- 9. Gaveta de Pendências e Rejeições (D4) ----
  const btnSyncStatus = document.getElementById('btn-sync-status');
  if (btnSyncStatus) {
    btnSyncStatus.addEventListener('click', () => {
      if (window.GasAppOffline) window.GasAppOffline.abrirModalPendencias();
    });
  }

  // Inicializa dados ao abrir a tela
  await carregarPacoteInicial();
  atualizarBannerRede();
});
