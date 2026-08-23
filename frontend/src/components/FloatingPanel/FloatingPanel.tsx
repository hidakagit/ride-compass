"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Rnd } from "react-rnd";
import styles from "./FloatingPanel.module.css";

interface FloatingPanelProps {
  /** パネル自体の開閉。呼び出し側（DebugConsole/SystemStatusPanel）が個別に持つ状態 */
  open: boolean;
  onClose: () => void;
  title: string;
  /** ヘッダーの閉じるボタンより前に置く追加ボタン（クリア・更新など、パネルごとに異なる） */
  headerButtons?: ReactNode;
  children: ReactNode;
  /** 既定の上端位置（rem）。天候ヘッダの下から始まる高さに揃えるため既定4.25 */
  topRem?: number;
  /** 既定の幅（rem） */
  widthRem?: number;
  /** 本文の最大高さ（px）。これを超える分はbody内でスクロールする */
  maxHeightPx?: number;
}

// 一般ユーザーは使わない開発者向けパネル（デバッグログ・システム状況）の共通シェル。
// サイドバー/地図に場所を固定せず、ビューポート基準で浮かせた独立パネルにする
// （「設定」内のボタンから開閉、T43）。位置はヘッダーのつまみをドラッグして動かせる。
// 2パネルとも同じ挙動（ドラッグ・既定位置リセット・半透明の暗い配色）を必要としたため、
// DebugConsole単体だった実装をここへ切り出した（システム状況パネルの新設に伴う共通化）。
//
// ドラッグ位置管理は自前のpointerイベント実装からreact-rnd（Rnd）へ移行した（T253併用導入）。
// dragHandleClassNameでヘッダーのつまみ（.dragHandle）に限定してドラッグを効かせ、
// bounds="window"で画面外へドラッグして見失う（現行に無い改善）ことも防ぐ。リサイズは
// 従来どおり提供しないためenableResizing={false}。
//
// 幅（widthRem）自体は従来どおりCSS側の`min(widthRem, 100vw - 2*space-3)`で応答的に
// 決める（Rndのsize props経由の固定pxにはしない。ウィンドウ幅変更にも追従させたいため）。
// Rndはx/y（左上原点の絶対px）でしか位置指定できずCSSの`left:50%; transform:translateX(-50%)`
// のような相対中央寄せができないため、開いた直後にuseLayoutEffectで実際の描画幅を測って
// 中央寄せのx座標を計算しRndへ反映する（ペイント前に同期実行されるため、ズレた位置が
// 一瞬見える心配は無い）。
export default function FloatingPanel({
  open,
  onClose,
  title,
  headerButtons,
  children,
  topRem = 4.25,
  widthRem = 22,
  maxHeightPx = 420,
}: FloatingPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const rndRef = useRef<Rnd>(null);

  // !openの間はこのコンポーネント自体がnullを返しRnd/panelRefのDOMごと毎回アンマウントする
  // （下記参照）ため、openがfalse→trueになるたびにRndは新規マウントとなり、この
  // useLayoutEffectも毎回走る。これにより「開き直すたびに中央寄せへ戻す」従来の挙動
  // （ドラッグ位置は開いている間だけの一時的な配置、永続化しない）を再現できる。
  useLayoutEffect(() => {
    if (!open) return;
    const rnd = rndRef.current;
    const el = panelRef.current;
    if (!rnd || !el) return;
    const rootFontSizePx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const width = el.getBoundingClientRect().width;
    rnd.updatePosition({ x: Math.max(0, (window.innerWidth - width) / 2), y: topRem * rootFontSizePx });
  }, [open, topRem]);

  if (!open) return null;

  return (
    <Rnd
      ref={rndRef}
      default={{ x: 0, y: 0, width: "auto", height: "auto" }}
      bounds="window"
      enableResizing={false}
      dragHandleClassName={styles.dragHandle}
      // Rndの既定style（position:"absolute"）だとページスクロールに追従してしまうため、
      // 元のCSS（.panel { position: fixed }）と同じ「常にビューポート基準」の浮遊挙動を
      // 保つためfixedへ上書きする（Rnd内部でstyleは最後にspreadされ上書きできる）。
      style={{ position: "fixed", zIndex: 50 }}
    >
      {/* app-floating-panelはglobals.css側のモバイル向けタップ領域ルール
          （.app-sidebar button, .app-floating-panel button）が参照するグローバルなマーカー
          クラス。CSS Modulesのクラス名はハッシュ化されグローバルCSSから参照できないため、
          見た目自体はstyles.panelに任せつつ、このマーカークラスだけ併用している。 */}
      <div
        ref={panelRef}
        className={`${styles.panel} app-floating-panel`}
        style={{
          width: `min(${widthRem}rem, calc(100vw - 2 * var(--space-3)))`,
          maxHeight: `${maxHeightPx}px`,
        }}
      >
        <div className={styles.header}>
          <div className={styles.dragHandle} role="separator" aria-label="ドラッグしてパネルを移動" title="ドラッグして移動">
            ⠿
          </div>
          <strong className={styles.title}>{title}</strong>
          <div className={styles.headerButtons}>
            {headerButtons}
            <button type="button" onClick={onClose} aria-label={`${title}を閉じる`} className={styles.closeButton}>
              ✕
            </button>
          </div>
        </div>
        <div className={styles.body}>{children}</div>
      </div>
    </Rnd>
  );
}
