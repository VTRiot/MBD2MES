# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# 実データの標本（リポに入れない）。環境変数 MBD2MES_SAMPLE にパスを渡す。無ければ該当の試験は skip
SAMPLE_ENV = "MBD2MES_SAMPLE"


def sample_path():
    v = os.environ.get(SAMPLE_ENV)
    return Path(v) if v and Path(v).is_file() else None
