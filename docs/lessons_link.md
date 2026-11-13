# 過去 PJ の教訓 — LINK_LLGX2MES（Link ECU .llgx -> 2D Analyzer .MES 変換）

## 本書の読者と目的

- 読者: MBD2MES の CC
- 目的: 先行の MES 変換 PJ で分かったこと・踏んだ地雷を、MBD2MES が同じ調べ直しをせずに使えるよう集める
- 出どころ: C:/_Prog/ECU/Car/LINK_LLGX2MES（読み取り専用）。2026-11-13 に三瀬谷のサブエージェントが読んで抜き出した二次資料。数値や行番号は使う前に出典で確かめる

## 概要

Link ECU(G4X Xtreme/PCLink 7.8.2)の .llgx ログを、MoTeC 用参考実装 Ld2MesConverter の出力系を流用して 2D の .MES フォルダ(DDD/CAL/A??)へ変換する Python/tkinter ツール。2026-10-17〜18 に解読・変換器・GUI・exe・テスト170件まで完成し、2026-10-18 に出力先修正をらいおがクローズ済み。
未解決は「2D Analyzer で実際に開けるか」(台帳 B1)と時刻軸の裁定(B2)。受理の結果報告は未受領で、完了とは宣言されていない。ただし RACE.INI の [START] Data=LINK-20261016-190850 に Analyzer が MES を開いた跡がある(002 報告)。2D で開けず失敗した例は記録に無い。
MBD2MES は入力形式だけ違う同型 PJ。「解読 -> 3関数契約のアダプタ -> 流用出力系 -> 不変量検査 -> 2D 実機ゲート」の型をそのまま写せる。

## 構成

- llgx_reader.py: .llgx パーサ(標準ライブラリのみ)。lf3/ld2/lm1/ds3 を読み LlgxLog(Channel/Segment/Marker)を返す。末尾ゴミ除外・区間分割・--summary/--csv
- llgx_adapter.py: reader の結果を出力系の3関数契約(parse_head/channel_meta/read_channel)へ写す。一様格子リサンプル・時刻軸再配置(block_uniform)・区間・hold・Log Segment・ID->ASCII名
- llgx_settings.py: 変換方針の定数(GRID_HZ=50、TIME_AXIS_MODE、MES名接頭辞、単位置換、量子化警告の閾値)
- llgx2mes.py: convert_one(唯一の入口)・convert_many・CLI・MES名決定・出力先4段決定・上書き処理・起動振り分け
- llgx2mes_gui.py: tkinter GUI(Convert/Channel Map/Other)、変換はスレッド+queue、出力先の Use This/Reload/Change
- mes_writer.py / mes_reader.py: 参考実装の逐語コピー。.MES(DDD/CAL/A??)の書き出しと読み戻し
- ddd_generator.py: DddEntry生成・名前一意化・gain/offset・基準Hz・sanitize_unit・量子化警告(参考を複製して改変)
- ddd_invariants.py: 変換ごとの不変量9種(名前長・単位安全・全A??サイズ一致・整数チャンネルの正確さ等)
- channel_map.py + channel_map.seed.json: 対応表と初期値(43ch)、auto-grow、破損退避・保存禁止(_SAVE_BLOCKS)
- config.py / version_info.py / race_env.py: 設定の原子的保存と破損退避、版名、2DのRACE.INIから出力先検出
- tools/: make_channel_map_seed.py(seed生成)、make_icon.py、write_build_info.py。dist_build/: PyInstaller spec と build_exe.bat
- tests/: 170件(test_fixes/test_real_logs/test_pipeline/test_resample/test_gui_dirs 他)。llgx_builder.py が仕様書から合成ログを書く
- _work/notes/: 仕様・調査・開発メモ。_work/scratch/: 使い捨て(約100本)。_work/verify/: 検証スクリプト。LOG/: 入力(読み取り専用)。out/: 試し出力

## 流用できるモジュール

- mes_writer.py: .MES フォルダ(DDD/CAL/A??)書き出し。参考 MoTeC 版からの逐語コピーで入力形式に非依存。2D が受理した書式定数を持つので変えずに写す(冒頭に来歴とSHA-256)
- mes_reader.py: MES 読み戻し(往復誤差検証用)。入力形式に非依存。cp1252 strict 固定の点に注意
- ddd_generator.py: メタ->DddEntry、名前の一意化・32byte、gain/offset(整数チャンネルは gain=1)、基準Hz選択、sanitize_unit(カンマ・引用符・制御文字の置換)、quantization_warnings。reader_module 引数で入力を差し替えられる
- ddd_invariants.py: 不変量9種(名前<=32byte、単位の安全、全A??のサイズ一致、整数チャンネルの正確さ等)。変換のたびに走る安全網
- channel_map.py + channel_map.seed.json の仕組み: 対応表(ID->ASCII名・単位・Custom Name・Multiplier/Offset・Enabled・補間方式hold)、auto-grow、破損退避・保存禁止の守り。seed の中身だけ MBD 用に作り直す(tools/make_channel_map_seed.py の『実ファイルからIDと単位を機械的に読み、英語名だけ手書き、ID並びが想定と違えば生成停止』方式)
- config.py / version_info.py: 設定の原子的書き込み・破損退避・%LOCALAPPDATA%フォールバック。APP_NAME 等の改名のみ
- race_env.py: RACE.INI から2Dの出力先候補を検出(cp1252・%・読めないバイトの修正済み版を写す)。2D側の仕様なので入力形式に無関係
- llgx2mes.py の骨格: convert_one(唯一の入口)・convert_many・CLI・MES名の決め方・出力先4段決定・上書きと旧A??の掃除・-n の名前検証
- llgx2mes_gui.py + dist_build(PyInstaller spec/build_exe.bat) + tools/write_build_info.py: 3タブGUI(Convert/Channel Map/Other)、スレッド+queue、Use This/Reload/Change の出力先設計。窓の文言と拡張子だけ差し替え
- llgx_adapter.py の設計(3関数契約 parse_head / channel_meta / read_channel の薄いアダプタ): 一様格子へのリサンプル、区間の扱い、hold、Log Segment 追加、未知ID->CH<ID>。reader を1回だけ読みキャッシュ。リサンプル・時刻再配置の式は MBD の時刻構造次第で再利用
- tests/ の型: llgx_builder.py(仕様書から合成バイト列を書く別実装)、test_zz_repo_state_untouched.py(実設定を触らない番人)、実ログの hash 識別、変異検査(_work/scratch/fix_mutation.py)、GUI自動操作(gui_autotest.py)
- 参考実装(読み取り専用): C:\_Prog\GMN_Gemini\04_Bike_Car\Ld2MesConverter\[MoTeC]Ld2MesConverter と、2D一次資料 HA22S_MoTeC_M130\Manuals\2D\(MES命名規則.txt, 2D_Logging_Data_Format_JP.txt)

## 教訓

### 2D実機受理は未確認のまま進んだ(最大の地雷)

機械検証(不変量・読み戻し誤差・テスト170件)は『2D が開く』ことを保証しない。LLGX2MES は 2D 実機確認(B1)を受け取らないまま実装・GUI・exe まで進んだ。MBD2MES は最初の数本の変換直後に、らいおに Analyzer で開いてもらう実機ゲートを最優先で組み込み、チャンネル一覧・波形・特殊チャンネルが出るかを先に確かめる。2D が開いたか否かの証跡は RACE.INI の [START] Data= にも残る。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_Prompt/02_buildai/LLGX2MES_001_impl_report.md L28,L121-127 / _Prompt/LLGX2MES_BOUND_PENDING.md B1 / 002_outdir_fix_report.md L95 / _work/notes/ref_architecture.md L254`
- 確度: 実測

### 未知バイナリの解読の進め方

(1) 先頭から末尾まで隙間なくブロック分割できるかで構造を確定し、長さ合計がファイル長に一致するかを検算する。(2) 3 本以上のサンプルで構造・チャンネル定義が同一か比べる。(3) 物理値の整合で意味を裏取りする(MAP-MGP=大気圧kPa、RPM/車速がギア別に一定、水温など)。(4) reader を使わず書いた最小の独立パーサで全チャンネルの値と時刻を照合する。(5) 『事実』と『推測』のラベルを仕様書に付ける。公開仕様は WebSearch 1 クエリで見つからず、全て実測だった。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/llgx_format.md L1-L8,L98-L104 / LLGX2MES_001_impl_report.md L103,L177`
- 確度: 実測

### Linkの .llgx 構造(MBD2MES の参考形)

ブロックは [u32 長さ(自身含む)][3文字タグ]。並びは lf3(215B)|ld2(7207B)|lm1(433B)xN|{ds3(645B)+(f32時刻,f32値)xcount}xC。文字列は UTF-16LE 固定長200B。日時はバイナリにあらず題名文字列にのみ有る。値は整数チャンネルも全て f32。MBD でも『固定長ブロック+タグ+長さ』を最初の仮説にすると解読が速い。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/llgx_format.md L9-L60 / llgx_reader.py L29-L63`
- 確度: 実測

### 時刻軸: 短い時刻刻みは実時間とは限らない

Link は『20ms x49 + 1ms x1』を繰り返す。時刻どおりに補間すると約1秒ごとに MAP・点火・回転数が1.4〜2.0倍の飛びを起こした(信号の変化量で検出)。時刻列の統計(平均周期19.6ms≠公称20ms)だけで信じず、短い刻みをまたぐ区間の値の変化量の比で実時間かを検証する。決着は外部時計(走行動画かラップタイム)と MES 長の比較で、これは未実施(B2)。MBD の時刻軸も同様に疑って検証すること。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_fix.md L10 / _work/notes/llgx_format.md L67-L68 / _Prompt/LLGX2MES_BOUND_PENDING.md B2`
- 確度: 実測(変化量の比)/推定(真の周期は未確定)

### 時刻軸の再タイミング: Resume 直後の短ブロックの詰め過ぎ

block_uniform の初版は Record Resume 直後の短いブロックを 1〜17ms に詰め潰した。区間の変わり目で先に区切り、区間内の典型ブロック長の0.2倍未満の短ブロックは次(無ければ前)へ併合してから等間隔に並べ直し、区間をまたぐ併合はしない方式に直した(TIME_MIN_BLOCK_FRACTION=0.2)。修正後の区間内最小刻みは公称の0.90〜0.91倍。補間の oracle は純Pythonの別実装で独立に書いて突き合わせる。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_fix.md L44-L67 / llgx_settings.py L38-L47`
- 確度: 実測

### 記録の中断・再開(Record Resume)と値の不連続

時刻は連続のまま、休止区間が詰められ値だけが不連続に飛ぶ。休止の実時間は不明。既定は MES を分割せず区間番号チャンネル(Log Segment、1始まりのステップ波形)を足し、区間をまたいで補間しない。MBD でも『ログの途切れ』『ラップ区切り』の有無を最初に実測し、補間が境界をまたがない設計にする。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/llgx_format.md L72-L76 / _work/notes/port_plan.md L55 / LLGX2MES_001_impl_report.md L86`
- 確度: 実測

### 非一様サンプル -> MES の一様格子

MES は時刻軸を持たず、チャンネルごとに一様周期の配列しか持てない。非一様なロガー(Link)は共通の一様格子(50Hz、基準400Hz÷除数8)へリサンプルが必須。連続量は線形補間、Gear・各Status・カウンタ等は直前値保持(0次)。『整数なら保持』の自動判定は連続量にも当たる(Engine Speed が全標本整数だった)ので、チャンネルごとに hold を対応表へ明示した。全チャンネルが共通格子なので長さは構成上一致する。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/port_plan.md L54 / dev_fix.md L12 (N3) / dev_core.md L47`
- 確度: 実測

### 2D は短いチャンネルを黙って捨てる

各チャンネルは周期x収録時間のサンプル数を持たねばならず、HED の Lap 宣言より短いチャンネルは 2D にエラーなく黙って捨てられる(V_Sat 消失として2026-09-04に実測)。参考実装の本番経路はこれを検査していなかったため、不変量 #8(全A??のサイズ一致、expected_samples指定で標本数x2byteまで)を追加した。MBD では全チャンネル同一長を不変量で毎回検査する。末尾ゴミ(file3)は reader 側で全チャンネル同数に揃えて除外する。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/ref_architecture.md L77 / dev_core.md L13 / port_plan.md L56`
- 確度: 実測

### チャンネル名は日本語を避け ASCII 名にする

2D 本体の既存 DDD 140,387 ch(1313本)に非ASCIIチャンネル名は0件。DDD は cp1252 で、cp1252 で書けない名前の基本チャンネルは参考実装でスキップされる(日本語名のチャンネルが大量に欠落する)。PCLink のチャンネルID(ds3+211)を ASCII 名へ写す表を seed に持ち、未知 ID は CH<ID> で必ず出す(黙って落とさない)。名前は 32 byte 以内(実在上限が32=推測の仕様)。日本語を 2D が表示できるかは未確認(U1)。MBD の名前が日本語・SJIS なら同じ対処が要る。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/ref_architecture.md L90-L101 / port_plan.md L58 / dev_core.md L53`
- 確度: 実測(既存DDD統計)/未確認(日本語が使えるか)

### 2D の特殊チャンネル名はこの PC の実イベントの EVENT.INI で確定する

初回は C:\RaceData の Event.ini だけを見て Car-Speed を当てたが誤り。実際に使う車の C:\RACEDATA\04_HA22S\26\*\EVENT.INI(8本、2D が MES を受理した実績あり)は DRIVE_SPEED=VEHICLE.SPEED、MILEAGE_SPEED=CAR-SPEED、DRIVE_RPM=RPM、THROTTLE=THROTTLE だった。元チャンネルを残したまま別名チャンネルを足す(43+4+Log Segment=48ch)。MBD2MES でも対象車のイベントの EVENT.INI を読んでから名前を決める。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_fix.md L11 / dev_core.md L60 / LLGX2MES_001_impl_report.md L88`
- 確度: 実測

### MES 名の衝突(ファイル名由来は全滅)

ファイル名どおりだと3本とも ECU-Log-2026-10-16-19 に潰れて衝突し、参考のバッチは全件保護で全滅する。ログ内の題名の日時から LINK-YYYYMMDD-HHMMSS を作る(題名が読めなければ更新日時、それも衝突なら連番 -2,-3)。ただしこれは PCLink が保存した時刻で走行時刻ではない(題名の時刻が43秒間隔でログ長と重なる)。-n の名前は検証し、出力先の外を指す ..\evil/x を拒否する。MBD のファイル名・内部日時の取り方を先に実測する。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/ref_architecture.md L103 / dev_fix.md L14,L20 / llgx2mes.py:135,149`
- 確度: 実測

### 単位: 量の種類名と実単位が混在・cp1252/カンマ問題

Link は単位欄が実単位と『量の種類名』(Pressure/Temperature/Speed/Lambda)の2種類で、後者の実単位(kPa/degC/kph)は物理整合から推測した。推測した単位は seed に明示し対応表で直せる形にする。DDD の4=項はカンマ区切りなので、単位の , を ; に、" を ' に、制御文字を _ に置換する(参考実装に無かった欠陥)。cp1252 で書けなければ単位を空にして警告し、チャンネルは残す。基準単位が PCLink の表示設定に依存しうる点は未検証。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/llgx_format.md L96-L111 / port_plan.md L61-L62 / dev_core.md L55`
- 確度: 実測(置換)/推定(実単位)

### 値の量子化: 整数チャンネルは gain=1 で正確に書く

W/16bit 固定で gain=(hi-lo)/65535 とすると、整数チャンネル(Gear 等)の復元値が float32 丸めで非整数になる。整数チャンネルは gain=1・offset=最小値にして不変量#9で検査。Gear Ratio Calc のように車速ほぼ0の発散値でレンジが広がると量子化が粗くなる(0.3〜1%)。量子化警告は gain が元データの最小識別幅の(1+1e-3)倍を超えたときに出す(変換は止めない)。NaN/inf は参考実装では黙って0化されるので直前の有限値で保持し件数を警告する。読み戻し誤差は最大0.502LSBを実測。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_fix.md L13 / dev_core.md L51-L52,L91 / ref_architecture.md L68-L69`
- 確度: 実測

### 設定・対応表の破損や排他ロックで黙って上書きしない

壊れた対応表・設定が黙って空表や初期値に上書きされる事故が独立検証で出た。直し型は、壊れたファイルは .corrupt-日時 へ退避(同一SHA-256なら増やさない)、退避や作り直しに失敗したら元ファイルに触れずメモリ上の seed で続行し、そのパスへの保存を禁止して通知し、書き込み関数は save_map と merge_and_save_map の2つだけに限定して冒頭で保存禁止を引く。禁止の理由は辞書の鍵ではなくパスごとのモジュール状態に置く(Reset All で消えた事故)。OSError(読めない)と ValueError(壊れている)を同じ except に入れない。実ロックの CreateFileW で試験した。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_fix.md L15-L16,L88-L89,L124-L126`
- 確度: 実測

### RACE.INI(2D の設定)の読み: cp1252・%・日本語

参考実装の race_env.py は、RACE.INI に cp1252 で読めないバイト(「ー」等)や % があると例外で GUI が起動時に黙って落ちた(exe は無言)。interpolation=None にし、読めないバイトは理由付き not detected で返すよう直した。文字コードは cp1252 のまま(2D が何で書くかは未確認)。出力先候補は RACE.INI の [START] EVENT と [DATADIR] 0 から出す。イベントを作るのは WinARace で Analyzer ではない(報告書で取り違え→訂正)。Use This は表示どおり、読み直しは明示の Reload ボタンのみ、という設計がらいおの指摘で固まった。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_Prompt/02_buildai/LLGX2MES_002_outdir_fix_report.md L29-L72 / race_env.py`
- 確度: 実測

### 検証の独立性: 同語反復を避ける

期待値を実装と同じ式で作らない。合成 .llgx は仕様書からバイト列で書く別実装(tests/llgx_builder.py)、標本数は元ログの最終時刻から手計算、補間の oracle は純Pythonの別実装、解読は reader を使わない最小パーサ。数値の独立検証と修正後の再検証は実装と別のモデル(Opus)に反証させ、実装・GUI・レビューは Sonnet 5.5 medium。独立検証の指摘は合計22件(major 6)。新しいテストは直す前のコードで落ちること、変異検査(意図的に壊して落ちること)で検出力を確認する。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_Prompt/02_buildai/LLGX2MES_001_impl_report.md L101-L112,L139-L148 / dev_fix.md L36-L43 / _work/notes/ref_architecture.md L251`
- 確度: 実測

### GUI 3経路を convert_one に一本化し変換はスレッドで

GUI・CLI・exe アイコンへのドロップは全て convert_one(convert_many) を通し、出力が byte 同一であることを自動操作試験で確認した(150ファイル)。変換は threading+queue で UI を固める。引数起動は『オプション無しで .llgx のパスだけ』なら GUI に入れ、オプションがあれば CLI、という振り分けにした(従来のオプション無しCLI動作が変わる点に注意)。exe 上でボタンを押す変換は未自動化で、人の確認項目として残った。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_gui.md L23-L47,L89-L93 / dev_core.md L28-L41`
- 確度: 実測

### HED/LAP/IXR は書かない・参考の書式定数は変えない

2D は MES を開くとき .HED([Laptimes]のみ46〜47byte)を自分で足す。DDD の未解読定数(1=,2=,3=,5=,7=)の2D受理は多くが A/B 未了で、変えると未検証領域に入るため参考の定数を変えない。実機受理の実績は W/16bit・基準400Hzが中心。F/32bit・他の基準Hz・日本語名は未確認(U1〜U3)。ラップ表示を HED 無しで使えるか(U6)も実機未確認。MBD にラップ情報があっても初版は書かない方針の根拠はここ。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/ref_architecture.md L37,L54,L61,L273-L277 / port_plan.md L63`
- 確度: 実測(書かない)/未確認(2D側の受理)

### 他の版・他機種は未検証(過信しない)

解読は G4X Xtreme / FW 6.31.2 / PCLink 7.8.2 の3本のみ。count や ID の幅(u16/u32)、0領域の用途、休止の実時間は不明。MBD2MES も、提供された1本の .MBD だけで形式を決め打ちせず、未検証の版は『失敗・警告が出たら掘り起こす』の放置ラベルで台帳に載せる。サンプル数が少ないほど『隙間なく分割できた』『3本同一』の裏付けが取れない点に注意。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/_Prompt/LLGX2MES_BOUND_PENDING.md B5 / _work/notes/llgx_format.md L106-L112`
- 確度: 実測

### 入力ログはコピーして触り、実データは hash で識別

LOG/ は読み取り専用・書換禁止。ファイル名は全角数字を含み Python では glob で拾う。実データはファイル名でなく SHA-256 で識別し、CLAUDE.local.md に3本の hash を控えた。試験は設定・対応表の写し(サンドボックス)で行い、全試験の前後でリポジトリ直下の channel_map.json と設定ファイルが不変であることを test_zz_repo_state_untouched で番人する。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES/CLAUDE.local.md L6-L14 / tests/test_zz_repo_state_untouched.py / port_plan.md L45`
- 確度: 実測

### git 管理が無く .bak 運用が膨らむ

新 PJ は git 管理なしで .bak 運用にしたため、直下に .bak〜.bak7 が大量に残り、_work/scratch に使い捨て修正スクリプトが約100本(fix_edit_*.py, rv2_edit*.py)溜まった。MBD2MES は git 初期化の可否を最初に決め、.bak と使い捨てスクリプトの置き場・掃除の方針を先に決める。

- 出典: `C:/_Prog/ECU/Car/LINK_LLGX2MES (ls で .bak 系を確認) / _work/scratch/`
- 確度: 実測

## 運用の決まり

- グローバル MANX 準拠(CLAUDE.md は CCPIT managed): 完了は実機で動くまで宣言しない。テスト PASS は完了条件でない。3階層 Before/After(コード/実機UX/ユーザーFB)を報告書に書く。報告書は _Prompt/02_buildai/ に MD、冒頭に『本報告書の読者と目的』
- LLGX2MES は『ユーザー FB 未受領。受け取るまで完了とは言わない』と明記して止めている(001報告 3階層表)。002 出力先修正だけらいお『動いてるっぽいなー。本件一旦Closeします。』で2026-10-18にクローズ
- PJ 定義は _Prompt\03_prj\ の最新 rev を参照(CLAUDE.md L13)。ただし実際には 03_prj は存在せず、_Prompt 配下は 02_buildai と BOUND_PENDING.md のみ
- 必ず対応するリスト _Prompt/LLGX2MES_BOUND_PENDING.md(B1〜B7): 玉は『踏み抜く(誰が・いつ)』か『放置(理由+再起動条件)』の二値で台帳に持つ。報告書の外で管理
- 入力 LOG/ は読み取り専用・書換禁止。参照・試験はコピーかサンドボックスで。実データは SHA-256 で識別。参考実装・HA22S も読み取り専用で、流用は複製してから改変し、冒頭 docstring にコピー元パスとSHA-256を記録
- 編集前に必ず .bak を取る(既存 .bak は上書きしない)。git 管理なし。使い捨てスクリプトは _work/scratch、メモは _work/notes
- サブエージェントの既定は Sonnet 5.5(effort medium)。数値の独立検証と再検証だけ Opus(実装と別モデルで反証させる)。独立検証 -> 修正 -> 再検証を3周回した(ワークフロー5本・延べ14体・約270万トークン)
- 単体テストは python -W error::DeprecationWarning -m unittest discover -s tests をプロジェクト直下で実行(170件)。期待値は実装と同じ式で作らない。新テストは直す前のコードで落ちることを確認
- 配布: PyInstaller 単体 exe(windowed・約24MB・dist\llgx2mes.exe)を dist_build\build_exe.bat でビルド。exe の出力は Python 直実行と byte 同一(150ファイル)であることを毎回確認。exe は隣に channel_map.json 等を作るので、試験は exe の写しで走らせ dist の実体を触らない。他人へ配る ZIP・マニュアル・一発変換は『放置、らいおが要望したとき』
- 起動は LLGX2MES.bat(pythonw)・dist\llgx2mes.exe・python llgx2mes.py <files> -o <dir> の3経路。出力先は 2D のイベントフォルダ(WinARace が作る。RACE.INI で検出)
- 削除は承認事項: _work 配下の残り物・.bak は消さず、要らなければ言ってほしいと報告する
- HTML 報告書は md-render(md2html.cjs)で生成・--lint/--verify。報告書末尾に用語集。コメント対応は comments_resolved に3部形式で記録(グローバル dogfood ルール)

## 読むべき文書

- C:/_Prog/ECU/Car/LINK_LLGX2MES/CLAUDE.md — PJ 概要・変換の既定方針・構成表(2026-10-17/18 時点。最初に読む)
- C:/_Prog/ECU/Car/LINK_LLGX2MES/CLAUDE.local.md — 作業メモ、3ログのSHA-256、サブエージェント既定モデル
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/llgx_format.md — 未知バイナリ解読の仕様書(事実/推測ラベル、時刻刻みの訂正、Resume・末尾ゴミ)。MBD の解読仕様書の雛形
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/ref_architecture.md — 参考実装の構造マップ。MES形式(DDD節・A??・gain/offset・基準Hz・名前制約)と未確認事項 U1〜U6 の正本。MES形式の知見の最重要ソース
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/port_plan.md — 移植計画。論点 L1〜L14(受け皿付き)・検証計画 A1〜A8・工程。MBD2MES で論点を同じ型で立てるひな型
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_fix.md — 独立検証の指摘16件+追加修正3回の記録。時刻軸・保存禁止・特殊名の地雷の根拠(最も地雷が多い)
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_core.md — 変換コアの実装位置(ファイル:行)・API・警告の中身
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/dev_gui.md — GUI・exe・起動振り分けの設計と未確認事項
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_work/notes/llgx_channels.md — 43ch の一覧(ID・名前・単位・範囲)。seed 作成の入力例
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_Prompt/02_buildai/LLGX2MES_001_impl_report.md — 初版の最新・完了報告(決めた既定と理由、3階層Before/After、確認待ち)
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_Prompt/02_buildai/LLGX2MES_002_outdir_fix_report.md — 出力先修正の最新 rev3・クローズ済み(RACE.INI・Reload 設計・WinARace)
- C:/_Prog/ECU/Car/LINK_LLGX2MES/_Prompt/LLGX2MES_BOUND_PENDING.md — 必ず対応するリスト B1〜B7(2D実機受理・時刻軸・同名上書き等の残り玉)
- C:/_Prog/ECU/Car/LINK_LLGX2MES/llgx_settings.py — 変換方針の定数集約(TIME_AXIS_MODE・GRID_HZ・MES名・単位置換)
- C:/_Prog/ECU/Car/LINK_LLGX2MES/llgx_reader.py — .llgx パーサ(標準ライブラリのみ、--summary/--csv、L29-L63 に形式定数)
- C:/_Prog/ECU/Car/LINK_LLGX2MES/llgx_adapter.py — 非一様->一様格子、区間、3関数契約のアダプタ
- C:/_Prog/ECU/Car/LINK_LLGX2MES/tests/llgx_builder.py — 仕様書から書く合成ログの別実装(同語反復回避の型)
- C:/_Prog/ECU/Car/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter — 参考実装本体(誤記注意: 実パスは C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter。読み取り専用。角括弧のパスはクォート必須)
- C:/_Prog/ECU/Car/HA22S_MoTeC_M130/Manuals/2D/ — 2D 一次資料(MES命名規則.txt、2D_Logging_Data_Format_JP.txt)。読み取り専用
