/**
 * Perfil Regulatório ANVISA & Gestão de Responsáveis Técnicos (CRF/CRQ)
 */

document.addEventListener('DOMContentLoaded', () => {
    const formPerfil = document.getElementById('form-perfil-regulatorio');
    const dialogRt = document.getElementById('dialog-novo-rt');
    const btnNovoRt = document.getElementById('btn-abrir-modal-rt');
    const btnFecharRt = document.getElementById('btn-fechar-modal-rt');
    const btnCancelarRt = document.getElementById('btn-cancelar-modal-rt');
    const formRt = document.getElementById('form-rt');

    // Abre modal para cadastrar novo RT
    if (btnNovoRt && dialogRt) {
        btnNovoRt.addEventListener('click', () => {
            document.getElementById('modal-rt-title').textContent = 'Cadastrar Responsável Técnico (RT)';
            document.getElementById('rt-id-input').value = '';
            formRt.reset();
            document.getElementById('rt-ativo-input').checked = true;
            dialogRt.showModal();
        });
    }

    // Fecha modal
    const fecharDialog = () => {
        if (dialogRt && dialogRt.open) dialogRt.close();
    };
    if (btnFecharRt) btnFecharRt.addEventListener('click', fecharDialog);
    if (btnCancelarRt) btnCancelarRt.addEventListener('click', fecharDialog);

    // Salvar Perfil Regulatório via AJAX
    if (formPerfil) {
        formPerfil.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(formPerfil);
            formData.append('action', 'salvar_perfil');

            const btnSubmit = formPerfil.querySelector('button[type="submit"]');
            const originalText = btnSubmit.innerHTML;
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = 'Salvando...';

            try {
                const res = await fetch(window.location.href, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });
                const data = await res.json();
                if (data.sucesso) {
                    mostrarToast('Perfil Regulatório salvo com sucesso!', 'success');
                    setTimeout(() => window.location.reload(), 800);
                } else {
                    mostrarToast(data.erro || 'Erro ao salvar perfil.', 'danger');
                }
            } catch (err) {
                console.error(err);
                mostrarToast('Erro na conexão com o servidor.', 'danger');
            } finally {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = originalText;
            }
        });
    }

    // Salvar RT via AJAX
    if (formRt) {
        formRt.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(formRt);
            formData.append('action', 'salvar_rt');

            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            formData.append('csrfmiddlewaretoken', csrfToken);

            try {
                const res = await fetch(window.location.href, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });
                const data = await res.json();
                if (data.sucesso) {
                    mostrarToast(data.mensagem || 'RT salvo com sucesso!', 'success');
                    fecharDialog();
                    setTimeout(() => window.location.reload(), 700);
                } else {
                    mostrarToast(data.erro || 'Erro ao salvar RT.', 'danger');
                }
            } catch (err) {
                console.error(err);
                mostrarToast('Erro de comunicação.', 'danger');
            }
        });
    }

    // Ação: Definir RT como Titular Vigente
    document.querySelectorAll('.btn-definir-titular').forEach(btn => {
        btn.addEventListener('click', async () => {
            const rtId = btn.getAttribute('data-rt-id');
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

            const formData = new FormData();
            formData.append('action', 'definir_rt_vigente');
            formData.append('rt_id', rtId);
            formData.append('csrfmiddlewaretoken', csrfToken);

            try {
                const res = await fetch(window.location.href, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });
                const data = await res.json();
                if (data.sucesso) {
                    mostrarToast(data.mensagem, 'success');
                    setTimeout(() => window.location.reload(), 600);
                } else {
                    mostrarToast(data.erro || 'Falha ao definir titular.', 'danger');
                }
            } catch (err) {
                console.error(err);
                mostrarToast('Erro ao contatar o servidor.', 'danger');
            }
        });
    });

    // Função de Toast
    function mostrarToast(msg, tipo = 'info') {
        let toast = document.getElementById('reg-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'reg-toast';
            toast.style.position = 'fixed';
            toast.style.bottom = '24px';
            toast.style.right = '24px';
            toast.style.padding = '12px 20px';
            toast.style.borderRadius = '8px';
            toast.style.fontSize = '14px';
            toast.style.fontWeight = '600';
            toast.style.color = '#fff';
            toast.style.zIndex = '9999';
            toast.style.boxShadow = '0 10px 25px rgba(0,0,0,0.2)';
            toast.style.transition = 'all 0.3s ease';
            document.body.appendChild(toast);
        }

        if (tipo === 'success') {
            toast.style.background = '#15803d';
        } else if (tipo === 'danger') {
            toast.style.background = '#b91c1c';
        } else {
            toast.style.background = '#0284c7';
        }

        toast.textContent = msg;
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px)';
        }, 3500);
    }
});
