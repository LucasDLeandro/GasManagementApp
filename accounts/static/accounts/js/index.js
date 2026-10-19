/**
 * Baros - Gestão de Pessoal & Acessos (Accounts)
 * Listagem despaginada, busca dinâmica, criação/edição com sincronização RBAC e crachá modal.
 */
document.addEventListener('DOMContentLoaded', function() {
    const modalFunc = document.getElementById('modal-funcionario');
    const modalFuncTitle = document.getElementById('modal-func-title');
    const btnNovo = document.getElementById('btn-novo-funcionario');
    const btnFechar = document.getElementById('btn-fechar-modal');
    const btnCancelar = document.getElementById('btn-cancelar');
    const formFunc = document.getElementById('form-funcionario');
    const formFuncId = document.getElementById('form-func-id');
    const tbody = document.getElementById('funcionarios-tbody');
    const searchInput = document.getElementById('input-busca-funcionario');
    const countBadge = document.getElementById('contagem-funcionarios');
    const funcPapelSelect = document.getElementById('func-papel');
    const rtAnvisaAlert = document.getElementById('rt-anvisa-alert');
    const labelPassword = document.getElementById('label-func-password');
    const inputPassword = document.getElementById('func-password');
    const hintPassword = document.getElementById('hint-func-password');

    let todosFuncionarios = [];

    // Gerenciamento de Abas do Modal
    const tabBtns = document.querySelectorAll('.modal-tab-btn');
    const tabPanes = document.querySelectorAll('.modal-tab-pane');

    function switchTab(targetTabId) {
        tabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-tab') === targetTabId);
        });
        tabPanes.forEach(pane => {
            pane.style.display = (pane.id === targetTabId) ? 'block' : 'none';
        });
    }

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.getAttribute('data-tab');
            switchTab(tabId);
        });
    });

    // Alerta contextual para Responsável Técnico
    if (funcPapelSelect && rtAnvisaAlert) {
        funcPapelSelect.addEventListener('change', () => {
            rtAnvisaAlert.style.display = (funcPapelSelect.value === 'RESPONSAVEL_TECNICO') ? 'flex' : 'none';
        });
    }

    // Abertura do Modal para Novo Funcionário
    btnNovo.addEventListener('click', () => {
        formFunc.reset();
        formFuncId.value = '';
        modalFuncTitle.textContent = 'Cadastrar Novo Funcionário';
        labelPassword.textContent = 'Senha Provisória*';
        inputPassword.required = true;
        if (hintPassword) hintPassword.style.display = 'none';
        if (rtAnvisaAlert) rtAnvisaAlert.style.display = 'none';
        switchTab('tab-acesso');
        modalFunc.classList.add('active');
    });

    function closeModal() {
        modalFunc.classList.remove('active');
    }

    btnFechar.addEventListener('click', closeModal);
    btnCancelar.addEventListener('click', closeModal);

    modalFunc.addEventListener('click', function(e) {
        if (e.target === modalFunc) closeModal();
    });

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

    function getAuthHeaders() {
        const headers = {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        };
        const token = localStorage.getItem('access') || localStorage.getItem('access_token');
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }
    
    function getAuthHeadersMultipart() {
        const headers = {
            'X-CSRFToken': getCookie('csrftoken')
        };
        const token = localStorage.getItem('access') || localStorage.getItem('access_token');
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }

    function formatDate(dateStr) {
        if (!dateStr) return '-';
        const parts = dateStr.split('-');
        if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
        const d = new Date(dateStr);
        return isNaN(d) ? dateStr : d.toLocaleDateString('pt-BR');
    }

    const papelMap = {
        'ADMIN': { label: 'Administrador', cls: 'badge-role-admin' },
        'GERENTE': { label: 'Gerente', cls: 'badge-role-gerente' },
        'RESPONSAVEL_TECNICO': { label: 'Resp. Técnico', cls: 'badge-role-rt' },
        'OPERADOR_PATIO': { label: 'Op. Pátio', cls: 'badge-role-operador' },
        'MOTORISTA': { label: 'Motorista', cls: 'badge-role-motorista' },
        'VENDEDOR': { label: 'Vendedor', cls: 'badge-role-vendedor' }
    };

    function renderTabela(lista) {
        tbody.innerHTML = '';
        if (countBadge) {
            countBadge.textContent = `${lista.length} usuário${lista.length === 1 ? '' : 's'} encontrado${lista.length === 1 ? '' : 's'}`;
        }

        if (!lista || lista.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align:center; padding: 40px 20px;">
                        <div class="empty-state-box">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                                <circle cx="9" cy="7" r="4"></circle>
                                <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                                <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                            </svg>
                            <p style="margin: 0; font-size: 15px; font-weight: 600; color: var(--color-text);">Nenhum funcionário encontrado</p>
                            <p style="margin: 6px 0 0 0; font-size: 13px;">Cadastre os operadores e gestores da distribuidora clicando em "Novo Funcionário".</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        lista.forEach(user => {
            const userPapel = user.papel || user.tipo_usuario || 'VENDEDOR';
            const papelInfo = papelMap[userPapel] || { label: userPapel, cls: 'badge-role-vendedor' };
            let cargo = '-';
            let admissao = '-';
            if (user.userprofile && user.userprofile.dadostrabalhistas) {
                cargo = user.userprofile.dadostrabalhistas.cargo || '-';
                admissao = formatDate(user.userprofile.dadostrabalhistas.data_admissao);
            }
            
            const nomeCompleto = `${user.first_name || ''} ${user.last_name || ''}`.trim() || user.username;

            tbody.innerHTML += `
                <tr>
                    <td>
                        <strong style="color: var(--color-text);">${nomeCompleto}</strong><br>
                        <small style="color:var(--color-text-muted)" class="font-mono">@${user.username} | ${user.email || 'Sem e-mail'}</small>
                    </td>
                    <td>${cargo}</td>
                    <td><span class="badge-role ${papelInfo.cls}">${papelInfo.label}</span></td>
                    <td>${admissao}</td>
                    <td style="text-align: right; white-space: nowrap;">
                        <button class="btn-secondary btn-sm" onclick="abrirEdicaoFuncionario(${user.id})" title="Editar dados funcionais e papel">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                            Editar
                        </button>
                        <button class="btn-secondary btn-sm" onclick="abrirDetalhesFuncionario(${user.id})" title="Visualizar crachá e perfil completo">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="3"></rect><circle cx="9" cy="10" r="2"></circle><line x1="15" y1="8" x2="17" y2="8"></line><line x1="15" y1="12" x2="17" y2="12"></line><line x1="7" y1="16" x2="17" y2="16"></line></svg>
                            Perfil
                        </button>
                    </td>
                </tr>
            `;
        });
    }

    function loadFuncionarios() {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 25px; color: var(--color-text-muted);">Carregando usuários do tenant ativo...</td></tr>';
        
        // Chamada despaginada com fallback resiliente
        fetch('/accounts/api/users/?sem_paginacao=1', { headers: getAuthHeaders() })
            .then(res => {
                if (res.status === 403) {
                    Swal.fire('Acesso Restrito', 'Você não tem permissão de administrador para gerenciar o quadro de pessoal.', 'error');
                    throw new Error('Forbidden');
                }
                return res.json();
            })
            .then(data => {
                // Desempacotamento seguro para arrays diretos ou envelopes paginados
                const lista = Array.isArray(data) ? data : (data && Array.isArray(data.results) ? data.results : []);
                todosFuncionarios = lista;
                renderTabela(todosFuncionarios);
            })
            .catch(err => {
                console.error('Erro ao carregar funcionários:', err);
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 25px; color: #ef4444;">Erro ao carregar lista de funcionários. Verifique sua conexão.</td></tr>';
            });
    }

    // Busca rápida em tempo real
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            const termo = (searchInput.value || '').toLowerCase().trim();
            if (!termo) {
                renderTabela(todosFuncionarios);
                return;
            }

            const filtrados = todosFuncionarios.filter(u => {
                const nomeCompleto = `${u.first_name || ''} ${u.last_name || ''}`.toLowerCase();
                const username = (u.username || '').toLowerCase();
                const email = (u.email || '').toLowerCase();
                const papel = (u.papel || u.tipo_usuario || '').toLowerCase();
                let cargo = '';
                let mat = '';
                if (u.userprofile && u.userprofile.dadostrabalhistas) {
                    cargo = (u.userprofile.dadostrabalhistas.cargo || '').toLowerCase();
                    mat = (u.userprofile.dadostrabalhistas.matricula || '').toLowerCase();
                }
                return nomeCompleto.includes(termo) ||
                       username.includes(termo) ||
                       email.includes(termo) ||
                       papel.includes(termo) ||
                       cargo.includes(termo) ||
                       mat.includes(termo);
            });
            renderTabela(filtrados);
        });
    }

    // Submissão do Formulário (Criação e Edição Completa)
    formFunc.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const userId = formFuncId.value;
        const formData = new FormData(formFunc);
        const isEditing = Boolean(userId);

        const url = isEditing ? `/accounts/api/users/${userId}/` : '/accounts/api/users/';
        const method = isEditing ? 'PUT' : 'POST';

        fetch(url, {
            method: method,
            headers: getAuthHeadersMultipart(),
            body: formData
        })
        .then(async res => {
            if (res.ok) {
                Swal.fire({
                    icon: 'success',
                    title: 'Sucesso',
                    text: isEditing ? 'Dados do funcionário atualizados com sucesso!' : 'Novo funcionário cadastrado com sucesso!',
                    timer: 2000,
                    showConfirmButton: false
                });
                closeModal();
                loadFuncionarios();
            } else {
                const err = await res.json();
                let errStr = '';
                if (typeof err === 'object') {
                    for (const [key, val] of Object.entries(err)) {
                        errStr += `${key}: ${Array.isArray(val) ? val.join(', ') : val}\n`;
                    }
                } else {
                    errStr = JSON.stringify(err);
                }
                Swal.fire({
                    icon: 'error',
                    title: 'Erro na Operação',
                    text: errStr || 'Ocorreu um erro ao salvar o funcionário.'
                });
            }
        })
        .catch(err => {
            console.error(err);
            Swal.fire('Erro', 'Ocorreu um erro na requisição.', 'error');
        });
    });

    // Edição de Funcionário
    window.abrirEdicaoFuncionario = function(id) {
        fetch(`/accounts/api/users/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                formFunc.reset();
                formFuncId.value = data.id;
                modalFuncTitle.textContent = `Editar Funcionário: ${data.first_name || data.username}`;

                // Popula Aba 1: Acesso
                document.getElementById('func-username').value = data.username || '';
                document.getElementById('func-email').value = data.email || '';
                labelPassword.textContent = 'Nova Senha (Opcional)';
                inputPassword.required = false;
                if (hintPassword) hintPassword.style.display = 'block';

                const papelVal = data.papel || data.tipo_usuario || 'VENDEDOR';
                funcPapelSelect.value = papelVal;
                if (rtAnvisaAlert) {
                    rtAnvisaAlert.style.display = (papelVal === 'RESPONSAVEL_TECNICO') ? 'flex' : 'none';
                }

                // Popula Aba 2: Pessoal
                document.getElementById('func-first-name').value = data.first_name || '';
                document.getElementById('func-last-name').value = data.last_name || '';

                if (data.userprofile) {
                    document.getElementById('func-cpf-input').value = data.userprofile.cpf || '';
                    document.getElementById('func-rg-input').value = data.userprofile.rg || '';
                    document.getElementById('func-birth-date').value = data.userprofile.birth_date || '';
                    document.getElementById('func-tel-input').value = data.userprofile.telefone || '';

                    // Popula Aba 3: Trabalhista
                    if (data.userprofile.dadostrabalhistas) {
                        const trab = data.userprofile.dadostrabalhistas;
                        document.getElementById('func-matricula').value = trab.matricula || '';
                        document.getElementById('func-cargo').value = trab.cargo || '';
                        document.getElementById('func-lotacao').value = trab.lotacao || '';
                        document.getElementById('func-salario').value = trab.salario || '';
                        document.getElementById('func-data-admissao').value = trab.data_admissao || '';
                        document.getElementById('func-empresa').value = trab.empresa || '';
                    }
                }

                switchTab('tab-acesso');
                modalFunc.classList.add('active');
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Não foi possível carregar os dados para edição.', 'error');
            });
    };

    // Detalhes do Funcionário (Crachá)
    const modalDetalhesFuncionario = document.getElementById('modal-detalhes-funcionario');
    const btnFecharDetalhesFuncionario = document.getElementById('btn-fechar-detalhes-funcionario');

    function closeDetalhesFunc() {
        modalDetalhesFuncionario.classList.remove('active');
    }

    btnFecharDetalhesFuncionario.addEventListener('click', closeDetalhesFunc);

    modalDetalhesFuncionario.addEventListener('click', function(e) {
        if (e.target === modalDetalhesFuncionario) closeDetalhesFunc();
    });

    window.abrirDetalhesFuncionario = function(id) {
        fetch(`/accounts/api/users/${id}/`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                document.getElementById('det-func-user').textContent = data.username || '-';
                document.getElementById('det-func-email').textContent = data.email || '-';
                
                const userPapel = data.papel || data.tipo_usuario || 'VENDEDOR';
                const papelInfo = papelMap[userPapel] || { label: userPapel, cls: 'badge-role-vendedor' };
                const roleEl = document.getElementById('det-func-role');
                if (roleEl) {
                    roleEl.textContent = papelInfo.label;
                    roleEl.className = 'badge-role ' + papelInfo.cls;
                }
                document.getElementById('det-func-nome').textContent = `${data.first_name || ''} ${data.last_name || ''}`.trim() || data.username || '-';
                
                let cpf = '-', rg = '-', nasc = '-', tel = '-';
                let mat = '-', cargo = '-', lot = '-', emp = '-', sal = '-', adm = '-';

                if (data.userprofile) {
                    cpf = data.userprofile.cpf || '-';
                    rg = data.userprofile.rg || '-';
                    nasc = formatDate(data.userprofile.birth_date);
                    tel = data.userprofile.telefone || '-';
                    
                    if (data.userprofile.foto_perfil) {
                        document.getElementById('det-func-foto').src = data.userprofile.foto_perfil;
                        document.getElementById('det-func-foto').style.display = 'block';
                        document.getElementById('det-func-avatar').style.display = 'none';
                    } else {
                        document.getElementById('det-func-foto').style.display = 'none';
                        document.getElementById('det-func-avatar').style.display = 'block';
                    }
                    
                    if (data.userprofile.dadostrabalhistas) {
                        mat = data.userprofile.dadostrabalhistas.matricula || '-';
                        cargo = data.userprofile.dadostrabalhistas.cargo || '-';
                        lot = data.userprofile.dadostrabalhistas.lotacao || '-';
                        emp = data.userprofile.dadostrabalhistas.empresa || '-';
                        sal = data.userprofile.dadostrabalhistas.salario ? parseFloat(data.userprofile.dadostrabalhistas.salario).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) : '-';
                        adm = formatDate(data.userprofile.dadostrabalhistas.data_admissao);
                    }
                } else {
                    document.getElementById('det-func-foto').style.display = 'none';
                    document.getElementById('det-func-avatar').style.display = 'block';
                }

                document.getElementById('det-func-cpf').textContent = cpf;
                document.getElementById('det-func-rg').textContent = rg;
                document.getElementById('det-func-nasc').textContent = nasc;
                document.getElementById('det-func-tel').textContent = tel;

                document.getElementById('det-func-mat').textContent = mat;
                document.getElementById('det-func-cargo').textContent = cargo;
                document.getElementById('det-func-lot').textContent = lot;
                document.getElementById('det-func-emp').textContent = emp;
                document.getElementById('det-func-sal').textContent = sal;
                document.getElementById('det-func-adm').textContent = adm;

                modalDetalhesFuncionario.classList.add('active');
            })
            .catch(err => {
                console.error(err);
                Swal.fire('Erro', 'Erro ao carregar detalhes do perfil.', 'error');
            });
    };

    loadFuncionarios();
});
