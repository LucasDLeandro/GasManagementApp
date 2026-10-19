document.addEventListener('DOMContentLoaded', function() {
    // Referências do Modal de Cliente (Redesenhado)
    const modal = document.getElementById('modal-cliente');
    const btnNovo = document.getElementById('btn-novo-cliente');
    const btnFechar = document.getElementById('btn-fechar-modal');
    const btnCancelar = document.getElementById('btn-cancelar');
    const form = document.getElementById('form-cliente');
    const modalTitulo = document.getElementById('modal-cliente-titulo');
    const btnSalvar = document.getElementById('btn-salvar-cliente');
    const inputClienteIdEdicao = document.getElementById('cliente_id_edicao');

    let clientesGlobais = [];
    let modelosDisponiveisGlobais = [];
    let dadosSimulacaoAtual = null;

    // Helper: Extrair Lista Resiliente do DRF (Array plano ou Envelope Paginado { results: [] })
    window.extrairListaDRF = function(data) {
        if (Array.isArray(data)) return data;
        if (data && Array.isArray(data.results)) return data.results;
        return [];
    };

    // Helper: Renderizar Empty State Elegante em Tabelas
    window.renderizarEmptyState = function(tbody, colspan, icon, titulo, subtitulo, botaoHtml = '') {
        if (!tbody) return;
        tbody.innerHTML = `
            <tr>
                <td colspan="${colspan}" style="text-align: center; padding: 48px 16px;">
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;">
                        <span style="font-size: 38px; line-height: 1; opacity: 0.85;">${icon}</span>
                        <strong style="font-size: 15px; color: var(--color-text);">${titulo}</strong>
                        <span style="font-size: 13px; color: var(--color-text-muted); max-width: 380px;">${subtitulo}</span>
                        ${botaoHtml ? `<div style="margin-top: 10px;">${botaoHtml}</div>` : ''}
                    </div>
                </td>
            </tr>
        `;
    };

    // Helper: Formatação de Moeda
    function formatCurrency(value) {
        if (value === null || value === undefined) return 'R$ 0,00';
        return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
    }

    // Helper: Formatação de Data
    function formatDate(dateStr) {
        if (!dateStr) return '-';
        if (dateStr.includes('/')) return dateStr;
        const parts = dateStr.split('-');
        if (parts.length === 3) {
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        return dateStr;
    }

    // Máscaras de Entrada (CNPJ, CEP, Telefone)
    function aplicarMascaraCNPJ(v) {
        v = (v || '').replace(/\D/g, '').slice(0, 14);
        if (v.length <= 2) return v;
        if (v.length <= 5) return v.replace(/^(\d{2})(\d+)/, '$1.$2');
        if (v.length <= 8) return v.replace(/^(\d{2})(\d{3})(\d+)/, '$1.$2.$3');
        if (v.length <= 12) return v.replace(/^(\d{2})(\d{3})(\d{3})(\d+)/, '$1.$2.$3/$4');
        return v.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d+)/, '$1.$2.$3/$4-$5');
    }

    function aplicarMascaraCEP(v) {
        v = (v || '').replace(/\D/g, '').slice(0, 8);
        if (v.length <= 5) return v;
        return v.replace(/^(\d{5})(\d+)/, '$1-$2');
    }

    function aplicarMascaraTelefone(v) {
        v = (v || '').replace(/\D/g, '').slice(0, 11);
        if (v.length <= 2) return v;
        if (v.length <= 6) return v.replace(/^(\d{2})(\d+)/, '($1) $2');
        if (v.length <= 10) return v.replace(/^(\d{2})(\d{4})(\d+)/, '($1) $2-$3');
        return v.replace(/^(\d{2})(\d{5})(\d+)/, '($1) $2-$3');
    }

    // Listeners de Máscaras
    const inputCnpj = document.getElementById('cnpj');
    if (inputCnpj) {
        inputCnpj.addEventListener('input', function() {
            this.value = aplicarMascaraCNPJ(this.value);
        });
    }

    const inputCep = document.getElementById('cep');
    if (inputCep) {
        inputCep.addEventListener('input', function() {
            this.value = aplicarMascaraCEP(this.value);
        });
    }

    const inputTel = document.getElementById('telefone');
    if (inputTel) {
        inputTel.addEventListener('input', function() {
            this.value = aplicarMascaraTelefone(this.value);
        });
    }

    // Toggle de Gás Medicinal / CNES
    window.toggleMedicinalFields = function(isMedicinal) {
        const container = document.getElementById('container-cnes');
        const inputCnes = document.getElementById('cnes_licenca_sanitaria');
        if (container) {
            container.style.display = isMedicinal ? 'block' : 'none';
        }
        if (inputCnes && !isMedicinal) {
            inputCnes.value = '';
        }
    };

    // Consulta de CNPJ na BrasilAPI com Auto-Fill
    window.buscarCNPJ = async function(cnpjRaw) {
        const cnpjLimpo = (cnpjRaw || '').replace(/\D/g, '');
        if (cnpjLimpo.length !== 14) {
            Swal.fire('CNPJ Inválido', 'Por favor, informe um CNPJ com 14 dígitos.', 'warning');
            return;
        }

        const btnText = document.getElementById('btn-buscar-cnpj-text');
        const btnSpinner = document.getElementById('btn-buscar-cnpj-spinner');
        if (btnText && btnSpinner) {
            btnText.style.display = 'none';
            btnSpinner.style.display = 'inline';
        }

        try {
            const res = await fetch(`https://brasilapi.com.br/api/cnpj/v1/${cnpjLimpo}`);
            if (!res.ok) {
                throw new Error(`Erro na consulta (HTTP ${res.status})`);
            }
            const data = await res.json();

            if (data.razao_social) document.getElementById('nome').value = data.razao_social;
            if (data.nome_fantasia) document.getElementById('nome_fantasia').value = data.nome_fantasia;
            if (data.cep) {
                document.getElementById('cep').value = aplicarMascaraCEP(data.cep);
            }
            if (data.logradouro) document.getElementById('endereco').value = data.logradouro;
            if (data.numero) document.getElementById('numero').value = data.numero;
            if (data.bairro) document.getElementById('bairro').value = data.bairro;
            if (data.complemento) document.getElementById('complemento').value = data.complemento;
            if (data.municipio) document.getElementById('cidade').value = data.municipio;
            if (data.uf) {
                const elUf = document.getElementById('estado');
                if (elUf) elUf.value = data.uf.toUpperCase();
            }
            if (data.ddd_telefone_1) {
                document.getElementById('telefone').value = aplicarMascaraTelefone(data.ddd_telefone_1);
            }
            if (data.email) {
                document.getElementById('email_financeiro').value = data.email;
            }
            if (data.qsa && data.qsa.length > 0 && data.qsa[0].nome_socio) {
                document.getElementById('proprietario').value = data.qsa[0].nome_socio;
            }

            Swal.fire({
                icon: 'success',
                title: 'CNPJ Localizado!',
                text: `${data.razao_social || 'Cliente'} preenchido via Receita Federal.`,
                timer: 2000,
                showConfirmButton: false
            });
        } catch (err) {
            console.warn('Erro ao consultar BrasilAPI:', err);
            Swal.fire({
                icon: 'info',
                title: 'Aviso',
                text: 'Não foi possível preencher automaticamente os dados do CNPJ (pode ser um CNPJ de teste ou indisponibilidade da API externa). Prossiga com o preenchimento manual.',
            });
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = 'inline';
                btnSpinner.style.display = 'none';
            }
        }
    };

    // Consulta de CEP no ViaCEP
    window.buscarCEP = async function(cepRaw) {
        const cepLimpo = (cepRaw || '').replace(/\D/g, '');
        if (cepLimpo.length !== 8) return;

        try {
            const res = await fetch(`https://viacep.com.br/ws/${cepLimpo}/json/`);
            const data = await res.json();
            if (data.erro) return;

            const endInput = document.getElementById('endereco');
            const bairroInput = document.getElementById('bairro');
            const cidadeInput = document.getElementById('cidade');
            const ufSelect = document.getElementById('estado');

            if (data.logradouro && endInput && !endInput.value) endInput.value = data.logradouro;
            if (data.bairro && bairroInput && !bairroInput.value) bairroInput.value = data.bairro;
            if (data.localidade && cidadeInput) cidadeInput.value = data.localidade;
            if (data.uf && ufSelect) ufSelect.value = data.uf.toUpperCase();
        } catch (e) {
            console.warn('Erro ao consultar ViaCEP:', e);
        }
    };

    // Headers de Autenticação com CSRF e JWT
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

    // Modal Cliente Funções: Criação e Edição
    window.abrirModalNovoCliente = function(tipoDefault = 'PJ') {
        if (!modal) return;
        form.reset();
        if (inputClienteIdEdicao) inputClienteIdEdicao.value = '';
        if (modalTitulo) modalTitulo.textContent = 'Cadastro de Cliente';
        if (btnSalvar) btnSalvar.textContent = 'Salvar Cliente';

        const tipoSelect = document.getElementById('tipo_cliente');
        if (tipoSelect) tipoSelect.value = tipoDefault;

        toggleMedicinalFields(false);
        modal.classList.add('active');
    };

    window.abrirModalEditarCliente = function(clienteId) {
        if (!modal) return;
        form.reset();

        fetch(`/clientes/api/${clienteId}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(cliente => {
                if (inputClienteIdEdicao) inputClienteIdEdicao.value = cliente.id;
                if (modalTitulo) modalTitulo.textContent = `Editar Cliente: ${cliente.nome}`;
                if (btnSalvar) btnSalvar.textContent = 'Salvar Alterações';

                document.getElementById('tipo_cliente').value = cliente.tipo_cliente || 'PJ';
                document.getElementById('cnpj').value = cliente.cnpj || '';
                document.getElementById('nome').value = cliente.nome || '';
                document.getElementById('nome_fantasia').value = cliente.nome_fantasia || '';
                document.getElementById('proprietario').value = cliente.proprietario || '';
                document.getElementById('telefone').value = cliente.telefone || '';
                document.getElementById('email_financeiro').value = cliente.email_financeiro || '';
                document.getElementById('cep').value = cliente.cep || '';
                document.getElementById('endereco').value = cliente.endereco || '';
                document.getElementById('numero').value = cliente.numero || '';
                document.getElementById('bairro').value = cliente.bairro || '';
                document.getElementById('complemento').value = cliente.complemento || '';
                document.getElementById('cidade').value = cliente.cidade || '';
                document.getElementById('estado').value = (cliente.estado || '').toUpperCase();

                const selectMatriz = document.getElementById('cliente_matriz');
                if (selectMatriz) selectMatriz.value = cliente.cliente_matriz || '';

                const checkMedicinal = document.getElementById('is_medicinal');
                if (checkMedicinal) checkMedicinal.checked = Boolean(cliente.is_medicinal);

                toggleMedicinalFields(Boolean(cliente.is_medicinal));
                if (cliente.is_medicinal && cliente.cnes_licenca_sanitaria) {
                    document.getElementById('cnes_licenca_sanitaria').value = cliente.cnes_licenca_sanitaria;
                }

                modal.classList.add('active');
            })
            .catch(err => {
                console.error("Erro ao carregar dados do cliente:", err);
                Swal.fire('Erro', 'Não foi possível carregar os dados do cliente para edição.', 'error');
            });
    };

    function closeModal() {
        if (modal) modal.classList.remove('active');
        if (form) form.reset();
        if (inputClienteIdEdicao) inputClienteIdEdicao.value = '';
    }

    if (btnNovo) btnNovo.addEventListener('click', () => abrirModalNovoCliente('PJ'));
    if (btnFechar) btnFechar.addEventListener('click', closeModal);
    if (btnCancelar) btnCancelar.addEventListener('click', closeModal);

    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) closeModal();
        });
    }

    // Navegação de Abas
    window.switchTab = function(tabId) {
        document.querySelectorAll('.tab-pane').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

        const target = document.getElementById('tab-' + tabId);
        if (target) target.style.display = 'block';

        const btn = document.querySelector(`.tab-btn[onclick="switchTab('${tabId}')"]`);
        if (btn) btn.classList.add('active');

        // Carregamentos sob demanda
        if (tabId === 'pj') {
            loadClientes('PJ');
        } else if (tabId === 'gov') {
            loadClientes('GOV');
        } else if (tabId === 'contratos') {
            carregarModelosDisponiveis();
            carregarContratosCliente();
        } else if (tabId === 'fechamento') {
            carregarFaturasFechadas();
        } else if (tabId === 'extravios') {
            carregarAlertasExtravio();
            carregarRadarCarencia();
        } else if (tabId === 'dashboard') {
            loadDashboard();
        }
    };

    // Carregamento de Clientes (PJ / GOV) com busca e tratamento DRF
    window.loadClientes = function(tipo, search = '') {
        const tbodyId = tipo === 'PJ' ? 'clientes-pj-tbody' : 'clientes-gov-tbody';
        const tbodyLocal = document.getElementById(tbodyId);
        if (!tbodyLocal) return;

        tbodyLocal.innerHTML = '<tr><td colspan="6" style="text-align:center;">Carregando clientes...</td></tr>';

        const url = `/clientes/api/?tipo=${tipo}&search=${encodeURIComponent(search || '')}`;
        fetch(url, { headers: getAuthHeaders() })
            .then(response => response.json())
            .then(data => {
                const clientes = extrairListaDRF(data);
                tbodyLocal.innerHTML = '';

                if (clientes.length === 0) {
                    if (search) {
                        renderizarEmptyState(
                            tbodyLocal,
                            6,
                            '🔍',
                            'Nenhum cliente localizado',
                            `Não foram encontrados registros para "${search}". Tente outro termo.`
                        );
                    } else {
                        const labelTipo = tipo === 'PJ' ? 'Clientes PJ' : 'Governamentais';
                        renderizarEmptyState(
                            tbodyLocal,
                            6,
                            tipo === 'PJ' ? '🏢' : '🏛️',
                            `Nenhum cliente ${labelTipo} cadastrado`,
                            `Cadastre o primeiro cliente ${labelTipo} para gerenciar vendas e comodatos.`,
                            `<button class="btn-primary" style="padding:6px 14px; font-size:12px;" onclick="abrirModalNovoCliente('${tipo}')">+ Cadastrar Cliente</button>`
                        );
                    }
                    return;
                }

                clientes.forEach(cliente => {
                    const tr = document.createElement('tr');

                    // Badges dinâmicas
                    const badges = [];
                    if (cliente.is_medicinal) {
                        badges.push('<span class="badge-medicinal" title="Cliente ANVISA Medicinal">🏥 Medicinal</span>');
                    }
                    if (cliente.tem_contrato_ativo) {
                        badges.push('<span class="badge-contrato" title="Contrato de Comodato Vigente">📄 Contrato Ativo</span>');
                    }
                    if (cliente.cilindros_em_posse_count > 0) {
                        badges.push(`<span class="badge-cilindros" title="Cilindros retidos">${cliente.cilindros_em_posse_count} em posse</span>`);
                    }
                    const badgesHtml = badges.length > 0 ? `<div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:2px;">${badges.join('')}</div>` : '<span style="color:var(--color-text-muted); font-size:12px;">Padrão</span>';

                    const nomeHtml = `
                        <div style="font-weight:600; color:var(--color-text);">${cliente.nome}</div>
                        ${cliente.nome_fantasia ? `<div style="font-size:12px; color:var(--color-text-muted);">${cliente.nome_fantasia}</div>` : ''}
                    `;

                    tr.innerHTML = `
                        <td class="font-mono" style="font-weight:600; font-size:13px;">${cliente.cnpj}</td>
                        <td>${nomeHtml}</td>
                        <td>${badgesHtml}</td>
                        <td>${cliente.cidade || '-'}/${cliente.estado || '-'}</td>
                        <td>${cliente.telefone || '-'}</td>
                        <td style="display:flex; gap:6px; flex-wrap:nowrap;">
                            <button class="btn-primary" style="padding:5px 9px; font-size:12px;" onclick="abrirModalEditarCliente(${cliente.id})" title="Editar Cadastro">Editar</button>
                            <button class="btn-secondary" style="padding:5px 9px; font-size:12px;" onclick="abrirModalContrato(null, ${cliente.id})" title="Criar ou Atualizar Contrato de Comodato">+ Contrato</button>
                            <button class="btn-secondary" style="padding:5px 9px; font-size:12px; background:var(--color-hover);" onclick="abrirDetalhesCliente(${cliente.id})" title="Ver Ficha Completa">Detalhes</button>
                        </td>
                    `;
                    tbodyLocal.appendChild(tr);
                });
            })
            .catch(err => {
                console.error(`Erro ao carregar clientes ${tipo}:`, err);
                renderizarEmptyState(
                    tbodyLocal,
                    6,
                    '⚠️',
                    'Erro na comunicação com o servidor',
                    'Não foi possível listar os clientes. Verifique a conexão e tente novamente.'
                );
            });
    };

    window.filtrarClientesLocal = function(tipo, termo) {
        loadClientes(tipo, termo);
    };

    // Carrega todos os clientes para alimentar selects (com ?sem_paginacao=1)
    function carregarTodosClientesSelects() {
        fetch('/clientes/api/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                clientesGlobais = extrairListaDRF(data);

                const selects = [
                    document.getElementById('filtro-contrato-cliente'),
                    document.getElementById('contrato-cliente-select'),
                    document.getElementById('fechamento-cliente'),
                    document.getElementById('cliente_matriz')
                ];

                selects.forEach(sel => {
                    if (!sel) return;
                    const valAtual = sel.value;
                    const isMatriz = (sel.id === 'cliente_matriz');

                    sel.innerHTML = isMatriz 
                        ? '<option value="">Nenhum (Cliente é Matriz ou Independente)</option>' 
                        : '<option value="">Selecione um cliente...</option>';

                    clientesGlobais.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id;
                        opt.textContent = `${c.nome} (${c.cnpj})`;
                        sel.appendChild(opt);
                    });
                    if (valAtual) sel.value = valAtual;
                });
            })
            .catch(err => console.error("Erro ao carregar clientes para selects:", err));
    }

    window.irParaContratoCliente = function(clienteId) {
        switchTab('contratos');
        const sel = document.getElementById('filtro-contrato-cliente');
        if (sel) {
            sel.value = clienteId;
            carregarContratosCliente();
        }
    };

    function loadDashboard() {
        fetch('/clientes/api/dashboard_metrics/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const elTot = document.getElementById('metric-total');
                const elPj = document.getElementById('metric-pj');
                const elGov = document.getElementById('metric-gov');
                const elCilindros = document.getElementById('metric-cilindros-posse');
                const elContratos = document.getElementById('metric-contratos-ativos');
                const elReceita = document.getElementById('metric-receita-estimada');

                if (elTot) elTot.textContent = data.total_clientes || 0;
                if (elPj) elPj.textContent = data.total_pj || 0;
                if (elGov) elGov.textContent = data.total_gov || 0;
                if (elCilindros) elCilindros.textContent = data.cilindros_em_posse || 0;
                if (elContratos) elContratos.textContent = data.contratos_ativos || 0;
                if (elReceita) elReceita.textContent = formatCurrency(data.receita_estimada_mes || 0);

                const topBody = document.getElementById('top-clientes-tbody');
                if (!topBody) return;
                topBody.innerHTML = '';

                const topClientes = extrairListaDRF(data.top_clientes || []);
                if (topClientes.length > 0) {
                    topClientes.forEach(c => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td class="font-mono" style="font-size: 0.85rem; color: var(--color-text-muted);">${c.cnpj}</td>
                            <td style="font-weight: 500;">${c.nome}</td>
                            <td style="font-weight: 700; color: var(--color-primary);">${formatCurrency(c.total_comprado || 0)}</td>
                        `;
                        topBody.appendChild(tr);
                    });
                } else {
                    renderizarEmptyState(
                        topBody,
                        3,
                        '📊',
                        'Nenhum faturamento registrado',
                        'Assim que os pedidos de venda forem confirmados, o ranking dos principais clientes será gerado aqui.'
                    );
                }
            })
            .catch(err => console.error("Erro ao carregar métricas do dashboard:", err));
    }

    // Submissão do Form de Cliente (Criar POST ou Atualizar PATCH)
    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(form);
            const data = Object.fromEntries(formData.entries());

            const clienteId = inputClienteIdEdicao ? inputClienteIdEdicao.value : '';
            const isEdicao = Boolean(clienteId);

            // Tratamentos de dados
            data.is_medicinal = Boolean(document.getElementById('is_medicinal') && document.getElementById('is_medicinal').checked);
            if (!data.cliente_matriz) delete data.cliente_matriz;
            if (!data.numero) data.numero = '';
            if (!data.bairro) data.bairro = '';
            if (!data.complemento) data.complemento = '';
            if (!data.email_financeiro) data.email_financeiro = '';
            if (!data.cnes_licenca_sanitaria) data.cnes_licenca_sanitaria = '';
            delete data.cliente_id_edicao;

            const url = isEdicao ? `/clientes/api/${clienteId}/` : '/clientes/api/';
            const method = isEdicao ? 'PATCH' : 'POST';

            fetch(url, {
                method: method,
                headers: getAuthHeaders(),
                body: JSON.stringify(data)
            })
            .then(async response => {
                if (response.ok) {
                    Swal.fire({
                        icon: 'success',
                        title: isEdicao ? 'Cliente Atualizado!' : 'Cliente Cadastrado!',
                        text: isEdicao ? 'Os dados do cliente foram atualizados com sucesso.' : 'Novo cliente cadastrado com sucesso!',
                        timer: 2000,
                        showConfirmButton: false
                    });
                    closeModal();
                    loadClientes('PJ');
                    loadClientes('GOV');
                    loadDashboard();
                    carregarTodosClientesSelects();
                } else {
                    const err = await response.json();
                    Swal.fire('Erro no Formulário', JSON.stringify(err), 'error');
                }
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Ocorreu um erro ao processar a requisição.', 'error');
            });
        });
    }

    // Modal Detalhes Cliente
    const modalDetalhesCliente = document.getElementById('modal-detalhes-cliente');
    const btnFecharDetalhesCliente = document.getElementById('btn-fechar-detalhes-cliente');

    function closeDetalhesCliente() {
        if (modalDetalhesCliente) modalDetalhesCliente.classList.remove('active');
    }

    if (btnFecharDetalhesCliente) btnFecharDetalhesCliente.addEventListener('click', closeDetalhesCliente);
    if (modalDetalhesCliente) {
        modalDetalhesCliente.addEventListener('click', function(e) {
            if (e.target === modalDetalhesCliente) closeDetalhesCliente();
        });
    }

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
    };

    // =========================================================================
    // FASE 2: CONTRATOS DE COMODATO VERSIONADOS
    // =========================================================================
    const modalContrato = document.getElementById('modal-contrato');

    function carregarModelosDisponiveis() {
        fetch('/clientes/api/contratos/modelos-disponiveis/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                modelosDisponiveisGlobais = extrairListaDRF(data);
            })
            .catch(err => console.error("Erro ao carregar modelos disponíveis:", err));
    }

    window.carregarContratosCliente = function() {
        const clienteId = document.getElementById('filtro-contrato-cliente').value;
        const tbody = document.getElementById('tbody-versoes-contrato');
        const painelAtivo = document.getElementById('painel-contrato-ativo');

        if (!clienteId) {
            renderizarEmptyState(
                tbody,
                7,
                '📋',
                'Nenhum cliente selecionado',
                'Selecione um cliente no campo acima para visualizar o histórico de versões de contratos de comodato.'
            );
            painelAtivo.style.display = 'none';
            return;
        }

        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Carregando histórico de contratos...</td></tr>';

        fetch(`/clientes/api/contratos/?cliente_id=${clienteId}&sem_paginacao=1`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const contratos = extrairListaDRF(data);
                tbody.innerHTML = '';
                if (!contratos || contratos.length === 0) {
                    renderizarEmptyState(
                        tbody,
                        7,
                        '📄',
                        'Nenhum contrato cadastrado',
                        'Este cliente ainda não possui versão de contrato de comodato cadastrada.',
                        `<button class="btn-primary" style="padding:6px 14px; font-size:12px;" onclick="abrirModalContrato(null, ${clienteId})">+ Criar Primeiro Contrato</button>`
                    );
                    painelAtivo.style.display = 'none';
                    return;
                }

                // Identifica o contrato ativo hoje (ou o mais recente)
                const ativo = contratos.find(c => c.ativo_hoje) || contratos[0];
                if (ativo) {
                    painelAtivo.style.display = 'block';
                    renderizarResumoContratoAtivo(ativo);
                } else {
                    painelAtivo.style.display = 'none';
                }

                contratos.forEach(c => {
                    const tr = document.createElement('tr');
                    const badgeClass = c.ativo_hoje ? 'contract-version-badge ativo' : 'contract-version-badge historico';
                    const badgeText = c.ativo_hoje ? 'Vigente / Ativo' : 'Histórico / Encerrado';

                    tr.innerHTML = `
                        <td><span class="${badgeClass}">${badgeText}</span></td>
                        <td><strong>${formatDate(c.vigencia_inicio)}</strong></td>
                        <td>${c.vigencia_fim ? formatDate(c.vigencia_fim) : '<em>Indeterminado</em>'}</td>
                        <td><span class="badge" style="background:var(--color-hover);">${c.criterio_franquia}</span></td>
                        <td>${c.agrupar_franquia_filiais ? 'Sim' : 'Não'}</td>
                        <td>${c.dias_limite_extravio} dias</td>
                        <td>
                            <button class="btn-secondary" style="padding:4px 8px; font-size:12px;" onclick="editarContrato(${c.id})">Editar / Visualizar</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            });
    };

    function renderizarResumoContratoAtivo(contrato) {
        const grid = document.getElementById('resumo-contrato-ativo-grid');
        grid.innerHTML = `
            <div class="resumo-card-mini">
                <span class="rotulo">Critério de Franquia</span>
                <span class="valor" style="color:var(--color-primary);">${contrato.criterio_franquia}</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Vigência Ativa</span>
                <span class="valor" style="font-size:1.1rem;">${formatDate(contrato.vigencia_inicio)} a ${contrato.vigencia_fim ? formatDate(contrato.vigencia_fim) : 'Indeterminado'}</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Carência Padrão</span>
                <span class="valor">${contrato.dias_carencia_giro} dias</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Diária Excedente</span>
                <span class="valor">${formatCurrency(contrato.valor_diaria_excedente)}</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Limite p/ Extravio</span>
                <span class="valor">${contrato.dias_limite_extravio} dias</span>
            </div>
        `;

        const tbodyFranquias = document.getElementById('tbody-franquias-ativas');
        tbodyFranquias.innerHTML = '';
        if (contrato.franquias_modelo && contrato.franquias_modelo.length > 0) {
            contrato.franquias_modelo.forEach(fm => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="font-weight:600;">${fm.modelo_descricao || 'Modelo #' + fm.modelo}</td>
                    <td>${fm.franquia_cilindros_isentos} cascos</td>
                    <td>${fm.dias_carencia_giro} dias</td>
                    <td style="font-weight:600; color:var(--color-primary);">${formatCurrency(fm.taxa_diaria)}/dia</td>
                    <td>${formatCurrency(fm.valor_reposicao_extravio)}</td>
                `;
                tbodyFranquias.appendChild(tr);
            });
        } else {
            tbodyFranquias.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align:center; color:var(--color-text-muted);">
                        Nenhuma regra específica por modelo; aplicando os parâmetros padrão (${contrato.franquia_cilindros_isentos} isentos, ${contrato.dias_carencia_giro}d carência, ${formatCurrency(contrato.valor_diaria_excedente)}/dia).
                    </td>
                </tr>
            `;
        }
    }

    window.abrirModalContrato = function(contratoId = null, preClienteId = null) {
        if (!modalContrato) return;
        modalContrato.classList.add('active');

        const formContrato = document.getElementById('form-contrato');
        formContrato.reset();
        document.getElementById('contrato-id').value = '';
        document.getElementById('tbody-modal-franquias').innerHTML = '';

        if (preClienteId) {
            document.getElementById('contrato-cliente-select').value = preClienteId;
        }

        const hoje = new Date().toISOString().split('T')[0];
        document.getElementById('contrato-vigencia-inicio').value = hoje;

        if (contratoId) {
            document.getElementById('modal-contrato-titulo').textContent = 'Editar Contrato de Comodato';
            fetch(`/clientes/api/contratos/${contratoId}/`, { headers: getAuthHeaders() })
                .then(res => res.json())
                .then(c => {
                    document.getElementById('contrato-id').value = c.id;
                    document.getElementById('contrato-cliente-select').value = c.cliente;
                    document.getElementById('contrato-vigencia-inicio').value = c.vigencia_inicio;
                    document.getElementById('contrato-vigencia-fim').value = c.vigencia_fim || '';
                    document.getElementById('contrato-criterio-franquia').value = c.criterio_franquia;
                    document.getElementById('contrato-limite-extravio').value = c.dias_limite_extravio;
                    document.getElementById('contrato-agrupar-filiais').checked = c.agrupar_franquia_filiais;
                    document.getElementById('contrato-franquia-padrao').value = c.franquia_cilindros_isentos;
                    document.getElementById('contrato-carencia-padrao').value = c.dias_carencia_giro;
                    document.getElementById('contrato-diaria-padrao').value = c.valor_diaria_excedente;
                    document.getElementById('contrato-reposicao-padrao').value = c.custo_reposicao_casco;

                    if (c.franquias_modelo && c.franquias_modelo.length > 0) {
                        c.franquias_modelo.forEach(fm => adicionarLinhaFranquiaModelo(fm));
                    }
                });
        } else {
            document.getElementById('modal-contrato-titulo').textContent = 'Novo Contrato de Comodato / Nova Versão';
        }
    };

    window.fecharModalContrato = function() {
        if (modalContrato) modalContrato.classList.remove('active');
    };

    window.adicionarLinhaFranquiaModelo = function(dados = null) {
        const tbody = document.getElementById('tbody-modal-franquias');
        const tr = document.createElement('tr');

        let opcoesModelos = modelosDisponiveisGlobais.map(m => `
            <option value="${m.id}" ${dados && dados.modelo == m.id ? 'selected' : ''}>
                ${m.descricao}
            </option>
        `).join('');

        tr.innerHTML = `
            <td>
                <select class="fm-modelo" required style="width:100%; padding:6px; border-radius:4px; border:1px solid var(--color-border); background:var(--color-surface); color:var(--color-text);">
                    ${opcoesModelos}
                </select>
            </td>
            <td>
                <input type="number" class="fm-isentos" min="0" value="${dados ? dados.franquia_cilindros_isentos : 0}" style="width:70px; padding:6px; border-radius:4px; border:1px solid var(--color-border); background:var(--color-surface); color:var(--color-text);">
            </td>
            <td>
                <input type="number" class="fm-carencia" min="0" value="${dados ? dados.dias_carencia_giro : 30}" style="width:70px; padding:6px; border-radius:4px; border:1px solid var(--color-border); background:var(--color-surface); color:var(--color-text);">
            </td>
            <td>
                <input type="number" step="0.01" class="fm-diaria" min="0" value="${dados ? dados.taxa_diaria : 3.50}" style="width:85px; padding:6px; border-radius:4px; border:1px solid var(--color-border); background:var(--color-surface); color:var(--color-text);">
            </td>
            <td>
                <input type="number" step="0.01" class="fm-reposicao" min="0" value="${dados ? dados.valor_reposicao_extravio : 1800.00}" style="width:100px; padding:6px; border-radius:4px; border:1px solid var(--color-border); background:var(--color-surface); color:var(--color-text);">
            </td>
            <td>
                <button type="button" class="btn-secondary" style="padding:4px 8px; color:var(--status-danger, #ef4444);" onclick="removerLinhaFranquiaModelo(this)">&times;</button>
            </td>
        `;
        tbody.appendChild(tr);
    };

    window.removerLinhaFranquiaModelo = function(btn) {
        btn.closest('tr').remove();
    };

    window.editarContrato = function(contratoId) {
        abrirModalContrato(contratoId);
    };

    window.salvarContrato = function(event) {
        event.preventDefault();

        const contratoId = document.getElementById('contrato-id').value;
        const clienteId = document.getElementById('contrato-cliente-select').value;
        const vigenciaInicio = document.getElementById('contrato-vigencia-inicio').value;
        const vigenciaFim = document.getElementById('contrato-vigencia-fim').value || null;
        const criterio = document.getElementById('contrato-criterio-franquia').value;
        const limiteExtravio = parseInt(document.getElementById('contrato-limite-extravio').value, 10);
        const agruparFiliais = document.getElementById('contrato-agrupar-filiais').checked;

        const franquiaPadrao = parseInt(document.getElementById('contrato-franquia-padrao').value, 10) || 0;
        const carenciaPadrao = parseInt(document.getElementById('contrato-carencia-padrao').value, 10) || 30;
        const diariaPadrao = parseFloat(document.getElementById('contrato-diaria-padrao').value) || 3.50;
        const reposicaoPadrao = parseFloat(document.getElementById('contrato-reposicao-padrao').value) || 1800.00;

        // Franquias por modelo
        const franquias = [];
        document.querySelectorAll('#tbody-modal-franquias tr').forEach(tr => {
            const modeloId = tr.querySelector('.fm-modelo').value;
            const isentos = parseInt(tr.querySelector('.fm-isentos').value, 10) || 0;
            const carencia = parseInt(tr.querySelector('.fm-carencia').value, 10) || 0;
            const diaria = parseFloat(tr.querySelector('.fm-diaria').value) || 0;
            const reposicao = parseFloat(tr.querySelector('.fm-reposicao').value) || 0;
            if (modeloId) {
                franquias.push({
                    modelo: modeloId,
                    franquia_cilindros_isentos: isentos,
                    dias_carencia_giro: carencia,
                    taxa_diaria: diaria,
                    valor_reposicao_extravio: reposicao
                });
            }
        });

        const payload = {
            cliente: clienteId,
            vigencia_inicio: vigenciaInicio,
            vigencia_fim: vigenciaFim,
            criterio_franquia: criterio,
            agrupar_franquia_filiais: agruparFiliais,
            dias_limite_extravio: limiteExtravio,
            franquia_cilindros_isentos: franquiaPadrao,
            dias_carencia_giro: carenciaPadrao,
            valor_diaria_excedente: diariaPadrao,
            custo_reposicao_casco: reposicaoPadrao,
            franquias_modelo: franquias
        };

        const url = contratoId ? `/clientes/api/contratos/${contratoId}/` : '/clientes/api/contratos/';
        const method = contratoId ? 'PUT' : 'POST';

        fetch(url, {
            method: method,
            headers: getAuthHeaders(),
            body: JSON.stringify(payload)
        })
        .then(async res => {
            if (res.ok) {
                Swal.fire({
                    icon: 'success',
                    title: 'Contrato Salvo',
                    text: 'A versão do contrato de comodato e suas franquias foram registradas com sucesso.',
                    timer: 2000,
                    showConfirmButton: false
                });
                fecharModalContrato();
                document.getElementById('filtro-contrato-cliente').value = clienteId;
                carregarContratosCliente();
            } else {
                const err = await res.json();
                Swal.fire('Erro ao salvar contrato', JSON.stringify(err), 'error');
            }
        })
        .catch(err => {
            console.error(err);
            Swal.fire('Erro', 'Falha na comunicação ao salvar contrato.', 'error');
        });
    };

    // =========================================================================
    // FASE 2: CONSOLE DE FECHAMENTO DE FATURAS (STEPPER DE 3 PASSOS)
    // =========================================================================
    window.voltarParaPasso = function(passo) {
        atualizarVisualStepper(passo);
    };

    window.avancarParaPasso = function(passo) {
        if (passo === 3 && dadosSimulacaoAtual) {
            renderizarResumoPasso3(dadosSimulacaoAtual);
        }
        atualizarVisualStepper(passo);
    };

    window.reiniciarStepper = function() {
        dadosSimulacaoAtual = null;
        document.getElementById('painel-sucesso-fechamento').style.display = 'none';
        atualizarVisualStepper(1);
        carregarFaturasFechadas();
    };

    function atualizarVisualStepper(passoAtivo) {
        for (let i = 1; i <= 3; i++) {
            const pane = document.getElementById(`step-pane-${i}`);
            const nav = document.getElementById(`step-nav-${i}`);
            if (pane) pane.style.display = (i === passoAtivo) ? 'block' : 'none';
            if (nav) {
                nav.classList.remove('active', 'completed');
                if (i === passoAtivo) {
                    nav.classList.add('active');
                } else if (i < passoAtivo) {
                    nav.classList.add('completed');
                }
            }
        }
    }

    window.executarSimulacaoPrevia = function() {
        const clienteId = document.getElementById('fechamento-cliente').value;
        const competencia = document.getElementById('fechamento-competencia').value;

        if (!clienteId || !competencia) {
            Swal.fire('Campos Obrigatórios', 'Informe a competência (AAAA-MM) e selecione o cliente.', 'warning');
            return;
        }

        const btn = document.getElementById('btn-executar-previa');
        const txtOrig = btn.textContent;
        btn.textContent = 'Calculando Motor Determinístico...';
        btn.disabled = true;

        fetch('/clientes/api/faturas-estadia/simular-drill-down/', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                cliente_id: parseInt(clienteId, 10),
                competencia_ano_mes: competencia
            })
        })
        .then(async res => {
            btn.textContent = txtOrig;
            btn.disabled = false;

            if (res.ok) {
                const dados = await res.json();
                dadosSimulacaoAtual = dados;
                renderizarDrillDown(dados);
                atualizarVisualStepper(2);
            } else {
                const err = await res.json();
                Swal.fire('Erro na Simulação', err.detail || JSON.stringify(err), 'error');
            }
        })
        .catch(err => {
            btn.textContent = txtOrig;
            btn.disabled = false;
            console.error(err);
            Swal.fire('Erro', 'Falha ao executar simulação de estadia.', 'error');
        });
    };

    function renderizarDrillDown(dados) {
        // 1. Comparativo com Mês Anterior
        const comp = dados.comparativo_mes_anterior;
        document.getElementById('comp-ant-label').textContent = comp.competencia_anterior || '-';
        document.getElementById('comp-ant-valor').textContent = formatCurrency(comp.valor_anterior);
        document.getElementById('comp-atual-valor').textContent = formatCurrency(dados.resumo_financeiro.valor_liquido_total);

        const badge = document.getElementById('comp-delta-badge');
        const varPct = comp.variacao_percentual;
        if (varPct > 0) {
            badge.textContent = `+${varPct}%`;
            badge.style.background = 'rgba(239, 68, 68, 0.15)';
            badge.style.color = '#dc2626';
        } else if (varPct < 0) {
            badge.textContent = `${varPct}%`;
            badge.style.background = 'rgba(16, 185, 129, 0.15)';
            badge.style.color = '#059669';
        } else {
            badge.textContent = `0.0%`;
            badge.style.background = 'var(--color-hover)';
            badge.style.color = 'var(--color-text-muted)';
        }

        // 2. Resumo Financeiro Grid
        const rf = dados.resumo_financeiro;
        const grid = document.getElementById('resumo-drilldown-grid');
        grid.innerHTML = `
            <div class="resumo-card-mini">
                <span class="rotulo">Total Bruto Diárias</span>
                <span class="valor">${formatCurrency(rf.valor_bruto_diarias)}</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Desconto Carência</span>
                <span class="valor" style="color:var(--status-approved, #10b981);">${formatCurrency(rf.valor_desconto_carencia)}</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Desconto Franquia</span>
                <span class="valor" style="color:var(--color-primary);">${formatCurrency(rf.valor_desconto_franquia)}</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Ajustes Retroativos</span>
                <span class="valor" style="color:${rf.valor_ajustes_retroativos < 0 ? '#10b981' : '#b45309'};">${formatCurrency(rf.valor_ajustes_retroativos)}</span>
            </div>
            <div class="resumo-card-mini">
                <span class="rotulo">Reposição Extravios</span>
                <span class="valor" style="color:${rf.valor_reposicao_extravios > 0 ? '#dc2626' : 'var(--color-text)'};">${formatCurrency(rf.valor_reposicao_extravios)}</span>
            </div>
            <div class="resumo-card-mini" style="border: 2px solid var(--color-primary);">
                <span class="rotulo">Valor Líquido da Fatura</span>
                <span class="valor" style="color:var(--color-primary); font-size:1.5rem;">${formatCurrency(rf.valor_liquido_total)}</span>
            </div>
        `;

        // 3. Ajustes Retroativos
        const secaoAjustes = document.getElementById('secao-ajustes-retroativos');
        const listaAjustes = document.getElementById('lista-ajustes-retroativos');
        listaAjustes.innerHTML = '';
        if (dados.ajustes_retroativos && dados.ajustes_retroativos.length > 0) {
            secaoAjustes.style.display = 'block';
            dados.ajustes_retroativos.forEach(a => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${a.tipo}:</strong> ${formatCurrency(a.valor)} (Ref. Competência ${a.competencia_afetada}) - <em>${a.motivo}</em>`;
                listaAjustes.appendChild(li);
            });
        } else {
            secaoAjustes.style.display = 'none';
        }

        // 4. Extravios
        const secaoExtravios = document.getElementById('secao-reposicoes-extravio');
        const listaExtravios = document.getElementById('lista-reposicoes-extravio');
        listaExtravios.innerHTML = '';
        if (dados.extravios_pendentes && dados.extravios_pendentes.length > 0) {
            secaoExtravios.style.display = 'block';
            dados.extravios_pendentes.forEach(e => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>Cilindro ${e.cilindro_serie} (${e.data_extravio}):</strong> ${formatCurrency(e.valor)} - ${e.justificativa}`;
                listaExtravios.appendChild(li);
            });
        } else {
            secaoExtravios.style.display = 'none';
        }

        // 5. Árvore Desdobrável (Tree Container)
        const container = document.getElementById('tree-drilldown-container');
        container.innerHTML = '';

        if (!dados.arvore_modelos || dados.arvore_modelos.length === 0) {
            container.innerHTML = '<div style="background:var(--color-surface); padding:24px; border-radius:8px; border:1px solid var(--color-border); text-align:center; color:var(--color-text-muted);">Nenhum cilindro com permanência ou cobrança registrada para este cliente nesta competência.</div>';
            return;
        }

        dados.arvore_modelos.forEach((mod, idx) => {
            const node = document.createElement('div');
            node.className = 'tree-model-node';

            let cilindrosHtml = '';
            mod.cilindros.forEach(cil => {
                let diasHtml = '';
                cil.calendario_dias.forEach(d => {
                    let pillClass = 'day-carencia';
                    let label = `${d.dia_mes}: Carência (${d.idade_posse_dias}d)`;

                    if (d.classe_cobranca === 'ISENTO_FRANQUIA') {
                        pillClass = 'day-franquia';
                        label = `${d.dia_mes}: Franquia`;
                    } else if (d.classe_cobranca === 'COBRAVEL') {
                        pillClass = 'day-cobravel';
                        label = `${d.dia_mes}: R$ ${d.valor_diaria.toFixed(2)}`;
                    } else if (d.classe_cobranca.includes('PROPRIEDADE')) {
                        pillClass = 'day-propriedade';
                        label = `${d.dia_mes}: Próprio`;
                    }

                    diasHtml += `<span class="day-pill ${pillClass}" title="${d.data} - ${d.classe_cobranca} (${d.idade_posse_dias} dias em posse)">${label}</span>`;
                });

                cilindrosHtml += `
                    <div class="tree-cylinder-card">
                        <div class="tree-cylinder-top">
                            <div class="tree-cylinder-info">
                                <span class="tech-id-badge" style="font-weight:700;">${cil.numero_serie || cil.codigo_qr}</span>
                                <span style="font-size:0.85rem; color:var(--color-text-muted);">Período: ${cil.periodo_inicio} a ${cil.periodo_fim}</span>
                                <span style="font-size:0.85rem;"><strong>${cil.dias_posse_mes}</strong> dias posse</span>
                                <span style="font-size:0.85rem; color:var(--status-approved, #10b981);">${cil.dias_carencia}d carência</span>
                                <span style="font-size:0.85rem; color:var(--color-primary);">${cil.dias_franquia}d franquia</span>
                                <span style="font-size:0.85rem; font-weight:700; color:#b45309;">${cil.dias_cobraveis}d cobráveis</span>
                            </div>
                            <div style="font-family:'JetBrains Mono',monospace; font-weight:700; color:var(--color-text);">
                                Subtotal: ${formatCurrency(cil.subtotal)}
                            </div>
                        </div>
                        <div class="calendar-pills-row">
                            ${diasHtml || '<span style="font-size:0.75rem; color:var(--color-text-muted);">Sem diárias individuais mapeadas.</span>'}
                        </div>
                    </div>
                `;
            });

            node.innerHTML = `
                <div class="tree-model-header" onclick="toggleTreeModel(this)">
                    <div class="tree-model-title">
                        <span class="tree-toggle-icon">▼</span>
                        <span>Grupo de Modelo: <strong>${mod.modelo}</strong> (${mod.total_cilindros} cilindros)</span>
                    </div>
                    <div class="tree-model-badges">
                        <span class="badge" style="background:rgba(59, 130, 246, 0.15); color:#2563eb;">${mod.total_dias_posse} dias posse</span>
                        <span class="badge" style="background:rgba(245, 158, 11, 0.15); color:#b45309;">${mod.total_dias_cobraveis} dias cobráveis</span>
                        <span style="font-family:'JetBrains Mono',monospace; font-weight:800; font-size:1.1rem; color:var(--color-text);">
                            ${formatCurrency(mod.subtotal)}
                        </span>
                    </div>
                </div>
                <div class="tree-model-body" style="display: flex;">
                    ${cilindrosHtml}
                </div>
            `;
            container.appendChild(node);
        });
    }

    window.toggleTreeModel = function(header) {
        const body = header.nextElementSibling;
        const icon = header.querySelector('.tree-toggle-icon');
        if (body.style.display === 'none') {
            body.style.display = 'flex';
            icon.textContent = '▼';
        } else {
            body.style.display = 'none';
            icon.textContent = '▶';
        }
    };

    function renderizarResumoPasso3(dados) {
        const div = document.getElementById('step3-previa-resumo');
        div.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                <div>
                    <h4 style="margin:0; font-size:1.1rem;">${dados.cliente_nome} (${dados.cliente_cnpj})</h4>
                    <span style="font-size:0.85rem; color:var(--color-text-muted);">Competência a congelar: <strong>${dados.competencia}</strong></span>
                </div>
                <div style="font-family:'JetBrains Mono',monospace; font-size:1.5rem; font-weight:800; color:var(--color-primary);">
                    ${formatCurrency(dados.resumo_financeiro.valor_liquido_total)}
                </div>
            </div>
        `;
    }

    window.executarFechamentoFormal = function() {
        if (!dadosSimulacaoAtual) return;

        Swal.fire({
            title: 'Confirmar Fechamento Fiscal?',
            text: `Esta ação gerará a fatura definitiva de ${dadosSimulacaoAtual.competencia} no valor de ${formatCurrency(dadosSimulacaoAtual.resumo_financeiro.valor_liquido_total)} e é estritamente imutável.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#10b981',
            cancelButtonColor: '#6b7280',
            confirmButtonText: 'Sim, Fechar Fatura',
            cancelButtonText: 'Cancelar'
        }).then(result => {
            if (result.isConfirmed) {
                const btn = document.getElementById('btn-confirmar-fechamento');
                btn.disabled = true;
                btn.textContent = 'Gravando Snapshot Fiscal...';

                fetch('/clientes/api/faturas-estadia/fechar/', {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({
                        cliente_id: dadosSimulacaoAtual.cliente_id,
                        competencia_ano_mes: dadosSimulacaoAtual.competencia,
                        persistir: true
                    })
                })
                .then(async res => {
                    btn.disabled = false;
                    btn.textContent = 'Confirmar Fechamento Formal (Imutável)';

                    if (res.ok) {
                        const faturaFechada = await res.json();
                        document.getElementById('step3-previa-resumo').parentElement.style.display = 'none';
                        const painelSucesso = document.getElementById('painel-sucesso-fechamento');
                        painelSucesso.style.display = 'block';

                        document.getElementById('btn-download-pdf').href = `/clientes/api/faturas-estadia/${faturaFechada.id}/espelho-pdf/`;
                        document.getElementById('btn-download-csv').href = `/clientes/api/faturas-estadia/${faturaFechada.id}/espelho-csv/`;

                        Swal.fire({
                            icon: 'success',
                            title: 'Fatura Fechada!',
                            text: `Fatura #${faturaFechada.id} registrada com sucesso. Webhook despachado.`,
                            timer: 2500,
                            showConfirmButton: false
                        });
                        carregarFaturasFechadas();
                    } else {
                        const err = await res.json();
                        Swal.fire('Erro no Fechamento', err.detail || JSON.stringify(err), 'error');
                    }
                })
                .catch(err => {
                    btn.disabled = false;
                    btn.textContent = 'Confirmar Fechamento Formal (Imutável)';
                    console.error(err);
                    Swal.fire('Erro', 'Falha na comunicação ao fechar fatura.', 'error');
                });
            }
        });
    };

    function carregarFaturasFechadas() {
        const tbody = document.getElementById('tbody-faturas-fechadas');
        if (!tbody) return;

        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">Carregando faturas fechadas...</td></tr>';

        fetch('/clientes/api/faturas-estadia/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                const faturas = extrairListaDRF(data);
                tbody.innerHTML = '';
                if (!faturas || faturas.length === 0) {
                    renderizarEmptyState(
                        tbody,
                        9,
                        '🧾',
                        'Nenhuma fatura fechada recentemente',
                        'As faturas mensais de estadia fechadas pelos operadores aparecerão listadas aqui para auditoria, emissão e download.'
                    );
                    return;
                }

                faturas.forEach(f => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><strong>${f.competencia_ano_mes}</strong></td>
                        <td style="font-weight:600;">${f.cliente_nome}</td>
                        <td>${formatDate(f.data_fechamento ? f.data_fechamento.split('T')[0] : '')}</td>
                        <td>${formatCurrency(f.valor_bruto_diarias)}</td>
                        <td style="color:var(--status-approved, #10b981);">${formatCurrency(parseFloat(f.valor_desconto_carencia) + parseFloat(f.valor_desconto_franquia))}</td>
                        <td style="color:#b45309;">${formatCurrency(parseFloat(f.valor_ajustes_retroativos) + parseFloat(f.valor_reposicao_extravios))}</td>
                        <td style="font-weight:800; font-family:'JetBrains Mono',monospace; color:var(--color-primary);">${formatCurrency(f.valor_liquido_total)}</td>
                        <td><span class="badge" style="background:rgba(16, 185, 129, 0.15); color:#059669;">${f.status_pagamento}</span></td>
                        <td style="display:flex; gap:6px;">
                            <a href="/clientes/api/faturas-estadia/${f.id}/espelho-pdf/" target="_blank" class="btn-primary" style="padding:4px 8px; font-size:11px;" title="Baixar PDF">PDF</a>
                            <a href="/clientes/api/faturas-estadia/${f.id}/espelho-csv/" target="_blank" class="btn-secondary" style="padding:4px 8px; font-size:11px;" title="Baixar CSV">CSV</a>
                            <button class="btn-secondary" style="padding:4px 8px; font-size:11px;" onclick="visualizarDrillDownFatura(${f.id})">Drill-Down</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            });
    }

    window.visualizarDrillDownFatura = function(faturaId) {
        fetch(`/clientes/api/faturas-estadia/${faturaId}/drill-down/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(dados => {
                dadosSimulacaoAtual = dados;
                renderizarDrillDown(dados);
                switchTab('fechamento');
                atualizarVisualStepper(2);
            });
    };

    // =========================================================================
    // FASE 2: FILA DE EXTRAVIOS & RADAR PREVENTIVO DE CARÊNCIA
    // =========================================================================
    const modalExtravio = document.getElementById('modal-declarar-extravio');

    window.carregarAlertasExtravio = function() {
        const tbody = document.getElementById('tbody-alertas-extravio');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">Monitorando cilindros retidos...</td></tr>';

        fetch('/clientes/api/extravios/alertas/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(alertas => {
                tbody.innerHTML = '';
                if (!alertas || alertas.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--status-approved, #10b981);">Nenhum cilindro retido além do limite contratual de extravio.</td></tr>';
                    return;
                }

                alertas.forEach(a => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><span class="tech-id-badge">${a.numero_serie}</span></td>
                        <td style="font-weight:600;">${a.cliente_nome}</td>
                        <td>${a.data_entrega}</td>
                        <td><strong style="color:var(--status-danger, #ef4444);">${a.dias_em_posse} dias</strong></td>
                        <td>${a.dias_limite_extravio}d</td>
                        <td>+${a.dias_excedentes_extravio}d</td>
                        <td style="font-weight:700; color:var(--status-danger, #ef4444); font-family:'JetBrains Mono',monospace;">${formatCurrency(a.valor_reposicao)}</td>
                        <td>
                            <button class="btn-primary" style="background:var(--status-danger, #ef4444); padding:4px 8px; font-size:12px;" onclick="abrirModalExtravio(${a.cilindro_id}, '${a.numero_serie}', '${a.cliente_nome}', ${a.dias_em_posse}, ${a.valor_reposicao})">
                                Declarar Extraviado
                            </button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            });
    };

    window.carregarRadarCarencia = function() {
        const tbody = document.getElementById('tbody-radar-carencia');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">Identificando cilindros prestes a vencer carência...</td></tr>';

        fetch('/clientes/api/extravios/radar-carencia/', { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(itens => {
                tbody.innerHTML = '';
                if (!itens || itens.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--color-text-muted);">Nenhum cilindro atingindo limite de carência nos próximos 5 dias.</td></tr>';
                    return;
                }

                itens.forEach(it => {
                    const tr = document.createElement('tr');
                    const isUrgente = it.dias_restantes_carencia <= 2;
                    const badgeStyle = isUrgente 
                        ? 'background:rgba(239, 68, 68, 0.2); color:#dc2626; border:1px solid #ef4444;' 
                        : 'background:rgba(245, 158, 11, 0.2); color:#b45309; border:1px solid #f59e0b;';

                    tr.innerHTML = `
                        <td><span class="tech-id-badge">${it.numero_serie}</span></td>
                        <td style="font-weight:600;">${it.cliente_nome}</td>
                        <td>${it.data_entrega}</td>
                        <td>${it.idade_posse_dias} dias</td>
                        <td>${it.carencia_dias} dias</td>
                        <td>
                            <span class="badge ${isUrgente ? 'radar-badge-pulse' : ''}" style="${badgeStyle}">
                                ${it.dias_restantes_carencia === 0 ? 'VENCE HOJE' : `${it.dias_restantes_carencia} dia(s)`}
                            </span>
                        </td>
                        <td style="font-family:'JetBrains Mono',monospace;">${formatCurrency(it.taxa_diaria_prevista)}/dia</td>
                        <td>
                            <button class="btn-secondary" style="padding:4px 8px; font-size:12px;" onclick="Swal.fire('Ação Comercial', 'Disparo de aviso de recolha/troca para ${it.cliente_nome}.', 'info')">
                                Contatar Cliente
                            </button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            });
    };

    window.abrirModalExtravio = function(cilindroId, serie, clienteNome, dias, valor) {
        if (!modalExtravio) return;
        document.getElementById('extravio-cilindro-id').value = cilindroId;
        document.getElementById('extravio-info-cilindro').textContent = serie;
        document.getElementById('extravio-info-cliente').textContent = clienteNome;
        document.getElementById('extravio-info-dias').textContent = dias;
        document.getElementById('extravio-info-valor').textContent = formatCurrency(valor);
        document.getElementById('extravio-justificativa').value = '';
        modalExtravio.classList.add('active');
    };

    window.fecharModalExtravio = function() {
        if (modalExtravio) modalExtravio.classList.remove('active');
    };

    window.confirmarDeclaracaoExtravio = function(event) {
        event.preventDefault();
        const cilindroId = document.getElementById('extravio-cilindro-id').value;
        const justificativa = document.getElementById('extravio-justificativa').value;

        fetch('/clientes/api/extravios/declarar/', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                cilindro_id: parseInt(cilindroId, 10),
                justificativa: justificativa
            })
        })
        .then(async res => {
            if (res.ok) {
                Swal.fire({
                    icon: 'success',
                    title: 'Extravio Registrado',
                    text: 'O cilindro foi declarado como extraviado e a indenização foi lançada para o próximo fechamento.',
                    timer: 2500,
                    showConfirmButton: false
                });
                fecharModalExtravio();
                carregarAlertasExtravio();
            } else {
                const err = await res.json();
                Swal.fire('Erro', err.detail || JSON.stringify(err), 'error');
            }
        })
        .catch(err => {
            console.error(err);
            Swal.fire('Erro', 'Falha ao declarar extravio.', 'error');
        });
    };

    // Ações de Navegação Integrada (Ponta a Ponta)
    window.irParaContratosCliente = function() {
        const modal = document.getElementById('modal-detalhes-cliente');
        if (modal) modal.classList.remove('active');
        switchTab('contratos');
    };

    window.irParaFaturasCliente = function() {
        const modal = document.getElementById('modal-detalhes-cliente');
        if (modal) modal.classList.remove('active');
        switchTab('fechamento');
    };

    window.irParaRadarCliente = function() {
        const modal = document.getElementById('modal-detalhes-cliente');
        if (modal) modal.classList.remove('active');
        switchTab('extravios');
    };

    // Inicialização
    loadDashboard();
    loadClientes('PJ');
    loadClientes('GOV');
    carregarTodosClientesSelects();
    carregarModelosDisponiveis();
});
