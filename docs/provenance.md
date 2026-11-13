# 写したファイルの由来（provenance）

RCZ2MES の MES 書き出し部を、このフォルダへ**写して**使う（RCZ2MES を import しない。`sys.path` に足さない）。
写した元は RCZ2MES の commit `5b31da804d8c6c2ad116d0b6103edd199255666f`（2026-10-20 15:05 +0900 の HEAD。`git -C C:/_Prog/ECU/Logger/RCZ2MES log -1`）。
写しは `git show 5b31da8:<file>` の出力（LF の blob）。写したのは `tools/copy_from_rcz2mes.py` で、RCZ2MES は読むだけ（`git show` のみ）。
写す時点で、対象 8 ファイルの作業ツリーは HEAD と差が無かった（`git diff HEAD --stat` が空）。

- 「blob の SHA-256」は commit `5b31da8` の中身（LF）。「写した先の SHA-256」はこのフォルダのファイル。
- 区分「無改変」は、写した先 = blob（`tests/test_provenance.py` が照合する）。
- 区分「改変」は、パッケージ内の相対 import に直した行だけが blob と違う。それ以外の行は一致する（同試験が、blob の代わりに「import 行を戻すと記録の blob の SHA-256 になる」ことで確かめる）。
- 元の RCZ2MES は、さらに LD2MES（`0160cf0`・`da75b27`）から `mes_writer.py`・`ddd_generator.py`・`ddd_invariants.py`・`mes_reader.py` を無改変で写している（`C:/_Prog/ECU/Logger/RCZ2MES/docs/provenance.md`）。ここへは RCZ2MES を経由して来た。

| 写した先 | 元のパス | commit | blob の SHA-256 | 区分 | 写した先の SHA-256 | 改変の要点 |
|---|---|---|---|---|---|---|
| `mbd2mes/mes_reader.py` | `C:\_Prog\ECU\Logger\RCZ2MES\mes_reader.py` | `5b31da8` | `3d1410c3f67d7f7ec2a49afa357063904c772eb2898adce04247ba156d7e00fe` | 無改変 | `3d1410c3f67d7f7ec2a49afa357063904c772eb2898adce04247ba156d7e00fe` | - |
| `mbd2mes/mes_writer.py` | `C:\_Prog\ECU\Logger\RCZ2MES\mes_writer.py` | `5b31da8` | `f813c2f32537e0ed0fb81882162eaef5012e0837d2346b524e8659181ccc6b26` | 改変 | `a58113fc43219ea7fb391a1b94a3db5157477ec6163fc40f72e58d61ab23982b` | import 行だけ: `from . import mes_reader as mr` |
| `mbd2mes/ddd_generator.py` | `C:\_Prog\ECU\Logger\RCZ2MES\ddd_generator.py` | `5b31da8` | `9d82aecd198b932e82b3682d8160c285dac7622ceb1637421257438accca6320` | 改変 | `7c4c952ce44484b7deccd6f847bda323c17e43115bd8a12a37fb43374a1c510c` | import 行だけ: `from . import mes_reader as mr` / `from . import mes_writer as mw` |
| `mbd2mes/ddd_invariants.py` | `C:\_Prog\ECU\Logger\RCZ2MES\ddd_invariants.py` | `5b31da8` | `bcacd24e201e56d747456181d94fa5d5992bffcb71557d6c98b4f5f00fca57ee` | 無改変 | `bcacd24e201e56d747456181d94fa5d5992bffcb71557d6c98b4f5f00fca57ee` | - |
| `mbd2mes/gps_entries.py` | `C:\_Prog\ECU\Logger\RCZ2MES\gps_entries.py` | `5b31da8` | `437d54b1c8e6a101fc1264ede8ff36dbd043107195dea87ef08c393d6ebb6a32` | 改変 | `87f0e79edf909cb027932c65f5932dbe41df19f8294c6a4c9c99eb25e4b545c8` | import 行だけ: `from . import ddd_generator as dg` / `from . import mes_reader as mr` |
| `mbd2mes/hed_download.py` | `C:\_Prog\ECU\Logger\RCZ2MES\hed_download.py` | `5b31da8` | `5812017117a56b80a75d56c2fb699127506701ea38b992543eb949f417d1d06f` | 改変 | `0ed826ade2631dead43985a0ff066de9020bb3e6f5d91017d29fd79284fb7b6e` | import 行だけ: `from . import gps_entries as ge` |
| `mbd2mes/lap_files.py` | `C:\_Prog\ECU\Logger\RCZ2MES\lap_files.py` | `5b31da8` | `4d0faae3723b361910d7858cdfe0e5d7c9e56a1233de062ce5db5655353e5f23` | 無改変 | `4d0faae3723b361910d7858cdfe0e5d7c9e56a1233de062ce5db5655353e5f23` | - |
| `mbd2mes/event_ini.py` | `C:\_Prog\ECU\Logger\RCZ2MES\event_ini.py` | `5b31da8` | `8fbc3d6a338382e67db0791718d12be614968761730837d8cfad94938f30eafe` | 無改変 | `8fbc3d6a338382e67db0791718d12be614968761730837d8cfad94938f30eafe` | - |

## 写さずに新規に書いたもの（入力側と、MBD に合わせた部分）

| ファイル | 何か | 参照した元（読んだだけ） |
|---|---|---|
| `mbd2mes/mbd_reader.py` | MBD の読み取り | `C:/RagVault/VehicleDevelopment/ECU開発/ロガー_HRC_MBDA2/mbd_dump.py`（形式仕様 `docs/mbd_format.md`）。参照実装の考え方を写し、numpy で GPS を一括に・失敗を例外に・定数に名前を付けて書き直した |
| `mbd2mes/channels.py` | 換算・符号 | `docs/mbd_format.md` §6 |
| `mbd2mes/timeline.py` | 零次ホールドで格子へ | `RCZ2MES/rcz_timeline.py` の `sample_count`（同じ式 ceil(T×レート/1000)）と基準 400 Hz の考え方。補間はしないので別に書いた |
| `mbd2mes/laps.py` | コントロールラインの通過からラップ | `RCZ2MES/lap_sections.py` の形（境目 N 本 = Analyzer は N+1 本・標本番号 = floor(t×Hz+0.5)・地球の半径 6371008.8 m）。線の通過は MBD のヘッダの 1 本の線から求める別実装 |
| `mbd2mes/convert.py` | 変換の本体 | `RCZ2MES/rcz2mes.py` の `convert_one` の骨格（作業フォルダで完成してから入れ替え・不変量の門・記録ファイル・`--force`）。入力側は新規 |
| `mbd2mes/__main__.py` | CLI | `RCZ2MES/rcz2mes.py` の `main`（引数は MBD 用に絞った。GUI・D&D・exe は未着手） |

## 追記の決まり

以後の案件で RCZ2MES から写すファイルは、この表に行を足す（元のパス・commit・blob と写した先の SHA-256）。
RCZ2MES から写さなかったもの（今回）: `config.py`・`channel_map.py`・`map_rules.py`（対応表）、`rcz2mes_gui.py`・`rcz_batch.py`（GUI・一発変換）、`race_env.py`、`version_info.py`、`dist_build/`・`tools/`（exe・配布）。
