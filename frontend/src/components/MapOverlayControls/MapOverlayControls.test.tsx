import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapOverlayControls, { type OverlayLayerChip } from "./MapOverlayControls";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";

function baseLayers(): OverlayLayerChip[] {
  return [
    { id: "elevation", label: "標高図", on: false },
    { id: "roadSurface", label: "路面", on: false },
    { id: "route", label: "ルート", on: false },
  ];
}

function baseProps() {
  return {
    layers: baseLayers(),
    onToggle: vi.fn(),
    // 改善計画T308: secondaryAxesが実行時APIから取得したprops経由になったため、
    // 以前ここが直接importしていた静的SECONDARY_AXES（既存6軸）をそのまま既定値にする
    // （推定グループの内訳を検証する既存テストの挙動を変えないため）。
    secondaryAxes: SECONDARY_AXES,
  };
}

// 凡例・絞り込み編集・色分けモード選択などの「細かな設定」はすべてサイドバー側
// （MapLayersPanel.test.tsx）で検証する。ここは地図の上に残った最小限の要素
// （ON/OFFチップと▶で開く凡例パネル）だけを見る。このコンポーネントはレイヤー固有の
// 知識を持たない汎用描画係のため、テストもpropsで渡した表示状態の反映のみを確認する。
describe("MapOverlayControls", () => {
  // グループの開閉・表示項目の設定はlocalStorageへ永続化される（ユーザー要望「次開いた時に
  // 同じ状態にして」）。前のテストで書き込まれた値が次のテストの初期状態に漏れないよう、
  // 各テストの前に消し込む。
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("各チップがON状態をaria-pressedで反映する", () => {
    const layers = baseLayers().map((layer) => ({ ...layer, on: true }));
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.getByRole("button", { name: "標高図" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "路面" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "ルート" })).toHaveAttribute("aria-pressed", "true");
  });

  it("チップのクリックでonToggleがレイヤーIDと現在値の反転で呼ばれる", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const layers = baseLayers();
    layers[1].on = true; // 路面だけON
    render(<MapOverlayControls {...baseProps()} layers={layers} onToggle={onToggle} />);

    await user.click(screen.getByRole("button", { name: "標高図" }));
    expect(onToggle).toHaveBeenCalledWith("elevation", true);

    await user.click(screen.getByRole("button", { name: "路面" }));
    expect(onToggle).toHaveBeenCalledWith("roadSurface", false);
  });

  // 全レイヤー一括OFFボタンは地図下部中央の時刻スライダー隣へ移設し、page.tsx
  // （handleClearAllLayers）が持つようになったため、このコンポーネント自体はもう
  // 描画しない（実機フィードバック「左上の全クリアアイコンをスライドバーの左側に
  // 移動して」、MapOverlayControls.module.css参照）。

  it("disabledのチップは押せず、on=trueでもaria-pressedはfalseのまま", () => {
    const layers = baseLayers();
    layers[2] = { ...layers[2], on: true, disabled: true };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const routeChip = screen.getByRole("button", { name: "ルート" });
    expect(routeChip).toBeDisabled();
    expect(routeChip).toHaveAttribute("aria-pressed", "false");
  });

  it("legendDetailsがあれば絞り込み中でなくても▶が出て、開くと軸ごとの全カテゴリ内訳が出る", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      summary: null, // 絞り込み無し
      legendDetails: [
        {
          label: "路面の種類",
          legend: [
            { key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] },
            { key: "concrete", label: "コンクリート", color: "#0d9488", filter: ["literal", true] },
          ],
          hiddenKeys: [],
        },
      ],
    };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const toggle = screen.getByRole("button", { name: "路面の凡例を表示" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("アスファルト")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    // 軸見出し・非表示カテゴリを含む全カテゴリがそれ単体で読める形で出る（1行要約は出さない）
    expect(screen.getByText("路面の種類")).toBeInTheDocument();
    expect(screen.getByText("アスファルト")).toBeInTheDocument();
    expect(screen.getByText("コンクリート")).toBeInTheDocument();
    expect(screen.queryByText(/路面:/)).not.toBeInTheDocument();
  });

  it("絞り込み中は非表示カテゴリに「非表示」バッジが付く", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      summary: "コンクリート以外",
      legendDetails: [
        {
          label: "路面の種類",
          legend: [
            { key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] },
            { key: "concrete", label: "コンクリート", color: "#0d9488", filter: ["literal", true] },
          ],
          hiddenKeys: ["concrete"],
        },
      ],
    };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);
    await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));

    expect(screen.getByText("非表示")).toBeInTheDocument();
    // 1行要約テキストそのものは表示しない（▶を押した本人には自明という実機フィードバック対応）
    expect(screen.queryByText("コンクリート以外")).not.toBeInTheDocument();
  });

  it("legendDetailsが空でもsummaryがあれば▶が出て、開くと案内文が出る", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = { ...layers[1], on: true, summary: "ズームインすると表示されます", legendDetails: [] };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const toggle = screen.getByRole("button", { name: "路面の凡例を表示" });
    await user.click(toggle);
    expect(screen.getByText("ズームインすると表示されます")).toBeInTheDocument();
  });

  it("OFF・disabled・凡例無しのレイヤーには▶が出ない", () => {
    const layers: OverlayLayerChip[] = [
      { id: "elevation", label: "標高図", on: true, summary: null, legendDetails: [] }, // 凡例無し
      { id: "roadSurface", label: "路面", on: false, summary: null, legendDetails: [{ label: "路面の種類", legend: [], hiddenKeys: [] }] }, // OFF
      { id: "route", label: "ルート", on: true, disabled: true, summary: "色分け: 風の影響" }, // disabled
    ];
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.queryByRole("button", { name: "標高図の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "路面の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ルートの凡例を表示" })).not.toBeInTheDocument();
  });

  // 次数束ね（改善計画T166）: T128のcategory束ねを、観測データ/推定指標（合成）の2トップへ
  // 反転した。categoryを持つraw（省略含む）チップは「観測」、compositeチップは「推定」へ
  // 集約され、categoryを持たないレイヤー（route等）は従来どおり単独。
  describe("次数束ね（改善計画T166）", () => {
    function groupedLayers(): OverlayLayerChip[] {
      return [
        { id: "elevation", label: "標高図", on: false }, // categoryなし→単独のまま
        { id: "roadType", label: "道路の種類", on: false, category: "roadCondition" },
        { id: "designation", label: "指定路線", on: true, category: "roadCondition" },
        { id: "axis:car_stress", label: "車の圧迫感", on: true, category: "trafficSafety", dataNature: "composite" },
        { id: "accidents", label: "事故地点", on: false, category: "trafficSafety" }, // dataNature省略→raw扱い
      ];
    }

    it("観測（raw）チップはすべて「観測」へ、推定（composite）チップはすべて「推定」へ束ねられ、個別ボタンは出ない", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      expect(screen.getByRole("button", { name: "標高図" })).toBeInTheDocument(); // categoryなしは単独のまま
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "指定路線" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "観測" })).toBeInTheDocument(); // 次数見出しの束ねチップ（略名）
      expect(screen.getByRole("button", { name: "推定" })).toBeInTheDocument();
    });

    // 表示順・展開方式の見直し（実機フィードバック: 「推定→観測」の順に入替え、観測の▼展開は
    // 独立したサブフレームではなくチップ列と地続きの縦並びにする）。
    it("チップ列は推定→観測→ルートの順で並ぶ", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      const names = screen.getAllByRole("button", { name: /^(推定|観測|標高図)$/ }).map((el) => el.textContent);
      expect(names.indexOf("推定")).toBeLessThan(names.indexOf("観測"));
    });

    it("観測グループを開いても内訳を囲むカード（サブフレーム）は出ず、メンバーはチップ列と同じ階層の兄弟要素として並ぶ", async () => {
      const user = userEvent.setup();
      const { container } = render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      // 以前は背景・枠・影付きのカードに閉じ込めていた。地続き化した今は出ない。
      expect(container.querySelector('[class*="detailPanelBase"]')).not.toBeInTheDocument();

      const observedButton = screen.getByRole("button", { name: "観測" });
      const designationButton = screen.getByRole("button", { name: "指定路線" });
      // ChipButtonは自身をchipRowItemとして返すため、観測チップの行とメンバーの行は
      // 同じ親（chipRow）を共有する兄弟要素になる。
      expect(observedButton.closest('[class*="chipRowItem"]')?.parentElement).toBe(
        designationButton.closest('[class*="chipRowItem"]')?.parentElement
      );
    });

    // 実機フィードバック「地図上の各アイコンの縁取りが見にくい。一度選択して解除すると、
    // 縁取りが全て青色になってしまう」への対応。ON状態（iconChipActive、背景が青）でも
    // グループ色分け用のクラス（iconChipGroupRaw等）自体は外れずに残ることを確認する
    // （CSS側でコンパウンドセレクタにより枠線だけグループ色を守り返す設計、
    // MapOverlayControls.module.css参照）。色の実値はjsdomでは信頼できないため、
    // クラスの併存という構造面だけを検証する。
    it("ONのメンバーもグループ色分けクラス(iconChipGroupRaw)を保持したままiconChipActiveが付く", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      await user.click(screen.getByRole("button", { name: "観測" }));
      const designationButton = screen.getByRole("button", { name: "指定路線" });
      expect(designationButton.className).toMatch(/iconChipGroupRaw/);
      expect(designationButton.className).toMatch(/iconChipActive/);
    });

    // 実機フィードバック「グループ親のアイコン（推定、観測、動的）は、展開中は薄色でON、
    // 展開解除は灰色でOFFを示して」。見出しチップだけに付く.groupHeaderChipマーカーと
    // groupTintの組み合わせで、折りたたみ=灰色系（iconChipExpandedを持たない）・
    // 展開=そのグループの薄色塗り（iconChipExpandedを持つ）を出し分ける設計になっている。
    it("観測見出しは折りたたみ時iconChipExpandedを持たず、展開するとgroupHeaderChip+iconChipGroupRaw+iconChipExpandedの組み合わせになる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      const observedButton = screen.getByRole("button", { name: "観測" });
      expect(observedButton.className).toMatch(/groupHeaderChip/);
      expect(observedButton.className).toMatch(/iconChipGroupRaw/);
      expect(observedButton.className).not.toMatch(/iconChipExpanded/);

      await user.click(observedButton);
      expect(observedButton.className).toMatch(/groupHeaderChip/);
      expect(observedButton.className).toMatch(/iconChipGroupRaw/);
      expect(observedButton.className).toMatch(/iconChipExpanded/);
    });

    // category小見出し（道路状態・交通・安全）は表示しない（実機フィードバック
    // 「道路状態や交通・安全等のグルーピングを消して」への対応）。フラットな一覧になる。
    it("観測グループを開くとcategory小見出しを出さずメンバーのON/OFFボタンがフラットに並ぶ", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      expect(screen.queryByText("道路状態")).not.toBeInTheDocument();
      expect(screen.queryByText("交通・安全")).not.toBeInTheDocument();
      const designationToggle = screen.getByRole("button", { name: "指定路線" });
      expect(designationToggle).toHaveAttribute("aria-pressed", "true");

      await user.click(designationToggle);
      expect(onToggle).toHaveBeenCalledWith("designation", false);
      // compositeのcarStressは観測グループに含まれない
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
    });

    // 展開方式の見直し（実機フィードバック: 観測の▼縦並び地続き化と対になる横並び版。
    // 推定も▶を開くと、独立したカード（サブフレーム、position: fixedのポータル）ではなく、
    // 推定チップ本体と同じ上端・同じ間隔の横並びとして地続きに展開する）。
    it("推定グループを開いても内訳を囲むカード（サブフレーム）は出ず、推定チップ本体と軸タイルは同じ上端の横並びの兄弟要素になる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "推定" }));
      // 以前はdocument.bodyへポータルしたposition: fixedのカード（.detailPanel）に
      // 閉じ込めていた。地続き化した今は出ない（.detailPanelはdocument.bodyへポータル
      // されるためcontainerの外に出る。document.body全体を見て確認する）。
      expect(document.body.querySelector('[class*="detailPanel"]')).not.toBeInTheDocument();

      const estimatedButton = screen.getByRole("button", { name: "推定" });
      const carStressButton = screen.getByRole("button", { name: "車の圧迫感" });
      // ChipButtonは自身をchipRowItemとして返すため、推定チップの行と軸タイルの行は
      // 同じ親（横並びのestimatedFlatRow）を共有する兄弟要素になる。
      expect(estimatedButton.closest('[class*="chipRowItem"]')?.parentElement).toBe(
        carStressButton.closest('[class*="chipRowItem"]')?.parentElement
      );
    });

    // マトリックス化（改善計画T169）: 推定グループの内訳は、観測グループのメンバーと同じ
    // 「アイコン+略名の四角タイル」（ChipButton）を横並びで並べる。専用レイヤーの無い軸は
    // タップ不能（disabled）の情報タイルとして同じ見た目で並ぶ（薄字の行ではなくなった）。
    it("推定グループを開くと確定命名表の6軸すべてがタイルとして並び、専用レイヤーの無い軸は押せない情報タイルになる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "推定" }));
      // レイヤーを持つ軸（car_stress）はON/OFFタイル
      const carStressToggle = screen.getByRole("button", { name: "車の圧迫感" });
      expect(carStressToggle).toHaveAttribute("aria-pressed", "true");
      expect(carStressToggle).not.toBeDisabled();
      // レイヤーを持たない軸（勾配のみ、材料gradient_percentがタイル非依存）は正式名の
      // タイルだが押せない（disabled）
      const gradientTile = screen.getByRole("button", { name: "勾配" });
      expect(gradientTile).toBeDisabled();
      // レイヤーはある（改善計画T278でsurface_q・nightもkind="ramp"の自動導出表示を
      // 持つようになった）がlayers propに渡されていない軸（舗装質・夜間・停止密度・
      // 事故密度）も同様にdisabledのタイルとして並ぶ（layersに無いので対応するチップを
      // 引けない）
      expect(screen.getByRole("button", { name: "舗装質" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "夜間" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "停止密度" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "事故密度" })).toBeDisabled();

      // 専用レイヤーの無い軸（勾配のみ）にも個々に▼展開ボタンが付き、材料の一次属性
      // 一覧（renderMaterialsNote）が見える。改善計画T318で代役案内文（旧proxyHint）は
      // 撤去したため、専用レイヤーを持たない軸の展開内容は材料一覧のみになった。
      await user.click(screen.getByRole("button", { name: "勾配の凡例を表示" }));
      expect(screen.getByText("材料: 標高")).toBeInTheDocument();
    });

    // モバイル限定の小型化（実機フィードバック「推定の横並びが複数行に折り返されて見にくい」
    // への対応）: 軸タイルにだけCSSフック用のクラス（.chipRowItemAxis）が付き、タイル本体で
    // 視覚的に隠す略名は▼展開パネル側にも見出しとして出る（アクセシビリティ上の名前は
    // タイル本体のテキストノードのままなので変わらない）。観測メンバーはこの対象外。
    it("推定グループの軸タイルにはモバイル小型化用クラスが付き、▼展開パネルに略名見出しが出る", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "推定" }));
      const carStressToggle = screen.getByRole("button", { name: "車の圧迫感" });
      expect(carStressToggle.closest('[class*="chipRowItem"]')?.className).toMatch(/chipRowItemAxis/);

      await user.click(screen.getByRole("button", { name: "勾配の凡例を表示" }));
      // タイル本体の略名（ボタン名）とパネル内見出しの2箇所に同じテキストが出る
      expect(screen.getAllByText("勾配")).toHaveLength(2);

      // 観測メンバー（例: 道路の種類）はこの小型化の対象外
      await user.click(screen.getByRole("button", { name: "観測" }));
      const roadTypeButton = screen.getByRole("button", { name: "道路の種類" });
      expect(roadTypeButton.closest('[class*="chipRowItem"]')?.className).not.toMatch(/chipRowItemAxis/);
    });

    it("推定グループはcompositeチップが1件も渡されなくても常に表示される（SECONDARY_AXESの情報タイルがあるため）", () => {
      render(<MapOverlayControls {...baseProps()} />); // baseLayers()にcompositeチップなし
      expect(screen.getByRole("button", { name: "推定" })).toBeInTheDocument();
    });

    // 次数グループ本体（観測/推定）は展開/収納の見出しであり、タップしてもレイヤーの
    // ON/OFFは切り替わらない。以前はメンバーが1件でもONならこの見出し自体もON扱い
    // （aria-pressed=true）にしていたが、材料の連動ON（T167、推定指標をONにすると
    // 観測データも連動ONする）で「事故密度だけONにしたつもりが推定・観測の見出しまで
    // ONに見える」という実機フィードバックを受け、見出し自体は常にfalseにした。
    // その後、展開三角ボタンを廃止し見出し自体のactive見た目で展開状態を表す方式
    // （expandViaSelf）へ変更したため、ON/OFFの意味を持つaria-pressedはそもそも
    // 持たず、開閉の意味を持つaria-expandedだけを持つ。
    it("グループチップ自体はメンバーのON状態を表すaria-pressedを持たず、展開状態のaria-expandedだけを持つ", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      // roadType=OFF・designation=ONの観測グループ、carStress=ONの推定グループ
      const observedButton = screen.getByRole("button", { name: "観測" });
      const estimatedButton = screen.getByRole("button", { name: "推定" });
      expect(observedButton).not.toHaveAttribute("aria-pressed");
      expect(estimatedButton).not.toHaveAttribute("aria-pressed");
      expect(observedButton).toHaveAttribute("aria-expanded", "false");
      expect(estimatedButton).toHaveAttribute("aria-expanded", "false");

      // 展開三角ボタンは廃止済みで別ボタンとしては存在せず、見出し自身のタップ+
      // aria-expandedで開閉を表す（実機フィードバック「展開三角アイコンをなくし、
      // 展開状態は推定と観測アイコンの状態で表現して」への対応）。
      expect(screen.queryByRole("button", { name: /観測の凡例を/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /推定の凡例を/ })).not.toBeInTheDocument();

      await user.click(observedButton);
      expect(observedButton).toHaveAttribute("aria-expanded", "true");
    });

    // 改善計画T181（実機フィードバック「縦アイコンが多くて見切れるようになってきた」への
    // 対応で再設計）: 折りたたみ時だけ見出しの脇に出る入口（Ⓘ）は、以前は読み取り専用の
    // 「アイコンの意味」一覧だったが、各項目にチェックボックスを持つ「表示する項目を選ぶ」
    // 設定パネルへ拡張した。展開後は絞り込み済みの軸タイル自体のアイコンが並ぶため、
    // 設定入口ボタンごと消える（同じ内容を二重に見せない）点は従来どおり。
    it("折りたたみ中だけ見出しの脇に「表示項目を設定」ボタンが出て、展開すると消える", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      // 折りたたみ中: 設定ボタンが見える（aria-labelは見出しの正式名を使う。他の凡例
      // トグル（例:「車の圧迫感の凡例を表示」）と同じく略名ではなく正式名を使う既存の
      // 命名規則に揃えている）
      const estimatedSettingsToggle = screen.getByRole("button", { name: "推定指標（合成）の表示項目を設定" });
      expect(estimatedSettingsToggle).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "観測データの表示項目を設定" })).toBeInTheDocument();

      // 押すとグループを展開せず（軸タイルは出ない）、アイコン+略名+チェックボックスの
      // 一覧だけが出る
      await user.click(estimatedSettingsToggle);
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "推定" })).toHaveAttribute("aria-expanded", "false");
      // SECONDARY_AXES6軸ぶんの略名がすべて一覧に出る
      for (const chipLabel of ["勾配", "舗装", "夜間", "停止密度", "圧迫感", "事故密度"]) {
        expect(screen.getByText(chipLabel)).toBeInTheDocument();
      }

      // 展開すると設定ボタンごと消える（軸タイル自体のアイコンと二重に見せないため）
      await user.click(screen.getByRole("button", { name: "推定" }));
      expect(screen.getByRole("button", { name: "車の圧迫感" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "推定指標（合成）の表示項目を設定" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "推定指標（合成）の表示項目を隠す" })).not.toBeInTheDocument();
    });

    it("表示項目の設定で非表示に選ぶと、グループを開いてもそのメンバー/軸だけが出ない", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      // 観測: 指定路線を非表示に選ぶ
      await user.click(screen.getByRole("button", { name: "観測データの表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "指定路線を表示しない" }));
      await user.click(screen.getByRole("button", { name: "観測" }));
      expect(screen.queryByRole("button", { name: "指定路線" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路の種類" })).toBeInTheDocument(); // 他は影響なし

      // 観測を折りたたんでから推定: 車の圧迫感を非表示に選ぶ
      await user.click(screen.getByRole("button", { name: "観測" }));
      await user.click(screen.getByRole("button", { name: "推定指標（合成）の表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "圧迫感を表示しない" }));
      await user.click(screen.getByRole("button", { name: "推定" }));
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "勾配" })).toBeInTheDocument(); // 他は影響なし
    });

    // 実機フィードバック「設定で非表示にした場合、裏でレイヤ表示ONになっていればOFFにして」
    // への対応。非表示に選んだ瞬間、対応するレイヤーがONならonToggleでOFFにする（groupedLayers
    // ではdesignation/axis:car_stressが両方on:trueのため、この2件で検証する）。逆に非表示解除は
    // レイヤーを自動でONにはしない（隠す/出すはチップの見た目の設定であり、ON/OFFの意思決定は
    // ユーザーが個別に行うため）。
    it("表示項目の設定で非表示に選ぶと、そのレイヤーがONなら即座にOFFにされる", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} onToggle={onToggle} />);

      // 観測: ON状態の指定路線を非表示に選ぶ→OFFになる
      await user.click(screen.getByRole("button", { name: "観測データの表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "指定路線を表示しない" }));
      expect(onToggle).toHaveBeenCalledWith("designation", false);

      // 推定: ON状態の車の圧迫感を非表示に選ぶ→OFFになる
      await user.click(screen.getByRole("button", { name: "観測" })); // 観測の設定パネルを閉じる
      await user.click(screen.getByRole("button", { name: "推定指標（合成）の表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "圧迫感を表示しない" }));
      expect(onToggle).toHaveBeenCalledWith("axis:car_stress", false);
    });

    it("表示項目の設定でOFF状態のメンバーを非表示に選んでもonToggleは呼ばれない", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} onToggle={onToggle} />);

      // 道路の種類はon:false
      await user.click(screen.getByRole("button", { name: "観測データの表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "道路の種類を表示しない" }));
      expect(onToggle).not.toHaveBeenCalled();
    });

    it("非表示を解除してもレイヤーは自動でONにならない", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "観測データの表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "指定路線を表示しない" }));
      expect(onToggle).toHaveBeenCalledWith("designation", false);
      onToggle.mockClear();

      await user.click(screen.getByRole("button", { name: "指定路線を表示する" }));
      expect(onToggle).not.toHaveBeenCalled();
    });

    // 実機フィードバック「スクロールできないことがある」への対応。内訳パネルは
    // position: fixedでJSが測った行の位置から浮かせるため（top: rect.bottom + gap等）、
    // 行が画面下端に近いとCSS既定の最大高さ（16rem=256px）ぶんがビューポート外へ
    // はみ出し、パネル自身のoverflow-y: autoでスクロールしても原理的に到達できない
    // 領域ができてしまう。toggleExpandedが画面の残り高さからmaxHeightを動的に縮める
    // ことで、パネル自体が必ずビューポート内に収まる（縮めた分はパネル内部でスクロール）
    // ことを確認する。
    it("画面下端に近い位置で設定パネルを開くと、パネルのmaxHeightが利用可能な高さに収まるよう縮む", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "innerHeight", "get").mockReturnValue(768);
      vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
        top: 700,
        bottom: 700,
        left: 10,
        right: 50,
        width: 40,
        height: 0,
        x: 10,
        y: 700,
        toJSON: () => ({}),
      });
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "観測データの表示項目を設定" }));
      const panel = document.querySelector('[class*="detailPanel"]') as HTMLElement;
      expect(panel).toBeTruthy();
      // top(708) + gap(8) を引いた残り(52px)は下限120pxを下回るため、120px（下限）まで
      // 縮まることを確認する。
      expect(panel.style.maxHeight).toBe("120px");

      vi.restoreAllMocks();
    });

    // ユーザー要望「グループの選択状態等は保持しておいて、次開いた時に同じ状態にして。
    // 過去の設定内容はlocalStorageで保持してほしい」。グループ本体の開閉と表示項目の
    // 設定（hiddenIds）がlocalStorageへ保存され、次回マウント時（ページ再訪問を模した
    // unmount→再render）に復元されることを確認する。
    it("グループの開閉状態と表示項目の設定はlocalStorageへ保存され、再マウント後も復元される", async () => {
      const user = userEvent.setup();
      const { unmount } = render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      // 設定パネル（折りたたみ中だけ出る）で道路の種類を非表示に選んでから観測グループを開く。
      await user.click(screen.getByRole("button", { name: "観測データの表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "道路の種類を表示しない" }));
      await user.click(screen.getByRole("button", { name: "観測" }));
      expect(screen.getByRole("button", { name: "観測" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();

      unmount();

      // 再訪問を模して同じlayersで新しくマウントする（layers自体はpage.tsx側のprops、
      // ここではhiddenIds/expandedIdsという別の永続化対象だけを検証する）。
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      expect(await screen.findByRole("button", { name: "観測" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "指定路線" })).toBeInTheDocument();
    });

    // 展開/折りたたみの切り替えの瞬間、見出し（ChipButton）のDOMノード自体が
    // アンマウント/再マウントされないことを確認する回帰テスト。ラッパーdivのkeyを
    // 状態で出し分けていた実装では、展開した直後に別のDOMノードへ差し替わってしまい、
    // aria-expanded等が反映されない不具合があった（MapOverlayControls.module.cssの
    // .headerLegendRowコメント参照）。
    it("見出しのDOMノードは折りたたみ↔展開の切り替えでも同一のまま保たれる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      const observedButton = screen.getByRole("button", { name: "観測" });
      await user.click(observedButton);
      // クリックしたのと同じ参照のまま、展開後の状態が反映されていること
      // （別ノードに差し替わっていれば、この参照は展開前の古い状態に取り残される）
      expect(observedButton).toHaveAttribute("aria-expanded", "true");
      expect(observedButton).toBe(screen.getByRole("button", { name: "観測" }));

      await user.click(observedButton);
      expect(observedButton).toHaveAttribute("aria-expanded", "false");
    });

    // 推定グループの各軸タイルに材料一覧を出す（改善計画T167→T169）。axisMaterials（T164）
    // から導出した一次属性を、表示レイヤーの有無で「材料」「地図では未表示の材料」の2行に
    // 分ける。マトリックス化後は各軸タイル自身の▼展開を押してはじめて見える。
    it("推定グループの各軸タイルの▼を開くと材料一覧が出て、表示レイヤーの有無で分けて表示される", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      await user.click(screen.getByRole("button", { name: "推定" }));

      // 車の圧迫感: 道路種別・インフラ・指定路線はレイヤーあり、車線数・制限速度・車両可否は無し
      await user.click(screen.getByRole("button", { name: "車の圧迫感の凡例を表示" }));
      expect(screen.getByText("材料: 道路種別・インフラ・指定路線")).toBeInTheDocument();
      expect(screen.getByText("地図では未表示の材料: 車線数・制限速度・車両可否")).toBeInTheDocument();

      // 勾配: 材料の標高にはレイヤーがある（未表示材料は無し）
      await user.click(screen.getByRole("button", { name: "勾配の凡例を表示" }));
      expect(screen.getByText("材料: 標高")).toBeInTheDocument();

      // 夜間: 材料はトンネル（レイヤーあり）・街灯（レイヤー無し）
      await user.click(screen.getByRole("button", { name: "夜間の凡例を表示" }));
      expect(screen.getByText("材料: トンネル")).toBeInTheDocument();
      expect(screen.getByText("地図では未表示の材料: 街灯")).toBeInTheDocument();
    });

    // タイルの見た目統一（改善計画T169、ユーザー指摘「1次要素、2次要素すべて推定と同様の
    // 四角タイルアイコンにして」）: 観測グループのメンバーは推定グループの軸タイルと同じ
    // ChipButtonを再利用しており、個々に凡例展開ボタンが付く。観測グループ自体が▼縦積みの
    // ため、メンバー個々の展開はそれと直交する▶（右）になる。
    it("観測グループのメンバータイルは凡例を持てば個別に▶展開ボタンが付き、開くと右へ凡例が出る", async () => {
      const user = userEvent.setup();
      const layers = groupedLayers();
      const roadType = layers.find((l) => l.id === "roadType")!;
      roadType.on = true;
      roadType.legendDetails = [
        {
          label: "道路の種類",
          legend: [{ key: "primary", label: "幹線道路", color: "#111827", filter: ["literal", true] }],
          hiddenKeys: [],
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      const expandToggle = screen.getByRole("button", { name: "道路の種類の凡例を表示" });
      expect(screen.queryByText("幹線道路")).not.toBeInTheDocument();

      await user.click(expandToggle);
      expect(screen.getByText("幹線道路")).toBeInTheDocument();
    });

    // 実機フィードバック「道路種別や路面等に▶を付けて、凡例を横展開できるようにして」
    // への対応: 以前はON時のみ▶を出していたが、推定グループの軸タイルが常に▼を出すのと
    // 揃え、OFFのままでも凡例があれば▶が出るようにした。
    it("観測グループのメンバータイルはOFFのままでも凡例があれば▶展開ボタンが付く", async () => {
      const user = userEvent.setup();
      const layers = groupedLayers();
      const roadType = layers.find((l) => l.id === "roadType")!;
      roadType.on = false;
      roadType.legendDetails = [
        {
          label: "道路の種類",
          legend: [{ key: "primary", label: "幹線道路", color: "#111827", filter: ["literal", true] }],
          hiddenKeys: [],
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      expect(screen.getByRole("button", { name: "道路の種類の凡例を表示" })).toBeInTheDocument();
    });

    // 実機フィードバック「たまに凡例を出すための▶が消える」への対応（回帰テスト）。
    // 道路種別・路面はregionZoomTooWide中legendDetailsが空配列になり、ズームインを促す
    // 案内文（summary）だけが内容になる。単独チップ側は元々summaryへフォールバックして
    // いたが、観測グループのメンバータイル側はlegendDetailsの有無だけでcanExpandを判定して
    // おり▶自体が消えてしまっていた（案内文を開けない）。
    it("観測グループのメンバータイルはlegendDetailsが空でもsummaryがあれば▶が出て、開くと案内文が出る", async () => {
      const user = userEvent.setup();
      const layers = groupedLayers();
      const roadType = layers.find((l) => l.id === "roadType")!;
      roadType.on = true;
      roadType.legendDetails = [];
      roadType.summary = "ズームインすると表示されます";
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      const expandToggle = screen.getByRole("button", { name: "道路の種類の凡例を表示" });
      expect(expandToggle).toBeInTheDocument();

      await user.click(expandToggle);
      expect(screen.getByText("ズームインすると表示されます")).toBeInTheDocument();
    });

    it("観測グループのメンバータイルはlegendDetailsもsummaryも無ければ▶が出ない", () => {
      const layers = groupedLayers();
      const roadType = layers.find((l) => l.id === "roadType")!;
      roadType.on = true;
      roadType.legendDetails = [];
      roadType.summary = null;
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      expect(screen.queryByRole("button", { name: "道路の種類の凡例を表示" })).not.toBeInTheDocument();
    });
  });

  // 動的グループ（改善計画T171、新設）。観測グループ（group:raw）と全く同じ「▼縦積み・
  // 地続き展開」の構成を使う。dataNature="dynamic"のcategory持ちチップだけが束ねられる。
  describe("動的グループ（改善計画T171）", () => {
    function layersWithDynamic(): OverlayLayerChip[] {
      return [
        { id: "elevation", label: "標高図", on: false }, // categoryなし→単独のまま
        {
          id: "precipitationNowcast",
          label: "降水ナウキャスト",
          chipLabel: "降水",
          on: false,
          category: "weather",
          dataNature: "dynamic",
        },
      ];
    }

    it("dataNature=dynamicのチップは「動的」へ束ねられ、個別ボタンは出ない", () => {
      render(<MapOverlayControls {...baseProps()} layers={layersWithDynamic()} />);

      expect(screen.queryByRole("button", { name: "降水" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "動的" })).toBeInTheDocument();
    });

    it("動的グループを開くと、独立したカードに閉じ込めずメンバーが兄弟要素として並ぶ", async () => {
      const user = userEvent.setup();
      const { container } = render(<MapOverlayControls {...baseProps()} layers={layersWithDynamic()} />);

      await user.click(screen.getByRole("button", { name: "動的" }));
      expect(container.querySelector('[class*="detailPanelBase"]')).not.toBeInTheDocument();

      const dynamicButton = screen.getByRole("button", { name: "動的" });
      const memberButton = screen.getByRole("button", { name: "降水" });
      expect(dynamicButton.closest('[class*="chipRowItem"]')?.parentElement).toBe(
        memberButton.closest('[class*="chipRowItem"]')?.parentElement
      );
    });

    it("動的グループのメンバーをタップするとonToggleがレイヤーIDと反転値で呼ばれる", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={layersWithDynamic()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "動的" }));
      await user.click(screen.getByRole("button", { name: "降水" }));
      expect(onToggle).toHaveBeenCalledWith("precipitationNowcast", true);
    });

    // 改善計画T199（統合レビュー2026-08-22指摘）: 降水ナウキャストと風の凡例を続けて開くと、
    // 両方がdocument.bodyへのfloatingパネルとして同時に表示され、近接する行同士で
    // 重なって両方とも判読不能になっていた（実機Playwright確認で再現）。member:系の
    // floatingパネルは排他（新しく開いたら他を閉じる）にする。
    it("動的グループの凡例は排他表示になる（先に開いた凡例は自動で閉じる）", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        {
          id: "precipitationNowcast",
          label: "降水ナウキャスト",
          chipLabel: "降水",
          on: true,
          category: "weather",
          dataNature: "dynamic",
          legendDetails: [{ label: "降水強度", legend: [{ key: "light", label: "弱い雨", color: "#7dd3fc", filter: ["literal", true] }], hiddenKeys: [] }],
        },
        {
          id: "windVector",
          label: "風（矢印）",
          chipLabel: "風",
          on: true,
          category: "weather",
          dataNature: "dynamic",
          legendDetails: [{ label: "風速", legend: [{ key: "calm", label: "無風", color: "#94a3b8", filter: ["literal", true] }], hiddenKeys: [] }],
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);
      await user.click(screen.getByRole("button", { name: "動的" }));

      await user.click(screen.getByRole("button", { name: "降水ナウキャストの凡例を表示" }));
      expect(screen.getByText("弱い雨")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "風（矢印）の凡例を表示" }));
      expect(screen.getByText("無風")).toBeInTheDocument();
      // 降水側の凡例は自動的に閉じている（重なって両方判読不能になる不具合の再発防止）
      expect(screen.queryByText("弱い雨")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "降水ナウキャストの凡例を表示" })).toHaveAttribute("aria-expanded", "false");
    });
  });
});
