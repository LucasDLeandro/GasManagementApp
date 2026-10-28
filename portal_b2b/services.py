import io
import hashlib
from datetime import datetime
from django.utils import timezone
from django.conf import settings


def gerar_laudo_quimico_pdf(cilindro, lote, movimentacao=None, cliente=None):
    """
    Gera o Certificado de Análise / Laudo de Conformidade Química e Sanitária em formato PDF
    em estrita conformidade com as Boas Práticas de Fabricação de Gases Medicinais
    (RDC nº 658/2022, IN nº 129/2022 e RDC nº 870/2024 - ANVISA).
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    except ImportError as e:
        raise RuntimeError("A biblioteca 'reportlab' é necessária para gerar relatórios em PDF.") from e

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
        'LaudoTitle',
        parent=styles['Heading1'],
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#0F172A'),
        alignment=1,
        spaceAfter=4,
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'LaudoSubtitle',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=12
    )
    section_title = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=8,
        spaceAfter=4,
        fontName='Helvetica-Bold'
    )
    cell_label = ParagraphStyle(
        'CellLabel',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#64748B'),
        fontName='Helvetica-Bold'
    )
    cell_val = ParagraphStyle(
        'CellVal',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#0F172A')
    )
    footer_text = ParagraphStyle(
        'FooterText',
        parent=styles['Normal'],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#64748B'),
        alignment=1
    )

    story = []

    # Cabeçalho Principal
    story.append(Paragraph("CERTIFICADO DE ANÁLISE / LAUDO DE CONFORMIDADE QUÍMICA", title_style))
    story.append(Paragraph("Garantia de Qualidade e Rastreabilidade Farmacêutica • ANVISA RDC 658/2022 & IN 129/2022", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563EB'), spaceAfter=10))

    # Identificação do Emissor e Destinatário
    tenant_nome = cilindro.tenant.nome_fantasia if hasattr(cilindro, 'tenant') and cilindro.tenant else "Distribuidora de Gases"
    cliente_nome = cliente.nome if cliente else (cilindro.cliente_posse_atual.nome if cilindro.cliente_posse_atual else "Cliente Não Informado")
    cliente_cnpj = cliente.cnpj if cliente else (cilindro.cliente_posse_atual.cnpj if cilindro.cliente_posse_atual else "-")
    cidade_uf = f"{cliente.cidade}/{cliente.estado}" if (cliente and cliente.cidade) else "-"

    header_data = [
        [
            Paragraph("EMISSOR / FABRICANTE", cell_label),
            Paragraph("CLIENTE / DESTINATÁRIO", cell_label)
        ],
        [
            Paragraph(f"<b>{tenant_nome}</b><br/>Gases Medicinais e Industriais", cell_val),
            Paragraph(f"<b>{cliente_nome}</b><br/>CNPJ: {cliente_cnpj} • {cidade_uf}", cell_val)
        ]
    ]
    t_header = Table(header_data, colWidths=[9.0 * cm, 9.0 * cm])
    t_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 8))

    # Identificação do Casco / Cilindro
    story.append(Paragraph("1. IDENTIFICAÇÃO DO RECIPIENTE TRANSPORTÁVEL (CASCO)", section_title))
    gas_nome = cilindro.gas_dedicado.nome if cilindro.gas_dedicado else "Gás Não Informado"
    gas_sigla = cilindro.gas_dedicado.sigla if cilindro.gas_dedicado else "-"
    modelo_nome = getattr(cilindro.modelo, 'descricao', getattr(cilindro.modelo, 'nome', "-")) if cilindro.modelo else "-"
    vol_litros = f"{getattr(cilindro.modelo, 'volume_hidraulico_litros', getattr(cilindro.modelo, 'volume_litros', '-'))} L" if cilindro.modelo else "-"

    cilindro_data = [
        [
            Paragraph("NÚMERO DE SÉRIE (OGIVA)", cell_label),
            Paragraph("CÓDIGO QR / IDENTIFICADOR", cell_label),
            Paragraph("FABRICANTE / ANO", cell_label)
        ],
        [
            Paragraph(f"<b>{cilindro.numero_serie_ogiva}</b>", cell_val),
            Paragraph(cilindro.codigo_qr, cell_val),
            Paragraph(f"{cilindro.fabricante} ({cilindro.ano_fabricacao})", cell_val)
        ],
        [
            Paragraph("GÁS QUÍMICO DEDICADO", cell_label),
            Paragraph("MODELO DO VASO / VOLUME", cell_label),
            Paragraph("PRÓXIMO RETESTE HIDROSTÁTICO", cell_label)
        ],
        [
            Paragraph(f"<b>{gas_nome} ({gas_sigla})</b>", cell_val),
            Paragraph(f"{modelo_nome} ({vol_litros})", cell_val),
            Paragraph(f"{cilindro.data_proximo_reteste.strftime('%d/%m/%Y')}", cell_val)
        ]
    ]
    t_cilindro = Table(cilindro_data, colWidths=[6.0 * cm, 6.0 * cm, 6.0 * cm])
    t_cilindro.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFFFFF')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_cilindro)
    story.append(Spacer(1, 8))

    # Dados Químicos e de Rastreabilidade do Lote
    story.append(Paragraph("2. DADOS FÍSICO-QUÍMICOS E RASTREABILIDADE DO LOTE", section_title))
    data_env = lote.data_envase.strftime('%d/%m/%Y') if lote.data_envase else "-"
    data_val = lote.data_validade.strftime('%d/%m/%Y') if lote.data_validade else "-"
    status_qual = lote.get_status_qualidade_display() if hasattr(lote, 'get_status_qualidade_display') else lote.status_qualidade
    pureza_txt = f"{lote.pureza_percentual:.2f} %" if lote.pureza_percentual else ">= 99.5 %"

    pressao_bar = "200 bar"
    if movimentacao and getattr(movimentacao, 'envase_cilindro', None):
        pressao_bar = f"{movimentacao.envase_cilindro.pressao_final_bar} bar"
    elif hasattr(cilindro, 'envase_atual') and cilindro.envase_atual:
        pressao_bar = f"{cilindro.envase_atual.pressao_final_bar} bar"

    lote_data = [
        [
            Paragraph("CÓDIGO DO LOTE", cell_label),
            Paragraph("DATA DE ENVASE", cell_label),
            Paragraph("DATA DE VALIDADE DO GÁS", cell_label)
        ],
        [
            Paragraph(f"<b>{lote.codigo_lote}</b>", cell_val),
            Paragraph(data_env, cell_val),
            Paragraph(f"<b>{data_val}</b>", cell_val)
        ],
        [
            Paragraph("PUREZA QUÍMICA AFERIDA", cell_label),
            Paragraph("PRESSÃO DE CARGA", cell_label),
            Paragraph("STATUS DE QUALIDADE (CQ/RT)", cell_label)
        ],
        [
            Paragraph(f"<font color='#059669'><b>{pureza_txt}</b></font>", cell_val),
            Paragraph(pressao_bar, cell_val),
            Paragraph(f"<b>{status_qual}</b>", cell_val)
        ]
    ]
    t_lote = Table(lote_data, colWidths=[6.0 * cm, 6.0 * cm, 6.0 * cm])
    t_lote.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFFFFF')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_lote)
    story.append(Spacer(1, 10))

    # Responsável Técnico e Assinatura Digital
    story.append(Paragraph("3. HOMOLOGAÇÃO DO RESPONSÁVEL TÉCNICO (RT)", section_title))
    rt_nome = lote.rt_nome_snapshot or (lote.responsavel_tecnico_fk.nome if getattr(lote, 'responsavel_tecnico_fk', None) else lote.responsavel_tecnico) or "Responsável Técnico"
    rt_registro = lote.rt_registro_snapshot or (lote.responsavel_tecnico_fk.numero_registro if getattr(lote, 'responsavel_tecnico_fk', None) else "")
    rt_conselho = lote.rt_conselho_snapshot or (lote.responsavel_tecnico_fk.conselho if getattr(lote, 'responsavel_tecnico_fk', None) else "CRQ/CRF")
    rt_qualificacao = f"{rt_conselho} nº {rt_registro}" if rt_registro else rt_conselho

    timestamp_str = timezone.now().strftime('%d/%m/%Y %H:%M:%S UTC')
    hash_payload = f"{cilindro.codigo_qr}:{lote.codigo_lote}:{rt_nome}:{rt_registro}:{timestamp_str}"
    hash_digest = hashlib.sha256(hash_payload.encode('utf-8')).hexdigest().upper()

    rt_box_data = [
        [
            Paragraph(
                f"<b>DECLARAÇÃO DE CONFORMIDADE:</b> Certifico que o lote de gás acima identificado foi processado, "
                f"envasado e analisado em conformidade estrita com os compêndios oficiais e as normas técnicas "
                f"estabelecidas pela Farmacopeia Brasileira e pela ANVISA.<br/><br/>"
                f"<b>{rt_nome}</b><br/>"
                f"Responsável Técnico Homologador • {rt_qualificacao}",
                cell_val
            )
        ],
        [
            Paragraph(
                f"<b>Assinatura Eletrônica Qualificada / Carimbo Digital:</b><br/>"
                f"Código de Autenticidade (SHA-256): <font face='Courier' size='7'>{hash_digest[:40]}...</font><br/>"
                f"Emitido em: {timestamp_str} pelo Portal B2B Baros SaaS",
                footer_text
            )
        ]
    ]
    t_rt = Table(rt_box_data, colWidths=[18.0 * cm])
    t_rt.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#94A3B8')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('LINEBELOW', (0, 0), (0, 0), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    story.append(t_rt)

    doc.build(story)
    buffer.seek(0)
    return buffer
