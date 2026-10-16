/**
 * GasManagementApp - Barra de Comando Global (Ctrl+K / Cmd+K)
 * Navegação por teclado, debounce 250ms e busca federada.
 */
document.addEventListener('DOMContentLoaded', () => {
    const dialog = document.getElementById('command-bar-dialog');
    const input = document.getElementById('command-bar-input');
    const resultsContainer = document.getElementById('command-bar-results-container');
    const btnOpen = document.getElementById('btn-open-command-bar');

    if (!dialog || !input || !resultsContainer) return;

    let debounceTimer = null;
    let currentResults = [];
    let selectedIndex = -1;

    // 1. Abrir Modal
    function openCommandBar() {
        if (!dialog.open) {
            dialog.showModal();
        }
        input.focus();
        input.select();
        selectedIndex = -1;
    }

    // 2. Fechar Modal
    function closeCommandBar() {
        if (dialog.open) {
            dialog.close();
        }
        input.value = '';
        currentResults = [];
        selectedIndex = -1;
        renderPlaceholder();
    }

    // 3. Listener Global de Teclado (Ctrl+K / Cmd+K)
    window.addEventListener('keydown', (e) => {
        if ((e.key === 'k' || e.key === 'K') && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            if (dialog.open) {
                closeCommandBar();
            } else {
                openCommandBar();
            }
        }
    });

    if (btnOpen) {
        btnOpen.addEventListener('click', (e) => {
            e.preventDefault();
            openCommandBar();
        });
    }

    // Fechar ao clicar no backdrop ou tecla Escape
    dialog.addEventListener('click', (e) => {
        if (e.target === dialog) {
            closeCommandBar();
        }
    });

    dialog.addEventListener('close', () => {
        input.value = '';
        currentResults = [];
        selectedIndex = -1;
        renderPlaceholder();
    });

    // 4. Navegação por Setas e Enter
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeCommandBar();
            return;
        }

        if (currentResults.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIndex = (selectedIndex + 1) % currentResults.length;
            updateSelection();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = (selectedIndex - 1 + currentResults.length) % currentResults.length;
            updateSelection();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (selectedIndex >= 0 && selectedIndex < currentResults.length) {
                selectItem(currentResults[selectedIndex]);
            }
        }
    });

    function updateSelection() {
        const itemElements = resultsContainer.querySelectorAll('.command-bar-item');
        itemElements.forEach((el, idx) => {
            if (idx === selectedIndex) {
                el.classList.add('is-selected');
                el.scrollIntoView({ block: 'nearest' });
            } else {
                el.classList.remove('is-selected');
            }
        });
    }

    // 5. Execução do Item Selecionado
    function selectItem(item) {
        closeCommandBar();
        // Se for cilindro e estivermos em uma tela com gaveta lateral ativa
        if (item.tipo === 'cilindro' && typeof window.abrirDrawerAtivo === 'function' && item.extra_id) {
            window.abrirDrawerAtivo(item.extra_id);
            return;
        }
        if (item.url) {
            window.location.href = item.url;
        }
    }

    // 6. Busca com Debounce de 250ms
    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const query = input.value.trim();

        if (!query) {
            currentResults = [];
            selectedIndex = -1;
            renderPlaceholder();
            return;
        }

        debounceTimer = setTimeout(() => {
            executarBusca(query);
        }, 250);
    });

    async function executarBusca(query) {
        resultsContainer.innerHTML = `
            <div class="command-bar-placeholder">
                <p>Pesquisando <strong>"${escapeHtml(query)}"</strong>...</p>
            </div>
        `;

        try {
            const token = localStorage.getItem('access_token');
            const headers = { 'Content-Type': 'application/json' };
            if (token) headers['Authorization'] = 'Bearer ' + token;

            const resp = await fetch(`/api/busca-global/?q=${encodeURIComponent(query)}`, { credentials: 'same-origin', headers });
            if (!resp.ok) throw new Error('Falha na consulta');

            const data = await resp.json();
            currentResults = data.results || [];
            selectedIndex = currentResults.length > 0 ? 0 : -1;
            renderResults(query, currentResults);
        } catch (err) {
            console.error('Erro na busca global:', err);
            resultsContainer.innerHTML = `
                <div class="command-bar-placeholder" style="color: var(--status-danger);">
                    <p>Erro ao realizar pesquisa unificada.</p>
                </div>
            `;
        }
    }

    function renderPlaceholder() {
        resultsContainer.innerHTML = `
            <div class="command-bar-placeholder">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <p>Digite para pesquisar em toda a base da distribuidora.</p>
                <div class="quick-tags">
                    <span class="quick-tag" onclick="document.getElementById('command-bar-input').value='OG-'; document.getElementById('command-bar-input').dispatchEvent(new Event('input'))">Série: OG-</span>
                    <span class="quick-tag" onclick="document.getElementById('command-bar-input').value='LT-'; document.getElementById('command-bar-input').dispatchEvent(new Event('input'))">Lote: LT-</span>
                    <span class="quick-tag" onclick="document.getElementById('command-bar-input').value='BRA'; document.getElementById('command-bar-input').dispatchEvent(new Event('input'))">Placa: BRA</span>
                </div>
            </div>
        `;
    }

    function renderResults(query, results) {
        if (!results || results.length === 0) {
            resultsContainer.innerHTML = `
                <div class="command-bar-placeholder">
                    <p>Nenhum resultado encontrado para <strong>"${escapeHtml(query)}"</strong></p>
                    <p style="font-size: 12px; color: var(--color-text-muted);">Tente buscar por número de ogiva, código QR, lote químico, nome do cliente ou placa.</p>
                </div>
            `;
            return;
        }

        let html = '';
        results.forEach((item, idx) => {
            const isSelected = idx === selectedIndex ? 'is-selected' : '';
            const iconSvg = getIconForType(item.tipo);

            html += `
                <div class="command-bar-item ${isSelected}" data-index="${idx}">
                    <div class="command-bar-item-left">
                        <div class="command-bar-item-icon icon-${item.tipo}">
                            ${iconSvg}
                        </div>
                        <div class="command-bar-item-texts">
                            <span class="command-bar-item-title">${escapeHtml(item.titulo)}</span>
                            <span class="command-bar-item-sub">${escapeHtml(item.subtitulo)}</span>
                        </div>
                    </div>
                    <span class="command-bar-item-badge badge-${item.tipo}">${item.badge}</span>
                </div>
            `;
        });

        resultsContainer.innerHTML = html;

        // Adiciona evento de clique em cada item
        resultsContainer.querySelectorAll('.command-bar-item').forEach((el, idx) => {
            el.addEventListener('click', () => {
                selectItem(currentResults[idx]);
            });
            el.addEventListener('mouseenter', () => {
                selectedIndex = idx;
                updateSelection();
            });
        });
    }

    function getIconForType(tipo) {
        if (tipo === 'cilindro') {
            return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path></svg>`;
        } else if (tipo === 'lote') {
            return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 2v7.31L4.5 19.3A2 2 0 0 0 6.24 22h11.52a2 2 0 0 0 1.74-2.7L14 9.31V2"></path><line x1="8" y1="2" x2="16" y2="2"></line></svg>`;
        } else if (tipo === 'cliente') {
            return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>`;
        } else {
            return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="3" width="15" height="13"></rect><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon><circle cx="5.5" cy="18.5" r="2.5"></circle><circle cx="18.5" cy="18.5" r="2.5"></circle></svg>`;
        }
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
});
