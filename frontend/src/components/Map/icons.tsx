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

/** 道路情報: 消失点へ向かう道路と車線の破線 */
export function RoadIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} {...svgProps}>
      <path d="M7 2 3 18M13 2l4 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M10 5v2M10 9.3v2M10 13.6v2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** 交通ストレス: 注意喚起の三角＋感嘆符 */
export function TrafficStressIcon({ size = 16 }: IconProps) {
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
