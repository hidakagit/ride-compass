-- 較正値の上書き（app/infrastructure/tuning_overrides.py）。
-- 既定値は宣言（app/domain/tuning.py: TUNING_PARAMETERS）が持ち、このテーブルは
-- そこから動かしたぶんだけを持つ。axis_definitionsのように「行そのものが定義」には
-- しない——テーブルが空でも宣言どおりに動くため、fresh bootstrap（CI・新規環境・
-- disaster recovery）でスナップショットの投入が要らない。
CREATE TABLE IF NOT EXISTS tuning_overrides (
    param_id TEXT PRIMARY KEY,
    value DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
