-- 改善計画T318（ユーザー判断: 「軸スタジオで、地図マップ上にアイコン表示するかどうか
-- ON/OFFできるようにして。代役案内文(proxy_hint)は不要になるので消して」、2026-08-25）。
--
-- axis_definitionsテーブルへshow_map_icon（真偽値、地図上チップ・地図の見え方パネルの
-- 両方からこの軸を丸ごと表示/除外する）を追加し、旧proxy_hint（0019 migration追加、
-- 専用地図レイヤーを持たない軸向けの代役案内文）を撤去する。以前は専用レイヤーを
-- 持たない軸を「常に無効化されたチップとして表示し、proxy_hintで理由を説明する」
-- 仕組みだったが、そもそも表示しないという選択肢自体が持てるようになったことで
-- proxy_hintは不要になった（domain/axis_definitions.py: AxisDefinition.show_map_icon
-- のdocstring参照）。
--
-- show_map_iconはNOT NULL DEFAULT trueで追加する（priority_overridesの`[]`既定と同じ
-- 「空だが確定した値」の考え方）。既存全軸が現在「地図上に表示される」状態のため、
-- 既定trueにすることでbackfillのUPDATE文なしに現在の挙動を保てる（0016
-- is_published追加時と同じ「既定値=移行時の安全側の値」パターン）。
--
-- proxy_hintのDROPは不可逆だが、実データを持つのはgradient軸1件のみ
-- （0019 migration参照）で、その内容（案内文の文言）はこのmigration適用と同時に
-- コード側（domain/axis_definitions.py）からも削除済みのため、DB側にだけ残しておく
-- 意味が無い。
ALTER TABLE axis_definitions
    ADD COLUMN show_map_icon BOOLEAN NOT NULL DEFAULT true,
    DROP COLUMN proxy_hint;
