-- 改善計画T353/T359/T360。
--
-- T353: car_stress_bicycle_infra_adjustment内部軸（`highway_is_cycleway`等4正規化
-- フラグ材料を`car_stress`と`bicycle_infra_quality`の両方が軸参照経由[T292]で共有する
-- 構造）が、材料の排他帰属原則（改善計画T268: check_material_exclusivity、1つの材料は
-- 原則1つの軸だけが使う）と矛盾していたため廃止する。`car_stress`から自転車インフラ
-- 由来の調整を完全に排除し、`bicycle_infra_quality`だけが正規化フラグ材料を直接持つ
-- 設計へ是正する。
--
-- T359: 王子-荒川ルート検索がヒットしない問題（本タスクの発端）への対応を合わせて含む。
-- `car_stress_highway_base`のmappingに`footway`/`path`を追加（車ストレス軸が評価不能
-- だった問題の解消）。`bicycle_infra_quality`に5つ目の材料`shared_pedestrian_path`
-- （highway=footway/pathかつbicycle=yes/designated、河川敷サイクリングロード等の
-- 共用歩行者自転車道を検知）を追加。
--
-- T360: T353実施時、この変更をmigrationではなくaxis_adminのAPI直接操作（unpublish->
-- PUT->republish、DELETE）でdev DBにのみ適用したため、fresh bootstrap（CI・新規開発
-- 環境・disaster recovery等、まっさらなDBへ全migrationを順に適用する経路）では
-- car_stress_bicycle_infra_adjustmentが14件目として復活してしまう不整合が発覚した
-- （T360で起票）。本migrationはこの不整合を解消し、dev DBで実際にAPI経由で適用済みの
-- 最終状態（13軸）を、migration適用だけでも再現できるようにする。
--
-- 値はいずれもdev DBでAPI経由（PUT /api/admin/axis-definitions/{axis_id}）適用済みの
-- 実際の値と1:1で一致させてある（0014〜0021と同じ「DBの内容とコード内蔵/適用済みの
-- 値を一致させる」原則）。

-- (1) car_stress_highway_base: footway/pathを追加（値1.0、cycleway・living_streetと
--     同格）。あわせてchip_label/show_map_iconを、現行のaxis_adminバリデーション
--     （show_map_icon=trueかつchip_label未設定ならlabel4文字以内を要求、この軸の
--     labelは20文字）を満たす値へ修正する（内部軸は元々地図チップに表示されない
--     ため、show_map_icon=falseが意味的にも正しい）。
UPDATE axis_definitions SET
    shape_params = '{"kind": "categorical", "mapping": {"path": 1.0, "track": 2.0, "trunk": 4.0, "footway": 1.0, "primary": 4.0, "cycleway": 1.0, "tertiary": 3.0, "secondary": 3.0, "trunk_link": 4.0, "residential": 2.0, "primary_link": 4.0, "unclassified": 2.0, "living_street": 1.0, "tertiary_link": 3.0, "secondary_link": 3.0}, "material": "highway"}'::jsonb,
    chip_label = '道路基準',
    show_map_icon = false
    WHERE axis_id = 'car_stress_highway_base';

-- (2) bicycle_infra_quality: car_stress_bicycle_infra_adjustment（軸参照）をやめ、
--     highway_is_cycleway/cycleway_has_track/cycleway_has_lane/cycleway_has_sharedの
--     4正規化フラグ材料を直接参照する（旧2段階のbreakpoint_linear変換を1段階へ
--     数学的に正確に合成、実データで発生する全パターンで旧来と同じ出力）。
--     さらに5つ目の材料shared_pedestrian_pathを追加（重み-4.0、track/highway=
--     cycleway同格）。breakpointsは[[-4,0],[-2,33.3],[-1,66.7],[0,100]]。
UPDATE axis_definitions SET
    shape_params = '{"kind": "breakpoint_linear", "terms": [{"weight": -4.0, "material": "highway_is_cycleway", "required": true}, {"weight": -4.0, "material": "cycleway_has_track", "required": true}, {"weight": -2.0, "material": "cycleway_has_lane", "required": true}, {"weight": -1.0, "material": "cycleway_has_shared", "required": true}, {"weight": -4.0, "material": "shared_pedestrian_path", "required": true}], "preprocess": "identity", "breakpoints": [[-4.0, 0.0], [-2.0, 33.3], [-1.0, 66.7], [0.0, 100.0]]}'::jsonb,
    description = '専用の自転車インフラ（分離自転車道・自転車レーン等、河川敷サイクリングロード等の自転車通行可の歩行者道を含む）が整備されているほど易しい。'
    WHERE axis_id = 'bicycle_infra_quality';

-- (3) car_stress: car_stress_bicycle_infra_adjustmentへの参照をtermsから削除。
--     breakpointsを[[1.0,0.0],[5.0,100.0]]から[[0.0,0.0],[4.0,100.0]]へ再較正する
--     （自転車インフラのベースラインオフセット+1を除去したことに対応。インフラ
--     非該当の道路では旧来と評価が完全一致するよう調整済み。自転車インフラの恩恵は
--     今後bicycle_infra_quality軸の重み付けのみで反映される、評価の意味の変更を
--     伴う——実データでの影響は86,642件中3,942件[4.5%]、T353本文参照）。
UPDATE axis_definitions SET
    shape_params = '{"kind": "breakpoint_linear", "terms": [{"weight": 1.0, "material": "car_stress_highway_base", "required": true}, {"weight": 1.0, "material": "car_stress_maxspeed_adjustment", "required": false}, {"weight": 1.0, "material": "car_stress_lanes_adjustment", "required": false}, {"weight": 1.0, "material": "car_stress_designation_adjustment", "required": false}, {"weight": 1.0, "material": "car_stress_motor_vehicle_no_adjustment", "required": false}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [4.0, 100.0]]}'::jsonb,
    description = '推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数の指標で、信号や交差点の頻度は含まない(別軸)。自転車インフラの有無は別軸(自転車インフラ)で評価します。',
    panel_hint = '道路種別・制限速度・車線数・指定路線・自動車通行可否から推定した車の圧迫感の目安です。実際の交通量そのものは加味していません。内訳は区間をクリックして確認できます。'
    WHERE axis_id = 'car_stress';

-- (4) car_stress_bicycle_infra_adjustment内部軸を削除する。上記(2)(3)で参照を
--     外した後のため、削除後も他の軸から参照されない孤立軸を残さない。
DELETE FROM axis_definitions WHERE axis_id = 'car_stress_bicycle_infra_adjustment';
