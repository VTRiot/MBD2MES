# -*- coding: utf-8 -*-
"""標本の MBD から対応表の初期値 channel_map.seed.json を作る（一度だけ回す。生成した seed を追跡する）。

  python -I tools/make_channel_map_seed.py <標本の .MBD（SHA-256 照合済みのコピー）> <出力 channel_map.seed.json>

行の名前は、実際に MES へ書かれる名前（channels.plan_channels の結果 + GPS の 3 本）。記録の無いチャンネルと GPSspd は入らない。
各行は恒等（unit/custom_name = null・multiplier 1.0・offset 0.0）で、raw_unit は MBD の単位（参照用）。
標本の SHA-256 と行数は標準出力へ出る（docs/provenance.md へ記録する）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mbd2mes import channels as chmod  # noqa: E402
from mbd2mes import gps_entries as ge  # noqa: E402
from mbd2mes.mbd_reader import read_mbd  # noqa: E402

GPS_ROWS = (("Latitude", "deg"), ("Longitude", "deg"), ("V_GPS", "km/h"))  # convert.py が書く単位
SCHEMA = 1


def build_seed(mbd_path: Path) -> dict:
    var = ge.get_variant(ge.DEFAULT_VARIANT)
    assert tuple(var.rename[k] for k in ("Lat_dez", "Lon_dez", "V_Sat")) == tuple(n for n, _u in GPS_ROWS)
    plans, _skipped, _warn = chmod.plan_channels(read_mbd(mbd_path))
    rows = list(GPS_ROWS) + [(p.name, p.unit) for p in plans]
    channels: dict = {}
    for name, unit in rows:
        if name in channels:
            raise SystemExit(f"duplicate channel name {name!r}")
        channels[name] = {"unit": None, "custom_name": None, "raw_unit": (unit or "").strip(), "multiplier": 1.0, "offset": 0.0}
    return {"schema": SCHEMA, "channels": channels}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    seed = build_seed(src)
    dst.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"input sha256: {hashlib.sha256(src.read_bytes()).hexdigest()}")
    print(f"rows: {len(seed['channels'])} (3 GPS + {len(seed['channels']) - 3} channels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
