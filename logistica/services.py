import io
from datetime import datetime
from django.utils import timezone
from django.core.exceptions import ValidationError

def validar_capacidade_veiculo_entrega(entrega, novos_cilindros=None, novo_peso_extra=0):
    """
    Valida a capacidade de carga do veículo alocado na entrega.
    Soma o peso bruto já carregado (tara + massa de gás para cheios, tara para vazios)
    mais o peso adicional de novos cilindros a serem alocados.
    Se o peso total exceder a capacidade de carga máxima do veículo (em kg),
    bloqueia a alocação e dispara ValidationError.
    """
    if not entrega.veiculo or not entrega.veiculo.capacidade_carga or entrega.veiculo.capacidade_carga <= 0:
        return float(entrega.peso_total_carregado)

    capacidade_maxima = float(entrega.veiculo.capacidade_carga)
    peso_atual = float(entrega.peso_total_carregado)

    peso_adicional = float(novo_peso_extra)
    if novos_cilindros:
        for cil in novos_cilindros:
            tara = float(cil.tara_real_kg) if cil.tara_real_kg is not None else float(cil.modelo.tara_nominal_kg or 0)
            # Se cilindro está cheio ou sendo expedido, soma tara + gás (SKU ou Modelo)
            sku = cil.gas_dedicado.skus_recarga.filter(modelo_cilindro=cil.modelo).first() if cil.gas_dedicado else None
            if sku and sku.massa_gas_kg:
                massa_gas = float(sku.massa_gas_kg)
            elif cil.modelo and cil.modelo.massa_gas_padrao_kg:
                massa_gas = float(cil.modelo.massa_gas_padrao_kg)
            else:
                massa_gas = 10.0
            peso_adicional += (tara + massa_gas)

    peso_total_previsto = round(peso_atual + peso_adicional, 2)

    if peso_total_previsto > capacidade_maxima:
        excesso = round(peso_total_previsto - capacidade_maxima, 2)
        raise ValidationError(
            f"Capacidade de carga do veículo excedida! O peso total previsto de {peso_total_previsto:.2f} kg "
            f"excede a capacidade máxima de {capacidade_maxima:.2f} kg do veículo {entrega.veiculo.placa} "
            f"em {excesso:.2f} kg (Sobrecarga de {(peso_total_previsto/capacidade_maxima*100)-100:.1f}%)."
        )

    return peso_total_previsto


def _obter_dados_carga_entrega(entrega):
    """
    Consolida as informações dos produtos perigosos e cilindros da entrega
    agrupados por gás químico e número ONU para documentação ANTT.
    """
    movimentacoes = entrega.movimentacoes_cilindros.select_related(
        'cilindro__gas_dedicado', 'cilindro__modelo'
    ).all()

    carga_agrupada = {}
    total_volumes = 0
    total_peso_bruto = 0.0

    if movimentacoes.exists():
        for mov in movimentacoes:
            cil = mov.cilindro
            gas = cil.gas_dedicado
            tara = float(cil.tara_real_kg) if cil.tara_real_kg is not None else float(cil.modelo.tara_nominal_kg or 0)
            
            is_cheio = mov.tipo in ['ENTREGA_CLIENTE', 'SAIDA_ROTA', 'SAIDA_ENTREGA']
            sku = gas.skus_recarga.filter(modelo_cilindro=cil.modelo).first() if (gas and is_cheio) else None
            if is_cheio:
                if sku and sku.massa_gas_kg:
                    massa_gas = float(sku.massa_gas_kg)
                elif cil.modelo and cil.modelo.massa_gas_padrao_kg:
                    massa_gas = float(cil.modelo.massa_gas_padrao_kg)
                else:
                    massa_gas = 10.0
            else:
                massa_gas = 0.0
            peso_item = tara + massa_gas

            key = (gas.id, gas.numero_onu or 'UN 1072', gas.classe_risco or '2.2')
            if key not in carga_agrupada:
                carga_agrupada[key] = {
                    'gas': gas,
                    'numero_onu': gas.numero_onu or 'UN 1072',
                    'classe_risco': gas.classe_risco or '2.2',
                    'nome_embarque': gas.nome.upper(),
                    'sigla': gas.sigla,
                    'formula': getattr(gas, 'formula_quimica', '') or '',
                    'volumes_cheios': 0,

                    'volumes_vazios': 0,
                    'peso_total_kg': 0.0
                }
            if is_cheio:
                carga_agrupada[key]['volumes_cheios'] += 1
            else:
                carga_agrupada[key]['volumes_vazios'] += 1
            carga_agrupada[key]['peso_total_kg'] += peso_item
            total_volumes += 1
            total_peso_bruto += peso_item
    else:
        # Fallback caso romaneio esteja agendado antes da bipagem física
        for venda in entrega.vendas.exclude(status='Cancelada'):
            for item in venda.itens.all():
                gas_nome = item.produto.nome.upper()
                key = (item.produto.id, 'UN 1072', '2.2')
                qtd = int(item.quantidade)
                peso_un = float(item.peso_unitario or 50.0)
                peso_total_item = qtd * peso_un
                if key not in carga_agrupada:
                    carga_agrupada[key] = {
                        'gas': None,
                        'numero_onu': 'UN 1072',
                        'classe_risco': '2.2',
                        'nome_embarque': gas_nome,
                        'sigla': item.produto.nome[:4].upper(),
                        'formula': '',
                        'volumes_cheios': qtd,
                        'volumes_vazios': 0,
                        'peso_total_kg': peso_total_item
                    }
                else:
                    carga_agrupada[key]['volumes_cheios'] += qtd
                    carga_agrupada[key]['peso_total_kg'] += peso_total_item
                total_volumes += qtd
                total_peso_bruto += peso_total_item

    # Se ainda estiver vazio, gera linha padrão para o romaneio não ficar em branco
    if not carga_agrupada:
        key = (0, 'UN 1072', '2.2')
        carga_agrupada[key] = {
            'gas': None,
            'numero_onu': 'UN 1072',
            'classe_risco': '2.2',
            'nome_embarque': 'GASES COMPRIMIDOS DIVERSOS',
            'sigla': 'GAS',
            'formula': '',
            'volumes_cheios': 0,
            'volumes_vazios': 0,
            'peso_total_kg': 0.0
        }

    return {
        'itens': list(carga_agrupada.values()),
        'total_volumes': total_volumes,
        'total_peso_bruto': round(total_peso_bruto, 2)
    }


def gerar_romaneio_carga_antt_pdf(entrega):
    """
    Gera o Romaneio de Carga de Produtos Perigosos conforme Resolução ANTT nº 5.998/2022.
    Retorna bytes do PDF.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
    except ImportError as e:
        raise RuntimeError("A biblioteca 'reportlab' é necessária para gerar relatórios em PDF. Instale com pip install reportlab.") from e

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ANTTTitle',
        parent=styles['Heading1'],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#0F172A'),
        alignment=1,
        spaceAfter=3
    )
    subtitle_style = ParagraphStyle(
        'ANTTSubtitle',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=10
    )
    section_style = ParagraphStyle(
        'ANTTSection',
        parent=styles['Heading2'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#1E293B'),
        fontName='Helvetica-Bold',
        spaceBefore=6,
        spaceAfter=4
    )
    body_bold = ParagraphStyle('ANTTBodyBold', parent=styles['Normal'], fontSize=8, leading=10, fontName='Helvetica-Bold')
    body_normal = ParagraphStyle('ANTTBodyNormal', parent=styles['Normal'], fontSize=8, leading=10)
    legal_text = ParagraphStyle('ANTTLegal', parent=styles['Normal'], fontSize=7, leading=9, textColor=colors.HexColor('#334155'))

    story = []

    # 1. Cabeçalho
    story.append(Paragraph("ROMANEIO DE TRANSPORTE DE PRODUTOS PERIGOSOS", title_style))
    story.append(Paragraph("Regulamentação Terrestre ANTT - Resolução nº 5.998/2022", subtitle_style))

    # 2. Dados do Expedidor, Transportador e Veículo
    tenant = entrega.tenant
    veiculo = entrega.veiculo
    motorista = entrega.motorista
    rota = entrega.rota

    info_table_data = [
        [
            Paragraph("<b>EXPEDIDOR / REMETENTE:</b>", body_bold),
            Paragraph(f"{tenant.razao_social} ({tenant.nome_fantasia})", body_normal),
            Paragraph("<b>CNPJ:</b>", body_bold),
            Paragraph(f"{tenant.cnpj}", body_normal),
        ],
        [
            Paragraph("<b>VEÍCULO:</b>", body_bold),
            Paragraph(f"{veiculo.modelo} ({veiculo.placa if veiculo else 'N/A'})", body_normal),
            Paragraph("<b>CAPACIDADE:</b>", body_bold),
            Paragraph(f"{veiculo.capacidade_carga if veiculo else 0} kg", body_normal),
        ],
        [
            Paragraph("<b>CONDUTOR (MOPP):</b>", body_bold),
            Paragraph(f"{motorista.get_full_name() or motorista.username if motorista else 'Não Alocado'}", body_normal),
            Paragraph("<b>ROTA:</b>", body_bold),
            Paragraph(f"{rota.nome if rota else 'Rota Livre'}", body_normal),
        ],
        [
            Paragraph("<b>ROMANEIO Nº:</b>", body_bold),
            Paragraph(f"#{entrega.id} - Emissão: {timezone.now().strftime('%d/%m/%Y %H:%M')}", body_normal),
            Paragraph("<b>STATUS:</b>", body_bold),
            Paragraph(f"{entrega.get_status_display()}", body_normal),
        ]
    ]

    t_info = Table(info_table_data, colWidths=[3.2 * cm, 7.0 * cm, 2.5 * cm, 5.5 * cm])
    t_info.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 8))

    # 3. Tabela de Produtos Perigosos Transportados
    story.append(Paragraph("DISCRIMINAÇÃO DOS PRODUTOS PERIGOSOS TRANSPORTADOS (CILINDROS)", section_style))

    carga = _obter_dados_carga_entrega(entrega)
    table_carga_data = [
        [
            Paragraph("<b>Número ONU</b>", body_bold),
            Paragraph("<b>Nome Apropriado para Embarque</b>", body_bold),
            Paragraph("<b>Classe de Risco</b>", body_bold),
            Paragraph("<b>Cheios</b>", body_bold),
            Paragraph("<b>Vazios</b>", body_bold),
            Paragraph("<b>Total Volumes</b>", body_bold),
            Paragraph("<b>Peso Bruto (kg)</b>", body_bold)
        ]
    ]

    for item in carga['itens']:
        tot_item_vol = item['volumes_cheios'] + item['volumes_vazios']
        formula_txt = f" ({item['formula']})" if item.get('formula') else ''
        table_carga_data.append([
            Paragraph(f"<b>{item['numero_onu']}</b>", body_normal),
            Paragraph(f"{item['nome_embarque']}{formula_txt}", body_normal),
            Paragraph(f"{item['classe_risco']}", body_normal),
            Paragraph(f"{item['volumes_cheios']}", body_normal),
            Paragraph(f"{item['volumes_vazios']}", body_normal),
            Paragraph(f"{tot_item_vol}", body_normal),
            Paragraph(f"{item['peso_total_kg']:.2f}", body_normal),
        ])


    # Linha de Totais
    table_carga_data.append([
        Paragraph("<b>TOTAL GERAL</b>", body_bold),
        Paragraph("", body_normal),
        Paragraph("", body_normal),
        Paragraph("", body_normal),
        Paragraph("", body_normal),
        Paragraph(f"<b>{carga['total_volumes']} un</b>", body_bold),
        Paragraph(f"<b>{carga['total_peso_bruto']:.2f} kg</b>", body_bold)
    ])

    t_carga = Table(table_carga_data, colWidths=[2.2 * cm, 6.8 * cm, 2.2 * cm, 1.4 * cm, 1.4 * cm, 2.0 * cm, 2.2 * cm])
    t_carga.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F1F5F9')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_carga)
    story.append(Spacer(1, 8))

    # 4. Verificação de Capacidade e Lotação
    cap_veiculo = float(veiculo.capacidade_carga) if veiculo and veiculo.capacidade_carga else 0.0
    peso_carregado = carga['total_peso_bruto']
    lotacao_perc = (peso_carregado / cap_veiculo * 100) if cap_veiculo > 0 else 0

    val_data = [
        [
            Paragraph(f"<b>Capacidade Nominal do Veículo:</b> {cap_veiculo:.2f} kg", body_normal),
            Paragraph(f"<b>Peso Total Carregado:</b> {peso_carregado:.2f} kg", body_normal),
            Paragraph(f"<b>Lotação Atual:</b> {lotacao_perc:.1f}%", body_normal),
            Paragraph(
                "<b>Status da Carga:</b> <font color='green'><b>CONFORME (SEM SOBRECARGA)</b></font>" if peso_carregado <= cap_veiculo or cap_veiculo == 0
                else "<b>Status da Carga:</b> <font color='red'><b>NÃO CONFORME (SOBRECARGA DETECTADA)</b></font>",
                body_normal
            )
        ]
    ]
    t_val = Table(val_data, colWidths=[4.5 * cm, 4.5 * cm, 3.2 * cm, 6.0 * cm])
    t_val.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_val)
    story.append(Spacer(1, 10))

    # 5. Declaração do Expedidor e Assinaturas (ANTT 5.998/2022)
    dec_text = (
        "<b>DECLARAÇÃO DO EXPEDIDOR CONFORME RESOLUÇÃO ANTT Nº 5.998/2022:</b><br/>"
        "Declaro que os produtos perigosos estão adequadamente classificados, embalados, marcados e rotulados, "
        "a fim de suportar os riscos das operações de transporte e que atendem a todas as exigências da regulamentação "
        "de transporte terrestre de produtos perigosos vigente. Os recipientes de gás comprimido possuem teste hidrostático "
        "válido e válvulas de segurança protegidas por capacetes."
    )
    story.append(Paragraph(dec_text, legal_text))
    story.append(Spacer(1, 20))

    sig_data = [
        [
            Paragraph("____________________________________________<br/><b>Assinatura do Expedidor / Conferente</b>", ParagraphStyle('Sig', parent=styles['Normal'], fontSize=8, alignment=1)),
            Paragraph("____________________________________________<br/><b>Assinatura do Condutor (MOPP)</b>", ParagraphStyle('Sig2', parent=styles['Normal'], fontSize=8, alignment=1))
        ]
    ]
    t_sig = Table(sig_data, colWidths=[9.1 * cm, 9.1 * cm])
    t_sig.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
    story.append(t_sig)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def gerar_ficha_emergencia_antt_pdf(entrega):
    """
    Gera a Ficha de Emergência para Transporte de Produtos Perigosos
    conforme norma técnica ABNT NBR 7503 e Resolução ANTT nº 5.998/2022.
    Retorna bytes do PDF.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
    except ImportError as e:
        raise RuntimeError("A biblioteca 'reportlab' é necessária para gerar relatórios em PDF. Instale com pip install reportlab.") from e

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'FichaTitle',
        parent=styles['Heading1'],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#991B1B'),
        alignment=1,
        spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        'FichaSub',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=8
    )
    header_block = ParagraphStyle('HBlock', parent=styles['Normal'], fontSize=8, leading=10, fontName='Helvetica-Bold')
    body_text = ParagraphStyle('BText', parent=styles['Normal'], fontSize=7.5, leading=10, textColor=colors.HexColor('#1E293B'))
    section_head = ParagraphStyle('SHead', parent=styles['Heading2'], fontSize=8.5, leading=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#0F172A'))

    story = []

    story.append(Paragraph("FICHA DE EMERGÊNCIA - TRANSPORTE TERRESTRE", title_style))
    story.append(Paragraph("Conforme Norma ABNT NBR 7503 e Resolução ANTT nº 5.998/2022", subtitle_style))

    tenant = entrega.tenant
    carga = _obter_dados_carga_entrega(entrega)

    # Identificação dos produtos perigosos
    onus_str = ", ".join(sorted(list({i['numero_onu'] for i in carga['itens']})))
    classes_str = ", ".join(sorted(list({i['classe_risco'] for i in carga['itens']})))
    nomes_str = "; ".join([f"{i['nome_embarque']} ({i['numero_onu']})" for i in carga['itens'][:4]])

    t_prod_data = [
        [
            Paragraph("<b>EXPEDIDOR:</b>", header_block),
            Paragraph(f"{tenant.razao_social} - CNPJ: {tenant.cnpj}", body_text),
            Paragraph("<b>FONE EMERGÊNCIA:</b>", header_block),
            Paragraph("<b>193 (Bombeiros) / (11) 4000-0000</b>", header_block),
        ],
        [
            Paragraph("<b>PRODUTO(S):</b>", header_block),
            Paragraph(nomes_str, body_text),
            Paragraph("<b>NÚMERO ONU:</b>", header_block),
            Paragraph(f"<b>{onus_str}</b>", header_block),
        ],
        [
            Paragraph("<b>CLASSE/SUBCLASSE:</b>", header_block),
            Paragraph(f"Classe {classes_str} - Gases Comprimidos", body_text),
            Paragraph("<b>DESCR. RISCO:</b>", header_block),
            Paragraph("20 / 22 / 23 (Gás Asfixiante / Oxidante)", body_text),
        ]
    ]

    t_prod = Table(t_prod_data, colWidths=[3.2 * cm, 7.5 * cm, 3.0 * cm, 4.5 * cm])
    t_prod.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FEF2F2')),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor('#EF4444')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#FECACA')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_prod)
    story.append(Spacer(1, 6))

    # Tabela de Riscos e Condutas de Emergência (NBR 7503)
    bloco_data = [
        [
            Paragraph("<b>ASPECTO E PROPRIEDADES FÍSICO-QUÍMICAS</b>", section_head),
        ],
        [
            Paragraph(
                "Gases comprimidos ou liquefeitos sob alta pressão em cilindros de aço sem costura ou alumínio. "
                "Incolores, grande parte inodoros ou com odor característico. Mais pesados ou mais leves que o ar. "
                "Cilindros expostos ao fogo ou calor intenso podem se romper violentamente (risco de explosão física e BLEVE).",
                body_text
            )
        ],
        [
            Paragraph("<b>RISCOS AO FOGO E EXPLOSÃO</b>", section_head),
        ],
        [
            Paragraph(
                "• <b>Oxigênio / Gases Oxidantes (Classe 2.2 / 5.1):</b> Não são combustíveis por si só, mas aceleram violentamente a queima de combustíveis, graxas e óleos.<br/>"
                "• <b>Gases Inflamáveis (Classe 2.1):</b> Vapores formam misturas explosivas com o ar. Risco extremo de ignição à distância.<br/>"
                "• <b>Comportamento ao Calor:</b> A pressão interna sobe rapidamente com o calor. Resfriar os cilindros com jatos de neblina d'água à máxima distância.",
                body_text
            )
        ],
        [
            Paragraph("<b>RISCOS À SAÚDE HUMANA</b>", section_head),
        ],
        [
            Paragraph(
                "• <b>Asfixia:</b> Gases inertes (Nitrogênio, Argônio, Dióxido de Carbono) deslocam o oxigênio do ar em ambientes confinados, causando perda rápida de consciência e morte por asfixia sem aviso prévio.<br/>"
                "• <b>Queimaduras por Frio:</b> O escape rápido de gases comprimidos/liquefeitos causa congelamento instantâneo da pele e mucosas (criogenia).<br/>"
                "• <b>Toxicidade:</b> Evitar inalação de vapores. Utilizar máscara autônoma se houver suspeita de gases tóxicos ou atmosfera deficiente em O2.",
                body_text
            )
        ],
        [
            Paragraph("<b>EQUIPAMENTOS DE PROTEÇÃO INDIVIDUAL (EPI) DO CONDUTOR</b>", section_head),
        ],
        [
            Paragraph(
                "Capacete de segurança com jugular, óculos panorâmicos de ampla visão contra impactos, luvas de vaqueta/raspa "
                "de couro para manuseio de válvulas e cilindros, calçado de segurança com biqueira de aço, protetor auricular e uniforme resistente.",
                body_text
            )
        ],
        [
            Paragraph("<b>MEDIDAS EM CASO DE ACIDENTE OU VAZAMENTO</b>", section_head),
        ],
        [
            Paragraph(
                "1. Isolar imediatamente a área em um raio de no mínimo 100 metros e afastar curiosos.<br/>"
                "2. Sinalizar a rodovia com triângulos, cones e pisca-alerta a montante e a jusante do sinistro.<br/>"
                "3. Posicionar-se a favor do vento (costas para o vento). Jamais adentrar nuvens visíveis ou áreas confinadas.<br/>"
                "4. Eliminar todas as fontes de ignição (faíscas, chamas, cigarros, interruptores elétricos). Não ligar rádio/celular próximo ao vazamento.<br/>"
                "5. Fechar a válvula do cilindro se isto puder ser feito com total segurança e sem risco físico.<br/>"
                "6. Se houver fogo em cilindros, NÃO apagar as chamas antes de cortar o fluxo. Resfriar os recipientes vizinhos com jato d'água nebulizada.",
                body_text
            )
        ],
        [
            Paragraph("<b>PRIMEIROS SOCORROS</b>", section_head),
        ],
        [
            Paragraph(
                "• <b>Inalação:</b> Remover a vítima imediatamente para local com ar fresco. Se a vítima não respirar, aplicar respiração artificial.<br/>"
                "• <b>Contato com Pele / Queimadura Criogênica:</b> Enxaguar abundantemente com água morna. Não friccionar a área congelada.<br/>"
                "• <b>Apoio Médico:</b> Manter a vítima aquecida e em repouso. Encaminhar para socorro médico especializado informando o número ONU.",
                body_text
            )
        ]
    ]

    t_bloco = Table(bloco_data, colWidths=[18.2 * cm])
    t_bloco.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#F1F5F9')),
        ('BACKGROUND', (0, 2), (0, 2), colors.HexColor('#F1F5F9')),
        ('BACKGROUND', (0, 4), (0, 4), colors.HexColor('#F1F5F9')),
        ('BACKGROUND', (0, 6), (0, 6), colors.HexColor('#F1F5F9')),
        ('BACKGROUND', (0, 8), (0, 8), colors.HexColor('#F1F5F9')),
        ('BACKGROUND', (0, 10), (0, 10), colors.HexColor('#F1F5F9')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_bloco)
    story.append(Spacer(1, 6))

    # Telefones de Emergência
    t_fones = Table([
        [
            Paragraph("<b>TELEFONES ÚTEIS DE EMERGÊNCIA (24H):</b>", header_block),
            Paragraph("<b>Bombeiros: 193</b>", header_block),
            Paragraph("<b>Polícia Rodoviária Federal: 191</b>", header_block),
            Paragraph("<b>Defesa Civil: 199</b>", header_block),
            Paragraph("<b>SAMU: 192</b>", header_block),
        ]
    ], colWidths=[6.2 * cm, 3.0 * cm, 4.0 * cm, 2.5 * cm, 2.5 * cm])
    t_fones.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_fones)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def gerar_envelope_transporte_antt_pdf(entrega):
    """
    Gera o Envelope para Transporte de Produtos Perigosos conforme Resolução ANTT nº 5.998/2022.
    Retorna bytes do PDF.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
    except ImportError as e:
        raise RuntimeError("A biblioteca 'reportlab' é necessária para gerar relatórios em PDF. Instale com pip install reportlab.") from e

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'EnvTitle',
        parent=styles['Heading1'],
        fontSize=15,
        leading=18,
        textColor=colors.HexColor('#0F172A'),
        alignment=1,
        spaceAfter=3
    )
    subtitle_style = ParagraphStyle(
        'EnvSubtitle',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=12
    )
    box_header = ParagraphStyle('BHead', parent=styles['Normal'], fontSize=9, leading=12, fontName='Helvetica-Bold')
    box_body = ParagraphStyle('BBody', parent=styles['Normal'], fontSize=8.5, leading=12)

    story = []

    story.append(Paragraph("ENVELOPE PARA TRANSPORTE DE PRODUTOS PERIGOSOS", title_style))
    story.append(Paragraph("Regulamentação Terrestre ANTT - Resolução nº 5.998/2022 e NBR 7503", subtitle_style))

    tenant = entrega.tenant
    veiculo = entrega.veiculo
    motorista = entrega.motorista
    carga = _obter_dados_carga_entrega(entrega)

    info_env = [
        [
            Paragraph("<b>EXPEDIDOR / REMETENTE:</b>", box_header),
            Paragraph(f"{tenant.razao_social}<br/>CNPJ: {tenant.cnpj}", box_body),
        ],
        [
            Paragraph("<b>TRANSPORTADOR:</b>", box_header),
            Paragraph(f"Frota Própria - {tenant.nome_fantasia}<br/>Veículo Placa: {veiculo.placa if veiculo else 'N/A'} - Condutor: {motorista.get_full_name() or motorista.username if motorista else 'N/A'}", box_body),
        ],
        [
            Paragraph("<b>PRODUTOS PERIGOSOS A BORDO:</b>", box_header),
            Paragraph("<br/>".join([f"• <b>{i['numero_onu']}</b> - {i['nome_embarque']} (Classe {i['classe_risco']}) - {i['volumes_cheios'] + i['volumes_vazios']} cilindros" for i in carga['itens']]), box_body),
        ]
    ]

    t_info = Table(info_env, colWidths=[5.5 * cm, 12.0 * cm])
    t_info.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor('#0F172A')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 14))

    # Lista de Documentos Obrigatórios contidos neste Envelope
    docs_data = [
        [Paragraph("<b>DOCUMENTOS OBRIGATÓRIOS QUE DEVEM CONSTAR DENTRO DESTE ENVELOPE:</b>", box_header)],
        [Paragraph(
            "<b>1. Romaneio de Transporte de Produtos Perigosos</b> (discriminando número ONU, nome apropriado para embarque, classe de risco e quantidade).<br/>"
            "<b>2. Ficha de Emergência do Expedidor</b> (ABNT NBR 7503) correspondente a todos os produtos químicos transportados no veículo.<br/>"
            "<b>3. Documentos Fiscais de Transporte</b> (NF-e de venda/remessa ou CT-e acompanhado de DACTE).<br/>"
            "<b>4. Certificado de Conclusão do Curso MOPP do Condutor</b> (Movimentação Operacional de Produtos Perigosos) e CNH com observação MOPP.<br/>"
            "<b>5. Certificados do Veículo:</b> CIPP (Certificado de Inspeção para o Transporte de Produtos Perigosos) e CIV (Certificado de Inspeção Veicular), quando aplicáveis.",
            box_body
        )]
    ]
    t_docs = Table(docs_data, colWidths=[17.5 * cm])
    t_docs.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor('#0F172A')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#F8FAFC')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_docs)
    story.append(Spacer(1, 14))

    # Procedimentos de Emergência do Envelope
    proc_data = [
        [Paragraph("<b>INSTRUÇÕES PARA O CONDUTOR EM CASO DE ACIDENTE OU EMERGÊNCIA:</b>", box_header)],
        [Paragraph(
            "1. Pare imediatamente o veículo em acostamento ou local seguro, longe de habitações, se possível.<br/>"
            "2. Desligue o motor e o sistema elétrico do veículo.<br/>"
            "3. Sinalize imediatamente a via pública utilizando os triângulos e cones do kit de emergência.<br/>"
            "4. Retire este envelope da cabine e consulte as instruções da Ficha de Emergência correspondente ao produto.<br/>"
            "5. Acione o Corpo de Bombeiros (193) e a Polícia Rodoviária (191) informando os números ONU transportados.<br/>"
            "6. Mantenha as pessoas afastadas e permaneça em posição a favor do vento.",
            box_body
        )]
    ]
    t_proc = Table(proc_data, colWidths=[17.5 * cm])
    t_proc.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor('#DC2626')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#FEF2F2')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_proc)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
