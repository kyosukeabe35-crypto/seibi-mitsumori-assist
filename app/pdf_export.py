import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# reportlabに同梱のCIDフォントで日本語を描画(追加フォントファイル不要)
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))


def build_estimate_pdf(est, items, settings) -> io.BytesIO:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)
    styles = getSampleStyleSheet()
    jp = ParagraphStyle("jp", fontName="HeiseiKakuGo-W5", fontSize=10, leading=14)
    jp_title = ParagraphStyle("jp_title", fontName="HeiseiKakuGo-W5", fontSize=18, leading=22)
    jp_small = ParagraphStyle("jp_small", fontName="HeiseiKakuGo-W5", fontSize=8, leading=11,
                               textColor=colors.grey)

    flow = []
    if est["is_sample"]:
        flow.append(Paragraph("【サンプルデータ】実在の取引ではありません", jp_small))
    flow.append(Paragraph("御見積書", jp_title))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph(f"見積日: {est['estimate_date'] or ''}　　有効期限: {est['valid_until'] or ''}", jp))
    flow.append(Paragraph(f"お客様名: {est['customer_name'] or ''} 様", jp))
    flow.append(Spacer(1, 8))

    company = settings.get("company_name") or "(会社名未設定)"
    flow.append(Paragraph(company, jp))
    if settings.get("company_address"):
        flow.append(Paragraph(settings["company_address"], jp))
    contact = " ".join(filter(None, [settings.get("company_tel"), settings.get("company_email")]))
    if contact:
        flow.append(Paragraph(contact, jp))
    flow.append(Spacer(1, 10))

    vehicle = f"{est['maker'] or ''} {est['model'] or ''} {est['year_or_type'] or ''}".strip()
    flow.append(Paragraph(f"車両: {vehicle}　走行距離: {est['mileage'] or ''}", jp))
    flow.append(Paragraph(f"作業内容: {est['work_description'] or ''}", jp))
    if est["symptom_note"]:
        flow.append(Paragraph(f"症状・補足: {est['symptom_note']}", jp))
    flow.append(Spacer(1, 10))

    data = [["区分", "項目", "数量", "単価", "金額"]]
    for it in items:
        data.append([it["category"], it["name"], f"{it['qty']:g}", f"¥{it['unit_price']:,}", f"¥{it['amount']:,}"])
    table = Table(data, colWidths=[22 * mm, 70 * mm, 18 * mm, 30 * mm, 30 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "HeiseiKakuGo-W5"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
    ]))
    flow.append(table)
    flow.append(Spacer(1, 8))

    totals = [
        ["小計", f"¥{est['subtotal']:,}"],
        [f"消費税({est['tax_rate'] * 100:.0f}%)", f"¥{est['tax']:,}"],
        ["合計", f"¥{est['total']:,}"],
    ]
    ttable = Table(totals, colWidths=[130 * mm, 40 * mm])
    ttable.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "HeiseiKakuGo-W5"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ("FONTSIZE", (0, -1), (-1, -1), 12),
    ]))
    flow.append(ttable)

    if est["notes"]:
        flow.append(Spacer(1, 10))
        flow.append(Paragraph(f"備考: {est['notes']}", jp))

    flow.append(Spacer(1, 14))
    flow.append(Paragraph(
        "※本見積は参考事例・入力内容をもとに作成した見積です。最終的な金額は現車確認の上で確定します。",
        jp_small,
    ))

    doc.build(flow)
    buf.seek(0)
    return buf
