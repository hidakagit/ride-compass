import { act } from "@testing-library/react";

/** 取りに行っていれば応答が届くだけの間をおく（取りに行かないこと・取り直さないことを確かめるため。届いた値を確かめる
 * ときは、その値が出るまで待つ。届くまでの時間は CI の負荷で変わる）。 */
export const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 50)));
