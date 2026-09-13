-- 派生データの世代（app/infrastructure/derived_data_meta.py）。
-- precompute系バッチが中身を書き直すたびに増える単調カウンタで、材料キャッシュが
-- 「ディスクへ書いた時点から中身が変わったか」を判定するのに使う。
-- axis_registry_meta（migration 0014）と同じ1行テーブルの形。
CREATE TABLE IF NOT EXISTS derived_data_meta (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    revision INTEGER NOT NULL DEFAULT 1
);

INSERT INTO derived_data_meta (id, revision) VALUES (1, 1) ON CONFLICT (id) DO NOTHING;
