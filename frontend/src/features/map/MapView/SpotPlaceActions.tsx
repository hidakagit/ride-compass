"use client";

import PointMark from "@/components/PinMark/PointMark";
import { Button } from "@/components/ui/Button/Button";

/** 小窓から置ける役割（出発地は置かない——出発地は現在地か、決まった所に置いて行き先だけを試し直す）。 */
export type SpotPlaceRole = "waypoint" | "destination";

interface SpotPlaceActionsProps {
  /** 経由地が生成の受け付ける数まで置いてあるか。 */
  waypointsFull: boolean;
  onPlace: (role: SpotPlaceRole) => void;
}

/**
 * 名前のある点の小窓に出す、その点を経由地に足す・目的地にする操作。パネルの操作と同じアイコンだけの形で、印は地点の並びと
 * 地図のピンと同じ図形にする（足すのは並びの「＋」と同じ丸）。
 */
export default function SpotPlaceActions({ waypointsFull, onPlace }: SpotPlaceActionsProps) {
  return (
    <div className="mt-1.5 flex gap-1.5">
      <Button
        size="panelIcon"
        aria-label={waypointsFull ? "経由地は上限まで置いてあります" : "経由地に足す"}
        disabled={waypointsFull}
        onClick={() => onPlace("waypoint")}
        usage="この場所を、通る経由地の最後に足します。"
      >
        <PointMark role="waypoint" label="＋" originLocated />
      </Button>
      <Button
        size="panelIcon"
        aria-label="目的地にする"
        onClick={() => onPlace("destination")}
        usage="この場所を目的地にします。置いてあった目的地は置き換えます。"
      >
        <PointMark role="destination" originLocated />
      </Button>
    </div>
  );
}
