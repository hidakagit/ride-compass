"""review_checks.py の経緯コメント検知のテスト。

この検知器は pre-commit と CI が「新規混入を機械的にブロックする」根拠になっている
（docs/comments.md「機械的な強制」）。検知できない書き方があると、止まっているつもりで
素通りし続けるため、**過去に実際にすり抜けた形**を回帰として固定する。

実行: backend/.venv/Scripts/python.exe -m pytest scripts/tests/test_review_checks.py -q
"""

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "review_checks", Path(__file__).resolve().parents[1] / "review_checks.py"
)
review_checks = importlib.util.module_from_spec(_SPEC)
sys.modules["review_checks"] = review_checks
_SPEC.loader.exec_module(review_checks)


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
    # 「保留」は[ ]（CLAUDE.md「コミット時の同期ルール」6番の用語法）。
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

    assert review_checks.unwired_detectors("since", declared) == []
    assert review_checks.unwired_detectors("since", declared - {"redis_skeleton"}) == ["redis_skeleton"]


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
