// Cadastro de cilindro em etapas (Design System v1). POST /produtos/api/cilindros/
document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('modal-cadastro-cilindro');
    const botaoAbrir = document.getElementById('btn-novo-cilindro');
    if (!modal || !botaoAbrir) return;

    const form = document.getElementById('form-cadastro-cilindro');
    const raizStepper = document.getElementById('stepper-cilindro');
    const btnVoltar = raizStepper.querySelector('[data-stepper-voltar]');
    const btnProximo = raizStepper.querySelector('[data-stepper-proximo]');
    const btnConfirmar = raizStepper.querySelector('[data-stepper-confirmar]');
    const grupoCliente = document.getElementById('grupo-cliente-proprietario');
    const dados = { modelos: [], gases: [], fabricantes: [], classes: [], clientes: [] };
    let carregado = false;

    const lista = (r) => (Array.isArray(r) ? r : (r && r.results) || []);

    function opcoes(select, itens, rotulo, vazio) {
        select.innerHTML = '';
        select.appendChild(new Option(vazio, ''));
        itens.forEach(i => select.appendChild(new Option(rotulo(i), i.id)));
    }

    async function carregarListas() {
        if (carregado) return;
        const [modelos, gases, fabricantes, classes, clientes] = await Promise.all([
            Baros.api('/produtos/api/catalogo/modelos/?page_size=500'),
            Baros.api('/produtos/api/catalogo/gases/'),
            Baros.api('/produtos/api/patrimonio/fabricantes/?page_size=500').catch(() => []),
            Baros.api('/produtos/api/patrimonio/classes/?page_size=500').catch(() => []),
            Baros.api('/clientes/api/?page_size=500').catch(() => []),
        ]);
        dados.modelos = lista(modelos);
        dados.gases = lista(gases);
        dados.fabricantes = lista(fabricantes);
        dados.classes = lista(classes);
        dados.clientes = lista(clientes);
        opcoes(form.modelo, dados.modelos, m => m.descricao, 'Selecione o modelo');
        opcoes(form.gas_dedicado, dados.gases, g => g.nome + ' (' + g.sigla + ')', 'Selecione o gás');
        opcoes(form.fabricante_catalogo, dados.fabricantes, f => f.nome, 'Outro / informar nome');
        opcoes(form.classe_ativo, dados.classes, c => c.nome || c.codigo, 'Padrão');
        opcoes(form.cliente_proprietario, dados.clientes, c => c.nome_fantasia || c.nome, 'Selecione o cliente');
        carregado = true;
    }

    function campoTexto(nome) {
        const campo = form.elements[nome];
        if (!campo || !campo.value) return '';
        return campo.tagName === 'SELECT' ? campo.selectedOptions[0].text : campo.value;
    }

    function montarRevisao() {
        const fabricante = form.fabricante_catalogo.value ? campoTexto('fabricante_catalogo') : form.fabricante.value;
        const linhas = [
            ['QR code', form.codigo_qr.value.toUpperCase()],
            ['Série', form.numero_serie_ogiva.value.toUpperCase()],
            ['Fabricante', [fabricante, form.ano_fabricacao.value, form.norma_fabricacao.value].filter(Boolean).join(' · ')],
            ['Modelo', campoTexto('modelo')],
            ['Gás dedicado', campoTexto('gas_dedicado')],
            ['Pressões', 'serviço ' + (form.pressao_servico_bar.value || 'do modelo') + ' bar · teste ' + (form.pressao_teste_bar.value || '—') + ' bar'],
            ['Último reteste', Baros.data(form.data_ultimo_reteste.value)],
            ['Propriedade', campoTexto('propriedade') + (form.propriedade.value === 'CLIENTE' ? ' · ' + campoTexto('cliente_proprietario') : '')],
            ['Patrimônio', [form.numero_patrimonio.value, form.valor_aquisicao.value ? Baros.moeda(form.valor_aquisicao.value) : ''].filter(Boolean).join(' · ') || '—'],
        ];
        const dl = document.getElementById('cilindro-revisao');
        dl.innerHTML = '';
        linhas.forEach(([r, v]) => {
            const dt = document.createElement('dt'); dt.textContent = r;
            const dd = document.createElement('dd'); dd.textContent = v || '—';
            dl.append(dt, dd);
        });
    }

    function validarEtapa(n) {
        const ok = Baros.validarCampos('#stepper-cilindro .ds-step-pane[data-step="' + n + '"]');
        if (!ok) return false;
        if (n === 1 && !form.fabricante_catalogo.value && !form.fabricante.value.trim()) {
            Baros.mostrarErrosApi(form, { campos: { fabricante: 'Escolha um fabricante do catálogo ou informe o nome.' } });
            return false;
        }
        if (n === 2 && form.pressao_teste_bar.value && form.pressao_servico_bar.value
            && Number(form.pressao_teste_bar.value) < Number(form.pressao_servico_bar.value)) {
            Baros.mostrarErrosApi(form, { campos: { pressao_teste_bar: 'A pressão de teste deve ser maior ou igual à de serviço.' } });
            return false;
        }
        return true;
    }

    const stepper = Baros.Stepper('#stepper-cilindro', {
        validar: validarEtapa,
        aoMudar: (atual, total) => {
            btnVoltar.hidden = atual === 1;
            btnProximo.hidden = atual === total;
            btnConfirmar.hidden = atual !== total;
            if (atual === total) montarRevisao();
        },
    });

    function atualizarPropriedade() {
        const cliente = form.propriedade.value === 'CLIENTE';
        grupoCliente.classList.toggle('ds-hidden', !cliente);
        form.cliente_proprietario.required = cliente;
        document.getElementById('secao-patrimonio').classList.toggle('ds-hidden', cliente);
    }
    form.propriedade.addEventListener('change', atualizarPropriedade);

    form.fabricante_catalogo.addEventListener('change', () => {
        form.fabricante.disabled = !!form.fabricante_catalogo.value;
        if (form.fabricante_catalogo.value) form.fabricante.value = '';
    });

    // Pressão de serviço sugerida pelo modelo
    form.modelo.addEventListener('change', () => {
        const m = dados.modelos.find(x => String(x.id) === form.modelo.value);
        form.pressao_servico_bar.placeholder = m ? String(m.pressao_servico_bar) : '';
    });

    function abrir() {
        form.reset();
        form.fabricante.disabled = false;
        form.querySelectorAll('.ds-field-error').forEach(el => el.remove());
        form.querySelectorAll('.ds-invalid').forEach(el => el.classList.remove('ds-invalid'));
        atualizarPropriedade();
        stepper.reiniciar();
        modal.classList.add('active');
        carregarListas()
            .then(() => {
                if (!dados.modelos.length) Baros.aviso('Cadastre um modelo de cilindro no Catálogo antes do primeiro cilindro.');
                form.codigo_qr.focus();
            })
            .catch(e => Baros.erro(e.mensagem || 'Não foi possível carregar as listas.'));
    }

    function fechar() { modal.classList.remove('active'); }

    botaoAbrir.addEventListener('click', abrir);
    modal.querySelectorAll('[data-fechar-modal]').forEach(b => b.addEventListener('click', fechar));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && modal.classList.contains('active')) fechar(); });
    btnProximo.addEventListener('click', () => stepper.proxima());
    btnVoltar.addEventListener('click', () => stepper.anterior());

    // Enter no QR/série avança para o próximo campo (bipagem por leitor)
    [form.codigo_qr, form.numero_serie_ogiva].forEach((campo, i, arr) => {
        campo.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            (arr[i + 1] || form.fabricante_catalogo).focus();
        });
    });

    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const corpo = {};
        Array.from(form.elements).forEach((c) => {
            if (!c.name || c.disabled || c.value === '') return;
            corpo[c.name] = c.value;
        });
        if (corpo.propriedade !== 'CLIENTE') delete corpo.cliente_proprietario;
        const restaurar = Baros.carregando(btnConfirmar, 'Cadastrando...');
        try {
            const cilindro = await Baros.api('/produtos/api/cilindros/', { method: 'POST', body: corpo });
            fechar();
            Baros.sucesso('Cilindro ' + cilindro.codigo_qr + ' cadastrado.');
            if (window.CilindrosFrota) {
                window.CilindrosFrota.recarregar();
                window.CilindrosFrota.abrir(cilindro.id);
            }
        } catch (e) {
            Baros.mostrarErrosApi(form, e);
            const comErro = form.querySelector('.ds-invalid');
            if (comErro) stepper.ir(Number(comErro.closest('.ds-step-pane').dataset.step));
        } finally {
            restaurar();
        }
    });
});
