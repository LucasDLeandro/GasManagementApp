// Backoffice Baros — ações das telas (/baros-admin/). Sem dependências além do SweetAlert2 (static/vendor).
(function () {
    'use strict';

    function csrf() {
        const item = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('csrftoken='));
        return item ? decodeURIComponent(item.split('=')[1]) : '';
    }

    async function enviar(url, dados, { json = false } = {}) {
        const headers = { 'X-CSRFToken': csrf(), 'Accept': 'application/json' };
        let body;
        if (json) {
            headers['Content-Type'] = 'application/json';
            body = JSON.stringify(dados || {});
        } else {
            body = new URLSearchParams(dados || {});
        }
        const resp = await fetch(url, { method: 'POST', headers, body, credentials: 'same-origin' });
        let corpo = null;
        try { corpo = await resp.json(); } catch (e) { corpo = null; }
        if (!resp.ok || (corpo && corpo.sucesso === false)) {
            const msg = (corpo && (corpo.erro || corpo.error || (corpo.erros && corpo.erros.join(' '))))
                || (resp.status === 403 ? 'Sessão expirada ou sem permissão. Faça login de novo.' : 'Não foi possível concluir a operação.');
            throw new Error(msg);
        }
        return corpo || {};
    }

    function toast(icon, title) {
        Swal.fire({ toast: true, position: 'top-end', icon, title, showConfirmButton: false, timer: 2800, timerProgressBar: true });
    }

    async function confirmar({ titulo, texto = '', botao = 'Confirmar', perigo = false, motivo = 0 }) {
        const config = {
            title: titulo, text: texto, icon: perigo ? 'warning' : 'question',
            showCancelButton: true, confirmButtonText: botao, cancelButtonText: 'Cancelar',
            reverseButtons: true, focusCancel: perigo,
        };
        if (perigo) config.confirmButtonColor = '#dc2626';
        if (motivo) {
            config.input = 'textarea';
            config.inputLabel = 'Motivo (mínimo ' + motivo + ' caracteres)';
            config.inputValidator = (v) => (!v || v.trim().length < motivo) ? 'Informe um motivo com pelo menos ' + motivo + ' caracteres.' : undefined;
        }
        const r = await Swal.fire(config);
        if (!r.isConfirmed) return null;
        return motivo ? r.value.trim() : true;
    }

    function recarregar(msg) {
        if (msg) sessionStorage.setItem('bo-toast', msg);
        window.location.reload();
    }

    const pendente = sessionStorage.getItem('bo-toast');
    if (pendente) {
        sessionStorage.removeItem('bo-toast');
        toast('success', pendente);
    }

    // ---- Módulos (interruptores) ----
    document.querySelectorAll('[data-acao="toggle-modulo"]').forEach((input) => {
        input.addEventListener('change', async () => {
            const ativo = input.checked;
            input.disabled = true;
            try {
                await enviar(input.dataset.url, { modulo: input.dataset.modulo, ativo: String(ativo) });
                toast('success', (ativo ? 'Ativado: ' : 'Desativado: ') + input.dataset.rotulo);
            } catch (e) {
                input.checked = !ativo;
                Swal.fire({ icon: 'error', title: 'Não foi possível alterar o módulo', text: e.message });
            } finally {
                input.disabled = false;
            }
        });
    });

    // ---- Assinatura ----
    document.querySelectorAll('[data-acao="assinatura"]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const destino = btn.dataset.status;
            const exigeMotivo = destino !== 'ATIVO' || btn.dataset.atual === 'CANCELADO';
            const motivo = await confirmar({
                titulo: btn.dataset.rotulo + ' a assinatura?',
                texto: 'Empresa: ' + btn.dataset.tenant,
                botao: btn.dataset.rotulo,
                perigo: destino !== 'ATIVO',
                motivo: exigeMotivo ? 10 : 0,
            });
            if (!motivo) return;
            try {
                await enviar(btn.dataset.url, { novo_status: destino, motivo: motivo === true ? '' : motivo });
                recarregar('Assinatura atualizada.');
            } catch (e) {
                Swal.fire({ icon: 'error', title: 'Transição não permitida', text: e.message });
            }
        });
    });

    // ---- Suporte (break-glass) ----
    document.querySelectorAll('[data-acao="break-glass"]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const motivo = await confirmar({
                titulo: 'Iniciar acesso de suporte?',
                texto: 'O acesso dura 30 minutos, fica registrado e mostra um banner vermelho no app de ' + btn.dataset.tenant + '.',
                botao: 'Iniciar e abrir o app',
                motivo: 10,
            });
            if (!motivo) return;
            try {
                const r = await enviar(btn.dataset.url, { motivo, abrir_app: '1' });
                window.location.href = r.redirect || '/inicio/';
            } catch (e) {
                Swal.fire({ icon: 'error', title: 'Não foi possível iniciar o acesso', text: e.message });
            }
        });
    });

    document.querySelectorAll('[data-acao="encerrar-acesso"]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            if (!await confirmar({ titulo: 'Encerrar o acesso de suporte agora?', botao: 'Encerrar' })) return;
            try {
                await enviar(btn.dataset.url, {});
                recarregar('Acesso encerrado.');
            } catch (e) {
                Swal.fire({ icon: 'error', title: 'Erro', text: e.message });
            }
        });
    });

    // ---- Faturas SaaS ----
    document.querySelectorAll('[data-acao="fatura-status"]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const status = btn.dataset.status;
            const rotulos = { PAGO: 'Marcar como paga', VENCIDO: 'Marcar como vencida', CANCELADO: 'Cancelar fatura', PENDENTE: 'Voltar para pendente' };
            if (!await confirmar({ titulo: rotulos[status] + '?', texto: btn.dataset.descricao, botao: rotulos[status], perigo: status === 'CANCELADO' })) return;
            try {
                await enviar(btn.dataset.url, { status });
                recarregar('Fatura atualizada.');
            } catch (e) {
                Swal.fire({ icon: 'error', title: 'Erro', text: e.message });
            }
        });
    });

    // ---- Formulários enviados como JSON (nova fatura, lote, planos) ----
    document.querySelectorAll('form[data-acao="enviar-json"]').forEach((form) => {
        form.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const dados = {};
            new FormData(form).forEach((v, k) => { dados[k] = v; });
            form.querySelectorAll('input[type="checkbox"]').forEach((cb) => { dados[cb.name] = cb.checked; });
            const botao = form.querySelector('[type="submit"]');
            if (botao) botao.disabled = true;
            try {
                const r = await enviar(form.action, dados, { json: true });
                const dialogo = form.closest('dialog');
                if (dialogo) dialogo.close();
                let msg = form.dataset.sucesso || 'Salvo.';
                if (r.criadas !== undefined) msg = r.criadas + ' fatura(s) criada(s); ' + r.ja_existentes + ' já existiam.';
                recarregar(msg);
            } catch (e) {
                Swal.fire({ icon: 'error', title: 'Não foi possível salvar', text: e.message });
            } finally {
                if (botao) botao.disabled = false;
            }
        });
    });

    // ---- Diálogos nativos ----
    document.querySelectorAll('[data-abrir-dialogo]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const dialogo = document.getElementById(btn.dataset.abrirDialogo);
            if (!dialogo) return;
            const form = dialogo.querySelector('form');
            if (form && btn.dataset.preencher) {
                const valores = JSON.parse(btn.dataset.preencher);
                if (btn.dataset.action) form.action = btn.dataset.action;
                Object.entries(valores).forEach(([nome, valor]) => {
                    const campo = form.elements[nome];
                    if (!campo) return;
                    if (campo.type === 'checkbox') campo.checked = !!valor; else campo.value = valor;
                });
                const titulo = dialogo.querySelector('[data-titulo]');
                if (titulo && btn.dataset.titulo) titulo.textContent = btn.dataset.titulo;
            } else if (form && btn.dataset.action) {
                form.reset();
                form.action = btn.dataset.action;
                const titulo = dialogo.querySelector('[data-titulo]');
                if (titulo && btn.dataset.titulo) titulo.textContent = btn.dataset.titulo;
            }
            dialogo.showModal();
        });
    });
    document.querySelectorAll('dialog [data-fechar]').forEach((btn) => {
        btn.addEventListener('click', () => btn.closest('dialog').close());
    });

    window.BarosAdmin = { enviar, confirmar, toast };
})();
