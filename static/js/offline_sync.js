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
    this.DB_VERSION = 9;
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
      const openWithVersion = (version) => {
        const request = (typeof version === 'number' && version > 0)
          ? indexedDB.open(this._dbName, version)
          : indexedDB.open(this._dbName);

        request.onupgradeneeded = (event) => {
          const db = event.target.result;
          const oldVersion = event.oldVersion;

          if (!db.objectStoreNames.contains(this.STORE_NAME)) {
            const store = db.createObjectStore(this.STORE_NAME, { keyPath: 'client_uuid' });
            store.createIndex('criado_em', 'criado_em', { unique: false });
            store.createIndex('status_local', 'status_local', { unique: false });
            store.createIndex('tipo', 'tipo', { unique: false });
          }
          if (!db.objectStoreNames.contains('rota_pacote')) {
            db.createObjectStore('rota_pacote', { keyPath: 'key' });
          }
          if (!db.objectStoreNames.contains('abastecimentos_queue')) {
            const abastStore = db.createObjectStore('abastecimentos_queue', { keyPath: 'client_uuid' });
            abastStore.createIndex('criado_em', 'criado_em', { unique: false });
            abastStore.createIndex('status_local', 'status_local', { unique: false });
          }
          if (!db.objectStoreNames.contains('checklists_queue')) {
            const chkStore = db.createObjectStore('checklists_queue', { keyPath: 'client_uuid' });
            chkStore.createIndex('criado_em', 'criado_em', { unique: false });
          }
          if (!db.objectStoreNames.contains('defeitos_queue')) {
            const defStore = db.createObjectStore('defeitos_queue', { keyPath: 'client_uuid' });
            defStore.createIndex('criado_em', 'criado_em', { unique: false });
          }
          if (!db.objectStoreNames.contains('sinistros_queue')) {
            const sinStore = db.createObjectStore('sinistros_queue', { keyPath: 'client_uuid' });
            sinStore.createIndex('criado_em', 'criado_em', { unique: false });
          }
          if (!db.objectStoreNames.contains('gps_tracking_queue')) {
            const gpsStore = db.createObjectStore('gps_tracking_queue', { keyPath: 'client_uuid' });
            gpsStore.createIndex('timestamp', 'timestamp', { unique: false });
            gpsStore.createIndex('entrega_id', 'entrega_id', { unique: false });
            gpsStore.createIndex('sequencia', 'sequencia', { unique: false });
          }

          // [CORREÇÃO F-40] Versão 8: Fila local despesas_pendentes no IndexedDB (Sprint 9C)
          if (oldVersion < 8) {
            if (!db.objectStoreNames.contains('despesas_pendentes')) {
              const despStore = db.createObjectStore('despesas_pendentes', { keyPath: 'client_uuid' });
              despStore.createIndex('criado_em', 'criado_em', { unique: false });
              despStore.createIndex('status_local', 'status_local', { unique: false });
              despStore.createIndex('tipo', 'tipo', { unique: false });
            }
          }

          // [CORREÇÃO F-40] Versão 9: Migração encadeada para gps_tracking_queue (Sprint 12A)
          if (oldVersion < 9) {
            if (!db.objectStoreNames.contains('gps_tracking_queue')) {
              const gpsStore = db.createObjectStore('gps_tracking_queue', { keyPath: 'client_uuid' });
              gpsStore.createIndex('timestamp', 'timestamp', { unique: false });
              gpsStore.createIndex('entrega_id', 'entrega_id', { unique: false });
              gpsStore.createIndex('sequencia', 'sequencia', { unique: false });
            }
          }
        };

        request.onsuccess = (event) => {
          this.db = event.target.result;
          this.updateBadge();
          resolve(this.db);
        };

        request.onerror = (event) => {
          const err = event.target.error;
          // Autocorreção Segura contra VersionError (SEM apagar dados pendentes)
          if (err && err.name === 'VersionError' && version !== null) {
            console.warn('[IndexedDB] VersionError detectado. Tentando abrir na versão mais alta existente no dispositivo...', err);
            openWithVersion(null);
            return;
          }
          console.error('[IndexedDB] Erro ao abrir banco local isolado:', err);
          reject(err);
        };
      };

      openWithVersion(this.DB_VERSION);
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

      // Sincroniza também abastecimentos, checklists e relatos de defeito offline pendentes
      await this.sincronizarAbastecimentos();
      await this.sincronizarChecklists();
      await this.sincronizarDefeitos();
    } catch (err) {
      console.error('[PWA Sync] Falha ao enviar lote de sincronização:', err);
    } finally {
      this.isSyncing = false;
      this.updateBadge();
    }
  }

  /**
   * Adiciona um registro de abastecimento à fila offline local com client_uuid exclusivo
   */
  async enfileirarAbastecimento(dados) {
    const db = await this.getDB();
    const item = {
      client_uuid: dados.client_uuid || (crypto.randomUUID ? crypto.randomUUID() : this._gerarUUID()),
      status_local: 'PENDENTE',
      motivo_rejeicao: null,
      veiculo_id: dados.veiculo_id,
      tipo_combustivel: dados.tipo_combustivel,
      odometro_km: dados.odometro_km,
      litros: dados.litros,
      valor_litro: dados.valor_litro,
      valor_total: dados.valor_total,
      tanque_cheio: dados.tanque_cheio !== undefined ? dados.tanque_cheio : true,
      posto_nome: dados.posto_nome || '',
      posto_cidade: dados.posto_cidade || '',
      posto_uf: dados.posto_uf || '',
      forma_pagamento: dados.forma_pagamento || 'Cartão frota',
      numero_cupom: dados.numero_cupom || '',
      observacoes: dados.observacoes || '',
      origem: 'PWA',
      data_hora: dados.data_hora || new Date().toISOString(),
      criado_em: new Date().toISOString()
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction(['abastecimentos_queue'], 'readwrite');
      const store = tx.objectStore('abastecimentos_queue');
      const req = store.put(item);
      req.onsuccess = () => {
        console.log('[IndexedDB] Abastecimento salvo na fila offline:', item.client_uuid);
        this.updateBadge();
        if (navigator.onLine) {
          this.sincronizarAbastecimentos();
        }
        resolve(item);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async listarAbastecimentosPendentes() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['abastecimentos_queue'], 'readonly');
      const store = tx.objectStore('abastecimentos_queue');
      const req = store.getAll();
      req.onsuccess = () => resolve((req.result || []).filter(i => i.status_local !== 'REJEITADO'));
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async removerAbastecimento(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['abastecimentos_queue'], 'readwrite');
      const store = tx.objectStore('abastecimentos_queue');
      const req = store.delete(clientUuid);
      req.onsuccess = () => {
        this.updateBadge();
        resolve();
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async sincronizarAbastecimentos() {
    if (!navigator.onLine) return;
    const pendentes = await this.listarAbastecimentosPendentes();
    if (pendentes.length === 0) return;

    console.log(`[PWA Sync] Sincronizando ${pendentes.length} abastecimentos offline...`);
    const token = localStorage.getItem('access_token');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': this._getCSRFToken(),
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    if (metaTenant && metaTenant.content) headers['X-Tenant-ID'] = metaTenant.content;

    for (const abast of pendentes) {
      try {
        const payload = {
          client_uuid: abast.client_uuid,
          veiculo: abast.veiculo_id,
          tipo_combustivel: abast.tipo_combustivel,
          odometro_km: abast.odometro_km,
          litros: abast.litros,
          valor_litro: abast.valor_litro,
          valor_total: abast.valor_total,
          tanque_cheio: abast.tanque_cheio,
          posto_nome: abast.posto_nome,
          posto_cidade: abast.posto_cidade,
          posto_uf: abast.posto_uf,
          forma_pagamento: abast.forma_pagamento,
          numero_cupom: abast.numero_cupom,
          observacoes: abast.observacoes,
          data_hora: abast.data_hora,
          origem: 'PWA'
        };

        const res = await fetch('/logistica/api/abastecimentos/', {
          method: 'POST',
          headers,
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        });

        if (res.ok || res.status === 201 || res.status === 200) {
          await this.removerAbastecimento(abast.client_uuid);
          this._mostrarNotificacao(`⛽ Abastecimento transmitido com sucesso (${abast.litros} L)`, 'sucesso');
        }
      } catch (err) {
        console.warn('[PWA Sync] Falha de rede ao transmitir abastecimento:', err);
      }
    }
  }

  /**
   * Checklist offline: enfileiramento e sincronização
   */
  async enfileirarChecklist(dados) {
    const db = await this.getDB();
    const item = {
      client_uuid: dados.client_uuid || (crypto.randomUUID ? crypto.randomUUID() : this._gerarUUID()),
      status_local: 'PENDENTE',
      veiculo_id: dados.veiculo_id,
      odometro: dados.odometro,
      respostas_itens: dados.respostas_itens,
      observacoes: dados.observacoes || '',
      data_hora: dados.data_hora || new Date().toISOString(),
      criado_em: new Date().toISOString()
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction(['checklists_queue'], 'readwrite');
      const store = tx.objectStore('checklists_queue');
      const req = store.put(item);
      req.onsuccess = () => {
        console.log('[IndexedDB] Checklist salvo na fila offline:', item.client_uuid);
        this.updateBadge();
        if (navigator.onLine) {
          this.sincronizarChecklists();
        }
        resolve(item);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async listarChecklistsPendentes() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['checklists_queue'], 'readonly');
      const store = tx.objectStore('checklists_queue');
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async removerChecklist(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['checklists_queue'], 'readwrite');
      const store = tx.objectStore('checklists_queue');
      const req = store.delete(clientUuid);
      req.onsuccess = () => {
        this.updateBadge();
        resolve();
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async sincronizarChecklists() {
    if (!navigator.onLine) return;
    const pendentes = await this.listarChecklistsPendentes();
    if (pendentes.length === 0) return;

    console.log(`[PWA Sync] Sincronizando ${pendentes.length} checklists offline...`);
    const token = localStorage.getItem('access_token');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': this._getCSRFToken(),
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    if (metaTenant && metaTenant.content) headers['X-Tenant-ID'] = metaTenant.content;

    for (const chk of pendentes) {
      try {
        const payload = {
          client_uuid: chk.client_uuid,
          veiculo: chk.veiculo_id,
          odometro: chk.odometro,
          respostas_itens: chk.respostas_itens,
          observacoes: chk.observacoes,
          data_hora: chk.data_hora
        };

        const res = await fetch('/logistica/api/checklists/', {
          method: 'POST',
          headers,
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        });

        if (res.ok || res.status === 201 || res.status === 200) {
          await this.removerChecklist(chk.client_uuid);
          this._mostrarNotificacao(`📋 Checklist sincronizado com sucesso`, 'sucesso');
        }
      } catch (err) {
        console.warn('[PWA Sync] Falha ao transmitir checklist offline:', err);
      }
    }
  }

  /**
   * Defeitos / Relato de falha offline: enfileiramento e sincronização
   */
  async enfileirarDefeito(dados) {
    const db = await this.getDB();
    const item = {
      client_uuid: dados.client_uuid || (crypto.randomUUID ? crypto.randomUUID() : this._gerarUUID()),
      status_local: 'PENDENTE',
      veiculo_id: dados.veiculo_id,
      odometro_entrada: dados.odometro_entrada,
      descricao_problema: dados.descricao_problema,
      prioridade: dados.prioridade || 'Normal',
      imobiliza_veiculo: !!dados.imobiliza_veiculo,
      tipo: 'Corretiva',
      origem: 'Motorista',
      criado_em: new Date().toISOString()
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction(['defeitos_queue'], 'readwrite');
      const store = tx.objectStore('defeitos_queue');
      const req = store.put(item);
      req.onsuccess = () => {
        console.log('[IndexedDB] Defeito salvo na fila offline:', item.client_uuid);
        this.updateBadge();
        if (navigator.onLine) {
          this.sincronizarDefeitos();
        }
        resolve(item);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async listarDefeitosPendentes() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['defeitos_queue'], 'readonly');
      const store = tx.objectStore('defeitos_queue');
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async removerDefeito(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['defeitos_queue'], 'readwrite');
      const store = tx.objectStore('defeitos_queue');
      const req = store.delete(clientUuid);
      req.onsuccess = () => {
        this.updateBadge();
        resolve();
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async sincronizarDefeitos() {
    if (!navigator.onLine) return;
    const pendentes = await this.listarDefeitosPendentes();
    if (pendentes.length === 0) return;

    console.log(`[PWA Sync] Sincronizando ${pendentes.length} relatos de defeito offline...`);
    const token = localStorage.getItem('access_token');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': this._getCSRFToken(),
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    if (metaTenant && metaTenant.content) headers['X-Tenant-ID'] = metaTenant.content;

    for (const def of pendentes) {
      try {
        const payload = {
          client_uuid: def.client_uuid,
          veiculo: def.veiculo_id,
          odometro_entrada: def.odometro_entrada,
          descricao_problema: def.descricao_problema,
          prioridade: def.prioridade,
          imobiliza_veiculo: def.imobiliza_veiculo,
          tipo: 'Corretiva',
          origem: 'Motorista'
        };

        const res = await fetch('/logistica/api/ordens-servico/', {
          method: 'POST',
          headers,
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        });

        if (res.ok || res.status === 201 || res.status === 200) {
          await this.removerDefeito(def.client_uuid);
          this._mostrarNotificacao(`⚠️ Relato de defeito transmitido (OS gerada)`, 'sucesso');
        }
      } catch (err) {
        console.warn('[PWA Sync] Falha ao transmitir relato de defeito offline:', err);
      }
    }
  }

  /**
   * Sinistros / Ocorrências de campo offline (Sprint L5): enfileiramento e sincronização idempotente
   */
  async enfileirarSinistro(dados) {
    const db = await this.getDB();
    const item = {
      client_uuid: dados.client_uuid || (crypto.randomUUID ? crypto.randomUUID() : this._gerarUUID()),
      status_local: 'PENDENTE',
      veiculo_id: dados.veiculo_id || null,
      entrega_id: dados.entrega_id || null,
      tipo: dados.tipo || 'Colisão',
      descricao: dados.descricao || '',
      houve_vitimas: !!dados.houve_vitimas,
      boletim_ocorrencia_numero: dados.boletim_ocorrencia_numero || '',
      latitude: dados.latitude || null,
      longitude: dados.longitude || null,
      endereco: dados.endereco || '',
      data_hora: dados.data_hora || new Date().toISOString(),
      status: 'Rascunho',
      foto_base64: dados.foto_base64 || null,
      foto_nome: dados.foto_nome || null,
      criado_em: new Date().toISOString()
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction(['sinistros_queue'], 'readwrite');
      const store = tx.objectStore('sinistros_queue');
      const req = store.put(item);
      req.onsuccess = () => {
        console.log('[IndexedDB] Ocorrência/Sinistro salvo na fila offline:', item.client_uuid);
        this.updateBadge();
        if (navigator.onLine) {
          this.sincronizarSinistros();
        }
        resolve(item);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async listarSinistrosPendentes() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['sinistros_queue'], 'readonly');
      const store = tx.objectStore('sinistros_queue');
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async removerSinistro(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['sinistros_queue'], 'readwrite');
      const store = tx.objectStore('sinistros_queue');
      const req = store.delete(clientUuid);
      req.onsuccess = () => {
        this.updateBadge();
        resolve();
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async sincronizarSinistros() {
    if (!navigator.onLine) return;
    const pendentes = await this.listarSinistrosPendentes();
    if (pendentes.length === 0) return;

    console.log(`[PWA Sync] Sincronizando ${pendentes.length} ocorrências/sinistros offline...`);
    const token = localStorage.getItem('access_token');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': this._getCSRFToken(),
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    if (metaTenant && metaTenant.content) headers['X-Tenant-ID'] = metaTenant.content;

    for (const sin of pendentes) {
      try {
        const payload = {
          client_uuid: sin.client_uuid,
          veiculo: sin.veiculo_id,
          entrega: sin.entrega_id,
          tipo: sin.tipo,
          descricao: sin.descricao,
          houve_vitimas: sin.houve_vitimas,
          boletim_ocorrencia_numero: sin.boletim_ocorrencia_numero,
          latitude: sin.latitude,
          longitude: sin.longitude,
          endereco: sin.endereco,
          data_hora: sin.data_hora,
          status: 'Rascunho'
        };

        const res = await fetch('/logistica/api/sinistros/', {
          method: 'POST',
          headers,
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        });

        if (res.ok || res.status === 201 || res.status === 200) {
          const dadosCriado = await res.json();
          if (sin.foto_base64 && dadosCriado.id) {
            try {
              await fetch(`/logistica/api/sinistros/${dadosCriado.id}/adicionar-anexo/`, {
                method: 'POST',
                headers,
                credentials: 'same-origin',
                body: JSON.stringify({
                  tipo: 'Foto Local',
                  descricao: sin.foto_nome || 'Foto Ocorrência Campo',
                  arquivo_base64: sin.foto_base64
                })
              });
            } catch (anexoErr) {
              console.warn('[PWA Sync] Falha ao enviar foto da ocorrência:', anexoErr);
            }
          }
          await this.removerSinistro(sin.client_uuid);
          this._mostrarNotificacao(`🛡️ Ocorrência (${sin.tipo}) transmitida à gestão`, 'sucesso');
        }
      } catch (err) {
        console.warn('[PWA Sync] Falha ao sincronizar ocorrência/sinistro offline:', err);
      }
    }
  }

  /**
   * Enfileira coordenada GPS capturada para a entrega ativa
   */
  async enfileirarCoordenadaGPS(dados) {
    const db = await this.getDB();
    const item = {
      lat: dados.lat,
      lng: dados.lng,
      timestamp: dados.timestamp || new Date().toISOString(),
      entrega_id: dados.entrega_id
    };
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['gps_tracking_queue'], 'readwrite');
      const store = tx.objectStore('gps_tracking_queue');
      const req = store.add(item);
      req.onsuccess = () => resolve(req.result);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async listarCoordenadasGPS() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['gps_tracking_queue'], 'readonly');
      const store = tx.objectStore('gps_tracking_queue');
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async limparCoordenadasGPS() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['gps_tracking_queue'], 'readwrite');
      const store = tx.objectStore('gps_tracking_queue');
      const req = store.clear();
      req.onsuccess = () => resolve();
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async sincronizarTrackingGPS() {
    if (!navigator.onLine) return;
    const coordenadas = await this.listarCoordenadasGPS();
    if (coordenadas.length === 0) return;

    const token = localStorage.getItem('access_token');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': this._getCSRFToken(),
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    if (metaTenant && metaTenant.content) headers['X-Tenant-ID'] = metaTenant.content;

    try {
      const res = await fetch('/logistica/api/tracking/sync/', {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({ coordenadas })
      });

      if (res.ok || res.status === 200) {
        await this.limparCoordenadasGPS();
        console.log(`[PWA Sync] ${coordenadas.length} coordenadas GPS sincronizadas com sucesso.`);
      }
    } catch (err) {
      console.warn('[PWA Sync] Falha ao enviar coordenadas GPS:', err);
    }
  }

  /**
   * [Sprint 9C] Fila offline local de despesas de campo (abastecimento, pedágio, manutenção, outro)
   */
  async enfileirarDespesaCampo(dados) {
    const db = await this.getDB();
    const item = {
      client_uuid: dados.client_uuid || (crypto.randomUUID ? crypto.randomUUID() : this._gerarUUID()),
      status_local: 'PENDENTE',
      motivo_rejeicao: null,
      tipo: dados.tipo || 'OUTRO',
      veiculo_id: dados.veiculo_id,
      motorista_id: dados.motorista_id || this._userId,
      entrega_id: dados.entrega_id || null,
      data_hora: dados.data_hora || new Date().toISOString(),
      odometro_informado: dados.odometro_informado !== undefined ? dados.odometro_informado : null,
      litros: dados.litros !== undefined ? dados.litros : null,
      valor_informado: dados.valor_informado,
      forma_pagamento: dados.forma_pagamento || 'CARTAO_FROTA',
      posto_nome: dados.posto_nome || '',
      posto_cnpj: dados.posto_cnpj || '',
      latitude: dados.latitude || null,
      longitude: dados.longitude || null,
      foto_cupom_base64: dados.foto_cupom_base64 || null,
      tentativas: 0,
      criado_em: new Date().toISOString()
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction(['despesas_pendentes'], 'readwrite');
      const store = tx.objectStore('despesas_pendentes');
      const req = store.put(item);
      req.onsuccess = () => {
        console.log('[IndexedDB] Despesa de campo enfileirada:', item.client_uuid);
        this.updateBadge();
        if (navigator.onLine) {
          this.sincronizarDespesasCampo();
        }
        resolve(item);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async listarDespesasPendentes() {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['despesas_pendentes'], 'readonly');
      const store = tx.objectStore('despesas_pendentes');
      const req = store.getAll();
      req.onsuccess = () => resolve((req.result || []).filter(i => i.status_local !== 'REJEITADO'));
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async removerDespesaCampo(clientUuid) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['despesas_pendentes'], 'readwrite');
      const store = tx.objectStore('despesas_pendentes');
      const req = store.delete(clientUuid);
      req.onsuccess = () => {
        this.updateBadge();
        resolve();
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async marcarDespesaRejeitada(clientUuid, motivo) {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['despesas_pendentes'], 'readwrite');
      const store = tx.objectStore('despesas_pendentes');
      const getReq = store.get(clientUuid);
      getReq.onsuccess = () => {
        const item = getReq.result;
        if (item) {
          item.status_local = 'REJEITADO';
          item.motivo_rejeicao = motivo;
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
   * Sincroniza fila de despesas de campo com o servidor.
   * Em caso de conflito, o servidor vence em dados já aprovados ou consolidados.
   */
  async sincronizarDespesasCampo() {
    if (!navigator.onLine) return;
    const pendentes = await this.listarDespesasPendentes();
    if (pendentes.length === 0) return;

    console.log(`[PWA Sync] Sincronizando ${pendentes.length} despesas de campo offline...`);
    const token = localStorage.getItem('access_token');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': this._getCSRFToken(),
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    if (metaTenant && metaTenant.content) headers['X-Tenant-ID'] = metaTenant.content;

    try {
      const res = await fetch('/financeiro/api/despesas-campo/sincronizar/', {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({ itens: pendentes })
      });

      if (res.ok || res.status === 200 || res.status === 201) {
        const data = await res.json();
        const resultados = data.resultados || [];
        let sucessos = 0;
        let rejeicoes = 0;

        for (const r of resultados) {
          if (r.status === 'APROVADO' || r.status === 'PENDENTE_CONFERENCIA' || r.status === 'ja_processado' || r.sucesso) {
            await this.removerDespesaCampo(r.client_uuid);
            sucessos++;
          } else if (r.status === 'REJEITADO' || r.erro) {
            await this.marcarDespesaRejeitada(r.client_uuid, r.erro || 'Rejeitado pelo servidor');
            rejeicoes++;
          }
        }

        if (sucessos > 0) {
          this._mostrarNotificacao(`⛽ ${sucessos} despesa(s) de campo sincronizada(s) com sucesso.`, 'sucesso');
        }
        if (rejeicoes > 0) {
          this._mostrarNotificacao(`⚠️ ${rejeicoes} despesa(s) com anomalia/rejeição no servidor.`, 'erro');
        }
      }
    } catch (err) {
      console.warn('[PWA Sync] Falha ao sincronizar despesas de campo:', err);
    }
  }

  /**
   * Enfileira ponto de rastreamento GPS na fila offline gps_tracking_queue (Sprint 12A - Tarefa 5).
   * Descarta pontos com precisão pior que 100 metros (LGPD e economia de banda).
   */
  async enfileirarCoordenadaGPS(ponto) {
    if (!ponto) return false;
    const precisao = parseFloat(ponto.precisao_m || ponto.accuracy || 0);
    if (precisao > 100.0) {
      console.warn(`[GPS Offline] Ponto descartado por baixa precisão (${precisao} m > 100 m)`);
      return false;
    }

    const db = await this.initDB();
    const item = {
      client_uuid: ponto.client_uuid || this._gerarUUID(),
      entrega_id: ponto.entrega_id,
      latitude: ponto.latitude || ponto.lat,
      longitude: ponto.longitude || ponto.lng,
      velocidade: ponto.velocidade || ponto.speed || null,
      precisao_m: precisao,
      sequencia: ponto.sequencia || Date.now(),
      capturado_em: ponto.capturado_em || ponto.timestamp || new Date().toISOString(),
      timestamp: ponto.timestamp || new Date().toISOString()
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction(['gps_tracking_queue'], 'readwrite');
      const store = tx.objectStore('gps_tracking_queue');
      const req = store.put(item);
      req.onsuccess = () => resolve(item);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Lista pontos de rastreamento GPS pendentes (até 200 por lote).
   */
  async listarCoordenadasGPSPendentes(limite = 200) {
    const db = await this.initDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['gps_tracking_queue'], 'readonly');
      const store = tx.objectStore('gps_tracking_queue');
      const req = store.openCursor();
      const itens = [];
      req.onsuccess = (e) => {
        const cursor = e.target.result;
        if (cursor && itens.length < limite) {
          itens.push(cursor.value);
          cursor.continue();
        } else {
          resolve(itens);
        }
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Remove pontos de rastreamento GPS sincronizados com sucesso.
   */
  async removerCoordenadasGPSSincronizadas(clientUuids) {
    if (!clientUuids || clientUuids.length === 0) return;
    const db = await this.initDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['gps_tracking_queue'], 'readwrite');
      const store = tx.objectStore('gps_tracking_queue');
      clientUuids.forEach(uuid => store.delete(uuid));
      tx.oncomplete = () => resolve(true);
      tx.onerror = (e) => reject(e.target.error);
    });
  }

  /**
   * Sincroniza fila de telemetria GPS offline com o servidor em lotes de até 200 pontos (Sprint 12A - Tarefa 5).
   */
  async sincronizarTrackingGPS() {
    if (!navigator.onLine) return;
    const pendentes = await this.listarCoordenadasGPSPendentes(200);
    if (!pendentes || pendentes.length === 0) return;

    console.log(`[PWA GPS Sync] Sincronizando lote de ${pendentes.length} pontos GPS...`);
    const token = localStorage.getItem('access_token');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': this._getCSRFToken(),
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const metaTenant = document.querySelector('meta[name="current-tenant-id"]');
    if (metaTenant && metaTenant.content) headers['X-Tenant-ID'] = metaTenant.content;

    try {
      const res = await fetch('/logistica/api/tracking/sync/', {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({ coordenadas: pendentes })
      });

      if (res.ok || res.status === 200) {
        const uuids = pendentes.map(p => p.client_uuid);
        await this.removerCoordenadasGPSSincronizadas(uuids);
        console.log(`[PWA GPS Sync] ${uuids.length} pontos GPS sincronizados com sucesso.`);
      }
    } catch (err) {
      console.warn('[PWA GPS Sync] Falha ao sincronizar telemetria GPS:', err);
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
  window.GasAppOffline.sincronizarChecklists();
  window.GasAppOffline.sincronizarDefeitos();
  window.GasAppOffline.sincronizarSinistros();
  window.GasAppOffline.sincronizarTrackingGPS();
  window.GasAppOffline.sincronizarDespesasCampo();
});

window.addEventListener('offline', () => {
  console.log('[PWA] Dispositivo desconectado da internet.');
  window.GasAppOffline.updateBadge();
});

// Sincronização periódica a cada 30 segundos se online
setInterval(() => {
  if (navigator.onLine) {
    window.GasAppOffline.sincronizarLote();
    window.GasAppOffline.sincronizarSinistros();
    window.GasAppOffline.sincronizarTrackingGPS();
    window.GasAppOffline.sincronizarDespesasCampo();
  }
}, 30000);
