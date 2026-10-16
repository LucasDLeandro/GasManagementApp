/**
 * GasApp Offline Synchronization Client (IndexedDB & Idempotent Batch Sync)
 * Conformidade com D3 (Isolamento por tenant_id + user_id) e D4 (Estado REJEITADO com intervenção).
 */

class GasAppOfflineQueue {
  constructor() {
    this.db = null;
    this.isSyncing = false;
    this._tenantId = null;
    this._userId = null;
    this._dbName = null;
    this.STORE_NAME = 'movimentacoes_queue';
    this.DB_VERSION = 2;
    this.initScope();
  }

  initScope() {
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    const metaUser = document.querySelector('meta[name="current-user-id"]');

    this._tenantId = (metaTenant && metaTenant.content) || window.__CURRENT_TENANT_ID__ || localStorage.getItem('current_tenant_id') || 'default';
    this._userId = (metaUser && metaUser.content) || window.__CURRENT_USER_ID__ || localStorage.getItem('current_user_id') || 'anon';
    this._dbName = `GasAppOfflineDB_t${this._tenantId}_u${this._userId}`;
  }

  initDB() {
    this.initScope();
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this._dbName, this.DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains(this.STORE_NAME)) {
          const store = db.createObjectStore(this.STORE_NAME, { keyPath: 'client_uuid' });
          store.createIndex('criado_em', 'criado_em', { unique: false });
          store.createIndex('status_local', 'status_local', { unique: false });
          store.createIndex('tipo', 'tipo', { unique: false });
        }
        if (!db.objectStoreNames.contains('rota_pacote')) {
          db.createObjectStore('rota_pacote', { keyPath: 'key' });
        }
      };

      request.onsuccess = (event) => {
        this.db = event.target.result;
        this.updateBadge();
        resolve(this.db);
      };

      request.onerror = (event) => {
        console.error('[IndexedDB] Erro ao abrir banco local isolado:', event.target.error);
        reject(event.target.error);
      };
    });
  }

  async getDB() {
    if (this.db) return this.db;
    return await this.initDB();
  }

  /**
   * Adiciona uma movimentação bipada à fila local com client_uuid exclusivo e status PENDENTE
   */
  async enfileirarMovimentacao(dados) {
    const db = await this.getDB();
    const item = {
      client_uuid: dados.client_uuid || (crypto.randomUUID ? crypto.randomUUID() : this._gerarUUID()),
      status_local: 'PENDENTE',
      motivo_rejeicao: null,
      rejeitado_em: null,
      tentativas: 0,
      tenant_id: this._tenantId,
      user_id: this._userId,
      tipo: dados.tipo || 'ENTREGA_CLIENTE',
      codigo_qr: dados.codigo_qr || '',
      cilindro_id: dados.cilindro_id || null,
      cliente_id: dados.cliente_id || null,
      entrega_id: dados.entrega_id || null,
      ocorrido_em: dados.ocorrido_em || new Date().toISOString(),
      observacao: dados.observacao || '',
      recebedor_nome: dados.recebedor_nome || null,
      recebedor_documento: dados.recebedor_documento || null,
      assinatura_base64: dados.assinatura_base64 || null,
      latitude: dados.latitude || null,
      longitude: dados.longitude || null,
      documento_fiscal_ref: dados.documento_fiscal_ref || null,
      criado_em: new Date().toISOString()
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction([this.STORE_NAME], 'readwrite');
      const store = tx.objectStore(this.STORE_NAME);
      const req = store.put(item);

      req.onsuccess = () => {
        console.log('[IndexedDB] Bipagem gravada na fila isolada:', item.client_uuid);
        this.updateBadge();
        if (navigator.onLine) {
          this.sincronizarLote();
        }
        resolve(item);
      };

      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Retorna apenas as movimentações com status PENDENTE (evita reenvio de itens rejeitados - D4)
   */
  async listarPendentes() {
    const todos = await this.listarTodos();
    return todos.filter((i) => i.status_local !== 'REJEITADO');
  }

  /**
   * Retorna todas as movimentações rejeitadas pelo servidor que exigem intervenção humana (D4)
   */
  async listarRejeitados() {
    const todos = await this.listarTodos();
    return todos.filter((i) => i.status_local === 'REJEITADO');
  }

  /**
   * Retorna todas as movimentações da store local
   */
  async listarTodos() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([this.STORE_NAME], 'readonly');
      const store = tx.objectStore(this.STORE_NAME);
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Marca um item local como REJEITADO com o motivo fornecido pelo backend (D4)
   */
  async marcarRejeitado(clientUuid, motivo) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([this.STORE_NAME], 'readwrite');
      const store = tx.objectStore(this.STORE_NAME);
      const getReq = store.get(clientUuid);

      getReq.onsuccess = () => {
        const item = getReq.result;
        if (item) {
          item.status_local = 'REJEITADO';
          item.motivo_rejeicao = motivo || 'Rejeitado pela validação do servidor';
          item.rejeitado_em = new Date().toISOString();
          item.tentativas = (item.tentativas || 0) + 1;
          const putReq = store.put(item);
          putReq.onsuccess = () => {
            this.updateBadge();
            resolve(item);
          };
          putReq.onerror = (e) => reject(e.target.error);
        } else {
          resolve(null);
        }
      };
      getReq.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Permite ao operador reaprovar um item rejeitado após intervenção humana para nova tentativa (D4)
   */
  async reaprovarItem(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([this.STORE_NAME], 'readwrite');
      const store = tx.objectStore(this.STORE_NAME);
      const getReq = store.get(clientUuid);

      getReq.onsuccess = () => {
        const item = getReq.result;
        if (item) {
          item.status_local = 'PENDENTE';
          item.motivo_rejeicao = null;
          const putReq = store.put(item);
          putReq.onsuccess = () => {
            this.updateBadge();
            if (navigator.onLine) {
              this.sincronizarLote();
            }
            resolve(item);
          };
          putReq.onerror = (e) => reject(e.target.error);
        } else {
          resolve(null);
        }
      };
      getReq.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Remove item sincronizado com sucesso ou descartado manualmente
   */
  async removerItem(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([this.STORE_NAME], 'readwrite');
      const store = tx.objectStore(this.STORE_NAME);
      const req = store.delete(clientUuid);
      req.onsuccess = () => {
        this.updateBadge();
        resolve();
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Limpa todos os dados da store local isolada
   */
  async limparFila() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([this.STORE_NAME], 'readwrite');
      const store = tx.objectStore(this.STORE_NAME);
      const req = store.clear();
      req.onsuccess = () => {
        this.updateBadge();
        resolve();
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Salva o Pacote da Rota para operação offline (Pre-flight Sync - D3)
   */
  async salvarPacoteRota(pacote) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['rota_pacote'], 'readwrite');
      const store = tx.objectStore('rota_pacote');
      const item = { key: 'pacote_atual', ...pacote, salvo_em: new Date().toISOString() };
      const req = store.put(item);
      req.onsuccess = () => {
        console.log('[IndexedDB] Pacote da Rota salvo com sucesso:', item);
        resolve(item);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Obtém o Pacote da Rota salvo localmente no IndexedDB
   */
  async obterPacoteRota() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['rota_pacote'], 'readonly');
      const store = tx.objectStore('rota_pacote');
      const req = store.get('pacote_atual');
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Limpa o Pacote da Rota local
   */
  async limparPacoteRota() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['rota_pacote'], 'readwrite');
      const store = tx.objectStore('rota_pacote');
      const req = store.delete('pacote_atual');
      req.onsuccess = () => resolve();
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Expurgo LGPD pós-sync (D8):
   * Remove imediatamente do IndexedDB dados sensíveis (imagem da assinatura e CPF)
   */
  async expurgarDadosSensiveis(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([this.STORE_NAME], 'readwrite');
      const store = tx.objectStore(this.STORE_NAME);
      const getReq = store.get(clientUuid);
      getReq.onsuccess = () => {
        const item = getReq.result;
        if (item) {
          delete item.assinatura_base64;
          delete item.recebedor_documento;
          const putReq = store.put(item);
          putReq.onsuccess = () => resolve(true);
          putReq.onerror = (e) => reject(e.target.error);
        } else {
          resolve(false);
        }
      };
      getReq.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Sincroniza apenas as movimentações PENDENTES com o endpoint em lote
   */
  async sincronizarLote() {
    if (!navigator.onLine || this.isSyncing) {
      return;
    }

    const pendentes = await this.listarPendentes();
    if (pendentes.length === 0) {
      this.updateBadge();
      return;
    }

    this.isSyncing = true;
    console.log(`[PWA Sync] Sincronizando ${pendentes.length} movimentações pendentes...`);

    try {
      let token = localStorage.getItem('access_token');
      const headers = {
        'Content-Type': 'application/json',
        'X-CSRFToken': this._getCSRFToken(),
      };
      if (token) headers['Authorization'] = 'Bearer ' + token;

      let response = await fetch('/api/movimentacoes/sync-offline/', {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({ itens: pendentes })
      });

      if (response.status === 401 && token) {
        localStorage.removeItem('access_token');
        delete headers['Authorization'];
        response = await fetch('/api/movimentacoes/sync-offline/', {
          method: 'POST',
          headers,
          credentials: 'same-origin',
          body: JSON.stringify({ itens: pendentes })
        });
      }

      if (!response.ok) {
        console.warn('[PWA Sync] Servidor retornou status de erro:', response.status);
        const erroJson = await response.json().catch(() => null);
        const msgErro = (erroJson && (erroJson.error || erroJson.detail)) || `Erro HTTP ${response.status}`;
        
        // Se for erro de validação (400), transiciona os itens enviados para REJEITADO (D4)
        if (response.status === 400) {
          for (const item of pendentes) {
            await this.marcarRejeitado(item.client_uuid, msgErro);
          }
          this._mostrarNotificacao(`Sincronização rejeitada: ${msgErro}. Verifique as pendências.`, 'erro');
        }
        this.isSyncing = false;
        this.updateBadge();
        return;
      }

      const data = await response.json();
      console.log('[PWA Sync] Resposta da sincronização em lote:', data);

      if (data && data.detalhes) {
        let removidos = 0;
        let rejeitados = 0;
        for (const item of data.detalhes) {
          if (item.status === 'sucesso' || item.status === 'ja_processado') {
            await this.removerItem(item.client_uuid);
            removidos++;
          } else if (item.status === 'erro' || item.status === 'rejeitado') {
            await this.marcarRejeitado(item.client_uuid, item.mensagem || item.erro || 'Erro retornado pela API');
            rejeitados++;
          }
        }
        if (removidos > 0) {
          this._mostrarNotificacao(`Sincronização concluída: ${removidos} movimentações registradas com sucesso.`, 'sucesso');
        }
        if (rejeitados > 0) {
          this._mostrarNotificacao(`Atenção: ${rejeitados} movimentação(ões) foram rejeitadas e exigem revisão.`, 'erro');
        }
      }
    } catch (err) {
      console.error('[PWA Sync] Falha ao enviar lote de sincronização:', err);
    } finally {
      this.isSyncing = false;
      this.updateBadge();
    }
  }

  /**
   * Atualiza indicadores visuais de pendências e rejeições na interface
   */
  async updateBadge() {
    let pendentes = [];
    let rejeitados = [];
    try {
      pendentes = await this.listarPendentes();
      rejeitados = await this.listarRejeitados();
    } catch {
      pendentes = [];
      rejeitados = [];
    }

    const countPendentes = pendentes.length;
    const countRejeitados = rejeitados.length;

    // Badges de itens pendentes
    const badgesPendentes = document.querySelectorAll('.offline-queue-badge');
    badgesPendentes.forEach((b) => {
      b.textContent = countPendentes;
      b.style.display = countPendentes > 0 ? 'inline-flex' : 'none';
    });

    // Badges de itens rejeitados (D4)
    const badgesRejeitados = document.querySelectorAll('.offline-rejected-badge');
    badgesRejeitados.forEach((b) => {
      b.textContent = countRejeitados;
      b.style.display = countRejeitados > 0 ? 'inline-flex' : 'none';
    });

    const indicator = document.getElementById('offline-sync-indicator');
    if (indicator) {
      if (countRejeitados > 0) {
        indicator.textContent = `Atenção: ${countRejeitados} rejeitado(s) / ${countPendentes} pendente(s)`;
        indicator.className = 'status-badge rejected';
        indicator.style.display = 'inline-flex';
        indicator.style.cursor = 'pointer';
        indicator.onclick = () => this.abrirModalPendencias();
      } else if (!navigator.onLine) {
        indicator.textContent = `Offline (${countPendentes} pendentes)`;
        indicator.className = 'status-badge offline';
        indicator.style.display = 'inline-flex';
      } else if (countPendentes > 0) {
        indicator.textContent = `Sincronizando (${countPendentes})...`;
        indicator.className = 'status-badge syncing';
        indicator.style.display = 'inline-flex';
      } else {
        indicator.textContent = 'Online';
        indicator.className = 'status-badge online';
        indicator.style.display = 'none';
      }
    }

    // Atualiza TopBar Connectivity Indicator (Fase 1)
    const topbarText = document.getElementById('topbar-sync-text');
    const topbarDot = document.getElementById('topbar-sync-dot');
    const topbarStatus = document.getElementById('topbar-sync-status');
    if (topbarText && topbarDot) {
      if (countRejeitados > 0) {
        topbarText.textContent = `${countRejeitados} Rejeitado(s)`;
        topbarDot.className = 'sync-status-dot offline';
        if (topbarStatus) {
          topbarStatus.style.cursor = 'pointer';
          topbarStatus.title = 'Clique para ver e resolver itens rejeitados na sincronização';
          topbarStatus.onclick = () => this.abrirModalPendencias();
        }
      } else if (!navigator.onLine) {
        topbarText.textContent = countPendentes > 0 ? `Offline (${countPendentes})` : 'Offline';
        topbarDot.className = 'sync-status-dot offline';
      } else if (countPendentes > 0) {
        topbarText.textContent = `Sincronizando (${countPendentes})`;
        topbarDot.className = 'sync-status-dot syncing';
      } else {
        topbarText.textContent = 'Online';
        topbarDot.className = 'sync-status-dot';
      }
    }
  }

  /**
   * Modal Interativo de Pendências e Rejeições de Sincronização (D4)
   */
  async abrirModalPendencias() {
    const rejeitados = await this.listarRejeitados();
    const pendentes = await this.listarPendentes();

    let existingModal = document.getElementById('modal-pendencias-sync');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.id = 'modal-pendencias-sync';
    modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(15,23,42,0.7);display:flex;align-items:center;justify-content:center;z-index:99999;backdrop-filter:blur(3px);';

    let htmlItensRejeitados = '';
    if (rejeitados.length === 0) {
      htmlItensRejeitados = '<p style="color:#64748B;font-size:14px;">Nenhuma bipagem rejeitada. Todas as sincronizações estão em conformidade.</p>';
    } else {
      htmlItensRejeitados = rejeitados.map(r => `
        <div style="background:#FFF1F2;border:1px solid #FECDD3;border-radius:8px;padding:12px;margin-bottom:10px;text-align:left;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong style="color:#BE123C;font-size:14px;">${r.tipo} - QR: ${r.codigo_qr || 'S/ QR'}</strong>
            <span style="font-size:11px;color:#9F1239;">${new Date(r.criado_em).toLocaleString('pt-BR')}</span>
          </div>
          <p style="margin:6px 0;font-size:13px;color:#881337;"><strong>Motivo da Rejeição:</strong> ${r.motivo_rejeicao}</p>
          <div style="display:flex;gap:8px;margin-top:8px;">
            <button onclick="window.GasAppOffline.reaprovarItem('${r.client_uuid}').then(() => window.GasAppOffline.abrirModalPendencias())" style="background:#0284C7;color:#fff;border:none;padding:6px 12px;border-radius:4px;font-size:12px;cursor:pointer;">Tentar Novamente</button>
            <button onclick="window.GasAppOffline.removerItem('${r.client_uuid}').then(() => window.GasAppOffline.abrirModalPendencias())" style="background:#E11D48;color:#fff;border:none;padding:6px 12px;border-radius:4px;font-size:12px;cursor:pointer;">Descartar</button>
          </div>
        </div>
      `).join('');
    }

    modal.innerHTML = `
      <div style="background:#fff;border-radius:12px;width:90%;max-width:600px;max-height:85vh;overflow-y:auto;padding:24px;box-shadow:0 20px 25px -5px rgba(0,0,0,0.3);">
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #E2E8F0;padding-bottom:12px;margin-bottom:16px;">
          <h3 style="margin:0;color:#0F172A;font-size:18px;">Pendências de Sincronização Offline</h3>
          <button onclick="document.getElementById('modal-pendencias-sync').remove()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#64748B;">&times;</button>
        </div>
        <div>
          <h4 style="color:#BE123C;margin:12px 0 8px 0;font-size:15px;">Itens Rejeitados pelo Servidor (${rejeitados.length})</h4>
          ${htmlItensRejeitados}
          <h4 style="color:#0284C7;margin:16px 0 8px 0;font-size:15px;">Fila Aguardando Conexão (${pendentes.length})</h4>
          <p style="font-size:13px;color:#64748B;">Estes itens serão transmitidos automaticamente assim que a conexão com o servidor estiver estável.</p>
        </div>
        <div style="text-align:right;margin-top:20px;">
          <button onclick="document.getElementById('modal-pendencias-sync').remove()" style="background:#475569;color:#fff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:14px;">Fechar</button>
        </div>
      </div>
    `;

    document.body.appendChild(modal);
  }

  _gerarUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  _getCSRFToken() {
    const cookie = document.cookie
      .split(';')
      .map((c) => c.trim())
      .find((c) => c.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
  }

  _mostrarNotificacao(texto, tipo = 'sucesso') {
    console.log('[PWA Toast]', texto);
    const container = document.getElementById('toast-container') || document.body;
    const toast = document.createElement('div');
    toast.className = `pwa-toast-notification ${tipo}`;
    const borderColor = tipo === 'erro' ? '#EF4444' : '#10B981';
    toast.style.cssText =
      `position: fixed; bottom: 20px; right: 20px; background: #0F172A; color: #fff; padding: 12px 20px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); z-index: 99999; font-size: 13px; font-weight: 500; border-left: 4px solid ${borderColor}; transition: opacity 0.3s ease;`;
    toast.textContent = texto;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 350);
    }, 4500);
  }
}

// Instancia singleton global
window.GasAppOffline = new GasAppOfflineQueue();

// Eventos de conectividade do navegador
window.addEventListener('online', () => {
  console.log('[PWA] Conexão restabelecida. Sincronizando fila...');
  window.GasAppOffline.updateBadge();
  window.GasAppOffline.sincronizarLote();
});

window.addEventListener('offline', () => {
  console.log('[PWA] Dispositivo desconectado da internet.');
  window.GasAppOffline.updateBadge();
});

// Sincronização periódica a cada 30 segundos se online
setInterval(() => {
  if (navigator.onLine) {
    window.GasAppOffline.sincronizarLote();
  }
}, 30000);
