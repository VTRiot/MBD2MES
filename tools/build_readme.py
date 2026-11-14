# -*- coding: utf-8 -*-
"""tools/build_readme.py -- docs/readme_ja.src.html から、配る README.html（docs/readme_ja.html）を作る。

原稿の `{{VERSION}}` を APP_VERSION に、`{{IMG:<名前>}}` を docs/img/<名前>.png の data URI に置き換える（外部の物を読まない 1 枚の HTML）。
    python tools/build_readme.py           # 作る
    python tools/build_readme.py --check   # 作り直しが要るか（要れば 1 を返す）
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mbd2mes import version  # noqa: E402

SRC = ROOT / "docs" / "readme_ja.src.html"
OUT = ROOT / "docs" / "readme_ja.html"
IMG_DIR = ROOT / "docs" / "img"


def render() -> str:
    text = SRC.read_text(encoding="utf-8")
    text = text.replace("{{VERSION}}", f"{version.APP_NAME} v{version.APP_VERSION}")

    def img(m: re.Match) -> str:
        data = (IMG_DIR / f"{m.group(1)}.png").read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")

    text = re.sub(r"\{\{IMG:([A-Za-z0-9_]+)\}\}", img, text)
    if "{{" in text:
        raise SystemExit("unresolved placeholder in README source")
    return text


def main() -> int:
    text = render()
    if "--check" in sys.argv[1:]:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else None
        if current != text:
            print("docs/readme_ja.html is stale (python tools/build_readme.py)")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
