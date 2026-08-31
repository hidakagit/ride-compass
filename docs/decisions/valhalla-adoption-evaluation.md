# Valhalla（既存OSSルーティングエンジン）採用検討ADR

T522（ルート生成の異常な遅延調査、`docs/tasks/T522.md`）の過程で、自前の経路探索エンジン
（`road_graph_engine.py`＋`domain/routing.py`＋`domain/evaluation.py`）を、OSRM/GraphHopper/
Valhallaのような既存OSSルーティングエンジンへ置き換える案が挙がったため検討した。

ステータス: **確定（2026-09-01、不採用）**。実装は行っていない。

## 検討の経緯

T522の調査でルート生成の遅延原因（`evaluate_graph`のCPUコスト）が判明した際、「一から
自前で再発明する意義があるのか、業界標準のエンジンを使うべきではないか」という疑問が
提起された。RideCompassのRoute Engineは`scipy.sparse.csgraph.dijkstra`をそのまま使う
薄いラッパーであり（`docs/decisions/road-graph-migration.md`「独自の経路探索アルゴリズムの
実装はしない」という当時の方針を踏襲）、探索アルゴリズム自体を自作していない。一方
Evaluation Engine（`domain/evaluation.py`・`domain/axis_definitions.py`・軸スタジオ）は
RideCompass独自の設計であり、この部分を既存エンジンで代替できるかが論点になった。

## 調査結果

### 1. 周回ルート生成機能について

**当初「Valhallaには周回ルート生成機能が無く、自前で作る必要がある」という理由で懸念材料に
挙げたが、これはRideCompassの現行実装を正しく踏まえていない指摘であり撤回した。**

RideCompass自身の`RoadGraphEngine.trace_loop`は、8方位ぶんクライアント側（`route_generator.py`）
で計算した経由地座標を`node_sequence = [起点, 経由地1, 経由地2, 起点]`という経由地列として
Dijkstraへ渡しているだけであり、これはValhallaの複数地点ルーティングAPI（`locations`配列）と
構造的に同一である。したがって「周回生成機能がエンジン側に無い」ことは移行の障害にならない
——8方位選定・経由地座標計算・候補評価というオーケストレーション層は、どのエンジンを
使っても自前で持つ薄い層であり、Valhallaへ置き換えてもこの構造は変わらない。

### 2. 軸スタジオ相当の動的コスト関数について

**これがValhalla不採用の決定的な理由である。**

Valhallaは「動的コスティング」（`Sif`モジュール）を持つが、これは`bicycle_type`・
`use_roads`・`use_hills`・`avoid_bad_surfaces`・`gate_cost`・`maneuver_penalty`等、
**Valhalla自身が事前定義した固定の少数パラメータ集合を、リクエストごとに調整できる**という
意味の動的さである。RideCompassの軸スタジオが提供する「任意の材料の組み合わせ・任意の
閾値・任意の重みで、コード変更なしに全く新しい評価軸をGUIから作る」という自由度とは
根本的に別物である。

実例として、GitHub Discussion #4699「Custom cost function」（2024年、Valhallaメンテナ
`nilsnolde`が回答）を確認した。質問者は`cost(edge) = param1 * heuristic + param2 *
probability + param3 * normal_cost`という、まさに複数要素の重み付き合成（RideCompassの
軸合成そのもの）を求めたが、メンテナの回答は:

1. `src/sif/autocost.cc`の`AutoCost`クラスを派生させ、`EdgeCost`メソッドを自前でC++で
   オーバーライドする
2. 自力でC++が書けない場合は、メンテナ自身の会社（gis-ops.com）への有償サポート依頼を提案

という内容だった。GitHub Issue #974（同種の「実行時カスタムデータでコスト計算に影響を
与える」要望、2017年）でも、メンテナの回答は「まだ完全には実装していない」というもので、
汎用的な仕組みは長期間存在していない。

**つまりValhallaには「宣言的に新しい重み付き合成式を定義する」仕組みが無く、新しいコスト式
1つごとにC++クラスを書く必要がある。** RideCompassの軸スタジオが要求するのは「1つの固定式」
ではなく「管理画面から都度自由に新しい軸を作れる汎用性」であり、これをValhalla側で実現するには、
1つのカスタムコスト式を書くより遥かに大きい、**前例の無い汎用コストエンジンのC++新規開発**
（かつValhalla本体へのフォーク維持という継続的な負債）が必要になる。

## 結論

Valhallaを含む既存ルーティングエンジンが得意とする領域（点A→B間の高速なコスト計算・
グラフ探索）は、RideCompassの本質的な差別化要素ではない。**RideCompassの実際の価値は
「材料×重みを管理画面から自由に組み替えて評価軸を研究できる」という、既存エンジンのどれも
提供していない部分にある。** ある意味、この検討によって「RideCompassは自前でエンジンを
作らないと挑戦できない領域のアプリである」という差別化要素を確認する結果になった。

したがって、Route Engine（探索アルゴリズム部分）は今後も標準的なグラフアルゴリズム
ライブラリ（現行scipy、あるいはT522派生タスクで検討中のrustworkx等）をそのまま使う方針を
維持しつつ、Evaluation Engine（軸スタジオ・材料カタログ・合成ロジック）は引き続き自前実装
とする。将来、性能要件がさらに厳しくなった場合でも、「Valhallaへ全面移行する」より
「自前のEvaluation Engineをどう高速化するか」を優先して検討すべきである。

Sources: [Custom cost function · valhalla/valhalla · Discussion #4699](https://github.com/valhalla/valhalla/discussions/4699)、
[Add custom data to affect routes - Dynamic costing · Issue #974 · valhalla/valhalla](https://github.com/valhalla/valhalla/issues/974)、
[Valhalla routing service API reference](https://valhalla.github.io/valhalla/api/route/api-reference/)
