document.addEventListener('DOMContentLoaded', () => {
    // ---- Autenticação via JWT ----
    function getAuthHeaders() {
        let token = localStorage.getItem('access_token') || localStorage.getItem('access');
        if (token && window.isJwtExpired && window.isJwtExpired(token)) {
            localStorage.removeItem('access');
            localStorage.removeItem('access_token');
            token = null;
        }
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
            if(target === 'tab-veiculos') loadVeiculos();
            if(target === 'tab-manutencoes') loadManutencoes();
        });
    });

    function formatCurrency(value) { return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value); }
    function formatDate(dateStr) { return new Date(dateStr).toLocaleString('pt-BR'); }

    // ==========================================
    // ABAS - FROTAS E MANUTENÇÕES
    // ==========================================

    function loadDashboard() {
        fetch('/frotas/api/veiculos/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('count-total-veiculos').innerText = data.length;
                const disponiveis = data.filter(v => v.status === 'Ativo').length;
                document.getElementById('count-veiculos-disponiveis').innerText = disponiveis;
            });
            
        fetch('/frotas/api/manutencoes/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const hoje = new Date();
                let atrasadas = 0;
                let proximas = 0;
                
                data.forEach(m => {
                    (m.pecas || []).forEach(p => {
                        if (p.proxima_troca_data) {
                            const dataTroca = new Date(p.proxima_troca_data);
                            const difDias = (dataTroca - hoje) / (1000 * 60 * 60 * 24);
                            if (difDias < 0) {
                                atrasadas++;
                            } else if (difDias <= 30) {
                                proximas++;
                            }
                        }
                    });
                });
                
                document.getElementById('count-manutencoes-atrasadas').innerText = atrasadas;
                document.getElementById('count-revisoes-proximas').innerText = proximas;
            });
    }

    // Inicializa carregando a dashboard
    loadDashboard();
    
    // ---- Veículos ----
    const modalVeiculo = document.getElementById('modal-veiculo');
    const btnNovoVeiculo = document.getElementById('btn-novo-veiculo');
    const formVeiculo = document.getElementById('form-veiculo');

    btnNovoVeiculo.addEventListener('click', () => {
        formVeiculo.reset();
        document.getElementById('veiculo-id').value = '';
        modalVeiculo.classList.add('active');
    });

    document.getElementById('btn-fechar-modal-veiculo').addEventListener('click', () => {
        modalVeiculo.classList.remove('active');
    });

    function loadVeiculos() {
        fetch('/frotas/api/veiculos/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const tbody = document.getElementById('tbody-veiculos');
                tbody.innerHTML = '';
                if(data.length === 0) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Nenhum veículo cadastrado.</td></tr>';
                data.forEach(v => {
                    const statusClass = v.status === 'Ativo' ? 'badge-success' : (v.status === 'Em Manutenção' ? 'badge-warning' : 'badge-danger');
                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${v.placa}</strong></td>
                            <td>${v.modelo} - ${v.marca}</td>
                            <td>${v.ano}</td>
                            <td>${v.capacidade_carga}</td>
                            <td>${v.localizacao_atual}</td>
                            <td><span class="badge ${statusClass}">${v.status}</span></td>
                            <td class="action-buttons">
                                <button class="btn-icon" onclick="editarVeiculo(${v.id})" title="Editar"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg></button>
                                <button class="btn-icon" onclick="excluirVeiculo(${v.id})" style="color:var(--color-danger);" title="Excluir"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>
                            </td>
                        </tr>
                    `;
                });
            });
    }

    formVeiculo.addEventListener('submit', (e) => {
        e.preventDefault();
        const id = document.getElementById('veiculo-id').value;
        const url = id ? `/frotas/api/veiculos/${id}/` : '/frotas/api/veiculos/';
        const method = id ? 'PUT' : 'POST';
        const data = Object.fromEntries(new FormData(formVeiculo).entries());
        if(!data.renavam) delete data.renavam;
        if(!data.chassi) delete data.chassi;
        if(!data.ano_licenciamento) delete data.ano_licenciamento;
        if(!data.debitos) delete data.debitos;

        fetch(url, {
            method: method,
            headers: getAuthHeaders(),
            body: JSON.stringify(data)
        }).then(res => {
            if(res.ok) {
                modalVeiculo.classList.remove('active');
                loadVeiculos();
                loadDashboard();
                Swal.fire('Sucesso!', 'Veículo salvo.', 'success');
            } else {
                Swal.fire('Erro!', 'Erro ao salvar veículo.', 'error');
            }
        });
    });

    window.editarVeiculo = (id) => {
        fetch(`/frotas/api/veiculos/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                for (const key in data) {
                    const el = formVeiculo.elements[key];
                    if (el) el.value = data[key];
                }
                document.getElementById('veiculo-id').value = id;
                modalVeiculo.classList.add('active');
            });
    };

    window.excluirVeiculo = (id) => {
        Swal.fire({
            title: 'Tem certeza?',
            text: "Deseja remover este veículo?",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#ef4444',
            confirmButtonText: 'Sim, excluir!'
        }).then((result) => {
            if (result.isConfirmed) {
                fetch(`/frotas/api/veiculos/${id}/`, {
                    method: 'DELETE',
                    headers: getAuthHeaders()
                }).then(res => {
                    if(res.ok) {
                        loadVeiculos();
                        loadDashboard();
                        Swal.fire('Removido!', 'Veículo excluído.', 'success');
                    }
                });
            }
        });
    };

    // ---- Manutenções ----
    const modalManutencao = document.getElementById('modal-manutencao');
    const btnNovaManutencao = document.getElementById('btn-nova-manutencao');
    const formManutencao = document.getElementById('form-manutencao');
    const modalHistoricoManutencoes = document.getElementById('modal-historico-manutencoes');
    let pecasCounter = 0;

    btnNovaManutencao.addEventListener('click', () => {
        formManutencao.reset();
        document.getElementById('manutencao-id').value = '';
        document.getElementById('pecas-container').innerHTML = '';
        document.getElementById('manutencao-custo-total').value = '0';
        document.getElementById('total-pecas').innerText = 'R$ 0,00';
        carregarOpcoesVeiculos();
        modalManutencao.classList.add('active');
    });

    document.getElementById('btn-fechar-modal-manutencao').addEventListener('click', () => {
        modalManutencao.classList.remove('active');
    });
    
    document.getElementById('btn-fechar-historico').addEventListener('click', () => {
        modalHistoricoManutencoes.classList.remove('active');
    });

    function carregarOpcoesVeiculos() {
        fetch('/frotas/api/veiculos/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const select = document.getElementById('manutencao-veiculo');
                select.innerHTML = '<option value="">Selecione...</option>';
                data.forEach(v => {
                    select.innerHTML += `<option value="${v.id}">${v.placa} - ${v.modelo}</option>`;
                });
            });
    }

    function loadManutencoes() {
        fetch('/frotas/api/manutencoes/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const tbody = document.getElementById('tbody-manutencoes');
                tbody.innerHTML = '';
                if(data.length === 0) tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Nenhuma manutenção registrada.</td></tr>';
                data.forEach(m => {
                    const statusClass = m.status === 'Concluída' ? 'badge-success' : (m.status === 'Em Progresso' ? 'badge-warning' : 'badge-info');
                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${m.veiculo_placa}</strong></td>
                            <td>${m.tipo_manutencao}</td>
                            <td>${formatDate(m.data_manutencao).split(',')[0]}</td>
                            <td>${m.km_atual || '-'}</td>
                            <td>${formatCurrency(m.custo)}</td>
                            <td><span class="badge ${statusClass}">${m.status}</span></td>
                            <td class="action-buttons">
                                <button class="btn-icon" onclick="editarManutencao(${m.id})" title="Editar"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg></button>
                                <button class="btn-icon" onclick="abrirHistoricoVeiculo(${m.veiculo})" title="Histórico do Veículo"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg></button>
                                <button class="btn-icon" onclick="excluirManutencao(${m.id})" style="color:var(--color-danger);" title="Excluir"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>
                            </td>
                        </tr>
                    `;
                });
            });
    }

    document.getElementById('btn-add-peca').addEventListener('click', () => {
        addPecaRow();
    });

    function addPecaRow(peca = {}) {
        const container = document.getElementById('pecas-container');
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="text" class="peca-tipo" placeholder="Ex: Óleo, Filtro" value="${peca.tipo_peca || ''}" required style="width:100%;"></td>
            <td><input type="text" class="peca-marca" placeholder="Marca" value="${peca.marca || ''}" style="width:100%;"></td>
            <td><input type="text" class="peca-codigo" placeholder="Código" value="${peca.codigo || ''}" style="width:100%;"></td>
            <td><input type="number" class="peca-proxima-km" placeholder="Km" value="${peca.proxima_troca_km || ''}" style="width:100%;"></td>
            <td><input type="date" class="peca-proxima-data" value="${peca.proxima_troca_data || ''}" style="width:100%;"></td>
            <td><input type="number" step="0.01" class="peca-valor input-valor-peca" value="${peca.valor || 0}" required style="width:100%; text-align:right;"></td>
            <td><button type="button" class="btn-icon btn-remove-peca" style="color:var(--color-danger);"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button></td>
        `;
        container.appendChild(tr);

        tr.querySelector('.btn-remove-peca').addEventListener('click', () => {
            tr.remove();
            calcularTotalManutencao();
        });

        tr.querySelector('.peca-valor').addEventListener('input', calcularTotalManutencao);
        calcularTotalManutencao();
    }

    function calcularTotalManutencao() {
        let total = 0;
        document.querySelectorAll('.input-valor-peca').forEach(input => {
            total += parseFloat(input.value) || 0;
        });
        document.getElementById('total-pecas').innerText = formatCurrency(total);
        
        // Sugere colocar o valor das peças no total (o usuário pode alterar pra adicionar a mão de obra)
        const inputCusto = document.getElementById('manutencao-custo-total');
        if(!inputCusto.dataset.manuallyEdited) {
            inputCusto.value = total.toFixed(2);
        }
    }

    document.getElementById('manutencao-custo-total').addEventListener('input', (e) => {
        e.target.dataset.manuallyEdited = "true";
    });

    formManutencao.addEventListener('submit', (e) => {
        e.preventDefault();
        const id = document.getElementById('manutencao-id').value;
        const url = id ? `/frotas/api/manutencoes/${id}/` : '/frotas/api/manutencoes/';
        const method = id ? 'PUT' : 'POST';
        
        const formData = new FormData(formManutencao);
        const data = Object.fromEntries(formData.entries());
        if(!data.km_atual) delete data.km_atual;
        
        const pecasRows = document.querySelectorAll('#pecas-container tr');
        const pecas = [];
        pecasRows.forEach(tr => {
            pecas.push({
                tipo_peca: tr.querySelector('.peca-tipo').value,
                marca: tr.querySelector('.peca-marca').value,
                codigo: tr.querySelector('.peca-codigo').value,
                proxima_troca_km: tr.querySelector('.peca-proxima-km').value || null,
                proxima_troca_data: tr.querySelector('.peca-proxima-data').value || null,
                valor: tr.querySelector('.peca-valor').value || 0
            });
        });
        data.pecas = pecas;

        fetch(url, {
            method: method,
            headers: getAuthHeaders(),
            body: JSON.stringify(data)
        }).then(res => {
            if(res.ok) {
                modalManutencao.classList.remove('active');
                loadManutencoes();
                loadDashboard();
                Swal.fire('Sucesso!', 'Manutenção registrada.', 'success');
            } else {
                Swal.fire('Erro!', 'Erro ao salvar manutenção.', 'error');
            }
        });
    });

    window.editarManutencao = (id) => {
        carregarOpcoesVeiculos();
        fetch(`/frotas/api/manutencoes/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                for (const key in data) {
                    const el = formManutencao.elements[key];
                    if (el && key !== 'pecas') el.value = data[key];
                }
                document.getElementById('manutencao-id').value = id;
                document.getElementById('manutencao-custo-total').value = data.custo;
                document.getElementById('manutencao-custo-total').dataset.manuallyEdited = "true";
                
                document.getElementById('pecas-container').innerHTML = '';
                if(data.pecas) {
                    data.pecas.forEach(p => addPecaRow(p));
                }
                
                modalManutencao.classList.add('active');
            });
    };

    window.excluirManutencao = (id) => {
        Swal.fire({
            title: 'Excluir Manutenção?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#ef4444',
            confirmButtonText: 'Excluir'
        }).then((result) => {
            if (result.isConfirmed) {
                fetch(`/frotas/api/manutencoes/${id}/`, {
                    method: 'DELETE',
                    headers: getAuthHeaders()
                }).then(res => {
                    if(res.ok) {
                        loadManutencoes();
                        loadDashboard();
                        Swal.fire('Removido!', '', 'success');
                    }
                });
            }
        });
    };

    window.abrirHistoricoVeiculo = (veiculoId) => {
        fetch(`/frotas/api/manutencoes/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const timeline = document.getElementById('timeline-manutencoes');
                timeline.innerHTML = '';
                
                const manuVeiculo = data.filter(m => m.veiculo == veiculoId).sort((a,b) => new Date(b.data_manutencao) - new Date(a.data_manutencao));
                
                if(manuVeiculo.length === 0) {
                    timeline.innerHTML = '<p>Nenhuma manutenção registrada para este veículo.</p>';
                } else {
                    manuVeiculo.forEach(m => {
                        let pecasHtml = '';
                        if(m.pecas && m.pecas.length > 0) {
                            pecasHtml = `<ul style="margin-top:10px; padding-left:20px; font-size:13px; color:#4b5563;">`;
                            m.pecas.forEach(p => {
                                pecasHtml += `<li>${p.tipo_peca} - Próx. Troca: ${p.proxima_troca_km ? p.proxima_troca_km + ' km' : ''} ${p.proxima_troca_data ? 'em ' + p.proxima_troca_data : ''}</li>`;
                            });
                            pecasHtml += `</ul>`;
                        }
                        
                        timeline.innerHTML += `
                            <div style="border-left: 3px solid var(--color-primary); padding-left: 15px; margin-bottom: 20px;">
                                <div style="font-size:0.9rem; color:var(--color-text-muted);">${formatDate(m.data_manutencao).split(',')[0]} - Km: ${m.km_atual || 'Não inf.'}</div>
                                <h4 style="margin:5px 0;">${m.tipo_manutencao}</h4>
                                <p style="margin:0; font-size:0.9rem;">${m.descricao}</p>
                                <p style="margin:5px 0 0 0; font-size:0.9rem; font-weight:bold;">Custo: ${formatCurrency(m.custo)}</p>
                                ${pecasHtml}
                            </div>
                        `;
                    });
                }
                modalHistoricoManutencoes.classList.add('active');
            });
    };
    
    // Inicia na aba Veículos
    if(document.getElementById('tab-veiculos').classList.contains('active')) {
        loadVeiculos();
    }
});
