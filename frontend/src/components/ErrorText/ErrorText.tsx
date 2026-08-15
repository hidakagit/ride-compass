import styles from "./ErrorText.module.css";

// 入力エラー・操作エラーの共通表示（role=alert・操作した箇所の直下に置く原則）。
// 以前はRouteForm/LocationControlが同じインラインスタイルを重複コピーしていた（T30で統一）。
export default function ErrorText({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className={styles.error}>
      {children}
    </p>
  );
}
