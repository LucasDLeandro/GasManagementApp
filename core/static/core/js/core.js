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
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
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

// ---- Dark Mode Logic ----
const themeToggle = document.getElementById('theme-toggle');
const themeIcon = document.getElementById('theme-icon');

function setTheme(isDark) {
    if(isDark) {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('theme', 'dark');
        if(themeIcon) themeIcon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
    } else {
        document.documentElement.setAttribute('data-theme', 'light');
        localStorage.setItem('theme', 'light');
        if(themeIcon) themeIcon.innerHTML = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
    }
}

if(themeToggle) {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    setTheme(isDark);

    themeToggle.addEventListener('click', () => {
        const currentlyDark = document.documentElement.getAttribute('data-theme') === 'dark';
        setTheme(!currentlyDark);
    });
}