document.addEventListener('DOMContentLoaded', function() {
    const modalFunc = document.getElementById('modal-funcionario');
    const btnNovo = document.getElementById('btn-novo-funcionario');
    const btnFechar = document.getElementById('btn-fechar-modal');
    const btnCancelar = document.getElementById('btn-cancelar');
    const formFunc = document.getElementById('form-funcionario');
    const tbody = document.getElementById('funcionarios-tbody');

    btnNovo.addEventListener('click', () => {
        modalFunc.classList.add('active');
        formFunc.reset();
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
        const d = new Date(dateStr);
        // Considerando que a API retorna YYYY-MM-DD
        return d.toLocaleDateString('pt-BR');
    }

    function loadFuncionarios() {
        fetch('/accounts/api/users/', { headers: getAuthHeaders() })
            .then(res => {
                if(res.status === 403) {
                    Swal.fire('Acesso Negado', 'Você não tem permissão para visualizar esta página.', 'error');
                    throw new Error('Forbidden');
                }
                return res.json();
            })
            .then(data => {
                tbody.innerHTML = '';
                if(data.length === 0) return tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Nenhum funcionário encontrado.</td></tr>';
                
                data.forEach(user => {
                    const userPapel = user.papel || user.tipo_usuario || 'VENDEDOR';
                    const papelMap = {
                        'ADMIN': { label: 'Administrador', cls: 'badge-role-admin' },
                        'GERENTE': { label: 'Gerente', cls: 'badge-role-gerente' },
                        'RESPONSAVEL_TECNICO': { label: 'Resp. Técnico', cls: 'badge-role-rt' },
                        'OPERADOR_PATIO': { label: 'Op. Pátio', cls: 'badge-role-operador' },
                        'MOTORISTA': { label: 'Motorista', cls: 'badge-role-motorista' },
                        'VENDEDOR': { label: 'Vendedor', cls: 'badge-role-vendedor' }
                    };
                    const papelInfo = papelMap[userPapel] || { label: userPapel, cls: 'badge-role-vendedor' };
                    let cargo = '-';
                    let admissao = '-';
                    if(user.userprofile && user.userprofile.dadostrabalhistas) {
                        cargo = user.userprofile.dadostrabalhistas.cargo || '-';
                        admissao = formatDate(user.userprofile.dadostrabalhistas.data_admissao);
                    }
                    
                    const nomeCompleto = `${user.first_name} ${user.last_name}`.trim() || user.username;

                    tbody.innerHTML += `
                        <tr>
                            <td>
                                <strong>${nomeCompleto}</strong><br>
                                <small style="color:var(--color-text-muted)">@${user.username} | ${user.email || 'Sem e-mail'}</small>
                            </td>
                            <td>${cargo}</td>
                            <td><span class="badge-role ${papelInfo.cls}">${papelInfo.label}</span></td>
                            <td>${admissao}</td>
                            <td style="text-align: right;">
                                <button class="btn-secondary" style="padding:6px 12px; font-size:12px;" onclick="abrirDetalhesFuncionario(${user.id})">Ver Perfil</button>
                            </td>
                        </tr>
                    `;
                });
            })
            .catch(err => console.error(err));
    }

    formFunc.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const formData = new FormData(formFunc);

        fetch('/accounts/api/users/', {
            method: 'POST',
            headers: getAuthHeadersMultipart(),
            body: formData
        })
        .then(async res => {
            if (res.ok) {
                Swal.fire({
                    icon: 'success',
                    title: 'Sucesso',
                    text: 'Funcionário cadastrado com sucesso!',
                    timer: 2000,
                    showConfirmButton: false
                });
                closeModal();
                loadFuncionarios();
            } else {
                const err = await res.json();
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

    // Detalhes Funcionário
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
                
                const papelMap = {
                    'ADMIN': { label: 'Administrador', cls: 'badge-role-admin' },
                    'GERENTE': { label: 'Gerente', cls: 'badge-role-gerente' },
                    'RESPONSAVEL_TECNICO': { label: 'Resp. Técnico', cls: 'badge-role-rt' },
                    'OPERADOR_PATIO': { label: 'Op. Pátio', cls: 'badge-role-operador' },
                    'MOTORISTA': { label: 'Motorista', cls: 'badge-role-motorista' },
                    'VENDEDOR': { label: 'Vendedor', cls: 'badge-role-vendedor' }
                };
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

                if(data.userprofile) {
                    cpf = data.userprofile.cpf || '-';
                    rg = data.userprofile.rg || '-';
                    nasc = formatDate(data.userprofile.birth_date);
                    tel = data.userprofile.telefone || '-';
                    
                    if(data.userprofile.foto_perfil) {
                        document.getElementById('det-func-foto').src = data.userprofile.foto_perfil;
                        document.getElementById('det-func-foto').style.display = 'block';
                        document.getElementById('det-func-avatar').style.display = 'none';
                    } else {
                        document.getElementById('det-func-foto').style.display = 'none';
                        document.getElementById('det-func-avatar').style.display = 'block';
                    }
                    
                    if(data.userprofile.dadostrabalhistas) {
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
    }

    loadFuncionarios();
});
