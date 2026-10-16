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
        const veiculo = e.veiculo_placa ? `${e.veiculo_placa} (${e.veiculo_modelo || 'Veículo'})` : 'Sem Veículo';
        const capMax = e.veiculo_capacidade || 0;
        const pesoLoad = e.peso_total_carregado || 0;
        const percReal = e.percentual_lotacao || 0;
        const percVisual = Math.min(percReal, 100);

        // Cores D11: Verde (< 80%), Âmbar (80%-99%), Vermelho (>= 100% sobrecarga)
        let barColor = '#10b981'; // Verde
        let statusTexto = 'Normal (<80%)';
        if (percReal >= 100) {
            barColor = '#ef4444'; // Vermelho
            statusTexto = 'SOBRECARGA (>100%)';
        } else if (percReal >= 80) {
            barColor = '#f59e0b'; // Âmbar
            statusTexto = 'Alerta Carga (80-99%)';
        }

        // Selo de aviso explícito "Contém peso estimado" se possui_peso_estimado for true
        const seloPesoEstimado = e.possui_peso_estimado 
            ? `<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.3); font-size: 10px; padding: 2px 6px; margin-left: 6px;" title="Cálculo utiliza tara nominal ou massa estimada">⚠️ Contém peso estimado</span>`
            : `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 10px; padding: 2px 6px; margin-left: 6px;">⚖️ Peso Aferido</span>`;

        // Se peso ultrapassar 100% da capacidade do veículo, desabilite o botão de saída/início de rota com mensagem explicativa
        let acaoBtn = '';
        if (emRota) {
            acaoBtn = `<button class="btn-primary" style="width:100%; padding:8px; margin-top:10px; background:#10b981;" onclick="gerenciarParadas(${e.id})">Gerenciar Paradas da Rota</button>`;
        } else if (percReal > 100) {
            acaoBtn = `
                <button disabled class="btn-primary" style="width:100%; padding:8px; margin-top:10px; background:#ef4444; cursor:not-allowed; opacity:0.9; font-size:12px; font-weight:700;" title="Trava de Segurança ANTT: O peso carregado (${pesoLoad} kg) excede a capacidade máxima (${capMax} kg).">
                    🚫 Saída Bloqueada: Sobrecarga ANTT (${percReal}%)
                </button>
                <div style="font-size:11px; color:#ef4444; margin-top:4px; text-align:center; font-weight:600;">
                    Bloqueio obrigatório Resolução ANTT 5.998/2022. Reduza o peso para liberar saída.
                </div>
            `;
        } else {
            acaoBtn = `<button class="btn-primary" style="width:100%; padding:8px; margin-top:10px;" onclick="mudarStatusEntrega(${e.id}, 'Em Rota')">🚀 Iniciar Rota</button>`;
        }

        container.innerHTML += `
            <div class="kanban-item" style="border-top: 4px solid ${barColor};">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <strong style="font-size:1.1rem;">Carga #${e.id}</strong>
                    <div style="display:flex; align-items:center;">
                        <span class="badge">${e.status}</span>
                        ${seloPesoEstimado}
                    </div>
                </div>
                <div style="font-size:0.85rem; color:var(--color-text-muted); margin-bottom:12px;">
                    <strong>Rota:</strong> ${e.rota_nome || 'Sem Rota'} | <strong>Motorista:</strong> ${e.motorista_nome || 'A definir'}
                </div>
                
                <div style="margin-bottom: 12px; background:var(--color-surface); padding:8px; border-radius:6px; border:1px solid var(--color-border);">
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
                        <span>🚚 ${veiculo}</span>
                        <strong style="color:${barColor};">${percReal}% (${statusTexto})</strong>
                    </div>
                    <div style="width: 100%; height: 8px; background: var(--color-border); border-radius: 4px; overflow: hidden;">
                        <div style="width: ${percVisual}%; height: 100%; background: ${barColor}; transition: width 0.3s ease;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size: 0.75rem; color: var(--color-text-muted); margin-top: 4px;">
                        <span>Capacidade: ${capMax} kg</span>
                        <span>Carregado: <strong>${pesoLoad} kg</strong></span>
                    </div>
                </div>
                
                <div style="font-size:0.85rem; margin-bottom:4px;"><strong>${e.vendas.length}</strong> Parada(s) / Pedido(s)</div>
                ${acaoBtn}
                
                <button class="btn-outline" style="width:100%; padding:6px; margin-top:6px; border-color:#6366f1; color:#6366f1; font-weight:600; font-size:12px;" onclick="abrirRomaneioBilateral(${e.id})">⚖️ Romaneio Bilateral (Full-for-Empty)</button>
                
                <!-- Emissão em 1 Clique dos PDFs ANTT -->
                <div style="margin-top:8px; border-top:1px solid var(--color-border); padding-top:6px;">
                    <div style="font-size:10px; font-weight:700; text-transform:uppercase; color:var(--color-text-muted); margin-bottom:4px;">Documentos ANTT Transporte Perigoso:</div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:4px;">
                        <a href="/logistica/api/entregas/${e.id}/romaneio-antt-pdf/" target="_blank" class="btn-outline" style="padding:4px; font-size:11px; text-align:center; text-decoration:none; color:var(--color-primary); border-color:var(--color-primary); border-radius:4px;" title="Romaneio Bilateral de Carga ANTT (Res. 5.998/2022)">📄 Romaneio</a>
                        <a href="/logistica/api/entregas/${e.id}/ficha-emergencia-pdf/" target="_blank" class="btn-outline" style="padding:4px; font-size:11px; text-align:center; text-decoration:none; color:#ea580c; border-color:#ea580c; border-radius:4px;" title="Ficha de Emergência NBR 7503 com números ONU">⚠️ Ficha ONU</a>
                        <a href="/logistica/api/entregas/${e.id}/envelope-transporte-pdf/" target="_blank" class="btn-outline" style="padding:4px; font-size:11px; text-align:center; text-decoration:none; color:#0284c7; border-color:#0284c7; border-radius:4px;" title="Envelope para Transporte de Produtos Perigosos">✉️ Envelope</a>
                    </div>
                </div>
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
            } else {
                const errData = await res.json().catch(() => null);
                const errMsg = (errData && (errData.non_field_errors?.[0] || errData.error || errData.detail)) || "Erro ao atualizar status da entrega.";
                Swal.fire('Trava ANTT / Bloqueio', errMsg, 'error');
            }
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
            data.filter(v=>v.status==='Ativo').forEach(v => {
                const mod = v.modelo ? ` - ${v.modelo}` : '';
                sV.innerHTML += `<option value="${v.id}">${v.placa}${mod} (Capacidade: ${v.capacidade_carga} kg)</option>`;
            });
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

    // ---- Romaneio Bilateral (Full-for-Empty) ----
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

            // Atualiza Veículo e Barra de Capacidade (D11: <80% Verde, 80-99% Âmbar, >100% Vermelho)
            const perc = data.percentual_lotacao || 0;
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
                tbodyEntregues.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:10px; color:#94a3b8;">Nenhum cheio entregue ainda.</td></tr>';
            } else {
                tbodyEntregues.innerHTML = data.cilindros_entregues.map(c => `
                    <tr style="border-bottom:1px solid #f1f5f9;">
                        <td style="padding:6px;"><strong>${c.numero_serie}</strong><br><small style="color:#64748b;">${c.codigo_qr}</small></td>
                        <td style="padding:6px;"><span class="badge" style="background:#10b981; color:white; font-size:10px;">${c.gas}</span></td>
                        <td style="padding:6px;">${c.cliente}</td>
                    </tr>
                `).join('');
            }

            // Tabela 2: Vazios Recolhidos
            const tbodyRecolhidos = document.getElementById('tbody-romaneio-recolhidos');
            if (!data.cilindros_recolhidos || data.cilindros_recolhidos.length === 0) {
                tbodyRecolhidos.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:10px; color:#94a3b8;">Nenhum vazio recolhido ainda.</td></tr>';
            } else {
                tbodyRecolhidos.innerHTML = data.cilindros_recolhidos.map(c => `
                    <tr style="border-bottom:1px solid #f1f5f9;">
                        <td style="padding:6px;"><strong>${c.numero_serie}</strong><br><small style="color:#64748b;">${c.codigo_qr}</small></td>
                        <td style="padding:6px;"><span class="badge" style="background:#f59e0b; color:white; font-size:10px;">${c.gas}</span></td>
                        <td style="padding:6px;">${c.tara} kg</td>
                    </tr>
                `).join('');
            }

            // Saldo de Comodato
            const divComodato = document.getElementById('romaneio-clientes-comodato');
            if (!data.clientes_comodato || data.clientes_comodato.length === 0) {
                divComodato.innerHTML = '<span style="color:#94a3b8;">Nenhum cliente associado a esta carga.</span>';
            } else {
                divComodato.innerHTML = data.clientes_comodato.map(c => `
                    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:6px 10px;">
                        <strong>${c.nome}</strong>: <span style="color:#4f46e5; font-weight:700;">${c.saldo_comodato} cilindros</span> em posse
                    </div>
                `).join('');
            }

        } catch (err) {
            console.error(err);
            if (typeof Swal !== 'undefined') Swal.fire('Erro', err.message, 'error');
        }
    }

    // Form Submits: Entregar Cheio
    const formEntregar = document.getElementById('form-entregar-cheio');
    if (formEntregar) {
        formEntregar.addEventListener('submit', async (e) => {
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
                if (!res.ok) throw new Error(resp.error || 'Erro ao registrar entrega.');

                if (typeof Swal !== 'undefined') Swal.fire('Entregue!', resp.mensagem, 'success');
                document.getElementById('input-qr-entrega').value = '';
                await carregarDadosRomaneio(entregaRomaneioAtualId);
            } catch (err) {
                if (typeof Swal !== 'undefined') Swal.fire('Bloqueio Operacional', err.message, 'warning');
                else alert(err.message);
            }
        });
    }

    // Form Submits: Recolher Vazio
    const formRecolher = document.getElementById('form-recolher-vazio');
    if (formRecolher) {
        formRecolher.addEventListener('submit', async (e) => {
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
                if (!res.ok) throw new Error(resp.error || 'Erro ao registrar recolha.');

                if (typeof Swal !== 'undefined') Swal.fire('Recolhido!', resp.mensagem, 'success');
                document.getElementById('input-qr-recolha').value = '';
                document.getElementById('input-obs-recolha').value = '';
                await carregarDadosRomaneio(entregaRomaneioAtualId);
            } catch (err) {
                if (typeof Swal !== 'undefined') Swal.fire('Atenção', err.message, 'warning');
                else alert(err.message);
            }
        });
    }

    // Init
    loadKanban();
});
