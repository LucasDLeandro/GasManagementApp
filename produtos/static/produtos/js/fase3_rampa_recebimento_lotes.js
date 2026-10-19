/**
 * Baros - Fase 3 (IN 129/2022, RDC 887/2024, Qualidade & Recall)
 * - Estação de Rampa de Envase em Batelada (Manifold Batch Grid com áudio e teclado wedge)
 * - Central de Recebimento de Cilindros Cheios de Fornecedor (Distribuidoras)
 * - Central de Lotes, Homologação CQ e Quarentena Sanitária
 */

// Sintetizador de Áudio via Web Audio API (100% nativo, sem arquivos externos)
const AudioFeedback = {
    ctx: null,
    init() {
        if (!this.ctx && (window.AudioContext || window.webkitAudioContext)) {
            this.ctx = new (window.AudioContext || window.webkitAudioContext)();
        }
    },
    success() {
        try {
            this.init();
            if (!this.ctx) return;
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(880, this.ctx.currentTime); // A5
            osc.frequency.setValueAtTime(1320, this.ctx.currentTime + 0.08); // E6
            gain.gain.setValueAtTime(0.2, this.ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, this.ctx.currentTime + 0.22);
            osc.connect(gain);
            gain.connect(this.ctx.destination);
            osc.start();
            osc.stop(this.ctx.currentTime + 0.25);
        } catch (e) {
            console.warn("Audio feedback error:", e);
        }
    },
    error() {
        try {
            this.init();
            if (!this.ctx) return;
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(220, this.ctx.currentTime); // A3
            osc.frequency.setValueAtTime(164.81, this.ctx.currentTime + 0.12); // E3
            gain.gain.setValueAtTime(0.25, this.ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, this.ctx.currentTime + 0.35);
            osc.connect(gain);
            gain.connect(this.ctx.destination);
            osc.start();
            osc.stop(this.ctx.currentTime + 0.38);
        } catch (e) {
            console.warn("Audio feedback error:", e);
        }
    }
};

function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
}

function getAuthHeaders(includeJson = true) {
    const headers = {};
    if (includeJson) headers['Content-Type'] = 'application/json';
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRFToken'] = csrf;
    const token = localStorage.getItem('access_token');
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return headers;
}

// ==============================================================================
// 1. ESTAÇÃO DE RAMPA EM BATELADA (MANIFOLD BATCH GRID - IN 129/2022)
// ==============================================================================

const RampaEnvase = {
    lotes: [],
    loteSelecionado: null,
    cilindrosBatelada: [],

    async inicializar() {
        await this.carregarLotes();
        this.configurarLeitorWedge();
    },

    async carregarLotes() {
        try {
            const res = await fetch('/produtos/api/lotes/', { headers: getAuthHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            this.lotes = Array.isArray(data) ? data : (data.results || []);
            
            const sel = document.getElementById('rampa-select-lote');
            if (!sel) return;
            sel.innerHTML = '<option value="">-- Selecione o Lote de Envase --</option>';

            this.lotes.forEach(l => {
                const opt = document.createElement('option');
                opt.value = l.id;
                const statusBadge = l.status_qualidade === 'APROVADO' ? '✓ CQ OK' : `[${l.status_qualidade}]`;
                opt.textContent = `${l.codigo_lote} | ${l.gas_sigla} (${l.gas_nome}) - Val: ${l.data_validade} ${statusBadge}`;
                sel.appendChild(opt);
            });
        } catch (e) {
            console.error("Erro ao carregar lotes da rampa:", e);
        }
    },

    onLoteChange() {
        const sel = document.getElementById('rampa-select-lote');
        const loteId = parseInt(sel.value, 10);
        this.loteSelecionado = this.lotes.find(l => l.id === loteId) || null;

        const infoPill = document.getElementById('rampa-lote-info-pill');
        if (!this.loteSelecionado) {
            if (infoPill) infoPill.style.display = 'none';
            return;
        }

        if (infoPill) {
            infoPill.style.display = 'flex';
            const l = this.loteSelecionado;
            let statusColor = '#16a34a';
            if (l.status_qualidade === 'REPROVADO') statusColor = '#dc2626';
            else if (l.status_qualidade === 'QUARENTENA') statusColor = '#d97706';

            infoPill.innerHTML = `
                <span><strong>Gás:</strong> ${l.gas_sigla} (${l.gas_nome})</span>
                <span><strong>Pureza:</strong> ${l.pureza_percentual}%</span>
                <span><strong>Validade:</strong> ${l.data_validade}</span>
                <span><strong>RT:</strong> ${l.rt_nome_snapshot || l.responsavel_tecnico || 'N/A'}</span>
                <span style="color: ${statusColor}; font-weight: 700;">[${l.status_qualidade_display || l.status_qualidade}]</span>
            `;
        }
    },

    configurarLeitorWedge() {
        const input = document.getElementById('input-scanner-wedge');
        if (!input) return;

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const codigo = input.value.trim();
                if (codigo) {
                    this.biparCilindro(codigo);
                    input.value = '';
                }
            }
        });
    },

    async biparCilindro(codigo) {
        if (!this.loteSelecionado) {
            this.mostrarFeedback('Selecione primeiro o Lote de Envase no topo da rampa antes de bipar cilindros.', false);
            AudioFeedback.error();
            return;
        }

        // Verifica se já está na rampa atual
        const termo = codigo.toUpperCase();
        const jaAcoplado = this.cilindrosBatelada.some(c => 
            c.codigo_qr.toUpperCase() === termo || c.numero_serie_ogiva.toUpperCase() === termo
        );
        if (jaAcoplado) {
            this.mostrarFeedback(`Cilindro '${codigo}' já está acoplado na grade da rampa!`, false);
            AudioFeedback.error();
            return;
        }

        // Validação em tempo real no backend
        try {
            const res = await fetch('/produtos/api/envases/validar-cilindro/', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    termo: codigo,
                    lote_id: this.loteSelecionado.id
                })
            });

            const data = await res.json();

            if (!res.ok || !data.valido) {
                const motivo = data.motivo || data.error || 'Cilindro rejeitado na validação de rampa.';
                this.mostrarFeedback(motivo, false);
                AudioFeedback.error();
                this.pulseContainer('error');
                return;
            }

            // Aprovado na rampa
            const cil = data.cilindro;
            this.cilindrosBatelada.push({
                id: cil.id,
                codigo_qr: cil.codigo_qr,
                numero_serie_ogiva: cil.numero_serie_ogiva,
                modelo_descricao: cil.modelo_descricao,
                volume_litros: cil.volume_litros,
                gas_sigla: cil.gas_sigla,
                gas_nome: cil.gas_nome,
                gas_cor_padrao_abnt: cil.gas_cor_padrao_abnt,
                data_proximo_reteste: cil.data_proximo_reteste,
                status_display: cil.status_display,
                // Checklist Inicial conforme IN 129/2022 (padrão conforme ao acoplar)
                valvula_integra: true,
                pressao_residual_positiva: true,
                pintura_cor_padrao_ok: true,
                rotulo_identificacao_ok: true,
                observacoes_inspecao: ''
            });

            AudioFeedback.success();
            this.pulseContainer('success');
            this.mostrarFeedback(`Cilindro ${cil.numero_serie_ogiva} (${cil.codigo_qr}) validado e acoplado na rampa.`, true);
            this.renderizarGrid();
        } catch (e) {
            console.error("Erro na validação do cilindro:", e);
            this.mostrarFeedback("Falha na comunicação com o servidor ao validar cilindro.", false);
            AudioFeedback.error();
        }
    },

    pulseContainer(tipo) {
        const wrap = document.getElementById('wedge-scanner-card');
        if (!wrap) return;
        wrap.classList.remove('scan-pulse');
        void wrap.offsetWidth; // trigger reflow
        wrap.classList.add('scan-pulse');
    },

    mostrarFeedback(msg, sucesso) {
        const banner = document.getElementById('rampa-scan-feedback');
        if (!banner) return;
        banner.style.display = 'flex';
        banner.className = `alert-scan-feedback ${sucesso ? 'alert-scan-success' : 'alert-scan-error'}`;
        banner.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                ${sucesso ? '<polyline points="20 6 9 17 4 12"></polyline>' : '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>'}
            </svg>
            <span>${msg}</span>
        `;
    },

    marcarConformeTodos() {
        if (this.cilindrosBatelada.length === 0) return;
        this.cilindrosBatelada.forEach(c => {
            c.valvula_integra = true;
            c.pressao_residual_positiva = true;
            c.pintura_cor_padrao_ok = true;
            c.rotulo_identificacao_ok = true;
        });
        this.renderizarGrid();
        this.mostrarFeedback('Checklist IN 129/2022 marcado como CONFORME em todos os cilindros da rampa.', true);
    },

    atualizarChecklist(cilId, campo, valor) {
        const item = this.cilindrosBatelada.find(c => c.id === cilId);
        if (item) {
            item[campo] = valor;
            this.atualizarLinhaStatus(cilId);
        }
    },

    atualizarLinhaStatus(cilId) {
        const item = this.cilindrosBatelada.find(c => c.id === cilId);
        if (!item) return;
        const conforme = item.valvula_integra && item.pressao_residual_positiva && item.pintura_cor_padrao_ok && item.rotulo_identificacao_ok;
        const statusEl = document.getElementById(`status-badge-${cilId}`);
        if (statusEl) {
            statusEl.className = conforme ? 'badge-conforme' : 'badge-nao-conforme';
            statusEl.textContent = conforme ? 'CONFORME (IN 129)' : 'NÃO CONFORME';
        }
    },

    removerCilindro(cilId) {
        this.cilindrosBatelada = this.cilindrosBatelada.filter(c => c.id !== cilId);
        this.renderizarGrid();
    },

    limparRampa() {
        if (this.cilindrosBatelada.length === 0) return;
        if (!confirm('Deseja realmente limpar todos os cilindros da rampa atual?')) return;
        this.cilindrosBatelada = [];
        this.renderizarGrid();
        this.mostrarFeedback('Rampa limpa.', true);
    },

    renderizarGrid() {
        const tbody = document.getElementById('rampa-grid-tbody');
        const contador = document.getElementById('rampa-contador-cilindros');
        const btnConcluir = document.getElementById('btn-concluir-batelada');

        if (contador) contador.textContent = `Batelada: ${this.cilindrosBatelada.length} cilindro(s)`;

        if (!tbody) return;
        tbody.innerHTML = '';

        if (this.cilindrosBatelada.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align: center; color: var(--color-text-muted); padding: 35px;">
                        Nenhum cilindro acoplado na rampa. Bipe com o leitor de código de barras ou digite o QR Code acima.
                    </td>
                </tr>
            `;
            if (btnConcluir) btnConcluir.disabled = true;
            return;
        }

        if (btnConcluir) btnConcluir.disabled = false;

        this.cilindrosBatelada.forEach(c => {
            const tr = document.createElement('tr');
            const conforme = c.valvula_integra && c.pressao_residual_positiva && c.pintura_cor_padrao_ok && c.rotulo_identificacao_ok;

            tr.innerHTML = `
                <td>
                    <div class="font-mono" style="font-weight: 700; color: var(--color-text);">${c.numero_serie_ogiva}</div>
                    <div class="font-mono text-muted" style="font-size: 11px;">${c.codigo_qr}</div>
                </td>
                <td>
                    <div>${c.modelo_descricao || 'N/A'}</div>
                    <div style="font-size: 11px; color: var(--color-text-muted);">${c.volume_litros || '-'} Litros</div>
                </td>
                <td>
                    <span class="gas-icon-abnt" style="background-color: ${c.gas_cor_padrao_abnt || '#0284c7'}; color: #fff; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 11px;">
                        ${c.gas_sigla}
                    </span>
                    <span style="font-size: 11px; margin-left: 4px; color: var(--color-text);">${c.gas_nome}</span>
                </td>
                <td>
                    <span class="font-mono" style="font-size: 12px;">${c.data_proximo_reteste || 'N/A'}</span>
                </td>
                <td>
                    <div class="checklist-cell-group">
                        <label class="checklist-label">
                            <input type="checkbox" ${c.valvula_integra ? 'checked' : ''} onchange="RampaEnvase.atualizarChecklist(${c.id}, 'valvula_integra', this.checked)">
                            Válvula Íntegra
                        </label>
                        <label class="checklist-label">
                            <input type="checkbox" ${c.pressao_residual_positiva ? 'checked' : ''} onchange="RampaEnvase.atualizarChecklist(${c.id}, 'pressao_residual_positiva', this.checked)">
                            Pressão Residual Positiva
                        </label>
                        <label class="checklist-label">
                            <input type="checkbox" ${c.pintura_cor_padrao_ok ? 'checked' : ''} onchange="RampaEnvase.atualizarChecklist(${c.id}, 'pintura_cor_padrao_ok', this.checked)">
                            Pintura / Cor ABNT
                        </label>
                        <label class="checklist-label">
                            <input type="checkbox" ${c.rotulo_identificacao_ok ? 'checked' : ''} onchange="RampaEnvase.atualizarChecklist(${c.id}, 'rotulo_identificacao_ok', this.checked)">
                            Rótulo Regulamentar
                        </label>
                    </div>
                </td>
                <td>
                    <span id="status-badge-${c.id}" class="${conforme ? 'badge-conforme' : 'badge-nao-conforme'}">
                        ${conforme ? 'CONFORME (IN 129)' : 'NÃO CONFORME'}
                    </span>
                </td>
                <td style="text-align: right;">
                    <button type="button" class="btn-auth" style="padding: 4px 8px; font-size: 11px; background: rgba(239, 68, 68, 0.1); color: #dc2626; border: 1px solid rgba(239, 68, 68, 0.3); cursor: pointer;" onclick="RampaEnvase.removerCilindro(${c.id})">
                        Remover
                    </button>
                </td>
            `;

            tbody.appendChild(tr);
        });
    },

    async concluirBatelada() {
        if (!this.loteSelecionado) {
            alert("Selecione o Lote de Envase no topo da rampa.");
            return;
        }

        const pressaoInput = document.getElementById('rampa-pressao-final');
        const pressao = parseInt(pressaoInput ? pressaoInput.value : '200', 10);
        if (!pressao || pressao <= 0) {
            alert("Informe uma pressão final válida da rampa (ex: 200 bar).");
            return;
        }

        if (this.cilindrosBatelada.length === 0) {
            alert("A rampa está vazia. Bipe ao menos um cilindro.");
            return;
        }

        // Validação se há itens não conformes
        const naoConformes = this.cilindrosBatelada.filter(c => 
            !(c.valvula_integra && c.pressao_residual_positiva && c.pintura_cor_padrao_ok && c.rotulo_identificacao_ok)
        );

        if (naoConformes.length > 0) {
            alert(`Atenção: Existem ${naoConformes.length} cilindro(s) com não conformidades no Checklist IN 129. Remova-os da rampa ou corrija a inspeção antes de concluir a batelada.`);
            return;
        }

        if (!confirm(`Deseja concluir o envase atômico de ${this.cilindrosBatelada.length} cilindros a ${pressao} bar com o Lote ${this.loteSelecionado.codigo_lote}?`)) {
            return;
        }

        const btn = document.getElementById('btn-concluir-batelada');
        btn.disabled = true;
        btn.textContent = 'Gravando Batelada...';

        const payload = {
            lote_id: this.loteSelecionado.id,
            pressao_final_bar: pressao,
            itens: this.cilindrosBatelada.map(c => ({
                cilindro_id: c.id,
                valvula_integra: c.valvula_integra,
                pressao_residual_positiva: c.pressao_residual_positiva,
                pintura_cor_padrao_ok: c.pintura_cor_padrao_ok,
                rotulo_identificacao_ok: c.rotulo_identificacao_ok,
                observacoes_inspecao: c.observacoes_inspecao || ''
            }))
        };

        try {
            const res = await fetch('/produtos/api/envases/batelada/', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            });

            const data = await res.json();

            if (!res.ok) {
                alert(data.error || "Erro ao concluir batelada.");
                return;
            }

            AudioFeedback.success();
            alert(`Batelada Concluída com Sucesso! ${data.total_envasados} cilindros envasados com o Lote ${data.lote_codigo}.`);
            
            // Abre Modal de Etiquetas de Colarinho do Lote
            const envaseIds = (data.envases || []).map(e => e.id).join(',');
            this.cilindrosBatelada = [];
            this.renderizarGrid();
            
            if (envaseIds) {
                abrirModalEtiquetasColarinho(envaseIds);
            }
        } catch (e) {
            console.error("Erro ao concluir batelada:", e);
            alert("Falha na comunicação com o servidor ao registrar batelada.");
        } finally {
            btn.disabled = false;
            btn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                Concluir Batelada de Envase (Atômico)
            `;
        }
    }
};

// ==============================================================================
// 2. MODAL DE ETIQUETAS DE COLARINHO DO LOTE (ABNT NBR 12176 / IN 129/2022)
// ==============================================================================

async function abrirModalEtiquetasColarinho(envaseIds) {
    const dialog = document.getElementById('modal-etiquetas-colarinho');
    const container = document.getElementById('collar-tags-container');
    if (!dialog || !container) return;

    container.innerHTML = '<div style="padding: 20px; color: var(--color-text-muted);">Gerando etiquetas de colarinho regulamentares...</div>';
    dialog.showModal();

    try {
        const res = await fetch(`/produtos/api/envases/etiquetas-colarinho/?envase_ids=${encodeURIComponent(envaseIds)}`, {
            headers: getAuthHeaders()
        });

        if (!res.ok) {
            container.innerHTML = '<div style="color: #dc2626; padding: 20px;">Falha ao obter dados das etiquetas de colarinho.</div>';
            return;
        }

        const etiquetas = await res.json();
        container.innerHTML = '';

        if (!etiquetas || etiquetas.length === 0) {
            container.innerHTML = '<div style="padding: 20px;">Nenhuma etiqueta encontrada.</div>';
            return;
        }

        etiquetas.forEach(tag => {
            const card = document.createElement('div');
            card.className = 'collar-tag-preview';
            card.innerHTML = `
                <div class="collar-tag-header">
                    ${tag.empresa_nome.toUpperCase()}
                </div>
                <div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 12px; border-bottom: 1px solid #0f172a; padding-bottom: 2px;">
                    <span>${tag.gas_nome.toUpperCase()}</span>
                    <span>${tag.gas_sigla}</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px; font-size: 10px;">
                    <div><strong>LOTE:</strong> ${tag.lote_codigo}</div>
                    <div><strong>PRESSÃO:</strong> ${tag.pressao_final_bar} bar</div>
                    <div><strong>PUREZA:</strong> ${tag.pureza_percentual}%</div>
                    <div><strong>VALIDADE:</strong> ${tag.data_validade}</div>
                    <div><strong>ONU:</strong> ${tag.numero_onu || 'N/A'}</div>
                    <div><strong>CLASSE:</strong> ${tag.classe_risco || '2.2'}</div>
                </div>
                <div style="border-top: 1px dashed #0f172a; padding-top: 4px; font-size: 10px;">
                    <div><strong>CILINDRO:</strong> ${tag.cilindro_serie} (${tag.cilindro_qr})</div>
                    <div><strong>MODELO:</strong> ${tag.modelo_descricao} (${tag.volume_litros}L)</div>
                    <div><strong>PRÓX. RETESTE:</strong> ${tag.data_proximo_reteste}</div>
                </div>
                <div style="border-top: 1px solid #0f172a; padding-top: 3px; font-size: 8px; text-align: center;">
                    RT: ${tag.rt_nome} (${tag.rt_registro})<br>
                    ${tag.normas}
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error("Erro ao carregar etiquetas:", e);
        container.innerHTML = '<div style="color: #dc2626; padding: 20px;">Erro na comunicação ao gerar etiquetas.</div>';
    }
}

// ==============================================================================
// 3. CENTRAL DE RECEBIMENTO DE FORNECEDOR (RDC 887/2024 - DISTRIBUIDORAS)
// ==============================================================================

const RecebimentoFornecedor = {
    cilindrosRecebidos: [],

    async inicializar() {
        await this.carregarRTs();
        await this.carregarHistorico();
        this.configurarLeitor();
    },

    async carregarRTs() {
        try {
            const sel = document.getElementById('rec-select-rt');
            if (!sel) return;
            // Carrega lotes para pegar RTs ou lista de responsáveis técnicos
            const res = await fetch('/produtos/api/lotes-anvisa/', { headers: getAuthHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            
            const rtsVistos = new Set();
            sel.innerHTML = '<option value="">-- Selecione o RT Conferente --</option>';

            data.forEach(l => {
                if (l.responsavel_tecnico && !rtsVistos.has(l.responsavel_tecnico)) {
                    rtsVistos.add(l.responsavel_tecnico);
                    const opt = document.createElement('option');
                    opt.value = l.id; // fallback reference
                    opt.textContent = `${l.responsavel_tecnico} (${l.rt_registro_snapshot || 'CRQ/CRF'})`;
                    sel.appendChild(opt);
                }
            });
        } catch (e) {
            console.error("Erro ao carregar RTs:", e);
        }
    },

    configurarLeitor() {
        const input = document.getElementById('input-rec-scanner');
        if (!input) return;

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const termo = input.value.trim();
                if (termo) {
                    this.adicionarCilindro(termo);
                    input.value = '';
                }
            }
        });
    },

    adicionarCilindro(codigo) {
        const c = codigo.trim().toUpperCase();
        if (this.cilindrosRecebidos.includes(c)) {
            AudioFeedback.error();
            alert(`Cilindro '${codigo}' já incluído na lista de recebimento.`);
            return;
        }
        this.cilindrosRecebidos.push(c);
        AudioFeedback.success();
        this.renderizarListaCilindros();
    },

    removerCilindro(idx) {
        this.cilindrosRecebidos.splice(idx, 1);
        this.renderizarListaCilindros();
    },

    renderizarListaCilindros() {
        const container = document.getElementById('rec-cilindros-chips');
        const contador = document.getElementById('rec-contador-cilindros');
        if (contador) contador.textContent = `${this.cilindrosRecebidos.length} casco(s) bipado(s)`;
        if (!container) return;

        container.innerHTML = '';
        if (this.cilindrosRecebidos.length === 0) {
            container.innerHTML = '<span style="color: var(--color-text-muted); font-size: 12px;">Nenhum cilindro bipado para esta nota fiscal.</span>';
            return;
        }

        this.cilindrosRecebidos.forEach((c, idx) => {
            const chip = document.createElement('span');
            chip.className = 'pill-filter-btn font-mono';
            chip.style.padding = '4px 8px';
            chip.innerHTML = `${c} <button type="button" onclick="RecebimentoFornecedor.removerCilindro(${idx})" style="background:none; border:none; color:#dc2626; cursor:pointer; font-weight:bold; margin-left:4px;">&times;</button>`;
            container.appendChild(chip);
        });
    },

    async submeterRecebimento(e) {
        e.preventDefault();
        if (this.cilindrosRecebidos.length === 0) {
            alert("Bipe ao menos um cilindro para registrar o recebimento da nota fiscal.");
            return;
        }

        const form = document.getElementById('form-recebimento-fornecedor');
        const formData = new FormData(form);
        formData.append('cilindros', JSON.stringify(this.cilindrosRecebidos));

        const btn = document.getElementById('btn-submit-recebimento');
        btn.disabled = true;
        btn.textContent = 'Registrando Entrada...';

        try {
            const res = await fetch('/produtos/api/recebimentos-fornecedor/registrar/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                    'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
                },
                body: formData
            });

            const data = await res.json();

            if (!res.ok) {
                alert(data.error || "Erro ao registrar recebimento.");
                return;
            }

            AudioFeedback.success();
            alert(`Recebimento Concluído com Sucesso! ${data.total_recebidos || 1} cilindro(s) cheios incorporados ao estoque.`);
            form.reset();
            this.cilindrosRecebidos = [];
            this.renderizarListaCilindros();
            await this.carregarHistorico();
        } catch (err) {
            console.error("Erro no recebimento:", err);
            alert("Falha de comunicação ao registrar recebimento.");
        } finally {
            btn.disabled = false;
            btn.textContent = 'Registrar Entrada de Fornecedor (RDC 887/2024)';
        }
    },

    async carregarHistorico() {
        const tbody = document.getElementById('tbody-historico-recebimentos');
        if (!tbody) return;

        try {
            const res = await fetch('/produtos/api/recebimentos-fornecedor/', { headers: getAuthHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            const itens = Array.isArray(data) ? data : (data.results || []);

            tbody.innerHTML = '';
            if (itens.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--color-text-muted); padding: 25px;">Nenhum recebimento externo de fornecedor registrado.</td></tr>';
                return;
            }

            itens.forEach(r => {
                const tr = document.createElement('tr');
                const laudoBtn = r.laudo_pdf 
                    ? `<a href="/produtos/api/recebimentos-fornecedor/${r.id}/laudo/" target="_blank" class="action-queue-btn" style="padding: 3px 8px; font-size: 11px;">PDF Laudo</a>`
                    : '<span style="color: var(--color-text-muted); font-size: 11px;">Sem laudo</span>';

                tr.innerHTML = `
                    <td><strong>${r.fornecedor_nome}</strong><br><small class="text-muted">CNPJ: ${r.fornecedor_cnpj}</small></td>
                    <td><code>NF ${r.nota_fiscal}</code></td>
                    <td><strong>${r.lote_fornecedor}</strong></td>
                    <td><span class="font-mono">${r.cilindro_qr}</span></td>
                    <td>${r.data_validade}</td>
                    <td>${r.rt_nome_snapshot || 'RT Conforme'}</td>
                    <td style="text-align: right;">${laudoBtn}</td>
                `;
                tbody.appendChild(tr);
            });
        } catch (e) {
            console.error("Erro ao carregar histórico de recebimentos:", e);
        }
    }
};

// ==============================================================================
// 4. CENTRAL DE LOTES & QUALIDADE CQ
// ==============================================================================

const CentralLotesCQ = {
    async carregar() {
        const tbody = document.getElementById('tbody-lotes-cq');
        if (!tbody) return;

        try {
            const res = await fetch('/produtos/api/lotes/', { headers: getAuthHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            const lotes = Array.isArray(data) ? data : (data.results || []);

            let totalAprov = 0, totalQuar = 0, totalReprov = 0;
            lotes.forEach(l => {
                if (l.status_qualidade === 'APROVADO') totalAprov++;
                else if (l.status_qualidade === 'QUARENTENA') totalQuar++;
                else if (l.status_qualidade === 'REPROVADO') totalReprov++;
            });

            const elAprov = document.getElementById('cq-kpi-aprovados');
            const elQuar = document.getElementById('cq-kpi-quarentena');
            const elReprov = document.getElementById('cq-kpi-reprovados');
            if (elAprov) elAprov.textContent = totalAprov;
            if (elQuar) elQuar.textContent = totalQuar;
            if (elReprov) elReprov.textContent = totalReprov;

            tbody.innerHTML = '';
            if (lotes.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 25px; color: var(--color-text-muted);">Nenhum lote químico registrado.</td></tr>';
                return;
            }

            lotes.forEach(l => {
                const tr = document.createElement('tr');
                let badgeClass = 'badge-conforme';
                if (l.status_qualidade === 'REPROVADO') badgeClass = 'badge-nao-conforme';
                else if (l.status_qualidade === 'QUARENTENA') badgeClass = 'pill-filter-btn';

                const laudoLink = l.laudo_pdf 
                    ? `<a href="/produtos/api/lotes-anvisa/${l.id}/laudo/" target="_blank" class="action-queue-btn" style="padding: 3px 8px; font-size: 11px;">Ver Laudo</a>`
                    : '<span style="font-size: 11px; color: var(--color-text-muted);">Sem PDF</span>';

                tr.innerHTML = `
                    <td><strong>${l.codigo_lote}</strong></td>
                    <td><strong>${l.gas_sigla}</strong> (${l.gas_nome})</td>
                    <td>${l.pureza_percentual}%</td>
                    <td>${l.data_validade}</td>
                    <td><span class="${badgeClass}">[${l.status_qualidade_display || l.status_qualidade}]</span></td>
                    <td>${l.rt_nome_snapshot || l.responsavel_tecnico || 'N/A'}</td>
                    <td style="text-align: right; display: flex; gap: 6px; justify-content: flex-end; align-items: center;">
                        <a href="/produtos/lotes/${l.id}/etiqueta-colarinho/" target="_blank" class="action-queue-btn" style="padding: 3px 8px; font-size: 11px; background: var(--color-surface); border: 1px solid var(--color-border); color: var(--color-text);" title="Imprimir Colarinho IN 129/2022">Colarinho</a>
                        ${laudoLink}
                        ${l.status_qualidade !== 'APROVADO' ? `<button class="action-queue-btn" style="padding: 3px 8px; font-size: 11px; background: #16a34a; color:#fff;" onclick="CentralLotesCQ.alterarQualidade(${l.id}, 'APROVADO')">Homologar RT</button>` : ''}
                        ${l.status_qualidade !== 'REPROVADO' ? `<button class="action-queue-btn" style="padding: 3px 8px; font-size: 11px; background: #dc2626; color:#fff;" onclick="CentralLotesCQ.reprovarLoteComJustificativa(${l.id}, '${l.codigo_lote}')">Reprovar</button>` : ''}
                    </td>
                `;
                tbody.appendChild(tr);
            });
        } catch (e) {
            console.error("Erro ao carregar lotes CQ:", e);
        }
    },

    async alterarQualidade(loteId, novoStatus, justificativa = '') {
        try {
            const res = await fetch(`/produtos/api/lotes/${loteId}/qualidade/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    novo_status: novoStatus,
                    justificativa: justificativa
                })
            });

            const data = await res.json();
            if (!res.ok) {
                alert(data.error || "Erro ao atualizar qualidade do lote.");
                return;
            }

            AudioFeedback.success();
            alert(`Status de qualidade atualizado com sucesso para [${novoStatus}].`);
            await this.carregar();
            await RampaEnvase.carregarLotes();
        } catch (e) {
            console.error("Erro ao atualizar qualidade:", e);
            alert("Falha na comunicação com o servidor.");
        }
    },

    reprovarLoteComJustificativa(loteId, codigoLote) {
        const justificativa = prompt(`ATENÇÃO: A reprovação do lote ${codigoLote} disparará BLOQUEIO SANITÁRIO IMEDIATO em todos os cilindros cheios ativos no pátio!\n\nInforme a justificativa técnica obrigatória:`);
        if (!justificativa || !justificativa.trim()) {
            alert("A justificativa técnica do Responsável Técnico é obrigatória para reprovar o lote.");
            return;
        }

        this.alterarQualidade(loteId, 'REPROVADO', justificativa.trim());
    }
};

// Inicialização automática das abas ao carregar DOM
document.addEventListener('DOMContentLoaded', () => {
    RampaEnvase.inicializar();
    RecebimentoFornecedor.inicializar();
    CentralLotesCQ.carregar();
});
