import type { CaptureScript } from "../context";

// 脚本の例: 気象庁の降水のタイルを、作業ツリーの backend の中継が返したもので撮る（中継の塗り方を変えた変更の後の画面）。
// 前は本番の画面で、後は気象庁のタイルの中継だけを作業ツリーの backend に返させて、同じ脚本で撮る。
//   node frontend/scripts/capture.mjs --app production --script frontend/capture/examples/jma-precipitation.ts
//   node frontend/scripts/capture.mjs --api <本番の backend> --backend /api/jma-tile/ --script frontend/capture/examples/jma-precipitation.ts

const script: CaptureScript = async ({ open, shot }) => {
  await open({ point: { latitude: 35.681, longitude: 139.767 }, zoom: 7, layers: ["precipitationNowcast"] });
  await shot("降水");
};

export default script;
