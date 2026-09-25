import { forwardRef } from "react";
import { cn } from "@/lib/cn";

// 入力欄（1行・複数行・選択）の見た目。3つとも同じ枠・大きさ・フォーカスの輪を持つ。
export const controlClass = cn(
  "rounded-sm border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 py-1",
  "text-[length:var(--font-size-md)] text-[var(--foreground)]",
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]",
  "read-only:bg-[var(--color-surface-2)] read-only:text-[var(--color-muted)] disabled:opacity-50",
);

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={cn(controlClass, className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return <textarea ref={ref} className={cn(controlClass, className)} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, ...props },
  ref,
) {
  return <select ref={ref} className={cn(controlClass, className)} {...props} />;
});

/** 入力欄と、その上に置く名前を縦に並べる。 */
export const fieldClass = "flex min-w-0 flex-col gap-0.5 text-[length:var(--font-size-sm)] text-[var(--color-muted)]";
