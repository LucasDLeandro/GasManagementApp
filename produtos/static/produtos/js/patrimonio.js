// Gestão de Patrimônio — Baros Design System v1
document.addEventListener('DOMContentLoaded', () => {
    const config = window.PATRIMONIO_CONFIG || { podeEditar: false, temFinanceiro: false };

    // =========================================================================
    // NAVEGAÇÃO DE ABAS
    // =========================================================================
    const botoesAba = document.querySelectorAll('.tabs-nav .tab-btn');
    const paineisAba = document.querySelectorAll('.tab-pane');

    function trocarAba(abaNome) {
        botoesAba.forEach(btn => {
            const ativo = btn.dataset.tab === abaNome;
            btn.classList.toggle('active', ativo);
            btn.setAttribute('aria-selected', ativo ? 'true' : 'false');
        });
        paineisAba.forEach(pane => {
            const ativo = pane.id === 'aba-' + abaNome;
            pane.classList.toggle('active', ativo);
            pane.classList.toggle('ds-hidden', !ativo);
        });

        // Atualiza URL sem recarregar a página
        const url = new URL(window.location);
        url.searchParams.set('aba', abaNome);
        window.history.replaceState({}, '', url);

        // Carrega dados da aba selecionada
        carregarAba(abaNome);
    }

    botoesAba.forEach(btn => {
        btn.addEventListener('click', () => trocarAba(btn.dataset.tab));
    });

    // Detecta aba inicial pela URL ou padrão 'ativos'
    const paramAba = new URLSearchParams(window.location.search).get('aba');
    const abaInicial = ['ativos', 'lotes', 'classes', 'fabricantes', 'indenizacao'].includes(paramAba) ? paramAba : 'ativos';
    trocarAba(abaInicial);

    function carregarAba(aba) {
        switch (aba) {
            case 'ativos':
                carregarAtivos();
                break;
            case 'lotes':
                carregarLotes();
                break;
            case 'classes':
                carregarClasses();
                break;
            case 'fabricantes':
                carregarFabricantes();
                break;
            case 'indenizacao':
                carregarIndenizacoes();
                carregarCilindrosSimulador();
                break;
        }
    }

    // Auxiliar: extrai lista de resposta paginada
    const extrairLista = (res) => (Array.isArray(res) ? res : (res && res.results) || []);

    // Cache local de cadastros para selects
    const cache = {
        classes: [],
        modelos: [],
        gases: [],
        cilindros: [],
        contasContabeis: [],
    };

    // =========================================================================
    // MODAIS: ABERTURA, FECHAMENTO E TECLA ESC
    // =========================================================================
    function abrirModal(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        modal.classList.add('active');
        const primeiroCampo = modal.querySelector('input:not([type=hidden]), select');
        if (primeiroCampo) primeiroCampo.focus();
    }

    function fecharModal(modal) {
        if (!modal) return;
        modal.classList.remove('active');
        const form = modal.querySelector('form');
        if (form) {
            form.reset();
            form.querySelectorAll('.ds-field-error').forEach(el => el.remove());
            form.querySelectorAll('.ds-invalid').forEach(el => el.classList.remove('ds-invalid'));
        }
    }

    document.querySelectorAll('.modal-overlay [data-fechar-modal]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const modal = e.target.closest('.modal-overlay');
            fecharModal(modal);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modalAberto = document.querySelector('.modal-overlay.active');
            if (modalAberto) fecharModal(modalAberto);
        }
    });

    // =========================================================================
    // 1. ABA ATIVOS IMOBILIZADOS
    // =========================================================================
    const corpoTabelaAtivos = document.getElementById('corpo-tabela-ativos');
    const skeletonAtivos = document.getElementById('skeleton-ativos');
    const vazioAtivos = document.getElementById('vazio-ativos');
    const erroAtivos = document.getElementById('erro-ativos');
    const filtroAtivoClasse = document.getElementById('filtro-ativo-classe');
    const filtroAtivoStatus = document.getElementById('filtro-ativo-status');
    const buscaAtivo = document.getElementById('busca-ativo');

    async function carregarAtivos() {
        if (!corpoTabelaAtivos) return;
        skeletonAtivos.classList.remove('ds-hidden');
        vazioAtivos.classList.add('ds-hidden');
        erroAtivos.classList.add('ds-hidden');
        corpoTabelaAtivos.textContent = '';

        try {
            // Busca dados e métricas em paralelo
            const params = new URLSearchParams();
            if (filtroAtivoClasse && filtroAtivoClasse.value) params.set('classe', filtroAtivoClasse.value);
            if (filtroAtivoStatus && filtroAtivoStatus.value) params.set('status', filtroAtivoStatus.value);
            params.set('page_size', '200');

            const [ativosRes, resumoRes] = await Promise.all([
                Baros.api('/produtos/api/patrimonio/ativos/?' + params.toString()),
                Baros.api('/produtos/api/patrimonio/ativos/resumo/?' + params.toString()).catch(() => null),
            ]);

            const ativos = extrairLista(ativosRes);

            // Atualiza métricas
            if (resumoRes) {
                const elAq = document.querySelector('#metrica-total-aquisicao [data-metric-value]');
                const elDep = document.querySelector('#metrica-total-depreciacao [data-metric-value]');
                const elLiq = document.querySelector('#metrica-total-liquido [data-metric-value]');
                if (elAq) elAq.textContent = Baros.moeda(resumoRes.total_aquisicao);
                if (elDep) elDep.textContent = Baros.moeda(resumoRes.total_depreciacao);
                if (elLiq) elLiq.textContent = Baros.moeda(resumoRes.total_liquido);
            }

            skeletonAtivos.classList.add('ds-hidden');

            const termo = (buscaAtivo && buscaAtivo.value.trim().toLowerCase()) || '';
            const filtrados = ativos.filter(a => {
                if (!termo) return true;
                return (a.numero_patrimonio || '').toLowerCase().includes(termo)
                    || (a.descricao || '').toLowerCase().includes(termo);
            });

            if (filtrados.length === 0) {
                vazioAtivos.classList.remove('ds-hidden');
                return;
            }

            filtrados.forEach(ativo => {
                const tr = document.createElement('tr');

                // Nº Patrimônio
                const tdPat = document.createElement('td');
                tdPat.className = 'font-mono';
                tdPat.textContent = ativo.numero_patrimonio || '—';
                tr.appendChild(tdPat);

                // Descrição
                const tdDesc = document.createElement('td');
                tdDesc.textContent = ativo.descricao || '—';
                tr.appendChild(tdDesc);

                // Classe
                const tdClasse = document.createElement('td');
                tdClasse.textContent = ativo.classe_nome || ativo.classe_codigo || '—';
                tr.appendChild(tdClasse);

                // Status
                const tdStatus = document.createElement('td');
                const badge = document.createElement('span');
                const st = ativo.status || 'EM_USO';
                badge.className = 'badge ' + (st === 'EM_USO' ? 'badge-status-approved' : (st === 'VENDIDO' ? 'badge-status-transit' : 'badge-status-danger'));
                badge.textContent = ativo.status_display || st;
                tdStatus.appendChild(badge);
                tr.appendChild(tdStatus);

                // Valor Aquisição
                const tdAq = document.createElement('td');
                tdAq.className = 'text-right font-mono';
                tdAq.textContent = Baros.moeda(ativo.valor_aquisicao);
                tr.appendChild(tdAq);

                // Depreciação Acumulada
                const tdDep = document.createElement('td');
                tdDep.className = 'text-right font-mono';
                tdDep.textContent = Baros.moeda(ativo.depreciacao_acumulada_rs);
                tr.appendChild(tdDep);

                // Valor Líquido
                const tdLiq = document.createElement('td');
                tdLiq.className = 'text-right font-mono';
                tdLiq.textContent = Baros.moeda(ativo.valor_contabil_liquido_atual);
                tr.appendChild(tdLiq);

                // Ações
                if (config.podeEditar) {
                    const tdAcoes = document.createElement('td');
                    tdAcoes.className = 'text-right';
                    const btnExcluir = document.createElement('button');
                    btnExcluir.type = 'button';
                    btnExcluir.className = 'btn-outline btn-sm btn-danger';
                    btnExcluir.textContent = 'Excluir';
                    btnExcluir.addEventListener('click', () => excluirAtivo(ativo));
                    tdAcoes.appendChild(btnExcluir);
                    tr.appendChild(tdAcoes);
                }

                corpoTabelaAtivos.appendChild(tr);
            });
        } catch (e) {
            skeletonAtivos.classList.add('ds-hidden');
            erroAtivos.classList.remove('ds-hidden');
            Baros.erro(e.mensagem || 'Não foi possível carregar os ativos imobilizados.');
        }
    }

    async function excluirAtivo(ativo) {
        const confirmado = await Baros.confirmar({
            titulo: 'Excluir ativo imobilizado',
            texto: `Deseja excluir permanentemente o ativo "${ativo.numero_patrimonio} - ${ativo.descricao}"?`,
            botao: 'Excluir ativo',
            perigo: true,
        });
        if (!confirmado) return;

        try {
            await Baros.api(`/produtos/api/patrimonio/ativos/${ativo.id}/`, { method: 'DELETE' });
            Baros.sucesso('Ativo imobilizado excluído com sucesso.');
            carregarAtivos();
        } catch (e) {
            Baros.erro(e.mensagem || 'Não foi possível excluir o ativo imobilizado.');
        }
    }

    if (filtroAtivoClasse) filtroAtivoClasse.addEventListener('change', carregarAtivos);
    if (filtroAtivoStatus) filtroAtivoStatus.addEventListener('change', carregarAtivos);
    if (buscaAtivo) buscaAtivo.addEventListener('input', carregarAtivos);

    // Modal Novo Ativo Imobilizado
    const btnNovoAtivo = document.getElementById('btn-novo-ativo');
    const formAtivo = document.getElementById('form-ativo-imobilizado');
    if (btnNovoAtivo && formAtivo) {
        btnNovoAtivo.addEventListener('click', async () => {
            await garantirClassesCarregadas();
            popularSelect(formAtivo.classe, cache.classes, c => `${c.codigo} - ${c.nome}`);
            abrirModal('modal-ativo-imobilizado');
        });

        formAtivo.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formAtivo)) return;

            const btn = document.getElementById('btn-salvar-ativo');
            const restaurar = Baros.carregando(btn, 'Salvando...');
            try {
                const dados = Baros.dadosDoForm(formAtivo);
                await Baros.api('/produtos/api/patrimonio/ativos/', {
                    method: 'POST',
                    body: dados,
                });
                Baros.sucesso('Ativo imobilizado cadastrado com sucesso.');
                fecharModal(document.getElementById('modal-ativo-imobilizado'));
                carregarAtivos();
            } catch (err) {
                Baros.mostrarErrosApi(formAtivo, err);
            } finally {
                restaurar();
            }
        });
    }

    // =========================================================================
    // 2. ABA LOTES DE AQUISIÇÃO
    // =========================================================================
    const corpoTabelaLotes = document.getElementById('corpo-tabela-lotes');
    const skeletonLotes = document.getElementById('skeleton-lotes');
    const vazioLotes = document.getElementById('vazio-lotes');
    const erroLotes = document.getElementById('erro-lotes');
    const buscaLote = document.getElementById('busca-lote');

    async function carregarLotes() {
        if (!corpoTabelaLotes) return;
        skeletonLotes.classList.remove('ds-hidden');
        vazioLotes.classList.add('ds-hidden');
        erroLotes.classList.add('ds-hidden');
        corpoTabelaLotes.textContent = '';

        try {
            const res = await Baros.api('/produtos/api/patrimonio/lotes/?page_size=200');
            const lotes = extrairLista(res);
            skeletonLotes.classList.add('ds-hidden');

            const termo = (buscaLote && buscaLote.value.trim().toLowerCase()) || '';
            const filtrados = lotes.filter(l => {
                if (!termo) return true;
                return (l.fornecedor_nome || '').toLowerCase().includes(termo)
                    || (l.chave_nfe || '').toLowerCase().includes(termo);
            });

            if (filtrados.length === 0) {
                vazioLotes.classList.remove('ds-hidden');
                return;
            }

            filtrados.forEach(lote => {
                const tr = document.createElement('tr');

                // Data
                const tdData = document.createElement('td');
                tdData.textContent = Baros.data(lote.data_aquisicao);
                tr.appendChild(tdData);

                // Fornecedor
                const tdForn = document.createElement('td');
                tdForn.textContent = lote.fornecedor_nome || '—';
                tr.appendChild(tdForn);

                // Chave NF-e
                const tdNfe = document.createElement('td');
                tdNfe.className = 'font-mono';
                tdNfe.textContent = lote.chave_nfe ? `${lote.chave_nfe.slice(0, 8)}...${lote.chave_nfe.slice(-4)}` : '—';
                tdNfe.title = lote.chave_nfe || '';
                tr.appendChild(tdNfe);

                // Classe
                const tdClasse = document.createElement('td');
                tdClasse.textContent = lote.classe_nome || lote.classe_codigo || '—';
                tr.appendChild(tdClasse);

                // Quantidade
                const tdQtd = document.createElement('td');
                tdQtd.className = 'text-right font-mono';
                tdQtd.textContent = lote.quantidade;
                tr.appendChild(tdQtd);

                // Vinculados
                const tdVinc = document.createElement('td');
                tdVinc.className = 'text-right font-mono';
                tdVinc.textContent = lote.total_cilindros_vinculados || 0;
                tr.appendChild(tdVinc);

                // Valor Unitário
                const tdVlUn = document.createElement('td');
                tdVlUn.className = 'text-right font-mono';
                tdVlUn.textContent = Baros.moeda(lote.valor_unitario);
                tr.appendChild(tdVlUn);

                // Valor Total
                const tdVlTot = document.createElement('td');
                tdVlTot.className = 'text-right font-mono';
                tdVlTot.textContent = Baros.moeda(lote.valor_total);
                tr.appendChild(tdVlTot);

                // Ações
                if (config.podeEditar) {
                    const tdAcoes = document.createElement('td');
                    tdAcoes.className = 'text-right';

                    const btnExcluir = document.createElement('button');
                    btnExcluir.type = 'button';
                    btnExcluir.className = 'btn-outline btn-sm btn-danger';
                    btnExcluir.textContent = 'Excluir';
                    btnExcluir.addEventListener('click', () => excluirLote(lote));
                    tdAcoes.appendChild(btnExcluir);

                    tr.appendChild(tdAcoes);
                }

                corpoTabelaLotes.appendChild(tr);
            });
        } catch (e) {
            skeletonLotes.classList.add('ds-hidden');
            erroLotes.classList.remove('ds-hidden');
            Baros.erro(e.mensagem || 'Não foi possível carregar os lotes de aquisição.');
        }
    }

    async function excluirLote(lote) {
        const confirmado = await Baros.confirmar({
            titulo: 'Excluir lote de aquisição',
            texto: `Deseja excluir o lote de aquisição do fornecedor "${lote.fornecedor_nome}" (${lote.quantidade} cilindros)?`,
            botao: 'Excluir lote',
            perigo: true,
        });
        if (!confirmado) return;

        try {
            await Baros.api(`/produtos/api/patrimonio/lotes/${lote.id}/`, { method: 'DELETE' });
            Baros.sucesso('Lote de aquisição excluído.');
            carregarLotes();
        } catch (e) {
            Baros.erro(e.mensagem || 'Não foi possível excluir o lote de aquisição.');
        }
    }

    if (buscaLote) buscaLote.addEventListener('input', carregarLotes);

    // Stepper Novo Lote de Aquisição
    const btnNovoLote = document.getElementById('btn-novo-lote');
    const formLote = document.getElementById('form-lote-aquisicao');
    const containerStepperLote = document.getElementById('container-stepper-lote');
    let stepperLoteInstancia = null;

    if (btnNovoLote && formLote && containerStepperLote) {
        const btnVoltarLote = containerStepperLote.querySelector('[data-stepper-voltar]');
        const btnProximoLote = containerStepperLote.querySelector('[data-stepper-proximo]');
        const btnConfirmarLote = containerStepperLote.querySelector('[data-stepper-confirmar]');

        function montarRevisaoLote() {
            const dl = document.getElementById('lote-revisao-dl');
            if (!dl) return;
            dl.textContent = '';

            const classeTexto = formLote.classe.selectedOptions[0] ? formLote.classe.selectedOptions[0].text : '';
            const linhas = [
                ['Chave da NF-e', formLote.chave_nfe.value || 'Não informada'],
                ['Fornecedor', formLote.fornecedor_nome.value + (formLote.fornecedor_documento.value ? ' · ' + formLote.fornecedor_documento.value : '')],
                ['Data de aquisição', Baros.data(formLote.data_aquisicao.value)],
                ['Quantidade', formLote.quantidade.value + ' cilindros'],
                ['Valor Total', Baros.moeda(formLote.valor_total.value)],
                ['Valor Unitário', Baros.moeda(formLote.valor_unitario.value)],
                ['Classe de Ativo', classeTexto],
            ];

            linhas.forEach(([rotulo, valor]) => {
                const dt = document.createElement('dt');
                dt.textContent = rotulo;
                const dd = document.createElement('dd');
                dd.textContent = valor || '—';
                dl.appendChild(dt);
                dl.appendChild(dd);
            });
        }

        function validarEtapaLote(etapa) {
            const ok = Baros.validarCampos(`#container-stepper-lote .ds-step-pane[data-step="${etapa}"]`);
            if (!ok) return false;

            if (etapa === 1 && formLote.chave_nfe.value.trim()) {
                const chave = formLote.chave_nfe.value.trim();
                if (!/^\d{44}$/.test(chave)) {
                    Baros.mostrarErrosApi(formLote, { campos: { chave_nfe: 'A chave de NF-e deve conter exatamente 44 dígitos numéricos.' } });
                    return false;
                }
            }
            return true;
        }

        stepperLoteInstancia = Baros.Stepper('#container-stepper-lote', {
            validar: validarEtapaLote,
            aoMudar: (atual, total) => {
                btnVoltarLote.hidden = atual === 1;
                btnProximoLote.hidden = atual === total;
                btnConfirmarLote.hidden = atual !== total;
                if (atual === total) montarRevisaoLote();
            }
        });

        btnVoltarLote.addEventListener('click', () => stepperLoteInstancia.anterior());
        btnProximoLote.addEventListener('click', () => stepperLoteInstancia.proxima());

        // Cálculo automático de valor unitário
        function atualizarCalculoUnitario() {
            const qtd = Number(formLote.quantidade.value);
            const tot = Number(formLote.valor_total.value);
            if (qtd > 0 && tot >= 0) {
                formLote.valor_unitario.value = (tot / qtd).toFixed(2);
            } else {
                formLote.valor_unitario.value = '';
            }
        }
        formLote.quantidade.addEventListener('input', atualizarCalculoUnitario);
        formLote.valor_total.addEventListener('input', atualizarCalculoUnitario);

        btnNovoLote.addEventListener('click', async () => {
            formLote.reset();
            stepperLoteInstancia.reiniciar();
            await garantirClassesCarregadas();
            popularSelect(formLote.classe, cache.classes, c => `${c.codigo} - ${c.nome}`);
            abrirModal('modal-lote-aquisicao');
        });

        formLote.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formLote)) return;

            const restaurar = Baros.carregando(btnConfirmarLote, 'Salvando lote...');
            try {
                const dados = Baros.dadosDoForm(formLote);
                if (!dados.chave_nfe) delete dados.chave_nfe;
                if (!dados.fornecedor_documento) delete dados.fornecedor_documento;

                await Baros.api('/produtos/api/patrimonio/lotes/', {
                    method: 'POST',
                    body: dados,
                });
                Baros.sucesso('Lote de aquisição cadastrado com sucesso.');
                fecharModal(document.getElementById('modal-lote-aquisicao'));
                carregarLotes();
            } catch (err) {
                Baros.mostrarErrosApi(formLote, err);
            } finally {
                restaurar();
            }
        });
    }

    // =========================================================================
    // 3. ABA CLASSES DE ATIVO
    // =========================================================================
    const corpoTabelaClasses = document.getElementById('corpo-tabela-classes');
    const skeletonClasses = document.getElementById('skeleton-classes');
    const vazioClasses = document.getElementById('vazio-classes');
    const erroClasses = document.getElementById('erro-classes');
    const buscaClasse = document.getElementById('busca-classe');

    async function carregarClasses() {
        if (!corpoTabelaClasses) return;
        skeletonClasses.classList.remove('ds-hidden');
        vazioClasses.classList.add('ds-hidden');
        erroClasses.classList.add('ds-hidden');
        corpoTabelaClasses.textContent = '';

        try {
            const res = await Baros.api('/produtos/api/patrimonio/classes/?page_size=200');
            const classes = extrairLista(res);
            cache.classes = classes;

            // Atualiza select de filtro na aba de ativos
            if (filtroAtivoClasse) {
                const selAtual = filtroAtivoClasse.value;
                filtroAtivoClasse.textContent = '';
                const optPadrao = document.createElement('option');
                optPadrao.value = '';
                optPadrao.textContent = 'Todas as classes de ativo';
                filtroAtivoClasse.appendChild(optPadrao);
                classes.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = `${c.codigo} - ${c.nome}`;
                    filtroAtivoClasse.appendChild(opt);
                });
                filtroAtivoClasse.value = selAtual;
            }

            skeletonClasses.classList.add('ds-hidden');

            const termo = (buscaClasse && buscaClasse.value.trim().toLowerCase()) || '';
            const filtrados = classes.filter(c => {
                if (!termo) return true;
                return (c.codigo || '').toLowerCase().includes(termo)
                    || (c.nome || '').toLowerCase().includes(termo);
            });

            if (filtrados.length === 0) {
                vazioClasses.classList.remove('ds-hidden');
                return;
            }

            filtrados.forEach(c => {
                const tr = document.createElement('tr');

                // Código
                const tdCod = document.createElement('td');
                tdCod.className = 'font-mono';
                tdCod.textContent = c.codigo;
                tr.appendChild(tdCod);

                // Nome
                const tdNome = document.createElement('td');
                tdNome.textContent = c.nome;
                tr.appendChild(tdNome);

                // Tipo
                const tdTipo = document.createElement('td');
                tdTipo.textContent = c.tipo_display || c.tipo;
                tr.appendChild(tdTipo);

                // Vida útil
                const tdVu = document.createElement('td');
                tdVu.className = 'text-right font-mono';
                tdVu.textContent = c.vida_util_meses_padrao;
                tr.appendChild(tdVu);

                // % Residual
                const tdRes = document.createElement('td');
                tdRes.className = 'text-right font-mono';
                tdRes.textContent = `${(Number(c.percentual_residual_padrao) * 100).toFixed(1)}%`;
                tr.appendChild(tdRes);

                // Método
                const tdMet = document.createElement('td');
                tdMet.textContent = c.metodo_depreciacao_display || c.metodo_depreciacao;
                tr.appendChild(tdMet);

                // Contas Contábeis
                const tdContas = document.createElement('td');
                const contas = [
                    c.codigo_conta_imobilizado,
                    c.codigo_conta_depreciacao_acumulada,
                    c.codigo_conta_despesa_depreciacao
                ].filter(Boolean);
                tdContas.className = 'font-mono';
                tdContas.textContent = contas.length ? contas.join(' · ') : 'Sem conta';
                tr.appendChild(tdContas);

                // Status
                const tdSt = document.createElement('td');
                const badge = document.createElement('span');
                badge.className = 'badge ' + (c.ativo ? 'badge-status-approved' : 'badge-status-danger');
                badge.textContent = c.ativo ? 'Ativo' : 'Inativo';
                tdSt.appendChild(badge);
                tr.appendChild(tdSt);

                // Ações
                if (config.podeEditar) {
                    const tdAcoes = document.createElement('td');
                    tdAcoes.className = 'text-right';
                    const btnExcluir = document.createElement('button');
                    btnExcluir.type = 'button';
                    btnExcluir.className = 'btn-outline btn-sm btn-danger';
                    btnExcluir.textContent = 'Excluir';
                    btnExcluir.addEventListener('click', () => excluirClasse(c));
                    tdAcoes.appendChild(btnExcluir);
                    tr.appendChild(tdAcoes);
                }

                corpoTabelaClasses.appendChild(tr);
            });
        } catch (e) {
            skeletonClasses.classList.add('ds-hidden');
            erroClasses.classList.remove('ds-hidden');
            Baros.erro(e.mensagem || 'Não foi possível carregar as classes de ativo.');
        }
    }

    async function excluirClasse(c) {
        const confirmado = await Baros.confirmar({
            titulo: 'Excluir classe de ativo',
            texto: `Deseja excluir a classe "${c.codigo} - ${c.nome}"?`,
            botao: 'Excluir classe',
            perigo: true,
        });
        if (!confirmado) return;

        try {
            await Baros.api(`/produtos/api/patrimonio/classes/${c.id}/`, { method: 'DELETE' });
            Baros.sucesso('Classe de ativo excluída.');
            carregarClasses();
        } catch (e) {
            Baros.erro(e.mensagem || 'Não foi possível excluir a classe de ativo.');
        }
    }

    if (buscaClasse) buscaClasse.addEventListener('input', carregarClasses);

    // Modal Nova Classe
    const btnNovaClasse = document.getElementById('btn-nova-classe');
    const formClasse = document.getElementById('form-classe-ativo');
    const avisoFinanceiro = document.getElementById('aviso-financeiro-desligado');

    if (btnNovaClasse && formClasse) {
        btnNovaClasse.addEventListener('click', async () => {
            formClasse.reset();
            formClasse.elements['id'].value = '';

            // Verifica status do financeiro
            if (!config.temFinanceiro) {
                if (avisoFinanceiro) avisoFinanceiro.classList.remove('ds-hidden');
            } else {
                if (avisoFinanceiro) avisoFinanceiro.classList.add('ds-hidden');
                await garantirContasContabeisCarregadas();
                popularSelectContas(formClasse.codigo_conta_imobilizado);
                popularSelectContas(formClasse.codigo_conta_depreciacao_acumulada);
                popularSelectContas(formClasse.codigo_conta_despesa_depreciacao);
            }

            abrirModal('modal-classe-ativo');
        });

        formClasse.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formClasse)) return;

            const btn = document.getElementById('btn-salvar-classe');
            const restaurar = Baros.carregando(btn, 'Salvando...');
            try {
                const dados = Baros.dadosDoForm(formClasse);
                await Baros.api('/produtos/api/patrimonio/classes/', {
                    method: 'POST',
                    body: dados,
                });
                Baros.sucesso('Classe de ativo cadastrada.');
                fecharModal(document.getElementById('modal-classe-ativo'));
                carregarClasses();
            } catch (err) {
                Baros.mostrarErrosApi(formClasse, err);
            } finally {
                restaurar();
            }
        });
    }

    // =========================================================================
    // 4. ABA FABRICANTES
    // =========================================================================
    const corpoTabelaFabricantes = document.getElementById('corpo-tabela-fabricantes');
    const skeletonFabricantes = document.getElementById('skeleton-fabricantes');
    const vazioFabricantes = document.getElementById('vazio-fabricantes');
    const erroFabricantes = document.getElementById('erro-fabricantes');
    const buscaFabricante = document.getElementById('busca-fabricante');

    async function carregarFabricantes() {
        if (!corpoTabelaFabricantes) return;
        skeletonFabricantes.classList.remove('ds-hidden');
        vazioFabricantes.classList.add('ds-hidden');
        erroFabricantes.classList.add('ds-hidden');
        corpoTabelaFabricantes.textContent = '';

        try {
            const res = await Baros.api('/produtos/api/patrimonio/fabricantes/?page_size=200');
            const fabricantes = extrairLista(res);
            skeletonFabricantes.classList.add('ds-hidden');

            const termo = (buscaFabricante && buscaFabricante.value.trim().toLowerCase()) || '';
            const filtrados = fabricantes.filter(f => {
                if (!termo) return true;
                return (f.nome || '').toLowerCase().includes(termo)
                    || (f.pais_origem || '').toLowerCase().includes(termo);
            });

            if (filtrados.length === 0) {
                vazioFabricantes.classList.remove('ds-hidden');
                return;
            }

            filtrados.forEach(f => {
                const tr = document.createElement('tr');

                // Nome
                const tdNome = document.createElement('td');
                tdNome.textContent = f.nome;
                tr.appendChild(tdNome);

                // País
                const tdPais = document.createElement('td');
                tdPais.textContent = f.pais_origem || 'BR';
                tr.appendChild(tdPais);

                // Norma
                const tdNorma = document.createElement('td');
                tdNorma.className = 'font-mono';
                tdNorma.textContent = f.norma_fabricacao_padrao || '—';
                tr.appendChild(tdNorma);

                // Status
                const tdSt = document.createElement('td');
                const badge = document.createElement('span');
                badge.className = 'badge ' + (f.ativo ? 'badge-status-approved' : 'badge-status-danger');
                badge.textContent = f.ativo ? 'Ativo' : 'Inativo';
                tdSt.appendChild(badge);
                tr.appendChild(tdSt);

                // Ações
                if (config.podeEditar) {
                    const tdAcoes = document.createElement('td');
                    tdAcoes.className = 'text-right';
                    const btnExcluir = document.createElement('button');
                    btnExcluir.type = 'button';
                    btnExcluir.className = 'btn-outline btn-sm btn-danger';
                    btnExcluir.textContent = 'Excluir';
                    btnExcluir.addEventListener('click', () => excluirFabricante(f));
                    tdAcoes.appendChild(btnExcluir);
                    tr.appendChild(tdAcoes);
                }

                corpoTabelaFabricantes.appendChild(tr);
            });
        } catch (e) {
            skeletonFabricantes.classList.add('ds-hidden');
            erroFabricantes.classList.remove('ds-hidden');
            Baros.erro(e.mensagem || 'Não foi possível carregar os fabricantes.');
        }
    }

    async function excluirFabricante(f) {
        const confirmado = await Baros.confirmar({
            titulo: 'Excluir fabricante',
            texto: `Deseja excluir o fabricante "${f.nome}"?`,
            botao: 'Excluir fabricante',
            perigo: true,
        });
        if (!confirmado) return;

        try {
            await Baros.api(`/produtos/api/patrimonio/fabricantes/${f.id}/`, { method: 'DELETE' });
            Baros.sucesso('Fabricante excluído.');
            carregarFabricantes();
        } catch (e) {
            Baros.erro(e.mensagem || 'Não foi possível excluir o fabricante.');
        }
    }

    if (buscaFabricante) buscaFabricante.addEventListener('input', carregarFabricantes);

    // Modal Novo Fabricante
    const btnNovoFabricante = document.getElementById('btn-novo-fabricante');
    const formFabricante = document.getElementById('form-fabricante-cilindro');
    if (btnNovoFabricante && formFabricante) {
        btnNovoFabricante.addEventListener('click', () => {
            formFabricante.reset();
            formFabricante.elements['id'].value = '';
            abrirModal('modal-fabricante-cilindro');
        });

        formFabricante.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formFabricante)) return;

            const btn = document.getElementById('btn-salvar-fabricante');
            const restaurar = Baros.carregando(btn, 'Salvando...');
            try {
                const dados = Baros.dadosDoForm(formFabricante);
                await Baros.api('/produtos/api/patrimonio/fabricantes/', {
                    method: 'POST',
                    body: dados,
                });
                Baros.sucesso('Fabricante cadastrado com sucesso.');
                fecharModal(document.getElementById('modal-fabricante-cilindro'));
                carregarFabricantes();
            } catch (err) {
                Baros.mostrarErrosApi(formFabricante, err);
            } finally {
                restaurar();
            }
        });
    }

    // =========================================================================
    // 5. ABA INDENIZAÇÃO & SIMULADOR
    // =========================================================================
    const corpoTabelaIndenizacoes = document.getElementById('corpo-tabela-indenizacoes');
    const skeletonIndenizacoes = document.getElementById('skeleton-indenizacoes');
    const vazioIndenizacoes = document.getElementById('vazio-indenizacoes');
    const erroIndenizacoes = document.getElementById('erro-indenizacoes');
    const buscaIndenizacao = document.getElementById('busca-indenizacao');

    async function carregarIndenizacoes() {
        if (!corpoTabelaIndenizacoes) return;
        skeletonIndenizacoes.classList.remove('ds-hidden');
        vazioIndenizacoes.classList.add('ds-hidden');
        erroIndenizacoes.classList.add('ds-hidden');
        corpoTabelaIndenizacoes.textContent = '';

        try {
            const res = await Baros.api('/produtos/api/patrimonio/indenizacoes/?page_size=200');
            const itens = extrairLista(res);
            skeletonIndenizacoes.classList.add('ds-hidden');

            const termo = (buscaIndenizacao && buscaIndenizacao.value.trim().toLowerCase()) || '';
            const filtrados = itens.filter(i => {
                if (!termo) return true;
                return (i.tipo_cilindro_descricao || '').toLowerCase().includes(termo)
                    || (i.gas_nome || '').toLowerCase().includes(termo)
                    || (i.gas_sigla || '').toLowerCase().includes(termo);
            });

            if (filtrados.length === 0) {
                vazioIndenizacoes.classList.remove('ds-hidden');
                return;
            }

            const hoje = new Date().toISOString().split('T')[0];

            filtrados.forEach(item => {
                const tr = document.createElement('tr');

                // Modelo
                const tdMod = document.createElement('td');
                tdMod.textContent = item.tipo_cilindro_descricao || '—';
                tr.appendChild(tdMod);

                // Gás
                const tdGas = document.createElement('td');
                tdGas.textContent = item.gas_nome ? `${item.gas_nome} (${item.gas_sigla})` : 'Todos os gases (Geral)';
                tr.appendChild(tdGas);

                // Valor Contratual
                const tdVal = document.createElement('td');
                tdVal.className = 'text-right font-mono';
                tdVal.textContent = Baros.moeda(item.valor);
                tr.appendChild(tdVal);

                // Início Vigência
                const tdIni = document.createElement('td');
                tdIni.textContent = Baros.data(item.vigencia_inicio);
                tr.appendChild(tdIni);

                // Fim Vigência
                const tdFim = document.createElement('td');
                tdFim.textContent = item.vigencia_fim ? Baros.data(item.vigencia_fim) : 'Indeterminado';
                tr.appendChild(tdFim);

                // Situação (Vigente / Encerrado)
                const tdSt = document.createElement('td');
                const badge = document.createElement('span');
                const isVigente = (!item.vigencia_fim || item.vigencia_fim >= hoje) && item.vigencia_inicio <= hoje;
                badge.className = 'badge ' + (isVigente ? 'badge-status-approved' : 'badge-status-danger');
                badge.textContent = isVigente ? 'Vigente' : 'Encerrada';
                tdSt.appendChild(badge);
                tr.appendChild(tdSt);

                // Ações
                if (config.podeEditar) {
                    const tdAcoes = document.createElement('td');
                    tdAcoes.className = 'text-right';

                    if (isVigente) {
                        const btnNovaVig = document.createElement('button');
                        btnNovaVig.type = 'button';
                        btnNovaVig.className = 'btn-outline btn-sm';
                        btnNovaVig.textContent = 'Nova vigência';
                        btnNovaVig.title = 'Registrar novo valor preservando o histórico anterior';
                        btnNovaVig.addEventListener('click', () => abrirModalNovaVigencia(item));
                        tdAcoes.appendChild(btnNovaVig);
                    }

                    tr.appendChild(tdAcoes);
                }

                corpoTabelaIndenizacoes.appendChild(tr);
            });
        } catch (e) {
            skeletonIndenizacoes.classList.add('ds-hidden');
            erroIndenizacoes.classList.remove('ds-hidden');
            Baros.erro(e.mensagem || 'Não foi possível carregar os parâmetros de indenização.');
        }
    }

    if (buscaIndenizacao) buscaIndenizacao.addEventListener('input', carregarIndenizacoes);

    // Modal Indenização (Nova Vigência ou Nova Linha)
    const btnNovaIndenizacao = document.getElementById('btn-nova-indenizacao');
    const formIndenizacao = document.getElementById('form-indenizacao');
    const avisoNovaVigencia = document.getElementById('aviso-nova-vigencia');
    const grupoCamposBaseInd = document.getElementById('grupo-campos-base-indenizacao');

    function abrirModalNovaVigencia(item) {
        if (!formIndenizacao) return;
        formIndenizacao.reset();
        formIndenizacao.elements['id'].value = item.id;
        formIndenizacao.elements['modo_nova_vigencia'].value = '1';
        document.getElementById('modal-indenizacao-titulo').textContent = `Nova vigência: ${item.tipo_cilindro_descricao}`;

        if (grupoCamposBaseInd) grupoCamposBaseInd.classList.add('ds-hidden');
        if (avisoNovaVigencia) avisoNovaVigencia.classList.remove('ds-hidden');

        // Sugere data de amanhã para início da nova vigência
        const amanha = new Date();
        amanha.setDate(amanha.getDate() + 1);
        formIndenizacao.elements['vigencia_inicio'].value = amanha.toISOString().split('T')[0];
        formIndenizacao.elements['valor'].value = item.valor;

        abrirModal('modal-indenizacao');
    }

    if (btnNovaIndenizacao && formIndenizacao) {
        btnNovaIndenizacao.addEventListener('click', async () => {
            formIndenizacao.reset();
            formIndenizacao.elements['id'].value = '';
            formIndenizacao.elements['modo_nova_vigencia'].value = '0';
            document.getElementById('modal-indenizacao-titulo').textContent = 'Novo parâmetro de indenização';

            if (grupoCamposBaseInd) grupoCamposBaseInd.classList.remove('ds-hidden');
            if (avisoNovaVigencia) avisoNovaVigencia.classList.add('ds-hidden');

            await garantirModelosEGasesCarregados();
            popularSelect(formIndenizacao.tipo_cilindro, cache.modelos, m => m.descricao);
            popularSelect(formIndenizacao.gas, cache.gases, g => `${g.nome} (${g.sigla})`, 'Todos os gases (Geral)');

            const hoje = new Date().toISOString().split('T')[0];
            formIndenizacao.elements['vigencia_inicio'].value = hoje;

            abrirModal('modal-indenizacao');
        });

        formIndenizacao.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!Baros.validarCampos(formIndenizacao)) return;

            const btn = document.getElementById('btn-salvar-indenizacao');
            const restaurar = Baros.carregando(btn, 'Salvando...');
            const modoNovaVig = formIndenizacao.elements['modo_nova_vigencia'].value === '1';
            const itemId = formIndenizacao.elements['id'].value;

            try {
                if (modoNovaVig) {
                    await Baros.api(`/produtos/api/patrimonio/indenizacoes/${itemId}/nova-vigencia/`, {
                        method: 'POST',
                        body: {
                            valor: formIndenizacao.elements['valor'].value,
                            vigencia_inicio: formIndenizacao.elements['vigencia_inicio'].value,
                        }
                    });
                    Baros.sucesso('Nova vigência registrada com sucesso.');
                } else {
                    const dados = Baros.dadosDoForm(formIndenizacao);
                    delete dados.id;
                    delete dados.modo_nova_vigencia;
                    if (!dados.gas) delete dados.gas;

                    await Baros.api('/produtos/api/patrimonio/indenizacoes/', {
                        method: 'POST',
                        body: dados,
                    });
                    Baros.sucesso('Parâmetro de indenização criado.');
                }
                fecharModal(document.getElementById('modal-indenizacao'));
                carregarIndenizacoes();
            } catch (err) {
                Baros.mostrarErrosApi(formIndenizacao, err);
            } finally {
                restaurar();
            }
        });
    }

    // SIMULADOR DE INDENIZAÇÃO
    const formSimulador = document.getElementById('form-simulador-indenizacao');
    const selectSimCilindro = document.getElementById('simulador-cilindro');
    const painelResultadoSim = document.getElementById('simulador-resultado-painel');

    async function carregarCilindrosSimulador() {
        if (!selectSimCilindro || selectSimCilindro.options.length > 1) return;
        try {
            const res = await Baros.api('/produtos/api/cilindros/?page_size=300');
            const cilindros = extrairLista(res);
            popularSelect(selectSimCilindro, cilindros, c => `${c.numero_serie_ogiva || c.codigo_qr} · ${c.modelo_descricao || ''} (${c.gas_sigla || ''})`);
        } catch (_) {}
    }

    if (formSimulador) {
        formSimulador.addEventListener('submit', async (e) => {
            e.preventDefault();
            const cilindroId = selectSimCilindro.value;
            if (!cilindroId) {
                Baros.aviso('Selecione um cilindro para simular.');
                return;
            }

            const btn = document.getElementById('btn-executar-simulacao');
            const restaurar = Baros.carregando(btn, 'Calculando...');
            try {
                const params = new URLSearchParams({ cilindro_id: cilindroId });
                const dataVal = document.getElementById('simulador-data').value;
                if (dataVal) params.set('data', dataVal);

                const res = await Baros.api('/produtos/api/patrimonio/indenizacoes/simular/?' + params.toString());

                // Exibe resultados
                if (painelResultadoSim) painelResultadoSim.classList.remove('ds-hidden');
                const elContr = document.querySelector('#metrica-sim-contratual [data-metric-value]');
                const elVcl = document.querySelector('#metrica-sim-vcl [data-metric-value]');
                const elGp = document.querySelector('#metrica-sim-ganho-perda [data-metric-value]');
                const textoOrigem = document.getElementById('texto-sim-origem');

                if (elContr) elContr.textContent = Baros.moeda(res.valor_contratual);
                if (elVcl) elVcl.textContent = Baros.moeda(res.valor_contabil_liquido);
                if (elGp) elGp.textContent = Baros.moeda(res.ganho_perda);

                if (textoOrigem) {
                    if (res.sinalizado_fallback) {
                        textoOrigem.textContent = 'Aviso: Não há parâmetro vigente na Tabela de Indenização para este modelo/gás. Foi utilizado o Valor Contábil Líquido (fallback) como valor contratual.';
                    } else {
                        textoOrigem.textContent = 'Cálculo baseado na Tabela Contratual de Indenização vigente para o modelo e gás químico.';
                    }
                }
            } catch (err) {
                Baros.erro(err.mensagem || 'Não foi possível simular o cálculo de indenização.');
            } finally {
                restaurar();
            }
        });
    }

    // =========================================================================
    // UTILITÁRIOS DE CARREGAMENTO E SELECTS
    // =========================================================================
    async function garantirClassesCarregadas() {
        if (cache.classes.length) return;
        const res = await Baros.api('/produtos/api/patrimonio/classes/?page_size=200').catch(() => []);
        cache.classes = extrairLista(res);
    }

    async function garantirModelosEGasesCarregados() {
        if (!cache.modelos.length) {
            const res = await Baros.api('/produtos/api/catalogo/modelos/?page_size=200').catch(() => []);
            cache.modelos = extrairLista(res);
        }
        if (!cache.gases.length) {
            const res = await Baros.api('/produtos/api/catalogo/gases/').catch(() => []);
            cache.gases = extrairLista(res);
        }
    }

    async function garantirContasContabeisCarregadas() {
        if (cache.contasContabeis.length) return;
        const res = await Baros.api('/financeiro/api/plano-contas/?tipo=ANALITICA&page_size=500').catch(() => []);
        cache.contasContabeis = extrairLista(res);
    }

    function popularSelect(select, itens, rotuloFn, textoPadrao = 'Selecione...') {
        if (!select) return;
        select.textContent = '';
        const optPadrao = document.createElement('option');
        optPadrao.value = '';
        optPadrao.textContent = textoPadrao;
        select.appendChild(optPadrao);

        itens.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.id;
            opt.textContent = rotuloFn(item);
            select.appendChild(opt);
        });
    }

    function popularSelectContas(select) {
        if (!select) return;
        select.textContent = '';
        const optPadrao = document.createElement('option');
        optPadrao.value = '';
        optPadrao.textContent = 'Selecione a conta analítica...';
        select.appendChild(optPadrao);

        cache.contasContabeis.forEach(conta => {
            const opt = document.createElement('option');
            opt.value = conta.codigo_estrutural || conta.codigo;
            opt.textContent = `${conta.codigo_estrutural} - ${conta.nome}`;
            select.appendChild(opt);
        });
    }
});

