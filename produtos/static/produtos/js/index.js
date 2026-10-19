document.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('modal-produto');
    const btnNovo = document.getElementById('btn-novo-produto');
    const btnFechar = document.getElementById('btn-fechar-modal');
    const btnCancelar = document.getElementById('btn-cancelar');
    const form = document.getElementById('form-produto');
    const tbody = document.getElementById('produtos-tbody');

    function openModal() {
        if (modal) modal.classList.add('active');
        if (form) form.reset();
    }

    function closeModal() {
        if (modal) modal.classList.remove('active');
    }

    if (btnNovo && modal) btnNovo.addEventListener('click', openModal);
    if (btnFechar && modal) btnFechar.addEventListener('click', closeModal);
    if (btnCancelar && modal) btnCancelar.addEventListener('click', closeModal);

    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) closeModal();
        });
    }

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

        let token = localStorage.getItem('access') || localStorage.getItem('access_token') || localStorage.getItem('token');
        if (token && window.isJwtExpired && window.isJwtExpired(token)) {
            localStorage.removeItem('access');
            localStorage.removeItem('access_token');
            token = null;
        }
        if (token) {
            headers['Authorization'] = 'Bearer ' + token;
        }

        return headers;
    }

    function formatCurrency(value) {
        return parseFloat(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    }

    function loadProdutos() {
        if (!tbody) return;
        fetch('/produtos/api/')
            .then(response => response.json())
            .then(data => {
                tbody.innerHTML = '';
                const list = Array.isArray(data) ? data : (data.results || []);
                if (list.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Nenhum produto cadastrado.</td></tr>';
                    return;
                }
                list.forEach(prod => {
                    const tr = document.createElement('tr');
                    const badgeClass = prod.categoria === 'Medicinal' ? 'badge-medicinal' : 'badge-industrial';
                    tr.innerHTML = `
                        <td>${prod.codigo_barras || '-'}</td>
                        <td><strong>${prod.nome}</strong></td>
                        <td><span class="badge ${badgeClass}">${prod.categoria}</span></td>
                        <td>${prod.capacidade} ${prod.unidade_medida}</td>
                        <td>${formatCurrency(prod.preco)}</td>
                        <td>${prod.estoque} un.</td>
                        <td>
                            <button class="btn-primary" style="padding:4px 8px; font-size:12px; background:var(--color-text-muted);" onclick="abrirDetalhesProduto(${prod.id})">Visualizar</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            })
            .catch(err => {
                console.error("Erro ao carregar produtos", err);
                if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Erro ao carregar dados.</td></tr>';
            });
    }

    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(form);
            const data = Object.fromEntries(formData.entries());

            fetch('/produtos/api/', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify(data)
            })
            .then(async response => {
                if (response.ok) {
                    Swal.fire({
                        icon: 'success',
                        title: 'Sucesso',
                        text: 'Cilindro cadastrado com sucesso!',
                        timer: 2000,
                        showConfirmButton: false
                    });
                    closeModal();
                    loadProdutos();
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
    }

    // Detalhes Produto
    const modalDetalhesProduto = document.getElementById('modal-detalhes-produto');
    const btnFecharDetalhesProduto = document.getElementById('btn-fechar-detalhes-produto');

    function closeDetalhesProduto() {
        if (modalDetalhesProduto) modalDetalhesProduto.classList.remove('active');
    }

    if (btnFecharDetalhesProduto) btnFecharDetalhesProduto.addEventListener('click', closeDetalhesProduto);

    if (modalDetalhesProduto) {
        modalDetalhesProduto.addEventListener('click', function(e) {
            if (e.target === modalDetalhesProduto) closeDetalhesProduto();
        });
    }

    window.abrirDetalhesProduto = function(id) {
        fetch(`/produtos/api/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const elNome = document.getElementById('det-prod-nome');
                const elCat = document.getElementById('det-prod-cat');
                const elSku = document.getElementById('det-prod-sku');
                const elCap = document.getElementById('det-prod-cap');
                const elPreco = document.getElementById('det-prod-preco');
                const elEst = document.getElementById('det-prod-est');

                if (elNome) elNome.textContent = data.nome || '-';
                if (elCat) elCat.textContent = data.categoria || '-';
                if (elSku) elSku.textContent = data.codigo_barras || '-';
                if (elCap) elCap.textContent = (data.capacidade && data.unidade_medida) ? `${data.capacidade} ${data.unidade_medida}` : '-';
                if (elPreco) elPreco.textContent = formatCurrency(data.preco) || '-';
                if (elEst) elEst.textContent = `${data.estoque} un.` || '-';

                if (modalDetalhesProduto) modalDetalhesProduto.classList.add('active');
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Erro ao carregar detalhes.', 'error');
            });
    };

    if (tbody) {
        loadProdutos();
    }
});
