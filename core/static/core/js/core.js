const token = localStorage.getItem('access_token')

if (!token) {
    window.location.href = '/accounts/login/';
}

const btnLogout = document.getElementById('btn-logout');

btnLogout.addEventListener('click', async(event) => {
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