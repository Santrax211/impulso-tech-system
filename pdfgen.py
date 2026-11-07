"""Generación del PDF de cotización con ReportLab + protección con pikepdf."""
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

import pikepdf
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

NAVY = colors.HexColor("#0F4C92")
BLUE = colors.HexColor("#1E7FE8")
INK = colors.HexColor("#1F4155")
STEEL = colors.HexColor("#9AA0A6")
PAPER = colors.HexColor("#F3F6F9")
LINE = colors.HexColor("#DCE3EA")
TEXT = colors.HexColor("#1B2B36")
MUTED = colors.HexColor("#5B6975")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=TEXT)
    base.update(kw)
    return ParagraphStyle(name, **base)


ST = {
    "body": S("body"),
    "small": S("small", fontSize=8.5, leading=12, textColor=MUTED),
    "biz": S("biz", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=NAVY),
    "tag": S("tag", fontSize=8.5, leading=11, textColor=STEEL),
    "title": S("title", fontName="Helvetica-Bold", fontSize=21, leading=24, textColor=NAVY, alignment=TA_RIGHT),
    "num": S("num", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=INK, alignment=TA_RIGHT),
    "meta": S("meta", fontSize=9, leading=13, textColor=MUTED, alignment=TA_RIGHT),
    "label": S("label", fontSize=7.5, leading=10, textColor=MUTED),
    "value": S("value", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=INK),
    "th": S("th", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.white),
    "thr": S("thr", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.white, alignment=TA_RIGHT),
    "cell": S("cell", fontSize=9.5, leading=13),
    "cellr": S("cellr", fontSize=9.5, leading=13, alignment=TA_RIGHT),
    "tl": S("tl", fontSize=9.5, leading=13, textColor=MUTED),
    "tr": S("tr", fontSize=9.5, leading=13, alignment=TA_RIGHT),
    "tt": S("tt", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=colors.white),
    "ttr": S("ttr", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=colors.white, alignment=TA_RIGHT),
    "h2": S("h2", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=NAVY, spaceAfter=3),
}


def P(text, style="body"):
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), ST[style])


def money(value):
    return f"{Decimal(value):,.2f}"


def qty_fmt(value):
    d = Decimal(value).normalize()
    return format(d, "f")


def fmt_date(d):
    return d.strftime("%d/%m/%Y")


def build_raw(quote, settings, logo_path):
    buf = BytesIO()
    biz = settings.get("business_name") or "Impulso Tech"
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm, bottomMargin=20 * mm,
        title=f"Cotización {quote['number']}", author=biz, subject=f"Cotización para {quote['client_name']}",
        creator="Impulso Tech · Cotizador",
    )
    issue = date.fromisoformat(quote["issue_date"])
    until = issue + timedelta(days=int(quote["valid_days"]))
    story = []

    # --- Encabezado
    contact = [settings.get(k) for k in ("ruc", "phone", "email", "web", "address")]
    lines = []
    if settings.get("ruc"):
        lines.append(f"RUC {settings['ruc']}")
    lines += [v for v in contact[1:] if v]
    info = [P(biz, "biz")]
    if settings.get("tagline"):
        info.append(P(settings["tagline"], "tag"))
    info.append(Spacer(1, 3))
    info += [P(l, "small") for l in lines]
    right = [P("COTIZACIÓN", "title"), P(quote["number"], "num"), Spacer(1, 4),
             P(f"Fecha: {fmt_date(issue)}", "meta"), P(f"Válida hasta: {fmt_date(until)}", "meta")]
    head = Table([[Image(logo_path, 27 * mm, 27 * mm), info, right]],
                 colWidths=[32 * mm, 70 * mm, CONTENT_W - 102 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 5 * mm), HRFlowable(width="100%", thickness=2.2, color=BLUE, spaceAfter=6 * mm)]

    # --- Cliente
    cols = [[P("Cliente", "label"), P(quote["client_name"], "value")]]
    doc_no = quote.get("client_doc")
    if doc_no:
        cols.append([P("DNI" if len(doc_no) == 8 else "RUC", "label"), P(doc_no, "value")])
    if quote.get("client_phone"):
        cols.append([P("Teléfono", "label"), P(quote["client_phone"], "value")])
    extra = len(cols) - 1
    first_w = CONTENT_W - extra * 42 * mm
    client = Table([cols], colWidths=[first_w] + [42 * mm] * extra)
    client.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER), ("LINEBEFORE", (0, 0), (0, 0), 3, BLUE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [client, Spacer(1, 7 * mm)]

    # --- Ítems
    rows = [[P("#", "th"), P("Descripción", "th"), P("Cant.", "thr"), P("P. unit. (S/)", "thr"), P("Importe (S/)", "thr")]]
    for n, it in enumerate(quote["items"], 1):
        rows.append([P(n, "cell"), P(it["desc"], "cell"), P(qty_fmt(it["qty"]), "cellr"),
                     P(money(it["price"]), "cellr"), P(money(it["amount"]), "cellr")])
    tbl = Table(rows, colWidths=[9 * mm, CONTENT_W - 9 * mm - 18 * mm - 28 * mm - 28 * mm, 18 * mm, 28 * mm, 28 * mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 1), (-1, -1), 0.6, LINE),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 4 * mm))

    # --- Totales
    sub, disc, base, igv, total = (Decimal(quote[k]) for k in ("subtotal", "discount_amount", "base", "igv", "total"))
    mode = quote["igv_mode"]
    trs = [[P("Subtotal", "tl"), P(f"S/ {money(sub)}", "tr")]]
    if disc > 0:
        label = f"Descuento ({qty_fmt(quote['discount_value'])}%)" if quote["discount_type"] == "percent" else "Descuento"
        trs.append([P(label, "tl"), P(f"- S/ {money(disc)}", "tr")])
    if mode != "none":
        if base != sub:
            trs.append([P("Base imponible", "tl"), P(f"S/ {money(base)}", "tr")])
        trs.append([P("IGV (18%)", "tl"), P(f"S/ {money(igv)}", "tr")])
    trs.append([P("TOTAL", "tt"), P(f"S/ {money(total)}", "ttr")])
    inner = Table(trs, colWidths=[38 * mm, 42 * mm])
    inner.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.6, LINE),
        ("BACKGROUND", (0, -1), (-1, -1), NAVY), ("TOPPADDING", (0, -1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7), ("LEFTPADDING", (0, -1), (-1, -1), 8),
        ("RIGHTPADDING", (0, -1), (-1, -1), 8),
    ]))
    note = {"add": "Los precios no incluyen IGV.", "included": "Los precios incluyen IGV (18%)."}.get(mode, "")
    right_col = [inner] + ([Spacer(1, 2), P(note, "small")] if note else [])
    wrap = Table([["", right_col]], colWidths=[CONTENT_W - 80 * mm, 80 * mm])
    wrap.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([wrap]))

    # --- Condiciones y pago
    terms = [P("Condiciones comerciales", "h2"),
             P(f"Esta cotización es válida por {quote['valid_days']} días (hasta el {fmt_date(until)}).")]
    if quote.get("conditions"):
        terms += [Spacer(1, 2), P(quote["conditions"])]
    if settings.get("payment_info"):
        terms += [Spacer(1, 8), P("Datos de pago", "h2"), P(settings["payment_info"])]
    story += [Spacer(1, 9 * mm), KeepTogether(terms), Spacer(1, 8 * mm),
              P(f"Gracias por confiar en {biz}.", "small")]

    footer_parts = [v for v in (biz, settings.get("phone"), settings.get("email"), settings.get("web")) if v]
    footer_text = "  |  ".join(footer_parts)

    def decorate(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 9.5 * mm, footer_text[:110])
        canvas.drawRightString(PAGE_W - MARGIN, 9.5 * mm, f"{quote['number']}  |  Página {canvas.getPageNumber()}")
        canvas.setFillColor(BLUE)
        canvas.rect(0, PAGE_H - 3 * mm, PAGE_W, 3 * mm, stroke=0, fill=1)
        canvas.restoreState()

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()


def protect(raw, owner_password):
    """Cifra con AES-256: abre sin clave, pero bloquea edición, copia y anotaciones."""
    src = pikepdf.open(BytesIO(raw))
    out = BytesIO()
    src.save(out, encryption=pikepdf.Encryption(
        owner=owner_password, user="", R=6,
        allow=pikepdf.Permissions(
            accessibility=True, extract=False, modify_annotation=False, modify_assembly=False,
            modify_form=False, modify_other=False, print_lowres=True, print_highres=True),
    ))
    src.close()
    return out.getvalue()


def build_pdf(quote, settings, logo_path, owner_password):
    return protect(build_raw(quote, settings, logo_path), owner_password)
