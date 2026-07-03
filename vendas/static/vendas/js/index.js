document.addEventListener('DOMContentLoaded', function() {
    // ---- Tabs Logic ----
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            const target = btn.getAttribute('data-target');
            document.getElementById(target).classList.add('active');

            // Refresh data based on active tab
            if(target === 'tab-dashboard') loadDashboard();
            if(target === 'tab-pendentes') loadVendasPendentes();
            if(target === 'tab-finalizadas') loadFinalizadas();
        });
    });

    // ---- API Auth Header ----
    function getAuthHeaders() {
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

        const headers = {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        };
        const token = localStorage.getItem('access') || localStorage.getItem('access_token');
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }

    // ---- Utils ----
    function formatCurrency(val) {
        return parseFloat(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    }
    function formatDate(dateStr) {
        const d = new Date(dateStr);
        return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
    }

    // ---- Chart Instance ----
    let vendasChartInstance = null;
    let categoriaChartInstance = null;

    // ---- Load Dashboard ----
    function loadDashboard() {
        fetch('/vendas/api/dashboard_metrics/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('metric-faturamento').textContent = formatCurrency(data.faturamento_total);
                document.getElementById('metric-total-vendas').textContent = data.total_vendas;
                document.getElementById('metric-pendentes').textContent = data.vendas_pendentes;
                document.getElementById('metric-entrega').textContent = data.vendas_em_entrega;

                // Novas Métricas
                document.getElementById('metric-ticket-medio').textContent = formatCurrency(data.ticket_medio);
                
                const listaTop = document.getElementById('lista-top-produtos');
                listaTop.innerHTML = '';
                if(data.top_produtos && data.top_produtos.length > 0) {
                    data.top_produtos.forEach((p, idx) => {
                        listaTop.innerHTML += `<li style="font-size: 0.9rem; color: var(--color-text); padding: 8px 0; border-bottom: 1px solid var(--color-border); display: flex; justify-content: space-between;">
                            <span><strong>#${idx+1}</strong> ${p.nome}</span>
                            <span style="color: var(--color-text-muted);">${p.total_qtd} un</span>
                        </li>`;
                    });
                } else {
                    listaTop.innerHTML = '<li style="font-size: 0.9rem; color: var(--color-text-muted);">Nenhum dado.</li>';
                }

                // Render Chart 1 (Evolução)
                const ctx = document.getElementById('vendasChart').getContext('2d');
                const labels = data.grafico.map(item => item.dia);
                const values = data.grafico.map(item => item.total);

                if (vendasChartInstance) {
                    vendasChartInstance.destroy();
                }
                
                let gradient = ctx.createLinearGradient(0, 0, 0, 300);
                gradient.addColorStop(0, 'rgba(59, 130, 246, 0.4)');
                gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

                vendasChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Faturamento (R$)',
                            data: values,
                            borderColor: '#3b82f6',
                            backgroundColor: gradient,
                            fill: true,
                            tension: 0.4,
                            pointBackgroundColor: '#ffffff',
                            pointBorderColor: '#3b82f6',
                            pointBorderWidth: 2,
                            pointRadius: 4,
                            pointHoverRadius: 6
                        }]
                    },
                    options: { responsive: true, maintainAspectRatio: false }
                });

                // Render Chart 2 (Categoria)
                const ctxCat = document.getElementById('categoriaChart').getContext('2d');
                if (categoriaChartInstance) categoriaChartInstance.destroy();

                const catLabels = data.vendas_por_categoria.map(c => c.categoria);
                const catValues = data.vendas_por_categoria.map(c => c.total_vendido);

                categoriaChartInstance = new Chart(ctxCat, {
                    type: 'doughnut',
                    data: {
                        labels: catLabels,
                        datasets: [{
                            data: catValues,
                            backgroundColor: ['#10b981', '#3b82f6', '#f59e0b', '#8b5cf6'],
                            borderWidth: 0
                        }]
                    },
                    options: { 
                        responsive: true, 
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'bottom' }
                        },
                        cutout: '70%'
                    }
                });
            });
    }

    // ---- Load Pendentes ----
    function loadVendasPendentes() {
        fetch('/vendas/api/?status=Pendente', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const tbody = document.getElementById('tbody-pendentes');
                tbody.innerHTML = '';
                if(data.length === 0) return tbody.innerHTML = '<tr><td colspan="5">Nenhuma venda pendente.</td></tr>';
                
                data.forEach(v => {
                    let badgeClass = 'badge-pendente';
                    if (v.status === 'Em Separação') badgeClass = 'badge-separacao';
                    
                    tbody.innerHTML += `
                        <tr>
                            <td><span style="font-weight: 500; color: var(--color-text-muted);">${formatDate(v.data_venda)}</span></td>
                            <td style="font-weight: 500;">${v.cliente_nome}</td>
                            <td style="font-weight: 600;">${formatCurrency(v.valor_total)}</td>
                            <td><span class="badge ${badgeClass}">${v.status}</span></td>
                            <td>
                                <button class="btn-outline" style="margin-right: 8px;" onclick="abrirDetalhes(${v.id})">Detalhes</button>
                                <button class="btn-primary" style="padding:6px 12px; font-size:12px;" onclick="iniciarSeparacao(${v.id})">Iniciar Separação</button>
                            </td>
                        </tr>
                    `;
                });
            });
    }

    window.iniciarSeparacao = function(id) {
        mudarStatus(id, 'Em Separação', () => { loadVendasPendentes(); });
    }

    // ---- Load Finalizadas ----
    function loadFinalizadas() {
        fetch('/vendas/api/?status=Finalizada', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const tbody = document.getElementById('tbody-finalizadas');
                tbody.innerHTML = '';
                if(data.length === 0) return tbody.innerHTML = '<tr><td colspan="4">Nenhuma venda finalizada.</td></tr>';
                
                data.forEach(v => {
                    tbody.innerHTML += `
                        <tr>
                            <td><span style="font-weight: 500; color: var(--color-text-muted);">${formatDate(v.data_venda)}</span></td>
                            <td style="font-weight: 500;">${v.cliente_nome}</td>
                            <td style="font-weight: 600;">${formatCurrency(v.valor_total)}</td>
                            <td><span class="badge badge-finalizada">${v.status}</span></td>
                            <td>
                                <button class="btn-outline" onclick="abrirDetalhes(${v.id})">Detalhes</button>
                            </td>
                        </tr>
                    `;
                });
            });
    }

    // ---- Mudar Status ----
    window.mudarStatus = function(id, novoStatus, callback) {
        fetch(`/vendas/api/${id}/alterar_status/`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ status: novoStatus })
        })
        .then(res => {
            if(res.ok) {
                Swal.fire({icon:'success', title:'Status Atualizado', text:`Venda movida para ${novoStatus}`, timer:1500, showConfirmButton:false});
                if(callback) callback();
            } else {
                Swal.fire('Erro', 'Não foi possível alterar status', 'error');
            }
        });
    }

    // ---- Detalhes da Venda ----
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
                document.getElementById('detalhe-cnpj').textContent = data.cliente_cnpj || 'N/D';
                document.getElementById('detalhe-status').textContent = data.status;
                document.getElementById('detalhe-data').textContent = formatDate(data.data_venda);
                document.getElementById('detalhe-prazo').textContent = data.prazo_entrega ? formatDate(data.prazo_entrega) : 'Não definido';
                document.getElementById('detalhe-efetiva').textContent = data.data_entrega_efetiva ? formatDate(data.data_entrega_efetiva) : 'Pendente';
                document.getElementById('detalhe-total').textContent = formatCurrency(data.valor_total);

                const tbody = document.getElementById('detalhe-itens-tbody');
                tbody.innerHTML = '';
                if(data.itens && data.itens.length > 0) {
                    data.itens.forEach(i => {
                        tbody.innerHTML += `
                            <tr style="border-bottom: 1px dotted #000;">
                                <td style="padding: 6px; border-right: 1px dotted #000;">${i.produto_nome}</td>
                                <td style="padding: 6px; text-align: center; border-right: 1px dotted #000;">${i.quantidade}</td>
                                <td style="padding: 6px; text-align: right; border-right: 1px dotted #000;">${formatCurrency(i.valor_unitario)}</td>
                                <td style="padding: 6px; text-align: right;">${formatCurrency(i.valor_total)}</td>
                            </tr>
                        `;
                    });
                } else {
                    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;">Nenhum item encontrado.</td></tr>';
                }
                modalDetalhes.classList.add('active');
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Erro ao carregar detalhes.', 'error');
            });
    }

    // ---- Gerar PDF ----
    window.gerarPDF = function() {
        const elemento = document.getElementById('conteudo-recibo');
        const botoes = elemento.querySelector('#detalhes-header div');
        
        // Hide buttons for printing
        botoes.style.display = 'none';

        // Fixar largura exata para caber no A4 sem cortar bordas
        const originalMaxWidth = elemento.style.maxWidth;
        const originalWidth = elemento.style.width;
        elemento.style.maxWidth = 'none';
        elemento.style.width = '790px';

        const opt = {
            margin:       10,
            filename:     `Recibo_Venda_${document.getElementById('detalhe-id').textContent}.pdf`,
            image:        { type: 'jpeg', quality: 1 },
            html2canvas:  { scale: 2, windowWidth: 810 },
            jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
        };

        html2pdf().set(opt).from(elemento).save().then(() => {
            // Restore styles and buttons
            elemento.style.maxWidth = originalMaxWidth;
            elemento.style.width = originalWidth;
            botoes.style.display = 'flex';
        });
    }

    // ---- Init ----
    loadDashboard();


    // ==========================================
    // Nova Venda Modal
    // ==========================================
    const modalVenda = document.getElementById('modal-venda');
    const btnNova = document.getElementById('btn-nova-venda');
    const btnFecharNova = document.getElementById('btn-fechar-modal-venda');
    const btnCancelarNova = document.getElementById('btn-cancelar-venda');
    const formVenda = document.getElementById('form-venda');
    const selectCliente = document.getElementById('cliente');
    const btnAddItem = document.getElementById('btn-add-item');
    const itensContainer = document.getElementById('itens-container');

    // Listas pré-carregadas para o select
    let produtosDisponiveis = [];

    btnNova.addEventListener('click', () => {
        modalVenda.classList.add('active');
        carregarClientes();
        carregarProdutos();
    });

    btnFecharNova.addEventListener('click', () => modalVenda.classList.remove('active'));
    btnCancelarNova.addEventListener('click', () => modalVenda.classList.remove('active'));

    function carregarClientes() {
        fetch('/clientes/api/', { headers: getAuthHeaders() })
            .then(r => r.json())
            .then(data => {
                selectCliente.innerHTML = '<option value="">Selecione...</option>';
                data.forEach(c => selectCliente.innerHTML += `<option value="${c.id}">${c.nome} (${c.cnpj})</option>`);
            });
    }

    function carregarProdutos() {
        fetch('/produtos/api/', { headers: getAuthHeaders() })
            .then(r => r.json())
            .then(data => {
                produtosDisponiveis = data;
                // Popula o primeiro select que já está na tela
                const firstSelect = document.querySelector('.produto-select');
                if (firstSelect) {
                    firstSelect.innerHTML = '<option value="">Selecione...</option>';
                    data.forEach(p => {
                        // Salvar info extras no option via data-* para fácil acesso
                        firstSelect.innerHTML += `<option value="${p.id}" data-preco="${p.preco}" data-peso="${p.capacidade}">
                            ${p.nome} - R$ ${p.preco} (Estoque: ${p.estoque})
                        </option>`;
                    });
                }
            });
    }

    btnAddItem.addEventListener('click', () => {
        const itemRow = document.createElement('div');
        itemRow.className = 'item-row';
        itemRow.style.cssText = 'display:flex; gap:10px; margin-bottom:10px;';
        
        let optionsHtml = '<option value="">Selecione...</option>';
        produtosDisponiveis.forEach(p => {
            optionsHtml += `<option value="${p.id}" data-preco="${p.preco}" data-peso="${p.capacidade}">
                ${p.nome} - R$ ${p.preco} (Estoque: ${p.estoque})
            </option>`;
        });

        itemRow.innerHTML = `
            <div class="form-group" style="flex:2;">
                <select class="produto-select" required>${optionsHtml}</select>
            </div>
            <div class="form-group" style="flex:1;">
                <input type="number" class="item-qtd" value="1" min="1" required>
            </div>
            <button type="button" class="btn-remove-item" style="background:#ef4444; color:var(--color-surface); border:none; border-radius:6px; cursor:pointer; padding:0 10px;">X</button>
        `;
        itensContainer.appendChild(itemRow);

        itemRow.querySelector('.btn-remove-item').addEventListener('click', () => itemRow.remove());
    });

    formVenda.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const clienteId = selectCliente.value;
        const rows = document.querySelectorAll('.item-row');
        const itens = [];

        rows.forEach(row => {
            const select = row.querySelector('.produto-select');
            const qtd = row.querySelector('.item-qtd').value;
            const option = select.options[select.selectedIndex];
            
            if (select.value) {
                itens.push({
                    produto: select.value,
                    quantidade: parseInt(qtd),
                    peso_unitario: parseFloat(option.getAttribute('data-peso') || 0),
                    valor_unitario: parseFloat(option.getAttribute('data-preco') || 0)
                });
            }
        });

        if (itens.length === 0) {
            Swal.fire('Aviso', 'Adicione pelo menos um produto.', 'warning');
            return;
        }

        const payload = {
            cliente: clienteId,
            status: 'Pendente',
            itens: itens
            // Vendedor pode ser pego do request.user no backend. Como temos null=True temporariamente, vamos mandar assim.
        };

        fetch('/vendas/api/', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify(payload)
        })
        .then(async res => {
            if (res.ok) {
                Swal.fire('Sucesso', 'Venda registrada com sucesso!', 'success');
                modalVenda.classList.remove('active');
                formVenda.reset();
                // Limpa itens extras
                const extraRows = document.querySelectorAll('.item-row:not(:first-child)');
                extraRows.forEach(r => r.remove());
                
                loadDashboard();
                loadVendasPendentes();
            } else {
                const err = await res.json();
                Swal.fire('Erro', JSON.stringify(err), 'error');
            }
        })
        .catch(err => console.error(err));
    });

});
