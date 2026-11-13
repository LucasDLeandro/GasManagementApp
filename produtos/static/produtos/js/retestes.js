/* global Baros */
document.addEventListener('DOMContentLoaded', () => {
    const config = window.RETESTES_CONFIG || { podeEditarPatrimonio: false };
    const extrairLista = (res) => (Array.isArray(res) ? res : (res && res.results) || []);

    // =========================================================================
    // REFERÊNCIAS DE DOM (declaradas antes de qualquer inicialização)
    // =========================================================================
    const tabButtons = document.querySelectorAll('.tabs-nav .tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    // KPIs
    const kpiVencidos = document.getElementById('kpi-reteste-vencidos');
    const kpi30d = document.getElementById('kpi-reteste-30d');
    const kpi60d = document.getElementById('kpi-reteste-60d');
    const kpi90d = document.getElementById('kpi-reteste-90d');
    const kpiRequalificacao = document.getElementById('kpi-reteste-requalificacao');

    // Aba Vencimentos
    const filtroSituacao = document.getElementById('filtro-venc-situacao');
    const filtroGas = document.getElementById('filtro-venc-gas');
    const filtroModelo = document.getElementById('filtro-venc-modelo');
    const btnEnviarSelecionados = document.getElementById('btn-enviar-selecionados');
    const countSelecionados = document.getElementById('count-selecionados');
    const chkTodos = document.getElementById('chk-todos-vencimentos');
    const corpoVencimentos = document.getElementById('corpo-tabela-vencimentos');
    const skeletonVencimentos = document.getElementById('skeleton-vencimentos');
    const vazioVencimentos = document.getElementById('vazio-vencimentos');
    const erroVencimentos = document.getElementById('erro-vencimentos');
    const btnRetryVencimentos = document.getElementById('btn-retry-vencimentos');

    // Aba Envios
    const corpoEnvios = document.getElementById('corpo-tabela-envios');
    const skeletonEnvios = document.getElementById('skeleton-envios');
    const vazioEnvios = document.getElementById('vazio-envios');
    const erroEnvios = document.getElementById('erro-envios');
    const btnRetryEnvios = document.getElementById('btn-retry-envios');
    const cardDetalheEnvio = document.getElementById('card-detalhe-envio');
    const tituloDetalheEnvio = document.getElementById('titulo-detalhe-envio');
    const subtituloDetalheEnvio = document.getElementById('subtitulo-detalhe-envio');
    const corpoItensEnvio = document.getElementById('corpo-itens-envio');
    const btnFecharDetalheEnvio = document.getElementById('btn-fechar-detalhe-envio');

    // Modal Novo Envio
    const btnAbrirNovoEnvio = document.getElementById('btn-abrir-novo-envio');
    const formNovoEnvio = document.getElementById('form-novo-envio');
    const bipeInput = document.getElementById('envio-bipe-input');
    const btnAddBipe = document.getElementById('btn-adicionar-bipe-envio');
    const bipeFeedback = document.getElementById('envio-bipe-feedback');
    const listaChipsEnvio = document.getElementById('lista-chips-envio');
    const totalCilindrosEnvio = document.getElementById('total-cilindros-envio');
    const envioRevisaoDl = document.getElementById('envio-revisao-dl');

    // Modal Retorno Completo
    const formRetorno = document.getElementById('form-retorno-reteste-completo');
    const retExpTotal = document.getElementById('ret-comp-exp-total');
    const retExpPerm = document.getElementById('ret-comp-exp-perm');
    const retExpFeedback = document.getElementById('ret-comp-exp-feedback');
    const retTara = document.getElementById('ret-comp-tara');
    const retTaraFeedback = document.getElementById('ret-comp-tara-feedback');
    const retResultado = document.getElementById('ret-comp-resultado');
    const grupoMotivoReprov = document.getElementById('grupo-motivo-reprovacao');
    const retMotivoReprov = document.getElementById('ret-comp-motivo-reprov');

    // Modal Retificação
    const formRetificacao = document.getElementById('form-retificacao-reteste');

    // Modal Baixa Patrimonial
    const formBaixa = document.getElementById('form-baixa-patrimonial');

    // Estado local
    let cilindrosSelecionados = new Map(); // id -> cilindroObj
    let cilindrosCache = [];
    let envioSelecionadoAtual = null;
    let taraAnteriorAtiva = null;
    const LIMITE_EXPANSAO_PCT = 10.0;
    const TOLERANCIA_TARA_PCT = 5.0;

    // =========================================================================
    // MODAIS: ABERTURA, FECHAMENTO E ESC
    // =========================================================================
    function abrirModal(id) {
        const m = document.getElementById(id);
        if (!m) return;
        m.classList.add('active');
        m.removeAttribute('hidden');
    }

    function fecharModal(id) {
        const m = document.getElementById(id);
        if (!m) return;
        m.classList.remove('active');
    }

    document.querySelectorAll('[data-fechar-modal]').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.getAttribute('data-fechar-modal');
            if (target) {
                fecharModal(target);
            } else {
                const overlay = btn.closest('.modal-overlay');
                if (overlay) overlay.classList.remove('active');
            }
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
        }
    });

    // =========================================================================
    // ABAS
    // =========================================================================
    function trocarAba(nome) {
        tabButtons.forEach(btn => {
            const ativa = btn.getAttribute('data-tab') === nome;
            btn.classList.toggle('active', ativa);
        });
        tabPanes.forEach(pane => {
            const ativa = pane.id === `aba-${nome}`;
            pane.classList.toggle('active', ativa);
            pane.classList.toggle('ds-hidden', !ativa);
        });
        if (window.location.hash !== `#aba-${nome}`) {
            history.replaceState(null, '', `#aba-${nome}`);
        }
        if (nome === 'vencimentos') carregarVencimentos();
        if (nome === 'envios') carregarEnvios();
    }

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => trocarAba(btn.getAttribute('data-tab')));
    });

    // =========================================================================
    // CARREGAR FILTROS AUXILIARES (GASES E MODELOS)
    // =========================================================================
    async function carregarFiltrosAuxiliares() {
        try {
            const [resGases, resModelos] = await Promise.all([
                Baros.api('/produtos/api/catalogo/gases/?page_size=100'),
                Baros.api('/produtos/api/catalogo/modelos/?page_size=100'),
            ]);
            const gases = extrairLista(resGases);
            const modelos = extrairLista(resModelos);

            if (filtroGas) {
                gases.forEach(g => {
                    const opt = document.createElement('option');
                    opt.value = g.id;
                    opt.textContent = `${g.sigla} - ${g.nome}`;
                    filtroGas.appendChild(opt);
                });
            }
            if (filtroModelo) {
                modelos.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.id;
                    opt.textContent = m.descricao;
                    filtroModelo.appendChild(opt);
                });
            }
        } catch (e) {
            // Não bloqueia carregamento principal
        }
    }

    // =========================================================================
    // ABA 1: VENCIMENTOS E SELEÇÃO MÚLTIPLA
    // =========================================================================
    function atualizarBotaoSelecionados() {
        const qtd = cilindrosSelecionados.size;
        if (countSelecionados) countSelecionados.textContent = String(qtd);
        if (btnEnviarSelecionados) {
            btnEnviarSelecionados.classList.toggle('ds-hidden', qtd === 0);
        }
    }

    async function carregarVencimentos() {
        if (!corpoVencimentos) return;
        skeletonVencimentos.classList.remove('ds-hidden');
        vazioVencimentos.classList.add('ds-hidden');
        erroVencimentos.classList.add('ds-hidden');
        corpoVencimentos.textContent = '';

        try {
            const params = new URLSearchParams();
            if (filtroSituacao && filtroSituacao.value) params.set('filtro', filtroSituacao.value);
            if (filtroGas && filtroGas.value) params.set('gas', filtroGas.value);
            if (filtroModelo && filtroModelo.value) params.set('modelo', filtroModelo.value);

            const res = await Baros.api(`/produtos/api/cilindros/relatorio-vencimentos/?${params.toString()}`);
            skeletonVencimentos.classList.add('ds-hidden');

            const cont = (res && res.contadores) || {};
            if (kpiVencidos) kpiVencidos.textContent = cont.vencidos ?? 0;
            if (kpi30d) kpi30d.textContent = cont.vencendo_30_dias ?? 0;
            if (kpi60d) kpi60d.textContent = cont.vencendo_60_dias ?? 0;
            if (kpi90d) kpi90d.textContent = cont.vencendo_90_dias ?? 0;
            if (kpiRequalificacao) kpiRequalificacao.textContent = cont.em_requalificacao ?? 0;

            const lista = (res && res.cilindros) || [];
            cilindrosCache = lista;

            if (!lista.length) {
                vazioVencimentos.classList.remove('ds-hidden');
                return;
            }

            const hojeIso = Baros.hojeISO();

            lista.forEach(c => {
                const tr = document.createElement('tr');
                const aptoEnvio = c.status === 'VAZIO_TRIAGEM' && !c.bloqueio_sanitario;

                const tdChk = document.createElement('td');
                const chk = document.createElement('input');
                chk.type = 'checkbox';
                chk.disabled = !aptoEnvio;
                chk.checked = cilindrosSelecionados.has(String(c.id));
                chk.title = aptoEnvio
                    ? 'Selecionar para envio ao reteste'
                    : 'Apenas cilindros em Vazio em Triagem sem bloqueio podem ser enviados';
                chk.addEventListener('change', () => {
                    if (chk.checked) {
                        cilindrosSelecionados.set(String(c.id), c);
                    } else {
                        cilindrosSelecionados.delete(String(c.id));
                    }
                    atualizarBotaoSelecionados();
                });
                tdChk.appendChild(chk);
                tr.appendChild(tdChk);

                const tdSerie = document.createElement('td');
                const strong = document.createElement('strong');
                strong.textContent = c.numero_serie_ogiva || '—';
                tdSerie.appendChild(strong);
                const divQr = document.createElement('div');
                divQr.className = 'text-muted text-sm font-mono';
                divQr.textContent = c.codigo_qr || '';
                tdSerie.appendChild(divQr);
                tr.appendChild(tdSerie);

                const tdMod = document.createElement('td');
                tdMod.textContent = `${c.modelo_descricao || '—'} (${c.gas_sigla || '—'})`;
                tr.appendChild(tdMod);

                const tdSt = document.createElement('td');
                tdSt.textContent = c.status_display || c.status;
                if (c.bloqueio_sanitario) {
                    const bSpan = document.createElement('span');
                    bSpan.className = 'badge badge-status-danger ml-1';
                    bSpan.textContent = 'Bloqueio Sanitário';
                    tdSt.appendChild(bSpan);
                }
                tr.appendChild(tdSt);

                const tdUlt = document.createElement('td');
                tdUlt.textContent = c.data_ultimo_reteste ? Baros.data(c.data_ultimo_reteste) : '—';
                tr.appendChild(tdUlt);

                const tdProx = document.createElement('td');
                tdProx.textContent = c.data_proximo_reteste ? Baros.data(c.data_proximo_reteste) : '—';
                tr.appendChild(tdProx);

                const tdSit = document.createElement('td');
                const badgeSit = document.createElement('span');
                const vencido = c.data_proximo_reteste && c.data_proximo_reteste < hojeIso;
                if (c.status === 'EM_REQUALIFICACAO') {
                    badgeSit.className = 'badge badge-status-info';
                    badgeSit.textContent = 'Em Requalificação';
                } else if (vencido) {
                    badgeSit.className = 'badge badge-status-danger';
                    badgeSit.textContent = 'Vencido';
                } else {
                    badgeSit.className = 'badge badge-status-approved';
                    badgeSit.textContent = 'No Prazo';
                }
                tdSit.appendChild(badgeSit);
                tr.appendChild(tdSit);

                const tdAcoes = document.createElement('td');
                tdAcoes.className = 'text-right';
                if (c.status === 'EM_REQUALIFICACAO' && c.envio_reteste_aberto) {
                    const btnRet = document.createElement('button');
                    btnRet.type = 'button';
                    btnRet.className = 'btn-primary btn-sm';
                    btnRet.textContent = 'Registrar Retorno';
                    btnRet.addEventListener('click', () => abrirModalRetornoCompleto(c, c.envio_reteste_aberto));
                    tdAcoes.appendChild(btnRet);
                } else if (config.podeEditarPatrimonio && c.status !== 'BAIXADO') {
                    const btnBaixa = document.createElement('button');
                    btnBaixa.type = 'button';
                    btnBaixa.className = 'btn-outline btn-sm';
                    btnBaixa.textContent = 'Dar Baixa';
                    btnBaixa.addEventListener('click', () => abrirModalBaixa(c, 'EXTRAVIO'));
                    tdAcoes.appendChild(btnBaixa);
                }
                tr.appendChild(tdAcoes);

                corpoVencimentos.appendChild(tr);
            });
        } catch (e) {
            skeletonVencimentos.classList.add('ds-hidden');
            erroVencimentos.classList.remove('ds-hidden');
            Baros.erro(e.mensagem || 'Erro ao carregar vencimentos.');
        }
    }

    if (chkTodos) {
        chkTodos.addEventListener('change', () => {
            cilindrosCache.forEach(c => {
                const apto = c.status === 'VAZIO_TRIAGEM' && !c.bloqueio_sanitario;
                if (!apto) return;
                if (chkTodos.checked) {
                    cilindrosSelecionados.set(String(c.id), c);
                } else {
                    cilindrosSelecionados.delete(String(c.id));
                }
            });
            atualizarBotaoSelecionados();
            carregarVencimentos();
        });
    }

    if (filtroSituacao) filtroSituacao.addEventListener('change', carregarVencimentos);
    if (filtroGas) filtroGas.addEventListener('change', carregarVencimentos);
    if (filtroModelo) filtroModelo.addEventListener('change', carregarVencimentos);
    if (btnRetryVencimentos) btnRetryVencimentos.addEventListener('click', carregarVencimentos);

    // =========================================================================
    // ABA 2: ENVIOS & DETALHE DE ITENS
    // =========================================================================
    async function carregarEnvios() {
        if (!corpoEnvios) return;
        skeletonEnvios.classList.remove('ds-hidden');
        vazioEnvios.classList.add('ds-hidden');
        erroEnvios.classList.add('ds-hidden');
        corpoEnvios.textContent = '';

        try {
            const res = await Baros.api('/produtos/api/patrimonio/envios-reteste/?page_size=100');
            const lista = extrairLista(res);
            skeletonEnvios.classList.add('ds-hidden');

            if (!lista.length) {
                vazioEnvios.classList.remove('ds-hidden');
                return;
            }

            lista.forEach(env => {
                const tr = document.createElement('tr');

                const tdId = document.createElement('td');
                tdId.textContent = `#${env.id}`;
                tr.appendChild(tdId);

                const tdOf = document.createElement('td');
                const strong = document.createElement('strong');
                strong.textContent = env.oficina_nome || '—';
                tdOf.appendChild(strong);
                const cnpjDiv = document.createElement('div');
                cnpjDiv.className = 'text-muted text-sm font-mono';
                cnpjDiv.textContent = env.oficina_cnpj || '';
                tdOf.appendChild(cnpjDiv);
                tr.appendChild(tdOf);

                const tdDoc = document.createElement('td');
                tdDoc.textContent = env.documento_envio || '—';
                tr.appendChild(tdDoc);

                const tdData = document.createElement('td');
                tdData.textContent = env.data_envio ? Baros.data(env.data_envio) : '—';
                tr.appendChild(tdData);

                const tdTot = document.createElement('td');
                tdTot.className = 'text-right';
                tdTot.textContent = String(env.total_cilindros ?? 0);
                tr.appendChild(tdTot);

                const tdPend = document.createElement('td');
                tdPend.className = 'text-right';
                const badgePend = document.createElement('span');
                const pendentes = Number(env.pendentes_retorno || 0);
                badgePend.className = 'badge ' + (pendentes > 0 ? 'badge-status-warning' : 'badge-status-approved');
                badgePend.textContent = pendentes > 0 ? `${pendentes} pendente(s)` : 'Concluído';
                tdPend.appendChild(badgePend);
                tr.appendChild(tdPend);

                const tdAcoes = document.createElement('td');
                tdAcoes.className = 'text-right';
                const btnVer = document.createElement('button');
                btnVer.type = 'button';
                btnVer.className = 'btn-outline btn-sm';
                btnVer.textContent = 'Ver Cilindros';
                btnVer.addEventListener('click', () => abrirDetalheEnvio(env));
                tdAcoes.appendChild(btnVer);
                tr.appendChild(tdAcoes);

                corpoEnvios.appendChild(tr);
            });

            if (envioSelecionadoAtual) {
                const atualizado = lista.find(e => e.id === envioSelecionadoAtual.id);
                if (atualizado) abrirDetalheEnvio(atualizado);
            }
        } catch (e) {
            skeletonEnvios.classList.add('ds-hidden');
            erroEnvios.classList.remove('ds-hidden');
            Baros.erro(e.mensagem || 'Erro ao carregar envios.');
        }
    }

    function abrirDetalheEnvio(envio) {
        envioSelecionadoAtual = envio;
        if (!cardDetalheEnvio) return;
        cardDetalheEnvio.classList.remove('ds-hidden');
        tituloDetalheEnvio.textContent = `Envio #${envio.id} — ${envio.oficina_nome}`;
        subtituloDetalheEnvio.textContent = `Data: ${Baros.data(envio.data_envio)} | Documento: ${envio.documento_envio || 'N/A'}`;
        corpoItensEnvio.textContent = '';

        (envio.itens || []).forEach(item => {
            const tr = document.createElement('tr');

            const tdSerie = document.createElement('td');
            const strong = document.createElement('strong');
            strong.textContent = item.cilindro_serie || '—';
            tdSerie.appendChild(strong);
            const divQr = document.createElement('div');
            divQr.className = 'text-muted text-sm font-mono';
            divQr.textContent = item.cilindro_qr || '';
            tdSerie.appendChild(divQr);
            tr.appendChild(tdSerie);

            const tdMod = document.createElement('td');
            tdMod.textContent = item.cilindro_modelo_descricao || '—';
            tr.appendChild(tdMod);

            const tdTara = document.createElement('td');
            tdTara.textContent = item.cilindro_tara_kg ? `${item.cilindro_tara_kg} kg` : 'Não aferida';
            tr.appendChild(tdTara);

            const tdRet = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = 'badge ' + (item.retornado ? 'badge-status-approved' : 'badge-status-warning');
            badge.textContent = item.retornado ? 'Retornado' : 'Aguardando Retorno';
            tdRet.appendChild(badge);
            tr.appendChild(tdRet);

            const tdAcoes = document.createElement('td');
            tdAcoes.className = 'text-right';
            if (!item.retornado) {
                const btnReg = document.createElement('button');
                btnReg.type = 'button';
                btnReg.className = 'btn-primary btn-sm';
                btnReg.textContent = 'Registrar Retorno';
                btnReg.addEventListener('click', () => {
                    abrirModalRetornoCompleto({
                        id: item.cilindro,
                        numero_serie_ogiva: item.cilindro_serie,
                        codigo_qr: item.cilindro_qr,
                        tara_real_kg: item.cilindro_tara_kg,
                    }, {
                        envio_id: envio.id,
                        oficina_nome: envio.oficina_nome,
                        oficina_cnpj: envio.oficina_cnpj,
                    });
                });
                tdAcoes.appendChild(btnReg);
            } else if (item.reteste_vinculado) {
                const btnRetif = document.createElement('button');
                btnRetif.type = 'button';
                btnRetif.className = 'btn-outline btn-sm';
                btnRetif.textContent = 'Retificar';
                btnRetif.addEventListener('click', () => abrirModalRetificacao(item.reteste_vinculado));
                tdAcoes.appendChild(btnRetif);
            }
            tr.appendChild(tdAcoes);

            corpoItensEnvio.appendChild(tr);
        });
    }

    if (btnFecharDetalheEnvio) {
        btnFecharDetalheEnvio.addEventListener('click', () => {
            envioSelecionadoAtual = null;
            cardDetalheEnvio.classList.add('ds-hidden');
        });
    }
    if (btnRetryEnvios) btnRetryEnvios.addEventListener('click', carregarEnvios);

    // =========================================================================
    // STEPPER: NOVO ENVIO EM LOTE (BIPAGEM + REVISÃO)
    // =========================================================================
    function renderizarChipsEnvio() {
        if (!listaChipsEnvio) return;
        listaChipsEnvio.textContent = '';
        cilindrosSelecionados.forEach((c, id) => {
            const chip = document.createElement('span');
            chip.className = 'ds-chip';
            const txt = document.createElement('span');
            txt.textContent = `${c.numero_serie_ogiva} (${c.codigo_qr || 'S/QR'})`;
            chip.appendChild(txt);

            const btnRem = document.createElement('button');
            btnRem.type = 'button';
            btnRem.className = 'ds-chip-remove';
            btnRem.textContent = '×';
            btnRem.ariaLabel = `Remover ${c.numero_serie_ogiva}`;
            btnRem.addEventListener('click', () => {
                cilindrosSelecionados.delete(id);
                renderizarChipsEnvio();
                atualizarBotaoSelecionados();
            });
            chip.appendChild(btnRem);
            listaChipsEnvio.appendChild(chip);
        });
        if (totalCilindrosEnvio) totalCilindrosEnvio.textContent = String(cilindrosSelecionados.size);
    }

    async function adicionarCilindroPorBipe() {
        if (!bipeInput) return;
        const termo = bipeInput.value.trim();
        if (!termo) return;
        bipeFeedback.classList.remove('ds-alerta-texto');

        try {
            const res = await Baros.api(`/produtos/api/cilindros/?search=${encodeURIComponent(termo)}&page_size=5`);
            const lista = extrairLista(res);
            const cil = lista.find(
                x => (x.codigo_qr && x.codigo_qr.toLowerCase() === termo.toLowerCase())
                    || (x.numero_serie_ogiva && x.numero_serie_ogiva.toLowerCase() === termo.toLowerCase())
            ) || lista[0];

            if (!cil) {
                bipeFeedback.textContent = `Cilindro "${termo}" não encontrado.`;
                bipeFeedback.classList.add('ds-alerta-texto');
                return;
            }
            if (cil.status !== 'VAZIO_TRIAGEM') {
                bipeFeedback.textContent = `Recusado: ${cil.numero_serie_ogiva} está em "${cil.status_display || cil.status}" (exige Vazio em Triagem).`;
                bipeFeedback.classList.add('ds-alerta-texto');
                return;
            }
            if (cil.bloqueio_sanitario) {
                bipeFeedback.textContent = `Recusado: ${cil.numero_serie_ogiva} possui bloqueio sanitário ativo.`;
                bipeFeedback.classList.add('ds-alerta-texto');
                return;
            }
            if (cilindrosSelecionados.has(String(cil.id))) {
                bipeFeedback.textContent = `Cilindro ${cil.numero_serie_ogiva} já adicionado à remessa.`;
                bipeInput.value = '';
                return;
            }

            cilindrosSelecionados.set(String(cil.id), cil);
            renderizarChipsEnvio();
            atualizarBotaoSelecionados();
            bipeFeedback.textContent = `Adicionado: ${cil.numero_serie_ogiva}.`;
            bipeInput.value = '';
            bipeInput.focus();
        } catch (e) {
            bipeFeedback.textContent = e.mensagem || 'Erro ao buscar cilindro.';
            bipeFeedback.classList.add('ds-alerta-texto');
        }
    }

    if (btnAddBipe) btnAddBipe.addEventListener('click', adicionarCilindroPorBipe);
    if (bipeInput) {
        bipeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                adicionarCilindroPorBipe();
            }
        });
    }

    function montarRevisaoEnvio() {
        if (!envioRevisaoDl) return;
        envioRevisaoDl.textContent = '';
        const itens = [
            ['Requalificadora', document.getElementById('envio-oficina-nome').value],
            ['CNPJ', document.getElementById('envio-oficina-cnpj').value],
            ['Documento', document.getElementById('envio-documento').value || '—'],
            ['Data de Envio', Baros.data(document.getElementById('envio-data').value)],
            ['Total de Cilindros', `${cilindrosSelecionados.size} cilindro(s)`],
        ];
        itens.forEach(([k, v]) => {
            const dt = document.createElement('dt');
            dt.textContent = k;
            const dd = document.createElement('dd');
            dd.textContent = v;
            envioRevisaoDl.appendChild(dt);
            envioRevisaoDl.appendChild(dd);
        });
    }

    const stepperEnvio = formNovoEnvio ? Baros.Stepper('#container-stepper-envio', {
        validar: (etapa) => {
            if (etapa === 1) {
                return Baros.validarCampos('#container-stepper-envio [data-step="1"]');
            }
            if (etapa === 2) {
                if (cilindrosSelecionados.size === 0) {
                    Baros.aviso('Adicione ou selecione ao menos um cilindro para envio.');
                    return false;
                }
                return true;
            }
            return true;
        },
        aoMudar: (etapa) => {
            if (etapa === 3) montarRevisaoEnvio();
        },
    }) : null;

    function abrirModalNovoEnvio() {
        if (!formNovoEnvio) return;
        formNovoEnvio.reset();
        const dtInput = document.getElementById('envio-data');
        if (dtInput) dtInput.value = Baros.hojeISO();
        if (stepperEnvio) stepperEnvio.irPara(1);
        renderizarChipsEnvio();
        abrirModal('modal-novo-envio');
    }

    if (btnAbrirNovoEnvio) btnAbrirNovoEnvio.addEventListener('click', abrirModalNovoEnvio);
    if (btnEnviarSelecionados) btnEnviarSelecionados.addEventListener('click', abrirModalNovoEnvio);

    if (formNovoEnvio) {
        formNovoEnvio.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (cilindrosSelecionados.size === 0) {
                Baros.aviso('Selecione ao menos um cilindro.');
                return;
            }
            const btnSubmit = formNovoEnvio.querySelector('[data-stepper-confirmar]');
            const restore = Baros.carregando(btnSubmit, 'Enviando...');
            try {
                await Baros.api('/produtos/api/patrimonio/envios-reteste/', {
                    method: 'POST',
                    body: {
                        oficina_nome: document.getElementById('envio-oficina-nome').value.trim(),
                        oficina_cnpj: document.getElementById('envio-oficina-cnpj').value.trim(),
                        documento_envio: document.getElementById('envio-documento').value.trim(),
                        data_envio: document.getElementById('envio-data').value,
                        observacoes: document.getElementById('envio-observacoes').value.trim(),
                        cilindro_ids: Array.from(cilindrosSelecionados.keys()),
                    },
                });
                Baros.sucesso('Remessa para reteste registrada com sucesso!');
                cilindrosSelecionados.clear();
                atualizarBotaoSelecionados();
                fecharModal('modal-novo-envio');
                carregarVencimentos();
                carregarEnvios();
            } catch (err) {
                Baros.mostrarErrosApi(formNovoEnvio, err);
                Baros.erro(err.mensagem || 'Erro ao registrar envio para reteste.');
            } finally {
                restore();
            }
        });
    }

    // =========================================================================
    // MODAL: RETORNO COMPLETO DE RETESTE (EXPANSÃO + TARA + LAUDO PDF)
    // =========================================================================
    function atualizarCalculoExpansao() {
        if (!retExpTotal || !retExpPerm || !retExpFeedback) return;
        const et = Number(retExpTotal.value);
        const ep = Number(retExpPerm.value);
        retExpFeedback.classList.remove('ds-alerta-texto');

        if (!et || et <= 0 || retExpPerm.value === '') {
            retExpFeedback.textContent = 'Informe expansão total e permanente para cálculo ao vivo.';
            return;
        }
        const pct = (ep / et) * 100;
        const fmtPct = pct.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
        if (pct > LIMITE_EXPANSAO_PCT) {
            retExpFeedback.textContent = `Expansão permanente de ${fmtPct}% supera o limite normativo de 10% (ABNT NBR 12274) — REPROVAÇÃO MANDATÓRIA.`;
            retExpFeedback.classList.add('ds-alerta-texto');
            if (retResultado) {
                retResultado.value = 'REPROVADO_CONDENADO';
                atualizarVisibilidadeMotivoCondenacao();
            }
        } else {
            retExpFeedback.textContent = `Expansão permanente: ${fmtPct}% (dentro do limite de 10% — Aprovado pela norma).`;
        }
    }

    function atualizarCalculoTara() {
        if (!retTara || !retTaraFeedback) return;
        retTaraFeedback.classList.remove('ds-alerta-texto');
        if (!taraAnteriorAtiva) {
            retTaraFeedback.textContent = 'Sem tara anterior registrada para comparação.';
            return;
        }
        if (!retTara.value) {
            retTaraFeedback.textContent = `Tara anterior: ${taraAnteriorAtiva} kg (tolerância 5%).`;
            return;
        }
        const nova = Number(retTara.value);
        const pct = ((nova - taraAnteriorAtiva) / taraAnteriorAtiva) * 100;
        const fmtPct = Math.abs(pct).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        const sinal = pct >= 0 ? '+' : '-';
        if (Math.abs(pct) > TOLERANCIA_TARA_PCT) {
            retTaraFeedback.textContent = `Variação de ${sinal}${fmtPct}% acima da tolerância de 5%: será gerado alerta no laudo.`;
            retTaraFeedback.classList.add('ds-alerta-texto');
        } else {
            retTaraFeedback.textContent = `Variação de ${sinal}${fmtPct}% (dentro da tolerância de 5%).`;
        }
    }

    function atualizarVisibilidadeMotivoCondenacao() {
        if (!retResultado || !grupoMotivoReprov) return;
        const condenado = retResultado.value === 'REPROVADO_CONDENADO';
        grupoMotivoReprov.classList.toggle('ds-hidden', !condenado);
        if (retMotivoReprov) retMotivoReprov.required = condenado;
    }

    if (retExpTotal) retExpTotal.addEventListener('input', atualizarCalculoExpansao);
    if (retExpPerm) retExpPerm.addEventListener('input', atualizarCalculoExpansao);
    if (retTara) retTara.addEventListener('input', atualizarCalculoTara);
    if (retResultado) retResultado.addEventListener('change', atualizarVisibilidadeMotivoCondenacao);

    function abrirModalRetornoCompleto(cilindro, envioInfo) {
        if (!formRetorno) return;
        formRetorno.reset();
        document.getElementById('ret-comp-cilindro-id').value = cilindro.id;
        document.getElementById('ret-comp-envio-id').value = (envioInfo && envioInfo.envio_id) || '';
        document.getElementById('ret-comp-cilindro-label').value = `${cilindro.numero_serie_ogiva} (${cilindro.codigo_qr || 'S/QR'})`;
        document.getElementById('ret-comp-data').value = Baros.hojeISO();
        if (envioInfo) {
            document.getElementById('ret-comp-oficina-nome').value = envioInfo.oficina_nome || '';
            document.getElementById('ret-comp-oficina-cnpj').value = envioInfo.oficina_cnpj || '';
        }
        taraAnteriorAtiva = cilindro.tara_real_kg ? Number(cilindro.tara_real_kg) : null;
        if (taraAnteriorAtiva && retTara) retTara.value = String(taraAnteriorAtiva);
        atualizarCalculoExpansao();
        atualizarCalculoTara();
        atualizarVisibilidadeMotivoCondenacao();
        abrirModal('modal-retorno-reteste-completo');
    }

    if (formRetorno) {
        formRetorno.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formRetorno)) return;
            const btn = document.getElementById('btn-salvar-retorno-completo');
            const restore = Baros.carregando(btn, 'Registrando...');

            try {
                const fd = new FormData(formRetorno);
                const res = await Baros.api('/produtos/api/cilindros/registrar-retorno-reteste/', {
                    method: 'POST',
                    body: fd,
                });
                fecharModal('modal-retorno-reteste-completo');

                const cilAtualizado = res && res.cilindro;
                const resultado = retResultado ? retResultado.value : 'APROVADO';
                if (resultado === 'REPROVADO_CONDENADO') {
                    if (cilAtualizado && cilAtualizado.status === 'BAIXADO') {
                        Baros.aviso('Cilindro condenado e baixado por Inutilização Técnica com bloqueio sanitário.');
                    } else if (cilAtualizado) {
                        if (RETESTES_CONFIG.podeEditarPatrimonio) {
                            Baros.aviso('Cilindro condenado no reteste. Complete a baixa patrimonial a seguir.');
                            abrirModalBaixa(cilAtualizado, 'INUTILIZACAO_TECNICA');
                        } else {
                            Baros.aviso('Cilindro condenado no reteste. Um Administrador ou Gerente precisa registrar a baixa patrimonial.');
                        }
                    }
                } else {
                    Baros.sucesso('Retorno aprovado registrado e validade renovada!');
                }

                carregarVencimentos();
                carregarEnvios();
            } catch (err) {
                Baros.mostrarErrosApi(formRetorno, err);
                Baros.erro(err.mensagem || 'Erro ao registrar retorno de reteste.');
            } finally {
                restore();
            }
        });
    }

    // =========================================================================
    // MODAL: RETIFICAÇÃO DE RETESTE
    // =========================================================================
    function abrirModalRetificacao(retesteId) {
        if (!formRetificacao) return;
        formRetificacao.reset();
        document.getElementById('retif-reteste-id').value = retesteId;
        abrirModal('modal-retificacao-reteste');
    }

    if (formRetificacao) {
        formRetificacao.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formRetificacao)) return;
            const retesteId = document.getElementById('retif-reteste-id').value;
            const payload = {
                motivo: document.getElementById('retif-motivo').value.trim(),
            };
            const cert = document.getElementById('retif-certificado').value.trim();
            const inm = document.getElementById('retif-inmetro').value.trim();
            if (cert) payload.numero_certificado = cert;
            if (inm) payload.registro_inmetro = inm;

            try {
                await Baros.api(`/produtos/api/patrimonio/retestes/${retesteId}/retificar/`, {
                    method: 'POST',
                    body: payload,
                });
                Baros.sucesso('Retificação formal registrada com sucesso.');
                fecharModal('modal-retificacao-reteste');
                carregarEnvios();
            } catch (err) {
                Baros.erro(err.mensagem || 'Erro ao emitir retificação.');
            }
        });
    }

    // =========================================================================
    // MODAL: BAIXA PATRIMONIAL (03.2)
    // =========================================================================
    function abrirModalBaixa(cilindro, tipoPadrao) {
        if (!formBaixa) return;
        formBaixa.reset();
        document.getElementById('baixa-cilindro-id').value = cilindro.id;
        document.getElementById('baixa-cilindro-label').value = `${cilindro.numero_serie_ogiva} (${cilindro.codigo_qr || 'S/QR'})`;
        document.getElementById('baixa-data').value = Baros.hojeISO();
        if (tipoPadrao) document.getElementById('baixa-tipo').value = tipoPadrao;
        abrirModal('modal-baixa-patrimonial');
    }

    if (formBaixa) {
        formBaixa.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formBaixa)) return;

            const confirmado = await Baros.confirmar({
                titulo: 'Confirmar Baixa Patrimonial?',
                texto: 'Esta ação altera o cilindro para o estado terminal BAIXADO. Somente a gestão poderá estornar posteriormente.',
                botao: 'Sim, Baixar Ativo',
                perigo: true,
            });
            if (!confirmado) return;

            const btn = document.getElementById('btn-confirmar-baixa');
            const restore = Baros.carregando(btn, 'Baixando...');
            try {
                await Baros.api('/produtos/api/patrimonio/baixas/', {
                    method: 'POST',
                    body: {
                        cilindro: document.getElementById('baixa-cilindro-id').value,
                        tipo: document.getElementById('baixa-tipo').value,
                        data: document.getElementById('baixa-data').value,
                        documento_ref: document.getElementById('baixa-documento-ref').value.trim(),
                        valor_recebido: document.getElementById('baixa-valor-recebido').value || '0.00',
                        motivo: document.getElementById('baixa-motivo').value.trim(),
                    },
                });
                Baros.sucesso('Baixa patrimonial registrada com sucesso.');
                fecharModal('modal-baixa-patrimonial');
                carregarVencimentos();
            } catch (err) {
                Baros.mostrarErrosApi(formBaixa, err);
                Baros.erro(err.mensagem || 'Não foi possível registrar a baixa.');
            } finally {
                restore();
            }
        });
    }

    // =========================================================================
    // INICIALIZAÇÃO FINAL (após todas as declarações)
    // =========================================================================
    carregarFiltrosAuxiliares();
    const hashAba = (window.location.hash || '').replace('#aba-', '');
    const abaInicial = ['vencimentos', 'envios'].includes(hashAba) ? hashAba : 'vencimentos';
    trocarAba(abaInicial);
});

