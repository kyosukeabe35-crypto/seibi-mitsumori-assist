"""サンプルデータ投入スクリプト。

ここで作られるデータは実在しない架空の顧客・整備士・車両・金額です。
is_sample=1 でマークされ、画面上には常に「サンプル」タグが表示されます。
実データを取り込んでも、このスクリプトを再実行すればサンプル分だけを
洗い替えでき、実データには影響しません。
"""
from db import init_db, get_conn

SAMPLE_CASES = [
    # (maker, model, year_or_type, mechanic, work, symptom, mileage, date, items[(cat,name,qty,price)])
    ("BMW MINI", "クーパーS(R56)", "2013年式", "山田(サンプル整備士)",
     "タイミングチェーン交換", "始動時にカラカラ音", "78,000km", "2026-06-02",
     [("部品", "タイミングチェーンキット(サンプル)", 1, 68000),
      ("工賃", "脱着・交換工賃(サンプル)", 1, 55000)]),
    ("BMW MINI", "クーパー(R56)", "2011年式", "佐藤(サンプル整備士)",
     "タイミングチェーン交換", "エンジン警告灯点灯", "92,000km", "2026-04-18",
     [("部品", "タイミングチェーンキット(サンプル)", 1, 65000),
      ("工賃", "脱着・交換工賃(サンプル)", 1, 60000)]),
    ("トヨタ", "アクア", "2016年式", "山田(サンプル整備士)",
     "ブレーキパッド交換(前後)", "ブレーキ鳴き", "45,000km", "2026-07-10",
     [("部品", "ブレーキパッド 前後セット(サンプル)", 1, 18000),
      ("工賃", "交換工賃(サンプル)", 1, 12000)]),
    ("ホンダ", "フィット", "2018年式", "未定",
     "エアコンガス補充・点検", "冷えが弱い", "30,000km", "2026-08-01",
     [("部品", "エアコンガス(サンプル)", 1, 4000),
      ("工賃", "点検・補充工賃(サンプル)", 1, 6000)]),
    ("BMW MINI", "クーパーS(R56)", "2014年式", "山田(サンプル整備士)",
     "クラッチ交換", "クラッチ滑り", "105,000km", "2026-05-20",
     [("部品", "クラッチキット(サンプル)", 1, 95000),
      ("工賃", "クラッチ交換工賃(サンプル)", 1, 80000)]),
]

SAMPLE_CONSULTATION = dict(
    maker="BMW MINI", model="クーパーS(R60)", year_or_type="2016年式",
    mechanic="未定", work_description="CVTミッションオーバーホール",
    symptom_note="加速時に異音・変速ショック", mileage="112,000km",
    rough_estimate=180000,
    memo_text=(
        "【整備見積のご相談(サンプル)】\n"
        "車両: BMW MINI クーパーS(R60) 2016年式\n"
        "走行距離: 112,000km\n"
        "作業内容: CVTミッションオーバーホール\n"
        "症状・補足: 加速時に異音・変速ショック\n"
        "参考事例が見つからなかったため、概算金額のご教示をお願いします。"
    ),
)


def run():
    init_db()
    conn = get_conn()
    conn.execute("DELETE FROM case_items WHERE case_id IN (SELECT id FROM cases WHERE is_sample=1)")
    conn.execute("DELETE FROM cases WHERE is_sample=1")
    conn.execute("DELETE FROM consultations WHERE is_sample=1")

    for maker, model, year, mechanic, work, symptom, mileage, cdate, items in SAMPLE_CASES:
        subtotal = sum(qty * price for _, _, qty, price in items)
        tax = round(subtotal * 0.10)
        total = subtotal + tax
        cur = conn.execute(
            """INSERT INTO cases (is_sample, customer_name, maker, model, year_or_type, mechanic,
               work_description, symptom_note, mileage, case_date, subtotal, tax, total, source_type)
               VALUES (1, ?,?,?,?,?,?,?,?,?,?,?,?, 'manual')""",
            (None, maker, model, year, mechanic, work, symptom, mileage, cdate, subtotal, tax, total),
        )
        case_id = cur.lastrowid
        for cat, name, qty, price in items:
            conn.execute(
                "INSERT INTO case_items (case_id, category, name, qty, unit_price, amount) VALUES (?,?,?,?,?,?)",
                (case_id, cat, name, qty, price, qty * price),
            )

    conn.execute(
        """INSERT INTO consultations (is_sample, maker, model, year_or_type, mechanic,
           work_description, symptom_note, mileage, rough_estimate, memo_text, status)
           VALUES (1,?,?,?,?,?,?,?,?,?, 'consulting')""",
        (
            SAMPLE_CONSULTATION["maker"], SAMPLE_CONSULTATION["model"], SAMPLE_CONSULTATION["year_or_type"],
            SAMPLE_CONSULTATION["mechanic"], SAMPLE_CONSULTATION["work_description"],
            SAMPLE_CONSULTATION["symptom_note"], SAMPLE_CONSULTATION["mileage"],
            SAMPLE_CONSULTATION["rough_estimate"], SAMPLE_CONSULTATION["memo_text"],
        ),
    )

    conn.commit()
    n = conn.execute("SELECT COUNT(*) c FROM cases WHERE is_sample=1").fetchone()["c"]
    conn.close()
    print(f"サンプル事例 {n} 件、相談メモ 1 件を投入しました。")


if __name__ == "__main__":
    run()
