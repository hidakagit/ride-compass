# 改善実行計画（2026-08-15 設計レビュー対応）

[design-review-2026-08-15.md](design-review-2026-08-15.md) の指摘に対する実行計画。
同日の第2回レビュー（[complexity-review-2026-08-15.md](complexity-review-2026-08-15.md)、複雑度平衡の観点）
の対応タスク（T16〜T22）は完了済みのため[docs/improvement-plan-archive/2026-08-15.md](improvement-plan-archive/2026-08-15.md)「第2回レビュー対応」節へ移設済み。
**進捗はこのファイルのチェックボックスを更新して管理する**（完了時に `[x]`＋完了日を追記）。

**このファイルは変更履歴であり、「現在の正」ではない**（過去レビュー基準と同じ扱い）。
評価軸の数・地図レイヤーの一覧・現在有効な設定値のような「動く事実」は、書かれた時点の
スナップショットに過ぎず本文中で何度も更新されている（例: 評価軸は7軸→8軸→9軸→8軸→7軸→
6軸+windと変遷）。現在の値は常に一次情報（`docs/architecture.md`）を参照し、本ファイル内の
古い記述と食い違っていても「矛盾」ではなく「その時点のスナップショット」として扱う。

**完了済みタスクの実施記録は[docs/improvement-plan-archive/](improvement-plan-archive/)へ日付ごとに
退避している**（2026-08-19棚卸し整理）。索引は[improvement-plan-archive/README.md]
(improvement-plan-archive/README.md)（完了タスク一覧つき）。本体にはオープンなタスクを
含む節と「進め方の原則」のみを残す。

## 進め方の原則

- **順序の根拠**: 「検証の自動化（Phase 1）→ 境界の固定（Phase 2）→ 内部の再配置（Phase 2後半）→
  スケール準備（Phase 3）」の順にすると、各修正が前の成果を安全網として使え、後続の修正量が最小になる。
- 1タスク=1コミット（またはPR）。着手前後で全テストgreenを確認する。
- 挙動を変えるタスクはテストを先に追加/更新してから実装する。
- **コミット時の同期ルール（OpenAPI生成物の再生成・architecture.md追従・タイル世代の
  対上げ）はCLAUDE.mdの「コミット時の同期ルール（必読）」節が正**（2026-08-23の棚卸で
  T196/T197のルールをここからCLAUDE.mdへ昇格・一本化した。本ファイルには重複記載しない）。
- 規模目安: S=1時間以内 / M=半日 / L=1日以上
- **フロントエンドで新しいUI機構（スライダー・タブ・ボトムシート等）を追加するときは、
  自前実装より先に定番ライブラリ（例: Radix UI、vaul等）で賄えないか検討する**
  （2026-08-23、ユーザー指示「一般的に使われているライブラリやスタイルを使うことで、
  車輪の再発明が防げるならば積極的に取り入れてほしい」、T250対応中に受領）。既存の
  BottomSheet（frontend/src/components/BottomSheet）は地図のピンチズームジェスチャーと
  衝突しないよう`touch-action`を実機フィードバックベースでチューニングした自前実装で、
  暗幕なし・部分表示という独自要件を持つため、置き換えを検討する場合はこの挙動を
  壊さないか要確認、かつ着手前にユーザーへ相談する。既存パターンの単純な拡張
  （例: コンポーネントへのprop追加）はこの原則の対象外。

---

**[Phase 1〜4（2026-08-15設計レビュー対応の原型4節、T1〜T15。T10/T11/T12は2026-08-23完了）は
docs/improvement-plan-archive/2026-08-15.md へ移設済み（2026-08-23棚卸）]**

## バックエンド一時的な到達不能の調査（2026-08-17・ユーザー報告）

### - [ ] T105. 地図をグリグリ操作した直後にバックエンドへ到達できなくなる事象の原因特定 規模S〜M — トリガー: 次回の再現報告

- 発端: ユーザーが本番サイト（Render）のモバイル実機スクリーンショットを提示。地図を素早く
  パン/ズームした直後、デバッグログに`region-road-surface-tiles`の`Failed to fetch`が2件、
  数分後には「システム状況」パネルの更新ボタンを3回連打してもバックエンド側
  （`/api/debug/stats`）だけが毎回`Failed to fetch`になり続けた（フロントエンド側
  `/api/version`は同一オリジンのNext.js自身の応答のため毎回即成功、対比でバックエンドの
  不調が際立った）。
- 調査所見: `/api/debug/stats`はDB・外部APIに依存しないプロセス内メモリ参照のみの
  軽量エンドポイント（`health.py`）のため、遅延ではなく到達不能（TCP接続不可）である
  可能性が高い。`region.py`には過去の実障害（グリグリ操作で並列タイル要求が急増→
  PostGIS問い合わせがCPUを奪い合う→Renderのヘルスチェックが無応答→インスタンス強制
  再起動、対策として`_region_tile_semaphore`で同時実行数6に制限済み）の記録があり、
  症状のパターンが一致する。ただし対策済みのはずの経路のため、(a)対策の再発、
  (b)Render無料枠のコールドスリープ（無操作でスリープ→次リクエストで再起動に数十秒）、
  のどちらか、あるいは両方が疑わしいが、Renderダッシュボード側のログ（インスタンス
  再起動イベント）を確認しないと確定できず、このセッションからは見えないため未確定。
- 副次対応（このラウンドで実施済み）: 調査中に`debugStatsApi.ts: getDebugStats`・
  `versionApi.ts: getFrontendVersion`が`fetch()`自体の失敗（通信エラー）をデバッグログへ
  記録していない不備を発見（HTTPステータス異常・JSON解析失敗はログするが、通信エラーだけ
  素通りしていた）。`regionApi.ts: refreshBasemapCache`で既に確立していた
  try/catchパターンへ統一し、次回同様の事象が起きた際にデバッグログだけで
  「フロントは動いているがバックエンドだけ通信エラー」を後から追跡できるようにした。
  frontend既存テストへ通信エラーケースを追加（各2件）、全green。
- 完了条件: ユーザーが同じ事象を再現・報告した際、更新後のデバッグログ（通信エラーの
  記録が残るようになった）とRenderダッシュボードのログを突き合わせて、
  「対策済み制御の再発」か「コールドスリープ」かを切り分ける。
- **関連（2026-08-24）**: 「20kmでルート生成に常に失敗する」報告の調査中、本タスクで
  確立したtry/catchパターンが`routeApi.ts`（POST系）・`regionApi.ts`の残り2関数・
  `jmaNowcastFrames.ts`には適用されておらず同種の穴が再発していたことが判明、
  T258で横断的に修正済み。20kmバグ自体の根本原因はT259で確定（Renderプラットフォームの
  約100秒タイムアウト）。本タスク（地図グリグリ操作直後の到達不能）とT259（ルート生成の
  20km失敗）は症状が別だが、いずれも「Render上の重い処理がプラットフォーム側の制約
  （ヘルスチェック無応答による強制再起動、または約100秒のリクエストタイムアウト）に
  引っかかって接続が切れる」という同根の可能性が高い。

### - [x] T259. 20kmルート生成が本番で常に失敗する事象の根本原因を特定 規模S（調査のみ、2026-08-24完了）

- 発端: ユーザー報告「現在地点から20kmでルート生成に常に失敗する」。ユーザー実機
  （緯度経度35.7506948, 139.7418897、本番フロント）で「fail to fetch」を確認。
  過去2回の直接API再現（ローカルスクリプトから本番DBへ直結、王子・ユーザー座標いずれも）は
  成功しており矛盾していたため、実際のブラウザ経由の本番環境で再調査した。
- **再現手順**: Browserツールで本番フロント（ride-compass-frontend.onrender.com）を開き、
  `navigator.geolocation.getCurrentPosition`をユーザー座標へモックした上で「現在地に移動」
  →距離20km→「ルート生成」を実行（`localStorage.setItem("ridecompass:debug-enabled","1")`
  でデバッグログも有効化）。
- **判明した事実**:
  1. ボタンが「生成中...」のままになり、**リクエスト開始から85.4秒後**に「Failed to fetch」
     でUIへエラー表示。ブラウザコンソールには
     `Access to fetch at 'https://ride-compass-backend.onrender.com/api/routes/generate' ...
     has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present`
     という**CORSポリシー違反に見えるメッセージ**が出ていたが、これは正しい診断ではない
     （後述）。T258で追加した`api:route`カテゴリのログにも
     `失敗 (通信エラー) {durationMs: 85435, error: TypeError: Failed to fetch}`として
     正しく記録された（T258の効果を実地で確認）。
  2. 同一リクエストをブラウザを介さずcurlで本番バックエンドへ直接送ったところ
     （`Origin`ヘッダーは付与、ブラウザのCORS強制は受けない）、**`HTTP/2 502`
     （`content-length: 0`、`server: cloudflare`、`x-render-origin-server: Render`）が
     `time_total=100.82秒`で返ってきた**。CORSヘッダーは一切無し。
  3. **結論**: これはアプリのCORS設定不備ではなく、**Render（Cloudflare経由）のプラット
     フォーム側が約100秒でリクエストを強制打ち切りし、空の502をエッジ層自身が生成して
     返している**。FastAPIアプリの`CORSMiddleware`はこの502に一切関与していない
     （アプリまで到達していない、またはアプリの応答より先にエッジが切っている）ため
     CORSヘッダーが無く、ブラウザは「CORSヘッダーの無いクロスオリジン応答」を実態と
     異なる「CORSポリシー違反」として報告している。フロント側のアプリレベルタイムアウト
     （`routeApi.ts`の360秒、T248参照）は一度も発火していない。
  4. **状況証拠（未確定）**: 502応答から26秒後に本番`/api/debug/stats`を確認したところ
     `started_at`（プロセス起動時刻）がその直後を指しており、複数回の確認でも安定していた
     （＝頻繁な再起動ではなく単発の再起動）。この重いリクエストの処理中にバックエンド
     プロセス自体がクラッシュ・自動再起動した可能性を示唆するが、Renderダッシュボードの
     再起動理由（OOM等）は本セッションから確認できず未確定。
  5. **過去の「直接検証は成功」との矛盾が解けた**: 過去の再現テストはローカルスクリプトから
     本番DBへ直結し、アルゴリズム・DB部分のみを計測していた。RenderのHTTP層（今回発見した
     約100秒のプラットフォームタイムアウト）を一切経由しないテストだったため、実際の
     ユーザー体験（ブラウザ→Render経由）とは異なる条件で「成功」していたに過ぎない。
- **T248との関係**: T248（road_graph既定エンジンの性能改善、規模M〜L）は「冷パスの体感
  遅延」として記録されていたが、本調査によりこの地点・距離の組み合わせは体感遅延ではなく
  **プラットフォームタイムアウトによる完全な失敗**に達することが確定した。T248のトリガー
  （「一般公開の意思決定時に必須化、それまでは研究利用での体感遅延報告で着手」）の前提
  （＝現状は"遅延"に留まる）を見直す必要がある可能性がある。
- 完了条件: 満たした（失敗のタイミング・エラー内容の特定というユーザー依頼の範囲）。
  ただし根本原因（冷パスがプラットフォーム制約を超えて完全失敗する）自体の修正は
  未着手。修正方針（冷パスの高速化＝T248、非同期ジョブ化、対象地点のキャッシュ事前温め等）
  はユーザー判断待ちのため、対応要否・優先度はT248側で改めて検討する。

### - [x] T261. 大規模な冷パスリクエストで本番バックエンドプロセスがクラッシュ→自動復旧する事象 規模不明（2026-08-24完了、T263のOracle VM移行で解消）

- 発端: T248候補1（save_graphのCOPY化）を本番デプロイした直後、ユーザーが「現在地10km」
  で生成を試みたところ25.8秒で`Failed to fetch`が発生（デバッグログ`durationMs:25842`）。
  直後の`GET /api/debug/stats`（DB・外部API非依存の軽量エンドポイント）まで同じく
  `Failed to fetch`になっており、個別リクエストの遅延ではなく**バックエンドプロセス
  自体がダウンしていた**ことを示す。ユーザーから「バックエンドは落ちてから自動復旧
  しているよう」という的確な指摘を受けた。
- **調査で判明した事実**:
  1. デプロイ直後から`/api/debug/stats`の`started_at`（プロセス起動時刻）が数分おきに
     更新され続けており、明確な**クラッシュ→自動再起動の繰り返し**を確認した
     （例: `22:42:46`→`22:46:22`と、こちらの追加リクエストのたび新しい起動時刻に
     切り替わる）。
  2. デプロイ直後という時系列とcommit一致から、当初はT248候補1（COPY化、一括で
     全レコードをメモリに載せてCOPYする実装）が原因と強く疑い、本番安定性を最優先して
     `git revert`で切り戻した（コミット`b2e846f`、詳細はT248候補1本文参照）。
  3. **しかし切り戻し後（`_bulk_upsert`のchunk=1000 ON CONFLICT、以前から本番で
     長期間安定稼働していたはずの実装）でも、同じ地点・10kmのリクエストが
     `http_code=502`・`time_total=71.4秒`で失敗し、直後にプロセスの`started_at`が
     再度更新されている（クラッシュが再現）ことを確認した**。これは
     **COPY化が原因ではない**ことを強く示唆する重大な発見であり、当初の仮説
     （T248候補1のメモリ使用量問題）は誤りだった可能性が高い。
  4. **新しい仮説**: T248・T259でこれまで「本番実測で成功」としてきた検証は、
     すべてローカルbackendから`DATABASE_URL`を本番Oracle Cloud PostGISへ直結する
     方式（RenderのHTTPレイヤー・実際のRenderアプリプロセスを一切経由しない）で
     行われていた。**Render上の実際のアプリプロセスが、大規模な新規split
     （`get_way_specs_with_closure`→`build_road_graph`→`save_graph`、都心規模で
     数万Node・十数万Edgeのグラフ全体をPythonオブジェクトとしてメモリに保持する
     経路）をこなせるだけのメモリを持っているかどうかは、今回のユーザー報告が
     初めての実地検証だった可能性が高い**。RenderのHTTPプロキシ層でのタイムアウト
     （T259で確定した約100秒）とは別に、**アプリプロセス自体のメモリ不足（OOM）
     によるクラッシュ**が真因である疑いが濃厚だが、Renderダッシュボードの再起動理由
     （OOM/ヘルスチェック失敗等）は本セッションから確認できず未確定。
  5. 切り戻し後のプロセスは、負荷が無い状態（アイドル時）では安定して200を返し続けて
     おり、常時落ちているわけではない。**特定の重い（未split・広域の）リクエストが
     トリガーになっている**点はT259と一致する。
- **現状**: T248候補1（COPY化）は切り戻し済みで、切り戻し自体は「メモリ使用量が
  未検証な新しい実装を本番から除去する」という安全側の判断として妥当だが、
  **クラッシュの根本原因は未解決のまま残っている**（切り戻し後の旧実装でも再現した
  ため）。「現在地」を含む一部地点・10km以上のリクエストで、ユーザーが実際に
  クラッシュ→復旧待ちを経験する状態が現在も続いている可能性がある。
- **ユーザー提供のRenderログによる追加調査（2026-08-24）**: ユーザーから該当時間帯の
  生ログを提供してもらい、2つの再起動を比較した。
  - `22:53:34`の再起動: 直前に`Shutting down`→`Waiting for application shutdown`→
    `Application shutdown complete`→`Finished server process`という**正常終了ログ**
    と`==> Your service is live`が出ていた（これは切り戻しデプロイそのもの）。
  - `22:56:41`の再起動: 直前の`22:56:27`の`GET /health -> 200`（90ms）から、正常終了
    ログが一切無いまま次の起動ログへ直接飛んでいた。しかもその手前で`/health`の
    応答時間が1ms→200〜300ms→90ms前後へ悪化する傾向が見えていた。
  - この非対称性（正常終了ログの有無）から、**プロセスが応答不能になり強制終了された**
    可能性が高いと判断した。T105が別トリガー（タイル要求急増）で記録していた
    「CPU専有→ヘルスチェック無応答→Render強制再起動」と同型の障害を疑い、
    `graph_service.py`の`build_road_graph(way_specs, node_coords)`が同ファイル内の
    他の重いCPU処理（`_rows_to_road_graph`等）と異なり`asyncio.to_thread`で
    オフロードされていない同期呼び出しのままイベントループ上に居ることを発見、
    修正した（コミット`5230bb5`）。
  - **しかし本番デプロイ後に再検証したところ、修正後も同じ症状が再現した**:
    同一リクエスト（10km、`http_code=502`・`time_total=71.5秒`）を実行しながら
    `/health`を1秒間隔でポーリングしたところ、応答時間が数百ms〜2.5秒へ悪化する
    だけでなく、**10秒のタイムアウトで2回応答が返らなかった**（`curl: Operation
    timed out`）。リクエスト失敗と同時に`started_at`も更新されており、クラッシュは
    解消していない。
  - **結論（暫定）**: `build_road_graph`のイベントループ専有は実在する問題だが、
    それだけでは説明がつかない。`asyncio.to_thread`はイベントループの
    スケジューリング公平性を改善するだけで、コンテナ自体のCPU割当（Renderの
    インスタンスプランがCPUを絞っている場合）が不足していれば、スレッドへ逃がした
    計算も同じ限られたCPU時間を奪い合い続け、ヘルスチェックも含め全体が遅くなる
    ことは避けられない。**Renderのインスタンスプラン（CPU/メモリの上限）が、この
    規模の冷パスリクエストに対して不足している可能性が、当初のOOM仮説と並ぶ
    有力候補として浮上した**。
- **Renderダッシュボードのイベントログで確定（2026-08-24、ユーザー提供のスクリーン
  ショット）**: Freeプランのため`Metrics`タブのCPU/メモリグラフは表示不可
  （`Upgrade to any paid instance type to view application metrics`）だったが、
  `Event timeline`に**`Instance failed`イベントが明示的に記録**されていた（推測では
  なく確定した事実）。時系列（新しい順）:
  - `8:09 AM` Instance failed: `xqvlt`（`5230bb5`＝asyncio.to_thread修正のインスタンス）
  - `8:08 AM` Deploy live for `5230bb5`
  - `7:56 AM` Instance failed: `w9zmn`（`b2e846f`＝切り戻し後のインスタンス）
  - `7:53 AM` Deploy live for `b2e846f`
  - `7:50/7:45/7:42/7:41 AM` Instance failed: `f4nmj`（**同一インスタンスIDで4回連続**、
    `91b25a7`＝COPY化のインスタンス）
  - `7:26 AM` Deploy live for `91b25a7`
  - **コードを何に変えても、デプロイ直後の重いリクエストで`Instance failed`が発生
    している**。これはT248候補1（COPY化）・T261の`asyncio.to_thread`修正のいずれも
    根本原因ではなかったことの確定的な裏付けであり、**Renderの無料プラン（公称
    0.1 CPU・512MB、Freeプランはこの数値も含めダッシュボードから直接は確認不可）の
    リソース制約そのものが律速要因である可能性が最も高い**という結論に至った。
    都心規模で数万〜十数万件のNode/Edgeをまるごとメモリ上のPythonオブジェクト
    （Pydantic/dataclass）として保持しながら交差点分割・PostGIS往復・バルクUPSERTを
    行う現在の冷パス設計は、512MB級のメモリ上限に対して明らかに重い可能性がある。
- 対応方針の選択肢（規模・コストの見積もりが異なるためユーザー判断が必要）:
  1. **Renderのインスタンスプランを有料枠へ増強する**（規模: 小、コスト: 月額課金）。
     最も直接的で低リスクな解決策。増強後に同じ10kmリクエストで再検証し、
     `Instance failed`が解消するか確認する。
  2. **冷パスの計算コスト・メモリ使用量そのものを削減する設計変更**
     （T248候補2「冷パスの体験設計」との統合、規模L以上）。Freeプランのまま
     解決したい場合はこちらが必須になるが、根本的な設計変更（ストリーミング処理・
     チャンク単位の逐次処理・バックグラウンドジョブ化等）が要る。
  3. 1と2の併用（増強しつつ将来的な負荷増にも備えて設計改善も行う）。
- **最終対応（2026-08-24）**: ユーザー判断により選択肢1・3のいずれでもなく、
  「Renderからの離脱」（別クラウドサービスへの移行）を選択。詳細検討・実装はT262
  （冷パス削減、性能改善として実施）・T263（Oracle Cloud VMへの移行、根本対応）を参照。
- 完了条件: 満たした。T263（Oracle VM移行）で実機ブラウザ検証まで完了し、T261が
  報告していた「大規模な冷パスリクエストでのクラッシュ」は新backend（Oracle Cloud VM）
  では再現しないことを確認した（詳細はT263参照）。Render側backendは1日間の並行稼働後に
  停止予定。

### - [x] T262. 冷パスのメモリ・CPU削減（Pydantic依存の解消、T261対応方針2） 規模M（2026-08-24完了、クラウド移行と併用でユーザー承認）

- 発端: T261の対応方針として「別クラウドサービスの調査」（ユーザーが別途比較検討）と
  「冷パスの計算・メモリ使用量削減」の併用を承認。後者の技術的フィージビリティを
  調査した結果（`domain/graph.py`の`Node`/`DirectedEdge`/`RoadGraph`/`WaySpec`が
  全てPydantic BaseModelで、都心規模（数万〜十数万Way/Edge）の`build_road_graph`が
  そのバリデーションコストを毎回払っていた）を踏まえ、既存の`LeanNode`/`LeanEdge`/
  `LeanRoadGraph`/`RoadGraphLike`基盤（T248候補1d、探索の読み取り専用パスに限定して
  導入済み）を「構築（build）」「保存（save）」パスへ拡張する形で実装した。
- **調査（Explore agent、実装前）**: `WaySpec`のコンストラクタ呼び出し・フィールド
  アクセス・`build_road_graph`戻り値の使われ方・`save_graph`引数の使われ方・関連
  テストのアサーションを全数洗い出し、Pydantic固有機能（`.model_dump()`等）への
  依存が0件であることを確認してから着手（障害になる箇所なし）。
- **実装1: `WaySpec`をdataclass化**（`domain/graph.py`）: 外部境界（API）を一切
  跨がない内部契約と確認済みのため、Lean/Full分離ではなく直接`@dataclass(frozen=True,
  slots=True)`へ変更。フィールド順を`node_ids`（必須）→デフォルト付きの順へ並び替え
  （全呼び出し元がキーワード引数のため無影響）。`tags`のミュータブルデフォルトは
  `field(default_factory=dict)`へ。
- **実装2: `build_road_graph`が`LeanRoadGraph`を返すよう変更**（`domain/graph.py`）:
  内部で構築する`Node`/`DirectedEdge`を`LeanNode`/`LeanEdge`へ変更。`LeanEdge.geometry`
  は「常に空」という規約（`get_graph_topology_in_bbox`側の規約）ではなく実座標を
  保持させることで、探索専用（`lean=True`）・地図表示（`lean=False`、実ジオメトリ
  必須）の両方の呼び出し元を同じ型で満たせるようにした（呼び出し元
  `GraphService.get_or_build_graph_with_attributes`は元々戻り値を`RoadGraphLike`
  Protocolで受けており、変更不要と確認済み）。
- **実装3: `save_graph`が`RoadGraphLike`を受けるよう変更**（`road_graph_repository.py`、
  本体・ファサード委譲の両方）。内部は元々`.node_id`/`.latitude`等の属性読み取りのみで
  完結しており、型注釈の変更のみで対応できた。
- **実装4: `Coordinates`（Pydantic、API境界のバリデーションが必要なため型自体は
  維持）への不要な変換を解消**（`domain/geo.py`・`domain/graph.py`・
  `domain/routing.py`）: `bearing_between`/`haversine_distance_km`の型ヒントを
  `Coordinates`固定から、`.latitude`/`.longitude`を持つ任意の型を受け付ける
  `LatLon`Protocol（新設）へ変更。`build_road_graph`の`_way_length_m`・bearing計算は
  座標ペアごとに`Coordinates`を構築し直していたのを、Pydanticバリデーション無しの
  `LatLonPoint`（`NamedTuple`、新設）へ変更。`domain/routing.py`の`find_nearest_node`/
  `find_nearest_node_indexed`（1リクエストにつき最大17回呼ばれる、T219）は、既に
  `latitude`/`longitude`を持つ`node`オブジェクトを`Coordinates`へ包み直さず直接渡す
  よう変更（無駄な構築そのものを無くした）。`Coordinates`自体はAPI境界（リクエスト
  スキーマの`ge=-90,le=90`検証等）で今後も使うため型は維持。
- **横展開の調査（ユーザー依頼「他にも同様修正を横展開できる個所はある？」）**:
  リポジトリ全体のPydantic BaseModelサブクラスを洗い出し、構築ホットパスの有無で
  仕分けた。
  - **対応済み**: `Node`/`DirectedEdge`/`RoadGraph`（T248候補1d）・`WaySpec`・
    `Coordinates`の内部ホットパス使用（本タスク）。
  - **追加候補として発見・未対応**: `EdgeAttributeCounts`/`ElevationAttribute`
    （`domain/attributes.py`）。`get_edge_materials_batch`・`get_graph_in_bbox`系の
    JOINクエリで、該当行があるEdgeの数ぶん（都心規模で数万件）ループ内でPydantic
    構築している。API層（ルーター）へは一切露出せず、`EvaluationService`が構造的
    アクセスのみで消費していることを確認済みで、`WaySpec`と同種の対応が可能と見込む。
    次に着手する場合の最有力候補として記録する。
  - **調査したが対象外と判断**: `WindGridPoint`/`WindGridResponse`（`domain/wind_grid.py`）
    はAPIレスポンスへ直接シリアライズされる境界型のため対象外。`POISpec`
    （`domain/osm_adapter.py`）はPBF取込バッチ（オフライン処理、リクエスト時間に
    影響しない）専用のため優先度低。
- **検証**: 隔離マイクロベンチマークで`Coordinates`→`LatLonPoint`の構築コストを
  直接計測（300,000回構築、`Coordinates`0.552秒→`LatLonPoint`0.185秒、**3.0倍**）。
  `Node`/`DirectedEdge`側の効果はT248候補1dの既存実測（171,461件で構築コスト推定
  11秒相当）を踏襲（実装が変わっていないため今回は再計測せず）。end-to-endの
  `bench_postgis_prepare.py`は、直前に実行したbackend全体テスト（155秒、通常47秒の
  3倍以上）等による同時実行負荷でノイズが大きく、今回は参考値に留める
  （システムが空いている時間帯に改めて計測することが望ましい）。
  backend全体1126件green（直列実行、xdist並列時の既存フレークはT248候補1と同じ理由
  で対象外）。
- 完了条件: 満たした（横展開調査を含む）。本番デプロイ後の`Instance failed`再発有無の
  確認、および追加候補（EdgeAttributeCounts/ElevationAttribute）への着手要否は
  T261側でユーザー判断を仰ぐ。
- **本番再検証（2026-08-24、デプロイ後）**: 同一座標・10kmで再検証したところ、
  `http_code=502`・`time_total=73.1秒`で失敗し、`/health`が10秒タイムアウト2回・
  9.75秒応答1回を記録、直後にプロセス`started_at`が更新（クラッシュ再現）。
  **T262（Pydantic依存削減）単独ではT261のクラッシュを解消できなかった**。
  この時点で本番コードはCOPY化を含まない（`b2e846f`切り戻し後のまま）状態であり、
  COPY化・T262いずれも原因ではないことが二重に確定したため、ユーザー指示により
  COPY化（T248候補1）を`git revert`でb2e846fを打ち消す形で再導入した（詳細は
  T248候補1の該当節参照）。T262（Pydantic依存削減）自体は性能改善として引き続き
  有効（クラッシュの根本解決ではないが、退行ではない）。

### - [x] T263. backendをOracle Cloud VM（DBと同居）へ移行 規模L（2026-08-24完了）

- 発端: T261で「Renderの無料プランのリソース制約（0.1 CPU/512MB）が冷パスクラッシュの
  真因」と確定（Renderのイベントログで「コードを何に変えてもInstance failedが発生」を
  確認済み）。ユーザー指示「クラウド移行する。Google Cloud Runで考えたいが、毎月の
  無料枠の範囲内で運用できる仕組みを構築できればという条件付」を受けて着手。
- **調査でCloud Runを断念**: Cloud Runの無料枠はegress（送信データ量）が月1GiBのみ
  （CPU/メモリの無料枠は180,000 vCPU秒・360,000 GiB秒と潤沢）。現在のbackendは
  basemapタイル・路面/事故/POIのMVTタイル・風の格子点データをそのままプロキシしており
  （`api/routers/basemap.py`等）、egressがボトルネックになり軽い利用でも無料枠を
  超過しうると判明。
- **既存Oracle Cloud VMへの同居を採用**: DBが既に稼働しているOracle Cloud Always Free
  VM（Ampere A1）を調査したところ、egressが月10TB（Cloud Runの1万倍）とほぼ無制限、
  SSH確認でメモリ8〜9GBの余裕があることが判明。PaaSの自動デプロイ・自動復旧は失うが、
  自前で（systemd/Dockerの再起動ポリシー・GitHub Actions経由のSSHデプロイ・
  nginx+certbotでのTLS）構築する方針とし、ユーザー承認を得て実施した。
- **実施内容**:
  - VM上にDocker・certbotを導入。既存nginx（`openmeteo-proxy.conf`と共存）へ
    新規`server`ブロックを追加。
  - TLS: 独自ドメイン不要な`sslip.io`（`193-123-166-150.sslip.io`）＋certbotで
    Let's Encrypt証明書を取得（自動更新設定済み）。
  - **ファイアウォールの二重構造が判明**: Oracle Cloud ConsoleのSecurity List
    （クラウド側）をユーザーが開放しても、**VM自身のiptables**（`netfilter-persistent`で
    永続化、22/5432/8080番のみ許可の既定REJECT構成）が別途80/443/22番を塞いでいた。
    両方の許可が必要と判明し、iptablesにも許可ルールを追加。
  - `.env`（DATABASE_URL・CORS_ALLOWED_ORIGINS・BASEMAP_PUBLIC_BASE_URL・
    OPEN_METEO_BASE_URL等、chmod 600・gitにコミットしない）をVM上に作成。
    `OPEN_METEO_BASE_URL`はDB同様に`http://localhost:8080/v1/forecast`
    （既存のOpen-Meteoリレープロキシへ同一VM内で直結）へ変更。
  - **CI/CD構築で発見した問題と対応**:
    1. 当初`docker/build-push-action`のcache-to type=ghaが既定の`docker`ドライバで
       非対応と判明（"Cache export is not supported for the docker driver"）、
       `docker/setup-buildx-action`を追加して解消。
    2. GitHub Actionsランナー（amd64）とOracle VM（Ampere A1、arm64）のアーキ不一致で
       `no matching manifest for linux/arm64/v8`が発生。`docker/setup-qemu-action`＋
       `platforms: linux/arm64`でクロスビルドを試みたが、**QEMUエミュレーションが
       10分超えても完了しないほど非現実的に遅い**と判明（numpy/scipy等のインストール
       自体がエミュレーション対象になるため）。ghcr.io経由のpush/pull方式を撤回し、
       **SSH経由でVM自身にgit pull→ネイティブdockerビルド→再起動させる方式**へ変更
       （実測約3分で完了）。
    3. デプロイ用SSH鍵（新規生成、ユーザーの個人鍵とは別）をVMの`authorized_keys`へ
       追加し、GitHub Secrets（`ORACLE_VM_SSH_KEY`・`ORACLE_VM_HOST`）へ登録。
    4. `--network=host`が必須と判明: PostgreSQLがVMにネイティブ（コンテナ外）で
       稼働しているため、Dockerの既定ブリッジネットワークだとコンテナ内の`localhost`が
       コンテナ自身を指し`ConnectionRefusedError`になった。ホストのネットワーク
       名前空間を共有することで解消。
  - フロントエンド（Render）側の環境変数を更新: `NEXT_PUBLIC_API_URL`（ブラウザ向け）と
    **`BACKEND_INTERNAL_URL`（Next.jsサーバー側のrewrites専用、basemap/MVTタイルの
    プロキシ先。`NEXT_PUBLIC_API_URL`とは別物と気づかず最初の疎通確認でbasemapが
    502になった）**をいずれも新backend URLへ更新。
- **検証**:
  - VM内直接実行でT261再現条件（現在地10km相当）: `total_ms=17,252`（17.25秒）→
    再実行`total_ms=4,639`（4.6秒）、いずれもHTTP 200・クラッシュなし。
    `docker stats`でメモリ658MB（ピーク）→599MB（安定）、6GB上限に対し十分な余裕。
  - CI/CDパイプライン自体をエンドツーエンドで検証（push→VM上でgit pull＋ビルド＋
    再起動が実際に成功することを確認）。
  - **実機ブラウザでの検証**（本番フロントエンド→新backend、Browserツール）:
    basemap表示成功、ルート生成（現在地10km相当）`durationMs=16,513`（16.5秒）・
    候補7件・クラッシュなしを確認。
- 完了条件: 満たした。1日間の並行稼働（Render backendは残したまま）で最終確認した後、
  Render側のbackendサービスを停止する（ユーザー合意、即削除はせずロールバック手段として
  当面残す）。
- **残作業: デプロイ確認機構（`/health`のcommit）の回帰を発見・修正（2026-08-24完了）**:
  T248の完了確認中、本番backendの`/api/debug/stats`が`"commit":null`を返し続けている
  ことに気付いた。原因はRender固有の自動注入環境変数`RENDER_GIT_COMMIT`
  （`docs/architecture.md`「Renderデプロイの反映確認」参照）がOracle VM上のDocker運用
  には存在せず、移行時に代替の注入手段を用意し忘れていたため。これにより
  「本番に実際にどのコミットが反映されているか」を`git rev-parse HEAD`と突き合わせて
  外部から確認する既存の仕組みが、backend側だけ恒久的に機能しなくなっていた
  （frontendは今もRender稼働のため`RENDER_GIT_COMMIT`は生きており影響なし）。
  - **修正**: `Settings.render_git_commit`を`Settings.git_commit`（環境変数`GIT_COMMIT`）へ
    改称し、[.github/workflows/deploy-backend.yml](../.github/workflows/deploy-backend.yml)で
    VM上ビルド直前に`git rev-parse HEAD`した値を`docker run -e GIT_COMMIT=...`で
    明示的にコンテナへ渡すよう変更（`backend/app/config.py`・`main.py`・
    `api/routers/health.py`・`version.py`、レスポンスのJSONキー`commit`自体は変更なし
    のためOpenAPI生成物への影響なし）。
  - `docs/architecture.md`の「Renderデプロイの反映確認」節を「デプロイの反映確認
    （backend/frontendで注入元が異なる点に注意）」へ改題し、backend
    （`GIT_COMMIT`・deploy-backend.yml経由）とfrontend（`RENDER_GIT_COMMIT`・Render
    自動注入のまま）で注入元が異なる旨を明記。コードベースマップ内の旧記述
    （`render_git_commit`・「Renderデプロイの反映確認」という節名への参照）も
    あわせて更新。
  - テスト: `test_config.py`・`test_health.py`のフィールド名・env var名を追従。
    backend全体1132件green（直列実行）。
  - **並行してユーザーがRender側のbackendサービスを停止**（2026-08-24、1時間強の
    並行稼働で確認）。本タスクの完了条件（1日間の並行稼働）よりは短いが、ユーザー
    判断により前倒しで実施。

### - [x] T264. 冷パスのステージ別ログ追加＋closure_ms削減 規模S（2026-08-24完了）

- 発端: T263移行後、ユーザーから「30kmがなかなか帰ってこない」報告。調査したところ
  未split地点への初回アクセス（冷パス）で正常に重い処理（クラッシュではない）が
  進行中と判明したが、`prepare_ms`の内訳が`save_graph`の個別ログ以外に無く、
  どの段が支配的か特定できなかった。ユーザー指示「もう少し軽くできない？」を受けて
  ステージ別計測を追加し、実測に基づいて改善余地を探った。
- **ステージ別ログ追加**（`graph_service.py: get_or_build_graph_with_attributes`・
  `_build_search_materials_uncached`）: `closure_ms`（`get_way_specs_with_closure`の
  DB空間クエリ）・`build_ms`（`build_road_graph`の交差点分割）・`save_ms`
  （`save_graph`、既存ログと重複するが1行サマリとして再掲）・`materials_ms`
  （`get_edge_materials_batch`の材料バッチ取得）を追加。
- **実測（水戸・宇都宮、30km・未split地点）**: `build_ms`はT262のlean型化の効果で
  既に軽い（142,081 Edge規模でも2.7秒、8%）。残る内訳: `save_ms`(35%、既にCOPY化済み)・
  `closure_ms`(29%)・`materials_ms`(15%)・その他(14%)。
- **Open-Meteo 429の調査（横道、実害なしと確認）**: 実測中に`weather:open-meteo`で
  429が複数発生していたが、`/api/debug/stats`で確認したところエラー座標が全て
  テスト地点と無関係な東京都心だった。原因は検証用に開いたままだったBrowserタブ
  （東京都心の地図を表示し裏で風データをポーリング）と同時実行したことによる
  Open-Meteo側レート制限への同時ヒットで、移行自体が原因ではないと判定した
  （リレープロキシの経路・送信元IPは移行前後で変わっていない）。タブを閉じて解消。
  既存のリトライ＋stale fallback機構が機能しており、ユーザーへの実害は無かった。
- **closure_msの`EXPLAIN (ANALYZE, BUFFERS)`によるDB側切り分け**: 宇都宮30km
  （primary_ways=35,725）の実際のbboxで`get_way_specs_with_closure`のWay取得クエリを
  直接実行したところ、GiST索引（`idx_osm_raw_ways_geom`）を使ったパラレル
  ビットマップスキャンで**DBサーバー側の実行時間はわずか112ms**だった。
  `closure_ms=9,748ms`との差（約85倍）は、Python側のORM行構築・デシリアライズ・
  ネットワーク転送が支配的であることを示す。
- **原因**: `_way_spec_row_to_domain`（Way→WaySpec変換）・`_raw_node_row_to_coords`
  （Node座標変換）はいずれも`geom`列を一切参照しない（前者はosm_way_id/node_ids/
  highway/surface/tags/directionのみ、後者は緯度経度のみ）にもかかわらず、
  `select(OsmRawWayRow)`・`select(OsmRawNodeRow)`で**全列（geom＝LINESTRING/POINT
  込み）をORM行として取得**しており、不要なshapely decode・ネットワーク転送量を
  発生させていた。`get_graph_topology_in_bbox`（T248候補1c）が同じ理由でEdge/Node
  ともにST_X/ST_Y列指定へ最適化済みだったが、`get_way_specs_with_closure`（closure
  取得）と`get_graph_in_bbox`（表示用フルパス）のNode取得には未適用のまま残っていた。
- **修正**（`road_graph_repository.py`）:
  1. `get_way_specs_with_closure`のway取得クエリを列指定（geom除外）へ変更。
     `_way_spec_row_to_domain`ヘルパーは呼び出し元が無くなったため削除。
  2. 同メソッドのnode座標取得クエリをST_X/ST_Y列指定へ変更。
     `_raw_node_row_to_coords`ヘルパーは呼び出し元が無くなったため削除。
  3. `get_graph_in_bbox`（`lean=False`の表示用パス）のnode取得も同様にST_X/ST_Y
     列指定へ変更（`Node`は`latitude`/`longitude`のみを持ち`geometry`フィールドを
     持たないため、lean/フルどちらのパスでも本来Node側にgeom decodeは不要）。
     `_rows_to_road_graph`を列指定行を受け取る形へ変更。
  4. 未使用になった`geoalchemy2.shape.to_shape`のimportを削除。
- **横展開調査（他に同様の無駄がないか再チェック）**: リポジトリ全体の`select(Model)`
  パターンを再確認。`get_edges_with_geometry`（最終候補への実ジオメトリ付与、T218）・
  `get_graph_in_bbox`のedge取得は実際にgeometry表示が必要なため対象外と確認。
  MVT生成・最近傍検索等の生SQLは全てDB側でgeomを直接使う設計（Pythonへ転送しない）で
  無駄なし。`recompute_node_degrees`系のINSERT...SELECTもDB内で完結しPython側は
  一切geomに触れないため対象外。
- **検証**: `EXPLAIN ANALYZE`と同じ座標帯で正規化比較（エッジあたりの時間）:
  修正前（宇都宮、142,081 Edge）`closure_ms=9,748ms`＝68.6μs/edge → 修正後
  （高崎、207,280 Edge）`closure_ms=5,839ms`＝28.2μs/edge、**約2.4倍の改善**
  （規模が46%大きいにもかかわらず絶対値でも9,748ms→5,839msへ40%減）。
  backend全体1125件green（1件`test_save_graph_with_way_ids_to_replace_handles_...`は
  合成データ（全17,000wayが同一2点を使い回す、GiST索引が病的に遅くなる既知の
  テスト特性）の影響で並列実行時に既存dev DBの状態と衝突し一時的に長時間化したが、
  単体実行では45秒で成功・今回の変更（`road_edges`のINSERTではなく`osm_raw_ways`/
  `osm_raw_nodes`のSELECT側）とは無関係と確認済み）。
- 完了条件: 満たした。`build_ms`は既に十分軽く、`closure_ms`は容易な改善（geom列の
  不要な取得除去）で2.4倍高速化。残る`save_ms`（既にCOPY化済み）・`materials_ms`は
  さらなる高速化にDB側の構造的な見直しが必要になる規模のため、ユーザー判断により
  一旦ここで区切りとする。

---


---

**[T106〜T117ほか（交通ストレスレシピ外出し基盤・交通ストレスレシピ調整UIパネル・
天候取得502の再発・研究パラメータの導線改善・交通ストレス5段階化、いずれも
2026-08-17完了）はdocs/improvement-plan-archive/2026-08-17.md（同一ファイル、
バックエンド一時的到達不能の調査より後の節）へ移設済み]**

## テストスイート実行効率化の検討事項（2026-08-18・フロントvitestタイムアウト調査より）

**[本節の完了タスク（T125・T126・T128）は docs/improvement-plan-archive/2026-08-18-part2.md へ移設済み（2026-08-23棚卸）]**


### - [ ] T127. 日本全国データ取込の実現可能性検証〔容量・所要時間〕規模不明（調査完了・未実施、2026-08-18） — トリガー: 全国展開の意思決定

- 発端: ユーザー相談「日本全国のデータ取込をするならどれだけの容量、時間がかかるか。
  現実的かを検証してほしい」。実施はせず調査のみ。
- **ファイルサイズ**（Geofabrik実測、2026-08-18時点）: 関東`kanto-latest.osm.pbf`
  466MB・全国`japan-latest.osm.pbf`2,358MB（8地域区分合計。北海道179MB/東北292MB/
  関東466MB/中部484MB/関西333MB/中国223MB/四国84MB/九州297MB）。**倍率は約5.06倍**。
- **ストレージ試算（問題なし）**: 本番DB（関東本土7都県、T101バックフィル後）は
  投入後2,050MB。単純比例で全国約10GB、契約中のOracle Cloudブロックストレージ150GBに
  対し約7%で十分収まる。
- **所要時間試算（不確実性が大きい、要追加検証）**: 本番投入ログ（2026-08-18、T101の
  バックフィル実行）のchunk単位タイムスタンプを精査したところ、**way数94万件を超えた
  あたりから処理速度が非線形に悪化し、投入完了（133万way）まで悪化し続け頭打ちの
  兆候が無かった**（序盤約0.28ms/way→終盤約1.97ms/way、最悪chunk単体で約7.44ms/way）。
  これは2026-08-15の関東拡大時（12章）にも「94万way超からの緩やかな減速」として
  記録済み・未解決の既知事象（GiST索引は対策済みで無関係と判明済み、原因未特定。
  Oracle Always Free枠が2026-06-15に無告知で4 OCPU/24GB→2 OCPU/12GBへ半減された
  小規模構成であることが一因の可能性）。全国規模（約665万way、133万wayの5.06倍）へ
  外挿すると、**楽観（悪化がKanto終了時点の水準で頭打ちすると仮定）で約3.2時間、
  現実的（悪化トレンドがそのまま継続すると仮定）には半日〜それ以上**という、
  133万way超の規模を一度も実行したことが無いゆえの幅の大きい見積もりにしかならない。
- **ローカル開発機の制約**: 作業機のCドライブが237GB中221GB使用済み・空き16GBのみ。
  日本全国PBF（2.3GB）のダウンロードは可能だが、pyosmiumの位置インデックス
  （大規模ファイルではディスクバック方式）の一時領域を考えると余裕は乏しい。
- **推奨する進め方**: いきなり全国投入をテストせず、中間規模（例: 関東+中部+関西＝
  1,283MB、全国の54%・関東の2.75倍）で先に投入し、94万way超の減速が実際にどこまで
  悪化する／頭打ちするかを実測してから全国投入の可否を最終判断する。より精度の高い
  試算をするなら、日本全国PBF（2.3GB、要ダウンロード許可）でway/node/POI件数を
  ローカルで正確にカウントする（DB書き込み無し）ことも検討候補。
- 完了条件（実施する場合の目安）: 上記の段階的検証（中間規模での実投入）で94万way超の
  減速カーブが頭打ちすることを確認し、全国規模の所要時間・リスクを再試算してから着手判断。

**[統合レビュー対応（2026-08-18・review:all第3回の指摘） の全タスクは docs/improvement-plan-archive/2026-08-18-part2.md へ移設済み（2026-08-23棚卸）]**

## 評価システムの層構造再設計（2026-08-18・区間評価の一次/二次/三次分離）

**[本節の完了タスク（T137・T138・T139・T140・T141・T142・T143・T144・T145b・T161・T162・T146・T147・T148・T149・T151・T150・T152）は docs/improvement-plan-archive/2026-08-18-part2.md へ移設済み（2026-08-23棚卸）]**


ユーザーから「一次データ（OSM等の生属性）・二次データ（軸スコア）・三次データ（重み付き合成コスト）の
役割が混ざっている」という課題認識のもと、層構造の再設計プロンプトが提示された。現状把握
（本セッション、Explore調査＋主要ファイル直接確認）の結果、提案の一部（〇次ハード制約の分離、
軸内係数と三次重みの分離、レシピの上書き可能な外部化）は既にT16〜T130の過程で実現済みだが、
以下は未実装または方向性の異なる決定事項として残っていた:

- **軸構成**: 提案は6軸（car_stress/accident/surface_q/stop_density/gradient/night）。現状は
  9軸（勾配・風・路面・停止密度・車の圧迫感・自転車インフラ・交差点密度・事故密度・安全度）で
  提案より粒度が細かく、かつ「車の圧迫感」と「安全度」が道路適正(N1)・自動車密度(N2)を意図的に
  共有する設計（T130、本日完了）になっている
- **レジストリ制**: `docs/complexity-review-2026-08-16.md`が「レシピが2つ目しかない段階では
  汎用レジストリ化は過剰」として明示的に見送っていた

ユーザーに確認のうえ、以下の方針で進める（詳細は本セクション追加時のセッション記録参照）:

1. **安全度軸は提案どおり廃止し、事故実績(accident)・夜間(night)へ分割する**（T130の
   「共有基盤化」路線からの転換。安全度が持つ街灯・トンネル補正はnight軸へ、highway別基準値・
   cycleway・maxspeed・lanes・指定路線補正はcar_stress軸へ統合し、事故密度は既存のaccident軸
   （変更なし）へ一本化）
2. **一次属性・二次軸のレジストリ制を導入する**（2026-08-16時点の見送り判断を、軸数が
   6〜9・将来のオープンデータ追加を見込む今回のスコープでは更新する）
3. **DB移行・両ルーティングエンジン書き換え・フロント全面改修を含む大規模変更のため、
   本セクションでタスク分割してから段階的に着手する**（1タスク=1コミット、着手前後で
   全テストgreenの原則をそのまま適用）

**未決定のまま残っている論点**（各タスクの着手時に確認・記録する）:

- ~~交差点密度（intersection_density）・自転車インフラ（bicycle_infra）は提案の6軸表に
  明示的な帰属先が無い~~ → **2026-08-18、設計プロンプト改訂で解決**。自転車インフラは
  car_stressの入力へ統合（T138、従来方針のまま）。交差点密度は単独軸を持たず、
  信号・横断歩道・一時停止・踏切と同じstop_density軸へ「タグなし交差点」を独立した
  低い重みのカテゴリ（例: `unsignaled_intersection: 0.3`、signal=1.0比）として吸収する
  （新規T149）。intersection_densityがstop_densityへ寄せられる理由は「立ち止まる／
  減速する頻度」という同じ性質の指標だから、car_stress（走行中の車との近接ストレス）
  ではなく質的に異なるという設計判断（改訂後の設計プロンプト「現行9軸からの帰属先」節）。
  bicycle_infra統合後は`accident`と`car_stress`の相関を確認し、二重計上懸念を潰す
  （T138の完了条件へ追加）。この決定を受け、T137で先行登録していた`intersection_density`
  単独軸はレジストリから削除しstop_density側のinputsへ統合する後方修正を実施済み（下記
  T137実装メモ追記参照）
- 提案の〇次フィルタは「自転車通行不可・高速道路」のみだが、現状の`DISALLOWED_HIGHWAY_TYPES`は
  `trunk`/`trunk_link`も含む（高速道路より広い）。また現状の`motor_vehicle=no`（自転車可の
  車両通行禁止）は〇次のハード除外ではなく二次軸内の最善値1固定という別ロジックであり、
  提案の「通行不可はハード制約へ統合」との対応関係を明確にする必要がある（T140で扱う）。
  → **2026-08-23、T231で解決済み**: 現行実装（二次軸内の最善値固定）を正とし、0次へは
  移さない方針を確定・記録した（`docs/architecture.md`1029〜1057行目参照）

### - [ ] T145. 地図レイヤーパネルをレジストリ駆動にし、三次（合成コスト）を既定表示レイヤーとして
  新設する 規模L →（2026-08-19、T145a/T145bへ分割・方針再定義）

- 背景: 設計プロンプトのレイヤー表。現状の`mapLayers.ts`は10レイヤーが個別列挙で、
  「常時表示は合成コストのみ」に対応する三次レイヤー自体が存在しない。一次・二次は
  レジストリ（T137、ただしフロント側は別途TypeScript版が必要）から動的に列挙し、軸を
  増やしてもレイヤーパネル・凡例の改修が不要な構造にする。
- 分割の経緯（2026-08-19）: ユーザーと方針を協議し、当初案の「二次レイヤーの動的生成」を
  具体化する過程で2つの重要な制約を確認した。(1) 現行タイルは全ユーザー共有キャッシュ
  （Cache-Control: max-age=3600）のため、レシピ依存の軸最終値をサーバー側で焼き込むと
  研究モードの重み上書き（将来的にはユーザー別レシピ、T141のJSON/DB化が布石）と矛盾する。
  (2) 逆にaccident/stop_density軸は入力データ（事故点・POI集計）自体がタイルに無いため、
  クライアント側expressionでは原理的に計算できない。この2つから、アプリ自身の層構造を
  配信アーキテクチャへ写す「**事実はタイルに、解釈はクライアントに**」方針を採択した:
  一次属性・事前集計カウント（レシピ非依存の事実）はサーバー焼き込み、二次軸スコア
  （レシピ依存の解釈）はクライアントexpressionで計算する。三次（合成コスト）レイヤーは
  本タスクのスコープから外す（係数検証が別途必要なため、実施時期はユーザー判断）。

### - [ ] T145a. night軸の専用レイヤーを追加する 規模S〜M — トリガー: night軸の入力データ
  （lit/tunnelタグ）の充実

- 背景: 6軸のうちnightだけ対応する地図レイヤーが無い。ただし現OSMデータではlitタグが
  疎で、レイヤーを作っても他軸との差がほぼ見えないことをユーザーと確認済み（2026-08-19）。
- 対応方針: T145bの汎用機構へ普通に乗せる（専用実装はしない）。データが充実した時点で
  レジストリ登録のみで地図に現れるのが理想形。
- 完了条件: night軸レイヤーが地図上で意味のある差を表示できること。

### - [x] T266. 0次ハードフィルタをAPI・ベクトル化計算パスへ配線する 規模M（2026-08-24完了）

- 背景: 2026-08-24、ユーザーから「自転車専用道をなるべく優先して探索したい」という要望を
  受けて調査した結果判明したギャップ。`domain/evaluation.py: is_edge_allowed`は
  `hard_filters`引数でフィルタ名（`no_bicycle`/`motorway`/`trunk`、T140）ごとの
  個別ON/OFFに対応する設計になっているが、(1) APIレイヤー（`api/routers/routes.py`）には
  この`hard_filters`を受け取るフィールドが一切存在せず、(2) 実際のルート生成が使う
  ベクトル化計算パス`compute_edge_costs_bulk`はコード内コメントに明記されている通り
  「hard_filters引数によるレシピ単位の上書きは本関数では未対応」で`DEFAULT_HARD_FILTERS`を
  決め打ちしている。つまり設計（ドメイン層のシグネチャ）は用意されているのに、APIも実計算
  パスも配線されておらず、研究モードから0次フィルタを触る手段が現状存在しない。
- 対応方針:
  1. `compute_edge_costs_bulk`へ`hard_filters`引数を追加し、`HARD_FILTER_HIGHWAY_TYPES`
     走査部分の`DEFAULT_HARD_FILTERS`決め打ち参照をパラメータ化する（`is_edge_allowed`と
     判定基準が食い違わないよう、テストで両者の同値性を担保する）。
  2. `routes.py`の`RouteGenerationRequest`へ`hard_filters`相当のフィールドを追加し、
     APIから受け取れるようにする（コミット時の同期ルールに従い
     `export_openapi.py`→`npm run generate:api`→`frontend/src/types/generated/`の
     diffクリーンを確認）。
  3. 拡張除外設定（highway種別3種＋no_bicycle以外の任意条件、例: 未舗装除外）の要否は
     スコープを絞り本タスクでは着手しない。まず既存4種フィルタの選択的ON/OFFのみを実装し、
     利用実績を見てから任意条件の拡張は別タスクとして起票する。
  4. ~~研究モードUIへ0次フィルタのON/OFFチェックボックス群を追加する~~ → **2026-08-24、
     目論見書承認によりUI側はT267（一般向けルート設定画面の「除外する道路」チップ）へ
     移管**。本タスクはbackend配線（上記1〜2）までをスコープとする。
- 完了条件: APIリクエストで`no_bicycle`/`motorway`/`trunk`を個別にON/OFFしてルート生成でき、
  OFFにしたフィルタに該当する道路が実際に経路候補へ現れることを確認する（UI経由の
  実機確認はT267の完了条件側で行う）。
- **実装メモ（2026-08-24完了）**:
  1. `compute_edge_costs_bulk`/`compute_edge_cost`（scalarオラクル側も合わせて）へ
     `hard_filters: frozenset[str] | None`引数を追加。抽出フェーズ冒頭で
     `active_hard_filters = hard_filters or DEFAULT_HARD_FILTERS`を1回だけ計算し、
     highway種別判定・`no_bicycle`判定の両方をこの値で判定するよう修正した。
  2. **副次的なバグ修正**: 従来の`compute_edge_costs_bulk`は`no_bicycle`フィルタの
     ON/OFFに関わらず`bicycle=no`のEdgeを常時除外していた（フィルタ名チェックが
     漏れていた）。`is_edge_allowed`とロジックがずれていたバグで、今回`hard_filters`の
     配線と同時に修正した（`no_bicycle`をhard_filtersから外すと実際に候補へ現れることを
     `test_bulk_hard_filters_empty_allows_bicycle_no_edge`で確認）。
  3. `EvaluationService.evaluate_graph`→`RoadGraphEngine`（コンストラクタで保持、
     `penalty_strength`/`max_average_grade_percent`と同じパターン）→
     `dependencies.py: RouteGenerationSetup`/`get_route_generation_builder`まで、
     既存の`max_average_grade_percent`と全く同じ経路で配線した。openrouteserviceエンジンは
     対象外（従来の`max_average_grade_percent`等と同じ「road_graphエンジンのみに効く」
     方針を踏襲）。
  4. API: `routes.py`に`HardFilterOverride`（`RootModel[dict[str, bool]]`、
     `RoutePreferenceWeights`と同じ「全3キー必須」検証）を新設し、
     `RouteGenerateRequest.hard_filters`・`GenerationConditions.hard_filters`へ追加。
     省略時は`DEFAULT_HARD_FILTERS`（全フィルタ有効）がconditionsへエコーされる。
  5. OpenAPI再生成・フロント型追従（`api.d.ts`/`openapi.json`）、
     `frontend/src/types/route.ts`へ`HardFilterOverride`型を追加。
  6. 検証: backend全1140件green（新規5件: bulk/scalar一致・no_bicycleバグ回帰・
     API上書き/エコー/バリデーションエラー）、フロントtsc/vitest 516件green。
     docs/architecture.md（Request/Response例・TS型定義）へ`hard_filters`を追記。

**[統合レビュー対応（2026-08-19・review:all第4回の指摘） の全タスクは docs/improvement-plan-archive/2026-08-19.md へ移設済み（2026-08-23棚卸）]**

**[地図レイヤー階層の次数反転（2026-08-19・T128/T161/T162の継続検討） の全タスクは docs/improvement-plan-archive/2026-08-19.md へ移設済み（2026-08-23棚卸）]**

**[動的要素（風・降雨等）の導入（2026-08-20・調査起票） の全タスクは docs/improvement-plan-archive/2026-08-20.md へ移設済み（2026-08-23棚卸）]**

**[統合レビュー対応（2026-08-22・review:all第5回の指摘） の全タスクは docs/improvement-plan-archive/2026-08-22.md へ移設済み（2026-08-23棚卸）]**

## 動的データの追加候補整理（2026-08-22・雷ほか未着手データの棚卸しと起票）

**[本節の完了タスク（T204・T205・T210・T211・T212・T213・T214・T215・T216・T217）は docs/improvement-plan-archive/2026-08-22.md へ移設済み（2026-08-23棚卸）]**
**[T12実装スタックの完了タスク（T218・T218a・T219・T220）は docs/improvement-plan-archive/2026-08-23.md へ移設済み（2026-08-23棚卸）]**


ユーザー要望「動的データの対応追加を進めたい。雷等の改善計画未記載の物含めて、取り込むべき
データを整理して」を受け、既存の動的要素導入（T170〜T178、上記節）以降に検討されていなかった
候補を実機調査つきで棚卸しした（2026-08-22）。T171実装メモが「雷ナウキャストは別レイヤー・
別調査として残す」としていた宿題も含む。設計判断はT170〜T178節と同じ方針を踏襲する
（「回避一択」の危険は評価軸にせず警告表示、動的データの欠測はT87のレイヤーデータ状態機構
へ正直に載せる）。

**実施順序（Phase）**: Phase A（T204）・Phase B（T205）は完了（2026-08-22）。

- **Phase A（最小コスト・即着手、完了）**: T204（雷ナウキャスト、竜巻はオプション同梱）。
  T171と同じタイル配信系で、プロダクトコード（`thns`/`targetTimes_N3.json`）の実在を
  今回のPlaywright実機確認で確定済みのため、残る作業は実装のみ。
- **Phase B（警告バッジ基盤、完了）**: T205（気象警報・注意報）。T174（WBGT）と警告バッジの
  表示枠を共有できるため、この基盤を先に作ってからT174へ進むと二重実装を避けられる
  （`WarningBadge.tsx`として実装済み、T174着手時はこれを再利用する）。
- **Phase C（既起票の優先順位再確認、内容変更なし）**: T176（河川敷冠水、台風期の今が
  調査の好機）→ T175（花粉、冬季着手で間に合う）→ T177（交通量時間帯補正、季節非依存）。
- **Phase D（トリガー付きDEFER・調査のみ）**: T206（積雪・凍結）・T207（雷ポテンシャル
  CAPE延長予報）・T208（視程・霧）・T209（黄砂・PM2.5）・T210（通行止め・道路規制調査）。
  いずれもトリガー未到達の実装を「ついで」にやらない（設計原則10）。

### - [ ] T206. 積雪・凍結情報（JMA「今後の雪」タイル・Open-Meteo積雪変数） 規模S〜M — トリガー: 冬季前（毎年11月）またはユーザーからの着手指示

- 発端: ユーザー要望（2026-08-22）。JMA「今後の雪」タイル配信
  （`https://www.jma.go.jp/bosai/jmatile/data/snow/targetTimes.json`、200 OK実機確認済み。
  `snowd`積雪深・`snowf01h`〜`snowf72h`各時間降雪量を含む）とOpen-Meteoの積雪変数
  （`snowfall`・`snow_depth`・`freezing_level_height`、いずれも実機取得確認済み）が
  候補。関東平野部では対象日が限定的だが、山間部ロングライドでは凍結・積雪が
  「回避一択」の危険になりうる。
- 対応方針（トリガー到達時）: 表現形式（rasterTileの面表示 vs 警告バッジ）・評価軸に
  組み込まない方針（凍結は危険側、警告表示のみ）を含めて着手前に再検討する。
  Open-Meteo経由の`freezing_level_height`（凍結高度）は既存のget_forecast_many格子へ
  変数追加するだけの低コストな経路（T183と同じ相乗り）。
- 完了条件（着手時に確定）: 積雪・凍結の警告が該当時期・該当地点で表示され、対象外
  シーズンは取得自体を行わずUIにも出ないこと。

### - [ ] T207. 雷ポテンシャル（CAPE）による延長予報の検討 規模S — トリガー: T204（雷ナウキャスト60分先まで）だけでは見通しが不足するという利用実績・要望が出た時点

- 発端: ユーザー要望（2026-08-22）。Open-MeteoのCAPE（対流有効位置エネルギー、
  実機取得値2040 J/kgを確認済み）は雷雲発達の指標として60分より先の見通しを提供できるが、
  「CAPE値→雷リスク」への変換は気象学的な閾値設定を要し専門性が高い。T204の
  雷ナウキャスト（実況〜60分）が既に主要な需要をカバーする可能性があり、CAPE延長は
  過剰投資になりうるため、実際に「60分より先も知りたい」という需要が確認できてから
  着手する。
- 対応方針（トリガー到達時）: 降水延長予報（T183、gridFill表現）と同じ経路
  （wind-grid格子へのCAPE変数相乗り）が使えるか検討。閾値設定（気象庁・気象予報士向け
  資料等を参照）を先に固めてから実装する。
- 完了条件（着手時に確定）。

### - [ ] T208. 視程・霧情報の導入可否を調査する 規模S（調査のみ）— トリガー: 山間部・河川霧発生地域での利用報告、または優先度見直し

- 発端: ユーザー要望（2026-08-22）。Open-Meteoの`visibility`変数は取得可能
  （実機取得値29,340m）だが、サイクリングでの実用価値（山岳・河川霧向け、早朝走行時の
  視認性）は関東平野中心の現状ユーザー像に対して優先度が低いと判断。
- 対応方針（調査項目、トリガー到達時）: (1) 表示形式（警告バッジ vs 数値表示）、
  (2) 「霧が出やすい」を判定する閾値（湿度・気温差との複合判定が必要か）、
  (3) 単独の情報価値が低い場合は気温・湿度と合成した「朝もや注意」のような複合指標に
  するか。調査結果を本エントリへ追記し実装可否を判断する（T50〜T54のJICE見送りと同じ
  「調査の結果、見送り」も正当な結論）。
- 完了条件（調査時に確定）。

### - [x] T209. 黄砂・PM2.5情報の導入可否を調査する 規模S（調査のみ、2026-08-23完了・判定: 実装可能、Open-Meteo採用を推奨）

- 発端: ユーザー要望（2026-08-22）。環境省そらまめくん（大気汚染物質広域監視システム）
  等が候補だが未調査。T175（花粉）が調査する「季節性の大気質情報をどう表示するか」
  （春季限定バッジ等の設計）と表現形式を共有できる可能性が高いため、T175の調査結果
  （利用規約・提供期間・地点粒度の調査知見）を踏まえてから着手する方が手戻りが少ない。
- 対応方針（調査項目）: (1) そらまめくんの公開データ提供経路（API/CSV）と利用規約、
  (2) Open-Meteoの大気質API（`air-quality-api.open-meteo.com`、別ドメイン・別クォータ）で
  PM2.5・黄砂（dust）が日本域で取れるかの実データ確認、(3) 表示形式（T175と共通化できるか）。
- 完了条件: 上記3点の調査結果と実装可否の判断が本エントリに記録されること。
- 依存: T175（完了済み）。

- **調査結果（2026-08-23）**:
  1. **そらまめくん（環境省）**: `soramame.env.go.jp/apiManual`にAPI仕様公開あり。
     JSON形式で測定局ごとの時報値（PM2.5・SPM・SP等）を取得可能、APIキー不要。ただし
     **著作権・利用ルールが測定局の運営主体で分かれており**、「国設局」（全国のごく一部）
     以外の大多数の地方公共団体運営局は個別に当該自治体へ問い合わせが必要
     （T175のウェザーニューズ花粉データと同型の「個別許諾が要る」ハードル）。取得可能
     期間も「現在月から遡って1年間のうち3か月以内」という制約があり、高頻度アクセスも
     自粛要請（他クライアントと同じ暗黙のマナー型レート制限）。全国一律で無条件利用
     できる公開データとは言えない。
  2. **Open-Meteo大気質API**: 実機確認（東京、2026年8月・2026年4月の2時点）で
     **PM2.5は常時実データ**（8月: 11.4〜94.3μg/m3、明確な日内変動あり）、
     **dust（黄砂）も黄砂シーズン相当の4月には実データ変動を確認**（240時間中159時間で
     非ゼロ、最大8.0μg/m3）、非シーズンの8月は終始0.0（データ欠損ではなく「観測上
     黄砂無し」の妥当な値と判断）。公式ドキュメントで両変数とも**CAMS Global
     （45km解像度、全球対応）由来と明記**されており、T175のpollen（欧州限定・
     日本は構造的にnull）とは異なり**技術的な対応制約は無い**。
  3. 表示形式: T174（WBGT）・T212（河川氾濫予報）と同じ`WarningBadgeList`共有
     コンポーネントが妥当。環境省の「注意喚起のための暫定的な指針となる値」
     （PM2.5日平均70μg/m3）等の既存の公的閾値を基準に警告バッジを出す設計が
     想定できる。
- **判断: 実装可能、Open-Meteo大気質APIの採用を推奨**。そらまめくんは全国一律の
  無条件利用ができない（T175と同型の許諾ハードル）ため不採用。Open-Meteoは
  技術的制約が無く、`weather_client.py`と同じ統合パターン（別ドメイン・別クォータの
  ため既存の天候クォータへ影響しない、TTLキャッシュ・tenacity再試行の型を流用可能）
  で実装できる。**本タスクは調査のみで完了とし、実装（規模M相当、フロント側の
  バッジ表示・axis/レイヤー設計を含む）は別タスクとして着手指示を待つ**（CLAUDE.mdの
  M以上の変更は着手前にタスクエントリを作成するルールに従う）。

### - [ ] T221. 評価軸のフルレジストリ駆動化＋GUI編集基盤 規模L（Part 3完了でStage Dまで到達、Stage E[GUI編集画面]は未着手）— トリガー: ユーザーの実装着手指示

- 背景: T12原則7の再検証（2026-08-23）で、現行7軸の変換ロジックが実質3テンプレート
  （折れ線補間・カテゴリ変換・フラグ加算、+car_stressの「レシピ→レベル→折れ線補間」の
  複合形）に還元できることが判明した。ユーザーから「将来的には見た目の磨き込み部分だけ
  IFで切り出して残し、裏のロジック部分はすべてフルレジストリ駆動化したい」という将来像
  （2026-08-23）を受け、独立したADRとして起票した。
- ADR: `docs/decisions/t221-axis-registry.md`（ドラフト、2026-08-23起票）。
  ロジック層（素材選択・変換テンプレート・パラメータ・重み・合成）を完全レジストリ駆動へ、
  見た目（アイコン・略名・案内文）は無指定時に汎用フォールバックが効くUIオーバーライド層へ
  分離する方向性のみ承認済み。段階構成（Stage A: 4テンプレートへの実装移行〜Stage E:
  GUI編集画面）・具体的スキーマ・DB化の要否は未承認のドラフトのまま。
- T12（探索速度）とは独立した設計課題だが、素材カタログ（T218参照）を共有する。
  Stage D（DB化）はT12 Part 2のキャッシュ無効化条件（軸定義の版数）との整合が要る。
- 未決の製品判断: GUI編集を誰に開放するか（研究モード限定か否か）、軸追加・重み変更の
  安全性検証をどう設けるか。詳細はADR末尾参照。
- **進捗と価値の変化（2026-08-23追記、統合レビュー第7回 統合-2）**: Stage Aは
  T239で実施済み（`domain/axis_templates.py`、7軸の変換ロジックを4テンプレートへ
  実装移行、外部契約不変）。あわせてT240のevaluate_graphベクトル化により、
  **評価軸追加の1本道が「スカラー2箇所＋配列3箇所」へ増えた**（difficulty.pyの
  スカラー関数と配列版関数の対、compute_edge_costs_bulkの抽出フェーズ・計算フェーズ
  への追記が新たに必要。同期ドリフトは`test_evaluation_bulk.py`のスカラー版全Edge
  一致テストが検知するため黙って壊れるリスクは低い）。**Stage B以降（レジストリ駆動化）
  でレジストリからスカラー/配列両実装を導出できれば、この二重管理が解消する**——
  ベクトル化によりStage B以降の価値が起票時点より上がったことを、将来の着手判断の
  材料として記録する。
- **Part 2着手（2026-08-23、ユーザー指示「T221に着手して」）**: スコープは
  ADRのStage B＋C相当。Stage D（DB化）・Stage E（GUI編集画面）はADR自身が
  「製品判断待ち（GUI編集の開放範囲・極端な重み設定への歯止め・T12 Part 2キャッシュ
  無効化条件との整合）」と明記しているため**今回も対象外のまま**とする。
  並行セッションがT250（モバイル上部バーUI、`page.tsx`等）を作業中のため、
  本タスクは専用worktree（ブランチ`t221-registry`）で実施し、masterへの統合は
  T250のコミット後に行う。実施内容の分割:
  1. **C-1 軸定義のデータ化**: 新規`domain/axis_definitions.py`へ、ADRの
     `AxisDefinition`スキーマ（axis_id・材料・shape・shape_params・default_weight）を
     宣言データとして7軸分定義する。breakpoints等の定数は`difficulty.py`/`night.py`から
     ここへ移動（定数の片側import原則）。
  2. **C-2 評価ロジックのレジストリ駆動化**: 汎用評価関数（スカラー/配列両対応）が
     `AxisDefinition`を読んでスコアを返す形にし、`difficulty.py`の`*_difficulty`
     スカラー関数を定義参照の薄いラッパへ（外部シグネチャ不変）、`*_array`個別実装は
     廃止して同一定義から導出（**T240で増えたスカラー/配列二重実装の解消**）。
     `compute_edge_axis_scores`/`compute_edge_costs_bulk`の軸ループを
     `AXIS_DEFINITIONS`駆動へ置き換え、軸ごとのハードコード行を消す。
  3. **B-1 内部dict化**: `AxisDifficulties`（NamedTuple）→`dict[axis_id, float | None]`、
     `evaluate_axis_difficulties`をレジストリループの薄い関数へ。両エンジンの
     区間ビルダー追従。
  4. **B-2 重みのdict化**: `RoutePreference`→axis_idキーの重み辞書（既知axis_id集合に
     対する全キー必須バリデーションは維持）、`route_preference.yaml`のキーをaxis_idへ、
     API層`RoutePreferenceWeights`→dict形式へ一般化。OpenAPI再生成＋フロント追従
     （`evaluationAxes.ts`の手書き対応表`PREFERENCE_WEIGHT_KEY_BY_AXIS_ID`廃止、
     `WeightPanel`のyamlミラーのaxis_idキー化）。`AXIS_WEIGHT_FIELD_TO_AXIS_ID`・
     `_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`の手書き対応表を削除。
  5. 整合: `registry_defaults.py`（表示カタログ）と`AXIS_DEFINITIONS`（評価定義）の
     軸集合突き合わせテスト、docs/architecture.md追従（同一コミット）。
  - 見送り（本Part内で判断）: `RouteSegmentDetail`の軸別固定フィールドのdict化は
    ADRでも「検討」止まりのため今回は据え置く。**保留の影響**: 軸を追加する際、
    評価・重み系はデータ変更のみで済むようになる一方、区間詳細表示（route.py＋
    両エンジンの区間ビルダー＋フロントのrouteStyleModes）へは引き続き軸ごとの
    手書き追記が必要なまま残る（ルート生成・探索コストはブロックされない。
    表示系の追従漏れは新軸の区間色分けが出ないという形で顕在化する）。
    必要になった時点で別タスクとして起票する。

- **Part 2実装メモ（2026-08-23完了、ブランチ`t221-registry`）**:
  - **C-1/C-2＋B-1（コミット`522e957`）**: 新規`domain/axis_definitions.py`に
    `AXIS_DEFINITIONS`（7軸の材料・shape・パラメータ・既定重みの宣言データ。辞書の
    挿入順が合成の加算順として意味を持つ——Neumaier加算のビット一致条件）と
    汎用評価関数`evaluate_axis_scalar`/`evaluate_axis_array`を実装。
    `difficulty.py`/`night.py`のスカラー関数は定義参照の互換ラッパ（None・負値ガードのみ
    担当）となり、`*_difficulty_array`群を削除して**T240で生じたスカラー/配列二重実装を
    解消**。`compute_edge_axis_scores`/`compute_edge_costs_bulk`/
    `axis_inspector_breakdown`/`evaluate_axis_difficulties`の軸ループをすべて
    `AXIS_DEFINITIONS`駆動化（軸ごとの1行ハードコードが消滅）。`AxisDifficulties`は
    axis_idキーの辞書＋compositeへ一般化。
  - **B-2（コミット`20cd840`）**: `RoutePreference`をaxis_idキーの重み辞書`weights`へ
    一般化（既定値は`AXIS_DEFINITIONS.default_weight`が単一ソース、部分指定は既定値補完・
    未知キーはエラー、night動的化は`with_weight()`）。手書き対応表
    `AXIS_WEIGHT_FIELD_TO_AXIS_ID`・`_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`・
    `preference_to_axis_weights`を削除。API層`RoutePreferenceWeights`はRootModel(dict)化
    （全axis_id明示＋非負の検証で「省略時に既定値が黙って入らない」従来方針を維持）。
    `route_preference.yaml`のキーをaxis_idへ移行。`axis-catalog.json`へ
    `preference_defaults`を追加し、フロントの既定重み手書きミラー・
    `PREFERENCE_WEIGHT_KEY_BY_AXIS_ID`対応表を廃止（キー集合の突き合わせは
    `evaluationAxes.test.ts`が生成物と機械照合）。OpenAPI再生成＋型追従、
    docs/architecture.md追従（重み表・APIサンプル・1本道・レジストリ節）。
  - **検証**: backend全1077件green・frontend全501件green・tsc green。dev DB実データ
    54,020エッジでscalar/bulk全件一致（不一致0）。`bench_evaluate_graph`は同一負荷条件の
    masterと同水準（性能回帰なし。並行セッション負荷で絶対値は不安定なためmin値で比較、
    68k: 1.17s vs 1.57s / 121k: 2.40s vs 2.50s）。実機API検証: 旧形式キー422拒否・
    部分指定422拒否・新形式全軸で生成成功（road_graph、5候補）＋conditionsエコー一致。
  - **達成状態**: 既存4テンプレート＋既存材料で表現できる新しい軸は、
    `AXIS_DEFINITIONS`への1エントリ追加＋`registry_defaults.py`の表示登録＋生成物再生成
    だけで、探索コスト・区間インスペクタ・重みAPI/UI（スライダー・既定値）まで反映される。
    残る手書き追記は区間詳細表示（`RouteSegmentDetail`固定フィールド、上記保留）のみ。
  - **残作業（保留、影響範囲付き）**:
    1. **masterへの統合**: 完了（2026-08-23、並行セッションのT250〜T252-255コミット後に
       マージ。コンフリクトはdocs/improvement-plan.mdのみで、`page.tsx`はT250側の変更と
       自動マージされた）。
    2. **研究タブ重みUIのPlaywright実機確認**: 完了（2026-08-23、master統合後に実施）。
       e2eスモーク2件green＋一時spec（T250と同じ運用、検証後削除）で研究タブの
       区間難易度の重み7軸がカタログ由来のラベル・既定値（preference_defaults）で
       表示されることを実機確認した。あわせて`e2e/fixtures.ts`のroute_preference
       フィクスチャが旧キーのまま残っていたのを発見し修正（RootModel化で
       RoutePreferenceWeightsがindex signature型になったため、旧キーでも型検査を
       通ってしまう——この種のドリフトは今後`evaluationAxes.test.ts`のキー集合照合と
       API側の422検証が防波堤になる）。
  - Stage D（レジストリDB化）・Stage E（GUI編集画面）は引き続き製品判断待ち
    （本エントリ冒頭のトリガー・ADR参照。T221自体はPart 2完了でStage Cまで到達）。

- **Part 3着手（2026-08-24、ユーザー指示「T221のDに進んで」）**: 未決だった3点の製品判断
  （GUI編集の開放範囲・極端な重み設定への歯止め・T12 Part 2キャッシュ無効化条件との整合）
  をユーザーへ確認し、それぞれ「研究モード限定」「型・範囲チェックのみ」「軸定義の版数を
  キャッシュキーに含める」で確定（ADR「Stage D実装」節参照）。加えて「将来、研究モードを
  一般ユーザーから隠し何らかの権限制御を導入する計画がある」という方針が示されたため、
  管理APIの認可を「研究モードだから無認可でよい」という前提にせず、差し替え可能な1関数へ
  集約する設計にした。
- **Part 3実装メモ（2026-08-24完了）**: Stage D（レジストリのDBテーブル化＋管理API）を
  実装した。
  - **DB化**: `backend/migrations/0014_axis_definitions.sql`が`axis_definitions`
    （軸定義本体）・`axis_registry_meta`（版数）の2テーブルを追加し、既存7軸を
    `domain/axis_definitions.py`の内容そのままシードする。ORM
    （`infrastructure/axis_definition_models.py`）・リポジトリ
    （`infrastructure/axis_definition_repository.py`）は既存の書き込み非commit規約に従う。
  - **評価ロジックの読み出し方法は変えていない**: `AXIS_DEFINITIONS`は引き続き同期的な
    モジュールレベル辞書として読まれる。`services/axis_registry_service.py:
    refresh_axis_definitions`がアプリ起動時（`main.py`のlifespan）・管理API書き込み直後の
    2箇所だけで同じdictオブジェクトをin-place更新する「push型」設計にし、評価ホットパス・
    Pydanticバリデータ等の既存の同期アクセス箇所を一切変更せずに済ませた。DB未接続・
    未migration・0行の場合はWARNINGログを出しコード内蔵の既定値のまま動作を続けるため、
    **本migrationを本番へ適用するまでの間は評価の振る舞いが一切変わらない**安全側
    ロールアウトになっている（T74の教訓を踏まえた設計）。
  - **管理API**: `/api/admin/axis-definitions`（CRUD）を共有トークンheader
    （`X-Admin-Token`、環境変数`AXIS_ADMIN_TOKEN`）で保護。未設定環境では常に拒否する。
    妥当性検証は型・範囲チェックのみだが、「最後の1軸は削除できない」制約だけは
    構造的な安全策として例外的に持つ（レジストリを空にできると`refresh_axis_definitions`の
    0件フォールバックと衝突し評価が壊れるため、重みの妥当性とは別次元の問題として実装）。
  - **axis-catalog.json（フロント）は変更していない**: CIの`api-contract`ジョブがDB接続を
    持たないため、`export_openapi.py`は引き続きPython内蔵の`AXIS_DEFINITIONS`から生成する。
  - **検証**: backend全1126件green（新規37件、リポジトリ・サービス・ルータの3層）。
    dev DBへ実際にmigrationを適用し、シードされた7軸がPython定義とバイト単位で一致
    すること、`refresh_axis_definitions`後の`AXIS_DEFINITIONS`が元の内容と一致すること
    （評価の振る舞いが変わらないこと）を実DBで確認した。OpenAPI再生成＋フロント型追従
    （`git diff --exit-code`確認、axis-catalog.jsonは無変化）、`tsc --noEmit` green。
    docs/architecture.md「評価軸定義のDB化＋管理API」節を新設。
  - **残作業（保留、影響範囲付き）**:
    1. **本番DBへのmigration適用**: 完了（2026-08-24、ユーザー指示）。既存テーブル・
       既存データには一切触れない加算的な変更で、シード内容がPython定義とバイト単位で
       一致することを本番DBに対して直接確認した。**未設定のまま残っている項目**: Render側の
       環境変数`AXIS_ADMIN_TOKEN`が未設定のため、本番の管理APIは現状常に403（安全側の
       デフォルト、意図通り）。実際に使う段階でRenderダッシュボードから設定すること。
    2. **Stage E（GUI編集画面）**: 引き続き別タスクとして起票する（本ADRのスコープ外）。

### - [x] T222. Overpassライブ経路（`repository`未指定構成）の削除 規模M（2026-08-23完了）

- 背景: T218（探索の素材事前計算化＋リーンロード）実装時に判明。`GraphService`は
  `repository`未指定時、`OverpassClient.get_ways_and_nodes`経由でOverpassから都度
  Road Graphを構築する経路を今も持つ（T22でoverpass_fallback_enabled設定・
  PythonMVTエンコーダ・`OverpassClient.get_roads`は撤去済みだが、`get_ways_and_nodes`は
  「DBなし構成専用」として意図的に存続、`docs/improvement-plan-archive/2026-08-15.md`
  T22参照）。本番・dev環境は常に`repository`を注入するため到達しないが、コードとしては
  並行して残り続けている。
- 対応方針（着手時に検討）: `GraphService.__init__`から`overpass_client`/`http_client`
  引数と`repository`未指定分岐を削除し、`repository`必須の構成へ一本化する。
  `build_graph_with_surface_tags_for_bbox`・`_fetch_graph_with_surface_attributes`・
  `_build`・`OverpassClient.get_ways_and_nodes`本体の要否も合わせて判断する（DBなし構成の
  テスト・ローカル検証で使われている場合は移行方法を検討する）。
- 完了条件: `repository is None`分岐が`GraphService`・`RoadGraphEngine`関連コードから
  消え、DBなし構成に依存していたテストが新方式（repositoryへの直接シード等、T22の
  `test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node`と
  同じ移行パターン）で置き換わること。

- **実装メモ（2026-08-23完了、ORS→road_graphエンジン移行の残作業調査を受けて着手）**:
  1. `GraphService.__init__`から`overpass_client`/`http_client`引数を削除し
     `repository: RoadGraphRepository`を必須化。`_build`・
     `build_graph_with_surface_tags_for_bbox`・`_fetch_graph_with_surface_attributes`を
     削除し、残り全メソッドの`if self._repository is None`分岐を除去（常に
     `self._repository.X(...)`を直接呼ぶ）。
  2. `app/infrastructure/overpass_client.py`（`OverpassClient`本体）を丸ごと削除
     （`get_ways_and_nodes`の呼び出し元がGraphService以外に無いことを確認済み。
     クラスの存在理由自体が「GraphServiceのDBなし構成専用」だったため）。
     `tests/test_overpass_client.py`も削除。
  3. `app/api/dependencies.py: get_graph_service()`の`road_graph_use_repository`分岐を
     削除し、常にrepository付きで構築（GraphServiceに限りこの設定の影響を受けなくなる。
     他4箇所[`get_elevation_attribute_service`/`get_surface_match_repository`/
     `get_region_service`/`get_accident_service`]の同フラグ利用は今回のスコープ外の
     ため維持）。`app/services/region_service.py`の直接構築箇所も同様に更新。
  4. `tests/test_graph_service.py`のDBなし構成自体を検証する4テスト（Overpass呼び出し
     回数を数えるテスト等）を削除し、他の全テストの`GraphService(...)`呼び出しを
     `repository=`のみの新シグネチャへ更新。`tests/test_routes_generate.py`の
     軽量ビルダーテストも同様に更新（`RoadGraphRepository(session=None)`でI/O無しの
     ダミーrepositoryを渡す）。
  5. `scripts/verify_phase1_e2e.py`・`scripts/verify_postgis_phase0.py`・
     `benchmarks/bench_postgis_prepare.py`にあった「Overpassが呼ばれないことを保証する」
     ためのFake/Failingスタブ（`FailingOverpassClient`等）を削除し、新シグネチャへ
     更新（これらのスタブの存在理由自体が消滅したため）。
  6. `docs/architecture.md`のファイル構成表（`overpass_client.py`・
     `test_overpass_client.py`の行を削除、`graph_service.py`の説明を更新）・
     `backend/app/config.py`・`backend/.env.example`（`road_graph_use_repository`の
     コメント・プロファイル表）を現状に追従。特に`.env.example`の「開発（DBなし）」
     プロファイルは`ROUTING_ENGINE=road_graph`が選べなくなった点（GraphServiceが
     DATABASE_URLへの実接続を常に必要とするため）を明記した。
  - 検証: backend pytest 1051件全green（削除した重複・DBなし構成専用テスト12件分減）。

### - [x] T223. DEM1A（1mメッシュ）標高データの組み込み可否調査 規模S（調査のみ、2026-08-23完了・判定: 見送り）

- 発端: T10実装直後、ユーザーから「dem 1mメッシュを仕組みに組み込むことは現実的？」との
  質問。T10は現在`DEM_TYPE_PRIORITY = (dem5a, dem5b, dem5c, dem)`（5m/10mメッシュ相当）の
  優先順位フォールバックのみを実装しており、GSI最高精度のDEM1A（航空レーザ測量、1m格子、
  最大ズーム17、東京都心を含む都市部中心にカバレッジ）は対象に含めていない。
  2026-08-16調査（本ファイルT10節参照）では「OSM形状点間隔（多くは5m超）に対し
  1m格子化の恩恵はほぼ出ない」「DEM1Aのカバレッジは全国均一ではない」と判断し
  見送っていたが、この判断はT10実装前の推測であり、T10完了後のDEM_TYPE_PRIORITY実装
  （2026-08-23の多段フォールバック修正）を踏まえた再検証はまだ行っていない。
- 調査事項（着手時に確認する）:
  - `dem1a`エンドポイントの実在・カバレッジ範囲・応答フォーマットを実タイルで確認
    （T10の`dem5a`等と同じ手法で`https://cyberjapandata.gsi.go.jp/xyz/dem1a/{z}/{x}/{y}.txt`
    を実際に叩く。z=14でも取得できるか、dem5a同様の挙動か）。
  - 対象範囲（関東本土）でのDEM1Aカバレッジ率の実測（全エッジ中どの程度が恩恵を受けるか）。
  - サイクリングルートの勾配評価（average_grade、区間長は交差点間=数十m〜数百m）という
    用途にとって、1m格子と5m格子の差が実際に評価結果（gradient軸のdifficulty・
    ルート選択）へ影響する規模かの試算・実データ比較（無作為サンプルで|Δgrade|分布を見る、
    2026-08-16調査が言及した検証方法と同種）。
  - `DEM_TYPE_PRIORITY`の先頭に`dem1a`を追加するだけで済むか（設計上は同じ多段
    フォールバック機構にもう1段追加するだけの想定だが、カバレッジ外の404が大半を占める
    場合は「常に1回余分な404往復が発生する」オーバーヘッドとのトレードオフも評価する）。
- 完了条件: 「組み込む／組み込まない」の判断とその根拠を本タスクへ記録する。組み込む
  判断になった場合は実装を別タスクとして起票する（本タスク自体は調査のみ、実装は
  含めない）。

- **調査結果（2026-08-23）**:
  1. **エンドポイント形式**: `dem1a`という名称は存在せず、正しくは
     `https://cyberjapandata.gsi.go.jp/xyz/dem1a_png/{z}/{x}/{y}.png`
     （**PNG形式**）。既存の`dem5a`/`dem5b`/`dem5c`/`dem`は全て`.txt`
     （カンマ区切りテキスト、`elevation_client.py`が現在パースしている形式）である
     のに対し、DEM1Aのみ形式が異なる。実機確認でz=14〜17は200、z=18は404
     （最大ズーム17、T223発端メモの記載と一致）。
  2. **カバレッジ**: 国土地理院公式発表（2024-03-31改定）で全国の3次メッシュに対する
     提供割合は**約46%**。実機確認（東京駅付近・横浜みなとみらい・奥多摩山間部は200、
     千葉県印西市郊外・埼玉県鴻巣市郊外は404）で、**都市部・山間部（土砂災害等の
     優先整備エリア）は覆う一方、関東近郊の郊外部には明確な欠測がある**ことを確認した。
     2026-08-16調査の「カバレッジは全国均一ではない」という判断は正しかったと裏付けられた。
  3. **本用途への影響試算**: 上記1の理由により、`DEM_TYPE_PRIORITY`への追加だけでは
     済まず、PNG形式のデコード（GSI地理院タイル標準の
     `標高 = 2^16×R + 2^8×G + B`系のエンコード方式、`elevation_client.py`に
     新規パーサが要る）という**既存想定より一段大きい実装コスト**が必要と判明した。
     加えて2026-08-16調査時点の「OSM形状点間隔（多くは5m超）に対し1m格子化の恩恵は
     ほぼ出ない」という判断（区間長が交差点間=数十m〜数百mのため、5m格子と1m格子の
     差はサンプリング間隔の粗さに埋もれる）自体は本調査で覆す新情報が得られなかった。
- **判断: 見送り**。(a) PNG形式デコードという新規実装が必要（想定より実装コストが
  大きい）、(b) カバレッジが依然として全国均一でない（郊外部に明確な欠測を実機確認）、
  (c) 2026-08-16時点の「1m格子化の効果は評価粒度に対し限定的」という判断を覆す新情報が
  得られなかった、の3点から総合的に見送りと判断する。
- 再検討条件: GSI側でDEM1Aの全国カバレッジが更に拡大した場合、またはOSM形状点の
  密度を上げる別の取り組みで区間内サンプリング間隔が5m未満まで細かくなった場合。

## 統合レビュー対応（2026-08-23・review:all第6回の指摘）

レビュー結果の全文・Evidenceは`.claude/commands/review/history/2026-08-23_all.md`、
スコア推移の視覚レポートはArtifact（レビュースコアボード）を参照。

### - [x] T224. save_graph再構築経路の32767パラメータ超過を修正し、road_graph APIのエンドツーエンドを実測してT218/T219の完了条件を裏取りする〔P1〕規模S（修正）＋S（検証）（2026-08-23完了、本番バックフィルはユーザー判断待ちで未実施）

- 発端: 統合レビュー2026-08-23 統合-1。`ROUTING_ENGINE=road_graph`でのAPI実行
  （`POST /api/routes/generate`、dev DB）が2回連続500になることを実機確認。原因は
  `road_graph_repository.py: save_graph`の`delete_stmt.where(RoadEdgeRow.edge_id.
  not_in(new_edge_ids))`——`new_edge_ids`（再構築対象の全edge_id、都心密度で数万件）が
  無分割でIN句パラメータ化され、`id_chunk`（1万件）と合算でasyncpgの上限32,767を超える。
  **T218以前（`a6c82a2`）から存在する既存バグ**であり8コミットの回帰ではないが、
  再構築が必ず失敗するため`split_at`が更新されず`is_split_up_to_date`がFalseのまま
  自己回復不能——以後の全リクエストが再構築→クラッシュを繰り返す恒久500ループになる。
  この状態ではT219のタイルキャッシュ経路にAPI経由で一度も到達できず、T218の完了条件
  「WARM 10秒以内」も裏取り不能のまま。T218検証時（2026-08-23）に「既知・スコープ外」と
  記録しながら起票しなかったため、レビューが再発見するまで追跡不能だった。
- 対応方針:
  1. `new_edge_ids`のNOT IN句をチャンク化または`=ANY(配列)`化して修正（同ファイルで
     確立済みの`=ANY(配列)`パターンを流用。`_ID_CHUNK_SIZE`との合算が上限を超えない設計に）。
  2. 修正後、dev DBでroad_graph API経由のエンドツーエンド（冷→温）を実測し、
     T218「WARM 10秒以内」・T219「同一エリア2回目以降5秒以内」の完了条件を裏取りして
     アーカイブの完了記録へ追記する。
  3. 本番Oracle DBへのmigration 0013（bearing_deg）適用＋バックフィル、
     `precompute_elevation_attributes`バッチの本番初回実行の確認フローを本タスクに含める
     （T218/T218aの完了記録で「実行前にユーザーへ確認」と保留になっている項目。
     実行はユーザー確認後）。
  4. T218aの完了条件「山岳エリア（平均勾配の高いエリア）でgradient重み・ペナルティ強度Pを
     上げると実際に経路が変わることを確認」も本タスクのエンドツーエンド検証に含める
     （2026-08-23の実装時は単体テスト（探索コストへの反映・勾配ハードフィルタ）のみで、
     実地の山岳エリアでの経路変化確認は未実施のまま`[x]`が付いている。2026-08-23棚卸の
     全記録見直しで判明したあいまい残件）。
- 完了条件: dev DBでroad_graphエンジンのルート生成が冷/温とも500にならず完走し、
  数値目標の実測値を記録。山岳エリアでのgradient経路変化を実測。バックフィルの実施可否が
  ユーザー判断で確定している。

- **実装メモ（2026-08-23完了）**:
  1. **修正**: `road_graph_repository.py: save_graph`のNOT IN句を`=ANY(配列)`化
     （`RoadEdgeRow.osm_way_id`/`OsmRawWayRow.osm_way_id`のIN句も同様に統一）。
     `~(RoadEdgeRow.edge_id == any_(cast(new_edge_ids, ARRAY(Text))))`でNOT IN相当を表現。
     回帰テスト`test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit`
     （17,000way・34,000Edgeの一括再構築、PostGIS統合テスト）を追加し、**修正前のコードで
     実際に同一エラー（32767超過）が再現すること・修正後は例外なく完了することの両方を
     確認**（一時的に修正をstashして検証）。backend全体1065件green。
  2. **road_graph APIエンドツーエンド実測**（dev DB、`ROUTING_ENGINE=road_graph`）:
     500エラーは解消し、複数の起点・条件で例外なく完走することを確認。
     数値目標: 10kmループ生成（122,710エッジのbbox）で**1回目（split未済・再構築、
     一度きりのコスト）約57秒→2回目（タイルキャッシュ初回投入）約21秒→3回目以降
     （温）約5.4〜5.6秒**。`prepare()`内訳を直接計測すると、タイルキャッシュ自体の
     取得は温状態で約0.16秒（T219の設計どおり）だが、**このbboxの規模
     （122,710エッジ）では`evaluate_graph`約3.4〜3.7秒＋グラフ構築（nx+sparse）約1.0秒が
     支配的**で、目標「5秒以内」をわずかに超過する（5.4〜5.6秒）。T219が完了条件検証時に
     使った基準bbox（東京都心4km四方相当、69,216エッジ）より広いbboxでは
     evaluate_graph等のPythonループコストがエッジ数に比例して伸びるため、目標達成は
     bboxの規模に依存する。この残課題はT220の完了メモに既に記録済み
     （「evaluate_graph自体は今回手を付けていない、将来さらに高速化が必要になった場合は
     個別に精査」）であり、本タスクはT12の当初目標bbox規模での達成を再確認したに留まる
     （新規の課題ではなく、既知のスコープ外事項の実測値更新）。
  3. **T218aの山岳エリア実測**（dev DB）: `elevation_attributes`が本番未バックフィル
     （全128,887エッジ中1,325件のみ）だったため、dev DBに対し
     `precompute_elevation_attributes`を実行し全件（128,887件）バックフィル
     （elapsed=107.5秒、GSI DEMタイルはT10のキャッシュにより現実的な時間で完了）。
     急勾配エッジが集中するエリア（(35.69, 139.68)付近、平均絶対勾配7〜15%のエッジ
     100件超）で8km周回を`penalty_strength=1.0`と`8.0`で比較生成し、**同一方位
     （route-315）で明確な経路変化を実測**（P=1.0: distance=10.02km・
     max_gradient_percent=48.2% → P=8.0: distance=10.74km・max_gradient_percent=31.2%、
     より緩やかな迂回路へ変化）。ペナルティ強度を上げると候補集合自体も変化する
     （P=1.0は6候補・P=8.0は5候補、方位180が新規出現し方位270/090が距離許容差外へ脱落）。
     `max_average_grade_percent=8.0`のハードフィルタも指定し例外なく完走・候補集合が
     変化することを確認（8候補、探索グラフから急勾配エッジが除外されたことによる
     経路再構成）。T218aの完了条件を実地で満たした。
  4. **本番Oracle DBへのmigration 0013適用・バックフィル**: **未実施**。本番DB書き込みを
     伴うため実行前にユーザーへ確認する（本タスクの範囲外として保留、実行判断は別途）。
  5. 検証用の一時ファイル（テスト用uvicornプロセス・診断用printデバッグ・スクリプト）は
     全て削除・復元済み。road_graph_engine.pyの差分はゼロ（診断目的で一時追加したprint文は
     検証後にすべて元へ戻した）。

### - [x] T225. OpenAPI生成物へpenalty_strength/max_average_grade_percentを反映する〔P1〕規模S（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-2。T218/T218aが`RouteGenerateRequest`・
  `GenerationConditions`へ追加した2フィールドが`openapi.json`/`api.d.ts`に未反映
  （生成物ドリフトの同型3例目。T196でルールを「進め方の原則」へ明文化した翌日に、
  明文化した場所を読まない実装セッションが違反した）。
- 対応方針: `export_openapi.py`→`npm run generate:api`を実行し再生成をコミット。
  再発防止のルール自体は本起票と同時の棚卸（2026-08-23）で**CLAUDE.mdの
  「コミット時の同期ルール」節へ昇格済み**（常時読み込まれる場所へ移動。3例目の
  根本原因が「ルールの置き場所」だったため）。
- 完了条件: `git diff --exit-code -- frontend/src/types/generated/`がクリーン、
  生成物に両フィールドが存在、frontend vitest/tsc green。

- **実装メモ（2026-08-23完了）**: `export_openapi.py`→`npm run generate:api`を実行し
  `openapi.json`/`api.d.ts`へ両フィールドを反映。再生成の結果、`penalty_strength`は
  openapi-typescriptの既定挙動（JSON Schemaに`default`があるフィールドは`?`なしの
  必須型として生成される。既存の`distance_tolerance_km`/`route_type`と同じ扱い）により
  型上は必須になったため、これを消費する3箇所（`page.tsx`のルート生成呼び出し・
  `ComparisonPanel.test.tsx`・`routeApi.test.ts`）へ`penalty_strength: 1.0`
  （UIに調整スライダーは無いため既定値を明示送信、`max_average_grade_percent`は
  `null`）を追加してtscエラーを解消した。frontend vitest 501件・eslint・tsc全green。

### - [x] T226. T218/T219/T220後の旧経路残骸を削除する〔P2〕規模S〜M（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-3（overall O-1・O-2）。設計原則9
  「並行追加→切替→旧削除」の3段目が未実施。
  - `GraphService.get_stop_poi_counts`/`get_intersection_counts`/`get_accident_counts`は
    ランタイム呼び出し元ゼロ（T218→T219の移行で不要化、テストのみが参照）。
  - `_RoadGraphContext.nx_graph`はランタイムで誰にも読まれないまま毎prepare構築されている
    （実測約0.2〜0.4秒/リクエスト@69,216エッジ。T220の「区間表示互換のため維持」という
    理由付けは事実誤認で、実際の読者はテストのみ）。
- 対応方針: GraphServiceラッパー3本と対応テストを削除。prepareのnx_graph構築を廃止し
  contextから外す（テストは`build_networkx_graph`を自前で呼ぶ形へ書き換え）。
  `domain/routing.py`のNetworkX系関数自体はsparse版回帰テストのオラクルとして維持する
  （削除しない）。Repositoryファサードのフラット委譲契約（Keep List）はRepository層の
  話であり本タスクの対象外。
- 完了条件: backend全テストgreen、削除後にprepareの所要時間が短縮されることを確認。

- **実装メモ（2026-08-23完了）**:
  1. `GraphService.get_stop_poi_counts`/`get_intersection_counts`/`get_accident_counts`
     （graph_service.py）を削除。対応する`test_graph_service.py`の2テスト
     （`test_get_stop_poi_counts_without_repository_returns_empty_dict`・
     `test_get_stop_poi_counts_with_repository_delegates`）と`FakeRoadGraphRepository`の
     未使用フィールド・メソッドも削除。`test_road_graph_engine.py`の`FakeGraphService`が
     持っていた同名3メソッド（呼び出し元皆無、コメントのみが参照）も同様に削除。
     `get_way_tags`（引き続き`_build_search_materials_uncached`から呼ばれ現役）は残す。
  2. `_RoadGraphContext.nx_graph`フィールドを削除し、`prepare()`の
     `nx_graph = build_networkx_graph(graph, search_edge_costs)`行を削除
     （`build_networkx_graph`のimport・`import networkx as nx`も不要化のため削除）。
     `domain/routing.py`のNetworkX系関数自体は削除せず維持（`test_routing.py`・
     `benchmarks/bench_route_trace.py`が引き続き参照）。
  3. テスト側で`context.nx_graph[...]`を読んでいた3箇所（night軸・gradient軸の
     コスト比較、ハードフィルタ除外確認）を、実際に探索本体が使う
     `context.sparse_graph`から直接読む方式へ書き換え（`_sparse_edge_weight`/
     `_sparse_has_edge`ヘルパーを追加）。`_RoadGraphContext(...)`を直接構築する
     残り2箇所の`nx_graph=None`引数も削除。
  4. モジュールdocstring・コード内コメントのNetworkX言及をscipy.sparse.csgraph基準の
     記述へ更新（road_graph_engine.py冒頭・`_RoadGraphContext.sparse_graph`docstring）。
     architecture.mdの`RoadGraphEngine.prepare`説明・事故密度精度改善の節も、
     削除済みラッパーへの言及が残らないよう現状に合わせて更新。
  5. **所要時間短縮の実測**: 削除された`build_networkx_graph`呼び出し単体のコストを、
     T219/T220が基準にした規模（69,216エッジ相当、合成格子グラフで再現）で計測すると
     約272ms（`build_sparse_graph`単体は約199ms）。両方構築していた従来の
     グラフ構築コスト約471ms→sparseのみの約199msへ、約58%（約272ms）短縮したことを
     確認（`build_networkx_graph`は削除しておらず`domain/routing.py`に残るため、
     同条件で直接比較できた）。
  - 検証: backend pytest 1063件全green（削除した2テスト分減、新規0件）。

### - [x] T227. architecture.mdのT11完了を追従する〔P2〕規模S（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-4（consistency F-3）。`docs/architecture.md`の
  「未着手: T11（segmentsのAPI境界ビン化）」行が、同日完了済みのT11
  （`aggregate_segments_into_bins`、約500m単位ビン化）に未追従。
- 対応方針: 該当行を完了の記述へ更新し、segments集約の1文（road_graphエンジンのみに
  適用・`RouteSegmentDetail`型は不変・集約方法の要点）を追記。
- 完了条件: architecture.mdにT11の現状が反映されている。

- **実装メモ（2026-08-23完了）**: `docs/architecture.md`の該当行を、`aggregate_segments_
  into_bins`（`domain/route.py`）による約500m単位集約の説明（road_graph_engine.pyの
  `prepare`が生成した候補のみに適用・openrouteserviceエンジンは対象外・
  `RouteSegmentDetail`型は不変で契約影響なし）へ更新。コード変更なしのためテスト実行は
  不要。

### - [x] T228. 統合レビュー第6回の軽微指摘4件を一括解消する〔P3〕規模S（2026-08-23完了）

- 発端: 統合レビュー2026-08-23 統合-5。いずれも規模S:
  1. `SearchMaterials`/`_TileMaterials`（graph_service.py）のフィールド完全一致の
     重複データクラスを1クラスへ統合。
  2. 緯度1度≒111kmの定数重複（`domain/routing.py`の`_KM_PER_DEGREE_LATITUDE`と
     `road_graph_engine.py`のリテラル111.0）を`domain/geo.py`へ片側import化（設計原則2）。
  3. `graph_material_cache.py`の型付け（`_LRUCache`ジェネリクス・`object`戻り値）と
     `clear()`のカプセル化（`_data`直接参照の解消）。
  4. ORS失敗時の`RoutingError('openrouteservice request failed: ')`が空文字で
     診断情報ゼロの問題——例外種別・HTTPステータスをメッセージへ含める
     （2026-08-23の実機確認でdev環境のORS全滅の原因切り分けができなかった実績）。
- 完了条件: backend全テストgreen。

- **実装メモ（2026-08-23完了）**:
  1. `SearchMaterials`を`domain/attributes.py`へ移設（`EdgeAttributeCounts`/
     `ElevationAttribute`が既にそこにあり、`domain/graph.py`側へ置くと循環importになる
     ため）。`graph_service.py`の`_TileMaterials`を削除し`SearchMaterials`を共有型として
     使用（`_get_or_build_tile_materials`の戻り値・生成箇所を差し替え）。
  2. `KM_PER_DEGREE_LATITUDE`を`domain/geo.py`（`EARTH_RADIUS_KM`の隣）へ定義し、
     `domain/routing.py`の`_KM_PER_DEGREE_LATITUDE`定義を削除してimportへ、
     `road_graph_engine.py: _bbox_around_point`のリテラル`111.0`2箇所をimportへ置換。
  3. `graph_material_cache.py`の`_LRUCache`を`_LRUCache[SearchMaterials]`として具体化し、
     `get_tile_materials`/`set_tile_materials`の型注釈も`object`→`SearchMaterials`へ。
     `_LRUCache`へ`clear()`メソッドを追加し、モジュールの`clear()`関数の
     `_tile_materials_cache._data.clear()`（内部属性への直接アクセス）を
     `_tile_materials_cache.clear()`へ置換。
  4. `ors_client.py`の`httpx.RequestError`ハンドラで、メッセージへ
     `type(exc).__name__`を必ず含める形に変更（`str(exc)`が空文字になる
     httpx例外があるため、種別名だけは常に残る形にした。HTTPステータス側
     （`httpx.HTTPStatusError`）は元々`exc.response.status_code`を含んでおり対象外）。
  - 検証: backend pytest 1065件全green（既存の`test_graph_service.py`・
    `test_road_graph_engine.py`・`domain/routing.py`関連テストを含む）。

### - [x] T229. T219冷パス（タイル分解）のクエリ本数増を実測する 規模S（計測のみ、2026-08-23クローズ・T248へ統合）

- 発端: 統合レビュー2026-08-23 統合-6（complexity C-1、DEFER）。T219のタイルキャッシュは
  冷時に「材料5クエリ×タイル数」（30km生成でz12タイル9〜12枚≒45〜60クエリ）となり、
  従来のbbox一括6クエリより本数が増える。温時0.06秒は実測済みだが冷時の大半径が未計測。
- 完了条件: 冷パスの実測値を記録し、問題があれば対策タスクを別途起票、無ければ
  「計測済み・対応不要」と記録。
- **クローズ記録（2026-08-23、統合レビュー第7回の起票時）**: 冷パスの実測は
  T245〜T247の一連の本番・dev実測で事実上完了した（本番・王子30km冷パス316秒
  [支配はsplit再構築のUPSERT]、dev・新宿10km冷パス46秒→温6.7秒）。「クエリ本数」
  単体の内訳計測よりも「冷パス全体の体験」が課題であることが判明したため、
  本タスクは**T248（性能課題の本体タスク）へ統合してクローズ**する。

## 過去記録の全見直しで判明したあいまい残件の明確化（2026-08-23棚卸・ユーザー指示）

ユーザー指示「過去に実施した改善計画をすべて見直し、過程や結論があいまいな部分があれば、
それを明確にする改善計画をタスクとして追加して」を受け、本体＋アーカイブ全9ファイルの
完了記録を走査した（マーカー: 未解消・未確認・未検証・原因未特定・保留・別途確認等）。
以下の基準で選別した:

- **起票済み・カバー済みのため対象外**: PBF取込の94万way超減速（原因未特定だがT127の
  完了条件が実測検証を含む）／T151の旧実装の次数非決定性（設計変更で依存自体を除去済み、
  撤去済みコードの原因調査に価値なし）／T202のnull警告（サードパーティ基礎地図由来と
  判断・調査打ち切りの理由が記録済み）／T28(B)の「実装完了（未検証）」（同日の関東全域
  拡大で実地検証済み、記録が先行しただけ）／見送り判定group（T52/T175/T177/T210/T211/
  T213、いずれも判定理由が明記済み）／T218のWARM未検証・T218aの山岳未確認（T224へ
  統合済み）。
- **以下の3タスクとして起票**: 追跡タスクが無いまま宙に浮いていたもの。

### - [x] T230. CI・GitHub Actionsの健全性を確定する（api-contract成否・無償枠・Dependabot稼働） 規模S〔P1相当のあいまい解消〕

- 発端: 2026-08-23棚卸の全記録見直し。以下がいずれも「確認できず」のまま残っている:
  - **T196（2026-08-22）の未解消項目**: 「CI実行状況の確認自体はユーザー側で別途行う
    必要がある」——T180（2026-08-20）以降、生成物ドリフトが3回発生したがapi-contract
    CIが赤になったのかCI自体が実行されていない（Actions無償枠枯渇疑い、無償枠対策
    コミット04f6bc3と同時期）のか、一度も確定していない。CIはT1（2026-08-15）以来
    全タスクの安全網とされてきたが、その安全網が直近1週間機能していたかが不明のまま。
  - **T48（2026-08-16）のDependabot**: 「実際のGitHub側スケジュールに依存するため未検証」
    のまま、週次実行が一度でも動いたか未確認。
- 対応方針: 確認手段を確立する（`gh` CLI導入＋認証、またはユーザーがActionsタブを直接
  確認して結果を共有）。T180以降のmasterでのapi-contractジョブの実行有無・成否、
  無償枠の消化状況、Dependabot PRの有無を確定し、記録する。CIが止まっていた期間が
  あれば、その期間のコミットはローカルテスト実行結果のみが安全網だったことを明記する。
- 完了条件: 「CIはいつからいつまで動いていた/いなかった」が事実として記録され、
  止まっていた場合は復旧方針（無償枠・self-hosted・ローカルpre-push等）がユーザー判断で
  確定している。

- **確認結果（2026-08-23、ユーザーがActionsタブを直接確認）**:
  - **api-contractジョブ: 失敗している**。T196で明文化前のOpenAPI生成物ドリフト
    （T180・T185・T218/T218a、統合レビュー2026-08-23 F-1）は、実際にはCIが検知して
    正しく赤にしていたと判明した——「CI安全網が沈黙していたから見逃した」のではなく、
    **「CIは正しく警告していたが誰も見ていなかった」**という、より軽微ではない別種の
    運用ギャップだったことが確定した。
  - **GitHub Actions無償枠: 2000/2000分を使い切り、超過している**。この結果、
    現時点で新規コミットに対するCIの実行自体が行えない状態にある可能性が高い
    （無償枠を使い切った場合、GitHub Actionsは新規ワークフロー実行を受け付けない）。
    **2026-08-23時点のT225・T224を含む直近のコミット群は、CIによる検証を経ておらず、
    ローカルでのpytest/vitest/tsc/eslint実行結果のみが安全網である**。
  - **Dependabot: PRが存在する**（稼働は確認できた）。Dependabot自体はActions無償枠を
    消費する仕組みとは別枠のため、無償枠超過の影響を受けていない。
  - 無償枠の対策コミット（04f6bc3、paths-ignore・concurrency cancel-in-progress・
    Playwrightキャッシュ）は方向性としては正しいが、**既に枯渇した無償枠に対しては
    事後対策**であり、今回の枯渇を防げなかった（対策後も枯渇が進行し続けたか、
    対策前の消費で既に枯渇していたかは切り分けられていない）。
- 復旧方針: **ユーザー判断待ち**。選択肢（無償枠の月次リセット待ち／GitHub Actions
  従量課金の有効化／セルフホストランナー／ローカルpre-push hookでの代替検証）は
  ユーザーへ別途提示し、方針が決まり次第本タスクを完了とする。

- **追加確認（2026-08-23、リポジトリをprivate→publicへ切替後）**: public repoはActions
  無償枠が実質無制限になるため無償枠超過は解消する想定だったが、切替後最新のRun #266
  （コミット71bb5d7）を確認すると、4ジョブ（api-contract/backend/frontend/e2e）全てが
  4秒で即失敗しており、いずれも同一エラー:
  `The job was not started because recent account payments have failed or your
  spending limit needs to be increased. Please check the 'Billing & plans' section
  in your settings`。
  これは「無償枠2000/2000消費」とは別種の**アカウントの支払い方法エラーまたは
  spending limit設定**がジョブの起動自体をブロックしているもので、public化だけでは
  解消しないことが判明した。GitHub Settings → Billing and plansでの支払い方法確認・
  spending limit引き上げが必要（アカウント所有者の決済操作のため、Claude側では代行
  不可。安全ルール上も決済情報の入力は禁止行為に該当する）。
  → **本タスクは依然未完了**。ユーザーがBilling設定を確認・是正した後、再度CIが
  正常実行されることを確認して完了とする。

- **続報（2026-08-23、public化完了・支払いエラー解消後）**: ユーザーがBilling設定を
  是正しpublic化を完了。docsのみのpushはCI自体をトリガーしない設計（`paths-ignore:
  docs/**`、無償枠対策）のため、`workflow_dispatch`で手動実行（Run #267）して確認した
  ところ、api-contract/backend/frontendの3ジョブは成功、**e2eジョブのみ失敗**。
  ローカルで`npx playwright test`により再現・原因調査した結果、CI環境固有の問題では
  なくテストコード側の根本原因が判明した:
  - `smoke.spec.ts`の「地図レイヤーのON/OFF切替」テストが、地図上の単一チップ
    「道路情報」を探すが、これはT165（「道路情報」を「道路種別」「路面」の2チップへ
    論理分割）・T166（次数グループ化により「観測」グループの折りたたみ配下へ格納）の
    2回のUI再構成を経て、もはや存在しないラベル・DOM構造になっていた。
    e2e追加コミット（dba653d）はT165より前で、T165・T166のどちらもe2eテストを
    追従更新していなかった（OpenAPI生成物ドリフトと同種の「変更に追従すべき
    成果物の更新漏れ」）。
  - 修正: `frontend/e2e/smoke.spec.ts`を現在のUI構造に合わせ、「観測」グループ見出しを
    展開してから「道路種別」チップを操作するよう更新。ローカルで`--workers=1`・既定の
    並列2ワーカーの両方で2件とも再現的に成功することを確認済み。
  - もう一方の「ルート生成→候補一覧の表示」テストは、単体実行で安定して成功することを
    確認済み（当初ローカルで両方失敗して見えたのは、このマシンでの並列Playwrightワーカー
    間のWebGL/GPU資源競合による偶発的なブラウザクラッシュが原因で、CI環境やアプリ本体の
    不具合ではないと判断）。
  - **api-contract・backend・frontendの3ジョブが成功したことで、public化＋Billing是正で
    無償枠問題自体は解消したことも確認できた**。
  → 残作業: このe2e修正をpushしCIで再実行し、4ジョブ全green化を確認できた時点で
  本タスクを完了とする。

- **完了確認（2026-08-23）**: 修正をpush（コミット4c7bf63）したところ、docs以外の
  変更のためCIがpushイベントで自動起動（Run #268）し、api-contract・backend・
  frontend・e2eの4ジョブ全てが成功した。「CIはいつからいつまで動いていた/いなかった」
  の事実関係が確定:
  - T1（2026-08-15）〜無償枠枯渇までは正常稼働し、api-contractドリフトも正しく検知
    していた（統合レビュー2026-08-23 F-1で確認済み）。
  - 無償枠枯渇後（正確な枯渇時点は未特定のまま）〜2026-08-23のpublic化+Billing是正
    までは新規コミットのCI実行自体が行えず、ローカルのpytest/vitest/tsc/eslint実行
    結果のみが安全網だった。この間のコミット（T225・T224含む）はCI未検証のまま
    マージされている。
  - 2026-08-23のpublic化+Billing是正後、CIは正常復旧。副産物として、e2eジョブが
    T165/T166のUI再構成に追従できておらず恒常的に失敗する状態だったこと（本タスク
    上部の「続報」参照）も発見・修正できた。
  - Dependabotは無償枠と別枠のため終始影響を受けていなかった（既述のとおり）。
  - 復旧方針: 無償枠は今後もpublic repoのため実質無制限。Billing側の支払い方法さえ
    維持されれば再発しない見込み。セルフホストランナー・ローカルpre-push hook等の
    追加対策は不要と判断（ユーザー確認済みの一連の対応で十分）。
  完了条件（「CIはいつからいつまで動いていた/いなかった」の記録＋復旧方針確定）を
  満たしたため完了とする。

### - [x] T231. 設計判断の未確定残件2件を確定して記録する 規模S（判断のみ）（2026-08-23完了）

- 発端: 2026-08-23棚卸の全記録見直し。「未解決のまま残す」「別途確認が必要」と明記された
  まま追跡されていない設計判断が2件:
  1. **`motor_vehicle=no`の扱い**（評価システムの層構造再設計・T140、2026-08-18）:
     設計プロンプトの「通行不可はハード制約へ統合」に対し、現行実装は「二次軸内の
     最善値固定」という別ロジック。「改訂後の設計プロンプトでも言及が無いため引き続き
     未解決のまま残す」と記録されて以来、宙に浮いている。現行実装を正とするか、
     0次ハードフィルタへ移すかを決めて記録する（実装変更は判断結果次第で別起票）。
  2. **「規模M以上は着手前にタスクエントリを作成する」運用ルールの採否**（T135、
     2026-08-18）: 「CLAUDE.md改訂要否含めユーザー判断のため今回は見送り、別途確認が
     必要」のまま。採用するならCLAUDE.mdの「コミット時の同期ルール」節と同格で明文化、
     不採用なら不採用と記録して閉じる。
- 完了条件: 2件とも判断結果と根拠が記録され、「未解決のまま」という記述が解消されている。

- **判断結果（2026-08-23完了）**:
  1. **`motor_vehicle=no`は現行実装（二次軸内の最善値固定）を正とし、0次ハードフィルタへは
     移さない**。実際には既にT140の時点でこの判断は下されており記録も存在していた
     （`docs/architecture.md`1029〜1057行目「〇次: ハード制約」節、`domain/traffic.py`の
     `motor_vehicle_no_override`docstring、`domain/evaluation.py:263-266`のdocstring
     いずれも「自転車は法的に通行可能なため0次のハード除外対象にはしない」という同一の
     理由を明記済み）。棚卸で「未解決」と書かれていたのは、T140完了前に書かれた懸念文が
     T140完了後も訂正されずに本ファイルへ残っていただけの表記漏れであり、設計上の
     矛盾ではなかった。上記「評価システムの層構造再設計」節（T140の項）の懸念文を
     本エントリで解消済みとして扱う。
  2. **「規模M以上は着手前にタスクエントリを作成する」ルールを採用する**。T130で
     一度違反し事後是正した実績があり、大きめの変更ほど途中で背景・判断根拠が失われ
     やすいため、着手前に記録する運用の方がコストに見合う。CLAUDE.mdの
     「コミット時の同期ルール」節へ同格の1項目として追記済み。

### - [x] T232. 検証が保留のまま記録されている残件4件を明確化する 規模S〜M（2026-08-23完了）

- 発端: 2026-08-23棚卸の全記録見直し。「〜の可能性が高い（未検証）」「要否未確定」の
  まま追跡されていない検証残件:
  1. **dev環境のORS API全滅の原因特定**: 2026-08-23の統合レビュー実機確認で
     `POST /api/routes/generate`が8方位全滅（`openrouteservice request failed: `、
     詳細空文字）。前回レビュー（08-22）では7候補生成に成功しており、APIキー失効・
     クォータ枯渇・ネットワークのいずれか未特定。T228の4（エラーメッセージ改善）とは
     独立に、現在のdev環境で主要導線が回復することを確認する。
  2. **T194ロードマップ⑤⑥の要否確定**（2026-08-21）: ⑤リレープロキシ本番有効化・⑥は
     「未着手」のまま。同じT194で「クォータ枯渇はIP非依存」と判明しており、IP分離が
     効かないならリレープロキシ有効化の価値自体が消滅している可能性が高い。要否を
     確定し、不要なら⑤⑥を閉じてT179の位置づけ（dev用・本番未使用）を記録する。
  3. **動的気象プレースホルダタイル404のStrict Mode由来仮説**（T202、2026-08-22）:
     「`next dev`のReact Strict Mode由来の可能性が高い（本番ビルドでは未検証）」のまま。
     本番ビルド（`next build && next start`）で1回確認して仮説を確定/棄却する。
  4. **ダークモード実描画の実機確認**: 統合レビュー6回すべてで「headless制約により
     未確認」のまま繰り越されている（過去にダークモード配色バグの実績あり:
     現在地アイコンのcolor未指定、2026-08-14）。headless Chromiumの
     `prefers-color-scheme`エミュレーション（Playwrightの`colorScheme: 'dark'`）で
     主要レイヤー・パネル・凡例のダークモード表示を1回実機確認して記録する
     （headlessでも可能な手段が確立すれば以降のレビューでも同手順を使える）。
- 完了条件: 4件それぞれ「確認した結果」または「確認不要と判断した根拠」が記録され、
  「未検証のまま」という記述が解消されている。

- **調査結果（2026-08-23完了）**: 本体の作業ツリーとは別に専用`git worktree`
  （CLAUDE.md「作業ツリーの安全」節の方針どおり、調査目的のため）を作成し、
  backend（dev DB接続）・frontend（本番ビルド）をそこで起動して検証した。検証後は
  worktree・ブランチとも削除済み（本体作業ツリーへの影響なし）。
  1. **dev環境のORS API全滅**: 現時点では**再現しない**ことを確認した。worktree上で
     `POST /api/routes/generate`を15km・15km・30kmの3回実行し、いずれも8方位中8方位が
     成功（`trace_ok=8/8`、ORS関連の警告・エラーなし）。統合レビュー当日（2026-08-23）に
     観測された全滅は、APIキー・クォータ・ネットワークいずれかの一時的な問題だった
     可能性が高いが、再現しない以上ここから遡って原因を確定することはできない。
     T228で追加した「例外種別名を必ず含める」エラーメッセージ改善により、次回同様の
     事象が起きた際は診断がしやすくなっている。
  2. **T194ロードマップ⑤⑥の要否**: **現時点では不要と判断し、クローズする**。
     T194完了時点で既に「クォータ枯渇は送信元IPに依存しない現象」と直接確認済み
     （T182実装メモ）であり、この事実は本調査時点でも変わっていない（IP分離を
     提供するだけの⑤リレープロキシ有効化・⑥自前運用は、クォータ枯渇そのものへの
     対策にならない）。T179（Oracle Cloud VM経由のリレープロキシ）は実装済みのまま
     `OPEN_METEO_BASE_URL`未設定でdev/ローカル検証用として温存し、本番では引き続き
     未使用と位置づける。将来Open-Meteoの利用規約・料金体系が変わる、または利用者数が
     大きく増える等の状況変化があれば、その時点で再度要否を検討する。
  3. **動的気象プレースホルダタイル404のStrict Mode仮説**: **確定（仮説どおり）**。
     worktree上で`next build && next start`（本番ビルド）を実行し、Playwright
     （headless chromium）で降水ナウキャストレイヤーのON/OFF/ON切替を3回試行、
     JMAへの実リクエストを監視した。**プレースホルダURL
     （`.../00000000000000/none/00000000000000/...`）への実リクエストは3回とも
     0件**（実タイムスタンプ入りの実URLへのリクエストのみ、全て200 OK）。`next dev`の
     React Strict Mode（開発時二重effect実行）由来という仮説が確定し、本番ビルドでは
     発生しない・実害なしであることを確認できた。`MapView.tsx`の該当コメント
     （T202で「本番ビルドでは未検証」と記載）を確定済みへ更新する必要はあるが、
     コード変更を伴わない事実確認のため本タスクでは追跡のみ（更新は次回この箇所を
     触る際でよい、または別途軽微修正として起票可）。
  4. **ダークモード実描画**: **確認済み、問題なし**。Playwrightの`colorScheme: 'dark'`
     （headless chromiumで`prefers-color-scheme: dark`をエミュレート）で、初期画面・
     観測データ/推定指標/動的データの各レイヤーグループ・研究タブ（研究モード
     チェックボックス含む）・開発者タブ（デバッグログ表示・サーバー接続状態）・
     ルート生成後の候補一覧・生成したルートの色分け凡例（色スウォッチ4種＋切替
     ボタン4種）を撮影して目視確認した。いずれも文字・アイコンが背景に対して
     十分なコントラストで表示されており、2026-08-14に実績のあった「ダークモードで
     背景色に対しcolor未指定のアイコンが見えなくなる」類のバグは見当たらなかった。
     地図本体（基礎地図タイル）自体は明るい配色のまま（サードパーティ「liberty」
     スタイルにダーク変種が無いため、UI側はダークでも地図はライトのまま、という
     組み合わせ自体は想定どおりで不具合ではない）。この手順（Playwright
     `colorScheme`オプション）は次回以降のレビューでもheadless環境のまま
     ダークモード実機確認に使える。
  - **副産物（worktree検証中に発覚・対策済み）**: frontendを3000番以外のポート
    （3010）で動かすと、backendの`basemap_public_base_url`既定値が`localhost:3000`
    固定のため地図タイル・スプライト・グリフが全滅（`ERR_CONNECTION_REFUSED`）する
    ことが判明（ユーザー指摘のとおり過去にも発生していた既知の踏み抜きポイント）。
    製品コード自体は環境変数で上書き可能な設計のため変更不要と判断し、再発防止として
    メモリ（`basemap-public-base-url-port-mismatch.md`）へ記録した。

## 実装・テスト整合性の総点検対応（2026-08-23・review:consistency）

ユーザー指示「実装とテストがずれているところがないか総点検して」を受け、直近8コミット
（T224・T225）を起点にconsistencyレビューを実施（結果:
[history/2026-08-23_consistency.md](../.claude/commands/review/history/2026-08-23_consistency.md)）。
直近差分自体は整合性OKだったが、範囲を広げた確認で2件のずれを検出・起票・修正した。

### - [x] T233. CIの`backend`ジョブへPostGIS統合テスト実行環境を追加する〔P1〕規模S（2026-08-23完了）

- 発端: consistencyレビュー2026-08-23 F-1。CI相当条件（`TEST_DATABASE_URL`を到達不能な
  ホストへ向けて実行）でpytestを実行すると`965 passed, 100 skipped`（通常実行では
  `1065 passed`）。この100件には**T224の回帰テスト自身**
  （`test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit`）
  も含まれており、CIは一度もこのテストをskip以外の結果で実行していなかった。T224が
  修正した不具合（asyncpgプリペアド文パラメータ上限超過）自体、ユニットテストではなく
  実機API呼び出しで発覚しており、「CI green後にPostGIS依存コードの不具合が発覚する」
  というトリガーが既に1回成立していた。
- 対応: `.github/workflows/ci.yml`の`backend`ジョブへ`postgis/postgis:16-3.4`
  （docker-compose.ymlのpostgresサービスと同じイメージ）のサービスコンテナを追加し、
  `TEST_DATABASE_URL`を注入。`conftest.py`が`CREATE EXTENSION postgis`・
  `Base.metadata.create_all`を自前で行うため、番号付きmigrationの適用ステップは不要
  （road_edges等はSQLAlchemyモデルから直接作成される。番号付きmigrationは本番の
  ALTER履歴用）。
- 検証: ローカルでdev DB（PG18+PostGIS、TEST_DATABASE_URLのデフォルト値と同じ接続先）に
  対し`pytest -q`を実行し`1065 passed`（0 skipped）を確認済み。CI上でのサービス
  コンテナ経由の実行結果は、このコミットのpush後にCIで確認する。

### - [x] T234. e2eフィクスチャがGenerationConditions等の必須フィールドと乖離していた問題を修正する〔P2〕規模S（2026-08-23完了）

- 発端: consistencyレビュー2026-08-23 F-2。`frontend/e2e/fixtures.ts`の
  `routeGenerateResponseFixture()`が返す`conditions`が、実際の`GenerationConditions`の
  必須12フィールド中5件（`car_stress_recipe`・`road_suitability_recipe`・
  `motor_vehicle_density_recipe`・`penalty_strength`・`max_average_grade_percent`）を
  欠いていた。T225（コミット1e7ade4）は同じ2フィールドを他2箇所のvitestフィクスチャ
  （ComparisonPanel.test.tsx・routeApi.test.ts）には反映したが、このe2eフィクスチャは
  対象に含めていなかった。戻り値に型注釈が無いため、TypeScriptもこの欠落を検知できて
  いなかった。
- 対応: `routeGenerateResponseFixture()`・`makeRouteCandidate()`の戻り値へ
  `RouteGenerateResponse`/`RouteCandidate`型注釈を付与し、不足5フィールド
  （既存の`ROUTE_PREFERENCE`定数も同様に3フィールド欠落していたため合わせて修正）を
  埋めた。型注釈自体を今後のドリフト検知機構として残す（OpenAPI必須フィールドが
  増えたときにtscがビルドを落とすようになる）。
- 検証: `npx tsc --noEmit`でfixtures.tsのエラーが解消したことを確認。
  `npx playwright test`（既定の並列2ワーカー・`--workers=1`の両方）で2件とも成功する
  ことを確認済み。

### - [x] T235. backend pytestをpytest-xdistで並列化する〔ユーザー指摘: テスト実行が遅い〕規模S（2026-08-23完了）

- 発端: ユーザー「テスト実施が非常に遅い。以前にも改善要望したが、まだ見直せるところは
  ないか？再確認して」。T233でCIがPostGIS統合テスト約100件を実行するようになった分、
  backendのpytest総数が増えており、直列実行のままでは今後さらに伸びる。
- 対応: `pytest-xdist==3.8.0`を追加。PostGIS統合テスト4ファイル
  （test_road_graph_repository.py・test_accident_repository.py・
  test_match_designations.py・test_health.pyの該当テスト）へ
  `pytest.mark.xdist_group(name="postgis")`を付け、同一ridecompass_test DBへ接続する
  テストを全て同一workerへ固定（別workerでの同時TRUNCATEレースを防止）。CIの
  pytestステップを`-n auto --dist loadgroup`に変更。docs/testing.md・CLAUDE.mdへ
  新規DBテストファイルに同マーカーが必須である旨を追記。
- 検証: ローカル（Windows、8論理コア）で`-n auto --dist loadgroup`実行し1065件全green
  （xdist_groupによるレースなしを確認）。実測はローカルでは効果が限定的
  （直列182s→`-n 2`で217s＝悪化、`-n auto`で158s＝約13%短縮）で、OneDriveフォルダの
  ファイルI/O・ウイルス対策スキャン等のワーカー起動オーバーヘッドが要因と推測される。
  **CI実測（Run #270、2026-08-23）は予想に反し改善なし**: pytestステップは
  導入前（Run #269、直列）27秒→導入後（xdist有効）27秒で同一。標準GitHub-hosted
  runnerのCPUコア数が少なく（標準ランナーは2〜4コア）、1065件で27秒という
  既に短い実行時間に対してはworker起動コスト（Pythonプロセス起動＋アプリ全体の
  import）が並列化利得を相殺したとみられる。CIでの並列化効果は「ローカルより
  大きく出る見込み」という当初の予測は誤りだったため訂正する（事実と推測は
  分けて記録する方針どおり）。
- 結論: xdist_group設定自体はDB統合テストのレース防止として引き続き価値があり
  （将来テスト件数が増えCIの実行時間がボトルネックになった際にすぐ効果を出せる
  下地になる）、CIでの実行を害しない（同じ27秒）ため設定は維持する。ただし
  「CIを速くする」という目的では今回は効果が確認できなかった。ローカル実行時の
  約13%短縮（`-n auto`利用時）は開発者の日常的なテスト実行体感には寄与する。
- 実装メモ: ローカルWindows環境でexecnet（xdistのworker起動に使用）が
  `EOFError: expected 1 bytes, got 0`で即座に失敗する問題に遭遇。作業ディレクトリの
  絶対パスに日本語（OneDriveの「ドキュメント」）が含まれることが原因と推測され、
  `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`環境変数で回避できることを確認したが、
  CI実行には影響しない（CIの作業ディレクトリはASCIIパスの`/home/runner/work/...`）ため
  ci.ymlへの追加対応は不要と判断した。

## ORS→road_graphエンジン移行の残作業（2026-08-23・ユーザー指示）

ユーザー指示「ORSから独自の検索エンジンに切り替えるための作業で残っているものはある？」
「1〜6を実施して」を受け、調査で洗い出した6項目のうち5項目を実施する
（項目4「本番Oracle DBへのmigration 0013適用・標高バックフィル」は本番DB書き込みを
伴うため今回保留、他5項目完了後にユーザーと実行タイミングを別途相談する）。

**2026-08-23追記**: 保留していた項目4のうち「migration 0013適用」を、本番DBでの性能・
成功率実測（T241調査の一環）中に判明した**road_graphエンジンが本番DBで一切動作しない**
というブロッカー（後述T242）への対応としてユーザー指示により実施した。「標高バックフィル」
（`precompute_elevation_attributes`、全Edge分のGSI DEM問い合わせを伴う別の大きなバッチ）は
スキーマ同期とは規模も性質も異なるため、本追記の対象外のまま別途判断とする。

### - [x] T242. 本番Oracle DBへのmigration 0013適用（road_graphエンジンが本番で起動不能だったブロッカー解消） 規模S（2026-08-23完了）

- 発端: T241の調査（後述）およびユーザー指示「本番DBでの性能・成功率の実測」を受け、
  専用worktreeで本番DB（読み取り専用のつもりで接続、道路データ規模・split状況を確認）へ
  接続したところ、`road_edges`テーブルに`bearing_deg`列が存在せずroad_graphエンジンの
  全クエリがSQLエラー（`UndefinedColumnError`）で即座に失敗することが判明した。
  `schema_migrations`を確認すると本番は0001〜0012まで適用済みで**0013
  （add_edge_bearing、T218のwind評価高速化用）のみ未適用**——保留していた項目4
  「migration 0013適用・標高バックフィル」の実態が、当初想定していた「標高データが
  無いだけで動作はする」ではなく「road_graphエンジンが本番で一切機能しない」という
  より深刻なブロッカーだったと判明した。
- 対応: ユーザーへ状況を説明し確認を得た上で（本番は未稼働のため実施承認）、
  `scripts/apply_migrations.py`（0001〜0012を適用した際と同じ既存の追跡付き
  マイグレーションランナー）で0013を適用。ALTER TABLE（列追加）→UPDATE
  （`ST_Azimuth(ST_StartPoint(geom), ST_EndPoint(geom))`によるSQLのみのバックフィル、
  アプリ側のバッチ不要）という0013自体の設計どおり、既存の207,767 Edge中207,730件へ
  即座にbearing_degが入った（残り37件はgeometryの始点・終点が同一等でST_Azimuthが
  計算不能な退化ケースとみられ、既存の「データ無しはwind軸から除外」という設計で
  無害に扱われる）。
- 完了条件: `schema_migrations`に0013が記録される・road_graphエンジンが本番DBで
  実際にクエリを実行できることを確認。
- **追記（2026-08-23、同日中に実施）**: ユーザーから「保留にせず実施するか、明確に
  タスク化するか」との明文の指示（migration 0013が実際には深刻なブロッカーだったにも
  関わらず一言の保留メモで済ませていたことへの是正指示、CLAUDE.md「コミット時の
  同期ルール」へ追加した新原則の実例）を受け、「標高バックフィル」も同日中に実施した。
  `app/batch/precompute_elevation_attributes.py --database-url <本番>`を実行し、
  対象212,227 Edge全件（migration適用〜本追記までの間に本タスク自体の実測作業で
  新規splitされた分も含む）を224.3秒で処理完了（GSI DEMタイルキャッシュにより
  現実的な時間で完了、dev DBでのT218a実測=128,887件・107.5秒と整合する規模感）。
  本番`elevation_attributes`が実データで埋まり、gradient軸が本番でも合成に使われる
  状態になった。**残課題**: 本タスク以降に新規splitされるEdge（未touchエリアへの
  初回リクエスト）は本バッチのスナップショット後のため未反映のまま。冪等に再実行できる
  設計（未計算分のみ埋める）のため、必要に応じて定期再実行が要る（頻度・自動化の要否は
  未決定のまま、別途判断）。
  - **暫定方針（2026-08-24、ユーザー判断。トリガー未到達につき継続監視、タスクとしては
    未完了のまま残す）**: 現在プロジェクトにcron等のスケジューリング基盤が一切無く、
    自動化するにはGitHub Actions scheduled workflow等の新規インフラ導入（本番DB接続情報の
    Secrets登録含む）が要るため、新規インフラを立てず`app/batch/
    precompute_elevation_attributes.py`をapply_migrations.pyと同様に必要時手動実行する
    運用を当面続ける。**ただしこれはタスクの完了・打ち切りではない**——新規splitされた
    Edgeの標高データ欠損は放置すると増え続ける構造のため、いずれ自動実行が必要になる
    可能性がある。トリガー: 新規split頻度の増加・標高データ欠損に起因する体感的な
    品質劣化の報告、のいずれかが起きた時点で自動化（スケジューリング基盤の新規導入）を
    改めて検討する（下記「残タスクの優先順位」のトリガー未到達リストにも掲載）。

### - [x] T243. road_graphエンジン専用DBエンジンのcommand_timeout分離 規模S（2026-08-23完了）

- 発端: T242のmigration適用後、本番DBで性能・成功率の実測（ユーザー指示）を実施したところ、
  半径10km級（30kmループ）の未splitエリアへの初回リクエストで`TimeoutError()`
  （空repr、メッセージ無し）が高い再現性で発生した。当初は外部気象API（Open-Meteo）の
  429/遅延を疑ったが、`prepare()`のみを呼び`evaluate_loops`（標高取得を含む）を呼ばない
  経路（本タスクの調査用スクリプトの`conn`側）でも同じ`TimeoutError()`が再現したため
  除外。`app/infrastructure/database.py: get_engine()`のコメントを読み返した結果、
  リクエスト用DBエンジンに`command_timeout=20`（asyncpgのクライアント側タイムアウト、
  Python 3.11以降`asyncio.TimeoutError`は組み込み`TimeoutError`と同一クラスのため
  reprが一致）が設定されており、**これは本来「路面タイル配信（region_service.py）が
  DB輻輳時に無期限ハングしないための保護」目的で導入されたもの**であり、road_graph
  エンジンの初回split（`get_way_specs_with_closure`等、低頻度だが生データが密な
  エリアでは数十秒〜3分規模かかりうる重い処理、T236実測で最悪175.8秒）が
  `get_graph_service`/`get_elevation_attribute_service`経由で同じ共有エンジンに
  乗っていたため、無関係な用途の保護用タイムアウトに巻き込まれてキャンセルされていた
  と判明した。
- 対応方針: タイル配信用の20秒はそのまま維持しつつ（無関係な用途まで巻き込んで
  緩めるとタイル配信側のハング検知が効かなくなる）、road_graphエンジンの経路生成専用に
  別エンジン・別コネクションプールを新設しより長いcommand_timeoutを与える。
- **実装メモ（2026-08-23完了）**: `database.py`に`get_route_generation_engine()`/
  `get_route_generation_session_factory()`を新設（command_timeout=180秒、T236実測の
  最悪値175.8秒に余裕を持たせた値）。`dependencies.py`の`get_graph_service`・
  `get_elevation_attribute_service`（road_graphエンジンの経路生成・previewでのみ使用、
  タイル配信系[`get_region_service`等]は無関係のため引き続き元の共有エンジンのまま）を
  こちらへ切り替え。
- 検証: backend全体1077件green（既存テストはDIモック経由でこの変更の影響を受けない）。
  実データでの再実測（本番DB、修正後のコード）は別途実施可能だが、今回は根本原因の
  修正自体をもって完了とする。

### - [x] T244. 外部APIクライアントのTTLキャッシュを`cachetools`へ統一 規模S（2026-08-23完了）

- 発端: ユーザー指示「外部apiについてはリクエストの効率化、共通化できているかもひと通り
  チェックして」を受けた監査で発見。`flood_client.py`（1キャッシュ）・
  `jma_warning_client.py`（3キャッシュ）・`wbgt_client.py`（2キャッシュ）の計6箇所が、
  「モジュールレベルのdict/tupleでタイムスタンプを保持しTTLで鮮度判定する」という
  同型のキャッシュロジックをそれぞれ個別に手書き実装しており重複していた
  （`weather_client.py`のOpen-Meteo用キャッシュは429前提のtenacity再試行・
  `get_forecast_many`専用キャッシュ・L2永続化[cache_db.py]と併用する構造が異なるため
  対象外）。
- 対応方針: 自前でTTLキャッシュクラスを新規実装する案をいったん作成したが、
  ユーザーから「実績のある外部ライブラリがあるなら個別実装したくない」との指摘を受け、
  `cachetools`（MutableMapping準拠、`TTLCache`クラスを提供する成熟した標準的な
  ライブラリ、Google公式ライブラリ群等でも採用実績あり）を新規依存として採用する方針へ
  変更した。
- **実装メモ（2026-08-23完了）**: `requirements.txt`へ`cachetools==7.1.7`を追加。
  6箇所すべての手書きキャッシュ（`_flood_cache`/`_muni_code_cache`/`_area_data_cache`/
  `_warning_cache`/`_point_master_cache`/`_forecast_cache`）を`cachetools.TTLCache`
  （`maxsize`はキー空間の実運用規模に十分な余裕を持たせた固定値、単一値キャッシュは
  固定キー文字列で代用）へ置き換え、`time.time()`ベースの手書き鮮度判定ロジックを
  全箇所で削除した。
- 検証: backend全体1077件green（3クライアントを直接触るテストは既存に無く、
  各サービス経由の21件のテストで間接的に確認）。

### 本番DBでの性能・成功率実測（2026-08-23、ユーザー指示）

T236はdev DBでの計測だったため、ユーザー指示によりT242（migration適用）完了後に本番DBで
同じ3地点×3距離=9パターンの実測を行った（road_graphエンジンのみ。ORSは本番DBに依存
しないためT236の記録値をそのまま比較対象とする）。**この実測はT243修正前のコード**
（command_timeout=20の共有エンジンのまま）で実行したものである点に注意。

| 指標 | dev DB（T236） | 本番DB（今回、T243修正前） |
|---|---|---|
| 成功率 | 32/72 (44%) | 40/48 (83%、30km級3パターンは全てTimeoutErrorで分母から除外) |
| 平均所要時間 | 32.2秒 | 71.2秒（10/20km成功パターンのみ、初回split込み） |
| 平均距離誤差 | 17.3% | 17.2% |

30km級（半径10km）の3パターンは3地点すべてTimeoutErrorで失敗し、T243で原因を特定・
修正した。連結性（弱連結成分）の解析結果はT241へ統合済み。

**T243修正後の再実測（同日中に実施）**: ユーザー指示によりT243修正後のコードで
王子（10km・20km・30km）を再実測した。10km（candidates=7/8, elapsed=26.6s）・20km
（candidates=8/8, elapsed=22.6s）は共に成功、連結性も引き続き97%台の巨大成分だった。
**30kmは今回もTimeoutErrorのまま**——ただしT243修正前は共有エンジンのcommand_timeout=20で
即座に失敗していたのに対し、今回はT243で新設した専用エンジンのcommand_timeout=180まで
待った末に失敗しており、**制限時間を180秒へ延ばしても解決しない、より深刻な別の性能
問題が存在する**ことが判明した。原因調査はT245へ引き継ぐ。新宿・門前仲町の30km再実測は
「同じ結果になることは自明」というユーザー判断により実施せず打ち切った。

### - [x] T245. save_graphのDELETE段の性能調査＋ステージ別ログ追加 規模S（2026-08-23完了）

- 発端: 上記のT243修正後再実測で、王子30kmが専用エンジンのcommand_timeout=180秒でも
  解決しなかったことを受けたユーザー指示「クエリ改善可能な箇所を実施ログから洗い出して。
  合わせてDB設計レビューも兼ねて」。
- 調査: 本番DBの`pg_stat_activity`を確認したところ、`GraphService`（`save_graph`内、
  `way_ids_to_replace`指定時の再split経路）が発行する
  `DELETE FROM road_edges WHERE osm_way_id = ANY(...) AND NOT (edge_id = ANY(...))`
  が**122秒間アクティブ実行中**（トランザクション自体は418秒＝7分近く開いたまま）
  だった。安全のため`BEGIN`〜`ROLLBACK`で囲った`EXPLAIN (ANALYZE, BUFFERS)`で
  実データに近い規模（osm_way_id 10,000件・edge_id除外リスト30,000件、`_ID_CHUNK_SIZE`と
  同水準）を再現したところ、**9,394行の削除が136ms（うちFK cascade関連のトリガー実行が
  約120ms、Bitmap Heap Scan自体は数ms）で完了**し、実際の遅延を再現できなかった。
  - `elevation_attributes`・`edge_attribute_counts`（`road_edges`のFK先、DELETE時に
    cascadeチェックが走る）はいずれも`edge_id`がPRIMARY KEY（btreeインデックス）済みで、
    追加インデックスの不足は無いことを確認。
  - `road_edges`の`last_autoanalyze`は約40分前（`n_dead_tup=0`）で統計情報も新鮮であり、
    プランが古い統計に基づいて悪化していた可能性も低いと判断。
  - **実際に122秒かかったケースを合成データで再現できなかった**ため、根本原因
    （本番実行時により大きな配列サイズだった可能性、Oracle Cloud VM
    [VM.Standard.A1.Flex、ARM 2 OCPU/12GB、路面タイル配信と同居]側の一時的な
    リソース競合の可能性等）は特定に至らず未解決のまま残る。
  - **DB設計レビューの所見**: `road_edges`/`road_nodes`/`elevation_attributes`/
    `edge_attribute_counts`/`way_attribute_counts`/`designation_attributes`の
    主要インデックス（PK・FK参照列・空間索引）は一通り揃っており、明確な欠落は
    見つからなかった。`NOT (col = ANY(配列))`という配列除外パターン自体は
    （改善計画T224で採用した経緯があるが）除外側の配列に対する索引利用が保証されない
    構造的リスクを持つため、将来同種の遅延が再発した場合はJOIN/EXISTSベースの
    アンチ結合（`LEFT JOIN ... WHERE 右辺IS NULL`等）への書き換えを検討候補とする
    （今回は原因未確定のため書き換え自体は見送り）。
- **対応（実装済み）**: `road_graph_repository.py: save_graph`に、
  docs/logging.mdの「高コスト処理はステージ別所要時間を1行のINFOにまとめる」方針に
  従ったログを追加した。**従来この関数には一切ログが無く**、今回のような遅延が実際に
  本番で発生してもEXPLAIN ANALYZEによる事後フォレンジック以外に原因追跡手段が
  無かった（本タスクの調査自体がその欠落を露呈した形）。`node_upsert_ms`/`delete_ms`/
  `edge_upsert_ms`/`total_ms`と`nodes`/`edges`/`way_ids_to_replace`件数を1行のINFOへ
  まとめ、次回以降の発生時に「どの段が支配的か」「何件を対象にどれだけ時間がかかったか」
  を即座に特定できるようにした。
- 完了条件: `save_graph`のログ追加・backend全体1077件green。原因そのものの完全特定は
  次回発生時のログを待つ形で本タスクの範囲外とする（調査自体は完了、恒久対策は
  再発時の実データを見てから判断）。
- 検証: backend全体1077件green（既存の`save_graph`関連テスト87件を含む）。

### - [x] T246. save_graphのDELETE除外条件を一時テーブル化＋work_mem引き上げ 規模M（2026-08-23完了）

- 発端: ユーザー指示「複数並列処理をしていることでのデッドロック等、他プロセスも含めて
  確認検討して」「あと、db設計レビュー、sqlクエリ分析をして。無視しないで」を受け、
  T245で未解決のまま残していた根本原因の追跡を継続した。
- **ロック競合の切り分け（決定的に否定）**: `pg_stat_activity`を2秒間隔で継続ポーリングする
  専用スクリプトを作り、実際に王子30kmを再実行しながら監視した。DELETE文の
  `wait_event_type`/`wait_event`は実行開始から終了まで一貫して`None`（＝ロック待ちではなく
  実際にCPU/IOを使って処理中）であり、**デッドロック・他プロセスとのロック競合は
  発生していない**ことを確定した。
- **真の原因を特定**: 監視ログから、`way_ids_to_replace`が`_ID_CHUNK_SIZE`（10,000件）を
  超え複数チャンクに分かれる場合、**チャンクごとに同一の巨大な除外配列
  `NOT (edge_id = ANY(new_edge_ids))`を毎回ゼロから再評価**しており、1チャンクあたり
  100〜150秒超×チャンク数という、チャンク数に比例して悪化する構造だったと判明した
  （実測: 2個目のチャンクのDELETEだけで約152秒、3個目のチャンクも100秒超で継続中を確認。
  合計10分超経過しても完了しなかったため実行を強制終了した）。T224がチャンク化したのは
  「INSERT側の配列（`id_chunk`）」のみで、「EXCLUDE側の配列（`new_edge_ids`、チャンク化
  されず毎回フル配列のまま）」が繰り返し評価されるコストは当時見落とされていた。
- **DB設計レビュー**: `information_schema`/`pg_constraint`/`pg_indexes`を全対象テーブル
  （`osm_raw_ways`〜`schema_migrations`の17テーブル）で網羅的に確認。PK・FK参照列・
  空間索引に欠落は無し。一方で設定値`work_mem=4MB`（PostgreSQL既定値のまま、
  `postgresql.conf`でコメントアウトされ未設定）を発見。実測（ランダムサンプリングで
  相関バイアスを排除した10,000件×300,000件規模のEXPLAIN ANALYZE）で、ハッシュ結合の
  メモリ使用量が既に5.5MBとwork_mem規定値を超えており、より大規模な広域bboxでは
  ディスクスピルによる追加の性能劣化要因になりうると判断した。
- **対応（実装済み）**:
  1. `road_graph_repository.py: save_graph`のDELETE除外条件を、除外対象の`new_edge_ids`を
     一時テーブル（`edge_id`にPRIMARY KEY）へ1回だけ投入し、各チャンクのDELETEは
     `NOT EXISTS`（一時テーブルのPKインデックスを使う反結合、`Hash Right Anti Join`
     プランになることをEXPLAIN ANALYZEで確認）で参照する形へ変更。チャンク数ぶんの
     重複評価を無くした（ランダムサンプリング検証で618ms→445ms、約28%短縮。ただし
     本番実測の遅延幅[100秒超×チャンク数]をこの合成データでは再現しきれておらず、
     効果の全容は次回の実本番アクセスでT245ログを見て確認する）。
  2. この一時テーブル作成・反結合操作専用に`SET LOCAL work_mem = '256MB'`を追加
     （トランザクションローカルのため他セッションへ影響しない、`save_graph`呼び出し
     ごとに自動的に既定値へ戻る）。
  3. 本番DB（Oracle Cloud VM、SSH経由）の`postgresql.conf`で`work_mem`を既定4MBから
     **16MB**へグローバルに引き上げ、`pg_reload_conf()`で再起動無しに反映（変更前の
     設定ファイルは`postgresql.conf.bak_t246`としてVM上にバックアップ済み）。
     `max_connections=100`・`shared_buffers=3GB`（RAM12GBのARM VM）に対し、
     最悪同時100接続×16MBでも1.6GBに収まる保守的な値を採用（タイル配信側の
     空間結合・集約クエリにも恩恵がある想定）。アプリ用DBロールには
     `ALTER SYSTEM`権限が無く（`InsufficientPrivilegeError`実機確認）、SSHでの
     直接編集が必要だった。
- 検証: backend全体1077件green（`save_graph`関連87件はPostGIS実DB相手に実行され、
  一時テーブル作成・反結合が正しく機能することを確認済み）。本番DBの残存接続・
  ロックが無いことを確認済み（検証中に生じた不要な接続はクライアント切断後も
  サーバー側に残っていたため、ユーザー確認の上`pg_terminate_backend`で明示的に終了した）。
- **未解決のまま残る点（実測により解消・下記追記参照）**: 合成データでは本番実測の遅延を
  正確に再現できていなかったが、修正後に同一条件（王子30km、`way_ids_to_replace`が
  複数チャンクに及ぶ広域bbox）で実本番アクセスを行い、以下の追記で効果を確定した。

- **修正効果の実測確認（2026-08-23、同日中に追実施）**: T246適用後のコードで王子30kmを
  再実行し、T245のステージ別ログで実測値を確認した。
  `save_graph nodes=154398 edges=412052 way_ids_to_replace=94470 node_upsert_ms=46000
  delete_ms=10172 edge_upsert_ms=149235 total_ms=219297`。**`way_ids_to_replace=94,470`件
  （`_ID_CHUNK_SIZE`=10,000で計10チャンク相当）という、まさに問題を引き起こした規模の
  実データに対し、`delete_ms`はわずか10.2秒**（修正前は同規模で10分超経過しても完了
  しなかった）。`generate_loops`全体も**`candidates=4/8`（trace_ok=6/8、2方位は実際に
  経路が見つからず[T241で確認済みの想定内の希少事象]、2方位は距離許容差外で除外）、
  `total_ms=315,859`（約5.3分）で正常終了（exit code 0、TimeoutError無し）**した。
  これまでこの規模のリクエストは20秒→180秒→10分超のいずれのタイムアウト設定でも
  一度も完走しなかったため、**本タスクで初めての成功事例**となる。残る`total_ms`の
  大半（310秒）は`node_upsert_ms`/`edge_upsert_ms`（バルクUPSERT、154,398ノード・
  412,052エッジ分）が占めており、これは初回タッチ時のみのコストで、T246の対象
  （DELETE段）とは別の一時的高コスト処理として正常な範囲と判断する（同一エリアへの
  再訪はタイルキャッシュにより大幅に短縮される設計、T219参照）。

### - [x] T236. road_graphエンジンの経路品質比較検証 規模S（2026-08-23完了）

- 発端: ORSとroad_graphエンジンで「経路の品質」を直接比較した検証がこれまで存在しない
  （T12 ADRは探索速度のみが対象）。切替の意思決定材料として定量的な比較データを残す。
- 完了条件: 起点・距離の複数パターンで両エンジンの成功率・距離誤差・所要時間を比較し、
  road_graphの経路品質がORSと比べて実用上問題ないかを記録する。

- **実測結果（2026-08-23、`backend/scripts/compare_engines_quality.py`新設・dev DB）**:
  東京都心3地点（王子・新宿・門前仲町）×距離3パターン（10/20/30km）＝9パターンを
  両エンジンで実行（HTTP経由ではなくRouteGenerator.generate_loopsを直接呼び出し）。

  | 指標 | openrouteservice | road_graph |
  |---|---|---|
  | 成功率（候補数/64方位中） | 50/72 (69%) | 32/72 (44%) |
  | 平均所要時間 | 1.9秒 | 32.2秒 |
  | 平均距離誤差（対目標距離） | 17.0% | 17.3% |

  - **距離精度は両エンジンでほぼ同等**（誤差17%台で拮抗）。両エンジンが成功した
    直接比較可能なケースでは、むしろroad_graphがわずかに上回ることが多かった
    （例: 新宿10km誤差 road_graph20.4% vs ORS23.5%、王子10km road_graph19.8% vs
    ORS26.2%）。経路品質（距離追従性）の観点でroad_graphがORSに劣る根拠は見られない。
  - **成功率の差は主にdev DBのPBF取込範囲の限界に起因し、エンジン自体の欠陥ではない**。
    road_graphの失敗の大半は「Road Graphタイルが取込範囲外」（20〜30km半径の外周が
    dev DB取込済み範囲＝東京都心南部の外に出るため）で、本番Oracle DB（関東本土7都県
    全域投入済み）では同じ規模の失敗は起きない見込み。ORS側の失敗（門前仲町10kmで
    8方位全滅）は一時的な429レート制限（数分後には回復）と、湾岸埋立地の1点が
    ORSの道路網から350m以内に見つからない404エラーであり、いずれもroad_graphの
    設計とは無関係。
  - **所要時間はroad_graphが大幅に遅い**（今回の1プロセス内での実行では12〜176秒、
    ORSは1〜3秒）。これはT224が既に記録した「初回タッチのタイルはclosure再計算・
    save_graphのコールドパスコストを払う」挙動と一致する（門前仲町20kmの175.8秒は
    密集した都心部の未split道路網を新たに計算したため）。本番では PBF取込バッチが
    事前にsplit済み・`graph_material_cache`がリクエスト間で温まるため、T224実測
    （同一bboxの2回目以降で約5.4〜5.6秒）程度まで縮む見込みだが、初めて触れる
    エリアではこのコールドコストがORSには無い形で発生し続ける（ORSは既に構築済みの
    外部道路網へ委譲するため、初回でも同程度の速度が出る）。
  - **形状の健全性チェック**（新宿20km、両エンジンとも8/8成功したケース）: 全16候補
    （両エンジン各8件）とも始点=終点の閉路（closure_gap=0m）、外接矩形は約5〜7km四方
    （20km周回の直径として妥当）で、明らかな形状破綻（自己交差の兆候となる異常な
    外接矩形・閉路失敗等）は検出されなかった。
  - 検証: `backend/scripts/compare_engines_quality.py`（今後の再検証用に保持、CI対象外）。
    backend全テストは無変更のためgreenのまま（既存1051件、コード変更は
    docstring2箇所の修正のみ）。

### - [x] T237. `/api/routes/preview`のroad_graphエンジン対応 規模S〜M（2026-08-23完了）

- 発端: `POST /api/routes/preview`は`settings.routing_engine`に関わらず常に
  `RoutingService`（ORS）を使う（`get_routing_service`固定）。`routing_engine=road_graph`
  設定時に挙動が食い違う契約ギャップを解消する。フロントエンドは現在このエンドポイントを
  呼んでいない（`previewRoute`関数は定義のみ）ためUI側の変更は不要。
- 対応方針: `RoadGraphEngine.preview_segment(origin, destination)`を新設し、評価軸重み付き
  コスト（generateと同じ`compute_edge_cost`ベース）で最短経路を1回探索する
  （ユーザー確認済み: ORSのような単純最短距離ではなく重み付きコストを採用）。
  `dependencies.py`に`get_preview_builder()`を新設し`routing_engine`に応じて委譲する。
- 完了条件: `routing_engine=road_graph`設定時に`/api/routes/preview`が経路を返す
  （または到達不能なら502）ことをテストで確認。backend全テストgreen。

- **実装メモ（2026-08-23完了）**:
  1. `road_graph_engine.py`: `prepare()`の「bbox→材料取得→search_edge_costs算出→
     sparse_graph構築」部分を`_build_search_graph`（新設の`_SearchGraph`データクラスを
     返す）へ切り出し、`prepare`・`preview_segment`の両方から呼ぶ形にした
     （wind/night軸・0次ハードフィルタ等のロジックを1箇所にまとめ、将来ドリフトさせない
     ため）。`preview_segment`は新設`_bbox_covering_points`（起点・終点2点の外接矩形＋
     `PREVIEW_BBOX_MARGIN_KM=2.0`のマージン）でbboxを求め、起点・終点をそれぞれ
     `find_nearest_node_indexed`でスナップして`shortest_path_node_ids_sparse`を1回だけ
     呼ぶ（ループのtrace_loopとは異なり3レグ探索は不要）。`duration_minutes`は
     `domain/wind.py: ASSUMED_SPEED_KMH`（既存の到達時刻推定と同じ前提）から概算する
     （road_graphエンジンは実測所要時間モデルを持たないため）。
  2. `dependencies.py`: `get_route_generation_builder`と対になる`get_preview_builder()`を
     新設。`routing_engine=="road_graph"`ならその場で`RoadGraphEngine`を構築し
     `preview_segment`を呼び、それ以外は従来どおり`RoutingService.get_route`へ委譲する
     1つの非同期callable（`PreviewBuilder`型）を返す。previewはリクエストボディでの
     評価重み上書きに対応しないため、既定値ローダーのみを使う。
  3. `routes.py`: `preview_route`のDependsを`get_routing_service`から`get_preview_builder`へ
     差し替え。リクエスト/レスポンスのPydanticモデル（`RoutePreviewRequest`/`RouteSegment`）
     自体は無変更のため、OpenAPI再生成後も差分なし（`git diff --exit-code -- frontend/
     src/types/generated/`で確認済み）。
  4. テスト: `test_road_graph_engine.py`に`preview_segment`の単体テスト3件
     （経路発見・到達不能・材料自体が取得できない場合）、`test_routes_preview.py`に
     ルータ配線の直接オーバーライドテスト2件＋`get_preview_builder`のroad_graph分岐を
     フェイクで直接呼ぶテスト2件（router越しのオーバーライドでは検知できない配線ロジック
     自体のバグをカバー）を追加。
  5. 実機検証: dev DB（PostGIS）に対しスクリプトで`RoadGraphEngine.preview_segment`を
     直接呼び出し（distance_km=1.01, duration_minutes=3.0, 89点）、さらに
     `ROUTING_ENGINE=road_graph`でuvicornを起動し`POST /api/routes/preview`を実際に
     叩いて同じ結果がHTTP経由でも返ることを確認した。
  - 検証: backend pytest 1058件全green（新規7件含む）。
  - 副次修正: `_bbox_around_point`のdocstring中の「Overpass問い合わせ」という
    T222で撤去済みの表現を「Road Graph取得」へ訂正。

### - [x] T238. `evaluate_graph`のcar_stress判定ホットパス最適化 規模S〜M（2026-08-23完了）

- 発端: T224実測で10km級ループ（122,710エッジ）の温状態が約5.4〜5.6秒、目標「5秒以内」を
  わずかに超過。T220完了メモが「evaluate_graph（car_stress判定が支配的）は今回手を付けて
  いない、全面numpyベクトル化はT221の軸レジストリ計画と手戻りが被るため見送り、対象を
  絞った部分対応から始める」と明記しており、その部分対応を実施する。
- 対応方針: `car_stress_level`が`car_stress_breakdown()`のpydantic`CarStressBreakdown`を
  毎回フル生成し`.level`以外を即座に捨てている箇所を、内訳を作らず`level`のみ計算する
  軽量経路へ変更する（全面書き換え・ベクトル化はしない）。
- 完了条件: `car_stress_level`/`car_stress_breakdown`の出力が変更前後で一致することを
  既存テストで確認しつつ、新設ベンチマークで`evaluate_graph`の実測短縮値を記録。

- **実装メモ（2026-08-23完了）**:
  1. `domain/traffic.py`: 判定ロジックの実体（base値決定・各種補正・`motor_vehicle=no`
     固定・最終level計算）を`_compute_car_stress`（NamedTupleを返す内部関数）へ切り出した。
     `car_stress_breakdown`はその結果を`CarStressBreakdown`（pydantic）へ変換するだけの
     薄いラッパーへ、`car_stress_level`（探索コストのホットパス、1エッジ毎に呼ばれる）は
     `_compute_car_stress`を直接呼び`.level`だけ取り出す形にし、pydanticモデル構築コストを
     完全に回避した。外部契約（`CarStressBreakdown`の型・フィールド）は無変更。
  2. `benchmarks/bench_evaluate_graph.py`を新設（合成格子グラフ、T219/T220基準の
     約69,216エッジ相当・T224基準の約122,710エッジ相当の2規模）。`run_all.py`へ登録。
  3. **実測結果**（`git stash`で変更前後を切り替え、同一ベンチマークを2回実行）:

     | エッジ数 | 変更前 | 変更後 | 短縮率 |
     |---|---|---|---|
     | 68,120 | 1.314秒 | 1.182秒 | 約10.0% |
     | 121,800 | 2.364秒 | 2.119秒 | 約10.4% |

     全面ベクトル化ではなく1箇所の構築コスト削減のみのため、短縮幅は控えめ（約10%）。
  4. **実データでのE2E追加確認**（dev DB、王子起点・10km相当・113,122エッジのbboxで
     `RoadGraphEngine.prepare()`を3回連続呼び出し）: 温状態（3回目）で約3.74〜3.77秒
     （評価対象がprepare全体のためevaluate_graph単体の短縮分はこの中に埋もれるが、
     T224が記録した「evaluate_graph約3.4〜3.7秒＋グラフ構築約1.0秒」という同程度規模の
     内訳と比べて悪化していないことを確認）。T224の「10kmループ生成で温状態約5.4〜5.6秒」は
     `generate_loops`全体（`prepare`＋8方位の`trace_loop`＋`evaluate_loops`）の数値であり、
     本タスクは`prepare`内の`evaluate_graph`部分（全体の一部）のみを対象にしているため、
     ベンチマークの約10%短縮をそのまま適用しても全体で約0.3〜0.4秒程度の短縮にとどまり、
     目標「5秒以内」への到達は本タスク単独では確定できない（T220が既に想定していたとおり、
     確実な到達には全面ベクトル化等のより大きな対応が要る）。正直に「部分対応・目標未達の
     可能性が高い」まま記録する。
  - 検証: backend pytest 1058件全green（`test_traffic.py`95件が変更前後で出力一致を
    既に検証済み）。

## T221 Stage A先行＋evaluate_graph全面ベクトル化（2026-08-23・ユーザー指示）

ユーザー指示「全面ベクトル化に踏み切って」「軸のフルレジストリ化（T221）を先にやった
ほうが効率いいならそちらも合わせて実施して」を受け、T220完了メモが示していた順序
（T221 Stage A→ベクトル化の方が対象が均質になり安価）に従い2段階で実施する。
T221のStage B〜E（RoutePreference等のdict化・レジストリを実評価の参照元へ昇格・
DB化・GUI編集画面）はADR自体が未承認・別途の製品判断が必要としており、
今回のベクトル化には不要なため明示的にスコープ外とする。

### - [x] T239. T221 Stage A: 現行7軸を4テンプレートへ実装移行 規模M（2026-08-23完了）

- 発端: `docs/decisions/t221-axis-registry.md`が「現行7軸の変換ロジックは実質4
  テンプレート（区分線形補間・カテゴリ→定数・フラグ加算・レシピ→レベル→区分線形補間）に
  還元できる」とし、Stage Aとして「ロジックは変えず表現だけを変える」内部移行を提案していた
  （方向性のみ承認済み、実装はユーザーの明示指示待ちのまま）。T220完了メモは「この
  移行を先に済ませてからevaluate_graphをベクトル化する方が対象が均質になり安価」と
  明記している。
- 対応方針: 新規`backend/app/domain/axis_templates.py`に4つの汎用関数
  （`evaluate_breakpoint_linear`/`evaluate_categorical`/`evaluate_flag_sum`/
  `evaluate_recipe_then_breakpoint_linear`）を実装し、`domain/difficulty.py`の6関数
  （gradient/wind/road/stop/car_stress/accident各difficulty）と`domain/night.py:
  night_difficulty`の内部実装をテンプレート呼び出しへ差し替える。関数シグネチャ・
  戻り値の型と意味は一切変更しない。
- 完了条件: 既存`test_difficulty.py`（42件）・`test_traffic.py`（95件）・
  `test_evaluation.py`（43件）・`test_evaluation_service.py`（17件）が無変更のまま
  全green（＝ロジック不変の回帰確認）。

- **実装メモ（2026-08-23完了）**: 新規`domain/axis_templates.py`に4関数を実装
  （スカラー・numpy配列の両方を受け付ける設計、配列モードはNaNを欠損値として伝播）。
  `domain/difficulty.py`の`gradient_difficulty`/`wind_difficulty`/`road_difficulty`/
  `stop_difficulty`/`car_stress_difficulty`/`accident_difficulty`と
  `domain/night.py: night_difficulty`の内部実装をテンプレート呼び出しへ差し替え、
  旧`_piecewise_linear`（`difficulty.py`のモジュール内プライベート関数）は削除
  （`evaluate_breakpoint_linear`が同じ意味論で置き換え済み）。`wind_difficulty`
  （従来は手書きのclamp+線形正規化）・`road_difficulty`（従来は三項演算子）も
  それぞれ`evaluate_breakpoint_linear`/`evaluate_categorical`へ統一。
  新設`tests/test_axis_templates.py`（10件）でテンプレート自体のスカラー/配列同値性・
  NaN伝播・両端クランプを検証。
- 検証: 対象4テストファイル（計197件）が**無変更のまま**全green（ロジック不変を確認）。
  新規10件含めbackend全体1068件全green。

### - [x] T240. `EvaluationService.evaluate_graph`のnumpyベクトル化 規模L（2026-08-23完了）

- 発端: T238で車ストレス判定のpydantic構築コストのみ対応したが約10%短縮に留まり、
  T224の「10kmループ生成で温状態約5.4〜5.6秒」という目標「5秒以内」への到達は
  未確定のまま。ユーザー指示によりT239（Stage A）完了を前提に全面ベクトル化を実施する。
- 対応方針: 新規`domain/evaluation.py: compute_edge_costs_bulk(...)`を実装し
  `EvaluationService.evaluate_graph`の内部実装をこれへ差し替える（外部シグネチャ・
  戻り値型`dict[str, EdgeCostResult]`は不変）。1回のPythonループでEdge単位の辞書・
  タグ解析をnumpy配列へ抽出した後は、Stage Aのテンプレートを使った配列演算のみで
  7軸のdifficulty・加重合成・costを算出する（`EdgeCostResult`の生成は
  `model_construct()`でバリデーション省略）。既存の`compute_edge_cost`（1件ずつの
  スカラー版）は削除せず、回帰テストのオラクルとして存続させる。
- 完了条件: 新設`test_evaluation_bulk.py`で、多様なEdge（highway種別・タグ組み合わせ・
  欠損データパターン網羅）に対しスカラー版とバルク版の`cost`/`allowed`/`difficulty`が
  全件一致することを確認。`benchmarks/bench_evaluate_graph.py`でT238時点
  （68,120エッジ約1.18秒/121,800エッジ約2.12秒）からの短縮率を実測・記録。
  dev DBでのroad_graphエンジン実行（T232/T236と同じ直接呼び出し方式）で1シナリオ
  以上の実データ動作確認。backend全テストgreen。

- **実装メモ（2026-08-23完了）**: `domain/evaluation.py`に`compute_edge_costs_bulk`を実装し、
  `EvaluationService.evaluate_graph`（`RoadGraphEngine._build_search_graph`が実際に呼ぶ、
  探索コストの本番経路）の内部実装をこれへ切り替えた。抽出フェーズ（1回のPythonループ、
  `car_closeness`/`tag_value_is`/`parse_lanes`等の既存タグ解析プリミティブをそのまま呼ぶ）
  →計算フェーズ（Stage Aの`*_difficulty_array`関数で7軸のdifficulty配列を求め、
  重み付き加重平均→cost算出までPythonループ無しの配列演算）の2段構成。

- **実装中に発見・対処した2件の浮動小数点の落とし穴**（いずれも新設の回帰テスト
  `test_evaluation_bulk.py`と実データ突き合わせ自身が発見。テストが実際に機能した実例）:
  1. **numpyの配列reduceとPythonの逐次加算は加算順序が異なりうる**: 当初
     `np.stack(...).sum(axis=1)`で7軸を合成していたが、スカラー版`composite_difficulty`の
     `sum(score*weight for ...)`と最終丸め（1桁）が.X5境界でごく稀に食い違った。
  2. **Python 3.12以降の組み込み`sum()`はNeumaier補償加算（Kahan加算の改良版）を使う**:
     1.への対応として単純な逐次`+=`ループに直しても、まだ実データで87/46,341エッジが
     不一致だった。原因はPython 3.12の`sum()`が単純な逐次加算ではなくNeumaier補償加算
     （丸め誤差を打ち消す補正項を別途積算）を行うよう変更されているため。
     `domain/evaluation.py: _neumaier_accumulate`でこれを配列演算のまま（Pythonループ無しで
     n件分まとめて）再現し解消。加えて`np.round`自体も内部で「×10→rint→÷10」の掛け算により
     丸め誤差が混入しPython組み込み`round()`と食い違いうる問題があり、最終cost/difficultyの
     丸めのみ`axis_templates.py: round1_array`（要素ごとのPython`round()`、n件のみ）で
     個別に回避。**軸別スコア単体の丸め（`difficulty.py`の`*_difficulty_array`）は
     `np.round`のまま**——実データで不一致が出ないことを確認した上で、要素ごとの
     Pythonループにする速度コスト（後述）を避けるため。
- **速度と正確さのトレードオフに関する正直な結論**: 上記の正確さ確保策（Neumaier加算・
  最終丸めのPython round()化）を軸別スコアも含め全箇所に適用すると、要素ごとの
  Pythonループが増えすぎてベクトル化前（T238時点）より**遅くなった**（68,120エッジで
  約1.38秒、121,800エッジで約2.45秒。実測して判明）。最終cost/difficultyの丸めのみに
  限定することで速度を回復した。
- **実測速度**: 68,120エッジで約1.18秒→約1.02秒、121,800エッジで約2.12秒→約1.83秒
  （約14%短縮）。当初期待したような大幅な短縮ではない——cProfileで確認した実際の
  ボトルネックは、抽出フェーズのタグ解析（`car_closeness`/`cycleway_class`/`tag_value_is`
  等、Edge数に比例する不可避なPythonループ）とpydantic`model_construct`であり、
  今回ベクトル化した「7軸の加重合成」自体は全体時間の一部に過ぎなかったため。
  T224の「5秒以内」目標は本タスク着手前から実測5.4〜5.6秒台で既に未達成であり
  今回の14%短縮だけでは解消しない可能性が高い（10kmループ生成のエンドツーエンド
  実測はT229がトリガー未到達のまま残っている、別タスク）。
- **回帰検証**: 新設`test_evaluation_bulk.py`（合成グラフ、highway種別・タグ組み合わせ・
  欠損データパターンを網羅、9パラメータ組み合わせ）で全Edge一致を確認。加えてdev DBの
  実データ2エリア（東京都心南部、計122,592エッジ）で`compute_edge_cost`（Edge毎）と
  `evaluate_graph`（バルク版）の`cost`/`allowed`/`difficulty`が**全件一致**することを
  確認（不一致0件）。backend全体1077件全green。
- **検証中に見つかった別件の懸念（本タスクとは無関係、対応は見送り）**: 実データでの
  経路探索確認中、特定のbbox（東京都心南部の一部エリア）で起点・終点が異なる弱連結成分に
  属し経路が見つからないケースを確認した。**スカラー版・バルク版どちらのコスト計算を
  使っても同一の現象が再現する**ため、本タスク（ベクトル化）が原因ではなく、
  道路グラフのトポロジ・データ由来の既存事象と判断（要因未特定のまま。→T241として起票）。

### - [x] T241. 道路グラフの連結性調査（弱連結成分の分断でルート探索が失敗するケース） 規模S〜M（調査のみ、2026-08-23完了）

- 発端: T240の実データ検証中（dev DB、東京都心南部、品川駅付近の2点間）に発見。
  `RoadGraphEngine.preview_segment`で起点・終点それぞれ最近傍Nodeへスナップした後、
  `shortest_path_node_ids_sparse`が経路を返さない（`None`）事象を確認した。原因を
  `scipy.sparse.csgraph.connected_components(connection="weak")`で調べたところ、
  対象bbox（マージン込みで約46,341エッジ・19,780ノード）が**706個の弱連結成分**に
  分断されており、起点・終点が別成分（起点側は成分内ノード数1件＝孤立点だった
  ケースもあり）に属していた。`compute_edge_cost`（スカラー版）・
  `compute_edge_costs_bulk`（T240のバルク版）のどちらでコストを計算しても同じ経路が
  見つからない（＝コスト計算ロジックではなくグラフのトポロジ・データ由来の事象）ことを
  確認済み。
- 未確定な点（要調査）: (1) 分断の主因がOSM一方通行タグの解釈（有向グラフとしての
  弱連結性はそもそも期待するほど強くない可能性）なのか、(2) PBF取込・Way分割
  （`build_road_graph`）側の不具合でノード間の接続関係が一部欠落しているのか、
  (3) bboxで道路網を切り出すこと自体が本質的に生む「境界で千切れる」現象で
  bboxを広げれば解消するのか、を切り分けられていない。dev DBの取込範囲・
  データ品質固有の問題である可能性と、本番Oracle DB（関東本土全域投入済み）でも
  再現する構造的な問題である可能性の両方が未検証。
- 完了条件（調査のみ、規模次第で対策は別タスクへ分離）: 上記3仮説を切り分け、
  弱連結成分の分断が実際のユーザー向けルート生成（`RouteGenerator.generate_loops`の
  8方位探索）でどの程度の頻度・影響（候補0件化）を持つかを実データで定量化する。
  対策が必要と判断した場合は原因に応じた対策タスクを別途起票する（現時点では対策の
  要否・方向性いずれも未決定のため、本タスクは調査のみに留める）。

- **調査結果（2026-08-23完了）**: dev DB（3地点×2距離、5パターン成功）・本番DB
  （migration 0013適用後、3地点×2〜3距離、7パターン成功、T242参照）を合わせた
  計12パターンで`prepare()`直後の`sparse_graph`を`connected_components(connection="weak")`
  で解析。**全パターンで起点が属する成分が全ノードの95〜98%を占める単一の巨大成分**
  だった（例: 本番・新宿20kmで76,256/78,893ノード＝96.7%、本番・門前仲町20kmで
  70,374/73,052ノード＝96.3%）。残り700〜1,800個の小さな成分（合計でも全ノードの
  2〜5%）に分断が集中しており、**「起点がランダムに小さな孤立成分へ入り込む」事象は
  実測上ごく稀**と判明した。
  - 個別ケースの深掘り（門前仲町20km、8方位中2方位のみ候補採用）: `trace_loop`自体は
    8方位中6方位で経路を発見しており、真の「経路が見つからない」（弱連結成分が別）
    による失敗は2方位のみ。残り4方位は経路自体は見つかったが目標距離±5kmの許容範囲を
    大きく超過し`distance_tolerance_km`フィルタで候補から除外されていた（例:
    目標20kmに対し39.71km等）。**T236が報告した低い候補採用率の主因は、グラフの
    分断そのものよりも「道路網の形状が目標距離ちょうどのループを作りにくい方位がある」
    という別要因（距離許容フィルタ）の寄与が大きい**ことが判明。
  - T240で確認した「component size 1（完全孤立）」の1件は、以降の12パターンでは
    一度も再現しなかった（発生頻度は極めて低い外れ値的事象とみられる）。
  - 3仮説（oneway解釈／PBF取込のWay分割不具合／bbox境界での分断）は、
    `connection="weak"`（有向グラフの向きを無視した連結性）を使っている時点で
    oneway由来の分断は原理的に起こらない（一方向にでも道が繋がっていれば同一成分に
    入る）ため、仮説1は理論上除外できる。仮説2・3の切り分け（特定の孤立ノードが
    実在する行き止まり道路なのか、Way分割の欠落なのか）は今回のデータでは決定的な
    証拠が得られず、頻度自体が低い（全体の数%）ため追加の詳細調査は費用対効果が
    低いと判断し、これ以上は深追いしない。
  - **結論**: 弱連結成分の分断は実在するが、実際のルート生成成功率への影響は
    限定的（起点は95%以上の確率で巨大成分に入る）。ORS→road_graph移行の判断材料
    としては「致命的な問題ではない」と評価する。

### - [x] T247. `routing_engine`既定値をroad_graphへ切替 規模M（2026-08-23完了）

- 発端: T236（品質比較）・T241（連結性調査）・T242〜T246（本番DB起動不能・DELETE性能問題の
  解消、実データ検証済み）を経て技術的な障害が解消されたことを受け、ユーザー指示
  「既定値を切り替えして」。
- 対応: `backend/app/config.py`の`routing_engine`既定値を`"openrouteservice"`から
  `"road_graph"`へ変更。デプロイ環境（Render）・`.env`のいずれにも`ROUTING_ENGINE`の
  明示的な上書きが無いことを確認済みのため、この既定値変更のみで実際に有効化される
  （`routing_engine`はAPIスキーマに現れない内部設定のためOpenAPI再生成は不要）。
- 追従した既存の食い違い:
  - `tests/test_config.py`の`test_default_field_declarations`が既定値`"openrouteservice"`を
    ハードコードしていたため更新。
  - `tests/test_routes_preview.py`の2件（ORS委譲経路をテストする
    `test_preview_route_returns_segment_on_success`/`test_preview_route_returns_502_on_routing_error`）
    が`settings.routing_engine`を明示的に固定せず既定値に依存していたため、
    `monkeypatch.setattr(settings, "routing_engine", "openrouteservice")`を追加
    （既定値変更で実際にテスト失敗として顕在化・検出できたことを確認）。
  - `.env.example`・`docs/architecture.md`内の「既定はopenrouteservice」という複数箇所の
    記述を現状に合わせて更新。あわせて`.env.example`のプロファイル表が「本番
    （Render+Supabase）」という2026-08-15のOracle Cloud移行前のまま古くなっていたため
    「本番（Render+Oracle Cloud）」へ訂正した（本タスクの主目的ではないが、同じ表を
    編集する過程で発見したため合わせて修正）。
- 完了条件: backend全体1077件green。既定値変更後もORS経由・road_graph経由どちらも
  明示指定で選択可能なまま（後方互換）。
- 検証: backend全体1077件green。

## 統合レビュー第7回の起票（2026-08-23、ユーザー承認済み）

統合レビュー第7回（`.claude/commands/review/history/2026-08-23_all_2.md`、対象
`1e7ade4..e686949`、健全度89/100）の統合Findings 3件をユーザー承認
（「起票し、さっそく対応して」）を受けて起票した。統合-2（T221背景追記）は
T221エントリへの追記として実施済み（新番号なし）。

### - [x] T248. road_graph既定エンジンの性能改善（バルクUPSERT最適化＋冷パス体験設計） 規模M〜L（2026-08-24完了、冷パスの体験設計本体はT265へ切り出し）

- 発端: 統合レビュー第7回 統合-1（P2）。T247でroad_graphが既定エンジンになったことで、
  従来「参考記録」だった性能課題が「全ユーザーの既定体験」の課題へ位置づけが変わった。
  T229（冷パスのクエリ本数計測、DEFER）は実測が事実上完了したため本タスクへ統合クローズ。
- 実測値（2026-08-23、統合レビュー第7回の実機確認）:
  - dev・新宿10km（API経由・エンドツーエンド）: 冷パス46.0秒→温パス7.5秒→完全温6.7秒
    （`prepare_ms=5281`が支配的）。**T224目標「温5秒以内」に対し+30%超過**。
  - 本番・王子30km（T246検証時）: 冷パス316秒（`node_upsert_ms=46000`＋
    `edge_upsert_ms=149235`のバルクUPSERTが支配、DELETE段はT246で10.2秒へ解消済み）。
- **本番実測（2026-08-23、専用worktreeでDATABASE_URLを本番Oracle Cloud PostGISへ向け、
  ローカルbackendから`POST /api/routes/generate`を6地点・8リクエスト実際に発行して再実施。
  ユーザー許可を得た上で本番DBへ実際に書き込みを伴う）**:
  - 王子15km（既存split済領域内）: prepare_ms=10,921・total_ms=14,203・候補7件。
  - 前橋10km（新規split）: `save_graph total_ms=42,406`（node_upsert=7,781・
    delete=672・edge_upsert=30,172）、prepare_ms=67,078・total_ms=77,891・候補8件
    （温再実行はprepare_ms=6,891・total_ms=7,922）。
  - 銚子25km（新規split、沿岸のため2方位失敗は妥当）: `save_graph total_ms=23,797`、
    prepare_ms=33,843・total_ms=41,125・候補2件。
  - バルクUPSERTがprepare全体の6〜7割を占める傾向を再確認（前橋63%・銚子70%）。
  - **新規発見: 「分割済みデータの冷読み出し」単体でも66〜91秒かかる**。新宿10km
    （既にsplit済み、`save_graph`は発生せず）でprepare_ms=88,219（初回）／
    91,578（サーバ再起動後の材料再読込のみ）。T229が懸念していた「材料5クエリ×
    タイル数」問題（冷パスのクエリ本数増）が、save_graph以外の内訳としても実測で
    裏付けられた。温パス（プロセス内キャッシュ命中）は一貫して5〜8秒でdev実測と
    ほぼ一致。
  - 詳細は改善計画の作業ログ（2026-08-23のT248本番実測セッション）参照。
- **T259との関係（2026-08-24）**: 上記の新宿10km（split済み材料の冷読み出しのみ）で
  prepare_ms=88,219〜91,578と判明していたが、これはT259で確定した**Renderプラット
  フォームの約100秒リクエストタイムアウト**の目前だった。実際、20km・未split地点
  （ユーザー実機再現）では本番HTTP経由で100.82秒の502（プラットフォームタイムアウト）
  に到達し、**体感遅延ではなく完全な失敗**になることをT259で実地確認した。つまり
  本タスクの「対応候補」（バルクUPSERT最適化・冷パス高速化）は、単なる体感改善では
  なく**プラットフォーム制約による完全失敗の回避**という、より緊急度の高い意味を持つ。
  トリガー（「一般公開の意思決定時に必須化、それまでは研究利用での体感遅延報告で着手」）
  の見直しが必要か、ユーザー判断を仰ぐ。
  - **2026-08-24追記**: ユーザー指示「改善して」を受け、下記対応候補1（バルクUPSERT
    最適化）をCOPY方式で実装し、本番実測で検証した。未split新規地点（土浦20km、
    69,210 Edge）で`edge_upsert_ms=4,906・save_graph total_ms=7,218`、リクエスト全体
    `total_ms=35,671`（`http_code=200`成功）を確認（詳細は下記1.の本番実測メモ）。
    Renderの約100秒制約に対し約65秒の余裕を確保でき、**未split・20km規模地点の
    プラットフォームタイムアウト到達リスクを実測で大きく低減した**。ただし1a（材料
    冷読み出し）で判明した「split済みでも88〜92秒」の律速要因（データ転送量そのもの）
    は本対応の対象外で未解消のまま残る。T259の再現座標自体は今回の検証時点で既に
    split済みだったため「split済み＋材料読み出し重い」ケースの本番実測（100秒制約への
    実際のマージン）はまだ得られていない。
- 対応候補（着手時に設計判断）:
  1. **バルクUPSERTの最適化**（2026-08-24実装完了）: `_bulk_upsert`（複数行VALUESの
     INSERT ... ON CONFLICT、chunk=1000）をPBF取込バッチ（app/batch/import_pbf.py）と
     同じasyncpg COPY方式（一時テーブルへCOPY→`INSERT ... SELECT ... ON CONFLICT`で
     1回のセット処理へマージ）へ置き換えた。T259で「20km・未split地点がRenderの
     約100秒プラットフォームタイムアウトに到達し完全失敗する」ことが確定した直後の
     ユーザー指示「改善して」を受けて、T248実測で最も支配的だった段（save_graphの
     node_upsert/edge_upsert、王子30kmでedge_upsert_ms=149,235）を対象に着手した。
     - **設計**: `road_graph_repository.py`に`_asyncpg_connection`（SQLAlchemy
       `AsyncSession`の裏の生asyncpg接続を`(await session.connection()).get_raw_connection()`
       の`driver_connection`で取得、SQLAlchemy 2.0の正式なAPI）・`_copy_upsert_road_nodes`・
       `_copy_upsert_road_edges`を新設。ジオメトリは`shapely.to_wkb`で素のWKB bytesへ
       変換して一時テーブル（`bytea`列）へCOPYし、マージSQL側で`ST_GeomFromWKB(wkb, 4326)`
       によりPostGIS geometryへ復元する（import_pbf.pyの`_MERGE_WAYS_SQL`と同じ考え方）。
       一時テーブルは`CREATE TEMP TABLE IF NOT EXISTS ... ON COMMIT DROP`（既存の
       `tmp_save_graph_new_edge_ids`と同じ規約）。
     - **実装中に踏んだ落とし穴**: SQLAlchemyの`AsyncSession`は「autobegin」のため、
       SQLAlchemy経由で何か実行するまで実トランザクション（BEGIN）がドライバへ
       送信されない。生のasyncpg接続を取得した直後にいきなりCOPY/INSERTを発行すると、
       接続がautocommitのまま動作し、`CREATE TEMP TABLE ... ON COMMIT DROP`が
       直後の暗黙コミットで即座にDROPされてしまい、続くTRUNCATEが「テーブルが存在しない」
       エラーになる（ベンチマーク実装時に実際に発生・原因特定）。`_asyncpg_connection`内で
       軽い`SELECT 1`を1つ挟んでBEGINを確定させてから生接続を取り出すことで解決した。
     - **`save_graph`側の変更**: node_rows/edge_rowsをORM用dictとして組み立てる処理を、
       生のNode/DirectedEgeオブジェクトのまま`_copy_upsert_*`へ渡す形へ簡略化（中間dict
       が不要になった）。DELETE段（境界Edge差分削除、T246で既に軽量化済み）・ログの
       フィールド名・意味は完全に維持。
     - **検証（プロファイリング、backend/benchmarks/bench_save_graph_copy.py新設）**:
       dev DB実測で現行実装とCOPY方式を同一データ・同一セッションで比較（DELETE段を
       除いたnode_upsert+edge_upsertのみ、公平のため2回ずつ計測）。
       10km（58,037 Edge）: 現行60.9秒→COPY方式6.4秒（**9.6倍**）。
       20km（143,905 Edge）: 現行86.2秒→COPY方式15.4秒（**5.6倍**）。
       既存の`bench_postgis_prepare.py`（4km、25,710 Edge）でend-to-end再計測したところ、
       save_graph単体3.8秒・COLD経路（closure+build+save）合計7.5秒まで短縮（同モジュールが
       docstringに記録している最初期の実測「271秒」・T248実測「10km冷46.0秒」から
       大幅に改善）。
     - **テスト**: `test_road_graph_repository.py`（save_graphの既存回帰テスト94件、
       うち大規模Edge数のasyncpgパラメータ上限回帰テストを含む）・`test_match_designations.py`
       を直列実行で全green。**pytest-xdist（`-n auto`）実行時、このタスクの変更とは
       無関係に発生する既存のDB競合フレーク（`test_get_nearest_stop_poi_counts_...`・
       `test_recompute_way_attribute_counts_...`のIntegrityError）を本タスクの検証中に
       発見した**（変更前のコードへ`git stash`で一時的に戻し、同一条件で同じ2件が
       再現することを確認済み。本タスクの変更が原因ではないが、CI・並列実行時の
       安定性リスクとして記録のみ残す。追加調査は本タスクのスコープ外）。
     - **本番実測（2026-08-24、ユーザー許可を得て実施。ローカルbackendからRenderの
       ネットワークホップを経由せずDATABASE_URLを本番Oracle Cloud PostGISへ直結し、
       実際に書き込みを伴う`POST /api/routes/generate`を発行）**:
       - **T259再現座標（35.7506948, 139.7418897、20km）**: `total_ms=48,922`
         （`http_code=200`、`time_total=49.74秒`）で成功。ただしこの地点は既にsplit済み
         （save_graphログなし、`prepare_ms=47,359`は材料冷読み出しのみ）だったため、
         本対応（save_graph高速化）そのものの効果はこの回では検証できていない。
       - **未split新規地点（土浦、36.0839, 140.1968、20km）**: `save_graph nodes=25,614
         edges=69,210 way_ids_to_replace=20,217 node_upsert_ms=1,140 delete_ms=1,140
         edge_upsert_ms=4,906 total_ms=7,218`。edge_upsert_msが**旧実装換算で数十秒級
         （T248実測: 前橋10kmでedge_upsert_ms=30,172、王子30kmで149,235）と推定される
         規模のEdge数（69,210件）に対し、新実装ではわずか4.9秒**。リクエスト全体は
         `prepare_ms=23,953・total_ms=35,671`（`http_code=200`）で成功、候補7件・
         8方位中8方位が経路発見。Renderの約100秒プラットフォームタイムアウトに対し
         約65秒の余裕を確保できており、**未split・20km規模の新規地点における
         プラットフォームタイムアウト到達リスクを実測で大きく低減したことを確認した**。
       - 検証後、ローカルサーバーは停止済み。土浦地点のsplit結果はDBへ実際に永続化
         されている（通常のユーザーリクエストと同じ書き込みのため実害無し）。
     - **一時切り戻し→原因除外を確認して再導入（2026-08-24）**: 本番デプロイ直後に
       バックエンドプロセスがクラッシュ→自動復旧を繰り返す障害（T261）が発生し、
       デプロイ直後という時系列から本対応が原因と疑い、一度`git revert`で切り戻した
       （コミット`b2e846f`）。しかし切り戻し後の旧実装（`_bulk_upsert`）でも同一条件で
       クラッシュが再現し、さらにT262（Pydantic依存削減）適用後でも再現したことから、
       **本対応（COPY化）は原因ではないと確定した**（詳細な時系列・証跡はT261参照）。
       ユーザー確認の上、`git revert`でb2e846fを打ち消す形（＝COPY化を再導入）で復元した
       （コミット、T262と同一トランザクション内でマージ）。クラッシュの真因は
       引き続きT261側で調査中（Renderのリソース制約が最有力）。
  1a. **材料読み込み（冷パス、split不要な場合の読み出し）の最適化**（2026-08-24調査・
     部分実装完了）: 本番実測で新規発見（上記）。「材料5クエリ×タイル数」（T229）の
     クエリ本数そのものを削減する方向で着手し、案A・案Bの2つを実装・本番実測したが、
     **案Bは本番実測で効果が確認できず revert し、案Aのみ採用した**。
     - **案A（`is_tile_cached`のバッチ化、採用・実装済み）**: タイル数ぶん個別に発行していた
       `is_tile_cached`ループを、`RoadGraphRepository.get_cached_tiles`（新設、
       `(zoom,x,y) IN (...)`の1クエリ）へ集約。`GraphService._ensure_tiles_cached`として
       `get_or_build_graph_with_attributes`・`get_search_materials_for_bbox`両方の入口で
       共有。**冷パス・温パスの両方**で毎リクエスト効く（温パスは新宿10kmで7クエリ→
       2クエリ）。副作用が無い機械的な改善のため、効果の大小によらず採用。
     - **案B（未キャッシュタイルの材料バッチ取得、試験実装したがrevert済み）**:
       `_build_search_materials_from_tile_cache`を、未キャッシュな複数タイルぶんを個別に
       問い合わせるループから、対象タイル群の外接矩形へ1回のクエリセット（計6クエリ）へ
       集約し、結果をタイルごとへ分割してキャッシュへ格納する方式を実装した
       （新宿10km・z12タイル6枚で49クエリ→25クエリへ削減）。テスト（単体・PostGIS統合・
       backend全体1085件green）は全通過し実装自体にバグは無かった。
       - **本番実測で判明した結論（2026-08-24、本番Oracle Cloud PostGISで新旧方式を
         同一セッション内で公平に比較。DBキャッシュ状態の揺れによる誤差を排除するため
         各方式2回ずつ計測）**: 新宿10km（旧43.63秒→新41.91秒、4%改善）・王子15km
         （旧38.27秒→新42.18秒、**10%悪化**）と、有意な改善は確認できなかった。
         1クエリあたりの実測コスト（旧: 約1.8秒/クエリ、新: 約1.7秒/クエリ）がほぼ
         変わらないことから、律速していたのは「ラウンドトリップの往復回数（レイテンシ）」
         ではなく「1クエリあたりの実行・転送コスト（数万〜十数万行という大きな結果セットの
         DB側処理・シリアライズ・クライアント側デシリアライズ）」だったと判明した。
         この結論はdev-local実測（新方式71.56秒≈旧方式68.80秒、ほぼ同等）とも整合する。
       - **判断・対応**: 「クエリ本数を減らす」という対策の方向性自体が、真のボトルネックに
         対して的外れだったため、投じた実装コスト（境界Edge多重登録・タイル分割ロジックの
         複雑性）に見合う効果が無いと判断し、案Bの実装は2026-08-24中に全てrevertした
         （`_bbox_covering_tiles`・`_partition_search_materials_by_tile`・
         `_fetch_and_cache_missing_tile_materials`・関連テストを削除、
         `_build_search_materials_from_tile_cache`・`_get_or_build_tile_materials`を
         タイル毎ループの元実装へ戻した。`domain/region.py`の`lonlat_to_tile_index`公開化も
         用途が無くなったため`_lonlat_to_tile_index`へ戻した）。
       - **教訓（次に類似の最適化を検討する際に活かす）**: ラウンドトリップ削減が効くのは
         「小さな結果セットを多数の往復で取りに行っている」場合に限られる。今回のように
         1回の結果セット自体が既に大きい（数万〜十数万行）場合は、往復回数を減らしても
         DB側の処理・転送コストは変わらないため効果が出ない。真のボトルネックが
         「往復回数」か「転送データ量」かを、本番実測（可能ならEXPLAIN ANALYZEやDB側の
         実行時間内訳）で先に切り分けてから着手すべきだった。データ量が真因であれば、
         対策の方向性はクエリ集約ではなく「そもそも読み込むデータ量を減らす」
         （タイル粒度の見直し・必要なEdgeへの絞り込み等）や、T248候補2の「冷パスを
         リクエスト同期から切り離す」方向にすべきである。
     - 対応方針としてgeo形式キャッシュ（DBと同じ`ST_Intersects`をサーバー側JOIN条件として
       使い、geometry自体はSELECTしない設計）も検討したが、真因が転送データ量である以上
       効果は薄いと判断し実装は見送った。
  1b. **材料5クエリの1クエリへの統合**（2026-08-24実装完了）: 案Bのrevert後、ユーザーから
     「転送量自体がネックならそれを減らす方針、アーキテクチャを考えられないか」という
     提起を受け、真因を再検討した。dev DBでプロファイリングした結果、律速は往復回数でも
     転送データ量そのものでもなく、**同じEdge集合に対しSQLAlchemy ORMの行オブジェクト
     構築を5回（surface/edge_attribute_counts/way_tags/elevation_attributes/
     designated_edge_ids）繰り返していたPython側のオーバーヘッド**と判明した
     （71,791 Edgeで現行5クエリ8.33秒 → 統合1クエリ[SQLAlchemy Core]1.30秒[6.4倍] →
     統合1クエリ[生asyncpg]0.83秒[10倍]）。
     - **実装**: `domain/attributes.py`に`EdgeMaterialsBatch`（`SearchMaterials`から
       `graph`を除いた5材料のみの型）を新設。`AttributeRepository.get_edge_materials_batch`
       （`road_graph_repository.py`）で、road_edges LEFT JOIN osm_raw_ways/
       edge_attribute_counts/elevation_attributes＋designation_attributesへの
       相関EXISTS副問い合わせを1クエリへ統合。生asyncpg（10倍）ではなくSQLAlchemy Core
       （6.4倍）を採用——効果の大部分をより低リスク（既存セッション・型を維持）に得られる
       ため。各材料の「該当行なし」の意味（surface/way_tagsはLEFT JOINでNone/{}を明示的に
       持つ・edge_attribute_counts/elevation_attributesはNOT NULL列で行の有無を判定し
       key自体を省略・designated_edge_idsはEXISTSの真偽）は元の5メソッドと完全に同じ
       意味を保つよう設計・テストした。`graph_service.py`の`_build_search_materials_uncached`・
       `_get_or_build_tile_materials`の両方をこの1メソッド呼び出しへ差し替え。
     - **テスト**: `test_road_graph_repository.py`に、実在するfwd/bwd2本のEdgeの一方だけへ
       edge_attribute_counts・elevation_attributesを投入し「該当行なしのkey省略」を
       検証する統合テストを追加。`test_graph_service.py`のFakeリポジトリにも
       `get_edge_materials_batch`を追加し、既存の呼び出し回数アサーションを更新。
       backend全体1084件green。dev DBでのE2E確認（新宿10km候補8/8・王子15km候補6/8）で
       機能面の回帰も無いことを確認。
     - **残課題（2026-08-24追記で対応済み、下記1c参照）**: この最適化は5つの「材料」
       クエリのみが対象で、`get_graph_topology_in_bbox`（Edge/Node本体のトポロジ取得、
       深掘りプロファイリングで新宿10km実測33秒）は当初未着手のまま残っていた。
  1c. **`get_graph_topology_in_bbox`のNode取得をST_X/ST_Y列指定へ変更**（2026-08-24実装
     完了）: 1a・1bの流れを受け、残っていた最大の未着手コストを調査した。Node取得が
     `select(RoadNodeRow)`（geom列込みのORM行）＋`shapely.from_wkb`によるgeometry decode
     をしていたが、探索フェーズが必要とするのは緯度経度のみ（Edge側は既にT218で
     `_topology_rows_to_road_graph`向けにgeom列を除いた列指定クエリへ最適化済みだった、
     Node側だけが未対応のまま残っていた）。dev DB実測（68,760件、6タイル拡張bbox・
     T229深掘り計測と同規模）でORM全体取得+shapely decode 2.76秒 → PostGIS側で
     `ST_X(geom)`/`ST_Y(geom)`を計算させプレーンなfloatとして受け取る方式0.89秒
     （**3.1倍**）を確認して実装した。
     - **実装**: `road_graph_repository.py`の`get_graph_topology_in_bbox`のnode_stmtを
       `select(RoadNodeRow)`から`select(RoadNodeRow.node_id, RoadNodeRow.osm_node_id,
       func.ST_X(RoadNodeRow.geom), func.ST_Y(RoadNodeRow.geom))`へ変更。
       `_topology_rows_to_road_graph`も同様に`shapely.from_wkb`呼び出しを削除し、
       行から緯度経度を直接読むだけにした。
     - **注意（深掘りで判明した誤差の原因）**: 当初「33秒の内訳」を特定しようとしたが、
       edge_query単体2.49秒・node取得（旧実装）2.76秒で合計5.25秒にしかならず、
       元の33秒との差が大きいことが判明した。33秒の計測はセッション序盤（DBキャッシュが
       冷えた状態）に対し、今回の内訳計測は同じ範囲への大量の反復アクセス後（DB
       キャッシュが温まった状態）だったための差と考えられる（T229で確認した同種の
       現象）。したがって「edgeクエリ・node取得のどちらが33秒の主因か」は未確定のまま
       だが、**node取得側の3.1倍という相対的な改善効果自体は2回の独立した計測
       （29,017件規模で3.2倍・68,760件規模で3.1倍）で再現しており、方式自体の有効性は
       確度高く確認できている**。`_topology_rows_to_road_graph`内のPydantic
       `model_construct`呼び出し（Edge+Node合計24万件規模）のコストは今回切り分けて
       おらず、次に着手する場合の候補として残る。
     - **テスト**: `get_graph_topology_in_bbox`にはPostGIS統合テストが1件も無かったため
       新規に3件追加（未保存時None・`get_graph_in_bbox`との座標一致回帰・bbox外Edge除外）。
       backend全体1087件green。dev DBでのE2E確認（新宿10km候補8/8・渋谷10km候補6/8・
       王子15km候補4/6）で機能面の回帰なし（新宿の初回計測で237秒という外れ値が出たが、
       直前の重いpytest実行によるDB側の一時的な負荷が原因と考えられ、再実行では10.2秒
       まで復帰したため再現性の問題ではないと判断した）。
  1d. **探索専用lean型をPydanticから完全に分離**（2026-08-24実装完了）: 1cで残課題として
     記録した`model_construct`のコスト（プロファイリングで新宿10km・171,461Edge規模の
     `DirectedEdge.model_construct`だけで8.938秒、`Node.model_construct`2.125秒、DB
     クエリ本体3.4秒より支配的）を受け、ユーザーから「lean型とフル型を完全に分ける」
     方向での実装指示を受けて着手した。
     - **設計**: `domain/graph.py`に`LeanNode`/`LeanEdge`/`LeanRoadGraph`
       （`@dataclass(frozen=True, slots=True)`、Pydanticのバリデーション・内部簿記を
       持たない）を新設。既存の`Node`/`DirectedEdge`/`RoadGraph`（Pydantic、表示・保存用）
       とフィールド構成を完全に一致させ、`NodeLike`/`EdgeLike`/`RoadGraphLike`
       （`typing.Protocol`、`@runtime_checkable`）で両者が満たす構造的型を定義した。
       `RoadGraphEngine.trace_loop`が`hydrated.get(edge_id) or context.graph.edges[edge_id]`
       でlean型（探索グラフ由来）とフル型（表示用に取り直したEdge）を同じリストへ
       混在させる境界があり、フィールド完全一致の設計がこれを事故なく成立させる
       （調査で特定した最大のリスク要因）。
     - **実装範囲**: `_topology_rows_to_road_graph`（road_graph_repository.py）が
       `LeanRoadGraph`を返すよう変更。`domain/routing.py`（`build_sparse_graph`・
       `build_networkx_graph`・`find_nearest_node`・`build_node_spatial_index`・
       `NodeSpatialIndex`）、`domain/evaluation.py`（`is_edge_allowed`・
       `compute_wind_penalty`・`compute_edge_axis_scores`・`compute_edge_cost`・
       `compute_edge_costs_bulk`）、`services/evaluation_service.py`
       （`EvaluationService.evaluate_graph`）、`services/elevation_attribute_service.py`
       （`get_attributes_for_graph`）、`services/road_graph_engine.py`
       （`_SearchGraph`/`_RoadGraphContext`の`graph`フィールド、`_build_segment_details`
       等のEdge集約関数群）、`domain/attributes.py`（`SearchMaterials.graph`）の型注釈を
       `RoadGraph`/`DirectedEdge`から`RoadGraphLike`/`EdgeLike`へ変更（実行時の分岐は
       元々duck typingで動いていたコードのため、型注釈の変更のみで済んだ箇所が大半）。
     - **実装中に見つけた実際のバグ**: `RoadGraphEngine._build_candidate`が
       `path_graph = RoadGraph(graph_version=..., nodes=context.graph.nodes, edges=...)`
       と、Pydantic `RoadGraph`へ`context.graph.nodes`（今回`LeanNode`の辞書になる）を
       直接渡しており、Pydanticのフィールド型検証（`dict[str, Node]`）に失敗して
       実行時エラーになる箇所を発見した。調査の結果`get_attributes_for_graph`は
       `graph.edges`しか参照せず`nodes`は完全に未使用と判明したため、`nodes={}`へ変更した
       上で、`RoadGraph`ではなくバリデーションを行わない`LeanRoadGraph`で`path_graph`を
       構築するよう修正（`edges_in_path`が稀にlean/フル混在になりうる`trace_loop`の
       フォールバック分岐に対しても安全）。副次効果として、候補ごとに数万件規模の
       `context.graph.nodes`をコピーしていた無駄も無くなった。
     - **`GraphService`側の型整合**: `get_or_build_graph_with_attributes`の戻り値、
       `_build_search_materials_from_tile_cache`・`_get_or_build_tile_materials`の
       空グラフ・結合グラフ構築を、`lean`引数や呼び出し経路に応じて`LeanRoadGraph`/
       `RoadGraph`を作り分けるよう修正（`get_or_build_graph_with_attributes`は
       `is_split_up_to_date=True`かつ`lean=True`の高速パスのみ`LeanRoadGraph`を返し、
       closure再構築を伴う低頻度の重い経路は`lean`に関わらず常に`RoadGraph`のまま）。
     - **テスト**: `test_graph.py`に`LeanNode`/`LeanEdge`/`LeanRoadGraph`が対応する
       Protocolを満たすこと・frozenであることの単体テストを追加。
       `test_road_graph_repository.py`の座標一致回帰テストに、戻り値の実体型が
       `LeanRoadGraph`/`LeanNode`/`LeanEdge`であることの検証を追加。backend全体
       1089件green。
     - **実測（dev DB、新宿10km・171,461Edge・68,760Node、6タイル拡張bbox規模）**:
       `get_graph_topology_in_bbox`全体（DBクエリ＋オブジェクト構築を含む）が
       4.2〜4.6秒（3回計測の範囲）。1cまでの実測（edge_query 2.49秒＋node取得
       [ST_X/ST_Y] 0.89秒 ≈ 3.4秒のDB部分のみ）と合わせて、Pydantic
       `model_construct`のオーバーヘッド（旧実装で推定11秒）がほぼ解消されたことを
       裏付ける。dev DBでのE2E確認（新宿10km候補8/8・渋谷10km候補6/8・王子15km候補4/6、
       いずれもエラー無し）で機能面の回帰も無いことを確認。
  2. **冷パスの体験設計**: 初回タッチの重い処理（split再構築）をリクエスト同期から
     切り離す選択肢（バックグラウンドウォームアップ・主要エリアの事前split・
     プログレス表示等）。T59の`_maybe_trigger_graph_build`（タイル閲覧起点の
     バックグラウンド構築）という既存機構との統合可能性を含めて検討する。
     - **調査（2026-08-24）**: `_maybe_trigger_graph_build`（region_service.py）は
       **地図タイル閲覧専用**で、ルート生成側（`RoadGraphEngine.prepare`）からは
       一切呼ばれておらず、そのままでは転用できないと判明。コールドパスは
       (a)未split→`save_graph`再構築が重い（バックグラウンド化で対応可能）と
       (b)split済みでも材料読み出し自体が重い（T229で判明、データ量律速のため
       バックグラウンド化だけでは解決しない）の2種があり、対策を分けて設計する
       必要がある。また、ルート生成経由の`save_graph`は`graph_build_max_concurrent`
       （タイル閲覧経由の構築が使う同時実行ガード）の対象外で、同じ処理が呼び出し
       経路によって異なる同時実行制御を受けている非対称性も確認した。
       本体（バックグラウンドウォームアップ・事前split等の実装）は規模が大きいため
       未着手のまま次回以降に持ち越す。
     - **独立したバグとして先に修正（2026-08-24完了）**: 調査中に、フロントエンドの
       `/api/routes/generate`タイムアウト（90秒、`frontend/src/services/routeApi.ts`）が
       バックエンドのDBコマンドタイムアウト（180秒、`ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS`、
       `database.py`）より短く設定されていることが判明した。王子30kmの本番実測
       （T246、total_ms=315,859≒316秒）のような重いケースでは、バックエンドが処理を
       継続しているにもかかわらずフロントエンドが先にタイムアウトしてユーザーには
       失敗と表示される、というズレが起きうる。冷パス体験設計そのものとは独立した
       既存バグのため先に修正した：フロントエンドのタイムアウトを本番実測の最悪値
       （316秒）を安全マージン込みで上回る360秒へ延長。`frontend/src/services/routeApi.test.ts`
       含めテスト影響なし（5件green）。
  3. 温パスの残り（evaluate_graph約2.6秒＋グラフ構築約1.0秒）はT238/T240で
     最適化済みのため、これ以上の短縮はT12 Part 2（キャッシュ永続化等）の領域。
- 完了条件（着手時に確定）: 温パス5秒以内（T224目標の達成）＋冷パスの体験方針の決定・
  実装。実測値をもって記録する。
- **切り出し**: 本番実測中に発見した「都心部（新宿・渋谷）で候補0件」は性能問題ではなく
  接続性の問題のため、本タスクのスコープ外としてT256へ切り出した。
- **T263（Oracle VM移行）・T264（closure_ms削減）後の再検証（2026-08-24、本番backend
  `https://193-123-166-150.sslip.io`へ直接curlで実施、書き込みを伴う）**: T259で確定した
  「未split・20km規模地点がRenderの約100秒プラットフォームタイムアウトで完全失敗する」
  事象が、移行後も再現するか確認した。
  - **ユーザー実座標（T259再現座標、20km、既にsplit済み）**: `http_code=200・
    time_total=44.1秒`で成功。
  - **前橋（今回初アクセスの未split地点、20km）**: 冷パス`http_code=200・
    time_total=27.6秒`で成功、候補あり。直後の温パス再実行は`time_total=13.3秒`
    （T224目標の温5秒以内には未達、1aで判明した「split済みでも材料読み出しが重い」
    残課題がなお効いている可能性）。
  - **秩父（今回初アクセスの未split地点、30km）**: `http_code=200・time_total=8.4秒`
    （山間部のため候補0件だが失敗ではない）。
  - いずれも`/api/debug/stats`の`started_at`（プロセス起動時刻）はリクエスト前後で
    不変＝クラッシュ・再起動なし。CORSヘッダー（`access-control-allow-origin`）も
    正しく返っており、T259で見られた「CORS違反に見える誤診断」（Renderのエッジ層が
    素の502を生成しCORSヘッダーが付かない現象）自体がOracle VM移行で構造的に
    再発しなくなっている（RenderのHTTPプロキシ層を経由しないため）。
  - **結論**: T259で確定した「完全な失敗」は解消された。20km級の冷パスは30〜45秒
    程度に収まり、フロントのアプリレベルタイムアウト（360秒）に対し十分な余裕がある。
    ただし「対応候補2（冷パスの体験設計）」「温パス5秒以内（完了条件）」は未達のまま
    残っており、これは失敗回避ではなく体感速度の課題として引き続き本タスクのスコープ内。
  1e. **タイル材料キャッシュの書き込み漏れを修正（2026-08-24実装完了）**: 上記の再検証で
     温パス5秒以内が未達（13.3秒）だった原因を深掘りしたところ、真の温パス（同一bboxへ
     3回目のアクセス）は`http_code=200・time_total=4.9秒`でT224目標を達成済みと判明した。
     つまり13.3秒は「温パス」ではなく「split直後の2回目アクセスがまだキャッシュ未着火の
     まま材料をDBから読み直している」状態を計測していただけだった。
     - **原因**: `_build_search_materials_uncached`（split・再構築を伴う経路）は、
       構築した材料を`graph_material_cache`（プロセス内タイル単位キャッシュ）へ書き込まず
       返していた。旧docstringには「この経路自体が低頻度・重い処理のため、タイルキャッシュの
       対象外のまま。ロジックを二重に持たない」という意図的な設計判断が明記されていたが、
       これにより「split直後の次のリクエスト」が毎回この無駄なDB再読み出しを踏む
       ユーザー体感上のギャップが生じていた。
     - **見送った案**: `_build_search_materials_uncached`が既にメモリ上に持つ
       グラフ・材料（リクエストbboxの範囲のみ）をそのままタイル単位キャッシュへ書き込む
       案は、bboxがタイル境界と一致しないため不完全なデータをタイルキーで永続化しうる
       （タイルの一部だけがbboxに含まれる場合、キャッシュされた材料がタイル全体を
       カバーせず、次回同じタイルを使う別リクエストが一部のEdgeを見落とす）ため見送った
       （T248候補1a「案B」がタイル分割ロジックの複雑性を指摘していたのと同じ理由）。
     - **採用した方式**: レスポンスを返した後、バックグラウンドで対象タイルを正規の
       経路（`_get_or_build_tile_materials`、タイル全体をDBから取得する既存メソッドの
       再利用）で温める。タイル全体を読み直すため、部分データによる不整合リスクが無い。
       `region_service.py`の`_maybe_trigger_graph_build`/`_build_graph_for_tile_background`
       （T59、地図タイル閲覧起点のバックグラウンド道路グラフ構築）と同じ設計判断
       （新規セッション・fire-and-forget・in-flight重複防止セット・失敗時はログのみで
       元のレスポンスに影響させない）を、対象データ・キャッシュ先が異なるため
       `graph_service.py`側に独立して実装した（`_maybe_warm_tile_cache`/
       `_warm_tile_cache_background`/`_warming_tiles`）。
     - **isinstanceガード**: `region_service.py`の既存箇所と同じ理由で、
       `isinstance(self._repository, RoadGraphRepository)`が真の場合のみ発火させる
       （テストの`FakeRoadGraphRepository`はダックタイピングでこのクラスを継承しない
       ため、ユニットテストが実DBセッションを開こうとすることはない）。
     - **テスト**: `test_graph_service.py`に6件追加（`_maybe_warm_tile_cache`が
       タイルごとにバックグラウンドタスクを起動すること・キャッシュ済み/温め中の
       タイルをスキップすること・失敗時もin-flightマーカーを解除すること・
       isinstance判定で実リポジトリのときのみ発火し`FakeRoadGraphRepository`では
       発火しないこと）。isinstance判定用に`__getattribute__`で全属性を委譲する
       `_RealRepositoryStandIn`を新設（`RoadGraphRepository`自体が同名の実メソッドを
       持つため、region_service.pyの`_FakeRealRoadGraphRepository`と同じ単純な
       継承オーバーライドでは足りなかった）。backend全体1132件green（直列実行、
       pytest-xdist特有の既存フレーク[T248本文既述]を除く）。
     - **効果**: split直後の2回目アクセスも、1回目のレスポンス後まもなくバックグラウンド
       温めが完了していれば真の温パス（4.9秒）を得られるようになる（温め自体の所要時間
       ぶんの猶予が必要なため、1回目の直後すぐの2回目アクセスでは間に合わない場合が
       残る点に注意）。
- **完了条件の達成状況**: 温パス5秒以内はT224目標どおり達成済み（4.9秒実測）。
  「冷パスの体験方針」はユーザー判断により、バックグラウンドウォームアップ・事前split等の
  大掛かりな設計は実施せず将来課題として保留する方針とした（T265へ切り出し）。
  以上をもって本タスクは完了とする。

### - [ ] T265. 冷パスの体験設計（バックグラウンドウォームアップ・主要エリア事前split・進捗表示） 規模M〜L — トリガー: 一般公開の意思決定、または研究利用での冷パス体感遅延に関する具体的な要望・報告

- 発端: T248完了条件「冷パスの体験方針の決定・実装」のうち、方針決定のみ行い実装は
  見送った本体をこちらへ切り出し（2026-08-24、ユーザー指示「バックグラウンドウォーム
  アップ等の大掛かりな設計は将来的な改善要素として今は実施しない課題として再登録して
  ほしい」）。
- **現状（T248時点までの調査結果、詳細はT248候補2参照）**: 未splitな新規地点への
  初回アクセスは、T263（Oracle VM移行）・T264（closure_ms削減）・T248（バルクUPSERTの
  COPY化・材料クエリ統合等）を経て20km級で30〜45秒程度まで縮んでおり、以前のような
  「完全な失敗」（T259、Renderの約100秒プラットフォームタイムアウト）ではなくなった。
  フロントは「生成中...」のボタン無効化のみで、進捗・見込み時間の表示は無い
  （[RouteForm.tsx](frontend/src/components/RouteForm/RouteForm.tsx)）。
- 保留すると何がブロックされるか: 30〜45秒（今後データ量増加でさらに伸びうる）の
  無反応な待ち時間中、ユーザーには「フリーズしているのでは」という不安が残る。また、
  未splitエリアへの初回アクセスが多数同時に発生した場合（例: 新機能公開直後のアクセス
  集中）、`graph_build_max_concurrent`のガード自体はあるが、待たされるユーザー体験の
  改善（進捗表示・事前warmup）は未着手のまま。一般公開判断が先送りされている間は
  実害が顕在化しにくいため、優先度は低いまま維持してよいという判断（ユーザー承認）。
- 検討対象（T248候補2の調査結果を引き継ぐ）:
  1. **バックグラウンドウォームアップ**: T59の`_maybe_trigger_graph_build`
     （地図タイル閲覧起点）はルート生成側から一切呼ばれておらず転用不可と判明済み。
     ルート生成専用の非同期ジョブ化（リクエストを即座に受理し、ポーリング/WebSocket等で
     完了を通知する設計）が必要。
  2. **主要エリアの事前split**: 関東本土の主要都市・観光地を対象に、デプロイ後や
     定期バッチで先回りしてsplitしておく方式。対象エリアの選定基準（アクセスログ由来か
     固定リストか）が未検討。
  3. **進捗表示**: 上記1・2をやらない場合の最小対応として、フロントに「初回アクセス
     地点は時間がかかる場合があります」等の待機中メッセージ・経過時間表示を追加する
     軽量な選択肢（規模S相当、本タスクとは別に着手も可能）。
  4. コールドパスには(a)未split→`save_graph`再構築が重いケースと(b)split済みでも
     材料読み出し自体が重いケース（T248 1a〜1eで大きく改善、ただしT264が指摘した
     「split済みデータの転送量そのもの」の律速は根本解消していない）の2種があり、
     対策を分けて設計する必要がある（T248候補2調査時点の知見）。
- 完了条件: 未確定（着手時に対応候補を1つ以上選び、設計判断とともに確定する）。

### - [x] T256. 都心部（新宿・渋谷）でルート生成が候補0件になる事象の原因調査＋修正 規模S〜M（2026-08-24完了）

- 発端: T248の本番実測（2026-08-23、専用worktreeでDATABASE_URLを本番Oracle Cloud
  PostGISへ向けた直接サンプリング）で偶発的に発見。
- 事象: 新宿駅(35.6896,139.7006)・渋谷駅(35.6580,139.7016)を起点にdistance_km=10〜20
  （半径≈3.3〜6.7km）で`/api/routes/generate`を実行すると、8方位すべてでtrace失敗し
  候補0件になる。60〜152秒（新規split時）ないし66〜92秒（split済みデータの読み込みのみ）
  待たされた末の結果であるため、単なる低速ではなく「時間をかけても使えない」という
  T248より深刻な体験。DEBUG_MODE有効時の詳細ログでは全方位が
  `RoutingError("no path found between waypoints")`で失敗しており、waypointの
  最近接ノードへのスナップ自体は成功している（＝スナップ失敗ではなく、
  scipy.sparse.csgraph Dijkstraでの経路探索が起点↔経由地間で経路を見つけられていない）。
  半径を10km→20kmに拡大しても再現するため、単純な半径不足ではなさそうである。
- 対照実験: 同じ本番実測で王子15km（候補7件・8/8成功）・前橋10km（候補8件・8/8成功）・
  銚子25km（候補2件・6/8成功、沿岸のため2方位失敗は妥当）はいずれも正常に候補を返しており、
  密集した都心部（山手線内側相当）特有の事象である可能性が高い。一方通行の多さ等、
  役場道路網のトポロジ的特性が疑われるが未検証。
- 影響範囲（保留・未着手のまま次に何が起きうるか）: これまでの性能実測はほぼ王子を
  起点に行われており（T236・T242〜T247）、王子は正常系のため本事象はT247での
  road_graph既定化以降も検出されずに残っていた。研究利用者が実際に試す可能性が高い
  都心部（新宿・渋谷等の主要駅）で発生するため、影響を受ける利用者の割合は郊外での
  発生より大きいと想定される。原因未特定のまま放置すると、T248（性能改善）に着手して
  冷パスを高速化しても、都心部では「速く0件が返る」だけで体験は改善しない。
- 完了条件（調査フェーズ）: 原因を切り分け、以下のいずれかに分類する。
  1. road_graphエンジンの経路探索ロジックの不具合（one-way処理・グラフ構築の
     連結性等）→ 修正タスクとして規模を見積もり直す。
  2. 本番DBのデータ品質固有の問題（特定エリアのOSMデータ・split処理の副作用等）→
     dev DBでも再現するか確認し、再現すればロジック側、しなければデータ側の問題として
     切り分ける。
  3. 既知の事象（T241「8方位中平均1〜2方位が見つからない」）の延長で説明できる限定的な
     ものと判明した場合は、その旨を記録し見送り判定とする（ただし今回は8/8全滅のため
     T241とは事象の severity が異なる点に留意）。
- 参考: T241（道路グラフの連結性、規模不明、8方位中平均1〜2方位の失敗は残存するが実運用
  影響は限定的と評価済み）。
- **原因特定（2026-08-23、専用worktreeでdev DBに対し直接調査）**: 上記完了条件の
  分類1（road_graphエンジンのロジック不具合）と判明。dev DB（東京都心南部データ）でも
  同じ条件で全方位失敗を再現し、本番DB固有の問題ではないことをまず確認した。
  次にdev DBへ直接SQLで最近傍`road_nodes`とその接続`road_edges`のhighwayタグを
  問い合わせたところ、新宿駅最近傍ノード（76m）・渋谷駅最近傍ノード（33m）はいずれも
  **接続edgeが全て`highway=trunk`（甲州街道・明治通り等の国道）のみ**という構造だった。
  一方、王子駅・前橋駅の最近傍ノードは`unclassified`で正常。
  - **根本原因**: `find_nearest_node_indexed`（`domain/routing.py`、`prepare`の
    origin_nodeスナップ・`trace_loop`の経由地スナップ両方で使用）は
    `build_node_spatial_index`が保持する**フィルタ前の生グラフ**（`search.graph`、
    Hard Constraint適用前）から純粋に地理的最近傍のNodeを選ぶ。一方
    `build_sparse_graph`（探索本体が使う`sparse_graph`）は`is_edge_allowed`の
    Hard Constraint（既定`DEFAULT_HARD_FILTERS={"no_bicycle","motorway","trunk"}`、
    `evaluation.py:63`）で`trunk`Edgeを除外する。主要駅が国道の幹線交差点に直接
    面していると、最近傍Nodeの接続Edgeが全てtrunkで除外され、探索用グラフ上では
    孤立点（次数0）になる。この状態でorigin_nodeからDijkstraを実行すると
    到達可能なNodeが存在せず、半径や経由地の位置に関わらず8方位すべてが
    `no path found`で失敗する（実際には50〜100m先に自転車で通行可能な道路網が
    広がっているにもかかわらず）。
  - 影響範囲の裏付け: 新宿・渋谷はいずれも駅前が国道の幹線交差点に面する典型例で、
    同種の主要駅（他にも新橋・池袋等、国道と直接面する駅は都心に多い）で同様の事象が
    起きうる。
  - 対応方針（次に着手する場合の規模見積もり、実装は未着手）: `find_nearest_node_indexed`
    （またはその呼び出し元の`prepare`/`trace_loop`/`preview_segment`）で、Hard
    Constraint適用後も次数1以上を保つNodeのみを候補にする。具体的には
    (a) 索引を`search.graph`ではなく`sparse_graph`側のNode集合から構築する、または
    (b) 最近傍探索が孤立Nodeに当たった場合はグリッドリング探索を継続し次善のNodeへ
    フォールバックする、のいずれか。影響箇所は`road_graph_engine.py`の
    `prepare`・`preview_segment`（node_index構築）と`domain/routing.py`
    （`build_node_spatial_index`/`find_nearest_node_indexed`）。規模S〜M（ロジック変更は
    限定的だが、origin・waypoint両方のスナップ経路・関連テストの追従が必要）。
- **実装（2026-08-24完了）**: 対応方針(a)を採用。
  1. `domain/routing.py`に`routable_node_ids(sparse_graph)`を新設。`sparse_graph.matrix`
     の非ゼロ行・列（＝Hard Constraint通過後も最低1本Edgeを持つNode）の和集合をNode ID
     集合として返す。
  2. `build_node_spatial_index`へ`node_ids`引数（省略時None=従来どおり`graph.nodes`
     全件、互換維持）を追加し、索引の構築対象を絞れるようにした。
  3. `road_graph_engine.py`の`prepare`・`preview_segment`で、`node_index`構築時に
     `node_ids=routable_node_ids(search.sparse_graph)`を渡すよう変更（2箇所）。
     索引の候補が孤立Nodeを含まなくなるため、`find_nearest_node_indexed`は地理的最近傍
     ではなく「実際に経路探索可能な」最近傍Nodeを返すようになる。
  4. テスト追加: `test_routing.py`に`routable_node_ids`の単体テストと、
     `build_node_spatial_index`のnode_ids絞り込みが孤立Nodeをスキップし次善のNodeを返す
     ことを確認する回帰テスト。`test_road_graph_engine.py`に`prepare`が孤立Node（trunk
     のみに接続）を避けて隣接する経路探索可能なNodeへスナップすることを確認する
     エンドツーエンドの回帰テストを追加。既存の
     `test_prepare_excludes_edge_exceeding_max_average_grade_percent_from_search_graph`
     は起点自体が全Edge除外で孤立してしまう構成だったため、除外されない迂回Edgeを
     追加して起点が孤立しないよう調整（新設のnode_ids絞り込みによりprepareがNoneを
     返すようになったための追従）。
- 検証: backend全体1080件green。dev DB（東京都心南部データ、ネイティブPG）に対し
  修正後のコードで実際に`/api/routes/generate`を再実行し、新宿10km（修正前:
  候補0件/8方位全滅 → 修正後: **候補8件・8/8成功**、prepare_ms=35,188）・
  渋谷10km（修正前: 候補0件/8方位全滅 → 修正後: **候補6件・6/8成功**、
  prepare_ms=66,797、残り2方位は距離フィルタ等の別要因で妥当な範囲）を確認した。

### - [x] T249. 統合レビュー第7回の軽微指摘一括 規模S（2026-08-23完了）

- 発端: 統合レビュー第7回 統合-3（P3）。
- 対応内容:
  1. `config.py:88-92`の接続プール上限コメントがT243の2系統エンジン化に未追従
     （「ルート生成用の接続と合わせてもプール上限（15接続）に収まり」という単一プール
     前提の記述が残る。実態はタイル配信系15＋ルート生成系15の2プール）。
  2. `.env`未作成のDBなし環境で、T247以降は既定`road_graph`のため
     `/api/routes/generate`が常に失敗する（`.env.example`には注記済みだが、コピーせず
     起動した場合には効かない）。起動時（lifespan）にroad_graph既定でDB接続不可の場合の
     WARNING1行を追加する。
- 完了条件: コメント更新＋起動時WARNING実装、backend全テストgreen。

- **実装メモ（2026-08-23完了）**:
  1. `config.py`のプール上限コメントを2系統プールの実態（タイル配信系15＋ルート生成系15、
     合計最大30接続で本番max_connections=100に余裕あり）へ更新。「Supabase側」という
     Oracle Cloud移行前の記述も「DB側」へ訂正。
  2. `main.py`の起動時スナップショットログの直後に、`routing_engine=road_graph`の場合の
     案内ログを追加。設計判断: (a) 起動時点ではイベントループ起動前のため実際のDB接続
     確認は行わず、設定の組み合わせのみで判定する（実際に接続不可かはリクエスト時の
     エラーで判明するため、ここはその読み解きの補助）、(b) DB接続ありの正常環境でも
     出るためレベルはWARNINGでなく**INFO**にした（正常構成で毎回WARNINGが出ると
     「WARNINGは常時異常のシグナル」というログ方針が薄まるため。docs/logging.mdの
     方針との整合を優先）、(c) DATABASE_URLは`@`以降（ホスト名部分）のみをログに出し
     認証情報を含めない。
- 検証: backend全体1077件green。起動ログの実出力（ホスト名のみ表示・案内文言）を
  実機確認済み。

## モバイル画面のスペース有効活用（2026-08-23・ユーザー指示）

### - [x] T250. スマホ上部バーへ出発地点・距離・生成ボタンを集約＋下部タブ再定義 規模S〜M（2026-08-23完了）

- 発端: ユーザー実機フィードバック「ルートを作るUIがスマホだと使いにくい。作成した
  ルートを地図で見ながらポイントになるところを見る、という使い方をするのだが、
  スマホだと少ないスペースを有効活用できるようにしたい」。「まずは上部バーのUI工夫して」
  との指示のため、今回は上部バー改修のみを対象にする（下部タブ本体の構成見直し・
  RouteListの表示方法変更等は範囲外、必要になれば別タスクとして起票）。
- 対応内容（モバイルのみ。デスクトップのサイドバー「ルートを作る」ブロックは現状維持）:
  1. 出発地点（LocationControl）を、常設の天候ヘッダー直下に新設したモバイル専用の
     操作バーへ移動。表示は座標を省き出典ラベルのみの1行に圧縮し、詳細はtitle属性へ
     退避（`compact`プロパティを追加）。
  2. 距離入力・ルート生成ボタン（RouteForm）も同じ操作バーへ移動。ボタン文言は
     「ルート生成」→「生成」に短縮（`compact`プロパティを追加）。
  3. 生成ボタンがタブを開かずとも常時押せるようになったことで、生成失敗時のエラー
     メッセージが従来のように「ルートを作る」シート内に隠れたままだと見えなくなる
     （以前は生成ボタン自体がそのシートの中にあったため、シートを開かないと押せず、
     結果として押した時点でエラー表示も見えていた）。回帰を避けるため、エラー
     メッセージは新しい操作バー側にも表示する。
  4. 下部タブ「ルートを作る」を「ルート詳細」へ改名。出発地点・距離入力・生成ボタンが
     ヘッダーへ移ったことで、このタブの中身は生成結果（RouteList・比較パネル・
     ルートの色分け設定・条件dirtyヒント）のみになる。
- 完了条件: フロントエンドの型検査・既存テストgreen、LocationControl/RouteFormの
  `compact`分岐に対するテスト追加、Playwrightでモバイル幅の実機確認。

- **実装メモ（2026-08-23完了）**:
  - `tsc --noEmit`・ESLint・vitest（LocationControl/RouteForm、compact分岐のテスト追加分含む）
    すべてgreen。
  - Playwright（一時spec、検証後削除）でモバイル幅(390x844)実機確認: ヘッダー直下の
    操作バーに出発地点・距離入力・生成ボタンが1行で収まること、生成→「ルート詳細」タブが
    地図を覆わない部分シートとして開き候補一覧が見えることを確認。デスクトップ幅でも
    別specでサイドバー側（出発地点・距離・「ルート生成」ボタン）が従来通り表示され、
    モバイル専用の操作バー・改名後のタブラベルが出ないことを確認（回帰なし）。
  - スコープ外として明記した下部タブ本体の構成見直し・RouteListの表示方法変更は
    今回未着手（次に着手する場合は新規タスクとして起票）。

### - [x] T251. 定番UIライブラリでの現行UI同等再現可否・規模の調査 規模M（2026-08-23調査完了、実装は未着手）

- 発端: T250対応中にユーザーが表明した方針（「新規UI機構は自前実装より定番ライブラリを
  優先検討」、進め方の原則へ追記済み）を受け、「今後もデザイン変更・調整を続けるので、
  早い段階で定番ライブラリ・汎用的な拡張機構を用意しておきたい」との指示。新規追加時に
  限らず、**現時点のUIを定番ライブラリ（Radix UI Primitives、vaul等）で同等再現できるか、
  それにどれだけの規模がかかるかを先行調査する**（実装はしない、調査のみ）。
- 完了条件: frontend/src/components配下の汎用UI機構（タブ・折りたたみ・ボトムシート・
  スライダー・トグル/ラジオグループ・モーダル/ポップオーバー等）を棚卸しし、component単位で
  候補ライブラリ・実現性・移行規模（S/M/L）を判定した表を作成。特にBottomSheet
  （地図のピンチズームと衝突しないtouch-action調整・暗幕なし表示という実機チューニング
  済みの独自要件を持つ）は個別にリスクを検討する。Tailwind導入の要否（Radix系ライブラリの
  多くはheadlessでCSS Modulesとも併用可能なため、必須ではない）も論点として明記する。

- **調査メモ（2026-08-23完了、Tailwind検証・ユーザー指摘による訂正を反映）**:
  frontend/src/components配下26コンポーネントを棚卸し（調査レポートはArtifactとして
  作成、ユーザーへ共有済み）。
  - **適合（規模S、機械的に置換可）**: トグルチップ（LayerChip等）→Radix Toggle、
    ラジオ/セグメント選択（ルート色分けモード・LevelPicker）→Radix RadioGroup/ToggleGroup、
    情報開閉ボタン（FieldLabelのinfoButton）→Radix Popover、アコーディオン
    （サイドバー4ブロック・MapLayersPanel・WeightPanel等の`<details>`）→Radix Accordion
    （ただし現状で機能不満はなく優先度低）、汎用アイコンのみ→lucide-react等（大半は
    ドメイン固有で流用不可、効果限定的）、**FloatingPanel（DebugConsole/SystemStatusPanel
    の共通シェル）→react-rnd**（`dragHandleClassName`で現行のハンドル限定ドラッグを再現可、
    `bounds="window"`で画面外へ出ないようクランプする現行に無い改善も可能）。
  - **要検証（規模M〜L）**: BottomSheet→vaul(Drawer)。ドラッグ高さ変更・暗幕なし・
    地図のピンチズームと衝突しないtouch-action調整という3つの独自要件はいずれもvaul単体
    では自動的にカバーされず、個別の実機再検証が要る。**DynamicLayerTimeSlider→Embla
    Carousel**（可変幅スライド・公式wheel-gesturesプラグイン・`align:"start"`スナップは
    いずれも標準機能でカバーできることを確認したが、キーボード操作(Arrow/Home/End)と
    `role="slider"`のARIA意味づけは今と同程度の自前配線が残る）。
  - **対象外**: RouteFormのバリデーション（数値1項目のみで導入コストに見合わない）、
    モバイル判定の二重管理（useIsMobile/globals.css、ライブラリで解決する種類の課題ではない）。
  - **訂正の経緯**: 初回調査ではRadix UI Primitivesの守備範囲だけで判定し、
    DynamicLayerTimeSlider・FloatingPanelを「適合ライブラリなし・非推奨」と誤って結論して
    いた。ユーザーから「類似のコンポーネント実装は世の中にはないか」と指摘を受けRadixに
    限定せず調べ直し（WebSearchでEmbla Carousel公式ドキュメント・react-rnd npmページを
    確認）、上記へ訂正した。
  - **Tailwind導入も検証**: 「下部シートの余白調整のようなデザイン微調整を素早く試したい」
    という動機を受け、①フル移行（26コンポーネント全書き換え、非推奨・規模L）②新規コード
    のみ（導入は軽いが既存ファイルの不満は解決しない）③既存CSS Modulesと併用しJSX上で
    ユーティリティクラスを都度足す（推奨・規模S）の3方式を比較。globals.cssの
    `--space-1〜4`（0.25/0.5/0.75/1rem）がTailwind既定のスペーシングスケールと数値一致
    しており、CSS変数を書き換えずに橋渡しできることを確認。あわせてBottomSheetの
    ヘッダーが窮屈に見える原因を実装から特定: 閉じるボタンの`min-width/height: 44px`
    （タップ領域確保の設計判断）が支配的で、Tailwind導入そのものでは解決しない
    （現行CSSのままでも数行の調整で対応可能）。
  - **推奨順序**: Phase0（Tailwind併用導入、規模S）→Phase1（トグル/ラジオ/Popover/
    FloatingPanel→react-rnd、規模S〜M）→Phase2（アコーディオン、任意・規模S）→
    Phase3（BottomSheet→vaul・DynamicLayerTimeSlider→Embla、規模M〜L、実機検証込み）。
  - 次のアクション: T251の推奨順序（Phase0〜3）をPhaseごとの個別タスク
    （T252〜T255、下記）として起票した。

**T252〜T255は並行して進行中の別セッションの作業が完了してから着手する
（2026-08-23、ユーザー指示）。それまでは4件とも指示待ちで保留する。保留による
実害はない（他のタスク・本番挙動をブロックしない、UI機構自体は現行の自前実装のまま
問題なく動作し続ける）ため、トリガーは「別セッション完了後のユーザーからの着手指示」
のみとする。着手する場合はT252→T253→T254→T255の順（T251の推奨順序どおり、後続
Phaseほど前Phaseの成果を安全網として使える）。**

### - [x] T252. Phase0: Tailwindの併用導入 規模S（2026-08-23完了）

- 発端: T251の調査結果。「デザインの微調整を素早く試したい」という動機（下部シートの
  余白調整等）を受け、既存CSS Modulesは維持したままTailwindのユーティリティクラスを
  併用できるようにする（T251「③併用（推奨）」方式）。
- 対応内容: `tailwindcss`/`@tailwindcss/postcss`を追加し、globals.cssへ
  `@import "tailwindcss";`。既存の`--space-*`/`--color-*`をTailwindの`@theme`で
  トークンとして取り込めるか検証（`--space-1〜4`は既にTailwind既定のスペーシング
  スケールと数値一致していることをT251で確認済み）。既存CSS Modulesファイルは変更しない。
- 完了条件: ビルド成功、既存の全画面表示に差分が出ないことを確認、型検査/ESLint green。
  T253以降でTailwindユーティリティを使う具体例（例: BottomSheetヘッダーの余白調整）を
  1件試して動作確認する。

- **実装メモ（2026-08-23完了）**:
  1. **導入**: `tailwindcss`/`@tailwindcss/postcss`を追加、`postcss.config.mjs`新設、
     `globals.css`先頭へ`@import "tailwindcss";`。`--space-1〜4`はTailwind既定の
     スペーシングスケール（`--spacing: 0.25rem`単位）と数値一致するため@theme上書き
     不要と確認。`--color-*`はダークモードを`@media (prefers-color-scheme: dark)`内の
     再定義で切り替える実装のため、`@theme`（静的値へ固定される）へは取り込まず
     `var(--color-*)`を個別クラスで参照する運用とした（取り込むとダークモード追従が
     壊れるため）。
  2. **重大な発見（1件試す動作確認で発覚）**: 完了条件の「1件試す」検証
     （一時ページ+一時Playwright spec、検証後削除）で`p-2`等のpaddingユーティリティが
     `padding:0`のまま効かないことを発見。原因はCSS Cascade Layersの仕様
     （unlayeredなルールはレイヤー内のルールに詳細度・順序に関係なく常に勝つ）と、
     既存`globals.css`の`* { padding:0; margin:0 }`等の汎用リセットがunlayeredの
     ままだったことの組み合わせ。Tailwindの`.p-2`は`@layer utilities`内にあるため
     機械的に無効化されていた。これはT252の動機そのもの（下部シートの余白調整）を
     阻害する致命的な穴のため、Phase0のうちに修正: `globals.css`の汎用リセット
     （`*`/`html`/`body`/`a`/`button`/`input`の既定値）を`@layer base`へ包み、
     Tailwindが内部で宣言する`@layer theme,base,components,utilities;`の同名
     レイヤーへ合流させ、`utilities`が正しく優先されるようにした。一方MapLibre
     ポップアップの配色上書き（別のunlayeredな`maplibre-gl.css`に詳細度で勝つ設計）と、
     モバイルの44pxタップ領域確保ルール（アクセシビリティ要件を意図的にどのユーティリティ
     クラスにも負けないよう保つ安全網）はunlayeredのまま維持し、その理由をコメントで
     明記した。ユーザー指示により、globals.css以外の全CSS（.module.css全件・
     `:global()`ブロック）も棚卸しし、他に同種の危険な汎用unlayered指定が無いことを
     確認済み（MapLibre関連の`:global()`上書きのみで、いずれも同じ理由で意図的に
     unlayered）。
  3. **副次的に発覚した既存バグ（E2Eサーバーの本番不一致）**: 検証中、Playwrightの
     webServerログに`"next start" does not work with "output: standalone"
     configuration`という警告を発見。`next.config.ts`は`output: "standalone"`
     （本番Dockerfileが`node server.js`で起動する構成）だが、`playwright.config.ts`の
     webServerは`next start`（`npm run start`）を使っており、E2Eがローカル・CIとも
     本番と異なるサーバー実装をテストしていた（フルリポジトリがある環境では
     `next start`でも動作するため偶然気づかれていなかった、T252以前からの既存問題）。
     `frontend/scripts/prepare-standalone.mjs`を新設（Dockerfileの`COPY .next/static`・
     `COPY public`相当をNode標準`fs.cp`でクロスプラットフォームに再現）、
     `package.json`へ`start:standalone`スクリプトを追加、`playwright.config.ts`の
     webServerを`npm run build && npm run start:standalone`へ切替。修正後は警告が
     消え、本番と同じ`node .next/standalone/server.js`エントリポイントでE2Eが走る。
  4. **副次的に発覚した問題（ローカルE2Eのリソース競合）**: 検証中、Playwrightの
     既定worker数（CPU論理コア数ベース）のまま3並列実行すると、同一のwebServer
     プロセスへ複数のヘッドレスChromiumが同時に地図（MapLibre GL・WASM）を読み込みに
     行き、ページ遷移・`beforeEach`フックが軒並み30秒タイムアウトする事象を複数回
     実測（ユーザー報告「同じようにリソース競合でタイムアウトすることが多い」を受け
     切り分け）。`workers: process.env.CI ? undefined : 1`でローカル実行を明示的に
     直列化し、同条件で安定して全green化を確認。CIはGitHub Actions側のジョブ専有
     リソースを前提に対象外。あわせて`docs/testing.md`へパターン4として本項目
     （本番同等サーバー・workers=1）を追記。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`
    いずれもgreen。Playwright E2E（smoke.spec.ts、standalone起動・workers=1）2件green。
    一時ページ・一時specは検証後に削除済み。

### - [x] T253. Phase1: 点在する小部品の置換＋FloatingPanel→react-rnd 規模S〜M（2026-08-23完了）

- 発端: T251の調査結果。
- 対応内容: トグルチップ（LayerChip等）→Radix Toggle、ラジオ/セグメント選択
  （ルート色分けモード・LevelPicker）→Radix RadioGroup/ToggleGroup、情報開閉ボタン
  （FieldLabelのinfoButton）→Radix Popover、FloatingPanel（DebugConsole/
  SystemStatusPanelの共通シェル）→react-rnd（`dragHandleClassName`でハンドル限定
  ドラッグを再現、`bounds="window"`で画面外へ出ないようクランプ）。
- 完了条件: 各コンポーネントの既存vitestテストgreen（必要なら更新）、Playwrightで
  モバイル実機確認、型検査/ESLint green。

- **実装メモ（2026-08-23完了）**:
  1. **LayerChip→Radix Toggle**: `pressed`/`onClick`（生イベント）のみ渡し、
     `onPressedChange`は使わない設計にした。`<summary>`内で使う呼び出し側
     （RecipePanelSection）が`event.preventDefault()`で親detailsの開閉を止めることが
     あり、Radixの`composeEventHandlers`は`defaultPrevented`時に内部トグルハンドラを
     スキップする仕様のため、内部ロジックへ依存すると押下が反映されないケースが生まれる
     ことが分かった。押下状態は従来どおり呼び出し側が完全外部管理のまま、Radixは
     セマンティクス（aria-pressed/data-state）とキーボード操作の提供に留める。
  2. **LevelPicker→Radix RadioGroup**: `role="group"`+個別`aria-pressed`ボタンの
     自前実装（矢印キー移動なし）から、`role="radiogroup"`/`role="radio"`＋roving
     tabindex（矢印キー移動が標準で付く）へ。見た目（`data-filled`+`--level-color`の
     進捗バー表現）はCSS変更なしで維持。呼び出し側テスト4ファイル
     （recipeControls/RoadSuitabilityRecipePanel）の`role: "group"`→`"radiogroup"`、
     `role: "button"`→`"radio"`、`aria-pressed`→`aria-checked`を更新。
  3. **ルート色分けモード（page.tsx）→Radix RadioGroup**: 既に手書きで
     `role="radiogroup"`/`role="radio"`/`aria-checked`を実装していた箇所を置き換え、
     矢印キー移動を標準搭載化。
  4. **FieldLabelのinfoButton→Radix Popover**: 単純な置換に留まらず設計を見直した。
     従来は`open`/`onToggle`を呼び出し側が持ち、説明文（`infoTooltip`）を呼び出し側が
     DOM上の直後（`<p>`または`<tr colSpan>`、呼び出し側ごとに配置形が違った）へ
     個別に配置していた。Popoverはトリガー位置基準のフローティング表示のためDOM配置に
     依存せず、開閉状態もFieldLabel自身が持てるようになったため、`open`/`onToggle`を
     廃し`description`を渡すだけのAPIへ簡素化した。呼び出し側4箇所
     （ScalarInput/ThresholdAdjustmentRow/WeightInput/HighwayRow）から
     `useState`＋条件付きレンダリングの重複コードが消え、`WeightPanel.module.css`/
     `RoadSuitabilityRecipePanel.module.css`の重複していた`infoTooltip`系クラスも削除。
     `.infoTooltip`（recipeControls.module.css）はPortal描画に伴い地の文から
     カード状の見た目（背景・枠線・影、MapLibreポップアップと同トークン）へ変更、
     z-index:46（BottomSheet:45より前面、FloatingPanel:50より背面）。
     `recipeControls.test.tsx`のFieldLabelテストを新API（`description`渡し・
     Popover開閉）へ書き換え。
  5. **FloatingPanel→react-rnd**: 自前のpointerイベントによるposition state管理を
     `Rnd`（`dragHandleClassName`でヘッダーのつまみへドラッグ限定、
     `bounds="window"`で画面外クランプ、`enableResizing={false}`でリサイズ不可は
     維持）へ置換。幅（`widthRem`）は従来どおりCSS側の`min(widthRem, 100vw -
     2*space-3)`で応答的に決め、Rnd自体はx/y位置のみ管理する設計にした
     （Rndのsize経由の固定px化だとウィンドウ幅変更に追従しなくなるため）。
     Rndはx/y絶対px指定のみでCSSの`left:50%+transform:translateX(-50%)`のような
     相対中央寄せができないため、開いた直後に`useLayoutEffect`（ペイント前に同期実行）
     で実際の描画幅を測って中央寄せのx座標を計算し反映する設計にした。Rndの既定
     `style.position`は`"absolute"`（ページスクロールに追従）のため、元のCSS
     （`position:fixed`）と同じビューポート基準の浮遊挙動を保つよう`style`propで
     `"fixed"`に上書きした。
  - **実機確認（Playwright、一時spec・検証後削除）**: モバイル幅(390x844)で
     (a) SystemStatusPanel（FloatingPanel/react-rnd）をハンドルドラッグし、画面外まで
     引っ張ってもbounds="window"でクランプされ座標が0以上に収まること、実際に位置が
     変わることを確認。(b) 研究タブでWeightPanelのFieldLabel Popoverを開き、
     BottomSheetの`overflow-y:auto`にクリップされずポータル先の内容が画面内
     （x/y≥0）に収まること、RoadSuitabilityRecipePanelのLevelPicker（RadioGroup）を
     クリックしaria-checkedが正しく切り替わることを確認。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`・
    Playwright smoke.spec.ts（standalone・workers=1）いずれもgreen。

### - [x] T254. Phase2: アコーディオンをRadix Accordionへ 規模S（2026-08-23完了、事前見積もりを上回るM相当の作業になった）

- 発端: T251の調査結果。サイドバー4ブロック（page.tsx）・MapLayersPanel・WeightPanel等の
  `<details>`をRadix Accordionへ置き換える。現状で機能不満はなく優先度は低いため、
  アニメーション等の明確な要望が出るまで見送ってもよい。
- 完了条件: 既存の開閉挙動（デスクトップ「ルートを作る」ブロックの状態外部管理を含む）
  と同等以上、既存テストgreen。
- **着手判断（2026-08-23）**: 実装前の調査で規模Sの見積もりを上回る3つの技術的課題
  （button内buttonの無効なHTML・Radix Accordionの追加DOM階層によるCSS/テスト影響・
  ネイティブ`<details>.open`へのテスト依存26箇所超）が判明したため、着手前にユーザーへ
  規模超過を報告し方針を確認した（AskUserQuestion）。ユーザー判断「計画通り進める」を
  受けて実施。

- **実装メモ（2026-08-23完了）**:
  1. **共通部品`Disclosure`を新設**（`frontend/src/components/Disclosure/`）。9ファイル・
     15箇所超の`<details>/<summary>`をRadix Accordion（`type="single" collapsible`、
     常に1項目のみ＝各セクションが独立開閉する既存の`<details>`と同じ挙動）でラップする
     共通コンポーネント。`Accordion.Item`は`display:contents`で透過させ親CSSへの影響を
     最小化。
  2. **button内buttonの回避**: MapLayersPanel（LayerChip「表示」）・
     RecipePanelSection（LayerChip「上書き」）の2箇所は見出し内に別のインタラクティブ
     ボタンをネストしていた。Radix `Accordion.Trigger`は実体が`<button>`のため、
     そのままネストすると無効なHTMLになる。`trailing` propでTrigger外（見出し行のflex
     コンテナ内の兄弟）に配置する設計へ変更し、以前`<summary>`内クリックの既定動作
     （details開閉）との衝突回避に必要だった`preventDefault`/`stopPropagation`を
     両箇所から削除できた（構造的に開閉トリガーへ伝播しなくなったため不要に）。
  3. **h3のtextContent汚染バグを実機不要で発見・修正**: 当初`trailing`をAccordion.Header
     （h3）の中に置いたところ、h3のtextContentに見出しテキスト＋trailingの文言
     （「勾配表示」等）が混入し、テキスト完全一致で検証する既存テストが複数破壊された。
     `trailing`がある場合のみ見出し行の視覚的な横並び（flex row）を素の`<div>`が担い、
     h3自体はTriggerだけを包む薄い意味付けに留める設計へ修正（trailingが無い単純な
     場合は素のh3のみで済ませ余計なラップを増やさない）。
  4. **ネイティブ`<details open]`>属性→Radix `data-state`のCSS移行**: 3ファイル
     （MapLayersPanel/WeightPanel/recipeControls、他3ファイルはcomposesで追従）の
     chevron回転セレクタを`.layerSection[open] > .layerHeader .chevron`から
     `.layerTitle[data-state="open"] .chevron`（Triggerが自身にdata-stateを持つため
     祖先属性セレクタが不要になった）へ書き換え、`::-webkit-details-marker`の
     dead CSSを削除。page.tsx側3ブロックはネイティブ`<summary>`の既定ディスクロージャ
     三角に頼っていたため（自前chevronが元々無かった）、Radix化でこれが失われる
     退行を防ぐため`.blockChevron`を新設した。
  5. **テストのjsdom依存差分**: 旧`<details>`はjsdomが閉じた中身も隠さずクエリ可能にする
     （実ブラウザのUAスタイルとは異なる）挙動だったため、多数の既存テストが開閉状態を
     意識せず中身を直接検証できていた。Radix Accordion.Contentは閉じるとネイティブ
     `hidden`属性を持ち実ブラウザに忠実に隠れるため、46件のテストが一斉に失敗した
     （CarStressRecipePanel/MotorVehicleDensityRecipePanel/RoadSuitabilityRecipePanel/
     MapLayersPanelの4ファイル）。各ファイルのrenderヘルパーへ「レンダー直後に
     閉じたAccordion.Triggerを全クリックして開く」ヘルパーを追加して解消（ネストした
     Disclosureは1回のクエリで拾いきれない場合があるため変化が無くなるまで反復、
     FieldLabelのPopover.Trigger・renderHintToggleの情報アイコンは同じ
     `aria-expanded="false"`を持つが`aria-controls`の有無で区別し誤って開かないようにした）。
     MapLayersPanel.test.tsxの`openSection`（`document.getElementById(...).open =
     true`）はコンテナ内のトリガーを`fireEvent.click`で辿る方式へ変更（生DOMの
     `.click()`だとReactのstate更新がact()で包まれず次のexpectまでに反映されないことが
     あったため`fireEvent.click`を使用）。domIdは旧`<details id>`と同じ位置づけで
     Trigger単体ではなくRoot（コンテナ）へ付け直した（`within()`によるセクション内
     スコープ検索を保つため）。
  - **実機確認（Playwright、一時spec・検証後削除）**: デスクトップでサイドバー3ブロック
     （ルートを作る/研究/開発者）の開閉・aria-expanded・チェブロン回転を確認。研究タブの
     ネストしたDisclosure（RecipePanelSection内のgroup）とLevelPicker（RadioGroup）の
     組み合わせ動作、および見出し(h3)のtextContentにtrailingの文言が混入していないことを
     実機でも確認（jsdomで見つけた問題の裏取り）。モバイル幅(390x844)でMapLayersPanelの
     レイヤーセクション開閉とLayerChip操作がセクション開閉に影響しないことを確認。
     スクリーンショットで視覚的な崩れ（チェブロン・上書きチップ・LevelPickerの色分け）が
     無いことも確認した。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`・
    Playwright smoke.spec.ts（standalone・workers=1）いずれもgreen。

### - [x] T255. Phase3: BottomSheet→vaul（断念）、DynamicLayerTimeSlider→Embla Carousel 規模M〜L（2026-08-24完了、BottomSheetは断念し現行実装を維持）

- 発端: T251の調査結果。4件中もっともリスクが高い2件。
- 対応内容: BottomSheet→vaul(Drawer)。4シート共有の高さ状態・暗幕なし・地図の
  ピンチズームとの共存・矢印キーでの5vh刻み調整は個別の実機再検証が要る（4シート共有の
  高さ状態はvaulの標準機能でカバーしきれない可能性があり、着手前に設計判断が必要）。
  DynamicLayerTimeSlider→Embla Carousel（+wheel-gesturesプラグイン）。可変幅スライド・
  ホイール変換・スナップは標準機能でカバーできるが、キーボード操作（Arrow/Home/End）・
  `role="slider"`のARIA・「現在」ボタンは今と同程度の自前実装が残る。
- 完了条件: 実機チューニング済みの現行操作性（touch-action・スワイプ閉じ・ホイール変換等）
  と同等以上をPlaywright＋実機確認。
- **着手判断（2026-08-24）**: T254で規模Sの想定がM相当になった直後だったため、着手前に
  改めてユーザーへ確認（AskUserQuestion）。「両方とも実施（リスク承知）」の回答を受けて着手。

- **実装メモ（2026-08-24完了）**:
  1. **BottomSheet→vaul: 断念（上流の確定バグ）**。実装自体はPlaywright実機Chromiumで
     一通り動作するところまで到達した（`modal={false}`＋`snapPoints`でheight=100vh＋
     transformで対象スナップポイント分だけ見せる設計、bottom:0＋padding-bottomで
     タブバー分のクリアランスを確保する等、vaulのtransform計算がbottom:0前提であることを
     実機検証で突き止めて回避策を確立した）。しかし最終検証で、`modal={false}`と
     `snapPoints`の組み合わせにおいて、vaulの内部実装（Radix Dialog由来）が`body`要素へ
     `pointer-events: none`を適用してしまい、シート表示中に地図・下部タブバーが
     一切クリックできなくなる**上流の確定した既知バグ**（GitHub Issue
     [emilkowalski/vaul#509](https://github.com/emilkowalski/vaul/issues/509)・
     [#534](https://github.com/emilkowalski/vaul/issues/534)、いずれもOpen・未修正）を
     発見・実機Chromiumで再現確認した。`body.style.pointerEvents`を強制的に空へ戻す
     回避策も試したが、4枚あるBottomSheetインスタンスが切り替わるたびに（Radix Dialogの
     マウント/アンマウントサイクルのたび）再発するため、継続的な監視（MutationObserver等）が
     要る不安定なハックにしかならないと判断した。「暗幕なし・地図が常に操作可能」は
     T34由来のこのアプリの核心要件のため、BottomSheetはvaul化を断念し現行の自前実装
     （pointerイベントによる自前ドラッグ・タッチスワイプ閉じ）をそのまま維持する
     （`git checkout`で復元）。vaulパッケージは削除した。
  2. **DynamicLayerTimeSlider→Embla Carousel: 完了**。可変幅コマ（正時/非正時で幅が違う）は
     Embla標準の可変スライド幅対応でそのままカバーできた。左端固定の目印（旧実装の
     `INDICATOR_OFFSET_PX`）に対して選択中コマの中心を合わせる操作感は、Emblaのカスタム
     `align`関数（`(viewSize, snapSize) => INDICATOR_OFFSET_PX - snapSize / 2`）で再現し、
     `containScroll: false`で最初/最後のコマも目印まで届くようにした。自前だった
     設定確定タイマー（90msデバウンス）・ドラッグのpointerイベント処理・ホイール変換の
     nativeリスナーはすべて撤去できた。キーボード操作（Arrow/Home/End）・
     `role="slider"`のARIAはEmblaが提供しないため従来どおり自前で維持（想定どおり）。
     `settle`イベントで最終確定indexを報告する設計を当初試みたが、実機Playwright検証で
     高速な合成ドラッグ後に`settle`が発火しないケースを確認したため、より標準的で
     確実に発火する`select`イベント（最寄りスナップ位置が変わった瞬間のみ発火し、
     ドラッグ中の毎フレームでは発火しないため過剰報告の懸念も生じない）へ切り替えた。
     jsdomでのテストはmatchMedia・IntersectionObserver・ResizeObserverの3つをEmbla自身が
     無条件に呼ぶため、いずれも未実装のjsdomでは例外になる（useIsMobile.test.tsと同じ
     既知の欠落パターン）。テストファイル側でモックして解消した。
  - **実機確認で判明した限界（Playwrightでは検証不能）**: ホイール（縦スクロール→横変換）
     動作は、Playwrightの合成`mouse.wheel()`イベントでは`embla-carousel-wheel-gestures`
     プラグインの内部ジェスチャー検出（wheelイベントを合成mousedown/mousemoveへ変換して
     Emblaの通常のドラッグ処理に載せる方式）が発火しないことを実機Chromiumで複数パターン
     確認した（単発・連続・高速連打いずれも不発）。ドラッグ（マウス/タッチ）・キーボードは
     Embla自身のAPI（`selectedScrollSnap()`）レベルで正しく動作することを確認済みのため、
     Embla本体の統合自体は機能している。ホイール変換だけがPlaywright上で検証できない状態
     だったため、Playwright特有の合成イベントの限界（vaulのケースのような確定した
     実ブラウザバグではない）なのか実機でも機能しないのかの切り分けをユーザーへ依頼した。
     **ユーザーの実機（実際のマウスホイール/トラックパッド）確認の結果、正常に機能する
     ことを確認済み**（2026-08-24）。Playwright側の合成イベントが検出されなかっただけで、
     実装自体に問題は無かったと判明した。
  - 検証: `tsc --noEmit`・ESLint・frontend vitest 56ファイル505件・`next build`・
    Playwright smoke.spec.ts（standalone・workers=1）いずれもgreen。BottomSheet.test.tsx
    （5件、既存の自前実装のまま）も引き続きgreen。DynamicLayerTimeSlider.test.tsx
    （9件）はEmbla化後も既存の検証観点（ARIA・キーボード操作）を維持したままgreen。

### - [x] T257. WBGT数値と気象庁警報・注意報の語彙混同バグを修正する 規模S（2026-08-24完了）

- 発端: ユーザー報告「wbgtの数値と、警報注意報の紐づけ。現在25だが警報扱いになっている。
  これは正しいか」に続けて「wbgtと、気象庁の一般的な注意報、警報ってどう紐づけているの？
  言葉から違うと思う。」という確認。
- 調査: WBGT（暑さ指数）は環境省の熱中症予防運動指針に基づく独立した5段階制度
  （ほぼ安全/注意/警戒/厳重警戒/危険、算出基準は気温ではなく湿球黒球温度）で、気象庁の
  気象警報・注意報（注意報/警報/特別警報の3段階）とは所管・算出方法とも無関係の別制度。
  `WarningBadge.tsx`の`LEVEL_SUMMARY_LABEL`は`Record<WarningBadgeLevel, string>`1本で
  JMA（T205）・WBGT（T174）・河川氾濫予報（T212）の3種の表示元を共有しており、
  共通のレベルキー`"warning"`にJMA側の語彙「警報」だけが固定されていた。WBGT値25は
  暑さ指数運動指針上「警戒」に相当するレベルだが、共有テーブル経由で「警報」と誤表示
  されていた（気象庁の公式な「警報」を実際に発表しているわけではない）。
- 修正: `WarningBadgeItem`へ`source: "jma" | "wbgt" | "flood"`を追加、
  `LEVEL_SUMMARY_LABEL`を`Record<WarningBadgeSource, Record<WarningBadgeLevel, string>>`化。
  WBGT: 注意/警戒/厳重警戒/危険、JMA: 注意報/警報/厳重警戒/特別警報、
  flood: 氾濫注意報/氾濫警報/氾濫危険警報/氾濫特別警報、とソースごとに独立した語彙表へ
  分離した。`page.tsx`の3箇所の`WarningBadgeItem`構築時に対応する`source`を付与。
- 検証: `WarningBadge.test.tsx`8件green（新規2件: 「WBGT単独（warningレベル）はJMAの
  『警報』ではなく『警戒』と表示する」「JMAとWBGTが同じwarningレベルで混在すると、
  最初に見つかった方（JMA）の語彙が使われる」）。

### - [x] T258. フロントのfetch()失敗がデバッグログに残らない箇所を横断的に修正する 規模S〜M（2026-08-24完了）

- 発端: ユーザー報告「現在地点から20kmでルート生成に常に失敗する」。本番実機
  （緯度経度35.7506948, 139.7418897、Renderデプロイ済みフロント）でユーザーが
  `POST /api/routes/generate`送信の約1分後に「fail to fetch」が表示される事象を確認したが、
  デバッグログには一切記録が残っていなかった。直接API再現（王子・ユーザー座標いずれも
  ローカルから本番DBへ直結）は2回とも成功しており、根本原因はRenderプラットフォーム側の
  HTTPタイムアウト（未確定、目安約1分）が疑われるが確定していない
  （**根本原因自体は未解決のままT105へ集約**、本タスクはその調査を継続可能にする
  デバッグログ側の穴を塞ぐもの）。ユーザーから「タイムアウト以外にも異常な状態になった
  時にはデバッグログにでてきてほしい。ほかにも表示すべきものがないか確認して」という
  横断監査の指示を受けて着手。
- 調査: T105（バックエンド一時的到達不能の調査、2026-08-17）で確立された
  「`fetch()`自体の例外（タイムアウト・通信エラー）は`response.ok`チェック以前に
  投げられるため、`try/catch`で囲まないとデバッグログに一切残らない」という既知パターンが、
  T105での修正範囲（GET系の`debugStatsApi.ts`・`versionApi.ts`）の外側に複数箇所
  再発していた。`frontend/src`配下の`fetch(`呼び出し箇所を全7ファイル洗い出して確認:
  - `routeApi.ts: postJson`（ルート生成・プレビューのPOST、**今回の20kmバグの直接該当箇所**）
    — 未対応
  - `regionApi.ts: fetchBreakdown・fetchAxisInspector` — 未対応
    （同ファイルの`refreshBasemapCache`のみ既に対応済みだった）
  - `jmaNowcastFrames.ts: fetchJmaTargetTimes` — 未対応、かつタイムアウト指定も無し
    （無期限に待ち続ける状態だった）
  - `page.tsx`: 降水ナウキャスト・雷ナウキャスト読み込み・`handleGenerate`
    （ルート生成ボタンのハンドラ）の3箇所の`catch`ブロック — 例外は捕まえてUIへは
    表示していたが、`debugLog`を呼んでいなかった
  - `weatherApi.ts`・`fetchJson.ts`自身・`healthApi.ts` — 確認の結果、対応済みまたは
    意図的サイレント（後述）
- 修正:
  1. `routeApi.ts`: `postJson`の`fetch()`を`try/catch`で囲み、
     `DOMException("TimeoutError")`か否かで「失敗 (タイムアウト)」「失敗 (通信エラー)」を
     区別して`debugLog`へ記録した上で再送出。
  2. `regionApi.ts`: `fetchBreakdown`・`fetchAxisInspector`へ`refreshBasemapCache`と
     同型の`try/catch`パターンを追加。
  3. `jmaNowcastFrames.ts`: `fetchJmaTargetTimes`を共通GETラッパー`fetchJson`
     （`lib/fetchJson.ts`、T105・regionApi.tsで確立済みのパターンの集約先）経由へ
     リファクタリング。15秒タイムアウトと`api:jma-nowcast-times`カテゴリのログが
     新たに付いた（降水・雷ナウキャスト双方に波及）。
  4. `page.tsx`: 降水・雷ナウキャストの`catch`ブロックへ`debugLog`追加。
     `handleGenerate`の`catch`ブロックへも`debugLog`追加（`postJson`側で既に記録済みの
     失敗を重複記録する形にはなるが、`postJson`を経由しない想定外の例外もこの層で
     拾えるようにする多層防御として残した）。
  5. `weatherApi.ts`は全関数が既に`fetchJson`経由で対応済みと確認（修正不要）。
  6. `healthApi.ts`はログが皆無（成功時含め）だが、頻繁なポーリング（ヘルスチェック）での
     ログスパムを避ける意図的設計と判断し、対象外とした。
- 副作用の修正: `jmaNowcastFrames.ts`のリファクタリングでエラーメッセージの文言・形式が
  `fetchJson`標準形式（`` `${errorLabel}の取得に失敗しました[HTTP ${status}]` ``）に
  変わったため、既存テスト3ファイル（`jmaNowcastFrames.test.ts`・
  `precipitationNowcast.test.ts`・`thunderNowcast.test.ts`）のモックレスポンスへ
  `headers: new Headers()`を追加し、期待エラーメッセージを新形式へ更新した。
- 検証: フロントvitest 56ファイル510件green、`tsc --noEmit`green。
- 完了条件: 満たした（`fetch(`呼び出し全7ファイルの横断監査は完了）。ただし20kmバグ自体の
  根本原因（Renderプラットフォームタイムアウトの確定）は**未解決のままT105へ残す**。
  次回の再現時は、本タスクで追加したデバッグログ（`api:route`カテゴリの
  「失敗 (タイムアウト ...ms)」/「失敗 (通信エラー)」記録）がT105の完了条件（対策済み
  制御の再発かコールドスリープかの切り分け）の材料になる想定。

---

## 目論見書による二画面構想の正式化（2026-08-24・ユーザー承認）

「自転車専用道を優先したい」という要望の調査から始まった一連の議論（0次フィルタの
未配線発見→T266起票→重みUI再設計案→二画面分割案→最終形の構想）を、目論見書
（Artifact: `RideCompass 目論見書`、https://claude.ai/code/artifact/ce418e86-3338-410b-9d14-826e00764b78 ）
として取りまとめ、**ユーザーが承認した**（2026-08-24）。骨子:

- **最終形**: 一般ユーザーは研究側で練り上げられた少数の推定軸の重みを調整するだけで
  最適なルーティングが得られる状態へ「蒸留」していく。一般UIの選択肢は増やさず、
  利用実績に基づいて淘汰する。
- **二画面分割**: 「軸を使う人」（一般向けルート設定）と「軸を作る人」（軸スタジオ=
  T221 Stage E相当）を別画面にする。**軸スタジオは既存ページ内のパネルではなく
  独立URLの管理画面として実装する**（ユーザー指示による修正点。URLレベルで切れて
  いる方が権限制御を敷きやすい）。現行メインページの「研究」セクション
  （ResearchPanel・WeightPanel・レシピパネル群）と「開発者」セクション（DebugPanel・
  DebugConsole・SystemStatusPanel）はこの管理画面へ移設する。
- **設計上の歯止め6条**（材料の排他帰属の機械検査／公開済みaxis_id不変・変更は複製＋
  新ID／テンプレート4種の線引き維持／材料の天井の明示／認可境界1箇所・安全側
  デフォルト／DBが追いつくまで挙動を変えない）を実装に埋め込む。

現在地: T221 Stage A〜D完了（DB化・管理API・本番migration適用済み）、T266起票済み。
残るギャップを以下のタスクへ正式分解する。Phase番号は目論見書6章のロードマップに対応。

### - [x] T267. 一般向けルート設定画面の再設計実装（Phase 1） 規模M〜L（2026-08-24完了）

- 背景: 目論見書4章「ルート設定」。現行の評価重みUI（研究タブ内のWeightPanel）は
  全軸が横並びの数値入力で、どの軸が効いているか・観測/推定/動的の別が分からない。
  これを一般ユーザー向けの導線として再設計する。
- 対応方針（モックアップは本セッションで提示済み・ユーザー合意済み）:
  1. 最上部に0次の除外チップ（自転車通行禁止・高速道路・幹線道路(trunk)）。
     backend配線はT266が前提。
  2. 軸を観測・推定・動的の3カテゴリにグルーピングし、チェックボックスで軸ごと
     ON/OFF＋スライダーで重み設定。**カテゴリ分類の確定（特に夜間軸が観測か推定かの
     境界例判断）を実装時に行い、分類基準を明文化する**（目論見書8章の要判断事項）。
  3. 有効な軸の重み配分を積み上げバーで常時可視化。
  4. プリセットボタン（バランス／自転車専用道を優先／最短時間重視／安全重視）で
     一発適用→微調整の導線。重み値は暫定でよい（実走検証を経て確定、目論見書8章）。
- 完了条件: 一般導線からプリセット適用・軸選択・重み調整・0次除外の変更ができ、
  「自転車専用道を優先」プリセットで実際にcycleway/自転車レーンのある道路が
  優先されたルートが生成されることを実機確認する。docs/architecture.md追従
  （規模M以上・UI構成の変更）。
- 依存: T266（0次チップのbackend）。
- **実装メモ（2026-08-24完了）**:
  1. カテゴリ分類を確定: 観測=`gradient`/`surface_q`/`stop_density`/`night`
     （タグ・POI等の一次属性を直接読む、または単純なフラグ加算のみで判定式を持たない軸）、
     推定=`car_stress`/`accident`（複数材料をレシピ・判定式で合成する軸）、
     動的=`wind`（時々刻々変わる外部データ由来）。夜間はlit/tunnelタグのフラグ加算のみで
     判定式が無いため観測へ分類（目論見書の暫定表と同じ結論。
     `frontend/src/lib/evaluationAxes.ts: axisCategory`が単一ソース）。
  2. 新規コンポーネント`frontend/src/components/RouteSettingsPanel/`。既存の研究モード
     `WeightPanel`とは別の常時表示パネルとして、`renderRouteResultsBody`（デスクトップ・
     モバイル両方が経由する共通関数）内の`RouteList`直前へ設置。
  3. **状態はWeightPanelと共有**: `route_preference`（`routePreference`/
     `weightOverrideEnabled`）はpage.tsxの同じstateをそのまま渡し、`withAutoEnable`で
     どちらのパネルを操作しても自動的に上書きが有効になる（研究モードとの二重管理を
     避けた。T270で研究UIを独立URLの管理画面へ分離する際に整理し直す前提）。
     `hard_filters`は新規state（`hardFilters`）で、既定値がbackendの
     `DEFAULT_HARD_FILTERS`と一致するため上書き専用トグルを設けず常時送信する。
  4. プリセット4種の重み値は目論見書提示のモックアップの値をそのまま採用（暫定、
     実走検証で調整予定と明記）。
  5. UI詳細: `FieldLabel`（説明ポップオーバー、内部に`<button>`を持つ）と
     `checkbox`を`<label>`で束ねると、ポップオーバーボタン押下でcheckboxも
     連動トグルされてしまう不具合になるため、`WeightPanel`の`WeightInput`と同じく
     `aria-label`で関連付ける非`<label>`構成にした。
  6. 実機確認（Playwright代替としてClaude Browserで確認、地図タイル自体は別ポート
     由来のポート不一致で無関係に表示失敗するが対象外）: プリセット「自転車専用道を優先」
     適用→重み配分バーがcar_stress 45%等へ更新→「幹線道路(trunk)」チップをOFF→
     「生成」→`POST /api/routes/generate`のリクエストボディで
     `route_preference`（car_stress:0.45等）・`hard_filters`（trunk:false）が
     期待通り送信され、レスポンスの`conditions`にも同じ値がエコーされることを確認。
  7. 検証: backend全1140件green（T266と共通）、フロントtsc/vitest 516件green。
     docs/architecture.md（コンポーネント一覧）へRouteSettingsPanelを追記。

### - [x] T268. 材料の排他帰属チェックを計算系レジストリへ移植する（Phase 2前提） 規模S〜M（2026-08-24完了）

- 背景: 目論見書7章・歯止め1。排他帰属の機械検査（`registry.py: register_axis`の
  `AxisInputConflictError`）は表示用レジストリにしか無く、実際のルーティング計算を
  駆動する`axis_definitions.py: AXIS_DEFINITIONS`（Stage DでDB化済み）には存在しない。
  軸スタジオ（T270）で自由に軸を登録できるようになる前にこの検査を計算系へ移植
  しないと、既存軸が専有する材料を新軸が黙って再利用し二重計上が混入する。
- 対応方針: 管理API（`/api/admin/axis-definitions`）の作成・更新経路で、材料
  （`AxisDefinition.materials`）の排他帰属を検査する。`shared`相当（距離等の共通
  コンテキスト）の扱いは`registry.py`の設計を踏襲。T218素材カタログ・`registry.py`側の
  attr_idとの対応関係（二重管理の回避、ADR「T12との関係」参照）もここで整理する。
- 完了条件: 既存軸が使用中の材料を参照する新軸の登録が管理APIレベルで拒否される
  テストがgreen。既存7軸のシードデータが検査を通過する（現状の共有設計と矛盾しない）
  ことを確認。
- **実装メモ（2026-08-24完了）**:
  1. `domain/axis_definitions.py`へ`AxisMaterialConflictError`（`registry.py:
     AxisInputConflictError`と同じ原則）と`check_material_exclusivity(candidate,
     existing)`を新設。`existing`に`candidate.axis_id`と同じキーがあれば
     自己比較としてスキップする（更新時に自分自身とは衝突しない）。
  2. **`shared`フラグは持たせなかった**（過剰な汎用化を避ける判断）: 現行7軸の材料
     （gradient_percent/wind_penalty/surface_good/stop_count_per_km/
     intersection_count_per_km/accident_count_per_km_year/car_stress_level/
     no_lit/has_tunnel）はいずれも単一軸専有で、`registry.py`の`shared=True`
     （距離等の共通コンテキスト）に相当する材料が1件も存在しないため
     （`compute_edge_axis_scores`のmaterials辞書を確認、distance_mは軸材料としては
     未使用）。必要になった時点で`MaterialTerm`側への追加を検討する注記のみ残した。
  3. `AxisRegistryAdminService.create`/`update`の冒頭で`check_material_exclusivity`を
     呼ぶ（`ValueError`系のため`axis_admin.py`の既存`except ValueError → 409`が
     そのまま機能し、ルーター側の変更は不要だった）。
  4. T218素材カタログとの対応関係整理は、既存7軸の材料が`registry.py`側の
     `attr_id`と1:1で対応済み（新規の乖離なし）と確認するに留めた。二重管理の解消
     そのもの（レジストリ統合）はT270着手時に改めて要否を判断する。
  5. 既存テスト（`test_axis_registry_service.py`）が同一material="dummy"を使い回す
     フィクスチャだったため、新チェックに引っかかった2件（sort_order確認用ダミー・
     最後の1軸削除ガード確認用の2軸目）をmaterial引数で分離して修正。
  6. 検証: 新規`test_axis_definitions.py`（純粋domain、既存7軸の相互チェックが通ることを
     含む）＋`test_axis_registry_service.py`への追加3件。backend全1147件green。

### - [x] T269. 軸カタログ（axis-catalog.json）のDB追従方式の決定＋実装（Phase 2前提） 規模M（2026-08-24完了）

- 背景: 目論見書8章の要判断事項。フロントの軸一覧・既定重み・ラベルは
  `export_openapi.py`が**Python内蔵の`AXIS_DEFINITIONS`から**生成する
  `axis-catalog.json`に由来し、CIの`api-contract`ジョブはDB接続を持たない。
  このままでは軸スタジオでDBに追加した軸がフロントのカタログに現れない
  （Stage D ADR「axis-catalog.jsonは変更していない」の積み残し）。
- 対応方針（実装前にユーザーと方式を決定する）: 候補は (a) CIにDB接続を追加して
  ビルド時生成を維持、(b) 公開操作時にカタログを再生成しランタイム配信へ切替、
  (c) カタログ取得APIを新設しフロントは起動時フェッチ。静的生成物としての
  型安全性（generated型とのペア）と、デプロイなしで軸が増える運用の両立が論点。
  → **ユーザー選択: (c) カタログ取得API + 起動時フェッチ**。
- 完了条件: 管理APIで追加した軸が、フロントの軸カタログ（一般UIの軸一覧・
  重み既定値）へコード変更・再デプロイなしに（または合意した方式の運用フローで）
  反映されること。
- **実装メモ（2026-08-24完了）**:
  1. **重要な前提の訂正**: 当初の背景文は「axis-catalog.jsonがAXIS_DEFINITIONSから
     生成される」としていたが、調査の結果`axis-catalog.json`の`axes[]`/
     `primary_attributes[]`は実際には`registry.py`（表示専用レジストリ、T137/T145b、
     DB化されていないPython宣言のみ）から生成されており、`AXIS_DEFINITIONS`由来なのは
     `preference_defaults`のみと判明した。`registry.py`はDB書き込み手段を持たないため
     GUIで作った軸を原理的に表現できず、既存のaxis-catalog.jsonをそのまま追従させても
     目的を達成できない。そのため`AxisDefinition`（DB化済み・GUI編集可能な方）自体へ
     `label`/`description`/`category`を追加し、これを単一ソースとする新エンドポイントを
     新設する方針に切り替えた。
  2. `domain/axis_definitions.py: AxisDefinition`へ`label: str`（必須）・
     `description: str = ""`・`category: AxisCategory("観測"|"推定"|"動的") = "推定"`を
     追加。既存7軸の値は`frontend/src/lib/evaluationAxes.ts`の旧`PREFERENCE_AXIS_DESCRIPTIONS`
     ・`registry_defaults.py`のlabelから移植（表示文言は変更なし）。
  3. DB: `migrations/0015_axis_definitions_label.sql`（`0014`は既に本番適用済みのため
     追加カラムのNOT NULL DEFAULT + backfillという安全な形の別migrationとした）。
     ORM（`AxisDefinitionRow`）・repository（`_row_to_definition`/`upsert`）・
     管理API（`AxisDefinitionPayload`/`_to_response`）を追従。本番・dev DB・
     ローカルテストDB(ridecompass_test)いずれにも適用済み。
  4. 新規公開エンドポイント`GET /api/axis-catalog`（`api/routers/axis_catalog.py`、
     認可不要）。DBへは触れず、プロセス内キャッシュ`AXIS_DEFINITIONS`
     （起動時・管理API書き込み直後にpush型更新済み、Stage D設計を踏襲）をそのまま
     読むだけの実装。
  5. フロント: `services/axisCatalogApi.ts`（`fetchJson`共通ヘルパー経由）・
     `hooks/useAxisCatalog.ts`（マウント時に1回取得、取得完了まで/失敗時は既存7軸の
     静的フォールバックを返す）を新設。`RouteSettingsPanel`をこのhook経由に置き換え、
     プリセット適用時は`{...catalog.defaultWeights, ...preset.weights}`で未言及の軸を
     補うようにした（新しい軸が増えてもプリセットが必須キー欠落で422にならないための
     防御）。カタログ更新後に未知のaxis_idが増えていた場合、`routePreference`stateへ
     自動で既定重みを補う`useEffect`も追加（同じ理由）。研究モードの`WeightPanel`は
     引き続き旧`axis-catalog.json`静的読み込みのまま（T270でWeightPanel自体を
     置き換える際に統合する想定、今回はスコープ外）。
  6. 検証: backend全1149件green（新規`test_axis_catalog_routes.py`2件含む）、
     フロントtsc/vitest 516件green、実機確認（`/api/axis-catalog`が200・
     RouteSettingsPanelがDB由来のlabel/description/categoryで正しく表示されることを
     ブラウザで確認）。docs/architecture.md追従。

### - [x] T270. 軸スタジオ — 独立URLの管理画面としてT221 Stage Eを実装する（Phase 2本体） 規模L（2026-08-24完了・残作業あり）

- 背景: 目論見書4章「軸スタジオ」・T221 ADRのStage E（GUI編集画面、ADRスコープ外と
  して起票待ちだったもの）。**ユーザー指示（2026-08-24）により、既存ページ内の
  パネルではなく独立URL（`/admin`系ルート）の管理画面として実装する**。URLレベルで
  一般画面から切れていることで、権限制御（T272）をルーティング境界で敷ける。
- 対応方針:
  1. Next.jsの独立ルートとして管理画面を新設。軸コンポーザー（材料選択→4テンプレート
     選択→パラメータ調整→保存）を管理API（`/api/admin/axis-definitions`）経由で実装。
  2. 検証手段（地図プレビュー・比較生成）への導線を持たせる。空間JOIN系材料
     （事故点・POI集計）は地図プレビュー不可という非対称をUI上で最初から明示する
     （目論見書・歯止め4）。
  3. **現行メインページの「研究」セクション（ResearchPanel・WeightPanel・
     CarStressRecipePanel等のレシピ群）と「開発者」セクション（DebugPanel・
     DebugConsole・SystemStatusPanel）を管理画面へ移設し、メインページからは
     削除する**（ユーザー指示。一般画面に開発者導線を残さない）。
     移設に伴うlocalStorageフラグ（research/debug）の扱いはT272の権限制御設計と
     整合させる。
  4. 本番Renderの`AXIS_ADMIN_TOKEN`設定（現状未設定で管理APIは常時403、
     Stage D ADR残作業1）を完了条件に含める。
- 完了条件: 管理画面から新しい軸を作成・保存し、（T269の方式で）一般UIのカタログに
  出現し、その軸へ重みを付けたルート生成が動作することをE2Eで実機確認。
  メインページから研究・開発者セクションが消え、管理画面で同機能が使えること。
  docs/architecture.md追従（新レイヤー種=管理画面の追加）。
- 依存: T268（排他検査）・T269（カタログ追従）。規模M以上のため着手時に本エントリを
  さらに分割してよい。
- **実装メモ（2026-08-24完了・一部残作業あり）**:
  1. **新規ルート`frontend/src/app/admin/page.tsx`**（+`admin.module.css`）。
     `AxisStudio`（軸コンポーザー・一覧・CRUD）、`ResearchPanel`＋`WeightPanel`＋
     `CarStressRecipePanel`/`RoadSuitabilityRecipePanel`/`MotorVehicleDensityRecipePanel`
     （研究セクション）、`DebugPanel`/`DebugConsole`/`SystemStatusPanel`/`BackendStatus`
     （開発者セクション）をすべて移設した。
  2. **状態共有の設計判断**: WeightPanel等が使うstate（`weightOverrideEnabled`・
     `scoringWeights`・`routePreference`・3レシピの`overrideEnabled`/`recipe`）は、
     メインページ（`/`）と`/admin`が別Reactツリーのため直接共有できない。
     `useStoredJsonState`（新設、`hooks/useStoredState.ts`にJSON直列化の薄いラッパーを
     追加）と、`useRecipeOverride`に追加した`storageKey`引数（指定時は内部で
     `useStoredJsonState`を使う）で、同じlocalStorageキーを両ルートから読み書きする形に
     した。同一タブでのリアルタイム同期ではなく次回マウント時に反映される
     （`lib/researchMode.ts`の既存挙動と同じ制約）。メインページ側は編集UIを持たず
     読み取り専用で使う（setterを破棄）。
  3. **軸コンポーザー**（`components/AxisStudio/`）: `AxisShape`の3判別式
     （区分線形補間・カテゴリ値・フラグ加算、`recipe_then_breakpoint_linear`込みで
     実質4テンプレート）をフォームへ写した。材料選択は
     `lib/axisMaterialsCatalog.ts`の**閉じた9件**
     （`AXIS_DEFINITIONS`が実際に参照するmaterial idの全量、
     `registry_defaults.py`の一次属性カタログとは別語彙）から選ぶ。
  4. **管理APIクライアント**: `lib/adminToken.ts`（localStorage、researchMode.tsと同型の
     簡易実装）＋`services/axisAdminApi.ts`（CRUD、X-Admin-Tokenヘッダ付与）。
  5. **実機E2E確認（2026-08-24、backend/.envへdev専用のAXIS_ADMIN_TOKENを設定して実施）**:
     (a) `/admin`でトークン入力→一覧取得成功。(b) 新規軸作成で`surface_good`材料を選ぶと
     T268の排他チェックが409で正しく拒否することを確認（既存`surface_q`軸と衝突する
     ケース）。(c) `gradient`軸の`default_weight`を編集→PUT 200→
     `GET /api/axis-catalog`が更新値を即座に返す（再起動不要のpush型更新）ことを確認、
     検証後に既定値0.15へ戻した。(d) メインページ（`/`）から「研究」タブが消え、
     「開発者」タブは地図キャッシュ再読み込みボタンのみが残ることを確認。
     backend全1149件・フロントtsc/vitest 516件green。
  6. **残作業（未完了、影響範囲付き）**:
     - **地図プレビュー・比較生成への導線**（対応方針2）は未実装。軸コンポーザーは
       数値入力のみで、作成した軸のスコア分布や地図上の見え方を確認する手段がない。
       次に軸を作る人が「妥当な折れ点か」を勘で決めるしかない状態。
     - **本番Renderの`AXIS_ADMIN_TOKEN`設定**（対応方針4）は未実施
       （Renderダッシュボードへのアクセスが必要、Stage D ADR残作業と同じ制約）。
       設定するまで本番の`/api/admin/axis-definitions`は常時403のまま
       （安全側のデフォルト、意図通り）。**T272（2026-08-24完了）でこの認可機構自体が
       `AXIS_ADMIN_TOKEN`共有トークンからHTTP Basic認証
       （`ADMIN_BASIC_AUTH_USERNAME`/`PASSWORD`）へ置き換わったため、この項目は
       本番側の設定作業として当時のまま未着手だが、設定すべき変数名が変わっている
       点に注意（T272エントリ参照）。**
     - **「新しい軸を作成→ルート生成」のE2Eは未検証**。原因は設計上の制約:
       `lib/axisMaterialsCatalog.ts`の9材料は**全て既存7軸が専有済み**のため、
       現在の閉じた材料集合の範囲では、既存軸を削除しない限りT268の排他チェックに
       必ず引っかかり新規作成できない（実機で実際に確認した制約、上記(b)参照）。
       真に新しい軸を作るには、まず新しい材料を取込パイプライン側に追加する
       （目論見書7章・歯止め4「材料の天井」、コード変更が要る）必要がある。
       軸スタジオ自体はこの制約下で正しく動作している（バグではない）が、
       「材料が増えるまで新規軸は事実上作れない」という運用上の制約は
       ユーザーへ明示しておくべき。

### - [x] T271. 軸の公開フローと統治ルール（Phase 3） 規模M

- 背景: 目論見書7章・歯止め2、8章。一般ユーザーの保存設定は`axis_id`キーで再現される
  ため、公開後の軸の破壊的変更・削除は他ユーザーの設定を黙って壊す。また同じ意図の
  軸が乱立すると一般UIの選択肢が増えて蒸留の方向と逆行する。
- 対応方針: (1) 公開済み`axis_id`の不変制約（管理APIレベルで、公開フラグ付き軸の
  破壊的更新・削除を拒否。改良は複製＋新IDの導線をUIに用意）。(2) 下書き→検証→公開の
  状態遷移をDBスキーマへ追加（公開前の軸は一般カタログに出さない）。(3) 命名・重複
  ガイドと公開前チェックリストを軸スタジオUIへ組み込む。
- 完了条件: 公開済み軸の破壊的変更が構造的に不可能であること、下書き軸が一般UIに
  漏れないことのテストがgreen。
- 依存: T270。
- 実装メモ（2026-08-24完了）: `AxisDefinition.is_published: bool`（既定False）を追加し
  （`migrations/0016_axis_definitions_is_published.sql`、既存7行はDEFAULT trueで
  backfill）、`domain/axis_definitions.py: AxisPublishedImmutableError`/
  `check_publish_immutability`を`AxisRegistryAdminService.update`/`delete`の冒頭で
  呼ぶ形で実装。`GET /api/axis-catalog`（T269）は`is_published=True`のみ返すよう変更。
  `axis_admin.py: update_axis_definition`に欠けていた`ValueError`ハンドラも追加
  （実装中に発見した既存の抜け穴、以前は更新時の材料衝突[T268]が想定外の500だった）。
  フロントは`AxisStudio.tsx`に公開済み/下書きバッジ・編集/削除の無効化・「複製して
  新規作成」ボタンを追加、`AxisComposer.tsx`に`draftFromDuplicate`（axis_idクリア・
  is_published強制false）と「公開する」チェックボックスを追加。「改良は複製＋新IDの
  導線」は3.命名・重複ガイドの専用UI（チェックリスト等）までは作らず、複製ボタン自体を
  唯一の導線とするミニマムな実装とした（対応方針3「命名・重複ガイド・公開前チェック
  リストのUI組み込み」は見送り、複製フローがあれば実用上十分と判断）。
  検証: backend全1169件green（新規`test_axis_definitions.py`3件・
  `test_axis_registry_service.py`3件・`test_axis_admin_routes.py`2件・
  `test_axis_catalog_routes.py`1件含む）、frontend tsc/eslint/vitest 517件green、
  実サーバーで軸スタジオの公開済みバッジ・編集/削除disabled・複製フロー（axis_id空・
  公開チェックOFF）を確認。複製後の新規作成は材料の天井（9材料が既存7軸で専有済み、
  [[rc-phase2-t270-axis-studio]]の既知の制約）により409（材料衝突）で拒否されたが、
  これはT271の不具合ではなく既存の設計上の制約——エラー応答自体が正しく返り、
  公開済みgradient軸のデータが無傷であることをAPI直接確認で検証した。

### - [x] T272. 管理画面・研究機能の権限制御導入（Phase 3） 規模M

- 背景: 目論見書6章Phase 3。「将来、研究パネルを一般ユーザーから隠し権限制御を導入
  する」という以前からの方針（Stage D ADRにも記録）を、管理画面のURL分離（T270）を
  機に実施する。現行の`researchMode.ts`（localStorageトグル、誰でもON可）は
  廃止または管理画面ログインへの置換対象。
- 対応方針: 管理画面のルーティング境界で認可を敷く。backend側は認可判定が
  FastAPI Dependency 1箇所に集約済み（Stage Dの設計）のため、共有トークンから
  実権限チェックへの差し替えを行う。frontend側の方式（Basic認証・トークン入力・
  アカウント制等）は着手時にユーザーと決定する。
- 完了条件: 一般ユーザーの導線から管理画面・研究機能へ到達できず、認可を持つ
  ユーザーのみがアクセスできること。docs/architecture.md追従（認可境界の記述）。
- 依存: T270。
- 実装メモ（2026-08-24完了）: フロント側方式はAskUserQuestionでユーザーに確認し
  「将来的にはアカウント制としたいが、現状は動作確認・研究用のためBasic認証として
  後から拡張する」との回答を得てBasic認証で実装した。共有トークンからの「差し替え」は
  backend/frontend両方でHTTP Basic認証へ統一する形にした（2箇所独立: (1)
  `frontend/src/proxy.ts`が`/admin/:path*`のルーティング境界でブラウザ標準Basic認証
  ダイアログを要求[Next.js 16で`middleware.ts`→`proxy.ts`へ改称、frontend/AGENTS.md
  「このNext.jsは知っているものと違う」の指示どおりnode_modules内docsを確認して
  対応]、(2) backend `axis_admin.py: require_admin_basic_auth`が
  `fastapi.security.HTTPBasic`+`secrets.compare_digest`で軸CRUD APIを保護——別
  オリジンのためブラウザの認証キャッシュが自動転送されず、軸スタジオUI自体の資格情報
  入力フォームは維持。`config.py`の`axis_admin_token`は`admin_basic_auth_username`/
  `admin_basic_auth_password`へ置換、`lib/adminToken.ts`は単一トークンからusername/
  password保持へ再設計、`hooks/useAdminToken.ts`は`useAdminCredentials.ts`へ改称。
  `researchMode.ts`は変更不要と判断（/admin自体が認証済みユーザーのみ到達可能になった
  ため、表示ON/OFFトグルとしての役割のみ残っても意味の重複は生じない）。
  検証: backend全1169件green（`test_axis_admin_routes.py`の認可テストをBasic認証へ
  書き換え）、frontend tsc/eslint/vitest 517件green、実サーバーで(1)`/admin`が資格情報
  なし/誤りで401＋`WWW-Authenticate`ヘッダ、正しい資格情報（`http://user:pass@host/admin`
  形式でBrowser paneから確認）で200、(2)軸CRUD APIも同様に401/200を確認、(3)軸スタジオの
  新ユーザー名/パスワードフォームで実際に軸一覧が取得できることを確認した。
  **残作業（影響範囲付き）**: 本番Render（backend・frontend双方）へ
  `ADMIN_BASIC_AUTH_USERNAME`/`ADMIN_BASIC_AUTH_PASSWORD`を未設定のため、
  設定するまで本番の`/admin`ページ・軸CRUD APIは共に401で到達不能のまま（Renderダッシュ
  ボードへのアクセスが必要、Stage D ADR「本番RenderのAXIS_ADMIN_TOKEN未設定」残作業と
  同じ制約が形を変えて継続）。機能低下ではない（本番の管理機能は以前から使えない設計
  だった）が、本番で軸スタジオ・研究モードを実際に使いたくなった時点で必ず両方の
  Renderサービスへ同じ値を設定する必要がある。

### - [ ] T273. 蒸留 — 一般UIの軸カタログ縮退（Phase 4） 規模S〜M（継続的）— トリガー: 一般公開の意思決定、およびPhase 3までの利用実績の蓄積

- 背景: 目論見書3章・6章Phase 4。最終形は「言葉のレベルのつまみ数個」。一般UIの
  軸カタログを練られた少数の推定軸＋プリセットへ絞り込み、観測系の生軸は推定軸の
  内部へ吸収していく。
- 対応方針: 縮退基準（どの利用実績をもって軸を「卒業」＝カタログから隠す・吸収すると
  判定するか、目論見書8章の要判断事項）を利用データが溜まった時点で定義してから
  着手する。機能削除ではなくカタログ表示の絞り込み（軸自体はレジストリに残す）を
  基本とする。
- 完了条件: トリガー到達時に縮退基準とあわせて再定義する。

### - [ ] T274. 周回ルートの逆回り（反時計回り/時計回り）候補も評価し、良い方を採用する 規模M — トリガー: ユーザーの実装意思は確定済み、着手タイミングのみ並行作業待ち

- 発端: ユーザー指摘「地図上に描画されているルートは有向グラフにできない？勾配や風向き等、
  同じルートでも左回り右回りで評点が変わるはず」（2026-08-24）。
- **調査で確認した現状**:
  1. road_graphエンジンのグラフは既に正しい有向グラフになっている
     （[domain/graph.py:312-336](../backend/app/domain/graph.py:312)）。道路の各区間は
     `-fwd`/`-bwd`という別々のedge_idを持ち、それぞれ実際の進行方向で算出した独自の
     `bearing_deg`（風向きペナルティに使用）を持つ。
  2. 勾配も進行方向で正しく符号反転している
     （[domain/attributes.py:88-124](../backend/app/domain/attributes.py:88):
     `compute_elevation_attribute`はedge自身の形状点列の順序で積算するため、`-fwd`と
     `-bwd`で獲得標高/損失標高・平均勾配の符号が入れ替わる）。
  3. **しかしルート生成（`RouteGenerator._loop_waypoints`、
     [route_generator.py:196-199](../backend/app/services/route_generator.py:196)）は
     8方位それぞれ「起点→経由地A(方位θ)→経由地B(方位θ+45°)→起点」という固定した
     回転方向でしか経路探索していない**。同じ物理的なループ形状を逆回り
     （起点→B→A→起点）で通った場合の候補は生成・比較されていない。
  4. edgeレベルの評価は方向を正しく区別できているのに、生成アルゴリズム側がその区別を
     活かせていない、という食い違いがある。
- **設計（ユーザーとの検討で確定、実装時はこの方針に従う）**: 単純に16候補（8方位×2回転）を
  全て新規にtrace_loop+評価すると、Dijkstra・DB幾何取得・GSI標高取得がいずれも倍になり
  重くなる。以下の要素分割により、**追加のDB/外部API呼び出しゼロ**で逆回り候補を合成できる。
  - **方向に依存しない（そのまま使い回せる）**: `distance_km`（物理長不変）・`road_score`・
    `stop_density`・`intersection_density`・`accident_density`・`car_stress_score`・
    `bicycle_infra_score`。いずれも`edge.edge_id`をキーに`context.surface_attributes`等
    （`prepare()`でbbox全域・両方向のedge_idぶんが取得済み）を引くだけの集計のため、
    逆方向edge_idで引いても新規フェッチ不要。
  - **方向に依存する（再計算は要るが追加I/Oはゼロ）**:
    - `wind_score`: `compute_wind_penalty`は`edge.bearing_deg`依存。逆方向edgeの
      `bearing_deg`は`road_edges`テーブルにpersisted済み・`context.graph`から既に
      取得済み（[road_graph_repository.py:1203](../backend/app/infrastructure/road_graph_repository.py:1203)）のため、参照するだけ。
    - `elevation_gain_m`/`max_gradient_percent`等: GSI標高APIを叩き直さず、順方向で
      既に取得済みの`ElevationAttribute`から代数的に導出する
      （`elevation_gain_m`↔`elevation_loss_m`を入れ替え、`max_grade`↔`min_grade`を
      符号反転して入れ替え、`start_elevation_m`↔`end_elevation_m`を入れ替え、
      `average_grade`を符号反転）。標高は地形の物理量で進行方向に依存しないため、
      この変換は厳密に正しい。
    - `geometry`・turn-by-turn `segments`: 順方向で既に`get_edges_with_geometry`済みの
      ジオメトリ点列を逆順に並べ替えるだけ（DB再取得不要）。
  - **逆回りが成立しない場合のガード**: 経路中に一方通行（`-bwd`が存在しない）edgeが
    1つでもあれば物理的に逆走不可能なため、その方位の逆candidateは生成しない。
    `context.graph`から一度（リクエスト単位）だけ`(from_node_id, to_node_id) → edge_id`
    の逆引きテーブルを作れば判定できる。多重辺（同じNode対を結ぶ別wayが複数存在する稀な
    ケース）は逆引きテーブルの後勝ちで曖昧になりうるが、既存のsparse_graph/
    NodeSpatialIndex側にも同種の簡略化があり許容範囲とした。
  - **候補の採否（ユーザー判断で確定）**: 逆回りcandidateが生成できた場合、
    レスポンスには**方位ごとに評点の良い方だけ**を採用する（両方向を別candidateとして
    追加する案は、候補リストUI・`direction_label`の重複対応が別途必要になり見送った）。
    比較指標は`distance_weighted_difficulty`（`car_stress_score`と同じ集計関数、
    segmentsの`composite_difficulty_value`を距離加重平均したもの）を両方向で算出し、
    小さい方を採用する（ルーティングコスト自体が使う軸重み付けと同じ基準のため、
    アドホックな新規スコア定義を避けられる）。
  - **実装イメージ**（`road_graph_engine.py`）: `_build_candidate`から標高取得部分を
    抽出し、順方向の`ElevationAttribute`を引数として受け取れるようにする。新設する
    `_reverse_traced_loop`（逆方向のEdgeシーケンス＋ジオメトリ合成、上記ガード判定）と
    `_reverse_elevation_attribute`（代数変換）を使い、`evaluate_loops`で各bearingについて
    順方向・逆方向（生成できれば）の両方の`_build_candidate`を呼び、
    `distance_weighted_difficulty`で比較して良い方だけを最終候補に残す。
    `candidate_identity`は方位ベースのまま変更不要（1方位1候補のため）。
- **保留する場合の影響**: 現状の8方位一方向のみのルート生成自体は正常に動作しており、
  失敗ではなく最適化機会の見送りに留まる。ただし保留し続けると、風向き・勾配が不利な
  回転方向のまま候補が提示され続け、同じ形状でより良いスコアの逆回りルートが存在しても
  ユーザーには見えない状態が続く。
- **着手タイミングに関する注記（2026-08-24）**: 設計検討中に、並行セッションが
  `backend/app/services/road_graph_engine.py`・`backend/app/domain/evaluation.py`等
  （T266〜T273、0次ハードフィルタ・二画面構想関連）を編集中であることが判明した
  （作業ツリーの安全ルールに従い、それらのファイルには一切触れていない）。本タスクの
  実装は同じファイルを触るため、並行作業のコミット完了後に着手すること。
- 完了条件: 未実装。着手時、上記設計に基づき実装・テスト（逆回り判定のガード条件・
  代数変換の正当性・比較ロジック）を行う。

### - [ ] T275. Tailwind CSSの採否を決定する（現状は未使用のまま依存関係にのみ存在） 規模S（調査・意思決定）

- 背景: 2026-08-24、T270作業中のユーザー質問（「Radix/Tailwindは実装コスト低減や保守性の
  向上につながっているか」）への回答時に調査して判明。`frontend/package.json`に
  `tailwindcss`/`@tailwindcss/postcss`が依存関係として存在し`globals.css`からも
  importされているが、実際のコンポーネント（`.tsx`）でTailwindのユーティリティクラス
  （`flex`/`gap-`/`bg-`等）を使っている箇所は**リポジトリ全体でゼロ**。全コンポーネントは
  一貫してCSS Modules＋手書きCSSカスタムプロパティ（`--space-*`/`--color-*`等、
  `globals.css`定義）で実装されている。Next.jsのデフォルトスキャフォールドが自動同梱した
  ものがそのまま残っているだけと推測され、意図して導入・活用された形跡がない。
  一方Radix UI（`@radix-ui/react-*`）は`Disclosure`/`FieldLabel`/`LevelPicker`/`LayerChip`等
  複数箇所で実際に採用され、キーボード操作（roving tabindex）・Popover位置計算・
  トグル押下等の自前実装を置き換えて明確にコスト削減できている（対比としてRadixは
  「効果が出ている」と評価できる状態）。
- 対応方針（実装前にユーザーと方式を決定する）: 既存のCSS Modules資産（多数のコンポーネント
  × module.css）をどう扱うかをコストと天秤にかけて判断する。候補は (a) Tailwindを
  依存関係から撤去し「使わない」と明文化してCSS Modules一本化を継続、(b) 新規コンポーネント
  のみTailwindを使い既存CSS Modulesは段階的に置き換えない併用方針、(c) 全面的な
  Tailwindへの移行（既存CSS Modules資産の書き換えコストが規模に対して大きい可能性が高く、
  現時点では推奨しない）。
- 完了条件: 方針を決定し、`docs/architecture.md`（技術選定表）へ明記する。(a)を選ぶ場合は
  `tailwindcss`/`@tailwindcss/postcss`の依存関係除去と`globals.css`のimport除去も行う。
  (b)を選ぶ場合はCSS ModulesとTailwindの使い分け基準（どういう場合にどちらを使うか）を
  明文化する。

### - [x] T276. registry.py（表示用レジストリ）とAXIS_DEFINITIONS（Stage D）の軸ラベル重複を解消する 規模S（2026-08-24完了）

- 背景: T270完了報告でユーザーから「2つのレジストリ未統合」について「意図的に据え置き」と
  説明したところ、その意図を問われた。実態を確認すると、これは重み付けした設計判断ではなく
  T270のタスク文に統合が明記されていなかったために単に着手していなかっただけで、しかも
  T269の実装メモで自ら「T270で統合する想定」と書いていた宿題を果たしていなかった
  （T270エントリ完了時の見落とし）。ユーザー指示によりその場で着手した。
- 現状把握: `domain/registry_defaults.py`（`registry.py`向けの既定登録、T137）の6軸
  （gradient/surface_q/stop_density/car_stress/night/accident）は、`AxisDisplaySpec.label`
  （地図レイヤーパネル・凡例が表示する軸名）を`AXIS_DEFINITIONS[axis_id].label`
  （T269でDB化、軸スタジオでGUI編集可能）と**完全に同じ文字列**で独立して手書きしていた
  （例:「車の圧迫感」を2箇所で個別に宣言）。一方`AxisSpec.description`
  （開発者向けの長い技術説明）・`AxisDisplaySpec.category`（地図レイヤーパネルの
  グルーピング用「terrain」「road」「trafficSafety」）は`AXIS_DEFINITIONS`側の
  `description`（ユーザー向けの短い説明）・`category`（軸の性質「観測」「推定」「動的」）
  とは対象読者・意味が異なる別概念と判断し、統合対象から除外した（同じ「category」という
  語を使うが指す軸が異なる点に注意）。
- 対応: `registry_defaults.py`の6軸登録で`AxisDisplaySpec(label="車の圧迫感", ...)`のような
  ハードコードをやめ、`AxisDisplaySpec(label=AXIS_DEFINITIONS["car_stress"].label, ...)`
  という参照へ置き換えた（`AXIS_DEFINITIONS`をimport）。`test_registry_defaults.py`へ
  `test_registry_axis_display_labels_match_axis_definitions`を追加し、この参照が将来
  また手書きの別文字列へ差し戻されないことを機械的に確認する（既存の
  `test_registry_axis_ids_match_axis_definitions`と同じ「片方だけ更新しても気づかない
  死角」対策のパターン）。
- **この対応が解決しない範囲（重要）**: `register_defaults()`はビルド時
  （`export_openapi.py`）とテストのみで呼ばれ、FastAPIアプリ起動時には呼ばれない
  （`registry_defaults.py`モジュールdocstring参照）。そのため今回の統合は
  「Pythonコード上の既定値が一致する」ことを保証するのみで、**軸スタジオでDBの`label`を
  GUI編集しても、地図レイヤーパネル・`axis-catalog.json`（ビルド時生成物）側のラベルは
  再デプロイまで追従しない**（T270「残作業」3・Stage D ADR「DB編集がこの生成物へ反映
  されるのはStage E以降の課題」と同根の制約が依然として残る）。真に動的反映させるには、
  地図レイヤー側（`SECONDARY_AXES`/`primaryAttributes.ts`等、`axis-catalog.json`静的importの
  複数箇所）を`useAxisCatalog`と同様の動的フェッチへ置き換える別タスクが必要
  （規模が大きく、地図UI一式に触れるリスクを伴うため本タスクのスコープ外とした）。
- 検証: `test_registry_defaults.py`全13件green（新規1件含む）、backend全1150件green、
  `export_openapi.py`再生成で`axis-catalog.json`が無変化（＝統合前後で値が完全一致、
  意図通りの無害な置き換え）であることを確認。フロントtsc green（生成物差分なし）。

### - [x] T277. 材料カタログをbackend正式レジストリ化し軸コンポーザーへ動的連携する 規模S〜M

- 背景: T276に続き「軸を編集することで地図上の推定アイコンを増減できるか」という
  ユーザー質問を調査した結果、(1) `registry.py`の軸集合と地図タイルのMVT焼き込み
  プロパティを調べたところ、`kind="ramp"`軸は`tile_inputs`（材料→tileプロパティの
  線形結合）から`MapOverlayControls`/`axisLayers.ts`が**既存コードのまま**汎用レイヤーを
  自動生成できること、アイコンも`SECONDARY_AXIS_ICONS[axisId] ?? AxisRampIcon`という
  汎用フォールバックが既にあり専用アイコン無しでも壊れないことが判明した。(2) 9材料中
  5〜6件がMVTタイルへ焼き込み済み（`surface_good`/`stop_per_km`/`intersection_per_km`/
  `accident_per_km`/`tunnel`、`lit`は符号反転要）で、`gradient_percent`/`wind_penalty`
  （タイル非焼き込み・動的取得）・`car_stress_level`（レシピ合成値）はramp化不可と
  判明した。(3) この調査中、ユーザーから「材料は今後システムメンテナンスで増減されうる
  ものとして設計してほしい。ただし材料自体をGUIでメンテナンスする必要はない。
  タイルに焼き込まれた状態である材料を取得し、推定要素（軸）に紐づけてCRUDできることが
  求めている点」という設計要件が示された。これは`frontend/src/lib/axisMaterialsCatalog.ts`
  （T270で作った、9材料をフロントに手書きしたリスト）自体が「システムメンテナンスで
  増減するものをフロントへ固定書きする」という、まさに避けるべき重複だったことを意味する。
- 対応方針:
  1. backendに材料カタログの正式レジストリを新設する（`domain/axis_definitions.py`への
     追加、または新規`domain/material_catalog.py`。案は着手時に決定）。各材料は
     `material_id`・`label`・`dtype`（numeric/boolean）に加え、内部用（フロントへは
     非公開）の`tile_property`（MVT焼き込み済みプロパティ名、無ければNone＝ramp化不可）・
     `tile_property_inverted`（no_lit⟵litのような符号反転フラグ）を持つ。
     `AXIS_MATERIAL_OPTIONS`（axisMaterialsCatalog.ts）と同じ9件を初期データとして移植する。
  2. 新規公開エンドポイント`GET /api/material-catalog`（認可不要、`material_id`/`label`/
     `dtype`のみ返す。`tile_property`系はbackend内部でのみ使う想定——T278（下記の地図表示
     ルール自動生成タスク、未起票）が消費する）。
  3. 管理API（`axis_admin.py`）の作成・更新経路に軽い検証を追加する: 送信された
     `material`（terms/flags/categoricalのmaterial）が材料カタログに存在しない場合は
     422で拒否する（現状は任意文字列を受け付けてしまう）。
  4. フロント: `services/materialCatalogApi.ts`＋`hooks/useMaterialCatalog.ts`
     （`useAxisCatalog`と同じ「マウント時1回取得、取得失敗時は静的フォールバック」
     パターン）を新設し、`components/AxisStudio/AxisComposer.tsx`をこのhook経由に
     置き換える。`lib/axisMaterialsCatalog.ts`はフォールバック定数としてのみ残す
     （またはhook内へ統合し削除）。
  5. **材料自体を追加・編集・削除するGUIは作らない**（ユーザー明示、材料の追加は
     引き続きbackendコード変更＋デプロイで行う、既存ADR「新素材の追加は引き続き
     バックフィルが必要」原則のまま）。
- 完了条件: `GET /api/material-catalog`が材料一覧を返し、軸コンポーザーの材料選択
  ドロップダウンがこのAPIから動的取得した値で構成されること。backend側に材料を
  1件追加（テスト用の一時的な追加で可）すると、フロントのコード変更・再デプロイなしに
  軸コンポーザーの選択肢に現れることを実機確認する。存在しない材料名を指定した
  軸作成・更新が422で拒否されることをテストで確認する。
- 依存: なし（T270完了後の独立タスクとして着手可能）。後続のT278（地図表示ルール
  自動生成、軸集合の同期・kind=ramp自動判定・SECONDARY_AXES動的化。未起票、
  T277完了後に別途起票する）の前提になる。
  **kind自動判定の手動オーバーライド要否はユーザー判断で解消済み（2026-08-24）**:
  `tile_property`を持つ材料（ramp化技術的に可能な材料）を使う軸は一律`kind="ramp"`とし、
  backend側にnoneへの手動オーバーライドは設けない。`surface_q`のような「技術的には
  ramp化可能だが既存の道路情報レイヤーと重複するため出したくない」というケースは、
  地図レイヤーパネル側（`MapOverlayControls`等）にレイヤーの表示/非表示切替を用意する
  ことで運用回避する（＝重複回避はUI層の関心事とし、backendのkind導出ロジックを
  複雑化させない）。T278起工時にこの方針で`kind`自動導出ルールを設計すること。
- 実装メモ（2026-08-24完了）: 対応方針1〜5をそのまま実装。新規`domain/material_catalog.py`
  （`MaterialSpec`/`MATERIAL_CATALOG`、既存9材料を移植）・新規`api/routers/material_catalog.py`
  （`GET /api/material-catalog`、`tile_property`系は非公開）・`axis_admin.py`へ
  `_check_materials_are_known`バリデータ追加（未知材料は422）。フロントは新規
  `services/materialCatalogApi.ts`・`hooks/useMaterialCatalog.ts`（`useAxisCatalog.ts`と
  同型：マウント時1回取得、失敗時は静的フォールバック）を追加し、`AxisComposer.tsx`の
  `emptyDraft`/`draftFromExisting`にmaterialOptions引数を追加してhook経由の材料一覧を
  注入する形へ変更。`lib/axisMaterialsCatalog.ts`は削除せず「フォールバック専用」へ
  役割を縮小（doc commentのみ更新）。OpenAPI再生成（`export_openapi.py`→
  `npm run generate:api`）で`MaterialCatalogEntry`/`MaterialCatalogResponse`型を
  frontend生成物へ反映。検証: backend全1151件green（新規テスト
  `test_create_returns_422_for_unknown_material`含む）、frontend tsc/eslint green、
  vitest全516件green、backend/frontend実サーバーでE2E確認
  （`GET /api/material-catalog`が9材料を返す、軸スタジオの材料ドロップダウンが
  API由来のラベルで構成されることをread_page/get_page_textで確認）。

### - [x] T278. 地図表示ルール(kind=ramp)の自動導出・軸集合の同期 規模M

- 背景: T277完了時点で、軸スタジオ（`/admin`）でDBへ新規登録した軸は`GET /api/axis-catalog`
  （T269）経由で一般向けルート設定画面には現れるが、**地図（レイヤーパネル・凡例・
  地図チップ）には一切現れない**——地図側は`registry.py: all_axes()`が書き出す
  build時静的生成物`axis-catalog.json`（`export_openapi.py`）を単一ソースとしており、
  `registry_defaults.py`に手書き登録された既存6軸（`wind`除く7軸中6軸）以外を知らない
  ため。またT276で調査した際、既存の`surface_q`軸は材料`surface_good`が
  タイルへ焼き込み済み（ramp化技術的に可能）にも関わらず「既存の道路情報レイヤーと
  重複するため」という理由で`kind="none"`に手書き固定されていた。この「技術的には
  ramp化可能だが手で`none`に固定している」という状態を、ユーザー判断（2026-08-24、
  T277完了報告時）で「一律`kind="ramp"`にし、重複回避は地図レイヤーパネル側の表示/
  非表示切替で運用する」という自動導出ルールへ統一する方針が決まった
  （T277エントリ「依存」節に記録済み）。
- 調査で判明した制約（重要）:
  1. `registry.py`の`axes[].inputs`（一次属性=OSM生タグ単位の参照。T167の「推定軸ON→
     観測レイヤー連動ON」・T146の「軸の材料一覧表示」が依存）と、`AXIS_DEFINITIONS`の
     `materials`（評価直前まで解決済みの値単位）は別の語彙で、機械的に統合できない
     （T12関係、docs/decisions/t221-axis-registry.md記載どおり）。そのため
     **`axis-catalog.json`の生成元をregistry.pyからAXIS_DEFINITIONSへ丸ごと差し替える
     ことはできない**——軸スタジオ作成軸は`inputs=[]`（材料一覧表示無し）で妥協する。
  2. `事故密度`軸の材料`accident_count_per_km_year`は年正規化済み（`accident_import_runs`
     の収録年数で除算、実行時に変動しうる）だが、タイル焼き込み済みの`accident_per_km`は
     年正規化前の生値。両者のスケール変換係数は静的に持てないため、**`accident`軸の
     ramp表示（thresholds等）は自動導出の対象外とし、`registry_defaults.py`の
     既存手書き値をそのまま維持する**。
  3. `停止密度`軸は2材料の重み付き線形結合（`stop_count_per_km` + 0.3×
     `intersection_count_per_km`）で、既存thresholds`[1,2,4]`は統計的な経験則であり
     単純な折れ点流用では再現できない。**複数材料の重み付き結合を伴う軸は自動導出の
     対象外**とし、既存の手書き値を維持する（stop_densityはこれに該当し変更しない）。
  4. `車ストレス`軸は材料`car_stress_level`がタイル非依存（レシピ合成値）のため
     自動的にramp化対象外と判定される（既存の`kind="bespoke"`を維持、変更不要）。
  5. MVLタイルの真偽値プロパティ（`surface_good`/`lit`/`tunnel`）はMapLibre上で
     `["==",["get","tunnel"],true]`のような真偽比較で読む必要があり、既存の
     `buildAxisRampValueExpression`（`Σ property×weight`の数値線形結合前提）では
     直接扱えない。`AxisTileInput`/`TileInputSpec`を拡張し、真偽値材料
     （`boolean`/`invert`/`true_value`/`false_value`）に対応させる必要がある。
- 対応方針（自動導出が安全に成立するケースに限定する）:
  1. 新規`domain/axis_display.py: derive_ramp_inputs(definition) -> RampInputs | None`。
     `AxisDefinition.materials`が全て`MATERIAL_CATALOG`でtile_property保持済みの場合のみ
     ramp化を試み、shape種別ごとに以下だけを扱う（それ以外は`None`＝自動導出対象外）:
     - `CategoricalShape`（真偽値材料1件）: 2値の中間点を閾値とする2段階ramp。
     - `FlagSumShape`（真偽値フラグN件）: 達成しうる合計値（部分和の全組合せ、cap適用後）の
       隣接中間点を閾値とする。
     - `BreakpointLinearShape`で**単一材料・weight=1.0・preprocess="identity"**の場合のみ:
       既存breakpointsのx値（先頭除く）をそのまま閾値に流用。複数材料・非等倍weight・
       abs前処理は対象外（制約3・既存stop_density等を変更しないため）。
  2. `registry.py: TileInputSpec`へ`boolean: bool = False`・`invert: bool = False`・
     `true_value: float = 0.0`・`false_value: float = 0.0`を追加（数値材料は`weight`のみ
     使用、真偽値材料は`boolean=True`で`true_value`/`false_value`を使用、`weight`は無視）。
  3. `registry_defaults.py`: `surface_q`（材料`surface_good`）と`night`
     （材料`no_lit`・`has_tunnel`）の`display`を`derive_ramp_inputs()`経由の
     `kind="ramp"`へ置き換える（`category`・`label`・既存の`note`文言は手書きのまま
     維持、`tile_inputs`/`thresholds`のみ自動導出値に差し替え）。`gradient`
     （タイル非依存で自動的に対象外）・`stop_density`（制約3）・`car_stress`
     （制約4）・`accident`（制約2）は変更しない。
  4. `export_openapi.py`: `axis-catalog.json`の`axes[]`生成を、`registry.all_axes()`に
     加えて「`AXIS_DEFINITIONS`にあるが`registry.py`未登録の軸」も走査し、
     `derive_ramp_inputs()`が`None`を返さない（＝ramp化可能と判定された）場合のみ
     `inputs=[]`・`output_range=(0,100)`・自動生成`display`（`category="trafficSafety"`
     既定、`note`はdefinition.descriptionを流用）で追加する。`None`の場合は追加しない
     （地図に出ない＝現状と同じ「専用レイヤー無し」のまま、regressionにならない）。
     これにより将来軸スタジオが作る新規軸のうち、真偽値材料またはシンプルな単一数値材料の
     ものは再デプロイ後に自動で地図へ現れるようになる（複雑な軸は従来どおり地図無しのまま
     グレースフルに動作）。
  5. フロント`components/Map/axisLayers.ts`: `AxisTileInput`に`boolean?`/`invert?`/
     `trueValue?`/`falseValue?`を追加し、`buildAxisRampValueExpression`が
     `boolean=true`の入力を`["case", 真偽比較, trueValue, falseValue]`で組み立てる分岐を
     追加する（既存の数値`Σproperty×weight`分岐とは独立、後方互換）。
  6. フロント`components/Map/secondaryAxes.ts`: `SECONDARY_AXIS_LAYER_IDS`（現状
     car_stress/stop_density/accidentの3件を手書き固定）を「`display.kind==="ramp"`なら
     `axisMapLayerId(axis_id)`を自動算出、bespoke（car_stress）のみ引き続き手書き」という
     ルールへ一般化する（将来ramp軸が増えるたびにこの辞書へ追記する手間を無くす、
     T278の「SECONDARY_AXES動的化」の一部）。`SECONDARY_AXIS_PROXY_HINTS`から
     `surface_q`・`night`のエントリを削除する（両軸ともkind="ramp"に変わり専用レイヤーを
     持つため、「地図表示なし」の代役案内は不要になる）。
  7. `MapView.tsx`・`mapLayers.ts`・`staticAttributeLayers.ts`は変更不要（`RAMP_AXES`を
     汎用的に走査する既存実装がそのまま新しいramp軸2件を拾う設計、調査で確認済み）。
- 完了条件: `surface_q`・`night`が地図の推定指標レイヤーとしてON/OFFトグル・凡例付きで
  表示され、`stop_density`/`accident`/`car_stress`/`gradient`の既存表示が変更前と
  完全に一致すること（回帰無し）。backend/frontend双方のテストが全てgreen。
  実機ブラウザでsurface_q・nightレイヤーのON/OFF・色分け・凡例クリック絞り込みを確認する。
- 依存: T277（材料カタログ、完了済み）。
- 実装メモ（2026-08-24完了）: 対応方針1〜7をそのまま実装。新規`domain/axis_display.py:
  derive_ramp_inputs()`（Categorical/FlagSum/単一材料BreakpointLinearのみ自動導出、
  部分和ベースの閾値算出込み）・`MaterialSpec.tile_property_needs_runtime_scale`
  （accidentを明示的に自動導出対象外とマーク）を追加。`registry_defaults.py`の
  surface_q/nightの`display`を自動導出値へ差し替え、`export_openapi.py`のaxis-catalog.json
  生成を「registry.py未登録だがramp化可能な軸」も含める形へ拡張。フロントは
  `axisLayers.ts`（`AxisTileInput`へboolean/invert/trueValue/falseValue追加、
  `buildAxisRampValueExpression`が`["case",...]`分岐を追加）・`secondaryAxes.ts`
  （`SECONDARY_AXIS_LAYER_IDS`をkind="ramp"なら自動算出する一般化、surface_q/nightの
  proxyHintエントリ削除）・`mapLayers.ts`（unit=""時の空`[]`表示を抑止する軽微な修正）を
  変更。`MapView.tsx`等は調査どおり無変更で新axisを拾えた。
  検証: backend全1160件green（新規`test_axis_display.py`7件＋`test_registry_defaults.py`
  2件含む）、frontend tsc/eslint/vitest 517件green（`MapOverlayControls.test.tsx`・
  `MapLayersPanel.test.tsx`の「surface_q/nightは専用レイヤー無し」という旧前提のテストを
  「他のramp軸と同じ実レイヤーセクションになる」という新前提へ更新）。実サーバーで
  `/api/material-catalog`・軸スタジオの材料ドロップダウン・地図の推定指標グループを
  確認し、舗装質・夜間が停止密度・事故密度と同じ「ON/OFF可能なタイル」として現れる
  （disabledの情報タイルではなくなる）ことをアクセシビリティツリー・コンソール
  エラー無し・ネットワークログで確認した。**ただし本セッションのBrowser paneが
  非表示（compositing不可）の制約により、地図キャンバスへの実際のタイル取得・
  色分けピクセル描画そのもの（MapLibreの実際の色分け結果）は確認できていない**——
  MapLibre style自体の妥当性（`["case",...]`式が無効ならスタイル読込時に例外が出る）は
  コンソールエラー無しで確認済みだが、これは「地図が実際に正しい色で塗られるか」の
  代用にはならない。次にBrowser paneが表示可能なセッションで、舗装質・夜間の
  色分け・凡例クリック絞り込みを実ピクセルで再確認することが望ましい。
- **レビュー修正（2026-08-24、T268〜T278の追加コミット分を対象に`/code-review`実施）**:
  上位10件を修正: (1) `export_openapi.py`がAXIS_DEFINITIONSをDBから再読込しておらず
  「軸スタジオで作った軸が再デプロイ後に地図へ自動反映される」という上記の完了条件が
  実は満たされていなかった致命的バグを修正（DB接続失敗時は`refresh_axis_definitions`と
  同じ安全側フォールバックへ倣う）。(2) OpenAPI/api.d.tsのX-Admin-Token残存ドリフトを
  再生成で解消。(3) 軸定義payloadのdtype（numeric/boolean）と形状種別の不整合を
  バリデーションで拒否するよう追加。(4) `surface_good`未分類路面がNULL→「悪い」評価に
  誤判定されていたバグを`has_unknown_fallback`で修正（灰色「不明」表示に変更）。
  (5) `AxisDefinitionResponse`が書き込み専用バリデータを継承し、削除済み材料を参照する
  既存軸の一覧/取得APIが500になる問題を、フィールド共有の基底クラス分割で修正。
  (6) `BreakpointLinearShape`のramp自動導出が符号反転(`tile_property_inverted`)を
  無視していたため、対象外（`None`）を返すガードへ修正。(7) docs/architecture.md・
  admin/page.tsxのX-Admin-Token時代の古い記述をT272後の実態へ更新。(8) `proxy.ts`の
  Basic認証比較を`timingSafeEqual`によるタイミング攻撃耐性のある比較へ修正。
  (9) `AxisRegistryAdminService.create`/`update`の冗長なDB往復（list_all()+get()の
  2回発行）を`list_all_with_sort_order()`新設で1回へ集約。(10) `FlagSumShape.flags`に
  `Field(max_length=12)`を追加し組合せ爆発を防止。加えてユーザー指示により、
  DebugConsole（地図イベントのライブログ）がT270で`/admin`へ移設された結果
  「`/admin`には地図が無くログがタブ間で共有されないため実質機能しなくなっていた」
  問題を、「`/`=地図を操作しながら見るライブログ本体」「`/admin`=デバッグモードの
  設定・集計」という役割分割で再設計・修正した。上位10件以外の候補6件も精査し、
  `useRecipeOverride.ts`のstorageKey省略時の非永続分岐（T270以降、本番の全呼び出し元が
  storageKeyを渡すためテスト以外では到達しない死んだ分岐だった）をstorageKey必須化で
  簡略化。残り5件（排他チェックの二重実装・TileInputSpecのデュアルモード・
  AxisComposerのDraft構造・proxy.ts/backend二重Basic認証・runtime_scaleフラグ）は
  既存設計が妥当と判断し見送った。検証: backend全1173件green、frontend
  tsc/eslint/vitest全519件green、Playwright(headless)でDebugConsole移設後の
  トップページ・`/admin`両方を実機確認。

---

## 全体最適レビュー第8回の起票（2026-08-24・ユーザー承認済み）

全ソースコード・DB設計をゼロから再読した総合診断レビュー
（[.claude/commands/review/history/2026-08-24_overall.md](../.claude/commands/review/history/2026-08-24_overall.md)、
対象コミット`fc7bd5a`、総合スコア83/100）の指摘を起票する。起票案A〜Fに加え、
ユーザー指示「知見として見つけたものもタスク化・掘り下げするべきものがないか再チェック」を
受け、レポート本文に留めていた知見4件（T285〜T288）もトリガー付きで正式起票した。

### - [x] T279. OpenAPI生成物ドリフトの解消＋CI状態確認＋コミット前検知の機械化判断〔P1〕規模S（2026-08-24完了）

- 背景: レビューで実測検出（レポートF-1）。HEAD `fc7bd5a`自身が`api/routers/axis_admin.py`の
  `AxisDefinitionResponse`へdocstringを追加（500バグ修正の継承分離）しながら
  `export_openapi.py`再生成を行わなかったため、worktreeで再生成すると
  `frontend/src/types/generated/openapi.json`に差分1件（`description`追加）が出る。
  CLAUDE.mdの同一コミット同期ルール（T180・T185・T218の実績を受けT196で明文化、
  2026-08-23にCLAUDE.mdへ昇格）の**4回目の類型再発**であり、ルール明文化・CI検知
  （api-contractジョブ）導入後の初再発である点が重い。
- 内容:
  1. `export_openapi.py`→`npm run generate:api`を実行し、生成物差分をコミットする
     （`git diff --exit-code -- frontend/src/types/generated/`クリーンを確認）。
  2. GitHub Actionsの`fc7bd5a`のapi-contractジョブ結果を確認する（赤である可能性が高い。
     ローカルにgh CLIが無く未確認のため、確認手段の整備〔gh導入またはブラウザ確認の
     手順明記〕も本タスクに含める）。
  3. 再発防止の機械化を判断する: 「気をつける」型のルールは4回破られた実績があるため、
     ローカルのコミット前検知（pre-commitフック等でbackend側API関連ファイル変更時に
     生成物ドリフトをチェック）の導入要否を決め、判断理由ごと記録する。導入しない場合も
     「なぜCIだけで足りるとするか」を明記する（設計原則10）。
- 対応:
  1. `export_openapi.py`→`npm run generate:api`を実行し再生成。差分はレビュー実測
     どおり`AxisDefinitionResponse`のdocstring1件のみ（`openapi.json`・`api.d.ts`）で
     他生成物は無変化。フロントtsc green（型整合確認）を確認しコミット。
  2. GitHub Actions公開API（`/repos/{owner}/{repo}/actions/runs`、認証不要）で`fc7bd5a`の
     CI実行を確認したところ、**予測どおりapi-contractジョブが`git diff --exit-code`で
     失敗（exit code 1）していた**（ユーザーが実際のCIログを提示し裏取り）。ローカルに
     `gh` CLI未導入のため、この公開API直叩きを今回の確認手段として採用した。
  3. **機械化判断: ローカルpre-commitフックを導入する（4回目の再発を受け「気をつける」型
     ルールでは不十分と判断）**。`scripts/pre-commit-api-contract.sh`（リポジトリへコミット、
     版管理下）を新設し、このワークツリーの`.git/hooks/pre-commit`へ手動配置して有効化した。
     設計判断: (a) ステージ済みファイルが`backend/app/api/`・`backend/app/domain/`・
     `backend/app/config.py`・`backend/scripts/export_openapi.py`に該当する場合のみ実行
     （実測約12秒のコストをdocsのみ・frontend UIのみのコミットに負わせない）。
     (b) venv・npmが見つからない環境（並行セッションの`git worktree`で`.venv`が
     複製されない構成を含む。CLAUDE.md「作業ツリーの安全」の並行セッション前提）では
     警告のみでコミットを止めないsoft-fail。差分が実際に検出された場合のみexit 1する。
     (c) `git config core.hooksPath`は変更しない（CLAUDE.md「git configを更新しない」
     方針に従い、このワークツリーへのファイル配置のみに留めた）。他のworktree・clone・CI
     環境には影響しない。**同種のリスクを持つ他の手動同期ペア（タイル世代番号・
     region-tile-config.json等）への同型フック拡張は本タスクのスコープ外**（まず
     OpenAPI契約1件で運用実績を積んでから判断する）。
- 完了条件: 生成物差分ゼロのコミット（済）＋CI状態確認（済、失敗を確認）＋機械化の判断記録（済）。

### - [ ] T280. 材料供給の1本道短縮（軸スタジオの「材料の天井」の構造対策）〔P2〕規模M〜L — トリガー: 次に軸・材料関連の実装要望が出た時点（軸スタジオのUI拡張より先に実施する）

- 背景: レビュー最重要指摘（レポートF-2）。Phase 2〜3（T270〜T272）で軸のGUI作成・統治
  基盤は完成したが、①9材料すべてが既存7軸に排他帰属（`check_material_exclusivity`、
  shared概念なし）、②公開済み軸は不変・削除不可（T271）、③GUI作成軸は表示レジストリ
  （`registry.py`、ビルド時静的・手書き登録）に載る経路が無い——の3制約が重なり、
  **軸スタジオから実用的な新軸を1つも作れない**。天井を破る唯一の変数は材料の供給で、
  現状の新材料追加はコード変更＋デプロイに加え、タイル焼き込みCASE式
  （`_ROAD_SURFACE_TILE_MVT_SQL`）・タイル世代・`compute_edge_costs_bulk`の抽出フェーズ
  （`evaluation.py:598〜`、材料ごとの手書きnumpy配列化）の追記を要する長い経路になっている。
- 内容（候補、着手時に設計判断）:
  1. 抽出フェーズの`MATERIAL_CATALOG`駆動化（材料id→抽出方法の宣言から numpy配列構築を
     導出し、材料追加時の手書き箇所を減らす）。T221 Stage B以降（レジストリ駆動化）の
     残り区間・スカラー/配列二重実装の解消（第7回C-1）と同一方向のため、統合して
     優先度を再評価する。
  2. タイル焼き込みプロパティの宣言化またはコード生成の検討（CASE式手書きの削減）。
  3. `shared`材料の導入判断: 例えば`gradient_percent`を複数軸で参照可能にする方が、
     新材料の追加より早く天井を破れる可能性がある。排他帰属原則（目論見書）との整合を
     ユーザーと確認のうえ決める。
- 影響範囲（保留した場合）: 軸スタジオはT273（蒸留）以降も「既存軸の閲覧・複製の練習場」に
  留まり、T270〜T272の投資が回収されない。GUI側をさらに拡張しても天井は動かない。
- 完了条件: 着手時に確定（少なくとも「新材料1件の追加に必要な編集箇所一覧」が現状から
  明確に減ったことを、実際の材料追加1件で実証する）。

### - [ ] T281. 派生データ鮮度の段階対応（依存DAG文書化→統合エントリポイント→鮮度台帳）〔P2〕規模S→M

- 背景: レビュー指摘（レポートF-3）。`batch/`配下8バッチ（import_pbf・import_accidents・
  import_designations・match_designations・precompute_edge_attribute_counts・
  precompute_elevation_attributes・precompute_road_node_degrees・
  precompute_way_attribute_counts）の実行順序・再実行要否がmigrationコメントと
  docstringに分散した不文律のまま。ランタイムの遅延構築（save_graph）で生まれた新規Edgeは
  バッチ手動再実行まで`edge_attribute_counts`/`elevation_attributes`が欠損し、
  stop/accident/intersection/gradient軸が**黙って評価から抜ける**（重み再正規化で薄まる
  だけで検知できない）。T74・T101・T242の本番障害はすべてこのクラスで、対策が
  「人が気をつけるルール」（CLAUDE.md 2本）に留まっている。
- 内容（段階、各段階にトリガー）:
  1. 【即時・S】依存DAGと「この生データが変わったらこのバッチ群を再実行」対応表を
     docsへ1枚化する（例: docs/osm-pbf-import.mdへの追記または独立ファイル）。
  2. 【M — トリガー: 次回のデータ投入・エリア拡大作業時】順序解決込みの単一エントリポイント
     （`python -m app.batch.refresh_derived`等）を導入し、手順書の複数コマンドを1つに畳む。
  3. 【トリガー: 同クラス障害の再発、またはT127全国展開の意思決定】*_import_runs系を一般化
     した鮮度台帳で「生データ更新時刻 vs 派生computed_at」を機械比較可能にする。
     T242残課題（標高バックフィル定期実行）のスケジューリング基盤新設と関連するため、
     着手時に統合を検討する。
- 完了条件: 段階1はドキュメント1枚の存在。段階2以降は着手時に確定。

### - [ ] T282. Repositoryファサード委譲33本 — R-8トリガー「30本超で再検討」発火の判断記録〔P2〕規模S（判断のみ）

- 背景: レビュー指摘（レポートF-4）。`RoadGraphRepository`ファサード
  （road_graph_repository.py:2259〜）の委譲メソッドが33本に達し、複雑度レビュー
  2026-08-16 R-8がKEEP判断時に設定した再検討トリガー「30本超」を超えた。
- 内容: 選択肢 (a) 現状維持を新上限（例: 45本）とともに再確定、(b) 呼び出し側を
  サブリポジトリ（AttributeRepository等）直接注入へ移行しファサード縮退、(c) 用途別
  ファサード分割（探索材料系/タイル系/バッチ系）。レビューの推奨は**(a)**
  （Fakeリポジトリが依存する正式契約として機能しており、呼び出し元は既にGraphService等で
  束ねられているため。分割は変更理由の異なる利用者が現れてからで遅くない）。
  トリガー発火→判断の記録自体が本タスクの成果物（設計原則10）。
- 完了条件: 判断と新トリガーをdocs（complexity-review系の規模ウォッチまたは本ファイル）へ記録。

### - [ ] T283. `road_graph_use_repository`設定の名称・既定値の再考〔P3〕規模S — トリガー: 次のconfig.py変更のついで、または新環境構築時

- 背景: レビュー指摘（レポートF-6）。T222（DBなし構成撤去）・T247（road_graph既定化）を
  経て、この設定の実質的な意味は「地図レイヤー（路面/POI/事故タイル）・標高キャッシュ・
  ORSエンジン路面評価のDB利用」フラグへ変わったが、名称は旧来のまま。既定`False`のため
  本番・新環境で設定を忘れると**ルート生成は動くのに地図レイヤーがすべて空**という
  気づきにくい縮退になる（既定エンジンがDB必須になった今、「DBはあるのにこのフラグだけ
  False」という中途半端な状態が最頻の罠）。
- 内容: 名称変更（例: `map_layers_use_db`等）または既定値`True`化（DB接続失敗時は既存の
  空タイルフォールバックが効くため安全側は保てる）を比較し、どちらかを実施する。
  `.env.example`のプロファイル表も追従する。
- 完了条件: 変更の実施＋.env.example追従＋architecture.md該当箇所の更新。

### - [ ] T284. page.tsx閾値発火前の分割方針の事前確認〔P3〕規模S（判断のみ）— トリガー: 次のUI機能（page.tsxへ追記が見込まれるもの）の着手前

- 背景: 規模ウォッチ実測（2026-08-24）: page.tsx **1,773行**（閾値1,900、残127行）・
  state **36件**（useState 28＋useStoredState 5＋useStoredJsonState 3、閾値40）。
  直近2日で+158行のペースであり、次の中規模UI機能で閾値到達がほぼ確実。MapView.tsxは
  2,489行（閾値2,800、残311行）でやや余裕がある。
- 内容: 発火してから慌てて分割するのではなく、着手前に対応方針（レイヤー可視性系の
  useReducer化 or レシピ軸単位のカスタムフック化、複雑度レビュー2026-08-18 F-3の候補）を
  選んでおき、次のUI機能実装と同時または直前に実施するかを判断する。
- 完了条件: 方針の決定記録（実施自体は閾値到達時でよい）。

### - [ ] T285. 表示系レジストリの縮退 — 軸カタログのランタイム一本化〔P3〕規模M〜L — トリガー: T280完了後、またはGUI作成軸を地図レイヤーへ出す要望が出た時点

- 背景: レビュー「目指すべきアーキテクチャ像」§10-2の正式化。軸の情報源が
  計算系（`AXIS_DEFINITIONS`、DB化・ランタイム反映）と表示系（`registry.py`、ビルド時
  静的・手書き登録）の二重レジストリになっており、GUI作成軸は地図レイヤー・凡例へ
  永遠に反映されない。**T276の実装メモが「真に動的反映させるには地図レイヤー側
  （`SECONDARY_AXES`/`primaryAttributes.ts`等、`axis-catalog.json`静的importの複数箇所）を
  `useAxisCatalog`と同様の動的フェッチへ置き換える別タスクが必要（規模が大きく本タスクの
  スコープ外とした）」と明記した宿題**であり、本タスクがその正式起票にあたる。
- 内容: ramp系軸の表示定義は`axis_display.py: derive_ramp_inputs`の自動導出へ寄せ、
  `registry.py`にはbespoke軸の宣言と一次属性カタログのみを残す。`axis-catalog.json`の
  「ビルド時静的」は一次属性・bespoke分に限定し、軸一覧はランタイムAPI
  （`GET /api/axis-catalog`、T269）へ一本化する。地図UI一式（MapView.tsxのレイヤー
  ファクトリ・レイヤーパネル）へ触れるため、Playwright実機確認を完了条件に含めること。
- 影響範囲（保留した場合）: GUI作成軸の地図表示不可という制約が残り続ける（T280が
  完了して軸を作れるようになった時点で、この制約が次のボトルネックとして顕在化する）。
- 完了条件: 着手時に確定（少なくともGUI作成軸1件が再デプロイなしで地図レイヤーに
  現れることの実機確認を含める）。

### - [ ] T286. architecture.mdの経緯記述をdecisions/へ追い出す第2弾〔P3〕規模M — トリガー: 次の大きな設計転換時に独立タスクとして、またはユーザーの整理指示

- 背景: レビュー指摘（レポート§7-4）。architecture.mdが1,680行に達し、「現状の姿」を
  記すはずのドキュメントにStep時代の試行錯誤・撤去済み機能の注記（「当初は〜だったが
  撤去」型の段落）が堆積している。T8（決定記録のdecisions/分離、第1弾）と同型の整理を
  もう一度行う時期に来ている。新規参加者（将来の自分を含む）の初読コストと、
  「コード変更と同一コミットでarchitecture.md更新」ルールの編集コストの両方に効く。
- 内容: 「現状の姿」として残す記述と「経緯・教訓」としてdecisions/へ移す記述を仕分ける。
  移設は内容無変更（リンクで辿れることが条件）。「ついで」にやらず独立タスクとして
  実施する（過去の同種整理T8・2026-08-19棚卸と同じ運用）。
- 完了条件: architecture.md本文の行数削減（目標は着手時に設定）＋decisions/側からの
  リンク整合＋CLAUDE.md/context.mdの参照先が壊れていないこと。

### - [ ] T287. road_nodes/road_edgesのtext型PKの容量・性能再評価〔P3〕規模S（調査のみ）— トリガー: T127（全国データ取込）の意思決定時に容量試算へ含める

- 背景: レビュー指摘（レポート§6）。`road_edges.edge_id`・`road_nodes.node_id`は
  決定論的文字列ID（text型PK）で、FK（elevation_attributes・edge_attribute_counts・
  designation_attributes旧キー）・JOIN・索引サイズがbigint比で数倍になる。関東規模
  （数十万Edge）では実測上問題になっていないが、全国規模（T127、既にPBF取込で
  94万way超の減速実測あり）では索引サイズ・JOINコストの支配項になりうる。
- 内容: T127の容量・所要時間検証に「決定論的採番を維持したままbigintハッシュ等へ移行する
  場合の容量・移行コスト試算」を1項目として含める。現時点でのスキーマ変更は行わない
  （関東規模で問題が出ていない変更は割に合わない）。
- 完了条件: T127検証レポートに本観点の試算が含まれること。

### - [ ] T288. AXIS_DEFINITIONS push型更新のマルチワーカー対応〔P3〕規模S〜M — トリガー: backendの複数ワーカー/複数プロセス構成の採用時（現状は単一プロセスデプロイのため未到達）

- 背景: レビュー指摘（レポート§6）。`AXIS_DEFINITIONS`はmutableグローバル辞書を
  「起動時＋管理API書き込み直後」の2箇所でin-place更新するpush型設計
  （`services/axis_registry_service.py`）。単一ワーカーでは安全だが、複数ワーカー化すると
  他プロセスでの軸編集が反映されない。また同一プロセス内でも「リクエスト冒頭の
  RoutePreference検証」と「後段の評価」の間にawaitを挟むため、管理API書き込みとの
  理論上の不整合ウィンドウがある（実害は管理者手動操作時のみ・確率極小）。
  対応方針（`axis_registry_meta.revision`のポーリングへ差し替え）は
  docs/decisions/t221-axis-registry.md「Stage D設計メモ」に記録済みで、本タスクは
  それをトリガー付きで拾えるようにする正式起票。
- 影響範囲（保留した場合）: 単一プロセスデプロイを続ける限り実害なし。複数ワーカー化を
  「別の理由」（性能等）で行う際に本タスクを見落とすと、軸スタジオの編集が一部プロセスに
  反映されない不整合が黙って起きる——複数ワーカー化のタスクを起こす際は本タスクを
  完了条件に含めること。
- 完了条件: 着手時に確定（ADRの方針どおりrevisionポーリング等へ差し替え、複数プロセスでの
  反映テストを含む）。

### - [x] T289. 一方通行（一次属性）を観測グループの独立レイヤーとして追加する 規模S〜M（2026-08-24完了）

- 背景: T280（材料供給の1本道短縮）着手にあたりユーザーへ具体的な新規要素を確認したところ
  「一方通行」の追加希望が挙がった。調査の結果、**一方通行は既にグラフ構造レベルで完全に
  ハンドリング済み**（`osm_adapter.py: _resolve_direction`が`oneway`/`oneway:bicycle`
  タグからforward/backward/bothを解決し、`graph.py: build_road_graph`が逆方向Edge自体を
  生成しない。探索は構造的に一方通行を厳密に守っており、逆走はそもそも不可能）と判明。
  そのためT280（評価軸向け材料の追加コスト削減）の実証対象にはならず、**独立タスク**として
  起票する。用途はユーザー確認により「まず表示のみ（評価軸への重み付け組み込みは別途）」に
  確定した。
- 設計: `MATERIAL_CATALOG`（評価軸専用）ではなく、`domain/registry.py:
  PrimaryAttributeSpec`（一次属性）＋地図の静的属性レイヤーとして追加する
  （2026-08-22のT217「トンネルを観測グループの独立レイヤーとして追加」と全く同型の
  一次属性追加パターン。tunnelはタイルへの焼き込み自体は既存だったためbackend変更
  ゼロだったが、one-wayは`osm_raw_ways.direction`列がありながらタイルSQLに未焼き込みの
  ため、backend側の変更が一手多い点が異なる）。
- 内容（T217を1本道の地図として利用、`git show 2a603c6`参照）:
  1. **backend**: `_ROAD_SURFACE_TILE_MVT_SQL`（road_graph_repository.py）のCASE式へ
     `CASE WHEN w.direction != 'both' THEN true END AS oneway`を追加
     （`osm_raw_ways.direction`は既にDB永続化済み、migration不要）。
  2. タイル世代番号を上げる（`region_service.py: ROAD_SURFACE_TILE_VERSION`と
     `region-tile-config.json`、CLAUDE.md同期ルール必須）。
  3. `registry_defaults.py`へ一次属性として登録（`attr_id="oneway"`,
     `dtype="boolean"`, `geometry="edge"`, `source="osm"`,
     `ingest_fn="app.domain.osm_adapter.osm_way_to_way_spec"`。どの評価軸のinputsにも
     含めない＝軸に属さない表示専用の一次属性、`all_primary_attributes()`が
     `axis-catalog.json`のprimary_attributes[]へ自動反映するため軸登録は不要と確認済み）。
  4. **frontend**: `mapLayers.ts`（MapLayerId型・MAP_LAYERS・ROAD_SURFACE_SHARED_LAYER_IDS）・
     `staticAttributeLayers.ts`（ONEWAY_LEGEND/COLOR_EXPRESSION/OPACITY_EXPRESSION、
     StaticFilterAxisId・STATIC_FILTER_AXES）・`icons.tsx`（OnewayIcon）・
     `MapView.tsx`（ONEWAY_LAYER_ID・ensureOnewayLayer・STATIC_OVERLAY_LAYERS・
     LAYER_DATA_SOURCES・showOneway props配線、T217差分どおり多数のuseEffect依存配列へ
     機械的に追加）・`page.tsx`（DEFAULT_LAYER_VISIBILITY・showOneway受け渡し）・
     `primaryAttributes.ts`（PRIMARY_ATTRIBUTE_LAYER_IDS・PRIMARY_ATTRIBUTE_CHIP_LABELS）・
     `MapLayersPanel.tsx`（switch文case追加）・`MapOverlayControls.tsx`（LAYER_ICONS）。
  5. テスト: T217の対応テスト（`staticAttributeLayers.test.ts`・`primaryAttributes.test.ts`・
     `MapView.dataStatus.test.ts`・`MapLayersPanel.test.tsx`・`MapOverlayControls.test.tsx`）と
     同型のケースを追加。
- 完了条件: backend/frontend全テストgreen、Playwright実機確認（地図上で一方通行区間が
  色分け表示されること）、docs/architecture.md追従。
- 検証: backend全1174件green（新規1件: `_ROAD_SURFACE_TILE_MVT_SQL`のoneway焼き込み検証）、
  frontend tsc/eslint/vitest全523件green（新規4件）。実機確認（Playwright headless
  chromium、ユーザー明示要望どおりClaude Browserペインでなく自前スクリプトで実施）:
  王子駅付近z14でタイルAPIを直接デコードしoneway=trueが671件中257件正しく焼き込まれて
  いることを確認、地図上で観測グループ「一方通行」チップをONにすると青色（`#2563eb`）で
  一方通行区間が明確に色分け表示されコンソールエラー0件を確認。区間クリックポップアップの
  「一方通行」行表示は座標特定がPlaywright側の制約で難航したため実機クリックでは
  未確認だが、`INTERACTIVE_LAYER_IDS`が`STATIC_OVERLAY_LAYERS`から自動導出される設計
  （手書きリストなし）のためonewayレイヤーは自動的にクリック判定対象へ含まれることを
  コードで確認済み。
- 実装メモ: `MATERIAL_CATALOG`ではなく一次属性として実装したため、当初の起票案どおり
  T280（材料供給の1本道短縮）の実証にはならなかった。T280は「軸スタジオUI拡張より先に
  実施する」という順序制約付きでトリガー待ちのまま据え置き。

### - [x] T290. MVTタイルに焼き込み済みだが材料未登録の生データをMATERIAL_CATALOGへ網羅登録する 規模M（2026-08-24完了）

- 背景: T289完了後、ユーザーから「設計の一貫性を取ろうとしている。評価や地図描画に
  使えそうな生データは全部材料登録しておきたい」という方針指示。`_ROAD_SURFACE_TILE_
  MVT_SQL`の全プロパティと`MATERIAL_CATALOG`（9材料）を突き合わせた結果、**11件の
  生データが既にタイルに焼き込まれているのに材料未登録**と判明した:
  - 既存dtype（numeric/boolean）でそのまま登録可能（5件）: `bridge`・`motor_vehicle_no`・
    `oneway`（T289で一次属性化したが材料化はしていなかった）・`maxspeed_kmh`・`lanes_count`
  - 多値カテゴリカル、dtype拡張が必要（6件）: `highway`・`surface`・`bicycle_infra`・
    `cycleway_class`・`designation`・`smoothness`
- 設計方針（ユーザー承認済み）:
  1. `material_catalog.py: MaterialDType`を`Literal["numeric", "boolean"]`から
     `Literal["numeric", "boolean", "categorical"]`へ拡張し、11材料すべてを登録する。
  2. **`categories`（許容値一覧）フィールドは追加しない**——highway等はこのプロジェクトで
     正準の閉じた集合を管理しておらず、無理に列挙すると事実と異なる情報になるため。
     詳細はMaterialSpecのコメントで説明する。
  3. **`axis_definitions.py: CategoricalShape`（`mapping: dict[bool, float]`）の
     文字列対応拡張は今回のスコープに含めない**——材料の「存在を宣言する」ことと
     「評価軸として実際に使えるようにする」ことは独立した作業であり、今使う予定のない
     評価ロジックを先回りで拡張すると過剰設計になる（設計原則9）。
     **トリガー: 上記6件のいずれかを実際に評価軸の材料として使う新規軸の要求が出た時点**
     （その時点でCategoricalShapeを拡張するか、その軸専用の新Shape種別を追加するかを
     具体的な要件に応じて判断する）。
- 影響範囲（保留した場合）: 現状どおり——軸スタジオの材料選択肢に現れないだけで、
  実害はない。ただしT280（材料の天井対策）の候補材料が見えないままになる。
- 完了条件: `material_catalog.py`へ11材料追加＋`MaterialDType`拡張。
  `GET /api/material-catalog`のレスポンスに20材料（既存9+新規11）が含まれることを
  確認。backend/frontend全テストgreen。既存7軸の挙動・OpenAPI契約（`AXIS_DEFINITIONS`
  非対象のため本来変更なしのはずだが、`material-catalog.json`生成物のドリフト確認は必須）に
  影響がないことを確認。
- 検証: backend全1181件green（新規7件: `test_material_catalog_routes.py`新設5件＋
  `test_axis_admin_routes.py`2件、`categorical`材料をBreakpointLinearShape/
  CategoricalShapeに指定した場合の422拒否を確認）。frontend tsc/eslint/vitest全523件
  green（既存件数のまま、回帰なし）。実機確認（`GET /api/material-catalog`で20材料・
  categorical6件のdtypeを確認、軸スタジオの3つのshape種別[区分線形補間/カテゴリ値/
  フラグ加算]それぞれで材料ドロップダウンを実機確認——numeric専用は7件[新規2件含む]、
  boolean専用は6件[新規3件含む]がそれぞれ正しく表示され、categorical6件はどちらにも
  混入しないことを確認、コンソールエラー0件）。
- 追従修正: `lib/axisMaterialsCatalog.ts: AxisMaterialOption.boolean`（2値フラグ）を
  `dtype: AxisMaterialDType`（"numeric"/"boolean"/"categorical"の3値）へ変更した。
  旧実装のまま`categorical`材料を追加すると`!boolean`（numeric用フィルタ）に誤って
  混入し「選べるのに送信時にエラーになる」UXを生むため、T290に付随する必須の追従修正
  として対応した（`AxisComposer.tsx`のフィルタ条件4箇所を`dtype`比較へ書き換え）。

### - [ ] T291. car_stress軸のcycleway補正をbicycle_infra（6値）ベースへ精密化する 規模L

- 背景: T290完了後、ユーザーから「自転車の走りやすい道を推定しようとした時、
  categorical型で特定カテゴリを選択したい」という要望。調査の結果、既に
  `domain/traffic.py: classify_bicycle_infrastructure`（6値: separated/lane/
  shared_busway/shared_pedestrian/prohibited/roadway）と`domain/recipe.py:
  cycleway_class`（3値: track/lane/shared、car_stress軸のcycleway補正専用）という
  **2つの独立した自転車インフラ判定ロジックが並存**していると判明した。ユーザーへ
  設計方針を確認した結果:
  1. 新規独立軸ではなく**既存car_stress軸の「再定義」**（推定カテゴリの軸を、
     T290で取り込んだ一次属性=bicycle_infraで再定義したい）
  2. 再定義の範囲は**cycleway補正部分のみ**（highway基準値・maxspeed補正・
     lanes補正・指定路線補正は維持、軸の趣旨=「車の圧迫感」は変えない）
  3. スコア案（0-100スケール、易→難）: separated=0・lane=20・shared_busway=40・
     shared_pedestrian=50・roadway=70・prohibited=100
  という3点で合意した。
- 設計方針:
  1. `recipe.py: cycleway_adjustment`を、現行の`cycleway_class`（3値）ではなく
     `classify_bicycle_infrastructure(tags, highway)`（6値）で判定するよう拡張する
     （引数へ`highway`を追加）。`cycleway_class`関数自体は撤去しない（SQL側の
     `cycleway_class`タイルプロパティ・T290で登録した同名材料は表示用途として
     引き続き独立に使われる）。
  2. `RoadSuitabilityRecipe`の補正フィールドを3値（track/lane/shared）→5値
     （separated/lane/shared_busway/shared_pedestrian/roadway）へ拡張する。
     `prohibited`は0次ハードフィルタ（`no_bicycle`）で通常除外されるため補正
     フィールドを持たない。
  3. ユーザー提示の0-100スケールを、既存のhighway基準値（1-5スケール）への
     加減算レンジへ線形変換する: `adjustment = round(score/100 × 4 − 2)`
     （現状のtrack=-2・lane=-1という実績値をレンジの両端に対応させる変換式）。
     結果: separated=**-2**（現状track相当・変更なし）・lane=**-1**（変更なし）・
     shared_busway=**0**（現状-1から変更）・shared_pedestrian=**0**（新規）・
     roadway=**+1**（新規）。**shared_buswayの挙動が変わる既存挙動変更**である点に
     注意（T240等の「安全側ロールアウト」原則とは異なり、今回はユーザー自身が
     再定義を求めているため意図的な変更）。
  4. `domain/traffic.py: car_stress_breakdown`の`lanes_low_threshold`抑制条件
     （現状`cycleway_class(tags) == "track"`）を`classify_bicycle_infrastructure(tags,
     highway) == "separated"`へ変更する（フロントの`cyclewayIsTrack`判定と対で変更）。
     内訳表示（`CarStressBreakdown`）のingredientキーも`bicycle_infra`ベースへ
     更新する。
  5. **frontend**: `recipeExpression.ts: cyclewayAdjustmentExpr`を、タイルの
     `bicycle_infra`プロパティ（T290で既に焼き込み済み）を読む6値`match`式へ
     書き換える。`carStressExpression.ts`の`cyclewayIsTrack`判定も対で変更。
     `RoadSuitabilityRecipePanel.tsx`（研究モードのレシピ調整UI）をフィールド変更へ
     追従。
- 影響範囲（調査済み、着手前の網羅確認）: backend
  `domain/recipe.py`・`domain/traffic.py`・`api/routers/routes.py`（Override
  モデルのフィールド変更）／frontend `recipeExpression.ts`・
  `carStressExpression.ts`・`recipeBreakdownPopup.ts`・
  `RoadSuitabilityRecipePanel.tsx`／テスト`test_recipe.py`・`test_traffic.py`・
  `test_evaluation*.py`・`test_measure_axis_stats.py`・`test_routes_generate.py`・
  `carStressExpression.test.ts`・`RoadSuitabilityRecipePanel.test.tsx`・
  `CarStressRecipePanel.test.tsx`・`ComparisonPanel.test.tsx`。
- 完了条件: 上記全ファイルの更新、backend/frontend全テストgreen（挙動変更を伴う
  既存テストの期待値更新を含む）、OpenAPI生成物ドリフトなし、実機確認（Playwright、
  区間クリック内訳表示・研究モードのレシピ調整UI・地図の色分け表示）。
  docs/architecture.md追従。

## 残タスクの優先順位（2026-08-24再整理・第18版）

第17版以降、**T263残作業（Render backendの停止）が完了した**。並行稼働期間は当初想定の
1日間より短い約1時間強だったが、ユーザー判断により前倒しで停止を実施。その過程で、
Render固有の自動注入環境変数`RENDER_GIT_COMMIT`に依存していたデプロイ確認機構
（`/health`のcommit）がbackend側だけ恒久的に`null`化する回帰を発見し、
`GIT_COMMIT`（deploy-backend.ymlが`git rev-parse HEAD`で明示注入）へ切り替えて修正した
（T263本文「残作業」参照）。指示待ちだった項目が無くなったため、指示待ちリストは
現在空。

**第18版への追記（2026-08-24・目論見書承認）**: 二画面構想の目論見書がユーザー承認され、
T266に加えT267〜T273の7タスクを正式起票した（上記「目論見書による二画面構想の正式化」
セクション参照）。着手順序はPhase順（T266→T267がPhase 1、T268・T269→T270がPhase 2、
T271・T272がPhase 3、T273がPhase 4=トリガー待ち）。**同日中にPhase 1（T266・T267）に続き
Phase 2の前提2件（T268・T269）も実装・完了した**。T268: 材料の排他帰属チェックを
`registry.py`から計算系レジストリ（`AXIS_DEFINITIONS`）へ移植。T269: 軸カタログを
`GET /api/axis-catalog`（新規公開API、`AxisDefinition`へlabel/description/category追加、
migration 0015）経由でDBの内容に追従させ、`RouteSettingsPanel`を静的`axis-catalog.json`
依存から切り離した（調査の結果、当初想定と異なり`axis-catalog.json`は`registry.py`
（DB化されていない別レジストリ）由来と判明し、方針を修正した経緯は実装メモ参照）。
backend全1149件・フロントtsc/vitest 516件green、実機確認済み。
**残るPhase 2はT270（軸スタジオ本体、独立URL管理画面）のみ**。

**第18版への追記2（2026-08-24）**: 同日中にPhase 2〜4が以下のとおり進んだ。
Phase 2: T270（軸スタジオ本体）完了、続けてT276（registry.py↔AXIS_DEFINITIONS
ラベル統合）・T277（材料カタログのbackend正式レジストリ化）・T278（地図表示ルール
kind=rampの自動導出、軸集合の同期）を追加着手・完了した——**T278でnight軸が
自動導出のrampレイヤーを持つようになったため、下記「トリガー未到達」リストの
T145a（night軸レイヤー、litタグデータの充実待ち）は解消済み**。Phase 3:
T271（軸の公開フローと統治ルール、is_published導入）・T272（管理画面の権限制御、
HTTP Basic認証）を完了し、**目論見書の二画面構想はPhase 1〜3すべて完了**。
残るはPhase 4のT273（一般UIの軸カタログ縮退、トリガー待ちの継続タスク）のみ。
副次的にT275（Tailwind CSSの要否判断）も起票済み（未着手）。

**第18版への追記3（2026-08-24・全体最適レビュー第8回の起票）**: 全ソースコード・DB設計を
ゼロから再読した総合診断レビュー（対象`fc7bd5a`、総合83/100、詳細は
`.claude/commands/review/history/2026-08-24_overall.md`）の指摘をT279〜T288の10件として
起票した（上記「全体最適レビュー第8回の起票」セクション参照）。即時実施可能なのは
**T279（P1・OpenAPIドリフト解消、唯一の実害ある欠陥）**・T281段階1（依存DAG文書化、S）・
T282（ファサード再検討の判断記録、S）の3件で、着手順はT279を最優先とする。
T280（材料供給の1本道短縮）はレビューの最重要提言であり、**次に軸・材料関連の要望が
出た際は軸スタジオのUI拡張より先に実施する**という順序制約ごと記録した。

- **参考記録（対応は不要〜任意、監視のみ）**:
  - T241で見つかった一部方位での「経路が見つからない」事象（8方位中平均1〜2方位）は
    残存するが、実運用への影響は限定的と評価済み（T241本文参照）。

- **トリガー未到達（現時点では着手しない）**:
  1. **T265**（冷パスの体験設計: バックグラウンドウォームアップ・事前split・進捗表示、
     規模M〜L）: T248から切り出し。一般公開の意思決定、または研究利用での冷パス体感
     遅延に関する具体的な要望・報告で着手。T259の「完全な失敗」自体は解消済みのため、
     T248時点にあった緊急性は無い。
  2. **T206**（積雪・凍結、規模S〜M）: 冬季前=11月。季節トリガーの到達が最も近い。
  3. ~~T145a（night軸レイヤー、規模S〜M）: litタグデータの充実待ち~~ →
     **2026-08-24、T278で解消**。night軸は材料（no_lit/has_tunnel）がタイル焼き込み
     済みのため、litタグの疎密に関わらず自動導出のrampレイヤーとして表示できるように
     なった（litタグデータ自体の充実は引き続き別問題として残るが、レイヤーの有無を
     それに依存させる必要が無くなった）。
  4. **T105**（バックエンド到達不能の原因特定、規模S〜M）: 次回の再現報告待ち。
  5. **T127**（全国データ取込の検証、規模不明）: 全国展開の意思決定待ち。
  6. **T145**（レイヤーパネルのレジストリ駆動化・三次レイヤー、規模L）: 裁量待ち。
  7. **T207**（CAPE延長予報、規模S）: 利用実績・要望待ち。
  8. **T208**（視程・霧調査、規模S）: 利用報告待ち。
  9. **T242残課題**（標高バックフィルの定期自動実行、規模S〜M・要スケジューリング基盤新設）:
     新規split頻度の増加、または標高データ欠損に起因する体感的な品質劣化の報告で着手。
     T281段階3（鮮度台帳）と関連するため着手時に統合を検討。
  10. **T280**（材料供給の1本道短縮、規模M〜L）: 次の軸・材料関連の実装要望で着手
      （軸スタジオUI拡張より先、という順序制約付き）。
  11. **T281段階2〜3**（統合エントリポイントバッチ・鮮度台帳、規模M）: 段階2は次回の
      データ投入・エリア拡大作業時、段階3は同クラス障害の再発またはT127。
  12. **T283**（`road_graph_use_repository`の名称・既定値再考、規模S）: 次のconfig.py
      変更のついで、または新環境構築時。
  13. **T284**（page.tsx分割方針の事前確認、規模S・判断のみ）: 次のUI機能着手前。
      実測1,773行/閾値1,900・state 36件/閾値40で発火目前。
  14. **T285**（表示系レジストリ縮退・軸カタログのランタイム一本化、規模M〜L）:
      T280完了後、またはGUI作成軸の地図表示要望。
  15. **T286**（architecture.md経緯追い出し第2弾、規模M）: 次の大きな設計転換時、
      またはユーザーの整理指示。
  16. **T287**（text型PKの再評価、規模S・調査のみ）: T127の意思決定時に容量試算へ含める。
  17. **T288**（AXIS_DEFINITIONSのマルチワーカー対応、規模S〜M）: 複数ワーカー構成の
      採用時（複数ワーカー化タスクの完了条件に含めること）。

いずれもトリガー未到達の実装を「ついで」にやらない（設計原則10）。

**サマリ（第8回レビュー起票後・19タスク）**: **T279・T289は2026-08-24に完了**
（T289は当初T280の実証候補として着手したが、調査の結果MATERIAL_CATALOG対象外の
一次属性追加パターンと判明し独立タスクとして完了、T280自体はトリガー待ちのまま）。
残る即時実施可能2件（T281段階1・T282。いずれも2026-08-24の全体最適レビュー第8回起票、
ユーザー承認済み）／
トリガー未到達16件（T265・T206・T105・T127・T145・T207・T208・T242残課題・
T280・T281段階2〜3・T283〜T288。T145aはT278で解消済みのため除外）／
このほかT275（Tailwind採否）・T273（Phase 4蒸留）・T274（逆回り候補）が着手待ち。T209・T223・T241は調査完了・T242本体（migration 0013適用・
標高バックフィル初回実行）・T243〜T249・T251〜T254・T256〜T259・T261〜T264・
**T248・T263（残作業含む）**は実装/調査完了・T255はDynamicLayerTimeSlider完了
（ホイール操作は実機確認済み）・BottomSheetは断念で完了扱い・T229はT248へ統合クローズ・
T221はPart 3（Stage D）まで実装完了（Stage Eは別タスクとして起票予定）のため、いずれも
本リストから外した。安全網の回復3件（T225・T224・T230）とレビュー指摘の消化5件
（T226〜T228・T231・T232）、およびT222（Overpassライブ経路削除）は全て完了済み。
T258で追加したデバッグログはT105の次回再現時の切り分け材料になる想定だが、T105自体は
トリガー未到達のまま残る。T259（20km失敗の根本原因特定）は調査として完了し、その結果は
T261の本番クラッシュ調査・T263（Oracle VM移行）という一連の対応につながった。
**T248候補1（バルクUPSERTのCOPY化）は一時的に切り戻したが、原因ではないと確定したため
`git revert`のrevertで再導入し、現在も本番で稼働中（詳細はT248候補1・T263参照）**。
**T248は2026-08-24に完了し、未着手のまま残っていた冷パスの体験設計（バックグラウンド
ウォームアップ等）はT265へ切り出してトリガー未到達リストへ移した。T263は同日、
Render backendの停止とデプロイ確認機構の修正をもって残作業を含め完了した。**

---

完了タスクの日付別一覧は[docs/improvement-plan-archive/README.md](improvement-plan-archive/README.md)を参照
（2026-08-23棚卸で完了タスクの実施記録は全件アーカイブへ移設済み。本体はオープンタスクのみ）。
