"""Markdown 문서 사이의 상대 링크가 실제 파일을 가리키는지 검사한다.

진입점 두 개(`CLAUDE.md`/`AGENTS.md`)가 동시에 존재하지 않는 `HANDOFF.md`를 가리킨 적이
있어서 만들었다. 진입점 링크가 깨지면 새 세션의 첫 지시가 죽는다.

검사 대상은 추적되는 `.md` 안의 상대 링크뿐이다. `http(s):`, `mailto:`, 앵커 전용
링크(`#섹션`), 그리고 `[[위키링크]]`(메모리 표기)는 건너뛴다. 디렉토리 링크는 디렉토리가
존재하면 통과한다.

    .venv\\Scripts\\python.exe verification\\check_doc_links.py
    .venv\\Scripts\\python.exe verification\\check_doc_links.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 벤더/업스트림 문서는 우리가 고칠 수 없으므로 제외한다.
EXCLUDED_PREFIXES = (
    "vendor/",
    "v3/ai/upstream/",
    "node_modules/",
    "tools/node_modules/",
)

LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "ftp://", "#")


def tracked_markdown() -> list[Path]:
    """검사 대상 .md 목록.

    추적 파일과 **미추적 파일 둘 다** 본다. 아직 커밋하지 않은 새 문서가 검사에서 빠지면
    이 검사기의 목적이 사라진다 (`--others --exclude-standard`가 그 역할이고,
    `.gitignore` 대상은 계속 제외된다). git이 없으면 파일 시스템으로 대체한다.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        names = [line.strip() for line in out.splitlines() if line.strip()]
    except (OSError, subprocess.CalledProcessError):
        names = [
            str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            for p in PROJECT_ROOT.rglob("*.md")
        ]
    return [
        PROJECT_ROOT / name
        for name in names
        if not name.startswith(EXCLUDED_PREFIXES)
    ]


def link_targets(text: str) -> list[tuple[int, str]]:
    """(줄 번호, 링크 대상) 목록. 건너뛸 스킴은 제외한다."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for raw in LINK_PATTERN.findall(line):
            target = raw.split(" ", 1)[0].strip()
            if not target or target.startswith(SKIP_SCHEMES):
                continue
            found.append((number, target))
    return found


def resolve(source: Path, target: str) -> Path:
    """링크 대상을 소스 파일 기준 절대 경로로 바꾼다. 앵커는 떼어낸다."""
    path_part = target.split("#", 1)[0]
    return (source.parent / path_part).resolve()


def broken_links() -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for document in tracked_markdown():
        if not document.is_file():
            continue
        text = document.read_text(encoding="utf-8", errors="replace")
        for number, target in link_targets(text):
            resolved = resolve(document, target)
            if resolved.exists():
                continue
            failures.append(
                {
                    "file": str(document.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "line": number,
                    "target": target,
                }
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="문서 상대 링크 무결성 검사")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = parser.parse_args()

    failures = broken_links()

    if args.json:
        print(json.dumps({"broken": failures}, ensure_ascii=False, indent=2))
    else:
        for failure in failures:
            print(f"BROKEN {failure['file']}:{failure['line']} -> {failure['target']}")

    if failures:
        print(f"DOC_LINKS=FAIL ({len(failures)} broken)")
        return 1
    print("DOC_LINKS=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
