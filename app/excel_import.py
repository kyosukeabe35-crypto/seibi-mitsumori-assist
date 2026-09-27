"""Excel/CSV取り込みの補助処理。

方針:
- 元ファイルは読み取り専用で開き、絶対に書き換えない(uploadsフォルダへ保存した
  コピーのみを扱う)。
- マクロや外部リンクは実行しない(openpyxlはマクロを実行しないread-onlyの
  読み取りのみ使用。.xlsmは非対応として画面に明記する)。
- 完全自動変換はしない。プレビューと列の割り当てを利用者が確認してから登録する。
"""
import csv
import hashlib
import io
from pathlib import Path

import openpyxl
import xlrd

SUPPORTED_EXTS = {".xlsx", ".xls", ".csv"}
UNSUPPORTED_NOTE = (
    "対応形式は .xlsx / .xls / .csv です。.xlsm(マクロ有効)・.xlsb・ODS・"
    "画像スキャンのPDF等は非対応のため、内容を確認しながら手入力で登録してください。"
)

# 案件として登録する際に割り当てられる項目
MAPPABLE_FIELDS = [
    ("skip", "(使用しない)"),
    ("case_date", "日付"),
    ("customer_name", "顧客名"),
    ("maker", "メーカー"),
    ("model", "車種"),
    ("year_or_type", "年式・型式"),
    ("mechanic", "整備士"),
    ("work_description", "作業内容"),
    ("symptom_note", "症状・補足"),
    ("mileage", "走行距離"),
    ("item_name", "明細名(部品/工賃の項目名)"),
    ("item_category", "明細区分(部品/工賃)"),
    ("item_qty", "数量"),
    ("item_unit_price", "単価"),
    ("item_amount", "金額"),
    ("total", "合計金額"),
]


def file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def list_sheets(path: Path):
    ext = path.suffix.lower()
    if ext == ".xlsx":
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        names = wb.sheetnames
        wb.close()
        return names
    if ext == ".xls":
        wb = xlrd.open_workbook(str(path))
        return wb.sheet_names()
    if ext == ".csv":
        return ["(CSV)"]
    raise ValueError(UNSUPPORTED_NOTE)


def read_sheet_rows(path: Path, sheet_name: str, max_rows=200):
    """先頭max_rows行を文字列の二次元リストとして返す(プレビュー・登録共通)。"""
    ext = path.suffix.lower()
    rows = []
    if ext == ".xlsx":
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        ws = wb[sheet_name]
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            rows.append(["" if c is None else str(c) for c in row])
        wb.close()
    elif ext == ".xls":
        wb = xlrd.open_workbook(str(path))
        ws = wb.sheet_by_name(sheet_name)
        for r in range(min(ws.nrows, max_rows)):
            rows.append(["" if c in (None, "") else str(c) for c in ws.row_values(r)])
    elif ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(row)
    else:
        raise ValueError(UNSUPPORTED_NOTE)
    return rows


def to_int(value):
    if value is None:
        return 0
    s = str(value).replace(",", "").replace("¥", "").replace("円", "").strip()
    if s == "":
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def to_float(value):
    if value is None:
        return 0.0
    s = str(value).replace(",", "").strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0
