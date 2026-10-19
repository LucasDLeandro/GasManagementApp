document.addEventListener('DOMContentLoaded', () => {
    // ---- Helpers de Autenticação e CSRF ----
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

    function isTokenExpired(token) {
        if (!token || typeof token !== 'string') return true;
        try {
            const parts = token.split('.');
            if (parts.length !== 3) return true;
            const payloadStr = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
            const payload = JSON.parse(payloadStr);
            if (!payload.exp) return false;
            return (payload.exp * 1000) <= (Date.now() + 10000);
        } catch (e) {
            return true;
        }
    }

    function getAuthHeaders() {
        let token = localStorage.getItem('access_token') || localStorage.getItem('access');
        if (token && isTokenExpired(token)) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('access');
            token = null;
            if (typeof window.renovarTokenSeNecessario === 'function') {
                window.renovarTokenSeNecessario();
            }
        }

        const headers = { 
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') || ''
        };
        if (token) headers['Authorization'] = 'Bearer ' + token;

        const activeTenantMeta = document.querySelector('meta[name="active-tenant-id"]') || document.querySelector('meta[name="current-tenant-id"]');
        if (activeTenantMeta && activeTenantMeta.content) {
            headers['X-Tenant-ID'] = activeTenantMeta.content;
        }

        return headers;
    }

    function getAuthHeadersMultipart() {
        let token = localStorage.getItem('access_token') || localStorage.getItem('access');
        const headers = { 
            'X-CSRFToken': getCookie('csrftoken') || ''
        };
        if (token) headers['Authorization'] = 'Bearer ' + token;

        const activeTenantMeta = document.querySelector('meta[name="active-tenant-id"]') || document.querySelector('meta[name="current-tenant-id"]');
        if (activeTenantMeta && activeTenantMeta.content) {
            headers['X-Tenant-ID'] = activeTenantMeta.content;
        }

        return headers;
    }

    // Helper Universal para Respostas Paginadas ou Nativas do DRF
    function extrairListaDRF(data) {
        if (Array.isArray(data)) return data;
        if (data && Array.isArray(data.results)) return data.results;
        return [];
    }

    // Utilitários de Formatação
    function formatCurrency(value) { 
        return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value || 0); 
    }
    function formatDate(dateStr) { 
        if (!dateStr) return 'N/D';
        const d = new Date(dateStr);
        return isNaN(d) ? dateStr : d.toLocaleString('pt-BR'); 
    }
    function formatPlaca(placa) {
        if (!placa) return 'N/D';
        const p = placa.toUpperCase().trim();
        if (p.length === 7) return p.slice(0, 3) + '-' + p.slice(3);
        return p;
    }

    // ---- Sistema de Abas Segmented Pills ----
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));
            
            btn.classList.add('active');
            const target = btn.getAttribute('data-target');
            const pane = document.getElementById(target);
            if (pane) pane.classList.add('active');
            
            // Carregar dados de acordo com a aba ativada
            if (target === 'tab-entregas') loadKanban();
            if (target === 'tab-veiculos') loadVeiculos();
            if (target === 'tab-rotas') loadRotas();
            if (target === 'tab-combustivel') loadCombustivel();
            if (target === 'tab-manutencao') loadManutencao();
            if (target === 'tab-seguros') loadSegurosESinistros();
            if (target === 'tab-rentabilidade') loadRentabilidade();
            if (target === 'tab-historico') loadHistorico();
        });
    });

    // ==============================================================================
    // 1. QUADRO DE ENTREGAS (KANBAN HÍBRIDO)
    // ==============================================================================
    function loadKanban() {
        // Coluna 1: Pedidos em Separação (Sem Romaneio)
        fetch('/vendas/api/?status=Pendente,Em Separação&entrega__isnull=true&sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' })
            .then(res => {
                if (res.status === 401) {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('access');
                }
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(raw => {
                const data = extrairListaDRF(raw);
                const colSep = document.querySelector('#col-separacao .kanban-items');
                const countBadge = document.getElementById('count-separacao');
                if (countBadge) countBadge.textContent = data.length;
                if (!colSep) return;
                colSep.innerHTML = '';
                
                if (data.length === 0) {
                    colSep.innerHTML = `
                        <div class="empty-state">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <circle cx="12" cy="12" r="10"></circle>
                                <polyline points="12 6 12 12 14 14"></polyline>
                            </svg>
                            <h4>Nenhum pedido pendente</h4>
                            <p>Todos os pedidos foram alocados a cargas ou concluídos.</p>
                        </div>
                    `;
                    return;
                }

                data.forEach(v => {
                    const badgeClass = v.status === 'Em Separação' ? 'em-separacao' : 'pendente';
                    colSep.innerHTML += `
                        <div class="kanban-item">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                                <strong style="font-size:1.05rem;">Pedido #${v.id}</strong>
                                <span class="badge ${badgeClass}">${v.status}</span>
                            </div>
                            <div style="font-size:0.9rem; font-weight:600; color:var(--color-text); margin-bottom:4px;">
                                ${v.cliente_nome || 'Cliente não informado'}
                            </div>
                            <div style="font-size:0.8rem; color:var(--color-text-muted); margin-bottom:12px;">
                                Total: <strong>${formatCurrency(v.valor_total)}</strong>
                            </div>
                            <div style="display:flex; flex-direction:column; gap:6px;">
                                <button class="btn-outline" style="padding:6px; font-size:12px;" onclick="abrirDetalhes(${v.id})">📄 Detalhes da Venda</button>
                                <button class="btn-val-trigger" onclick="abrirValidacaoCarga(${v.id}, 'Em Separação')">⚖️ Validar Envase</button>
                                <button class="btn-primary" style="padding:6px; font-size:12px; width:100%;" onclick="abrirModalAtribuir(${v.id})">🚚 Atribuir a Caminhão</button>
                            </div>
                        </div>
                    `;
                });
            })
            .catch(err => {
                console.error("Erro ao carregar coluna de separação:", err);
            });

        // Coluna 2: Caminhões em Montagem (Agendados / Em Produção)
        fetch('/logistica/api/entregas/?status=Agendada,Em Produção&sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' })
            .then(res => {
                if (res.status === 401) {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('access');
                }
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(raw => {
                const data = extrairListaDRF(raw);
                const colCam = document.querySelector('#col-caminhoes .kanban-items');
                const countBadge = document.getElementById('count-caminhoes');
                if (countBadge) countBadge.textContent = data.length;
                if (!colCam) return;
                colCam.innerHTML = '';

                if (data.length === 0) {
                    colCam.innerHTML = `
                        <div class="empty-state">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <rect x="1" y="3" width="15" height="13"></rect>
                                <polygon points="16 8 20 8 23 11 23 16 16 16 8"></polygon>
                                <circle cx="5.5" cy="18.5" r="2.5"></circle>
                                <circle cx="18.5" cy="18.5" r="2.5"></circle>
                            </svg>
                            <h4>Nenhuma carga em montagem</h4>
                            <p>Crie uma carga para agrupar pedidos ou atribua pedidos na coluna 1.</p>
                        </div>
                    `;
                    return;
                }

                data.forEach(e => renderEntregaCard(e, colCam, false));
            })
            .catch(err => {
                console.error("Erro ao carregar coluna de montagem:", err);
            });

        // Coluna 3: Caminhões Em Rota
        fetch('/logistica/api/entregas/?status=Em Rota&sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' })
            .then(res => {
                if (res.status === 401) {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('access');
                }
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(raw => {
                const data = extrairListaDRF(raw);
                const colRota = document.querySelector('#col-em-rota .kanban-items');
                const countBadge = document.getElementById('count-em-rota');
                if (countBadge) countBadge.textContent = data.length;
                if (!colRota) return;
                colRota.innerHTML = '';

                if (data.length === 0) {
                    colRota.innerHTML = `
                        <div class="empty-state">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <polygon points="3 11 22 2 13 21 11 13 3 11"></polygon>
                            </svg>
                            <h4>Nenhum veículo em rota</h4>
                            <p>Quando um caminhão partir da base, ele será monitorado aqui.</p>
                        </div>
                    `;
                    return;
                }

                data.forEach(e => renderEntregaCard(e, colRota, true));
            })
            .catch(err => {
                console.error("Erro ao carregar coluna em rota:", err);
            });
    }

    // Renderizador Unificado de Cards de Entrega (Coluna 2 e Coluna 3)
    function renderEntregaCard(e, container, emRota) {
        const veiculoDesc = e.veiculo_placa ? `${formatPlaca(e.veiculo_placa)} (${e.veiculo_modelo || 'Veículo'})` : '⚠️ Sem Veículo';
        const capMax = parseFloat(e.veiculo_capacidade) || 0;
        const pesoLoad = parseFloat(e.peso_total_carregado) || 0;
        const percReal = parseFloat(e.percentual_lotacao) || 0;
        const percVisual = Math.min(percReal, 100);

        // Cores da Validação de Capacidade ANTT (D11)
        let barColor = '#10b981'; // Verde (< 80%)
        let statusTexto = 'Normal (<80%)';
        if (percReal >= 100) {
            barColor = '#ef4444'; // Vermelho (Sobrecarga)
            statusTexto = 'SOBRECARGA (>100%)';
        } else if (percReal >= 80) {
            barColor = '#f59e0b'; // Âmbar (Alerta 80-99%)
            statusTexto = 'Alerta Carga (80-99%)';
        }

        // Selo de aviso explícito "Contém peso estimado"
        const seloPesoEstimado = e.possui_peso_estimado 
            ? `<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.3); font-size: 10px; padding: 2px 6px;" title="Cálculo utiliza tara nominal ou massa padrão de modelo">⚠️ Peso Estimado</span>`
            : `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 10px; padding: 2px 6px;">⚖️ Peso Aferido</span>`;

        // Pendência de Veículo ou Motorista
        const hasVeiculo = Boolean(e.veiculo);
        const hasMotorista = Boolean(e.motorista);
        const configPendente = (!hasVeiculo || !hasMotorista) && !emRota;
        const alertaPendente = configPendente 
            ? `<div style="background:rgba(239,68,68,0.1); border:1px dashed #ef4444; color:#ef4444; border-radius:6px; padding:6px; font-size:11px; font-weight:600; margin-bottom:8px; text-align:center;">
                 ⚠️ Veículo ou Motorista não atribuído!
               </div>` 
            : '';

        // Alerta de Veículo Inapto / Em Oficina (Sprint L3)
        const alertaVeiculoInapto = (hasVeiculo && !e.veiculo_apto)
            ? `<div style="background:rgba(239,68,68,0.12); border:1px solid #ef4444; color:#ef4444; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:700; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between; gap:6px;">
                 <span>🚨 Veículo Inapto / Oficina: Realoque a Carga!</span>
                 <button type="button" class="btn-secondary" style="font-size:10px; padding:2px 6px; background:#ef4444; color:#fff; border:none; cursor:pointer;" onclick="editarEntrega(${e.id})">Realocar</button>
               </div>`
            : '';

        // Botão de Ação Principal
        let acaoBtn = '';
        if (emRota) {
            acaoBtn = `<button class="btn-primary" style="width:100%; padding:8px; margin-top:8px; background:#10b981;" onclick="gerenciarParadas(${e.id})">🗺️ Gerenciar Paradas da Rota</button>`;
        } else if (hasVeiculo && !e.veiculo_apto) {
            const motivoBloq = (e.veiculo_motivos_bloqueio && e.veiculo_motivos_bloqueio.length) ? e.veiculo_motivos_bloqueio[0] : 'Veículo inapto na oficina';
            acaoBtn = `
                <button disabled class="btn-primary" style="width:100%; padding:8px; margin-top:8px; background:#dc2626; cursor:not-allowed; opacity:0.95; font-size:12px; font-weight:700;" title="${motivoBloq}">
                    🛑 Saída Bloqueada: Veículo Inapto
                </button>
            `;
        } else if (percReal > 100) {
            acaoBtn = `
                <button disabled class="btn-primary" style="width:100%; padding:8px; margin-top:8px; background:#ef4444; cursor:not-allowed; opacity:0.9; font-size:12px; font-weight:700;" title="Trava ANTT: Peso excede a capacidade regulamentar do veículo.">
                    🚫 Saída Bloqueada: Sobrecarga ANTT (${percReal}%)
                </button>
            `;
        } else {
            acaoBtn = `<button class="btn-primary" style="width:100%; padding:8px; margin-top:8px;" onclick="iniciarRotaComValidacao(${e.id}, ${hasVeiculo}, ${hasMotorista})">🚀 Iniciar Rota</button>`;
        }

        const thumbImg = e.veiculo_miniatura_url 
            ? `<img src="${e.veiculo_miniatura_url}" class="vehicle-thumb-mini" alt="${e.veiculo_placa || ''}">`
            : `<div class="vehicle-thumb-mini" style="display:flex; align-items:center; justify-content:center; font-size:1.2rem;">🚚</div>`;

        const badgeApto = e.veiculo ? (e.veiculo_apto 
            ? `<span class="doc-badge-status doc-badge-ok" style="font-size:10px;">✓ Apto</span>` 
            : `<span class="doc-badge-status doc-badge-danger" style="font-size:10px;" title="${(e.veiculo_motivos_bloqueio || []).join('; ')}">⚠️ Irregular</span>`) : '';

        const qtdVendas = Array.isArray(e.vendas) ? e.vendas.length : 0;

        container.innerHTML += `
            <div class="kanban-item" style="border-top: 4px solid ${barColor};">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        ${thumbImg}
                        <div>
                            <strong style="font-size:1.05rem; color:var(--color-text);">Carga #${e.id}</strong>
                            <div style="font-size:0.8rem; color:var(--color-text-muted); font-weight:600;">${e.veiculo_placa ? formatPlaca(e.veiculo_placa) : 'Sem Veículo'}</div>
                        </div>
                    </div>
                    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:3px;">
                        <span class="badge ${e.status === 'Em Rota' ? 'em-rota' : 'agendada'}">${e.status}</span>
                        <div style="display:flex; gap:4px; align-items:center;">
                            ${seloPesoEstimado}
                            ${badgeApto}
                        </div>
                    </div>
                </div>

                ${alertaPendente}
                ${alertaVeiculoInapto}

                <div style="font-size:0.85rem; color:var(--color-text-muted); margin-bottom:10px; line-height:1.4;">
                    <div><strong>Rota:</strong> ${e.rota_nome || '<span style="color:#ef4444;">Não definida</span>'}</div>
                    <div><strong>Motorista:</strong> ${e.motorista_nome || '<span style="color:#ef4444;">Não atribuído</span>'}</div>
                </div>
                
                <!-- Barra de Lotação ANTT (D11) -->
                <div style="margin-bottom: 12px; background:var(--color-hover); padding:10px; border-radius:8px; border:1px solid var(--color-border);">
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 5px;">
                        <span style="font-weight:600;">🚚 ${veiculoDesc}</span>
                        <strong style="color:${barColor};">${percReal}% (${statusTexto})</strong>
                    </div>
                    <div style="width: 100%; height: 8px; background: var(--color-border); border-radius: 4px; overflow: hidden;">
                        <div style="width: ${percVisual}%; height: 100%; background: ${barColor}; transition: width 0.3s ease;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size: 0.75rem; color: var(--color-text-muted); margin-top: 5px;">
                        <span>Cap: ${capMax} kg</span>
                        <span>Carregado: <strong>${pesoLoad} kg</strong></span>
                    </div>
                </div>
                
                <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.85rem; margin-bottom:8px;">
                    <span><strong>${qtdVendas}</strong> Parada(s) / Pedido(s)</span>
                    ${!emRota ? `<button class="btn-outline" style="padding:4px 8px; font-size:11px;" onclick="abrirConfigurarCarga(${e.id})">⚙️ Configurar Carga</button>` : ''}
                </div>

                ${(() => {
                    const cvr = e.custo_viagem_resumo;
                    if (!cvr) return '';
                    const alertaAverbacaoHtml = cvr.alerta_averbacao 
                        ? `<div style="background:rgba(239,68,68,0.12); border:1px solid #ef4444; color:#ef4444; border-radius:6px; padding:5px 8px; font-size:11px; font-weight:700; margin-bottom:6px;" title="${cvr.motivo_alerta_averbacao}">
                             ⚠️ ${cvr.motivo_alerta_averbacao}
                           </div>` 
                        : '';

                    const alertaOcupacaoHtml = cvr.alerta_baixa_ocupacao 
                        ? `<div style="background:rgba(245,158,11,0.12); border:1px solid #f59e0b; color:#d97706; border-radius:6px; padding:5px 8px; font-size:11px; font-weight:700; margin-bottom:6px;" title="${cvr.motivo_baixa_ocupacao}">
                             📉 ${cvr.motivo_baixa_ocupacao}
                           </div>` 
                        : '';

                    const fmt = (v) => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
                    
                    if (cvr.snapshot_congelado) {
                        return `
                            ${alertaAverbacaoHtml}
                            ${alertaOcupacaoHtml}
                            <div style="background:var(--color-hover); border:1px solid var(--color-border); border-radius:8px; padding:8px 10px; margin-bottom:10px; font-size:11px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                    <span style="font-weight:700; color:var(--color-text);">📊 Custo Real Fechado:</span>
                                    <span style="font-weight:700; color:#ef4444;">${fmt(cvr.custo_total_real)}</span>
                                </div>
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                    <span style="color:var(--color-text-muted);">Receita Frete:</span>
                                    <span style="font-weight:600; color:var(--color-text);">${fmt(cvr.receita_frete)}</span>
                                </div>
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <span style="font-weight:700; color:var(--color-text);">Margem Real:</span>
                                    <span style="font-weight:700; color:${cvr.margem_bruta >= 0 ? '#10b981' : '#ef4444'};">${fmt(cvr.margem_bruta)} (${cvr.margem_percentual.toFixed(1)}%)</span>
                                </div>
                            </div>
                        `;
                    } else {
                        const tooltipComb = `Preço: R$ ${cvr.combustivel_estimado_preco_litro || 0}/L (${cvr.combustivel_estimado_fonte_preco || 'ANP'} - ${cvr.combustivel_estimado_data_preco || 'recente'}) | Consumo: ${cvr.combustivel_estimado_consumo_usado || 0} km/L`;
                        const avisoSemDados = cvr.dados_incompletos ? `<span class="badge" style="background:rgba(100,116,139,0.15); color:var(--color-text-muted); font-size:10px;" title="${cvr.motivo_dados_incompletos || 'Sem dados suficientes'}">⚠️ Sem dados de odômetro</span>` : '';

                        return `
                            ${alertaAverbacaoHtml}
                            ${alertaOcupacaoHtml}
                            <div style="background:var(--color-hover); border:1px solid var(--color-border); border-radius:8px; padding:8px 10px; margin-bottom:10px; font-size:11px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                    <span style="color:var(--color-text-muted);" title="${tooltipComb}">⛽ Combustível Previsto ℹ️:</span>
                                    <span style="font-weight:600; color:var(--color-text);">${fmt(cvr.combustivel_estimado)}</span>
                                </div>
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                    <span style="color:var(--color-text-muted);">Receita Prevista:</span>
                                    <span style="font-weight:600; color:var(--color-text);">${fmt(cvr.receita_frete)}</span>
                                </div>
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <span style="font-weight:700; color:var(--color-text);">Margem Prevista:</span>
                                    <span style="font-weight:700; color:${cvr.margem_bruta >= 0 ? '#10b981' : '#ef4444'};">${fmt(cvr.margem_bruta)} (${cvr.margem_percentual.toFixed(1)}%)</span>
                                </div>
                                ${avisoSemDados ? `<div style="margin-top:4px; text-align:right;">${avisoSemDados}</div>` : ''}
                            </div>
                        `;
                    }
                })()}

                ${acaoBtn}
                
                <button class="btn-outline" style="width:100%; padding:6px; margin-top:6px; border-color:#6366f1; color:#6366f1; font-weight:600; font-size:12px;" onclick="abrirRomaneioBilateral(${e.id})">
                    ⚖️ Romaneio Bilateral (Cheio x Vazio)
                </button>
                
                <!-- Emissão em 1 Clique dos 3 PDFs ANTT -->
                <div style="margin-top:10px; border-top:1px solid var(--color-border); padding-top:8px;">
                    <div style="font-size:10px; font-weight:700; text-transform:uppercase; color:var(--color-text-muted); margin-bottom:6px;">Documentos ANTT Transporte Perigoso:</div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:4px;">
                        <a href="/logistica/api/entregas/${e.id}/romaneio-antt-pdf/" target="_blank" class="btn-outline" style="padding:4px 2px; font-size:11px; text-decoration:none;" title="Romaneio Bilateral de Carga ANTT (Res. 5.998/2022)">📄 Romaneio</a>
                        <a href="/logistica/api/entregas/${e.id}/ficha-emergencia-pdf/" target="_blank" class="btn-outline" style="padding:4px 2px; font-size:11px; text-decoration:none; color:#ea580c; border-color:#ea580c;" title="Ficha de Emergência NBR 7503 com números ONU">⚠️ Ficha ONU</a>
                        <a href="/logistica/api/entregas/${e.id}/envelope-transporte-pdf/" target="_blank" class="btn-outline" style="padding:4px 2px; font-size:11px; text-decoration:none; color:#0284c7; border-color:#0284c7;" title="Envelope para Transporte de Produtos Perigosos">✉️ Envelope</a>
                    </div>
                </div>
            </div>
        `;
    }

    // Início de Rota com Pré-validação de Veículo e Motorista
    window.iniciarRotaComValidacao = function(entregaId, hasVeiculo, hasMotorista) {
        if (!hasVeiculo || !hasMotorista) {
            Swal.fire({
                title: 'Configuração Incompleta',
                text: 'É obrigatório selecionar um Veículo e um Motorista antes de liberar a saída do caminhão!',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Configurar Agora',
                cancelButtonText: 'Cancelar'
            }).then(result => {
                if (result.isConfirmed) {
                    abrirConfigurarCarga(entregaId);
                }
            });
            return;
        }
        mudarStatusEntrega(entregaId, 'Em Rota');
    };

    window.mudarStatusEntrega = async function(id, novoStatus) {
        try {
            const res = await fetch(`/logistica/api/entregas/${id}/`, {
                method: 'PATCH',
                headers: getAuthHeaders(),
                body: JSON.stringify({ status: novoStatus })
            });
            if (res.ok) {
                Swal.fire({ 
                    title: novoStatus === 'Em Rota' ? 'Caminhão Partiu!' : 'Status Atualizado!', 
                    text: novoStatus === 'Em Rota' ? 'Romaneio sincronizado para o App de Campo do motorista.' : '',
                    icon: 'success', 
                    timer: 1800, 
                    showConfirmButton: false 
                });
                loadKanban();
            } else {
                const errData = await res.json().catch(() => null);
                const errMsg = (errData && (errData.non_field_errors?.[0] || errData.error || errData.detail)) || "Erro ao atualizar status da entrega.";
                Swal.fire('Trava ANTT / Bloqueio', errMsg, 'error');
            }
        } catch (error) { 
            Swal.fire('Erro', error.message, 'error'); 
        }
    };

    // ==============================================================================
    // 2. MODAL DE CONFIGURAÇÃO DIRETA DE CARGA (COLUNA 2)
    // ==============================================================================
    const modalConfigurarCarga = document.getElementById('modal-configurar-carga');
    const formConfigurarCarga = document.getElementById('form-configurar-carga');
    const btnFecharCfg = document.getElementById('btn-fechar-configurar-carga');
    const btnCancelarCfg = document.getElementById('btn-cancelar-configurar-carga');

    function fecharModalConfigurarCarga() {
        if (modalConfigurarCarga) modalConfigurarCarga.classList.remove('active');
    }
    if (btnFecharCfg) btnFecharCfg.onclick = fecharModalConfigurarCarga;
    if (btnCancelarCfg) btnCancelarCfg.onclick = fecharModalConfigurarCarga;

    window.abrirConfigurarCarga = async function(entregaId) {
        document.getElementById('cfg-entrega-id').value = entregaId;
        document.getElementById('cfg-entrega-num').textContent = entregaId;

        // Carrega dados da entrega
        try {
            const [resEntrega, resVeiculos, resRotas] = await Promise.all([
                fetch(`/logistica/api/entregas/${entregaId}/`, { headers: getAuthHeaders() }),
                fetch('/logistica/api/veiculos/?sem_paginacao=1', { headers: getAuthHeaders() }),
                fetch('/logistica/api/rotas/?sem_paginacao=1', { headers: getAuthHeaders() })
            ]);

            const entrega = await resEntrega.json();
            const veiculos = extrairListaDRF(await resVeiculos.json());
            const rotas = extrairListaDRF(await resRotas.json());

            // Preenche select de veículos com indicação de aptidão e bloqueio
            const selV = document.getElementById('cfg-veiculo');
            selV.innerHTML = '<option value="">Selecione o Veículo...</option>';
            veiculos.forEach(v => {
                const isSel = (entrega.veiculo && (entrega.veiculo == v.id || entrega.veiculo.id == v.id)) ? 'selected' : '';
                const isApto = v.apto_operacao !== false;
                const motivo = (!isApto && v.motivos_bloqueio && v.motivos_bloqueio.length) ? ` [INAPTO: ${v.motivos_bloqueio[0]}]` : '';
                const disAttr = !isApto ? 'disabled style="color:var(--color-text-muted);"' : '';
                selV.innerHTML += `<option value="${v.id}" ${isSel} ${disAttr}>${formatPlaca(v.placa)} - ${v.modelo} (${v.capacidade_carga} kg)${motivo}</option>`;
            });

            // Preenche select de rotas
            const selR = document.getElementById('cfg-rota');
            selR.innerHTML = '<option value="">Selecione a Rota...</option>';
            rotas.filter(r => r.ativa !== false).forEach(r => {
                const isSel = (entrega.rota && (entrega.rota == r.id || entrega.rota.id == r.id)) ? 'selected' : '';
                selR.innerHTML += `<option value="${r.id}" ${isSel}>${r.nome} (${r.distancia_km} km)</option>`;
            });

            // Preenche select de motoristas
            const selM = document.getElementById('cfg-motorista');
            if (entrega.motorista) {
                const motId = typeof entrega.motorista === 'object' ? entrega.motorista.id : entrega.motorista;
                selM.value = motId;
            } else {
                selM.value = '';
            }

            modalConfigurarCarga.classList.add('active');
        } catch (err) {
            console.error(err);
            Swal.fire('Erro', 'Não foi possível carregar as opções de carga.', 'error');
        }
    };

    if (formConfigurarCarga) {
        formConfigurarCarga.onsubmit = async (e) => {
            e.preventDefault();
            const entregaId = document.getElementById('cfg-entrega-id').value;
            const veiculo = document.getElementById('cfg-veiculo').value || null;
            const rota = document.getElementById('cfg-rota').value || null;
            const motorista = document.getElementById('cfg-motorista').value || null;

            try {
                const res = await fetch(`/logistica/api/entregas/${entregaId}/`, {
                    method: 'PATCH',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ veiculo, rota, motorista })
                });

                if (res.ok) {
                    Swal.fire('Configurado!', 'Carga atualizada e vinculada com sucesso.', 'success');
                    fecharModalConfigurarCarga();
                    loadKanban();
                } else {
                    const errData = await res.json().catch(() => null);
                    Swal.fire('Erro', errData?.detail || 'Erro ao atualizar carga.', 'error');
                }
            } catch (err) {
                Swal.fire('Erro', err.message, 'error');
            }
        };
    }

    // ==============================================================================
    // 3. MODAL ATRIBUIR PEDIDO A CAMINHÃO (COLUNA 1 -> COLUNA 2)
    // ==============================================================================
    const modalAtribuir = document.getElementById('modal-atribuir-caminhao');
    const formAtribuir = document.getElementById('form-atribuir-caminhao');
    const btnFecharAtr = document.getElementById('btn-fechar-atribuir');
    const btnCancelarAtr = document.getElementById('btn-cancelar-atribuir');

    function fecharModalAtribuir() {
        if (modalAtribuir) modalAtribuir.classList.remove('active');
    }
    if (btnFecharAtr) btnFecharAtr.onclick = fecharModalAtribuir;
    if (btnCancelarAtr) btnCancelarAtr.onclick = fecharModalAtribuir;

    window.abrirModalAtribuir = function(vendaId) {
        document.getElementById('atr-venda-id').value = vendaId;
        
        // Puxar Entregas em montagem (sem paginação para select completo)
        fetch('/logistica/api/entregas/?status=Agendada,Em Produção&sem_paginacao=1', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(raw => {
                const data = extrairListaDRF(raw);
                window.entregasDisponiveis = data;
                const select = document.getElementById('atr-entrega-id');
                select.innerHTML = '<option value="">Selecione uma Carga...</option>';
                data.forEach(e => {
                    select.innerHTML += `<option value="${e.id}">Carga #${e.id} - ${e.rota_nome || 'Sem Rota'} (${e.percentual_lotacao || 0}%)</option>`;
                });
                document.getElementById('atr-entrega-info').style.display = 'none';
            });

        // Puxar Veículos e Rotas
        fetch('/logistica/api/veiculos/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(r => r.json())
            .then(raw => {
                const data = extrairListaDRF(raw);
                const sV = document.getElementById('atr-veiculo'); 
                sV.innerHTML = '<option value="">Selecione...</option>';
                data.filter(v => v.status === 'Ativo').forEach(v => {
                    sV.innerHTML += `<option value="${v.id}">${formatPlaca(v.placa)} - ${v.modelo} (${v.capacidade_carga} kg)</option>`;
                });
            });

        fetch('/logistica/api/rotas/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(r => r.json())
            .then(raw => {
                const data = extrairListaDRF(raw);
                const sR = document.getElementById('atr-rota'); 
                sR.innerHTML = '<option value="">Selecione...</option>';
                data.filter(r => r.ativa !== false).forEach(r => {
                    sR.innerHTML += `<option value="${r.id}">${r.nome}</option>`;
                });
            });

        modalAtribuir.classList.add('active');
    };

    document.getElementById('atr-entrega-id')?.addEventListener('change', (e) => {
        const divInfo = document.getElementById('atr-entrega-info');
        const val = e.target.value;
        if (!val || !window.entregasDisponiveis) {
            divInfo.style.display = 'none';
            return;
        }
        const entrega = window.entregasDisponiveis.find(x => x.id == val);
        if (entrega) {
            divInfo.style.display = 'block';
            divInfo.innerHTML = `
                <div><strong>Rota:</strong> ${entrega.rota_nome || 'Não definida'}</div>
                <div><strong>Veículo:</strong> ${entrega.veiculo_placa ? formatPlaca(entrega.veiculo_placa) : 'Sem veículo'} (Ocupado: ${entrega.percentual_lotacao}%)</div>
                <div><strong>Motorista:</strong> ${entrega.motorista_nome || 'Sem motorista'}</div>
                <div><strong>Pedidos Vinculados:</strong> ${entrega.vendas ? entrega.vendas.length : 0} parada(s)</div>
            `;
        }
    });

    document.getElementById('atr-modo')?.addEventListener('change', (e) => {
        if (e.target.value === 'nova') {
            document.getElementById('div-carga-existente').style.display = 'none';
            document.getElementById('div-nova-carga').style.display = 'grid';
        } else {
            document.getElementById('div-carga-existente').style.display = 'block';
            document.getElementById('div-nova-carga').style.display = 'none';
        }
    });

    if (formAtribuir) {
        formAtribuir.onsubmit = async (e) => {
            e.preventDefault();
            const vendaId = document.getElementById('atr-venda-id').value;
            const modo = document.getElementById('atr-modo').value;
            let entregaId = document.getElementById('atr-entrega-id').value;

            if (modo === 'nova') {
                const v = document.getElementById('atr-veiculo').value || null;
                const r = document.getElementById('atr-rota').value || null;
                const mot = document.getElementById('atr-motorista').value || null;
                const payload = { status: 'Agendada' };
                if (v) payload.veiculo = v;
                if (r) payload.rota = r;
                if (mot) payload.motorista = mot;

                const resE = await fetch('/logistica/api/entregas/', {
                    method: 'POST', 
                    headers: getAuthHeaders(),
                    body: JSON.stringify(payload)
                });
                if (resE.ok) {
                    const dataE = await resE.json();
                    entregaId = dataE.id;
                } else {
                    Swal.fire('Erro', 'Não foi possível criar o romaneio.', 'error');
                    return;
                }
            }

            if (!entregaId) { 
                Swal.fire('Atenção', 'Selecione uma carga ou configure uma nova.', 'warning'); 
                return; 
            }

            // Atribui venda à entrega colocando-a em 'Em Separação' (não Em Rota!)
            const resV = await fetch(`/vendas/api/${vendaId}/`, {
                method: 'PATCH', 
                headers: getAuthHeaders(), 
                body: JSON.stringify({ entrega: entregaId, status: 'Em Separação' })
            });

            if (resV.ok) {
                Swal.fire('Atribuído!', 'Pedido vinculado ao romaneio em montagem.', 'success');
                fecharModalAtribuir();
                loadKanban();
            } else {
                Swal.fire('Erro', 'Erro ao vincular pedido.', 'error');
            }
        };
    }

    // ==============================================================================
    // 4. PARADAS DA ROTA E BAIXA RÁPIDA
    // ==============================================================================
    const modalParadas = document.getElementById('modal-paradas-rota');
    let rotaAtualId = null;

    function fecharModalParadas() {
        if (modalParadas) modalParadas.classList.remove('active');
    }
    document.getElementById('btn-fechar-paradas')?.addEventListener('click', fecharModalParadas);
    document.getElementById('btn-fechar-paradas-btn')?.addEventListener('click', fecharModalParadas);

    window.gerenciarParadas = function(entregaId) {
        rotaAtualId = entregaId;
        fetch(`/logistica/api/entregas/${entregaId}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const lista = document.getElementById('paradas-lista');
                lista.innerHTML = '';
                
                const vendas = Array.isArray(data.vendas) ? data.vendas : [];
                if (vendas.length === 0) {
                    lista.innerHTML = '<div class="empty-state"><h4>Nenhuma parada vinculada</h4><p>Adicione pedidos a esta rota.</p></div>';
                } else {
                    vendas.forEach(v => {
                        let badgeClass = v.status === 'Entregue' ? 'entregue' : (v.status === 'Cancelada' ? 'cancelada' : 'em-rota');
                        lista.innerHTML += `
                            <div style="display:flex; justify-content:space-between; align-items:center; background: var(--color-hover); padding: 14px; border-radius: 10px; margin-bottom: 10px; border: 1px solid var(--color-border); flex-wrap:wrap; gap:10px;">
                                <div>
                                    <div style="display:flex; align-items:center; gap:8px;">
                                        <strong style="font-size: 1rem; color:var(--color-text);">Pedido #${v.id}</strong>
                                        <span class="badge ${badgeClass}">${v.status}</span>
                                    </div>
                                    <div style="font-size: 0.9rem; font-weight:600; color:var(--color-text); margin-top:2px;">${v.cliente_nome}</div>
                                    <div style="font-size: 0.8rem; color: var(--color-text-muted);">${v.cliente_endereco || 'Endereço não informado'}</div>
                                    <div style="font-size: 0.8rem; font-weight:700; color:var(--color-primary); margin-top:2px;">${formatCurrency(v.valor_total)}</div>
                                </div>
                                <div style="display:flex; flex-direction:column; gap:6px;">
                                    <button class="btn-primary" style="padding: 6px 12px; font-size: 12px; background: #10b981;" onclick="mudarStatusVendaModal(${v.id}, 'Entregue')">✓ Baixa (Entregue)</button>
                                    <button class="btn-val-trigger" onclick="abrirValidacaoCarga(${v.id}, 'Em Rota')">⚖️ Validar Carga</button>
                                    <button class="btn-outline" style="padding: 6px 12px; font-size: 12px; border-color: #ef4444; color: #ef4444;" onclick="mudarStatusVendaModal(${v.id}, 'Cancelada')">✕ Recusar</button>
                                </div>
                            </div>
                        `;
                    });
                }
                modalParadas.classList.add('active');
            });
    };

    window.mudarStatusVendaModal = async function(id, novoStatus) {
        try {
            const res = await fetch(`/vendas/api/${id}/alterar_status/`, {
                method: 'POST', 
                headers: getAuthHeaders(), 
                body: JSON.stringify({ status: novoStatus })
            });
            if (res.ok) {
                Swal.fire({ title: 'Status Atualizado!', icon: 'success', timer: 1000, showConfirmButton: false });
                gerenciarParadas(rotaAtualId);
                loadKanban();
            } else {
                throw new Error("Erro ao atualizar status do pedido.");
            }
        } catch (error) { 
            Swal.fire('Erro', error.message, 'error'); 
        }
    };

    document.getElementById('btn-finalizar-rota')?.addEventListener('click', async () => {
        if (!rotaAtualId) return;
        const confirm = await Swal.fire({
            title: 'Concluir Romaneio?',
            text: 'Isso finalizará o trajeto, registrará a conclusão de rota e disparará as notificações.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Sim, Finalizar Rota',
            cancelButtonText: 'Cancelar'
        });

        if (confirm.isConfirmed) {
            try {
                const res = await fetch(`/logistica/api/entregas/${rotaAtualId}/concluir-romaneio/`, {
                    method: 'POST', 
                    headers: getAuthHeaders()
                });
                if (res.ok) {
                    const data = await res.json();
                    let htmlResumo = '<p>O veículo está de volta à base e o histórico financeiro foi consolidado.</p>';
                    if (data.custo_viagem) {
                        const cv = data.custo_viagem;
                        const fmt = v => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
                        htmlResumo += `
                            <div style="background:var(--color-hover); border:1px solid var(--color-border); border-radius:8px; padding:12px; text-align:left; font-size:13px; margin-top:12px;">
                                <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Receita do Frete:</span><strong>${fmt(cv.receita_frete)}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Custo Real da Viagem:</span><strong style="color:#ef4444;">${fmt(cv.custo_total_real)}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Margem Operacional:</span><strong style="color:${cv.margem_bruta >= 0 ? '#10b981' : '#ef4444'};">${fmt(cv.margem_bruta)} (${Number(cv.margem_percentual || 0).toFixed(1)}%)</strong></div>
                                <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--color-text-muted);"><span>Km Percorrido:</span><span>${cv.km_real || cv.km_planejado || 0} km</span></div>
                            </div>
                        `;
                    }
                    Swal.fire({
                        title: 'Rota Finalizada & Custo Consolidado!',
                        html: htmlResumo,
                        icon: 'success'
                    });
                    fecharModalParadas();
                    loadKanban();
                } else {
                    throw new Error("Erro ao concluir romaneio.");
                }
            } catch (err) {
                Swal.fire('Erro', err.message, 'error');
            }
        }
    });

    // ==============================================================================
    // 5. FROTA / VEÍCULOS (CRUD COMPLETO)
    // ==============================================================================
    // ==============================================================================
    // 5. FROTA / VEÍCULOS (SPRINT L1: CADASTRO COMPLETO, FIPE, FOTOS E DOCUMENTOS)
    // ==============================================================================
    let veiculoModalAtualId = null;

    // Sub-abas internas do Modal de Veículo
    const modalVeiculoSubtabBtns = document.querySelectorAll('#modal-veiculo .modal-subtab-btn');
    const modalVeiculoSubtabPanes = document.querySelectorAll('#modal-veiculo .modal-subtab-pane');
    modalVeiculoSubtabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            modalVeiculoSubtabBtns.forEach(b => b.classList.remove('active'));
            modalVeiculoSubtabPanes.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-subtab');
            const pane = document.getElementById(targetId);
            if (pane) pane.classList.add('active');
        });
    });

    function ativarSubtabVeiculo(targetId) {
        modalVeiculoSubtabBtns.forEach(b => {
            if (b.getAttribute('data-subtab') === targetId) b.classList.add('active');
            else b.classList.remove('active');
        });
        modalVeiculoSubtabPanes.forEach(p => {
            if (p.id === targetId) p.classList.add('active');
            else p.classList.remove('active');
        });
    }

    function loadVeiculos() {
        // Carrega alertas de conformidade da frota
        fetch('/logistica/api/veiculos/pendencias-documentos/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const pendencias = data.pendencias || [];
                let totalVencidos = 0;
                let totalVencendo = 0;
                let totalFaltantes = 0;

                pendencias.forEach(p => {
                    totalVencidos += (p.vencidos || []).length;
                    totalVencendo += (p.vencendo || []).length;
                    totalFaltantes += (p.faltantes || []).length;
                });

                const elVencidos = document.getElementById('alert-count-vencidos');
                const elVencendo = document.getElementById('alert-count-vencendo');
                const elFaltantes = document.getElementById('alert-count-faltantes');
                if (elVencidos) elVencidos.textContent = totalVencidos;
                if (elVencendo) elVencendo.textContent = totalVencendo;
                if (elFaltantes) elFaltantes.textContent = totalFaltantes;
            })
            .catch(err => console.error("Erro ao carregar pendências da frota:", err));

        // Carrega tabela de veículos
        fetch('/logistica/api/veiculos/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(raw => {
                const data = extrairListaDRF(raw);
                const elAtivos = document.getElementById('alert-count-ativos');
                if (elAtivos) {
                    const ativos = data.filter(v => (v.status_ativo || v.status) === 'Ativo').length;
                    elAtivos.textContent = `${ativos} / ${data.length}`;
                }

                const tbody = document.getElementById('tbody-veiculos');
                tbody.innerHTML = '';

                if (data.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="10">
                                <div class="empty-state">
                                    <h4>Nenhum veículo cadastrado</h4>
                                    <p>Cadastre os veículos da sua frota para alocação nas entregas e controle documental.</p>
                                    <button class="btn-primary" onclick="abrirModalVeiculo()">+ Cadastrar Primeiro Veículo</button>
                                </div>
                            </td>
                        </tr>
                    `;
                    return;
                }

                data.forEach(v => {
                    const statusStr = v.status_ativo || v.status || 'Ativo';
                    const badgeClass = statusStr === 'Ativo' ? 'ativo' : (statusStr === 'Em Manutenção' ? 'manutencao' : 'inativo');
                    
                    let locColor = 'var(--color-text)';
                    if (v.localizacao_atual === 'Em Rota') locColor = '#2563eb';
                    else if (v.localizacao_atual === 'Oficina') locColor = '#ef4444';
                    
                    const thumbHtml = (v.miniatura_principal_url || v.foto_principal_url)
                        ? `<img src="${v.miniatura_principal_url || v.foto_principal_url}" class="vehicle-thumb-mini" alt="${v.placa}" onerror="this.outerHTML='🚚'">`
                        : `<div class="vehicle-thumb-mini" style="display:flex; align-items:center; justify-content:center; font-size:1.2rem;">🚚</div>`;

                    const situacaoDocHtml = v.apto_operacao 
                        ? `<span class="doc-badge-status doc-badge-ok">✓ Em dia</span>` 
                        : `<span class="doc-badge-status doc-badge-danger" title="${(v.motivos_bloqueio || []).join('; ')}">⚠️ Irregular (${(v.motivos_bloqueio || []).length})</span>`;

                    const valMercado = v.valor_mercado_estimado || v.fipe_valor;
                    const valMercadoStr = valMercado ? formatCurrency(valMercado) : '<span style="color:var(--color-text-muted);">-</span>';

                    tbody.innerHTML += `
                        <tr>
                            <td>${thumbHtml}</td>
                            <td><span class="plate-tag">${formatPlaca(v.placa)}</span></td>
                            <td><strong>${v.modelo}</strong> <span style="color:var(--color-text-muted);">(${v.marca})</span></td>
                            <td>${v.ano_modelo || v.ano || '-'}</td>
                            <td>
                                <strong>${v.capacidade_carga} kg</strong>
                                ${v.pbt_kg ? `<div style="font-size:11px; color:var(--color-text-muted);">PBT: ${v.pbt_kg} kg</div>` : ''}
                            </td>
                            <td>
                                <strong>${valMercadoStr}</strong>
                                ${v.fipe_codigo ? `<div style="font-size:10px; color:var(--color-text-muted);">FIPE: ${v.fipe_codigo}</div>` : ''}
                            </td>
                            <td>${situacaoDocHtml}</td>
                            <td style="color: ${locColor}; font-weight: 600;">${v.localizacao_atual || 'Base'}</td>
                            <td><span class="badge ${badgeClass}">${statusStr}</span></td>
                            <td style="text-align: right; white-space: nowrap;">
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px;" onclick="editarVeiculo(${v.id})">Editar</button>
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px; color:var(--color-primary);" onclick="abrirOSParaVeiculo(${v.id})" title="Abrir Ordem de Serviço">🔧 OS</button>
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px;" onclick="verManutencoes(${v.id})">Histórico</button>
                            </td>
                        </tr>
                    `;
                });
            })
            .catch(err => console.error("Erro ao carregar veículos:", err));
    }

    const modalVeiculo = document.getElementById('modal-veiculo');
    const formVeiculo = document.getElementById('form-veiculo');
    
    function fecharModalVeiculo() {
        if (modalVeiculo) modalVeiculo.classList.remove('active');
        veiculoModalAtualId = null;
    }
    document.getElementById('btn-novo-veiculo')?.addEventListener('click', () => abrirModalVeiculo());
    document.getElementById('btn-fechar-modal-veiculo')?.addEventListener('click', fecharModalVeiculo);
    document.getElementById('btn-cancelar-modal-veiculo')?.addEventListener('click', fecharModalVeiculo);
    document.getElementById('btn-abrir-os-do-veiculo')?.addEventListener('click', () => {
        const vid = veiculoModalAtualId;
        fecharModalVeiculo();
        const maintTabBtn = document.querySelector('.tab-btn[data-target="tab-manutencao"]');
        if (maintTabBtn) maintTabBtn.click();
        abrirModalOS(null, vid);
    });

    function atualizarFipeHero(fipeVal, adicVal, mesRef) {
        const valF = parseFloat(fipeVal) || 0;
        const valA = parseFloat(adicVal) || 0;
        const valEst = valF + valA;

        const elBase = document.getElementById('fipe-val-base');
        const elAdic = document.getElementById('fipe-val-adicionais');
        const elEst = document.getElementById('fipe-val-estimado');
        const elBadge = document.getElementById('fipe-badge-ref');

        if (elBase) elBase.textContent = formatCurrency(valF);
        if (elAdic) elAdic.textContent = formatCurrency(valA);
        if (elEst) elEst.textContent = formatCurrency(valEst);
        if (elBadge) {
            elBadge.textContent = mesRef ? `Ref: ${mesRef}` : 'Sem Cotação';
            elBadge.style.background = mesRef ? 'rgba(16, 185, 129, 0.15)' : 'var(--color-border)';
            elBadge.style.color = mesRef ? '#10b981' : 'var(--color-text)';
        }
    }

    window.abrirModalVeiculo = function(id = null) {
        veiculoModalAtualId = id;
        formVeiculo.reset();
        ativarSubtabVeiculo('subtab-veiculo-dados');
        document.getElementById('veiculo-id').value = id || '';

        const elTit = document.getElementById('modal-veiculo-titulo');
        const elSub = document.getElementById('modal-veiculo-subtitulo');
        const fotosAlerta = document.getElementById('fotos-novo-veiculo-alerta');
        const fotosWrap = document.getElementById('fotos-gerenciador-wrap');
        const docsAlerta = document.getElementById('docs-novo-veiculo-alerta');
        const docsWrap = document.getElementById('docs-gerenciador-wrap');
        const countFotos = document.getElementById('count-fotos-aba');
        const countDocs = document.getElementById('count-docs-aba');

        const btnAbrirOS = document.getElementById('btn-abrir-os-do-veiculo');
        if (btnAbrirOS) btnAbrirOS.style.display = id ? 'inline-block' : 'none';

        if (!id) {
            if (elTit) elTit.textContent = 'Cadastrar Veículo';
            if (elSub) elSub.textContent = 'Cadastro de novo ativo da frota e conformidade';
            if (fotosAlerta) fotosAlerta.style.display = 'block';
            if (fotosWrap) fotosWrap.style.display = 'none';
            if (docsAlerta) docsAlerta.style.display = 'block';
            if (docsWrap) docsWrap.style.display = 'none';
            if (countFotos) countFotos.textContent = '0';
            if (countDocs) countDocs.textContent = '0';
            atualizarFipeHero(0, 0, null);
            modalVeiculo.classList.add('active');
            carregarMarcasFipe('caminhoes');
        } else {
            if (elTit) elTit.textContent = 'Carregando veículo...';
            if (fotosAlerta) fotosAlerta.style.display = 'none';
            if (fotosWrap) fotosWrap.style.display = 'block';
            if (docsAlerta) docsAlerta.style.display = 'none';
            if (docsWrap) docsWrap.style.display = 'block';
            modalVeiculo.classList.add('active');
            editarVeiculo(id);
        }
    };

    window.editarVeiculo = function(id) {
        veiculoModalAtualId = id;
        fetch(`/logistica/api/veiculos/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('veiculo-id').value = data.id;
                document.getElementById('modal-veiculo-titulo').textContent = `Veículo: ${formatPlaca(data.placa)} - ${data.modelo}`;
                document.getElementById('modal-veiculo-subtitulo').textContent = `Marca: ${data.marca} | Ano: ${data.ano_modelo || data.ano}`;

                // Popula Dados Cadastrais
                const f = formVeiculo.elements;
                if (f['placa']) f['placa'].value = data.placa || '';
                if (f['chassi']) f['chassi'].value = data.chassi || '';
                if (f['renavam']) f['renavam'].value = data.renavam || '';
                if (f['cor']) f['cor'].value = data.cor || '';
                if (f['modelo']) f['modelo'].value = data.modelo || '';
                if (f['marca']) f['marca'].value = data.marca || '';
                if (f['ano_fabricacao']) f['ano_fabricacao'].value = data.ano_fabricacao || data.ano || '';
                if (f['ano_modelo']) f['ano_modelo'].value = data.ano_modelo || data.ano || '';
                if (f['capacidade_carga']) f['capacidade_carga'].value = data.capacidade_carga || '';
                if (f['tara_veiculo_kg']) f['tara_veiculo_kg'].value = data.tara_veiculo_kg || '';
                if (f['pbt_kg']) f['pbt_kg'].value = data.pbt_kg || '';
                if (f['tipo_carroceria']) f['tipo_carroceria'].value = data.tipo_carroceria || '';
                if (f['eixos']) f['eixos'].value = data.eixos || '';
                if (f['combustivel_padrao']) f['combustivel_padrao'].value = data.combustivel_padrao || 'Diesel S10';
                if (f['capacidade_tanque_l']) f['capacidade_tanque_l'].value = data.capacidade_tanque_l || '';
                if (f['consumo_referencia_km_l']) f['consumo_referencia_km_l'].value = data.consumo_referencia_km_l || '';
                if (f['odometro_atual_km']) f['odometro_atual_km'].value = data.odometro_atual_km || '';
                if (f['rntrc_antt']) f['rntrc_antt'].value = data.rntrc_antt || '';
                if (f['data_aquisicao']) f['data_aquisicao'].value = data.data_aquisicao || '';
                if (f['valor_aquisicao']) f['valor_aquisicao'].value = data.valor_aquisicao || '';
                if (f['motorista_padrao']) f['motorista_padrao'].value = data.motorista_padrao || '';
                if (f['status_ativo']) f['status_ativo'].value = data.status_ativo || data.status || 'Ativo';
                if (f['localizacao_atual']) f['localizacao_atual'].value = data.localizacao_atual || 'Base';
                if (f['observacoes']) f['observacoes'].value = data.observacoes || '';

                // Popula FIPE
                if (f['fipe_tipo']) f['fipe_tipo'].value = data.fipe_tipo || 'caminhoes';
                if (f['fipe_codigo']) f['fipe_codigo'].value = data.fipe_codigo || '';
                if (f['fipe_mes_referencia']) f['fipe_mes_referencia'].value = data.fipe_mes_referencia || '';
                if (f['fipe_valor']) f['fipe_valor'].value = data.fipe_valor || '';
                if (f['valor_adicionais']) f['valor_adicionais'].value = data.valor_adicionais || '';

                atualizarFipeHero(data.fipe_valor, data.valor_adicionais, data.fipe_mes_referencia);
                carregarMarcasFipe(data.fipe_tipo || 'caminhoes');

                // Carrega Fotos, Documentos, Seguros/Sinistros e TCO
                carregarFotosVeiculo(data.id);
                carregarDocumentosVeiculo(data.id);
                if (typeof carregarSegurosVeiculoAba === 'function') {
                    carregarSegurosVeiculoAba(data);
                }
                if (typeof carregarTCOVeiculoAba === 'function') {
                    carregarTCOVeiculoAba(data.id);
                }
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Não foi possível carregar os dados do veículo.', 'error');
            });
    };

    // Submissão do Formulário de Veículo (PUT / POST)
    if (formVeiculo) {
        formVeiculo.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(formVeiculo);
            const data = Object.fromEntries(formData.entries());
            const vId = data.id;
            delete data.id;

            if (data.placa) data.placa = data.placa.toUpperCase().replace(/[^A-Z0-9]/g, '');
            if (data.chassi) data.chassi = data.chassi.toUpperCase().trim();
            if (!data.chassi) delete data.chassi;
            if (!data.motorista_padrao) data.motorista_padrao = null;
            if (!data.tara_veiculo_kg) data.tara_veiculo_kg = null;
            if (!data.pbt_kg) data.pbt_kg = null;
            if (!data.ano_modelo) data.ano_modelo = null;
            if (!data.capacidade_tanque_l) data.capacidade_tanque_l = null;
            if (!data.consumo_referencia_km_l) data.consumo_referencia_km_l = null;
            if (!data.odometro_atual_km) data.odometro_atual_km = null;
            if (!data.data_aquisicao) data.data_aquisicao = null;
            if (!data.valor_aquisicao) data.valor_aquisicao = null;
            if (!data.fipe_valor) data.fipe_valor = null;
            if (!data.valor_adicionais) data.valor_adicionais = null;
            if (!data.eixos) data.eixos = null;

            // Mantém ano compatível com testes legados
            if (data.ano_fabricacao && !data.ano) data.ano = parseInt(data.ano_fabricacao);

            const url = vId ? `/logistica/api/veiculos/${vId}/` : '/logistica/api/veiculos/';
            const method = vId ? 'PATCH' : 'POST';

            try {
                const res = await fetch(url, {
                    method: method,
                    headers: getAuthHeaders(),
                    body: JSON.stringify(data)
                });

                if (res.ok) {
                    const saved = await res.json();
                    Swal.fire({
                        title: 'Sucesso!',
                        text: 'Veículo salvo com sucesso!',
                        icon: 'success',
                        timer: 1500,
                        showConfirmButton: false
                    });
                    loadVeiculos();
                    
                    if (!vId) {
                        // Ativa modo edição para permitir anexar fotos e documentos
                        editarVeiculo(saved.id);
                    } else {
                        fecharModalVeiculo();
                    }
                } else {
                    const err = await res.json().catch(() => null);
                    let msg = 'Erro ao salvar veículo.';
                    if (err) {
                        const firstKey = Object.keys(err)[0];
                        if (firstKey) msg = `${firstKey}: ${Array.isArray(err[firstKey]) ? err[firstKey][0] : err[firstKey]}`;
                    }
                    Swal.fire('Atenção', msg, 'error');
                }
            } catch (err) {
                Swal.fire('Erro', err.message, 'error');
            }
        };
    }

    // Listener para recalcular dinamicamente FIPE no blur
    document.getElementById('veiculo-fipe-valor')?.addEventListener('input', () => {
        const fVal = document.getElementById('veiculo-fipe-valor').value;
        const aVal = document.getElementById('veiculo-valor-adicionais').value;
        const mesRef = document.getElementById('veiculo-fipe-mes-ref').value;
        atualizarFipeHero(fVal, aVal, mesRef);
    });
    document.getElementById('veiculo-valor-adicionais')?.addEventListener('input', () => {
        const fVal = document.getElementById('veiculo-fipe-valor').value;
        const aVal = document.getElementById('veiculo-valor-adicionais').value;
        const mesRef = document.getElementById('veiculo-fipe-mes-ref').value;
        atualizarFipeHero(fVal, aVal, mesRef);
    });

    // ==============================================================================
    // INTEGRAÇÃO FIPE (CASCATA TIPO -> MARCA -> MODELO -> ANO)
    // ==============================================================================
    function carregarMarcasFipe(tipo) {
        const selMarca = document.getElementById('fipe-marca-select');
        const selModelo = document.getElementById('fipe-modelo-select');
        const selAno = document.getElementById('fipe-ano-select');
        if (!selMarca) return;

        selMarca.innerHTML = '<option value="">Carregando marcas...</option>';
        selModelo.innerHTML = '<option value="">Selecione primeiro a marca...</option>';
        selModelo.disabled = true;
        selAno.innerHTML = '<option value="">Selecione primeiro o modelo...</option>';
        selAno.disabled = true;

        fetch(`/logistica/api/fipe/marcas/?tipo=${tipo}`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(marcas => {
                selMarca.innerHTML = '<option value="">Selecione a marca...</option>';
                if (Array.isArray(marcas)) {
                    marcas.forEach(m => {
                        const cod = m.codigo || m.code;
                        const nome = m.nome || m.name;
                        selMarca.innerHTML += `<option value="${cod}">${nome}</option>`;
                    });
                }
            })
            .catch(err => {
                selMarca.innerHTML = '<option value="">Erro ao carregar marcas</option>';
            });
    }

    document.getElementById('fipe-tipo-select')?.addEventListener('change', (e) => {
        carregarMarcasFipe(e.target.value);
    });

    document.getElementById('fipe-marca-select')?.addEventListener('change', (e) => {
        const marcaCod = e.target.value;
        const tipo = document.getElementById('fipe-tipo-select').value;
        const selModelo = document.getElementById('fipe-modelo-select');
        const selAno = document.getElementById('fipe-ano-select');

        if (!marcaCod) {
            selModelo.innerHTML = '<option value="">Selecione primeiro a marca...</option>';
            selModelo.disabled = true;
            selAno.innerHTML = '<option value="">Selecione primeiro o modelo...</option>';
            selAno.disabled = true;
            return;
        }

        selModelo.disabled = false;
        selModelo.innerHTML = '<option value="">Carregando modelos...</option>';
        selAno.innerHTML = '<option value="">Selecione primeiro o modelo...</option>';
        selAno.disabled = true;

        fetch(`/logistica/api/fipe/modelos/?tipo=${tipo}&marca=${marcaCod}`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(modelos => {
                selModelo.innerHTML = '<option value="">Selecione o modelo...</option>';
                const lista = Array.isArray(modelos) ? modelos : (modelos.modelos || []);
                lista.forEach(mod => {
                    const cod = mod.codigo || mod.code;
                    const nome = mod.nome || mod.name;
                    selModelo.innerHTML += `<option value="${cod}">${nome}</option>`;
                });
            })
            .catch(() => {
                selModelo.innerHTML = '<option value="">Erro ao carregar modelos</option>';
            });
    });

    document.getElementById('fipe-modelo-select')?.addEventListener('change', (e) => {
        const modeloCod = e.target.value;
        const marcaCod = document.getElementById('fipe-marca-select').value;
        const tipo = document.getElementById('fipe-tipo-select').value;
        const selAno = document.getElementById('fipe-ano-select');

        if (!modeloCod) {
            selAno.innerHTML = '<option value="">Selecione primeiro o modelo...</option>';
            selAno.disabled = true;
            return;
        }

        selAno.disabled = false;
        selAno.innerHTML = '<option value="">Carregando anos...</option>';

        fetch(`/logistica/api/fipe/anos/?tipo=${tipo}&marca=${marcaCod}&modelo=${modeloCod}`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(anos => {
                selAno.innerHTML = '<option value="">Selecione o ano / versão...</option>';
                if (Array.isArray(anos)) {
                    anos.forEach(a => {
                        const cod = a.codigo || a.code;
                        const nome = a.nome || a.name;
                        selAno.innerHTML += `<option value="${cod}">${nome}</option>`;
                    });
                }
            })
            .catch(() => {
                selAno.innerHTML = '<option value="">Erro ao carregar anos</option>';
            });
    });

    document.getElementById('fipe-ano-select')?.addEventListener('change', (e) => {
        const anoCod = e.target.value;
        const modeloCod = document.getElementById('fipe-modelo-select').value;
        const marcaCod = document.getElementById('fipe-marca-select').value;
        const tipo = document.getElementById('fipe-tipo-select').value;

        if (!anoCod) return;

        Swal.fire({
            title: 'Consultando FIPE...',
            text: 'Buscando cotação oficial em tempo real.',
            allowOutsideClick: false,
            didOpen: () => Swal.showLoading()
        });

        fetch(`/logistica/api/fipe/valor/?tipo=${tipo}&marca=${marcaCod}&modelo=${modeloCod}&ano=${anoCod}`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(dados => {
                Swal.close();
                if (!dados || dados.erro) {
                    Swal.fire('FIPE Indisponível', dados?.erro || 'Não foi possível obter a cotação.', 'warning');
                    return;
                }

                // Extrai valor numérico
                let valStr = dados.valorFipe || dados.Valor || '';
                let valNum = parseFloat(String(valStr).replace(/[^\d,]/g, '').replace(',', '.')) || 0;
                let mesRef = dados.mesReferencia || dados.MesReferencia || dados.referenceTable || '';
                let codFipe = dados.codeFipe || dados.CodigoFipe || '';

                document.getElementById('veiculo-fipe-valor').value = valNum.toFixed(2);
                document.getElementById('veiculo-fipe-codigo').value = codFipe;
                document.getElementById('veiculo-fipe-mes-ref').value = mesRef;

                // Auto-preenche marca e modelo se vazios
                const selMarca = document.getElementById('fipe-marca-select');
                const selModelo = document.getElementById('fipe-modelo-select');
                const marcaNome = selMarca.options[selMarca.selectedIndex]?.text || '';
                const modeloNome = selModelo.options[selModelo.selectedIndex]?.text || '';

                if (marcaNome && !document.getElementById('veiculo-marca').value) {
                    document.getElementById('veiculo-marca').value = marcaNome;
                }
                if (modeloNome && !document.getElementById('veiculo-modelo').value) {
                    document.getElementById('veiculo-modelo').value = modeloNome;
                }

                const adicVal = document.getElementById('veiculo-valor-adicionais').value;
                atualizarFipeHero(valNum, adicVal, mesRef);

                Swal.fire({
                    title: 'FIPE Vinculada!',
                    text: `Valor Base: ${formatCurrency(valNum)} (${mesRef})`,
                    icon: 'success',
                    timer: 1800,
                    showConfirmButton: false
                });
            })
            .catch(err => {
                Swal.close();
                Swal.fire('Erro', 'Falha na requisição à API FIPE.', 'error');
            });
    });

    // Botão de Atualizar Cotação FIPE Agora
    document.getElementById('btn-atualizar-fipe-agora')?.addEventListener('click', async () => {
        if (!veiculoModalAtualId) {
            Swal.fire('Atenção', 'Salve o veículo antes de solicitar atualização FIPE.', 'warning');
            return;
        }

        Swal.fire({
            title: 'Atualizando Cotação...',
            text: 'Consultando snapshot mais recente da FIPE.',
            allowOutsideClick: false,
            didOpen: () => Swal.showLoading()
        });

        try {
            const res = await fetch(`/logistica/api/veiculos/${veiculoModalAtualId}/atualizar-fipe/`, {
                method: 'POST',
                headers: getAuthHeaders()
            });
            const data = await res.json();
            Swal.close();

            if (res.ok && data.sucesso) {
                document.getElementById('veiculo-fipe-valor').value = (data.fipe_valor || 0).toFixed(2);
                document.getElementById('veiculo-fipe-mes-ref').value = data.fipe_mes_referencia || '';
                const adicVal = document.getElementById('veiculo-valor-adicionais').value;
                atualizarFipeHero(data.fipe_valor, adicVal, data.fipe_mes_referencia);

                Swal.fire({
                    title: 'Cotação Atualizada!',
                    text: `Novo valor: ${formatCurrency(data.fipe_valor)} (${data.fipe_mes_referencia})`,
                    icon: 'success',
                    timer: 1800,
                    showConfirmButton: false
                });
                loadVeiculos();
            } else {
                Swal.fire('Aviso', data.mensagem || 'Não foi possível atualizar a cotação no momento.', 'warning');
            }
        } catch (err) {
            Swal.close();
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // ==============================================================================
    // GERENCIAMENTO DE FOTOS DO VEÍCULO
    // ==============================================================================
    function carregarFotosVeiculo(veiculoId) {
        fetch(`/logistica/api/veiculos/${veiculoId}/fotos/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(fotos => {
                const lista = Array.isArray(fotos) ? fotos : [];
                const grid = document.getElementById('grid-fotos-veiculo');
                const badgeCount = document.getElementById('count-fotos-aba');
                if (badgeCount) badgeCount.textContent = lista.length;
                if (!grid) return;

                grid.innerHTML = '';
                if (lista.length === 0) {
                    grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:24px; color:var(--color-text-muted);">Nenhuma foto cadastrada para este veículo.</div>';
                    return;
                }

                lista.forEach(f => {
                    const isPrincipal = f.principal;
                    const cardClass = isPrincipal ? 'photo-gallery-card is-principal' : 'photo-gallery-card';
                    const principalBadge = isPrincipal ? '<span class="photo-badge-principal">★ Principal</span>' : '';

                    grid.innerHTML += `
                        <div class="${cardClass}">
                            ${principalBadge}
                            <div class="photo-img-wrap">
                                <img src="${f.miniatura_url || f.imagem_url}" alt="${f.tipo}">
                            </div>
                            <div class="photo-body">
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <strong style="font-size:0.85rem; color:var(--color-text);">${f.tipo}</strong>
                                    <span style="font-size:10px; color:var(--color-text-muted);">${formatDate(f.criado_em)}</span>
                                </div>
                                <div style="display:flex; gap:6px; margin-top:6px;">
                                    ${!isPrincipal ? `<button type="button" class="btn-outline" style="flex:1; padding:4px; font-size:11px;" onclick="definirFotoPrincipal(${veiculoId}, ${f.id})">★ Principal</button>` : ''}
                                    <button type="button" class="btn-outline" style="padding:4px 8px; font-size:11px; border-color:#ef4444; color:#ef4444;" onclick="excluirFotoVeiculo(${veiculoId}, ${f.id})">🗑️</button>
                                </div>
                            </div>
                        </div>
                    `;
                });
            })
            .catch(err => console.error("Erro ao carregar fotos:", err));
    }

    // Upload de Fotos
    document.getElementById('btn-enviar-foto')?.addEventListener('click', async () => {
        if (!veiculoModalAtualId) return;

        const inputFiles = document.getElementById('foto-input-arquivo');
        const files = inputFiles.files;
        if (!files || files.length === 0) {
            Swal.fire('Atenção', 'Selecione ao menos um arquivo de imagem.', 'warning');
            return;
        }

        const tipo = document.getElementById('foto-select-tipo').value;
        const principal = document.getElementById('foto-check-principal').checked;

        Swal.fire({
            title: 'Enviando foto(s)...',
            text: 'Gerando miniatura e validando integridade.',
            allowOutsideClick: false,
            didOpen: () => Swal.showLoading()
        });

        let sucessos = 0;
        let erros = [];

        for (let i = 0; i < files.length; i++) {
            const formData = new FormData();
            formData.append('imagem', files[i]);
            formData.append('tipo', tipo);
            formData.append('principal', (i === 0 && principal) ? 'true' : 'false');

            try {
                const res = await fetch(`/logistica/api/veiculos/${veiculoModalAtualId}/fotos/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCookie('csrftoken') || '',
                        'X-Tenant-ID': document.querySelector('meta[name="active-tenant-id"]')?.content || ''
                    },
                    body: formData
                });
                if (res.ok) {
                    sucessos++;
                } else {
                    const err = await res.json().catch(() => null);
                    erros.push(err?.imagem?.[0] || `Erro no arquivo ${files[i].name}`);
                }
            } catch (e) {
                erros.push(`Falha no upload de ${files[i].name}`);
            }
        }

        Swal.close();
        inputFiles.value = '';

        if (sucessos > 0) {
            carregarFotosVeiculo(veiculoModalAtualId);
            loadVeiculos();
        }

        if (erros.length > 0) {
            Swal.fire('Resultado do Upload', `${sucessos} foto(s) enviada(s). Erros: ${erros.join(', ')}`, 'warning');
        } else {
            Swal.fire({ title: 'Upload Concluído!', text: `${sucessos} foto(s) adicionada(s).`, icon: 'success', timer: 1500, showConfirmButton: false });
        }
    });

    window.definirFotoPrincipal = async function(veiculoId, fotoId) {
        try {
            const res = await fetch(`/logistica/api/veiculos/${veiculoId}/fotos/${fotoId}/`, {
                method: 'PATCH',
                headers: getAuthHeaders(),
                body: JSON.stringify({ principal: true })
            });
            if (res.ok) {
                carregarFotosVeiculo(veiculoId);
                loadVeiculos();
            } else {
                Swal.fire('Erro', 'Não foi possível definir como principal.', 'error');
            }
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    };

    window.excluirFotoVeiculo = function(veiculoId, fotoId) {
        Swal.fire({
            title: 'Excluir Foto?',
            text: 'Esta imagem será removida permanentemente do cadastro do veículo.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Sim, Excluir',
            cancelButtonText: 'Cancelar'
        }).then(async result => {
            if (result.isConfirmed) {
                try {
                    const res = await fetch(`/logistica/api/veiculos/${veiculoId}/fotos/${fotoId}/`, {
                        method: 'DELETE',
                        headers: getAuthHeaders()
                    });
                    if (res.ok) {
                        carregarFotosVeiculo(veiculoId);
                        loadVeiculos();
                    } else {
                        Swal.fire('Erro', 'Não foi possível excluir a foto.', 'error');
                    }
                } catch (e) {
                    Swal.fire('Erro', e.message, 'error');
                }
            }
        });
    };

    // ==============================================================================
    // GERENCIAMENTO DE DOCUMENTOS DO VEÍCULO COM SEMÁFORO DE VENCIMENTO
    // ==============================================================================
    function carregarDocumentosVeiculo(veiculoId) {
        fetch(`/logistica/api/veiculos/${veiculoId}/documentos/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(docs => {
                const lista = Array.isArray(docs) ? docs : [];
                const tbody = document.getElementById('tbody-documentos-veiculo');
                const badgeCount = document.getElementById('count-docs-aba');
                if (badgeCount) badgeCount.textContent = lista.length;
                if (!tbody) return;

                tbody.innerHTML = '';
                if (lista.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:18px; color:var(--color-text-muted);">Nenhum documento anexado.</td></tr>';
                    return;
                }

                lista.forEach(d => {
                    let badgeClass = 'doc-badge-ok';
                    let sitTexto = d.situacao || 'Em dia';
                    if (sitTexto === 'Vencido') {
                        badgeClass = 'doc-badge-danger';
                    } else if (sitTexto.includes('Vence em até')) {
                        badgeClass = 'doc-badge-warning';
                    }

                    const arquivoLink = d.arquivo_url 
                        ? `<a href="${d.arquivo_url}" target="_blank" class="btn-outline" style="padding:2px 8px; font-size:11px; text-decoration:none;">📄 Baixar</a>` 
                        : '<span style="color:var(--color-text-muted);">-</span>';

                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${d.tipo}</strong></td>
                            <td>${d.numero || '-'}</td>
                            <td>${d.emissao ? d.emissao : '-'}</td>
                            <td><strong>${d.vencimento ? d.vencimento : '-'}</strong></td>
                            <td><span class="doc-badge-status ${badgeClass}">${sitTexto}</span></td>
                            <td>${arquivoLink}</td>
                            <td style="text-align:right;">
                                <button type="button" class="btn-outline" style="padding:2px 6px; font-size:11px; border-color:#ef4444; color:#ef4444;" onclick="excluirDocumentoVeiculo(${veiculoId}, ${d.id})">🗑️</button>
                            </td>
                        </tr>
                    `;
                });
            })
            .catch(err => console.error("Erro ao carregar documentos:", err));
    }

    // Salvar Novo Documento
    document.getElementById('btn-salvar-documento')?.addEventListener('click', async () => {
        if (!veiculoModalAtualId) return;

        const tipo = document.getElementById('doc-input-tipo').value;
        const numero = document.getElementById('doc-input-numero').value;
        const emissao = document.getElementById('doc-input-emissao').value;
        const vencimento = document.getElementById('doc-input-vencimento').value;
        const obs = document.getElementById('doc-input-obs').value;
        const inputFile = document.getElementById('doc-input-arquivo');

        if (!vencimento) {
            Swal.fire('Atenção', 'A data de vencimento é obrigatória para controle de conformidade.', 'warning');
            return;
        }

        const formData = new FormData();
        formData.append('tipo', tipo);
        formData.append('numero', numero);
        if (emissao) formData.append('emissao', emissao);
        formData.append('vencimento', vencimento);
        if (obs) formData.append('observacoes', obs);
        if (inputFile.files && inputFile.files[0]) {
            formData.append('arquivo', inputFile.files[0]);
        }

        Swal.fire({
            title: 'Gravando documento...',
            allowOutsideClick: false,
            didOpen: () => Swal.showLoading()
        });

        try {
            const res = await fetch(`/logistica/api/veiculos/${veiculoModalAtualId}/documentos/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken') || '',
                    'X-Tenant-ID': document.querySelector('meta[name="active-tenant-id"]')?.content || ''
                },
                body: formData
            });

            Swal.close();
            if (res.ok) {
                Swal.fire({ title: 'Documento Anexado!', icon: 'success', timer: 1500, showConfirmButton: false });
                document.getElementById('doc-input-numero').value = '';
                document.getElementById('doc-input-emissao').value = '';
                document.getElementById('doc-input-vencimento').value = '';
                document.getElementById('doc-input-obs').value = '';
                inputFile.value = '';
                carregarDocumentosVeiculo(veiculoModalAtualId);
                loadVeiculos();
            } else {
                const err = await res.json().catch(() => null);
                Swal.fire('Erro', err?.arquivo?.[0] || err?.vencimento?.[0] || 'Não foi possível salvar o documento.', 'error');
            }
        } catch (e) {
            Swal.close();
            Swal.fire('Erro', e.message, 'error');
        }
    });

    window.excluirDocumentoVeiculo = function(veiculoId, docId) {
        Swal.fire({
            title: 'Excluir Documento?',
            text: 'O registro do documento e seu arquivo serão excluídos.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Sim, Excluir',
            cancelButtonText: 'Cancelar'
        }).then(async result => {
            if (result.isConfirmed) {
                try {
                    const res = await fetch(`/logistica/api/veiculos/${veiculoId}/documentos/${docId}/`, {
                        method: 'DELETE',
                        headers: getAuthHeaders()
                    });
                    if (res.ok) {
                        carregarDocumentosVeiculo(veiculoId);
                        loadVeiculos();
                    } else {
                        Swal.fire('Erro', 'Não foi possível excluir o documento.', 'error');
                    }
                } catch (e) {
                    Swal.fire('Erro', e.message, 'error');
                }
            }
        });
    };

    // Histórico de Manutenções
    const modalHistoricoManut = document.getElementById('modal-historico-manutencoes');
    function fecharModalHistoricoManut() {
        if (modalHistoricoManut) modalHistoricoManut.classList.remove('active');
    }
    document.getElementById('btn-fechar-historico')?.addEventListener('click', fecharModalHistoricoManut);
    document.getElementById('btn-fechar-historico-btn')?.addEventListener('click', fecharModalHistoricoManut);

    window.verManutencoes = function(veiculoId) {
        fetch('/logistica/api/manutencoes/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(raw => {
                const data = extrairListaDRF(raw);
                const timeline = document.getElementById('timeline-manutencoes');
                timeline.innerHTML = '';
                const manutencoes = data.filter(m => m.veiculo === veiculoId);
                
                if (manutencoes.length === 0) {
                    timeline.innerHTML = `
                        <div class="empty-state">
                            <p>Nenhuma manutenção registrada para este veículo.</p>
                        </div>
                    `;
                } else {
                    manutencoes.forEach(m => {
                        timeline.innerHTML += `
                            <div style="border-left: 3px solid var(--color-primary); padding-left: 15px; margin-bottom: 20px;">
                                <div style="font-weight:bold; color:var(--color-primary);">${formatDate(m.data_manutencao)}</div>
                                <div><strong>Status:</strong> ${m.status}</div>
                                <div><strong>Custo:</strong> ${formatCurrency(m.custo)}</div>
                                <div><strong>Descrição:</strong> ${m.descricao}</div>
                            </div>
                        `;
                    });
                }
                modalHistoricoManut.classList.add('active');
            })
            .catch(err => console.error(err));
    };

    // ==============================================================================
    // 6. ROTAS / FRETES (CRUD COMPLETO COM EXCLUSÃO E EDIÇÃO)
    // ==============================================================================
    function loadRotas() {
        fetch('/logistica/api/rotas/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(raw => {
                const data = extrairListaDRF(raw);
                const tbody = document.getElementById('tbody-rotas');
                tbody.innerHTML = '';

                if (data.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="7">
                                <div class="empty-state">
                                    <h4>Nenhuma rota cadastrada</h4>
                                    <p>Cadastre rotas para roteirização e cálculo de frete da expedição.</p>
                                    <button class="btn-primary" onclick="abrirModalRota()">+ Cadastrar Primeira Rota</button>
                                </div>
                            </td>
                        </tr>
                    `;
                    return;
                }

                data.forEach(r => {
                    const badgeClass = r.ativa !== false ? 'ativo' : 'inativo';
                    const statusText = r.ativa !== false ? 'Ativa' : 'Inativa';

                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${r.nome}</strong></td>
                            <td>${r.origem}</td>
                            <td>${r.destino}</td>
                            <td><strong>${r.distancia_km} km</strong></td>
                            <td>${r.tempo_estimado_horas} h</td>
                            <td><span class="badge ${badgeClass}">${statusText}</span></td>
                            <td style="text-align: right; white-space: nowrap;">
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px;" onclick="editarRota(${r.id})">Editar</button>
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px; border-color:#ef4444; color:#ef4444;" onclick="excluirRota(${r.id}, '${r.nome.replace(/'/g, "\\'")}')">Excluir</button>
                            </td>
                        </tr>
                    `;
                });
            })
            .catch(err => console.error("Erro ao carregar rotas:", err));
    }

    const modalRota = document.getElementById('modal-rota');
    const formRota = document.getElementById('form-rota');
    
    function fecharModalRota() {
        if (modalRota) modalRota.classList.remove('active');
    }
    document.getElementById('btn-nova-rota')?.addEventListener('click', () => abrirModalRota());
    document.getElementById('btn-fechar-modal-rota')?.addEventListener('click', fecharModalRota);
    document.getElementById('btn-cancelar-modal-rota')?.addEventListener('click', fecharModalRota);

    window.abrirModalRota = function(id = null) {
        formRota.reset();
        document.getElementById('rota-id').value = '';
        document.getElementById('modal-rota-titulo').textContent = 'Cadastrar Rota';
        modalRota.classList.add('active');
    };

    window.editarRota = function(id) {
        fetch(`/logistica/api/rotas/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('rota-id').value = data.id;
                document.getElementById('modal-rota-titulo').textContent = `Editar Rota: ${data.nome}`;
                formRota.elements['nome'].value = data.nome;
                formRota.elements['origem'].value = data.origem;
                formRota.elements['destino'].value = data.destino;
                formRota.elements['distancia_km'].value = data.distancia_km;
                formRota.elements['tempo_estimado_horas'].value = data.tempo_estimado_horas;
                formRota.elements['observacoes_rota'].value = data.observacoes_rota || '';
                formRota.elements['ativa'].value = data.ativa !== false ? 'true' : 'false';
                modalRota.classList.add('active');
            })
            .catch(err => Swal.fire('Erro', 'Não foi possível carregar a rota.', 'error'));
    };

    window.excluirRota = async function(id, nome) {
        const confirm = await Swal.fire({
            title: 'Excluir Rota?',
            text: `Tem certeza que deseja excluir a rota "${nome}"?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#ef4444',
            confirmButtonText: 'Sim, Excluir',
            cancelButtonText: 'Cancelar'
        });

        if (confirm.isConfirmed) {
            try {
                const res = await fetch(`/logistica/api/rotas/${id}/`, {
                    method: 'DELETE',
                    headers: getAuthHeaders()
                });
                if (res.ok || res.status === 204) {
                    Swal.fire('Excluída!', 'A rota foi removida com sucesso.', 'success');
                    loadRotas();
                } else {
                    Swal.fire('Erro', 'Não foi possível excluir a rota (ela pode estar vinculada a entregas).', 'error');
                }
            } catch (err) {
                Swal.fire('Erro', err.message, 'error');
            }
        }
    };

    if (formRota) {
        formRota.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());
            const rId = data.id;
            delete data.id;

            data.ativa = data.ativa === 'true';

            const url = rId ? `/logistica/api/rotas/${rId}/` : '/logistica/api/rotas/';
            const method = rId ? 'PUT' : 'POST';

            try {
                const res = await fetch(url, {
                    method: method,
                    headers: getAuthHeaders(),
                    body: JSON.stringify(data)
                });

                if (res.ok) {
                    Swal.fire('Sucesso', 'Rota salva com sucesso!', 'success');
                    fecharModalRota();
                    loadRotas();
                } else {
                    const err = await res.json().catch(() => null);
                    Swal.fire('Erro', err?.nome?.[0] || 'Erro ao salvar rota.', 'error');
                }
            } catch (err) {
                Swal.fire('Erro', err.message, 'error');
            }
        };
    }

    // ==============================================================================
    // 7. ABA 4: HISTÓRICO & COMPROVANTES D8 (AUDITORIA FORENSE DE ASSINATURAS)
    // ==============================================================================
    window.loadHistorico = function() {
        fetch('/logistica/api/entregas/?status=Concluída,Cancelada&sem_paginacao=1', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(raw => {
                const data = extrairListaDRF(raw);
                const tbody = document.getElementById('tbody-historico');
                tbody.innerHTML = '';

                if (data.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="8">
                                <div class="empty-state">
                                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                        <polyline points="14 2 14 8 20 8"></polyline>
                                        <line x1="16" y1="13" x2="8" y2="13"></line>
                                        <line x1="16" y1="17" x2="8" y2="17"></line>
                                        <polyline points="10 9 9 9 8 9"></polyline>
                                    </svg>
                                    <h4>Nenhum romaneio no histórico</h4>
                                    <p>Entregas finalizadas ou canceladas aparecerão arquivadas aqui com seus comprovantes.</p>
                                </div>
                            </td>
                        </tr>
                    `;
                    return;
                }

                data.forEach(e => {
                    const badgeClass = e.status === 'Concluída' ? 'concluida' : 'cancelada';
                    const veiculo = e.veiculo_placa ? `<span class="plate-tag">${formatPlaca(e.veiculo_placa)}</span>` : '-';
                    const mot = e.motorista_nome || 'N/A';
                    const rota = e.rota_nome || 'Sem Rota';
                    const paradas = Array.isArray(e.vendas) ? `${e.vendas.length} pedido(s)` : '-';
                    const dataSaida = formatDate(e.data_saida);

                    tbody.innerHTML += `
                        <tr>
                            <td><strong>Romaneio #${e.id}</strong></td>
                            <td>${dataSaida}</td>
                            <td>${veiculo}</td>
                            <td>${rota}</td>
                            <td>${mot}</td>
                            <td>${paradas}</td>
                            <td><span class="badge ${badgeClass}">${e.status}</span></td>
                            <td style="text-align: right; white-space: nowrap;">
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px;" onclick="verComprovantesEntrega(${e.id})">
                                    ✍️ Comprovantes (D8)
                                </button>
                                <a href="/logistica/api/entregas/${e.id}/romaneio-antt-pdf/" target="_blank" class="btn-outline" style="padding:4px 8px; font-size:12px; text-decoration:none; margin-right:4px;">
                                    📄 Romaneio ANTT
                                </a>
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px;" onclick="gerenciarParadas(${e.id})">
                                    👁️ Paradas
                                </button>
                            </td>
                        </tr>
                    `;
                });
            })
            .catch(err => console.error("Erro ao carregar histórico:", err));
    };

    // Modal de Comprovantes & Assinaturas D8
    const modalComprovantes = document.getElementById('modal-comprovantes-entrega');
    function fecharModalComprovantes() {
        if (modalComprovantes) modalComprovantes.classList.remove('active');
    }
    document.getElementById('btn-fechar-comprovantes')?.addEventListener('click', fecharModalComprovantes);
    document.getElementById('btn-fechar-comprovantes-btn')?.addEventListener('click', fecharModalComprovantes);

    window.verComprovantesEntrega = function(entregaId) {
        document.getElementById('comp-modal-entrega-id').textContent = entregaId;
        const container = document.getElementById('lista-comprovantes-d8');
        container.innerHTML = '<div style="text-align:center; padding:20px;">Carregando comprovantes com assinatura digital...</div>';
        modalComprovantes.classList.add('active');

        fetch(`/logistica/api/comprovantes/?entrega=${entregaId}&sem_paginacao=1`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(raw => {
                const comprovantes = extrairListaDRF(raw);
                container.innerHTML = '';

                if (comprovantes.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <p>Nenhum comprovante bilateral com assinatura eletrônica registrado para este romaneio.</p>
                        </div>
                    `;
                    return;
                }

                comprovantes.forEach(c => {
                    const dataCaptura = formatDate(c.timestamp_captura);
                    const docMasc = c.recebedor_documento ? (c.recebedor_documento.slice(0, 3) + '.***.***-' + c.recebedor_documento.slice(-2)) : 'N/D';
                    const gpsInfo = (c.latitude && c.longitude) 
                        ? `<a href="https://maps.google.com/?q=${c.latitude},${c.longitude}" target="_blank" style="color:var(--color-primary); text-decoration:none;">📍 ${parseFloat(c.latitude).toFixed(4)}, ${parseFloat(c.longitude).toFixed(4)}</a>`
                        : '<span style="color:var(--color-text-muted);">GPS não disponível</span>';
                    
                    const assUrl = c.assinatura_url || `/logistica/api/comprovantes/${c.id}/assinatura/`;

                    container.innerHTML += `
                        <div class="comprovante-card">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px;">
                                <div>
                                    <strong style="font-size:1.05rem; color:var(--color-text);">${c.recebedor_nome}</strong>
                                    <div style="font-size:0.8rem; color:var(--color-text-muted);">Documento: <strong>${docMasc}</strong> | Capturado em: ${dataCaptura}</div>
                                </div>
                                <div>
                                    <span class="badge" style="background:rgba(16,185,129,0.1); color:#10b981; border:1px solid rgba(16,185,129,0.3);">
                                        🔒 Assinatura Válida (D8)
                                    </span>
                                </div>
                            </div>

                            <div style="font-size:0.8rem; margin-bottom:8px;">
                                <strong>Geolocalização de Captura:</strong> ${gpsInfo}
                            </div>

                            <!-- Hash SHA-256 Canônico com Botão Copiar -->
                            <div class="hash-container">
                                <div>
                                    <span style="font-weight:700; color:var(--color-text);">HASH SHA-256:</span>
                                    <span id="hash-val-${c.id}">${c.hash_integridade_sha256}</span>
                                </div>
                                <button type="button" class="btn-outline" style="padding:2px 8px; font-size:10px;" onclick="copiarHash('hash-val-${c.id}')">
                                    📋 Copiar
                                </button>
                            </div>

                            <!-- Imagem da Assinatura Digitalizada -->
                            <div style="margin-top:12px;">
                                <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--color-text-muted); margin-bottom:4px;">Assinatura Digitalizada Capturada:</div>
                                <div style="background:#ffffff; padding:10px; border-radius:8px; display:inline-block; border:1px solid var(--color-border);">
                                    <img src="${assUrl}" alt="Assinatura Digital do Recebedor" style="max-height:100px; display:block;" onerror="this.onerror=null; this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'160\\' height=\\'60\\'><text x=\\'10\\' y=\\'35\\' fill=\\'%23999\\' font-size=\\'12\\'>Assinatura indisponível</text></svg>';">
                                </div>
                            </div>
                        </div>
                    `;
                });
            })
            .catch(err => {
                console.error(err);
                container.innerHTML = '<div class="empty-state"><p>Erro ao carregar comprovantes.</p></div>';
            });
    };

    window.copiarHash = function(elementId) {
        const text = document.getElementById(elementId).textContent;
        navigator.clipboard.writeText(text).then(() => {
            Swal.fire({ title: 'Copiado!', text: 'Hash SHA-256 copiado para a área de transferência.', icon: 'success', timer: 1200, showConfirmButton: false });
        });
    };

    // ==============================================================================
    // 8. DETALHES DA VENDA / ROMANEIO A4
    // ==============================================================================
    const modalDetalhes = document.getElementById('modal-detalhes-venda');
    document.getElementById('btn-fechar-detalhes')?.addEventListener('click', () => modalDetalhes.classList.remove('active'));

    window.abrirDetalhes = function(id) {
        fetch(`/vendas/api/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('detalhe-id').textContent = data.id;
                document.getElementById('detalhe-cliente').textContent = data.cliente_nome || 'N/A';
                document.getElementById('detalhe-cnpj').textContent = data.cliente_cnpj || 'N/D';
                document.getElementById('detalhe-status').textContent = data.status;
                document.getElementById('detalhe-data').textContent = formatDate(data.data_venda);
                document.getElementById('detalhe-total').textContent = formatCurrency(data.valor_total);

                const tbody = document.getElementById('detalhe-itens-tbody');
                tbody.innerHTML = '';
                const itens = Array.isArray(data.itens) ? data.itens : [];
                if (itens.length > 0) {
                    itens.forEach(i => {
                        const nomeItem = i.sku_nome || i.produto_nome || 'Gás / Item';
                        tbody.innerHTML += `
                            <tr>
                                <td>${nomeItem}</td>
                                <td style="text-align: center;">${i.quantidade}</td>
                                <td style="text-align: right;">${formatCurrency(i.valor_unitario)}</td>
                                <td style="text-align: right;"><strong>${formatCurrency(i.valor_total)}</strong></td>
                            </tr>
                        `;
                    });
                } else {
                    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;">Nenhum item registrado.</td></tr>';
                }
                modalDetalhes.classList.add('active');
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Não foi possível carregar detalhes da venda.', 'error');
            });
    };

    // ==============================================================================
    // 9. VALIDAÇÃO DE CARGA, ALÇADAS, AUDITORIA & RELATÓRIOS (SPRINT L4)
    // ==============================================================================
    const modalValidacao = document.getElementById('modal-validacao-carga');
    const formValidacao = document.getElementById('form-validacao');
    const valProdutoSelect = document.getElementById('val-produto');
    const valQtdAtualHidden = document.getElementById('val-qtd-atual');
    const valDisplayQtdAtual = document.getElementById('val-display-qtd-atual');
    const valQtdConferidaInput = document.getElementById('val-qtd-conferida-input');
    const valDisplayDiferenca = document.getElementById('val-display-diferenca');
    const valResultBadge = document.getElementById('val-result-badge');
    const valMotivoSelect = document.getElementById('val-motivo-padrao');
    const valJustificativa = document.getElementById('val-justificativa');
    const valCharCount = document.getElementById('val-char-count');
    const valMinCharAviso = document.getElementById('val-min-char-aviso');
    const btnConfirmarVal = document.getElementById('btn-confirmar-validacao');

    const valPreviewNota = document.getElementById('val-preview-nota-texto');
    const valPreviewFinanceiro = document.getElementById('val-preview-financeiro-texto');
    const valPreviewPeso = document.getElementById('val-preview-peso-texto');

    const valAlertaAlcada = document.getElementById('val-alerta-alcada');
    const valAlertaSobrecarga = document.getElementById('val-alerta-sobrecarga');
    const valCheckSobrecarga = document.getElementById('val-check-autorizar-sobrecarga');
    const valJustificativaSobrecarga = document.getElementById('val-justificativa-sobrecarga');
    const valAlertaSinistro = document.getElementById('val-alerta-sinistro');
    const valFotoObrigatoriaTag = document.getElementById('val-foto-obrigatoria-tag');
    const valFotoInput = document.getElementById('val-foto-input');
    const valEvidenciasPreview = document.getElementById('val-evidencias-preview');

    const valPrecoUnitarioHidden = document.getElementById('val-preco-unitario');
    const valPesoUnitarioHidden = document.getElementById('val-peso-unitario');
    const valCapacidadeVeiculoHidden = document.getElementById('val-capacidade-veiculo');
    const valPesoTotalAtualHidden = document.getElementById('val-peso-total-atual');

    // Modais complementares
    const modalValidacoesPendentes = document.getElementById('modal-validacoes-pendentes');
    const modalRelatorioDivergencias = document.getElementById('modal-relatorio-divergencias');
    const badgePendenciasVal = document.getElementById('badge-pendencias-val');

    function fecharModalValidacao() {
        if (modalValidacao) modalValidacao.classList.remove('active');
    }
    document.getElementById('btn-fechar-validacao')?.addEventListener('click', fecharModalValidacao);
    document.getElementById('btn-cancelar-validacao')?.addEventListener('click', fecharModalValidacao);

    document.getElementById('btn-fechar-pendencias-val')?.addEventListener('click', () => {
        if (modalValidacoesPendentes) modalValidacoesPendentes.classList.remove('active');
    });

    document.getElementById('btn-fechar-relatorio-divergencias')?.addEventListener('click', () => {
        if (modalRelatorioDivergencias) modalRelatorioDivergencias.classList.remove('active');
    });

    // Preview de Fotos Anexadas
    if (valFotoInput) {
        valFotoInput.addEventListener('change', (e) => {
            if (!valEvidenciasPreview) return;
            valEvidenciasPreview.innerHTML = '';
            const files = Array.from(e.target.files || []);
            files.forEach((file) => {
                const isImage = file.type.startsWith('image/');
                const thumb = document.createElement('div');
                thumb.className = 'val-thumb-item';
                if (isImage) {
                    const img = document.createElement('img');
                    img.src = URL.createObjectURL(file);
                    thumb.appendChild(img);
                } else {
                    thumb.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:10px;text-align:center;padding:2px;">PDF DOC</div>`;
                }
                valEvidenciasPreview.appendChild(thumb);
            });
        });
    }

    if (valCheckSobrecarga) {
        valCheckSobrecarga.addEventListener('change', (e) => {
            if (valJustificativaSobrecarga) {
                valJustificativaSobrecarga.style.display = e.target.checked ? 'block' : 'none';
                if (e.target.checked) valJustificativaSobrecarga.focus();
            }
        });
    }

    function atualizarCalculoValidacao() {
        const qtdEsperada = parseFloat(valQtdAtualHidden?.value || 0);
        const rawConferida = valQtdConferidaInput?.value;
        const qtdConferida = (rawConferida === '' || rawConferida === undefined) ? qtdEsperada : parseFloat(rawConferida);

        const diferenca = qtdConferida - qtdEsperada;

        if (valDisplayQtdAtual) valDisplayQtdAtual.textContent = qtdEsperada;
        if (valDisplayDiferenca) {
            valDisplayDiferenca.textContent = (diferenca > 0 ? '+' : '') + diferenca;
            valDisplayDiferenca.style.color = diferenca > 0 ? 'var(--color-primary)' : (diferenca < 0 ? '#ef4444' : 'var(--color-text)');
        }

        if (valPreviewNota) {
            valPreviewNota.textContent = `Passará de ${qtdEsperada} para ${qtdConferida} un`;
        }

        // Impacto Financeiro
        const precoUn = parseFloat(valPrecoUnitarioHidden?.value || 0);
        const valorImpacto = diferenca * precoUn;
        if (valPreviewFinanceiro) {
            const prefixo = valorImpacto > 0 ? '+ R$ ' : (valorImpacto < 0 ? '- R$ ' : 'R$ ');
            valPreviewFinanceiro.textContent = prefixo + Math.abs(valorImpacto).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            valPreviewFinanceiro.style.color = valorImpacto > 0 ? 'var(--color-primary)' : (valorImpacto < 0 ? '#ef4444' : 'var(--color-text)');
        }

        // Peso / Lotação ANTT
        const pesoUn = parseFloat(valPesoUnitarioHidden?.value || 1);
        const pesoTotalAtual = parseFloat(valPesoTotalAtualHidden?.value || 0);
        const capVeiculo = parseFloat(valCapacidadeVeiculoHidden?.value || 0);
        const novoPeso = Math.max(0, pesoTotalAtual + (diferenca * pesoUn));
        const lotacaoPerc = capVeiculo > 0 ? ((novoPeso / capVeiculo) * 100).toFixed(1) : '0.0';

        if (valPreviewPeso) {
            valPreviewPeso.textContent = `${novoPeso.toFixed(1)} kg (${lotacaoPerc}%)`;
            valPreviewPeso.style.color = (capVeiculo > 0 && novoPeso > capVeiculo) ? '#ef4444' : 'var(--color-text)';
        }

        // Alerta de Sobrecarga
        if (valAlertaSobrecarga) {
            if (capVeiculo > 0 && novoPeso > capVeiculo && diferenca > 0) {
                valAlertaSobrecarga.style.display = 'block';
            } else {
                valAlertaSobrecarga.style.display = 'none';
            }
        }

        // Alerta de Alçada Excedida (|Δ| > 1 un ou |valor| > R$ 100,00)
        if (valAlertaAlcada) {
            if (Math.abs(diferenca) > 1 || Math.abs(valorImpacto) > 100.0) {
                valAlertaAlcada.style.display = 'block';
            } else {
                valAlertaAlcada.style.display = 'none';
            }
        }

        // Badges Visuais
        if (valResultBadge) {
            if (diferenca < 0) {
                valResultBadge.className = 'val-result-badge badge-reduction';
                valResultBadge.textContent = `📉 Redução (${diferenca})`;
            } else if (diferenca > 0) {
                valResultBadge.className = 'val-result-badge badge-increase';
                valResultBadge.textContent = `📈 Acréscimo (+${diferenca})`;
            } else {
                valResultBadge.className = 'val-result-badge';
                valResultBadge.textContent = 'Sem alteração';
            }
        }
    }

    valProdutoSelect?.addEventListener('change', (e) => {
        const opt = e.target.selectedOptions[0];
        const qtd = opt ? (opt.getAttribute('data-qtd') || '0') : '0';
        const preco = opt ? (opt.getAttribute('data-preco') || '0') : '0';
        const peso = opt ? (opt.getAttribute('data-peso') || '0') : '0';

        if (valQtdAtualHidden) valQtdAtualHidden.value = qtd;
        if (valDisplayQtdAtual) valDisplayQtdAtual.textContent = qtd;
        if (valQtdConferidaInput) valQtdConferidaInput.value = qtd;
        if (valPrecoUnitarioHidden) valPrecoUnitarioHidden.value = preco;
        if (valPesoUnitarioHidden) valPesoUnitarioHidden.value = peso;

        atualizarCalculoValidacao();
    });

    valQtdConferidaInput?.addEventListener('input', atualizarCalculoValidacao);

    document.getElementById('btn-val-minus')?.addEventListener('click', () => {
        let cur = parseFloat(valQtdConferidaInput?.value || 0);
        if (isNaN(cur)) cur = 0;
        if (cur > 0) cur -= 1;
        if (valQtdConferidaInput) valQtdConferidaInput.value = cur;
        atualizarCalculoValidacao();
    });

    document.getElementById('btn-val-plus')?.addEventListener('click', () => {
        let cur = parseFloat(valQtdConferidaInput?.value || 0);
        if (isNaN(cur)) cur = 0;
        cur += 1;
        if (valQtdConferidaInput) valQtdConferidaInput.value = cur;
        atualizarCalculoValidacao();
    });

    valMotivoSelect?.addEventListener('change', (e) => {
        const motivo = e.target.value;
        const exigeFoto = ['Avaria no manuseio', 'Vazamento', 'Roubo/Extravio'].includes(motivo);
        const sugereSinistro = ['Vazamento', 'Roubo/Extravio'].includes(motivo);

        if (valFotoObrigatoriaTag) {
            valFotoObrigatoriaTag.style.display = exigeFoto ? 'inline' : 'none';
        }
        if (valAlertaSinistro) {
            valAlertaSinistro.style.display = sugereSinistro ? 'block' : 'none';
        }
        if (valMinCharAviso) {
            valMinCharAviso.textContent = motivo === 'Outro'
                ? "Mínimo de 15 caracteres obrigatórios para o motivo 'Outro'."
                : "Mínimo de 10 caracteres obrigatórios para fins de auditoria.";
        }
    });

    valJustificativa?.addEventListener('input', (e) => {
        if (valCharCount) valCharCount.textContent = `${e.target.value.length} caracteres`;
    });

    window.abrirValidacaoCarga = function(vendaId, etapa, entregaId) {
        document.getElementById('val-venda-id').value = vendaId;
        document.getElementById('val-entrega-id').value = entregaId || '';
        document.getElementById('val-etapa').value = etapa || 'Separação / Envase';
        document.getElementById('val-valida-anterior-id').value = '';

        // Reset
        if (valQtdConferidaInput) valQtdConferidaInput.value = '0';
        if (valQtdAtualHidden) valQtdAtualHidden.value = '0';
        if (valDisplayQtdAtual) valDisplayQtdAtual.textContent = '0';
        if (valDisplayDiferenca) valDisplayDiferenca.textContent = '0';
        if (valMotivoSelect) valMotivoSelect.value = '';
        if (valJustificativa) valJustificativa.value = '';
        if (valCharCount) valCharCount.textContent = '0 caracteres';
        if (valFotoInput) valFotoInput.value = '';
        if (valEvidenciasPreview) valEvidenciasPreview.innerHTML = '';
        if (valAlertaAlcada) valAlertaAlcada.style.display = 'none';
        if (valAlertaSobrecarga) valAlertaSobrecarga.style.display = 'none';
        if (valAlertaSinistro) valAlertaSinistro.style.display = 'none';
        if (valFotoObrigatoriaTag) valFotoObrigatoriaTag.style.display = 'none';
        if (valCheckSobrecarga) valCheckSobrecarga.checked = false;
        if (valJustificativaSobrecarga) {
            valJustificativaSobrecarga.value = '';
            valJustificativaSobrecarga.style.display = 'none';
        }

        const infoPedido = document.getElementById('val-info-pedido');
        const infoCliente = document.getElementById('val-info-cliente');
        const infoRomaneio = document.getElementById('val-info-romaneio');
        const infoEtapa = document.getElementById('val-info-etapa');

        if (infoPedido) infoPedido.textContent = `#${vendaId}`;
        if (infoCliente) infoCliente.textContent = 'Consultando pedido...';
        if (infoRomaneio) infoRomaneio.textContent = entregaId ? `#${entregaId}` : 'N/A';
        if (infoEtapa) infoEtapa.textContent = etapa || 'Separação / Envase';

        if (valProdutoSelect) {
            valProdutoSelect.innerHTML = '<option value="">Carregando itens da nota...</option>';
        }

        modalValidacao.classList.add('active');

        // Carrega dados da venda
        fetch(`/vendas/api/${vendaId}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                if (infoPedido) infoPedido.textContent = `#${data.numero_pedido || data.id}`;
                if (infoCliente) infoCliente.textContent = data.cliente_nome || 'Cliente não identificado';

                const entId = entregaId || data.entrega;
                if (entId) {
                    document.getElementById('val-entrega-id').value = entId;
                    if (infoRomaneio) infoRomaneio.textContent = `#${entId}`;
                    fetch(`/logistica/api/entregas/${entId}/`, { headers: getAuthHeaders() })
                        .then(r => r.json())
                        .then(ent => {
                            if (valCapacidadeVeiculoHidden) valCapacidadeVeiculoHidden.value = ent.capacidade_carga_kg || 0;
                            if (valPesoTotalAtualHidden) valPesoTotalAtualHidden.value = ent.peso_total_carregado || 0;
                            atualizarCalculoValidacao();
                        })
                        .catch(() => {});
                }

                if (valProdutoSelect) {
                    valProdutoSelect.innerHTML = '<option value="">Selecione o produto na nota...</option>';
                    const itens = Array.isArray(data.itens) ? data.itens : [];
                    if (itens.length === 0) {
                        valProdutoSelect.innerHTML = '<option value="">Nenhum item encontrado nesta venda</option>';
                    } else {
                        itens.forEach((i) => {
                            const prodId = i.produto || i.sku;
                            const prodNome = i.sku_nome || i.produto_nome || `Item #${i.id}`;
                            const qtd = i.quantidade || 0;
                            const preco = i.preco_unitario_congelado || i.valor_unitario || 0;
                            const peso = i.peso_unitario || 1;
                            valProdutoSelect.innerHTML += `<option value="${prodId}" data-qtd="${qtd}" data-preco="${preco}" data-peso="${peso}">${prodNome} (Qtd: ${qtd} un - R$ ${parseFloat(preco).toFixed(2)})</option>`;
                        });

                        // Auto-seleciona primeiro item
                        if (itens.length >= 1) {
                            valProdutoSelect.selectedIndex = 1;
                            const firstOpt = valProdutoSelect.options[1];
                            const firstQtd = firstOpt.getAttribute('data-qtd') || '0';
                            const firstPreco = firstOpt.getAttribute('data-preco') || '0';
                            const firstPeso = firstOpt.getAttribute('data-peso') || '1';

                            if (valQtdAtualHidden) valQtdAtualHidden.value = firstQtd;
                            if (valDisplayQtdAtual) valDisplayQtdAtual.textContent = firstQtd;
                            if (valQtdConferidaInput) valQtdConferidaInput.value = firstQtd;
                            if (valPrecoUnitarioHidden) valPrecoUnitarioHidden.value = firstPreco;
                            if (valPesoUnitarioHidden) valPesoUnitarioHidden.value = firstPeso;

                            atualizarCalculoValidacao();
                        }
                    }
                }
            })
            .catch(err => {
                console.error('Erro ao carregar detalhes da venda para validação:', err);
                if (infoCliente) infoCliente.textContent = 'Erro ao carregar cliente';
                if (valProdutoSelect) valProdutoSelect.innerHTML = '<option value="">Erro ao buscar produtos</option>';
            });
    };

    if (formValidacao) {
        formValidacao.onsubmit = async (e) => {
            e.preventDefault();
            const vendaId = document.getElementById('val-venda-id').value;
            const entregaId = document.getElementById('val-entrega-id').value;
            const produtoId = valProdutoSelect?.value;
            const etapa = document.getElementById('val-etapa').value;
            const validaAnteriorId = document.getElementById('val-valida-anterior-id').value;

            const qtdEsperada = parseFloat(valQtdAtualHidden?.value || 0);
            const qtdConferida = parseFloat(valQtdConferidaInput?.value);
            const motivo = valMotivoSelect?.value;
            const categoriaRadio = document.querySelector('input[name="val-categoria-item"]:checked');
            const categoria = categoriaRadio ? categoriaRadio.value : 'Cheio';
            const justificativa = valJustificativa?.value.trim();

            if (!produtoId) {
                Swal.fire('Atenção', 'Selecione um produto da lista para validar.', 'warning');
                return;
            }

            if (isNaN(qtdConferida) || qtdConferida < 0) {
                Swal.fire('Quantidade Inválida', 'A quantidade conferida não pode ser negativa ou vazia.', 'warning');
                valQtdConferidaInput?.focus();
                return;
            }

            if (!motivo) {
                Swal.fire('Motivo Obrigatório', 'Selecione o motivo padronizado da ocorrência.', 'warning');
                valMotivoSelect?.focus();
                return;
            }

            const exigeFoto = ['Avaria no manuseio', 'Vazamento', 'Roubo/Extravio'].includes(motivo);
            const temFoto = valFotoInput && valFotoInput.files && valFotoInput.files.length > 0;
            if (exigeFoto && !temFoto) {
                Swal.fire('Foto Obrigatória', `O motivo '${motivo}' exige obrigatoriamente o envio de foto comprobatória da ocorrência.`, 'warning');
                valFotoInput?.focus();
                return;
            }

            const minChars = motivo === 'Outro' ? 15 : 10;
            if (!justificativa || justificativa.length < minChars) {
                Swal.fire('Justificativa Insuficiente', `Por favor, forneça uma justificativa detalhada com no mínimo ${minChars} caracteres.`, 'warning');
                valJustificativa?.focus();
                return;
            }

            const autorizarSobrecarga = valCheckSobrecarga?.checked || false;
            const justificativaSobrecarga = valJustificativaSobrecarga?.value.trim() || '';

            if (valAlertaSobrecarga && valAlertaSobrecarga.style.display !== 'none' && !autorizarSobrecarga) {
                Swal.fire('Sobrecarga Bloqueada', 'O novo peso projetado excede a capacidade ANTT. Liberação permitida apenas a supervisores com autorização técnica.', 'error');
                return;
            }

            if (autorizarSobrecarga && justificativaSobrecarga.length < 10) {
                Swal.fire('Justificativa Técnica de Sobrecarga', 'Informe a justificativa técnica para liberação de sobrecarga (mínimo 10 caracteres).', 'warning');
                valJustificativaSobrecarga?.focus();
                return;
            }

            try {
                if (btnConfirmarVal) {
                    btnConfirmarVal.disabled = true;
                    btnConfirmarVal.innerHTML = 'Processando...';
                }

                const formData = new FormData();
                formData.append('venda', vendaId);
                formData.append('produto', produtoId);
                formData.append('quantidade_conferida', qtdConferida);
                formData.append('quantidade_esperada', qtdEsperada);
                formData.append('motivo', motivo);
                formData.append('categoria_item', categoria);
                formData.append('justificativa', justificativa);
                formData.append('etapa_logistica', etapa);
                if (entregaId) formData.append('entrega', entregaId);
                if (validaAnteriorId) formData.append('valida_anterior', validaAnteriorId);
                if (autorizarSobrecarga) {
                    formData.append('autorizar_sobrecarga', 'true');
                    formData.append('justificativa_sobrecarga', justificativaSobrecarga);
                }

                if (valFotoInput && valFotoInput.files) {
                    for (let i = 0; i < valFotoInput.files.length; i++) {
                        formData.append('evidencias', valFotoInput.files[i]);
                    }
                }

                const res = await fetch('/logistica/api/validacoes/', {
                    method: 'POST',
                    headers: getAuthHeadersMultipart(),
                    body: formData
                });

                if (res.ok) {
                    const data = await res.json();
                    if (data.status === 'Pendente de Aprovação') {
                        Swal.fire({
                            title: 'Validação Registrada!',
                            text: 'Divergência acima da alçada. Ficará pendente de aprovação gerencial antes de produzir efeitos em estoque e notas.',
                            icon: 'warning',
                            confirmButtonColor: '#f59e0b'
                        });
                    } else {
                        Swal.fire({
                            title: 'Validação Concluída!',
                            text: 'Divergência validada e pedido/estoque/peso recalculados com sucesso.',
                            icon: 'success',
                            confirmButtonColor: 'var(--color-primary)'
                        });
                    }
                    fecharModalValidacao();
                    loadKanban();
                    window.atualizarBadgePendenciasValidacao();
                } else {
                    const errData = await res.json().catch(() => ({}));
                    const msg = errData.detail || errData.error || (typeof errData === 'object' ? JSON.stringify(errData) : 'Não foi possível registrar a validação.');
                    Swal.fire('Erro ao Validar Carga', msg, 'error');
                }
            } catch (err) {
                Swal.fire('Erro de Conexão', err.message, 'error');
            } finally {
                if (btnConfirmarVal) {
                    btnConfirmarVal.disabled = false;
                    btnConfirmarVal.innerHTML = '<span>⚖️</span> Confirmar Validação';
                }
            }
        };
    }

    // ==============================================================================
    // 9.1 GESTÃO DE VALIDAÇÕES PENDENTES DE APROVAÇÃO
    // ==============================================================================
    window.atualizarBadgePendenciasValidacao = async function() {
        if (!badgePendenciasVal) return;
        try {
            const res = await fetch('/logistica/api/validacoes/pendentes-aprovacao/', { headers: getAuthHeaders() });
            if (res.ok) {
                const pendentes = await res.json();
                const total = Array.isArray(pendentes) ? pendentes.length : 0;
                if (total > 0) {
                    badgePendenciasVal.textContent = total;
                    badgePendenciasVal.style.display = 'inline-block';
                } else {
                    badgePendenciasVal.style.display = 'none';
                }
            }
        } catch (e) {
            console.error('Erro ao verificar pendências de validação:', e);
        }
    };

    window.abrirModalValidacoesPendentes = async function() {
        if (!modalValidacoesPendentes) return;
        modalValidacoesPendentes.classList.add('active');
        const container = document.getElementById('lista-validacoes-pendentes');
        if (!container) return;
        container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--color-text-muted);">Consultando pendências de validação...</div>';

        try {
            const res = await fetch('/logistica/api/validacoes/pendentes-aprovacao/', { headers: getAuthHeaders() });
            if (!res.ok) throw new Error('Não foi possível carregar as pendências.');
            const lista = await res.json();

            if (!Array.isArray(lista) || lista.length === 0) {
                container.innerHTML = `
                    <div style="text-align:center;padding:40px;color:var(--color-text-muted);">
                        <div style="font-size:2rem;margin-bottom:8px;">✅</div>
                        <h4 style="margin:0 0 4px 0;font-weight:700;">Nenhuma validação pendente</h4>
                        <p style="margin:0;font-size:0.85rem;">Todas as validações de carga estão aprovadas ou dentro da alçada automática.</p>
                    </div>
                `;
                return;
            }

            let html = '';
            lista.forEach(val => {
                const impactoFmt = parseFloat(val.valor_impacto || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
                const diferencaFmt = (val.diferenca > 0 ? '+' : '') + val.diferenca;
                const evidenciasHtml = (val.evidencias && val.evidencias.length > 0)
                    ? val.evidencias.map(ev => `<a href="/logistica/api/validacoes/evidencias/${ev.id}/download/" target="_blank" style="font-size:0.75rem;display:inline-flex;align-items:center;gap:3px;background:var(--color-bg);padding:3px 6px;border-radius:4px;border:1px solid var(--color-border);text-decoration:none;">📸 Anexo #${ev.id}</a>`).join(' ')
                    : '<span style="font-size:0.75rem;color:var(--color-text-muted);">Sem foto</span>';

                html += `
                    <div class="val-card-pendente">
                        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
                            <div>
                                <span class="val-status-badge val-status-pendente">Pendente de Aprovação</span>
                                <h4 style="margin:6px 0 2px 0;font-size:1.05rem;">Pedido #${val.venda} - ${val.cliente_nome || 'Cliente'}</h4>
                                <div style="font-size:0.82rem;color:var(--color-text-muted);">
                                    Produto: <strong>${val.produto_nome}</strong> (${val.categoria_item}) | Motivo: <strong>${val.motivo}</strong>
                                </div>
                            </div>
                            <div style="text-align:right;">
                                <div style="font-size:1.15rem;font-weight:700;color:${val.diferenca < 0 ? '#ef4444' : 'var(--color-primary)'};">Δ ${diferencaFmt} un</div>
                                <div style="font-size:0.82rem;font-weight:600;color:var(--color-text-muted);">Impacto: ${impactoFmt}</div>
                            </div>
                        </div>

                        <div style="margin-top:10px;padding:8px 12px;background:var(--color-bg);border-radius:6px;font-size:0.83rem;">
                            <strong>Justificativa do operador:</strong> "${val.justificativa || 'Sem justificativa informada'}"
                            <div style="margin-top:4px;font-size:0.75rem;color:var(--color-text-muted);">
                                Registrado por: <strong>${val.criado_por_nome || 'N/A'}</strong> | IP/Dispositivo: ${val.dispositivo_ip || 'N/A'} | Data: ${new Date(val.data_hora).toLocaleString('pt-BR')}
                            </div>
                        </div>

                        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;flex-wrap:wrap;gap:8px;">
                            <div>${evidenciasHtml}</div>
                            <div style="display:flex;gap:8px;">
                                <button type="button" class="btn-secondary" style="color:#ef4444;border-color:#ef4444;padding:6px 14px;font-size:0.82rem;" onclick="rejeitarValidacaoCargaAction(${val.id})">
                                    ❌ Rejeitar
                                </button>
                                <button type="button" class="btn-primary" style="background:#10b981;border-color:#10b981;padding:6px 14px;font-size:0.82rem;" onclick="aprovarValidacaoCargaAction(${val.id})">
                                    ✅ Aprovar Ajuste
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = `<div style="text-align:center;padding:24px;color:#ef4444;">Erro ao carregar pendências: ${e.message}</div>`;
        }
    };

    document.getElementById('btn-abrir-pendencias-val')?.addEventListener('click', window.abrirModalValidacoesPendentes);

    window.aprovarValidacaoCargaAction = async function(valId) {
        const { value: obs } = await Swal.fire({
            title: 'Aprovar Validação de Carga?',
            text: 'O ajuste de estoque, peso e pedido de venda será efetivado imediatamente na base de dados.',
            input: 'textarea',
            inputPlaceholder: 'Observação da aprovação (opcional)...',
            showCancelButton: true,
            confirmButtonText: 'Confirmar Aprovação',
            cancelButtonText: 'Cancelar',
            confirmButtonColor: '#10b981'
        });

        if (obs !== undefined) {
            try {
                const res = await fetch(`/logistica/api/validacoes/${valId}/aprovar/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ observacao: obs })
                });

                if (res.ok) {
                    Swal.fire('Aprovado!', 'A validação foi aprovada e seus efeitos aplicados.', 'success');
                    window.abrirModalValidacoesPendentes();
                    window.atualizarBadgePendenciasValidacao();
                    loadKanban();
                } else {
                    const err = await res.json().catch(() => ({}));
                    Swal.fire('Erro na Aprovação', err.detail || err.error || 'Não foi possível aprovar a validação.', 'error');
                }
            } catch (e) {
                Swal.fire('Erro de Conexão', e.message, 'error');
            }
        }
    };

    window.rejeitarValidacaoCargaAction = async function(valId) {
        const { value: obs } = await Swal.fire({
            title: 'Rejeitar Validação de Carga?',
            text: 'O registro será marcado como rejeitado e nenhum efeito de estoque ou valor será produzido.',
            input: 'textarea',
            inputPlaceholder: 'Motivo da rejeição (obrigatório)...',
            showCancelButton: true,
            confirmButtonText: 'Confirmar Rejeição',
            cancelButtonText: 'Cancelar',
            confirmButtonColor: '#ef4444',
            inputValidator: (v) => !v && 'Informe o motivo da rejeição.'
        });

        if (obs) {
            try {
                const res = await fetch(`/logistica/api/validacoes/${valId}/rejeitar/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ observacao: obs })
                });

                if (res.ok) {
                    Swal.fire('Rejeitado!', 'A validação foi rejeitada.', 'info');
                    window.abrirModalValidacoesPendentes();
                    window.atualizarBadgePendenciasValidacao();
                    loadKanban();
                } else {
                    const err = await res.json().catch(() => ({}));
                    Swal.fire('Erro na Rejeição', err.detail || err.error || 'Não foi possível rejeitar a validação.', 'error');
                }
            } catch (e) {
                Swal.fire('Erro de Conexão', e.message, 'error');
            }
        }
    };

    // ==============================================================================
    // 9.2 RELATÓRIO DE DIVERGÊNCIAS & PERDAS DE CARGA
    // ==============================================================================
    window.carregarRelatorioDivergencias = async function(inicio, fim) {
        if (!modalRelatorioDivergencias) return;
        modalRelatorioDivergencias.classList.add('active');

        let url = '/logistica/api/validacoes/relatorio-divergencias/';
        const params = [];
        if (inicio) params.push(`inicio=${inicio}`);
        if (fim) params.push(`fim=${fim}`);
        if (params.length > 0) url += `?${params.join('&')}`;

        const kpisContainer = document.getElementById('rel-div-kpis');
        const alertasContainer = document.getElementById('rel-div-alertas-recorrencia');
        const tabMotivos = document.getElementById('rel-div-tabela-motivos');
        const tabProdutos = document.getElementById('rel-div-tabela-produtos');
        const tabSeparadores = document.getElementById('rel-div-tabela-separadores');
        const tabMotoristas = document.getElementById('rel-div-tabela-motoristas');

        if (kpisContainer) kpisContainer.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding: 12px; color:var(--color-text-muted);">Carregando métricas...</div>';

        try {
            const res = await fetch(url, { headers: getAuthHeaders() });
            if (!res.ok) throw new Error('Não foi possível carregar relatório.');
            const data = await res.json();

            // Render KPIs
            if (kpisContainer) {
                kpisContainer.innerHTML = `
                    <div class="rel-kpi-card">
                        <div class="rel-kpi-lbl">Total Ocorrências</div>
                        <div class="rel-kpi-num">${data.total_validacoes || 0}</div>
                    </div>
                    <div class="rel-kpi-card">
                        <div class="rel-kpi-lbl">Aprovadas</div>
                        <div class="rel-kpi-num" style="color:#10b981;">${data.total_aprovadas || 0}</div>
                    </div>
                    <div class="rel-kpi-card">
                        <div class="rel-kpi-lbl">Pendentes Alçada</div>
                        <div class="rel-kpi-num" style="color:#f59e0b;">${data.total_pendentes || 0}</div>
                    </div>
                    <div class="rel-kpi-card">
                        <div class="rel-kpi-lbl">Rejeitadas</div>
                        <div class="rel-kpi-num" style="color:#ef4444;">${data.total_rejeitadas || 0}</div>
                    </div>
                    <div class="rel-kpi-card">
                        <div class="rel-kpi-lbl">Perdas Reais (R$)</div>
                        <div class="rel-kpi-num" style="color:#ef4444;">${parseFloat(data.perdas_financeiras_reais || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</div>
                    </div>
                `;
            }

            // Alertas de Recorrência
            if (alertasContainer) {
                if (data.alertas_recorrencia && data.alertas_recorrencia.length > 0) {
                    alertasContainer.style.display = 'block';
                    alertasContainer.innerHTML = `
                        <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:8px;padding:12px;">
                            <h4 style="margin:0 0 8px 0;color:#dc2626;font-size:0.95rem;display:flex;align-items:center;gap:6px;">
                                <span>🚨</span> Alertas de Recorrência de Divergência (Últimos 15 dias)
                            </h4>
                            ${data.alertas_recorrencia.map(a => `
                                <div style="font-size:0.83rem;margin-bottom:4px;color:var(--color-text);">
                                    • <strong style="color:#dc2626;">[${a.nivel_alerta}]</strong> ${a.mensagem} (Perda estimada acumulada: ${parseFloat(a.perda_acumulada).toLocaleString('pt-BR', {style:'currency', currency:'BRL'})})
                                </div>
                            `).join('')}
                        </div>
                    `;
                } else {
                    alertasContainer.style.display = 'none';
                }
            }

            // Tabela Motivos
            if (tabMotivos) {
                if (data.motivos_frequentes && data.motivos_frequentes.length > 0) {
                    tabMotivos.innerHTML = `
                        <table style="width:100%;font-size:0.82rem;border-collapse:collapse;">
                            <thead><tr style="border-bottom:1px solid var(--color-border);text-align:left;color:var(--color-text-muted);"><th style="padding:6px;">Motivo</th><th>Qtd</th><th>%</th><th>Valor R$</th></tr></thead>
                            <tbody>
                                ${data.motivos_frequentes.map(m => `
                                    <tr style="border-bottom:1px solid var(--color-hover);">
                                        <td style="padding:6px;font-weight:600;">${m.motivo}</td>
                                        <td>${m.contagem}</td>
                                        <td>${m.percentual}%</td>
                                        <td>${parseFloat(m.valor_impacto).toLocaleString('pt-BR', {style:'currency', currency:'BRL'})}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    `;
                } else {
                    tabMotivos.innerHTML = '<div style="color:var(--color-text-muted);font-size:0.85rem;padding:8px;">Sem dados de motivos no período.</div>';
                }
            }

            // Tabela Produtos
            if (tabProdutos) {
                if (data.por_produto && data.por_produto.length > 0) {
                    tabProdutos.innerHTML = `
                        <table style="width:100%;font-size:0.82rem;border-collapse:collapse;">
                            <thead><tr style="border-bottom:1px solid var(--color-border);text-align:left;color:var(--color-text-muted);"><th style="padding:6px;">Produto</th><th>Ocorrências</th><th>Δ Unid</th><th>Impacto R$</th></tr></thead>
                            <tbody>
                                ${data.por_produto.map(p => `
                                    <tr style="border-bottom:1px solid var(--color-hover);">
                                        <td style="padding:6px;font-weight:600;">${p.produto}</td>
                                        <td>${p.total_ocorrencias} (${p.taxa_percentual}%)</td>
                                        <td>${p.quantidade_divergente} un</td>
                                        <td>${parseFloat(p.valor_impacto).toLocaleString('pt-BR', {style:'currency', currency:'BRL'})}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    `;
                } else {
                    tabProdutos.innerHTML = '<div style="color:var(--color-text-muted);font-size:0.85rem;padding:8px;">Sem divergências por produto.</div>';
                }
            }

            // Tabela Separadores
            if (tabSeparadores) {
                if (data.por_separador && data.por_separador.length > 0) {
                    tabSeparadores.innerHTML = `
                        <table style="width:100%;font-size:0.82rem;border-collapse:collapse;">
                            <thead><tr style="border-bottom:1px solid var(--color-border);text-align:left;color:var(--color-text-muted);"><th style="padding:6px;">Separador / Operador</th><th>Ocorrências</th><th>Taxa %</th><th>Impacto R$</th></tr></thead>
                            <tbody>
                                ${data.por_separador.map(s => `
                                    <tr style="border-bottom:1px solid var(--color-hover);">
                                        <td style="padding:6px;font-weight:600;">${s.separador}</td>
                                        <td>${s.total_ocorrencias}</td>
                                        <td>${s.taxa_percentual}%</td>
                                        <td>${parseFloat(s.valor_impacto).toLocaleString('pt-BR', {style:'currency', currency:'BRL'})}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    `;
                } else {
                    tabSeparadores.innerHTML = '<div style="color:var(--color-text-muted);font-size:0.85rem;padding:8px;">Sem dados de separadores.</div>';
                }
            }

            // Tabela Motoristas
            if (tabMotoristas) {
                if (data.por_motorista && data.por_motorista.length > 0) {
                    tabMotoristas.innerHTML = `
                        <table style="width:100%;font-size:0.82rem;border-collapse:collapse;">
                            <thead><tr style="border-bottom:1px solid var(--color-border);text-align:left;color:var(--color-text-muted);"><th style="padding:6px;">Motorista</th><th>Ocorrências</th><th>Taxa %</th><th>Impacto R$</th></tr></thead>
                            <tbody>
                                ${data.por_motorista.map(m => `
                                    <tr style="border-bottom:1px solid var(--color-hover);">
                                        <td style="padding:6px;font-weight:600;">${m.motorista}</td>
                                        <td>${m.total_ocorrencias}</td>
                                        <td>${m.taxa_percentual}%</td>
                                        <td>${parseFloat(m.valor_impacto).toLocaleString('pt-BR', {style:'currency', currency:'BRL'})}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    `;
                } else {
                    tabMotoristas.innerHTML = '<div style="color:var(--color-text-muted);font-size:0.85rem;padding:8px;">Sem dados de motoristas.</div>';
                }
            }
        } catch (e) {
            if (kpisContainer) kpisContainer.innerHTML = `<div style="grid-column: 1/-1; color:#ef4444; padding:12px;">Erro ao carregar dados: ${e.message}</div>`;
        }
    };

    document.getElementById('btn-abrir-relatorio-divergencias')?.addEventListener('click', () => {
        const ini = document.getElementById('rel-div-data-inicio')?.value || '';
        const fim = document.getElementById('rel-div-data-fim')?.value || '';
        window.carregarRelatorioDivergencias(ini, fim);
    });

    document.getElementById('btn-filtrar-relatorio-divergencias')?.addEventListener('click', () => {
        const ini = document.getElementById('rel-div-data-inicio')?.value || '';
        const fim = document.getElementById('rel-div-data-fim')?.value || '';
        window.carregarRelatorioDivergencias(ini, fim);
    });

    // Inicializa contador de pendências na carga inicial
    setTimeout(window.atualizarBadgePendenciasValidacao, 1500);

    // ==============================================================================
    // 10. ROMANEIO BILATERAL (FULL-FOR-EMPTY)
    // ==============================================================================
    let entregaRomaneioAtualId = null;
    const modalRomaneio = document.getElementById('modal-romaneio-bilateral');
    const btnFecharRomaneio = document.getElementById('btn-fechar-romaneio');

    if (btnFecharRomaneio) {
        btnFecharRomaneio.addEventListener('click', () => {
            modalRomaneio.classList.remove('active');
            loadKanban();
        });
    }

    window.baixarDocANTT = function(tipo) {
        if (entregaRomaneioAtualId) {
            window.open(`/logistica/api/entregas/${entregaRomaneioAtualId}/${tipo}/`, '_blank');
        }
    };

    window.abrirRomaneioBilateral = async function(entregaId) {
        entregaRomaneioAtualId = entregaId;
        modalRomaneio.classList.add('active');
        document.getElementById('romaneio-entrega-id').textContent = entregaId;
        await carregarDadosRomaneio(entregaId);
    };

    async function carregarDadosRomaneio(entregaId) {
        try {
            const res = await fetch(`/logistica/api/entregas/${entregaId}/romaneio-bilateral/`, {
                headers: getAuthHeaders()
            });
            if (!res.ok) throw new Error("Erro ao carregar romaneio bilateral.");
            const data = await res.json();

            // Atualiza Veículo e Barra de Capacidade (D11: <80% Verde, 80-99% Âmbar, >=100% Vermelho)
            const perc = parseFloat(data.percentual_lotacao) || 0;
            let barColor = '#10b981';
            let statusBadge = '<span style="color:#10b981;">(Normal <80%)</span>';
            if (perc >= 100) {
                barColor = '#ef4444';
                statusBadge = '<span style="color:#ef4444; font-weight:700;">(SOBRECARGA ANTT >100%)</span>';
            } else if (perc >= 80) {
                barColor = '#f59e0b';
                statusBadge = '<span style="color:#f59e0b; font-weight:600;">(Alerta 80-99%)</span>';
            }

            document.getElementById('romaneio-veiculo-info').textContent = data.veiculo;
            document.getElementById('romaneio-peso-carregado').textContent = data.peso_total_carregado;
            document.getElementById('romaneio-capacidade-max').textContent = data.capacidade_carga_kg;
            document.getElementById('romaneio-perc-texto').innerHTML = `${perc}% Ocupação ${statusBadge}`;

            const barra = document.getElementById('romaneio-barra-peso');
            barra.style.width = Math.min(perc, 100) + '%';
            barra.style.background = barColor;

            // Preenche Select de Clientes para Entrega
            const selectCliente = document.getElementById('select-cliente-entrega');
            selectCliente.innerHTML = '<option value="">Selecione o Cliente de Destino</option>';
            if (data.clientes_comodato && data.clientes_comodato.length) {
                data.clientes_comodato.forEach(c => {
                    selectCliente.innerHTML += `<option value="${c.id}">${c.nome} (${c.cnpj})</option>`;
                });
            }

            // Tabela 1: Cheios Entregues
            const tbodyEntregues = document.getElementById('tbody-romaneio-entregues');
            if (!data.cilindros_entregues || data.cilindros_entregues.length === 0) {
                tbodyEntregues.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:10px; color:var(--color-text-muted);">Nenhum cheio entregue ainda.</td></tr>';
            } else {
                tbodyEntregues.innerHTML = data.cilindros_entregues.map(c => `
                    <tr style="border-bottom:1px solid var(--color-border);">
                        <td style="padding:6px;"><strong>${c.numero_serie}</strong><br><small class="font-mono" style="color:var(--color-text-muted);">${c.codigo_qr}</small></td>
                        <td style="padding:6px;"><span class="badge" style="background:rgba(16,185,129,0.15); color:#10b981; font-size:10px;">${c.gas}</span></td>
                        <td style="padding:6px;">${c.cliente}</td>
                    </tr>
                `).join('');
            }

            // Tabela 2: Vazios Recolhidos
            const tbodyRecolhidos = document.getElementById('tbody-romaneio-recolhidos');
            if (!data.cilindros_recolhidos || data.cilindros_recolhidos.length === 0) {
                tbodyRecolhidos.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:10px; color:var(--color-text-muted);">Nenhum vazio recolhido ainda.</td></tr>';
            } else {
                tbodyRecolhidos.innerHTML = data.cilindros_recolhidos.map(c => `
                    <tr style="border-bottom:1px solid var(--color-border);">
                        <td style="padding:6px;"><strong>${c.numero_serie}</strong><br><small class="font-mono" style="color:var(--color-text-muted);">${c.codigo_qr}</small></td>
                        <td style="padding:6px;"><span class="badge" style="background:rgba(245,158,11,0.15); color:#f59e0b; font-size:10px;">${c.gas}</span></td>
                        <td style="padding:6px;">${c.tara} kg</td>
                    </tr>
                `).join('');
            }

            // Saldo de Comodato
            const divComodato = document.getElementById('romaneio-clientes-comodato');
            if (!data.clientes_comodato || data.clientes_comodato.length === 0) {
                divComodato.innerHTML = '<span style="color:var(--color-text-muted);">Nenhum cliente associado a esta carga.</span>';
            } else {
                divComodato.innerHTML = data.clientes_comodato.map(c => `
                    <div style="background:var(--color-hover); border:1px solid var(--color-border); border-radius:6px; padding:6px 10px;">
                        <strong>${c.nome}</strong>: <span style="color:var(--color-primary); font-weight:700;">${c.saldo_comodato} cilindros</span> em posse
                    </div>
                `).join('');
            }

        } catch (err) {
            console.error(err);
            Swal.fire('Erro', err.message, 'error');
        }
    }

    // Submissão: Entregar Cheio
    document.getElementById('form-entregar-cheio')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const qr = document.getElementById('input-qr-entrega').value.trim();
        const clienteId = document.getElementById('select-cliente-entrega').value;

        try {
            const res = await fetch(`/logistica/api/entregas/${entregaRomaneioAtualId}/romaneio-bilateral/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    acao: 'entregar',
                    codigo_qr: qr,
                    cliente_id: clienteId
                })
            });
            const resp = await res.json();
            if (!res.ok) throw new Error(resp.error || 'Erro ao registrar entrega de cilindro.');

            Swal.fire('Entregue!', resp.mensagem, 'success');
            document.getElementById('input-qr-entrega').value = '';
            await carregarDadosRomaneio(entregaRomaneioAtualId);
        } catch (err) {
            Swal.fire('Bloqueio Operacional', err.message, 'warning');
        }
    });

    // Submissão: Recolher Vazio
    document.getElementById('form-recolher-vazio')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const qr = document.getElementById('input-qr-recolha').value.trim();
        const obs = document.getElementById('input-obs-recolha').value.trim();

        try {
            const res = await fetch(`/logistica/api/entregas/${entregaRomaneioAtualId}/romaneio-bilateral/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    acao: 'recolher',
                    codigo_qr: qr,
                    observacao: obs
                })
            });
            const resp = await res.json();
            if (!res.ok) throw new Error(resp.error || 'Erro ao registrar recolha de cilindro.');

            Swal.fire('Recolhido!', resp.mensagem, 'success');
            document.getElementById('input-qr-recolha').value = '';
            document.getElementById('input-obs-recolha').value = '';
            await carregarDadosRomaneio(entregaRomaneioAtualId);
        } catch (err) {
            Swal.fire('Atenção', err.message, 'warning');
        }
    });

    // ==============================================================================
    // SPRINT L2: GESTÃO DE COMBUSTÍVEL E ABASTECIMENTOS
    // ==============================================================================
    let cacheVeiculosCombustivel = [];
    let cachePrecosANP = [];
    let lastEditedFuelField = 'litros';

    // Utilitário de formatação de números
    function formatLitros(val) {
        if (val === null || val === undefined || isNaN(val)) return '0,000 L';
        return Number(val).toLocaleString('pt-BR', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' L';
    }

    function formatPrecoLitro(val) {
        if (val === null || val === undefined || isNaN(val)) return 'R$ 0,0000';
        return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 4, maximumFractionDigits: 4 });
    }

    // Carregamento Principal da Aba de Combustível
    async function loadCombustivel() {
        const periodo = document.getElementById('filtro-combustivel-periodo')?.value || 'este_mes';
        let inicio = '';
        let fim = '';

        const hoje = new Date();
        const ano = hoje.getFullYear();
        const mes = hoje.getMonth();

        if (periodo === 'este_mes') {
            const primeiroDia = new Date(ano, mes, 1);
            inicio = primeiroDia.toISOString().split('T')[0];
            fim = hoje.toISOString().split('T')[0];
        } else if (periodo === 'mes_anterior') {
            const primeiroDiaAnt = new Date(ano, mes - 1, 1);
            const ultimoDiaAnt = new Date(ano, mes, 0);
            inicio = primeiroDiaAnt.toISOString().split('T')[0];
            fim = ultimoDiaAnt.toISOString().split('T')[0];
        } else if (periodo === 'ultimos_3_meses') {
            const d = new Date();
            d.setDate(d.getDate() - 90);
            inicio = d.toISOString().split('T')[0];
            fim = hoje.toISOString().split('T')[0];
        } else if (periodo === 'personalizado') {
            inicio = document.getElementById('filtro-combustivel-inicio')?.value || '';
            fim = document.getElementById('filtro-combustivel-fim')?.value || '';
        }

        const veiculoId = document.getElementById('filtro-combustivel-veiculo')?.value || '';
        const tipoComb = document.getElementById('filtro-combustivel-tipo')?.value || '';
        const statusVal = document.getElementById('filtro-combustivel-status')?.value || '';

        // 1. Carregar Veículos no Select de Filtro e Modal se ainda não carregados
        if (cacheVeiculosCombustivel.length === 0) {
            await carregarSelectsCombustivel();
        }

        // 2. Carregar Resumo de KPIs e Análises
        const resumoParams = new URLSearchParams();
        if (inicio) resumoParams.append('inicio', inicio);
        if (fim) resumoParams.append('fim', fim);
        if (veiculoId) resumoParams.append('veiculo', veiculoId);

        try {
            const resResumo = await fetch(`/logistica/api/combustivel/resumo/?${resumoParams.toString()}`, {
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (resResumo.ok) {
                const dataResumo = await resResumo.json();
                renderizarKPIsCombustivel(dataResumo);
                renderizarRankingEficiencia(dataResumo.ranking_veiculos || []);
                renderizarComparativoANP(dataResumo.por_combustivel || []);
            }
        } catch (e) {
            console.error('Erro ao carregar resumo de combustível:', e);
        }

        // 3. Atualizar Status das Referências ANP
        try {
            const resANP = await fetch('/logistica/api/combustivel/precos-referencia/vigente/', {
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (resANP.ok) {
                const dataANP = await resANP.json();
                cachePrecosANP = extrairListaDRF(dataANP);
                atualizarBadgesANP(cachePrecosANP);
            }
        } catch (e) {
            console.error('Erro ao verificar referências ANP:', e);
        }

        // 4. Carregar Tabela de Abastecimentos
        const tableParams = new URLSearchParams();
        if (inicio) tableParams.append('data_hora__date__gte', inicio);
        if (fim) tableParams.append('data_hora__date__lte', fim);
        if (veiculoId) tableParams.append('veiculo', veiculoId);
        if (tipoComb) tableParams.append('tipo_combustivel', tipoComb);
        if (statusVal) tableParams.append('status_validacao', statusVal);
        tableParams.append('sem_paginacao', '1');

        const tbody = document.getElementById('tbody-abastecimentos');
        if (tbody) tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding:18px;">Carregando registros de abastecimento...</td></tr>';

        try {
            const resAbast = await fetch(`/logistica/api/abastecimentos/?${tableParams.toString()}`, {
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (resAbast.ok) {
                const dataAbast = await resAbast.json();
                const lista = extrairListaDRF(dataAbast);
                renderizarTabelaAbastecimentos(lista);
            } else {
                if (tbody) tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; color:var(--color-danger); padding:16px;">Erro ao carregar abastecimentos.</td></tr>';
            }
        } catch (e) {
            console.error('Erro ao buscar abastecimentos:', e);
            if (tbody) tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; color:var(--color-danger); padding:16px;">Erro de conexão ao carregar abastecimentos.</td></tr>';
        }
    }

    // Renderizar KPIs do Topo
    function renderizarKPIsCombustivel(resumo) {
        const elGasto = document.getElementById('kpi-combustivel-total-gasto');
        const elArlaGasto = document.getElementById('kpi-combustivel-arla-gasto');
        const elLitros = document.getElementById('kpi-combustivel-total-litros');
        const elArlaLitros = document.getElementById('kpi-combustivel-arla-litros');
        const elPrecoMedio = document.getElementById('kpi-combustivel-preco-medio');
        const elBenchmarkANP = document.getElementById('kpi-combustivel-benchmark-anp');
        const elKmL = document.getElementById('kpi-combustivel-km-l');
        const elKmTotal = document.getElementById('kpi-combustivel-km-total');
        const elCustoKm = document.getElementById('kpi-combustivel-custo-km');
        const elAnomalias = document.getElementById('kpi-combustivel-anomalias');
        const elRevisarInfo = document.getElementById('kpi-combustivel-revisar-info');

        if (elGasto) elGasto.textContent = formatCurrency(resumo.total_gasto || 0);
        if (elArlaGasto) elArlaGasto.textContent = `Arla 32: ${formatCurrency(resumo.total_arla_gasto || 0)}`;

        if (elLitros) elLitros.textContent = formatLitros(resumo.total_litros || 0);
        if (elArlaLitros) elArlaLitros.textContent = `Arla 32: ${formatLitros(resumo.total_arla_litros || 0)}`;

        if (elPrecoMedio) elPrecoMedio.textContent = formatPrecoLitro(resumo.preco_medio_litro || 0);

        if (elKmL) {
            elKmL.textContent = resumo.km_l_medio ? `${resumo.km_l_medio} km/l` : '-- km/l';
        }
        if (elKmTotal) {
            elKmTotal.textContent = `${(resumo.km_total || 0).toLocaleString('pt-BR')} km apurados`;
        }

        if (elCustoKm) {
            elCustoKm.textContent = resumo.custo_por_km ? `R$ ${Number(resumo.custo_por_km).toFixed(2)} / km` : 'R$ -- / km';
        }

        const totalAnomalias = (resumo.anomalias_count || 0) + (resumo.revisar_count || 0);
        if (elAnomalias) elAnomalias.textContent = totalAnomalias;
        if (elRevisarInfo) {
            if (resumo.revisar_count > 0) {
                elRevisarInfo.innerHTML = `<span style="color:var(--color-danger); font-weight:700;">🚨 ${resumo.revisar_count} requer(em) revisão urgente</span>`;
            } else if (resumo.anomalias_count > 0) {
                elRevisarInfo.innerHTML = `<span style="color:var(--color-warning); font-weight:700;">⚠️ ${resumo.anomalias_count} com alerta</span>`;
            } else {
                elRevisarInfo.innerHTML = `<span style="color:var(--color-success); font-weight:700;">✅ Nenhuma anomalia</span>`;
            }
        }
    }

    // Renderizar Ranking de Eficiência por Veículo
    function renderizarRankingEficiencia(ranking) {
        const container = document.getElementById('container-ranking-veiculos');
        if (!container) return;

        if (!ranking || ranking.length === 0) {
            container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--color-text-muted);">Nenhum dado de abastecimento com tanque cheio para calcular km/l neste período.</div>';
            return;
        }

        let html = '';
        ranking.forEach(item => {
            const kmLReal = item.km_l_real ? `${item.km_l_real} km/l` : 'Calculando...';
            const kmLRef = item.km_l_referencia ? `${item.km_l_referencia} km/l` : 'Sem ref.';
            const semaforoClass = `bar-${item.semaforo || 'cinza'}`;

            let pctMeta = 50;
            if (item.km_l_real && item.km_l_referencia && item.km_l_referencia > 0) {
                pctMeta = Math.min(100, Math.max(10, Math.round((item.km_l_real / item.km_l_referencia) * 80)));
            }

            let semaforoBadge = '';
            if (item.semaforo === 'verde') semaforoBadge = '🟢 Na meta';
            else if (item.semaforo === 'ambar') semaforoBadge = '🟡 Atenção';
            else if (item.semaforo === 'vermelho') semaforoBadge = '🔴 Anômalo';
            else semaforoBadge = '⚪ Base';

            html += `
                <div class="vehicle-rank-item">
                    <div class="vehicle-rank-header">
                        <div>
                            <span class="vehicle-rank-placa">${formatPlaca(item.placa)}</span>
                            <span style="color:var(--color-text-muted); font-size:0.82rem; margin-left:6px;">${item.modelo}</span>
                        </div>
                        <div class="vehicle-rank-vals">
                            <strong>${kmLReal}</strong> (Meta: ${kmLRef})
                            <span style="font-size:0.75rem; margin-left:6px;">${semaforoBadge}</span>
                        </div>
                    </div>
                    <div class="vehicle-rank-bar-bg">
                        <div class="vehicle-rank-bar-fill ${semaforoClass}" style="width: ${pctMeta}%;"></div>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    }

    // Renderizar Benchmark de Preços Próprios vs ANP
    function renderizarComparativoANP(porCombustivel) {
        const container = document.getElementById('container-comparativo-anp');
        if (!container) return;

        if (!porCombustivel || porCombustivel.length === 0) {
            container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--color-text-muted);">Sem dados de consumo no período.</div>';
            return;
        }

        let html = '<table style="width:100%; font-size:0.86rem; border-collapse:collapse;">';
        html += `
            <thead>
                <tr style="border-bottom:1px solid var(--color-border); text-align:left; color:var(--color-text-muted); font-size:0.75rem; text-transform:uppercase;">
                    <th style="padding:8px 4px;">Combustível</th>
                    <th style="padding:8px 4px; text-align:right;">Preço Próprio</th>
                    <th style="padding:8px 4px; text-align:right;">Média ANP</th>
                    <th style="padding:8px 4px; text-align:right;">Variação</th>
                </tr>
            </thead>
            <tbody>
        `;

        porCombustivel.forEach(c => {
            const precoProprio = formatPrecoLitro(c.preco_medio_proprio);
            const precoANP = c.preco_medio_anp ? formatPrecoLitro(c.preco_medio_anp) : 'Não cadastrada';
            let variacaoHtml = '<span style="color:var(--color-text-muted);">--</span>';

            if (c.variacao_pct !== null && c.variacao_pct !== undefined) {
                if (c.variacao_pct > 0) {
                    variacaoHtml = `<span style="color:var(--color-danger); font-weight:700;">+${c.variacao_pct}% (Acima)</span>`;
                } else if (c.variacao_pct < 0) {
                    variacaoHtml = `<span style="color:var(--color-success); font-weight:700;">${c.variacao_pct}% (Abaixo)</span>`;
                } else {
                    variacaoHtml = `<span style="color:var(--color-text); font-weight:700;">0% (Paridade)</span>`;
                }
            }

            html += `
                <tr style="border-bottom:1px solid var(--color-border);">
                    <td style="padding:8px 4px; font-weight:600;">${c.tipo}</td>
                    <td style="padding:8px 4px; text-align:right; font-family:var(--font-family-mono, monospace);">${precoProprio}</td>
                    <td style="padding:8px 4px; text-align:right; font-family:var(--font-family-mono, monospace);">${precoANP}</td>
                    <td style="padding:8px 4px; text-align:right;">${variacaoHtml}</td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.innerHTML = html;
    }

    // Renderizar Tabela de Abastecimentos
    function renderizarTabelaAbastecimentos(lista) {
        const tbody = document.getElementById('tbody-abastecimentos');
        if (!tbody) return;

        if (!lista || lista.length === 0) {
            tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding:30px; color:var(--color-text-muted);">Nenhum abastecimento encontrado para o filtro aplicado.</td></tr>';
            return;
        }

        let html = '';
        lista.forEach(a => {
            const dataFmt = a.data_hora ? new Date(a.data_hora).toLocaleString('pt-BR') : '--';
            const placa = a.veiculo_placa ? formatPlaca(a.veiculo_placa) : 'N/D';
            const modelo = a.veiculo_modelo || '';
            const motorista = a.motorista_nome || 'Frota';
            const odometroFmt = Number(a.odometro_km || 0).toLocaleString('pt-BR') + ' km';
            const tanqueIcon = a.tanque_cheio ? ' 🟢' : '';
            const litrosFmt = formatLitros(a.litros);
            const vLitroFmt = formatPrecoLitro(a.valor_litro);
            const totalFmt = formatCurrency(a.valor_total);
            const kmLFmt = a.consumo_calculado_km_l ? `${a.consumo_calculado_km_l} km/l` : (a.tipo_combustivel === 'Arla 32' ? 'Arla' : '--');

            // Badges de Status e Alertas
            let statusBadge = '<span class="badge-status-normal">Normal</span>';
            let alertTooltip = '';
            if (a.alertas && Array.isArray(a.alertas) && a.alertas.length > 0) {
                alertTooltip = a.alertas.join(' | ');
            }

            if (a.status_validacao === 'REVISAR') {
                statusBadge = `<span class="badge-status-revisar" title="${alertTooltip}">🚨 Revisar</span>`;
            } else if (a.status_validacao === 'ALERTA') {
                statusBadge = `<span class="badge-status-alerta" title="${alertTooltip}">⚠️ Alerta</span>`;
            }

            // Comprovante
            let compHtml = '<span style="color:var(--color-text-muted);">—</span>';
            if (a.comprovante) {
                compHtml = `<button type="button" class="btn-outline" style="padding:4px 8px; font-size:0.75rem;" onclick="abrirModalComprovante(${a.id}, '${a.comprovante}')" title="Visualizar comprovante fiscal">📄 Ver Cupom</button>`;
            }

            html += `
                <tr>
                    <td style="white-space:nowrap; font-size:0.85rem;">${dataFmt}</td>
                    <td>
                        <strong style="font-family:var(--font-family-mono, monospace);">${placa}</strong>
                        <div style="font-size:0.78rem; color:var(--color-text-muted);">${modelo}</div>
                    </td>
                    <td style="font-size:0.85rem;">${motorista}</td>
                    <td style="font-family:var(--font-family-mono, monospace); font-size:0.85rem;">${odometroFmt}${tanqueIcon}</td>
                    <td><span class="badge" style="font-size:0.75rem;">${a.tipo_combustivel}</span></td>
                    <td style="text-align:right; font-family:var(--font-family-mono, monospace); font-size:0.85rem;">${litrosFmt}</td>
                    <td style="text-align:right; font-family:var(--font-family-mono, monospace); font-size:0.85rem;">${vLitroFmt}</td>
                    <td style="text-align:right; font-weight:700; font-family:var(--font-family-mono, monospace); font-size:0.88rem;">${totalFmt}</td>
                    <td style="text-align:center; font-weight:600; font-family:var(--font-family-mono, monospace); font-size:0.85rem;">${kmLFmt}</td>
                    <td style="text-align:center;">${statusBadge}</td>
                    <td style="text-align:center;">${compHtml}</td>
                    <td style="text-align:right; white-space:nowrap;">
                        <button type="button" class="btn-outline" style="padding:4px 8px; font-size:0.75rem; border-color:var(--color-danger); color:var(--color-danger);" onclick="excluirAbastecimento(${a.id})" title="Excluir abastecimento">🗑️</button>
                    </td>
                </tr>
            `;
        });

        tbody.innerHTML = html;
    }

    // Atualizar Badges de Vigência ANP
    function atualizarBadgesANP(listaANP) {
        const badgeStatus = document.getElementById('badge-anp-status');
        const infoDefasagem = document.getElementById('anp-info-defasagem');
        const infoRegistros = document.getElementById('anp-info-registros');

        if (infoRegistros) infoRegistros.textContent = `${listaANP.length} referências ativas`;

        const defasado = listaANP.some(ref => ref.esta_defasado);

        if (defasado) {
            if (badgeStatus) {
                badgeStatus.className = 'fuel-badge-defasado';
                badgeStatus.textContent = 'Referência Defasada (>14 dias)';
            }
            if (infoDefasagem) {
                infoDefasagem.innerHTML = '<span style="color:var(--color-danger); font-weight:700;">⚠️ Base de preços da ANP defasada há mais de 14 dias. Importe um novo arquivo LPC para atualizar.</span>';
            }
        } else {
            if (badgeStatus) {
                badgeStatus.className = 'fuel-badge-vigente';
                badgeStatus.textContent = 'Referência Vigente';
            }
            if (infoDefasagem) {
                infoDefasagem.innerHTML = '<span style="color:var(--color-success); font-weight:700;">✅ Preços oficiais dentro do prazo regular de vigência.</span>';
            }
        }
    }

    // Carregar Veículos e Motoristas nos selects
    async function carregarSelectsCombustivel() {
        try {
            const resV = await fetch('/logistica/api/veiculos/?sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' });
            if (resV.ok) {
                const dataV = await resV.json();
                cacheVeiculosCombustivel = extrairListaDRF(dataV);

                const selFiltro = document.getElementById('filtro-combustivel-veiculo');
                const selModal = document.getElementById('abastecimento-veiculo');

                let options = '<option value="">Todos os Veículos</option>';
                let modalOptions = '<option value="">Selecione o Veículo</option>';

                cacheVeiculosCombustivel.forEach(v => {
                    const texto = `${formatPlaca(v.placa)} - ${v.modelo} (${v.marca})`;
                    options += `<option value="${v.id}">${texto}</option>`;
                    modalOptions += `<option value="${v.id}">${texto}</option>`;
                });

                if (selFiltro) selFiltro.innerHTML = options;
                if (selModal) selModal.innerHTML = modalOptions;
            }
        } catch (e) {
            console.error('Erro ao carregar veículos para combustível:', e);
        }

        // Carregar Motoristas no modal
        try {
            const resU = await fetch('/accounts/api/users/?sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' });
            if (resU.ok) {
                const dataU = await resU.json();
                const usuarios = extrairListaDRF(dataU);
                const selMotorista = document.getElementById('abastecimento-motorista');
                if (selMotorista) {
                    let uOpts = '<option value="">Não informado / Frota</option>';
                    usuarios.forEach(u => {
                        const nome = u.first_name ? `${u.first_name} ${u.last_name || ''}`.trim() : u.username;
                        uOpts += `<option value="${u.id}">${nome}</option>`;
                    });
                    selMotorista.innerHTML = uOpts;
                }
            }
        } catch (e) {}
    }

    // Filtros de Período
    const selPeriodo = document.getElementById('filtro-combustivel-periodo');
    if (selPeriodo) {
        selPeriodo.addEventListener('change', () => {
            const grpIni = document.getElementById('grp-filtro-inicio');
            const grpFim = document.getElementById('grp-filtro-fim');
            if (selPeriodo.value === 'personalizado') {
                if (grpIni) grpIni.style.display = 'flex';
                if (grpFim) grpFim.style.display = 'flex';
            } else {
                if (grpIni) grpIni.style.display = 'none';
                if (grpFim) grpFim.style.display = 'none';
                loadCombustivel();
            }
        });
    }

    document.getElementById('btn-aplicar-filtros-combustivel')?.addEventListener('click', () => {
        loadCombustivel();
    });

    document.getElementById('btn-limpar-filtros-combustivel')?.addEventListener('click', () => {
        if (selPeriodo) selPeriodo.value = 'este_mes';
        const grpIni = document.getElementById('grp-filtro-inicio');
        const grpFim = document.getElementById('grp-filtro-fim');
        if (grpIni) grpIni.style.display = 'none';
        if (grpFim) grpFim.style.display = 'none';
        const sV = document.getElementById('filtro-combustivel-veiculo');
        const sT = document.getElementById('filtro-combustivel-tipo');
        const sS = document.getElementById('filtro-combustivel-status');
        if (sV) sV.value = '';
        if (sT) sT.value = '';
        if (sS) sS.value = '';
        loadCombustivel();
    });

    // ==============================================================================
    // MODAL NOVO ABASTECIMENTO
    // ==============================================================================
    const modalAbast = document.getElementById('modal-abastecimento');
    const btnNovoAbast = document.getElementById('btn-novo-abastecimento');
    const btnFecharAbast = document.getElementById('btn-fechar-modal-abastecimento');
    const btnCancelarAbast = document.getElementById('btn-cancelar-abastecimento');

    function abrirModalAbastecimento() {
        document.getElementById('form-abastecimento')?.reset();
        document.getElementById('abastecimento-id').value = '';
        document.getElementById('aviso-odometro-menor').style.display = 'none';

        // Preenche data/hora local atual
        const agora = new Date();
        const offset = agora.getTimezoneOffset() * 60000;
        const localISOTime = (new Date(agora - offset)).toISOString().slice(0, 16);
        const inputData = document.getElementById('abastecimento-data-hora');
        if (inputData) inputData.value = localISOTime;

        if (modalAbast) modalAbast.classList.add('active');
        atualizarComparativoANPModal();
    }

    btnNovoAbast?.addEventListener('click', abrirModalAbastecimento);
    btnFecharAbast?.addEventListener('click', () => modalAbast?.classList.remove('active'));
    btnCancelarAbast?.addEventListener('click', () => modalAbast?.classList.remove('active'));

    // Ao selecionar o veículo no modal
    const selVeiculoModal = document.getElementById('abastecimento-veiculo');
    const inputOdoAnterior = document.getElementById('abastecimento-odometro-anterior');
    const inputNovoOdo = document.getElementById('abastecimento-odometro');
    const avisoOdo = document.getElementById('aviso-odometro-menor');
    const selTipoCombModal = document.getElementById('abastecimento-tipo-combustivel');

    selVeiculoModal?.addEventListener('change', () => {
        const vId = Number(selVeiculoModal.value);
        const v = cacheVeiculosCombustivel.find(item => item.id === vId);
        if (v) {
            const odoAtual = v.odometro_atual_km || 0;
            if (inputOdoAnterior) inputOdoAnterior.value = `${odoAtual.toLocaleString('pt-BR')} km`;
            if (inputNovoOdo) inputNovoOdo.value = odoAtual;
            if (v.combustivel_padrao && selTipoCombModal) {
                selTipoCombModal.value = v.combustivel_padrao;
            }
        } else {
            if (inputOdoAnterior) inputOdoAnterior.value = '-- km';
        }
        verificarOdometroValido();
        atualizarComparativoANPModal();
    });

    inputNovoOdo?.addEventListener('input', verificarOdometroValido);

    function verificarOdometroValido() {
        const vId = Number(selVeiculoModal?.value);
        const v = cacheVeiculosCombustivel.find(item => item.id === vId);
        if (v && inputNovoOdo) {
            const novo = Number(inputNovoOdo.value || 0);
            const atual = Number(v.odometro_atual_km || 0);
            if (novo < atual) {
                if (avisoOdo) avisoOdo.style.display = 'block';
            } else {
                if (avisoOdo) avisoOdo.style.display = 'none';
            }
        }
    }

    // Auto-cálculo dos 3 valores (Litros, Valor/Litro, Valor Total)
    const inLitros = document.getElementById('abastecimento-litros');
    const inValorLitro = document.getElementById('abastecimento-valor-litro');
    const inValorTotal = document.getElementById('abastecimento-valor-total');

    inLitros?.addEventListener('input', () => {
        lastEditedFuelField = 'litros';
        const l = parseFloat(inLitros.value);
        const vl = parseFloat(inValorLitro.value);
        const vt = parseFloat(inValorTotal.value);

        if (!isNaN(l) && l > 0) {
            if (!isNaN(vl) && vl > 0) {
                inValorTotal.value = (l * vl).toFixed(2);
            } else if (!isNaN(vt) && vt > 0) {
                inValorLitro.value = (vt / l).toFixed(4);
            }
        }
        atualizarComparativoANPModal();
    });

    inValorLitro?.addEventListener('input', () => {
        lastEditedFuelField = 'valor_litro';
        const l = parseFloat(inLitros.value);
        const vl = parseFloat(inValorLitro.value);
        const vt = parseFloat(inValorTotal.value);

        if (!isNaN(vl) && vl > 0) {
            if (!isNaN(l) && l > 0) {
                inValorTotal.value = (l * vl).toFixed(2);
            } else if (!isNaN(vt) && vt > 0) {
                inLitros.value = (vt / vl).toFixed(3);
            }
        }
        atualizarComparativoANPModal();
    });

    inValorTotal?.addEventListener('input', () => {
        lastEditedFuelField = 'valor_total';
        const l = parseFloat(inLitros.value);
        const vl = parseFloat(inValorLitro.value);
        const vt = parseFloat(inValorTotal.value);

        if (!isNaN(vt) && vt > 0) {
            if (!isNaN(l) && l > 0) {
                inValorLitro.value = (vt / l).toFixed(4);
            } else if (!isNaN(vl) && vl > 0) {
                inLitros.value = (vt / vl).toFixed(3);
            }
        }
        atualizarComparativoANPModal();
    });

    selTipoCombModal?.addEventListener('change', atualizarComparativoANPModal);

    function atualizarComparativoANPModal() {
        const prod = selTipoCombModal?.value;
        const vl = parseFloat(inValorLitro?.value);
        const callout = document.getElementById('abastecimento-anp-texto');
        if (!callout) return;

        if (!prod || prod === 'Arla 32') {
            callout.textContent = 'Arla 32 não é precificado na pesquisa de combustíveis da ANP.';
            return;
        }

        const ref = cachePrecosANP.find(r => r.produto === prod);
        if (!ref) {
            callout.textContent = `Referência ANP: Não há preço oficial cadastrado para ${prod}.`;
            return;
        }

        const media = Number(ref.preco_medio);
        let texto = `Referência Oficial ANP (${ref.uf || 'Brasil'}): ${formatPrecoLitro(media)}/L`;

        if (!isNaN(vl) && vl > 0 && media > 0) {
            const delta = ((vl - media) / media) * 100;
            if (delta > 0) {
                texto += ` • Seu preço está +${delta.toFixed(1)}% acima da média oficial.`;
            } else if (delta < 0) {
                texto += ` • Seu preço está ${delta.toFixed(1)}% abaixo da média oficial (economia).`;
            } else {
                texto += ` • Preço em paridade exata com a média ANP.`;
            }
        }
        callout.textContent = texto;
    }

    // Submissão do Formulário de Abastecimento
    document.getElementById('form-abastecimento')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const vId = Number(document.getElementById('abastecimento-veiculo').value);
        const v = cacheVeiculosCombustivel.find(item => item.id === vId);
        const novoOdo = Number(document.getElementById('abastecimento-odometro').value);

        if (v && novoOdo < Number(v.odometro_atual_km || 0)) {
            Swal.fire('Quilometragem Inválida', `O novo odômetro (${novoOdo} km) não pode ser inferior ao último odômetro do veículo (${v.odometro_atual_km} km).`, 'warning');
            return;
        }

        const btnSubmit = document.getElementById('btn-salvar-abastecimento');
        if (btnSubmit) {
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = 'Gravando...';
        }

        const formData = new FormData(form);
        // Trata checkbox tanque_cheio booleano explicitamente
        const isTanqueCheio = document.getElementById('abastecimento-tanque-cheio').checked;
        formData.set('tanque_cheio', isTanqueCheio ? 'true' : 'false');
        formData.set('origem', 'Painel');

        try {
            const res = await fetch('/logistica/api/abastecimentos/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken') || '',
                    'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
                    'X-Tenant-ID': (document.querySelector('meta[name="active-tenant-id"]')?.content || '')
                },
                body: formData
            });

            const resp = await res.json();
            if (!res.ok) {
                let msg = 'Erro ao registrar abastecimento.';
                if (typeof resp === 'object') {
                    msg = Object.entries(resp).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : v}`).join('\n');
                }
                throw new Error(msg);
            }

            modalAbast?.classList.remove('active');
            Swal.fire({
                title: 'Abastecimento Registrado!',
                text: resp.alertas && resp.alertas.length > 0 ? `Atenção aos alertas:\n${resp.alertas.join('\n')}` : 'Registro gravado e odômetro do veículo atualizado com sucesso.',
                icon: resp.status_validacao === 'NORMAL' ? 'success' : 'warning'
            });

            // Atualiza cache de veículos
            cacheVeiculosCombustivel = [];
            await loadCombustivel();
        } catch (err) {
            Swal.fire('Falha no Registro', err.message, 'error');
        } finally {
            if (btnSubmit) {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = '💾 Salvar Abastecimento';
            }
        }
    });

    // Exclusão de Abastecimento
    window.excluirAbastecimento = async function(id) {
        const confirm = await Swal.fire({
            title: 'Excluir Abastecimento?',
            text: 'Esta ação não poderá ser desfeita.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#ef4444',
            confirmButtonText: 'Sim, excluir'
        });

        if (!confirm.isConfirmed) return;

        try {
            const res = await fetch(`/logistica/api/abastecimentos/${id}/`, {
                method: 'DELETE',
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (!res.ok) throw new Error('Não foi possível excluir o abastecimento.');
            Swal.fire('Excluído!', 'Registro de abastecimento removido.', 'success');
            loadCombustivel();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    };

    // Modal Visualizar Comprovante Seguro
    const modalComp = document.getElementById('modal-comprovante-abastecimento');
    const btnFecharComp = document.getElementById('btn-fechar-modal-comprovante');
    const btnFecharComp2 = document.getElementById('btn-fechar-comprovante-viewer');

    btnFecharComp?.addEventListener('click', () => modalComp?.classList.remove('active'));
    btnFecharComp2?.addEventListener('click', () => modalComp?.classList.remove('active'));

    window.abrirModalComprovante = function(id, urlRelativa) {
        const viewer = document.getElementById('comprovante-viewer-container');
        const btnDown = document.getElementById('btn-download-comprovante');
        const urlSegura = `/logistica/api/abastecimentos/${id}/comprovante/`;

        if (btnDown) btnDown.href = urlSegura;

        const isPdf = urlRelativa.toLowerCase().endsWith('.pdf');
        if (isPdf) {
            viewer.innerHTML = `<iframe src="${urlSegura}" style="width:100%; height:420px; border:none; border-radius:8px;"></iframe>`;
        } else {
            viewer.innerHTML = `<img src="${urlSegura}" style="max-width:100%; max-height:420px; border-radius:8px; object-fit:contain;" alt="Cupom Fiscal" onerror="this.onerror=null; this.src='${urlRelativa}';">`;
        }

        if (modalComp) modalComp.classList.add('active');
    };

    // ==============================================================================
    // MODAL IMPORTAR DADOS ANP
    // ==============================================================================
    const modalANP = document.getElementById('modal-importar-anp');
    const btnAbrirANP = document.getElementById('btn-abrir-importar-anp');
    const btnFecharANP = document.getElementById('btn-fechar-modal-importar-anp');

    btnAbrirANP?.addEventListener('click', () => {
        if (modalANP) modalANP.classList.add('active');
        document.getElementById('resultado-importacao-anp').style.display = 'none';
    });
    btnFecharANP?.addEventListener('click', () => modalANP?.classList.remove('active'));

    // Upload de CSV Oficial da ANP
    document.getElementById('form-upload-csv-anp')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const inputCsv = document.getElementById('input-csv-anp');
        if (!inputCsv || !inputCsv.files || inputCsv.files.length === 0) {
            Swal.fire('Arquivo Ausente', 'Selecione o arquivo CSV baixado da ANP.', 'warning');
            return;
        }

        const btnEnv = document.getElementById('btn-enviar-csv-anp');
        if (btnEnv) {
            btnEnv.disabled = true;
            btnEnv.innerHTML = 'Processando CSV ANP...';
        }

        const formData = new FormData();
        formData.append('arquivo', inputCsv.files[0]);

        try {
            const res = await fetch('/logistica/api/combustivel/importar-anp/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken') || '',
                    'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
                    'X-Tenant-ID': (document.querySelector('meta[name="active-tenant-id"]')?.content || '')
                },
                body: formData
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao processar CSV da ANP.');

            const resDiv = document.getElementById('resultado-importacao-anp');
            if (resDiv) {
                resDiv.style.display = 'block';
                resDiv.style.background = 'rgba(16, 185, 129, 0.12)';
                resDiv.style.border = '1px solid rgba(16, 185, 129, 0.3)';
                resDiv.style.color = 'var(--color-success)';
                resDiv.innerHTML = `<strong>Sucesso!</strong> Foram criadas ${data.criados} referências e atualizadas ${data.atualizados}.`;
            }

            Swal.fire('Importação Concluída', `Preços ANP importados com sucesso! (${data.criados} criados, ${data.atualizados} atualizados)`, 'success');
            loadCombustivel();
        } catch (err) {
            Swal.fire('Falha na Importação', err.message, 'error');
        } finally {
            if (btnEnv) {
                btnEnv.disabled = false;
                btnEnv.innerHTML = '📥 Processar Arquivo CSV';
            }
        }
    });

    // Carga Rápida de Referência ANP
    document.getElementById('btn-carga-rapida-anp')?.addEventListener('click', async () => {
        const btnCarga = document.getElementById('btn-carga-rapida-anp');
        if (btnCarga) {
            btnCarga.disabled = true;
            btnCarga.innerHTML = 'Carregando médias oficiais...';
        }

        try {
            const res = await fetch('/logistica/api/combustivel/importar-anp/', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Falha ao executar carga padrão.');

            const resDiv = document.getElementById('resultado-importacao-anp');
            if (resDiv) {
                resDiv.style.display = 'block';
                resDiv.style.background = 'rgba(16, 185, 129, 0.12)';
                resDiv.style.border = '1px solid rgba(16, 185, 129, 0.3)';
                resDiv.style.color = 'var(--color-success)';
                resDiv.innerHTML = `<strong>Carga Padrão Aplicada!</strong> ${data.criados} referências criadas e ${data.atualizados} atualizadas para Diesel S10, Gasolina e Etanol.`;
            }

            Swal.fire('Carga Concluída', `Base de preços da ANP atualizada com sucesso (${data.criados} criados, ${data.atualizados} atualizados).`, 'success');
            loadCombustivel();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        } finally {
            if (btnCarga) {
                btnCarga.disabled = false;
                btnCarga.innerHTML = '⚡ Executar Carga Imediata de Preços ANP';
            }
        }
    });


    // ==============================================================================
    // 5. MÓDULO DE MANUTENÇÃO PREVENTIVA E CORRETIVA (SPRINT L3)
    // ==============================================================================

    let veiculosFrotaCache = [];
    let fornecedoresFrotaCache = [];
    let ordensServicoCache = [];
    let planosManutencaoCache = [];
    let osModalAtualId = null;
    let planoModalAtualId = null;
    let fornecedorModalAtualId = null;

    // Sub-navegação interna de Manutenção (Pills)
    const maintSubtabBtns = document.querySelectorAll('.maint-subtab-btn');
    const maintSubtabPanes = document.querySelectorAll('.maint-subtab-pane');

    maintSubtabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            maintSubtabBtns.forEach(b => b.classList.remove('active'));
            maintSubtabPanes.forEach(p => {
                p.classList.remove('active');
                p.style.display = 'none';
            });
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-maint-subtab');
            const pane = document.getElementById(targetId);
            if (pane) {
                pane.classList.add('active');
                pane.style.display = 'block';
            }
        });
    });

    // Sub-navegação interna do Modal de OS (4 Abas)
    const osSubtabBtns = document.querySelectorAll('#modal-os .modal-subtab-btn');
    const osSubtabPanes = document.querySelectorAll('#modal-os .os-subtab-pane');

    osSubtabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            osSubtabBtns.forEach(b => b.classList.remove('active'));
            osSubtabPanes.forEach(p => {
                p.classList.remove('active');
                p.style.display = 'none';
            });
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-os-subtab');
            const pane = document.getElementById(targetId);
            if (pane) {
                pane.classList.add('active');
                pane.style.display = 'block';
            }
        });
    });

    function ativarSubtabOS(tabId) {
        const btn = document.querySelector(`#modal-os [data-os-subtab="${tabId}"]`);
        if (btn) btn.click();
    }

    // Fechamento de Modais de Manutenção
    const modalOS = document.getElementById('modal-os');
    const modalPlano = document.getElementById('modal-plano-manutencao');
    const modalFornecedor = document.getElementById('modal-fornecedor');
    const modalChkDetalhe = document.getElementById('modal-checklist-detalhe');

    function fecharModalOS() {
        if (modalOS) modalOS.classList.remove('active');
        osModalAtualId = null;
    }
    function fecharModalPlano() {
        if (modalPlano) modalPlano.classList.remove('active');
        planoModalAtualId = null;
    }
    function fecharModalFornecedor() {
        if (modalFornecedor) modalFornecedor.classList.remove('active');
        fornecedorModalAtualId = null;
    }
    function fecharModalChkDetalhe() {
        if (modalChkDetalhe) modalChkDetalhe.classList.remove('active');
    }

    document.getElementById('btn-fechar-modal-os')?.addEventListener('click', fecharModalOS);
    document.getElementById('btn-fechar-modal-os-bottom')?.addEventListener('click', fecharModalOS);
    document.getElementById('btn-fechar-modal-plano')?.addEventListener('click', fecharModalPlano);
    document.getElementById('btn-cancelar-modal-plano')?.addEventListener('click', fecharModalPlano);
    document.getElementById('btn-fechar-modal-fornecedor')?.addEventListener('click', fecharModalFornecedor);
    document.getElementById('btn-cancelar-modal-fornecedor')?.addEventListener('click', fecharModalFornecedor);
    document.getElementById('btn-fechar-modal-chk')?.addEventListener('click', fecharModalChkDetalhe);
    document.getElementById('btn-fechar-modal-chk-bottom')?.addEventListener('click', fecharModalChkDetalhe);

    // Botões de Abertura nos Cabeçalhos
    document.getElementById('btn-nova-os')?.addEventListener('click', () => abrirModalOS());
    document.getElementById('btn-novo-plano')?.addEventListener('click', () => abrirModalPlano());
    document.getElementById('btn-novo-fornecedor')?.addEventListener('click', () => abrirModalFornecedor());

    // Disparador de Alertas Preventivos
    document.getElementById('btn-executar-alertas-preventivos')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-executar-alertas-preventivos');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '⏳ Processando Alertas...';
        }
        try {
            const res = await fetch('/logistica/api/planos-manutencao/gerar-alertas/', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Falha ao processar alertas preventivos.');

            Swal.fire({
                title: 'Varredura Preventiva Concluída',
                text: `${data.planos_verificados} planos verificados. ${data.alertas_gerados} alertas emitidos e ${data.os_geradas} novas OS preventivas abertas automaticamente.`,
                icon: 'success'
            });
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro na Varredura', err.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '⚡ Gerar OS Preventivas';
            }
        }
    });

    // Filtros do Kanban
    document.getElementById('filtro-maint-veiculo')?.addEventListener('change', renderKanbanOS);
    document.getElementById('filtro-maint-tipo')?.addEventListener('change', renderKanbanOS);

    // Mudança de Veículo no Modal de OS para carregar planos e odômetro
    document.getElementById('os-veiculo')?.addEventListener('change', (e) => {
        const vId = parseInt(e.target.value, 10);
        popularPlanosNoSelectOS(vId);
        if (vId) {
            const vObj = veiculosFrotaCache.find(x => x.id === vId);
            if (vObj && vObj.odometro_atual_km !== undefined) {
                const odoEntrada = document.getElementById('os-odometro-entrada');
                if (odoEntrada && !odoEntrada.value) {
                    odoEntrada.value = vObj.odometro_atual_km;
                }
            }
        }
    });

    function popularPlanosNoSelectOS(veiculoId, selectedPlanoId = null) {
        const sel = document.getElementById('os-plano');
        if (!sel) return;
        sel.innerHTML = '<option value="">Nenhum (Livre / Avulso)</option>';
        if (!veiculoId) return;

        const planos = planosManutencaoCache.filter(p => p.veiculo === veiculoId && p.ativo);
        planos.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = `${p.descricao} (A cada ${p.gatilho_km ? p.gatilho_km + ' km' : ''}${p.gatilho_km && p.gatilho_dias ? ' / ' : ''}${p.gatilho_dias ? p.gatilho_dias + ' dias' : ''})`;
            if (selectedPlanoId && p.id === parseInt(selectedPlanoId, 10)) {
                opt.selected = true;
            }
            sel.appendChild(opt);
        });
    }

    // ==============================================================================
    // CARREGADOR CENTRAL DE MANUTENÇÃO (loadManutencao)
    // ==============================================================================
    async function loadManutencao() {
        try {
            // 1. Carrega Veículos e Fornecedores em Paralelo
            const [resVeiculos, resFornecedores, resPlanos] = await Promise.all([
                fetch('/logistica/api/veiculos/?sem_paginacao=1', { headers: getAuthHeaders() }),
                fetch('/logistica/api/fornecedores/?sem_paginacao=1', { headers: getAuthHeaders() }),
                fetch('/logistica/api/planos-manutencao/?sem_paginacao=1', { headers: getAuthHeaders() })
            ]);

            const [rawVeic, rawForn, rawPlanos] = await Promise.all([
                resVeiculos.json(),
                resFornecedores.json(),
                resPlanos.json()
            ]);

            veiculosFrotaCache = extrairListaDRF(rawVeic);
            fornecedoresFrotaCache = extrairListaDRF(rawForn);
            planosManutencaoCache = extrairListaDRF(rawPlanos);

            // Popula Selects de Veículos e Fornecedores
            popularSelectsManutencao();

            // 2. Carrega Ordens de Serviço (Kanban e KPIs)
            await carregarOrdensServico();

            // 3. Carrega Planos Preventivos e Próximos Vencimentos
            await carregarVencimentosEPlanos();

            // 4. Carrega Indicadores e TCO
            await carregarIndicadoresManutencao();

            // 5. Carrega Checklists Realizados
            await carregarChecklists();

            // 6. Atualiza Tabela de Fornecedores
            renderFornecedoresTable();

        } catch (err) {
            console.error('Erro ao carregar dados de manutenção:', err);
        }
    }

    function popularSelectsManutencao() {
        // Filtro do Kanban
        const filtroVeic = document.getElementById('filtro-maint-veiculo');
        const osVeic = document.getElementById('os-veiculo');
        const planoVeic = document.getElementById('plano-veiculo');

        if (filtroVeic) {
            const valAtual = filtroVeic.value;
            filtroVeic.innerHTML = '<option value="">Todos os Veículos</option>';
            veiculosFrotaCache.forEach(v => {
                filtroVeic.innerHTML += `<option value="${v.id}">${formatPlaca(v.placa)} - ${v.modelo}</option>`;
            });
            filtroVeic.value = valAtual;
        }

        if (osVeic) {
            const valAtual = osVeic.value;
            osVeic.innerHTML = '<option value="">Selecione o Veículo</option>';
            veiculosFrotaCache.forEach(v => {
                osVeic.innerHTML += `<option value="${v.id}">${formatPlaca(v.placa)} - ${v.modelo}</option>`;
            });
            osVeic.value = valAtual;
        }

        if (planoVeic) {
            const valAtual = planoVeic.value;
            planoVeic.innerHTML = '<option value="">Selecione o Veículo</option>';
            veiculosFrotaCache.forEach(v => {
                planoVeic.innerHTML += `<option value="${v.id}">${formatPlaca(v.placa)} - ${v.modelo}</option>`;
            });
            planoVeic.value = valAtual;
        }

        // Fornecedores selects
        const osForn = document.getElementById('os-fornecedor');
        const planoForn = document.getElementById('plano-fornecedor');

        if (osForn) {
            const valAtual = osForn.value;
            osForn.innerHTML = '<option value="">Selecione a Oficina (Opcional)</option>';
            fornecedoresFrotaCache.forEach(f => {
                if (f.ativo) {
                    osForn.innerHTML += `<option value="${f.id}">${f.nome} (${f.cidade || 'Base'})</option>`;
                }
            });
            osForn.value = valAtual;
        }

        if (planoForn) {
            const valAtual = planoForn.value;
            planoForn.innerHTML = '<option value="">Nenhum (Livre)</option>';
            fornecedoresFrotaCache.forEach(f => {
                if (f.ativo) {
                    planoForn.innerHTML += `<option value="${f.id}">${f.nome} (${f.cidade || 'Base'})</option>`;
                }
            });
            planoForn.value = valAtual;
        }
    }

    // ==============================================================================
    // KANBAN DE ORDENS DE SERVIÇO (5 ETAPAS)
    // ==============================================================================
    async function carregarOrdensServico() {
        try {
            const res = await fetch('/logistica/api/ordens-servico/?sem_paginacao=1', { headers: getAuthHeaders() });
            const raw = await res.json();
            ordensServicoCache = extrairListaDRF(raw);

            // Atualiza KPI Na Oficina / Imobilizados
            const imobilizados = ordensServicoCache.filter(o => 
                o.imobiliza_veiculo && ['Aberta', 'Orçada', 'Aprovada', 'Em Execução'].includes(o.status)
            ).length;
            const elOficina = document.getElementById('maint-count-oficina');
            if (elOficina) elOficina.textContent = imobilizados;

            // Atualiza KPI Custo Manutenção do Período
            const totalCusto = ordensServicoCache
                .filter(o => o.status === 'Concluída')
                .reduce((acc, o) => acc + (parseFloat(o.custo_total) || 0), 0);
            const elCustoMes = document.getElementById('maint-custo-mes');
            if (elCustoMes) elCustoMes.textContent = formatCurrency(totalCusto);

            renderKanbanOS();
        } catch (err) {
            console.error('Erro ao carregar Ordens de Serviço:', err);
        }
    }

    function renderKanbanOS() {
        const vId = document.getElementById('filtro-maint-veiculo')?.value;
        const tipo = document.getElementById('filtro-maint-tipo')?.value;

        let lista = ordensServicoCache;
        if (vId) lista = lista.filter(o => o.veiculo === parseInt(vId, 10));
        if (tipo) lista = lista.filter(o => o.tipo === tipo);

        const colunas = {
            'Aberta': { itemsEl: document.getElementById('items-os-aberta'), countEl: document.getElementById('count-os-aberta'), list: [] },
            'Orçada': { itemsEl: document.getElementById('items-os-orcada'), countEl: document.getElementById('count-os-orcada'), list: [] },
            'Aprovada': { itemsEl: document.getElementById('items-os-aprovada'), countEl: document.getElementById('count-os-aprovada'), list: [] },
            'Em Execução': { itemsEl: document.getElementById('items-os-execucao'), countEl: document.getElementById('count-os-execucao'), list: [] },
            'Concluída': { itemsEl: document.getElementById('items-os-concluida'), countEl: document.getElementById('count-os-concluida'), list: [] }
        };

        lista.forEach(o => {
            if (colunas[o.status]) {
                colunas[o.status].list.push(o);
            }
        });

        Object.keys(colunas).forEach(key => {
            const col = colunas[key];
            if (col.countEl) col.countEl.textContent = col.list.length;
            if (!col.itemsEl) return;

            col.itemsEl.innerHTML = '';
            if (col.list.length === 0) {
                col.itemsEl.innerHTML = '<div style="text-align:center; padding:18px 8px; font-size:0.8rem; color:var(--color-text-muted);">Nenhuma OS nesta etapa.</div>';
                return;
            }

            col.list.forEach(os => {
                const prioClass = (os.prioridade || 'Normal').toLowerCase();
                const tipoClass = (os.tipo || 'Preventiva').toLowerCase();
                const placaFmt = os.veiculo_placa ? formatPlaca(os.veiculo_placa) : 'Veículo';
                const custoStr = formatCurrency(os.custo_total || 0);

                const card = document.createElement('div');
                card.className = `maint-os-card prioridade-${prioClass}`;
                card.onclick = () => abrirModalOS(os.id);

                card.innerHTML = `
                    <div class="maint-os-card-header">
                        <span class="maint-os-num">${os.numero}</span>
                        <span class="maint-badge-prio prio-${prioClass}">${os.prioridade}</span>
                    </div>
                    <div class="maint-os-vehicle">
                        <span class="plate-tag" style="font-size:0.75rem; padding:2px 6px;">${placaFmt}</span>
                        <span style="font-size:0.82rem; font-weight:700; color:var(--color-text);">${os.veiculo_modelo || ''}</span>
                    </div>
                    <div style="display:flex; gap:6px; flex-wrap:wrap; margin:6px 0;">
                        <span class="maint-badge-tipo tipo-${tipoClass}">${os.tipo}</span>
                        <span class="maint-badge-origem">${os.origem}</span>
                        ${os.imobiliza_veiculo ? '<span class="maint-badge-imobilizado">🛑 Imobilizado</span>' : ''}
                    </div>
                    <div class="maint-os-desc" title="${os.descricao_problema}">${os.descricao_problema}</div>
                    <div class="maint-os-card-footer">
                        <span class="maint-os-cost">${custoStr}</span>
                        <span class="maint-os-date">${os.data_abertura ? formatDate(os.data_abertura) : ''}</span>
                    </div>
                `;
                col.itemsEl.appendChild(card);
            });
        });
    }

    // ==============================================================================
    // PLANOS PREVENTIVOS E VENCIMENTOS
    // ==============================================================================
    async function carregarVencimentosEPlanos() {
        try {
            const res = await fetch('/logistica/api/planos-manutencao/vencimentos/', { headers: getAuthHeaders() });
            const lista = await res.json();

            const elTotalPlanos = document.getElementById('maint-count-planos');
            const elVencidas = document.getElementById('maint-count-vencidas');
            const elVencendo = document.getElementById('maint-count-vencendo');

            if (elTotalPlanos) elTotalPlanos.textContent = lista.length;

            const vencidos = lista.filter(x => x.vencido).length;
            const vencendo = lista.filter(x => x.alerta && !x.vencido).length;

            if (elVencidas) elVencidas.textContent = vencidos;
            if (elVencendo) elVencendo.textContent = vencendo;

            const tbody = document.getElementById('tbody-planos-manutencao');
            if (!tbody) return;

            tbody.innerHTML = '';
            if (lista.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:var(--color-text-muted);">Nenhum plano preventivo configurado na frota.</td></tr>';
                return;
            }

            lista.forEach(p => {
                let badgeClass = 'doc-badge-ok';
                let badgeText = '✓ Em Dia';

                if (p.vencido) {
                    badgeClass = 'doc-badge-danger';
                    badgeText = '❌ VENCIDO';
                } else if (p.alerta) {
                    badgeClass = 'doc-badge-warning';
                    badgeText = '⚠️ Vencendo';
                }

                const gatKm = p.gatilho_km ? `${p.gatilho_km.toLocaleString('pt-BR')} km` : '-';
                const gatDias = p.gatilho_dias ? `${p.gatilho_dias} dias` : '-';
                
                let vencInfo = '';
                if (p.proximo_km) vencInfo += `Km: <strong>${p.proximo_km.toLocaleString('pt-BR')}</strong>`;
                if (p.proxima_data) vencInfo += `${vencInfo ? '<br>' : ''}Data: <strong>${formatDate(p.proxima_data)}</strong>`;
                if (!vencInfo) vencInfo = '-';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>
                        <span class="plate-tag">${formatPlaca(p.veiculo_placa)}</span>
                        <div style="font-size:0.75rem; color:var(--color-text-muted); margin-top:2px;">${p.veiculo_modelo}</div>
                    </td>
                    <td><strong>${p.descricao}</strong></td>
                    <td>${gatKm}</td>
                    <td>${gatDias}</td>
                    <td>${vencInfo}</td>
                    <td>${formatCurrency(p.custo_estimado)}</td>
                    <td>${p.fornecedor_nome || '<span style="color:var(--color-text-muted);">-</span>'}</td>
                    <td style="text-align:center;">
                        <span class="doc-badge-status ${badgeClass}" title="${p.motivo || ''}">${badgeText}</span>
                    </td>
                    <td style="text-align:right; white-space:nowrap;">
                        <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px;" onclick="abrirModalOS(null, ${p.veiculo_id}, ${p.id})" title="Abrir OS deste Plano">⚡ Gerar OS</button>
                        <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px;" onclick="abrirModalPlano(${p.id})">Editar</button>
                        <button class="btn-outline" style="padding:4px 8px; font-size:12px; color:var(--color-danger);" onclick="excluirPlano(${p.id})">🗑️</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        } catch (err) {
            console.error('Erro ao carregar vencimentos de planos preventivos:', err);
        }
    }

    // ==============================================================================
    // INDICADORES DE FROTA & TCO
    // ==============================================================================
    async function carregarIndicadoresManutencao() {
        try {
            const res = await fetch('/logistica/api/manutencao/indicadores/', { headers: getAuthHeaders() });
            const data = await res.json();

            // Card 1: Confiabilidade
            const elDisp = document.getElementById('ind-disponibilidade');
            const elMtbf = document.getElementById('ind-mtbf');
            const elMttr = document.getElementById('ind-mttr');
            const elCustoKm = document.getElementById('ind-custo-km');

            if (elDisp) elDisp.textContent = `${data.disponibilidade_frota_percentual || 0}%`;
            if (elMtbf) elMtbf.textContent = `${data.mtbf_dias || 0} dias`;
            if (elMttr) elMttr.textContent = `${data.mttr_horas || 0} horas`;
            if (elCustoKm) elCustoKm.textContent = `R$ ${data.custo_manutencao_por_km || '0.00'} / km`;

            // Card 2: Preventiva vs Corretiva
            const pData = data.proporcao_preventiva_vs_corretiva || {};
            const elQtdPrev = document.getElementById('ind-qtd-prev');
            const elQtdCorr = document.getElementById('ind-qtd-corr');
            const elCustoPrev = document.getElementById('ind-custo-prev');
            const elCustoCorr = document.getElementById('ind-custo-corr');

            if (elQtdPrev) elQtdPrev.textContent = `${pData.qtd_preventivas || 0} (${pData.percentual_preventivas || 0}%)`;
            if (elQtdCorr) elQtdCorr.textContent = `${pData.qtd_corretivas || 0} (${pData.percentual_corretivas || 0}%)`;
            if (elCustoPrev) elCustoPrev.textContent = formatCurrency(pData.custo_preventivas || 0);
            if (elCustoCorr) elCustoCorr.textContent = formatCurrency(pData.custo_corretivas || 0);

            // Card 3: Alertas FIPE (>30%)
            const contFipe = document.getElementById('container-alertas-fipe');
            if (contFipe) {
                const alertasFipe = data.alertas_substituicao_fipe || [];
                if (alertasFipe.length === 0) {
                    contFipe.innerHTML = `
                        <div style="text-align:center; padding: 24px; color:var(--color-text-muted); font-size:0.85rem;">
                            ✓ Nenhum veículo excedeu o teto de 30% do valor de tabela FIPE.
                        </div>
                    `;
                } else {
                    contFipe.innerHTML = '';
                    alertasFipe.forEach(a => {
                        contFipe.innerHTML += `
                            <div class="maint-fipe-alert-card">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                    <strong>${formatPlaca(a.placa)} - ${a.modelo}</strong>
                                    <span class="maint-fipe-tag-danger">${a.percentual_atingido}% da FIPE</span>
                                </div>
                                <div style="font-size:0.8rem; color:var(--color-text-muted);">
                                    Gasto Anual: <strong>${formatCurrency(a.custo_manutencao_12m)}</strong> | FIPE: <strong>${formatCurrency(a.valor_fipe)}</strong>
                                </div>
                                <div style="font-size:0.75rem; color:var(--color-danger); margin-top:4px;">
                                    ⚠️ ${a.mensagem}
                                </div>
                            </div>
                        `;
                    });
                }
            }

            // Tabela Ranking TCO
            const tbodyTCO = document.getElementById('tbody-ranking-tco');
            if (tbodyTCO) {
                const ranking = data.ranking_tco || [];
                tbodyTCO.innerHTML = '';
                if (ranking.length === 0) {
                    tbodyTCO.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--color-text-muted);">Sem dados de custos para compor o TCO.</td></tr>';
                } else {
                    ranking.forEach(r => {
                        const fipeStr = r.valor_fipe ? formatCurrency(r.valor_fipe) : '<span style="color:var(--color-text-muted);">-</span>';
                        tbodyTCO.innerHTML += `
                            <tr>
                                <td><span class="plate-tag">${formatPlaca(r.placa)}</span></td>
                                <td><strong>${r.modelo}</strong> <span style="color:var(--color-text-muted);">(${r.ano_modelo || r.ano || '-'})</span></td>
                                <td style="text-align:right;">${formatCurrency(r.custo_manutencao)}</td>
                                <td style="text-align:right;">${formatCurrency(r.custo_combustivel)}</td>
                                <td style="text-align:right; font-weight:700; color:var(--color-primary);">${formatCurrency(r.tco_total)}</td>
                                <td style="text-align:right;">${(r.km_rodados_periodo || 0).toLocaleString('pt-BR')} km</td>
                                <td style="text-align:right;">R$ ${r.custo_por_km} / km</td>
                                <td style="text-align:right;">${fipeStr}</td>
                            </tr>
                        `;
                    });
                }
            }

        } catch (err) {
            console.error('Erro ao carregar indicadores de manutenção:', err);
        }
    }

    // ==============================================================================
    // CHECKLISTS REALIZADOS
    // ==============================================================================
    async function carregarChecklists() {
        try {
            const res = await fetch('/logistica/api/checklists/?sem_paginacao=1', { headers: getAuthHeaders() });
            const raw = await res.json();
            const lista = extrairListaDRF(raw);

            const elCount = document.getElementById('maint-count-checklists');
            if (elCount) elCount.textContent = lista.length;

            const tbody = document.getElementById('tbody-checklists-executados');
            if (!tbody) return;

            tbody.innerHTML = '';
            if (lista.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--color-text-muted);">Nenhum checklist registrado pelos motoristas.</td></tr>';
                return;
            }

            lista.forEach(chk => {
                const statusBadge = chk.aprovado 
                    ? '<span class="doc-badge-status doc-badge-ok">✓ APROVADO</span>'
                    : '<span class="doc-badge-status doc-badge-danger">❌ REPROVADO</span>';

                let impeditivosHtml = '-';
                if (chk.itens_impeditivos_reprovados && chk.itens_impeditivos_reprovados.length > 0) {
                    impeditivosHtml = `<span style="color:var(--color-danger); font-weight:700;">${chk.itens_impeditivos_reprovados.join(', ')}</span>`;
                }

                let osGeradaHtml = '<span style="color:var(--color-text-muted);">-</span>';
                if (chk.os_gerada) {
                    osGeradaHtml = `<button class="btn-outline" style="padding:2px 6px; font-size:11px;" onclick="abrirModalOS(${chk.os_gerada})">🔧 Ver OS</button>`;
                }

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${formatDate(chk.data_hora)}</td>
                    <td><span class="plate-tag">${chk.veiculo_placa ? formatPlaca(chk.veiculo_placa) : '-'}</span></td>
                    <td>${chk.motorista_nome || 'Motorista'}</td>
                    <td>${chk.odometro ? chk.odometro.toLocaleString('pt-BR') + ' km' : '-'}</td>
                    <td style="text-align:center;">${statusBadge}</td>
                    <td>${impeditivosHtml}</td>
                    <td>${osGeradaHtml}</td>
                    <td style="text-align:right;">
                        <button class="btn-outline" style="padding:4px 8px; font-size:12px;" onclick="abrirModalChecklistDetalhe(${chk.id})">🔍 Ver Inspeção</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        } catch (err) {
            console.error('Erro ao carregar checklists de veículos:', err);
        }
    }

    // Modal Detalhes do Checklist
    window.abrirModalChecklistDetalhe = async function(chkId) {
        try {
            const res = await fetch(`/logistica/api/checklists/${chkId}/`, { headers: getAuthHeaders() });
            const data = await res.json();

            const elResumo = document.getElementById('modal-chk-resumo');
            const tbody = document.getElementById('tbody-chk-itens-detalhe');
            const contFoto = document.getElementById('modal-chk-foto-container');

            if (elResumo) {
                elResumo.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                        <div>
                            <strong>Veículo:</strong> ${data.veiculo_placa ? formatPlaca(data.veiculo_placa) : '-'} | 
                            <strong>Motorista:</strong> ${data.motorista_nome || '-'} | 
                            <strong>Data:</strong> ${formatDate(data.data_hora)} | 
                            <strong>Odômetro:</strong> ${data.odometro ? data.odometro + ' km' : '-'}
                        </div>
                        <div>
                            ${data.aprovado ? '<span class="doc-badge-status doc-badge-ok">✓ Aprovado</span>' : '<span class="doc-badge-status doc-badge-danger">❌ Reprovado</span>'}
                        </div>
                    </div>
                    ${data.observacoes ? `<div style="margin-top:6px; font-style:italic;">Obs: "${data.observacoes}"</div>` : ''}
                `;
            }

            if (tbody) {
                tbody.innerHTML = '';
                const respostas = data.respostas_itens || [];
                if (respostas.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;">Sem respostas gravadas.</td></tr>';
                } else {
                    respostas.forEach(it => {
                        let stBadge = '<span style="color:var(--color-success); font-weight:700;">OK</span>';
                        if (it.status === 'Não OK') stBadge = '<span style="color:var(--color-danger); font-weight:700;">NÃO OK</span>';
                        else if (it.status === 'N.A.') stBadge = '<span style="color:var(--color-text-muted);">N.A.</span>';

                        tbody.innerHTML += `
                            <tr>
                                <td><strong>${it.nome}</strong></td>
                                <td style="text-align:center;">${stBadge}</td>
                                <td style="text-align:center;">${it.impeditivo ? '🛑 Sim' : 'Não'}</td>
                                <td>${it.obs || '-'}</td>
                            </tr>
                        `;
                    });
                }
            }

            if (contFoto) {
                if (data.foto) {
                    contFoto.innerHTML = `
                        <div style="margin-top:10px;">
                            <label style="font-size:0.8rem; font-weight:700; color:var(--color-text-muted);">Foto Registrada no Checklist:</label>
                            <div style="margin-top:6px;">
                                <a href="/logistica/api/manutencao/checklist-foto/${data.id}/download/" target="_blank">
                                    <img src="/logistica/api/manutencao/checklist-foto/${data.id}/download/" style="max-height:180px; border-radius:8px; border:1px solid var(--color-border);" alt="Foto do Checklist">
                                </a>
                            </div>
                        </div>
                    `;
                } else {
                    contFoto.innerHTML = '';
                }
            }

            modalChkDetalhe.classList.add('active');
        } catch (err) {
            Swal.fire('Erro', 'Não foi possível carregar o checklist selecionado.', 'error');
        }
    };

    // ==============================================================================
    // TABELA E MODAL DE FORNECEDORES / OFICINAS
    // ==============================================================================
    function renderFornecedoresTable() {
        const tbody = document.getElementById('tbody-fornecedores');
        if (!tbody) return;

        tbody.innerHTML = '';
        if (fornecedoresFrotaCache.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--color-text-muted);">Nenhuma oficina ou fornecedor cadastrado.</td></tr>';
            return;
        }

        fornecedoresFrotaCache.forEach(f => {
            const statusBadge = f.ativo 
                ? '<span class="doc-badge-status doc-badge-ok">Ativo</span>'
                : '<span class="doc-badge-status doc-badge-danger">Inativo</span>';

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${f.nome}</strong></td>
                <td>${f.documento || '-'}</td>
                <td>
                    <div>${f.telefone || '-'}</div>
                    <small style="color:var(--color-text-muted);">${f.email || ''}</small>
                </td>
                <td>${f.cidade || ''}${f.cidade && f.uf ? ' / ' : ''}${f.uf || ''}</td>
                <td>${f.especialidades || '<span style="color:var(--color-text-muted);">-</span>'}</td>
                <td style="text-align:center;"><strong>${f.total_os || 0}</strong></td>
                <td style="text-align:center;">${statusBadge}</td>
                <td style="text-align:right; white-space:nowrap;">
                    <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px;" onclick="abrirModalFornecedor(${f.id})">Editar</button>
                    <button class="btn-outline" style="padding:4px 8px; font-size:12px; color:var(--color-danger);" onclick="excluirFornecedor(${f.id})">🗑️</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    window.abrirModalFornecedor = function(id = null) {
        fornecedorModalAtualId = id;
        const form = document.getElementById('form-fornecedor');
        if (form) form.reset();
        document.getElementById('fornecedor-id').value = id || '';

        const tit = document.getElementById('modal-fornecedor-titulo');
        if (!id) {
            if (tit) tit.textContent = 'Cadastrar Fornecedor / Oficina';
        } else {
            if (tit) tit.textContent = 'Editar Fornecedor / Oficina';
            const fObj = fornecedoresFrotaCache.find(x => x.id === id);
            if (fObj) {
                document.getElementById('fornecedor-nome').value = fObj.nome || '';
                document.getElementById('fornecedor-documento').value = fObj.documento || '';
                document.getElementById('fornecedor-telefone').value = fObj.telefone || '';
                document.getElementById('fornecedor-email').value = fObj.email || '';
                document.getElementById('fornecedor-cidade').value = fObj.cidade || '';
                document.getElementById('fornecedor-uf').value = fObj.uf || '';
                document.getElementById('fornecedor-especialidades').value = fObj.especialidades || '';
                document.getElementById('fornecedor-observacoes').value = fObj.observacoes || '';
            }
        }
        modalFornecedor.classList.add('active');
    };

    document.getElementById('form-fornecedor')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fId = document.getElementById('fornecedor-id').value;
        const payload = {
            nome: document.getElementById('fornecedor-nome').value.trim(),
            documento: document.getElementById('fornecedor-documento').value.trim(),
            telefone: document.getElementById('fornecedor-telefone').value.trim(),
            email: document.getElementById('fornecedor-email').value.trim(),
            cidade: document.getElementById('fornecedor-cidade').value.trim(),
            uf: document.getElementById('fornecedor-uf').value.trim().toUpperCase(),
            especialidades: document.getElementById('fornecedor-especialidades').value.trim(),
            observacoes: document.getElementById('fornecedor-observacoes').value.trim(),
            ativo: true
        };

        const url = fId ? `/logistica/api/fornecedores/${fId}/` : '/logistica/api/fornecedores/';
        const method = fId ? 'PATCH' : 'POST';

        try {
            const res = await fetch(url, {
                method: method,
                headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            });
            if (!res.ok) {
                const errData = await res.json();
                throw new Error(JSON.stringify(errData));
            }
            Swal.fire('Sucesso!', 'Fornecedor salvo com sucesso.', 'success');
            fecharModalFornecedor();
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro ao Salvar', err.message, 'error');
        }
    });

    window.excluirFornecedor = async function(id) {
        const confirm = await Swal.fire({
            title: 'Excluir Fornecedor?',
            text: 'Deseja realmente remover esta oficina / prestador?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Sim, excluir',
            cancelButtonText: 'Cancelar'
        });
        if (!confirm.isConfirmed) return;

        try {
            const res = await fetch(`/logistica/api/fornecedores/${id}/`, {
                method: 'DELETE',
                headers: getAuthHeaders()
            });
            if (!res.ok) throw new Error('Não foi possível excluir o fornecedor.');
            Swal.fire('Removido', 'Fornecedor removido com sucesso.', 'success');
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    };

    // ==============================================================================
    // CRUD DE PLANOS PREVENTIVOS
    // ==============================================================================
    window.abrirModalPlano = function(id = null, veiculoId = null) {
        planoModalAtualId = id;
        const form = document.getElementById('form-plano-manutencao');
        if (form) form.reset();
        document.getElementById('plano-id').value = id || '';

        const tit = document.getElementById('modal-plano-titulo');
        if (!id) {
            if (tit) tit.textContent = 'Novo Plano Preventivo';
            if (veiculoId) document.getElementById('plano-veiculo').value = veiculoId;
        } else {
            if (tit) tit.textContent = 'Editar Plano Preventivo';
            const pObj = planosManutencaoCache.find(x => x.id === id);
            if (pObj) {
                document.getElementById('plano-veiculo').value = pObj.veiculo || '';
                document.getElementById('plano-descricao').value = pObj.descricao || '';
                document.getElementById('plano-gatilho-km').value = pObj.gatilho_km || '';
                document.getElementById('plano-gatilho-dias').value = pObj.gatilho_dias || '';
                document.getElementById('plano-alerta-km').value = pObj.antecedencia_alerta_km || '1000';
                document.getElementById('plano-alerta-dias').value = pObj.antecedencia_alerta_dias || '15';
                document.getElementById('plano-custo').value = pObj.custo_estimado || '0.00';
                document.getElementById('plano-fornecedor').value = pObj.fornecedor_preferido || '';
                document.getElementById('plano-ativo').checked = !!pObj.ativo;
            }
        }
        modalPlano.classList.add('active');
    };

    document.getElementById('form-plano-manutencao')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const pId = document.getElementById('plano-id').value;
        const veiculoVal = parseInt(document.getElementById('plano-veiculo').value, 10);
        const gatKm = document.getElementById('plano-gatilho-km').value ? parseInt(document.getElementById('plano-gatilho-km').value, 10) : null;
        const gatDias = document.getElementById('plano-gatilho-dias').value ? parseInt(document.getElementById('plano-gatilho-dias').value, 10) : null;

        if (!gatKm && !gatDias) {
            Swal.fire('Validação', 'Informe ao menos um gatilho para o plano (km ou dias).', 'warning');
            return;
        }

        const payload = {
            veiculo: veiculoVal,
            descricao: document.getElementById('plano-descricao').value.trim(),
            gatilho_km: gatKm,
            gatilho_dias: gatDias,
            antecedencia_alerta_km: parseInt(document.getElementById('plano-alerta-km').value, 10) || 1000,
            antecedencia_alerta_dias: parseInt(document.getElementById('plano-alerta-dias').value, 10) || 15,
            custo_estimado: parseFloat(document.getElementById('plano-custo').value) || 0,
            fornecedor_preferido: document.getElementById('plano-fornecedor').value ? parseInt(document.getElementById('plano-fornecedor').value, 10) : null,
            ativo: document.getElementById('plano-ativo').checked
        };

        const url = pId ? `/logistica/api/planos-manutencao/${pId}/` : '/logistica/api/planos-manutencao/';
        const method = pId ? 'PATCH' : 'POST';

        try {
            const res = await fetch(url, {
                method: method,
                headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            });
            if (!res.ok) {
                const errData = await res.json();
                throw new Error(JSON.stringify(errData));
            }
            Swal.fire('Sucesso!', 'Plano preventivo salvo com sucesso.', 'success');
            fecharModalPlano();
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro ao Salvar Plano', err.message, 'error');
        }
    });

    window.excluirPlano = async function(id) {
        const confirm = await Swal.fire({
            title: 'Excluir Plano Preventivo?',
            text: 'Deseja realmente remover este plano preventivo?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Sim, excluir',
            cancelButtonText: 'Cancelar'
        });
        if (!confirm.isConfirmed) return;

        try {
            const res = await fetch(`/logistica/api/planos-manutencao/${id}/`, {
                method: 'DELETE',
                headers: getAuthHeaders()
            });
            if (!res.ok) throw new Error('Não foi possível excluir o plano.');
            Swal.fire('Removido', 'Plano preventivo excluído com sucesso.', 'success');
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    };

    // ==============================================================================
    // GESTÃO COMPLETA DE ORDEM DE SERVIÇO (MODAL OS COM 4 ABAS)
    // ==============================================================================
    window.abrirModalOS = async function(id = null, veiculoId = null, planoId = null) {
        osModalAtualId = id;
        ativarSubtabOS('subtab-os-dados');
        const form = document.getElementById('form-os');
        if (form) form.reset();

        document.getElementById('os-id').value = id || '';
        const tit = document.getElementById('modal-os-titulo');
        const sub = document.getElementById('modal-os-subtitulo');
        const transCont = document.getElementById('container-transicoes-os');

        // Botões de Transição
        const btnAprovar = document.getElementById('btn-aprovar-os');
        const btnExec = document.getElementById('btn-iniciar-execucao-os');
        const btnConcluir = document.getElementById('btn-concluir-os');
        const btnCancelar = document.getElementById('btn-cancelar-os');

        if (btnAprovar) btnAprovar.style.display = 'none';
        if (btnExec) btnExec.style.display = 'none';
        if (btnConcluir) btnConcluir.style.display = 'none';
        if (btnCancelar) btnCancelar.style.display = 'none';

        if (!id) {
            if (tit) tit.textContent = 'Nova Ordem de Serviço';
            if (sub) sub.textContent = 'Abertura de OS preventiva, corretiva ou sinistro';
            document.getElementById('os-numero').value = 'Gerado ao Salvar';
            document.getElementById('os-status').value = 'Aberta';

            if (veiculoId) {
                document.getElementById('os-veiculo').value = veiculoId;
                popularPlanosNoSelectOS(veiculoId, planoId);
                const vObj = veiculosFrotaCache.find(x => x.id === parseInt(veiculoId, 10));
                if (vObj && vObj.odometro_atual_km !== undefined) {
                    document.getElementById('os-odometro-entrada').value = vObj.odometro_atual_km;
                }
            }
            if (planoId) {
                document.getElementById('os-tipo').value = 'Preventiva';
                document.getElementById('os-origem').value = 'Plano';
                const pObj = planosManutencaoCache.find(x => x.id === parseInt(planoId, 10));
                if (pObj) {
                    document.getElementById('os-descricao').value = `Revisão Preventiva Programada: ${pObj.descricao}`;
                }
            }

            atualizarResumoFinanceiroOS(0, 0, 0);
            renderItensOSTable([]);
            renderAnexosOSTable([]);
            renderTimelineOS([]);

            modalOS.classList.add('active');
        } else {
            if (tit) tit.textContent = 'Carregando Ordem de Serviço...';
            modalOS.classList.add('active');

            try {
                const res = await fetch(`/logistica/api/ordens-servico/${id}/`, { headers: getAuthHeaders() });
                const os = await res.json();

                if (tit) tit.textContent = `Ordem de Serviço ${os.numero}`;
                if (sub) sub.textContent = `${os.tipo} | ${os.origem} | Status: ${os.status}`;

                document.getElementById('os-numero').value = os.numero || '';
                document.getElementById('os-veiculo').value = os.veiculo || '';
                popularPlanosNoSelectOS(os.veiculo, os.plano);
                
                document.getElementById('os-tipo').value = os.tipo || 'Preventiva';
                document.getElementById('os-origem').value = os.origem || 'Manual';
                document.getElementById('os-plano').value = os.plano || '';
                document.getElementById('os-prioridade').value = os.prioridade || 'Normal';
                document.getElementById('os-status').value = os.status || 'Aberta';
                document.getElementById('os-imobiliza-veiculo').checked = !!os.imobiliza_veiculo;

                document.getElementById('os-descricao').value = os.descricao_problema || '';
                document.getElementById('os-diagnostico').value = os.diagnostico || '';
                document.getElementById('os-fornecedor').value = os.fornecedor || '';
                document.getElementById('os-odometro-entrada').value = os.odometro_entrada || '';
                document.getElementById('os-odometro-saida').value = os.odometro_saida || '';
                document.getElementById('os-data-prevista').value = os.data_prevista ? os.data_prevista.slice(0, 10) : '';
                document.getElementById('os-garantia-ate').value = os.garantia_ate ? os.garantia_ate.slice(0, 10) : '';
                document.getElementById('os-custo-terceiros').value = os.custo_terceiros || '0.00';

                atualizarResumoFinanceiroOS(os.custo_pecas, os.custo_mao_de_obra, os.custo_terceiros);
                renderItensOSTable(os.itens || []);
                renderAnexosOSTable(os.anexos || []);
                renderTimelineOS(os);

                // Configura botões de transição conforme estado
                if (['Aberta', 'Orçada'].includes(os.status)) {
                    if (btnAprovar) btnAprovar.style.display = 'inline-block';
                    if (btnCancelar) btnCancelar.style.display = 'inline-block';
                } else if (os.status === 'Aprovada') {
                    if (btnExec) btnExec.style.display = 'inline-block';
                    if (btnCancelar) btnCancelar.style.display = 'inline-block';
                } else if (os.status === 'Em Execução') {
                    if (btnConcluir) btnConcluir.style.display = 'inline-block';
                    if (btnCancelar) btnCancelar.style.display = 'inline-block';
                }

            } catch (err) {
                Swal.fire('Erro', 'Não foi possível carregar a Ordem de Serviço selecionada.', 'error');
                fecharModalOS();
            }
        }
    };

    function atualizarResumoFinanceiroOS(pecas, mo, terc) {
        const valP = parseFloat(pecas) || 0;
        const valM = parseFloat(mo) || 0;
        const valT = parseFloat(terc) || 0;
        const tot = valP + valM + valT;

        const elP = document.getElementById('os-resumo-pecas');
        const elM = document.getElementById('os-resumo-mo');
        const elT = document.getElementById('os-resumo-terceiros');
        const elTot = document.getElementById('os-resumo-total');

        if (elP) elP.textContent = formatCurrency(valP);
        if (elM) elM.textContent = formatCurrency(valM);
        if (elT) elT.textContent = formatCurrency(valT);
        if (elTot) elTot.textContent = formatCurrency(tot);
    }

    function renderItensOSTable(itens) {
        const tbody = document.getElementById('tbody-itens-os');
        const count = document.getElementById('count-itens-os');
        if (count) count.textContent = itens.length;
        if (!tbody) return;

        tbody.innerHTML = '';
        if (itens.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:18px; color:var(--color-text-muted);">Nenhum item adicionado a esta OS.</td></tr>';
            return;
        }

        itens.forEach(it => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><span class="maint-badge-tipo ${it.tipo === 'Peça' ? 'tipo-preventiva' : 'tipo-corretiva'}">${it.tipo}</span></td>
                <td><strong>${it.descricao}</strong></td>
                <td style="text-align:right;">${it.quantidade}</td>
                <td style="text-align:right;">${formatCurrency(it.valor_unitario)}</td>
                <td style="text-align:right; font-weight:700;">${formatCurrency(it.valor_total)}</td>
                <td>${it.garantia_dias ? it.garantia_dias + ' dias' : '-'}</td>
                <td style="text-align:right;">
                    <button class="btn-outline" style="padding:2px 6px; font-size:11px; color:var(--color-danger);" onclick="removerItemOS(${it.id})">🗑️</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    function renderAnexosOSTable(anexos) {
        const tbody = document.getElementById('tbody-anexos-os');
        const count = document.getElementById('count-anexos-os');
        if (count) count.textContent = anexos.length;
        if (!tbody) return;

        tbody.innerHTML = '';
        if (anexos.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:18px; color:var(--color-text-muted);">Nenhum anexo digitalizado nesta OS.</td></tr>';
            return;
        }

        anexos.forEach(a => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${formatDate(a.criado_em)}</td>
                <td><strong>${a.tipo}</strong></td>
                <td>${a.descricao || '-'}</td>
                <td>${a.enviado_por_nome || 'Operador'}</td>
                <td style="text-align:right;">
                    <a href="/logistica/api/manutencao/os-anexo/${a.id}/download/" target="_blank" class="btn-outline" style="padding:4px 8px; font-size:12px; text-decoration:none;">📄 Baixar / Ver</a>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    function renderTimelineOS(os) {
        const cont = document.getElementById('container-timeline-os');
        if (!cont) return;

        cont.innerHTML = `
            <div class="os-timeline-item">
                <div class="os-timeline-marker success"></div>
                <div class="os-timeline-content">
                    <h5>Abertura da OS</h5>
                    <p>Registrada em <strong>${os.data_abertura ? formatDate(os.data_abertura) : '-'}</strong> por ${os.criado_por_nome || 'Sistema'}. Origem: <strong>${os.origem || 'Manual'}</strong>.</p>
                </div>
            </div>
            ${os.aprovado_em ? `
            <div class="os-timeline-item">
                <div class="os-timeline-marker primary"></div>
                <div class="os-timeline-content">
                    <h5>Ordem Aprovada para Serviço</h5>
                    <p>Aprovada em <strong>${formatDate(os.aprovado_em)}</strong> por ${os.aprovado_por_nome || 'Gestor'}.</p>
                </div>
            </div>
            ` : ''}
            ${os.data_entrada ? `
            <div class="os-timeline-item">
                <div class="os-timeline-marker warning"></div>
                <div class="os-timeline-content">
                    <h5>Entrada na Oficina / Em Execução</h5>
                    <p>Início dos reparos em <strong>${formatDate(os.data_entrada)}</strong>. Odômetro entrada: <strong>${os.odometro_entrada || '-'} km</strong>.</p>
                </div>
            </div>
            ` : ''}
            ${os.data_conclusao ? `
            <div class="os-timeline-item">
                <div class="os-timeline-marker success"></div>
                <div class="os-timeline-content">
                    <h5>Conclusão da OS & Liberação Operacional</h5>
                    <p>Concluída em <strong>${formatDate(os.data_conclusao)}</strong> com odômetro de saída <strong>${os.odometro_saida || '-'} km</strong>. Custo Total: <strong>${formatCurrency(os.custo_total)}</strong>.</p>
                </div>
            </div>
            ` : ''}
            ${os.status === 'Cancelada' ? `
            <div class="os-timeline-item">
                <div class="os-timeline-marker danger"></div>
                <div class="os-timeline-content">
                    <h5>OS Cancelada</h5>
                    <p>${os.observacoes || 'Cancelamento registrado pela gestão.'}</p>
                </div>
            </div>
            ` : ''}
        `;
    }

    // Salvar Dados Gerais da OS
    document.getElementById('form-os')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const osId = document.getElementById('os-id').value;
        const payload = {
            veiculo: parseInt(document.getElementById('os-veiculo').value, 10),
            tipo: document.getElementById('os-tipo').value,
            origem: document.getElementById('os-origem').value,
            plano: document.getElementById('os-plano').value ? parseInt(document.getElementById('os-plano').value, 10) : null,
            prioridade: document.getElementById('os-prioridade').value,
            imobiliza_veiculo: document.getElementById('os-imobiliza-veiculo').checked,
            descricao_problema: document.getElementById('os-descricao').value.trim(),
            diagnostico: document.getElementById('os-diagnostico').value.trim(),
            fornecedor: document.getElementById('os-fornecedor').value ? parseInt(document.getElementById('os-fornecedor').value, 10) : null,
            odometro_entrada: document.getElementById('os-odometro-entrada').value ? parseFloat(document.getElementById('os-odometro-entrada').value) : null,
            odometro_saida: document.getElementById('os-odometro-saida').value ? parseFloat(document.getElementById('os-odometro-saida').value) : null,
            data_prevista: document.getElementById('os-data-prevista').value || null,
            garantia_ate: document.getElementById('os-garantia-ate').value || null,
            custo_terceiros: parseFloat(document.getElementById('os-custo-terceiros').value) || 0
        };

        const url = osId ? `/logistica/api/ordens-servico/${osId}/` : '/logistica/api/ordens-servico/';
        const method = osId ? 'PATCH' : 'POST';

        try {
            const res = await fetch(url, {
                method: method,
                headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            });
            if (!res.ok) {
                const errData = await res.json();
                throw new Error(JSON.stringify(errData));
            }
            const data = await res.json();
            Swal.fire('Sucesso!', `Ordem de Serviço ${data.numero || ''} salva com sucesso.`, 'success');
            fecharModalOS();
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro ao Salvar OS', err.message, 'error');
        }
    });

    // Ações de Transição de Status
    document.getElementById('btn-aprovar-os')?.addEventListener('click', async () => {
        if (!osModalAtualId) return;
        try {
            const res = await fetch(`/logistica/api/ordens-servico/${osModalAtualId}/aprovar/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao aprovar OS.');
            Swal.fire('OS Aprovada!', 'Ordem de serviço aprovada para execução de oficina.', 'success');
            abrirModalOS(osModalAtualId);
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    document.getElementById('btn-iniciar-execucao-os')?.addEventListener('click', async () => {
        if (!osModalAtualId) return;
        try {
            const res = await fetch(`/logistica/api/ordens-servico/${osModalAtualId}/iniciar-execucao/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao iniciar execução.');
            Swal.fire('Em Execução!', 'OS colocada em manutenção ativa.', 'success');
            abrirModalOS(osModalAtualId);
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    document.getElementById('btn-concluir-os')?.addEventListener('click', async () => {
        if (!osModalAtualId) return;

        const odoEntrada = parseFloat(document.getElementById('os-odometro-entrada')?.value) || 0;
        const odoSugerido = odoEntrada > 0 ? odoEntrada + 10 : 0;

        const { value: formValues } = await Swal.fire({
            title: 'Concluir Ordem de Serviço',
            html: `
                <div style="text-align:left; font-size:0.9rem;">
                    <div style="margin-bottom:12px;">
                        <label style="display:block; font-weight:700; margin-bottom:4px;">Odômetro de Saída (km) *</label>
                        <input id="swal-odo-saida" type="number" step="0.1" class="swal2-input" style="width:100%; margin:0;" value="${odoSugerido}">
                    </div>
                    <div style="margin-bottom:12px;">
                        <label style="display:block; font-weight:700; margin-bottom:4px;">Parecer / Diagnóstico Técnico</label>
                        <textarea id="swal-diagnostico" class="swal2-textarea" style="width:100%; margin:0; height:80px;" placeholder="Descreva os serviços concluídos, testes executados..."></textarea>
                    </div>
                </div>
            `,
            focusConfirm: false,
            showCancelButton: true,
            confirmButtonText: '🏁 Finalizar e Homologar',
            cancelButtonText: 'Cancelar',
            preConfirm: () => {
                const odo = document.getElementById('swal-odo-saida').value;
                if (!odo || parseFloat(odo) <= 0) {
                    Swal.showValidationMessage('Informe o odômetro de saída válido.');
                    return false;
                }
                return {
                    odometro_saida: parseFloat(odo),
                    diagnostico: document.getElementById('swal-diagnostico').value
                };
            }
        });

        if (!formValues) return;

        try {
            const res = await fetch(`/logistica/api/ordens-servico/${osModalAtualId}/concluir/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify(formValues)
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao concluir OS.');

            Swal.fire('OS Concluída!', 'Manutenção finalizada com sucesso. Veículo liberado para operações e planos preventivos recalculados.', 'success');
            fecharModalOS();
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro ao Concluir OS', err.message, 'error');
        }
    });

    document.getElementById('btn-cancelar-os')?.addEventListener('click', async () => {
        if (!osModalAtualId) return;

        const { value: motivo } = await Swal.fire({
            title: 'Cancelar Ordem de Serviço?',
            input: 'textarea',
            inputLabel: 'Motivo do Cancelamento *',
            inputPlaceholder: 'Informe o motivo técnico ou operacional...',
            showCancelButton: true,
            confirmButtonText: 'Confirmar Cancelamento',
            cancelButtonText: 'Voltar',
            inputValidator: (value) => {
                if (!value || !value.trim()) {
                    return 'É obrigatório informar o motivo do cancelamento.';
                }
            }
        });

        if (!motivo) return;

        try {
            const res = await fetch(`/logistica/api/ordens-servico/${osModalAtualId}/cancelar/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({ motivo: motivo.trim() })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao cancelar OS.');

            Swal.fire('OS Cancelada', 'Ordem de serviço cancelada com sucesso.', 'info');
            fecharModalOS();
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro ao Cancelar', err.message, 'error');
        }
    });

    // Inclusão de Itens na OS
    document.getElementById('btn-adicionar-item-os')?.addEventListener('click', async () => {
        if (!osModalAtualId) {
            Swal.fire('Aviso', 'Salve a OS antes de incluir peças ou serviços.', 'warning');
            return;
        }

        const tipo = document.getElementById('novo-item-tipo').value;
        const desc = document.getElementById('novo-item-desc').value.trim();
        const qtd = parseFloat(document.getElementById('novo-item-qtd').value) || 1;
        const valor = parseFloat(document.getElementById('novo-item-valor').value);
        const garantia = parseInt(document.getElementById('novo-item-garantia').value, 10) || 90;

        if (!desc) {
            Swal.fire('Validação', 'Informe a descrição do item.', 'warning');
            return;
        }
        if (isNaN(valor) || valor < 0) {
            Swal.fire('Validação', 'Informe um valor unitário válido.', 'warning');
            return;
        }

        try {
            const res = await fetch(`/logistica/api/ordens-servico/${osModalAtualId}/adicionar-item/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    tipo: tipo,
                    descricao: desc,
                    quantidade: qtd,
                    valor_unitario: valor,
                    garantia_dias: garantia
                })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(JSON.stringify(data));

            document.getElementById('novo-item-desc').value = '';
            document.getElementById('novo-item-valor').value = '';

            atualizarResumoFinanceiroOS(data.custo_pecas, data.custo_mao_de_obra, data.custo_terceiros);
            renderItensOSTable(data.itens || []);
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro ao Incluir Item', err.message, 'error');
        }
    });

    window.removerItemOS = async function(itemId) {
        if (!osModalAtualId) return;
        const confirm = await Swal.fire({
            title: 'Remover Item?',
            text: 'Deseja excluir este item da Ordem de Serviço?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Sim, remover',
            cancelButtonText: 'Cancelar'
        });
        if (!confirm.isConfirmed) return;

        try {
            const res = await fetch(`/logistica/api/os-itens/${itemId}/`, {
                method: 'DELETE',
                headers: getAuthHeaders()
            });
            if (!res.ok) throw new Error('Não foi possível remover o item.');
            abrirModalOS(osModalAtualId);
            loadManutencao();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    };

    // Upload de Anexo na OS
    document.getElementById('btn-upload-anexo-os')?.addEventListener('click', async () => {
        if (!osModalAtualId) {
            Swal.fire('Aviso', 'Salve a OS antes de anexar documentos ou fotos.', 'warning');
            return;
        }

        const fileInput = document.getElementById('novo-anexo-file');
        if (!fileInput.files || fileInput.files.length === 0) {
            Swal.fire('Aviso', 'Selecione um arquivo para enviar.', 'warning');
            return;
        }

        const formData = new FormData();
        formData.append('arquivo', fileInput.files[0]);
        formData.append('tipo', document.getElementById('novo-anexo-tipo').value);
        formData.append('descricao', document.getElementById('novo-anexo-desc').value.trim());

        const btnEnv = document.getElementById('btn-upload-anexo-os');
        if (btnEnv) {
            btnEnv.disabled = true;
            btnEnv.innerHTML = 'Enviando...';
        }

        try {
            const res = await fetch(`/logistica/api/ordens-servico/${osModalAtualId}/adicionar-anexo/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken') || '',
                    'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
                    'X-Tenant-ID': (document.querySelector('meta[name="active-tenant-id"]')?.content || '')
                },
                body: formData
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao anexar arquivo.');

            fileInput.value = '';
            document.getElementById('novo-anexo-desc').value = '';
            Swal.fire('Anexo Enviado!', 'Documento/foto adicionado à OS.', 'success');
            abrirModalOS(osModalAtualId);
        } catch (err) {
            Swal.fire('Erro no Upload', err.message, 'error');
        } finally {
            if (btnEnv) {
                btnEnv.disabled = false;
                btnEnv.innerHTML = '📤 Enviar';
            }
        }
    });

    // Exposição Global de Manutenção
    window.loadManutencao = loadManutencao;

    // Exposição Global
    window.loadCombustivel = loadCombustivel;

    // ==============================================================================
    // 8. SEGUROS E SINISTROS (SPRINT L5)
    // ==============================================================================
    let sinistroModalAtualId = null;
    let cacheApolices = [];
    let cacheSinistros = [];
    let cacheVeiculosSeguros = [];

    // Sub-abas internas de Seguros & Sinistros (Segmented Pills)
    const segSubtabBtns = document.querySelectorAll('.seg-subtab-btn');
    const segSubtabPanes = document.querySelectorAll('.seg-subtab-pane');
    segSubtabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            segSubtabBtns.forEach(b => b.classList.remove('active'));
            segSubtabPanes.forEach(p => {
                p.classList.remove('active');
                p.style.display = 'none';
            });
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-seg-subtab');
            const pane = document.getElementById(targetId);
            if (pane) {
                pane.classList.add('active');
                pane.style.display = 'block';
            }
        });
    });

    // Sub-abas do Modal de Detalhes do Sinistro
    const sinModalSubtabBtns = document.querySelectorAll('#modal-sinistro-detalhe .modal-subtab-btn');
    const sinModalSubtabPanes = document.querySelectorAll('#modal-sinistro-detalhe .modal-subtab-pane');
    sinModalSubtabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            sinModalSubtabBtns.forEach(b => b.classList.remove('active'));
            sinModalSubtabPanes.forEach(p => {
                p.classList.remove('active');
                p.style.display = 'none';
            });
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-sin-subtab');
            const pane = document.getElementById(targetId);
            if (pane) {
                pane.classList.add('active');
                pane.style.display = 'block';
            }
        });
    });

    // Toggle entre Kanban e Lista de Sinistros
    document.getElementById('btn-toggle-sinistro-kanban')?.addEventListener('click', () => {
        document.getElementById('sinistro-kanban-view').style.display = 'block';
        document.getElementById('sinistro-lista-view').style.display = 'none';
        document.getElementById('btn-toggle-sinistro-kanban').style.fontWeight = '700';
        document.getElementById('btn-toggle-sinistro-lista').style.fontWeight = '500';
    });
    document.getElementById('btn-toggle-sinistro-lista')?.addEventListener('click', () => {
        document.getElementById('sinistro-kanban-view').style.display = 'none';
        document.getElementById('sinistro-lista-view').style.display = 'block';
        document.getElementById('btn-toggle-sinistro-kanban').style.fontWeight = '500';
        document.getElementById('btn-toggle-sinistro-lista').style.fontWeight = '700';
    });

    // Função de Preenchimento da Aba de Seguros na Ficha do Veículo
    function carregarSegurosVeiculoAba(data) {
        const statusBadge = document.getElementById('veiculo-seguro-status-badge');
        const grid = document.getElementById('veiculo-seguro-dados-grid');
        const cobsResumo = document.getElementById('veiculo-seguro-coberturas-resumo');
        const tbodySin = document.getElementById('tbody-veiculo-sinistros-historico');

        const ap = data.apolice_vigente_info;
        if (ap) {
            if (statusBadge) {
                statusBadge.className = `semaforo-pill semaforo-${ap.semaforo_vigencia || 'green'}`;
                statusBadge.textContent = `${ap.status_vigencia} (${ap.dias_para_vencimento}d)`;
            }
            if (grid) {
                grid.innerHTML = `
                    <div><strong>Seguradora:</strong> ${ap.seguradora || '-'}</div>
                    <div><strong>Nº Apólice:</strong> ${ap.numero_apolice || '-'}</div>
                    <div><strong>Tipo:</strong> ${ap.tipo || '-'}</div>
                    <div><strong>Vigência Até:</strong> ${ap.vigencia_fim || '-'}</div>
                    <div><strong>Assistência 24h:</strong> ${ap.telefone_assistencia_24h || '-'}</div>
                    <div><strong>Valor Segurado:</strong> ${ap.valor_segurado ? formatCurrency(ap.valor_segurado) : '100% FIPE'} (${ap.tipo_valor})</div>
                `;
            }
            if (cobsResumo) {
                if (ap.coberturas && ap.coberturas.length > 0) {
                    const cobHtml = ap.coberturas.map(c => 
                        `<span style="display:inline-block; margin-right:12px; margin-bottom:4px; background:var(--color-surface); padding:3px 8px; border-radius:6px; border:1px solid var(--color-border);">
                            <strong>${c.cobertura}:</strong> LMI: ${c.limite ? formatCurrency(c.limite) : 'N/D'} | Franquia: ${formatCurrency(c.franquia_valor || 0)}
                        </span>`
                    ).join('');
                    cobsResumo.innerHTML = `<strong>Coberturas e Franquias Contratadas:</strong><div style="margin-top:6px;">${cobHtml}</div>`;
                } else {
                    cobsResumo.innerHTML = `<em>Nenhuma cobertura detalhada cadastrada para esta apólice.</em>`;
                }
            }
        } else {
            if (statusBadge) {
                statusBadge.className = 'semaforo-pill semaforo-red';
                statusBadge.textContent = 'Sem Apólice Ativa';
            }
            if (grid) {
                grid.innerHTML = `<div style="grid-column: 1 / -1; color:#ef4444;">⚠️ Este veículo não possui apólice de seguro vigente vinculada.</div>`;
            }
            if (cobsResumo) cobsResumo.innerHTML = '';
        }

        // Histórico de Sinistros Anteriores
        if (tbodySin) {
            const hist = data.sinistros_recentes_resumo || [];
            if (hist.length === 0) {
                tbodySin.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--color-text-muted);">Nenhum sinistro registrado para este veículo.</td></tr>`;
            } else {
                tbodySin.innerHTML = hist.map(s => `
                    <tr>
                        <td style="font-weight:700; font-family:'JetBrains Mono', monospace;">${s.numero}</td>
                        <td>${s.tipo}</td>
                        <td>${s.data_hora}</td>
                        <td><span class="badge ${s.status === 'Encerrado' ? 'badge-success' : 'badge-warning'}">${s.status}</span></td>
                        <td style="text-align:center;">${s.houve_vitimas ? '🚨 <strong style="color:#ef4444;">SIM</strong>' : 'Não'}</td>
                        <td style="text-align:right; font-weight:700; color:#ef4444;">${formatCurrency(s.prejuizo_liquido)}</td>
                    </tr>
                `).join('');
            }
        }
    }

    // Carregamento Geral de Seguros & Sinistros
    async function loadSegurosESinistros() {
        await Promise.all([
            carregarIndicadoresSeguros(),
            carregarApolices(),
            carregarSinistros(),
            carregarSelectsSeguros()
        ]);
    }

    // 1. Indicadores de Sinistralidade e KPIs
    async function carregarIndicadoresSeguros() {
        const dtInicio = document.getElementById('indicadores-seg-inicio')?.value || '';
        const dtFim = document.getElementById('indicadores-seg-fim')?.value || '';
        let url = '/logistica/api/sinistros/indicadores/';
        const params = new URLSearchParams();
        if (dtInicio) params.append('data_inicio', dtInicio);
        if (dtFim) params.append('data_fim', dtFim);
        if (params.toString()) url += `?${params.toString()}`;

        try {
            const res = await fetch(url, { headers: getAuthHeaders(), credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            // Atualiza KPIs Top Cards
            document.getElementById('seg-kpi-total-sinistros').textContent = data.total_sinistros || 0;
            const abertos = (data.sinistros_por_status?.['Registrado'] || 0) + (data.sinistros_por_status?.['Em Análise'] || 0) + (data.sinistros_por_status?.['Em Vistoria'] || 0) + (data.sinistros_por_status?.['Comunicado à Seguradora'] || 0);
            document.getElementById('seg-kpi-sinistros-abertos').textContent = `${abertos} em andamento`;

            const urgentes = data.alertas_comunicacao?.length || 0;
            const expirados = data.alertas_comunicacao?.filter(a => a.expirado).length || 0;
            document.getElementById('seg-kpi-prazos-urgentes').textContent = urgentes;
            document.getElementById('seg-kpi-prazos-expirados').textContent = `${expirados} estourado(s)`;

            document.getElementById('seg-kpi-taxa-100k').textContent = data.taxa_sinistralidade_100k_km || '0.00';
            document.getElementById('seg-kpi-km-total').textContent = `${Number(data.km_total_rodados || 0).toLocaleString('pt-BR')} km rodados`;

            document.getElementById('seg-kpi-prejuizo-liquido').textContent = formatCurrency(data.total_prejuizo_liquido || 0);
            document.getElementById('seg-kpi-loss-ratio').textContent = `Loss Ratio: ${data.loss_ratio_percentual || 0}%`;

            // Aba Indicadores Detalhada
            document.getElementById('ind-sinistralidade-taxa').textContent = data.taxa_sinistralidade_100k_km || '0.00';
            document.getElementById('ind-loss-ratio-val').textContent = `${data.loss_ratio_percentual || 0}%`;
            document.getElementById('ind-tempo-resolucao').textContent = data.tempo_medio_resolucao_dias || '0.0';

            // Gráfico/Breakdown por Tipo
            const boxTipo = document.getElementById('container-sinistros-por-tipo');
            if (boxTipo) {
                const tipos = data.sinistros_por_tipo || {};
                const keys = Object.keys(tipos);
                if (keys.length === 0) {
                    boxTipo.innerHTML = `<em style="color:var(--color-text-muted);">Nenhum sinistro registrado no período.</em>`;
                } else {
                    boxTipo.innerHTML = keys.map(k => `
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <span>${k}</span>
                            <span style="font-weight:700; background:var(--color-hover); padding:2px 8px; border-radius:10px;">${tipos[k]}</span>
                        </div>
                    `).join('');
                }
            }

            // Balanço Financeiro
            const boxFin = document.getElementById('container-balanco-financeiro');
            if (boxFin) {
                boxFin.innerHTML = `
                    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                        <span>Prejuízo Bruto Estimado:</span>
                        <strong style="color:#ef4444;">${formatCurrency(data.total_prejuizo_estimado || 0)}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                        <span>Franquias Pagas:</span>
                        <strong style="color:#f59e0b;">${formatCurrency(data.total_franquia || 0)}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                        <span>Indenizações Recebidas:</span>
                        <strong style="color:#10b981;">${formatCurrency(data.total_indenizacoes || 0)}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-top:8px; border-top:1px dashed var(--color-border); padding-top:6px; font-weight:700;">
                        <span>Prejuízo Líquido Final:</span>
                        <span style="color:#dc2626;">${formatCurrency(data.total_prejuizo_liquido || 0)}</span>
                    </div>
                `;
            }
        } catch (err) {
            console.error('Erro ao carregar indicadores de sinistralidade:', err);
        }
    }

    // 2. Apólices & Coberturas
    async function carregarApolices() {
        const tbody = document.getElementById('tbody-apolices-lista');
        const alertContainer = document.getElementById('seg-alertas-renovacao-container');
        try {
            const [resApolices, resAlertas] = await Promise.all([
                fetch('/logistica/api/apolices/?sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' }),
                fetch('/logistica/api/apolices/alertas-renovacao/', { headers: getAuthHeaders(), credentials: 'same-origin' })
            ]);
            const rawApolices = await resApolices.json();
            const rawAlertas = await resAlertas.json();

            cacheApolices = extrairListaDRF(rawApolices);
            const alertas = rawAlertas.alertas || [];

            document.getElementById('seg-kpi-apolices-ativas').textContent = cacheApolices.filter(a => a.ativa).length;
            document.getElementById('seg-kpi-apolices-vencendo').textContent = `${alertas.length} a vencer em 60 dias`;
            document.getElementById('seg-count-apolices-pill').textContent = cacheApolices.length;

            // Renderiza Alertas de Renovação em Destaque
            if (alertContainer) {
                if (alertas.length === 0) {
                    alertContainer.innerHTML = '';
                } else {
                    alertContainer.innerHTML = `
                        <div style="background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:12px 16px;">
                            <div style="font-weight:700; color:#92400e; margin-bottom:6px; font-size:0.9rem;">
                                ⚠️ ${alertas.length} Apólice(s) com Renovação Próxima (Vencendo em até 60 dias):
                            </div>
                            <div style="display:flex; gap:10px; flex-wrap:wrap;">
                                ${alertas.map(al => `
                                    <div style="background:#ffffff; border:1px solid #fcd34d; border-radius:6px; padding:6px 12px; font-size:0.82rem;">
                                        <strong>${al.seguradora}</strong> (${al.numero_apolice}) - 
                                        <span class="semaforo-pill semaforo-${al.semaforo}">${al.status_vigencia} (${al.dias_para_vencimento}d)</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    `;
                }
            }

            // Renderiza Tabela de Apólices
            if (!tbody) return;
            if (cacheApolices.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--color-text-muted);">Nenhuma apólice cadastrada. Clique em "+ Nova Apólice" para registrar.</td></tr>`;
                return;
            }

            tbody.innerHTML = cacheApolices.map(ap => {
                const veicsCount = ap.veiculos_segurados?.length || 0;
                const cobsCount = ap.coberturas?.length || 0;
                const semClass = ap.semaforo_vigencia || 'green';
                const statusTxt = `${ap.status_vigencia || 'Vigente'} (${ap.dias_para_vencimento}d)`;

                let badgePerigoso = '⚠️ Não verificado';
                if (ap.cobre_produto_perigoso === 'Sim') badgePerigoso = '✅ Sim (GLP/Gás)';
                else if (ap.cobre_produto_perigoso === 'Não') badgePerigoso = '❌ Não Cobre';

                return `
                    <tr>
                        <td>
                            <div style="font-weight:700; color:var(--color-text);">${ap.seguradora}</div>
                            <div style="font-size:0.78rem; font-family:'JetBrains Mono', monospace; color:var(--color-text-muted);">${ap.numero_apolice}</div>
                        </td>
                        <td><span class="badge badge-info">${ap.tipo}</span></td>
                        <td>
                            <span class="semaforo-pill semaforo-${semClass}">${statusTxt}</span>
                            <div style="font-size:0.75rem; color:var(--color-text-muted); margin-top:2px;">Até ${ap.vigencia_fim}</div>
                        </td>
                        <td style="text-align:center; font-size:0.82rem;">
                            <span style="font-weight:600; color:${ap.cobre_produto_perigoso === 'Sim' ? '#059669' : (ap.cobre_produto_perigoso === 'Não' ? '#dc2626' : '#d97706')};">
                                ${badgePerigoso}
                            </span>
                        </td>
                        <td>
                            <button type="button" class="btn-outline" onclick="abrirModalVincularVeiculo(${ap.id}, '${ap.seguradora} - ${ap.numero_apolice}')" style="padding:2px 8px; font-size:0.75rem;">
                                🚚 ${veicsCount} Veículo(s)
                            </button>
                        </td>
                        <td>
                            <span style="font-size:0.82rem; color:var(--color-text-muted);">${cobsCount} cobertura(s)</span>
                        </td>
                        <td style="text-align:right; font-weight:700;">${formatCurrency(ap.premio_total || 0)}</td>
                        <td style="text-align:right; white-space:nowrap;">
                            ${ap.arquivo_pdf_url ? `<a href="${ap.arquivo_pdf_url}" target="_blank" class="btn-secondary" style="padding:3px 8px; font-size:0.75rem;" title="Baixar PDF">📄 PDF</a>` : ''}
                            <button class="btn-secondary" onclick="editarApolice(${ap.id})" style="padding:3px 8px; font-size:0.75rem;">✏️</button>
                            <button class="btn-secondary" onclick="excluirApolice(${ap.id})" style="padding:3px 8px; font-size:0.75rem; color:#ef4444;">🗑️</button>
                        </td>
                    </tr>
                `;
            }).join('');
        } catch (err) {
            console.error('Erro ao carregar apólices:', err);
            if (tbody) tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#ef4444;">Erro ao carregar apólices: ${err.message}</td></tr>`;
        }
    }

    // 3. Quadro de Sinistros (Kanban & Lista)
    async function carregarSinistros() {
        const veiculoId = document.getElementById('filtro-sinistro-veiculo')?.value || '';
        const tipoSin = document.getElementById('filtro-sinistro-tipo')?.value || '';

        let url = '/logistica/api/sinistros/?sem_paginacao=1';
        if (veiculoId) url += `&veiculo=${veiculoId}`;
        if (tipoSin) url += `&tipo=${encodeURIComponent(tipoSin)}`;

        try {
            const res = await fetch(url, { headers: getAuthHeaders(), credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const raw = await res.json();
            cacheSinistros = extrairListaDRF(raw);

            document.getElementById('seg-count-sinistros-pill').textContent = cacheSinistros.length;

            // Agrupamento por colunas do Kanban
            const cols = {
                rascunho: document.getElementById('sin-col-rascunho'),
                registrado: document.getElementById('sin-col-registrado'),
                comunicado: document.getElementById('sin-col-comunicado'),
                analise: document.getElementById('sin-col-analise'),
                concluido: document.getElementById('sin-col-concluido')
            };

            const counts = { rascunho: 0, registrado: 0, comunicado: 0, analise: 0, concluido: 0 };
            Object.values(cols).forEach(c => { if (c) c.innerHTML = ''; });

            // Tabela View
            const tbodyLista = document.getElementById('tbody-sinistros-lista');
            if (tbodyLista) tbodyLista.innerHTML = '';

            cacheSinistros.forEach(s => {
                const st = s.status;
                let targetColKey = 'registrado';
                if (st === 'Rascunho') targetColKey = 'rascunho';
                else if (st === 'Comunicado à Seguradora') targetColKey = 'comunicado';
                else if (st === 'Em Análise' || st === 'Em Vistoria') targetColKey = 'analise';
                else if (st === 'Aprovado' || st === 'Negado' || st === 'Indenizado' || st === 'Encerrado') targetColKey = 'concluido';

                counts[targetColKey]++;

                // Badge de Prazo
                let prazoBadge = '';
                if (s.prazo_comunicacao_expirado) {
                    prazoBadge = `<span class="badge-prazo-expirado">Prazo Expirado</span>`;
                } else if (s.prazo_comunicacao_urgente) {
                    prazoBadge = `<span class="badge-prazo-urgente">Aviso Urgente</span>`;
                }

                // Render Card Kanban
                const card = document.createElement('div');
                card.className = `sinistro-kanban-card ${s.houve_vitimas ? 'com-vitimas' : 'sem-vitimas'}`;
                card.onclick = () => abrirModalSinistroDetalhe(s.id);
                card.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="font-weight:700; font-family:'JetBrains Mono', monospace; font-size:0.85rem; color:var(--color-primary);">${s.numero}</span>
                        ${s.houve_vitimas ? '<span style="background:#ef4444; color:#fff; font-size:0.7rem; font-weight:800; padding:1px 6px; border-radius:4px;">🚨 VÍTIMAS</span>' : ''}
                    </div>
                    <div style="font-weight:700; font-size:0.86rem; color:var(--color-text); margin-bottom:4px;">${s.tipo}</div>
                    <div style="font-size:0.78rem; color:var(--color-text-muted); margin-bottom:6px;">
                        🚚 ${s.veiculo_placa || 'Sem veículo'} | 👤 ${s.motorista_nome || 'N/D'}
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem; margin-top:8px; border-top:1px dashed var(--color-border); padding-top:6px;">
                        <span style="color:var(--color-text-muted);">${formatDateTime(s.data_hora)}</span>
                        ${prazoBadge}
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px; font-size:0.78rem;">
                        <span style="color:var(--color-text-muted);">Prejuízo Líq.:</span>
                        <strong style="color:#ef4444;">${formatCurrency(s.prejuizo_liquido || 0)}</strong>
                    </div>
                `;
                cols[targetColKey]?.appendChild(card);

                // Render Linha na Lista
                if (tbodyLista) {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td style="font-weight:700; font-family:'JetBrains Mono', monospace;">${s.numero}</td>
                        <td><strong>${s.tipo}</strong></td>
                        <td>${formatDateTime(s.data_hora)}</td>
                        <td>${s.veiculo_placa ? `<strong>${s.veiculo_placa}</strong> (${s.veiculo_modelo || ''})` : 'N/A'}<br><small style="color:var(--color-text-muted);">${s.motorista_nome || ''}</small></td>
                        <td style="text-align:center;">${s.houve_vitimas ? '<span style="color:#ef4444; font-weight:800;">🚨 SIM</span>' : 'Não'}</td>
                        <td>
                            ${s.prazo_limite_comunicacao ? formatDateTime(s.prazo_limite_comunicacao) : '-'}
                            ${prazoBadge ? `<br>${prazoBadge}` : ''}
                        </td>
                        <td style="text-align:center;"><span class="badge ${s.status === 'Encerrado' ? 'badge-success' : 'badge-warning'}">${s.status}</span></td>
                        <td style="text-align:right; font-weight:700; color:#ef4444;">${formatCurrency(s.prejuizo_liquido || 0)}</td>
                        <td style="text-align:center;">${s.os_vinculada_numero ? `<span class="badge badge-info">OS #${s.os_vinculada_numero}</span>` : '-'}</td>
                        <td style="text-align:right;">
                            <button class="btn-primary" onclick="abrirModalSinistroDetalhe(${s.id})" style="padding:3px 9px; font-size:0.75rem;">Detalhes</button>
                        </td>
                    `;
                    tbodyLista.appendChild(tr);
                }
            });

            // Atualiza contadores do Kanban
            document.getElementById('kanban-sin-count-rascunho').textContent = counts.rascunho;
            document.getElementById('kanban-sin-count-registrado').textContent = counts.registrado;
            document.getElementById('kanban-sin-count-comunicado').textContent = counts.comunicado;
            document.getElementById('kanban-sin-count-analise').textContent = counts.analise;
            document.getElementById('kanban-sin-count-concluido').textContent = counts.concluido;

            if (tbodyLista && cacheSinistros.length === 0) {
                tbodyLista.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--color-text-muted);">Nenhum sinistro registrado com os filtros selecionados.</td></tr>`;
            }
        } catch (err) {
            console.error('Erro ao carregar sinistros:', err);
        }
    }

    // 4. Detalhes do Sinistro (Modal com 5 Abas)
    async function abrirModalSinistroDetalhe(id) {
        sinistroModalAtualId = id;
        document.getElementById('sinistro-detalhe-id').value = id;

        try {
            const res = await fetch(`/logistica/api/sinistros/${id}/`, { headers: getAuthHeaders(), credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const s = await res.json();

            // Header & Titulos
            document.getElementById('sinistro-detalhe-titulo').textContent = `Sinistro ${s.numero} (${s.tipo})`;
            document.getElementById('sinistro-detalhe-subtitulo').textContent = `Status: ${s.status} | Data: ${formatDateTime(s.data_hora)}`;

            // Banner Vítimas
            const banVit = document.getElementById('sinistro-detalhe-alerta-vitimas');
            if (banVit) banVit.style.display = s.houve_vitimas ? 'flex' : 'none';

            // Banner Prazo
            const banPrazo = document.getElementById('sinistro-detalhe-alerta-prazo');
            if (banPrazo) banPrazo.style.display = (s.prazo_comunicacao_urgente || s.prazo_comunicacao_expirado) ? 'block' : 'none';

            // Dados Gerais Grid
            const dadosGrid = document.getElementById('sin-dados-grid');
            if (dadosGrid) {
                dadosGrid.innerHTML = `
                    <div><strong>Veículo:</strong> ${s.veiculo_placa ? `${s.veiculo_placa} (${s.veiculo_modelo || ''})` : 'Nenhum'}</div>
                    <div><strong>Motorista:</strong> ${s.motorista_nome || 'N/D'}</div>
                    <div><strong>Entrega / Romaneio:</strong> ${s.entrega_id_display ? `#${s.entrega_id_display}` : 'Rota Livre'}</div>
                    <div><strong>Apólice Acionada:</strong> ${s.apolice_numero ? `${s.apolice_seguradora} (${s.apolice_numero})` : 'Nenhuma'}</div>
                    <div><strong>BO Policial:</strong> ${s.boletim_ocorrencia_numero || 'Não lavrado'}</div>
                    <div><strong>Protocolo Seguradora:</strong> ${s.protocolo_seguradora || 'Pendente'}</div>
                    <div><strong>Prazo Comunicação:</strong> ${s.prazo_limite_comunicacao ? formatDateTime(s.prazo_limite_comunicacao) : '-'}</div>
                    <div><strong>Endereço / Local:</strong> ${s.endereco || 'Não informado'}</div>
                    <div><strong>Coordenadas GPS:</strong> ${s.latitude && s.longitude ? `${s.latitude}, ${s.longitude}` : 'N/D'}</div>
                    <div><strong>Registrado Por:</strong> ${s.criado_por_nome || 'Sistema'}</div>
                `;
            }
            document.getElementById('sin-detalhe-descricao').textContent = s.descricao || 'Sem descrição informada.';

            // Dados de Terceiros (LGPD)
            const tercBox = document.getElementById('sin-detalhe-terceiros');
            if (tercBox) {
                const terc = s.terceiros || {};
                if (terc.acesso_restrito_lgpd) {
                    tercBox.innerHTML = `<span style="color:#d97706;">🔒 ${terc.mensagem || 'Dados protegidos pela LGPD.'}</span>`;
                } else if (Object.keys(terc).length > 0) {
                    tercBox.innerHTML = `
                        <div><strong>Nome / Identificação:</strong> ${terc.nome || terc.descricao || '-'}</div>
                        <div><strong>Telefone de Contato:</strong> ${terc.telefone || '-'}</div>
                        <div><strong>Veículo / Placa:</strong> ${terc.veiculo || terc.placa || '-'}</div>
                        <div><strong>Danos Apontados:</strong> ${terc.danos || '-'}</div>
                    `;
                } else {
                    tercBox.innerHTML = `<em>Nenhum terceiro ou veículo externo envolvido.</em>`;
                }
            }

            // Comparativo FIPE (Perda Total)
            const fipeBox = document.getElementById('sin-detalhe-fipe-box');
            if (fipeBox) {
                const cf = s.comparativo_fipe;
                if (cf) {
                    fipeBox.style.display = 'block';
                    fipeBox.innerHTML = `
                        <div style="font-weight:700; margin-bottom:4px; color:#166534;">📊 Comparativo com Referência FIPE (Perda Total):</div>
                        <div>Valor FIPE do Veículo: <strong>${formatCurrency(cf.valor_referencia_fipe)}</strong> | Indenização: <strong>${formatCurrency(cf.valor_indenizacao)}</strong></div>
                        <div>Divergência: <strong>${formatCurrency(cf.divergencia_reais)} (${cf.divergencia_percentual}%)</strong></div>
                        ${cf.alerta_divergencia_alta ? '<div style="color:#dc2626; font-weight:700; margin-top:4px;">⚠️ ALERTA: Divergência superior a 15% em relação à tabela FIPE de referência.</div>' : ''}
                    `;
                } else {
                    fipeBox.style.display = 'none';
                }
            }

            // Carga Afetada
            const itensCarga = s.itens_carga || [];
            document.getElementById('count-sin-itens-carga').textContent = itensCarga.length;
            const tbodyCarga = document.getElementById('tbody-sin-itens-carga');
            if (tbodyCarga) {
                if (itensCarga.length === 0) {
                    tbodyCarga.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--color-text-muted);">Nenhum produto de carga afetado neste sinistro.</td></tr>`;
                } else {
                    tbodyCarga.innerHTML = itensCarga.map(it => `
                        <tr>
                            <td><strong>${it.produto_nome}</strong></td>
                            <td style="text-align:center;"><span class="badge ${it.categoria === 'Cheio' ? 'badge-primary' : (it.categoria === 'Vazio' ? 'badge-secondary' : 'badge-warning')}">${it.categoria}</span></td>
                            <td style="text-align:center; font-weight:700;">${it.quantidade}</td>
                            <td style="text-align:right;">${formatCurrency(it.valor_unitario)}</td>
                            <td style="text-align:right; font-weight:700; color:#ef4444;">${formatCurrency(it.valor_total)}</td>
                            <td style="text-align:center;">${it.ajuste_estoque_realizado ? '✅ Sim' : '❌ Pendente'}</td>
                        </tr>
                    `).join('');
                }
            }

            // Anexos
            const anexos = s.anexos || [];
            document.getElementById('count-sin-anexos').textContent = anexos.length;
            const tbodyAnexos = document.getElementById('tbody-sin-anexos-lista');
            if (tbodyAnexos) {
                if (anexos.length === 0) {
                    tbodyAnexos.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--color-text-muted);">Nenhum anexo registrado. Envie fotos ou laudos pelo formulário acima.</td></tr>`;
                } else {
                    tbodyAnexos.innerHTML = anexos.map(an => `
                        <tr>
                            <td><span class="badge badge-info">${an.tipo}</span></td>
                            <td>${an.descricao || '-'}</td>
                            <td>${formatDateTime(an.criado_em)}</td>
                            <td>${an.enviado_por_nome || 'Sistema'}</td>
                            <td style="text-align:right;">
                                <a href="${an.arquivo_url}" target="_blank" class="btn-secondary" style="padding:3px 8px; font-size:0.75rem;">Visualizar / Baixar</a>
                            </td>
                        </tr>
                    `).join('');
                }
            }

            // Linha do Tempo Imutável
            const eventos = s.eventos || [];
            document.getElementById('count-sin-eventos').textContent = eventos.length;
            const timelineCont = document.getElementById('sin-timeline-container');
            if (timelineCont) {
                if (eventos.length === 0) {
                    timelineCont.innerHTML = `<em style="color:var(--color-text-muted);">Nenhum evento registrado.</em>`;
                } else {
                    timelineCont.innerHTML = eventos.map(ev => `
                        <div class="timeline-v-item">
                            <div class="timeline-v-badge">📌</div>
                            <div class="timeline-v-content">
                                <div class="timeline-v-header">
                                    <span class="timeline-v-title">${ev.tipo}</span>
                                    <span class="timeline-v-date">${formatDateTime(ev.data_hora)} por ${ev.autor_nome || 'Sistema'}</span>
                                </div>
                                <div class="timeline-v-desc">${ev.descricao}</div>
                                ${ev.status_novo ? `<div style="margin-top:4px; font-size:0.75rem; color:var(--color-primary); font-weight:700;">Status: ${ev.status_anterior ? `${ev.status_anterior} ➔ ` : ''}${ev.status_novo}</div>` : ''}
                            </div>
                        </div>
                    `).join('');
                }
            }

            // Financeiro & OS
            document.getElementById('fin-sin-prejuizo-estimado').textContent = formatCurrency(s.valor_prejuizo_estimado || 0);
            document.getElementById('fin-sin-franquia').textContent = formatCurrency(s.valor_franquia || 0);
            document.getElementById('fin-sin-indenizacao').textContent = formatCurrency(s.valor_indenizacao || 0);
            document.getElementById('fin-sin-prejuizo-liquido').textContent = formatCurrency(s.prejuizo_liquido || 0);

            const osBox = document.getElementById('fin-sin-os-container');
            if (osBox) {
                if (s.os_vinculada) {
                    osBox.innerHTML = `
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <strong>Ordem de Serviço #${s.os_vinculada_numero}</strong>
                                <span class="badge badge-info" style="margin-left:6px;">Vinculada</span>
                            </div>
                            <button type="button" class="btn-secondary" onclick="abrirModalOS(${s.os_vinculada})" style="font-size:0.78rem; padding:4px 8px;">Visualizar OS</button>
                        </div>
                        <div style="margin-top:6px; color:var(--color-text-muted); font-size:0.8rem;">
                            Os custos das peças, serviços e terceiros desta OS integram automaticamente o cálculo de prejuízo deste sinistro.
                        </div>
                    `;
                } else {
                    osBox.innerHTML = `<em>Nenhuma OS corretiva vinculada. Clique no botão acima para abrir e imobilizar o veículo se necessário.</em>`;
                }
            }

            // Seta status no form de transição
            document.getElementById('transicao-sin-status').value = s.status;
            document.getElementById('transicao-sin-protocolo').value = s.protocolo_seguradora || '';
            document.getElementById('transicao-sin-indenizacao').value = s.valor_indenizacao || '';

            // Ativa primeira aba e abre modal
            document.querySelector('#modal-sinistro-detalhe .modal-subtab-btn[data-sin-subtab="subtab-sin-dados"]')?.click();
            document.getElementById('modal-sinistro-detalhe').classList.add('active');
        } catch (err) {
            Swal.fire('Erro', 'Não foi possível carregar os detalhes do sinistro: ' + err.message, 'error');
        }
    }

    // 5. Selects Auxiliares (Veículos, Motoristas, Entregas)
    async function carregarSelectsSeguros() {
        try {
            const [resVeic, resMotoristas, resEntregas] = await Promise.all([
                fetch('/logistica/api/veiculos/?sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' }),
                fetch('/accounts/api/users/?sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' }),
                fetch('/logistica/api/entregas/?sem_paginacao=1', { headers: getAuthHeaders(), credentials: 'same-origin' })
            ]);
            cacheVeiculosSeguros = resVeic.ok ? extrairListaDRF(await resVeic.json()) : [];
            const motoristas = resMotoristas.ok ? extrairListaDRF(await resMotoristas.json()) : [];
            const entregas = resEntregas.ok ? extrairListaDRF(await resEntregas.json()) : [];

            // Filtro de Veículos
            const fVeic = document.getElementById('filtro-sinistro-veiculo');
            if (fVeic) {
                fVeic.innerHTML = `<option value="">Todos os Veículos</option>` + cacheVeiculosSeguros.map(v => `<option value="${v.id}">${v.placa} - ${v.modelo}</option>`).join('');
            }

            // Select Veículo no Novo Sinistro
            const nVeic = document.getElementById('novo-sin-veiculo');
            if (nVeic) {
                nVeic.innerHTML = `<option value="">Nenhum / Não aplicável</option>` + cacheVeiculosSeguros.map(v => `<option value="${v.id}">${v.placa} - ${v.modelo} (${v.status_ativo || v.status})</option>`).join('');
            }

            // Select Veículo Sinistrado para Liberação
            const libVeic = document.getElementById('liberar-veiculo-select');
            if (libVeic) {
                const sinistrados = cacheVeiculosSeguros.filter(v => (v.status_ativo === 'Sinistrado' || v.status === 'Sinistrado'));
                libVeic.innerHTML = `<option value="">Selecione o Veículo Sinistrado</option>` + sinistrados.map(v => `<option value="${v.id}">${v.placa} - ${v.modelo} (Sinistrado)</option>`).join('');
            }

            // Select Veículo para Vincular à Apólice
            const vincVeic = document.getElementById('vincular-veiculo-select');
            if (vincVeic) {
                vincVeic.innerHTML = `<option value="">Selecione o Veículo</option>` + cacheVeiculosSeguros.map(v => `<option value="${v.id}">${v.placa} - ${v.modelo}</option>`).join('');
            }

            // Select Motorista
            const nMot = document.getElementById('novo-sin-motorista');
            if (nMot) {
                nMot.innerHTML = `<option value="">Selecione o Motorista</option>` + motoristas.map(m => `<option value="${m.id}">${m.first_name ? `${m.first_name} ${m.last_name || ''}` : m.username}</option>`).join('');
            }

            // Select Entrega
            const nEnt = document.getElementById('novo-sin-entrega');
            if (nEnt) {
                nEnt.innerHTML = `<option value="">Nenhuma / Rota Livre</option>` + entregas.map(e => `<option value="${e.id}">Romaneio #${e.id} (${e.status})</option>`).join('');
            }

            // Select Apólice no Novo Sinistro
            const nApol = document.getElementById('novo-sin-apolice');
            if (nApol) {
                nApol.innerHTML = `<option value="">Buscar automaticamente pelo veículo</option>` + cacheApolices.map(a => `<option value="${a.id}">${a.seguradora} - ${a.numero_apolice} (${a.tipo})</option>`).join('');
            }
        } catch (err) {
            console.error('Erro ao carregar selects de apoio para seguros:', err);
        }
    }

    // Modal Apólice: Abrir, Salvar, Excluir
    document.getElementById('btn-nova-apolice')?.addEventListener('click', () => {
        document.getElementById('form-apolice').reset();
        document.getElementById('apolice-id').value = '';
        document.getElementById('modal-apolice-titulo').textContent = 'Cadastrar Apólice de Seguro';
        document.getElementById('banner-alerta-produto-perigoso').style.display = 'block';
        document.getElementById('modal-apolice').classList.add('active');
    });

    document.getElementById('btn-fechar-modal-apolice')?.addEventListener('click', () => {
        document.getElementById('modal-apolice').classList.remove('active');
    });
    document.getElementById('btn-cancelar-modal-apolice')?.addEventListener('click', () => {
        document.getElementById('modal-apolice').classList.remove('active');
    });

    // Alerta visual de produto perigoso não verificado no form de apólice
    document.getElementById('apolice-cobre-perigoso')?.addEventListener('change', (e) => {
        const val = e.target.value;
        const banner = document.getElementById('banner-alerta-produto-perigoso');
        if (banner) banner.style.display = (val === 'Não verificado') ? 'block' : 'none';
    });

    document.getElementById('form-apolice')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = document.getElementById('form-apolice');
        const formData = new FormData(form);
        const apId = document.getElementById('apolice-id').value;

        // Trata checkbox ativa
        formData.set('ativa', document.getElementById('apolice-ativa').checked ? 'true' : 'false');

        const url = apId ? `/logistica/api/apolices/${apId}/` : '/logistica/api/apolices/';
        const method = apId ? 'PATCH' : 'POST';

        try {
            const res = await fetch(url, {
                method: method,
                headers: {
                    'X-CSRFToken': getCookie('csrftoken') || '',
                    'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
                    'X-Tenant-ID': (document.querySelector('meta[name="active-tenant-id"]')?.content || '')
                },
                credentials: 'same-origin',
                body: formData
            });
            if (!res.ok) {
                const errData = await res.json();
                throw new Error(JSON.stringify(errData));
            }

            Swal.fire('Sucesso!', 'Apólice de seguro salva com êxito.', 'success');
            document.getElementById('modal-apolice').classList.remove('active');
            await carregarApolices();
            await carregarIndicadoresSeguros();
        } catch (err) {
            Swal.fire('Erro ao Salvar Apólice', err.message, 'error');
        }
    });

    window.editarApolice = function(id) {
        const ap = cacheApolices.find(a => a.id === id);
        if (!ap) return;
        document.getElementById('apolice-id').value = ap.id;
        document.getElementById('modal-apolice-titulo').textContent = `Editar Apólice: ${ap.numero_apolice}`;
        document.getElementById('apolice-seguradora').value = ap.seguradora || '';
        document.getElementById('apolice-numero').value = ap.numero_apolice || '';
        document.getElementById('apolice-tipo').value = ap.tipo || 'Frota/Casco+RCF';
        document.getElementById('apolice-corretor').value = ap.corretor || '';
        document.getElementById('apolice-assistencia').value = ap.telefone_assistencia_24h || '';
        document.getElementById('apolice-prazo-horas').value = ap.prazo_comunicacao_sinistro_horas || 24;
        document.getElementById('apolice-inicio').value = ap.vigencia_inicio || '';
        document.getElementById('apolice-fim').value = ap.vigencia_fim || '';
        document.getElementById('apolice-premio').value = ap.premio_total || '';
        document.getElementById('apolice-forma-pagamento').value = ap.forma_pagamento || '';
        document.getElementById('apolice-parcelas').value = ap.parcelas || 1;
        document.getElementById('apolice-limite-viagem').value = ap.limite_maximo_por_viagem || '';
        document.getElementById('apolice-cobre-perigoso').value = ap.cobre_produto_perigoso || 'Não verificado';
        document.getElementById('apolice-riscos-excluidos').value = ap.produtos_riscos_excluidos || '';
        document.getElementById('apolice-observacoes').value = ap.observacoes || '';
        document.getElementById('apolice-ativa').checked = Boolean(ap.ativa);

        const banner = document.getElementById('banner-alerta-produto-perigoso');
        if (banner) banner.style.display = (ap.cobre_produto_perigoso === 'Não verificado') ? 'block' : 'none';

        document.getElementById('modal-apolice').classList.add('active');
    };

    window.excluirApolice = async function(id) {
        const conf = await Swal.fire({
            title: 'Excluir Apólice?',
            text: 'Esta apólice será removida do sistema.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#ef4444',
            confirmButtonText: 'Sim, excluir'
        });
        if (!conf.isConfirmed) return;

        try {
            const res = await fetch(`/logistica/api/apolices/${id}/`, {
                method: 'DELETE',
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (!res.ok) throw new Error('Não foi possível excluir.');
            Swal.fire('Excluída!', 'Apólice removida.', 'success');
            await carregarApolices();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    };

    // Modal Vincular Veículo à Apólice
    window.abrirModalVincularVeiculo = function(apoliceId, apoliceNome) {
        document.getElementById('vincular-apolice-id').value = apoliceId;
        document.getElementById('modal-vincular-apolice-nome').textContent = `Apólice: ${apoliceNome}`;
        document.getElementById('modal-vincular-veiculo-apolice').classList.add('active');
    };
    document.getElementById('btn-fechar-modal-vincular-veiculo')?.addEventListener('click', () => {
        document.getElementById('modal-vincular-veiculo-apolice').classList.remove('active');
    });
    document.getElementById('btn-cancelar-modal-vincular-veiculo')?.addEventListener('click', () => {
        document.getElementById('modal-vincular-veiculo-apolice').classList.remove('active');
    });

    document.getElementById('form-vincular-veiculo-apolice')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const apId = document.getElementById('vincular-apolice-id').value;
        const veicId = document.getElementById('vincular-veiculo-select').value;
        const tipoValor = document.getElementById('vincular-veiculo-tipo-valor').value;
        const valorSegurado = document.getElementById('vincular-veiculo-valor').value;

        try {
            const res = await fetch(`/logistica/api/apolices/${apId}/veiculos/`, {
                method: 'POST',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    veiculo: veicId,
                    tipo_valor: tipoValor,
                    valor_segurado: valorSegurado || null
                })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Erro ao vincular veículo.');
            }
            Swal.fire('Sucesso!', 'Veículo vinculado à apólice.', 'success');
            document.getElementById('modal-vincular-veiculo-apolice').classList.remove('active');
            await carregarApolices();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // Modal Novo Sinistro
    document.getElementById('btn-novo-sinistro')?.addEventListener('click', () => {
        document.getElementById('form-novo-sinistro').reset();
        const agora = new Date();
        agora.setMinutes(agora.getMinutes() - agora.getTimezoneOffset());
        document.getElementById('novo-sin-data-hora').value = agora.toISOString().slice(0, 16);
        document.getElementById('form-novo-sin-alerta-vitimas').style.display = 'none';
        document.getElementById('modal-novo-sinistro').classList.add('active');
    });
    document.getElementById('btn-fechar-modal-novo-sinistro')?.addEventListener('click', () => {
        document.getElementById('modal-novo-sinistro').classList.remove('active');
    });
    document.getElementById('btn-cancelar-modal-novo-sinistro')?.addEventListener('click', () => {
        document.getElementById('modal-novo-sinistro').classList.remove('active');
    });

    // Alerta Imediato de Vítimas no Form
    document.getElementById('novo-sin-houve-vitimas')?.addEventListener('change', (e) => {
        const checked = e.target.checked;
        document.getElementById('form-novo-sin-alerta-vitimas').style.display = checked ? 'flex' : 'none';
        if (checked) {
            Swal.fire({
                title: '🚨 ATENÇÃO: HOUVE VÍTIMAS',
                text: 'Acione imediatamente os serviços de emergência (SAMU 192 ou Bombeiros 193) antes de continuar o registro.',
                icon: 'warning',
                confirmButtonColor: '#dc2626'
            });
        }
    });

    // Detectar GPS
    document.getElementById('btn-detectar-gps-sinistro')?.addEventListener('click', () => {
        const feedback = document.getElementById('novo-sin-gps-feedback');
        if (!navigator.geolocation) {
            feedback.textContent = 'Geolocalização não suportada neste navegador.';
            return;
        }
        feedback.textContent = 'Obtendo coordenadas do satélite...';
        navigator.geolocation.getCurrentPosition(
            pos => {
                const lat = pos.coords.latitude.toFixed(6);
                const lng = pos.coords.longitude.toFixed(6);
                document.getElementById('novo-sin-lat').value = lat;
                document.getElementById('novo-sin-lng').value = lng;
                feedback.textContent = `📍 Coordenadas obtidas: ${lat}, ${lng}`;
            },
            err => {
                feedback.textContent = `Falha ao obter GPS: ${err.message}`;
            },
            { enableHighAccuracy: true, timeout: 8000 }
        );
    });

    // Submissão de Novo Sinistro
    document.getElementById('form-novo-sinistro')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const tipo = document.getElementById('novo-sin-tipo').value;
        const dataHora = document.getElementById('novo-sin-data-hora').value;
        const veiculoId = document.getElementById('novo-sin-veiculo').value || null;
        const motoristaId = document.getElementById('novo-sin-motorista').value || null;
        const entregaId = document.getElementById('novo-sin-entrega').value || null;
        const apoliceId = document.getElementById('novo-sin-apolice').value || null;
        const houveVitimas = document.getElementById('novo-sin-houve-vitimas').checked;
        const bo = document.getElementById('novo-sin-bo').value.trim();
        const prejuizo = document.getElementById('novo-sin-prejuizo').value || '0.00';
        const endereco = document.getElementById('novo-sin-endereco').value.trim();
        const lat = document.getElementById('novo-sin-lat').value || null;
        const lng = document.getElementById('novo-sin-lng').value || null;
        const descricao = document.getElementById('novo-sin-descricao').value.trim();
        const terceiros = document.getElementById('novo-sin-terceiros').value.trim();

        const payload = {
            tipo: tipo,
            data_hora: dataHora,
            veiculo: veiculoId,
            motorista: motoristaId,
            entrega: entregaId,
            apolice: apoliceId,
            houve_vitimas: houveVitimas,
            boletim_ocorrencia_numero: bo,
            valor_prejuizo_estimado: prejuizo,
            endereco: endereco,
            latitude: lat,
            longitude: lng,
            descricao: descricao,
            terceiros: terceiros ? { descricao: terceiros } : {},
            status: 'Registrado'
        };

        try {
            const res = await fetch('/logistica/api/sinistros/', {
                method: 'POST',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(JSON.stringify(err));
            }
            const s = await res.json();
            Swal.fire({
                title: 'Sinistro Registrado!',
                html: `Ocorrência <strong>${s.numero}</strong> cadastrada.<br>Veículo marcado como <strong>Sinistrado</strong> e eventos inseridos na linha do tempo.`,
                icon: 'success'
            });
            document.getElementById('modal-novo-sinistro').classList.remove('active');
            await loadSegurosESinistros();
            abrirModalSinistroDetalhe(s.id);
        } catch (err) {
            Swal.fire('Erro ao Registrar Sinistro', err.message, 'error');
        }
    });

    // Fechar Detalhes de Sinistro
    document.getElementById('btn-fechar-modal-sinistro-detalhe')?.addEventListener('click', () => {
        document.getElementById('modal-sinistro-detalhe').classList.remove('active');
    });
    document.getElementById('btn-fechar-modal-sinistro-detalhe-bottom')?.addEventListener('click', () => {
        document.getElementById('modal-sinistro-detalhe').classList.remove('active');
    });

    // Enviar Anexo para o Sinistro
    document.getElementById('form-upload-anexo-sinistro')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!sinistroModalAtualId) return;
        const fileInput = document.getElementById('sin-anexo-arquivo');
        if (!fileInput.files.length) {
            Swal.fire('Atenção', 'Selecione um arquivo.', 'warning');
            return;
        }

        const formData = new FormData();
        formData.append('arquivo', fileInput.files[0]);
        formData.append('tipo', document.getElementById('sin-anexo-tipo').value);
        formData.append('descricao', document.getElementById('sin-anexo-descricao').value.trim());

        try {
            const res = await fetch(`/logistica/api/sinistros/${sinistroModalAtualId}/adicionar-anexo/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken') || '',
                    'Authorization': (localStorage.getItem('access_token') ? 'Bearer ' + localStorage.getItem('access_token') : ''),
                    'X-Tenant-ID': (document.querySelector('meta[name="active-tenant-id"]')?.content || '')
                },
                credentials: 'same-origin',
                body: formData
            });
            if (!res.ok) throw new Error('Falha no upload do anexo.');
            Swal.fire('Anexo Enviado!', 'Arquivo adicionado ao sinistro.', 'success');
            fileInput.value = '';
            document.getElementById('sin-anexo-descricao').value = '';
            abrirModalSinistroDetalhe(sinistroModalAtualId);
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // Transição de Status do Sinistro
    document.getElementById('form-transicionar-sinistro')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!sinistroModalAtualId) return;

        const novoStatus = document.getElementById('transicao-sin-status').value;
        const protocolo = document.getElementById('transicao-sin-protocolo').value.trim();
        const indenizacao = document.getElementById('transicao-sin-indenizacao').value;
        const obs = document.getElementById('transicao-sin-obs').value.trim();

        try {
            const res = await fetch(`/logistica/api/sinistros/${sinistroModalAtualId}/transicionar-status/`, {
                method: 'POST',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    status: novoStatus,
                    protocolo_seguradora: protocolo || null,
                    valor_indenizacao: indenizacao || null,
                    observacao: obs
                })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Erro na transição.');
            }
            Swal.fire('Status Atualizado!', `Sinistro transicionado para "${novoStatus}".`, 'success');
            await carregarSinistros();
            await carregarIndicadoresSeguros();
            abrirModalSinistroDetalhe(sinistroModalAtualId);
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // Vincular OS de Manutenção ao Sinistro em 1 Clique
    document.getElementById('btn-vincular-os-sinistro')?.addEventListener('click', async () => {
        if (!sinistroModalAtualId) return;
        const conf = await Swal.fire({
            title: 'Abrir OS Corretiva?',
            text: 'Será gerada uma Ordem de Serviço corretiva vinculada ao sinistro para orçamentação e reparo do veículo na oficina.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Sim, abrir OS'
        });
        if (!conf.isConfirmed) return;

        try {
            const res = await fetch(`/logistica/api/sinistros/${sinistroModalAtualId}/vincular-os/`, {
                method: 'POST',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    prioridade: 'Alta',
                    imobiliza_veiculo: true
                })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.erro?.[0] || 'Falha ao vincular OS.');
            }
            const data = await res.json();
            Swal.fire('OS Vinculada!', data.mensagem, 'success');
            abrirModalSinistroDetalhe(sinistroModalAtualId);
            await carregarSinistros();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // Modal Ajuste de Estoque de Carga
    document.getElementById('btn-abrir-ajuste-estoque-sinistro')?.addEventListener('click', () => {
        document.getElementById('modal-ajuste-estoque-sinistro').classList.add('active');
    });
    document.getElementById('btn-fechar-modal-ajuste-estoque')?.addEventListener('click', () => {
        document.getElementById('modal-ajuste-estoque-sinistro').classList.remove('active');
    });
    document.getElementById('btn-cancelar-modal-ajuste-estoque')?.addEventListener('click', () => {
        document.getElementById('modal-ajuste-estoque-sinistro').classList.remove('active');
    });

    document.getElementById('form-ajuste-estoque-sinistro')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!sinistroModalAtualId) return;

        const decisao = document.getElementById('ajuste-decisao-entrega').value;
        const justificativa = document.getElementById('ajuste-justificativa').value.trim();

        try {
            const res = await fetch(`/logistica/api/sinistros/${sinistroModalAtualId}/ajustar-estoque-carga/`, {
                method: 'POST',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    decisao_entrega: decisao,
                    justificativa: justificativa
                })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.erro?.[0] || 'Erro no ajuste de estoque.');
            }
            const data = await res.json();
            Swal.fire('Ajuste Concluído!', data.mensagem, 'success');
            document.getElementById('modal-ajuste-estoque-sinistro').classList.remove('active');
            abrirModalSinistroDetalhe(sinistroModalAtualId);
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // Modal Liberar Veículo Sinistrado
    document.getElementById('btn-abrir-liberar-veiculo')?.addEventListener('click', () => {
        document.getElementById('form-liberar-veiculo').reset();
        document.getElementById('liberar-veiculo-alerta-os').style.display = 'none';
        carregarSelectsSeguros();
        document.getElementById('modal-liberar-veiculo').classList.add('active');
    });
    document.getElementById('btn-fechar-modal-liberar-veiculo')?.addEventListener('click', () => {
        document.getElementById('modal-liberar-veiculo').classList.remove('active');
    });
    document.getElementById('btn-cancelar-modal-liberar-veiculo')?.addEventListener('click', () => {
        document.getElementById('modal-liberar-veiculo').classList.remove('active');
    });

    document.getElementById('form-liberar-veiculo')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const veicId = document.getElementById('liberar-veiculo-select').value;
        const obs = document.getElementById('liberar-veiculo-obs').value.trim();
        if (!veicId) {
            Swal.fire('Atenção', 'Selecione o veículo.', 'warning');
            return;
        }

        try {
            const res = await fetch('/logistica/api/sinistros/liberar-veiculo/', {
                method: 'POST',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    veiculo: veicId,
                    observacao: obs
                })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.erro?.[0] || 'Não foi possível liberar o veículo.');
            }
            const data = await res.json();
            Swal.fire('Veículo Ativado!', data.mensagem, 'success');
            document.getElementById('modal-liberar-veiculo').classList.remove('active');
            if (window.loadVeiculos) window.loadVeiculos();
            await loadSegurosESinistros();
        } catch (err) {
            Swal.fire('Bloqueio Operacional', err.message, 'error');
        }
    });

    // Modal Configuração de Seguros
    document.getElementById('btn-config-seguros')?.addEventListener('click', async () => {
        try {
            const res = await fetch('/logistica/api/seguros/configuracao/', { headers: getAuthHeaders(), credentials: 'same-origin' });
            if (res.ok) {
                const cfg = await res.json();
                document.getElementById('cfg-exigir-apolice').checked = Boolean(cfg.exigir_apolice_ativa_para_operar);
                document.getElementById('cfg-alerta-dias').value = cfg.alerta_renovacao_dias || 30;
            }
            document.getElementById('modal-seguros-config').classList.add('active');
        } catch (err) {
            console.error(err);
        }
    });
    document.getElementById('btn-fechar-modal-config-seguros')?.addEventListener('click', () => {
        document.getElementById('modal-seguros-config').classList.remove('active');
    });
    document.getElementById('btn-cancelar-modal-config-seguros')?.addEventListener('click', () => {
        document.getElementById('modal-seguros-config').classList.remove('active');
    });

    document.getElementById('form-seguros-config')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const exigir = document.getElementById('cfg-exigir-apolice').checked;
        const alertaDias = document.getElementById('cfg-alerta-dias').value;

        try {
            const res = await fetch('/logistica/api/seguros/configuracao/', {
                method: 'PATCH',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    exigir_apolice_ativa_para_operar: exigir,
                    alerta_renovacao_dias: parseInt(alertaDias, 10)
                })
            });
            if (!res.ok) throw new Error('Não foi possível salvar configurações.');
            Swal.fire('Configurações Salvas!', 'Regras de seguro atualizadas para a empresa.', 'success');
            document.getElementById('modal-seguros-config').classList.remove('active');
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // Botões de Recarregamento e Filtros
    document.getElementById('btn-recarregar-seguros')?.addEventListener('click', loadSegurosESinistros);
    document.getElementById('filtro-sinistro-veiculo')?.addEventListener('change', carregarSinistros);
    document.getElementById('filtro-sinistro-tipo')?.addEventListener('change', carregarSinistros);
    document.getElementById('btn-filtrar-indicadores-seguros')?.addEventListener('click', carregarIndicadoresSeguros);

    // Exposição Global de Seguros & Sinistros
    window.loadSegurosESinistros = loadSegurosESinistros;
    window.abrirModalSinistroDetalhe = abrirModalSinistroDetalhe;

    // ==============================================================================
    // 7. SPRINT L6: FRETE, RENTABILIDADE E CUSTO TOTAL (TCO)
    // ==============================================================================
    const formatBRL = (val) => Number(val || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

    async function loadRentabilidade() {
        const inicio = document.getElementById('rentab-filtro-inicio')?.value || '';
        const fim = document.getElementById('rentab-filtro-fim')?.value || '';
        const agrupar = document.getElementById('rentab-filtro-agrupamento')?.value || 'rota';

        const params = new URLSearchParams();
        if (inicio) params.append('inicio', inicio);
        if (fim) params.append('fim', fim);
        if (agrupar) params.append('agrupar', agrupar);

        try {
            const res = await fetch(`/logistica/api/rentabilidade/?${params.toString()}`, {
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (!res.ok) throw new Error('Não foi possível carregar indicadores de rentabilidade.');
            const data = await res.json();
            const detalhes = data.itens || [];

            // 1. Atualizar KPIs do Topo
            const elReceita = document.getElementById('kpi-rentab-receita');
            const elViagens = document.getElementById('kpi-rentab-viagens');
            const elCusto = document.getElementById('kpi-rentab-custo');
            const elCustoEntr = document.getElementById('kpi-rentab-custo-entrega');
            const elMargemBruta = document.getElementById('kpi-rentab-margem-bruta');
            const elMargemPct = document.getElementById('kpi-rentab-margem-pct');
            const elCustoKm = document.getElementById('kpi-rentab-custo-km');
            const elOcupacao = document.getElementById('kpi-rentab-ocupacao');

            if (elReceita) elReceita.textContent = formatBRL(data.receita_total);
            if (elViagens) elViagens.textContent = `${data.total_viagens || 0} viagens realizadas`;
            if (elCusto) elCusto.textContent = formatBRL(data.custo_total);
            if (elCustoEntr) elCustoEntr.textContent = `${formatBRL(data.custo_por_entrega)} / entrega`;
            
            if (elMargemBruta) {
                elMargemBruta.textContent = formatBRL(data.margem_bruta);
                elMargemBruta.style.color = (data.margem_bruta >= 0) ? '#10b981' : '#ef4444';
            }
            if (elMargemPct) elMargemPct.textContent = `Margem: ${Number(data.margem_percentual || 0).toFixed(1)}%`;
            if (elCustoKm) elCustoKm.textContent = `${formatBRL(data.custo_por_km)} / km`;
            if (elOcupacao) elOcupacao.textContent = `Lotação Média: ${Number(data.ocupacao_media || 0).toFixed(1)}%`;

            // 2. Gráfico / Ranking de Margem por Grupo (Top 6)
            const rankingContainer = document.getElementById('rentab-ranking-margem');
            if (rankingContainer) {
                if (!detalhes.length) {
                    rankingContainer.innerHTML = '<div style="color:var(--color-text-muted); font-size:13px; text-align:center; padding:20px;">Nenhum dado encontrado no período.</div>';
                } else {
                    const topGrupos = [...detalhes].sort((a, b) => b.margem - a.margem).slice(0, 6);
                    rankingContainer.innerHTML = topGrupos.map(g => {
                        const pctMargem = Math.max(-100, Math.min(100, g.margem_pct || 0));
                        const barWidth = Math.max(5, Math.min(100, Math.abs(pctMargem)));
                        const barColor = (g.margem >= 0) ? '#10b981' : '#ef4444';
                        return `
                            <div class="rentab-bar-container">
                                <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:4px;">
                                    <span style="color:var(--color-text);">${g.nome || 'Geral'}</span>
                                    <span style="color:${barColor};">${formatBRL(g.margem)} (${(g.margem_pct || 0).toFixed(1)}%)</span>
                                </div>
                                <div class="rentab-bar-track">
                                    <div class="rentab-bar-fill" style="width:${barWidth}%; background:${barColor};"></div>
                                </div>
                            </div>
                        `;
                    }).join('');
                }
            }

            // 3. Tabela Detalhada de Rentabilidade
            const tbodyDetalhes = document.getElementById('tbody-rentabilidade-detalhada');
            if (tbodyDetalhes) {
                if (!detalhes.length) {
                    tbodyDetalhes.innerHTML = '<tr><td colspan="9" style="text-align:center; color:var(--color-text-muted); padding:16px;">Nenhum registro encontrado no filtro atual.</td></tr>';
                } else {
                    tbodyDetalhes.innerHTML = detalhes.map(item => {
                        const corMargem = (item.margem >= 0) ? '#10b981' : '#ef4444';
                        const cEntrega = item.custo_entrega || (item.viagens ? (item.custo / item.viagens) : 0);
                        return `
                            <tr>
                                <td><strong>${item.nome || '-'}</strong></td>
                                <td style="text-align:center;">${item.viagens || 0}</td>
                                <td style="text-align:right;">${formatBRL(item.receita)}</td>
                                <td style="text-align:right; color:#ef4444;">${formatBRL(item.custo)}</td>
                                <td style="text-align:right; font-weight:700; color:${corMargem};">${formatBRL(item.margem)}</td>
                                <td style="text-align:right; font-weight:700; color:${corMargem};">${(item.margem_pct || 0).toFixed(1)}%</td>
                                <td style="text-align:right;">${formatBRL(item.custo_km)}</td>
                                <td style="text-align:right;">${formatBRL(cEntrega)}</td>
                                <td style="text-align:center;">${(item.ocupacao_media || 0).toFixed(1)}%</td>
                            </tr>
                        `;
                    }).join('');
                }
            }

            // 4. Carregar Ranking Consolidado TCO da Frota
            await loadTCOFrota();

        } catch (err) {
            console.error('Erro em loadRentabilidade:', err);
        }
    }

    async function loadTCOFrota() {
        try {
            const res = await fetch('/logistica/api/rentabilidade/tco/', {
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (!res.ok) return;
            const data = await res.json();
            const veiculos = data.veiculos || [];
            const composicao = data.composicao_geral || {};

            // Atualizar barras de composição do TCO
            const compContainer = document.getElementById('tco-frota-composicao-visual');
            if (compContainer) {
                const combPct = Number(composicao.combustivel_pct || 0);
                const manutPct = Number(composicao.manutencao_pct || 0);
                const segPct = Number(composicao.seguro_pct || 0);
                const sinPct = Number(composicao.sinistros_pct || 0);
                const depPct = Number(composicao.depreciacao_pct || 0);

                compContainer.innerHTML = `
                    <div class="rentab-bar-container">
                        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
                            <span>⛽ Combustível (${formatBRL(composicao.custo_combustivel)})</span>
                            <strong>${combPct.toFixed(1)}%</strong>
                        </div>
                        <div class="rentab-bar-track"><div class="rentab-bar-fill" style="width:${combPct}%; background:#3b82f6;"></div></div>
                    </div>
                    <div class="rentab-bar-container">
                        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
                            <span>🔧 Manutenção & Peças (${formatBRL(composicao.custo_manutencao)})</span>
                            <strong>${manutPct.toFixed(1)}%</strong>
                        </div>
                        <div class="rentab-bar-track"><div class="rentab-bar-fill" style="width:${manutPct}%; background:#f59e0b;"></div></div>
                    </div>
                    <div class="rentab-bar-container">
                        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
                            <span>🛡️ Seguro Rateado (${formatBRL(composicao.custo_seguro)})</span>
                            <strong>${segPct.toFixed(1)}%</strong>
                        </div>
                        <div class="rentab-bar-track"><div class="rentab-bar-fill" style="width:${segPct}%; background:#10b981;"></div></div>
                    </div>
                    <div class="rentab-bar-container">
                        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
                            <span>🚨 Sinistros Líquidos (${formatBRL(composicao.custo_sinistros)})</span>
                            <strong>${sinPct.toFixed(1)}%</strong>
                        </div>
                        <div class="rentab-bar-track"><div class="rentab-bar-fill" style="width:${sinPct}%; background:#ef4444;"></div></div>
                    </div>
                    <div class="rentab-bar-container">
                        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
                            <span>📉 Depreciação (${formatBRL(composicao.custo_depreciacao)})</span>
                            <strong>${depPct.toFixed(1)}%</strong>
                        </div>
                        <div class="rentab-bar-track"><div class="rentab-bar-fill" style="width:${depPct}%; background:#6366f1;"></div></div>
                    </div>
                `;
            }

            // Atualizar tabela de ranking da frota
            const tbodyTCO = document.getElementById('tbody-tco-ranking-frota');
            if (tbodyTCO) {
                if (!veiculos.length) {
                    tbodyTCO.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--color-text-muted); padding:16px;">Nenhum veículo com movimentação.</td></tr>';
                } else {
                    tbodyTCO.innerHTML = veiculos.map((v, idx) => {
                        const statusAlerta = v.sugestao_substituicao
                            ? `<span class="badge" style="background:rgba(239,68,68,0.15); color:#ef4444; border:1px solid #ef4444;" title="${v.motivo_substituicao}">⚠️ Avaliar Substituição</span>`
                            : `<span class="badge" style="background:rgba(16,185,129,0.15); color:#10b981; border:1px solid #10b981;">✓ Normal</span>`;
                        return `
                            <tr>
                                <td>
                                    <strong>#${idx + 1} - ${formatPlaca(v.placa)}</strong>
                                    <div style="font-size:11px; color:var(--color-text-muted);">${v.modelo || ''} (${v.tipo_veiculo || 'Caminhão'})</div>
                                </td>
                                <td style="text-align:center;">${v.total_viagens || 0}</td>
                                <td style="text-align:right; font-weight:700;">${formatBRL(v.custo_total_acumulado)}</td>
                                <td style="text-align:right;">${formatBRL(v.custo_por_km)}</td>
                                <td style="text-align:right;">${formatBRL(v.custo_mensal_medio)}</td>
                                <td style="text-align:center;">
                                    <span style="font-weight:600; color:${(v.percentual_manut_sobre_fipe > 50) ? '#ef4444' : 'var(--color-text)'};">
                                        ${(v.percentual_manut_sobre_fipe || 0).toFixed(1)}%
                                    </span>
                                </td>
                                <td style="text-align:center;">${statusAlerta}</td>
                            </tr>
                        `;
                    }).join('');
                }
            }

        } catch (err) {
            console.error('Erro em loadTCOFrota:', err);
        }
    }

    // Carregar Aba TCO no Modal do Veículo
    async function carregarTCOVeiculoAba(veiculoId) {
        if (!veiculoId) return;
        try {
            const res = await fetch(`/logistica/api/rentabilidade/tco/?veiculo_id=${veiculoId}`, {
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (!res.ok) return;
            const data = await res.json();
            const v = (data.veiculos && data.veiculos.length) ? data.veiculos[0] : null;
            if (!v) return;

            const elTotal = document.getElementById('veiculo-tco-custo-total');
            const elKm = document.getElementById('veiculo-tco-km-total');
            const elKmCusto = document.getElementById('veiculo-tco-custo-km');
            const elMes = document.getElementById('veiculo-tco-custo-mes');
            const elMesesOp = document.getElementById('veiculo-tco-meses-operacao');
            const elFipe = document.getElementById('veiculo-tco-valor-fipe');
            const elManutFipe = document.getElementById('veiculo-tco-manut-vs-fipe');
            const elAlerta = document.getElementById('veiculo-tco-alerta-box');

            if (elTotal) elTotal.textContent = formatBRL(v.custo_total_acumulado);
            if (elKm) elKm.textContent = `${Number(v.km_total_rodado || 0).toLocaleString('pt-BR')} km rodados`;
            if (elKmCusto) elKmCusto.textContent = `${formatBRL(v.custo_por_km)} /km`;
            if (elMes) elMes.textContent = `${formatBRL(v.custo_mensal_medio)} /mês`;
            if (elMesesOp) elMesesOp.textContent = `${v.meses_em_operacao || 1} meses de operação`;
            if (elFipe) elFipe.textContent = formatBRL(v.valor_fipe);
            if (elManutFipe) elManutFipe.textContent = `Manut: ${(v.percentual_manut_sobre_fipe || 0).toFixed(1)}% da FIPE`;

            if (elAlerta) {
                if (v.sugestao_substituicao) {
                    elAlerta.style.display = 'block';
                    elAlerta.style.background = 'rgba(239,68,68,0.12)';
                    elAlerta.style.border = '1px solid #ef4444';
                    elAlerta.style.color = '#ef4444';
                    elAlerta.innerHTML = `⚠️ <strong>Avaliar Substituição:</strong> ${v.motivo_substituicao}`;
                } else {
                    elAlerta.style.display = 'none';
                }
            }

            // Composição Detalhada
            const setComp = (idVal, idPct, val, pct) => {
                const elV = document.getElementById(idVal);
                const elP = document.getElementById(idPct);
                if (elV) elV.textContent = formatBRL(val);
                if (elP) elP.textContent = `${Number(pct || 0).toFixed(1)}%`;
            };

            setComp('tco-comp-combustivel', 'tco-comp-combustivel-pct', v.custo_combustivel, v.combustivel_pct);
            setComp('tco-comp-manutencao', 'tco-comp-manutencao-pct', v.custo_manutencao, v.manutencao_pct);
            setComp('tco-comp-seguro', 'tco-comp-seguro-pct', v.custo_seguro_rateado, v.seguro_pct);
            setComp('tco-comp-sinistros', 'tco-comp-sinistros-pct', v.custo_sinistros_liquido, v.sinistros_pct);
            setComp('tco-comp-depreciacao', 'tco-comp-depreciacao-pct', v.custo_depreciacao, v.depreciacao_pct);

            const elRankTxt = document.getElementById('veiculo-tco-ranking-texto');
            if (elRankTxt) {
                elRankTxt.textContent = `Veículo ocupa a ${v.posicao_ranking || 1}ª posição em eficiência entre ${v.total_veiculos_tipo || 1} veículos cadastrados da categoria ${v.tipo_veiculo || 'Caminhão'}.`;
            }
        } catch (err) {
            console.error('Erro em carregarTCOVeiculoAba:', err);
        }
    }

    // Exportação CSV de Rentabilidade
    function exportarCSVRentabilidade() {
        const inicio = document.getElementById('rentab-filtro-inicio')?.value || '';
        const fim = document.getElementById('rentab-filtro-fim')?.value || '';
        const agrupar = document.getElementById('rentab-filtro-agrupamento')?.value || 'rota';

        const params = new URLSearchParams();
        if (inicio) params.append('inicio', inicio);
        if (fim) params.append('fim', fim);
        if (agrupar) params.append('agrupar', agrupar);
        params.append('formato', 'csv');

        window.location.href = `/logistica/api/rentabilidade/?${params.toString()}`;
    }

    // Modal Configurações de Rentabilidade
    document.getElementById('btn-abrir-config-rentab')?.addEventListener('click', async () => {
        try {
            const res = await fetch('/logistica/api/rentabilidade/configuracao/', {
                headers: getAuthHeaders(),
                credentials: 'same-origin'
            });
            if (res.ok) {
                const cfg = await res.json();
                const chkEst = document.getElementById('cfg-usar-estimativa-combustivel');
                const selMetodo = document.getElementById('cfg-metodo-rateio-seguro');
                const inpKm = document.getElementById('cfg-km-anual-estimado');
                const inpVida = document.getElementById('cfg-vida-util-anos');
                const inpRes = document.getElementById('cfg-percentual-residual');
                const inpLot = document.getElementById('cfg-media-lotacao-alerta');
                const inpViag = document.getElementById('cfg-viagens-alerta');

                if (chkEst) chkEst.checked = Boolean(cfg.usar_estimativa_combustivel);
                if (selMetodo) selMetodo.value = cfg.metodo_rateio_seguro || 'Km Rodado';
                if (inpKm) inpKm.value = cfg.km_anual_estimado_veiculo || 40000;
                if (inpVida) inpVida.value = cfg.vida_util_anos || 5;
                if (inpRes) inpRes.value = cfg.percentual_residual || 20.0;
                if (inpLot) inpLot.value = cfg.media_lotacao_alerta_minima || 50;
                if (inpViag) inpViag.value = cfg.viagens_baixa_ocupacao_alerta || 5;
            }
            document.getElementById('modal-config-rentabilidade')?.classList.add('active');
        } catch (err) {
            console.error('Erro ao carregar config rentabilidade:', err);
        }
    });

    document.getElementById('btn-fechar-modal-config-rentab')?.addEventListener('click', () => {
        document.getElementById('modal-config-rentabilidade')?.classList.remove('active');
    });
    document.getElementById('btn-cancelar-modal-config-rentab')?.addEventListener('click', () => {
        document.getElementById('modal-config-rentabilidade')?.classList.remove('active');
    });

    document.getElementById('form-config-rentabilidade')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            usar_estimativa_combustivel: document.getElementById('cfg-usar-estimativa-combustivel')?.checked ?? true,
            metodo_rateio_seguro: document.getElementById('cfg-metodo-rateio-seguro')?.value || 'Km Rodado',
            km_anual_estimado_veiculo: parseInt(document.getElementById('cfg-km-anual-estimado')?.value || '40000', 10),
            vida_util_anos: parseInt(document.getElementById('cfg-vida-util-anos')?.value || '5', 10),
            percentual_residual: parseFloat(document.getElementById('cfg-percentual-residual')?.value || '20.0'),
            media_lotacao_alerta_minima: parseFloat(document.getElementById('cfg-media-lotacao-alerta')?.value || '50.0'),
            viagens_baixa_ocupacao_alerta: parseInt(document.getElementById('cfg-viagens-alerta')?.value || '5', 10),
        };

        try {
            const res = await fetch('/logistica/api/rentabilidade/configuracao/', {
                method: 'PATCH',
                headers: {
                    ...getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error('Não foi possível salvar os parâmetros de rentabilidade.');
            Swal.fire('Parâmetros Salvos!', 'Premissas de rentabilidade e rateios atualizadas com sucesso.', 'success');
            document.getElementById('modal-config-rentabilidade')?.classList.remove('active');
            loadRentabilidade();
        } catch (err) {
            Swal.fire('Erro', err.message, 'error');
        }
    });

    // Eventos da Tela de Rentabilidade
    document.getElementById('btn-aplicar-filtros-rentab')?.addEventListener('click', loadRentabilidade);
    document.getElementById('btn-limpar-filtros-rentab')?.addEventListener('click', () => {
        const inpIni = document.getElementById('rentab-filtro-inicio');
        const inpFim = document.getElementById('rentab-filtro-fim');
        const selAgrup = document.getElementById('rentab-filtro-agrupamento');
        if (inpIni) inpIni.value = '';
        if (inpFim) inpFim.value = '';
        if (selAgrup) selAgrup.value = 'rota';
        loadRentabilidade();
    });
    document.getElementById('btn-exportar-csv-rentab')?.addEventListener('click', exportarCSVRentabilidade);
    document.getElementById('subtab-btn-tco')?.addEventListener('click', () => {
        if (veiculoModalAtualId) carregarTCOVeiculoAba(veiculoModalAtualId);
    });

    // Exposição global
    window.loadRentabilidade = loadRentabilidade;
    window.carregarTCOVeiculoAba = carregarTCOVeiculoAba;

    // Inicialização da Página
    loadKanban();
});
