// 地図上のアイコンボタン（MapOverlayControls）で使う自作SVGアイコン集。
// 外部アイコンライブラリは使わず、既存の現在地アイコン（page.tsx）と同じ線画スタイル
// （stroke=currentColor、丸端、フォント非依存）に揃えている。
// サイズは呼び出し側のCSSで決まる（デフォルトは16px）ため、ここでは形だけを定義する。

interface IconProps {
  size?: number;
}

const svgProps = {
  viewBox: "0 0 20 20",
  fill: "none" as const,
  "aria-hidden": true as const,
};

/** 標高図: 色別標高図のイメージに合わせた山並みのシルエット */
export function ElevationIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M1.5 15.5 6 8l3 3.5 2.5-4 5.5 8H1.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 二次軸rampレイヤーの汎用フォールバック: 密度の濃淡を表す棒グラフ。各軸は`icon_id`
 * （軸自身のデータ）でaxisIconPalette.tsxの固定パレットから専用アイコンを選べる。
 * この汎用形はicon_id未設定の軸（まだ専用アイコンを選んでいないramp軸・単独チップ）
 * 向けのフォールバックとして残す。 */
export function AxisRampIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M3.5 16.5v-4M8 16.5v-7M12.5 16.5V6M17 16.5V3.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 勾配（推定軸）: 地面から立ち上がる傾斜線+矢頭。標高図（ElevationIcon、山並みの
 * シルエット）は生の標高そのものを表すのに対し、こちらは傾き（変化率）という別概念を表す
 * ため意匠を分ける。 */
export function GradientAxisIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M2.5 16.5h15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M3.5 16.5 13.5 5.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M9.5 5.5h4v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** 舗装質（推定軸）: 路面の滑らかさ/粗さを表す波線。路面の種類（RoadSurfaceIcon、材質の
 * テクスチャを表す帯+点）は観測データ（種別の分類）、こちらは推定指標（質のスコア）という
 * 別概念を表すため意匠を分ける。 */
export function SurfaceQualityAxisIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M2 14c1.8-3.4 3.6-3.4 5.4 0s3.6 3.4 5.4 0 3.6-3.4 5.4 0"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** 夜間（推定軸）: 三日月のシルエット */
export function NightAxisIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M17.5 10.66A7.5 7.5 0 1 1 9.34 2.5 5.83 5.83 0 0 0 17.5 10.66Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 停止密度（推定軸）: 縦に積み重なり下ほど大きくなる点で、停止要因の集積を表す。
 * 停止要因（StopPoiIcon、信号機のシルエット）は観測データ（個々の要因の種類）、こちらは
 * 推定指標（密度）という別概念を表すため意匠を分ける。 */
export function StopDensityAxisIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="4.6" r="1.3" fill="currentColor" />
      <circle cx="10" cy="9.6" r="1.9" fill="currentColor" />
      <circle cx="10" cy="15.4" r="2.6" fill="currentColor" />
    </svg>
  );
}

/** 事故密度（推定軸）: 大小不揃いに散らばる点の集まりで、集積（ヒートマップ）を表す。
 * 事故（AccidentIcon、単一の衝突バースト）は観測データ（個々の事故地点）、こちらは
 * 推定指標（密度）という別概念を表すため意匠を分ける。停止密度（StopDensityAxisIcon）とは
 * 縦一列の整列 vs 不規則な散らばりで区別する。 */
export function AccidentDensityAxisIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="5.5" cy="13.5" r="1.6" fill="currentColor" />
      <circle cx="11" cy="7" r="2.3" fill="currentColor" />
      <circle cx="15.5" cy="14.5" r="1.3" fill="currentColor" />
      <circle cx="8" cy="16.3" r="1" fill="currentColor" />
    </svg>
  );
}

/** 道路の種類（「道路情報」から論理分割した1軸）: 消失点へ向かう道路と車線の破線 */
export function RoadIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M7 2 3 18M13 2l4 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M10 5v2M10 9.3v2M10 13.6v2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 路面の種類（「道路情報」から論理分割した1軸）: 材質のテクスチャを表す帯+点の並び */
export function RoadSurfaceIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <rect x="2.5" y="6" width="15" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="6" cy="8.6" r="0.9" fill="currentColor" />
      <circle cx="10" cy="11.4" r="0.9" fill="currentColor" />
      <circle cx="14" cy="8.6" r="0.9" fill="currentColor" />
      <circle cx="6.5" cy="11.6" r="0.7" fill="currentColor" />
      <circle cx="14" cy="11.6" r="0.7" fill="currentColor" />
    </svg>
  );
}

/** 車ストレス: 注意喚起の三角＋感嘆符 */
export function CarStressIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M10 2 18.5 17H1.5L10 2Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M10 8v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="10" cy="14.4" r="0.9" fill="currentColor" />
    </svg>
  );
}

/** 指定路線（外部静的データソース T51、緊急輸送道路・重要物流道路）: 道路標識風の盾形 */
export function DesignationIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M10 2 17 4.5v5.2c0 4.4-3 7.2-7 8.3-4-1.1-7-3.9-7-8.3V4.5L10 2Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** トンネル（一次属性、OSMのtunnelタグ）: 山を貫くアーチ型の坑口 */
export function TunnelIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M3 17V9a7 7 0 0 1 14 0v8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3 17h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 一方通行（一次属性、OSM onewayタグ）: 一方向の矢印 */
export function OnewayIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M3 10h13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path
        d="M12 5.5 17 10l-5 4.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

/** 事故（外部静的データソース T50）: 衝突を示す星形バースト */
export function AccidentIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M10 1.5v5M10 13.5v5M1.5 10h5M13.5 10h5M4 4l3.5 3.5M16 4l-3.5 3.5M4 16l3.5-3.5M16 16l-3.5-3.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="10" cy="10" r="2.3" fill="currentColor" />
    </svg>
  );
}

/** 停止要因: 信号機のシルエット（3灯） */
export function StopPoiIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <rect x="7" y="2" width="6" height="13" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="10" cy="5.3" r="1" fill="currentColor" />
      <circle cx="10" cy="8.5" r="1" fill="currentColor" />
      <circle cx="10" cy="11.7" r="1" fill="currentColor" />
      <path d="M10 15v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** 補給・休憩ポイント: 買い物袋のシルエット */
export function SupplyPoiIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M5 7h10l-1 10a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1L5 7Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M7.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** 観測データ（地図チップ最上位グループ）: 生データをそのまま見る目=虫眼鏡 */
export function ObservedDataIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12.5 12.5 17.5 17.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 推定指標（合成）（地図チップ最上位グループ）: 複数要因を合成した値=メーター */
export function EstimatedIndexIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M2.5 14.5a7.5 7.5 0 0 1 15 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M10 14.5 13.8 8.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="10" cy="14.5" r="1.1" fill="currentColor" />
    </svg>
  );
}

/** 動的データ（地図チップ最上位グループ）: 時刻で変わることを表す時計 */
export function DynamicDataIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="10" r="7.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M10 5.6V10l3.2 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** 環境（地図チップ最上位グループ）: 標高（terrain）・降水/風/雷等（weather）をまとめて
 * 表す雲のシルエット。DynamicDataIcon（時計）はweatherの時刻依存性を象徴する別アイコンで、
 * こちらはterrain（標高）も含む広い「屋外環境」グループを表す。 */
export function EnvironmentDataIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M6 15a3.3 3.3 0 0 1 .4-6.58A4.6 4.6 0 0 1 15.3 9.6 3 3 0 0 1 14.7 15H6Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** スポット（地図チップ最上位グループ）: 停止要因・補給・事故等の点データを
 * まとめて表す地図ピンのシルエット。 */
export function SpotDataIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M10 18s6-6.7 6-11a6 6 0 0 0-12 0c0 4.3 6 11 6 11Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="7" r="1.8" fill="currentColor" />
    </svg>
  );
}

/** ルート: 起点・終点のドットと曲がりくねった経路 */
export function RouteIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M3.5 16c2.8-1 2.8-5.2 6-6s3.2-5.2 6-6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeDasharray="0.2 3"
      />
      <circle cx="3.5" cy="16" r="1.6" fill="currentColor" />
      <circle cx="15.5" cy="4" r="1.6" fill="currentColor" />
    </svg>
  );
}

/** ログ: 記録済みの行を表す簡易ターミナル/リスト */
export function LogIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <rect x="2" y="2.5" width="16" height="15" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M5 7h10M5 10.2h10M5 13.4h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

/** 風（天候ヘッダ T57）: 渦を巻く気流を表す3本の曲線 */
export function WindIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M2 6.5h11a2.5 2.5 0 1 0-2.2-3.7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M2 10.5h14.5a2.5 2.5 0 1 1-2.2 3.7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M2 14.5h8a2 2 0 1 1-1.8 2.9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 風向（天候ヘッダのスマホ1行化）: まっすぐな矢印。呼び出し側がwind_direction_degぶん
 * 回転させて使う（回転前提のため、渦を巻くWindIconと違い上向き固定の単純な矢印にしてある）。 */
export function WindDirectionArrowIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M10 2v14M10 2 5 8M10 2l5 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** 気温（天候ヘッダ T61）: 温度計 */
export function ThermometerIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M9 3.2v8.75a3 3 0 1 0 2 0V3.2a1 1 0 0 0-2 0Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx="10" cy="15" r="1.2" fill="currentColor" />
    </svg>
  );
}

/** 降水確率（天候ヘッダ T61）: 雨粒 */
export function RaindropIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M10 2.8C7.2 7 4.8 10.2 4.8 12.8a5.2 5.2 0 0 0 10.4 0C15.2 10.2 12.8 7 10 2.8Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 雷ナウキャスト（地図チップ）: 雷雲から伸びる稲妻 */
export function ThunderIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M6 8.5a4 4 0 0 1 7.6-1.7A3.2 3.2 0 0 1 13 13H6.5a3.5 3.5 0 0 1-.5-6.95"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <path d="M10.5 12 8 16.5h2.6L9.5 20l4-6h-2.6L12.5 12Z" fill="currentColor" />
    </svg>
  );
}

/** UV指数（天候ヘッダ）: 太陽 */
export function SunIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="10" r="3.6" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M10 2.5v2.2M10 15.3v2.2M17.5 10h-2.2M4.7 10H2.5M15.3 4.7l-1.6 1.6M6.3 13.7l-1.6 1.6M15.3 15.3l-1.6-1.6M6.3 6.3 4.7 4.7"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 天気アイコン（天候ヘッダ）: 夜間の快晴。三日月 */
export function MoonIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M17.4 10.6A7.4 7.4 0 1 1 9.3 2.5 5.8 5.8 0 0 0 17.4 10.6Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 天気アイコン（天候ヘッダ）: くもり。丸みを帯びた雲のシルエット */
export function CloudIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M6.3 14.6a3.3 3.3 0 0 1 .4-6.6 4.3 4.3 0 0 1 8.1-1.3 3.6 3.6 0 0 1-.4 7.9H6.3Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 天気アイコン（天候ヘッダ）: 霧。視界不良を表す水平線3本 */
export function FogIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M3 7h11M3 10.2h14M3 13.4h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 天気アイコン（天候ヘッダ）: 雪。3本の直径が交差する結晶 */
export function SnowflakeIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M10 3v14M4.5 6.5l11 7M15.5 6.5l-11 7"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 全レイヤー一括OFF: 丸で囲んだバツ印（「クリア」の意味、地図上のチップ一括OFF用） */
export function ClearAllLayersIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M7.3 7.3 12.7 12.7M12.7 7.3 7.3 12.7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 補足説明: ラベル横に添える汎用の情報アイコン（円＋i、hoverで詳細を出す補足用途）。 */
export function InfoIcon({ size = 14 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="10" cy="6.6" r="0.9" fill="currentColor" />
      <path d="M10 9.4v5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 地図の見え方（モバイル下部タブ）: 積み重なったレイヤーを表す菱形+2本の折れ線 */
export function MapAppearanceIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M10 2.5 17.5 7 10 11.5 2.5 7 10 2.5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M2.5 10.8 10 15.3 17.5 10.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2.5 14.3 10 18.8 17.5 14.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** ルート設定（モバイル下部タブ）: 高さ違いのスライダー3本 */
export function RouteSettingsIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="7" cy="6" r="1.8" fill="currentColor" />
      <circle cx="13" cy="10" r="1.8" fill="currentColor" />
      <circle cx="9" cy="14" r="1.8" fill="currentColor" />
    </svg>
  );
}

// --- 軸スタジオの地図チップアイコン選択パレット向け、汎用ピクトグラム ---
// 既存の軸専用アイコン（勾配=GradientAxisIcon等）に加え、新規作成した軸がすぐ選べる
// スペアをあらかじめ用意しておく。既存アイコンと同じ線画スタイル（stroke=currentColor、
// 丸端、塗りなし基調）に揃える。新しい意匠の追加は引き続きコード変更を要する
// （axisIconPalette.tsx参照、GUIからの任意SVG登録はしない）。

/** 盾（安全・保護の概念向け）: 縦の盾形シルエット */
export function ShieldIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M10 2.5 16.5 5v5c0 4.2-2.9 6.8-6.5 7.5-3.6-.7-6.5-3.3-6.5-7.5V5L10 2.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 的（精度・命中の概念向け）: 同心円3つ */
export function TargetIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="10" cy="10" r="4" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="10" cy="10" r="1.2" fill="currentColor" />
    </svg>
  );
}

/** 時計（時間・スケジュールの概念向け）: 円+短針長針 */
export function ClockIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M10 6v4.2l3 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** 積層（複数材料の合成・複合指標の概念向け）: ずらして重ねた3枚のひし形 */
export function LayersStackIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M10 3 17 7.5 10 12 3 7.5 10 3Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <path d="M3 11 10 15.5 17 11" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** メニュー起動（HeaderMenu.tsx）: 縦3点（ケバブメニュー）の一般的な「その他の操作」
 * アフォーダンス。RouteSettingsIcon（横線+丸、スライダーの見た目）とは意味が異なる
 * ため区別する。 */
export function MenuIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="5" r="1.5" fill="currentColor" />
      <circle cx="10" cy="10" r="1.5" fill="currentColor" />
      <circle cx="10" cy="15" r="1.5" fill="currentColor" />
    </svg>
  );
}

// ルート結果ヘッダの操作枠（保存・GPX出力）。機能実装まではdisabledの占位として使う。
export function SaveIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M4 3h9l3 3v11H4z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M7 3v4h5V3M7 17v-5h6v5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

export function DownloadIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M10 3v9m0 0-3.5-3.5M10 12l3.5-3.5M4 15v2h12v-2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
