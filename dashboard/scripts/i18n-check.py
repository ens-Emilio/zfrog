#!/usr/bin/env python3
"""Fail the build when i18n dicts drift or PT leaks outside the dictionary.

Checks:
1. en/pt/es dicts in src/lib/i18n.ts have identical key sets.
2. No PT-diacritic string literals remain in src/ outside i18n.ts
   (pt/es translations live only in the dictionary).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "src" / "lib" / "i18n.ts"
SRC = ROOT / "src"

text = P.read_text(encoding="utf-8")
dicts: dict[str, set[str]] = {}
for lang in ("en", "pt", "es"):
    m = re.search(rf"const {lang}(?:: Dict)? = \{{(.*?)\n\}}", text, re.S)
    if not m:
        print(f"FAIL: dict '{lang}' not found in src/lib/i18n.ts")
        sys.exit(1)
    dicts[lang] = set(re.findall(r'"([^"]+)":', m.group(1)))

errors: list[str] = []
base = dicts["en"]
for lang in ("pt", "es"):
    missing = sorted(base - dicts[lang])
    extra = sorted(dicts[lang] - base)
    if missing:
        errors.append(f"{lang} missing {len(missing)} keys: {missing[:10]}")
    if extra:
        errors.append(f"{lang} has {len(extra)} extra keys: {extra[:10]}")

print(f"keys: en={len(base)} pt={len(dicts['pt'])} es={len(dicts['es'])}")

accent = re.compile(r"[ãõçéêíóúâêôàüÁÃÕÇÉÍÓÚÂÊÔÀÜ]")
for f in sorted(SRC.rglob("*.tsx")) + sorted(SRC.rglob("*.ts")):
    if f.name == "i18n.ts":
        continue
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if accent.search(line):
            errors.append(f"{f.relative_to(ROOT)}:{i}: PT diacritic outside i18n.ts")

if errors:
    print("FAIL:")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
print("i18n OK")
