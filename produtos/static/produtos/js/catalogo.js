// Aba Catálogo (SKUs de recarga, modelos de cilindro e gases) — Design System v1.
// API: /produtos/api/catalogo/{skus,modelos,gases}/
document.addEventListener('DOMContentLoaded', () => {
    const raiz = document.getElementById('aba-conteudo-catalogo');
    if (!raiz) return;

    const API = '/produtos/api/catalogo/';
    const podeEditar = raiz.dataset.podeEditar === '1';
    const cache = { gases: [], modelos: [], skus: [] };

    const lista = (dados) => (Array.isArray(dados) ? dados : (dados && dados.results) || []);
    const num = (v, casas = 2) => (v === null || v === undefined || v === '') ? '—'
        : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });

    function celula(texto, classe) {
        const td = document.createElement('td');
        if (classe) td.className = classe;
        td.textContent = texto;
        return td;
    }

    function badge(texto, tom) {
        const span = document.createElement('span');
        span.className = 'badge-status-' + tom;
        span.textContent = texto;
        return span;
    }

    function estado(tbody, colunas, titulo, texto, erro) {
        tbody.innerHTML = '';
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = colunas;
        const caixa = document.createElement('div');
        caixa.className = 'ds-empty' + (erro ? ' ds-empty--danger' : '');
        caixa.innerHTML = '<p class="ds-empty-title"></p><p class="ds-empty-text"></p>';
        caixa.children[0].textContent = titulo;
        caixa.children[1].textContent = texto || '';
        td.appendChild(caixa);
        tr.appendChild(td);
        tbody.appendChild(tr);
    }

    function carregando(tbody, colunas) {
        tbody.innerHTML = '';
        for (let i = 0; i < 3; i++) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = colunas;
            td.innerHTML = '<span class="ds-skeleton"></span>';
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    }

    function botaoLinha(texto, aoClicar) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn-outline btn-sm';
        b.textContent = texto;
        b.addEventListener('click', aoClicar);
        return b;
    }

    // ---------------------------------------------------------------- Sub-abas
    raiz.querySelectorAll('[data-catalogo-aba]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const alvo = btn.dataset.catalogoAba;
            raiz.querySelectorAll('[data-catalogo-aba]').forEach(b => b.classList.toggle('active', b === btn));
            raiz.querySelectorAll('[data-catalogo-painel]').forEach(p => p.classList.toggle('ds-hidden', p.dataset.catalogoPainel !== alvo));
        });
    });

    // ---------------------------------------------------------------- Gases
    async function carregarGases() {
        const tbody = document.getElementById('catalogo-gases-tbody');
        carregando(tbody, 7);
        try {
            cache.gases = lista(await Baros.api(API + 'gases/'));
            tbody.innerHTML = '';
            if (!cache.gases.length) return estado(tbody, 7, 'Nenhum gás cadastrado na plataforma');
            cache.gases.forEach((g) => {
                const tr = document.createElement('tr');
                const nome = celula(g.nome);
                tr.append(nome, celula(g.sigla, 'font-mono'));
                const cat = document.createElement('td');
                cat.appendChild(badge(g.categoria, g.categoria === 'MEDICINAL' ? 'approved' : 'transit'));
                tr.append(cat, celula(g.numero_onu || '—', 'font-mono'), celula(g.classe_risco || '—'),
                    celula(g.cor_padrao_abnt || '—'), celula(g.exige_lote_anvisa ? 'Sim' : 'Não'));
                tbody.appendChild(tr);
            });
        } catch (e) {
            estado(tbody, 7, 'Não foi possível carregar os gases', e.mensagem, true);
        }
    }

    // ---------------------------------------------------------------- Modelos
    async function carregarModelos() {
        const tbody = document.getElementById('catalogo-modelos-tbody');
        carregando(tbody, 7);
        try {
            cache.modelos = lista(await Baros.api(API + 'modelos/?page_size=500'));
            tbody.innerHTML = '';
            if (!cache.modelos.length) {
                return estado(tbody, 7, 'Nenhum modelo de cilindro', podeEditar ? 'Cadastre o primeiro em "Novo modelo de cilindro".' : '');
            }
            cache.modelos.forEach((m) => {
                const tr = document.createElement('tr');
                tr.append(celula(m.descricao), celula(m.material_display || m.material), celula(num(m.volume_hidraulico_litros), 'ds-num'),
                    celula(m.pressao_servico_bar, 'ds-num'), celula(num(m.tara_nominal_kg), 'ds-num'),
                    celula(m.periodicidade_reteste_anos + ' anos', 'ds-num'));
                const acoes = document.createElement('td');
                acoes.className = 'ds-row-actions';
                if (podeEditar) {
                    acoes.append(botaoLinha('Editar', () => abrirModelo(m)), botaoLinha('Excluir', () => excluir('modelos', m.id, m.descricao)));
                }
                tr.appendChild(acoes);
                tbody.appendChild(tr);
            });
        } catch (e) {
            estado(tbody, 7, 'Não foi possível carregar os modelos', e.mensagem, true);
        }
    }

    // ---------------------------------------------------------------- SKUs
    const busca = document.getElementById('catalogo-busca');
    const soAtivos = document.getElementById('catalogo-so-ativos');
    let temporizador = null;

    async function carregarSkus() {
        const tbody = document.getElementById('catalogo-skus-tbody');
        carregando(tbody, 8);
        const params = new URLSearchParams({ page_size: 500 });
        if (busca.value.trim()) params.set('q', busca.value.trim());
        if (soAtivos.checked) params.set('ativo', '1');
        try {
            cache.skus = lista(await Baros.api(API + 'skus/?' + params));
            tbody.innerHTML = '';
            if (!cache.skus.length) {
                return estado(tbody, 8, 'Nenhum SKU encontrado', podeEditar ? 'Ajuste os filtros ou cadastre um SKU.' : 'Ajuste os filtros.');
            }
            cache.skus.forEach((s) => {
                const tr = document.createElement('tr');
                const nome = document.createElement('td');
                const forte = document.createElement('strong');
                forte.textContent = s.nome_comercial;
                nome.appendChild(forte);
                if (s.medicinal) { nome.append(' '); nome.appendChild(badge('Medicinal', 'approved')); }
                tr.append(nome, celula(s.gas_sigla + ' · ' + s.gas_nome), celula(s.modelo_descricao),
                    celula(num(s.quantidade_carga) + ' ' + (s.unidade_display || s.unidade), 'ds-num'),
                    celula(Baros.moeda(s.preco_base), 'ds-num'),
                    celula(s.ncm ? 'NCM ' + s.ncm : 'Sem NCM', s.ncm ? 'font-mono' : 'ds-muted'));
                const st = document.createElement('td');
                st.appendChild(s.ativo ? badge('Ativo', 'approved') : badge('Inativo', 'danger'));
                tr.appendChild(st);
                const acoes = document.createElement('td');
                acoes.className = 'ds-row-actions';
                if (podeEditar) {
                    acoes.append(botaoLinha('Editar', () => abrirSku(s)));
                }
                tr.appendChild(acoes);
                tbody.appendChild(tr);
            });
        } catch (e) {
            estado(tbody, 8, 'Não foi possível carregar os SKUs', e.mensagem, true);
        }
    }

    busca.addEventListener('input', () => { clearTimeout(temporizador); temporizador = setTimeout(carregarSkus, 300); });
    soAtivos.addEventListener('change', carregarSkus);

    // ---------------------------------------------------------------- Exclusão
    async function excluir(recurso, id, nome) {
        const ok = await Baros.confirmar({ titulo: 'Excluir "' + nome + '"?', texto: 'Só é possível excluir o que ainda não foi usado.', botao: 'Excluir', perigo: true });
        if (!ok) return;
        try {
            await Baros.api(API + recurso + '/' + id + '/', { method: 'DELETE' });
            Baros.sucesso('Excluído.');
            carregarModelos();
        } catch (e) {
            Baros.erro(e.mensagem);
        }
    }

    // ---------------------------------------------------------------- Modais
    function abrirModal(id) { document.getElementById(id).classList.add('active'); }
    function fecharModal(id) { document.getElementById(id).classList.remove('active'); }
    document.querySelectorAll('#modal-sku [data-fechar-modal]').forEach(b => b.addEventListener('click', () => fecharModal('modal-sku')));
    document.querySelectorAll('#modal-modelo [data-fechar-modal]').forEach(b => b.addEventListener('click', () => fecharModal('modal-modelo')));
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { ['modal-sku', 'modal-modelo'].forEach(id => { const m = document.getElementById(id); if (m) m.classList.remove('active'); }); }
    });

    function preencher(form, dados) {
        Array.from(form.elements).forEach((campo) => {
            if (!campo.name || !(campo.name in dados)) return;
            const valor = dados[campo.name];
            if (campo.type === 'checkbox') campo.checked = !!valor;
            else campo.value = valor === null || valor === undefined ? '' : valor;
        });
    }

    function dadosForm(form) {
        const dados = {};
        Array.from(form.elements).forEach((campo) => {
            if (!campo.name) return;
            if (campo.type === 'checkbox') dados[campo.name] = campo.checked;
            else if (campo.value !== '' || campo.type !== 'number') dados[campo.name] = campo.value;
            else dados[campo.name] = null;
        });
        return dados;
    }

    // Modelo
    const formModelo = document.getElementById('form-modelo');
    let modeloEditando = null;
    function abrirModelo(modelo) {
        modeloEditando = modelo ? modelo.id : null;
        formModelo.reset();
        formModelo.querySelectorAll('.ds-field-error').forEach(el => el.remove());
        formModelo.querySelectorAll('.ds-invalid').forEach(el => el.classList.remove('ds-invalid'));
        if (modelo) preencher(formModelo, modelo);
        document.getElementById('modal-modelo-titulo').textContent = modelo ? 'Editar modelo de cilindro' : 'Novo modelo de cilindro';
        abrirModal('modal-modelo');
    }

    if (formModelo) {
        document.getElementById('btn-novo-modelo').addEventListener('click', () => abrirModelo(null));
        formModelo.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            if (!Baros.validarCampos(formModelo)) return;
            const restaurar = Baros.carregando(formModelo.querySelector('[type=submit]'), 'Salvando...');
            try {
                const url = API + 'modelos/' + (modeloEditando ? modeloEditando + '/' : '');
                await Baros.api(url, { method: modeloEditando ? 'PATCH' : 'POST', body: dadosForm(formModelo) });
                fecharModal('modal-modelo');
                Baros.sucesso('Modelo salvo.');
                await carregarModelos();
            } catch (e) {
                Baros.mostrarErrosApi(formModelo, e);
            } finally {
                restaurar();
            }
        });
    }

    // SKU (stepper)
    const formSku = document.getElementById('form-sku');
    let skuEditando = null;
    let stepperSku = null;

    function opcoes(select, itens, rotulo, vazio) {
        select.innerHTML = '';
        select.appendChild(new Option(vazio, ''));
        itens.forEach(i => select.appendChild(new Option(rotulo(i), i.id)));
    }

    function montarRevisaoSku() {
        const d = dadosForm(formSku);
        const gas = cache.gases.find(g => String(g.id) === String(d.gas));
        const modelo = cache.modelos.find(m => String(m.id) === String(d.modelo_cilindro));
        const unidade = formSku.unidade.selectedOptions[0] ? formSku.unidade.selectedOptions[0].text : d.unidade;
        const linhas = [
            ['Nome comercial', d.nome_comercial],
            ['Gás', gas ? gas.nome + ' (' + gas.sigla + ')' : '—'],
            ['Modelo de cilindro', modelo ? modelo.descricao : '—'],
            ['Carga', num(d.quantidade_carga) + ' ' + unidade + ' · ' + num(d.massa_gas_kg) + ' kg de gás'],
            ['Preço base', Baros.moeda(d.preco_base)],
            ['Fiscal', ['NCM ' + (d.ncm || '—'), 'CEST ' + (d.cest || '—'), 'origem ' + d.origem, d.grupo_fiscal ? 'grupo ' + d.grupo_fiscal : ''].filter(Boolean).join(' · ')],
            ['Medicinal', d.medicinal ? 'Sim' + (d.registro_anvisa ? ' · ANVISA ' + d.registro_anvisa : '') : 'Não'],
            ['Status', d.ativo ? 'Disponível para venda' : 'Inativo'],
        ];
        const dl = document.getElementById('sku-revisao');
        dl.innerHTML = '';
        linhas.forEach(([r, v]) => {
            const dt = document.createElement('dt'); dt.textContent = r;
            const dd = document.createElement('dd'); dd.textContent = v;
            dl.append(dt, dd);
        });
    }

    function atualizarBotoesStepper(atual, total) {
        const raizStepper = document.getElementById('stepper-sku');
        raizStepper.querySelector('[data-stepper-voltar]').hidden = atual === 1;
        raizStepper.querySelector('[data-stepper-proximo]').hidden = atual === total;
        raizStepper.querySelector('[data-stepper-confirmar]').hidden = atual !== total;
        if (atual === total) montarRevisaoSku();
    }

    async function abrirSku(sku) {
        if (!cache.gases.length) await carregarGases();
        if (!cache.modelos.length) await carregarModelos();
        if (!cache.modelos.length) {
            Baros.aviso('Cadastre um modelo de cilindro antes do primeiro SKU.');
            return;
        }
        skuEditando = sku ? sku.id : null;
        formSku.reset();
        formSku.querySelectorAll('.ds-field-error').forEach(el => el.remove());
        formSku.querySelectorAll('.ds-invalid').forEach(el => el.classList.remove('ds-invalid'));
        opcoes(formSku.gas, cache.gases, g => g.nome + ' (' + g.sigla + ')', 'Selecione o gás');
        opcoes(formSku.modelo_cilindro, cache.modelos, m => m.descricao, 'Selecione o modelo');
        if (sku) preencher(formSku, sku);
        document.getElementById('modal-sku-titulo').textContent = sku ? 'Editar SKU' : 'Novo SKU';
        stepperSku.reiniciar();
        abrirModal('modal-sku');
    }

    if (formSku) {
        stepperSku = Baros.Stepper('#stepper-sku', {
            validar: (n) => Baros.validarCampos('#stepper-sku .ds-step-pane[data-step="' + n + '"]'),
            aoMudar: atualizarBotoesStepper,
        });
        const raizStepper = document.getElementById('stepper-sku');
        raizStepper.querySelector('[data-stepper-proximo]').addEventListener('click', () => stepperSku.proxima());
        raizStepper.querySelector('[data-stepper-voltar]').addEventListener('click', () => stepperSku.anterior());
        document.getElementById('btn-novo-sku').addEventListener('click', () => abrirSku(null));

        // Ao escolher o modelo, sugere a massa de gás padrão dele
        formSku.modelo_cilindro.addEventListener('change', () => {
            const m = cache.modelos.find(x => String(x.id) === formSku.modelo_cilindro.value);
            if (m && m.massa_gas_padrao_kg && !formSku.massa_gas_kg.value) formSku.massa_gas_kg.value = m.massa_gas_padrao_kg;
        });

        formSku.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const restaurar = Baros.carregando(raizStepper.querySelector('[data-stepper-confirmar]'), 'Salvando...');
            try {
                const url = API + 'skus/' + (skuEditando ? skuEditando + '/' : '');
                await Baros.api(url, { method: skuEditando ? 'PATCH' : 'POST', body: dadosForm(formSku) });
                fecharModal('modal-sku');
                Baros.sucesso('SKU salvo.');
                carregarSkus();
            } catch (e) {
                Baros.mostrarErrosApi(formSku, e);
                // Volta para a primeira etapa com erro
                const comErro = formSku.querySelector('.ds-invalid');
                if (comErro) stepperSku.ir(Number(comErro.closest('.ds-step-pane').dataset.step));
            } finally {
                restaurar();
            }
        });
    }

    carregarGases();
    carregarModelos();
    carregarSkus();
});
