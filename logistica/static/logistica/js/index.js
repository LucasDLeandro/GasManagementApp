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

    // ---- 1. Kanban Híbrido ----
    function formatCurrency(value) { return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value); }
    function formatDate(dateStr) { return new Date(dateStr).toLocaleString('pt-BR'); }

    function loadKanban() {
        // Coluna 1: Pedidos em Separação (Sem Romaneio)
        fetch('/vendas/api/?status=Pendente,Em Separação&entrega__isnull=true', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const colSep = document.querySelector('#col-separacao .kanban-items');
                colSep.innerHTML = '';
                if(data.length === 0) colSep.innerHTML = '<div style="text-align:center; color:var(--color-text-muted);">Nenhum pedido pendente.</div>';
                data.forEach(v => {
                    colSep.innerHTML += `
                        <div class="kanban-item">
                            <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                                <strong style="font-size:1.1rem;">#${v.id}</strong>
                                <span class="badge" style="background:var(--color-primary); color:white;">${v.status}</span>
                            </div>
                            <div style="font-size:0.9rem; margin-bottom:10px;">${v.cliente_nome}</div>
                            <div style="display:flex; flex-direction:column; gap:6px;">
                                <button class="btn-outline" style="padding:6px; font-size:12px;" onclick="abrirDetalhes(${v.id})">Detalhes</button>
                                <button class="btn-outline" style="padding:6px; font-size:12px; border-color:#f59e0b; color:#f59e0b;" onclick="abrirValidacaoCarga(${v.id}, 'Em Separação')">Validar Envase</button>
                                <button class="btn-primary" style="padding:6px; font-size:12px;" onclick="abrirModalAtribuir(${v.id})">Atribuir Caminhão</button>
                            </div>
                        </div>
                    `;
                });
            });

        // Coluna 2: Caminhões em Montagem (Agendados)
        fetch('/logistica/api/entregas/?status=Agendada,Em Produção', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const colCam = document.querySelector('#col-caminhoes .kanban-items');
                colCam.innerHTML = '';
                if(data.length === 0) colCam.innerHTML = '<div style="text-align:center; color:var(--color-text-muted);">Nenhum caminhão.</div>';
                data.forEach(e => renderEntregaCard(e, colCam, false));
            });

        // Coluna 3: Caminhões Em Rota
        fetch('/logistica/api/entregas/?status=Em Rota', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const colRota = document.querySelector('#col-em-rota .kanban-items');
                colRota.innerHTML = '';
                if(data.length === 0) colRota.innerHTML = '<div style="text-align:center; color:var(--color-text-muted);">Nenhum veículo em rota.</div>';
                data.forEach(e => renderEntregaCard(e, colRota, true));
            });
    }

    function renderEntregaCard(e, container, emRota) {
        const veiculo = e.veiculo_placa ? `Caminhão: ${e.veiculo_placa}` : 'Sem Veículo';
        const capMax = e.veiculo_capacidade || 0;
        const pesoLoad = e.peso_total_carregado || 0;
        let perc = e.percentual_lotacao || 0;
        if(perc > 100) perc = 100;
        let barColor = perc < 50 ? '#10b981' : (perc < 85 ? '#f59e0b' : '#ef4444');

        let acaoBtn = emRota 
            ? `<button class="btn-primary" style="width:100%; padding:8px; margin-top:10px; background:#10b981;" onclick="gerenciarParadas(${e.id})">Gerenciar Paradas da Rota</button>`
            : `<button class="btn-primary" style="width:100%; padding:8px; margin-top:10px;" onclick="mudarStatusEntrega(${e.id}, 'Em Rota')">🚀 Iniciar Rota</button>`;

        container.innerHTML += `
            <div class="kanban-item" style="border-top: 4px solid var(--color-primary);">
                <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                    <strong style="font-size:1.1rem;">Carga #${e.id}</strong>
                    <span class="badge">${e.status}</span>
                </div>
                <div style="font-size:0.85rem; color:var(--color-text-muted); margin-bottom:12px;">${e.rota_nome || 'Sem Rota'}</div>
                
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
                        <span>${veiculo}</span>
                        <strong>${perc}%</strong>
                    </div>
                    <div style="width: 100%; height: 6px; background: var(--color-border); border-radius: 3px; overflow: hidden;">
                        <div style="width: ${perc}%; height: 100%; background: ${barColor};"></div>
                    </div>
                    <div style="font-size: 0.75rem; color: var(--color-text-muted); text-align: right; margin-top: 2px;">
                        ${pesoLoad} kg / ${capMax} kg
                    </div>
                </div>
                
                <div style="font-size:0.85rem;"><strong>${e.vendas.length}</strong> Paradas (Pedidos)</div>
                ${acaoBtn}
            </div>
        `;
    }

    window.mudarStatusEntrega = async function(id, novoStatus) {
        try {
            const res = await fetch(`/logistica/api/entregas/${id}/`, {
                method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify({ status: novoStatus })
            });
            if (res.ok) {
                Swal.fire({ title: 'Caminhão Partiu!', icon: 'success', timer: 1500, showConfirmButton: false });
                loadKanban();
            } else throw new Error("Erro.");
        } catch (error) { Swal.fire('Erro', error.message, 'error'); }
    };

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

    // ---- Modais e Ações (Atribuir Caminhão e Paradas) ----
    const modalAtribuir = document.getElementById('modal-atribuir-caminhao');
    if(document.getElementById('btn-fechar-atribuir')) {
        document.getElementById('btn-fechar-atribuir').onclick = () => modalAtribuir.classList.remove('active');
    }

    window.abrirModalAtribuir = function(vendaId) {
        document.getElementById('atr-venda-id').value = vendaId;
        
        // Puxar Entregas em montagem
        fetch('/logistica/api/entregas/?status=Agendada,Em Produção', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                window.entregasDisponiveis = data; // Guardar para acesso rápido no select
                const select = document.getElementById('atr-entrega-id');
                select.innerHTML = '<option value="">Selecione...</option>';
                data.forEach(e => {
                    select.innerHTML += `<option value="${e.id}">Carga #${e.id} - ${e.rota_nome || 'Sem Rota'} (${e.percentual_lotacao}%)</option>`;
                });
                document.getElementById('atr-entrega-info').style.display = 'none';
            });

        // Puxar Veiculos e Rotas para caso de Nova Carga
        fetch('/logistica/api/veiculos/', { headers: getAuthHeaders() }).then(r=>r.json()).then(data=>{
            const sV = document.getElementById('atr-veiculo'); sV.innerHTML = '<option value="">Selecione...</option>';
            data.filter(v=>v.status==='Ativo').forEach(v => sV.innerHTML += `<option value="${v.id}">${v.placa} (${v.capacidade_carga}kg)</option>`);
        });
        fetch('/logistica/api/rotas/', { headers: getAuthHeaders() }).then(r=>r.json()).then(data=>{
            const sR = document.getElementById('atr-rota'); sR.innerHTML = '<option value="">Selecione...</option>';
            data.forEach(r => sR.innerHTML += `<option value="${r.id}">${r.nome}</option>`);
        });

        modalAtribuir.classList.add('active');
    };

    document.getElementById('atr-entrega-id').addEventListener('change', (e) => {
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
                <strong>Rota:</strong> ${entrega.rota_nome || 'Não definida'}<br>
                <strong>Veículo:</strong> ${entrega.veiculo_placa || 'Sem veículo'} (Ocupado: ${entrega.percentual_lotacao}%)<br>
                <strong>Motorista:</strong> ${entrega.motorista_nome || 'Sem motorista'}<br>
                <strong>Pedidos Atuais:</strong> ${entrega.vendas.length} parada(s)
            `;
        }
    });

    document.getElementById('atr-modo').addEventListener('change', (e) => {
        if(e.target.value === 'nova') {
            document.getElementById('div-carga-existente').style.display = 'none';
            document.getElementById('div-nova-carga').style.display = 'grid';
        } else {
            document.getElementById('div-carga-existente').style.display = 'flex';
            document.getElementById('div-nova-carga').style.display = 'none';
        }
    });

    document.getElementById('form-atribuir-caminhao').onsubmit = async (e) => {
        e.preventDefault();
        const vendaId = document.getElementById('atr-venda-id').value;
        const modo = document.getElementById('atr-modo').value;
        let entregaId = document.getElementById('atr-entrega-id').value;

        if(modo === 'nova') {
            // Criar Entrega
            const v = document.getElementById('atr-veiculo').value;
            const r = document.getElementById('atr-rota').value;
            const mot = document.getElementById('atr-motorista').value;
            const payload = { status: 'Agendada' };
            if (v) payload.veiculo = v;
            if (r) payload.rota = r;
            if (mot) payload.motorista = mot;

            const resE = await fetch('/logistica/api/entregas/', {
                method: 'POST', headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            });
            if(resE.ok) {
                const dataE = await resE.json();
                entregaId = dataE.id;
            } else {
                Swal.fire('Erro', 'Não foi possível criar o romaneio.', 'error');
                return;
            }
        }

        if(!entregaId) { Swal.fire('Erro', 'Selecione uma carga', 'warning'); return; }

        // Atribuir venda à entrega
        const resV = await fetch(`/vendas/api/${vendaId}/`, {
            method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify({ entrega: entregaId, status: 'Em Rota' })
        });

        if(resV.ok) {
            Swal.fire('Atribuído!', 'Pedido enviado para carga.', 'success');
            modalAtribuir.classList.remove('active');
            loadKanban();
        }
    };

    // Modal Paradas
    const modalParadas = document.getElementById('modal-paradas-rota');
    if(document.getElementById('btn-fechar-paradas')) {
        document.getElementById('btn-fechar-paradas').onclick = () => modalParadas.classList.remove('active');
    }
    
    let rotaAtualId = null;

    window.gerenciarParadas = function(entregaId) {
        rotaAtualId = entregaId;
        fetch(`/logistica/api/entregas/${entregaId}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const lista = document.getElementById('paradas-lista');
                lista.innerHTML = '';
                
                if(!data.vendas || data.vendas.length === 0) {
                    lista.innerHTML = '<p>Nenhuma parada encontrada.</p>';
                } else {
                    data.vendas.forEach(v => {
                        let sColor = v.status === 'Entregue' ? '#10b981' : (v.status === 'Cancelada' ? '#ef4444' : 'var(--color-primary)');
                        lista.innerHTML += `
                            <div style="display:flex; justify-content:space-between; align-items:center; background: var(--color-hover); padding: 16px; border-radius: 8px; margin-bottom: 10px; border: 1px solid var(--color-border);">
                                <div>
                                    <strong style="font-size: 1rem;">Pedido #${v.id}</strong><br>
                                    <span style="font-size: 0.9rem; color: var(--color-text-muted);">${v.cliente_nome}</span><br>
                                    <span style="font-size: 0.8rem; font-weight: 600; color: ${sColor}; margin-top: 4px; display:inline-block;">Status Atual: ${v.status}</span>
                                </div>
                                <div style="text-align: right; display:flex; flex-direction:column; gap:6px;">
                                    <button class="btn-primary" style="padding: 6px 12px; font-size: 12px; background: #10b981;" onclick="mudarStatusVendaModal(${v.id}, 'Entregue')">Baixa (Entregue)</button>
                                    <button class="btn-outline" style="padding: 6px 12px; font-size: 12px; border-color: #f59e0b; color: #f59e0b;" onclick="abrirValidacaoCarga(${v.id}, 'Em Rota')">Validar Carga</button>
                                    <button class="btn-outline" style="padding: 6px 12px; font-size: 12px; border-color: #ef4444; color: #ef4444;" onclick="mudarStatusVendaModal(${v.id}, 'Cancelada')">Recusar Entrega</button>
                                </div>
                            </div>
                        `;
                    });
                }
                modalParadas.classList.add('active');
            });
    }

    window.mudarStatusVendaModal = async function(id, novoStatus) {
        try {
            const res = await fetch(`/vendas/api/${id}/mudar_status/`, {
                method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify({ status: novoStatus })
            });
            if (res.ok) {
                Swal.fire({ title: 'Status Atualizado!', icon: 'success', timer: 1000, showConfirmButton: false });
                gerenciarParadas(rotaAtualId); // reload modal
                loadKanban(); // reload background
            }
        } catch (error) { Swal.fire('Erro', error.message, 'error'); }
    }

    document.getElementById('btn-finalizar-rota').onclick = async () => {
        if(!rotaAtualId) return;
        const res = await fetch(`/logistica/api/entregas/${rotaAtualId}/`, {
            method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify({ status: 'Concluída' })
        });
        if(res.ok) {
            Swal.fire('Rota Finalizada', 'O veículo está de volta à base.', 'success');
            modalParadas.classList.remove('active');
            loadKanban();
        }
    };

    // ---- Validação de Carga ----
    const modalValidacao = document.getElementById('modal-validacao-carga');
    const formValidacao = document.getElementById('form-validacao');
    if(document.getElementById('btn-fechar-validacao')) {
        document.getElementById('btn-fechar-validacao').onclick = () => modalValidacao.classList.remove('active');
    }
    
    let itensDaVendaAtual = [];

    window.abrirValidacaoCarga = function(vendaId, etapa) {
        document.getElementById('val-venda-id').value = vendaId;
        document.getElementById('val-etapa').value = etapa;
        document.getElementById('val-ajuste').value = '';
        document.getElementById('val-justificativa').value = '';
        
        fetch(`/vendas/api/${vendaId}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                itensDaVendaAtual = data.itens || [];
                const selectProd = document.getElementById('val-produto');
                selectProd.innerHTML = '<option value="">Selecione...</option>';
                itensDaVendaAtual.forEach(i => {
                    selectProd.innerHTML += `<option value="${i.produto}" data-qtd="${i.quantidade}">${i.produto_nome}</option>`;
                });
                document.getElementById('val-qtd-atual').value = '';
                modalValidacao.classList.add('active');
            });
    }

    document.getElementById('val-produto').addEventListener('change', (e) => {
        const option = e.target.options[e.target.selectedIndex];
        document.getElementById('val-qtd-atual').value = option ? option.getAttribute('data-qtd') : '';
    });

    if (formValidacao) {
        formValidacao.addEventListener('submit', (e) => {
            e.preventDefault();
            const payload = {
                venda: document.getElementById('val-venda-id').value,
                etapa_logistica: document.getElementById('val-etapa').value,
                produto: document.getElementById('val-produto').value,
                quantidade_alterada: parseInt(document.getElementById('val-ajuste').value),
                justificativa: document.getElementById('val-justificativa').value,
            };

            fetch('/logistica/api/validacoes/', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            })
            .then(res => {
                if(res.ok) {
                    Swal.fire('Validação Registrada', 'Carga atualizada com sucesso', 'success');
                    modalValidacao.classList.remove('active');
                    loadKanban();
                } else {
                    Swal.fire('Erro', 'Erro ao validar', 'error');
                }
            });
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
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Nenhum veículo cadastrado.</td></tr>';
                    return;
                }
                data.forEach(v => {
                    const badgeClass = v.status === 'Ativo' ? 'ativo' : (v.status === 'Em Manutenção' ? 'manutencao' : '');
                    let locColor = 'var(--color-text)';
                    if(v.localizacao_atual === 'Em Rota') locColor = '#2563eb';
                    else if(v.localizacao_atual === 'Oficina') locColor = '#ef4444';
                    
                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${v.placa}</strong></td>
                            <td>${v.modelo} / ${v.marca}</td>
                            <td>${v.ano}</td>
                            <td>${v.capacidade_carga} kg</td>
                            <td style="color: ${locColor}; font-weight: bold;">${v.localizacao_atual || 'Base'}</td>
                            <td><span class="badge ${badgeClass}">${v.status}</span></td>
                            <td>
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px; margin-right:4px;" onclick="editarVeiculo(${v.id})">Editar</button>
                                <button class="btn-outline" style="padding:4px 8px; font-size:12px;" onclick="verManutencoes(${v.id})">Manutenções</button>
                            </td>
                        </tr>
                    `;
                });
            });
    }

    const modalVeiculo = document.getElementById('modal-veiculo');
    const formVeiculo = document.getElementById('form-veiculo');
    
    document.getElementById('btn-novo-veiculo').onclick = () => {
        formVeiculo.reset();
        document.getElementById('veiculo-id').value = '';
        modalVeiculo.classList.add('active');
    };
    document.getElementById('btn-fechar-modal-veiculo').onclick = () => modalVeiculo.classList.remove('active');
    
    window.editarVeiculo = function(id) {
        fetch(`/logistica/api/veiculos/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('veiculo-id').value = data.id;
                formVeiculo.elements['placa'].value = data.placa;
                formVeiculo.elements['modelo'].value = data.modelo;
                formVeiculo.elements['marca'].value = data.marca;
                formVeiculo.elements['ano'].value = data.ano;
                formVeiculo.elements['capacidade_carga'].value = data.capacidade_carga;
                formVeiculo.elements['status'].value = data.status;
                formVeiculo.elements['localizacao_atual'].value = data.localizacao_atual;
                modalVeiculo.classList.add('active');
            });
    }

    formVeiculo.onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const data = Object.fromEntries(formData.entries());
        const vId = data.id;
        delete data.id;

        const url = vId ? `/logistica/api/veiculos/${vId}/` : '/logistica/api/veiculos/';
        const method = vId ? 'PUT' : 'POST';

        const res = await fetch(url, {
            method: method,
            headers: getAuthHeaders(),
            body: JSON.stringify(data)
        });

        if(res.ok) {
            Swal.fire('Sucesso', 'Veículo salvo!', 'success');
            modalVeiculo.classList.remove('active');
            e.target.reset();
            loadVeiculos();
        } else {
            Swal.fire('Erro', 'Erro ao salvar.', 'error');
        }
    };

    // Histórico de Manutenções
    const modalHistorico = document.getElementById('modal-historico-manutencoes');
    if(document.getElementById('btn-fechar-historico')) {
        document.getElementById('btn-fechar-historico').onclick = () => modalHistorico.classList.remove('active');
    }

    window.verManutencoes = function(veiculoId) {
        // Para simplificar, vou puxar todas as manutenções e filtrar no front (em prod usaria query params se a API suportar filterset)
        fetch('/logistica/api/manutencoes/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const timeline = document.getElementById('timeline-manutencoes');
                timeline.innerHTML = '';
                const manutencoes = data.filter(m => m.veiculo === veiculoId);
                
                if (manutencoes.length === 0) {
                    timeline.innerHTML = '<p style="text-align:center;">Nenhuma manutenção registrada.</p>';
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
                modalHistorico.classList.add('active');
            });
    }

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
