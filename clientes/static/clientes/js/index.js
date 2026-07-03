document.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('modal-cliente');
    const btnNovo = document.getElementById('btn-novo-cliente');
    const btnFechar = document.getElementById('btn-fechar-modal');
    const btnCancelar = document.getElementById('btn-cancelar');
    const form = document.getElementById('form-cliente');
    const tbody = document.getElementById('clientes-tbody');

    // Modal Functions
    function openModal() {
        modal.classList.add('active');
        form.reset();
    }

    function closeModal() {
        modal.classList.remove('active');
    }

    btnNovo.addEventListener('click', openModal);
    btnFechar.addEventListener('click', closeModal);
    btnCancelar.addEventListener('click', closeModal);

    modal.addEventListener('click', function(e) {
        if (e.target === modal) closeModal();
    });

    // Format Currency
    function formatCurrency(value) {
        return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
    }

    // Tabs logic
    window.switchTab = function(tabId) {
        document.querySelectorAll('.tab-pane').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        
        document.getElementById('tab-' + tabId).style.display = 'block';
        document.querySelector(`.tab-btn[onclick="switchTab('${tabId}')"]`).classList.add('active');
    };

    // API Functions
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

        // Adiciona o token JWT caso exista no localStorage
        const token = localStorage.getItem('access') || localStorage.getItem('access_token') || localStorage.getItem('token');
        if (token) {
            headers['Authorization'] = 'Bearer ' + token;
        }

        return headers;
    }

    function loadClientes(tipo) {
        fetch(`/clientes/api/?tipo=${tipo}`)
            .then(response => response.json())
            .then(data => {
                let tbodyId = tipo === 'PJ' ? 'clientes-pj-tbody' : 'clientes-gov-tbody';
                let tbodyLocal = document.getElementById(tbodyId);
                
                tbodyLocal.innerHTML = '';
                if (data.length === 0) {
                    tbodyLocal.innerHTML = '<tr><td colspan="5" style="text-align:center;">Nenhum cliente cadastrado.</td></tr>';
                    return;
                }
                data.forEach(cliente => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${cliente.cnpj}</td>
                        <td style="font-weight:500;">${cliente.nome}</td>
                        <td>${cliente.cidade}/${cliente.estado}</td>
                        <td>${cliente.telefone}</td>
                        <td>
                            <button class="btn-primary" style="padding:6px 12px; font-size:12px; background:var(--color-text-muted);" onclick="abrirDetalhesCliente(${cliente.id})">Visualizar</button>
                        </td>
                    `;
                    tbodyLocal.appendChild(tr);
                });
            })
            .catch(err => {
                console.error("Erro ao carregar clientes", err);
                let tbodyId = tipo === 'PJ' ? 'clientes-pj-tbody' : 'clientes-gov-tbody';
                document.getElementById(tbodyId).innerHTML = '<tr><td colspan="5" style="text-align:center;">Erro ao carregar dados.</td></tr>';
            });
    }

    function loadDashboard() {
        fetch('/clientes/api/dashboard_metrics/')
            .then(res => res.json())
            .then(data => {
                document.getElementById('metric-total').textContent = data.total_clientes;
                document.getElementById('metric-pj').textContent = data.total_pj;
                document.getElementById('metric-gov').textContent = data.total_gov;
                
                const topBody = document.getElementById('top-clientes-tbody');
                topBody.innerHTML = '';
                if(data.top_clientes && data.top_clientes.length > 0) {
                    data.top_clientes.forEach(c => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td style="font-size: 0.85rem; color: var(--color-text-muted);">${c.cnpj}</td>
                            <td style="font-weight: 500;">${c.nome}</td>
                            <td style="font-weight: 600; color: var(--color-primary);">${formatCurrency(c.total_comprado || 0)}</td>
                        `;
                        topBody.appendChild(tr);
                    });
                } else {
                    topBody.innerHTML = '<tr><td colspan="3" style="text-align:center; color: var(--color-text-muted);">Nenhuma venda registrada.</td></tr>';
                }
            });
    }

    // Form Submit
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const formData = new FormData(form);
        const data = Object.fromEntries(formData.entries());

        fetch('/clientes/api/', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify(data)
        })
        .then(async response => {
            if (response.ok) {
                Swal.fire({
                    icon: 'success',
                    title: 'Sucesso',
                    text: 'Cliente cadastrado com sucesso!',
                    timer: 2000,
                    showConfirmButton: false
                });
                closeModal();
                loadClientes('PJ');
                loadClientes('GOV');
                loadDashboard();
            } else {
                const err = await response.json();
                let errStr = JSON.stringify(err);
                Swal.fire({
                    icon: 'error',
                    title: 'Erro no Cadastro',
                    text: errStr
                });
            }
        })
        .catch(err => {
            console.error(err);
            Swal.fire('Erro', 'Ocorreu um erro na requisição.', 'error');
        });
    });

    // Detalhes Cliente
    const modalDetalhesCliente = document.getElementById('modal-detalhes-cliente');
    const btnFecharDetalhesCliente = document.getElementById('btn-fechar-detalhes-cliente');

    function closeDetalhesCliente() {
        modalDetalhesCliente.classList.remove('active');
    }

    btnFecharDetalhesCliente.addEventListener('click', closeDetalhesCliente);

    modalDetalhesCliente.addEventListener('click', function(e) {
        if (e.target === modalDetalhesCliente) closeDetalhesCliente();
    });

    window.abrirDetalhesCliente = function(id) {
        fetch(`/clientes/api/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('det-cli-tipo').textContent = data.tipo_cliente === 'PJ' ? 'Pessoa Jurídica' : 'Governamental';
                document.getElementById('det-cli-tipo').className = 'badge ' + (data.tipo_cliente === 'PJ' ? 'badge-pj' : 'badge-gov');
                
                document.getElementById('det-cli-nome').textContent = data.nome || '-';
                document.getElementById('det-cli-cnpj').textContent = data.cnpj || '-';
                document.getElementById('det-cli-prop').textContent = data.proprietario || '-';
                document.getElementById('det-cli-tel').textContent = data.telefone || '-';
                document.getElementById('det-cli-end').textContent = data.endereco || '-';
                document.getElementById('det-cli-cid').textContent = data.cidade || '-';
                document.getElementById('det-cli-uf').textContent = data.estado || '-';

                modalDetalhesCliente.classList.add('active');
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Erro ao carregar detalhes.', 'error');
            });
    }

    // Initial Load
    loadDashboard();
    loadClientes('PJ');
    loadClientes('GOV');
});
