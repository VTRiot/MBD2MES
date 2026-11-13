# 過去 PJ の教訓 — Ld2MesConverter（MoTeC i2 の .ld を 2D Analyzer の MES へ変換。リポジトリ名 LD2MES_Converter）

## 本書の読者と目的

- 読者: MBD2MES の CC
- 目的: 先行の MES 変換 PJ で分かったこと・踏んだ地雷を、MBD2MES が同じ調べ直しをせずに使えるよう集める
- 出どころ: C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter（読み取り専用）。2026-11-13 に三瀬谷のサブエージェントが読んで抜き出した二次資料。数値や行番号は使う前に出典で確かめる

## 概要

MoTeC .ld（M1 ECU と C125 Dash）を 2D Analyzer の .MES フォルダ（DDD+A??+CAL+HED）へ変換する Python/tkinter ソフト。GUI・D&D・CLI の 3 経路が同じ convert_one を通り、対応表・派生チャンネル・RaceChrono GPS の時刻合わせとマージ・ラップ(.IXR)/セクター(.STI)のコース別コピー・配布 ZIP まで作り込み済み（v0.12.0、a84935d、2026-10-21 に店じまい、発注待ちなし）。
MES の「書き方」の知見（DDD の項目割り当て・gain/offset の符号化・ext 命名・サンプル数規則・GPS の地図が出る形・IXR/STI の符号化・Analyzer 受理の経緯）が mes_writer/ddd_generator/gps_channels/lap_files に入力形式非依存でまとまっており、MBD2MES は入力側（MBD 解析）だけ新規に作ればよい。入力リーダ（motec_ld_reader）は MoTeC 固有で流用不可。
注意: 数値を直す前に Analyzer 受理の根拠が「未確認」の定数が多い（ddd_generator の定数台帳）。MBD2MES でも最初の試験は必ずコピーで、Analyzer を開くと副作用が出る。

## 流用できるモジュール

- mes_writer.py（341行）: DDD テキストの書き出し(render_ddd_text_reconstructed)・gain/offset の float32 16進符号化・encode_channel_data（raw=(物理値-offset)/gain、整数型は丸め＋クリップ）・write_reconstructed_mes・n_samples_for_duration。入力形式を一切知らず mr.DddEntry だけを受けるので MBD2MES にそのまま写せる。理由: Analyzer が受理済みの書式（CRLF・cp1252・空行・0x7F）の知見が全部入っている。mes_reader.py(280行)の DddEntry データクラスとセット。
- ddd_generator.py（566行）: 入力メタ(name/unit/freq/values)から DddEntry を作る make_entry/build_entries、choose_base_hz、unique_names（32byte 一意化）、sanitize_name/unit、gain_offset_for、data_ext_for、定数台帳。入力は reader_module.channel_meta()/read_channel() という 2 関数のインタフェースだけなので、MBD リーダをこの形で用意すれば build_entries が再利用できる。理由: テンプレート非依存の生成と定数の出所が整理済み。
- ddd_invariants.py（177行）: DDD の独自直読みによる不変量 5 項目チェック。入力形式非依存で完全に流用可。
- lap_files.py（85行）: .IXR/.STI の符号化(encode_ixr/encode_sti)。MBD にラップ情報があれば即使える。写し元の commit・SHA-256 を docstring に残す方式も踏襲。RCZ2MES と共通部品なので三つ目の写しになる点は同一部品の重複管理に注意。
- gps_channels.py（約200行以降を含む）: 地図の出る GPS 6 チャンネルの DDD 定義・機器の印・HED [GPS] 節・merge_hed_gps。MBD に GPS が含まれるなら流用。外部 GPS との時刻合わせ(gps_sync.py 969行・gps_merge.py 989行)は MBD が自前 GPS を持つなら不要。
- race_env.py（111行）: 2D の RACE.INI から出力先候補を検出（読み取り専用）。入力非依存で流用可。
- config.py（349行）の frozen/非frozen 判定 app_base_dir・exe 隣→%LOCALAPPDATA% フォールバック・原子的 JSON 書き込み(_atomic_write_json)、channel_map.py（500行）の seed+実効 2 層の対応表と autogrow、ld2mes.py の ensure_console_for_cli と convert_one 集約パターン、batch_converter.py の台帳方式一発変換、tools/make_release.py・check_exe_version.py・write_build_info.py・build_manual.py の配布一式、tests/test_zz_repo_state_untouched.py と tests/lapfile_readback.py の別実装読み戻しパターン。いずれも MoTeC に依存せず、理由: 配布・設定・GUI/CLI 集約の型が実機で検収済み。
- 流用しないもの: motec_ld_reader.py（MoTeC .ld 構造体専用・MBD には使えない）、derived_*（足の踏み量復元の表引き。MBD で必要が出たときだけ）、rcz_reader.py/course_*（RaceChrono RCZ 前提）

## 教訓

### MES 構造とサンプル数（最重要の地雷）

MES の各チャンネルは「レート×時間長」のサンプル数でなければならない。全チャンネルを同数で切り出すとレート差で実時間長が食い違い、HED/最長より短いチャンネルは Analyzer にエラー無く黙って捨てられる（V_Sat 消失で実測）。n_samples_for_duration(hz, dur)=round(hz*dur)。MBD の各チャンネルのレートが違うなら最初にここを守る。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/mes_writer.py:48-57`
- 確度: 実測

### DDD の書式（バイト単位）

DDD は cp1252・CRLF・各節の後に空行 1 行（欠くと元ファイルとバイト一致しない・実機確認レビューで判明）。節ヘッダは [hex]（大文字・先頭 0 詰めなし）、生成側の節 ID は 0x300 + (通し番号-1)、データ拡張子は A01..A0Z,A10.. の base36 2 桁（上限 1295）。キーは数値キー 1..7 昇順→文字キー('A','Stamp')。[Additional] 節は素通しで保持。name 欄は 32 byte 制限、空欄は 0x7F。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/mes_writer.py:79-118 ; ddd_generator.py:82-85,244-255`
- 確度: 実測

### DDD の gain/offset 符号化

3= の第4/第5フィールドは ビッグエンディアン IEEE754 float32 の 16 進・大文字・先頭ゼロ省略（offset=0.0 は "0"、"00000000" ではない。実機ground truth突合で判明）。物理値=生値*gain+offset。float64（9〜16桁）の gain/offset を持つ実機 DDD があり float32 前提だと struct.error で落ちる（読む側の注意）。gain が float32 でアンダーフローして 0 になる/ offset が非有限になる入力は書く前に拒否する。gain=0 は非可逆なので書かず例外にする。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/mes_writer.py:181-190,293-318 ; ddd_generator.py:358-420 ; C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ.md:43-49`
- 確度: 実測

### テンプレート位置継承の禁止

Demo-CAR.DDD の i 番目節をテンプレにして書き換える方式は、無関係チャンネルに非表示フラグ等を貼り付け、83ch 中 37ch が非表示のまま出る事故を起こした（読み戻し検証では検出不能）。以後テンプレート非依存で、各フィールドを「入力から生成」か「定数＋出所明記」で組む。MBD2MES も最初からこの方式にする。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_generator.py:1-33`
- 確度: 実測

### 定数台帳（Analyzer 受理が未確認の値）

1= の第1欄 '4'（可視種別・1000x 系は非表示）、2=/7= 全ゼロ、5= 第2欄 '51'、6= の '2D'、3= の末尾定数などは「実走 DDD の多数決」であり Analyzer 受理は A/B 未確認として台帳化されている。意味は未解読。MBD2MES は同じ定数を流用してよいが、表示がおかしいときの A/B 代替値（コメントに列挙済み）から試す。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_generator.py:35-80`
- 確度: 実測（出所）／未確認（Analyzer 受理）

### base_hz と divisor

基準 Hz は 400/800/1000/2000 の候補から「全チャンネルのレートが割り切れる最小」を選び、割り切れないレートのチャンネルはスキップして理由を記録する。divisor=base_hz/rate、基準 Hz は DDD の 1= 第7欄（16進）。派生/追加チャンネルを足しても base_hz は既存チャンネルのレートだけから決め、変えない。MBDA2 のサンプリングレートが 400 の約数系に乗るか最初に実測すること（800 は実走ログで受理実績あり、1000/2000 は未検証）。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_generator.py:76-80,136-162,365,433-441`
- 確度: 実測（800）／未確認（1000・2000）

### データ型の制限

生成側は全チャンネル u16(bit_width=0x10, dtype 'W')固定で、実レンジ[lo,hi]を 0..65535 へ線形写像する（gain=(hi-lo)/65535, offset=lo-gain*min）。定数チャンネルは gain=1, offset=定数、raw=0。非有限値(NaN/Inf)は写像で壊れる。32bit は GPS 専用の make_wide_entry だけ（6= 第1欄 FFFFFFFC、符号なし・負は 0 に黙って切られる）。MBD の高分解能チャンネルで精度が要るなら dtype F/32bit 経路は未整備。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_generator.py:295-345 ; gps_channels.py:28-122`
- 確度: 実測

### チャンネル名・単位のサニタイズ

名前の , " と制御文字は _ に置換。cp1252 で書けない文字（日本語等）を対応表の任意名に入れると DDD 全体のエンコードで UnicodeEncodeError になる実バグがあったため、書く前に cp1252 検査して不能ならそのチャンネル（または単位だけ）を理由付きでスキップする。名前衝突は 32 byte 内で末尾 _ 反復により一意化（既存名は動かさず入力順に解消）。MBD のチャンネル名が日本語/空の場合を最初に洗うこと。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_generator.py:106-133,258-292,478-519`
- 確度: 実測

### DDD 不変量チェック

生成物の自己検査として ddd_invariants が DDD を reader 非経由の独自正規表現で直読みし、(1) 可視種別と 10000 以上の非表示がない (2) データ拡張子が空/不正/重複でなくファイルが実在 (3) name 一意 (4) 通し番号集合が 1..N (5) 節 ID の一意（16進正規化後も）を検査する。reader が読み捨てた行も検査対象にするための設計。1= 第1判定は自ツール出力専用（他ツール由来 DDD には不適用）。MBD2MES は入力形式に依存せずそのまま流用できる。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_invariants.py:1-177`
- 確度: 実測

### M1 と C125 の .ld の違い（入力解析の教訓）

.ld のチャンネルヘッダで offset+64 の 8 byte と offset+72 の 12 byte の用途がロガー種別で異なる（M1=単位が+64・+72 は空、C125/標準Dash=短縮名+64・単位+72）。「M1 だけを標本に+72 は常にゼロ」と誤認して C125 で短縮名が単位欄に入る不具合を出した。入力ロガー機種ごとにヘッダレイアウトの検証サンプルを必ず複数機種で持ち、機種判定はヘッダの device 文字列で一次判定、未知機種は保守的に空単位にする。MBDA2 でも「1 機種の標本から決め打ちしない」が教訓。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/motec_ld_reader.py:11-20,55-134`
- 確度: 実測

### 未対応データ型の扱い

ECU ログの Lap.Beacon Ticks が型 6（dtype_a=6）で未対応だったが、変換経路は read_channel の ValueError を skipped に記録して 83ch で完走する設計。ただし load() は例外で止まる。未知型は「落とさず理由付きでスキップして完走」が既定。型 6 の解読は『ラップのビーコンを 2D で見たくなったとき』まで放置。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.local.md:57 ; ddd_generator.py:446-453 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:67`
- 確度: 実測

### スケーリング

対応表に Multiplier/Offset を持たせ、恒等(1.0,0.0)のときは浮動小数演算を通さず生配列参照を完全パススルー（既存出力のバイト一致保証）。スケール後に NaN/Inf が出たら変換全体を拒否。単位を触る作業の前に対象チャンネルの単位・最小・中央・最大を実測して表で計画書に書く（指示書の前提単位と実測単位が文字列で違えば機械的に『要確認』）。M1/C125 の λ→A/F(×14.7) の同語反復テスト事故が元。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_generator.py:456-463 ; docs/development.md:91-105 ; CLAUDE.md:197-205`
- 確度: 実測

### チャンネル名の対応表

対応表 channel_map.json はMoTeC名→{unit, custom_name}。custom_name が設定されたチャンネルは元の名前を維持したまま同一データを別名で追加出力する（2D 側の標準名 RPM など）。未登録チャンネルは変換時に自動追記（autogrow）。保存場所は exe 隣→書けなければ %LOCALAPPDATA%\LD2MES\。初期値は channel_map.seed.json（Ambient.Pressure kPa a、Coolant.Temperature C、Engine.Speed rpm、Engine.Load mg 等 79ch）。MBD2MES の対応表も同じ仕組み(seed+実効の2層、自動成長)を踏襲できる。2D Analyzer 側のチャンネル名と合うかで表示が決まる（Engine.Speed と RPM の表示差は EVENT.INI [SPECIAL CHANNELS] 由来の見込み）。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/channel_map.py:84-500 ; channel_map.seed.json ; docs/roadmap.md:100-104`
- 確度: 実測

### GPS の書き方（地図が出る形）

地図を出すには、チャンネル名を Latitude / Longitude / V_GPS（短名 Latitude・Longitud）にし、緯度経度は 32bit・倍率 float32(1e-7)=16進 33D6BF95・6= 第1欄 FFFFFFFC・6= 第3欄に 2D の GPS ロガーの印（Latitude=S227D9, Longitude=S227D10, V_GPS=S227D5, Course=S227D8, Altitude=S227D11, HorAccu=S227D14）、HED に [GPS] 節（Rate=10, Version=22.1213, ... MSR=基準Hz）。決め手はチャンネル名が EVENT.INI の GPS_LATITUDE/GPS_LONGITUDE の指す名前と合うこと（行が無ければ Analyzer が Latitude/Longitude を書き足す）。名目の 1e-7 は float32 でずれ経度が約 1.6e-6 度狂うので float32 実値で符号化する。南緯・西経は符号なし 32bit で 0 に切られるので事前に拒否。書く並びは V_GPS・Altitude・Course・HorAccu・Latitude・Longitude。MBDA2 が GPS を持つなら同じ形で書ける。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/gps_channels.py:1-167 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:57（RCZ2MES M1/M2 の Analyzer 確認）`
- 確度: 実測（らいおが Analyzer で確認）

### HED の扱い

HED は MES が無ければ Analyzer が開いたときに自動生成（46〜47 byte, [Laptimes] だけ）。チャンネル定義・レート・gain/offset は HED に無い。HED を書くなら既存の節（Analyzer が書いた [Laptimes]/[CalcTool]/[COMMENT]/[SectionTimes]）をバイトのまま残して [GPS] 節や [DOWNLOAD] MainSamplingRate だけ差し替える merge_hed_gps を使う（作り直しで Analyzer の物を消す事故が反証で何度も出た）。HED は cp1252・CRLF・節の後に空行。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/scratch/evidence_008/f6_2d_processing_findings.md:9-14,30,60 ; gps_channels.py:10-11,149-167 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:57`
- 確度: 実測

### Analyzer で開く副作用と試験の作法

Analyzer で MES を開くと、開いたフォルダに HED・.udm、親に Event.ini・Users.ini、C:\RaceData\GPSMapCache\、C:\ProgramData\Race2026\*.ini（Race.ini の最後に開いたイベント・最近のフォルダ、Analyzer.ini）が書き換わる。開かなかったフォルダは無汚染（A/B 実験）。試験は必ず使い捨てコピー（RaceData の外の試験用イベント）で、開く前に Race2026 の ini を全部控え、開いた後に比べて記録する。らいおの本物のイベントは開かない。2D は 1 イベント=1 コースが作法（GPS Sections.txt がイベントに 1 つ）。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/scratch/evidence_008/f6_2d_processing_findings.md:11-13 ; _Prompt/02_buildai/Ld2Mes_013_owner_check.md:1-1-3,4 ; C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ.md:57`
- 確度: 実測

### 2D の加工が書き換える範囲

実例では 2D 側加工後に DDD のチャンネル名の行（2 行）だけが書き換わり、A??・CAL・HED は無変更（_Orig と無印の比較）。つまり人がチャンネル名を変えうるので、DDD の行を探すときは名前でなく 6= のデータ拡張子（A??）を主キーにする。数式チャンネルの保存先・ゲイン行の書き換え・CAL 書込有無は未確認。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/scratch/evidence_008/f6_2d_processing_findings.md:34-59`
- 確度: 実測（実例）／未確認（数式チャンネルほか）

### ラップ(.IXR)・セクター(.STI) の符号化

.IXR=int32 LE の語列: 0,0 → (標本番号,累積距離m)×N → (記録終端標本,全体距離m) → ((N<<16)|offset, MainSamplingRate, N, 0)、offset=8+8*(N+1) は 16bit に収まる必要（N 上限は MAX_BOUNDARIES）。標本番号は厳密昇順（重複は呼び出し側で除く）。.STI=int32: 件数, MainSamplingRate, 0, (標本番号,区間番号0始まり,-1,-1)×件数 時刻順。Analyzer の一覧は「境目数+1」本（先頭と末尾は記録の前後区間、計測ラップは奇数番）。.LAP だけの形は 015 で不使用（未確認）。Analyzer は IXR があれば IXR、無ければ LAP を使う。HED は [DOWNLOAD] MainSamplingRate が最小で受理された（013 の P4 で Analyzer 受理）。MBDA2 にラップ情報があれば lap_files.py はそのまま写せる。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/lap_files.py:1-85 ; _Prompt/02_buildai/Ld2Mes_013_owner_check.md ; 2D_知見ハブ.md:67-73`
- 確度: 実測（らいおが Analyzer で確認）

### ラップ境目と時刻合わせ（GPS が別機器の場合）

別機器（RaceChrono）の GPS を .ld に合わせるとき、時計のずれは直線でなく『段』（区間ごとのずらし量、C125 の電源のつなぎ目・RCZ の約2sの時刻の段・GPS+297s の位置の飛び）。1 つのずらし量で全点を写すと境目がずれる（変異 M1 で試験が落ちる）。段が 100ms 以下のときだけ区間またぎのラップを始まりのずらし量で写す。M1 車速の倍率が GPS と 4.4〜4.8% 違うデータが実在（倍率補正の経緯は らいおの 08-29/10-03 の補正に由来・差の出どころ未確認）。MBD に外部 GPS を合わせる要件が出たらこの設計(gps_sync.py)を参照。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/00_FromDesignAi/_design_lane_todo.md:57 ; _Prompt/02_buildai/Ld2Mes_015_laps_sectors_report_to_design.md:48,67 ; Ld2Mes_014_gps_merge_report_to_design.md:41-45`
- 確度: 実測（区間のずれ）／未確認（M1 の車速倍率差の出どころ）

### 元の MES を変えない・作り直しで Analyzer の物を失わない

015 の根幹: 本体の MES は 014 の出力とバイト一致で不変、ラップ/セクター付きはトラックごとの『コピー <名前>_<コース名>.MES』に隔離。作り直しは新旧の境目が同じなら Analyzer が書いた HED 節とファイルを引き継ぎ、違えば .ld2mes_gps_backup\<名前>_<日時>_course_replaced\ に退避。反証で出た後退の型: 作り直しで HED の [Laptimes] が消える・退避の途中失敗で Latitude が抜ける・人が写したコピーを自分のものと誤認して消す・同名の別物を消す。『LD2MES が書いたコピーだけを自分のものとする（記録 LD2MES_course.json）』『消さずに _course_gone/_course_stale/_course_held へ移す』『合わない RCZ が届いても一発変換を失敗にせず、組が変わるまで試さない』が確立した型。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/02_buildai/Ld2Mes_015_laps_sectors_report_to_design.md:34-48,263-279 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:57`
- 確度: 実測

### 回帰基準と出力互換性（CRITICAL）

オーナーは既に MES 資産を作っているため、既存チャンネルの変換出力を変えてはならない。変更を伴う改修では、実ログ(_test_fixtures)と out/ のサンプルで改修前後の出力一致を SHA-256 で証明（baseline_m1_hashes.json / baseline_20261009_hashes.json）。旧版のコードを git show HEAD:<file> で別フォルダに写して新旧を同じ入力で変換し、ファイルごとの SHA-256 を比べる（b8_compare_v014.py 型）。凍結した旧出力の SHA-256 を常設テストにも置く。MBD2MES は v1 から基準ハッシュを取り始めること。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.md:197-199 ; _Prompt/02_buildai/Ld2Mes_015_laps_sectors_report_to_design.md:233-261`
- 確度: 実測

### テストの作り方（同語反復の禁止）

期待値を確かめる側と同じ式・関数・定数で作るな（λ→A/F の ×14.7 事故。A/F 済みチャンネルを入れても通った）。期待値の出どころは 実測値/物理の常識/別機器の記録/手計算の具体値・仕様書 のどれかをテストのコメントに書く。やむを得ず同じ式のものは『計算の通り道の確認』と名乗る。間違った入力で落ちる常設テストを 1 つ置く（入力検査を独立関数にする）。外れ値に引きずられる統計量(最大/95%分位)をしきい値に使わない（C125 の λ は 2.55 に張り付く）。実装を 1 か所壊して該当テストが落ちるか確認する変異試験（6〜11 通り）を毎回行う。読み戻しは製品の関数を import しない別実装(lapfile_readback.py)で行う。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/docs/development.md:91-110 ; CLAUDE.md:201-205 ; _Prompt/02_buildai/Ld2Mes_015_laps_sectors_report_to_design.md:376-421`
- 確度: 実測

### 実データの識別と試験データの扱い

実データ前提はファイル名でなく SHA-256 で識別（再現不能なら実装側は差し戻してよい）。実データの試験は環境変数（LD2MES_REAL_DATA_DIRS）から探し、無ければ skip（リポジトリに実ログ・RCZ・個人パスを入れない）。ただし skip で通った試験は『通った』と扱わず、実データ付きで走らせて skip でないことを確認する。誤りと判明した試験は無効化マーカーを付けて単独コミット（黙って消さない）。"座標らしい数を含む文"の証跡はコミットせずローカルに残した。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.md:201-205 ; CLAUDE.local.md:71-72 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:5-22`
- 確度: 実測

### GUI/CLI/D&D の 3 経路を 1 関数に集約

変換ワークフロー全体（対応表ロード→build_entries→write→不変量チェック）を convert_one() に集約し、GUI も D&D も CLI もこれだけを呼ぶ＝3 経路の結果一致を構造的に保証。D&D は『exe アイコンへファイルを落とす＝引数あり起動』の経路（専用 DnD ライブラリは使っていない）。windowed exe(console=False)で引数あり起動時のみ ensure_console_for_cli()（AttachConsole→AllocConsole）、ただし stdout/stderr/stdin を個別に usable 判定しリダイレクト先を尊重（--show-map > x.txt が空になった実バグ）。GUI 起動時はコンソール API を一切呼ばない（窓が一瞬も出ない）。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ld2mes.py:21-28,95-150 ; ld2mes_gui.py`
- 確度: 実測

### 出力先の決定順と RACE.INI

出力先は ①-o 明示 → ②設定ファイル → ③2D の RACE.INI から自動検出（C:\ProgramData\Race<最大の年>\RACE.INI の [ALL] Data_DRV + [START] EVENT。[DATADIR] 0= と一致なら high、不一致/欠損は low）→ ④不成立なら SystemExit。--yes（無人）時は high のみ自動採用。RACE.INI は読み取り専用（書かない・cp1252）。MBD2MES の出力先も 2D のイベントフォルダに合わせるなら race_env.py はそのまま流用可。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/race_env.py:1-111 ; ld2mes.py:16-20`
- 確度: 実測

### 一発変換（バッチ）の設計

『前回一括変換した時刻以降に更新・新規作成された .ld だけ』を変換する一発変換、台帳(ledger)で変換済みを管理、『全部含めて変換』チェックボックス、変換リストの一括クリア。Multiplier を変えた・極性を逆にしたい等で過去分も再変換したい場面がある。一時フォルダへ変換してから公開（途中で止まると書きかけが残る→次回の初めに一時フォルダ・古い組を掃除）。通常 Convert の公開は電源断に対して原子的でないが、実害が出るまで放置と裁定。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/docs/roadmap.md:62 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:40-47 ; batch_converter.py`
- 確度: 実測

### 派生チャンネル（復元）機構

記録済みチャンネルから未記録の信号を表の逆引き（出力=f(X,Y,Z)、Z=層の切替、未知の連続軸を 1 つ復元、1D/2D は軸を減らして同じ関数）で復元し MES に足す汎用機構。最初の使い道は C125 に来ない足の踏み量。設定は exe 隣のサブフォルダに『チャンネル名・作成タイムスタンプ・リビジョン』を含む 1 チャンネル 1 JSON で履歴保存。派生は対応表・Multiplier を適用せず、既存チャンネルの後ろに同じ経路で足す。既存 MES への Fix（派生だけ作り直し）は DDD 行単位で書き換え、A??/CAL/HED を触らない。MBD に計算で補うべき信号（例: 派生量）が出たらこの機構を流用できる。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/derived_channels.py ; docs/roadmap.md:60-69 ; ddd_generator.py:423-441 ; scratch/evidence_008/f6_2d_processing_findings.md:58-59`
- 確度: 実測

### 配布形態

配るのは MoTeC と 2D を使う知り合いへ『ZIP を渡す』形（GitHub 公開は考えていない）。リポ直下 release\ に最新 ZIP と .sha256、旧版は release\old\、ZIP は git 非追跡。作るのは 1 コマンド python tools\make_release.py（検査→組み立て→ZIP の別場所展開後の再検査→配置）。ZIP 名 LD2MES_Converter_v<版>-<commit>.zip。入れる物は許可リスト（exe・README 日英・CHANGES.md・VERSION.txt・マニュアル日英 HTML・画像1枚）のみで、設定・対応表・派生定義/履歴・実データ・個人情報（<ユーザー名>/RACEDATA/C:\_Prog/C:\Users を UTF-8/16 と exe 内の圧縮 Python コードまで検査）は入れない。+dirty の exe は配れない・版の食い違いで止まる。一度でも渡した版は中身が変わるなら必ず版を上げる。exe を作る際はビルド直前に exe が動いていると PyInstaller が前の exe を消せず止まる。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.md:53-64 ; docs/development.md:68-85 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:57（exe 作り直し停止の件）`
- 確度: 実測

### exe を動かすと隣の設定が書き換わる

設定 ld2mes_config.json・channel_map.json・derived_* は exe 隣（書けなければ %LOCALAPPDATA%\LD2MES\）に作られるため、dist\ld2mes.exe で試験するとオーナーの本物の設定を汚す。試験は dist の写しを別フォルダに置いて行う。試験が repo 直下の channel_map.json を汚した事故あり（161 行追記）→ test_zz_repo_state_untouched.py で守る。ZIP に設定を入れないのも同じ理由（受け取った人が上書き展開しても設定が消えない）。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.local.md:78 ; docs/development.md:10,89 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:38`
- 確度: 実測

### マニュアル・READMEの運用

正本は docs\manual_ja.src.md / manual_en.src.md / readme_*.src.md の 4 本。manual.md/html・README は生成物で手で直さない（tools\build_manual.py、--check で現物との一致検査、版の数字は {{APP_VERSION}} 差し込みで直書き禁止）。test_manuals.py が『画面表記(text= 定数・ボタン表)が日英両方に載っている』『CLI オプションが載っている』『個人情報が無い』『HTML が自己完結(base64 PNG のみ)』を機械検査。人が見るのは手順の実挙動・画面写真の鮮度・文章の質。MBD2MES も同じ 4 原稿＋生成器の型を使えばマニュアル陳腐化を試験で検出できる。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/docs/development.md:12-66`
- 確度: 実測

### チャンネルのレート・時間長の揃え方（GPS 追加時）

GPS を 10 Hz で足すなど別レートのチャンネルを加える場合も『レート×時間長』のサンプル数規則と、GPS の無い時間は最初/最後の位置を保持（0 の点を書かない＝偽の線が引かれる）。GPSValid/Satellites/Fix は地図の出た形に無いため書かない（理由を記録に残す）。RCZ2MES との整合は『同じ書き方を写しで揃え、写し元の commit と SHA-256 を docstring に書く』方式。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/gps_channels.py:4-12,84-90 ; lap_files.py:4-6`
- 確度: 実測

### M1 ログの特殊事情

M1 の .ld は電源の区間のつなぎ（ECU.Uptime）、ヘッダは記録の終わりの約 212〜224 s 後、C125 は電源のつなぎ目がある。1 つの .ld に電源のつなぎ目をまたぐ区間があると時刻合わせが段になる。峠で走りの間にエンジンを切る頻度は『ほぼ無い（99%以上）』とオーナーが答え、放置で閉じた。MBDA2 の記録の継ぎ目（電源断・ロガー再起動・セッション分割）を最初に実データで確認すること。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/00_FromDesignAi/_design_lane_todo.md:15,57`
- 確度: 実測

### パスと環境の地雷

プロジェクト名に [MoTeC] のように角括弧があると bash のグロブメタ文字として解釈され、パスが黙って解決されない。Bash では必ずクォート、PowerShell では -LiteralPath。MBD2MES のパスは C:\_Prog\ECU\Logger\MBD2MES で括弧は無いが、サンプル MBD のパス（C:\RaceData 配下・CLAUDE.local.md に記載）は日本語を含むため、Windows の cp932/UTF-8 の取り違えと、PS 5.1 の BOM 無し UTF-8 .ps1 の日本語に注意。JS/Python 文字列の \0・\2 等は 8 進エスケープ化する。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.local.md:16-28 ; 三瀬谷の記憶（RagVault の memory の MEMORY.md）（js-string-windows-path / vbs-cp932 項）`
- 確度: 実測

### 設計/実装レーン分離と運用

このリポジトリでは設計レーン（CC）は What/Why/受け入れ条件（条件/判定方法/証跡の形/区分の 4 列）/スコープ外/受理判定を書き、How は実装レーン（Gemini、または設計が Workflow で起動した Sonnet 5.5 サブエージェント）が決める。実装は段 A 計画→設計の検分→段 B 実装→反証の確かめ（検査役の Workflow）→検分 return→段 C 直し→Codex レビュー（上限 2〜3 回）の型。投下文面はチャットに直接貼る。完了は『オーナーが Analyzer で実機視認するまで完了と言わない』。最小限の先回りに留める（スタンス: 欲しいものを速攻で作る・事前に長い計画を立てない）。MBD2MES は今回 CLAUDE.md を整備するだけで、解析や実装は PJ フォルダの CC がやる。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.md:18-44,66-76,210-211 ; _Prompt/00_FromDesignAi/_design_lane_todo.md:57`
- 確度: 実測

### 放置と踏み抜くの二値ラベル・台帳運用

残玉は『放置（理由＋再び取り上げる条件）』か『踏み抜く（受け皿＝台帳の行）』の二値で書く。例: 型 6 の読み取り＝放置（ラップのビーコンを見たくなったら）、F-4 通常 Convert の公開が原子的でない＝放置（書きかけが残って困ったら）、H-8 Fix の確認画面が派生を並べない＝踏み抜く（次に Fix を触るラウンドの指示書に入れる）。店じまいで台帳を整理し、試験の中間成果物は根ごと ZIP 化して git 非追跡で保管（228MB・実データの写し 882MB は ZIP と 1 本ずつ照合してから削除）。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/00_FromDesignAi/_design_lane_todo.md:5-22,46,60`
- 確度: 実測

### リポジトリの衛生（避けるべき実態）

リポ直下に .bak（*.014.bak/*.015c.bak 等）が大量に残り、dist/ と build/ が同居、scratch/ が evidence_* で膨らんでいる。ホーム側 CLAUDE.md の『編集前 .bak』ルールの副作用。MBD2MES は .bak の置き場を決め（例: scratch\bak\ を .gitignore）、リポ直下を汚さない構成から始めると後で楽。また .playwright-mcp の出力・未追跡の '--verify' のような引数誤りの迷子ファイル（md2html の引数順ミス）が出た。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/（find -maxdepth 2 の列挙）; _Prompt/00_FromDesignAi/_design_lane_todo.md:47,54`
- 確度: 実測

### 解析の出発点に関する未確認事項（MBD2MES 固有の注意）

Ld2MesConverter の知見で MBD（HRC MBDA2 のバイナリ）の解析に直接使えるものは無い（.ld はリバースエンジニアリングされた MoTeC 形式で、構造体 LDHEAD_FMT/LDCHAN_FMT を struct で読む方式）。MBD の読み取り器は新規に作る必要があり、Ld2MesConverter の流儀（ChatGPT 作成の参考リーダを cmp でバイト一致確認後に正本化、複数ログでヘッダ判定、未対応型は理由付きスキップ、チャンネルヘッダは連結リストを seen 集合でループ防止・サイズ境界を厳格にチェック）は踏襲できる。MBDA2 のサンプリングレート・型・ヘッダの機種差・単位の取り方はすべて未確認。

- 出典: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/motec_ld_reader.py:1-30,55-100`
- 確度: 推定

## 運用の決まり

- 設計レーン CLAUDE.md の型: 『このプロジェクトは何か／あなたの役割／最上位命題(オーナー本人の言葉)／配布の形／いま出来ていること／進行中タスク(正本は _design_lane_todo.md)／環境／HA22S 等の親プロジェクトとの関係と読み取り専用の約束／作業ガード／出力』の章立て（218 行）。作業ガード=事実/推測/未確認のラベル分離・コードの挙動は ファイル名:行番号 を添える・変換出力の互換性(CRITICAL)・実データは SHA-256 識別・完了条件に期待値と出どころ・.bak・完了の定義。
- 完了の定義: テスト PASS は完了ではない。オーナーが 2D Analyzer 等の実機で視認するまで『完了』と宣言しない。らいおに質問は最小回数・一度に一つ・選択式。
- 配布形態: ZIP を知り合いに渡す（GitHub 公開なし）。release\ に最新 ZIP+.sha256、旧版は release\old\、ZIP は git 非追跡。作成は python tools\make_release.py 1 コマンド。ZIP に設定・対応表・派生定義・実データ・個人情報(<ユーザー名>/RACEDATA/C:\_Prog/C:\Users)を入れない（UTF-8/16 と exe 内圧縮コードまで検査）。一度渡した版は中身が変わるなら必ず版を上げる。ZIP 名に commit を入れる。ライセンス・署名は未決。
- 検証方法: python -m unittest discover -s tests（依存ゼロ・実環境の設定に触れない作り）。実データの試験は環境変数 LD2MES_REAL_DATA_DIRS から探し無ければ skip（ただし skip でないことを実データ付きで確認）。全テストは 1 案件で 2 回まで等の上限を決めて回す。変異試験(1 か所壊して該当テストが落ちるか)を毎ラウンド実施。exe は dist の写しで試験し本物の設定を汚さない（test_zz_repo_state_untouched）。
- ラウンド運用: 指示書は build.md 単体(What/Why/受け入れ条件 4 列/スコープ外、How は『参考』明示)・frontmatter に発行元スタンプ・投下文面はチャットに直接貼る・段 A 計画→設計が検分→段 B 実装→反証の確かめ→検分 return→段 C 直し→Codex レビュー上限・報告書は実在ファイルの行を include=/cite= で引用し md-render --verify を通す・らいおの確認の表(確認ごとにコメント欄＋チェック欄)を 1 枚で渡す。
- Analyzer を開く試験の手順: 試験用イベントを RaceData の外に作る→開く前に C:\ProgramData\Race2026\*.ini を全部控える→らいおの本物のイベントは開かない→開いた後に ini と MES のハッシュを比べ書き換わった物を記録→試験用フォルダは記録後に捨てる（らいおの了承後）。
- commit/push はオーナーの明示指示がある時だけ（グローバル git-operation）。1 案件=1 コミット・明示パスで add・Lane トレーラ。試験の中間成果物は根ごと ZIP して git 非追跡で保管、実データの写しは ZIP と 1 本ずつ照合後に消す。
- 家訓: 見つけた地雷は踏み抜く。残玉は『放置(理由＋再び取り上げる条件)』か『踏み抜く(受け皿=台帳の行)』の二値。『急がない』『いずれ』等の曖昧ラベル禁止。
- オーナーのスタンス: 自分が欲しいと思ったものを速攻で作る。頼まれていない先回り設計・大きな事前計画を作らない。roadmap §2（オーナーの言葉）に無いものは着手しない。『やらない』を最初に決めない。
- HA22S 側（スピンオフ元）は読み取り専用で参照のみ（書き戻しは必ずらいおに諮る）。凍結した旧写しは触らない・削除しない（他スクリプトが import しているため）。
- 2D の MES 知見は RagVault の知見ハブに集約: 新しく分かったことは確度（実測/推定/未検証）を付けて 1〜3 行追記する（2026-11-12 らいお Yes）。MES を書く話はハブ §3 を最初に見る。

## 読むべき文書

- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.md : 役割分担・配布形態・作業ガード・環境の型（MBD2MES の CLAUDE.md の雛形に最適）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/CLAUDE.local.md : [ ] を含むパスのクォート注意・検証材料の SHA-256 表・環境メモ・2D 知見ハブへのポインタ
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/docs/roadmap.md : オーナー本人の言葉による最上位命題とスタンス（MUST=トリガ検知→自動変換→2D イベントフォルダ配置、WANT=他人の環境でも）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/docs/development.md : 開発者向けメモ（マニュアル生成・配る ZIP の作り方・テストの期待値の作り方・Codex レビューの頼み方）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/mes_writer.py : MES 書き出しの正本実装（先頭 docstring に verbatim 系と reconstructed 系の違いと実機確認の経緯）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_generator.py : DDD 生成と定数台帳（Analyzer 受理が未確認の値とその A/B 代替値の一覧）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/ddd_invariants.py : DDD 不変量 5 項目（自己検査に流用）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/gps_channels.py : 地図が出る GPS の書き方と機器の印
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/lap_files.py : .IXR/.STI の語列仕様
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/scratch/evidence_008/f6_2d_processing_findings.md : Analyzer が MES のどこを書き換えるか（HED のみ追加・DDD の名前行のみ書換え等）の実測と、未確認の一覧
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/00_FromDesignAi/_design_lane_todo.md : 設計レーン台帳（全ラウンドの経緯・放置と踏み抜くの判断・店じまい記録。180 行のうち 1-102 行を読んだ。H-12 の長い行に 013〜015 の詳細）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/02_buildai/Ld2Mes_015_laps_sectors_report_to_design.md : 最新の完了報告（r4）。How の判断表・受け入れ条件ごとの証跡・変異試験・期待値の出どころ（1290 行のうち 1-424 行を読んだ）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/02_buildai/Ld2Mes_014_gps_merge_report_to_design.md : GPS マージの時刻合わせ・地図の出る形の実測と段 C の直し（2690 行、冒頭と結論のみ読んだ）
- C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/02_buildai/Ld2Mes_013_owner_check.md : Analyzer での目視確認の表の型（準備・控え・戻し方・合格の見え方・コメント欄）
- C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ.md : 2D の MES/DDD/ラップの仕様の要約（続き 2D_知見ハブ_Part2.md＝未解明・出典マップ）。MES を書く話はまず §3
- C:/_Prog/ECU/Car/HA22S_MoTeC_M130/Manuals/2D/2Dロギングデータ保存形式.md と同 Manuals/2D/MES命名規則.txt : 2D 公式資料の一次（CLAUDE.md で参照先として指定。今回は本文を読んでいない）
