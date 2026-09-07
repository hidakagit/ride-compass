import { vi } from "vitest";

/**
 * Embla Carouselがマウント時に無条件で呼ぶブラウザAPIを、DOM環境へ用意する。
 *
 * happy-dom/jsdomはmatchMedia・IntersectionObserver・ResizeObserverのいずれも
 * 実装しない。Emblaはbreakpoints機能でmatchMediaを、slidesInView検出で
 * IntersectionObserverを、寸法追従でResizeObserverを初期化処理の中で呼ぶため、
 * 用意しないとマウント時に例外になる。DynamicLayerTimeSliderを描画するテストの
 * `beforeEach`から呼ぶ。
 */
export function stubEmblaBrowserApis() {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    media: "",
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  } as unknown as MediaQueryList);

  class IntersectionObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    takeRecords = vi.fn(() => []);
  }
  window.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver;

  class ResizeObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  }
  window.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
}
