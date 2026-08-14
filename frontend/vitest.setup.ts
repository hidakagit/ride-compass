import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// test.globals(vitest.config.mts)を有効にしていないため、Testing Libraryの
// afterEach自動検出によるアンマウントが効かない。各テスト後に明示的にDOMを
// クリーンアップしないと、前のテストでrenderした要素が残ったまま次のテストが
// 実行され、getByRole等が意図しない古い要素まで拾ってしまう。
afterEach(() => {
  cleanup();
});
