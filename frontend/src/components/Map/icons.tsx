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

/** 二次軸rampレイヤー（改善計画T145b）の共通アイコン: 密度の濃淡を表す棒グラフ。
 * 軸はレジストリ生成物から自動で増えるため、軸ごとの専用アイコンは持たず全ramp軸で共用する */
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

/** 道路の種類（改善計画T165で「道路情報」から論理分割）: 消失点へ向かう道路と車線の破線 */
export function RoadIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M7 2 3 18M13 2l4 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M10 5v2M10 9.3v2M10 13.6v2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 路面の種類（改善計画T165で「道路情報」から論理分割）: 材質のテクスチャを表す帯+点の並び */
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

/** 自転車インフラ: 二輪と車体を表す最小限の自転車シルエット */
export function BicycleInfraIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="5" cy="14.5" r="2.7" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="15" cy="14.5" r="2.7" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M5 14.5 9.5 6.5h2.5l3 8M9.5 6.5 7 11.2h6.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
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

/** 補給・休憩ポイント（改善計画T101）: 買い物袋のシルエット */
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

/** システム状況: バージョン/稼働状況の確認を表す情報アイコン（円＋i） */
export function StatusIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="10" cy="6.6" r="0.9" fill="currentColor" />
      <path d="M10 9.4v5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 補足説明: ラベル横に添える汎用の情報アイコン（円＋i）。StatusIconと同形だが、
 * 「システム状況ボタン」ではなく「hoverで詳細を出す補足」という別用途のため名前を分ける。 */
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

/** 研究（モバイル下部タブ）: パラメータ調整の実験を表すフラスコ */
export function ResearchIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path
        d="M8 2.5h4M8.5 2.5V7L3.5 17h13L11.5 7V2.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M5.5 13h9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

/** 開発者（モバイル下部タブ）: コードを表す山カッコ「&lt; &gt;」 */
export function DeveloperIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M7 5 2 10l5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13 5l5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
