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

    async limparRampa() {
        if (this.cilindrosBatelada.length === 0) return;
        const ok = await Baros.confirmar({ titulo: 'Limpar a rampa?', texto: 'Todos os cilindros bipados nesta batelada saem da lista.', botao: 'Limpar', perigo: true });
        if (!ok) return;
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
            Baros.aviso('Selecione o lote de envase no topo da rampa.');
            return;
        }

        const pressaoInput = document.getElementById('rampa-pressao-final');
        const pressao = parseInt(pressaoInput ? pressaoInput.value : '200', 10);
        if (!pressao || pressao <= 0) {
            Baros.aviso('Informe uma pressão final válida (ex.: 200 bar).');
            return;
        }

        if (this.cilindrosBatelada.length === 0) {
            Baros.aviso('A rampa está vazia. Bipe ao menos um cilindro.');
            return;
        }

        // Validação se há itens não conformes
        const naoConformes = this.cilindrosBatelada.filter(c => 
            !(c.valvula_integra && c.pressao_residual_positiva && c.pintura_cor_padrao_ok && c.rotulo_identificacao_ok)
        );

        if (naoConformes.length > 0) {
            Swal.fire({ icon: 'warning', title: 'Há cilindros não conformes', text: `${naoConformes.length} cilindro(s) reprovaram no checklist da IN 129. Remova-os da rampa ou corrija a inspeção antes de concluir.` });
            return;
        }

        const confirmado = await Baros.confirmar({
            titulo: 'Concluir o envase?',
            texto: `${this.cilindrosBatelada.length} cilindro(s) a ${pressao} bar no lote ${this.loteSelecionado.codigo_lote}.`,
            botao: 'Concluir envase',
        });
        if (!confirmado) {
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
                Baros.erro(data.error || 'Não foi possível concluir a batelada.');
                return;
            }

            AudioFeedback.success();
            Baros.sucesso(`Batelada concluída: ${data.total_envasados} cilindro(s) envasado(s) no lote ${data.lote_codigo}.`);
            
            // Abre Modal de Etiquetas de Colarinho do Lote
            const envaseIds = (data.envases || []).map(e => e.id).join(',');
            this.cilindrosBatelada = [];
            this.renderizarGrid();
            
            if (envaseIds) {
                abrirModalEtiquetasColarinho(envaseIds);
            }
        } catch (e) {
            console.error("Erro ao concluir batelada:", e);
            Baros.erro('Sem comunicação com o servidor. A batelada não foi registrada.');
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
    stepper: null,

    async inicializar() {
        const raiz = document.getElementById('stepper-recebimento');
        if (!raiz) return;
        this.form = document.getElementById('form-recebimento-fornecedor');
        this.btnVoltar = raiz.querySelector('[data-stepper-voltar]');
        this.btnProximo = raiz.querySelector('[data-stepper-proximo]');
        this.btnConfirmar = raiz.querySelector('[data-stepper-confirmar]');

        this.stepper = Baros.Stepper(raiz, {
            validar: (n) => this.validarEtapa(n),
            aoMudar: (atual, total) => {
                this.btnVoltar.hidden = atual === 1;
                this.btnProximo.hidden = atual === total;
                this.btnConfirmar.hidden = atual !== total;
                if (atual === 2) document.getElementById('input-rec-scanner').focus();
                if (atual === total) this.montarRevisao();
            },
        });
        this.btnProximo.addEventListener('click', () => this.stepper.proxima());
        this.btnVoltar.addEventListener('click', () => this.stepper.anterior());
        document.getElementById('btn-rec-limpar').addEventListener('click', () => this.limpar(true));
        this.form.addEventListener('submit', (e) => this.submeterRecebimento(e));
        this.configurarLeitor();
        this.renderizarListaCilindros();
        await this.carregarHistorico();
    },

    validarEtapa(n) {
        if (n === 1) {
            if (!Baros.validarCampos('#stepper-recebimento .ds-step-pane[data-step="1"]')) return false;
            const envase = this.form.data_envase_origem.value;
            const validade = this.form.data_validade.value;
            if (envase && validade && validade <= envase) {
                Baros.mostrarErrosApi(this.form, { campos: { data_validade: 'A validade deve ser posterior à data de envase.' } });
                return false;
            }
            return true;
        }
        if (n === 2 && this.cilindrosRecebidos.length === 0) {
            Baros.aviso('Bipe ao menos um cilindro desta nota.');
            return false;
        }
        return true;
    },

    configurarLeitor() {
        const input = document.getElementById('input-rec-scanner');
        const adicionar = () => {
            const termo = input.value.trim();
            if (termo) this.adicionarCilindro(termo);
            input.value = '';
            input.focus();
        };
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); adicionar(); }
        });
        document.getElementById('btn-rec-adicionar').addEventListener('click', adicionar);
    },

    adicionarCilindro(codigo) {
        const c = codigo.trim().toUpperCase();
        if (this.cilindrosRecebidos.includes(c)) {
            AudioFeedback.error();
            Baros.aviso(`O cilindro ${c} já está na lista.`);
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
        const total = this.cilindrosRecebidos.length;
        document.getElementById('rec-contador-cilindros').textContent = `${total} cilindro${total === 1 ? '' : 's'}`;
        container.innerHTML = '';
        if (total === 0) {
            const vazio = document.createElement('span');
            vazio.className = 'ds-muted';
            vazio.textContent = 'Nenhum cilindro bipado ainda.';
            container.appendChild(vazio);
            return;
        }
        this.cilindrosRecebidos.forEach((c, idx) => {
            const chip = document.createElement('span');
            chip.className = 'ds-chip font-mono';
            chip.textContent = c;
            const remover = document.createElement('button');
            remover.type = 'button';
            remover.setAttribute('aria-label', `Remover ${c}`);
            remover.textContent = '×';
            remover.addEventListener('click', () => this.removerCilindro(idx));
            chip.appendChild(remover);
            container.appendChild(chip);
        });
    },

    montarRevisao() {
        const f = this.form;
        const rt = f.responsavel_tecnico_id.value ? f.responsavel_tecnico_id.selectedOptions[0].text : 'Não informado';
        const laudo = f.laudo_pdf.files[0] ? f.laudo_pdf.files[0].name : 'Sem laudo';
        const linhas = [
            ['Fornecedor', `${f.fornecedor_nome.value} · CNPJ ${f.fornecedor_cnpj.value}`],
            ['Nota fiscal', f.nota_fiscal.value],
            ['Lote do fornecedor', f.lote_fornecedor.value],
            ['Envase / validade', `${Baros.data(f.data_envase_origem.value)} → ${Baros.data(f.data_validade.value)}`],
            ['Pressão', `${f.pressao_recebimento_bar.value} bar`],
            ['RT conferente', rt],
            ['Laudo', laudo],
            ['Cilindros', `${this.cilindrosRecebidos.length}: ${this.cilindrosRecebidos.join(', ')}`],
        ];
        const dl = document.getElementById('rec-revisao');
        dl.innerHTML = '';
        linhas.forEach(([r, v]) => {
            const dt = document.createElement('dt'); dt.textContent = r;
            const dd = document.createElement('dd'); dd.textContent = v;
            dl.append(dt, dd);
        });
    },

    limpar(perguntar) {
        const executar = () => {
            this.form.reset();
            this.cilindrosRecebidos = [];
            this.renderizarListaCilindros();
            this.form.querySelectorAll('.ds-field-error').forEach(el => el.remove());
            this.form.querySelectorAll('.ds-invalid').forEach(el => el.classList.remove('ds-invalid'));
            this.stepper.reiniciar();
        };
        if (!perguntar || (!this.cilindrosRecebidos.length && !this.form.nota_fiscal.value)) return executar();
        Baros.confirmar({ titulo: 'Limpar o recebimento?', texto: 'Os dados da nota e os cilindros bipados serão descartados.', botao: 'Limpar', perigo: true })
            .then(ok => { if (ok) executar(); });
    },

    async submeterRecebimento(e) {
        e.preventDefault();
        const formData = new FormData(this.form);
        formData.append('cilindros', JSON.stringify(this.cilindrosRecebidos));
        const restaurar = Baros.carregando(this.btnConfirmar, 'Registrando...');
        try {
            const data = await Baros.api('/produtos/api/recebimentos-fornecedor/registrar/', { method: 'POST', body: formData });
            AudioFeedback.success();
            Baros.sucesso(`Entrada registrada: ${data.total_recebidos || this.cilindrosRecebidos.length} cilindro(s) cheio(s) no estoque.`);
            this.limpar(false);
            await this.carregarHistorico();
        } catch (err) {
            AudioFeedback.error();
            Baros.mostrarErrosApi(this.form, err);
        } finally {
            restaurar();
        }
    },

    async carregarHistorico() {
        const tbody = document.getElementById('tbody-historico-recebimentos');
        if (!tbody) return;
        const linhaUnica = (texto, erro) => {
            tbody.innerHTML = '';
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 7;
            const caixa = document.createElement('div');
            caixa.className = 'ds-empty' + (erro ? ' ds-empty--danger' : '');
            const p = document.createElement('p');
            p.className = 'ds-empty-title';
            p.textContent = texto;
            caixa.appendChild(p);
            td.appendChild(caixa);
            tr.appendChild(td);
            tbody.appendChild(tr);
        };
        tbody.innerHTML = '<tr><td colspan="7"><span class="ds-skeleton"></span><span class="ds-skeleton"></span></td></tr>';
        try {
            const data = await Baros.api('/produtos/api/recebimentos-fornecedor/');
            const itens = Array.isArray(data) ? data : (data.results || []);
            if (itens.length === 0) return linhaUnica('Nenhum recebimento registrado ainda.');
            tbody.innerHTML = '';
            itens.forEach(r => {
                const tr = document.createElement('tr');
                const celula = (texto, classe) => { const td = document.createElement('td'); td.textContent = texto; if (classe) td.className = classe; return td; };
                const forn = celula(r.fornecedor_nome);
                const sub = document.createElement('span');
                sub.className = 'ds-cell-sub font-mono';
                sub.textContent = r.fornecedor_cnpj;
                forn.appendChild(sub);
                const laudo = document.createElement('td');
                laudo.className = 'ds-num';
                if (r.laudo_pdf) {
                    const a = document.createElement('a');
                    a.href = `/produtos/api/recebimentos-fornecedor/${r.id}/laudo/`;
                    a.target = '_blank';
                    a.rel = 'noopener';
                    a.className = 'btn-outline btn-sm';
                    a.textContent = 'PDF';
                    laudo.appendChild(a);
                } else {
                    laudo.textContent = '—';
                }
                tr.append(forn, celula('NF ' + r.nota_fiscal, 'font-mono'), celula(r.lote_fornecedor, 'font-mono'),
                    celula(r.cilindro_qr, 'font-mono'), celula(Baros.data(r.data_validade)), celula(r.rt_nome_snapshot || '—'), laudo);
                tbody.appendChild(tr);
            });
        } catch (e) {
            linhaUnica('Não foi possível carregar o histórico.', true);
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
                Baros.erro(data.error || 'Não foi possível atualizar a qualidade do lote.');
                return;
            }

            AudioFeedback.success();
            Baros.sucesso(`Qualidade do lote atualizada: ${novoStatus}.`);
            await this.carregar();
            await RampaEnvase.carregarLotes();
        } catch (e) {
            console.error("Erro ao atualizar qualidade:", e);
            Baros.erro('Sem comunicação com o servidor.');
        }
    },

    async reprovarLoteComJustificativa(loteId, codigoLote) {
        const justificativa = await Baros.confirmar({
            titulo: `Reprovar o lote ${codigoLote}?`,
            texto: 'Todos os cilindros cheios deste lote no pátio entram em bloqueio sanitário imediato.',
            botao: 'Reprovar lote',
            perigo: true,
            motivo: 10,
        });
        if (!justificativa) return;

        this.alterarQualidade(loteId, 'REPROVADO', justificativa);
    }
};

// Inicialização automática das abas ao carregar DOM
document.addEventListener('DOMContentLoaded', () => {
    RampaEnvase.inicializar();
    RecebimentoFornecedor.inicializar();
    CentralLotesCQ.carregar();
});
