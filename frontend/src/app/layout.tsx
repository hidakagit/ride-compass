import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "RideCompass",
  description: "ロードバイク向け周回ルート生成アプリ（プロトタイプ）",
};

// viewport meta（width=device-width）が無いと、スマホブラウザは既定の仮想ビューポート
// （多くは980px幅）でレイアウトを解釈してからページ全体を縮小表示する。この場合
// globals.cssの@media (max-width: 640px)が実デバイス幅ではなくその仮想980px基準で
// 評価されるため、スマホ実機で常にfalseとなりサイドバーのドロワー化（position:fixed）が
// 一切発動せず、サイドバーが通常のflexアイテムとして幅を占有し地図が右へ押しやられる
// レイアウト崩れが実機でのみ発生していた（実機スクリーンショットで確認）。
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
