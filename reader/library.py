"""Manage the reader's library folder (reader/library).

    python reader/library.py                     rebuild library/index.json
    python reader/library.py add <book folder>   copy a book in (Markdown, notes file, linked images), then rebuild
    python reader/library.py list                show what is in the library

A book is a Markdown file in its own folder with the images it links to. `index.json` is what the
reader lists when it is served over http(s); opened as a local file the reader lists the connected
folder itself and does not need it. Standard library only.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

LIBRARY = Path(__file__).resolve().parent / "library"
NOT_A_BOOK = re.compile(r"(\.original|\.notes)\.(md|markdown)$|^readme\.(md|markdown)$", re.I)
SKIP_DIRS = {"assets", "images", "tmp", "node_modules"}
IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def is_book(path: Path) -> bool:
    return path.suffix.lower() in (".md", ".markdown") and not NOT_A_BOOK.search(path.name)


def image_links(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for src in IMAGE_LINK.findall(text):
        if not re.match(r"(https?:|data:)", src, re.I):
            seen.setdefault(unquote(src.split("?")[0].split("#")[0]).replace("\\", "/"), None)
    return list(seen)


def find_books(root: Path, depth: int = 3) -> list[Path]:
    books: list[Path] = []

    def walk(folder: Path, level: int) -> None:
        for entry in sorted(folder.iterdir()):
            if entry.is_file() and is_book(entry):
                books.append(entry)
            elif entry.is_dir() and level < depth and not entry.name.startswith(".") and entry.name.lower() not in SKIP_DIRS:
                walk(entry, level + 1)

    if root.is_dir():
        walk(root, 0)
    return books


def describe(md: Path) -> dict:
    text = md.read_text(encoding="utf-8-sig", errors="replace")
    links = image_links(text)
    cover = next((link for link in links if (md.parent / link).is_file()), "")
    stat = md.stat()
    rel = md.relative_to(LIBRARY).as_posix()
    return {
        "title": md.stem.replace("_", " ").strip(),
        "md": rel,
        "cover": (md.parent / cover).relative_to(LIBRARY).as_posix() if cover else "",
        "bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chapters": len(re.findall(r"^#{1,2} \S", text, re.M)),
        "images": len(links),
        "missing_images": sum(1 for link in links if not (md.parent / link).is_file()),
    }


def build() -> list[dict]:
    LIBRARY.mkdir(exist_ok=True)
    books = [describe(md) for md in find_books(LIBRARY)]
    books.sort(key=lambda b: b["modified"], reverse=True)
    index = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "books": books}
    (LIBRARY / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return books


def add(source: Path) -> None:
    source = source.resolve()
    mds = [source] if source.is_file() else [p for p in sorted(source.iterdir()) if p.is_file() and is_book(p)]
    if not mds:
        sys.exit(f"Markdown 책을 찾지 못했습니다: {source}")
    folder = source.parent if source.is_file() else source
    target = LIBRARY / folder.name
    if target.resolve() == folder:
        sys.exit("이미 서재 안에 있는 폴더입니다.")
    target.mkdir(parents=True, exist_ok=True)
    copied = missing = 0
    for md in mds:
        shutil.copy2(md, target / md.name)
        notes = md.with_name(md.stem + ".notes.json")
        if notes.is_file():
            if (target / notes.name).exists():
                print(f"  주석 파일은 서재에 이미 있어 덮지 않았습니다: {notes.name}")
            else:
                shutil.copy2(notes, target / notes.name)
        for link in image_links(md.read_text(encoding="utf-8-sig", errors="replace")):
            src = (folder / link).resolve()
            if folder not in src.parents or not src.is_file():
                missing += 1
                continue
            dst = target / link
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    print(f"{folder.name}: Markdown {len(mds)}개, 그림 {copied}개 복사" + (f", 못 찾은 그림 {missing}개" if missing else "") + f" -> {target}")


def main(argv: list[str]) -> None:
    if argv and argv[0] == "add":
        if len(argv) < 2:
            sys.exit(__doc__)
        for item in argv[1:]:
            add(Path(item))
    elif argv and argv[0] not in ("list", "build"):
        sys.exit(__doc__)
    books = build()
    print(f"서재 {LIBRARY}: {len(books)}권")
    for b in books:
        note = f", 못 찾은 그림 {b['missing_images']}" if b["missing_images"] else ""
        print(f"  {b['md']}  ({b['chapters']}장, 그림 {b['images']}{note}, {b['bytes'] // 1024}KB)")


if __name__ == "__main__":
    main(sys.argv[1:])
