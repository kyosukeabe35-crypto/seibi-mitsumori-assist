import io
import json
import os
import shutil
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for, flash, send_file, abort, g
)

from db import init_db, ensure_initialized, get_conn, get_settings, set_settings
from matching import find_reference_cases
from excel_import import (
    SUPPORTED_EXTS, UNSUPPORTED_NOTE, MAPPABLE_FIELDS,
    file_checksum, list_sheets, read_sheet_rows, to_int, to_float,
)

BASE_DIR = Path(__file__).resolve().parent.parent
IS_VERCEL = bool(os.environ.get("VERCEL"))
UPLOAD_DIR = Path("/tmp/uploads") if IS_VERCEL else (BASE_DIR / "uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-only-not-secret")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB

if IS_VERCEL:
    # サーバーレス環境: DBが無ければ初期化し、デモ用にサンプルデータを投入する。
    # /tmp は実行インスタンスの寿命分しか保持されないため、あくまで提出・閲覧用の
    # 一時公開を想定している(実運用のデータ保存はローカル版を利用する)。
    if ensure_initialized():
        import seed_demo
        seed_demo.run()


def db():
    if "conn" not in g:
        g.conn = get_conn()
    return g.conn


@app.teardown_appcontext
def close_conn(exc):
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


@app.context_processor
def inject_globals():
    return {"today": date.today().isoformat()}


# ---------------------------------------------------------------- helpers --

def recalc_estimate(estimate_id):
    conn = db()
    items = conn.execute(
        "SELECT * FROM estimate_items WHERE estimate_id=? ORDER BY sort_order, id",
        (estimate_id,),
    ).fetchall()
    subtotal = sum(i["amount"] for i in items)
    est = conn.execute("SELECT tax_rate FROM estimates WHERE id=?", (estimate_id,)).fetchone()
    tax_rate = est["tax_rate"] if est else 0.10
    tax = round(subtotal * tax_rate)
    total = subtotal + tax
    conn.execute(
        "UPDATE estimates SET subtotal=?, tax=?, total=?, updated_at=datetime('now','localtime') WHERE id=?",
        (subtotal, tax, total, estimate_id),
    )
    conn.commit()


def get_estimate_or_404(estimate_id):
    conn = db()
    est = conn.execute("SELECT * FROM estimates WHERE id=?", (estimate_id,)).fetchone()
    if est is None:
        abort(404)
    return est


# --------------------------------------------------------------- estimates --

@app.route("/")
def index():
    return redirect(url_for("estimates_new"))


@app.route("/estimates/new", methods=["GET", "POST"])
def estimates_new():
    if request.method == "POST":
        conn = db()
        settings = get_settings()
        validity_days = int(settings.get("default_validity_days") or 30)
        cur = conn.execute(
            """INSERT INTO estimates
               (customer_name, maker, model, year_or_type, mechanic, work_description,
                symptom_note, mileage, estimate_date, valid_until, tax_rate, basis_note, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request.form.get("customer_name", "").strip(),
                request.form.get("maker", "").strip(),
                request.form.get("model", "").strip(),
                request.form.get("year_or_type", "").strip(),
                request.form.get("mechanic", "").strip(),
                request.form.get("work_description", "").strip(),
                request.form.get("symptom_note", "").strip(),
                request.form.get("mileage", "").strip(),
                date.today().isoformat(),
                (date.today() + timedelta(days=validity_days)).isoformat(),
                float(settings.get("tax_rate") or 0.10),
                "手入力(参考事例未採用)",
                "draft",
            ),
        )
        conn.commit()
        return redirect(url_for("estimate_detail", estimate_id=cur.lastrowid))
    mechanics = db().execute(
        "SELECT DISTINCT mechanic FROM cases WHERE mechanic IS NOT NULL AND mechanic != '' "
        "UNION SELECT DISTINCT mechanic FROM estimates WHERE mechanic IS NOT NULL AND mechanic != ''"
    ).fetchall()
    return render_template("estimate_new.html", mechanics=[m[0] for m in mechanics])


@app.route("/estimates/<int:estimate_id>")
def estimate_detail(estimate_id):
    conn = db()
    est = get_estimate_or_404(estimate_id)
    items = conn.execute(
        "SELECT * FROM estimate_items WHERE estimate_id=? ORDER BY sort_order, id",
        (estimate_id,),
    ).fetchall()
    query = {
        "maker": est["maker"], "model": est["model"],
        "mechanic": est["mechanic"], "work_description": est["work_description"],
    }
    candidates = find_reference_cases(conn, query)
    adopted_case_ids = {
        r["case_id"] for r in conn.execute(
            "SELECT case_id FROM estimate_references WHERE estimate_id=?", (estimate_id,)
        ).fetchall()
    }
    settings = get_settings()
    return render_template(
        "estimate_detail.html", est=est, items=items, candidates=candidates,
        adopted_case_ids=adopted_case_ids, settings=settings,
    )


@app.route("/estimates/<int:estimate_id>/update_case", methods=["POST"])
def estimate_update_case(estimate_id):
    get_estimate_or_404(estimate_id)
    conn = db()
    conn.execute(
        """UPDATE estimates SET customer_name=?, maker=?, model=?, year_or_type=?,
           mechanic=?, work_description=?, symptom_note=?, mileage=?,
           updated_at=datetime('now','localtime') WHERE id=?""",
        (
            request.form.get("customer_name", "").strip(),
            request.form.get("maker", "").strip(),
            request.form.get("model", "").strip(),
            request.form.get("year_or_type", "").strip(),
            request.form.get("mechanic", "").strip(),
            request.form.get("work_description", "").strip(),
            request.form.get("symptom_note", "").strip(),
            request.form.get("mileage", "").strip(),
            estimate_id,
        ),
    )
    conn.commit()
    flash("案件情報を更新しました。参考事例を再検索しました。", "success")
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/update_meta", methods=["POST"])
def estimate_update_meta(estimate_id):
    get_estimate_or_404(estimate_id)
    conn = db()
    tax_rate = to_float(request.form.get("tax_rate", "0.10"))
    conn.execute(
        """UPDATE estimates SET estimate_date=?, valid_until=?, notes=?, tax_rate=?,
           updated_at=datetime('now','localtime') WHERE id=?""",
        (
            request.form.get("estimate_date", "").strip(),
            request.form.get("valid_until", "").strip(),
            request.form.get("notes", "").strip(),
            tax_rate,
            estimate_id,
        ),
    )
    conn.commit()
    recalc_estimate(estimate_id)
    flash("見積条件を更新しました。", "success")
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/adopt_case/<int:case_id>", methods=["POST"])
def estimate_adopt_case(estimate_id, case_id):
    conn = db()
    get_estimate_or_404(estimate_id)
    case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if case is None:
        abort(404)
    case_items = conn.execute(
        "SELECT * FROM case_items WHERE case_id=? ORDER BY id", (case_id,)
    ).fetchall()

    replace = request.form.get("mode") == "replace"
    if replace:
        conn.execute("DELETE FROM estimate_items WHERE estimate_id=?", (estimate_id,))

    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS m FROM estimate_items WHERE estimate_id=?",
        (estimate_id,),
    ).fetchone()["m"]

    for i, ci in enumerate(case_items):
        conn.execute(
            """INSERT INTO estimate_items (estimate_id, category, name, qty, unit_price, amount, sort_order)
               VALUES (?,?,?,?,?,?,?)""",
            (estimate_id, ci["category"], ci["name"], ci["qty"], ci["unit_price"], ci["amount"],
             max_order + 1 + i),
        )

    reasons = request.form.get("reasons", "")
    conn.execute(
        "INSERT INTO estimate_references (estimate_id, case_id, match_note) VALUES (?,?,?)",
        (estimate_id, case_id, reasons),
    )
    label = f"事例#{case_id}（{case['maker'] or ''} {case['model'] or ''} / {case['case_date'] or ''}）を採用"
    if reasons:
        label += f"：一致条件={reasons}"
    conn.execute(
        "UPDATE estimates SET basis_note = COALESCE(basis_note || char(10), '') || ? WHERE id=?",
        (label, estimate_id),
    )
    conn.commit()
    recalc_estimate(estimate_id)
    flash("参考事例の明細を見積に反映しました。金額は編集できます。", "success")
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/items", methods=["POST"])
def estimate_update_items(estimate_id):
    get_estimate_or_404(estimate_id)
    conn = db()
    conn.execute("DELETE FROM estimate_items WHERE estimate_id=?", (estimate_id,))

    names = request.form.getlist("item_name")
    categories = request.form.getlist("item_category")
    qtys = request.form.getlist("item_qty")
    prices = request.form.getlist("item_unit_price")

    order = 0
    for name, cat, qty, price in zip(names, categories, qtys, prices):
        name = (name or "").strip()
        if not name:
            continue
        qty_f = to_float(qty) or 1
        price_i = to_int(price)
        amount = round(qty_f * price_i)
        conn.execute(
            """INSERT INTO estimate_items (estimate_id, category, name, qty, unit_price, amount, sort_order)
               VALUES (?,?,?,?,?,?,?)""",
            (estimate_id, cat or "工賃", name, qty_f, price_i, amount, order),
        )
        order += 1
    conn.execute(
        "UPDATE estimates SET basis_note = COALESCE(basis_note || char(10), '') || ? WHERE id=?",
        ("明細を手動で編集", estimate_id),
    )
    conn.commit()
    recalc_estimate(estimate_id)
    flash("明細を更新し、金額を再計算しました。", "success")
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/finalize", methods=["POST"])
def estimate_finalize(estimate_id):
    get_estimate_or_404(estimate_id)
    conn = db()
    conn.execute("UPDATE estimates SET status='created' WHERE id=?", (estimate_id,))
    conn.commit()
    flash("見積書を作成済みにしました。", "success")
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


@app.route("/estimates/<int:estimate_id>/print")
def estimate_print(estimate_id):
    conn = db()
    est = get_estimate_or_404(estimate_id)
    items = conn.execute(
        "SELECT * FROM estimate_items WHERE estimate_id=? ORDER BY sort_order, id",
        (estimate_id,),
    ).fetchall()
    settings = get_settings()
    return render_template("estimate_print.html", est=est, items=items, settings=settings)


@app.route("/estimates/<int:estimate_id>/pdf")
def estimate_pdf(estimate_id):
    from pdf_export import build_estimate_pdf
    conn = db()
    est = get_estimate_or_404(estimate_id)
    items = conn.execute(
        "SELECT * FROM estimate_items WHERE estimate_id=? ORDER BY sort_order, id",
        (estimate_id,),
    ).fetchall()
    settings = get_settings()
    buf = build_estimate_pdf(est, items, settings)
    return send_file(
        buf, mimetype="application/pdf", as_attachment=True,
        download_name=f"estimate_{estimate_id}.pdf",
    )


@app.route("/estimates/<int:estimate_id>/xlsx")
def estimate_xlsx(estimate_id):
    from xlsx_export import build_estimate_xlsx
    conn = db()
    est = get_estimate_or_404(estimate_id)
    items = conn.execute(
        "SELECT * FROM estimate_items WHERE estimate_id=? ORDER BY sort_order, id",
        (estimate_id,),
    ).fetchall()
    settings = get_settings()
    buf = build_estimate_xlsx(est, items, settings)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=f"estimate_{estimate_id}.xlsx",
    )


# -------------------------------------------------------------------- cases --

@app.route("/cases")
def cases_list():
    conn = db()
    q_maker = request.args.get("maker", "").strip()
    q_model = request.args.get("model", "").strip()
    q_mechanic = request.args.get("mechanic", "").strip()
    q_work = request.args.get("work", "").strip()

    sql = "SELECT * FROM cases WHERE 1=1"
    params = []
    for col, val in (("maker", q_maker), ("model", q_model), ("mechanic", q_mechanic), ("work_description", q_work)):
        if val:
            sql += f" AND {col} LIKE ?"
            params.append(f"%{val}%")
    sql += " ORDER BY case_date DESC, id DESC LIMIT 200"
    rows = conn.execute(sql, params).fetchall()
    return render_template("cases_list.html", rows=rows, q={
        "maker": q_maker, "model": q_model, "mechanic": q_mechanic, "work": q_work,
    })


@app.route("/cases/new", methods=["GET", "POST"])
def cases_new():
    """明細を読み取れない帳票向け: 基本情報+合計金額のみで手入力登録"""
    if request.method == "POST":
        conn = db()
        total = to_int(request.form.get("total"))
        cur = conn.execute(
            """INSERT INTO cases (is_sample, customer_name, maker, model, year_or_type, mechanic,
               work_description, symptom_note, mileage, case_date, subtotal, tax, total, source_type)
               VALUES (0,?,?,?,?,?,?,?,?,?,?,?,?,'manual')""",
            (
                request.form.get("customer_name", "").strip(),
                request.form.get("maker", "").strip(),
                request.form.get("model", "").strip(),
                request.form.get("year_or_type", "").strip(),
                request.form.get("mechanic", "").strip(),
                request.form.get("work_description", "").strip(),
                request.form.get("symptom_note", "").strip(),
                request.form.get("mileage", "").strip(),
                request.form.get("case_date", "").strip(),
                total, 0, total,
            ),
        )
        case_id = cur.lastrowid
        conn.execute(
            "INSERT INTO case_items (case_id, category, name, qty, unit_price, amount) VALUES (?,?,?,?,?,?)",
            (case_id, "その他", "合計金額のみ登録(明細不明)", 1, total, total),
        )
        conn.commit()
        flash("案件を登録しました(合計金額のみ・明細は手入力の1件として記録)。", "success")
        return redirect(url_for("case_detail", case_id=case_id))
    return render_template("case_new.html")


@app.route("/cases/<int:case_id>")
def case_detail(case_id):
    conn = db()
    case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if case is None:
        abort(404)
    items = conn.execute("SELECT * FROM case_items WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
    source_file = None
    if case["source_file_id"]:
        source_file = conn.execute("SELECT * FROM import_files WHERE id=?", (case["source_file_id"],)).fetchone()
    return render_template("case_detail.html", case=case, items=items, source_file=source_file)


# ------------------------------------------------------------------- import --

@app.route("/import", methods=["GET"])
def import_home():
    conn = db()
    files = conn.execute("SELECT * FROM import_files ORDER BY id DESC LIMIT 50").fetchall()
    return render_template("import_home.html", files=files, unsupported_note=UNSUPPORTED_NOTE)


@app.route("/import/upload", methods=["POST"])
def import_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        flash("ファイルが選択されていません。", "error")
        return redirect(url_for("import_home"))
    ext = Path(f.filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        flash(f"「{f.filename}」は非対応の形式です。{UNSUPPORTED_NOTE}", "error")
        return redirect(url_for("import_home"))

    token = uuid.uuid4().hex[:12]
    stored_name = f"{token}{ext}"
    stored_path = UPLOAD_DIR / stored_name
    f.save(stored_path)  # 元ファイルはユーザーの端末に残ったまま。ここでは保存された「コピー」だけを扱う

    checksum = file_checksum(stored_path)
    conn = db()
    dup = conn.execute("SELECT * FROM import_files WHERE checksum=?", (checksum,)).fetchone()
    dup_warning = None
    if dup:
        dup_warning = f"同一内容のファイルが既に取り込まれています(取込ID {dup['id']}, {dup['imported_at']})。重複登録に注意してください。"

    try:
        sheets = list_sheets(stored_path)
    except Exception as e:
        flash(f"読み込みに失敗しました: {e}", "error")
        stored_path.unlink(missing_ok=True)
        return redirect(url_for("import_home"))

    return render_template(
        "import_sheet_select.html",
        original_name=f.filename, stored_name=stored_name, sheets=sheets,
        checksum=checksum, dup_warning=dup_warning,
    )


@app.route("/import/preview", methods=["POST"])
def import_preview():
    stored_name = request.form["stored_name"]
    original_name = request.form["original_name"]
    checksum = request.form["checksum"]
    sheet_name = request.form["sheet_name"]
    path = UPLOAD_DIR / stored_name
    if not path.exists():
        flash("アップロードされたファイルが見つかりません。もう一度アップロードしてください。", "error")
        return redirect(url_for("import_home"))

    rows = read_sheet_rows(path, sheet_name, max_rows=200)
    header_row_index = 0
    preview_rows = rows[:30]
    ncols = max((len(r) for r in rows), default=0)

    return render_template(
        "import_mapping.html",
        original_name=original_name, stored_name=stored_name, checksum=checksum,
        sheet_name=sheet_name, rows=preview_rows, ncols=ncols,
        fields=MAPPABLE_FIELDS, header_row_index=header_row_index,
        total_rows=len(rows),
    )


@app.route("/import/register", methods=["POST"])
def import_register():
    stored_name = request.form["stored_name"]
    original_name = request.form["original_name"]
    checksum = request.form["checksum"]
    sheet_name = request.form["sheet_name"]
    header_row_index = int(request.form.get("header_row_index", 0))
    force = request.form.get("force") == "1"

    path = UPLOAD_DIR / stored_name
    if not path.exists():
        flash("アップロードされたファイルが見つかりません。もう一度アップロードしてください。", "error")
        return redirect(url_for("import_home"))

    conn = db()
    dup = conn.execute("SELECT * FROM import_files WHERE checksum=?", (checksum,)).fetchone()
    if dup and not force:
        flash("重複と判定されたため登録を中止しました。続行する場合はチェックを入れて再送信してください。", "error")
        return redirect(url_for("import_home"))

    col_map = {}
    for key, _ in MAPPABLE_FIELDS:
        idx = request.form.get(f"col_{key}")
        if idx not in (None, "", "none"):
            col_map[key] = int(idx)

    rows = read_sheet_rows(path, sheet_name, max_rows=5000)
    data_rows = rows[header_row_index + 1:]

    def cell(row, key):
        idx = col_map.get(key)
        if idx is None or idx >= len(row):
            return ""
        return row[idx]

    cur = conn.execute(
        "INSERT INTO import_files (filename, sheet_name, checksum, row_count, note) VALUES (?,?,?,?,?)",
        (original_name, sheet_name, checksum, len(data_rows), None),
    )
    file_id = cur.lastrowid

    registered = 0
    for i, row in enumerate(data_rows):
        if not any(str(c).strip() for c in row):
            continue
        maker = cell(row, "maker")
        model = cell(row, "model")
        work = cell(row, "work_description")
        if not (maker or model or work):
            continue  # 空行・注記行はスキップ

        item_name = cell(row, "item_name") or "取込明細"
        item_category = cell(row, "item_category") or "その他"
        item_qty = to_float(cell(row, "item_qty")) or 1
        item_unit_price = to_int(cell(row, "item_unit_price"))
        item_amount = to_int(cell(row, "item_amount"))
        total = to_int(cell(row, "total"))
        if item_amount == 0 and item_unit_price:
            item_amount = round(item_qty * item_unit_price)
        if total == 0:
            total = item_amount

        case_cur = conn.execute(
            """INSERT INTO cases (is_sample, customer_name, maker, model, year_or_type, mechanic,
               work_description, symptom_note, mileage, case_date, subtotal, tax, total,
               source_type, source_file_id, source_sheet_row)
               VALUES (0,?,?,?,?,?,?,?,?,?,?,?,?, 'imported', ?, ?)""",
            (
                cell(row, "customer_name"), maker, model, cell(row, "year_or_type"),
                cell(row, "mechanic"), work, cell(row, "symptom_note"), cell(row, "mileage"),
                cell(row, "case_date"), total, 0, total, file_id,
                f"{sheet_name}!row{header_row_index + 2 + i}",
            ),
        )
        case_id = case_cur.lastrowid
        conn.execute(
            "INSERT INTO case_items (case_id, category, name, qty, unit_price, amount) VALUES (?,?,?,?,?,?)",
            (case_id, item_category, item_name, item_qty, item_unit_price or (item_amount and round(item_amount / item_qty)) or 0, item_amount),
        )
        registered += 1

    conn.commit()
    flash(f"{registered}件の案件を取り込みました(元ファイルは変更していません)。", "success")
    return redirect(url_for("import_home"))


# ------------------------------------------------------------- consultations --

@app.route("/consultations")
def consultations_list():
    conn = db()
    rows = conn.execute("SELECT * FROM consultations ORDER BY id DESC").fetchall()
    return render_template("consultations_list.html", rows=rows)


@app.route("/consultations/new", methods=["GET", "POST"])
def consultations_new():
    estimate_id = request.values.get("estimate_id", type=int)
    prefill = None
    if estimate_id:
        prefill = get_estimate_or_404(estimate_id)

    if request.method == "POST":
        conn = db()
        cur = conn.execute(
            """INSERT INTO consultations (maker, model, year_or_type, mechanic, work_description,
               symptom_note, mileage, rough_estimate, memo_text, status, linked_estimate_id)
               VALUES (?,?,?,?,?,?,?,?,?, 'consulting', ?)""",
            (
                request.form.get("maker", "").strip(),
                request.form.get("model", "").strip(),
                request.form.get("year_or_type", "").strip(),
                request.form.get("mechanic", "").strip(),
                request.form.get("work_description", "").strip(),
                request.form.get("symptom_note", "").strip(),
                request.form.get("mileage", "").strip(),
                to_int(request.form.get("rough_estimate")),
                request.form.get("memo_text", "").strip(),
                estimate_id,
            ),
        )
        conn.commit()
        flash("相談メモを作成しました。内容を確認のうえ、ご自身で整備士へ送付してください。", "success")
        return redirect(url_for("consultation_detail", consultation_id=cur.lastrowid))

    memo_text = ""
    if prefill:
        memo_text = (
            f"【整備見積のご相談】\n"
            f"車両: {prefill['maker']} {prefill['model']} {prefill['year_or_type']}\n"
            f"走行距離: {prefill['mileage']}\n"
            f"作業内容: {prefill['work_description']}\n"
            f"症状・補足: {prefill['symptom_note']}\n"
            f"参考事例が見つからなかったため、概算金額のご教示をお願いします。"
        )
    return render_template("consultation_new.html", prefill=prefill, memo_text=memo_text)


@app.route("/consultations/<int:consultation_id>")
def consultation_detail(consultation_id):
    conn = db()
    c = conn.execute("SELECT * FROM consultations WHERE id=?", (consultation_id,)).fetchone()
    if c is None:
        abort(404)
    return render_template("consultation_detail.html", c=c)


@app.route("/consultations/<int:consultation_id>/answer", methods=["POST"])
def consultation_answer(consultation_id):
    conn = db()
    conn.execute(
        """UPDATE consultations SET status='answered', answer_text=?, answer_amount=?,
           answered_at=? WHERE id=?""",
        (
            request.form.get("answer_text", "").strip(),
            to_int(request.form.get("answer_amount")),
            date.today().isoformat(),
            consultation_id,
        ),
    )
    conn.commit()
    flash("回答を記録しました。", "success")
    return redirect(url_for("consultation_detail", consultation_id=consultation_id))


@app.route("/consultations/<int:consultation_id>/save_as_case", methods=["POST"])
def consultation_save_as_case(consultation_id):
    conn = db()
    c = conn.execute("SELECT * FROM consultations WHERE id=?", (consultation_id,)).fetchone()
    if c is None:
        abort(404)
    amount = c["answer_amount"] or c["rough_estimate"] or 0
    cur = conn.execute(
        """INSERT INTO cases (is_sample, maker, model, year_or_type, mechanic, work_description,
           symptom_note, mileage, case_date, subtotal, tax, total, source_type)
           VALUES (0,?,?,?,?,?,?,?,?,?,?,?, 'mechanic_confirmed')""",
        (
            c["maker"], c["model"], c["year_or_type"], c["mechanic"], c["work_description"],
            c["symptom_note"], c["mileage"], c["answered_at"] or date.today().isoformat(),
            amount, 0, amount,
        ),
    )
    case_id = cur.lastrowid
    conn.execute(
        "INSERT INTO case_items (case_id, category, name, qty, unit_price, amount) VALUES (?,?,?,?,?,?)",
        (case_id, "その他", "整備士確認済み概算(相談メモより)", 1, amount, amount),
    )
    conn.execute("UPDATE consultations SET linked_case_id=? WHERE id=?", (case_id, consultation_id))
    conn.commit()
    flash("整備士確認済みの参考事例として保存しました。今後の検索に使われます。", "success")
    return redirect(url_for("consultation_detail", consultation_id=consultation_id))


@app.route("/consultations/<int:consultation_id>/apply_to_estimate", methods=["POST"])
def consultation_apply_to_estimate(consultation_id):
    conn = db()
    c = conn.execute("SELECT * FROM consultations WHERE id=?", (consultation_id,)).fetchone()
    if c is None:
        abort(404)
    amount = c["answer_amount"] or c["rough_estimate"] or 0

    estimate_id = c["linked_estimate_id"]
    if not estimate_id:
        settings = get_settings()
        validity_days = int(settings.get("default_validity_days") or 30)
        cur = conn.execute(
            """INSERT INTO estimates (maker, model, year_or_type, mechanic, work_description,
               symptom_note, mileage, estimate_date, valid_until, tax_rate, basis_note, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'draft')""",
            (
                c["maker"], c["model"], c["year_or_type"], c["mechanic"], c["work_description"],
                c["symptom_note"], c["mileage"], date.today().isoformat(),
                (date.today() + timedelta(days=validity_days)).isoformat(),
                float(settings.get("tax_rate") or 0.10),
                "整備士への相談回答をもとに作成",
            ),
        )
        estimate_id = cur.lastrowid
        conn.execute("UPDATE consultations SET linked_estimate_id=? WHERE id=?", (estimate_id, consultation_id))

    conn.execute(
        "INSERT INTO estimate_items (estimate_id, category, name, qty, unit_price, amount, sort_order) "
        "VALUES (?,?,?,?,?,?,0)",
        (estimate_id, "その他", f"整備士確認済み概算（相談#{consultation_id}）", 1, amount, amount),
    )
    conn.execute(
        "UPDATE estimates SET basis_note = COALESCE(basis_note || char(10), '') || ? WHERE id=?",
        (f"相談#{consultation_id}の整備士回答額({amount}円)を反映", estimate_id),
    )
    conn.execute("UPDATE consultations SET status='estimated' WHERE id=?", (consultation_id,))
    conn.commit()
    recalc_estimate(estimate_id)
    flash("回答額を見積に反映しました。", "success")
    return redirect(url_for("estimate_detail", estimate_id=estimate_id))


# ------------------------------------------------------------------ settings --

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        set_settings({
            "company_name": request.form.get("company_name", "").strip(),
            "company_address": request.form.get("company_address", "").strip(),
            "company_tel": request.form.get("company_tel", "").strip(),
            "company_email": request.form.get("company_email", "").strip(),
            "tax_rate": str(to_float(request.form.get("tax_rate", "0.10"))),
            "default_validity_days": str(to_int(request.form.get("default_validity_days", "30")) or 30),
        })
        flash("設定を保存しました。", "success")
        return redirect(url_for("settings_page"))
    return render_template("settings.html", settings=get_settings())


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5001, debug=True)
