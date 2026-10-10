import {
  ORIGIN_MARK_COLOR,
  ORIGIN_MARK_FALLBACK_COLOR,
  PIN_MARK_BACKGROUND,
  PinMark,
} from "@/components/PinMark/PinMark";
import { cn } from "@/lib/cn";
import type { PinRole } from "@/types/route";

interface PointMarkProps {
  role: PinRole;
  /** 経由地の番号（地図のピンと同じ訪問の順）。 */
  label?: string;
  /** 出発地の印を、実際の位置（現在地か置いた地点）の色で出すか。 */
  originLocated: boolean;
  className?: string;
}

/** 地点の並びと詳しくに出す、地図のピンと同じ図形の丸。同じものを2度描くと、片方だけ直したときにピンと違う見た目になる。 */
export default function PointMark({ role, label, originLocated, className }: PointMarkProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex size-4.5 flex-none items-center justify-center rounded-full text-[0.7rem] text-white",
        className,
      )}
      style={{ background: PIN_MARK_BACKGROUND[role] }}
    >
      <PinMark
        role={role}
        label={label}
        size={13}
        color={originLocated ? ORIGIN_MARK_COLOR : ORIGIN_MARK_FALLBACK_COLOR}
      />
    </span>
  );
}
