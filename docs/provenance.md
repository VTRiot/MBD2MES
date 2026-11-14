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

## アプリ部分の写し（GUI・対応表・設定・exe のビルド）

RCZ2MES の commit `5b31da804d8c6c2ad116d0b6103edd199255666f`（`5b31da8`）から、`tools/copy_app_from_rcz2mes.py`（`git show` で元の blob を取り、SHA-256 を記録。RCZ2MES は読むだけ）で元を取り、**手で直した**。
取った時点で、元 12 ファイルのうち 11 は作業ツリーが blob と同一、`dist_build/build_exe.bat` だけ改行の違い（blob は LF・作業ツリーは CRLF）だった。
区分「改変（手直し）」は、上の表の「import 行だけの改変」とは違い、中身を直している（改変の要点の欄）。`tests/test_provenance_app.py` が、写し先の SHA-256 が現物と一致することを確かめる。

| 写し先 | 元のパス | commit | blob の SHA-256 | 区分 | 写し先の SHA-256 | 改変の要点 |
|---|---|---|---|---|---|---|
| `mbd2mes/channel_map.py` | `C:\_Prog\ECU\Logger\RCZ2MES\channel_map.py` | `5b31da8` | `9ce4033f61fa8fef8bccb8c747a15dbf83f66ecb5479fb21e088282c94dc2d1b` | 改変（手直し） | `e23857bce439fd38a27464f3bc45db726d48893bf22d9d8f2cad25b70c4733c2` | 相対 import（`from . import config as cfgmod`・`from . import ddd_generator as gen`）・docstring の名前の置換。`output` の欄は持たない。ロジックは無改変 |
| `mbd2mes/config.py` | `C:\_Prog\ECU\Logger\RCZ2MES\config.py` | `5b31da8` | `60457e0f9016394d896546f3e1ec35f24ccc5ade537fa5b8f6354f941795d4bc` | 改変（手直し） | `8b1ebfa056d2b0224db12d636e3bd957bb6c328a3145f6d594fd84cb2155be19` | 名前を MBD2MES に（seed・config・プローブ・`%LOCALAPPDATA%\MBD2MES`・環境変数 `MBD2MES_SETTINGS_DIR`）。`app_base_dir()` の非 frozen はパッケージの 1 つ上。`last_rcz_dir`→`last_mbd_dir`。`default_rcz_dir` を削除。FB01: 一発変換の起点（`normalize_checkpoint_key`・`get/set/clear_batch_checkpoint`）を写し直し、schema の再初期化でも起点を引き継ぐ |
| `mbd2mes/map_rules.py` | `C:\_Prog\ECU\Logger\RCZ2MES\map_rules.py` | `5b31da8` | `ebe4089a894a7cde70d2e04e29e08e56d16199e00c337de669d39dfef034d913` | 改変（手直し） | `c82d7e5789c2e91af77f45ba9bd9b0d55e8933472c44f2ee8667b19f1b9f3aa4` | 保護する行・`make_apply_fn`（cp1252 で書けない候補を build_entries の前に外す）・`make_scaling_fn`・自動成長・`save_map_preserving_others`（新規）だけを残して書き直し。`output` の欄・`CAN_<id>` の移し替えを削除 |
| `mbd2mes/gui.py` | `C:\_Prog\ECU\Logger\RCZ2MES\rcz2mes_gui.py` | `5b31da8` | `78118a3de9cb8effaba4d830a4c9c1c307fcaa24e06392fc0b3f7562d6158edb` | 改変（手直し） | `937979acde951f0be09775bb29bbb0211dd2ef0593654b40b390e65c40c63363` | Convert・Channel Map・Other の 3 タブへ絞り、Output 列・RaceChrono Channel 列・マニュアルを削除。表の並び・検査・保存を Tk を使わない関数に分離。アイコンは `Pic\ICON`。FB01: 一発変換のボタンと確認の流れ（`_on_convert_unconverted`）・イベントフォルダ候補の行（Use This・Reload）・始まりのフォルダ `dialog_start_dir`（LD2MES の `_dialog_start_dir`）を写して足した |
| `mbd2mes/console_io.py` | `C:\_Prog\ECU\Logger\RCZ2MES\rcz2mes.py` | `5b31da8` | `97216ca2e363a7f731b5f8886cb57c984c94abea1b856fe94435528a6f7f80eb` | 改変（手直し） | `9b8c95c84335fcfc9d621fe869a6f7b85b3b107170765eac2c2774391274fdf9` | `_NullWriter`・`_stream_is_usable`・`ensure_console_for_cli`・`should_wait_for_enter`・`wait_for_enter` を切り出して写した（関数の中身は無改変） |
| `mbd2mes/version.py` | `C:\_Prog\ECU\Logger\RCZ2MES\version_info.py` | `5b31da8` | `3dfeadf885cbced21e39e3baf2290352a27af701a008c8397bebb5383fa677a0` | 改変（手直し） | `9c0f44e12f3a5243843e5a08fe80cfb7df733fa5bf25d8df10437703eb8106cb` | `APP_NAME`・`APP_VERSION`・説明だけ |
| `mbd2mes/race_env.py` | `C:\_Prog\ECU\Logger\RCZ2MES\race_env.py` | `5b31da8` | `4b465d87021abbc4cb6d22b491ff9d04fb11dc1a85adf31243596199cfc94b6b` | 改変（手直し） | `e9411af00780ce5ebf7f143b0fb1725441e7b0b589c1cdf33842184328be69ea` | FB01: 元の blob（RCZ2MES）は LD2MES から無改変で写された物。`ConfigParser(interpolation=None)`・`UnicodeDecodeError` を未検出として返す 2 点だけを直した版（`C:\_Prog\ECU\Car\LINK_LLGX2MES\race_env.py`・2026-10-18・元の SHA-256 は同じ `4b465d87…`・LF で保存）を、そのまま写した。% を含む値や cp1252 で読めないバイトで GUI が黙って止まる実害への直し（Codex の FB01 レビュー [1]・`docs/lessons_link.md`） |
| `mbd2mes/batch.py` | `C:\_Prog\ECU\Logger\RCZ2MES\rcz_batch.py` | `5b31da8` | `ef1ba555dda6826b14693ff6322fff15a3659db1f76c7262f3c787110c608d85` | 改変（手直し） | `cbeaed6a27a184be0c0701835e63eb4778ee41d54f55213a8be5c7a51e2c1264` | FB01: 一発変換。`.rcz` -> `.MBD`・名前の置換。セッションか否かの見分けを MBD のマジックと大きさだけに（`rcz_reader` を使わない）・SHA-256 を 1 MiB ずつの逐次読みに・変換を `app_convert.convert_many` 経由に・`date_for`（入力ごとの記録日。HED の日付の裁定待ちの差し込み口）を足した。台帳・判定表・起点・確認の文言の考え方は無改変 |
| `mbd2mes_app.py` | `C:\_Prog\ECU\Logger\RCZ2MES\rcz2mes.py` | `5b31da8` | `97216ca2e363a7f731b5f8886cb57c984c94abea1b856fe94435528a6f7f80eb` | 改変（手直し） | `6d53e99d9d2e3ee38dd28a46cb3ad91976d322cb266c06d8701d75aacf8a63d8` | 入口の分岐（引数なし = GUI、あり = CLI）と `run_cli` の骨格を MBD2MES の構成で書き直した（`rcz2mes.py` 末尾 `run_cli`・`__main__`） |
| `dist_build/mbd2mes.spec` | `C:\_Prog\ECU\Logger\RCZ2MES\dist_build\rcz2mes.spec` | `5b31da8` | `10b70e863341bae8903763662052a2b1581e9371ce7816c719f0a6aaaf53b82e` | 改変（手直し） | `0d912cbf5ac3dc1f553b3b5b746c89ba4292b8698d43519f38cb6382260ea894` | 入口・同梱（seed 2 つとアイコン）・名前。アイコンは `Pic\ICON\MBD2MES.ico` が無ければビルドを止める（既定のアイコンで黙って作らない） |
| `dist_build/build_exe.bat` | `C:\_Prog\ECU\Logger\RCZ2MES\dist_build\build_exe.bat` | `5b31da8` | `7982ef138d17003f091d1f25d5d7f1d35fe962a701b7295b829c5725a013d572` | 改変（手直し） | `b274553939f10602bf77cc1b8327ea31cb5637c36738f025deb13a606a1f3bdd` | 名前・アイコンの存在確認・exe のアイコンの照合の追加。ASCII + CRLF（元の blob は LF。作業ツリーは CRLF） |
| `tools/write_build_info.py` | `C:\_Prog\ECU\Logger\RCZ2MES\tools\write_build_info.py` | `5b31da8` | `79eb91f3ce1c580a6fe08a6b56f2388ad37d94a2d86e5aae8f49593abb9b3fea` | 改変（手直し） | `122534dea6b87ec1b016dcfe47a4b03a753fcff5512e87b4bee5243b5a952801` | `DIRTY_PATHSPECS` を MBD2MES の spec に合わせた・説明だけ |
| `tools/check_exe_version.py` | `C:\_Prog\ECU\Logger\RCZ2MES\tools\check_exe_version.py` | `5b31da8` | `86451588f6a6236b4cfa063c601f7488d0f3412bdc45f23dcf9e07e328c40d9d` | 改変（手直し） | `a9e596f402841e08340c3a29008efc1477a72e783483df1227390b6e6814a498` | exe の名前（`mbd2mes.exe`）・import 先・説明だけ |
| `mbd2mes_config.seed.json` | `C:\_Prog\ECU\Logger\RCZ2MES\rcz2mes_config.seed.json` | `5b31da8` | `7c14914fb5bc38e602b21ea3c6fdec664f8c4eb0719ab23626d6d8e6b0287743` | 改変（手直し） | `ae6b3c9dadede8aabd762cfabed5ac292e09649f48bdce69b4e386b18f382a22` | キーを `output_dir`・`last_mbd_dir` に（`default_rcz_dir` を削除） |

## 新しく書いたもの（アプリ部分）

| ファイル | 何か |
|---|---|
| `mbd2mes/app_convert.py` | GUI・CLI 共通の「複数本を順に変換する」層（`convert_many`）。1 件の失敗で止めない・上書きの確認・終了コード |
| `mbd2mes/dates.py` | 記録の日付の決め方（FB01 の 4・案 C）: 明示の指定 > ファイル名（基準は標本の `26.11.8…`）> 更新時刻（警告）。写しではなく新規 |
| `channel_map.seed.json` | 対応表の初期値（恒等）。`tools/make_channel_map_seed.py` が標本から一度だけ生成した（下の記録） |
| `tools/make_channel_map_seed.py`・`tools/copy_app_from_rcz2mes.py`・`tools/exe_icon.py` | seed の生成・元の blob の取得・exe のアイコンの照合 |

## 対応表の seed の生成記録

- 生成: `python -I tools/make_channel_map_seed.py <標本の .MBD（SHA-256 照合済みのコピー）> channel_map.seed.json`（2026-11-14）
- 入力の SHA-256: `089d052133ccd87a9d9d525563ccf3be5955bb644b98c0c71174cd0031f9982f`（標本 1 本。`CLAUDE.local.md` の値と同じ）
- 結果: 58 行（保護する GPS の 3 行 + 実際に書かれる 55 チャンネル）。生成物の SHA-256: `59cecf66fbce0a535e28ddf4676df2439299507657a2d3c7ddd1b559640699fb`
- 別の出どころとの突き合わせ: `tests/test_settings.py::test_seed_rows_match_appendix_a`（`docs/mbd_format.md` 付録 A の件数 > 0 の行から GPSspd・GPS ブロックを除いた集合 = seed の名前の集合）

## 追記の決まり

以後の案件で RCZ2MES から写すファイルは、この表に行を足す（元のパス・commit・blob と写した先の SHA-256）。
RCZ2MES から写さなかったもの: `tools/make_release.py`（ZIP の配布）・マニュアル・Output 列（Plan §12 の B2・B3）。B4 のうちイベントフォルダ候補（`race_env.py`）と一発変換（`rcz_batch.py` -> `batch.py`）は FB01 で写した。
