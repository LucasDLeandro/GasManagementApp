const form = document.getElementById('login-form');

form.addEventListener('submit', async (event) => {
    event.preventDefault();

    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    try {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
        const response = await fetch('/accounts/api/login/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                username: username,
                password: password,
            })
        });

        let dados;
        try {
            dados = await response.json();
        } catch(e) {
            throw new Error("Erro no servidor (não retornou JSON). Verifique o console.");
        }

        if (response.ok) {
            localStorage.setItem('access_token', dados.access);
            localStorage.setItem('refresh_token', dados.refresh);
            
            await Swal.fire({
                title: "Login bem-sucedido!",
                icon: "success",
                confirmButtonText: "OK"
            });
            window.location.href = '/inicio/';
        } else {
            await Swal.fire({
                title: "Erro ao fazer login!",
                text: dados.detail || "Credenciais inválidas",
                icon: "error",
                confirmButtonText: "OK"
            });
        }
    } catch (error) {
        console.error('Erro ao fazer login:', error);
        Swal.fire({
            title: "Erro interno",
            text: error.message,
            icon: "error",
            confirmButtonText: "OK"
        });
    }
});
