import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

// 入力エラー・操作エラーの共通表示（role=alert・操作した箇所の直下に置く原則）。
export default function ErrorText({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className={cn(textVariants({ variant: "error" }), "mt-1")}>
      {children}
    </p>
  );
}
