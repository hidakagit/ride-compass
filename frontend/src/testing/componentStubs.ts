import { useLayoutEffect, useState, type ReactNode } from "react";

/**
 * 子の部品の代役（`vi.mock`の工場）と、代役が受け取ったpropsの記録。
 *
 * 代役は受け取ったpropsを名前で記録し、`children`を描くだけで、子の振る舞いを真似ない。
 * 記録は描かれている間だけ引け、外れると消える。
 *
 * `vi.mock`はimportより先へ巻き上げられるため、テストはこのモジュールを
 * `await vi.hoisted(() => import("@/testing/componentStubs"))`で取り、`vi.mock`の前に置く。
 */
type Props = Record<string, unknown>;

const mounted = new Map<string, { token: object; props: Props }>();

/**
 * propsを`name`で記録する代役。`name`をpropsから決めると、同じ部品の別の描き方を分けて引ける。
 * 渡されたノードを描く形が要るときだけ`draw`を渡す。
 */
export function stubComponent(
  name: string | ((props: Props) => string),
  draw: (props: Props) => ReactNode = (props) => props.children as ReactNode,
) {
  const nameOf = typeof name === "string" ? () => name : name;
  return function Stub(props: Props) {
    const [token] = useState(() => ({}));
    const key = nameOf(props);
    useLayoutEffect(() => {
      mounted.set(key, { token, props });
    });
    useLayoutEffect(
      () => () => {
        if (mounted.get(key)?.token === token) mounted.delete(key);
      },
      [key, token],
    );
    return draw(props);
  };
}

/** 既定の書き出しを代役に差し替える`vi.mock`の工場。 */
export function stubModule(name: string) {
  return async () => ({ default: stubComponent(name) });
}

export function isStubMounted(name: string): boolean {
  return mounted.has(name);
}

/** `name`の代役が最後に受け取ったprops。描かれていなければ投げる。 */
export function stubProps<P = Props>(name: string): P {
  const entry = mounted.get(name);
  if (!entry) throw new Error(`${name}が描かれていない`);
  return entry.props as P;
}
