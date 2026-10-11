// 表示中の結果について注意を促す1行（条件のずれ・補正・欠けたデータ）。誤り（`ErrorText`）と違い、操作を止めない。
export default function WarningText({ children }: { children: React.ReactNode }) {
  return <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">{children}</p>;
}
