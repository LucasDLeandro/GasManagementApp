document.addEventListener('DOMContentLoaded', () => {
    // ---- Autenticação via JWT ----
    function getAuthHeaders() {
        const token = localStorage.getItem('access_token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }

    // ---- Sistema de Abas ----
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));
            
            btn.classList.add('active');
            const target = btn.getAttribute('data-target');
            document.getElementById(target).classList.add('active');
            
            // Carregar dados de acordo com a aba
            if(target === 'tab-entregas') loadKanban();
            if(target === 'tab-veiculos') loadVeiculos();
            if(target === 'tab-rotas') loadRotas();
        });
    });

    // ---- 1. Kanban de Entregas (Lendo do app Vendas) ----
    function formatCurrency(value) { return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value); }
    function formatDate(dateStr) { return new Date(dateStr).toLocaleString('pt-BR'); }

    function loadKanban() {
        fetch('/vendas/api/?status=Em Separação,Em Rota,Entregue', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const colSep = document.querySelector('#col-separacao .kanban-items');
                const colRota = document.querySelector('#col-rota .kanban-items');
                const colEntregue = document.querySelector('#col-entregue .kanban-items');

                colSep.innerHTML = ''; colRota.innerHTML = ''; colEntregue.innerHTML = '';

                data.forEach(v => {
                    const card = `
                        <div class="kanban-item">
                            <strong>#${v.id} - ${v.cliente_nome}</strong><br>
                            <small>${formatDate(v.data_venda)}</small><br>
                            <strong>${formatCurrency(v.valor_total)}</strong>
                            <div style="margin-top:10px;">
                                <button class="btn-primary" style="width:100%; padding:4px; margin-bottom:5px; background:var(--color-text-muted);" onclick="abrirDetalhes(${v.id})">Ver Detalhes</button>
                                ${v.status === 'Em Separação' ? `<button class="btn-primary" style="width:100%; padding:4px;" onclick="mudarStatusVenda(${v.id}, 'Em Rota')">Enviar p/ Rota</button>` : ''}
                                ${v.status === 'Em Rota' ? `<button class="btn-primary" style="width:100%; padding:4px; background:#10b981;" onclick="mudarStatusVenda(${v.id}, 'Entregue')">Marcar Entregue</button>` : ''}
                                ${v.status === 'Entregue' ? `<button class="btn-primary" style="width:100%; padding:4px; background:var(--color-text-muted);" onclick="mudarStatusVenda(${v.id}, 'Finalizada')">Finalizar Venda</button>` : ''}
                            </div>
                        </div>
                    `;
                    if (v.status === 'Em Separação') colSep.innerHTML += card;
                    if (v.status === 'Em Rota') colRota.innerHTML += card;
                    if (v.status === 'Entregue') colEntregue.innerHTML += card;
                });
            });
    }

    window.mudarStatusVenda = async function(id, novoStatus) {
        try {
            const res = await fetch(`/vendas/api/${id}/mudar_status/`, {
                method: 'PATCH',
                headers: getAuthHeaders(),
                body: JSON.stringify({ status: novoStatus })
            });
            if (res.ok) {
                Swal.fire({ title: 'Status Atualizado!', icon: 'success', timer: 1500, showConfirmButton: false });
                loadKanban();
            } else {
                throw new Error("Erro ao atualizar.");
            }
        } catch (error) {
            Swal.fire('Erro', error.message, 'error');
        }
    };

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
            filename:     `Romaneio_Entrega_${document.getElementById('detalhe-id').textContent}.pdf`,
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

    // ---- 2. Frota / Veículos ----
    function loadVeiculos() {
        fetch('/logistica/api/veiculos/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const tbody = document.getElementById('tbody-veiculos');
                tbody.innerHTML = '';
                if(data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Nenhum veículo cadastrado.</td></tr>';
                    return;
                }
                data.forEach(v => {
                    const badgeClass = v.status === 'Ativo' ? 'ativo' : (v.status === 'Em Manutenção' ? 'manutencao' : '');
                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${v.placa}</strong></td>
                            <td>${v.modelo} / ${v.marca}</td>
                            <td>${v.ano}</td>
                            <td>${v.capacidade_carga} kg</td>
                            <td><span class="badge ${badgeClass}">${v.status}</span></td>
                        </tr>
                    `;
                });
            });
    }

    const modalVeiculo = document.getElementById('modal-veiculo');
    document.getElementById('btn-novo-veiculo').onclick = () => modalVeiculo.classList.add('active');
    document.getElementById('btn-fechar-modal-veiculo').onclick = () => modalVeiculo.classList.remove('active');
    
    document.getElementById('form-veiculo').onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const data = Object.fromEntries(formData.entries());

        const res = await fetch('/logistica/api/veiculos/', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify(data)
        });

        if(res.ok) {
            Swal.fire('Sucesso', 'Veículo cadastrado!', 'success');
            modalVeiculo.classList.remove('active');
            e.target.reset();
            loadVeiculos();
        } else {
            Swal.fire('Erro', 'Erro ao cadastrar.', 'error');
        }
    };

    // ---- 3. Rotas ----
    function loadRotas() {
        fetch('/logistica/api/rotas/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const tbody = document.getElementById('tbody-rotas');
                tbody.innerHTML = '';
                if(data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Nenhuma rota cadastrada.</td></tr>';
                    return;
                }
                data.forEach(r => {
                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${r.nome}</strong></td>
                            <td>${r.origem}</td>
                            <td>${r.destino}</td>
                            <td>${r.distancia_km} km</td>
                            <td>${r.tempo_estimado_horas} h</td>
                        </tr>
                    `;
                });
            });
    }

    const modalRota = document.getElementById('modal-rota');
    document.getElementById('btn-nova-rota').onclick = () => modalRota.classList.add('active');
    document.getElementById('btn-fechar-modal-rota').onclick = () => modalRota.classList.remove('active');
    
    document.getElementById('form-rota').onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const data = Object.fromEntries(formData.entries());

        const res = await fetch('/logistica/api/rotas/', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify(data)
        });

        if(res.ok) {
            Swal.fire('Sucesso', 'Rota cadastrada!', 'success');
            modalRota.classList.remove('active');
            e.target.reset();
            loadRotas();
        } else {
            Swal.fire('Erro', 'Erro ao cadastrar.', 'error');
        }
    };

    // Init
    loadKanban();
});
