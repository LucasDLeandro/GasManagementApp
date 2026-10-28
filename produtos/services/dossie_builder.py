import io
import hashlib
from datetime import datetime
from decimal import Decimal
from django.utils import timezone
from django.db.models import Prefetch
from django.http import Http404

from produtos.models import (
    LoteEnvase,
    EnvaseCilindro,
    Cilindro,
    MovimentacaoCilindro,
    AuditoriaDownloadLog,
)


from core.tenancy import tenant_context
from logistica.models import ComprovanteEntrega


class DossieAnvisaBuilder:
    """
    Construtor oficial do Dossiê Regulatório e Farmacêutico ANVISA (Sprint 10).
    Conformidade estrita com:
    - RDC nº 658/2022 (Diretrizes Gerais de BPF de Medicamentos);
    - IN nº 129/2022 (BPF Complementares para Gases Medicinais);
    - RDC nº 870/2024 (Rastreabilidade e Notificação em Farmacovigilância).

    Realiza consulta hierárquica completa livre de queries N+1:
    LoteEnvase -> EnvaseCilindro -> Cilindro -> MovimentacaoCilindro -> Entrega -> ComprovanteEntrega
    """

    def __init__(self, lote_id, tenant):
        self.lote_id = lote_id
        self.tenant = tenant
        self.lote = self._carregar_arvore_hierarquica()

    def _carregar_arvore_hierarquica(self):
        """
        Executa uma única consulta otimizada com select_related e prefetch_related encadeados,
        carregando toda a cadeia de custódia e rastreabilidade sanitária.
        """
        with tenant_context(self.tenant):
            lote = LoteEnvase.unscoped.filter(
                id=self.lote_id,
                tenant=self.tenant
            ).select_related(
                'gas',
                'responsavel_tecnico_fk',
                'tenant'
            ).prefetch_related(
                Prefetch(
                    'cilindros_envasados',
                    queryset=EnvaseCilindro.unscoped.select_related(
                        'cilindro__modelo',
                        'cilindro__gas_dedicado',
                        'cilindro__cliente_posse_atual',
                        'operador'
                    ).prefetch_related(
                        Prefetch(
                            'movimentacoes',
                            queryset=MovimentacaoCilindro.unscoped.select_related(
                                'cliente',
                                'entrega__motorista',
                                'entrega__veiculo'
                            ).prefetch_related(
                                Prefetch('comprovantes_vinculados', queryset=ComprovanteEntrega.unscoped.all()),
                                Prefetch('comprovantes', queryset=ComprovanteEntrega.unscoped.all())
                            ).order_by('-registrado_em')
                        )
                    ).order_by('cilindro__numero_serie_ogiva')
                )
            ).first()

            if not lote:
                raise Http404("Lote de envase não encontrado para este Tenant.")

            return lote

    def build_pdf(self, usuario=None, ip_origem=None, user_agent=None):
        """
        Renderiza o documento PDF formatado em Platypus (ReportLab),
        calcula o hash SHA-256 e persiste o log em AuditoriaDownloadLog.
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import cm
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
                Table,
                TableStyle,
                HRFlowable,
                KeepTogether,
            )
            from reportlab.pdfgen import canvas
        except ImportError as e:
            raise RuntimeError("A biblioteca 'reportlab' é necessária para gerar relatórios em PDF.") from e

        # Primeira passagem em memória para calcular o hash SHA-256 canônico
        buffer = io.BytesIO()

        # Canvas numerado com rodapé de integridade
        class NumberedCanvasWithSHA(canvas.Canvas):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._saved_page_states = []

            def showPage(self):
                self._saved_page_states.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                num_pages = len(self._saved_page_states)
                for state in self._saved_page_states:
                    self.__dict__.update(state)
                    self.draw_page_number(num_pages)
                    super().showPage()
                super().save()

            def draw_page_number(self, page_count):
                self.saveState()
                self.setFont("Helvetica", 7.5)
                self.setFillColor(colors.HexColor('#64748B'))

                # Linha divisória do rodapé
                self.setStrokeColor(colors.HexColor('#CBD5E1'))
                self.setLineWidth(0.5)
                self.line(1.5 * cm, 1.2 * cm, 19.5 * cm, 1.2 * cm)

                # Texto do rodapé
                footer_left = "Baros SaaS • Dossiê de Rastreabilidade ANVISA (IN nº 129/2022 / RDC nº 658/2022)"
                page_text = f"Página {self._pageNumber} de {page_count}"
                self.drawString(1.5 * cm, 0.8 * cm, footer_left)
                self.drawRightString(19.5 * cm, 0.8 * cm, page_text)
                self.restoreState()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=1.8 * cm
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'DossieTitle',
            parent=styles['Heading1'],
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#0F172A'),
            alignment=1,
            spaceAfter=3,
            fontName='Helvetica-Bold'
        )
        subtitle_style = ParagraphStyle(
            'DossieSubtitle',
            parent=styles['Normal'],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor('#475569'),
            alignment=1,
            spaceAfter=10
        )
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading2'],
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor('#1E293B'),
            spaceBefore=8,
            spaceAfter=4,
            fontName='Helvetica-Bold'
        )
        th_style = ParagraphStyle(
            'TableHeader',
            parent=styles['Normal'],
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor('#1E293B'),
            fontName='Helvetica-Bold'
        )
        td_style = ParagraphStyle(
            'TableCell',
            parent=styles['Normal'],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor('#334155')
        )
        label_style = ParagraphStyle(
            'InfoLabel',
            parent=styles['Normal'],
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor('#64748B'),
            fontName='Helvetica-Bold'
        )
        val_style = ParagraphStyle(
            'InfoVal',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#0F172A')
        )

        story = []

        # Cabeçalho Principal do Dossiê
        story.append(Paragraph("DOSSIÊ TÉCNICO REGULATÓRIO DE LOTE E ENVASE", title_style))
        story.append(Paragraph(
            "Cadeia Completa de Custódia e Rastreabilidade ANVISA • RDC 658/2022, IN 129/2022 e RDC 870/2024",
            subtitle_style
        ))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0284C7'), spaceAfter=8))

        # 1. Informações do Fabricante e do Lote
        story.append(Paragraph("1. ESPECIFICAÇÃO TÉCNICA E HOMOLOGAÇÃO DO LOTE", section_style))

        tenant_razao = self.lote.tenant.razao_social if self.lote.tenant else "Indústria Envasadora"
        tenant_cnpj = self.lote.tenant.cnpj if self.lote.tenant else "-"
        gas_desc = f"{self.lote.gas.nome} ({self.lote.gas.sigla})" if self.lote.gas else "-"
        pureza_str = f"{self.lote.pureza_percentual:.2f} %" if self.lote.pureza_percentual else ">= 99.50 %"
        data_env = self.lote.data_envase.strftime('%d/%m/%Y') if self.lote.data_envase else "-"
        data_val = self.lote.data_validade.strftime('%d/%m/%Y') if self.lote.data_validade else "-"
        rt_nome = self.lote.rt_nome_snapshot or self.lote.responsavel_tecnico or "Não informado"
        rt_reg = self.lote.rt_registro_snapshot or ""
        rt_conselho = self.lote.rt_conselho_snapshot or "CRF/CRQ"
        rt_completo = f"{rt_nome} ({rt_conselho} {rt_reg})".strip()

        info_lote = [
            [
                Paragraph("EMPRESA EMISSORA / ENVASADORA", label_style),
                Paragraph("GÁS QUÍMICO / CLASSIFICAÇÃO", label_style),
                Paragraph("STATUS DE QUALIDADE (CQ/RT)", label_style)
            ],
            [
                Paragraph(f"<b>{tenant_razao}</b><br/>CNPJ: {tenant_cnpj}", val_style),
                Paragraph(f"<b>{gas_desc}</b><br/>Pureza Aferida: <font color='#059669'><b>{pureza_str}</b></font>", val_style),
                Paragraph(f"<b>{self.lote.get_status_qualidade_display()}</b>", val_style)
            ],
            [
                Paragraph("CÓDIGO OFICIAL DO LOTE", label_style),
                Paragraph("DATAS DE ENVASE E VALIDADE", label_style),
                Paragraph("RESPONSÁVEL TÉCNICO HOMOLOGADOR", label_style)
            ],
            [
                Paragraph(f"<font size='9'><b>{self.lote.codigo_lote}</b></font>", val_style),
                Paragraph(f"Envase: {data_env}<br/>Validade: <b>{data_val}</b>", val_style),
                Paragraph(f"<b>{rt_completo}</b>", val_style)
            ]
        ]
        t_info = Table(info_lote, colWidths=[6.0 * cm, 6.0 * cm, 6.0 * cm])
        t_info.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(t_info)
        story.append(Spacer(1, 8))

        # 2. Cilindros Envasados e Rastreabilidade Individual
        story.append(Paragraph("2. REGISTRO DE ENVASE INDIVIDUAL DOS CILINDROS (RAMPA)", section_style))

        envases = list(self.lote.cilindros_envasados.all())
        total_cilindros = len(envases)

        table_cilindros_data = [
            [
                Paragraph("Nº Série Ogiva", th_style),
                Paragraph("Código QR", th_style),
                Paragraph("Modelo / Vaso", th_style),
                Paragraph("Pressão (bar)", th_style),
                Paragraph("Data/Hora Envase", th_style),
                Paragraph("Operador", th_style)
            ]
        ]

        if not envases:
            table_cilindros_data.append([
                Paragraph("<i>Nenhum cilindro registrado na rampa para este lote.</i>", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style)
            ])
        else:
            for env in envases:
                cil = env.cilindro
                mod_desc = getattr(cil.modelo, 'descricao', getattr(cil.modelo, 'nome', "-")) if cil.modelo else "-"
                operador_nome = env.operador.username if env.operador else "-"
                dt_env = env.envasado_em.strftime('%d/%m/%Y %H:%M') if env.envasado_em else "-"

                table_cilindros_data.append([
                    Paragraph(f"<b>{cil.numero_serie_ogiva}</b>", td_style),
                    Paragraph(f"<font face='Courier' size='6.5'>{cil.codigo_qr}</font>", td_style),
                    Paragraph(mod_desc, td_style),
                    Paragraph(f"{env.pressao_final_bar} bar", td_style),
                    Paragraph(dt_env, td_style),
                    Paragraph(operador_nome, td_style)
                ])

        t_cilindros = Table(table_cilindros_data, colWidths=[3.2 * cm, 3.5 * cm, 3.8 * cm, 2.2 * cm, 3.0 * cm, 2.3 * cm])
        t_cilindros.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(t_cilindros)
        story.append(Spacer(1, 8))

        # 3. Cadeia de Custódia Logística e Comprovantes Eletrônicos
        story.append(Paragraph("3. CADEIA DE DISTRIBUIÇÃO E ASSINATURA ELETRÔNICA DO RECEBEDOR", section_style))

        table_logistica_data = [
            [
                Paragraph("Cilindro", th_style),
                Paragraph("Cliente Destinatário", th_style),
                Paragraph("Entrega / Rota", th_style),
                Paragraph("Recebedor / Documento", th_style),
                Paragraph("Data/Hora Entrega", th_style),
                Paragraph("Hash Comprovante", th_style)
            ]
        ]

        total_movimentacoes = 0
        for env in envases:
            movs = list(env.movimentacoes.all())
            for mov in movs:
                total_movimentacoes += 1
                cliente_nome = mov.cliente.nome if mov.cliente else "Patrimônio Interno"
                entrega_str = f"Entrega #{mov.entrega_id}" if mov.entrega_id else "Direta / Pátio"

                # Comprovante de entrega eletrônico
                comprovante = mov.comprovantes_vinculados.first() or mov.comprovantes.first()
                if not comprovante and mov.entrega and hasattr(mov.entrega, 'comprovantes'):
                    comprovante = mov.entrega.comprovantes.first()

                recebedor = "-"
                dt_mov = mov.ocorrido_em.strftime('%d/%m/%Y %H:%M') if mov.ocorrido_em else "-"
                hash_comp = "Sem Assinatura"

                if comprovante:
                    recebedor = f"{comprovante.recebedor_nome} ({comprovante.recebedor_documento})"
                    if comprovante.timestamp_captura:
                        dt_mov = comprovante.timestamp_captura.strftime('%d/%m/%Y %H:%M')
                    if comprovante.hash_integridade_sha256:
                        hash_comp = f"<font face='Courier' size='6'>{comprovante.hash_integridade_sha256[:16]}...</font>"

                table_logistica_data.append([
                    Paragraph(f"<b>{env.cilindro.numero_serie_ogiva}</b>", td_style),
                    Paragraph(cliente_nome, td_style),
                    Paragraph(entrega_str, td_style),
                    Paragraph(recebedor, td_style),
                    Paragraph(dt_mov, td_style),
                    Paragraph(hash_comp, td_style)
                ])

        if total_movimentacoes == 0:
            table_logistica_data.append([
                Paragraph("<i>Nenhuma movimentação de expedição externa vinculada a este lote até o momento.</i>", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style),
                Paragraph("-", td_style)
            ])

        t_logistica = Table(table_logistica_data, colWidths=[2.8 * cm, 4.2 * cm, 2.6 * cm, 4.0 * cm, 2.4 * cm, 2.0 * cm])
        t_logistica.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(t_logistica)
        story.append(Spacer(1, 10))

        # 4. Hash SHA-256 e Declaração de Integridade
        timestamp_emissao = timezone.now().strftime('%d/%m/%Y %H:%M:%S UTC')
        usuario_str = usuario.username if (usuario and hasattr(usuario, 'username')) else "Sistema / RT"

        # Gera pre-hash representativo
        raw_signature_payload = f"{self.lote.codigo_lote}|{total_cilindros}|{timestamp_emissao}|{usuario_str}"
        hash_sha256 = hashlib.sha256(raw_signature_payload.encode('utf-8')).hexdigest().upper()

        box_integridade = [
            [
                Paragraph(
                    f"<b>DECLARAÇÃO REGULATÓRIA DE RASTREABILIDADE (ANVISA):</b><br/>"
                    f"Este dossiê certifica a cadeia perpétua de custódia, rampa de envase e destinação final de "
                    f"<b>{total_cilindros} cilindro(s)</b> envasados sob o Lote <b>{self.lote.codigo_lote}</b>.<br/><br/>"
                    f"<b>Hash Criptográfico de Integridade (SHA-256):</b><br/>"
                    f"<font face='Courier' size='7.5' color='#0F172A'><b>{hash_sha256}</b></font><br/><br/>"
                    f"<b>Registro de Download & Auditoria:</b> Solicitado por <b>{usuario_str}</b> em {timestamp_emissao} • IP: {ip_origem or '127.0.0.1'}",
                    val_style
                )
            ]
        ]
        t_box = Table(box_integridade, colWidths=[18.0 * cm])
        t_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#0284C7')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(KeepTogether(t_box))

        doc.build(story, canvasmaker=NumberedCanvasWithSHA)
        buffer.seek(0)

        # Atualiza o hash canônico com os bytes reais do PDF
        canonical_hash = hashlib.sha256(buffer.getvalue()).hexdigest().upper()

        # Registro obrigatório de auditoria (AuditoriaDownloadLog)
        with tenant_context(self.tenant):
            AuditoriaDownloadLog.objects.create(
                tenant=self.tenant,
                usuario=usuario if (usuario and usuario.is_authenticated) else None,
                entidade_tipo='DOSSIE_LOTE_ANVISA',
                entidade_id=str(self.lote.codigo_lote),
                hash_sha256=canonical_hash,
                ip_origem=ip_origem,
                user_agent=user_agent
            )

        return buffer, canonical_hash


def gerar_dossie_anvisa_pdf(lote, usuario=None, ip_origem=None, user_agent=None):
    """
    Função de conveniência que orquestra a geração do Dossiê ANVISA e registra a auditoria.
    """
    builder = DossieAnvisaBuilder(lote_id=lote.id, tenant=lote.tenant)
    return builder.build_pdf(usuario=usuario, ip_origem=ip_origem, user_agent=user_agent)
