// Recall e rastreabilidade sanitária (2.2.9) — Design System v1.
// Dados de clientes vêm do cadastro: sempre via textContent (nunca innerHTML).
document.addEventListener('DOMContentLoaded', () => {
    const $ = (id) => document.getElementById(id);
    const estado = { lote: null, dossie: null, campanhas: [], campanhaAtual: null };

    const ETAPAS = [
        ['ABERTO', 'Aberta'],
        ['HOMOLOGADO_RT', 'Homologada pelo RT'],
        ['EM_NOTIFICACAO', 'Em notificação'],
        ['CONCLUIDO', 'Concluída'],
    ];
    const ANDAMENTO = [
        ['PENDENTE', 'Notificação pendente'],
        ['NOTIFICADO', 'Cliente notificado'],
        ['RECOLHIDO', 'Cilindro recolhido'],
        ['CONSUMIDO_DECLARADO', 'Consumo declarado'],
    ];

    // ------------------------------------------------------------- utilidades
    function el(tag, opcoes = {}, ...filhos) {
        const e = document.createElement(tag);
        if (opcoes.classe) e.className = opcoes.classe;
        if (opcoes.texto !== undefined) e.textContent = opcoes.texto;
        if (opcoes.attrs) Object.entries(opcoes.attrs).forEach(([k, v]) => e.setAttribute(k, v));
        filhos.filter(Boolean).forEach(f => e.append(f));
        return e;
    }
    function badge(texto, tom) { return el('span', { classe: 'badge-status-' + tom, texto }); }
    function celula(...conteudo) { return el('td', {}, ...conteudo); }
    function duasLinhas(principal, sub, mono) {
        return el('div', {}, el('strong', { classe: mono ? 'font-mono' : '', texto: principal || '—' }), el('span', { classe: 'ds-cell-sub', texto: sub || '' }));
    }
    function linhaVazia(tbody, colunas, titulo, erro) {
        tbody.innerHTML = '';
        const caixa = el('div', { classe: 'ds-empty' + (erro ? ' ds-empty--danger' : '') }, el('p', { classe: 'ds-empty-title', texto: titulo }));
        tbody.append(el('tr', {}, el('td', { attrs: { colspan: colunas } }, caixa)));
    }
    function dataBR(v) { return v ? Baros.data(String(v).split('T')[0]) : '—'; }

    // ------------------------------------------------------------- abas
    document.querySelectorAll('[data-recall-aba]').forEach(btn => btn.addEventListener('click', () => {
        const alvo = btn.dataset.recallAba;
        document.querySelectorAll('[data-recall-aba]').forEach(b => b.classList.toggle('active', b === btn));
        document.querySelectorAll('[data-recall-painel]').forEach(p => p.classList.toggle('ds-hidden', p.dataset.recallPainel !== alvo));
        $('filtros-tabelas').classList.toggle('ds-hidden', alvo === 'campanhas');
    }));

    $('filtro-tabela').addEventListener('input', () => {
        const termo = $('filtro-tabela').value.toLowerCase();
        document.querySelectorAll('#tbody-contencao tr, #tbody-exposicao tr').forEach(r => {
            r.classList.toggle('ds-hidden', !r.textContent.toLowerCase().includes(termo));
        });
    });

    // ------------------------------------------------------------- lotes
    async function carregarLotes() {
        const pills = $('pills-lotes-container');
        try {
            const lotes = await Baros.api('/produtos/api/lotes-anvisa/');
            const lista = $('lista-lotes-sugestoes');
            lista.innerHTML = '';
            pills.innerHTML = '';
            if (!lotes.length) { pills.append(el('span', { classe: 'ds-muted', texto: 'Nenhum lote cadastrado.' })); return; }
            lotes.forEach(l => {
                const opt = el('option', { attrs: { value: l.codigo_lote, label: `${l.gas_sigla} · validade ${l.data_validade}` } });
                lista.append(opt);
            });
            lotes.slice(0, 12).forEach(l => {
                const b = el('button', { classe: 'recall-pill', texto: l.codigo_lote, attrs: { type: 'button', title: `${l.gas_nome} · validade ${l.data_validade}` } });
                b.addEventListener('click', () => { $('input-codigo-lote').value = l.codigo_lote; buscarLote(); });
                pills.append(b);
            });
            const codigoUrl = new URLSearchParams(location.search).get('lote');
            if (codigoUrl) { $('input-codigo-lote').value = codigoUrl; buscarLote(); }
        } catch (e) {
            pills.innerHTML = '';
            pills.append(el('span', { classe: 'ds-muted', texto: e.mensagem || 'Não foi possível carregar os lotes.' }));
        }
    }

    async function buscarLote() {
        const codigo = $('input-codigo-lote').value.trim();
        if (!codigo) { Baros.validarCampos('#form-busca-lote'); return; }
        const restaurar = Baros.carregando($('btn-rastrear'), 'Rastreando...');
        try {
            const data = await Baros.api(`/produtos/api/lotes-anvisa/recall/?codigo_lote=${encodeURIComponent(codigo)}`);
            estado.dossie = data;
            estado.lote = data.lote;
            history.replaceState(null, '', `?lote=${encodeURIComponent(data.lote.codigo_lote)}`);
            document.querySelectorAll('.recall-pill').forEach(p => p.classList.toggle('ativo', p.textContent === data.lote.codigo_lote));
            renderizarLote(data);
            await carregarCampanhas();
        } catch (e) {
            Baros.erro(e.mensagem || 'Lote não encontrado.');
        } finally {
            restaurar();
        }
    }
    $('form-busca-lote').addEventListener('submit', (ev) => { ev.preventDefault(); buscarLote(); });

    function renderizarLote(data) {
        const lote = data.lote;
        const met = data.metricas || {};
        const contencao = data.contencao_operacional || [];
        const exposicao = data.exposicao_historica || [];
        $('recall-vazio').classList.add('ds-hidden');
        $('recall-resultado').classList.remove('ds-hidden');
        $('titulo-lote').textContent = lote.codigo_lote;

        $('card-gas').textContent = `${lote.gas_sigla}${lote.numero_onu ? ' · ONU ' + lote.numero_onu : ''}`;
        $('card-pureza').textContent = `Pureza ${lote.pureza_percentual}% · ${lote.gas_nome}`;
        const qualidade = $('card-qualidade');
        qualidade.textContent = lote.status_qualidade_display || lote.status_qualidade;
        qualidade.className = 'recall-metrica-texto';
        const tomQualidade = { APROVADO: 'approved', REPROVADO: 'danger' }[lote.status_qualidade] || 'warning';
        $('card-qualidade-box').className = 'metric-card metric-card--' + tomQualidade;
        $('card-rt').textContent = lote.responsavel_tecnico ? `RT: ${lote.responsavel_tecnico}` : '';
        $('card-validade').textContent = lote.data_validade;
        $('card-status-validade').textContent = lote.esta_vencido ? 'Lote vencido' : 'Dentro da validade';
        $('card-validade-box').className = 'metric-card metric-card--' + (lote.esta_vencido ? 'danger' : 'approved');
        $('card-em-clientes').textContent = met.total_em_clientes || 0;
        $('card-exposicao-total').textContent = met.total_entregas_historicas || exposicao.length;
        $('card-clientes-expostos').textContent = `${met.total_clientes_expostos || 0} cliente(s) atendido(s)`;

        const banner = $('banner-recall');
        banner.hidden = !met.alerta_recall_ativo;
        $('banner-recall-texto').textContent = `${met.total_em_clientes} cilindro(s) deste lote estão com clientes agora. Contate os clientes abaixo, bloqueie e recolha.`;

        $('contador-contencao').textContent = contencao.length;
        $('contador-exposicao').textContent = exposicao.length;
        renderizarContencao(contencao);
        renderizarExposicao(exposicao);
    }

    function renderizarContencao(cilindros) {
        const tbody = $('tbody-contencao');
        if (!cilindros.length) return linhaVazia(tbody, 7, 'Nenhum cilindro contém gás deste lote agora.');
        tbody.innerHTML = '';
        cilindros.forEach(c => {
            let onde, acao, contato = el('span', { classe: 'ds-muted', texto: '—' });
            if (c.local_tipo === 'CLIENTE' && c.cliente) {
                onde = duasLinhas(c.cliente.nome, c.cliente.endereco);
                acao = badge('Recolher do cliente', 'danger');
                const tel = (c.cliente.telefone || '').replace(/\D/g, '');
                contato = el('div', {}, el('span', { texto: c.cliente.telefone || 'Sem telefone' }), el('span', { classe: 'ds-cell-sub font-mono', texto: c.cliente.cnpj || '' }));
                if (tel) {
                    const msg = encodeURIComponent(`Aviso urgente de recall sanitário do lote ${estado.lote.codigo_lote}.`);
                    contato.append(el('a', { classe: 'btn-outline btn-sm', texto: 'WhatsApp', attrs: { href: `https://wa.me/55${tel}?text=${msg}`, target: '_blank', rel: 'noopener' } }));
                }
            } else if (c.local_tipo === 'ROTA') {
                onde = badge('Em rota de entrega', 'transit');
                acao = badge('Abortar a entrega', 'warning');
            } else {
                onde = badge('Pátio / base', 'muted');
                acao = badge('Segregar no pátio', 'warning');
            }
            tbody.append(el('tr', {},
                celula(duasLinhas(c.numero_serie_ogiva, c.codigo_qr, true)),
                celula(el('span', { texto: c.envasado_em || '—' }), el('span', { classe: 'ds-cell-sub', texto: c.pressao_final_bar ? `${c.pressao_final_bar} bar` : '' })),
                celula(el('span', { texto: c.status_atual_display || '—' })),
                celula(c.bloqueio_sanitario ? badge('Bloqueado', 'danger') : badge('Não', 'muted')),
                celula(onde),
                celula(acao),
                celula(contato),
            ));
        });
    }

    function renderizarExposicao(entregas) {
        const tbody = $('tbody-exposicao');
        if (!entregas.length) return linhaVazia(tbody, 7, 'Nenhuma entrega deste lote registrada.');
        tbody.innerHTML = '';
        entregas.forEach(e => {
            const cli = e.cliente || {};
            tbody.append(el('tr', {},
                celula(el('span', { classe: 'font-mono', texto: e.data_entrega || '—' })),
                celula(el('span', { classe: 'font-mono', texto: e.documento_fiscal_ref || '—' })),
                celula(duasLinhas(cli.nome, cli.cnpj)),
                celula(duasLinhas(e.numero_serie_ogiva, e.codigo_qr, true)),
                celula(el('span', { texto: e.operador || '—' })),
                celula(duasLinhas(e.status_atual_display, e.lote_atual_cilindro ? `Hoje no lote ${e.lote_atual_cilindro}` : 'Vazio')),
                celula(e.is_envase_ativo ? badge('Risco ativo', 'danger') : badge('Encerrada', 'muted')),
            ));
        });
    }

    // ------------------------------------------------------------- campanhas
    function linhaDoTempo(status) {
        const caixa = el('div', { classe: 'recall-linha-tempo', attrs: { 'aria-label': 'Andamento da campanha' } });
        if (status === 'CANCELADO') {
            caixa.append(el('span', { classe: 'recall-etapa cancelada' }, el('span', { classe: 'recall-etapa-ponto', texto: '×' }), 'Cancelada'));
            return caixa;
        }
        const idxAtual = ETAPAS.findIndex(([s]) => s === status);
        ETAPAS.forEach(([s, rotulo], i) => {
            if (i > 0) caixa.append(el('span', { classe: 'recall-etapa-traco' }));
            const situacao = i < idxAtual || status === 'CONCLUIDO' ? 'feita' : (i === idxAtual ? 'atual' : '');
            caixa.append(el('span', { classe: 'recall-etapa ' + situacao }, el('span', { classe: 'recall-etapa-ponto', texto: situacao === 'feita' ? '✓' : String(i + 1) }), rotulo));
        });
        return caixa;
    }

    async function carregarCampanhas(manterSelecao) {
        const lista = $('lista-campanhas');
        try {
            const data = await Baros.api(`/produtos/api/campanhas-recall/?lote_id=${estado.lote.id}`);
            estado.campanhas = Array.isArray(data) ? data : (data.results || []);
        } catch (e) {
            lista.innerHTML = '';
            lista.append(el('div', { classe: 'ds-empty ds-empty--danger' }, el('p', { classe: 'ds-empty-title', texto: e.mensagem || 'Não foi possível carregar as campanhas.' })));
            return;
        }
        $('contador-campanhas').textContent = estado.campanhas.length;
        lista.innerHTML = '';
        if (!estado.campanhas.length) {
            lista.append(el('div', { classe: 'ds-empty' }, el('p', { classe: 'ds-empty-title', texto: 'Nenhuma campanha para este lote' }), el('p', { classe: 'ds-empty-text', texto: 'Use "Abrir campanha de recall" se houver desvio de qualidade.' })));
            $('detalhe-campanha').classList.add('ds-hidden');
            return;
        }
        estado.campanhas.forEach(c => {
            const card = el('article', { classe: 'recall-campanha', attrs: { 'data-campanha': c.id } });
            const topo = el('div', { classe: 'recall-campanha-topo' },
                el('div', {}, el('strong', { classe: 'font-mono', texto: c.codigo_campanha }), el('span', { classe: 'ds-cell-sub', texto: `Aberta por ${c.criado_por_nome || 'sistema'} em ${dataBR(c.aberto_em)}` })),
            );
            const acoes = el('div', { classe: 'recall-campanha-acoes' });
            if (c.status === 'ABERTO') {
                const homologar = el('button', { classe: 'btn-primary btn-sm', texto: 'Homologar (RT)', attrs: { type: 'button' } });
                homologar.addEventListener('click', () => homologarCampanha(c));
                acoes.append(homologar);
            }
            const ver = el('button', { classe: 'btn-outline btn-sm', texto: 'Ver clientes', attrs: { type: 'button' } });
            ver.addEventListener('click', () => selecionarCampanha(c.id));
            acoes.append(ver);
            topo.append(acoes);
            const rt = c.homologado_em ? `Homologada por ${c.rt_nome_snapshot || 'RT'} (${c.rt_registro_snapshot || ''}) em ${dataBR(c.homologado_em)}` : 'Aguardando homologação do Responsável Técnico.';
            card.append(topo, el('p', { classe: 'recall-campanha-motivo', texto: c.motivo }), linhaDoTempo(c.status), el('span', { classe: 'ds-cell-sub', texto: rt }));
            lista.append(card);
        });
        const alvo = manterSelecao && estado.campanhas.find(c => c.id === manterSelecao) ? manterSelecao : estado.campanhas[0].id;
        selecionarCampanha(alvo);
    }

    async function homologarCampanha(c) {
        const ok = await Baros.confirmar({
            titulo: `Homologar a campanha ${c.codigo_campanha}?`,
            texto: 'Como Responsável Técnico, você libera a notificação dos clientes. A homologação fica registrada com seu nome e registro profissional.',
            botao: 'Homologar',
        });
        if (!ok) return;
        try {
            await Baros.api(`/produtos/api/campanhas-recall/${c.id}/homologar/`, { method: 'POST', body: {} });
            Baros.sucesso('Campanha homologada.');
            await carregarCampanhas(c.id);
        } catch (e) {
            Baros.erro(e.mensagem);
        }
    }

    function selecionarCampanha(id) {
        estado.campanhaAtual = estado.campanhas.find(c => c.id === id);
        document.querySelectorAll('.recall-campanha').forEach(card => card.classList.toggle('selecionada', Number(card.dataset.campanha) === id));
        $('detalhe-campanha').classList.remove('ds-hidden');
        $('detalhe-campanha-codigo').textContent = estado.campanhaAtual.codigo_campanha;
        const travada = ['ABERTO', 'CONCLUIDO', 'CANCELADO'].includes(estado.campanhaAtual.status);
        $('detalhe-campanha-aviso').textContent = {
            ABERTO: 'Homologue a campanha com o RT para liberar as notificações.',
            CONCLUIDO: 'Campanha concluída: todos os cilindros foram recolhidos ou tiveram o consumo declarado.',
            CANCELADO: 'Campanha cancelada.',
        }[estado.campanhaAtual.status] || 'Registre a notificação e o recolhimento de cada cilindro. A campanha conclui sozinha quando não houver pendências.';
        renderizarItens(estado.campanhaAtual.itens_cliente || [], travada);
    }

    function renderizarItens(itens, travada) {
        const tbody = $('tbody-itens-recall');
        if (!itens.length) return linhaVazia(tbody, 7, 'Nenhum cliente exposto nesta campanha.');
        tbody.innerHTML = '';
        itens.forEach(item => {
            const select = el('select', { classe: 'recall-status-select', attrs: { 'aria-label': `Andamento de ${item.cilindro_qr}` } });
            ANDAMENTO.forEach(([v, r]) => select.append(new Option(r, v, false, v === item.status_notificacao)));
            select.disabled = travada;
            const salvar = el('button', { classe: 'btn-primary btn-sm', texto: 'Salvar', attrs: { type: 'button' } });
            salvar.disabled = travada;
            salvar.addEventListener('click', () => salvarAndamento(item, select.value, salvar));
            tbody.append(el('tr', {},
                celula(duasLinhas(item.cliente_nome, item.cliente_cnpj)),
                celula(duasLinhas(item.cilindro_serie, item.cilindro_qr, true)),
                celula(item.tipo_exposicao === 'CONTENCAO_ATIVA' ? badge('Risco ativo', 'danger') : badge('Exposição passada', 'muted')),
                celula(select),
                celula(el('span', { classe: 'font-mono', texto: dataBR(item.notificado_em) })),
                celula(el('span', { classe: 'font-mono', texto: dataBR(item.recolhido_em) })),
                celula(salvar),
            ));
        });
    }

    async function salvarAndamento(item, novoStatus, botao) {
        const restaurar = Baros.carregando(botao, '...');
        try {
            const r = await Baros.api(`/produtos/api/itens-recall/${item.id}/confirmar-recolhimento/`, {
                method: 'POST',
                body: { status_notificacao: novoStatus, observacoes: `Andamento: ${novoStatus}` },
            });
            Baros.sucesso(r.campanha_status === 'CONCLUIDO' ? 'Andamento salvo. Campanha concluída.' : 'Andamento salvo.');
            await carregarCampanhas(item.campanha);
        } catch (e) {
            Baros.erro(e.mensagem);
        } finally {
            restaurar();
        }
    }

    // ------------------------------------------------------------- abrir campanha
    const dialogo = $('modal-abrir-recall');
    const formCampanha = $('form-criar-recall');
    dialogo.querySelectorAll('[data-fechar-dialogo]').forEach(b => b.addEventListener('click', () => dialogo.close()));

    $('btn-abrir-campanha').addEventListener('click', () => {
        if (!estado.lote) return;
        const codigo = estado.lote.codigo_lote;
        formCampanha.reset();
        formCampanha.querySelectorAll('.ds-field-error').forEach(e => e.remove());
        formCampanha.querySelectorAll('.ds-invalid').forEach(e => e.classList.remove('ds-invalid'));
        $('recall-input-codigo').value = `REC-${codigo}-${new Date().getFullYear()}`;
        $('recall-input-texto').value = `COMUNICADO URGENTE DE RECALL SANITÁRIO\n\nPrezado cliente,\ninformamos o recolhimento cautelar do lote ${codigo}. Separe os cilindros deste lote e deixe-os disponíveis para o recolhimento pela nossa equipe.`;
        dialogo.showModal();
        $('recall-input-motivo').focus();
    });

    formCampanha.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        if (!Baros.validarCampos(formCampanha)) return;
        const restaurar = Baros.carregando(formCampanha.querySelector('[type=submit]'), 'Abrindo...');
        try {
            const c = await Baros.api('/produtos/api/campanhas-recall/', {
                method: 'POST',
                body: {
                    lote_id: estado.lote.id,
                    codigo_campanha: $('recall-input-codigo').value.trim(),
                    motivo: $('recall-input-motivo').value.trim(),
                    texto_notificacao: $('recall-input-texto').value.trim(),
                },
            });
            dialogo.close();
            Baros.sucesso(`Campanha ${c.codigo_campanha} aberta com ${(c.itens_cliente || []).length} item(ns).`);
            document.querySelector('[data-recall-aba="campanhas"]').click();
            await carregarCampanhas(c.id);
        } catch (e) {
            Baros.mostrarErrosApi(formCampanha, e);
        } finally {
            restaurar();
        }
    });

    // ------------------------------------------------------------- dossiê
    $('btn-export-csv').addEventListener('click', () => {
        if (estado.lote) window.location.href = `/produtos/api/lotes-anvisa/recall/?codigo_lote=${encodeURIComponent(estado.lote.codigo_lote)}&export=csv`;
    });
    $('btn-imprimir').addEventListener('click', () => window.print());

    carregarLotes();
});
