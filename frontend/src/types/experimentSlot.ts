import type { GenerationConditions, RouteCandidate } from "@/types/route";

// フロントの実験スロット（研究インターフェース改善 §10-3）。直近の生成結果を条件付きで
// 2〜3件保持し、地図への重ね描き・メトリクス表での並置比較に使う。保存はメモリ内のみ
// （リロードで消えてよい、永続化はDEFER）。
export interface ExperimentSlot {
  id: string;
  color: string;
  conditions: GenerationConditions;
  engine: string;
  // 比較の代表候補。生成直後にoverall_difficulty昇順の先頭（=デフォルト選択候補）で固定する。
  // 以降ユーザーがRouteListで別候補を選び直しても、過去スロットの比較対象は変えない
  // （「生成結果のスナップショット」として扱う）。
  topCandidate: RouteCandidate;
}

// 最新3スロットまで保持（研究インターフェース改善 §10-3、多すぎると地図が輻輳するため）。
export const MAX_EXPERIMENT_SLOTS = 3;

// route-candidates-line（選択#2563eb/未選択#64748b）・selected-outline（#1e3a8a）と
// 重ならない寒色以外の配色にして、スロット重ね描きを既存のルート表示と区別できるようにする。
export const EXPERIMENT_SLOT_COLORS = ["#16a34a", "#ea580c", "#9333ea"] as const;
