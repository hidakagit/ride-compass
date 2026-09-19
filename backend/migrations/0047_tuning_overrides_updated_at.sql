-- `tuning_overrides.updated_at`（いつその較正値へ動かしたか）。
--
-- 0043の`CREATE TABLE IF NOT EXISTS`にも同じ列があるが、fresh bootstrapでは
-- `create_tables()`が先に表を作るためそちらは何もしない。ORMが作った表にもこの列を
-- 持たせて、どの経路で作った環境でも同じ形にする。
ALTER TABLE tuning_overrides ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
