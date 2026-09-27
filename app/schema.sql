-- 整備見積アシスト データベーススキーマ
-- 単純平均や自動確定を避けるため、金額の根拠(basis_note)は文字列として必ず残す設計にしている。

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 取り込んだExcel/CSVファイルの記録(重複取り込み検知・元資料へのトレース用)
CREATE TABLE IF NOT EXISTS import_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL,
    sheet_name    TEXT,
    checksum      TEXT NOT NULL,
    row_count     INTEGER DEFAULT 0,
    imported_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    note          TEXT
);

-- 過去事例(参考事例として検索される確定済みの実績データ)
CREATE TABLE IF NOT EXISTS cases (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    is_sample         INTEGER NOT NULL DEFAULT 0,
    customer_name     TEXT,
    maker             TEXT,
    model             TEXT,
    year_or_type      TEXT,
    mechanic          TEXT,
    work_description  TEXT,
    symptom_note      TEXT,
    mileage           TEXT,
    case_date         TEXT,
    subtotal          INTEGER DEFAULT 0,
    tax               INTEGER DEFAULT 0,
    total             INTEGER DEFAULT 0,
    source_type       TEXT NOT NULL DEFAULT 'manual', -- manual / imported / mechanic_confirmed
    source_file_id    INTEGER REFERENCES import_files(id),
    source_sheet_row  TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS case_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    category    TEXT NOT NULL DEFAULT '工賃', -- 部品 / 工賃 / その他
    name        TEXT NOT NULL,
    qty         REAL NOT NULL DEFAULT 1,
    unit_price  INTEGER NOT NULL DEFAULT 0,
    amount      INTEGER NOT NULL DEFAULT 0
);

-- 見積書(下書き〜作成済み)
CREATE TABLE IF NOT EXISTS estimates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    is_sample         INTEGER NOT NULL DEFAULT 0,
    customer_name     TEXT,
    maker             TEXT,
    model             TEXT,
    year_or_type      TEXT,
    mechanic          TEXT,
    work_description  TEXT,
    symptom_note      TEXT,
    mileage           TEXT,
    estimate_date     TEXT,
    valid_until       TEXT,
    notes             TEXT,
    tax_rate          REAL NOT NULL DEFAULT 0.10,
    subtotal          INTEGER DEFAULT 0,
    tax               INTEGER DEFAULT 0,
    total             INTEGER DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'draft', -- draft / created
    basis_note        TEXT, -- 金額の根拠(内部記録): 採用した参考事例 or 手入力である旨
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS estimate_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_id INTEGER NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
    category    TEXT NOT NULL DEFAULT '工賃',
    name        TEXT NOT NULL,
    qty         REAL NOT NULL DEFAULT 1,
    unit_price  INTEGER NOT NULL DEFAULT 0,
    amount      INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- 見積が採用した参考事例(根拠の記録)
CREATE TABLE IF NOT EXISTS estimate_references (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_id  INTEGER NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
    case_id      INTEGER NOT NULL REFERENCES cases(id),
    match_note   TEXT -- 一致した条件(車種一致/作業一致/整備士一致 等)
);

-- 参考事例がない案件の整備士相談メモ
CREATE TABLE IF NOT EXISTS consultations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    is_sample         INTEGER NOT NULL DEFAULT 0,
    maker             TEXT,
    model             TEXT,
    year_or_type      TEXT,
    mechanic          TEXT,
    work_description  TEXT,
    symptom_note      TEXT,
    mileage           TEXT,
    rough_estimate    INTEGER,
    memo_text         TEXT,
    status            TEXT NOT NULL DEFAULT 'consulting', -- consulting / answered / estimated
    answer_text       TEXT,
    answer_amount     INTEGER,
    answered_at       TEXT,
    linked_case_id    INTEGER REFERENCES cases(id),
    linked_estimate_id INTEGER REFERENCES estimates(id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
