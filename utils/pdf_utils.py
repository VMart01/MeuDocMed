"""
Geração de PDF para exportação do histórico de acessos.
Usa fpdf2 com suporte completo a Unicode (UTF-8).
"""
from fpdf import FPDF
from datetime import datetime


class HistoryPDF(FPDF):
    def __init__(self, patient_name: str, patient_cpf: str):
        super().__init__()
        self.patient_name = patient_name
        self.patient_cpf = patient_cpf
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        # Título
        self.set_font('Helvetica', 'B', 16)
        self.set_fill_color(21, 101, 192)
        self.set_text_color(255, 255, 255)
        self.cell(0, 12, 'MeuDocMed - Histórico de Acessos', border=0, ln=True,
                  align='C', fill=True)

        self.set_text_color(0, 0, 0)
        self.set_font('Helvetica', '', 10)
        self.ln(4)
        self.cell(0, 6, f'Paciente: {self.patient_name}', ln=True)
        self.cell(0, 6, f'CPF: {self.patient_cpf}', ln=True)
        self.cell(0, 6,
                  f'Exportado em: {datetime.now().strftime("%d/%m/%Y às %H:%M")}',
                  ln=True)
        self.ln(4)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Página {self.page_no()}', align='C')

    def add_log_table(self, logs):
        """Adiciona a tabela com os registros de log."""
        # Cabeçalho da tabela
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(240, 240, 240)
        self.set_draw_color(200, 200, 200)

        col_widths = [35, 35, 60, 30, 30]
        headers = ['Data/Hora', 'Evento', 'Descrição', 'IP', 'Realizado por']

        for i, h in enumerate(headers):
            self.cell(col_widths[i], 8, h, border=1, fill=True, align='C')
        self.ln()

        # Linhas de dados
        self.set_font('Helvetica', '', 8)
        fill = False

        for log in logs:
            if self.get_y() > 270:
                self.add_page()

            self.set_fill_color(248, 248, 248) if fill else self.set_fill_color(255, 255, 255)

            dt = log.created_at.strftime('%d/%m/%Y\n%H:%M') if log.created_at else ''
            action = log.action_display[:20] if log.action_display else ''
            desc = (log.description or '')[:50]
            ip = (log.ip_address or '')[:15]

            if log.performed_by == 'professional' and log.professional_ref:
                by = log.professional_ref.name[:15]
            else:
                by = 'Paciente'

            row_h = 6

            # Data/Hora
            x = self.get_x()
            y = self.get_y()
            self.multi_cell(col_widths[0], row_h,
                            log.created_at.strftime('%d/%m/%Y %H:%M') if log.created_at else '',
                            border=1, fill=fill)
            self.set_xy(x + col_widths[0], y)

            # Evento
            self.multi_cell(col_widths[1], row_h, action, border=1, fill=fill)
            self.set_xy(x + col_widths[0] + col_widths[1], y)

            # Descrição
            self.multi_cell(col_widths[2], row_h, desc, border=1, fill=fill)
            self.set_xy(x + col_widths[0] + col_widths[1] + col_widths[2], y)

            # IP
            self.multi_cell(col_widths[3], row_h, ip, border=1, fill=fill)
            self.set_xy(x + col_widths[0] + col_widths[1] + col_widths[2] + col_widths[3], y)

            # Realizado por
            self.multi_cell(col_widths[4], row_h, by, border=1, fill=fill)

            fill = not fill


def generate_history_pdf(patient, logs) -> bytes:
    """
    Gera o PDF do histórico e retorna os bytes.
    """
    pdf = HistoryPDF(patient.name, patient.cpf_formatted)
    pdf.add_page()
    pdf.add_log_table(logs)

    return pdf.output()
