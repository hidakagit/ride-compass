-- `tuning_overrides.updated_at`を、ORMが作ったテーブルにも足す。
--
-- 0043はこの列を含む`CREATE TABLE IF NOT EXISTS`だが、fresh bootstrapは
-- `create_tables()`（ORMのメタデータ）→`apply_pending_migrations()`の順で走るため、
-- ORMが先に作ったテーブルに対して0043は何もしない。その結果、migrationだけで
-- テーブルができた環境（本番）にはこの列があり、fresh bootstrapで作った環境
-- （CI・新規環境・開発機）には無い、という食い違いが残っていた。
-- ORM側へ列を足したうえで、既にORMが作ってしまったテーブルをこのmigrationで揃える。
ALTER TABLE tuning_overrides ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
