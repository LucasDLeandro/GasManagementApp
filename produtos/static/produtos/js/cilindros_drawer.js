/**
 * Baros - Cilindros Ativo 360° & Drawer de Auditoria (Sprint 01.01)
 * Modular Vanilla JS com zero dependências externas, sincronização bidirecional de URL,
 * contadores agregados da frota e construção de DOM 100% segura contra XSS.
 */

document.addEventListener('DOMContentLoaded', () => {
    // --------------------------------------------------------------------------
    // Estado local da tela de ativos
    // --------------------------------------------------------------------------
    let currentPage = 1;
    let currentFilter = 'todos'; // 'todos' | 'CHEIO_DISPONIVEL' | 'EM_POSSE_CLIENTE' | 'VAZIO_TRIAGEM' | 'EM_RETESTE' | 'RESERVADO_ROTA' | 'bloqueio_sanitario' | 'reteste_vencido' | 'reteste_30_dias' | 'extravio_candidato' | 'proprio'
    let currentSearch = '';
    let currentGas = '';
    let currentPropriedade = '';
    let totalCilindros = 0;
    let activeCilindroId = null;
    let activeCilindroData = null;
    let lastFocusedElement = null;

    // --------------------------------------------------------------------------
    // Elementos DOM principais
    // --------------------------------------------------------------------------
    const tbodyCilindros = document.getElementById('cilindros-tbody');
    const inputSearch = document.getElementById('input-busca-cilindros');
    const paginationInfo = document.getElementById('pagination-info');
    const btnPrevPage = document.getElementById('btn-prev-page');
    const btnNextPage = document.getElementById('btn-next-page');
    const filterPills = document.querySelectorAll('.pill-filter-btn');
    const kpiCards = document.querySelectorAll('.ativos-kpi-grid .metric-card--clickable');

    // Drawer & Modais Contextuais
    const drawerDialog = document.getElementById('cylinder-drawer');
    const btnCloseDrawer = document.getElementById('btn-close-drawer');

    const modalBloqueio = document.getElementById('modal-bloqueio-sanitario');
    const modalReteste = document.getElementById('modal-retorno-reteste');
    const modalReclassificar = document.getElementById('modal-reclassificar-gas');
    const modalEstorno = document.getElementById('modal-estorno-ledger');
    const modalEtiqueta = document.getElementById('modal-etiqueta-termica');

    // --------------------------------------------------------------------------
    // Utilitários de DOM seguro (Zero XSS)
    // --------------------------------------------------------------------------
    function el(tag, className = '', textContent = '', attributes = {}) {
        const elemento = document.createElement(tag);
        if (className) elemento.className = className;
        if (textContent !== undefined && textContent !== null && textContent !== '') {
            elemento.textContent = textContent;
        }
        for (const [chave, valor] of Object.entries(attributes)) {
            if (valor !== null && valor !== undefined) {
                elemento.setAttribute(chave, valor);
            }
        }
        return elemento;
    }

    function formatarData(dataIso) {
        if (!dataIso) return '-';
        const parts = dataIso.split('T')[0].split('-');
        if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
        return dataIso;
    }

    function getOgivaClass(sigla) {
        if (!sigla) return 'ogiva-dot--oxigenio-ind';
        const s = String(sigla).toUpperCase();
        if (s.includes('MED')) return 'ogiva-dot--oxigenio-med';
        if (s.includes('IND')) return 'ogiva-dot--oxigenio-ind';
        if (s.includes('N2') || s.includes('NIT')) return 'ogiva-dot--nitrogenio';
        if (s.includes('AR') || s.includes('ARG')) return 'ogiva-dot--argonio';
        if (s.includes('CO2')) return 'ogiva-dot--co2';
        if (s.includes('AC') || s.includes('ACET')) return 'ogiva-dot--acetileno';
        if (s.includes('AR-COMP')) return 'ogiva-dot--ar-comp';
        return 'ogiva-dot--oxigenio-ind';
    }

    function ligarFechar(dialogo) {
        if (!dialogo) return;
        dialogo.querySelectorAll('[data-fechar-dialogo]').forEach(b => b.addEventListener('click', () => dialogo.close()));
    }

    function limparErros(form) {
        if (!form) return;
        form.querySelectorAll('.ds-field-error').forEach(item => item.remove());
        form.querySelectorAll('.ds-invalid').forEach(item => item.classList.remove('ds-invalid'));
    }

    function rotuloCilindro() {
        return activeCilindroData ? `${activeCilindroData.codigo_qr} · ${activeCilindroData.gas_sigla} · série ${activeCilindroData.numero_serie_ogiva}` : '';
    }

    function aposAcao(mensagem) {
        if (window.Baros && typeof Baros.sucesso === 'function') {
            Baros.sucesso(mensagem);
        }
        if (activeCilindroId) {
            abrirDrawerAtivo(activeCilindroId);
        }
        carregarResumoFrota();
        carregarCilindros(currentPage);
    }

    // --------------------------------------------------------------------------
    // 1. SINCRONIZAÇÃO DE FILTROS COM A URL
    // --------------------------------------------------------------------------
    function lerFiltrosDaUrl() {
        const params = new URLSearchParams(window.location.search);

        const statusParam = params.get('status');
        const bloqueioParam = params.get('bloqueio_sanitario');
        const retesteAteDiasParam = params.get('reteste_ate_dias');
        const retesteParam = params.get('reteste_vencido');
        const filtroParam = params.get('filtro');
        const gasParam = params.get('gas');
        const propriedadeParam = params.get('propriedade');
        const searchParam = params.get('search') || params.get('q');
        const pageParam = parseInt(params.get('page'), 10);

        if (statusParam) {
            currentFilter = statusParam;
        } else if (bloqueioParam === 'true') {
            currentFilter = 'bloqueio_sanitario';
        } else if (retesteAteDiasParam) {
            currentFilter = 'reteste_30_dias';
        } else if (retesteParam === 'true') {
            currentFilter = 'reteste_vencido';
        } else if (filtroParam === 'extravio_candidato') {
            currentFilter = 'extravio_candidato';
        } else if (propriedadeParam === 'DISTRIBUIDORA') {
            currentFilter = 'proprio';
        } else {
            currentFilter = 'todos';
        }

        if (searchParam) {
            currentSearch = searchParam;
            if (inputSearch) inputSearch.value = searchParam;
        }

        if (gasParam) currentGas = gasParam;
        if (propriedadeParam) currentPropriedade = propriedadeParam;
        if (!isNaN(pageParam) && pageParam > 0) currentPage = pageParam;

        sincronizarUiFiltros();
    }

    function sincronizarUiFiltros() {
        // Atualiza pílulas
        filterPills.forEach(pill => {
            const f = pill.getAttribute('data-filter');
            if (f === currentFilter) {
                pill.classList.add('active');
            } else {
                pill.classList.remove('active');
            }
        });

        // Atualiza cards de métricas
        kpiCards.forEach(card => {
            const f = card.getAttribute('data-filtro');
            if (f === currentFilter) {
                card.classList.add('active');
            } else {
                card.classList.remove('active');
            }
        });
    }

    function atualizarUrlFiltros() {
        const url = new URL(window.location.href);
        const params = url.searchParams;

        // Limpa parâmetros de filtro anteriores
        params.delete('status');
        params.delete('bloqueio_sanitario');
        params.delete('reteste_vencido');
        params.delete('reteste_ate_dias');
        params.delete('filtro');
        params.delete('propriedade');

        if (currentFilter === 'CHEIO_DISPONIVEL') params.set('status', 'CHEIO_DISPONIVEL');
        else if (currentFilter === 'EM_POSSE_CLIENTE') params.set('status', 'EM_POSSE_CLIENTE');
        else if (currentFilter === 'VAZIO_TRIAGEM') params.set('status', 'VAZIO_TRIAGEM');
        else if (currentFilter === 'EM_RETESTE') params.set('status', 'EM_RETESTE');
        else if (currentFilter === 'RESERVADO_ROTA') params.set('status', 'RESERVADO_ROTA');
        else if (currentFilter === 'bloqueio_sanitario') params.set('bloqueio_sanitario', 'true');
        else if (currentFilter === 'reteste_vencido') params.set('reteste_vencido', 'true');
        else if (currentFilter === 'reteste_30_dias') params.set('reteste_ate_dias', '30');
        else if (currentFilter === 'extravio_candidato') params.set('filtro', 'extravio_candidato');
        else if (currentFilter === 'proprio') params.set('propriedade', 'DISTRIBUIDORA');

        if (currentSearch) {
            params.set('q', currentSearch);
        } else {
            params.delete('q');
            params.delete('search');
        }

        if (currentPage > 1) {
            params.set('page', String(currentPage));
        } else {
            params.delete('page');
        }

        window.history.replaceState(null, '', url.pathname + (params.toString() ? '?' + params.toString() : ''));
    }

    function aplicarFiltro(filtroNome) {
        currentFilter = filtroNome;
        currentPage = 1;
        sincronizarUiFiltros();
        atualizarUrlFiltros();
        carregarCilindros(1);
    }

    // --------------------------------------------------------------------------
    // 2. RESUMO AGREGADO DA FROTA (CARDS DE KPI)
    // --------------------------------------------------------------------------
    async function carregarResumoFrota() {
        try {
            const data = await Baros.api('/produtos/api/cilindros/resumo/');
            const setVal = (id, val) => {
                const node = document.getElementById(id);
                if (node) node.textContent = (val !== undefined && val !== null) ? Number(val).toLocaleString('pt-BR') : '0';
            };

            setVal('kpi-frota-total', data.total);
            setVal('kpi-frota-cheios', data.cheios_patio);
            setVal('kpi-frota-clientes', data.em_clientes);
            setVal('kpi-frota-triagem', data.vazios_triagem);
            setVal('kpi-frota-rota', data.em_rota);
            setVal('kpi-frota-reteste', data.em_reteste);
            setVal('kpi-frota-bloqueados', data.bloqueados);
            setVal('kpi-frota-vencidos', data.reteste_vencido);
            setVal('kpi-frota-30dias', data.reteste_30_dias);
        } catch (err) {
            console.error("Erro ao carregar resumo da frota:", err);
        }
    }

    // --------------------------------------------------------------------------
    // 3. CARREGAMENTO E PAGINAÇÃO DE CILINDROS
    // --------------------------------------------------------------------------
    async function carregarCilindros(page = 1) {
        currentPage = page;
        if (tbodyCilindros) {
            tbodyCilindros.innerHTML = '';
            const trLoading = el('tr');
            const tdLoading = el('td', 'ativos-table-loading', 'Carregando frota de cilindros...', { colspan: '8' });
            trLoading.appendChild(tdLoading);
            tbodyCilindros.appendChild(trLoading);
        }

        let url = `/produtos/api/cilindros/?page=${page}`;
        if (currentSearch) {
            url += `&q=${encodeURIComponent(currentSearch)}`;
        }

        if (currentFilter === 'CHEIO_DISPONIVEL') url += '&status=CHEIO_DISPONIVEL';
        else if (currentFilter === 'EM_POSSE_CLIENTE') url += '&status=EM_POSSE_CLIENTE';
        else if (currentFilter === 'VAZIO_TRIAGEM') url += '&status=VAZIO_TRIAGEM';
        else if (currentFilter === 'EM_RETESTE') url += '&status=EM_RETESTE';
        else if (currentFilter === 'RESERVADO_ROTA') url += '&status=RESERVADO_ROTA';
        else if (currentFilter === 'bloqueio_sanitario') url += '&bloqueio_sanitario=true';
        else if (currentFilter === 'reteste_vencido') url += '&reteste_vencido=true';
        else if (currentFilter === 'reteste_30_dias') url += '&reteste_ate_dias=30';
        else if (currentFilter === 'extravio_candidato') url += '&filtro=extravio_candidato';
        else if (currentFilter === 'proprio') url += '&propriedade=DISTRIBUIDORA';

        try {
            const data = await Baros.api(url);
            const cilindros = data.results || (Array.isArray(data) ? data : []);
            totalCilindros = data.count || cilindros.length;

            renderTabelaCilindros(cilindros);
            atualizarControlesPaginacao(data.count, data.next, data.previous);
            atualizarUrlFiltros();
        } catch (err) {
            console.error("Erro ao carregar cilindros:", err);
            if (tbodyCilindros) {
                tbodyCilindros.innerHTML = '';
                const trErro = el('tr');
                const tdErro = el('td', 'ativos-table-empty', '', { colspan: '8' });
                const wrapperErro = el('div', 'ds-empty ds-empty--danger');
                const tituloErro = el('div', 'ds-empty__title', 'Falha ao consultar frota de cilindros');
                const msgErro = el('div', 'ds-empty__description', err.message || 'Erro inesperado na comunicação.');
                const btnRetry = el('button', 'btn-secondary', 'Tentar novamente', { type: 'button' });
                btnRetry.addEventListener('click', () => carregarCilindros(currentPage));

                wrapperErro.appendChild(tituloErro);
                wrapperErro.appendChild(msgErro);
                wrapperErro.appendChild(btnRetry);
                tdErro.appendChild(wrapperErro);
                trErro.appendChild(tdErro);
                tbodyCilindros.appendChild(trErro);
            }
        }
    }

    function renderTabelaCilindros(cilindros) {
        if (!tbodyCilindros) return;
        tbodyCilindros.innerHTML = '';

        if (cilindros.length === 0) {
            const trVazio = el('tr');
            const tdVazio = el('td', 'ativos-table-empty', 'Nenhum cilindro encontrado com os filtros selecionados.', { colspan: '8' });
            trVazio.appendChild(tdVazio);
            tbodyCilindros.appendChild(trVazio);
            return;
        }

        cilindros.forEach(c => {
            const tr = el('tr', 'cilindro-row', '', { 'data-id': String(c.id) });

            // Coluna 1: Código QR / Ogiva
            const tdQr = el('td');
            const divBadge = el('div', 'tech-id-badge font-mono', c.codigo_qr);
            const btnCopy = el('button', 'copy-btn', '', { type: 'button', 'data-copy': c.codigo_qr, title: 'Copiar QR Code' });
            btnCopy.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
            btnCopy.addEventListener('click', (e) => {
                e.stopPropagation();
                if (navigator.clipboard) {
                    navigator.clipboard.writeText(c.codigo_qr);
                    if (window.Baros && typeof Baros.sucesso === 'function') Baros.sucesso('Código QR copiado!');
                }
            });
            divBadge.appendChild(btnCopy);
            tdQr.appendChild(divBadge);

            const divSerie = el('div', 'drawer-header-subtitle');
            divSerie.appendChild(document.createTextNode('Série: '));
            divSerie.appendChild(el('strong', 'font-mono', c.numero_serie_ogiva || '-'));
            tdQr.appendChild(divSerie);
            tr.appendChild(tdQr);

            // Coluna 2: Gás
            const tdGas = el('td');
            const divGas = el('div', 'ogiva-badge');
            const dotGas = el('span', `ogiva-dot ${getOgivaClass(c.gas_sigla)}`);
            const strongGas = el('strong', '', c.gas_sigla || 'GÁS');
            divGas.appendChild(dotGas);
            divGas.appendChild(strongGas);
            tdGas.appendChild(divGas);
            tr.appendChild(tdGas);

            // Coluna 3: Capacidade / Tara
            const tdCap = el('td');
            const strongCap = el('strong', '', `${c.volume_litros || c.modelo_descricao || '-'}L`);
            const divTara = el('div', 'drawer-header-subtitle', c.tara_real_kg ? `${c.tara_real_kg} kg` : 'Tara s/ aferição');
            tdCap.appendChild(strongCap);
            tdCap.appendChild(divTara);
            tr.appendChild(tdCap);

            // Coluna 4: Status Operacional
            const tdStatus = el('td');
            let statusClasse = 'badge-status-approved';
            let statusTexto = 'Disponível';

            if (c.status === 'EM_POSSE_CLIENTE') {
                statusClasse = 'badge-status-transit';
                statusTexto = 'Em Cliente';
            } else if (c.status === 'VAZIO_TRIAGEM') {
                statusClasse = 'badge-status-warning';
                statusTexto = 'Vazio / Triagem';
            } else if (c.status === 'EM_RETESTE' || c.status === 'EM_REQUALIFICACAO') {
                statusClasse = 'badge-status-warning';
                statusTexto = 'Em Reteste';
            } else if (c.status === 'RESERVADO_ROTA') {
                statusClasse = 'badge-status-transit';
                statusTexto = 'Em Rota';
            } else if (c.status === 'BAIXADO') {
                statusClasse = 'badge-status-danger';
                statusTexto = 'Baixado';
            }
            const spanStatus = el('span', `badge ${statusClasse}`, statusTexto);
            tdStatus.appendChild(spanStatus);
            tr.appendChild(tdStatus);

            // Coluna 5: Reteste INMETRO
            const tdReteste = el('td');
            if (c.reteste_vencido) {
                const spanVenc = el('span', 'badge badge-status-danger', `VENCIDO (${formatarData(c.data_proximo_reteste)})`);
                tdReteste.appendChild(spanVenc);
            } else {
                const spanOk = el('span', '', formatarData(c.data_proximo_reteste));
                tdReteste.appendChild(spanOk);
            }
            tr.appendChild(tdReteste);

            // Coluna 6: Bloqueio ANVISA
            const tdBloq = el('td');
            if (c.bloqueio_sanitario) {
                const spanBloq = el('span', 'badge badge-status-danger', 'BLOQUEADO', {
                    title: c.motivo_bloqueio_sanitario || 'Bloqueio Sanitário Ativo'
                });
                tdBloq.appendChild(spanBloq);
            } else {
                const spanLivre = el('span', 'badge badge-status-approved', 'Livre');
                tdBloq.appendChild(spanLivre);
            }
            tr.appendChild(tdBloq);

            // Coluna 7: Localização Atual
            const tdPosse = el('td');
            if (c.cliente_posse_nome) {
                const strongCliente = el('strong', '', c.cliente_posse_nome);
                tdPosse.appendChild(strongCliente);
            } else {
                const spanPatio = el('span', 'drawer-muted-text', 'Pátio Central');
                tdPosse.appendChild(spanPatio);
            }
            tr.appendChild(tdPosse);

            // Coluna 8: Ações
            const tdAcoes = el('td', 'text-right');
            const btnAuditar = el('button', 'btn-secondary btn-abrir-drawer', 'Auditar Ativo', {
                type: 'button',
                'data-id': String(c.id)
            });
            btnAuditar.addEventListener('click', (e) => {
                e.stopPropagation();
                lastFocusedElement = btnAuditar;
                abrirDrawerAtivo(c.id);
            });
            tdAcoes.appendChild(btnAuditar);
            tr.appendChild(tdAcoes);

            // Clique na linha abre o drawer
            tr.addEventListener('click', () => {
                lastFocusedElement = tr;
                abrirDrawerAtivo(c.id);
            });

            tbodyCilindros.appendChild(tr);
        });
    }

    function atualizarControlesPaginacao(count, next, previous) {
        if (!paginationInfo) return;
        const totalPages = Math.ceil((count || 1) / 20) || 1;
        paginationInfo.textContent = `Página ${currentPage} de ${totalPages} (${count || 0} cilindros)`;
        if (btnPrevPage) btnPrevPage.disabled = !previous;
        if (btnNextPage) btnNextPage.disabled = !next;
    }

    // --------------------------------------------------------------------------
    // 4. GAVETA LATERAL DESLIZANTE (DRAWER / <dialog> NATIVO SEGURO)
    // --------------------------------------------------------------------------
    async function abrirDrawerAtivo(cilindroId) {
        activeCilindroId = cilindroId;
        if (!drawerDialog) {
            console.error("Elemento #cylinder-drawer não encontrado no DOM!");
            return;
        }

        const elQrTitle = document.getElementById('drawer-qr-title');
        const elSerieTitle = document.getElementById('drawer-serie-title');
        const elTimeline = document.getElementById('drawer-timeline-container');
        if (elQrTitle) elQrTitle.textContent = 'Carregando...';
        if (elSerieTitle) elSerieTitle.textContent = '';
        if (elTimeline) {
            elTimeline.innerHTML = '';
            elTimeline.appendChild(el('p', 'drawer-muted-text', 'Carregando histórico do ledger...'));
        }

        if (!drawerDialog.open) {
            drawerDialog.showModal();
        }

        try {
            // Busca dados do cilindro
            activeCilindroData = await Baros.api(`/produtos/api/cilindros/${cilindroId}/`);
            renderDetalhesDrawer(activeCilindroData);

            // Busca timeline do ledger
            try {
                const timeline = await Baros.api(`/produtos/api/cilindros/${cilindroId}/timeline/`);
                renderTimelineLedger(timeline);
            } catch (errTimeline) {
                console.error("Erro na timeline:", errTimeline);
                if (elTimeline) {
                    elTimeline.innerHTML = '';
                    elTimeline.appendChild(el('p', 'drawer-muted-text', 'Nenhuma movimentação registrada no livro-razão (Ledger).'));
                }
            }

            // Busca histórico perpétuo de retestes (Sprint 8B)
            try {
                const retestes = await Baros.api(`/produtos/api/cilindros/${cilindroId}/timeline-retestes/`);
                renderTimelineRetestes(retestes);
            } catch (errRetestes) {
                console.error("Erro nos retestes:", errRetestes);
            }
        } catch (err) {
            console.error("Erro no drawer:", err);
            if (elTimeline) {
                elTimeline.innerHTML = '';
                const pErro = el('p', 'text-danger', `Erro: ${err.message || 'Falha ao buscar detalhes'}`);
                elTimeline.appendChild(pErro);
            }
        }
    }

    function fecharDrawer() {
        if (drawerDialog && drawerDialog.open) {
            drawerDialog.close();
        }
        if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
            lastFocusedElement.focus();
        }
    }

    if (btnCloseDrawer && drawerDialog) {
        btnCloseDrawer.addEventListener('click', fecharDrawer);
    }

    // Tecla Esc fecha gaveta e devolve o foco
    if (drawerDialog) {
        drawerDialog.addEventListener('cancel', (e) => {
            e.preventDefault();
            fecharDrawer();
        });
        drawerDialog.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                fecharDrawer();
            }
        });
    }

    function renderDetalhesDrawer(c) {
        const setTxt = (id, val) => {
            const node = document.getElementById(id);
            if (node) node.textContent = (val !== undefined && val !== null && val !== '') ? String(val) : '-';
        };

        setTxt('drawer-qr-title', c.codigo_qr);
        setTxt('drawer-serie-title', `Série: ${c.numero_serie_ogiva || '-'}`);

        const linkPassaporte = document.getElementById('drawer-link-passaporte');
        if (linkPassaporte) {
            linkPassaporte.href = `/v/cilindro/${encodeURIComponent(c.codigo_qr)}/`;
        }

        const linkCasco = document.getElementById('drawer-link-etiqueta-casco');
        if (linkCasco) {
            linkCasco.href = `/produtos/cilindros/${c.id}/etiqueta-casco/`;
        }

        const linkColarinho = document.getElementById('drawer-link-etiqueta-colarinho');
        if (linkColarinho) {
            if (c.envase_atual) {
                linkColarinho.classList.remove('is-hidden');
                linkColarinho.href = `/produtos/cilindros/${c.id}/etiqueta-colarinho/`;
            } else {
                linkColarinho.classList.add('is-hidden');
            }
        }

        // Ficha Técnica
        setTxt('drawer-gas-nome', `${c.gas_nome || '-'} (${c.gas_sigla || '-'})`);
        setTxt('drawer-capacidade', `${c.volume_litros || '-'}L (${c.pressao_servico_bar || 200} bar)`);
        setTxt('drawer-tara', c.tara_real_kg ? `${c.tara_real_kg} kg` : 'Não aferida');
        setTxt('drawer-fabricante', `${c.fabricante || '-'} (${c.ano_fabricacao || '-'})`);
        setTxt('drawer-reteste', `${formatarData(c.data_proximo_reteste)} ${c.reteste_vencido ? '⚠️ (VENCIDO)' : '✅'}`);
        setTxt('drawer-status', c.status_display || c.status);
        setTxt('drawer-posse', c.cliente_posse_nome ? `${c.cliente_posse_nome} (desde ${formatarData(c.posse_desde ? c.posse_desde.split('T')[0] : '')})` : 'Pátio Central');

        // Card Patrimônio & CAPEX (Sprint 8A)
        setTxt('drawer-patrimonio-propriedade', c.propriedade_display || c.propriedade);
        setTxt('drawer-patrimonio-numero', c.numero_patrimonio || 'Não tombado');
        setTxt('drawer-patrimonio-valor-aquisicao', c.valor_aquisicao ? `R$ ${Number(c.valor_aquisicao).toFixed(2)}` : '-');
        setTxt('drawer-patrimonio-valor-contabil', c.valor_contabil_liquido_atual ? `R$ ${Number(c.valor_contabil_liquido_atual).toFixed(2)}` : '-');
        setTxt('drawer-patrimonio-lote', c.lote_aquisicao ? `Lote #${c.lote_aquisicao}` : '-');
        setTxt('drawer-patrimonio-nfe', c.chave_nfe_aquisicao ? `${c.chave_nfe_aquisicao.slice(0, 6)}...${c.chave_nfe_aquisicao.slice(-6)}` : '-');

        // Atualiza botão de bloqueio sanitário
        const btnToggleBloqueio = document.getElementById('drawer-btn-bloqueio');
        if (btnToggleBloqueio) {
            if (c.bloqueio_sanitario) {
                btnToggleBloqueio.textContent = 'Liberar Bloqueio Sanitário';
                btnToggleBloqueio.classList.remove('action-queue-btn--danger');
                btnToggleBloqueio.classList.add('action-queue-btn--primary');
                btnToggleBloqueio.setAttribute('data-action', 'DESBLOQUEIO');
            } else {
                btnToggleBloqueio.textContent = 'Acionar Bloqueio Sanitário';
                btnToggleBloqueio.classList.remove('action-queue-btn--primary');
                btnToggleBloqueio.classList.add('action-queue-btn--danger');
                btnToggleBloqueio.setAttribute('data-action', 'BLOQUEIO');
            }
        }
    }

    function renderTimelineLedger(movs) {
        const container = document.getElementById('drawer-timeline-container');
        if (!container) return;
        container.innerHTML = '';

        if (!movs || movs.length === 0) {
            container.appendChild(el('p', 'drawer-muted-text', 'Nenhuma movimentação registrada no livro-razão (Ledger).'));
            return;
        }

        movs.forEach(m => {
            const item = el('div', 'timeline-item');

            let dotClasse = 'dot-approved';
            if (m.tipo === 'ESTORNO') dotClasse = 'dot-estorno';
            else if (m.tipo === 'ENTREGA_CLIENTE') dotClasse = 'dot-transit';
            else if (m.tipo === 'RECOLHA_CLIENTE') dotClasse = 'dot-warning';
            else if (m.tipo === 'BAIXA') dotClasse = 'dot-danger';

            const dot = el('div', `timeline-dot ${dotClasse}`);
            const dotInner = el('div', '', '', { style: 'width: 6px; height: 6px; border-radius: 50%; background: currentColor;' });
            dot.appendChild(dotInner);
            item.appendChild(dot);

            const content = el('div', 'timeline-content');
            const header = el('div', 'timeline-header');

            const title = el('span', 'timeline-title');
            title.appendChild(document.createTextNode(m.tipo_display || m.tipo));
            if (m.estornada) {
                const tagEstornada = el('span', 'drawer-header-subtitle font-mono', ' [ESTORNADA]');
                title.appendChild(tagEstornada);
            }
            header.appendChild(title);

            const time = el('span', 'timeline-time', new Date(m.registrado_em).toLocaleString('pt-BR'));
            header.appendChild(time);
            content.appendChild(header);

            const desc = el('p', 'timeline-desc');
            if (m.cliente_nome) {
                desc.appendChild(document.createTextNode('Cliente: '));
                desc.appendChild(el('strong', '', m.cliente_nome));
                desc.appendChild(document.createElement('br'));
            }
            desc.appendChild(document.createTextNode(`Transição: ${m.status_anterior || '-'} → `));
            desc.appendChild(el('strong', '', m.status_novo || '-'));
            desc.appendChild(document.createElement('br'));

            desc.appendChild(document.createTextNode('Registrado por: '));
            desc.appendChild(el('em', '', m.registrado_por_nome || 'Sistema'));

            if (m.observacao) {
                desc.appendChild(document.createElement('br'));
                desc.appendChild(el('span', '', m.observacao));
            }
            content.appendChild(desc);

            if (!m.estornada && m.tipo !== 'ESTORNO') {
                const divEstorno = el('div', 'text-right');
                const btnEstorno = el('button', 'btn-page font-sm', 'Estornar Lançamento', {
                    type: 'button',
                    'data-mov-id': String(m.id),
                    'data-tipo': m.tipo_display || m.tipo
                });
                btnEstorno.addEventListener('click', () => {
                    iniciarModalEstorno(m.id, m.tipo_display || m.tipo);
                });
                divEstorno.appendChild(btnEstorno);
                content.appendChild(divEstorno);
            }

            item.appendChild(content);
            container.appendChild(item);
        });
    }

    function renderTimelineRetestes(retestes) {
        const container = document.getElementById('drawer-retestes-timeline');
        const countBadge = document.getElementById('drawer-reteste-count');
        if (!container) return;
        container.innerHTML = '';

        if (countBadge) {
            const qtd = retestes ? retestes.length : 0;
            countBadge.textContent = `${qtd} ${qtd === 1 ? 'ensaio' : 'ensaios'}`;
        }

        if (!retestes || retestes.length === 0) {
            container.appendChild(el('p', 'drawer-muted-text', 'Nenhum ensaio hidrostático registrado.'));
            return;
        }

        retestes.forEach(r => {
            const isAprovado = r.resultado === 'APROVADO';
            const card = el('div', 'drawer-card-box');

            const header = el('div', 'drawer-card-title drawer-card-title--between');
            const spanData = el('span', '', formatarData(r.data_execucao));
            if (r.retifica) {
                const badgeRetifica = el('span', 'drawer-badge-count', 'Retificação');
                spanData.appendChild(badgeRetifica);
            }
            header.appendChild(spanData);

            const badgeRes = el('span', `badge ${isAprovado ? 'badge-status-approved' : 'badge-status-danger'}`, r.resultado_display || r.resultado);
            header.appendChild(badgeRes);
            card.appendChild(header);

            const corpo = el('div', 'drawer-header-subtitle');
            corpo.appendChild(el('div', '', `Certificado: ${r.numero_certificado || 'Carga Legada'} | Oficina: ${r.oficina_nome || '-'}`));
            corpo.appendChild(el('div', '', `Exp. Permanente: ${r.expansao_permanente_percentual ? r.expansao_permanente_percentual + '%' : '-'} (Limite: ${r.limite_expansao_percentual_aplicado || '-'}%)`));
            if (r.tara_real_kg) {
                corpo.appendChild(el('div', '', `Tara Aferida: ${r.tara_real_kg} kg ${r.variacao_tara_percentual ? `(Var: ${r.variacao_tara_percentual}%)` : ''}`));
            }
            if (r.data_proximo_reteste) {
                corpo.appendChild(el('div', '', `Próximo Vencimento: ${formatarData(r.data_proximo_reteste)}`));
            }
            if (r.motivo_reprovacao) {
                const divMotivo = el('div', 'text-danger', `Motivo: ${r.motivo_reprovacao}`);
                corpo.appendChild(divMotivo);
            }

            card.appendChild(corpo);
            container.appendChild(card);
        });
    }

    // --------------------------------------------------------------------------
    // 5. AÇÕES CONTEXTUAIS E MODAIS
    // --------------------------------------------------------------------------

    // 5.1 Bloqueio / Liberação Sanitária (RT)
    const btnDrawerBloqueio = document.getElementById('drawer-btn-bloqueio');
    if (btnDrawerBloqueio && modalBloqueio) {
        const formBloqueio = document.getElementById('form-bloqueio-sanitario');
        ligarFechar(modalBloqueio);

        btnDrawerBloqueio.addEventListener('click', () => {
            const acao = btnDrawerBloqueio.getAttribute('data-action') || 'BLOQUEIO';
            const bloquear = acao === 'BLOQUEIO';
            limparErros(formBloqueio);
            document.getElementById('modal-bloqueio-acao-title').textContent = bloquear ? 'Bloquear cilindro (sanitário)' : 'Liberar bloqueio sanitário';
            document.getElementById('bloqueio-acao-input').value = acao;
            document.getElementById('bloqueio-justificativa').value = '';
            document.getElementById('bloqueio-alvo').textContent = rotuloCilindro();
            const confirmar = document.getElementById('btn-confirmar-bloqueio');
            confirmar.textContent = bloquear ? 'Bloquear cilindro' : 'Liberar cilindro';
            confirmar.className = bloquear ? 'btn-danger' : 'btn-primary';
            modalBloqueio.showModal();
        });

        const btnCancBloq = document.getElementById('btn-cancelar-bloqueio');
        if (btnCancBloq) btnCancBloq.addEventListener('click', () => modalBloqueio.close());

        formBloqueio.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (window.Baros && typeof Baros.validarCampos === 'function' && !Baros.validarCampos(formBloqueio)) return;
            const acao = document.getElementById('bloqueio-acao-input').value;
            const bloquear = acao === 'BLOQUEIO';
            modalBloqueio.close();

            const ok = await Baros.confirmar({
                titulo: bloquear ? 'Confirmar o bloqueio?' : 'Confirmar a liberação?',
                texto: rotuloCilindro() + (bloquear ? '. O cilindro não poderá ser expedido até ser liberado.' : '. O cilindro volta a poder ser expedido.'),
                botao: bloquear ? 'Bloquear' : 'Liberar',
                perigo: bloquear,
            });
            if (!ok) { modalBloqueio.showModal(); return; }

            try {
                await Baros.api(`/produtos/api/cilindros/${activeCilindroId}/bloqueio-sanitario/`, {
                    method: 'POST',
                    body: { acao, motivo: document.getElementById('bloqueio-justificativa').value.trim() },
                });
                aposAcao(bloquear ? 'Cilindro bloqueado.' : 'Bloqueio liberado.');
            } catch (err) {
                if (window.Baros && typeof Baros.erro === 'function') Baros.erro(err.message || 'Erro ao processar bloqueio');
            }
        });
    }

    // 5.2 Retorno de Reteste (variação de tara ao vivo; tolerância de 5%)
    const btnDrawerReteste = document.getElementById('drawer-btn-reteste');
    if (btnDrawerReteste && modalReteste) {
        const formReteste = document.getElementById('form-retorno-reteste');
        const campoTara = document.getElementById('reteste-nova-tara');
        const avisoTara = document.getElementById('reteste-variacao-tara');
        const TOLERANCIA_TARA_PCT = 5;
        const fmt = (v) => Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        ligarFechar(modalReteste);

        function atualizarVariacaoTara() {
            const atual = activeCilindroData ? Number(activeCilindroData.tara_real_kg) : 0;
            const nova = Number(campoTara.value);
            avisoTara.classList.remove('ds-alerta-texto');
            if (!atual) { avisoTara.textContent = 'Sem tara registrada para comparar.'; return; }
            if (!campoTara.value) { avisoTara.textContent = `Tara atual: ${fmt(atual)} kg`; return; }
            const pct = ((nova - atual) / atual) * 100;
            const texto = `Atual ${fmt(atual)} kg · variação ${pct >= 0 ? '+' : ''}${fmt(pct)}%`;
            if (Math.abs(pct) > TOLERANCIA_TARA_PCT) {
                avisoTara.textContent = texto + ` (acima da tolerância de ${TOLERANCIA_TARA_PCT}%: registre no laudo)`;
                avisoTara.classList.add('ds-alerta-texto');
            } else {
                avisoTara.textContent = texto;
            }
        }
        if (campoTara) campoTara.addEventListener('input', atualizarVariacaoTara);

        btnDrawerReteste.addEventListener('click', () => {
            limparErros(formReteste);
            const dtField = document.getElementById('reteste-data-realizado');
            if (dtField) dtField.valueAsDate = new Date();
            if (campoTara) campoTara.value = activeCilindroData && activeCilindroData.tara_real_kg ? activeCilindroData.tara_real_kg : '';
            const obsField = document.getElementById('reteste-obs');
            if (obsField) obsField.value = '';
            atualizarVariacaoTara();
            modalReteste.showModal();
        });

        const btnCancRet = document.getElementById('btn-cancelar-reteste');
        if (btnCancRet) btnCancRet.addEventListener('click', () => modalReteste.close());

        if (formReteste) {
            formReteste.addEventListener('submit', async (e) => {
                e.preventDefault();
                if (window.Baros && typeof Baros.validarCampos === 'function' && !Baros.validarCampos(formReteste)) return;
                try {
                    await Baros.api(`/produtos/api/cilindros/${activeCilindroId}/retorno-reteste/`, {
                        method: 'POST',
                        body: {
                            nova_data_reteste: document.getElementById('reteste-data-realizado').value,
                            nova_tara_kg: campoTara.value,
                            observacao: document.getElementById('reteste-obs').value.trim(),
                        },
                    });
                    modalReteste.close();
                    aposAcao('Reteste registrado e validade renovada.');
                } catch (err) {
                    if (window.Baros && typeof Baros.mostrarErrosApi === 'function') {
                        Baros.mostrarErrosApi(formReteste, err);
                    }
                }
            });
        }
    }

    // 5.3 Reclassificar Gás
    const btnDrawerReclassificar = document.getElementById('drawer-btn-reclassificar');
    if (btnDrawerReclassificar && modalReclassificar) {
        const formReclassificar = document.getElementById('form-reclassificar-gas');
        ligarFechar(modalReclassificar);

        btnDrawerReclassificar.addEventListener('click', async () => {
            const selectGas = document.getElementById('reclassificar-novo-gas');
            formReclassificar.reset();
            limparErros(formReclassificar);
            selectGas.innerHTML = '';
            selectGas.appendChild(new Option('Carregando gases...', ''));
            modalReclassificar.showModal();
            try {
                const gases = await Baros.api('/produtos/api/catalogo/gases/');
                const gasAtual = activeCilindroData ? activeCilindroData.gas_dedicado : null;
                selectGas.innerHTML = '';
                selectGas.appendChild(new Option('Selecione o novo gás...', ''));
                gases.filter(g => g.id !== gasAtual).forEach(g => {
                    const cor = g.cor_padrao_abnt ? ` [${g.cor_padrao_abnt}]` : '';
                    selectGas.appendChild(new Option(`${g.nome} (${g.sigla})${cor}`, g.id));
                });
            } catch (err) {
                selectGas.innerHTML = '';
                selectGas.appendChild(new Option('Erro ao carregar a lista de gases', ''));
            }
        });

        const btnCancReclass = document.getElementById('btn-cancelar-reclassificar');
        if (btnCancReclass) btnCancReclass.addEventListener('click', () => modalReclassificar.close());

        if (formReclassificar) {
            formReclassificar.addEventListener('submit', async (e) => {
                e.preventDefault();
                if (window.Baros && typeof Baros.validarCampos === 'function' && !Baros.validarCampos(formReclassificar)) return;
                try {
                    await Baros.api(`/produtos/api/cilindros/${activeCilindroId}/reclassificar/`, {
                        method: 'POST',
                        body: {
                            novo_gas_id: document.getElementById('reclassificar-novo-gas').value,
                            descontaminacao_purga_executada: document.getElementById('check-purga').checked,
                            troca_valvula_executada: document.getElementById('check-valvula').checked,
                            adequacao_pintura_executada: document.getElementById('check-pintura').checked,
                            observacoes: document.getElementById('reclassificar-obs').value.trim(),
                        },
                    });
                    modalReclassificar.close();
                    aposAcao('Cilindro reclassificado.');
                } catch (err) {
                    if (window.Baros && typeof Baros.mostrarErrosApi === 'function') {
                        Baros.mostrarErrosApi(formReclassificar, err);
                    }
                }
            });
        }
    }

    // 5.4 Estorno Auditado do Ledger
    function iniciarModalEstorno(movId, tipo) {
        if (!modalEstorno) return;
        const formEstorno = document.getElementById('form-estorno-ledger');
        limparErros(formEstorno);
        document.getElementById('estorno-mov-id').value = movId;
        document.getElementById('estorno-mov-desc').textContent = `Lançamento #${movId} · ${tipo} · ${rotuloCilindro()}`;
        document.getElementById('estorno-justificativa').value = '';
        modalEstorno.showModal();
    }

    if (modalEstorno) {
        const formEstorno = document.getElementById('form-estorno-ledger');
        ligarFechar(modalEstorno);
        const btnCancEstorno = document.getElementById('btn-cancelar-estorno');
        if (btnCancEstorno) btnCancEstorno.addEventListener('click', () => modalEstorno.close());

        formEstorno.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (window.Baros && typeof Baros.validarCampos === 'function' && !Baros.validarCampos(formEstorno)) return;
            try {
                await Baros.api(`/produtos/api/cilindros/${activeCilindroId}/estorno/`, {
                    method: 'POST',
                    body: {
                        movimentacao_id: document.getElementById('estorno-mov-id').value,
                        justificativa: document.getElementById('estorno-justificativa').value.trim(),
                    },
                });
                modalEstorno.close();
                aposAcao('Lançamento estornado.');
            } catch (err) {
                if (window.Baros && typeof Baros.mostrarErrosApi === 'function') {
                    Baros.mostrarErrosApi(formEstorno, err);
                }
            }
        });
    }

    // 5.5 Etiqueta Térmica QR Patrimonial 60x40mm
    const btnDrawerEtiqueta = document.getElementById('drawer-btn-etiqueta');
    if (btnDrawerEtiqueta && modalEtiqueta) {
        btnDrawerEtiqueta.addEventListener('click', () => {
            if (!activeCilindroData) return;
            document.getElementById('label-qr-code').textContent = activeCilindroData.codigo_qr;
            document.getElementById('label-serie').textContent = activeCilindroData.numero_serie_ogiva;
            document.getElementById('label-gas').textContent = `${activeCilindroData.gas_sigla} - ${activeCilindroData.gas_nome}`;
            document.getElementById('label-tara').textContent = `Tara: ${activeCilindroData.tara_real_kg || '-'} kg | Vol: ${activeCilindroData.volume_litros || '-'}L`;
            document.getElementById('label-reteste').textContent = `Reteste: ${formatarData(activeCilindroData.data_proximo_reteste)}`;
            modalEtiqueta.showModal();
        });

        const btnFecharEtiqueta = document.getElementById('btn-fechar-etiqueta');
        if (btnFecharEtiqueta) btnFecharEtiqueta.addEventListener('click', () => modalEtiqueta.close());
    }

    // --------------------------------------------------------------------------
    // 6. FILTROS RÁPIDOS E BUSCA
    // --------------------------------------------------------------------------
    if (inputSearch) {
        let timeout = null;
        inputSearch.addEventListener('input', (e) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => {
                currentSearch = e.target.value.trim();
                currentPage = 1;
                atualizarUrlFiltros();
                carregarCilindros(1);
            }, 300);
        });
    }

    filterPills.forEach(pill => {
        pill.addEventListener('click', () => {
            const f = pill.getAttribute('data-filter');
            aplicarFiltro(f);
        });
    });

    kpiCards.forEach(card => {
        card.addEventListener('click', () => {
            const f = card.getAttribute('data-filtro');
            aplicarFiltro(f);
        });
    });

    if (btnPrevPage) {
        btnPrevPage.addEventListener('click', () => {
            if (currentPage > 1) carregarCilindros(currentPage - 1);
        });
    }

    if (btnNextPage) {
        btnNextPage.addEventListener('click', () => {
            carregarCilindros(currentPage + 1);
        });
    }

    // --------------------------------------------------------------------------
    // 7. INICIALIZAÇÃO
    // --------------------------------------------------------------------------
    lerFiltrosDaUrl();
    carregarResumoFrota();
    carregarCilindros(currentPage);

    // Exposição global para a barra de comando (Ctrl+K) e cadastro
    window.abrirDrawerAtivo = abrirDrawerAtivo;
    window.CilindrosFrota = {
        recarregar: () => {
            carregarResumoFrota();
            carregarCilindros(1);
        },
        abrir: (id) => abrirDrawerAtivo(id)
    };

    // Abertura automática caso haja parâmetro cilindro_id ou abrir_drawer na URL
    const urlParams = new URLSearchParams(window.location.search);
    const paramCilindroId = urlParams.get('cilindro_id') || urlParams.get('abrir_drawer');
    if (paramCilindroId) {
        setTimeout(() => abrirDrawerAtivo(paramCilindroId), 300);
    }
});
