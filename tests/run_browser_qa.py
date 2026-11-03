"""Run all browser regressions against separate disposable local databases.

Requires Node, Playwright and the browser channel used by the existing suites.
Never accepts a production URL or reuses a database. Logs/results stay ignored.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--suite", action="append", help="Имя *_browser.cjs без расширения; можно повторить")
    args = parser.parse_args()
    available = {path.stem: path for path in (ROOT / "tests").glob("*_browser.cjs")}
    names = sorted(set(args.suite or available))
    unknown = set(names) - available.keys()
    if unknown:parser.error("Неизвестные сценарии: " + ", ".join(sorted(unknown)))
    folder = ROOT / ".theme-qa" / ("full-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    folder.mkdir(parents=True, exist_ok=False)
    results = []

    def run(name):
        env = dict(os.environ, HPOINT_QA_TEST_FUNDS="1", HPOINT_QA_PAID_FLOW="0",
                   HPOINT_QA_HELP_AWARDS="1" if name == "help_achievements_browser" else "0",
                   PYTHONIOENCODING="utf-8")
        started = datetime.now(timezone.utc)
        log = folder / (name + ".log")
        try:
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run([sys.executable, str(ROOT / "tests/run_theme_qa.py"),
                                         str(available[name].relative_to(ROOT))], cwd=ROOT, env=env,
                                        stdout=stream, stderr=subprocess.STDOUT, timeout=300)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        return {"suite": name, "exit_code": code, "seconds": round((datetime.now(timezone.utc)-started).total_seconds(), 1), "log": str(log)}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run, name) for name in names]):
            result = future.result();results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            (folder / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": len(results), "passed": sum(item["exit_code"] == 0 for item in results), "results": str(folder / "results.json")}, ensure_ascii=False), flush=True)
    return int(any(item["exit_code"] != 0 for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
