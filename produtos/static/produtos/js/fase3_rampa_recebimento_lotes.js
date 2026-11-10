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
    ITENS_CHECKLIST: [
        ['valvula_integra', 'Válvula íntegra'],
        ['pressao_residual_positiva', 'Pressão residual positiva'],
        ['pintura_cor_padrao_ok', 'Pintura / cor ABNT'],
        ['rotulo_identificacao_ok', 'Rótulo regulamentar'],
    ],

    async inicializar() {
        if (!document.getElementById('aba-conteudo-rampa')) return;
        document.getElementById('rampa-select-lote').addEventListener('change', () => this.onLoteChange());
        document.getElementById('btn-rampa-acoplar').addEventListener('click', () => this.lerCampo());
        document.getElementById('btn-rampa-limpar').addEventListener('click', () => this.limparRampa());
        document.getElementById('btn-rampa-conferir-todos').addEventListener('click', () => this.marcarConformeTodos());
        document.getElementById('btn-concluir-batelada').addEventListener('click', () => this.concluirBatelada());
        this.configurarLeitorWedge();
        this.renderizarGrid();
        await this.carregarLotes();
    },

    async carregarLotes() {
        const sel = document.getElementById('rampa-select-lote');
        sel.innerHTML = '';
        sel.appendChild(new Option('Carregando lotes...', ''));
        try {
            const data = await Baros.api('/produtos/api/lotes/');
            this.lotes = Array.isArray(data) ? data : (data.results || []);
            sel.innerHTML = '';
            sel.appendChild(new Option(this.lotes.length ? 'Selecione o lote' : 'Nenhum lote disponível', ''));
            this.lotes.forEach(l => {
                const cq = l.status_qualidade === 'APROVADO' ? 'CQ aprovado' : (l.status_qualidade_display || l.status_qualidade);
                sel.appendChild(new Option(`${l.codigo_lote} · ${l.gas_sigla} · validade ${Baros.data(l.data_validade)} · ${cq}`, l.id));
            });
        } catch (e) {
            sel.innerHTML = '';
            sel.appendChild(new Option('Erro ao carregar os lotes', ''));
        }
    },

    onLoteChange() {
        const id = parseInt(document.getElementById('rampa-select-lote').value, 10);
        const novo = this.lotes.find(l => l.id === id) || null;
        if (this.cilindrosBatelada.length && novo && this.loteSelecionado && novo.id !== this.loteSelecionado.id) {
            this.mostrarFeedback('Lote trocado: os cilindros já acoplados serão revalidados ao concluir.', 'aviso');
        }
        this.loteSelecionado = novo;
        const info = document.getElementById('rampa-lote-info-pill');
        info.innerHTML = '';
        if (!novo) return;
        const tons = { APROVADO: 'approved', QUARENTENA: 'warning', REPROVADO: 'danger' };
        const itens = [
            ['Gás', `${novo.gas_sigla} · ${novo.gas_nome}`],
            ['Pureza', `${novo.pureza_percentual}%`],
            ['Validade', Baros.data(novo.data_validade)],
            ['RT', novo.rt_nome_snapshot || novo.responsavel_tecnico || '—'],
        ];
        itens.forEach(([r, v]) => {
            const span = document.createElement('span');
            const b = document.createElement('strong');
            b.textContent = r + ': ';
            span.append(b, v);
            info.appendChild(span);
        });
        const badge = document.createElement('span');
        badge.className = 'badge-status-' + (tons[novo.status_qualidade] || 'transit');
        badge.textContent = novo.status_qualidade_display || novo.status_qualidade;
        info.appendChild(badge);
        document.getElementById('input-scanner-wedge').focus();
    },

    configurarLeitorWedge() {
        const input = document.getElementById('input-scanner-wedge');
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); this.lerCampo(); }
        });
    },

    lerCampo() {
        const input = document.getElementById('input-scanner-wedge');
        const codigo = input.value.trim();
        input.value = '';
        input.focus();
        if (codigo) this.biparCilindro(codigo);
    },

    async biparCilindro(codigo) {
        if (!this.loteSelecionado) {
            this.mostrarFeedback('Selecione o lote de envase antes de bipar.', 'erro');
            AudioFeedback.error();
            return;
        }
        const termo = codigo.toUpperCase();
        if (this.cilindrosBatelada.some(c => c.codigo_qr.toUpperCase() === termo || c.numero_serie_ogiva.toUpperCase() === termo)) {
            this.mostrarFeedback(`${termo} já está na rampa.`, 'erro');
            AudioFeedback.error();
            return;
        }
        try {
            const data = await Baros.api('/produtos/api/envases/validar-cilindro/', {
                method: 'POST',
                body: { termo: codigo, lote_id: this.loteSelecionado.id },
            });
            if (!data.valido) throw new Baros.ApiError(400, { error: data.motivo || 'Cilindro recusado na validação da rampa.' });
            const cil = data.cilindro;
            const item = {
                id: cil.id,
                codigo_qr: cil.codigo_qr,
                numero_serie_ogiva: cil.numero_serie_ogiva,
                modelo_descricao: cil.modelo_descricao,
                volume_litros: cil.volume_litros,
                gas_sigla: cil.gas_sigla,
                gas_nome: cil.gas_nome,
                data_proximo_reteste: cil.data_proximo_reteste,
                observacoes_inspecao: '',
            };
            // IN 129: a inspeção física é um ato do operador; nada começa marcado.
            this.ITENS_CHECKLIST.forEach(([campo]) => { item[campo] = false; });
            this.cilindrosBatelada.push(item);
            AudioFeedback.success();
            this.mostrarFeedback(`${cil.codigo_qr} acoplado. Faça a inspeção.`, 'ok');
            this.renderizarGrid();
        } catch (e) {
            AudioFeedback.error();
            this.mostrarFeedback(e.mensagem || 'Cilindro recusado.', 'erro');
        }
    },

    mostrarFeedback(msg, tipo) {
        const banner = document.getElementById('rampa-scan-feedback');
        banner.className = 'estacao-feedback estacao-feedback--' + tipo;
        banner.textContent = msg;
        const card = document.getElementById('wedge-scanner-card');
        card.classList.remove('estacao-pulso-ok', 'estacao-pulso-erro');
        void card.offsetWidth;
        if (tipo === 'ok') card.classList.add('estacao-pulso-ok');
        if (tipo === 'erro') card.classList.add('estacao-pulso-erro');
    },

    situacao(c) {
        const marcados = this.ITENS_CHECKLIST.filter(([campo]) => c[campo]).length;
        if (marcados === this.ITENS_CHECKLIST.length) return 'conforme';
        return marcados === 0 ? 'pendente' : 'incompleta';
    },

    async marcarConformeTodos() {
        const pendentes = this.cilindrosBatelada.filter(c => this.situacao(c) !== 'conforme');
        if (!pendentes.length) return;
        const ok = await Baros.confirmar({
            titulo: 'Confirmar a inspeção de todos?',
            texto: `Você declara que inspecionou fisicamente ${pendentes.length} cilindro(s) e que todos estão conformes nos 4 itens da IN 129. Isso fica registrado no envase.`,
            botao: 'Sim, inspecionei',
        });
        if (!ok) return;
        pendentes.forEach(c => this.ITENS_CHECKLIST.forEach(([campo]) => { c[campo] = true; }));
        this.renderizarGrid();
    },

    removerCilindro(cilId) {
        this.cilindrosBatelada = this.cilindrosBatelada.filter(c => c.id !== cilId);
        this.renderizarGrid();
    },

    async limparRampa() {
        if (this.cilindrosBatelada.length === 0) return;
        const ok = await Baros.confirmar({ titulo: 'Limpar a rampa?', texto: 'Todos os cilindros desta batelada saem da lista.', botao: 'Limpar', perigo: true });
        if (!ok) return;
        this.cilindrosBatelada = [];
        this.renderizarGrid();
        this.mostrarFeedback('Rampa limpa.', 'ok');
    },

    renderizarGrid() {
        const grade = document.getElementById('rampa-grid');
        const total = this.cilindrosBatelada.length;
        const conformes = this.cilindrosBatelada.filter(c => this.situacao(c) === 'conforme').length;
        document.getElementById('rampa-contador-cilindros').textContent = `${total} cilindro${total === 1 ? '' : 's'}`;
        document.getElementById('rampa-resumo-inspecao').textContent = total ? `· ${conformes} de ${total} inspecionados` : '';
        document.getElementById('btn-concluir-batelada').disabled = total === 0;
        document.getElementById('btn-rampa-conferir-todos').disabled = conformes === total;

        grade.innerHTML = '';
        if (!total) {
            const vazio = document.createElement('div');
            vazio.className = 'ds-empty';
            vazio.innerHTML = '<p class="ds-empty-title"></p><p class="ds-empty-text"></p>';
            vazio.children[0].textContent = 'Nenhum cilindro na rampa';
            vazio.children[1].textContent = 'Escolha o lote e bipe os cilindros.';
            grade.appendChild(vazio);
            return;
        }

        const rotulos = { conforme: ['Conforme', 'approved'], pendente: ['Inspeção pendente', 'warning'], incompleta: ['Inspeção incompleta', 'danger'] };
        this.cilindrosBatelada.forEach(c => {
            const sit = this.situacao(c);
            const card = document.createElement('article');
            card.className = 'estacao-cilindro estacao-cilindro--' + sit;

            const topo = document.createElement('div');
            topo.className = 'estacao-cilindro-topo';
            const ident = document.createElement('div');
            const qr = document.createElement('strong');
            qr.className = 'font-mono';
            qr.textContent = c.codigo_qr;
            const sub = document.createElement('span');
            sub.className = 'ds-cell-sub';
            sub.textContent = `Série ${c.numero_serie_ogiva} · ${c.gas_sigla} · ${c.modelo_descricao || ''} · reteste ${Baros.data(c.data_proximo_reteste)}`;
            ident.append(qr, sub);
            const badge = document.createElement('span');
            badge.className = 'badge-status-' + rotulos[sit][1];
            badge.textContent = rotulos[sit][0];
            topo.append(ident, badge);

            const checks = document.createElement('div');
            checks.className = 'estacao-checks';
            this.ITENS_CHECKLIST.forEach(([campo, rotulo]) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'estacao-check' + (c[campo] ? ' marcado' : '');
                b.setAttribute('aria-pressed', c[campo] ? 'true' : 'false');
                b.textContent = (c[campo] ? '✓ ' : '') + rotulo;
                b.addEventListener('click', () => { c[campo] = !c[campo]; this.renderizarGrid(); });
                checks.appendChild(b);
            });

            const remover = document.createElement('button');
            remover.type = 'button';
            remover.className = 'btn-outline btn-sm estacao-remover';
            remover.textContent = 'Remover';
            remover.setAttribute('aria-label', `Remover ${c.codigo_qr} da rampa`);
            remover.addEventListener('click', () => this.removerCilindro(c.id));

            card.append(topo, checks, remover);
            grade.appendChild(card);
        });
    },

    async concluirBatelada() {
        if (!this.loteSelecionado) { Baros.aviso('Selecione o lote de envase.'); return; }
        const pressao = parseInt(document.getElementById('rampa-pressao-final').value, 10);
        if (!pressao || pressao <= 0) { Baros.aviso('Informe uma pressão final válida (ex.: 200 bar).'); return; }
        if (!this.cilindrosBatelada.length) { Baros.aviso('A rampa está vazia.'); return; }

        const semInspecao = this.cilindrosBatelada.filter(c => this.situacao(c) !== 'conforme');
        if (semInspecao.length) {
            Swal.fire({
                icon: 'warning',
                title: 'Inspeção incompleta',
                text: `${semInspecao.length} cilindro(s) sem os 4 itens da IN 129 conferidos: ${semInspecao.map(c => c.codigo_qr).join(', ')}. Confira ou remova da rampa.`,
            });
            return;
        }

        const confirmado = await Baros.confirmar({
            titulo: 'Concluir o envase?',
            texto: `${this.cilindrosBatelada.length} cilindro(s) a ${pressao} bar no lote ${this.loteSelecionado.codigo_lote}.`,
            botao: 'Concluir envase',
        });
        if (!confirmado) return;

        const btn = document.getElementById('btn-concluir-batelada');
        const restaurar = Baros.carregando(btn, 'Gravando...');
        try {
            const data = await Baros.api('/produtos/api/envases/batelada/', {
                method: 'POST',
                body: {
                    lote_id: this.loteSelecionado.id,
                    pressao_final_bar: pressao,
                    itens: this.cilindrosBatelada.map(c => ({
                        cilindro_id: c.id,
                        valvula_integra: c.valvula_integra,
                        pressao_residual_positiva: c.pressao_residual_positiva,
                        pintura_cor_padrao_ok: c.pintura_cor_padrao_ok,
                        rotulo_identificacao_ok: c.rotulo_identificacao_ok,
                        observacoes_inspecao: c.observacoes_inspecao || '',
                    })),
                },
            });
            AudioFeedback.success();
            Baros.sucesso(`Envase concluído: ${data.total_envasados} cilindro(s) no lote ${data.lote_codigo}.`);
            const envaseIds = (data.envases || []).map(e => e.id).join(',');
            this.cilindrosBatelada = [];
            this.renderizarGrid();
            this.mostrarFeedback('Batelada gravada. Pronto para a próxima.', 'ok');
            if (envaseIds) abrirModalEtiquetasColarinho(envaseIds);
        } catch (e) {
            AudioFeedback.error();
            Baros.erro(e.mensagem || 'Não foi possível concluir a batelada.');
        } finally {
            restaurar();
            btn.disabled = this.cilindrosBatelada.length === 0;
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
    // Utilitário para construção segura de nós do DOM sem innerHTML
    el(tag, opcoes = {}, ...filhos) {
        const e = document.createElement(tag);
        if (opcoes.classe) e.className = opcoes.classe;
        if (opcoes.texto !== undefined && opcoes.texto !== null) e.textContent = opcoes.texto;
        if (opcoes.attrs) {
            Object.entries(opcoes.attrs).forEach(([k, v]) => {
                if (v !== undefined && v !== null) e.setAttribute(k, v);
            });
        }
        filhos.filter(Boolean).forEach(f => e.append(f));
        return e;
    },

    async carregar() {
        const tbody = document.getElementById('tbody-lotes-cq');
        if (!tbody) return;

        try {
            const data = await Baros.api('/produtos/api/lotes/');
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
                const trVazia = this.el('tr', {},
                    this.el('td', { attrs: { colspan: 7 }, classe: 'ds-cell-sub' },
                        this.el('div', { classe: 'ds-empty' },
                            this.el('p', { classe: 'ds-empty-title', texto: 'Nenhum lote químico registrado.' })
                        )
                    )
                );
                tbody.append(trVazia);
                return;
            }

            lotes.forEach(l => {
                const tr = this.el('tr');

                // 1. Código do lote
                const tdCodigo = this.el('td', {},
                    this.el('strong', { classe: 'font-mono', texto: l.codigo_lote })
                );

                // 2. Gás Químico
                const tdGas = this.el('td', {},
                    this.el('strong', { texto: l.gas_sigla }),
                    this.el('span', { classe: 'ds-cell-sub', texto: ` (${l.gas_nome})` })
                );

                // 3. Pureza
                const purezaNum = Number(l.pureza_percentual || 0).toLocaleString('pt-BR', { maximumFractionDigits: 2 });
                const tdPureza = this.el('td', { classe: 'font-mono', texto: `${purezaNum}%` });

                // 4. Validade
                const tdValidade = this.el('td', { classe: 'font-mono', texto: l.data_validade || '—' });

                // 5. Status CQ Badge
                const tomBadge = {
                    APROVADO: 'approved',
                    QUARENTENA: 'quarantine',
                    REPROVADO: 'danger'
                }[l.status_qualidade] || 'warning';
                const statusTexto = l.status_qualidade_display || l.status_qualidade;
                const tdStatus = this.el('td', {},
                    this.el('span', { classe: `badge-status-${tomBadge}`, texto: statusTexto })
                );

                // 6. Liberado por (RT, registro e data da última liberação)
                const tdLiberado = this.el('td');
                const ultima = l.ultima_liberacao;
                if (ultima && ultima.data) {
                    const dataFormatada = Baros.data ? Baros.data(ultima.data.split('T')[0]) : ultima.data.split('T')[0];
                    const infoRT = `${ultima.rt} (${ultima.registro})`;
                    tdLiberado.append(
                        this.el('div', {},
                            this.el('strong', { texto: infoRT }),
                            this.el('span', { classe: 'ds-cell-sub', texto: dataFormatada })
                        )
                    );
                } else if (ultima && ultima.rt) {
                    tdLiberado.append(this.el('span', { classe: 'ds-cell-sub', texto: ultima.rt }));
                } else {
                    tdLiberado.append(this.el('span', { classe: 'ds-cell-sub', texto: 'Sem registro (anterior ao histórico)' }));
                }

                // 7. Ações
                const tdAcoes = this.el('td');
                const divAcoes = this.el('div', { classe: 'lotes-acoes-celula' });

                // Botão Colarinho
                const btnColarinho = this.el('a', {
                    classe: 'btn-outline btn-sm',
                    texto: 'Colarinho',
                    attrs: {
                        href: `/produtos/lotes/${l.id}/etiqueta-colarinho/`,
                        target: '_blank',
                        title: 'Imprimir Colarinho IN 129/2022'
                    }
                });
                divAcoes.append(btnColarinho);

                // Botão Laudo
                if (l.laudo_pdf) {
                    const btnLaudo = this.el('a', {
                        classe: 'btn-outline btn-sm',
                        texto: 'Ver Laudo',
                        attrs: {
                            href: `/produtos/api/lotes-anvisa/${l.id}/laudo/`,
                            target: '_blank'
                        }
                    });
                    divAcoes.append(btnLaudo);
                } else {
                    divAcoes.append(this.el('span', { classe: 'ds-cell-sub', texto: 'Sem PDF' }));
                }

                // Botão Histórico
                const btnHistorico = this.el('button', {
                    classe: 'btn-outline btn-sm',
                    texto: 'Histórico',
                    attrs: { type: 'button' }
                });
                btnHistorico.addEventListener('click', () => CentralLotesCQ.abrirHistorico(l));
                divAcoes.append(btnHistorico);

                // Botões de transição permitida
                const transicoes = l.transicoes_permitidas || [];
                if (transicoes.length > 0) {
                    if (transicoes.includes('APROVADO')) {
                        const btnAprovar = this.el('button', {
                            classe: 'btn-primary btn-sm',
                            texto: 'Aprovar',
                            attrs: { type: 'button' }
                        });
                        btnAprovar.addEventListener('click', () => CentralLotesCQ.confirmarAprovacao(l));
                        divAcoes.append(btnAprovar);
                    }
                    if (transicoes.includes('REPROVADO')) {
                        const btnReprovar = this.el('button', {
                            classe: 'btn-danger btn-sm',
                            texto: 'Reprovar',
                            attrs: { type: 'button' }
                        });
                        btnReprovar.addEventListener('click', () => CentralLotesCQ.confirmarReprovacao(l));
                        divAcoes.append(btnReprovar);
                    }
                } else {
                    divAcoes.append(this.el('span', { classe: 'lotes-restrito-texto', texto: 'Liberação restrita ao RT' }));
                }

                tdAcoes.append(divAcoes);

                tr.append(tdCodigo, tdGas, tdPureza, tdValidade, tdStatus, tdLiberado, tdAcoes);
                tbody.append(tr);
            });
        } catch (e) {
            console.error("Erro ao carregar lotes CQ:", e);
            const msg = (e && (e.mensagem || e.message)) || 'Não foi possível carregar os lotes químicos.';
            tbody.innerHTML = '';
            const trErro = this.el('tr', {},
                this.el('td', { attrs: { colspan: 7 } },
                    this.el('div', { classe: 'ds-empty ds-empty--danger' },
                        this.el('p', { classe: 'ds-empty-title', texto: msg }),
                        this.el('button', {
                            classe: 'btn-secondary btn-sm',
                            texto: 'Tentar novamente',
                            attrs: { type: 'button' }
                        })
                    )
                )
            );
            const btnTentar = trErro.querySelector('button');
            if (btnTentar) {
                btnTentar.addEventListener('click', () => CentralLotesCQ.carregar());
            }
            tbody.append(trErro);
            if (window.Baros && typeof Baros.erro === 'function') {
                Baros.erro(msg);
            }
        }
    },

    async confirmarAprovacao(lote) {
        const pureza = Number(lote.pureza_percentual || 0).toLocaleString('pt-BR', { maximumFractionDigits: 2 });
        const laudoTexto = lote.laudo_pdf
            ? '✓ Laudo de Análise (PDF) anexado.'
            : '⚠️ ATENÇÃO: Este lote NÃO possui Laudo de Análise anexado em PDF (não impede aprovação técnica).';

        const detalhes = [
            `Lote: ${lote.codigo_lote}`,
            `Gás: ${lote.gas_sigla} - ${lote.gas_nome}`,
            `Pureza: ${pureza}%`,
            `Validade: ${lote.data_validade || '—'}`,
            '',
            laudoTexto
        ].join('\n');

        const confirmou = await Baros.confirmar({
            titulo: `Aprovar lote ${lote.codigo_lote}?`,
            texto: detalhes,
            botao: 'Confirmar Aprovação',
        });
        if (!confirmou) return;

        await this.alterarQualidade(lote.id, 'APROVADO', 'Aprovação pelo Responsável Técnico');
    },

    async confirmarReprovacao(lote) {
        const justificativa = await Baros.confirmar({
            titulo: `Reprovar o lote ${lote.codigo_lote}?`,
            texto: 'Atenção regulatória: Todos os cilindros cheios deste lote no pátio entrarão em bloqueio sanitário imediato.',
            botao: 'Reprovar lote',
            perigo: true,
            motivo: 10,
        });
        if (!justificativa) return;

        await this.alterarQualidade(lote.id, 'REPROVADO', justificativa);
    },

    async alterarQualidade(loteId, novoStatus, justificativa = '') {
        try {
            await Baros.api(`/produtos/api/lotes/${loteId}/qualidade/`, {
                method: 'POST',
                body: {
                    novo_status: novoStatus,
                    justificativa: justificativa
                }
            });

            if (window.AudioFeedback && typeof AudioFeedback.success === 'function') {
                AudioFeedback.success();
            }
            Baros.sucesso(`Qualidade do lote atualizada para ${novoStatus}.`);
            await this.carregar();
            if (window.RampaEnvase && typeof RampaEnvase.carregarLotes === 'function') {
                await RampaEnvase.carregarLotes();
            }
        } catch (e) {
            console.error("Erro ao atualizar qualidade:", e);
            const msg = (e && (e.mensagem || e.message)) || 'Não foi possível atualizar a qualidade do lote.';
            Baros.erro(msg);
        }
    },

    async abrirHistorico(lote) {
        const dialog = document.getElementById('drawer-historico-lote');
        const subtitulo = document.getElementById('drawer-historico-subtitulo');
        const conteudo = document.getElementById('drawer-historico-conteudo');
        if (!dialog || !conteudo) return;

        if (subtitulo) {
            subtitulo.textContent = `${lote.codigo_lote} · ${lote.gas_sigla} (${lote.gas_nome})`;
        }
        conteudo.innerHTML = '';
        conteudo.append(this.el('p', { classe: 'ds-cell-sub', texto: 'Carregando histórico...' }));
        dialog.showModal();

        try {
            const historicos = await Baros.api(`/produtos/api/lotes/${lote.id}/historico-qualidade/`);
            conteudo.innerHTML = '';
            if (!historicos || historicos.length === 0) {
                conteudo.append(
                    this.el('div', { classe: 'ds-empty' },
                        this.el('p', { classe: 'ds-empty-title', texto: 'Nenhuma alteração registrada.' }),
                        this.el('span', { classe: 'ds-cell-sub', texto: 'Este lote não possui registros no novo formato de histórico.' })
                    )
                );
                return;
            }

            historicos.forEach(h => {
                const tom = { APROVADO: 'approved', REPROVADO: 'danger' }[h.status_novo] || 'warning';
                const card = this.el('div', { classe: 'historico-card' },
                    this.el('div', { classe: 'historico-card-header' },
                        this.el('div', {},
                            this.el('strong', { texto: `${h.status_anterior} \u2192 ` }),
                            this.el('span', { classe: `badge-status-${tom}`, texto: h.status_novo_display || h.status_novo })
                        ),
                        this.el('span', {
                            classe: 'font-mono ds-cell-sub',
                            texto: h.criado_em ? (Baros.data ? Baros.data(h.criado_em.split('T')[0]) : h.criado_em.split('T')[0]) + ' ' + (h.criado_em.split('T')[1] || '').substring(0, 5) : '—'
                        })
                    ),
                    this.el('div', { classe: 'historico-card-rt' },
                        this.el('strong', { texto: 'RT: ' }),
                        this.el('span', { texto: `${h.rt_nome_snapshot} (${h.rt_registro_snapshot})` }),
                        this.el('span', { classe: 'ds-cell-sub', texto: ` · Operador: ${h.usuario_nome}` })
                    )
                );
                if (h.justificativa) {
                    card.append(this.el('div', { classe: 'historico-card-justificativa', texto: `Justificativa: ${h.justificativa}` }));
                }
                conteudo.append(card);
            });
        } catch (e) {
            conteudo.innerHTML = '';
            conteudo.append(
                this.el('div', { classe: 'ds-empty ds-empty--danger' },
                    this.el('p', { classe: 'ds-empty-title', texto: (e && (e.mensagem || e.message)) || 'Erro ao carregar histórico.' })
                )
            );
        }
    }
};

// Inicialização automática das abas ao carregar DOM
document.addEventListener('DOMContentLoaded', () => {
    RampaEnvase.inicializar();
    RecebimentoFornecedor.inicializar();
    CentralLotesCQ.carregar();
    const btnFechar = document.getElementById('btn-fechar-drawer-historico');
    if (btnFechar) {
        btnFechar.addEventListener('click', () => {
            const dialog = document.getElementById('drawer-historico-lote');
            if (dialog && typeof dialog.close === 'function') dialog.close();
        });
    }
});
