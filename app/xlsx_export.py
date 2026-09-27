import io

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment


def build_estimate_xlsx(est, items, settings) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "見積書"

    bold = Font(bold=True)
    title_font = Font(bold=True, size=16)

    row = 1
    if est["is_sample"]:
        ws.cell(row=row, column=1, value="【サンプルデータ】実在の取引ではありません").font = Font(color="FF0000")
        row += 2

    ws.cell(row=row, column=1, value="御見積書").font = title_font
    row += 2
    ws.cell(row=row, column=1, value="見積日").font = bold
    ws.cell(row=row, column=2, value=est["estimate_date"] or "")
    ws.cell(row=row, column=3, value="有効期限").font = bold
    ws.cell(row=row, column=4, value=est["valid_until"] or "")
    row += 1
    ws.cell(row=row, column=1, value="お客様名").font = bold
    ws.cell(row=row, column=2, value=est["customer_name"] or "")
    row += 2

    ws.cell(row=row, column=1, value=settings.get("company_name") or "(会社名未設定)")
    row += 1
    if settings.get("company_address"):
        ws.cell(row=row, column=1, value=settings["company_address"])
        row += 1
    contact = " ".join(filter(None, [settings.get("company_tel"), settings.get("company_email")]))
    if contact:
        ws.cell(row=row, column=1, value=contact)
        row += 1
    row += 1

    vehicle = f"{est['maker'] or ''} {est['model'] or ''} {est['year_or_type'] or ''}".strip()
    ws.cell(row=row, column=1, value="車両").font = bold
    ws.cell(row=row, column=2, value=vehicle)
    ws.cell(row=row, column=3, value="走行距離").font = bold
    ws.cell(row=row, column=4, value=est["mileage"] or "")
    row += 1
    ws.cell(row=row, column=1, value="作業内容").font = bold
    ws.cell(row=row, column=2, value=est["work_description"] or "")
    row += 1
    if est["symptom_note"]:
        ws.cell(row=row, column=1, value="症状・補足").font = bold
        ws.cell(row=row, column=2, value=est["symptom_note"])
        row += 1
    row += 1

    header_row = row
    headers = ["区分", "項目", "数量", "単価", "金額"]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=c, value=h)
        cell.font = bold
    row += 1
    items_start = row
    for it in items:
        ws.cell(row=row, column=1, value=it["category"])
        ws.cell(row=row, column=2, value=it["name"])
        ws.cell(row=row, column=3, value=it["qty"])
        ws.cell(row=row, column=4, value=it["unit_price"])
        ws.cell(row=row, column=5, value=it["amount"])
        row += 1
    row += 1

    ws.cell(row=row, column=4, value="小計").font = bold
    ws.cell(row=row, column=5, value=est["subtotal"])
    row += 1
    ws.cell(row=row, column=4, value=f"消費税({est['tax_rate'] * 100:.0f}%)").font = bold
    ws.cell(row=row, column=5, value=est["tax"])
    row += 1
    ws.cell(row=row, column=4, value="合計").font = bold
    ws.cell(row=row, column=5, value=est["total"]).font = bold
    row += 2

    if est["notes"]:
        ws.cell(row=row, column=1, value="備考").font = bold
        ws.cell(row=row, column=2, value=est["notes"])
        row += 1

    for col, width in zip("ABCDE", (12, 36, 10, 14, 14)):
        ws.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
