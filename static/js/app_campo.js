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

  // ---- Funções Utilitárias Centralizadas de Modal (Isolamento Estrito) ----
  function abrirModalCampo(modalEl) {
    if (!modalEl) return;
    modalEl.removeAttribute('hidden');
    modalEl.style.display = 'flex';
    modalEl.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function fecharModalCampo(modalEl) {
    if (!modalEl) return;
    modalEl.classList.remove('active');
    modalEl.style.display = 'none';
    modalEl.setAttribute('hidden', '');
    document.body.style.overflow = '';
  }

  window.abrirModalCampo = abrirModalCampo;
  window.fecharModalCampo = fecharModalCampo;

  // Fechar qualquer modal com Esc e clique no backdrop
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const activeModals = document.querySelectorAll('.field-modal.active, .modal-sheet-overlay.active');
      activeModals.forEach(m => fecharModalCampo(m));
    }
  });

  document.querySelectorAll('.field-modal, .modal-sheet-overlay').forEach(m => {
    m.addEventListener('click', (e) => {
      if (e.target === m) fecharModalCampo(m);
    });
  });

  // ---- Navegação Mobile-First em 4 Etapas da Jornada ----
  function ativarAbaJornada(targetId) {
    document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.bottom-nav-btn').forEach(btn => btn.classList.remove('active'));

    const targetPane = document.getElementById(targetId);
    if (targetPane) targetPane.classList.add('active');

    const activeNavBtn = document.querySelector(`.bottom-nav-btn[data-tab-target="${targetId}"]`);
    if (activeNavBtn) activeNavBtn.classList.add('active');

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  window.ativarAbaJornada = ativarAbaJornada;

  document.querySelectorAll('.bottom-nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-tab-target');
      if (targetId) ativarAbaJornada(targetId);
    });
  });

  // ---- Componente Customizado de Câmera Touch / Foto ----
  function configurarUploadCameraTouch() {
    document.querySelectorAll('.campo-btn-foto').forEach(btn => {
      const targetInputId = btn.getAttribute('data-target');
      const inputEl = document.getElementById(targetInputId);
      const previewEl = document.getElementById(targetInputId + '-preview');
      if (!inputEl) return;

      btn.addEventListener('click', () => inputEl.click());

      inputEl.addEventListener('change', () => {
        if (!previewEl) return;
        const file = inputEl.files && inputEl.files[0];
        if (!file) {
          previewEl.innerHTML = '';
          previewEl.style.display = 'none';
          return;
        }

        const isImage = file.type && file.type.startsWith('image/');
        const fileSizeKb = (file.size / 1024).toFixed(0);

        if (isImage) {
          const reader = new FileReader();
          reader.onload = (e) => {
            previewEl.style.display = 'block';
            previewEl.innerHTML = `
              <div class="campo-foto-preview-card" style="display:flex; align-items:center; gap:12px; background:var(--app-surface); border:1px solid var(--app-border); border-radius:var(--border-radius); padding:8px 12px; margin-top:8px;">
                <img src="${e.target.result}" style="width:52px; height:52px; object-fit:cover; border-radius:6px; border:1px solid var(--app-border);" alt="Preview">
                <div style="flex:1; overflow:hidden;">
                  <div style="font-size:13px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${file.name}</div>
                  <div style="font-size:11px; color:var(--app-text-muted);">${fileSizeKb} KB • Foto capturada</div>
                </div>
                <button type="button" class="btn-touch btn-touch-outline" style="min-height:36px; padding:4px 8px; font-size:12px; color:#ef4444; border-color:#ef4444;" data-remove-target="${targetInputId}">✕</button>
              </div>
            `;
            const btnRemover = previewEl.querySelector(`button[data-remove-target="${targetInputId}"]`);
            if (btnRemover) {
              btnRemover.addEventListener('click', (ev) => {
                ev.stopPropagation();
                inputEl.value = '';
                previewEl.innerHTML = '';
                previewEl.style.display = 'none';
              });
            }
          };
          reader.readAsDataURL(file);
        } else {
          previewEl.style.display = 'block';
          previewEl.innerHTML = `
            <div class="campo-foto-preview-card" style="display:flex; align-items:center; gap:12px; background:var(--app-surface); border:1px solid var(--app-border); border-radius:var(--border-radius); padding:8px 12px; margin-top:8px;">
              <span style="font-size:24px;">📄</span>
              <div style="flex:1; overflow:hidden;">
                <div style="font-size:13px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${file.name}</div>
                <div style="font-size:11px; color:var(--app-text-muted);">${fileSizeKb} KB</div>
              </div>
              <button type="button" class="btn-touch btn-touch-outline" style="min-height:36px; padding:4px 8px; font-size:12px; color:#ef4444; border-color:#ef4444;" data-remove-target="${targetInputId}">✕</button>
            </div>
          `;
          const btnRemover = previewEl.querySelector(`button[data-remove-target="${targetInputId}"]`);
          if (btnRemover) {
            btnRemover.addEventListener('click', (ev) => {
              ev.stopPropagation();
              inputEl.value = '';
              previewEl.innerHTML = '';
              previewEl.style.display = 'none';
            });
          }
        }
      });
    });
  }

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

  // ---- 5. Pre-flight Sync (Pacote da Rota no IndexedDB) & Empty State ----
  const btnBaixarRota = document.getElementById('btn-baixar-rota');
  if (btnBaixarRota) {
    btnBaixarRota.addEventListener('click', async () => {
      await baixarPacoteRotaServidor({ silencioso: false });
    });
  }

  const btnAtualizarPacoteTopo = document.getElementById('btn-atualizar-pacote-topo');
  if (btnAtualizarPacoteTopo) {
    btnAtualizarPacoteTopo.addEventListener('click', async () => {
      await baixarPacoteRotaServidor({ silencioso: false });
    });
  }

  function renderizarEmptyStateRota(msg) {
    const elTitulo = document.getElementById('rota-titulo');
    const elMotorista = document.getElementById('rota-motorista');
    const elVeiculo = document.getElementById('rota-veiculo');
    const elBarra = document.getElementById('rota-barra-fill');
    const elLotacao = document.getElementById('rota-lotacao-texto');
    const elSelo = document.getElementById('rota-selo-estimado');
    const stopsList = document.getElementById('stops-list');

    if (elTitulo) elTitulo.textContent = 'Minha Rota de Campo';
    if (elVeiculo) elVeiculo.textContent = 'Nenhum veículo vinculado';
    if (elBarra) {
      elBarra.style.width = '0%';
      elBarra.style.backgroundColor = 'var(--app-success)';
    }
    if (elLotacao) {
      elLotacao.textContent = '0%';
      elLotacao.style.color = 'var(--app-text-muted)';
    }
    if (elSelo) {
      elSelo.innerHTML = '<span style="background:var(--app-border); color:var(--app-text-muted); padding:2px 8px; border-radius:6px; font-size:11px; font-weight:700;">Sem Carga</span>';
    }

    if (stopsList) {
      stopsList.innerHTML = `
        <div class="empty-state-campo">
          <div class="empty-state-icon">🚚</div>
          <div class="empty-state-title">Nenhuma rota ativa no momento</div>
          <div class="empty-state-desc">${msg || 'Você não possui uma rota ou carga em andamento atribuída ao seu usuário. Quando a expedição liberar a carga, clique no botão abaixo para sincronizar.'}</div>
          <button type="button" class="btn-touch btn-touch-primary" id="btn-recarregar-rota-empty" style="margin-top:16px; min-height:48px;">
            🔄 Sincronizar Rota Agora
          </button>
        </div>
      `;
      const btnRecarregar = document.getElementById('btn-recarregar-rota-empty');
      if (btnRecarregar) {
        btnRecarregar.addEventListener('click', () => baixarPacoteRotaServidor({ silencioso: false }));
      }
    }
  }

  async function baixarPacoteRotaServidor(opts = {}) {
    const silencioso = opts && opts.silencioso === true;
    if (!navigator.onLine) {
      if (!silencioso) {
        Swal.fire('Sem Conexão', 'Conecte-se à internet para realizar a sincronização da rota.', 'warning');
      }
      return;
    }

    const btn = btnBaixarRota || btnAtualizarPacoteTopo;
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Sincronizando...';
    }

    try {
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
          renderizarEmptyStateRota(msg);
          if (!silencioso) {
            Swal.fire('Nenhuma Rota Ativa', msg, 'info');
          }
          return;
        }
        if (res.status === 401 || res.status === 403) {
          renderizarEmptyStateRota('Sessão expirada. Faça login novamente para carregar sua rota.');
          if (!silencioso) {
            Swal.fire('Sessão Expirada', 'Faça login novamente para sincronizar a rota.', 'warning');
          }
          return;
        }
        throw new Error(`Falha ao obter pacote da rota do servidor (HTTP ${res.status}).`);
      }

      const pacote = await res.json();
      if (!pacote || !pacote.entrega_id) {
        renderizarEmptyStateRota('Nenhuma entrega ativa configurada para o seu usuário.');
        return;
      }

      if (window.GasAppOffline) {
        await window.GasAppOffline.salvarPacoteRota(pacote);
      }
      rotaPacote = pacote;
      renderizarRota();
      playSuccessBeep();
      if (!silencioso) {
        Swal.fire({
          title: 'Pacote da Rota Baixado!',
          text: `${(pacote.paradas || []).length} paradas e ${(pacote.cilindros_caminhao || []).length} cilindros carregados offline.`,
          icon: 'success',
          timer: 2000,
          showConfirmButton: false
        });
      }
    } catch (err) {
      playErrorBeep();
      renderizarEmptyStateRota(err.message);
      if (!silencioso) {
        Swal.fire('Pre-flight Sync', err.message, 'info');
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '📥 Sincronizar Rota';
      }
    }
  }

  // Carrega Pacote Inicial do IndexedDB se existir ou busca online sem travar a interface
  async function carregarPacoteInicial() {
    let pacoteSalvo = null;
    if (window.GasAppOffline) {
      try {
        pacoteSalvo = await window.GasAppOffline.obterPacoteRota();
      } catch (err) {
        console.warn('[App de Campo] Falha ao carregar pacote offline:', err);
      }
    }

    if (pacoteSalvo && (pacoteSalvo.entrega_id || (pacoteSalvo.paradas && pacoteSalvo.paradas.length > 0))) {
      rotaPacote = pacoteSalvo;
      renderizarRota();
      console.log('[App de Campo] Pacote da rota carregado do IndexedDB com sucesso.');
      return;
    }

    if (navigator.onLine) {
      await baixarPacoteRotaServidor({ silencioso: true });
    } else {
      renderizarEmptyStateRota('Dispositivo offline e nenhum pacote de rota previamente salvo no IndexedDB.');
    }
  }

  // ---- 6. Renderização da Rota e Paradas ----
  function renderizarRota() {
    if (!rotaPacote || !rotaPacote.entrega_id) {
      renderizarEmptyStateRota();
      return;
    }

    // Cabeçalho da Carga
    const elTitulo = document.getElementById('rota-titulo');
    const elMotorista = document.getElementById('rota-motorista');
    const elVeiculo = document.getElementById('rota-veiculo');

    if (elTitulo) elTitulo.textContent = `Entrega #${rotaPacote.entrega_id} - ${rotaPacote.rota_nome || 'Rota'}`;
    if (elMotorista) elMotorista.textContent = rotaPacote.motorista || 'Motorista';
    if (elVeiculo) {
      const v = rotaPacote.veiculo;
      elVeiculo.textContent = v ? `${v.placa || ''} (${v.modelo || 'Veículo'})` : (rotaPacote.veiculo_placa ? `${rotaPacote.veiculo_placa} (${rotaPacote.veiculo_modelo || 'Veículo'})` : 'Veículo da Rota');
    }

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
    const viewParada = document.getElementById('view-parada');
    const viewRota = document.getElementById('view-rota');
    if (viewParada) viewParada.style.display = 'none';
    if (viewRota) viewRota.style.display = 'block';
    ativarAbaJornada('tab-pane-rota');
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

      abrirModalCampo(modalAssinatura);
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
      fecharModalCampo(modalAssinatura);
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
        fecharModalCampo(modalAssinatura);

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

  // ---- 9. Gaveta de Pendências e Rejeições (D4) & Aba de Sincronização ----
  const btnSyncStatus = document.getElementById('btn-sync-status');
  if (btnSyncStatus) {
    btnSyncStatus.addEventListener('click', () => {
      if (window.GasAppOffline) window.GasAppOffline.abrirModalPendencias();
    });
  }

  const btnForcarSync = document.getElementById('btn-forcar-sync-manual');
  if (btnForcarSync) {
    btnForcarSync.addEventListener('click', async () => {
      if (!navigator.onLine) {
        Swal.fire('Modo Offline', 'Dispositivo sem conexão com a internet para sincronizar.', 'warning');
        return;
      }
      btnForcarSync.disabled = true;
      btnForcarSync.textContent = 'Sincronizando...';
      try {
        if (window.GasAppOffline) {
          await window.GasAppOffline.sincronizarLote();
          await atualizarBannerRede();
          Swal.fire('Sincronização', 'Processo de sincronização com o servidor concluído com sucesso.', 'success');
        }
      } catch (err) {
        Swal.fire('Erro na Sincronização', err.message || 'Falha ao transmitir dados.', 'error');
      } finally {
        btnForcarSync.disabled = false;
        btnForcarSync.textContent = '🔄 Forçar Sincronização Agora';
      }
    });
  }

  const btnAbrirPendenciasTab = document.getElementById('btn-abrir-modal-pendencias');
  if (btnAbrirPendenciasTab) {
    btnAbrirPendenciasTab.addEventListener('click', () => {
      if (window.GasAppOffline) {
        window.GasAppOffline.abrirModalPendencias();
      }
    });
  }

  // ==============================================================================
  // 10. AÇÃO RÁPIDA: REGISTRAR ABASTECIMENTO NO CAMPO (SPRINT L2)
  // ==============================================================================
  const btnAbrirAbastCampo = document.getElementById('btn-abrir-abastecimento-campo');
  const modalAbastCampo = document.getElementById('modal-campo-abastecimento');
  const btnFecharAbastCampo = document.getElementById('btn-fechar-abastecimento-campo');
  const selVeiculoCampo = document.getElementById('campo-abast-veiculo');
  const inOdoAnteriorCampo = document.getElementById('campo-abast-odo-anterior');
  const inNovoOdoCampo = document.getElementById('campo-abast-odometro');
  const avisoOdoCampo = document.getElementById('campo-abast-aviso-odo');
  const inLitrosCampo = document.getElementById('campo-abast-litros');
  const inValorLitroCampo = document.getElementById('campo-abast-valor-litro');
  const inValorTotalCampo = document.getElementById('campo-abast-valor-total');
  const formAbastCampo = document.getElementById('form-campo-abastecimento');

  let veiculosCampoCache = [];

  async function carregarVeiculosCampo() {
    try {
      const res = await fetch('/logistica/api/veiculos/?sem_paginacao=1', {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
          'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
        },
        credentials: 'same-origin'
      });
      if (res.ok) {
        const data = await res.json();
        veiculosCampoCache = Array.isArray(data) ? data : (data.results || []);
      }
    } catch (e) {
      console.warn('[PWA] Não foi possível carregar lista online de veículos:', e);
    }

    if (selVeiculoCampo) {
      let opts = '<option value="">Selecione o Veículo</option>';
      if (rotaPacote && rotaPacote.veiculo) {
        opts += `<option value="${rotaPacote.veiculo.id || ''}" selected>${rotaPacote.veiculo.placa || ''} - ${rotaPacote.veiculo.modelo || ''}</option>`;
      }
      veiculosCampoCache.forEach(v => {
        if (!rotaPacote?.veiculo || v.id !== rotaPacote.veiculo.id) {
          opts += `<option value="${v.id}">${v.placa} - ${v.modelo}</option>`;
        }
      });
      selVeiculoCampo.innerHTML = opts;
      atualizarOdometroVeiculoCampo();
    }
  }

  function atualizarOdometroVeiculoCampo() {
    const vId = Number(selVeiculoCampo?.value);
    const v = veiculosCampoCache.find(i => i.id === vId) || (rotaPacote?.veiculo && rotaPacote.veiculo.id === vId ? rotaPacote.veiculo : null);
    if (v) {
      const odo = v.odometro_atual_km || 0;
      if (inOdoAnteriorCampo) inOdoAnteriorCampo.value = `${odo} km`;
      if (inNovoOdoCampo && !inNovoOdoCampo.value) inNovoOdoCampo.value = odo;
    } else {
      if (inOdoAnteriorCampo) inOdoAnteriorCampo.value = '-- km';
    }
  }

  selVeiculoCampo?.addEventListener('change', atualizarOdometroVeiculoCampo);

  inNovoOdoCampo?.addEventListener('input', () => {
    const vId = Number(selVeiculoCampo?.value);
    const v = veiculosCampoCache.find(i => i.id === vId) || (rotaPacote?.veiculo && rotaPacote.veiculo.id === vId ? rotaPacote.veiculo : null);
    if (v && inNovoOdoCampo && avisoOdoCampo) {
      const novo = Number(inNovoOdoCampo.value || 0);
      const atual = Number(v.odometro_atual_km || 0);
      avisoOdoCampo.style.display = novo < atual ? 'block' : 'none';
    }
  });

  // Auto-cálculo dos 3 valores no PWA
  inLitrosCampo?.addEventListener('input', () => {
    const l = parseFloat(inLitrosCampo.value);
    const vl = parseFloat(inValorLitroCampo.value);
    const vt = parseFloat(inValorTotalCampo.value);
    if (!isNaN(l) && l > 0) {
      if (!isNaN(vl) && vl > 0) inValorTotalCampo.value = (l * vl).toFixed(2);
      else if (!isNaN(vt) && vt > 0) inValorLitroCampo.value = (vt / l).toFixed(4);
    }
  });

  inValorLitroCampo?.addEventListener('input', () => {
    const l = parseFloat(inLitrosCampo.value);
    const vl = parseFloat(inValorLitroCampo.value);
    const vt = parseFloat(inValorTotalCampo.value);
    if (!isNaN(vl) && vl > 0) {
      if (!isNaN(l) && l > 0) inValorTotalCampo.value = (l * vl).toFixed(2);
      else if (!isNaN(vt) && vt > 0) inLitrosCampo.value = (vt / vl).toFixed(3);
    }
  });

  inValorTotalCampo?.addEventListener('input', () => {
    const l = parseFloat(inLitrosCampo.value);
    const vl = parseFloat(inValorLitroCampo.value);
    const vt = parseFloat(inValorTotalCampo.value);
    if (!isNaN(vt) && vt > 0) {
      if (!isNaN(l) && l > 0) inValorLitroCampo.value = (vt / l).toFixed(4);
      else if (!isNaN(vl) && vl > 0) inLitrosCampo.value = (vt / vl).toFixed(3);
    }
  });

  if (btnAbrirAbastCampo) {
    btnAbrirAbastCampo.addEventListener('click', async () => {
      await carregarVeiculosCampo();
      abrirModalCampo(modalAbastCampo);
    });
  }

  if (btnFecharAbastCampo) {
    btnFecharAbastCampo.addEventListener('click', () => {
      fecharModalCampo(modalAbastCampo);
    });
  }

  if (formAbastCampo) {
    formAbastCampo.addEventListener('submit', async (e) => {
      e.preventDefault();
      const vId = Number(selVeiculoCampo.value);
      if (!vId) {
        Swal.fire('Veículo Obrigatório', 'Selecione o veículo abastecido.', 'warning');
        return;
      }

      const odo = Number(inNovoOdoCampo.value);
      const v = veiculosCampoCache.find(i => i.id === vId) || (rotaPacote?.veiculo && rotaPacote.veiculo.id === vId ? rotaPacote.veiculo : null);
      if (v && odo < Number(v.odometro_atual_km || 0)) {
        playErrorBeep();
        Swal.fire('Quilometragem Inválida', `O novo odômetro (${odo} km) não pode ser inferior ao atual (${v.odometro_atual_km} km).`, 'warning');
        return;
      }

      const litros = inLitrosCampo.value;
      const valorLitro = inValorLitroCampo.value;
      const valorTotal = inValorTotalCampo.value;
      const tanqueCheio = document.getElementById('campo-abast-tanque-cheio').checked;
      const tipoComb = document.getElementById('campo-abast-tipo').value;
      const posto = document.getElementById('campo-abast-posto').value.trim();

      const clientUuid = crypto.randomUUID ? crypto.randomUUID() : (window.GasAppOffline ? window.GasAppOffline._gerarUUID() : 'pwa-' + Date.now());

      const payload = {
        client_uuid: clientUuid,
        veiculo_id: vId,
        tipo_combustivel: tipoComb,
        odometro_km: odo,
        litros: litros,
        valor_litro: valorLitro,
        valor_total: valorTotal,
        tanque_cheio: tanqueCheio,
        posto_nome: posto,
        origem: 'PWA',
        data_hora: new Date().toISOString()
      };

      const btnSalvar = document.getElementById('btn-salvar-abastecimento-campo');
      if (btnSalvar) {
        btnSalvar.disabled = true;
        btnSalvar.textContent = 'Gravando...';
      }

      try {
        if (navigator.onLine) {
          const res = await fetch('/logistica/api/abastecimentos/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': (window.GasAppOffline ? window.GasAppOffline._getCSRFToken() : ''),
              'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
              'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
            },
            body: JSON.stringify({
              client_uuid: clientUuid,
              veiculo: vId,
              tipo_combustivel: tipoComb,
              odometro_km: odo,
              litros: litros,
              valor_litro: valorLitro,
              valor_total: valorTotal,
              tanque_cheio: tanqueCheio,
              posto_nome: posto,
              origem: 'PWA',
              data_hora: new Date().toISOString()
            })
          });

          if (!res.ok) {
            const errJson = await res.json().catch(() => ({}));
            throw new Error(errJson.detail || errJson.error || 'Erro na transmissão ao vivo.');
          }

          playSuccessBeep();
          Swal.fire({
            icon: 'success',
            title: 'Abastecimento Gravado!',
            text: `${litros} L registrados e transmitidos com sucesso.`,
            timer: 2000,
            showConfirmButton: false
          });
        } else {
          // Operação Offline
          if (window.GasAppOffline) {
            await window.GasAppOffline.enfileirarAbastecimento(payload);
          }
          playSuccessBeep();
          Swal.fire({
            icon: 'info',
            title: 'Gravado Offline!',
            text: 'Abastecimento salvo na fila local. Será sincronizado assim que a conexão retornar.',
            timer: 3000,
            showConfirmButton: false
          });
        }

        formAbastCampo.reset();
        fecharModalCampo(modalAbastCampo);
        atualizarBannerRede();
      } catch (err) {
        console.warn('[PWA] Falha online, salvando na fila offline:', err);
        if (window.GasAppOffline) {
          await window.GasAppOffline.enfileirarAbastecimento(payload);
          playSuccessBeep();
          Swal.fire({
            icon: 'info',
            title: 'Gravado na Fila Offline',
            text: 'Falha momentânea de rede. O registro foi armazenado com segurança no celular e será reenviado.',
            timer: 3000,
            showConfirmButton: false
          });
          formAbastCampo.reset();
          fecharModalCampo(modalAbastCampo);
          atualizarBannerRede();
        } else {
          playErrorBeep();
          Swal.fire('Erro', err.message, 'error');
        }
      } finally {
        if (btnSalvar) {
          btnSalvar.disabled = false;
          btnSalvar.textContent = '💾 Confirmar e Gravar Abastecimento';
        }
      }
    });
  }

  // ==============================================================================
  // 11. CHECKLIST PRÉ-SAÍDA DO MOTORISTA (SPRINT L3)
  // ==============================================================================
  const btnAbrirChecklistCampo = document.getElementById('btn-abrir-checklist-campo');
  const modalChecklistCampo = document.getElementById('modal-campo-checklist');
  const btnFecharChecklistCampo = document.getElementById('btn-fechar-checklist-campo');
  const formChecklistCampo = document.getElementById('form-campo-checklist');
  const inChkOdometro = document.getElementById('campo-chk-odometro');
  const elChkVeiculoInfo = document.getElementById('campo-chk-veiculo-info');
  const listaItensChkEl = document.getElementById('campo-chk-itens-lista');

  const ITENS_CHECKLIST_PADRAO = [
    { nome: 'Pneus e Rodas (calibragem, estepe e desgaste)', impeditivo: true },
    { nome: 'Sistema de Freios (pedal e freio de mão)', impeditivo: true },
    { nome: 'Luzes, Faróis, Lanternas e Setas', impeditivo: true },
    { nome: 'Vazamentos Visíveis (óleo, combustível, arla)', impeditivo: true },
    { nome: 'Extintor de Incêndio (pressão e lacre válido)', impeditivo: true },
    { nome: 'Kit de Emergência (triângulo, macaco, chave)', impeditivo: false },
    { nome: 'Cintas e Travas de Carga de Gás/GLP', impeditivo: true },
    { nome: 'Documentação de Bordo (CRLV e CNH)', impeditivo: true }
  ];

  function renderItensChecklist() {
    if (!listaItensChkEl) return;
    listaItensChkEl.innerHTML = '';
    ITENS_CHECKLIST_PADRAO.forEach((it, idx) => {
      const div = document.createElement('div');
      div.style.cssText = 'background:var(--app-bg); padding:10px; border-radius:var(--border-radius); border:1px solid var(--app-border);';
      div.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <strong style="font-size:13px;">${it.nome}</strong>
          ${it.impeditivo ? '<span style="font-size:10px; background:rgba(239,68,68,0.15); color:#ef4444; padding:2px 6px; border-radius:4px; font-weight:700;">IMPEDITIVO</span>' : ''}
        </div>
        <div style="display:flex; gap:12px; align-items:center;">
          <label style="display:flex; align-items:center; gap:4px; font-size:13px; font-weight:600; cursor:pointer; color:var(--app-success);">
            <input type="radio" name="chk_item_${idx}" value="OK" checked style="width:18px; height:18px;"> OK
          </label>
          <label style="display:flex; align-items:center; gap:4px; font-size:13px; font-weight:600; cursor:pointer; color:#ef4444;">
            <input type="radio" name="chk_item_${idx}" value="Não OK" style="width:18px; height:18px;"> Não OK
          </label>
          <label style="display:flex; align-items:center; gap:4px; font-size:13px; font-weight:600; cursor:pointer; color:var(--app-text-muted);">
            <input type="radio" name="chk_item_${idx}" value="N.A." style="width:18px; height:18px;"> N.A.
          </label>
        </div>
        <div id="chk_obs_wrap_${idx}" style="display:none; margin-top:6px;">
          <input type="text" id="chk_obs_${idx}" class="input-touch" placeholder="Descreva o problema detectado neste item..." style="font-size:12px; padding:6px;">
        </div>
      `;
      listaItensChkEl.appendChild(div);

      const radios = div.querySelectorAll(`input[name="chk_item_${idx}"]`);
      radios.forEach(r => {
        r.addEventListener('change', () => {
          const wrap = document.getElementById(`chk_obs_wrap_${idx}`);
          if (wrap) wrap.style.display = (r.value === 'Não OK') ? 'block' : 'none';
        });
      });
    });
  }

  btnAbrirChecklistCampo?.addEventListener('click', () => {
    const v = rotaPacote?.veiculo;
    if (elChkVeiculoInfo) {
      elChkVeiculoInfo.textContent = v ? `${v.placa} - ${v.modelo}` : 'Sem veículo alocado';
    }
    if (inChkOdometro && v) {
      const vObj = veiculosCampoCache.find(x => x.id === v.id);
      inChkOdometro.value = vObj?.odometro_atual_km || '';
    }
    renderItensChecklist();
    abrirModalCampo(modalChecklistCampo);
  });

  btnFecharChecklistCampo?.addEventListener('click', () => {
    fecharModalCampo(modalChecklistCampo);
  });

  formChecklistCampo?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const v = rotaPacote?.veiculo;
    const vId = v ? v.id : (veiculosCampoCache[0]?.id || null);
    if (!vId) {
      Swal.fire('Aviso', 'Nenhum veículo identificado para o checklist.', 'warning');
      return;
    }

    const odo = parseFloat(inChkOdometro.value);
    if (isNaN(odo) || odo <= 0) {
      Swal.fire('Validação', 'Informe o odômetro atual do veículo.', 'warning');
      return;
    }

    const respostas = [];
    let possuiNaoOkImpeditivo = false;

    ITENS_CHECKLIST_PADRAO.forEach((it, idx) => {
      const radioChecked = document.querySelector(`input[name="chk_item_${idx}"]:checked`);
      const st = radioChecked ? radioChecked.value : 'OK';
      const obs = document.getElementById(`chk_obs_${idx}`)?.value || '';
      respostas.push({
        nome: it.nome,
        status: st,
        impeditivo: it.impeditivo,
        obs: obs
      });
      if (st === 'Não OK' && it.impeditivo) {
        possuiNaoOkImpeditivo = true;
      }
    });

    const fotoInput = document.getElementById('campo-chk-foto');
    const observacoes = document.getElementById('campo-chk-obs')?.value || '';
    const btnSalvar = document.getElementById('btn-salvar-checklist-campo');

    if (btnSalvar) {
      btnSalvar.disabled = true;
      btnSalvar.textContent = 'Enviando Checklist...';
    }

    const clientUuid = (crypto.randomUUID ? crypto.randomUUID() : ('chk_' + Date.now()));

    try {
      if (navigator.onLine) {
        const formData = new FormData();
        formData.append('client_uuid', clientUuid);
        formData.append('veiculo', vId);
        formData.append('odometro', odo);
        formData.append('respostas_itens', JSON.stringify(respostas));
        formData.append('observacoes', observacoes);
        if (rotaPacote?.entrega_id) formData.append('entrega', rotaPacote.entrega_id);
        if (fotoInput?.files?.length > 0) {
          formData.append('foto', fotoInput.files[0]);
        }

        const res = await fetch('/logistica/api/checklists/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken') || '',
            'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
            'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
          },
          body: formData
        });

        const data = await res.json();
        if (!res.ok) throw new Error(JSON.stringify(data));

        fecharModalCampo(modalChecklistCampo);
        formChecklistCampo.reset();

        if (!data.aprovado || possuiNaoOkImpeditivo) {
          playErrorBeep();
          Swal.fire({
            icon: 'warning',
            title: 'Checklist Reprovado!',
            text: 'Itens críticos com defeito foram detectados. Uma OS Corretiva foi gerada e o veículo está inapto para iniciar rota.',
            confirmButtonText: 'Entendido'
          });
        } else {
          playSuccessBeep();
          Swal.fire({
            icon: 'success',
            title: 'Checklist Aprovado!',
            text: 'Veículo inspecionado e liberado com sucesso para a rota.',
            timer: 2500,
            showConfirmButton: false
          });
        }
      } else {
        await window.GasAppOffline.enfileirarChecklist({
          client_uuid: clientUuid,
          veiculo_id: vId,
          odometro: odo,
          respostas_itens: respostas,
          observacoes: observacoes
        });

        fecharModalCampo(modalChecklistCampo);
        formChecklistCampo.reset();
        playSuccessBeep();

        if (possuiNaoOkImpeditivo) {
          Swal.fire({
            icon: 'warning',
            title: 'Checklist Salvo Offline (Reprovado)',
            text: 'Itens críticos apontados. O veículo será imobilizado assim que sincronizar com a base.',
            confirmButtonText: 'OK'
          });
        } else {
          Swal.fire({
            icon: 'info',
            title: 'Checklist Gravado Offline',
            text: 'Checklist registrado na memória do celular. Será transmitido automaticamente assim que a conexão retornar.',
            timer: 3000,
            showConfirmButton: false
          });
        }
      }
    } catch (err) {
      await window.GasAppOffline.enfileirarChecklist({
        client_uuid: clientUuid,
        veiculo_id: vId,
        odometro: odo,
        respostas_itens: respostas,
        observacoes: observacoes
      });
      fecharModalCampo(modalChecklistCampo);
      formChecklistCampo.reset();
      Swal.fire('Salvo Offline', 'Falha temporária de rede. O checklist foi gravado com segurança no dispositivo.', 'info');
    } finally {
      if (btnSalvar) {
        btnSalvar.disabled = false;
        btnSalvar.textContent = '💾 Gravar e Transmitir Checklist';
      }
    }
  });

  // ==============================================================================
  // 12. REPORTAR DEFEITO MECÂNICO / ELÉTRICO (SPRINT L3)
  // ==============================================================================
  const btnAbrirDefeitoCampo = document.getElementById('btn-abrir-defeito-campo');
  const modalDefeitoCampo = document.getElementById('modal-campo-defeito');
  const btnFecharDefeitoCampo = document.getElementById('btn-fechar-defeito-campo');
  const formDefeitoCampo = document.getElementById('form-campo-defeito');
  const inDefeitoOdo = document.getElementById('campo-defeito-odometro');
  const elDefeitoVeiculoInfo = document.getElementById('campo-defeito-veiculo-info');

  btnAbrirDefeitoCampo?.addEventListener('click', () => {
    const v = rotaPacote?.veiculo;
    if (elDefeitoVeiculoInfo) {
      elDefeitoVeiculoInfo.textContent = v ? `${v.placa} - ${v.modelo}` : 'Sem veículo alocado';
    }
    if (inDefeitoOdo && v) {
      const vObj = veiculosCampoCache.find(x => x.id === v.id);
      inDefeitoOdo.value = vObj?.odometro_atual_km || '';
    }
    abrirModalCampo(modalDefeitoCampo);
  });

  btnFecharDefeitoCampo?.addEventListener('click', () => {
    fecharModalCampo(modalDefeitoCampo);
  });

  formDefeitoCampo?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const v = rotaPacote?.veiculo;
    const vId = v ? v.id : (veiculosCampoCache[0]?.id || null);
    if (!vId) {
      Swal.fire('Aviso', 'Nenhum veículo identificado.', 'warning');
      return;
    }

    const desc = document.getElementById('campo-defeito-descricao')?.value.trim();
    if (!desc) {
      Swal.fire('Validação', 'Descreva o defeito ou sintoma apresentado pelo veículo.', 'warning');
      return;
    }

    const odo = inDefeitoOdo?.value ? parseFloat(inDefeitoOdo.value) : null;
    const prioridade = document.getElementById('campo-defeito-prioridade')?.value || 'Normal';
    const imobiliza = document.getElementById('campo-defeito-imobiliza')?.checked;
    const fotoInput = document.getElementById('campo-defeito-foto');
    const btnSalvar = document.getElementById('btn-salvar-defeito-campo');

    if (btnSalvar) {
      btnSalvar.disabled = true;
      btnSalvar.textContent = 'Transmitindo Relato...';
    }

    const clientUuid = (crypto.randomUUID ? crypto.randomUUID() : ('def_' + Date.now()));

    try {
      if (navigator.onLine) {
        const payload = {
          client_uuid: clientUuid,
          veiculo: vId,
          tipo: 'Corretiva',
          origem: 'Motorista',
          prioridade: prioridade,
          imobiliza_veiculo: imobiliza,
          descricao_problema: desc,
          odometro_entrada: odo,
          status: 'Aberta'
        };

        const res = await fetch('/logistica/api/ordens-servico/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') || '',
            'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
            'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
          },
          body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) throw new Error(JSON.stringify(data));

        if (data.id && fotoInput?.files?.length > 0) {
          try {
            const fd = new FormData();
            fd.append('tipo', 'Foto Antes');
            fd.append('descricao', 'Foto do defeito reportado pelo motorista no campo');
            fd.append('arquivo', fotoInput.files[0]);
            await fetch(`/logistica/api/ordens-servico/${data.id}/adicionar-anexo/`, {
              method: 'POST',
              headers: {
                'X-CSRFToken': getCookie('csrftoken') || '',
                'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
                'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
              },
              body: fd
            });
          } catch(e) {
            console.warn('Foto não anexada:', e);
          }
        }

        fecharModalCampo(modalDefeitoCampo);
        formDefeitoCampo.reset();

        playSuccessBeep();
        if (imobiliza) {
          Swal.fire({
            icon: 'warning',
            title: 'Defeito Crítico Reportado!',
            text: `OS ${data.numero} gerada com imobilização. O veículo foi bloqueado para segurança operacional.`,
            confirmButtonText: 'Entendido'
          });
        } else {
          Swal.fire({
            icon: 'success',
            title: 'Relato de Defeito Enviado!',
            text: `OS ${data.numero} registrada na esteira de manutenção da oficina.`,
            timer: 3000,
            showConfirmButton: false
          });
        }
      } else {
        await window.GasAppOffline.enfileirarDefeito({
          client_uuid: clientUuid,
          veiculo_id: vId,
          descricao_problema: desc,
          prioridade: prioridade,
          imobiliza_veiculo: imobiliza,
          odometro_entrada: odo
        });

        fecharModalCampo(modalDefeitoCampo);
        formDefeitoCampo.reset();
        playSuccessBeep();

        Swal.fire({
          icon: 'info',
          title: 'Relato Gravado Offline',
          text: 'O defeito foi salvo localmente. Assim que houver conexão, a OS será gerada automaticamente na oficina.',
          timer: 3000,
          showConfirmButton: false
        });
      }
    } catch (err) {
      await window.GasAppOffline.enfileirarDefeito({
        client_uuid: clientUuid,
        veiculo_id: vId,
        descricao_problema: desc,
        prioridade: prioridade,
        imobiliza_veiculo: imobiliza,
        odometro_entrada: odo
      });
      fecharModalCampo(modalDefeitoCampo);
      formDefeitoCampo.reset();
      Swal.fire('Salvo Offline', 'Falha momentânea de rede. O relato de defeito foi armazenado no aparelho.', 'info');
    } finally {
      if (btnSalvar) {
        btnSalvar.disabled = false;
        btnSalvar.textContent = '🚨 Transmitir Relato de Defeito (Gerar OS)';
      }
    }
  });

  // ==============================================================================
  // 13. CONFERÊNCIA DE SAÍDA (SPRINT L4)
  // ==============================================================================
  const btnAbrirConfSaida = document.getElementById('btn-abrir-conferencia-saida');
  const modalConfSaida = document.getElementById('modal-campo-conferencia-saida');
  const btnFecharConfSaida = document.getElementById('btn-fechar-conf-saida-campo');
  const btnSalvarConfSaida = document.getElementById('btn-salvar-conferencia-saida');
  const containerItensSaida = document.getElementById('campo-saida-itens-container');
  const inBarcodeSaida = document.getElementById('campo-saida-barcode-input');
  const btnBiparSaida = document.getElementById('btn-campo-bipar-saida');

  let itensSaidaCache = [];

  async function carregarConferenciaSaida() {
    if (!rotaPacote || !rotaPacote.entrega_id) {
      Swal.fire('Aviso', 'Nenhuma rota ativa baixada no momento.', 'warning');
      return;
    }

    abrirModalCampo(modalConfSaida);
    if (containerItensSaida) {
      containerItensSaida.innerHTML = '<div style="text-align:center; padding:20px; color:var(--app-text-muted);">Carregando romaneio...</div>';
    }

    try {
      let dados = null;
      if (navigator.onLine) {
        const res = await fetch(`/logistica/api/entregas/${rotaPacote.entrega_id}/conferencia-saida/`, {
          headers: {
            'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
            'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
          },
          credentials: 'same-origin'
        });
        if (res.ok) {
          dados = await res.json();
        }
      }

      if (!dados) {
        // Fallback offline a partir do rotaPacote
        const itensMap = [];
        (rotaPacote.paradas || []).forEach(p => {
          (p.itens || []).forEach(it => {
            itensMap.push({
              venda_id: p.pedido_id || p.venda_id || p.ordem,
              cliente_nome: p.cliente_nome,
              produto_id: it.produto_id || 1,
              produto_nome: it.produto,
              quantidade_esperada: it.quantidade,
              quantidade_conferida_atual: it.quantidade,
              possui_divergencia: false,
              peso_unitario_kg: it.peso_unitario_kg || 0
            });
          });
        });
        dados = {
          entrega_id: rotaPacote.entrega_id,
          itens_esperados: itensMap,
          percentual_lotacao: rotaPacote.percentual_lotacao || 0
        };
      }

      itensSaidaCache = dados.itens_esperados || [];
      renderizarItensConferenciaSaida(itensSaidaCache);
    } catch (err) {
      console.warn('Erro ao carregar itens da conferência:', err);
      if (containerItensSaida) {
        containerItensSaida.innerHTML = '<div style="color:var(--app-danger); text-align:center;">Falha ao carregar itens do romaneio.</div>';
      }
    }
  }

  function renderizarItensConferenciaSaida(itens) {
    if (!containerItensSaida) return;
    if (!itens || itens.length === 0) {
      containerItensSaida.innerHTML = '<div style="text-align:center; padding:20px; color:var(--app-text-muted);">Nenhum item encontrado no romaneio.</div>';
      return;
    }

    let totalEsp = 0;
    let totalConf = 0;
    let divergencias = 0;

    let html = '';
    itens.forEach((it, idx) => {
      const esp = parseFloat(it.quantidade_esperada) || 0;
      const conf = it.quantidade_conferida !== undefined ? parseFloat(it.quantidade_conferida) : esp;
      totalEsp += esp;
      totalConf += conf;
      const isDiv = conf !== esp;
      if (isDiv) divergencias++;

      html += `
        <div class="conf-item-card ${isDiv ? 'divergent' : ''}" data-idx="${idx}">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
            <div>
              <strong style="font-size:14px;">${it.produto_nome}</strong>
              <div style="font-size:11px; color:var(--app-text-muted);">Destino: ${it.cliente_nome || 'Cliente'}</div>
            </div>
            <div style="text-align:right;">
              <span style="font-size:12px; color:var(--app-text-muted);">Esperado: <strong>${esp}</strong></span>
            </div>
          </div>
          <div style="display:flex; gap:10px; align-items:center;">
            <label style="font-size:12px; font-weight:700;">Conferido:</label>
            <input type="number" class="input-touch item-qtd-conf" data-idx="${idx}" value="${conf}" min="0" step="1" style="width:90px; padding:6px 10px; font-weight:800; text-align:center;">
            ${isDiv ? `<span style="color:var(--app-warning); font-size:12px; font-weight:700;">⚠️ Dif: ${conf - esp}</span>` : '<span style="color:var(--app-success); font-size:12px; font-weight:700;">✓ OK</span>'}
          </div>
          ${isDiv ? `
            <div style="margin-top:10px; border-top:1px dashed var(--app-border); padding-top:8px;">
              <label style="font-size:11px; font-weight:700; color:var(--app-text-muted); display:block; margin-bottom:4px;">Motivo da Divergência *</label>
              <select class="input-touch item-motivo-conf" data-idx="${idx}" style="padding:6px; font-size:12px; margin-bottom:6px;">
                <option value="Avaria no manuseio" ${it.motivo === 'Avaria no manuseio' ? 'selected' : ''}>Avaria no manuseio</option>
                <option value="Erro de separação" ${it.motivo === 'Erro de separação' || !it.motivo ? 'selected' : ''}>Erro de separação</option>
                <option value="Cilindro vazio/errado" ${it.motivo === 'Cilindro vazio/errado' ? 'selected' : ''}>Cilindro vazio/errado</option>
                <option value="Outro" ${it.motivo === 'Outro' ? 'selected' : ''}>Outro</option>
              </select>
              <input type="text" class="input-touch item-just-conf" data-idx="${idx}" placeholder="Justificativa da divergência *" value="${it.justificativa || ''}" style="padding:6px 10px; font-size:12px;">
            </div>
          ` : ''}
        </div>
      `;
    });

    containerItensSaida.innerHTML = html;

    // Atualiza resumo
    const elTotEsp = document.getElementById('campo-saida-total-esp');
    const elTotConf = document.getElementById('campo-saida-total-conf');
    const elAviso = document.getElementById('campo-saida-aviso-liberacao');
    const elLotacao = document.getElementById('campo-saida-lotacao');

    if (elTotEsp) elTotEsp.textContent = totalEsp;
    if (elTotConf) elTotConf.textContent = totalConf;
    if (elLotacao && rotaPacote) elLotacao.textContent = `${rotaPacote.percentual_lotacao || 0}%`;

    if (elAviso) {
      if (divergencias === 0) {
        elAviso.textContent = '100% Conferido (Liberação Imediata)';
        elAviso.style.color = 'var(--app-success)';
      } else {
        elAviso.textContent = `${divergencias} Divergência(s) registrada(s) - Requer Justificativa`;
        elAviso.style.color = 'var(--app-warning)';
      }
    }

    // Handlers de alteração nos inputs
    containerItensSaida.querySelectorAll('.item-qtd-conf').forEach(inp => {
      inp.addEventListener('change', (e) => {
        const i = parseInt(e.target.dataset.idx);
        itensSaidaCache[i].quantidade_conferida = parseFloat(e.target.value) || 0;
        renderizarItensConferenciaSaida(itensSaidaCache);
      });
    });

    containerItensSaida.querySelectorAll('.item-motivo-conf').forEach(sel => {
      sel.addEventListener('change', (e) => {
        const i = parseInt(e.target.dataset.idx);
        itensSaidaCache[i].motivo = e.target.value;
      });
    });

    containerItensSaida.querySelectorAll('.item-just-conf').forEach(inp => {
      inp.addEventListener('input', (e) => {
        const i = parseInt(e.target.dataset.idx);
        itensSaidaCache[i].justificativa = e.target.value;
      });
    });
  }

  btnAbrirConfSaida?.addEventListener('click', carregarConferenciaSaida);
  btnFecharConfSaida?.addEventListener('click', () => fecharModalCampo(modalConfSaida));

  btnBiparSaida?.addEventListener('click', () => {
    const code = inBarcodeSaida?.value.trim().toLowerCase();
    if (!code) return;
    const itemMatch = itensSaidaCache.find(it => (it.produto_nome && it.produto_nome.toLowerCase().includes(code)) || (it.produto_id && String(it.produto_id) === code));
    if (itemMatch) {
      itemMatch.quantidade_conferida = (itemMatch.quantidade_conferida || 0) + 1;
      playSuccessBeep();
      inBarcodeSaida.value = '';
      renderizarItensConferenciaSaida(itensSaidaCache);
    } else {
      playErrorBeep();
      Swal.fire('Não encontrado', 'Código não coincide com nenhum item deste romaneio.', 'warning');
    }
  });

  btnSalvarConfSaida?.addEventListener('click', async () => {
    if (!rotaPacote || !rotaPacote.entrega_id) return;

    // Valida se divergências têm justificativa
    for (let it of itensSaidaCache) {
      const esp = parseFloat(it.quantidade_esperada) || 0;
      const conf = it.quantidade_conferida !== undefined ? parseFloat(it.quantidade_conferida) : esp;
      if (conf !== esp) {
        if (!it.justificativa || it.justificativa.trim().length < 5) {
          Swal.fire('Aviso', `Informe uma justificativa válida para a divergência em: ${it.produto_nome}`, 'warning');
          return;
        }
      }
    }

    btnSalvarConfSaida.disabled = true;
    btnSalvarConfSaida.textContent = 'Gravando Conferência...';

    const payloadItens = itensSaidaCache.map(it => ({
      venda_id: it.venda_id,
      produto_id: it.produto_id,
      quantidade_esperada: parseFloat(it.quantidade_esperada) || 0,
      quantidade_conferida: it.quantidade_conferida !== undefined ? parseFloat(it.quantidade_conferida) : (parseFloat(it.quantidade_esperada) || 0),
      motivo: it.motivo || 'Outro',
      justificativa: it.justificativa || 'Conferência de saída validada sem divergência.',
      categoria_item: 'Cheio'
    }));

    try {
      if (navigator.onLine) {
        const res = await fetch(`/logistica/api/entregas/${rotaPacote.entrega_id}/conferencia-saida/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') || '',
            'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
            'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
          },
          body: JSON.stringify({
            itens: payloadItens,
            iniciar_rota: true
          })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(JSON.stringify(data));

        fecharModalCampo(modalConfSaida);
        playSuccessBeep();

        if (data.saida_liberada) {
          Swal.fire('Saída Liberada!', '100% dos itens conferidos. Rota iniciada com sucesso!', 'success');
        } else {
          Swal.fire('Validação Registrada!', `Divergência enviada. Aguardando liberação/aprovação de alçada do gestor (${data.pendencias_aprovacao} pendente(s)).`, 'info');
        }
      } else {
        fecharModalCampo(modalConfSaida);
        playSuccessBeep();
        Swal.fire('Gravado Offline', 'Conferência de saída armazenada localmente para sincronização.', 'info');
      }
    } catch (err) {
      playErrorBeep();
      Swal.fire('Erro na Conferência', err.message || 'Falha ao processar conferência de saída.', 'error');
    } finally {
      btnSalvarConfSaida.disabled = false;
      btnSalvarConfSaida.textContent = '✅ Salvar Conferência e Liberar Rota';
    }
  });

  // ==============================================================================
  // 14. BALANÇO E RETORNO DE VIAGEM (SPRINT L4)
  // ==============================================================================
  const btnAbrirConfRetorno = document.getElementById('btn-abrir-conferencia-retorno');
  const modalConfRetorno = document.getElementById('modal-campo-conferencia-retorno');
  const btnFecharConfRetorno = document.getElementById('btn-fechar-conf-retorno-campo');
  const btnSalvarConfRetorno = document.getElementById('btn-salvar-conferencia-retorno');
  const elRetSaiu = document.getElementById('campo-ret-despachado');
  const elRetEntregue = document.getElementById('campo-ret-entregue');
  const elRetVazios = document.getElementById('campo-ret-vazios');
  const elRetCheiosRetorno = document.getElementById('campo-ret-cheios-retorno');
  const elRetJustificado = document.getElementById('campo-ret-justificado');
  const elRetPendente = document.getElementById('campo-ret-pendente');
  const elRetAvisoPendencia = document.getElementById('campo-ret-aviso-pendencia');

  async function carregarConferenciaRetorno() {
    if (!rotaPacote || !rotaPacote.entrega_id) {
      Swal.fire('Aviso', 'Nenhuma rota ativa baixada no momento.', 'warning');
      return;
    }

    abrirModalCampo(modalConfRetorno);

    try {
      if (navigator.onLine) {
        const res = await fetch(`/logistica/api/entregas/${rotaPacote.entrega_id}/conferencia-retorno/`, {
          headers: {
            'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
            'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
          },
          credentials: 'same-origin'
        });
        if (res.ok) {
          const dados = await res.json();
          if (elRetSaiu) elRetSaiu.textContent = dados.total_despachado || 0;
          if (elRetEntregue) elRetEntregue.textContent = dados.total_entregue || 0;
          if (elRetVazios) elRetVazios.textContent = dados.total_recolhido_vazio || 0;
          if (elRetCheiosRetorno) elRetCheiosRetorno.textContent = dados.cheios_nao_entregues || 0;
          if (elRetJustificado) elRetJustificado.textContent = dados.total_justificado || 0;
          if (elRetPendente) elRetPendente.textContent = dados.diferenca_pendente || 0;

          if (elRetAvisoPendencia) {
            elRetAvisoPendencia.style.display = dados.possui_pendencia ? 'block' : 'none';
          }
          return;
        }
      }

      // Offline calculation fallback
      let totalDespachado = 0;
      let totalEntregue = 0;
      let totalVazios = 0;
      (rotaPacote.paradas || []).forEach(p => {
        (p.itens || []).forEach(it => {
          totalDespachado += parseFloat(it.quantidade) || 0;
        });
        if (p.status === 'Concluída') {
          (p.itens || []).forEach(it => {
            totalEntregue += parseFloat(it.quantidade) || 0;
          });
        }
      });

      const cheiosNaoEntregues = Math.max(0, totalDespachado - totalEntregue);
      if (elRetSaiu) elRetSaiu.textContent = totalDespachado;
      if (elRetEntregue) elRetEntregue.textContent = totalEntregue;
      if (elRetVazios) elRetVazios.textContent = totalVazios;
      if (elRetCheiosRetorno) elRetCheiosRetorno.textContent = cheiosNaoEntregues;
      if (elRetJustificado) elRetJustificado.textContent = 0;
      if (elRetPendente) elRetPendente.textContent = cheiosNaoEntregues;
      if (elRetAvisoPendencia) {
        elRetAvisoPendencia.style.display = cheiosNaoEntregues > 0 ? 'block' : 'none';
      }
    } catch (err) {
      console.warn('Falha ao obter balanço de retorno:', err);
    }
  }

  btnAbrirConfRetorno?.addEventListener('click', carregarConferenciaRetorno);
  btnFecharConfRetorno?.addEventListener('click', () => fecharModalCampo(modalConfRetorno));

  btnSalvarConfRetorno?.addEventListener('click', async () => {
    if (!rotaPacote || !rotaPacote.entrega_id) return;

    const obs = document.getElementById('campo-ret-obs')?.value.trim();
    btnSalvarConfRetorno.disabled = true;
    btnSalvarConfRetorno.textContent = 'Registrando Retorno...';

    try {
      if (navigator.onLine) {
        const res = await fetch(`/logistica/api/entregas/${rotaPacote.entrega_id}/conferencia-retorno/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') || '',
            'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
            'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
          },
          body: JSON.stringify({ observacao: obs })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(JSON.stringify(data));

        fecharModalCampo(modalConfRetorno);
        playSuccessBeep();
        Swal.fire({
          icon: data.diferenca_pendente > 0 ? 'warning' : 'success',
          title: 'Conferência de Retorno Gravada!',
          text: data.diferenca_pendente > 0
            ? `Balanço finalizado com ${data.diferenca_pendente} pendência(s) registrada(s) no romaneio.`
            : 'Todos os cilindros e vasilhames foram conferidos em 100% de conformidade.'
        });
      } else {
        fecharModalCampo(modalConfRetorno);
        playSuccessBeep();
        Swal.fire('Salvo Offline', 'Conferência de retorno armazenada para sincronização ao restabelecer sinal.', 'info');
      }
    } catch (err) {
      playErrorBeep();
      Swal.fire('Erro', err.message || 'Falha ao registrar retorno da viagem.', 'error');
    } finally {
      btnSalvarConfRetorno.disabled = false;
      btnSalvarConfRetorno.textContent = '💾 Confirmar e Registrar Retorno de Viagem';
    }
  });

  // ==============================================================================
  // 15. REPORTAR OCORRÊNCIA / SINISTRO DE CAMPO (SPRINT L5)
  // ==============================================================================
  const btnAbrirSinistro = document.getElementById('btn-abrir-sinistro-campo');
  const modalSinistro = document.getElementById('modal-campo-sinistro');
  const btnFecharSinistro = document.getElementById('btn-fechar-sinistro-campo');
  const formSinistro = document.getElementById('form-campo-sinistro');
  const btnSalvarSinistro = document.getElementById('btn-salvar-sinistro-campo');
  const checkVitimas = document.getElementById('campo-sinistro-houve-vitimas');
  const bannerVitimas = document.getElementById('campo-sinistro-aviso-emergencia');

  // Abre modal e atualiza contexto (veículo, entrega, GPS)
  btnAbrirSinistro?.addEventListener('click', () => {
    abrirModalCampo(modalSinistro);

    // Contexto do veículo e entrega
    const vInfo = document.getElementById('campo-sinistro-veiculo-info');
    const inVeiculoId = document.getElementById('campo-sinistro-veiculo-id');
    const inEntregaId = document.getElementById('campo-sinistro-entrega-id');
    const inLat = document.getElementById('campo-sinistro-lat');
    const inLng = document.getElementById('campo-sinistro-lng');
    const localTexto = document.getElementById('campo-sinistro-local-texto');

    if (rotaPacote) {
      if (vInfo) vInfo.textContent = `${rotaPacote.veiculo_placa || ''} - ${rotaPacote.veiculo_modelo || 'Veículo da Rota'}`;
      if (inVeiculoId) inVeiculoId.value = rotaPacote.veiculo_id || '';
      if (inEntregaId) inEntregaId.value = rotaPacote.entrega_id || '';
    }

    // Coleta GPS atual em tempo real
    if (navigator.geolocation) {
      if (localTexto) localTexto.textContent = 'Obtendo coordenadas de GPS...';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (inLat) inLat.value = pos.coords.latitude;
          if (inLng) inLng.value = pos.coords.longitude;
          if (localTexto) {
            localTexto.textContent = `Lat: ${pos.coords.latitude.toFixed(6)}, Lng: ${pos.coords.longitude.toFixed(6)} (Precisão: ${Math.round(pos.coords.accuracy)}m)`;
          }
        },
        (err) => {
          console.warn('GPS indisponível no momento:', err);
          if (localTexto) localTexto.textContent = 'GPS não disponível no momento (será registrado sem coordenadas)';
        },
        { enableHighAccuracy: true, timeout: 8000 }
      );
    }
  });

  btnFecharSinistro?.addEventListener('click', () => {
    fecharModalCampo(modalSinistro);
  });

  // Destaque visual se houver vítimas
  checkVitimas?.addEventListener('change', (e) => {
    if (bannerVitimas) {
      if (e.target.checked) {
        bannerVitimas.style.background = '#b91c1c';
        bannerVitimas.style.boxShadow = '0 0 16px rgba(220, 38, 38, 0.8)';
        if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      } else {
        bannerVitimas.style.background = '#ef4444';
        bannerVitimas.style.boxShadow = '0 4px 10px rgba(239, 68, 68, 0.3)';
      }
    }
  });

  // Submissão do formulário de sinistro (Online / Offline idempotente com client_uuid)
  formSinistro?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const tipo = document.getElementById('campo-sinistro-tipo')?.value || 'Colisão';
    const descricao = document.getElementById('campo-sinistro-descricao')?.value.trim();
    const houveVitimas = !!checkVitimas?.checked;
    const bo = document.getElementById('campo-sinistro-bo')?.value.trim();
    const vId = document.getElementById('campo-sinistro-veiculo-id')?.value || (rotaPacote ? rotaPacote.veiculo_id : null);
    const eId = document.getElementById('campo-sinistro-entrega-id')?.value || (rotaPacote ? rotaPacote.entrega_id : null);
    const lat = document.getElementById('campo-sinistro-lat')?.value || null;
    const lng = document.getElementById('campo-sinistro-lng')?.value || null;
    const fotoInput = document.getElementById('campo-sinistro-foto');

    if (!descricao || descricao.length < 5) {
      Swal.fire('Atenção', 'Descreva o que ocorreu com pelo menos 5 caracteres.', 'warning');
      return;
    }

    const clientUuid = crypto.randomUUID ? crypto.randomUUID() : ('campo-sin-' + Date.now() + '-' + Math.random().toString(36).substring(2, 9));

    btnSalvarSinistro.disabled = true;
    btnSalvarSinistro.textContent = 'Transmitindo Ocorrência...';

    // Se houver arquivo selecionado, lê base64 para contingência offline
    let fotoBase64 = null;
    let fotoNome = null;
    if (fotoInput && fotoInput.files && fotoInput.files[0]) {
      const file = fotoInput.files[0];
      fotoNome = file.name;
      try {
        fotoBase64 = await new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => resolve(null);
          reader.readAsDataURL(file);
        });
      } catch (fErr) {
        console.warn('Falha ao codificar imagem:', fErr);
      }
    }

    try {
      if (navigator.onLine) {
        const formData = new FormData();
        formData.append('client_uuid', clientUuid);
        formData.append('tipo', tipo);
        formData.append('descricao', descricao);
        formData.append('houve_vitimas', houveVitimas ? 'true' : 'false');
        if (bo) formData.append('boletim_ocorrencia_numero', bo);
        if (vId) formData.append('veiculo', vId);
        if (eId) formData.append('entrega', eId);
        if (lat) formData.append('latitude', lat);
        if (lng) formData.append('longitude', lng);
        formData.append('status', 'Rascunho');
        if (fotoInput && fotoInput.files && fotoInput.files[0]) {
          formData.append('foto', fotoInput.files[0]);
        }

        const res = await fetch('/logistica/api/sinistros/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken') || '',
            'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
            'X-Tenant-ID': (document.querySelector('meta[name="current-tenant-id"]')?.content || '')
          },
          credentials: 'same-origin',
          body: formData
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.erro ? data.erro.join(', ') : JSON.stringify(data));
        }

        fecharModalCampo(modalSinistro);
        formSinistro.reset();
        playSuccessBeep();

        Swal.fire({
          icon: 'success',
          title: 'Ocorrência Registrada!',
          text: `Ocorrência #${data.numero || data.id} enviada com sucesso em Rascunho. A equipe de gestão e frotas foi notificada.`,
          confirmButtonText: 'Entendido'
        });
      } else {
        // Enfileira offline no IndexedDB
        if (window.GasAppOffline) {
          await window.GasAppOffline.enfileirarSinistro({
            client_uuid: clientUuid,
            veiculo_id: vId,
            entrega_id: eId,
            tipo: tipo,
            descricao: descricao,
            houve_vitimas: houveVitimas,
            boletim_ocorrencia_numero: bo,
            latitude: lat,
            longitude: lng,
            foto_base64: fotoBase64,
            foto_nome: fotoNome,
            data_hora: new Date().toISOString()
          });
        }

        fecharModalCampo(modalSinistro);
        formSinistro.reset();
        playSuccessBeep();

        Swal.fire({
          icon: 'info',
          title: 'Ocorrência Salva Offline',
          text: 'Você está sem conexão de internet. Os dados e fotos foram gravados com segurança neste dispositivo e serão transmitidos assim que restabelecer o sinal.',
          confirmButtonText: 'Entendido'
        });
      }
    } catch (err) {
      console.warn('Erro ao transmitir sinistro, gravando na fila offline:', err);
      if (window.GasAppOffline) {
        await window.GasAppOffline.enfileirarSinistro({
          client_uuid: clientUuid,
          veiculo_id: vId,
          entrega_id: eId,
          tipo: tipo,
          descricao: descricao,
          houve_vitimas: houveVitimas,
          boletim_ocorrencia_numero: bo,
          latitude: lat,
          longitude: lng,
          foto_base64: fotoBase64,
          foto_nome: fotoNome,
          data_hora: new Date().toISOString()
        });
      }

      fecharModalCampo(modalSinistro);
      formSinistro.reset();
      Swal.fire({
        icon: 'info',
        title: 'Gravado na Fila Offline',
        text: 'Instabilidade de conexão detectada. A ocorrência foi armazenada e sincronizará automaticamente.',
        confirmButtonText: 'OK'
      });
    } finally {
      btnSalvarSinistro.disabled = false;
      btnSalvarSinistro.textContent = '🚨 Transmitir Ocorrência para a Gestão';
    }
  });

  // Inicializa upload touch de fotos e garante todos os modais fechados
  configurarUploadCameraTouch();
  [
    modalAssinatura,
    modalAbastCampo,
    modalChecklistCampo,
    modalDefeitoCampo,
    modalConfSaida,
    modalConfRetorno,
    modalSinistro
  ].forEach(m => {
    if (m) fecharModalCampo(m);
  });

  // Inicializa dados ao abrir a tela
  await carregarPacoteInicial();
  atualizarBannerRede();
});

