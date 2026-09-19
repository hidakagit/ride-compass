"""review_checks.py の経緯コメント検知のテスト。

この検知器は pre-commit と CI が「新規混入を機械的にブロックする」根拠になっている
（docs/comments.md「機械的な強制」）。検知できない書き方があると、止まっているつもりで
素通りし続けるため、**過去に実際にすり抜けた形**を回帰として固定する。

実行: backend/.venv/Scripts/python.exe -m pytest scripts/tests/test_review_checks.py -q
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "review_checks", Path(__file__).resolve().parents[1] / "review_checks.py"
)
review_checks = importlib.util.module_from_spec(_SPEC)
sys.modules["review_checks"] = review_checks
_SPEC.loader.exec_module(review_checks)


@pytest.fixture(autouse=True)
def _clear_repo_wide_caches():
    """リポジトリ全体を読むキャッシュをテストごとに落とす。

    `identifier_exists`は引数の`corpus`以外に、`Settings`のフィールド名とimport文が
    持ち込む名前（どちらもリポジトリ全体から集める）も見る。一時リポジトリを差し込む
    テストと実リポジトリを見るテストが同じプロセスで走るため、キャッシュが残ると
    **テストの実行順で結果が変わる**。
    """
    review_checks.settings_field_names.cache_clear()
    review_checks.imported_names.cache_clear()
    yield
    review_checks.settings_field_names.cache_clear()
    review_checks.imported_names.cache_clear()


def _violations(path: str, lines: list[tuple[int, str]]) -> list[str]:
    return review_checks.find_source_narrative_violations({path: lines})


class TestNarrativePattern:
    """パターンが拾えずすり抜けた実例。"""

    def test_kaizen_keikaku_followed_by_punctuation(self):
        # 「改善計画T572。」（句点）・「改善計画T87/T606」（スラッシュ）・「改善計画T278、」（読点）は
        # かつて `改善計画T[0-9]+で|[:：]` しか要求していなかったため素通りしていた。
        for text in ("改善計画T572。basemap.pyと同じ方式", "改善計画T87/T606", "改善計画T278、例: 舗装質"):
            assert review_checks.NARRATIVE_PATTERN.search(text), text

    def test_paraphrases_that_slipped_through(self):
        for text in ("旧実装は昇順制約に違反していた", "旧デザインは直方体の軸", "ユーザーからの明示許可"):
            assert review_checks.NARRATIVE_PATTERN.search(text), text

    def test_current_tense_constraints_are_not_flagged(self):
        # 現在形の制約表現は経緯ではないため検出しない（誤検出すると書けなくなる）。
        for text in ("このロックはXがYから並列に呼ばれるため必要", "配信元は要素ごとにzoomUseを持つ"):
            assert not review_checks.NARRATIVE_PATTERN.search(text), text


class TestPythonDocstring:
    """Pythonの説明文は大半がdocstringにあるが、以前は`#`しか見ていなかった。"""

    def test_module_docstring_is_scanned(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text('"""説明。\n\n改善計画T999。以前はこうだった。\n"""\n\nX = 1\n', encoding="utf-8")
        out = _violations(str(f), [(3, "改善計画T999。以前はこうだった。")])
        assert len(out) == 1, out

    def test_function_docstring_is_scanned(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text('def f():\n    """実測で0.2秒だった。"""\n    return 1\n', encoding="utf-8")
        assert len(_violations(str(f), [(2, '    """実測で0.2秒だった。"""')])) == 1

    def test_hash_comment_still_works(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("# 以前はこうだった\nX = 1\n", encoding="utf-8")
        assert len(_violations(str(f), [(1, "# 以前はこうだった")])) == 1

    def test_code_line_is_not_flagged(self, tmp_path):
        # 文字列リテラルに同じ語が入っていても、コメント/docstringでなければ検出しない。
        f = tmp_path / "m.py"
        f.write_text('MESSAGE = "以前は取得できました"\n', encoding="utf-8")
        assert _violations(str(f), [(1, 'MESSAGE = "以前は取得できました"')]) == []


class TestCssModules:
    """CSS Modulesは設計意図を長文コメントで書く運用だが、以前はパス対象外だった。"""

    def test_block_comment_is_scanned(self, tmp_path):
        f = tmp_path / "a.module.css"
        assert len(_violations(str(f), [(1, "/* ユーザー要望「まとめて1ボタンで」 */")])) == 1

    def test_multiline_block_continuation_is_scanned(self, tmp_path):
        f = tmp_path / "a.module.css"
        out = _violations(str(f), [(1, "/* 全レイヤー一括OFF"), (2, "   実機フィードバックで左上から移設）。 */")])
        assert len(out) == 1, out

    def test_declaration_is_not_flagged(self, tmp_path):
        f = tmp_path / "a.module.css"
        assert _violations(str(f), [(1, "  color: var(--foreground);")]) == []


def test_css_is_in_pathspecs():
    assert any("css" in spec for spec in review_checks.SOURCE_COMMENT_PATHSPECS)

# --- docs/tasks の「状態:」行の分類（improvement-plan.mdの[x]/[ ]との照合の土台） ---


_task_file_seq = 0


def _task_file(tmp_path, body: str):
    # 1テスト内で複数作るため名前を重複させない（同名だと後の書き込みが前のを上書きし、
    # 先に作ったパスを検証しているつもりで後の内容を見ることになる）。
    global _task_file_seq
    _task_file_seq += 1
    path = tmp_path / f"T{900 + _task_file_seq}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_task_status_kind_reads_a_line_starting_with_the_marker(tmp_path):
    done = _task_file(tmp_path, """# T999

規模S。

状態: 完了（2026-09-08）
""")
    assert review_checks.task_status_kind(done) == "done"

    open_ = _task_file(tmp_path, """# T999

規模S。

状態: 未着手（起票のみ）
""")
    assert review_checks.task_status_kind(open_) == "open"


def test_task_status_kind_returns_none_when_the_marker_is_not_at_line_head(tmp_path):
    # 実際にすり抜けた形。規模と同じ行へ畳むと照合対象から外れ、[x]との不一致が
    # 検知されないまま残る（この戻り値がNoneのときcheck_plan_vs_tasksが違反を上げる）。
    folded = _task_file(tmp_path, """# T999

規模S。状態: 完了（2026-09-08）。
""")
    assert review_checks.task_status_kind(folded) is None


def test_task_status_kind_treats_deferred_as_closed_and_on_hold_as_open(tmp_path):
    # 「見送り」は今後もやらない確定判断でimprovement-plan側は[x]、トリガー待ちの
    # 「保留」は[ ]（CLAUDE.md「コミット時の同期ルール」節の用語法）。
    deferred = _task_file(tmp_path, "状態: 見送り（ユーザー判断で現状維持）")
    on_hold = _task_file(tmp_path, "状態: 保留（トリガー成立まで着手しない）")

    assert review_checks.task_status_kind(deferred) == "done"
    assert review_checks.task_status_kind(on_hold) == "open"


# --- 未定義のCSSトークン検知 ---


def test_css_var_def_re_matches_definitions_on_any_line():
    # `re.MULTILINE`が無いと先頭行の定義しか拾えず、globals.cssの全トークンが
    # 「未定義」として誤検知される（実装時に踏んだ）。
    css = ":root {\n  --color-border: #e5e7eb;\n  --space-4: 1rem;\n}\n"
    assert set(review_checks.CSS_VAR_DEF_RE.findall(css)) == {"--color-border", "--space-4"}


def test_css_var_ref_re_matches_references_with_and_without_fallback():
    # フォールバックは未定義であることを隠すだけで、トークン名の綴り違いはそのまま残る
    # （docs/frontend-design-system.md「テーマトークンにフォールバックを付けないこと」）。
    assert review_checks.CSS_VAR_REF_RE.findall("color: var(--color-text);") == ["--color-text"]
    assert review_checks.CSS_VAR_REF_RE.findall("color: var(--color-accent, #2563eb);") == ["--color-accent"]


def test_css_var_ref_re_ignores_wildcards_and_runtime_interpolation():
    # 説明文中の`var(--color-*)`や、実行時に名前を合成する`var(--color-${variant})`を
    # 参照として拾うと、存在しないトークン名（`--color-`）が毎回違反になる。
    assert review_checks.CSS_VAR_REF_RE.findall("色は必ずvar(--color-*)を使う") == []
    assert review_checks.CSS_VAR_REF_RE.findall("`bg-[var(--color-${variant})]`") == []
    assert review_checks.CSS_VAR_REF_RE.findall('"bg-[var(--color-accent)]"') == ["--color-accent"]


def test_find_undefined_css_tokens_reports_only_undefined_ones(tmp_path, monkeypatch):
    root = tmp_path
    (root / "frontend" / "src" / "app").mkdir(parents=True)
    (root / "frontend" / "src" / "app" / "globals.css").write_text(
        ":root {\n  --foreground: #171717;\n}\n", encoding="utf-8"
    )
    target = root / "frontend" / "src" / "a.module.css"
    target.write_text(
        ".x {\n  color: var(--foreground);\n  fill: var(--color-text);\n}\n", encoding="utf-8"
    )
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    out = review_checks.find_undefined_css_tokens(["frontend/src/a.module.css"])

    assert len(out) == 1
    assert "--color-text" in out[0]
    assert "a.module.css:3" in out[0]


def test_find_undefined_css_tokens_accepts_tokens_defined_in_the_same_file(tmp_path, monkeypatch):
    root = tmp_path
    (root / "frontend" / "src" / "app").mkdir(parents=True)
    (root / "frontend" / "src" / "app" / "globals.css").write_text(":root {\n}\n", encoding="utf-8")
    target = root / "frontend" / "src" / "b.module.css"
    target.write_text(".x {\n  --local: 4px;\n  gap: var(--local);\n}\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    assert review_checks.find_undefined_css_tokens(["frontend/src/b.module.css"]) == []


def _css_root(tmp_path, globals_css: str):
    (tmp_path / "frontend" / "src" / "app").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app" / "globals.css").write_text(globals_css, encoding="utf-8")
    return tmp_path


def test_find_undefined_css_tokens_allows_vendor_runtime_tokens(tmp_path, monkeypatch):
    # UIライブラリが自分の要素へ実行時に設定するトークン（Radixのポップオーバーが測った
    # 空き幅等）は定義がnode_modules側にあり、globals.cssにもリポジトリ内の.ts/.tsxにも
    # 現れない。名前空間で許すが、同じファイルの自前トークンの綴り違いは通さない。
    root = _css_root(tmp_path, ":root {}")
    (root / "frontend" / "src" / "v.module.css").write_text(
        ".x {" + chr(10)
        + "  max-width: var(--radix-popover-content-available-width);" + chr(10)
        + "  color: var(--color-typo);" + chr(10)
        + "}" + chr(10),
        encoding="utf-8",
    )
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    out = review_checks.find_undefined_css_tokens(["frontend/src/v.module.css"])

    assert len(out) == 1
    assert "--color-typo" in out[0]


def test_find_undefined_css_tokens_scans_tsx(tmp_path, monkeypatch):
    # .tsxはTailwindの任意値記法（`bg-[var(--x)]`）でトークンを参照するが、
    # 検知が.cssしか見ていないと綴り違いが素通りする。
    root = _css_root(tmp_path, ":root {\n  --color-accent: #2563eb;\n}\n")
    (root / "frontend" / "src" / "C.tsx").write_text(
        'const a = "bg-[var(--color-accent)]";\nconst b = "text-[var(--color-acccent)]";\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    out = review_checks.find_undefined_css_tokens(["frontend/src/C.tsx"])

    assert len(out) == 1, out
    assert "--color-acccent" in out[0] and "C.tsx:2" in out[0]


def test_find_undefined_css_tokens_reports_undefined_even_with_fallback(tmp_path, monkeypatch):
    root = _css_root(tmp_path, ":root {\n}\n")
    (root / "frontend" / "src" / "d.module.css").write_text(
        ".x {\n  font-size: var(--font-size-xs, 0.72rem);\n}\n", encoding="utf-8"
    )
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    out = review_checks.find_undefined_css_tokens(["frontend/src/d.module.css"])

    assert len(out) == 1 and "--font-size-xs" in out[0], out


def test_find_undefined_css_tokens_accepts_tokens_set_at_runtime_from_tsx(tmp_path, monkeypatch):
    # `style["--width-swatch-color"] = color`のように.tsxが実行時に設定するトークンは
    # CSS側からは定義が見えない。母集団（all_files）から拾って定義済みとして扱う。
    root = _css_root(tmp_path, ":root {\n}\n")
    (root / "frontend" / "src" / "W.tsx").write_text(
        'style["--width-swatch-color"] = color;\n', encoding="utf-8"
    )
    (root / "frontend" / "src" / "w.module.css").write_text(
        ".x {\n  background: var(--width-swatch-color, #888);\n}\n", encoding="utf-8"
    )
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    files = ["frontend/src/W.tsx", "frontend/src/w.module.css"]
    assert review_checks.find_undefined_css_tokens(["frontend/src/w.module.css"], files) == []
    # 母集団を渡さなければ「未定義」として出る＝all_filesが効いていることの確認。
    assert len(review_checks.find_undefined_css_tokens(["frontend/src/w.module.css"])) == 1


# --- docs/modules の死んだ識別子参照 ---


def test_dead_identifier_refs_catches_renamed_symbols():
    doc_lines = {"docs/modules/x.md": [
        (1, "`page.tsx: FIXED_LAYER_VISIBILITY_DEFAULTS`は既定ONにしている"),
        (2, "`buildAxisOverlayLayers`が軸ごとのレイヤーを組み立てる"),
    ]}
    out = review_checks.find_dead_identifier_refs(doc_lines, "const DEFAULT_LAYER_VISIBILITY = {};\nbuildAxisOverlayLayers()")
    assert len(out) == 1, out
    assert "FIXED_LAYER_VISIBILITY_DEFAULTS" in out[0] and ":1:" in out[0]


def test_dead_identifier_refs_ignores_plain_english_words():
    # 説明文の強調（`hidden`・`boolean`）まで識別子として扱うと、実装にその綴りが
    # 無いだけで違反になる。
    doc_lines = {"docs/modules/x.md": [(1, "`hidden`のとき`boolean`として扱う")]}
    assert review_checks.find_dead_identifier_refs(doc_lines, "") == []


def test_looks_like_identifier_accepts_code_shaped_names_only():
    for token in ("evaluate_graph", "buildAxisOverlayLayers", "MapView", "RAMP_AXES"):
        assert review_checks.looks_like_identifier(token), token
    for token in ("hidden", "boolean", "true"):
        assert not review_checks.looks_like_identifier(token), token


# --- 経緯コメントの時制表現 ---


def test_narrative_pattern_catches_past_tense_phrases():
    # 「〜だった頃は」「〜ていたころは」は過去の状態を語る＝経緯。
    for text in ("独自実装だった頃はここだけrequestIdを残さず", "手書きで持っていたころは選択肢が古かった"):
        assert review_checks.NARRATIVE_PATTERN.search(text), text


def test_narrative_pattern_does_not_flag_tokoro_wa():
    # 「今のところは」は`たところ`であって`たころ`ではない（誤検出しない）。
    for text in ("今のところは1箇所だけで足りる", "見たところは同じ形をしている"):
        assert not review_checks.NARRATIVE_PATTERN.search(text), text


def test_source_corpus_excludes_test_bodies_but_keeps_helpers(tmp_path, monkeypatch):
    # テスト本体が旧名を文字列として持っていると、改名の取り残しが「実在する」と
    # 判定されて素通りする（この検知器自身の回帰テストで実際に起きた）。一方で
    # テスト専用ヘルパーは、docs/modulesが「本番コードに置かずテスト側に持つ」ことを
    # 明記して名指しする対象のため母集団に残す。
    root = tmp_path
    (root / "backend" / "tests").mkdir(parents=True)
    (root / "backend" / "tests" / "test_x.py").write_text("OLD_NAME = 1\n", encoding="utf-8")
    (root / "backend" / "tests" / "geo_fixtures.py").write_text("def destination_point():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    corpus = review_checks.source_corpus(["backend/tests/test_x.py", "backend/tests/geo_fixtures.py"])

    assert "OLD_NAME" not in corpus
    assert "destination_point" in corpus


# --- 素のBaseModel継承（T721） ---


def test_bare_basemodel_is_reported_only_under_backend_app():
    """backend/app配下だけを対象にする。

    テスト・スクリプト側のモデルまで縛ると、検知器の回帰テスト自体が違反になる
    （このファイルがまさにそう）。
    """
    lines = [(1, "class Foo(BaseModel):")]

    assert review_checks.find_bare_basemodel_violations({"backend/app/domain/foo.py": lines})
    assert review_checks.find_bare_basemodel_violations({"backend/tests/test_foo.py": lines}) == []
    assert review_checks.find_bare_basemodel_violations({"frontend/src/foo.py": lines}) == []


def test_bare_basemodel_accepts_strict_model_and_other_bases():
    rows = {
        "backend/app/domain/foo.py": [
            (1, "class A(StrictModel):"),
            (2, "class B(StrictModel, Generic[T]):"),
            (3, "class C(BaseSettings):"),
            # 多重継承でBaseModelを含む形は、意図がある（Genericの併用等）とみなして拾わない。
            # 検知の狙いは「既定のまま素で書いた」ケース。
            (4, "class D(BaseModel, Generic[T]):"),
        ]
    }

    assert review_checks.find_bare_basemodel_violations(rows) == []


def test_bare_basemodel_allowlist_covers_the_definition_of_strict_model_itself():
    rows = {"backend/app/domain/strict_model.py": [(1, "class StrictModel(BaseModel):")]}

    assert review_checks.find_bare_basemodel_violations(rows) == []


# --- architecture.md の「断りなき名指し」（T723） ---


def _arch(lines):
    return {"docs/architecture.md": list(enumerate(lines, 1))}


def test_undeclared_dead_ref_reports_a_name_stated_as_current():
    lines = ["評価は`totally_gone_symbol`が担当する。"]

    out = review_checks.find_undeclared_dead_refs(_arch(lines), [], "")

    assert len(out) == 1
    assert "totally_gone_symbol" in out[0]


def test_undeclared_dead_ref_accepts_a_name_declared_as_removed():
    """「もう無い」と同じ行に書いてあれば通す。

    architecture.mdは経緯も書く文書で、撤去済みのものを名指しすること自体は正当。
    誤らせるのは「撤去したと書かずに名指しする」ことだけ。
    """
    lines = [
        "`totally_gone_symbol`はT462で撤去済み。",
        "`another_gone_symbol`はかつて使っていたが、現在は別の仕組みへ移行した。",
    ]

    assert review_checks.find_undeclared_dead_refs(_arch(lines), [], "") == []


def test_undeclared_dead_ref_ignores_external_api_paths():
    """気象庁APIのパスはリポジトリのファイルではないため実在判定の対象外。"""
    lines = ["ナウキャストは`targetTimes.json`1本に実況〜+60分の予測が入る。"]

    assert review_checks.find_undeclared_dead_refs(_arch(lines), [], "") == []


def test_undeclared_dead_ref_accepts_names_that_exist():
    lines = ["`live_symbol`が担当する（`app/live_file.py`）。"]

    out = review_checks.find_undeclared_dead_refs(
        _arch(lines), ["backend/app/live_file.py"], "def live_symbol():"
    )

    assert out == []


# --- 検知器の配線（pre-commit経路とCI経路の一致） ---------------------------
#
# `.git/hooks/pre-commit`は各clone・各コンテナで手動インストールする前提のため、
# 常に走る安全網はCI（docs-consistency.yml、`docs --since`）側にしかない。
# 片方の経路にしか繋がっていない検知器は「手元では止まるのにCIでは素通り」になる。


def test_precommit_and_ci_enforce_the_same_detectors():
    staged = {k for k, modes in review_checks.DETECTOR_ENFORCEMENT.items() if "staged" in modes}
    since = {k for k, modes in review_checks.DETECTOR_ENFORCEMENT.items() if "since" in modes}

    assert staged == since, (
        "pre-commit（--staged）とCI（--since）で強制する検知器が食い違っている: "
        f"pre-commitのみ={sorted(staged - since)} / CIのみ={sorted(since - staged)}"
    )


def test_unwired_detectors_reports_a_declared_but_missing_detector():
    declared = {k for k, modes in review_checks.DETECTOR_ENFORCEMENT.items() if "since" in modes}

    # 「表から作った集合を表と突き合わせる」assertは恒真で何も守らないため置かない。
    # 見るのは関数の仕事そのもの（宣言から配線済みを引いた差）だけにする。
    assert review_checks.unwired_detectors("since", declared - {"redis_skeleton"}) == ["redis_skeleton"]


def test_cmd_docs_fails_when_a_declared_detector_is_not_wired(monkeypatch, capsys):
    """表へ足しただけ・分岐から外しただけの検知器を、実行経路として落とす。

    `unwired_detectors`が正しく差を返すことと、`cmd_docs`がその差を違反として扱うことは
    別物である。宣言だけ増えても件数0のまま静かに素通りするのが、この検査の防ぐ壊れ方。
    """
    monkeypatch.setitem(review_checks.DETECTOR_ENFORCEMENT, "zzz_never_wired", frozenset({"staged"}))

    exit_code = review_checks.cmd_docs(
        argparse.Namespace(staged=True, since=None, keys=False))

    assert exit_code == 1
    assert "zzz_never_wired" in capsys.readouterr().out


def test_unwired_detectors_ignores_detectors_not_enforced_in_that_mode():
    # task_linksはどの経路でも参考表示のみ。繋がっていなくても違反にしない。
    assert "task_links" not in review_checks.unwired_detectors("full", set())


def test_detector_allowlists_only_name_existing_files():
    # 許可リストが消えたファイルを指し続けると、検知器はそのぶん静かに緩む。
    for name in ("REDIS_SKELETON_ALLOWLIST", "BARE_BASEMODEL_ALLOWLIST"):
        for path in getattr(review_checks, name):
            assert (review_checks.REPO_ROOT / path).exists(), f"{name}が存在しないファイルを指している: {path}"


def test_redis_skeleton_allowlist_covers_the_batched_hash_cache():
    # 全国約1,300観測所をpipelineでHashへ一括読み書きする（get_json/set_jsonでは表現
    # できない）。docs/caching.md「自前で骨格を書いてよい例外」に当たる。
    assert "backend/app/services/jma_amedas_service.py" in review_checks.REDIS_SKELETON_ALLOWLIST


def test_identifier_exists_accepts_env_var_spelling_of_a_settings_field():
    # `.env`で設定する環境変数名は、実装側にはpydantic Settingsの小文字フィールドとして
    # しか現れない。大文字の綴りだけを探すと、設定可能な環境変数を名指しするたび違反になる。
    corpus = "weather_rate_limit_per_minute: int = 60"

    assert review_checks.identifier_exists("WEATHER_RATE_LIMIT_PER_MINUTE", corpus)
    assert not review_checks.identifier_exists("REMOVED_RATE_LIMIT_PER_MINUTE", corpus)


def test_identifier_exists_does_not_lowercase_camel_case_names():
    # 小文字化の緩和はSCREAMING_SNAKE_CASEだけに効かせる。
    assert not review_checks.identifier_exists("WindService", "windservice")
    assert not review_checks.identifier_exists("WINDSERVICE", "windservice")


# --- ガードの実効性監査（mutate） -------------------------------------------


def test_every_enforced_detector_has_a_way_to_produce_a_violation():
    # 検知器を足したら、その検知器だけが拾う違反の作り方も足す。無いと`mutate`が
    # その検知器を一度も試せず、鳴らなくなっても気づけない。
    enforced = {k for k, modes in review_checks.DETECTOR_ENFORCEMENT.items() if modes}
    probes = set(review_checks.guard_probe_mutations(review_checks.REPO_ROOT))

    assert enforced <= probes, f"違反の作り方が無い検知器: {sorted(enforced - probes)}"


def test_every_enforced_detector_has_an_edge_case_or_declares_it_has_no_outside():
    # 正例は母集団の内側へ違反を置くため、母集団が狭すぎることを検出できない。外縁の
    # ケース（またはその検知器に外側が無いという宣言）を1件ずつ持たせ、穴の有無を測る。
    enforced = {k for k, modes in review_checks.DETECTOR_ENFORCEMENT.items() if modes}
    edges = review_checks.guard_probe_edges(review_checks.REPO_ROOT)

    assert enforced <= set(edges), f"外縁のケースが無い検知器: {sorted(enforced - set(edges))}"
    for key in sorted(enforced):
        edge = edges[key]
        assert isinstance(edge, str) or edge.where, f"{key}の外縁に説明が無い"


def test_gap_edges_carry_a_control_placed_inside_the_population():
    # 見逃されたという事実だけでは、その位置が母集団の外だからなのか、違反がそもそも
    # 成立していないのかを区別できない。同じ違反を内側へ置く手順を1件ずつ持たせる。
    edges = review_checks.guard_probe_edges(review_checks.REPO_ROOT)

    assert review_checks.edges_without_control(edges) == [], (
        "detected=False の外縁に、同じ違反を母集団の内側へ置く手順（control）が無い。"
        "内側でも鳴らないなら、その外縁は何も試していない"
    )


def test_covered_edges_were_once_observed_as_a_real_hole():
    # 外縁を母集団の**内側**へ書いてしまうと初日から検知され、穴が埋まっているのと見分けが
    # つかない。「一度は見逃した」という観測の記録だけがこの2つを分ける。
    edges = review_checks.guard_probe_edges(review_checks.REPO_ROOT)

    assert review_checks.unproven_edges(edges) == [], (
        "見逃すと観測された記録が無いまま detected=True になっている外縁がある。"
        "母集団の内側へ置いていないか確かめ、本当に穴なら`mutate --update`で記録を取る"
    )


def test_edge_gap_records_only_name_existing_edges():
    # 記録へ先回りしてキーを書けば上のテストはすり抜けられる。記録の側にも「実在する外縁の
    # ものだけ」を課して、観測せずに正当化する経路を塞ぐ。
    edges = review_checks.guard_probe_edges(review_checks.REPO_ROOT)

    assert review_checks.stale_edge_gap_records(edges) == []


def test_probe_section_count_reads_the_keyed_heading():
    out = "## [redis_skeleton] Redis骨格の自前実装（docs/caching.md参照）: 2件\n"

    assert review_checks.probe_section_count(out, "redis_skeleton") == 2
    assert review_checks.probe_section_count(out, "narrative") is None


def test_probe_section_count_distinguishes_zero_from_a_missing_section():
    # 「検査はあるが0件（見逃し）」と「検査項目自体が無い」は別の失敗のため区別する。
    assert review_checks.probe_section_count("## [narrative] 記載粒度違反（全件）: 0件\n", "narrative") == 0
    assert review_checks.probe_section_count("", "narrative") is None


def test_guard_probe_identifier_is_not_spelled_out_in_this_repository():
    # このファイル自身が実在判定のコーパスに入るため、綴りをそのまま書くと
    # 「実装に存在する名前」になり、実在判定の検知器が鳴らなくなる。
    corpus = review_checks.source_corpus(review_checks.git_files())

    assert review_checks.GUARD_PROBE_IDENT not in corpus


def test_removal_marker_applies_to_the_whole_paragraph(tmp_path, monkeypatch):
    # この文書は1文が複数行へ折り返される。行で見ると「名前」と「撤去済み」が別の行へ
    # 落ちただけで違反になり、実測では違反47件のうち41件がこの形だった。
    root = tmp_path
    (root / "docs").mkdir()
    (root / "docs" / "architecture.md").write_text(
        "旧`zzzGone`は\n撤去済みである。\n\n`zzzAlive`が現在の実装で値を組み立てる。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    marked = review_checks.paragraphs_with_removal_marker("docs/architecture.md")

    assert marked == {1, 2}, "撤去の断りがある段落の全行が対象になる"
    assert 4 not in marked, "断りの無い別段落まで巻き込まない"


def test_removal_marker_does_not_leak_across_a_blank_line(tmp_path, monkeypatch):
    root = tmp_path
    (root / "docs").mkdir()
    (root / "docs" / "architecture.md").write_text(
        "この機構は撤去済み。\n\n`zzzStillNamed`が値を組み立てる。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)

    assert review_checks.paragraphs_with_removal_marker("docs/architecture.md") == {1}


# --- [x]化したタスクに残る、別タスクへ渡していない残り ---


def _plan_and_task(tmp_path, monkeypatch, task_body: str):
    (tmp_path / "docs" / "tasks").mkdir(parents=True)
    (tmp_path / "docs" / "tasks" / "T900.md").write_text(task_body, encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(review_checks, "TASKS_DIR", tmp_path / "docs" / "tasks")
    monkeypatch.setattr(review_checks, "newly_closed_task_numbers", lambda base: ["900"])


def test_unfiled_deferrals_reports_a_leftover_section_without_a_task_number(tmp_path, monkeypatch):
    _plan_and_task(tmp_path, monkeypatch, "# T900\n\n## 派生（関連指摘）\n\n- あとで直す箇所がある。\n")

    assert review_checks.find_unfiled_deferrals(None) == [
        "docs/tasks/T900.md:3: ## 派生（関連指摘）"
    ]


def test_unfiled_deferrals_accepts_a_bare_task_number_as_the_destination(tmp_path, monkeypatch):
    _plan_and_task(tmp_path, monkeypatch, "# T900\n\n## 残課題\n\n- T901へ分離した。\n")

    assert review_checks.find_unfiled_deferrals(None) == []


def test_unfiled_deferrals_accepts_a_stated_decision_not_to_file(tmp_path, monkeypatch):
    _plan_and_task(tmp_path, monkeypatch, "# T900\n\n## 積み残し\n\n- 効果が薄いため見送り。\n")

    assert review_checks.find_unfiled_deferrals(None) == []


def test_unfiled_deferrals_stops_the_section_at_the_next_heading(tmp_path, monkeypatch):
    # 次の見出し以降のTxxx言及を巻き込むと、無関係な番号で黙って解消扱いになる。
    _plan_and_task(
        tmp_path, monkeypatch,
        "# T900\n\n## 派生\n\n- あとで直す。\n\n## 検証結果\n\nT901のテストで確認した。\n")

    assert len(review_checks.find_unfiled_deferrals(None)) == 1


# --- 免除した段落の中身を参考として出す ---


def _arch_doc(tmp_path, monkeypatch, text: str):
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "architecture.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    return {"docs/architecture.md": list(enumerate(text.splitlines(), 1))}


def test_exempted_paragraph_still_reports_its_dead_names_as_reference(tmp_path, monkeypatch):
    # 段落単位の免除は「その段落のどこかに撤去の断りがあるか」しか見ていない。
    # 別の名前について撤去を断っている段落の中で、実在しない名前を現在形で語れる。
    doc = _arch_doc(
        tmp_path, monkeypatch,
        "`zzzGoneThing`は撤去済み。\n絞り込みは`zzzStillNamedThing`のみが担う。\n")

    assert review_checks.find_undeclared_dead_refs(doc, [], "") == []
    exempted = review_checks.find_dead_refs_inside_exempted_paragraphs(doc, [], "")
    assert len(exempted) == 1
    assert "zzzStillNamedThing" in exempted[0]


def test_design_change_words_alone_do_not_exempt_a_paragraph(tmp_path, monkeypatch):
    # 「統合」「移行」「分離」は設計変更を述べるだけで、その名前が無くなったとは言っていない。
    doc = _arch_doc(tmp_path, monkeypatch, "car_stressへ統合した。`zzzStillNamedThing`が値を組み立てる。\n")

    assert len(review_checks.find_undeclared_dead_refs(doc, [], "")) == 1


# --- npm同梱のnpx-cli.jsの解決 ---


def test_npx_cli_path_finds_it_next_to_the_resolved_npm_cli(tmp_path):
    # POSIXの`which("npm")`はシンボリックリンクで、解決するとnpm本体のbin/npm-cli.jsになる。
    # そこから改めてnode_modules/npm/binを足すと二重になり、存在しないパスを指す。
    real_bin = tmp_path / "lib" / "node_modules" / "npm" / "bin"
    real_bin.mkdir(parents=True)
    (real_bin / "npm-cli.js").write_text("", encoding="utf-8")
    (real_bin / "npx-cli.js").write_text("", encoding="utf-8")
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "npm"
    shim.symlink_to(real_bin / "npm-cli.js")

    assert review_checks.npx_cli_path(str(shim)) == real_bin / "npx-cli.js"


def test_npx_cli_path_finds_it_under_a_sibling_node_modules(tmp_path):
    # シムの隣にnode_modulesがある並び（Windows等）。
    shim_dir = tmp_path / "npmroot"
    cli = shim_dir / "node_modules" / "npm" / "bin"
    cli.mkdir(parents=True)
    (cli / "npx-cli.js").write_text("", encoding="utf-8")
    shim = shim_dir / "npm"
    shim.write_text("", encoding="utf-8")

    assert review_checks.npx_cli_path(str(shim)) == cli / "npx-cli.js"


def test_npx_cli_path_returns_none_when_nothing_matches(tmp_path):
    shim = tmp_path / "npm"
    shim.write_text("", encoding="utf-8")

    assert review_checks.npx_cli_path(str(shim)) is None


# --- SCREAMING_SNAKE定数の小文字化緩和 ---


def _settings_py(tmp_path, monkeypatch, body: str):
    (tmp_path / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / "app" / "config.py").write_text(body, encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    # identifier_existsは引数のcorpus以外にリポジトリ全体も見る（Settingsフィールド・
    # import文）。実リポジトリの内容が漏れ込むとこのテストの判定が変わるため、
    # 母集団もこの一時リポジトリへ差し替えてキャッシュを落とす。
    monkeypatch.setattr(review_checks, "git_files", lambda: ["backend/app/config.py"])
    review_checks.settings_field_names.cache_clear()
    review_checks.imported_names.cache_clear()


def test_env_var_names_are_rescued_by_the_settings_field(tmp_path, monkeypatch):
    # .envで設定する環境変数名は、実装側にはSettingsの小文字フィールドとしてしか現れない。
    _settings_py(tmp_path, monkeypatch, "class Settings(BaseSettings):\n    weather_rate_limit_per_minute: int = 30\n")
    try:
        assert review_checks.identifier_exists("WEATHER_RATE_LIMIT_PER_MINUTE", "")
    finally:
        review_checks.settings_field_names.cache_clear()
        review_checks.imported_names.cache_clear()


def test_a_constant_is_not_rescued_just_because_a_module_shares_its_lowercase_name(tmp_path, monkeypatch):
    # corpus全体で小文字形を探していたころ、`AXIS_DEFINITIONS`はモジュール名
    # `axis_definitions.py`に一致して常に「実在する」と判定されていた（撤去しても鳴らない）。
    _settings_py(tmp_path, monkeypatch, "class Settings(BaseSettings):\n    database_url: str = ''\n")
    try:
        assert not review_checks.identifier_exists("AXIS_DEFINITIONS", "from app.domain import axis_definitions")
    finally:
        review_checks.settings_field_names.cache_clear()
        review_checks.imported_names.cache_clear()


# --- 段落判定の内容は、行番号の出所と同じものを読む ---


def test_paragraph_marker_reads_the_index_not_the_working_tree(tmp_path, monkeypatch):
    """`--staged`はインデックスの行番号を返すのに、段落判定が作業ツリーを読むとずれる。

    `git add -p`での部分ステージやステージ後の追記で両者が食い違うと、**別の段落の免除が
    適用される**（見逃し・誤検知の両方向）。pre-commitはインデックスを検査する契約なので、
    結果が作業ツリーの状態に依存してはいけない。
    """
    (tmp_path / "docs").mkdir()
    # 作業ツリー: 1行目の段落に撤去の断りがある
    (tmp_path / "docs" / "architecture.md").write_text(
        "`zzzA`は撤去済み。\n\n`zzzB`が値を組み立てる。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    # インデックス: 断りが2つ目の段落にある（段落の位置が入れ替わっている）
    monkeypatch.setattr(
        review_checks, "git",
        lambda *args, **kwargs: "`zzzB`が値を組み立てる。\n\n`zzzA`は撤去済み。\n"
        if args[:1] == ("show",) else "",
    )

    from_index = review_checks.paragraphs_with_removal_marker("docs/architecture.md", revision="")
    from_worktree = review_checks.paragraphs_with_removal_marker("docs/architecture.md")

    assert from_index == {3}
    assert from_worktree == {1}


# --- 空の母集団でも通るテストのループ ---


def _vacuous(tmp_path, monkeypatch, name: str, body: str) -> list[str]:
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    return review_checks.find_vacuous_test_loops([name])


def test_vacuous_loop_over_a_filtered_population_is_reported(tmp_path, monkeypatch):
    hits = _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("something", () => {
  const picked = items.filter((i) => i.kind === "gone");
  for (const i of picked) {
    expect(i.ok).toBe(true);
  }
});
""")
    assert len(hits) == 1 and "picked" in hits[0]


def test_a_non_empty_assertion_in_the_same_test_clears_it(tmp_path, monkeypatch):
    assert _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("something", () => {
  const picked = items.filter((i) => i.kind === "gone");
  expect(picked.length).toBeGreaterThan(0);
  for (const i of picked) {
    expect(i.ok).toBe(true);
  }
});
""") == []


def test_vitest_message_argument_does_not_hide_the_non_empty_assertion(tmp_path, monkeypatch):
    """`expect(値, "説明")`の第2引数付きも空でないことの主張として数える。"""
    assert _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("something", () => {
  const picked = items.filter((i) => i.kind === "gone");
  expect(picked.length, "実例が無い").toBeGreaterThan(0);
  for (const i of picked) {
    expect(i.ok).toBe(true);
  }
});
""") == []


def test_the_guard_must_be_inside_the_same_test(tmp_path, monkeypatch):
    """別のテストで空でないことを確かめても、このテストが空振りしないことにはならない。"""
    hits = _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("other", () => {
  expect(picked.length).toBeGreaterThan(0);
});

it("something", () => {
  const picked = items.filter((i) => i.kind === "gone");
  for (const i of picked) {
    expect(i.ok).toBe(true);
  }
});
""")
    assert len(hits) == 1


def test_a_filter_split_across_a_method_chain_is_still_seen(tmp_path, monkeypatch):
    """束縛が`.filter(...)`を次の行へ折り返す書き方（鎖の継続は括弧で区切られない）。"""
    hits = _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("something", () => {
  const ids = (catalog.axes as CatalogAxis[])
    .filter((axis) => axis.category === "gone")
    .map((axis) => axis.axis_id);
  for (const id of ids) {
    expect(KNOWN.includes(id)).toBe(false);
  }
});
""")
    assert len(hits) == 1 and "ids" in hits[0]


def test_python_comprehension_population_is_reported(tmp_path, monkeypatch):
    hits = _vacuous(tmp_path, monkeypatch, "tests/test_x.py", """
def test_something():
    picked = [m for m, s in SPECS.items() if isinstance(s, Way)]
    for material_id in picked:
        assert material_id in sql
""")
    assert len(hits) == 1 and "picked" in hits[0]


def test_python_truthiness_assert_counts_as_the_guard(tmp_path, monkeypatch):
    assert _vacuous(tmp_path, monkeypatch, "tests/test_x.py", """
def test_something():
    picked = [m for m, s in SPECS.items() if isinstance(s, Way)]
    assert picked, "1件も無い"
    for material_id in picked:
        assert material_id in sql
""") == []


def test_a_population_that_was_never_narrowed_is_not_reported(tmp_path, monkeypatch):
    """絞り込みを経ていない一覧は、空になりうる母集団ではない（誤検知を防ぐ）。"""
    assert _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("something", () => {
  for (const axis of RAMP_AXES) {
    expect(axis.id).toBeTruthy();
  }
});
""") == []


def test_a_loop_without_assertions_is_not_reported(tmp_path, monkeypatch):
    """組み立てのためのループは検査ではないので対象外。"""
    assert _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("something", () => {
  const picked = items.filter((i) => i.kind === "gone");
  for (const i of picked) {
    seen.push(i);
  }
  expect(seen).toEqual([]);
});
""") == []


def test_a_template_literal_message_does_not_swallow_the_rest_of_the_line(tmp_path, monkeypatch):
    """行内で閉じるテンプレートリテラルを潰すときに、同じ行の残りまで落としてはいけない。"""
    assert _vacuous(tmp_path, monkeypatch, "x.test.ts", """
it("something", () => {
  const picked = items.filter((i) => i.kind === "gone");
  expect(picked.length, `${field}の実例が無い`).toBeGreaterThan(0);
  for (const i of picked) {
    expect(i.ok).toBe(true);
  }
});
""") == []


def test_sample_code_inside_a_string_literal_is_not_a_test_loop(tmp_path, monkeypatch):
    """検知器自身のテストは「違反の例」を文字列として持つ。実行されないコード片で鳴らない。"""
    body = (
        "def test_detector():\n"
        "    sample = '''\n"
        "    picked = [x for x in xs if x]\n"
        "    for x in picked:\n"
        "        assert x\n"
        "    '''\n"
        "    assert detect(sample)\n"
    )
    assert _vacuous(tmp_path, monkeypatch, "tests/test_x.py", body) == []


# --- 現在の軸定義に無いaxis_id / 文書が書いた定数値 ---


def _axis_repo(tmp_path, monkeypatch, live_ids, files: dict[str, str]):
    import json as _json
    (tmp_path / "backend" / "fixtures").mkdir(parents=True)
    (tmp_path / "backend" / "fixtures" / "axis_definitions_snapshot.json").write_text(
        _json.dumps({"axes": [{"definition": {"axis_id": a}} for a in live_ids]}), encoding="utf-8")
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    return list(files) + ["backend/fixtures/axis_definitions_snapshot.json"]


def test_an_axis_id_that_left_the_snapshot_is_reported(tmp_path, monkeypatch):
    files = _axis_repo(tmp_path, monkeypatch, ["gradient"], {
        # 「消えたid」の集合はテストのフィクスチャからしか作れない
        "frontend/src/lib/x.test.ts": 'const a = { axis_id: "stop_density" };\n',
        "frontend/src/lib/x.ts": "// ramp軸（stop_density等）はカタログ由来。\n",
    })
    hits = review_checks.find_removed_axis_mentions(files)
    assert len(hits) == 1 and "stop_density" in hits[0] and hits[0].startswith("frontend/src/lib/x.ts:")


def test_a_live_axis_id_is_not_reported(tmp_path, monkeypatch):
    files = _axis_repo(tmp_path, monkeypatch, ["gradient", "stop_density"], {
        "frontend/src/lib/x.test.ts": 'const a = { axis_id: "stop_density" };\n',
        "frontend/src/lib/x.ts": "// ramp軸（stop_density等）はカタログ由来。\n",
    })
    assert review_checks.find_removed_axis_mentions(files) == []


def test_a_single_word_axis_id_is_not_matched_in_prose(tmp_path, monkeypatch):
    """1語のidは普通名詞と区別できないため母集団へ入れない（`safety`等の誤検知を防ぐ）。"""
    files = _axis_repo(tmp_path, monkeypatch, ["gradient"], {
        "frontend/src/lib/x.test.ts": 'const a = { axis_id: "safety" };\n',
        "frontend/src/lib/x.ts": "// safety のための処理。\n",
    })
    assert review_checks.find_removed_axis_mentions(files) == []


def test_a_paragraph_that_declares_the_id_gone_is_exempt(tmp_path, monkeypatch):
    files = _axis_repo(tmp_path, monkeypatch, ["gradient"], {
        "frontend/src/lib/x.test.ts": 'const a = { axis_id: "stop_density" };\n',
        "docs/modules/frontend/x.md": "`stop_density`のaxis_idは廃止。当時はこの軸が担っていた。\n",
    })
    assert review_checks.find_removed_axis_mentions(files) == []


def test_a_doc_value_that_disagrees_with_the_constant_is_reported(tmp_path, monkeypatch):
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "x.py").write_text("_JOB_TTL_SECONDS = 600.0\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("`_JOB_TTL_SECONDS`（300）で掃除する。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    hits = review_checks.find_doc_constant_drift(["backend/app/x.py", "docs/x.md"])
    assert len(hits) == 1 and "300" in hits[0] and "600" in hits[0]


def test_a_doc_value_in_a_human_unit_is_accepted(tmp_path, monkeypatch):
    """文書は人が読む単位（分・秒）で書くことがある。秒↔分の読み替えは一致とみなす。"""
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "x.py").write_text("_JOB_TTL_SECONDS = 600.0\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("`_JOB_TTL_SECONDS`は10分。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    assert review_checks.find_doc_constant_drift(["backend/app/x.py", "docs/x.md"]) == []


def test_a_number_that_is_not_right_after_the_name_is_ignored(tmp_path, monkeypatch):
    """同じ文に別の定数の値が並ぶ書き方は普通にある。名前の直後だけを見る。"""
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "x.py").write_text("MAX_ENTRIES = 300\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("`MAX_ENTRIES`を別立てにしてある——1エントリが16本。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    assert review_checks.find_doc_constant_drift(["backend/app/x.py", "docs/x.md"]) == []


def test_records_of_the_time_are_exempt_from_constant_drift(tmp_path, monkeypatch):
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "x.py").write_text("_JOB_TTL_SECONDS = 600.0\n", encoding="utf-8")
    (tmp_path / "docs" / "tasks").mkdir(parents=True)
    (tmp_path / "docs" / "tasks" / "T1.md").write_text("`_JOB_TTL_SECONDS`（300）だった。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    assert review_checks.find_doc_constant_drift(["backend/app/x.py", "docs/tasks/T1.md"]) == []


# --- レビュー手順書の死んだ識別子参照 / 段落の切れ目 ---


def test_a_list_item_does_not_exempt_its_siblings(tmp_path, monkeypatch):
    """空行を挟まないリストでは、1項目の撤去の断りがリスト全体を免除してはいけない。"""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text(
        "1. `zzzA`は撤去済み。\n2. `zzzB`が値を組み立てる。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    assert review_checks.paragraphs_with_removal_marker("docs/architecture.md") == {1}


def test_a_wrapped_list_item_is_still_one_unit(tmp_path, monkeypatch):
    """1項目が複数行へ折り返される書き方は、折り返し位置で切らない。"""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text(
        "- `zzzA`は\n  撤去済み。\n- `zzzB`が値を組み立てる。\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    assert review_checks.paragraphs_with_removal_marker("docs/architecture.md") == {1, 2}


def _review_doc(tmp_path, monkeypatch, name: str, body: str, source: str = "") -> list[str]:
    doc = tmp_path / ".claude" / "commands" / "review" / name
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(body, encoding="utf-8")
    (tmp_path / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / "app" / "x.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    return review_checks.find_review_doc_dead_refs(
        [f".claude/commands/review/{name}", "backend/app/x.py"])


def test_a_review_doc_naming_something_gone_is_reported(tmp_path, monkeypatch):
    hits = _review_doc(tmp_path, monkeypatch, "context.md", "- `zzzGoneThing`が評価の値を組み立てる。\n")
    assert len(hits) == 1 and "zzzGoneThing" in hits[0]


def test_a_review_doc_that_declares_the_removal_is_exempt(tmp_path, monkeypatch):
    assert _review_doc(tmp_path, monkeypatch, "context.md",
                       "- `zzzGoneThing`は撤去済み。\n") == []


def test_records_of_the_time_among_the_review_docs_are_exempt(tmp_path, monkeypatch):
    """`_history.md`・`history/`は当時の名前をそのまま持つ記録。"""
    assert _review_doc(tmp_path, monkeypatch, "_history.md",
                       "- `zzzGoneThing`が評価の値を組み立てる。\n") == []


def test_agent_tool_names_are_not_project_identifiers(tmp_path, monkeypatch):
    assert _review_doc(tmp_path, monkeypatch, "context.md",
                       "- 結果は`ReportFindings`で報告する。\n") == []


# --- import文が持ち込む名前の救済（テストだけが使う外部API） ---


def _identifier_repo(tmp_path, monkeypatch, files: dict[str, str]):
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    # `imported_names`は`git ls-files`で母集団を取る（`git_files`を経由しない）。
    listing = "\n".join(files)
    monkeypatch.setattr(review_checks, "git", lambda *a, **k: listing if a[:1] == ("ls-files",) else "")
    monkeypatch.setattr(review_checks, "git_files", lambda: list(files))
    review_checks.imported_names.cache_clear()
    review_checks.settings_field_names.cache_clear()


def test_a_name_only_imported_by_a_test_counts_as_existing(tmp_path, monkeypatch):
    """テスト本体はcorpusから外しているため、テストだけが使う外部APIが「存在しない」になる。"""
    try:
        _identifier_repo(tmp_path, monkeypatch, {
            "frontend/src/x.test.ts": 'import { createExpression } from "@maplibre/maplibre-gl-style-spec";\n',
        })
        corpus = review_checks.source_corpus(review_checks.git_files())
        assert "createExpression" not in corpus  # corpusには入らない
        assert review_checks.identifier_exists("createExpression", corpus)
    finally:
        review_checks.imported_names.cache_clear()
        review_checks.settings_field_names.cache_clear()


def test_an_old_name_left_in_a_test_body_is_still_reported(tmp_path, monkeypatch):
    """救済はimport文に限る。アサーションや文字列に残る旧名は改名の取り残しのまま。"""
    try:
        _identifier_repo(tmp_path, monkeypatch, {
            "backend/tests/test_x.py": 'def test_x():\n    assert row["zzz_old_field"] == 1\n',
        })
        corpus = review_checks.source_corpus(review_checks.git_files())
        assert not review_checks.identifier_exists("zzz_old_field", corpus)
    finally:
        review_checks.imported_names.cache_clear()
        review_checks.settings_field_names.cache_clear()


# --- map_redraw_coverage ----------------------------------------------------

# map.setStyle()後の再描画から辿れない描画を探す検知器の骨格。実ファイルではなく
# 合成したソースへ掛けて、辿れる/辿れないの判定そのものを固定する。
REDRAW_SOURCE = """
export function drawKept(map) {
  map.addSource(KEPT_SOURCE_ID, { type: "geojson" });
}

export function drawDropped(map) {
  map.addSource(DROPPED_SOURCE_ID, { type: "geojson" });
}

export function ensureFromTable(map) {
  map.addSource(TABLE_SOURCE_ID, { type: "geojson" });
}

export const OVERLAY_LAYERS = [{ key: "x", ensure: ensureFromTable }];

export function applyOverlays(map, layers) {
  for (const layer of layers) layer.ensure(map);
}

export function redrawAllLayers(map, props) {
  drawKept(map);
  applyOverlays(map, props.layers);
}
"""


def test_map_redraw_gaps_reports_only_what_the_redraw_cannot_reach():
    gaps = review_checks.map_redraw_gaps_in(REDRAW_SOURCE)

    assert len(gaps) == 1
    assert "drawDropped" in gaps[0]


def test_map_redraw_gaps_does_not_count_a_name_that_only_a_comment_mentions():
    # コメントで名前に触れただけで「辿れる」ことにすると、検知器が黙る。
    source = REDRAW_SOURCE.replace(
        "  drawKept(map);", "  drawKept(map);\n  // drawDroppedはここでは呼ばない"
    )

    assert len(review_checks.map_redraw_gaps_in(source)) == 1


# 描画の担当を別ファイルへ分けたとき、分けた先が検知の外へ出ないこと。母集団を入口の
# 1ファイルに限ると、抽出した関数が呼ばれなくなっても0件のまま通る（T877の抽出で実際に
# その状態になった）。
ENTRY_SOURCE = """
import { drawMoved } from "@/components/Map/Entry.routes";

export function redrawAllLayers(map, props) {
  drawMoved(map);
}
"""

MOVED_SOURCE = """
export function drawMoved(map) {
  map.addSource(MOVED_SOURCE_ID, { type: "geojson" });
}

export function drawForgotten(map) {
  map.addSource(FORGOTTEN_SOURCE_ID, { type: "geojson" });
}
"""


def test_map_redraw_population_follows_the_entry_imports(tmp_path):
    # 母集団は手で列挙せず、入口のファイルが取り込んでいる先から導く。列挙にすると、
    # 次に担当を分けた人が足し忘れた時点で静かに検知範囲から外れる。
    (tmp_path / "Moved.ts").write_text(MOVED_SOURCE, encoding="utf-8")
    (tmp_path / "Unrelated.ts").write_text(MOVED_SOURCE, encoding="utf-8")
    source = 'import { drawMoved } from "@/components/Map/Moved";'

    picked = review_checks.map_redraw_local_modules(source, tmp_path)

    assert [path.rsplit("/", 1)[-1] for path, _ in picked] == ["Moved.ts"]


def test_map_redraw_gaps_crosses_module_boundaries():
    parts = [("Entry.tsx", ENTRY_SOURCE), ("Entry.routes.ts", MOVED_SOURCE)]
    source = "\n".join(text for _, text in parts)

    gaps = review_checks.map_redraw_gaps_in(source, parts)

    # 入口から呼ばれている方は出ず、呼ばれていない方だけが出る。
    assert len(gaps) == 1
    assert "drawForgotten" in gaps[0]


def test_map_redraw_gaps_points_at_the_file_the_declaration_lives_in():
    parts = [("Entry.tsx", ENTRY_SOURCE), ("Entry.routes.ts", MOVED_SOURCE)]
    source = "\n".join(text for _, text in parts)

    gaps = review_checks.map_redraw_gaps_in(source, parts)

    # 連結後の行をそのまま出すと、入口のファイルの存在しない行を指す。
    assert gaps[0].startswith("Entry.routes.ts:")


def test_map_redraw_gaps_reports_a_missing_entry_instead_of_passing_silently():
    source = REDRAW_SOURCE.replace("redrawAllLayers", "somethingElse")

    gaps = review_checks.map_redraw_gaps_in(source)

    assert len(gaps) == 1
    assert "redrawAllLayers" in gaps[0]


# --- cross_layer_claim ------------------------------------------------------


def test_cross_layer_claim_reports_assertions_about_the_other_side():
    src = {
        "backend/app/domain/zzz.py": [(3, "    # フロントは先頭から順に出す（並べ替えを持たない）。")],
        "frontend/src/lib/zzz.ts": [(4, "// backendはキー集合の完全一致を要求する。")],
    }

    hits = review_checks.find_cross_layer_claims(src)

    assert len(hits) == 2


def test_cross_layer_claim_ignores_own_contract_and_generated_files():
    # 「呼び出し側」は自分が課す契約の相手で、レイヤーの名指しではない。生成物は契約そのもの。
    src = {
        "backend/app/domain/zzz.py": [(1, "    # 呼び出し側は1回呼ぶだけでよい。")],
        "frontend/src/types/generated/api.d.ts": [(2, " * backendは空配列を返す。")],
    }

    assert review_checks.find_cross_layer_claims(src) == []


def test_cross_layer_claim_ignores_the_same_side_and_code_lines():
    # 自分の側を主語にした説明と、コメントでない行は対象外。
    src = {
        "backend/app/domain/zzz.py": [(1, '    BACKEND_NOTE = "backendは〜"')],
        "frontend/src/lib/zzz.ts": [(2, "// フロントは先頭から順に出す。")],
    }

    assert review_checks.find_cross_layer_claims(src) == []


# --- count_narrative --------------------------------------------------------


def test_count_narrative_reports_counts_in_comments_and_docs():
    src = {"frontend/src/components/Map/zzz.ts": [(3, "// 災害は7要素をまとめて描く。")]}
    doc = {"docs/modules/frontend/zzz.md": [(5, "静的レイヤーは8種ある。")]}

    hits = review_checks.find_count_narratives(src, doc)

    assert len(hits) == 2


def test_count_narrative_ignores_code_and_task_entries():
    # コメント以外の行（定数定義）と、当時の数をそのまま残すタスクの個票は対象外。
    src = {"frontend/src/components/Map/zzz.ts": [(3, "const DISASTER_SOURCE_COUNT = 7;")]}
    doc = {"docs/tasks/T999.md": [(1, "内部軸5つ。")]}

    assert review_checks.find_count_narratives(src, doc) == []


def test_count_narrative_ignores_units_that_stay_true_when_something_is_added():
    # 長さ・時間・回数は「1つ増えたときに嘘になる」型ではない。
    src = {"backend/app/domain/zzz.py": [(1, "# 3秒で諦め、2回まで再試行する（5件まで）。")]}

    assert review_checks.find_count_narratives(src, {}) == []


# --- unscanned_target_files -------------------------------------------------


def _jscpd_tree(tmp_path: Path) -> Path:
    target = tmp_path / "backend" / "app"
    target.mkdir(parents=True)
    body = "x = 1" + ("\n" * 10)
    for name in ("scanned.py", "skipped.py", "notes.md"):
        (target / name).write_text(body, encoding="utf-8")
    (target / "tiny.py").write_text("x = 1", encoding="utf-8")
    return target


def test_unscanned_target_files_names_what_jscpd_left_out(tmp_path, monkeypatch):
    """走査から外れたファイルが名指しで出ること。

    上限に当たったことが出力へ出ないと、「クローン0件」と「見ていない」が区別できない。
    """
    _jscpd_tree(tmp_path)
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(review_checks, "JSCPD_TARGETS", ["backend/app"])

    missing = review_checks.unscanned_target_files({"backend/app/scanned.py"})

    assert missing == ["backend/app/skipped.py"]


def test_unscanned_target_files_derives_the_formats_from_what_was_scanned(tmp_path, monkeypatch):
    """対象の拡張子は手で並べず、jscpdが実際に読んだものから導くこと。

    並べると、jscpdが対応形式を増やしたときに検査の側が黙って狭くなる。.mdを読んで
    いなければ.mdは母集団に入らず、読んでいれば入る。
    """
    _jscpd_tree(tmp_path)
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(review_checks, "JSCPD_TARGETS", ["backend/app"])

    assert "backend/app/notes.md" not in review_checks.unscanned_target_files({"a/b.py"})
    assert "backend/app/notes.md" in review_checks.unscanned_target_files({"a/b.py", "a/c.md"})


def test_unscanned_target_files_ignores_files_below_the_min_lines(tmp_path, monkeypatch):
    # 比べる相手を持ちようがない短いファイルは、外れているのが正しい。
    _jscpd_tree(tmp_path)
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(review_checks, "JSCPD_TARGETS", ["backend/app"])

    assert "backend/app/tiny.py" not in review_checks.unscanned_target_files({"a/b.py"})


# --- module_redefinition ----------------------------------------------------


def _src(*lines: str) -> str:
    return chr(10).join(lines) + chr(10)


def test_module_redefinition_catches_a_constant_defined_twice():
    """撤去の切り出しが広すぎて貼り直したときに残る形。

    後の定義が前を同じ値で上書きするため、テストも`ruff`も落ちない。
    """
    src = _src("FOO = 1", "", "", "BAR = 2", "", "", "FOO = 1")

    hits = review_checks.find_module_level_redefinitions({"backend/app/zzz.py": src})

    assert len(hits) == 1
    assert "`FOO`" in hits[0]


def test_module_redefinition_catches_functions_and_classes_too():
    src = _src("def zzz():", "    return 1", "", "", "def zzz():", "    return 2")

    assert len(review_checks.find_module_level_redefinitions({"backend/app/zzz.py": src})) == 1


def test_module_redefinition_allows_definitions_under_a_branch():
    """`if`/`try`の下は、環境ごとに片方だけが走る正当な形のため見ない。"""
    src = _src("import sys", "", "if sys.version_info >= (3, 12):", "    FOO = 1",
               "else:", "    FOO = 2")

    assert review_checks.find_module_level_redefinitions({"backend/app/zzz.py": src}) == []


def test_module_redefinition_ignores_a_name_defined_once():
    src = _src("FOO = 1", "BAR = 2", "def zzz():", "    FOO = 3", "    return FOO")

    assert review_checks.find_module_level_redefinitions({"backend/app/zzz.py": src}) == []


def test_python_sources_only_reads_the_scanned_prefixes(tmp_path, monkeypatch):
    """対象外のディレクトリを読まないこと（frontendやmigrationsを巻き込まない）。"""
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "backend" / "app" / "zzz.py").write_text("FOO = 1", encoding="utf-8")
    (tmp_path / "docs" / "zzz.py").write_text("FOO = 1", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", tmp_path)

    got = review_checks.python_sources(["backend/app/zzz.py", "docs/zzz.py", "backend/app/none.py"])

    assert list(got) == ["backend/app/zzz.py"]


# --- 位置引数の個数（call_arity） -------------------------------------------


def test_call_arity_catches_one_argument_too_many():
    """シグネチャを変えた側が呼び出し元を取り残した形（docs/tasks/T889.md）。"""
    src = _src("def zzz(a, b):", "    return a + b", "", "", "VALUE = zzz(1, 2, 3)")

    hits = review_checks.find_call_arity_mismatches({"backend/app/zzz.py": src})

    assert len(hits) == 1
    assert "`zzz`" in hits[0]


def test_call_arity_catches_a_missing_required_argument():
    src = _src("def zzz(a, b):", "    return a + b", "", "", "VALUE = zzz(1)")

    assert len(review_checks.find_call_arity_mismatches({"backend/app/zzz.py": src})) == 1


def test_call_arity_counts_keyword_arguments_as_supplied():
    """`f(a, b, digits=3)`は位置2個でも欠けていない。"""
    src = _src("def zzz(a, b, digits):", "    return a", "", "", "VALUE = zzz(1, 2, digits=3)")

    assert review_checks.find_call_arity_mismatches({"backend/app/zzz.py": src}) == []


def test_call_arity_allows_any_count_for_varargs():
    src = _src("def zzz(a, *rest):", "    return a", "", "", "VALUE = zzz(1, 2, 3, 4)")

    assert review_checks.find_call_arity_mismatches({"backend/app/zzz.py": src}) == []


def test_call_arity_skips_decorated_functions():
    """デコレータはシグネチャを変えうるため、定義側の宣言をそのまま信じない。"""
    src = _src("import functools", "", "", "@functools.wraps", "def zzz(a, b):", "    return a",
               "", "", "VALUE = zzz(1, 2, 3)")

    assert review_checks.find_call_arity_mismatches({"backend/app/zzz.py": src}) == []


def test_call_arity_skips_star_unpacking_at_the_call_site():
    src = _src("def zzz(a, b):", "    return a", "", "", "ARGS = [1, 2]", "VALUE = zzz(*ARGS)")

    assert review_checks.find_call_arity_mismatches({"backend/app/zzz.py": src}) == []


def test_call_arity_resolves_names_imported_from_another_module():
    """実際に壊れたのはこの形（別モジュールの関数を素の名前で呼ぶ）。"""
    defs = _src("def zzz(a, b):", "    return a + b")
    caller = _src("from app.domain.zzz_probe import zzz", "", "VALUE = zzz(1, 2, 3)")

    hits = review_checks.find_call_arity_mismatches({
        "backend/app/domain/zzz_probe.py": defs,
        "backend/app/services/zzz_caller.py": caller,
    })

    assert len(hits) == 1
    assert "backend/app/services/zzz_caller.py" in hits[0]


def test_call_arity_ignores_a_same_named_function_from_an_unresolvable_import():
    """どの定義を指すか決まらない綴りは見ない（誤検知を出さない側へ倒す）。"""
    defs = _src("def zzz(a, b):", "    return a + b")
    caller = _src("from third_party.zzz import zzz", "", "VALUE = zzz(1, 2, 3)")

    assert review_checks.find_call_arity_mismatches({
        "backend/app/domain/zzz_probe.py": defs,
        "backend/app/services/zzz_caller.py": caller,
    }) == []


# --- 入口関数を直接呼ぶユニットテスト（mutateだけが担保していた検知器） -------
#
# `mutate`は実際に鳴るかを見るが、1検知器あたり1つの違反しか通さない。境界（何を拾い、
# 何を拾わないか）はここで固定する。


def _lines(*rows: str) -> dict[str, list[tuple[int, str]]]:
    return {"docs/modules/backend/zzz.md": list(enumerate(rows, 1))}


def test_find_dead_file_refs_reports_a_file_that_does_not_exist():
    docs = _lines("実装は`Map/zzzGone.ts`が持つ。")

    hits = review_checks.find_dead_file_refs(docs, ["frontend/src/components/Map/other.ts"])

    assert len(hits) == 1
    assert "zzzGone.ts" in hits[0]


def test_find_dead_file_refs_accepts_a_file_that_exists():
    docs = _lines("実装は`Map/other.ts`が持つ。")

    assert review_checks.find_dead_file_refs(docs, ["frontend/src/components/Map/other.ts"]) == []


def test_find_narrative_violations_reports_history_in_module_docs():
    assert len(review_checks.find_narrative_violations(_lines("以前はこの方式ではなかった。"))) == 1


def test_find_narrative_violations_accepts_a_present_tense_description():
    assert review_checks.find_narrative_violations(_lines("この値はタイルの世代を決める。")) == []


def test_find_redis_skeleton_violations_reports_a_hand_written_client():
    src = {"backend/app/services/zzz.py": list(enumerate([
        "from app.infrastructure.redis_client import get_redis_client_or_none",
    ], 1))}

    assert len(review_checks.find_redis_skeleton_violations(src)) == 1


def test_find_web_layer_batch_imports_covers_main_py():
    """`main.py`は本番webが起動時に読む筆頭のファイル。手書きのディレクトリ一覧では
    ここが外れていた（docs/tasks/T905.md）。"""
    src = {"backend/app/main.py": list(enumerate([
        "from app.batch.precompute_way_landcover import ALGORITHM_VERSION",
    ], 1))}

    assert len(review_checks.find_web_layer_batch_imports(src)) == 1


def test_find_web_layer_batch_imports_allows_batch_itself():
    src = {"backend/app/batch/refresh_derived.py": list(enumerate([
        "from app.batch.precompute_way_landcover import ALGORITHM_VERSION",
    ], 1))}

    assert review_checks.find_web_layer_batch_imports(src) == []


def test_find_way_tag_allowlist_violations_covers_files_outside_the_material_catalog():
    """`hard_filters.py`・`night.py`のように、材料カタログを持たないがway_tagsを読む
    ファイルも対象（手書き3本の一覧では外れていた）。"""
    src = {"backend/app/domain/hard_filters.py": list(enumerate([
        'if tag_value_is(way_tags, "zzz_not_allowed", "yes"):',
    ], 1))}

    hits = review_checks.find_way_tag_allowlist_violations(src)

    assert len(hits) == 1
    assert "zzz_not_allowed" in hits[0]


def test_find_way_tag_allowlist_violations_accepts_an_allowed_key():
    src = {"backend/app/domain/night.py": list(enumerate([
        'if tag_value_is(tags, "lit", "yes"):',
    ], 1))}

    assert review_checks.find_way_tag_allowlist_violations(src) == []


def test_find_undocumented_files_reports_a_file_named_nowhere():
    files = ["backend/app/services/zzz_alone.py"]

    hits = review_checks.find_undocumented_files(files, "何も書いていない", files)

    assert len(hits) == 1


def test_find_undocumented_files_does_not_let_a_same_named_file_stand_in():
    """同じ名前が複数あるとき、片方の記載でもう片方を「記載済み」にしない。

    対象ファイル表は`| api | zzz.py・… |`のように列で階層を表すため、パスでの照合には
    できない。その代わり、**そのファイルにしか無い階層の語**が同じ行にあることを求める。
    """
    files = ["backend/app/api/routers/zzz.py", "backend/app/domain/zzz.py"]
    modules = "| api | `zzz.py`（タイル配信） |"

    hits = review_checks.find_undocumented_files(files, modules, files)

    assert [h.split(":")[0] for h in hits] == ["backend/app/domain/zzz.py"]


def test_find_undocumented_files_accepts_both_when_each_row_names_its_layer():
    files = ["backend/app/api/routers/zzz.py", "backend/app/domain/zzz.py"]
    modules = "| api | `zzz.py`（タイル配信） |\n| domain | `zzz.py`（純関数） |"

    assert review_checks.find_undocumented_files(files, modules, files) == []


def test_check_dead_doc_links_reports_a_link_that_does_not_resolve(tmp_path, monkeypatch):
    """名前だけの照合では通ってしまう「階層が1つ足りないリンク」を拾う。"""
    root = tmp_path
    (root / "docs" / "tasks").mkdir(parents=True)
    (root / "docs" / "tasks" / "T001.md").write_text("# T001", encoding="utf-8")
    (root / "docs" / "sub").mkdir()
    (root / "docs" / "sub" / "a.md").write_text("詳細は[T001](tasks/T001.md)参照。", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)
    monkeypatch.setattr(review_checks, "TASKS_DIR", root / "docs" / "tasks")
    monkeypatch.setattr(review_checks, "HISTORY_DIR", root / "history")
    review_checks.read_text.cache_clear()

    hits = review_checks.check_dead_doc_links(["docs/sub/a.md"])

    assert len(hits) == 1
    assert "解決できない" in hits[0]


def test_check_dead_doc_links_accepts_a_link_that_resolves(tmp_path, monkeypatch):
    root = tmp_path
    (root / "docs" / "tasks").mkdir(parents=True)
    (root / "docs" / "tasks" / "T001.md").write_text("# T001", encoding="utf-8")
    (root / "docs" / "sub").mkdir()
    (root / "docs" / "sub" / "a.md").write_text("詳細は[T001](../tasks/T001.md)参照。", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)
    monkeypatch.setattr(review_checks, "TASKS_DIR", root / "docs" / "tasks")
    monkeypatch.setattr(review_checks, "HISTORY_DIR", root / "history")
    review_checks.read_text.cache_clear()

    assert review_checks.check_dead_doc_links(["docs/sub/a.md"]) == []


def test_find_cross_file_env_writes_reports_a_shared_variable(tmp_path, monkeypatch):
    root = tmp_path
    (root / "frontend" / "src" / "lib").mkdir(parents=True)
    (root / "frontend" / "src" / "lib" / "reader.ts").write_text(
        "export const url = process.env.NEXT_PUBLIC_ZZZ;\n", encoding="utf-8")
    (root / "frontend" / "src" / "lib" / "other.test.ts").write_text(
        'it("x", () => { process.env.NEXT_PUBLIC_ZZZ = "a"; });\n', encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)
    review_checks.read_text.cache_clear()

    hits = review_checks.find_cross_file_env_writes(
        ["frontend/src/lib/reader.ts", "frontend/src/lib/other.test.ts"])

    assert len(hits) == 1


def test_find_source_comment_dead_identifier_refs_reports_a_name_only_in_comments(tmp_path, monkeypatch):
    root = tmp_path
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "zzz.py").write_text(
        "# `zzz_gone_name`が値を組み立てる。\nvalue = 1\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)
    review_checks.read_text.cache_clear()

    hits = review_checks.find_source_comment_dead_identifier_refs(["backend/app/zzz.py"])

    assert len(hits) == 1
    assert "zzz_gone_name" in hits[0]


def test_find_source_comment_dead_identifier_refs_accepts_a_name_in_code(tmp_path, monkeypatch):
    root = tmp_path
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "zzz.py").write_text(
        "# `zzz_live_name`が値を組み立てる。\nzzz_live_name = 1\n", encoding="utf-8")
    monkeypatch.setattr(review_checks, "REPO_ROOT", root)
    review_checks.read_text.cache_clear()

    assert review_checks.find_source_comment_dead_identifier_refs(["backend/app/zzz.py"]) == []


def test_count_categories_separates_the_fixed_vocabulary_from_free_text(tmp_path):
    shard = tmp_path / "2026-01-01_all_shards.md"
    shard.write_text(
        "- file: a.py / line: 1 / category: doc-drift / severity: P2\n"
        "  `category`: `contract` / severity: P1\n"
        "  **category**: 重複（値のコピー）\n"
        "- category: doc-drift / 撤去済み軸の残存\n",
        encoding="utf-8")
    review_checks.read_text.cache_clear()

    known, unknown = review_checks.count_categories(shard)

    assert known == {"doc-drift": 2, "contract": 1}
    assert sum(unknown.values()) == 1


def test_count_categories_counts_nothing_when_no_entry_names_a_category(tmp_path):
    shard = tmp_path / "2026-01-02_all_shards.md"
    shard.write_text("- file: a.py / line: 1 / severity: P2 / summary: ...\n", encoding="utf-8")
    review_checks.read_text.cache_clear()

    assert review_checks.count_categories(shard) == ({}, {})


def _edge(detected):
    return review_checks.EdgeProbe("どこか", detected, lambda: None, lambda: None)


def test_edges_without_gap_note_reports_a_gap_left_without_a_reason(monkeypatch):
    monkeypatch.setitem(review_checks.EDGE_GAP_NOTES, "zzz_probe", "測った理由")
    edges = {"zzz_probe": _edge(False), "zzz_other": _edge(False)}

    assert review_checks.edges_without_gap_note(edges) == ["zzz_other"]


def test_edges_without_gap_note_accepts_a_closed_edge_without_a_reason():
    assert review_checks.edges_without_gap_note({"zzz_closed": _edge(True)}) == []


def test_stale_gap_notes_reports_a_reason_left_after_the_gap_was_closed(monkeypatch):
    monkeypatch.setitem(review_checks.EDGE_GAP_NOTES, "zzz_probe", "測った理由")

    # 他の実在キーもこのedges辞書には無いため一緒に挙がる。見るのは「閉じた穴の理由が
    # 挙がること」だけで、全体の一致は見ない。
    assert "zzz_probe" in review_checks.stale_gap_notes({"zzz_probe": _edge(True)})


def test_stale_gap_notes_accepts_a_reason_for_a_gap_that_is_still_open(monkeypatch):
    monkeypatch.setitem(review_checks.EDGE_GAP_NOTES, "zzz_probe", "測った理由")

    assert "zzz_probe" not in review_checks.stale_gap_notes({"zzz_probe": _edge(False)})


#: 表名の宣言は2箇所にある。テストは実在するファイルを使う——正規表現だけを合わせても、
#: 実際の書き方（`IF NOT EXISTS`・引用符・スキーマ修飾）から外れれば意味がない。
_DDL_FILE = "backend/migrations/0036_add_way_geometry.sql"
_ORM_FILE = "backend/app/infrastructure/tuning_overrides.py"


def test_declared_tables_reads_both_the_migration_ddl_and_the_orm():
    found = review_checks.declared_tables([_DDL_FILE, _ORM_FILE])

    assert found == {"way_geometry": _DDL_FILE, "tuning_overrides": _ORM_FILE}


def test_find_undocumented_tables_is_quiet_when_the_document_names_them():
    assert review_checks.find_undocumented_tables([_DDL_FILE, _ORM_FILE]) == []


def test_find_undocumented_tables_reports_a_table_the_document_never_names(monkeypatch):
    # 文書の側を「その名前を書いていない文書」へ差し替えて、拾うことを見る。
    monkeypatch.setattr(review_checks, "ARCHITECTURE_DOC", "docs/design-principles.md")

    hits = review_checks.find_undocumented_tables([_DDL_FILE, _ORM_FILE])

    assert len(hits) == 2


def test_find_undocumented_tables_only_looks_at_the_given_scope(monkeypatch):
    monkeypatch.setattr(review_checks, "ARCHITECTURE_DOC", "docs/design-principles.md")

    hits = review_checks.find_undocumented_tables([_DDL_FILE, _ORM_FILE], scope=[_ORM_FILE])

    assert [h for h in hits if "way_geometry" in h] == []


def test_find_stale_task_premises_ignores_a_name_that_never_existed(monkeypatch):
    """未完了タスクは「これから作るもの」の名前を正当に書く。実在しないだけでは挙げない。"""
    monkeypatch.setattr(review_checks, "open_task_files", lambda: ["docs/tasks/T943.md"])
    monkeypatch.setattr(
        review_checks, "read_text", lambda p: "`zzzNeverExistedIdent`を新設する。")

    assert review_checks.find_stale_task_premises([]) == []


def test_find_stale_task_premises_reports_a_name_the_repository_once_had(monkeypatch):
    """撤去された名前は、そのタスクの前提が崩れた合図になる。"""
    monkeypatch.setattr(review_checks, "open_task_files", lambda: ["docs/tasks/T629.md"])
    # `MapLayersPanel`は実際に撤去済み。pickaxeが履歴から見つけることまで込みで確かめる。
    monkeypatch.setattr(
        review_checks, "read_text", lambda p: "`MapLayersPanel`の再編に着手するとき。")

    hits = review_checks.find_stale_task_premises([])

    assert len(hits) == 1 and "MapLayersPanel" in hits[0]
