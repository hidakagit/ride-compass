"""mutmut に変異の生成と関数ごとのテストの記録だけをさせる（変異は回さない。回すのは runner.py）。backend の下で打つ。

mutmut 自身の回し方は最初の失敗で止め、テストごとの発見が取れないので使わない（issue #661 の「打ち方」）。
Windows では、mutmut 3.8.0 が読み込みの時点で断るので、その照らしと Unix 専用の読み込み（resource・fork）だけを避ける
（fork を使うのは変異を回す段だけで、生成は multiprocessing.Pool、記録はこのプロセスで pytest を回す）。
"""
import os
import platform
import sys
import time
import types

if os.name == "nt":
    import multiprocessing

    sys.modules.setdefault("resource", types.ModuleType("resource"))
    multiprocessing.set_start_method = lambda *a, **k: None
    _real_system = platform.system
    platform.system = lambda: "Linux"
    import mutmut.__main__ as m  # noqa: E402
    platform.system = _real_system
else:
    import mutmut.__main__ as m  # noqa: E402


def main():
    workers = os.cpu_count() or 4
    t0 = time.time()
    m.set_mutant_under_test("mutant_generation")
    os.makedirs("mutants", exist_ok=True)
    m.copy_src_dir()
    m.copy_also_copy_files()
    m.setup_source_paths()
    m.store_lines_covered_by_tests()
    st = m.create_mutants(workers)
    print("生成", st, round(time.time() - t0, 1), "秒", flush=True)
    t1 = time.time()
    m.collect_or_load_stats(m.get_mutant_runner(1))
    print("記録", round(time.time() - t1, 1), "秒", flush=True)


if __name__ == "__main__":
    main()
