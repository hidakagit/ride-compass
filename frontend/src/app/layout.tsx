import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { paletteCssText } from "@/lib/paletteCssVariables";

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
  description: "ロードバイク向け周回ルート生成アプリ[プロトタイプ]",
};

// viewport meta（width=device-width）が無いと、スマホブラウザは既定の仮想ビューポート
// （多くは980px幅）でレイアウトを解釈してからページ全体を縮小表示する。この場合
// globals.cssの幅のメディアクエリが実デバイス幅ではなくその仮想幅で評価され、スマホでも
// モバイルの配置にならない（開発者ツールの端末の模擬では再現しないことがある）。
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja" className={`${geistSans.variable} ${geistMono.variable}`}>
      <head>
        <style>{paletteCssText()}</style>
      </head>
      <body>{children}</body>
    </html>
  );
}
