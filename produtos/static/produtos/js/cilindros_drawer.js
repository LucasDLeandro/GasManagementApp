/**
 * Baros - Cilindros Ativo 360° & Drawer de Auditoria (Fase 1)
 * Modular Vanilla JS com zero dependências externas e suporte a RBAC nativo.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Estado local da tela de ativos
    let currentPage = 1;
    let currentFilter = 'todos';
    let currentSearch = '';
    let totalCilindros = 0;
    let activeCilindroId = null;
    let activeCilindroData = null;

    // Elementos DOM principais
    const tbodyCilindros = document.getElementById('cilindros-tbody');
    const inputSearch = document.getElementById('input-busca-cilindros');
    const paginationInfo = document.getElementById('pagination-info');
    const btnPrevPage = document.getElementById('btn-prev-page');
    const btnNextPage = document.getElementById('btn-next-page');
    const filterPills = document.querySelectorAll('.pill-filter-btn');

    // Dialog Drawer & Modais Contextuais
    const drawerDialog = document.getElementById('cylinder-drawer');
    const btnCloseDrawer = document.getElementById('btn-close-drawer');

    const modalBloqueio = document.getElementById('modal-bloqueio-sanitario');
    const modalReteste = document.getElementById('modal-retorno-reteste');
    const modalReclassificar = document.getElementById('modal-reclassificar-gas');
    const modalEstorno = document.getElementById('modal-estorno-ledger');
    const modalEtiqueta = document.getElementById('modal-etiqueta-termica');

    function getAuthHeaders() {
        const token = localStorage.getItem('access_token');
        const headers = {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        };
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function getOgivaClass(sigla) {
        if (!sigla) return 'ogiva-oxigenio-ind';
        const s = sigla.toUpperCase();
        if (s.includes('MED')) return 'ogiva-oxigenio-med';
        if (s.includes('IND')) return 'ogiva-oxigenio-ind';
        if (s.includes('N2') || s.includes('NIT')) return 'ogiva-nitrogenio';
        if (s.includes('AR') || s.includes('ARG')) return 'ogiva-argonio';
        if (s.includes('CO2')) return 'ogiva-co2';
        if (s.includes('AC') || s.includes('ACET')) return 'ogiva-acetileno';
        if (s.includes('AR-COMP')) return 'ogiva-ar-comp';
        return 'ogiva-oxigenio-ind';
    }

    // ==============================================================================
    // 1. CARREGAMENTO E PAGINAÇÃO DE CILINDROS
    // ==============================================================================
    async function carregarCilindros(page = 1) {
        currentPage = page;
        if (tbodyCilindros) {
            tbodyCilindros.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--color-text-muted); padding: 30px;">Carregando frota de cilindros...</td></tr>';
        }

        let url = `/produtos/api/cilindros/?page=${page}`;
        if (currentSearch) {
            url += `&q=${encodeURIComponent(currentSearch)}`;
        }

        if (currentFilter === 'CHEIO_DISPONIVEL') url += '&status=CHEIO_DISPONIVEL';
        else if (currentFilter === 'EM_POSSE_CLIENTE') url += '&status=EM_POSSE_CLIENTE';
        else if (currentFilter === 'VAZIO_TRIAGEM') url += '&status=VAZIO_TRIAGEM';
        else if (currentFilter === 'bloqueio_sanitario') url += '&bloqueio_sanitario=true';
        else if (currentFilter === 'reteste_vencido') url += '&reteste_vencido=true';
        else if (currentFilter === 'proprio') url += '&propriedade=DISTRIBUIDORA';

        try {
            const res = await fetch(url, { headers: getAuthHeaders() });
            if (!res.ok) throw new Error("Erro ao consultar API de cilindros");
            const data = await res.json();

            const cilindros = data.results || (Array.isArray(data) ? data : []);
            totalCilindros = data.count || cilindros.length;

            renderTabelaCilindros(cilindros);
            atualizarControlesPaginacao(data.count, data.next, data.previous);
        } catch (err) {
            console.error("Erro ao carregar cilindros:", err);
            if (tbodyCilindros) {
                tbodyCilindros.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--color-danger); padding: 30px;">Erro ao carregar ativos: ${err.message}</td></tr>`;
            }
        }
    }

    function renderTabelaCilindros(cilindros) {
        if (!tbodyCilindros) return;
        if (cilindros.length === 0) {
            tbodyCilindros.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--color-text-muted); padding: 40px;">Nenhum cilindro encontrado com os filtros selecionados.</td></tr>';
            return;
        }

        tbodyCilindros.innerHTML = cilindros.map(c => {
            const ogivaClass = getOgivaClass(c.gas_sigla);
            let statusBadge = '<span class="badge-status badge-normal">Disponível</span>';
            if (c.status === 'EM_POSSE_CLIENTE') {
                statusBadge = '<span class="badge-status" style="background:#e0f2fe; color:#0369a1;">Em Cliente</span>';
            } else if (c.status === 'VAZIO_TRIAGEM') {
                statusBadge = '<span class="badge-status" style="background:#fef3c7; color:#92400e;">Vazio / Triagem</span>';
            } else if (c.status === 'EM_RETESTE') {
                statusBadge = '<span class="badge-status" style="background:#f3e8ff; color:#7e22ce;">Em Reteste</span>';
            } else if (c.status === 'RESERVADO_ROTA') {
                statusBadge = '<span class="badge-status" style="background:#e0e7ff; color:#3730a3;">Em Rota</span>';
            } else if (c.status === 'BAIXADO') {
                statusBadge = '<span class="badge-status badge-critico">Baixado</span>';
            }

            let retesteBadge = `<span style="color: var(--color-text); font-weight: 500;">${formatarData(c.data_proximo_reteste)}</span>`;
            if (c.reteste_vencido) {
                retesteBadge = `<span style="color: var(--status-danger); font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    VENCIDO (${formatarData(c.data_proximo_reteste)})
                </span>`;
            }

            let bloqueioBadge = '<span style="color: var(--status-approved); font-weight: 600;">Livre</span>';
            if (c.bloqueio_sanitario) {
                bloqueioBadge = `<span class="badge-status badge-critico" title="${c.motivo_bloqueio_sanitario || 'Bloqueio Ativo'}">BLOQUEADO</span>`;
            }

            return `
                <tr style="cursor: pointer;" data-id="${c.id}" class="cilindro-row">
                    <td>
                        <div class="tech-id-badge">
                            ${c.codigo_qr}
                            <button class="copy-btn" data-copy="${c.codigo_qr}" title="Copiar QR Code">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                            </button>
                        </div>
                        <div style="font-size: 11px; color: var(--color-text-muted); margin-top: 3px;">
                            Série: <strong class="font-mono">${c.numero_serie_ogiva}</strong>
                        </div>
                    </td>
                    <td>
                        <div class="gas-badge">
                            <span class="ogiva-dot ${ogivaClass}"></span>
                            <strong>${c.gas_sigla || 'GÁS'}</strong>
                        </div>
                    </td>
                    <td>
                        <strong>${c.volume_litros || c.modelo_descricao || '-'}L</strong>
                        <div style="font-size: 11px; color: var(--color-text-muted);">${c.tara_real_kg ? c.tara_real_kg + ' kg' : 'Tara s/ aferição'}</div>
                    </td>
                    <td>${statusBadge}</td>
                    <td>${retesteBadge}</td>
                    <td>${bloqueioBadge}</td>
                    <td>
                        ${c.cliente_posse_nome ? `<strong>${c.cliente_posse_nome}</strong>` : '<span style="color: var(--color-text-muted);">Pátio Central</span>'}
                    </td>
                    <td>
                        <button class="action-queue-btn btn-abrir-drawer" data-id="${c.id}" style="padding: 5px 10px; font-size: 12px;">
                            Auditar Ativo
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        // Event listener de clique nas linhas e botões
        document.querySelectorAll('.cilindro-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.copy-btn')) return;
                const id = row.getAttribute('data-id');
                abrirDrawerAtivo(id);
            });
        });

        document.querySelectorAll('.btn-abrir-drawer').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.getAttribute('data-id');
                abrirDrawerAtivo(id);
            });
        });
    }

    function atualizarControlesPaginacao(count, next, previous) {
        if (!paginationInfo) return;
        const totalPages = Math.ceil((count || 1) / 20) || 1;
        paginationInfo.textContent = `Página ${currentPage} de ${totalPages} (${count || 0} cilindros)`;
        if (btnPrevPage) btnPrevPage.disabled = !previous;
        if (btnNextPage) btnNextPage.disabled = !next;
    }

    function formatarData(dataIso) {
        if (!dataIso) return '-';
        const parts = dataIso.split('-');
        if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
        return dataIso;
    }

    // ==============================================================================
    // 2. GAVETA LATERAL DESLIZANTE (DRAWER / <dialog> NATIVO)
    // ==============================================================================
    async function abrirDrawerAtivo(cilindroId) {
        activeCilindroId = cilindroId;
        if (!drawerDialog) {
            console.error("Elemento #cylinder-drawer não encontrado no DOM!");
            return;
        }

        // Limpa e abre o dialog nativo
        const elQrTitle = document.getElementById('drawer-qr-title');
        const elSerieTitle = document.getElementById('drawer-serie-title');
        const elTimeline = document.getElementById('drawer-timeline-container');
        if (elQrTitle) elQrTitle.textContent = 'Carregando...';
        if (elSerieTitle) elSerieTitle.textContent = '';
        if (elTimeline) elTimeline.innerHTML = '<p style="color: var(--color-text-muted);">Carregando histórico do ledger...</p>';

        if (!drawerDialog.open) {
            drawerDialog.showModal();
        }

        try {
            // Busca dados do cilindro
            const resCil = await fetch(`/produtos/api/cilindros/${cilindroId}/`, { headers: getAuthHeaders() });
            if (!resCil.ok) throw new Error("Erro ao buscar detalhes do cilindro");
            activeCilindroData = await resCil.json();

            renderDetalhesDrawer(activeCilindroData);

            // Busca timeline do ledger
            const resTimeline = await fetch(`/produtos/api/cilindros/${cilindroId}/timeline/`, { headers: getAuthHeaders() });
            if (resTimeline.ok) {
                const timeline = await resTimeline.json();
                renderTimelineLedger(timeline);
            }

            // Busca histórico perpétuo de retestes (Sprint 8B)
            const resRetestes = await fetch(`/produtos/api/cilindros/${cilindroId}/timeline-retestes/`, { headers: getAuthHeaders() });
            if (resRetestes.ok) {
                const retestes = await resRetestes.json();
                renderTimelineRetestes(retestes);
            }
        } catch (err) {
            console.error("Erro no drawer:", err);
            document.getElementById('drawer-timeline-container').innerHTML = `<p style="color: var(--status-danger);">Erro: ${err.message}</p>`;
        }
    }

    function renderDetalhesDrawer(c) {
        document.getElementById('drawer-qr-title').textContent = c.codigo_qr;
        document.getElementById('drawer-serie-title').textContent = `Série: ${c.numero_serie_ogiva}`;
        document.getElementById('drawer-link-passaporte').href = `/v/cilindro/${encodeURIComponent(c.codigo_qr)}/`;

        const linkCasco = document.getElementById('drawer-link-etiqueta-casco');
        if (linkCasco) {
            linkCasco.href = `/produtos/cilindros/${c.id}/etiqueta-casco/`;
        }

        const linkColarinho = document.getElementById('drawer-link-etiqueta-colarinho');
        if (linkColarinho) {
            if (c.envase_atual) {
                linkColarinho.style.display = 'inline-flex';
                linkColarinho.href = `/produtos/cilindros/${c.id}/etiqueta-colarinho/`;
            } else {
                linkColarinho.style.display = 'none';
            }
        }

        // Preenche Ficha Técnica
        document.getElementById('drawer-gas-nome').textContent = `${c.gas_nome} (${c.gas_sigla})`;
        document.getElementById('drawer-capacidade').textContent = `${c.volume_litros || '-'}L (${c.pressao_servico_bar || 200} bar)`;
        document.getElementById('drawer-tara').textContent = c.tara_real_kg ? `${c.tara_real_kg} kg` : 'Não aferida';
        document.getElementById('drawer-fabricante').textContent = `${c.fabricante} (${c.ano_fabricacao})`;
        document.getElementById('drawer-reteste').textContent = `${formatarData(c.data_proximo_reteste)} ${c.reteste_vencido ? '⚠️ (VENCIDO)' : '✅'}`;
        document.getElementById('drawer-status').textContent = c.status_display;
        document.getElementById('drawer-posse').textContent = c.cliente_posse_nome ? `${c.cliente_posse_nome} (desde ${formatarData(c.posse_desde ? c.posse_desde.split('T')[0] : '')})` : 'Pátio Central';

        // Preenche Card Patrimônio & CAPEX (Sprint 8A)
        const elProp = document.getElementById('drawer-patrimonio-propriedade');
        if (elProp) elProp.textContent = c.propriedade_display || c.propriedade || '-';
        const elPatNum = document.getElementById('drawer-patrimonio-numero');
        if (elPatNum) elPatNum.textContent = c.numero_patrimonio || 'Não tombado';
        const elValAq = document.getElementById('drawer-patrimonio-valor-aquisicao');
        if (elValAq) elValAq.textContent = c.valor_aquisicao ? `R$ ${Number(c.valor_aquisicao).toFixed(2)}` : '-';
        const elValCont = document.getElementById('drawer-patrimonio-valor-contabil');
        if (elValCont) elValCont.textContent = c.valor_contabil_liquido_atual ? `R$ ${Number(c.valor_contabil_liquido_atual).toFixed(2)}` : '-';
        const elLote = document.getElementById('drawer-patrimonio-lote');
        if (elLote) elLote.textContent = c.lote_aquisicao ? `Lote #${c.lote_aquisicao}` : '-';
        const elNfe = document.getElementById('drawer-patrimonio-nfe');
        if (elNfe) elNfe.textContent = c.chave_nfe_aquisicao ? `${c.chave_nfe_aquisicao.slice(0, 6)}...${c.chave_nfe_aquisicao.slice(-6)}` : '-';

        // Atualiza botão de bloqueio sanitário
        const btnToggleBloqueio = document.getElementById('drawer-btn-bloqueio');
        if (btnToggleBloqueio) {
            if (c.bloqueio_sanitario) {
                btnToggleBloqueio.textContent = 'Liberar Bloqueio Sanitário';
                btnToggleBloqueio.style.background = '#059669';
                btnToggleBloqueio.setAttribute('data-action', 'DESBLOQUEIO');
            } else {
                btnToggleBloqueio.textContent = 'Acionar Bloqueio Sanitário';
                btnToggleBloqueio.style.background = '#dc2626';
                btnToggleBloqueio.setAttribute('data-action', 'BLOQUEIO');
            }
        }
    }

    function renderTimelineLedger(movs) {
        const container = document.getElementById('drawer-timeline-container');
        if (!container) return;

        if (!movs || movs.length === 0) {
            container.innerHTML = '<p style="color: var(--color-text-muted); font-size: 13px;">Nenhuma movimentação registrada no livro-razão (Ledger).</p>';
            return;
        }

        container.innerHTML = movs.map(m => {
            let dotClass = 'dot-approved';
            if (m.tipo === 'ESTORNO') dotClass = 'dot-estorno';
            else if (m.tipo === 'ENTREGA_CLIENTE') dotClass = 'dot-transit';
            else if (m.tipo === 'RECOLHA_CLIENTE') dotClass = 'dot-warning';
            else if (m.tipo === 'BAIXA') dotClass = 'dot-danger';

            return `
                <div class="timeline-item">
                    <div class="timeline-dot ${dotClass}">
                        <div style="width: 6px; height: 6px; border-radius: 50%; background: currentColor;"></div>
                    </div>
                    <div class="timeline-content">
                        <div class="timeline-header">
                            <span class="timeline-title">
                                ${m.tipo_display}
                                ${m.estornada ? '<span style="color: #8b5cf6; font-size: 11px; margin-left: 6px;">[ESTORNADA]</span>' : ''}
                            </span>
                            <span class="timeline-time">${new Date(m.registrado_em).toLocaleString('pt-BR')}</span>
                        </div>
                        <p class="timeline-desc">
                            ${m.cliente_nome ? `Cliente: <strong>${m.cliente_nome}</strong><br>` : ''}
                            Transição: ${m.status_anterior} &rarr; <strong>${m.status_novo}</strong><br>
                            Registrado por: <em>${m.registrado_por_nome}</em>
                            ${m.observacao ? `<br><span style="color: var(--color-text);">${m.observacao}</span>` : ''}
                        </p>
                        ${!m.estornada && m.tipo !== 'ESTORNO' ? `
                            <div style="margin-top: 6px; text-align: right;">
                                <button class="btn-iniciar-estorno" data-mov-id="${m.id}" data-tipo="${m.tipo_display}" style="background: none; border: 1px solid var(--color-border); border-radius: 4px; padding: 2px 8px; font-size: 11px; color: var(--color-text-muted); cursor: pointer;">
                                    Estornar Lançamento
                                </button>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');

        // Listeners para estorno de movimentações individuais
        document.querySelectorAll('.btn-iniciar-estorno').forEach(btn => {
            btn.addEventListener('click', () => {
                const movId = btn.getAttribute('data-mov-id');
                const tipo = btn.getAttribute('data-tipo');
                iniciarModalEstorno(movId, tipo);
            });
        });
    }

    function renderTimelineRetestes(retestes) {
        const container = document.getElementById('drawer-retestes-timeline');
        const countBadge = document.getElementById('drawer-reteste-count');
        if (!container) return;

        if (countBadge) {
            const qtd = retestes ? retestes.length : 0;
            countBadge.textContent = `${qtd} ${qtd === 1 ? 'ensaio' : 'ensaios'}`;
        }

        if (!retestes || retestes.length === 0) {
            container.innerHTML = `<p style="color: var(--color-text-muted); font-size: 12px; margin: 4px 0;">Nenhum ensaio hidrostático registrado.</p>`;
            return;
        }

        container.innerHTML = retestes.map(r => {
            const isAprovado = r.resultado === 'APROVADO';
            const badgeColor = isAprovado ? '#10b981' : '#ef4444';
            const badgeBg = isAprovado ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)';
            const retificaBadge = r.retifica ? `<span style="font-size: 10px; background: rgba(245, 158, 11, 0.2); color: #f59e0b; padding: 1px 4px; border-radius: 3px; margin-left: 6px;">Retificação</span>` : '';

            return `
                <div style="background: rgba(30, 41, 59, 0.5); border-left: 3px solid ${badgeColor}; padding: 8px 10px; border-radius: 4px; font-size: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <span style="font-weight: 700; color: #f1f5f9;">
                            ${formatarData(r.data_execucao)}
                            ${retificaBadge}
                        </span>
                        <span style="font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; background: ${badgeBg}; color: ${badgeColor};">
                            ${r.resultado_display || r.resultado}
                        </span>
                    </div>
                    <div style="color: #94a3b8; font-size: 11px; display: flex; flex-direction: column; gap: 2px;">
                        <div><strong>Certificado:</strong> ${r.numero_certificado || 'Carga Legada'} | <strong>Oficina:</strong> ${r.oficina_nome || '-'}</div>
                        <div><strong>Exp. Permanente:</strong> ${r.expansao_permanente_percentual ? r.expansao_permanente_percentual + '%' : '-'} (Limite: ${r.limite_expansao_percentual_aplicado}%)</div>
                        ${r.tara_real_kg ? `<div><strong>Tara Aferida:</strong> ${r.tara_real_kg} kg ${r.variacao_tara_percentual ? `(Var: ${r.variacao_tara_percentual}%)` : ''}</div>` : ''}
                        ${r.data_proximo_reteste ? `<div><strong>Próximo Vencimento:</strong> ${formatarData(r.data_proximo_reteste)}</div>` : ''}
                        ${r.motivo_reprovacao ? `<div style="color: #f87171;"><strong>Motivo:</strong> ${r.motivo_reprovacao}</div>` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }

    if (btnCloseDrawer && drawerDialog) {
        btnCloseDrawer.addEventListener('click', () => drawerDialog.close());
    }

    // ==============================================================================
    // 3. AÇÕES CONTEXTUAIS E MODAIS
    // ==============================================================================

    // 3.1 Bloqueio / Liberação Sanitária (RT)
    const btnDrawerBloqueio = document.getElementById('drawer-btn-bloqueio');
    if (btnDrawerBloqueio && modalBloqueio) {
        btnDrawerBloqueio.addEventListener('click', () => {
            const acao = btnDrawerBloqueio.getAttribute('data-action') || 'BLOQUEIO';
            document.getElementById('modal-bloqueio-acao-title').textContent = acao === 'BLOQUEIO' ? 'Acionar Bloqueio Sanitário' : 'Liberar Bloqueio Sanitário';
            document.getElementById('bloqueio-acao-input').value = acao;
            document.getElementById('bloqueio-justificativa').value = '';
            modalBloqueio.showModal();
        });

        document.getElementById('btn-cancelar-bloqueio').addEventListener('click', () => modalBloqueio.close());

        document.getElementById('form-bloqueio-sanitario').addEventListener('submit', async (e) => {
            e.preventDefault();
            const acao = document.getElementById('bloqueio-acao-input').value;
            const motivo = document.getElementById('bloqueio-justificativa').value;

            try {
                const res = await fetch(`/produtos/api/cilindros/${activeCilindroId}/bloqueio-sanitario/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ acao, motivo })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "Erro ao processar bloqueio sanitário");

                modalBloqueio.close();
                Swal.fire("Sucesso!", `Bloqueio sanitário ${acao === 'BLOQUEIO' ? 'acionado' : 'liberado'} com sucesso.`, "success");
                abrirDrawerAtivo(activeCilindroId);
                carregarCilindros(currentPage);
            } catch (err) {
                Swal.fire("Erro!", err.message, "error");
            }
        });
    }

    // 3.2 Retorno de Reteste
    const btnDrawerReteste = document.getElementById('drawer-btn-reteste');
    if (btnDrawerReteste && modalReteste) {
        btnDrawerReteste.addEventListener('click', () => {
            document.getElementById('reteste-data-realizado').valueAsDate = new Date();
            document.getElementById('reteste-nova-tara').value = activeCilindroData && activeCilindroData.tara_real_kg ? activeCilindroData.tara_real_kg : '';
            document.getElementById('reteste-obs').value = '';
            modalReteste.showModal();
        });

        document.getElementById('btn-cancelar-reteste').addEventListener('click', () => modalReteste.close());

        document.getElementById('form-retorno-reteste').addEventListener('submit', async (e) => {
            e.preventDefault();
            const nova_data_reteste = document.getElementById('reteste-data-realizado').value;
            const nova_tara_kg = document.getElementById('reteste-nova-tara').value;
            const observacao = document.getElementById('reteste-obs').value;

            try {
                const res = await fetch(`/produtos/api/cilindros/${activeCilindroId}/retorno-reteste/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ nova_data_reteste, nova_tara_kg, observacao })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "Erro ao registrar retorno de reteste");

                modalReteste.close();
                Swal.fire("Aprovado!", "Reteste hidrostático registrado e validade renovada com sucesso.", "success");
                abrirDrawerAtivo(activeCilindroId);
                carregarCilindros(currentPage);
            } catch (err) {
                Swal.fire("Erro no Reteste!", err.message, "error");
            }
        });
    }

    // 3.3 Reclassificar Gás
    const btnDrawerReclassificar = document.getElementById('drawer-btn-reclassificar');
    if (btnDrawerReclassificar && modalReclassificar) {
        btnDrawerReclassificar.addEventListener('click', async () => {
            // Carrega lista de gases químicos
            const selectGas = document.getElementById('reclassificar-novo-gas');
            selectGas.innerHTML = '<option value="">Carregando gases...</option>';
            modalReclassificar.showModal();

            try {
                const res = await fetch('/produtos/api/cilindros/1/reclassificar/', { method: 'OPTIONS', headers: getAuthHeaders() });
                const resGases = await fetch('/produtos/api/?page_size=100', { headers: getAuthHeaders() });
                // Fallback ou carregamento padrão
                selectGas.innerHTML = `
                    <option value="">Selecione o novo gás...</option>
                    <option value="1">Oxigênio Medicinal (O2-MED) [Branco]</option>
                    <option value="2">Oxigênio Industrial (O2-IND) [Verde]</option>
                    <option value="3">Nitrogênio (N2) [Cinza]</option>
                    <option value="4">Argônio (AR) [Marrom]</option>
                    <option value="5">Dióxido de Carbono (CO2) [Alumínio]</option>
                    <option value="6">Acetileno (AC) [Bordô]</option>
                    <option value="7">Ar Comprimido Medicinal (AR-COMP) [Azul]</option>
                `;
            } catch (err) {
                selectGas.innerHTML = '<option value="">Erro ao carregar lista de gases</option>';
            }
        });

        document.getElementById('btn-cancelar-reclassificar').addEventListener('click', () => modalReclassificar.close());

        document.getElementById('form-reclassificar-gas').addEventListener('submit', async (e) => {
            e.preventDefault();
            const novo_gas_id = document.getElementById('reclassificar-novo-gas').value;
            const purga = document.getElementById('check-purga').checked;
            const valvula = document.getElementById('check-valvula').checked;
            const pintura = document.getElementById('check-pintura').checked;
            const observacoes = document.getElementById('reclassificar-obs').value;

            if (!novo_gas_id) {
                Swal.fire("Atenção", "Selecione o gás de destino.", "warning");
                return;
            }

            try {
                const res = await fetch(`/produtos/api/cilindros/${activeCilindroId}/reclassificar/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({
                        novo_gas_id,
                        descontaminacao_purga_executada: purga,
                        troca_valvula_executada: valvula,
                        adequacao_pintura_executada: pintura,
                        observacoes
                    })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "Erro ao reclassificar gás");

                modalReclassificar.close();
                Swal.fire("Reclassificado!", "Cilindro reclassificado com conformidade ABNT e registro de auditoria.", "success");
                abrirDrawerAtivo(activeCilindroId);
                carregarCilindros(currentPage);
            } catch (err) {
                Swal.fire("Erro na Reclassificação", err.message, "error");
            }
        });
    }

    // 3.4 Estorno Auditado do Ledger
    function iniciarModalEstorno(movId, tipo) {
        if (!modalEstorno) return;
        document.getElementById('estorno-mov-id').value = movId;
        document.getElementById('estorno-mov-desc').textContent = `Movimentação #${movId} (${tipo})`;
        document.getElementById('estorno-justificativa').value = '';
        modalEstorno.showModal();
    }

    if (modalEstorno) {
        document.getElementById('btn-cancelar-estorno').addEventListener('click', () => modalEstorno.close());

        document.getElementById('form-estorno-ledger').addEventListener('submit', async (e) => {
            e.preventDefault();
            const movimentacao_id = document.getElementById('estorno-mov-id').value;
            const justificativa = document.getElementById('estorno-justificativa').value;

            try {
                const res = await fetch(`/produtos/api/cilindros/${activeCilindroId}/estorno/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ movimentacao_id, justificativa })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "Erro ao estornar movimentação");

                modalEstorno.close();
                Swal.fire("Estorno Concluído!", "Movimentação revertida com contra-partida no Ledger imutável.", "success");
                abrirDrawerAtivo(activeCilindroId);
                carregarCilindros(currentPage);
            } catch (err) {
                Swal.fire("Erro no Estorno", err.message, "error");
            }
        });
    }

    // 3.5 Etiqueta Térmica QR Patrimonial 60x40mm
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

        document.getElementById('btn-fechar-etiqueta').addEventListener('click', () => modalEtiqueta.close());
    }

    // ==============================================================================
    // 4. FILTROS E BUSCA INSTANTÂNEA
    // ==============================================================================
    if (inputSearch) {
        let timeout = null;
        inputSearch.addEventListener('input', (e) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => {
                currentSearch = e.target.value;
                carregarCilindros(1);
            }, 300);
        });
    }

    filterPills.forEach(pill => {
        pill.addEventListener('click', () => {
            filterPills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            currentFilter = pill.getAttribute('data-filter');
            carregarCilindros(1);
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

    // Carregamento inicial
    carregarCilindros(1);

    // Exposição global para a barra de comando (Ctrl+K)
    window.abrirDrawerAtivo = abrirDrawerAtivo;

    // Abertura automática caso haja parâmetro cilindro_id ou abrir_drawer na URL
    const urlParams = new URLSearchParams(window.location.search);
    const paramCilindroId = urlParams.get('cilindro_id') || urlParams.get('abrir_drawer');
    if (paramCilindroId) {
        setTimeout(() => abrirDrawerAtivo(paramCilindroId), 300);
    }
});
