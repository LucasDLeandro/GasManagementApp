document.addEventListener('DOMContentLoaded', function() {
    // ---- DRF Paginated Data Extractor Helper ----
    function extrairListaDRF(data) {
        if (!data) return [];
        if (Array.isArray(data)) return data;
        if (data.results && Array.isArray(data.results)) return data.results;
        return [];
    }

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
        let token = localStorage.getItem('access') || localStorage.getItem('access_token');
        if (token && isTokenExpired(token)) {
            localStorage.removeItem('access');
            localStorage.removeItem('access_token');
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

        // Se houver um tenant ativo no DOM (meta tag ou storage), repassa no header para redundância perfeita
        const activeTenantMeta = document.querySelector('meta[name="active-tenant-id"]') || document.querySelector('meta[name="current-tenant-id"]');
        if (activeTenantMeta && activeTenantMeta.content) {
            headers['X-Tenant-ID'] = activeTenantMeta.content;
        }

        return headers;
    }

    // ---- Utils ----
    function formatCurrency(val) {
        return parseFloat(val || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    }
    function formatDate(dateStr) {
        if (!dateStr) return '—';
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
    }
    function formatDateOnly(dateStr) {
        if (!dateStr) return 'Não definido';
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toLocaleDateString('pt-BR');
    }

    function renderEmptyState(tbody, colSpan, title, desc) {
        tbody.innerHTML = `<tr><td colspan="${colSpan}" style="padding: 0;">
            <div class="empty-state">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="8" y1="12" x2="16" y2="12"></line>
                </svg>
                <h4>${title}</h4>
                <p>${desc}</p>
                <button class="btn-primary" onclick="document.getElementById('btn-nova-venda').click()">+ Nova Venda</button>
            </div>
        </td></tr>`;
    }

    // ---- Tabs Logic ----
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    let currentTab = 'tab-dashboard';

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            const target = btn.getAttribute('data-target');
            currentTab = target;
            const targetPane = document.getElementById(target);
            if (targetPane) targetPane.classList.add('active');

            if (target === 'tab-dashboard') loadDashboard();
            if (target === 'tab-ativas') loadVendasAtivas();
            if (target === 'tab-concluidas') loadVendasConcluidas();
            if (target === 'tab-canceladas') loadVendasCanceladas();
        });
    });

    // ---- Filter Pills & Search na Fila Ativa ----
    let filtroStatusAtivas = '';
    let termoBuscaAtivas = '';

    const pills = document.querySelectorAll('#pills-status-ativas .pill');
    pills.forEach(pill => {
        pill.addEventListener('click', () => {
            pills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            filtroStatusAtivas = pill.getAttribute('data-filter') || '';
            loadVendasAtivas();
        });
    });

    const inputSearchAtivas = document.getElementById('search-ativas');
    let searchDebounce = null;
    if (inputSearchAtivas) {
        inputSearchAtivas.addEventListener('input', (e) => {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => {
                termoBuscaAtivas = e.target.value.trim();
                loadVendasAtivas();
            }, 300);
        });
    }

    // ---- Chart Instances ----
    let vendasChartInstance = null;
    let categoriaChartInstance = null;

    // ---- 1. Load Dashboard ----
    function loadDashboard() {
        fetch('/vendas/api/dashboard_metrics/', { headers: getAuthHeaders(), credentials: 'same-origin' })
            .then(res => {
                if (res.status === 401) {
                    localStorage.removeItem('access');
                    localStorage.removeItem('access_token');
                }
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                if (!data) return;
                const elFat = document.getElementById('metric-faturamento');
                if (elFat) elFat.textContent = formatCurrency(data.faturamento_total);
                const elTotal = document.getElementById('metric-total-vendas');
                if (elTotal) elTotal.textContent = data.total_vendas ?? 0;
                const elPend = document.getElementById('metric-pendentes');
                if (elPend) elPend.textContent = data.vendas_pendentes ?? 0;
                const elEnt = document.getElementById('metric-entrega');
                if (elEnt) elEnt.textContent = data.vendas_em_entrega ?? 0;
                const elTick = document.getElementById('metric-ticket-medio');
                if (elTick) elTick.textContent = formatCurrency(data.ticket_medio);
                
                const listaTop = document.getElementById('lista-top-produtos');
                if (!listaTop) return;
                listaTop.innerHTML = '';
                const topProdutos = extrairListaDRF(data.top_produtos);
                if (topProdutos && topProdutos.length > 0) {
                    topProdutos.forEach((p, idx) => {
                        listaTop.innerHTML += `<li style="font-size: 0.9rem; color: var(--color-text); padding: 8px 0; border-bottom: 1px solid var(--color-border); display: flex; justify-content: space-between;">
                            <span><strong>#${idx+1}</strong> ${p.nome || 'Produto'}</span>
                            <span style="color: var(--color-text-muted); font-weight: 600;">${p.total_qtd} un</span>
                        </li>`;
                    });
                } else {
                    listaTop.innerHTML = '<li style="font-size: 0.9rem; color: var(--color-text-muted);">Nenhum dado registrado para este tenant.</li>';
                }

                // Render Chart 1: Evolução com ApexCharts e grid padding seguro
                const vendasContainer = document.getElementById('vendasChart');
                if (vendasContainer && typeof ApexCharts !== 'undefined') {
                    const graficoLista = Array.isArray(data.grafico) ? data.grafico : [];
                    const labels = graficoLista.map(item => item.dia || '');
                    const values = graficoLista.map(item => parseFloat(item.total) || 0);

                    if (vendasChartInstance) {
                        try { vendasChartInstance.destroy(); } catch (e) {}
                    }

                    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

                    const optionsVendas = {
                        chart: {
                            type: 'area',
                            height: 260,
                            toolbar: { show: false },
                            background: 'transparent',
                            fontFamily: 'Inter, sans-serif'
                        },
                        colors: ['#0284c7'],
                        series: [{
                            name: 'Faturamento',
                            data: values
                        }],
                        xaxis: {
                            categories: labels.length ? labels : ['Sem dados'],
                            labels: {
                                style: {
                                    colors: isDark ? '#94a3b8' : '#64748b',
                                    fontSize: '11px',
                                    fontWeight: 600
                                }
                            },
                            axisBorder: { show: false },
                            axisTicks: { show: false }
                        },
                        yaxis: {
                            labels: {
                                formatter: val => 'R$ ' + (val >= 1000 ? (val/1000).toFixed(1) + 'k' : val.toFixed(0)),
                                style: {
                                    colors: isDark ? '#94a3b8' : '#64748b',
                                    fontSize: '11px'
                                }
                            }
                        },
                        stroke: {
                            curve: 'smooth',
                            width: 2.5
                        },
                        fill: {
                            type: 'gradient',
                            gradient: {
                                shadeIntensity: 1,
                                opacityFrom: 0.45,
                                opacityTo: 0.05,
                                stops: [0, 90, 100]
                            }
                        },
                        dataLabels: { enabled: false },
                        tooltip: {
                            y: {
                                formatter: val => formatCurrency(val)
                            }
                        },
                        grid: {
                            borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
                            strokeDashArray: 4,
                            padding: {
                                left: 16,
                                right: 20,
                                bottom: 8
                            }
                        }
                    };

                    vendasChartInstance = new ApexCharts(vendasContainer, optionsVendas);
                    vendasChartInstance.render();
                }

                // Render Chart 2: Categoria (Donut)
                const catContainer = document.getElementById('categoriaChart');
                if (catContainer && typeof ApexCharts !== 'undefined') {
                    if (categoriaChartInstance) {
                        try { categoriaChartInstance.destroy(); } catch (e) {}
                    }

                    const catLista = Array.isArray(data.vendas_por_categoria) ? data.vendas_por_categoria : [];
                    const catLabels = catLista.map(c => c.categoria || 'Gás');
                    const catValues = catLista.map(c => parseFloat(c.total_vendido) || 0);

                    const optionsCat = {
                        chart: {
                            type: 'donut',
                            height: 260,
                            background: 'transparent',
                            fontFamily: 'Inter, sans-serif'
                        },
                        series: catValues.length ? catValues : [1],
                        labels: catLabels.length ? catLabels : ['Sem dados'],
                        colors: ['#10b981', '#38bdf8', '#f59e0b', '#a855f7', '#ec4899'],
                        legend: {
                            position: 'bottom',
                            fontSize: '12px',
                            labels: {
                                colors: document.documentElement.getAttribute('data-theme') === 'dark' ? '#cbd5e1' : '#475569'
                            }
                        },
                        plotOptions: {
                            pie: {
                                donut: {
                                    size: '70%',
                                    labels: {
                                        show: true,
                                        total: {
                                            show: true,
                                            label: 'Total',
                                            formatter: w => {
                                                const total = w.globals.seriesTotals.reduce((a, b) => a + b, 0);
                                                return formatCurrency(total);
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        dataLabels: { enabled: false },
                        stroke: { width: 0 }
                    };

                    categoriaChartInstance = new ApexCharts(catContainer, optionsCat);
                    categoriaChartInstance.render();
                }
            })
            .catch(err => {
                console.error("Erro ao carregar dashboard:", err);
            });
    }

    // Helper de Badges Semânticos
    function getStatusBadge(status) {
        let badgeClass = 'badge-pendente';
        if (status === 'Em Separação') badgeClass = 'badge-separacao';
        if (status === 'Em Rota') badgeClass = 'badge-rota';
        if (status === 'Entregue' || status === 'Finalizada') badgeClass = 'badge-entregue';
        if (status === 'Cancelada') badgeClass = 'badge-cancelada';
        return `<span class="badge ${badgeClass}">${status}</span>`;
    }

    // ---- 2. Load Vendas da Fila Ativa ----
    function loadVendasAtivas() {
        const tbody = document.getElementById('tbody-ativas');
        if (!tbody) return;

        let url = '/vendas/api/?grupo_status=ativas';
        if (filtroStatusAtivas) url += `&status=${encodeURIComponent(filtroStatusAtivas)}`;
        if (termoBuscaAtivas) url += `&search=${encodeURIComponent(termoBuscaAtivas)}`;

        fetch(url, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const vendas = extrairListaDRF(data);
                tbody.innerHTML = '';
                if (vendas.length === 0) {
                    return renderEmptyState(tbody, 9, 'Nenhuma venda ativa encontrada', 'Todas as vendas foram concluídas ou não há pedidos correspondentes ao filtro atual.');
                }

                vendas.forEach(v => {
                    const totalQtdItens = v.itens ? v.itens.reduce((acc, item) => acc + (item.quantidade || 0), 0) : 0;
                    
                    let entregaHtml = '';
                    if (v.entrega) {
                        const statusBadge = v.entrega_status ? ` <span style="font-size:0.75rem; color:#2563eb;">(${v.entrega_status})</span>` : '';
                        entregaHtml = `<a href="/logistica/" style="text-decoration:none; color:#2563eb; font-weight:600; font-size:0.82rem; background: rgba(59, 130, 246, 0.1); padding: 3px 8px; border-radius: 6px; display:inline-block;">🚚 Entrega #${v.entrega}${statusBadge}</a>`;
                    } else {
                        entregaHtml = `<button class="btn-outline" style="font-size:0.75rem; padding:3px 8px; color:#d97706; border-color:#fde68a;" onclick="enviarParaLogistica(${v.id})">+ Alocar Logística</button>`;
                    }

                    const opDisplay = v.tipo_operacao_display || 'Recarga';
                    const pgtoDisplay = v.forma_pagamento_display || 'Boleto';

                    // Botões de Ação Dinâmicos
                    let acoesHtml = `
                        <button class="btn-outline" style="padding: 5px 10px; margin-right: 4px;" onclick="abrirDetalhes(${v.id})" title="Ver Recibo / Detalhes">Detalhes</button>
                    `;

                    if (v.status === 'Pendente') {
                        acoesHtml += `
                            <button class="btn-primary" style="padding: 5px 10px; font-size: 0.8rem; margin-right: 4px;" onclick="iniciarSeparacao(${v.id})" title="Iniciar Separação / Expedição">Separar</button>
                        `;
                    } else if (v.status === 'Em Separação' || v.status === 'Em Rota') {
                        acoesHtml += `
                            <button class="btn-primary" style="padding: 5px 10px; font-size: 0.8rem; background-color:#10b981; margin-right: 4px;" onclick="finalizarVenda(${v.id})" title="Finalizar Entrega / Venda">Finalizar</button>
                        `;
                    }

                    acoesHtml += `
                        <button class="btn-outline" style="padding: 5px 8px; color: #ef4444; border-color: #fecaca;" onclick="cancelarVenda(${v.id})" title="Cancelar Venda">✕</button>
                    `;

                    tbody.innerHTML += `
                        <tr>
                            <td><span style="font-weight: 700; color: var(--color-text);">#${v.id}</span></td>
                            <td><span style="font-weight: 500; color: var(--color-text-muted); font-size: 0.82rem;">${formatDate(v.data_venda)}</span></td>
                            <td>
                                <div style="font-weight: 600; color: var(--color-text);">${v.cliente_nome}</div>
                                <div style="font-size: 0.75rem; color: var(--color-text-muted);">${v.cliente_cnpj || ''}</div>
                            </td>
                            <td>
                                <div style="font-size: 0.82rem; font-weight: 600;">${opDisplay}</div>
                                <div style="font-size: 0.75rem; color: var(--color-text-muted);">${pgtoDisplay}</div>
                            </td>
                            <td>${entregaHtml}</td>
                            <td><span style="background: var(--color-hover); padding: 4px 8px; border-radius: 4px; font-size: 0.82rem; font-weight: 600;">${totalQtdItens} un</span></td>
                            <td style="font-weight: 700; color: var(--color-primary);">${formatCurrency(v.valor_total)}</td>
                            <td>${getStatusBadge(v.status)}</td>
                            <td style="text-align: right; white-space: nowrap;">${acoesHtml}</td>
                        </tr>
                    `;
                });
            })
            .catch(err => {
                console.error("Erro ao carregar vendas ativas:", err);
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#ef4444; padding:20px;">Erro ao carregar vendas ativas.</td></tr>';
            });
    }

    // ---- 3. Load Vendas Concluídas ----
    function loadVendasConcluidas() {
        const tbody = document.getElementById('tbody-concluidas');
        if (!tbody) return;

        fetch('/vendas/api/?grupo_status=concluidas', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const vendas = extrairListaDRF(data);
                tbody.innerHTML = '';
                if (vendas.length === 0) {
                    return renderEmptyState(tbody, 9, 'Nenhuma venda concluída', 'Vendas finalizadas ou entregues aparecerão nesta aba para consulta histórica e reimpressão de recibo.');
                }

                vendas.forEach(v => {
                    const totalQtdItens = v.itens ? v.itens.reduce((acc, item) => acc + (item.quantidade || 0), 0) : 0;
                    const entregaHtml = v.entrega ? `<span style="color:#059669; font-weight:600; font-size:0.8rem; background: rgba(16, 185, 129, 0.1); padding: 2px 6px; border-radius: 4px;">Entrega #${v.entrega}</span>` : `<span style="color:var(--color-text-muted); font-size:0.8rem;">Balcão</span>`;
                    
                    tbody.innerHTML += `
                        <tr>
                            <td><span style="font-weight: 700; color: var(--color-text);">#${v.id}</span></td>
                            <td><span style="font-weight: 500; color: var(--color-text-muted); font-size: 0.82rem;">${formatDate(v.data_venda)}</span></td>
                            <td>
                                <div style="font-weight: 600; color: var(--color-text);">${v.cliente_nome}</div>
                                <div style="font-size: 0.75rem; color: var(--color-text-muted);">${v.cliente_cnpj || ''}</div>
                            </td>
                            <td>
                                <div style="font-size: 0.82rem; font-weight: 600;">${v.tipo_operacao_display || 'Recarga'}</div>
                                <div style="font-size: 0.75rem; color: var(--color-text-muted);">${v.forma_pagamento_display || 'Boleto'}</div>
                            </td>
                            <td>${entregaHtml}</td>
                            <td><span style="background: var(--color-hover); padding: 4px 8px; border-radius: 4px; font-size: 0.82rem; font-weight: 600;">${totalQtdItens} un</span></td>
                            <td style="font-weight: 700; color: var(--color-primary);">${formatCurrency(v.valor_total)}</td>
                            <td>${getStatusBadge(v.status)}</td>
                            <td style="text-align: right;">
                                <button class="btn-outline" onclick="abrirDetalhes(${v.id})">Recibo / Detalhes</button>
                            </td>
                        </tr>
                    `;
                });
            })
            .catch(err => {
                console.error("Erro ao carregar finalizadas:", err);
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#ef4444; padding:20px;">Erro ao carregar vendas concluídas.</td></tr>';
            });
    }

    // ---- 4. Load Vendas Canceladas ----
    function loadVendasCanceladas() {
        const tbody = document.getElementById('tbody-canceladas');
        if (!tbody) return;

        fetch('/vendas/api/?grupo_status=canceladas', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const vendas = extrairListaDRF(data);
                tbody.innerHTML = '';
                if (vendas.length === 0) {
                    return renderEmptyState(tbody, 8, 'Nenhuma venda cancelada', 'Nenhum pedido cancelado no histórico deste tenant.');
                }

                vendas.forEach(v => {
                    const totalQtdItens = v.itens ? v.itens.reduce((acc, item) => acc + (item.quantidade || 0), 0) : 0;
                    tbody.innerHTML += `
                        <tr>
                            <td><span style="font-weight: 700; color: var(--color-text);">#${v.id}</span></td>
                            <td><span style="font-weight: 500; color: var(--color-text-muted); font-size: 0.82rem;">${formatDate(v.data_venda)}</span></td>
                            <td>
                                <div style="font-weight: 600; color: var(--color-text);">${v.cliente_nome}</div>
                                <div style="font-size: 0.75rem; color: var(--color-text-muted);">${v.cliente_cnpj || ''}</div>
                            </td>
                            <td>
                                <div style="font-size: 0.82rem;">${v.tipo_operacao_display || 'Venda'}</div>
                            </td>
                            <td><span style="background: var(--color-hover); padding: 4px 8px; border-radius: 4px; font-size: 0.82rem; font-weight: 600;">${totalQtdItens} un</span></td>
                            <td style="font-weight: 700; color: var(--color-text-muted);">${formatCurrency(v.valor_total)}</td>
                            <td>${getStatusBadge(v.status)}</td>
                            <td style="text-align: right;">
                                <button class="btn-outline" onclick="abrirDetalhes(${v.id})">Detalhes</button>
                            </td>
                        </tr>
                    `;
                });
            })
            .catch(err => {
                console.error("Erro ao carregar canceladas:", err);
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:#ef4444; padding:20px;">Erro ao carregar vendas canceladas.</td></tr>';
            });
    }

    // ---- Ações da Tabela de Vendas ----
    window.iniciarSeparacao = function(id) {
        fetch(`/vendas/api/${id}/alterar_status/`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ status: 'Em Separação', gerar_entrega_logistica: true })
        })
        .then(res => res.json())
        .then(data => {
            Swal.fire({
                icon: 'success',
                title: 'Separação Iniciada',
                text: 'Pedido movido para Em Separação e agendado na Logística.',
                timer: 1600,
                showConfirmButton: false
            });
            loadVendasAtivas();
            loadDashboard();
        })
        .catch(err => Swal.fire('Erro', 'Não foi possível iniciar a separação.', 'error'));
    };

    window.enviarParaLogistica = function(id) {
        fetch(`/vendas/api/${id}/enviar_para_logistica/`, {
            method: 'POST',
            headers: getAuthHeaders()
        })
        .then(res => res.json())
        .then(data => {
            Swal.fire({
                icon: 'success',
                title: 'Alocado na Logística',
                text: `Pedido vinculado à Entrega #${data.entrega_id}.`,
                timer: 1600,
                showConfirmButton: false
            });
            loadVendasAtivas();
        })
        .catch(err => Swal.fire('Erro', 'Não foi possível alocar na logística.', 'error'));
    };

    window.finalizarVenda = function(id) {
        Swal.fire({
            title: 'Finalizar Venda?',
            text: 'Confirma a conclusão e faturamento deste pedido?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#10b981',
            confirmButtonText: 'Sim, Finalizar'
        }).then((result) => {
            if (result.isConfirmed) {
                fetch(`/vendas/api/${id}/alterar_status/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ status: 'Finalizada' })
                })
                .then(res => {
                    if (res.ok) {
                        Swal.fire({ icon: 'success', title: 'Venda Finalizada!', timer: 1400, showConfirmButton: false });
                        loadVendasAtivas();
                        loadDashboard();
                    } else {
                        Swal.fire('Erro', 'Não foi possível finalizar a venda.', 'error');
                    }
                });
            }
        });
    };

    window.cancelarVenda = function(id) {
        Swal.fire({
            title: 'Cancelar Pedido?',
            text: 'Esta ação marcará a venda como Cancelada.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#ef4444',
            confirmButtonText: 'Sim, Cancelar'
        }).then((result) => {
            if (result.isConfirmed) {
                fetch(`/vendas/api/${id}/alterar_status/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ status: 'Cancelada' })
                })
                .then(res => {
                    if (res.ok) {
                        Swal.fire({ icon: 'success', title: 'Venda Cancelada', timer: 1400, showConfirmButton: false });
                        loadVendasAtivas();
                        loadDashboard();
                    } else {
                        Swal.fire('Erro', 'Não foi possível cancelar o pedido.', 'error');
                    }
                });
            }
        });
    };

    // ---- Detalhes da Venda (Modal Recibo A4) ----
    const modalDetalhes = document.getElementById('modal-detalhes-venda');
    if (document.getElementById('btn-fechar-detalhes')) {
        document.getElementById('btn-fechar-detalhes').onclick = () => modalDetalhes.classList.remove('active');
    }

    window.abrirDetalhes = function(id) {
        fetch(`/vendas/api/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('detalhe-id').textContent = data.id;
                document.getElementById('detalhe-cliente').textContent = data.cliente_nome;
                document.getElementById('detalhe-cnpj').textContent = data.cliente_cnpj || 'Não informado';
                document.getElementById('detalhe-status').textContent = data.status;
                document.getElementById('detalhe-operacao').textContent = data.tipo_operacao_display || 'Venda';
                document.getElementById('detalhe-pagamento').textContent = `${data.forma_pagamento_display || 'Boleto'} (${data.condicao_pagamento || 'À Vista'})`;
                document.getElementById('detalhe-logistica').textContent = data.entrega ? `Entrega #${data.entrega} (${data.entrega_status || 'Agendada'})` : 'Retirada Balcão';
                document.getElementById('detalhe-data').textContent = formatDate(data.data_venda);
                document.getElementById('detalhe-prazo').textContent = formatDateOnly(data.prazo_entrega);
                document.getElementById('detalhe-total').textContent = formatCurrency(data.valor_total);

                const obsElement = document.getElementById('detalhe-obs');
                if (obsElement) {
                    obsElement.textContent = data.observacoes ? `Observações: ${data.observacoes}` : '';
                }

                const tbody = document.getElementById('detalhe-itens-tbody');
                tbody.innerHTML = '';
                const itens = extrairListaDRF(data.itens);
                if (itens && itens.length > 0) {
                    itens.forEach(i => {
                        const nomeItem = i.produto_nome || i.sku_nome || 'Item do Pedido';
                        tbody.innerHTML += `
                            <tr style="border-bottom: 1px dotted var(--color-border);">
                                <td style="padding: 8px 10px;">${nomeItem}</td>
                                <td style="padding: 8px 10px; text-align: center;">${i.quantidade}</td>
                                <td style="padding: 8px 10px; text-align: right;">${formatCurrency(i.valor_unitario)}</td>
                                <td style="padding: 8px 10px; text-align: right; font-weight:600;">${formatCurrency(i.valor_total)}</td>
                            </tr>
                        `;
                    });
                } else {
                    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:12px;">Nenhum item associado a esta venda.</td></tr>';
                }
                modalDetalhes.classList.add('active');
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Não foi possível carregar os detalhes da venda.', 'error');
            });
    };

    // ==========================================
    // Nova Venda Modal (Redesign & Cálculo em Tempo Real)
    // ==========================================
    const modalVenda = document.getElementById('modal-venda');
    const btnNova = document.getElementById('btn-nova-venda');
    const btnFecharNova = document.getElementById('btn-fechar-modal-venda');
    const btnCancelarNova = document.getElementById('btn-cancelar-venda');
    const formVenda = document.getElementById('form-venda');
    const selectCliente = document.getElementById('cliente');
    const btnAddItem = document.getElementById('btn-add-item');
    const itensContainer = document.getElementById('itens-container');
    const inputDesconto = document.getElementById('valor_desconto');
    const alertaSanitario = document.getElementById('alerta-sanitario-modal');

    let clientesMap = {};
    let produtosDisponiveis = [];

    btnNova.addEventListener('click', () => {
        modalVenda.classList.add('active');
        carregarClientes();
        carregarProdutos();
    });

    btnFecharNova.addEventListener('click', () => modalVenda.classList.remove('active'));
    btnCancelarNova.addEventListener('click', () => modalVenda.classList.remove('active'));

    function carregarClientes() {
        selectCliente.innerHTML = '<option value="">Carregando clientes...</option>';
        fetch('/clientes/api/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(r => r.json())
            .then(data => {
                const clientes = extrairListaDRF(data);
                clientesMap = {};
                selectCliente.innerHTML = '<option value="">Selecione um cliente...</option>';
                clientes.forEach(c => {
                    clientesMap[c.id] = c;
                    const tagMedicinal = c.is_medicinal ? ' [Medicinal]' : '';
                    selectCliente.innerHTML += `<option value="${c.id}">${c.nome} (${c.cnpj})${tagMedicinal}</option>`;
                });
            })
            .catch(err => {
                selectCliente.innerHTML = '<option value="">Erro ao carregar clientes</option>';
            });
    }

    function carregarProdutos() {
        fetch('/produtos/api/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(r => r.json())
            .then(data => {
                produtosDisponiveis = extrairListaDRF(data);
                // Se o container estiver vazio, adiciona a primeira linha
                if (itensContainer.children.length === 0) {
                    adicionarLinhaItem();
                } else {
                    atualizarSelectsProdutos();
                }
            })
            .catch(err => console.error("Erro ao carregar produtos:", err));
    }

    function gerarOptionsProdutosHtml() {
        let html = '<option value="">Selecione o produto...</option>';
        produtosDisponiveis.forEach(p => {
            const badgeCat = p.categoria ? ` [${p.categoria}]` : '';
            html += `<option value="${p.id}" data-preco="${p.preco || 0}" data-peso="${p.capacidade || 1}" data-cat="${p.categoria || ''}">
                ${p.nome}${badgeCat} — R$ ${p.preco} (Estoque: ${p.estoque || 0})
            </option>`;
        });
        return html;
    }

    function atualizarSelectsProdutos() {
        const optionsHtml = gerarOptionsProdutosHtml();
        itensContainer.querySelectorAll('.produto-select').forEach(select => {
            const val = select.value;
            select.innerHTML = optionsHtml;
            if (val) select.value = val;
        });
    }

    function adicionarLinhaItem() {
        const row = document.createElement('div');
        row.className = 'item-grid-row';
        row.innerHTML = `
            <div style="flex: 2.6;">
                <select class="produto-select" required>
                    ${gerarOptionsProdutosHtml()}
                </select>
            </div>
            <div style="flex: 1.5;">
                <select class="forma-faturamento" required>
                    <option value="cilindro">Por Cilindro</option>
                    <option value="medida">Por Medida (m³/kg)</option>
                </select>
            </div>
            <div style="flex: 0.9;">
                <input type="number" class="item-qtd" value="1" min="1" required>
            </div>
            <div style="flex: 1.2;">
                <input type="number" step="0.01" class="item-valor" placeholder="0.00" required>
            </div>
            <div style="flex: 1.3;">
                <input type="text" class="item-subtotal" value="R$ 0,00" readonly>
            </div>
            <div style="width: 44px; text-align: center;">
                <button type="button" class="btn-remove-row" title="Remover item">✕</button>
            </div>
        `;
        itensContainer.appendChild(row);

        // Eventos da Linha
        const selectProd = row.querySelector('.produto-select');
        const selectForma = row.querySelector('.forma-faturamento');
        const inputQtd = row.querySelector('.item-qtd');
        const inputVal = row.querySelector('.item-valor');
        const btnRemover = row.querySelector('.btn-remove-row');

        selectProd.addEventListener('change', () => {
            const opt = selectProd.options[selectProd.selectedIndex];
            if (opt && opt.value) {
                inputVal.value = opt.getAttribute('data-preco') || '0.00';
            }
            recalcularLinha(row);
            checarAlertaSanitario();
        });

        selectForma.addEventListener('change', () => recalcularLinha(row));
        inputQtd.addEventListener('input', () => recalcularLinha(row));
        inputVal.addEventListener('input', () => recalcularLinha(row));

        btnRemover.addEventListener('click', () => {
            if (itensContainer.children.length > 1) {
                row.remove();
                atualizarBotoesRemover();
                recalcularTotalPedido();
                checarAlertaSanitario();
            }
        });

        atualizarBotoesRemover();
        recalcularLinha(row);
    }

    function atualizarBotoesRemover() {
        const rows = itensContainer.querySelectorAll('.item-grid-row');
        const canRemove = rows.length > 1;
        rows.forEach(r => {
            const btn = r.querySelector('.btn-remove-row');
            if (btn) btn.disabled = !canRemove;
        });
    }

    function recalcularLinha(row) {
        const selectProd = row.querySelector('.produto-select');
        const selectForma = row.querySelector('.forma-faturamento');
        const inputQtd = row.querySelector('.item-qtd');
        const inputVal = row.querySelector('.item-valor');
        const inputSubtotal = row.querySelector('.item-subtotal');

        const opt = selectProd.options[selectProd.selectedIndex];
        const precoUn = parseFloat(inputVal.value) || 0;
        const qtd = parseInt(inputQtd.value) || 0;
        const peso = parseFloat(opt ? opt.getAttribute('data-peso') : 1) || 1;
        const forma = selectForma.value;

        let subtotal = 0;
        if (forma === 'medida') {
            subtotal = qtd * peso * precoUn;
        } else {
            subtotal = qtd * precoUn;
        }

        inputSubtotal.value = formatCurrency(subtotal);
        inputSubtotal.setAttribute('data-valor-bruto', subtotal.toFixed(2));
        recalcularTotalPedido();
    }

    function recalcularTotalPedido() {
        let subtotalGeral = 0;
        itensContainer.querySelectorAll('.item-subtotal').forEach(el => {
            subtotalGeral += parseFloat(el.getAttribute('data-valor-bruto') || 0);
        });

        const desconto = parseFloat(inputDesconto.value) || 0;
        const totalFinal = Math.max(0, subtotalGeral - desconto);

        document.getElementById('summary-subtotal').textContent = formatCurrency(subtotalGeral);
        document.getElementById('summary-total').textContent = formatCurrency(totalFinal);
    }

    inputDesconto.addEventListener('input', recalcularTotalPedido);

    // Validação Sanitária Preventiva (ANVISA)
    function checarAlertaSanitario() {
        const clienteId = selectCliente.value;
        const cliente = clientesMap[clienteId];
        let possuiProdutoMedicinal = false;

        itensContainer.querySelectorAll('.produto-select').forEach(sel => {
            const opt = sel.options[sel.selectedIndex];
            if (opt && opt.getAttribute('data-cat') === 'Medicinal') {
                possuiProdutoMedicinal = true;
            }
        });

        if (possuiProdutoMedicinal && cliente && !cliente.is_medicinal && cliente.tipo_cliente !== 'GOV') {
            alertaSanitario.style.display = 'flex';
        } else {
            alertaSanitario.style.display = 'none';
        }
    }

    selectCliente.addEventListener('change', checarAlertaSanitario);
    btnAddItem.addEventListener('click', adicionarLinhaItem);

    // Submissão do Formulário de Venda
    formVenda.addEventListener('submit', function(e) {
        e.preventDefault();

        const clienteId = selectCliente.value;
        if (!clienteId) {
            Swal.fire('Atenção', 'Selecione um cliente para prosseguir.', 'warning');
            return;
        }

        const rows = itensContainer.querySelectorAll('.item-grid-row');
        const itensPayload = [];

        rows.forEach(row => {
            const selectProd = row.querySelector('.produto-select');
            const selectForma = row.querySelector('.forma-faturamento');
            const inputQtd = row.querySelector('.item-qtd');
            const inputVal = row.querySelector('.item-valor');

            if (selectProd.value) {
                const opt = selectProd.options[selectProd.selectedIndex];
                itensPayload.push({
                    produto: parseInt(selectProd.value),
                    forma_faturamento: selectForma.value,
                    quantidade: parseInt(inputQtd.value) || 1,
                    peso_unitario: parseFloat(opt.getAttribute('data-peso') || 0),
                    valor_unitario: parseFloat(inputVal.value || 0)
                });
            }
        });

        if (itensPayload.length === 0) {
            Swal.fire('Atenção', 'Adicione pelo menos um produto na venda.', 'warning');
            return;
        }

        const submitBtn = document.getElementById('btn-submit-venda');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Gravando...';

        const payload = {
            cliente: parseInt(clienteId),
            tipo_operacao: document.getElementById('tipo_operacao').value,
            forma_pagamento: document.getElementById('forma_pagamento').value,
            condicao_pagamento: document.getElementById('condicao_pagamento').value || 'À Vista',
            valor_desconto: parseFloat(inputDesconto.value) || 0.00,
            documento_fiscal_ref: document.getElementById('documento_fiscal_ref').value || null,
            observacoes: document.getElementById('observacoes').value || null,
            prazo_entrega: document.getElementById('prazo_entrega').value || null,
            gerar_entrega_logistica: document.getElementById('gerar_entrega_logistica').checked,
            status: 'Pendente',
            itens: itensPayload
        };

        fetch('/vendas/api/', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify(payload)
        })
        .then(async res => {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Concluir e Registrar Pedido';

            if (res.ok) {
                const vendaCriada = await res.json();
                Swal.fire({
                    icon: 'success',
                    title: 'Venda Registrada!',
                    text: `Pedido #${vendaCriada.id} emitido com sucesso.${vendaCriada.entrega ? ` Agendado na Entrega #${vendaCriada.entrega}.` : ''}`,
                    timer: 2000,
                    showConfirmButton: false
                });

                modalVenda.classList.remove('active');
                formVenda.reset();
                itensContainer.innerHTML = '';
                adicionarLinhaItem();
                alertaSanitario.style.display = 'none';

                loadDashboard();
                if (currentTab === 'tab-ativas') loadVendasAtivas();
            } else {
                const err = await res.json();
                Swal.fire('Erro na Emissão', JSON.stringify(err), 'error');
            }
        })
        .catch(err => {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Concluir e Registrar Pedido';
            console.error(err);
            Swal.fire('Erro', 'Ocorreu um erro de comunicação com o servidor.', 'error');
        });
    });

    // Início padrão
    loadDashboard();
});
