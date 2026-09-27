"""過去事例の参考検索ロジック。

単純な文字列一致・部分一致によるスコアリングのみを行う。外部APIやAIによる
類似度判定は使わない。金額の自動確定は行わず、あくまで「候補の並べ替え」
だけが目的。
"""
import re

SEPARATORS = re.compile(r"[、,，・/\s　]+")


def _norm(s):
    return (s or "").strip().lower()


def _tokens(s):
    s = _norm(s)
    if not s:
        return []
    return [t for t in SEPARATORS.split(s) if t]


def _field_match(query, target):
    """完全一致/部分一致を判定し、(一致したか, ラベル)を返す"""
    q, t = _norm(query), _norm(target)
    if not q or not t:
        return (False, None)
    if q == t:
        return (True, "完全一致")
    if q in t or t in q:
        return (True, "部分一致")
    return (False, None)


def score_case(query, case):
    """query: dict(maker, model, mechanic, work_description)
    case: sqlite3.Row (cases table)
    戻り値: (score:int, reasons:list[str])
    """
    score = 0
    reasons = []

    ok, label = _field_match(query.get("maker"), case["maker"])
    if ok:
        score += 3
        reasons.append(f"メーカー{label}")

    ok, label = _field_match(query.get("model"), case["model"])
    if ok:
        score += 3
        reasons.append(f"車種{label}")

    ok, label = _field_match(query.get("mechanic"), case["mechanic"])
    if ok:
        score += 2
        reasons.append(f"整備士{label}")

    q_tokens = set(_tokens(query.get("work_description")))
    c_tokens = set(_tokens(case["work_description"]))
    overlap = q_tokens & c_tokens
    if overlap:
        score += len(overlap)
        reasons.append("作業内容一致(" + "・".join(sorted(overlap)) + ")")
    else:
        ok, label = _field_match(query.get("work_description"), case["work_description"])
        if ok:
            score += 2
            reasons.append(f"作業内容{label}")

    return score, reasons


def find_reference_cases(conn, query, limit=20):
    """スコア0より大きい事例を降順で返す。無ければ空リスト。"""
    rows = conn.execute(
        "SELECT * FROM cases ORDER BY case_date DESC, id DESC"
    ).fetchall()
    scored = []
    for row in rows:
        score, reasons = score_case(query, row)
        if score > 0:
            scored.append((score, reasons, row))
    scored.sort(key=lambda x: (-x[0], x[2]["id"] * -1))
    return scored[:limit]
