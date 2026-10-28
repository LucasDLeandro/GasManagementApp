// ---- Gerenciamento de Sessão & Tokens JWT (Core) ----
window.isJwtExpired = function(token) {
    if (!token || typeof token !== 'string') return true;
    try {
        const parts = token.split('.');
        if (parts.length !== 3) return true;
        const payloadStr = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
        const payload = JSON.parse(payloadStr);
        if (!payload.exp) return false;
        return (payload.exp * 1000) <= (Date.now() + 10000);
    } catch (e) {
        return true;
    }
};

window.renovarTokenSeNecessario = async function() {
    let access = localStorage.getItem('access_token') || localStorage.getItem('access');
    const refresh = localStorage.getItem('refresh_token');

    if (access && !window.isJwtExpired(access)) {
        return access;
    }

    if (refresh && !window.isJwtExpired(refresh)) {
        try {
            const res = await fetch('/api/token/refresh/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh })
            });
            if (res.ok) {
                const data = await res.json();
                if (data.access) {
                    localStorage.setItem('access_token', data.access);
                    localStorage.setItem('access', data.access);
                    return data.access;
                }
            } else {
                localStorage.removeItem('access_token');
                localStorage.removeItem('access');
                localStorage.removeItem('refresh_token');
            }
        } catch (e) {
            console.warn('Falha na renovação silenciosa do token JWT:', e);
        }
    } else {
        localStorage.removeItem('access_token');
        localStorage.removeItem('access');
    }
    return null;
};

// Executa verificação inicial de autenticação
(function verificarAutenticacaoInicial() {
    const metaUserId = document.querySelector('meta[name="current-user-id"]');
    const isSessionAuth = metaUserId && metaUserId.content && metaUserId.content.trim() !== '';
    const hasAnyToken = localStorage.getItem('access_token') || localStorage.getItem('refresh_token');

    // Se não há sessão web ativa nem tokens no localStorage, redireciona para login
    if (!isSessionAuth && !hasAnyToken) {
        window.location.href = '/accounts/login/';
        return;
    }

    // Se há tokens, garante que estão válidos ou tenta renovar em segundo plano
    if (hasAnyToken) {
        window.renovarTokenSeNecessario();
    }
})();


const btnLogout = document.getElementById('btn-logout');

// Sem o botão (página sem a topbar), um erro aqui interromperia o resto do core.js.
if (btnLogout) btnLogout.addEventListener('click', async(event) => {
    event.preventDefault();

    const sair = await Swal.fire({
        title: "Deseja realmente sair?",
        icon: "warning",
        buttons: true,
        showCancelButton: true,
        confirmButtonText: "Sim",
        cancelButtonText: "Não"
    })

    if (sair.isConfirmed) {
        // Limpa todos os caches do Service Worker e do navegador (D5)
        try {
            if ('caches' in window) {
                const cacheNames = await caches.keys();
                await Promise.all(cacheNames.map(name => caches.delete(name)));
            }
            if (navigator.serviceWorker && navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({ action: 'CLEAR_CACHES' });
            }
        } catch (e) {
            console.warn('Erro ao limpar caches no logout:', e);
        }
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('current_tenant_id');
        localStorage.removeItem('current_user_id');
        sessionStorage.clear();
        window.location.href = '/accounts/login/';
    }
});

const userMenuBtn = document.getElementById('user-menu-btn');
const userDropdownMenu = document.getElementById('user-dropdown-menu');

if (userMenuBtn && userDropdownMenu) {
    userMenuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        userDropdownMenu.style.display = userDropdownMenu.style.display === 'none' ? 'block' : 'none';
    });

    document.addEventListener('click', (e) => {
        if (!userMenuBtn.contains(e.target) && !userDropdownMenu.contains(e.target)) {
            userDropdownMenu.style.display = 'none';
        }
    });
}

// ---- Theme Toggle Logic (Light / Dark / High-Contrast Sun) ----
const themeToggle = document.getElementById('theme-toggle');
const themeIcon = document.getElementById('theme-icon');

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    if (!themeIcon) return;

    if (theme === 'dark') {
        themeIcon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
        themeToggle.setAttribute('title', 'Tema Escuro (Clique para Alto Contraste Solar)');
    } else if (theme === 'high-contrast-sun') {
        themeIcon.innerHTML = '<circle cx="12" cy="12" r="4" fill="currentColor"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" stroke-width="2.5"></path>';
        themeToggle.setAttribute('title', 'Tema Solar Alto Contraste (Clique para Modo Claro)');
    } else {
        themeIcon.innerHTML = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
        themeToggle.setAttribute('title', 'Tema Claro (Clique para Modo Escuro)');
    }
}

if (themeToggle) {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    setTheme(currentTheme);

    themeToggle.addEventListener('click', () => {
        const active = document.documentElement.getAttribute('data-theme') || 'light';
        let next = 'light';
        if (active === 'light') next = 'dark';
        else if (active === 'dark') next = 'high-contrast-sun';
        else next = 'light';
        setTheme(next);
    });
}

// ---- Botão Global de Cópia em 1-Clique para IDs Técnicos (.copy-btn) ----
document.addEventListener('click', (e) => {
    const copyBtn = e.target.closest('.copy-btn');
    if (copyBtn) {
        e.preventDefault();
        e.stopPropagation();
        const textToCopy = copyBtn.getAttribute('data-copy') || copyBtn.parentElement.textContent.replace(/\s+/g, ' ').trim();
        if (textToCopy && navigator.clipboard) {
            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalHtml = copyBtn.innerHTML;
                copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
                setTimeout(() => { copyBtn.innerHTML = originalHtml; }, 1500);
            }).catch(err => console.warn('Falha ao copiar:', err));
        }
    }
});

// ---- MÁSCARAS & FORMATAÇÃO UNIVERSAL PT-BR (DESIGN SYSTEM) ----
window.formatCurrencyBR = function(val) {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val || 0);
};

window.formatDateBR = function(dateStr) {
    if (!dateStr) return '-';
    const parts = dateStr.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    const d = new Date(dateStr);
    return isNaN(d) ? dateStr : d.toLocaleDateString('pt-BR');
};

function applyMask(value, type) {
    if (!value) return '';
    const clean = value.replace(/\D/g, '');
    
    if (type === 'cnpj') {
        return clean.slice(0, 14)
            .replace(/^(\d{2})(\d)/, '$1.$2')
            .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
            .replace(/\.(\d{3})(\d)/, '.$1/$2')
            .replace(/(\d{4})(\d)/, '$1-$2');
    }
    if (type === 'cpf') {
        return clean.slice(0, 11)
            .replace(/^(\d{3})(\d)/, '$1.$2')
            .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
            .replace(/\.(\d{3})(\d)/, '.$1-$2');
    }
    if (type === 'phone') {
        if (clean.length > 10) {
            return clean.slice(0, 11)
                .replace(/^(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
        } else {
            return clean.slice(0, 10)
                .replace(/^(\d{2})(\d{4})(\d{4})/, '($1) $2-$3');
        }
    }
    if (type === 'cep') {
        return clean.slice(0, 8)
            .replace(/^(\d{5})(\d)/, '$1-$2');
    }
    if (type === 'placa') {
        const valUpper = value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 7);
        if (valUpper.length > 3) {
            return valUpper.slice(0, 3) + '-' + valUpper.slice(3);
        }
        return valUpper;
    }
    return value;
}

// Auto-detector de campos para máscaras e fontes mono via Event Delegation
document.addEventListener('input', (e) => {
    const input = e.target;
    if (!input || input.tagName !== 'INPUT') return;

    const name = (input.name || '').toLowerCase();
    const id = (input.id || '').toLowerCase();
    const cls = input.className.toLowerCase();

    if (name.includes('cnpj') || id.includes('cnpj') || cls.includes('mask-cnpj')) {
        input.classList.add('font-mono');
        input.value = applyMask(input.value, 'cnpj');
    } else if (name.includes('cpf') || id.includes('cpf') || cls.includes('mask-cpf')) {
        input.classList.add('font-mono');
        input.value = applyMask(input.value, 'cpf');
    } else if (name.includes('tel') || id.includes('tel') || name.includes('phone') || cls.includes('mask-phone')) {
        input.classList.add('font-mono');
        input.value = applyMask(input.value, 'phone');
    } else if (name.includes('placa') || id.includes('placa') || cls.includes('mask-placa')) {
        input.classList.add('font-mono');
        input.value = applyMask(input.value, 'placa');
    } else if (name.includes('cep') || id.includes('cep') || cls.includes('mask-cep')) {
        input.classList.add('font-mono');
        input.value = applyMask(input.value, 'cep');
    } else if (name.includes('serie') || name.includes('codigo_qr') || name.includes('lote') || name.includes('matricula')) {
        input.classList.add('font-mono');
    }
});

// Toast / Feedback Unificado Nativo
window.showToast = function({ icon = 'success', title = 'Sucesso', text = '' }) {
    if (typeof Swal !== 'undefined') {
        const Toast = Swal.mixin({
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 3000,
            timerProgressBar: true,
            didOpen: (toast) => {
                toast.addEventListener('mouseenter', Swal.stopTimer);
                toast.addEventListener('mouseleave', Swal.resumeTimer);
            }
        });
        Toast.fire({ icon, title, text });
    } else {
        alert(`${title}: ${text}`);
    }
};

// ---- Gerenciador do Menu Lateral / Sidebar (Mobile, Tablet & Desktop) ----
(function initSidebarToggle() {
    const toggleBtn = document.getElementById('toggle-sidebar');
    const sidebar = document.getElementById('app-sidebar') || document.querySelector('.sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');

    if (!toggleBtn || !sidebar) return;

    function isMobileOrTablet() {
        return window.innerWidth <= 1024;
    }

    function closeSidebar() {
        sidebar.classList.remove('open');
        if (backdrop) backdrop.classList.remove('active');
        document.body.classList.remove('sidebar-drawer-active');
    }

    function openSidebar() {
        sidebar.classList.add('open');
        if (backdrop) backdrop.classList.add('active');
        document.body.classList.add('sidebar-drawer-active');
    }

    toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (isMobileOrTablet()) {
            if (sidebar.classList.contains('open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        } else {
            // Desktop: alterna estado recolhido (collapsed)
            sidebar.classList.toggle('collapsed');
        }
    });

    if (backdrop) {
        backdrop.addEventListener('click', () => {
            closeSidebar();
        });
    }

    // Fecha ao pressionar Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar.classList.contains('open')) {
            closeSidebar();
        }
    });

    // Fecha gaveta em mobile/tablet ao clicar em qualquer item do menu
    sidebar.addEventListener('click', (e) => {
        const link = e.target.closest('a');
        if (link && isMobileOrTablet()) {
            closeSidebar();
        }
    });

    // Ajusta classes ao redimensionar a tela
    window.addEventListener('resize', () => {
        if (!isMobileOrTablet() && sidebar.classList.contains('open')) {
            closeSidebar();
        }
    });
})();

// ==========================================================================
// Design System v1 — utilitários compartilhados (docs/DESIGN_SYSTEM.md, seção 6)
// ==========================================================================
(function (global) {
    'use strict';

    function lerCookie(nome) {
        const item = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith(nome + '='));
        return item ? decodeURIComponent(item.split('=').slice(1).join('=')) : '';
    }

    function cabecalhos(extra) {
        const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': lerCookie('csrftoken') };
        let token = localStorage.getItem('access_token') || localStorage.getItem('access');
        if (token && global.isJwtExpired && global.isJwtExpired(token)) token = null;
        if (token) headers['Authorization'] = 'Bearer ' + token;
        const meta = document.querySelector('meta[name="current-tenant-id"]');
        if (meta && meta.content) headers['X-Tenant-ID'] = meta.content;
        return Object.assign(headers, extra || {});
    }

    const CHAVES_MENSAGEM = ['error', 'erro', 'detail', 'mensagem', 'non_field_errors'];

    class ApiError extends Error {
        constructor(status, corpo) {
            const campos = {};
            let mensagem = '';
            if (corpo && typeof corpo === 'object') {
                mensagem = corpo.error || corpo.erro || corpo.detail || corpo.mensagem
                    || (Array.isArray(corpo.non_field_errors) ? corpo.non_field_errors[0] : '') || '';
                Object.keys(corpo).forEach((chave) => {
                    if (CHAVES_MENSAGEM.includes(chave)) return;
                    const valor = corpo[chave];
                    campos[chave] = Array.isArray(valor) ? valor.join(' ') : String(valor);
                });
                if (!mensagem && Object.keys(campos).length) mensagem = 'Confira os campos destacados.';
            } else if (typeof corpo === 'string' && corpo) {
                mensagem = corpo.slice(0, 300);
            }
            if (status === 403 && !mensagem) mensagem = 'Você não tem permissão para esta ação.';
            if (status >= 500) mensagem = 'Erro interno no servidor. Tente de novo em instantes.';
            super(mensagem || 'Não foi possível concluir a operação.');
            this.name = 'ApiError';
            this.status = status;
            this.mensagem = this.message;
            this.campos = campos;
            this.corpo = corpo;
        }
    }

    async function api(url, opcoes) {
        const opts = opcoes || {};
        if (global.renovarTokenSeNecessario) {
            try { await global.renovarTokenSeNecessario(); } catch (e) { /* segue com a sessão */ }
        }
        const init = {
            method: (opts.method || 'GET').toUpperCase(),
            headers: cabecalhos(opts.headers),
            credentials: 'same-origin',
        };
        if (opts.body !== undefined) {
            if (opts.body instanceof FormData) {
                delete init.headers['Content-Type'];
                init.body = opts.body;
            } else {
                init.body = typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);
            }
        }
        let resposta;
        try {
            resposta = await fetch(url, init);
        } catch (e) {
            throw new ApiError(0, 'Sem conexão com o servidor. Verifique sua internet.');
        }
        const tipo = resposta.headers.get('content-type') || '';
        let corpo = null;
        if (resposta.status !== 204) {
            corpo = tipo.includes('application/json')
                ? await resposta.json().catch(() => null)
                : await resposta.text();
        }
        if (!resposta.ok) throw new ApiError(resposta.status, corpo);
        return corpo;
    }

    function toast(icon, texto) {
        if (global.showToast) global.showToast({ icon, title: texto });
    }

    async function confirmar(opcoes) {
        const o = Object.assign({ titulo: 'Confirmar?', texto: '', botao: 'Confirmar', perigo: false, motivo: false }, opcoes || {});
        const minimo = o.motivo === true ? 10 : (Number(o.motivo) || 0);
        const config = {
            title: o.titulo,
            text: o.texto,
            icon: o.perigo ? 'warning' : 'question',
            showCancelButton: true,
            confirmButtonText: o.botao,
            cancelButtonText: 'Cancelar',
            reverseButtons: true,
            focusCancel: !!o.perigo,
        };
        if (o.perigo) config.confirmButtonColor = '#dc2626';
        if (minimo) {
            config.input = 'textarea';
            config.inputLabel = 'Motivo (mínimo ' + minimo + ' caracteres)';
            config.inputValidator = (v) => ((!v || v.trim().length < minimo)
                ? 'Informe um motivo com pelo menos ' + minimo + ' caracteres.'
                : undefined);
        }
        const r = await Swal.fire(config);
        if (!r.isConfirmed) return null;
        return minimo ? r.value.trim() : true;
    }

    function carregando(botao, texto) {
        if (!botao) return () => {};
        const original = botao.innerHTML;
        botao.disabled = true;
        botao.setAttribute('aria-busy', 'true');
        if (texto) botao.textContent = texto;
        return () => {
            botao.disabled = false;
            botao.removeAttribute('aria-busy');
            botao.innerHTML = original;
        };
    }

    function limparErros(raiz) {
        raiz.querySelectorAll('.ds-field-error').forEach(el => el.remove());
        raiz.querySelectorAll('.form-group.ds-invalid').forEach(el => el.classList.remove('ds-invalid'));
    }

    function marcarErro(campo, mensagem) {
        const grupo = campo.closest('.form-group') || campo.parentElement;
        grupo.classList.add('ds-invalid');
        const aviso = document.createElement('span');
        aviso.className = 'ds-field-error';
        aviso.textContent = mensagem;
        grupo.appendChild(aviso);
    }

    function validarCampos(seletor) {
        const raiz = typeof seletor === 'string' ? document.querySelector(seletor) : seletor;
        if (!raiz) return true;
        limparErros(raiz);
        let primeiro = null;
        raiz.querySelectorAll('input, select, textarea').forEach((campo) => {
            if (campo.disabled || campo.type === 'hidden' || campo.checkValidity()) return;
            marcarErro(campo, campo.validationMessage);
            primeiro = primeiro || campo;
        });
        if (primeiro) primeiro.focus();
        return !primeiro;
    }

    function mostrarErrosApi(form, erro) {
        const raiz = typeof form === 'string' ? document.querySelector(form) : form;
        if (raiz) limparErros(raiz);
        const naoMapeados = [];
        Object.entries((erro && erro.campos) || {}).forEach(([nome, mensagem]) => {
            const campo = raiz ? raiz.querySelector('[name="' + nome + '"]') : null;
            if (campo) marcarErro(campo, mensagem); else naoMapeados.push(mensagem);
        });
        const texto = [erro && erro.mensagem].concat(naoMapeados).filter(Boolean).join(' ');
        toast('error', texto || 'Não foi possível salvar.');
    }

    function dadosDoForm(form) {
        const dados = {};
        new FormData(form).forEach((valor, chave) => { dados[chave] = valor; });
        return dados;
    }

    function Stepper(seletor, opcoes) {
        const raiz = typeof seletor === 'string' ? document.querySelector(seletor) : seletor;
        const o = opcoes || {};
        const itens = Array.from(raiz.querySelectorAll('[data-stepper-nav] .step-item'));
        const paineis = Array.from(raiz.querySelectorAll('.ds-step-pane'));
        const total = paineis.length;
        let atual = 1;

        function render() {
            itens.forEach((item) => {
                const n = Number(item.dataset.step);
                item.classList.toggle('active', n === atual);
                item.classList.toggle('completed', n < atual);
                if (n === atual) item.setAttribute('aria-current', 'step');
                else item.removeAttribute('aria-current');
            });
            paineis.forEach(p => p.classList.toggle('active', Number(p.dataset.step) === atual));
            if (o.aoMudar) o.aoMudar(atual, total);
        }

        const controle = {
            get atual() { return atual; },
            get total() { return total; },
            ir(n) { atual = Math.min(Math.max(1, n), total); render(); },
            proxima() {
                if (o.validar && o.validar(atual) === false) return false;
                if (atual < total) { atual += 1; render(); }
                return true;
            },
            anterior() { if (atual > 1) { atual -= 1; render(); } },
            reiniciar() { atual = 1; render(); },
        };
        render();
        return controle;
    }

    global.Baros = Object.assign(global.Baros || {}, {
        api,
        ApiError,
        confirmar,
        sucesso: (texto) => toast('success', texto),
        erro: (texto) => toast('error', texto),
        aviso: (texto) => toast('warning', texto),
        carregando,
        validarCampos,
        mostrarErrosApi,
        dadosDoForm,
        Stepper,
        moeda: (v) => (global.formatCurrencyBR ? global.formatCurrencyBR(v) : v),
        data: (v) => (global.formatDateBR ? global.formatDateBR(v) : v),
    });
})(window);