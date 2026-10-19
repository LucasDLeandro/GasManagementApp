/**
 * Baros - Gestão de Webhooks HMAC, Delivery Logs e Exportações Canônicas ERP (Fase 5)
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Alternância de Abas
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.style.display = 'none');

            btn.classList.add('active');
            const targetId = btn.getAttribute('data-target');
            const targetContent = document.getElementById(targetId);
            if (targetContent) targetContent.style.display = 'block';
        });
    });

    // Helper CSRF & Auth
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

    function getHeaders(isJson = true) {
        const headers = {
            'X-CSRFToken': getCookie('csrftoken')
        };
        if (isJson) headers['Content-Type'] = 'application/json';
        const token = localStorage.getItem('access_token');
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }

    // ==============================================================================
    // 2. MODAL DE EXIBIÇÃO ÚNICA DE SEGREDO HMAC
    // ==============================================================================
    const modalSecret = document.getElementById('modal-secret-highlight');
    const inputSecretVal = document.getElementById('input-raw-secret');
    const btnCopySecret = document.getElementById('btn-copy-secret');
    const btnCloseSecret = document.getElementById('btn-close-secret');

    window.exibirModalSegredo = function(secretKey) {
        if (!modalSecret || !inputSecretVal) return;
        inputSecretVal.value = secretKey;
        modalSecret.showModal();
    };

    if (btnCopySecret) {
        btnCopySecret.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(inputSecretVal.value);
                const originalText = btnCopySecret.innerHTML;
                btnCopySecret.innerHTML = '✅ Copiado!';
                btnCopySecret.style.background = 'var(--status-approved)';
                setTimeout(() => {
                    btnCopySecret.innerHTML = originalText;
                    btnCopySecret.style.background = '';
                }, 2000);
            } catch (err) {
                inputSecretVal.select();
                document.execCommand('copy');
                alert('Segredo copiado para a área de transferência!');
            }
        });
    }

    if (btnCloseSecret) {
        btnCloseSecret.addEventListener('click', () => {
            modalSecret.close();
            inputSecretVal.value = '';
            carregarEndpoints();
        });
    }

    // ==============================================================================
    // 3. CADASTRO DE WEBHOOK
    // ==============================================================================
    const modalNovoWebhook = document.getElementById('modal-novo-webhook');
    const btnAbrirNovoWebhook = document.getElementById('btn-abrir-novo-webhook');
    const formNovoWebhook = document.getElementById('form-novo-webhook');

    if (btnAbrirNovoWebhook && modalNovoWebhook) {
        btnAbrirNovoWebhook.addEventListener('click', () => modalNovoWebhook.showModal());
    }

    if (formNovoWebhook) {
        formNovoWebhook.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btnSubmit = formNovoWebhook.querySelector('button[type="submit"]');
            btnSubmit.disabled = true;
            btnSubmit.textContent = 'Gravando...';

            const urlVal = document.getElementById('webhook-url').value.trim();
            const descVal = document.getElementById('webhook-descricao').value.trim();
            const ativoVal = document.getElementById('webhook-ativo').checked;

            const eventosChecked = [];
            document.querySelectorAll('input[name="eventos"]:checked').forEach(cb => {
                eventosChecked.push(cb.value);
            });

            if (eventosChecked.length === 0) {
                eventosChecked.push('*');
            }

            try {
                const resp = await fetch('/api/webhooks/', {
                    method: 'POST',
                    headers: getHeaders(true),
                    body: JSON.stringify({
                        url: urlVal,
                        descricao: descVal,
                        eventos: eventosChecked,
                        ativo: ativoVal
                    })
                });

                const data = await resp.json();
                if (!resp.ok) {
                    const errMsg = data.url ? data.url.join(', ') : (data.detail || JSON.stringify(data));
                    throw new Error(errMsg);
                }

                modalNovoWebhook.close();
                formNovoWebhook.reset();

                // Exibe segredo HMAC gerado exclusivamente nesta criação
                if (data.secret_exclusivo) {
                    exibirModalSegredo(data.secret_exclusivo);
                } else {
                    carregarEndpoints();
                }
            } catch (err) {
                alert('Erro ao cadastrar endpoint: ' + err.message);
            } finally {
                btnSubmit.disabled = false;
                btnSubmit.textContent = 'Salvar Endpoint';
            }
        });
    }

    // ==============================================================================
    // 4. LISTAGEM, PING DE TESTE E ROTAÇÃO DE SEGREDO
    // ==============================================================================
    window.carregarEndpoints = async function() {
        const tbody = document.getElementById('tbody-endpoints');
        if (!tbody) return;

        try {
            const resp = await fetch('/api/webhooks/', { headers: getHeaders(false) });
            const data = await resp.json();
            const endpoints = data.results || data;

            if (endpoints.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--color-text-muted); padding: 24px;">Nenhum endpoint de webhook cadastrado para esta empresa.</td></tr>';
                return;
            }

            let html = '';
            endpoints.forEach(ep => {
                const eventosPills = (ep.eventos || []).map(ev => `<span class="badge-event-pill">${ev}</span>`).join(' ');
                const statusBadge = ep.ativo ? '<span class="badge-status badge-status-sucesso">Ativo</span>' : '<span class="badge-status badge-status-falha">Inativo</span>';

                html += `
                    <tr id="row-endpoint-${ep.id}">
                        <td>
                            <strong>${escapeHtml(ep.descricao || 'Sem descrição')}</strong>
                            <div style="font-family: var(--font-family-mono); font-size: 12px; color: var(--color-text-muted); margin-top: 3px;">
                                ${escapeHtml(ep.url)}
                            </div>
                        </td>
                        <td>${eventosPills || '<span class="badge-event-pill">*</span>'}</td>
                        <td><span class="secret-masked">${ep.secret_mascarado || '••••••••••••••••••••••••••••••••'}</span></td>
                        <td>${statusBadge}</td>
                        <td>
                            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                                <button class="btn-action-sm btn-ping-teste" data-id="${ep.id}" title="Dispara evento de teste assinado com HMAC-SHA256">
                                    ⚡ Ping de Teste
                                </button>
                                <button class="btn-action-sm btn-rotacionar-secret" data-id="${ep.id}" title="Rotacionar Chave Criptográfica HMAC">
                                    🔄 Rotacionar Segredo
                                </button>
                                <button class="btn-action-sm btn-action-danger btn-excluir-endpoint" data-id="${ep.id}">
                                    🗑️
                                </button>
                            </div>
                            <div id="ping-feedback-${ep.id}" style="margin-top: 6px; font-size: 11px; font-family: var(--font-family-mono); display: none;"></div>
                        </td>
                    </tr>
                `;
            });

            tbody.innerHTML = html;
            anexarEventosEndpoints();
        } catch (err) {
            console.error('Erro ao listar endpoints:', err);
        }
    };

    function anexarEventosEndpoints() {
        // Disparar Ping de Teste
        document.querySelectorAll('.btn-ping-teste').forEach(btn => {
            btn.addEventListener('click', async () => {
                const epId = btn.getAttribute('data-id');
                const feedbackDiv = document.getElementById(`ping-feedback-${epId}`);
                btn.disabled = true;
                const originalHtml = btn.innerHTML;
                btn.innerHTML = '⏳ Enviando...';

                if (feedbackDiv) {
                    feedbackDiv.style.display = 'block';
                    feedbackDiv.innerHTML = '<span style="color: var(--color-text-muted);">Enviando evento ping.teste assinado com HMAC-SHA256...</span>';
                }

                try {
                    const resp = await fetch(`/api/webhooks/${epId}/testar/`, {
                        method: 'POST',
                        headers: getHeaders(true)
                    });
                    const resData = await resp.json();

                    if (feedbackDiv) {
                        const latenciaStr = resData.latencia_ms ? `${resData.latencia_ms}ms` : 'N/A';
                        if (resData.sucesso) {
                            feedbackDiv.innerHTML = `<span style="color: var(--status-approved); font-weight: 600;">✅ HTTP ${resData.status_code || 200} (${latenciaStr}) - Sucesso!</span>`;
                        } else {
                            feedbackDiv.innerHTML = `<span style="color: var(--status-danger); font-weight: 600;">❌ Falha (${latenciaStr}): HTTP ${resData.status_code || 'Erro'} - ${escapeHtml(resData.resposta || 'Sem resposta')}</span>`;
                        }
                    }
                    carregarLogs();
                } catch (err) {
                    if (feedbackDiv) {
                        feedbackDiv.innerHTML = `<span style="color: var(--status-danger);">❌ Erro na requisição: ${err.message}</span>`;
                    }
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = originalHtml;
                }
            });
        });

        // Rotacionar Segredo HMAC
        document.querySelectorAll('.btn-rotacionar-secret').forEach(btn => {
            btn.addEventListener('click', async () => {
                const epId = btn.getAttribute('data-id');
                if (!confirm('Atenção: Ao rotacionar a chave secreta HMAC, o segredo antigo deixará de funcionar imediatamente. Deseja continuar?')) {
                    return;
                }

                btn.disabled = true;
                try {
                    const resp = await fetch(`/api/webhooks/${epId}/rotacionar-secret/`, {
                        method: 'POST',
                        headers: getHeaders(true)
                    });
                    const resData = await resp.json();
                    if (resData.secret_exclusivo) {
                        exibirModalSegredo(resData.secret_exclusivo);
                    } else {
                        alert(resData.mensagem || 'Chave rotacionada com sucesso!');
                        carregarEndpoints();
                    }
                } catch (err) {
                    alert('Erro ao rotacionar segredo: ' + err.message);
                } finally {
                    btn.disabled = false;
                }
            });
        });

        // Excluir Endpoint
        document.querySelectorAll('.btn-excluir-endpoint').forEach(btn => {
            btn.addEventListener('click', async () => {
                const epId = btn.getAttribute('data-id');
                if (!confirm('Tem certeza de que deseja remover este endpoint de webhook?')) return;

                try {
                    const resp = await fetch(`/api/webhooks/${epId}/`, {
                        method: 'DELETE',
                        headers: getHeaders(false)
                    });
                    if (resp.ok || resp.status === 204) {
                        carregarEndpoints();
                    } else {
                        alert('Erro ao excluir endpoint.');
                    }
                } catch (err) {
                    alert('Erro ao excluir endpoint: ' + err.message);
                }
            });
        });
    }

    // ==============================================================================
    // 5. HISTÓRICO DE ENTREGAS (OUTBOX LOGS / D7)
    // ==============================================================================
    const modalInspect = document.getElementById('modal-inspect-log');
    const inspectPayloadCode = document.getElementById('inspect-payload-code');
    const inspectResponseCode = document.getElementById('inspect-response-code');
    const btnCloseInspect = document.getElementById('btn-close-inspect');

    if (btnCloseInspect && modalInspect) {
        btnCloseInspect.addEventListener('click', () => modalInspect.close());
    }

    window.carregarLogs = async function() {
        const tbody = document.getElementById('tbody-logs');
        if (!tbody) return;

        try {
            const resp = await fetch('/api/webhook-logs/', { headers: getHeaders(false) });
            const data = await resp.json();
            const logs = data.results || data;

            if (logs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--color-text-muted); padding: 24px;">Nenhum disparo registrado na Outbox até o momento.</td></tr>';
                return;
            }

            let html = '';
            logs.forEach(lg => {
                let badgeClass = 'badge-status-pendente';
                if (lg.status === 'SUCESSO') badgeClass = 'badge-status-sucesso';
                if (lg.status === 'FALHA') badgeClass = 'badge-status-falha';

                const latenciaStr = lg.latencia_ms ? `${lg.latencia_ms}ms` : '-';
                const dataEnvioStr = lg.enviado_em ? new Date(lg.enviado_em).toLocaleString('pt-BR') : '-';
                const statusHttpStr = lg.status_code ? `HTTP ${lg.status_code}` : '-';

                const podeReenviar = lg.status === 'FALHA' || lg.status === 'PENDENTE';
                const btnReenviar = podeReenviar
                    ? `<button class="btn-action-sm btn-reenviar-log" data-id="${lg.id}" title="Reenviar este evento imediatamente">🔁 Reenviar</button>`
                    : '';

                html += `
                    <tr>
                        <td style="white-space: nowrap; font-size: 12px;">${dataEnvioStr}</td>
                        <td><span class="badge-event-pill">${escapeHtml(lg.evento)}</span></td>
                        <td style="font-family: var(--font-family-mono); font-size: 11px; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            ${escapeHtml(lg.endpoint_url || '-')}
                        </td>
                        <td><span class="badge-status ${badgeClass}">${lg.status}</span></td>
                        <td>${statusHttpStr}</td>
                        <td><span class="badge-latency">${latenciaStr}</span></td>
                        <td>
                            <div style="display: flex; gap: 6px;">
                                <button class="btn-action-sm btn-inspect-log" data-id="${lg.id}">
                                    👁️ Inspecionar
                                </button>
                                ${btnReenviar}
                            </div>
                        </td>
                    </tr>
                `;
            });

            tbody.innerHTML = html;
            anexarEventosLogs(logs);
        } catch (err) {
            console.error('Erro ao listar logs da Outbox:', err);
        }
    };

    function anexarEventosLogs(logs) {
        // Inspecionar Payload & Resposta
        document.querySelectorAll('.btn-inspect-log').forEach(btn => {
            btn.addEventListener('click', () => {
                const logId = parseInt(btn.getAttribute('data-id'), 10);
                const log = logs.find(l => l.id === logId);
                if (!log || !modalInspect) return;

                inspectPayloadCode.textContent = JSON.stringify(log.payload, null, 2);
                inspectResponseCode.textContent = log.resposta_body || 'Nenhum corpo de resposta recebido.';
                modalInspect.showModal();
            });
        });

        // Reenviar Manualmente
        document.querySelectorAll('.btn-reenviar-log').forEach(btn => {
            btn.addEventListener('click', async () => {
                const logId = btn.getAttribute('data-id');
                btn.disabled = true;
                btn.textContent = 'Enviando...';

                try {
                    const resp = await fetch(`/api/webhook-logs/${logId}/reenviar/`, {
                        method: 'POST',
                        headers: getHeaders(true)
                    });
                    const resData = await resp.json();
                    if (resData.sucesso) {
                        alert(`Reenvio concluído com sucesso! (HTTP ${resData.status_code || 200})`);
                    } else {
                        alert(`Falha no reenvio: HTTP ${resData.status_code || 'Erro'} - ${resData.resposta || ''}`);
                    }
                    carregarLogs();
                } catch (err) {
                    alert('Erro ao reenviar webhook: ' + err.message);
                } finally {
                    btn.disabled = false;
                    btn.textContent = '🔁 Reenviar';
                }
            });
        });
    }

    const btnAtualizarLogs = document.getElementById('btn-atualizar-logs');
    if (btnAtualizarLogs) {
        btnAtualizarLogs.addEventListener('click', () => carregarLogs());
    }

    // ==============================================================================
    // 6. EXPORTAÇÃO CANÔNICA ERP (D9)
    // ==============================================================================
    function atualizarUrlsErp() {
        const host = window.location.origin;

        // Faturas
        const fCompetencia = document.getElementById('erp-fat-competencia')?.value || '';
        const fDtIni = document.getElementById('erp-fat-dt-ini')?.value || '';
        const fDtFim = document.getElementById('erp-fat-dt-fim')?.value || '';
        const fUpdatedSince = document.getElementById('erp-fat-updated-since')?.value || '';

        const paramsFat = new URLSearchParams();
        if (fCompetencia) paramsFat.append('competencia', fCompetencia);
        if (fDtIni) paramsFat.append('data_inicio', fDtIni);
        if (fDtFim) paramsFat.append('data_fim', fDtFim);
        if (fUpdatedSince) paramsFat.append('updated_since', fUpdatedSince);

        const urlFatJson = `${host}/api/erp/faturas/?${paramsFat.toString()}`;
        const inputFatUrl = document.getElementById('erp-fat-api-url');
        if (inputFatUrl) inputFatUrl.textContent = urlFatJson;

        // Entregas
        const eStatus = document.getElementById('erp-ent-status')?.value || '';
        const eDtIni = document.getElementById('erp-ent-dt-ini')?.value || '';
        const eDtFim = document.getElementById('erp-ent-dt-fim')?.value || '';
        const eUpdatedSince = document.getElementById('erp-ent-updated-since')?.value || '';

        const paramsEnt = new URLSearchParams();
        if (eStatus) paramsEnt.append('status', eStatus);
        if (eDtIni) paramsEnt.append('data_inicio', eDtIni);
        if (eDtFim) paramsEnt.append('data_fim', eDtFim);
        if (eUpdatedSince) paramsEnt.append('updated_since', eUpdatedSince);

        const urlEntJson = `${host}/api/erp/entregas/?${paramsEnt.toString()}`;
        const inputEntUrl = document.getElementById('erp-ent-api-url');
        if (inputEntUrl) inputEntUrl.textContent = urlEntJson;
    }

    // Ouvintes de alteração nos filtros ERP
    ['erp-fat-competencia', 'erp-fat-dt-ini', 'erp-fat-dt-fim', 'erp-fat-updated-since',
     'erp-ent-status', 'erp-ent-dt-ini', 'erp-ent-dt-fim', 'erp-ent-updated-since'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', atualizarUrlsErp);
    });

    // Botões de Download Faturas
    const btnDownloadFatJson = document.getElementById('btn-download-fat-json');
    if (btnDownloadFatJson) {
        btnDownloadFatJson.addEventListener('click', () => {
            const url = document.getElementById('erp-fat-api-url')?.textContent;
            if (url) window.open(url, '_blank');
        });
    }

    const btnDownloadFatCsv = document.getElementById('btn-download-fat-csv');
    if (btnDownloadFatCsv) {
        btnDownloadFatCsv.addEventListener('click', () => {
            const baseUrl = document.getElementById('erp-fat-api-url')?.textContent;
            if (baseUrl) {
                const sep = baseUrl.includes('?') ? '&' : '?';
                window.open(`${baseUrl}${sep}format=csv`, '_blank');
            }
        });
    }

    // Botões de Download Entregas
    const btnDownloadEntJson = document.getElementById('btn-download-ent-json');
    if (btnDownloadEntJson) {
        btnDownloadEntJson.addEventListener('click', () => {
            const url = document.getElementById('erp-ent-api-url')?.textContent;
            if (url) window.open(url, '_blank');
        });
    }

    const btnDownloadEntCsv = document.getElementById('btn-download-ent-csv');
    if (btnDownloadEntCsv) {
        btnDownloadEntCsv.addEventListener('click', () => {
            const baseUrl = document.getElementById('erp-ent-api-url')?.textContent;
            if (baseUrl) {
                const sep = baseUrl.includes('?') ? '&' : '?';
                window.open(`${baseUrl}${sep}format=csv`, '_blank');
            }
        });
    }

    // Botões Copiar URL
    const btnCopyFatUrl = document.getElementById('btn-copy-fat-url');
    if (btnCopyFatUrl) {
        btnCopyFatUrl.addEventListener('click', () => {
            const text = document.getElementById('erp-fat-api-url')?.textContent;
            if (text) {
                navigator.clipboard.writeText(text);
                btnCopyFatUrl.textContent = '✅ Copiado!';
                setTimeout(() => btnCopyFatUrl.textContent = '📋 Copiar URL', 2000);
            }
        });
    }

    const btnCopyEntUrl = document.getElementById('btn-copy-ent-url');
    if (btnCopyEntUrl) {
        btnCopyEntUrl.addEventListener('click', () => {
            const text = document.getElementById('erp-ent-api-url')?.textContent;
            if (text) {
                navigator.clipboard.writeText(text);
                btnCopyEntUrl.textContent = '✅ Copiado!';
                setTimeout(() => btnCopyEntUrl.textContent = '📋 Copiar URL', 2000);
            }
        });
    }

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Inicialização
    carregarEndpoints();
    carregarLogs();
    atualizarUrlsErp();
});
