# 過去 PJ の教訓 — RCZ2MES（RaceChrono の .rcz を 2D Analyzer の MES へ変換）

## 本書の読者と目的

- 読者: MBD2MES の CC
- 目的: 先行の MES 変換 PJ で分かったこと・踏んだ地雷を、MBD2MES が同じ調べ直しをせずに使えるよう集める
- 出どころ: C:/_Prog/ECU/Logger/RCZ2MES（読み取り専用）。2026-11-13 に三瀬谷のサブエージェントが読んで抜き出した二次資料。数値や行番号は使う前に出典で確かめる

## 概要

RaceChrono のスマホセッション .rcz（ZIP、機器ごとに時刻軸が別の不規則標本）を、LD2MES（MoTeC .ld→MES）と機能コンパチの Python/tkinter/PyInstaller 製デスクトップ exe で 2D の .MES に変換する PJ。M1 試作→M2 GUI・exe→M3a ラップ・セクター→M3b 一発変換→M3c CAN 名→M4 マニュアル・配布 ZIP まで完了し、v0.5.0 を 2026-10-20 に手仕舞い（らいおが Analyzer で地図・ラップ・区間・日付・周比較を視認済み、全 690 試験 OK）。残りは再起動条件つきの放置玉のみ（B21 派生チャンネル・Fix・履歴など）。MBD2MES は入力側だけ差し替え、MES 書き出し・ラップ・Event.ini 警告・配布の作法を写せる。

## 流用できるモジュール

- mes_writer.py（LD2MES 0160cf0 の無改変の写し・blob byte一致）: DDD(cp1252/CRLF)・A??・CAL の書き出し。入力形式に依存せず、32bit位置も entry の bit_width/gain/raw_key6 を差し替えるだけで書けるため、そのまま写せる。負値は 0 に黙って切り上がる点を呼び出し側で防ぐこと
- mes_reader.py・ddd_invariants.py・ddd_generator.py（同上・無改変）: 読み戻しと不変量検査(変換後に必ず通す門)。入力形式非依存。tests/golden の16bit固定出力と test_ld2mes_copy.py の SHA-256 照合も一緒に写すと『写しが壊れていない』証明になる
- gps_entries.py: 32bit 位置チャンネル(make_wide_entry・POSITION_GAIN=float32(1e-7)・NegativeCoordinateError)・V4変種(Latitude/Longitude/V_GPS＋機器の印 S227D9 等＋HED [GPS] 節)・apply_marks・render_hed_gps。GPS を2D地図に出す書き方が入力形式と無関係に必要
- hed_download.py: HED [DOWNLOAD](日付・時刻・Timezone・Start/End of download・MainSamplingRate)。t0(UTC ms)と基準Hzだけで決まる。タイムゾーン固定+09:00 の前提は MBD の時刻帯確認後に差し替え
- lap_files.py / lap_sections.py: .IXR/.STI の符号化(int32LE語列・上限8189境目)と、finish付きラップ→境目標本・同標本の周回つなぎ・traps(スタート/ゴール/セクター線)を GPS が横切る時刻の求め方。入力が『ラップの開始/終了時刻＋線の定義(緯度経度・方位・幅)＋GPS 軌跡』の形なら流用可。MBD のラップ表現に合わせて入力アダプタ(session.json 相当)だけ書く。tests/oracle_cross.py(球面大円＋二分の別実装)も流用可
- rcz_timeline.py(名前は変えて): 機器ごとの不規則標本を共通 t0 から一定レートへ(線形補間・1050ms超の空きは保持・方位は円周補間・値なし除外・レートは中央値に最も近い400Hzの約数・1Hz区間検出)。Honda ロガーが固定レートでも欠損・不規則区間があれば有効。値なしの印と時刻軸が違うだけで関数は入力形式非依存
- event_ini.py: 変換先 Event.ini の [Special channels] GPS_Latitude/GPS_Longitude と今回の位置チャンネル名の食い違い警告(読むだけ・大文字小文字無視)。地図が出ない最大の原因を事前に捕まえる。race_env.py(RACE.INI から出力先候補を検出・無改変の写し)も同様
- rcz2mes.py の convert_one/convert_many の骨格(stage フォルダで完成→不変量門→入れ替え・--force・output appeared 断り・InvariantViolationError・記録ファイル・終了コード・ensure_console_for_cli/CONIN$ 周り): 入力読み取り部だけ差し替えれば MBD2MES の中核になる。GUI/D&D/CLI を1関数に通す構造も
- config.py / channel_map.py / map_rules.py: RCZ2MES_SETTINGS_DIR で置き場を替えられる設定・対応表(名前・単位・Multiplier/Offset・Output・自動成長・保護する行 Latitude/Longitude/V_GPS・壊れた設定の .corrupt_* 退避・migrate)。入力の名前列(RaceChrono Name)を MBD の名前に替えるだけ
- rcz2mes_gui.py(tkinter 3タブ Convert/Channel Map/Other・Browse初期フォルダ・Reload・Convert Unconverted・アプリID設定)と rcz_batch.py(一発変換: 台帳・持ち主確認・PROTECTED・指紋ガード・before_replace)。拡張子と入力の peek(種別判定)・既定フォルダだけ MBD 用に
- version_info.py・dist_build/(rcz2mes.spec・build_exe.bat)・tools/(write_build_info.py・check_exe_version.py・make_release.py・build_manual.py・make_manual_shots.py): 版の表示・exe作成・配布ZIP(許可リスト・針・鮮度・展開し直し検査)・マニュアル生成・画面写真撮影。名前と許可リストを MBD2MES に替えれば配布まで同じ手順で出せる
- tests/_common.py・test_isolation.py・test_zz_settings_untouched.py・batch_support.py・lap_synth.py(合成RCZ)の型: 隔離環境変数・全試験の import 検査・実設定の前後比較・合成入力生成。入力が MBD になっても『合成入力＋別出どころの期待値』の作法を踏襲できる
- docs/provenance.md の書式と test_provenance*.py: 写したファイルの元パス・commit・blob SHA-256・写した先SHA-256・改変の要点の台帳と機械照合。MBD2MES が RCZ2MES を写す時も同じ書式で『RCZ2MES の commit bc558de 以降から写した』と記録する

## 教訓

### GPS が地図に出る条件（最重要・最初の1週間の地雷）

Analyzer が地図に使う GPS チャンネルは『イベントフォルダの Event.ini [Special channels] の GPS_Latitude / GPS_Longitude に書かれた名前』で決まる。生の名前(Lat_dez/Lon_dez)の MES は Event.ini が既定(Latitude/Longitude)のイベントでは地図が出ず、V4（計算後の名前 Latitude/Longitude/V_GPS＋HED [GPS] 節＋機器の印）で出た。V3(生の名前+[GPS]節+印)でも出なかった。Event.ini に GPS_Latitude=Lat_dez を書いたイベントでは生の名前の V1 でも地図が出た(対照2本)。MBD2MES は既定を V4 の名前にし、変換先 Event.ini が別名なら警告する(RCZ2MES は Event.ini を書かず読むだけで警告: event_ini.py)。V4 から [GPS]節/印を外しても出るかは未確認(B7)。

- 出典: `C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/02_buildai/RCZ2MES_M1_analyzer_check.md 5章・5-2、RCZ2MES_M2_analyzer_check.md 1章 #3-#4、event_ini.py、gps_entries.py:151、BOUND_PENDING B7・B9・B10`
- 確度: 実測（Analyzer で対照。V4 から節・印を外す件のみ未確認）

### 緯度経度は 32bit で書く（16bit 固定では足りない）

LD2MES の ddd_generator/mes_writer は全チャンネル16bit固定。位置は度×1e-7 の32bit整数で書く必要がある。DDD の gain は float32 なので符号化にも float32(1e-7) の実値(POSITION_GAIN)を使わないと経度137度付近で読み戻しが最大1.6e-6度ずれる。ddd_generator.make_entry の返りを dataclasses.replace で作り直し(bit_width=0x20、6=第1欄 FFFFFFFC)、mes_writer は無改変のまま書ける。2D 実物 GPS ロガーの 1=第6欄 20・3=第4欄 33D6BF95・6=第1欄 FFFFFFFC と一致を試験で確認。Analyzer は32bit整数の位置を受理した。

- 出典: `gps_entries.py:27-66、RCZ2MES_M1_report.md 4章(mutation)・8章、RCZ2MES_M1_plan_review.md`
- 確度: 実測（Analyzer 受理・DDD欄一致）。6=第1欄 FFFFFFFC の意味『符号付き4byte』は推測

### 負の緯度経度（南半球・西半球）は書けない

mes_writer は符号なし32bitで書き、負値を np.clip で 0 に黙って切り上げる。RCZ2MES は NegativeCoordinateError で変換全体を止め『Nothing was written』を出す(南緯・西経は未対応・B1・放置)。MBD2MES の Honda データが国内なら同じ放置で良いが、符号付き化するなら mes_writer の符号なし32bit を替える必要がある。黙って 0 になるのが最悪なので、最低でも例外で止めること。

- 出典: `gps_entries.py:13,52-56、BOUND_PENDING B1、RCZ2MES_M1_plan_review.md D11、tests/test_negative_coord.py`
- 確度: 実測（コードと試験）

### MES は『t=0 から一定レート』しか持てない。時間軸そろえの設計

各チャンネルは t=0 から一定レートで並ぶ形しか無い。RCZ2MES は全機器の最初の時刻の最小を t0 とし、標本数 n=ceil(T*rate/1000) を全チャンネルで共通の T から決め、線形補間する。隣り合う有効標本の間隔が 1050ms(名目1000+許容50)を超えるところは補間せず直前値を保持し、変換ログと記録ファイルに空きと1Hz区間を出す。方位だけ np.unwrap(period=360) の円周補間。値なし(NaN)は補間の材料にしない。レートは元の間隔の中央値(値なしを含む元の標本時刻から取る・正の間隔だけ)に対数で最も近い、基準400Hzの約数(1〜100Hz)。基準Hz 400 は Analyzer 受理実績がある唯一の値(LD2MES由来)。

- 出典: `rcz_timeline.py:24-210、RCZ2MES_001_design.md『時間軸のそろえ方』・数字の札、RCZ2MES_M1_report.md 5章C3`
- 確度: 実測（設計・実装・Analyzerで終わりまで線が続くのを確認）。1秒閾値は仮置き

### チャンネル長がそろっていないと短い物が黙って捨てられる

MES の各チャンネルは『レート×時間長』のサンプル数でなければならない。全チャンネルを同数で切るとレート差で時間長が食い違い、HED の Lap 宣言より短いチャンネルは Analyzer がエラー無く黙って捨てる(LD2MES実機 09-04 で V_Sat 消失)。長さ検査(T ≤ 長さ < T+1標本)を試験に入れた。

- 出典: `mes_writer.py:48-57、RCZ2MES_001_design.md、RCZ2MES_M1_report.md 条件4、C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ.md §3`
- 確度: 実測（LD2MES実機・RCZ2MESの試験）

### ラップ(.IXR)とセクター(.STI)の書き方（Analyzer が実際にラップ・区間を出す形）

.IXR=int32LEの語列[0,0,(標本番号,累積距離m)×N,(記録終端標本,全距離m),(N<<16|offset),MainSamplingRate,N,0]、offset=8+8*(N+1)、N上限8189(16bitに収まる範囲。計画の8190は式の計算違いだった)。.STI=[件数,MainSamplingRate,0,(標本,区間番号0始まり,-1,-1)×件数]。HED は [DOWNLOAD] MainSamplingRate=基準Hz が必要。標本番号=floor((t-t0)*Hz/1000+0.5)。周回コースは前の finish と次の start が同標本なら境目を1本にまとめる(長さ0を作らない)。Analyzer はラップを自分で切り直さず(EVENT.INI に [TrackChecked] を書かなくて良い)、全ラップが RaceChrono の時間と1標本(2.5ms)以内で合い、最速の印も一致、Section times も合計が合った。Analyzer は開いた時 HED に [Laptimes]/[SectionTimes] を書き足し、イベントフォルダに GPS Sections.txt(1イベント1つ)を作る。

- 出典: `lap_files.py:1-100、lap_sections.py、RCZ2MES_M3a_report.md、RCZ2MES_M3a_analyzer_check.md 1章・3-2節、BOUND_PENDING B13`
- 確度: 実測（らいおが Section times・比較を視認。形の出どころは LD2MES Ld2Mes-013 のらいお確認の仕様）

### ラップ境目の位置は『線を GPS が横切る時刻』を別実装で突き合わせる

セクターは trackId.json の type4(sector) の線を GPS 軌跡が横切る時刻(隣り合う有効2点の符号変化を線形補間、幅の外の通過は数えない、uniDirectional は進行方向のみ)から求め、スタート/ゴール線に同じ式を通して RaceChrono の記録時刻と±1msで較正した。期待値は球面大円距離+1ms刻み二分の別実装(tests/oracle_cross.py)で作る。traps の NaN/Infinity/幅0以下は Codex 指摘(high)で拒否に直した。距離の項目が無い RCZ は速度の台形積分で代替。MBD2MES はラップ・セクター情報の所在(Honda ロガー側にラップ記録があるか)を先に調べ、無ければ GPS 線交差から作る。

- 出典: `lap_sections.py:131-207、tests/oracle_cross.py、RCZ2MES_M3a_report.md 2・5章`
- 確度: 実測

### HED は [DOWNLOAD] を書く（開始日時と基準Hz）

HED に [DOWNLOAD] の Date=YY.MMDD / Time=HHMMSS / Timezone=+09:00 / Start of download=DD.MM.YYYY HH:MM:SS / End of download / MainSamplingRate を cp1252・CRLF・節末に空行で書くと、Analyzer の日付表示が正しく出た(らいお『日付OK』)。[DOWNLOAD] と [GPS] の同居でも地図は出る。日付は t0 を秒で切り捨てて固定+09:00。ファイル名の時刻は JST、中の timestamp は UTC という取り違えに注意(MBD2MES の元データの時刻帯を最初に確定すること)。国外記録は9時間ずれる(B15放置)。

- 出典: `hed_download.py、RCZ2MES_M2_analyzer_check.md 1章#1-#2、RCZ2MES_M3a_analyzer_check.md 3-2節#3、BOUND_PENDING B4・B15`
- 確度: 実測（Analyzer で視認）

### Analyzer は MES を開くと副作用を出す（試験はコピーで・起動は承認制）

Analyzer で MES を開くとフォルダに HED、親に Event.ini/Users.ini/GPS Sections.txt、C:\RaceData\GPSMapCache が増え、C:\ProgramData\Race2026\Analyzer.ini の Recent Files(10行)が入れ替わる。指揮役が起動した際、引数のパス表記違い(C:\_Prog と C:\Prog)で別項目として足され、RaceData の2件が押し出されたためらいお承認で戻した。2回目起動が即終了しRecent Filesの並びが入れ替わった例もある。Analyzer 起動はらいおの承認を取り、out\ 内のコピーだけを開き、起動前に Analyzer.ini を控え(.before_*)、動作中は起動しない。

- 出典: `RCZ2MES_M1_analyzer_check.md 5-1・5-2、RCZ2MES_M2_analyzer_check.md 2章、RCZ2MES_M4_report_review.md『コミットの後』、CLAUDE.md 作業ガード1`
- 確度: 実測

### ロガー固有の名前付けは『出どころ2つが合うものだけ』。CAN名はアプリのAPK逆解析で全確定

RCZ の CAN は RaceChrono の設定で id が決まり公開の対応表が無い。初期は先行解析 rc2vbo.py と値の範囲が合う10本だけ名前を付け、残りは CAN_<id> で全部出した(捨てない)。1020 は先行解析の『燃料』と実測が食い違い(34.8→27.0で再上昇)名前を付けなかった。のちに RaceChrono Pro 10.2.4 の APK を逆解析して全 id の名前・単位を確定(docs/racechrono_channel_ids.json、id を基本番号・位置・番号・デルタbit31に分ける規則 split_id、256行中244行で不一致0)。決め打ちせず、表に無い id は CAN_<id> に倒す設計。MBD2MES は『ロガーソフト MBDA2(C:\_Tool\HRC\MBDA2)自体の中にチャンネル名・単位・換算表があるはず』と見て、先にそれを探す(推定)。

- 出典: `RCZ2MES_001_design.md『既定のチャンネル名』注、RCZ2MES_M3c_report.md、docs/racechrono_rcz_format.md 0章・4-0、rc_channel_names.py`
- 確度: 実測（RCZ2MES）。MBDA2 の表の所在は推定

### チャンネル名変更の migrate は別プロセスの保存を消さない作りに

対応表(channel_map.json)の旧 CAN_<id> 行を新名の行へ『設定ごと』移す際、Codex high 指摘で保存直前に読み直し最新内容へ適用する形に。両方に利用者設定があるときは古い行を残してログ1行。.pre_m3c に旧版を残す。らいおの dist\channel_map.json の写しで検証し、本体の SHA-256 は実装前後で不変を確認。利用者の設定ファイルは壊れたら上書き前に .corrupt_* へ退避し、退避できなければ上書きしない(M2 Codex指摘)。

- 出典: `RCZ2MES_M3c_report.md 4・5章、RCZ2MES_M2_report.md 5章、map_rules.py、config.py(改変の要点は provenance.md)`
- 確度: 実測

### RCZ（入力形式）側の落とし穴一式（入力は違うが同種の罠が MBD にもある前提で点検）

①標本間隔は一定でない(10Hz GPS が内蔵1Hzに切替・数秒の空き) ②拡張子が同じでも中身が別物(車両プロファイル .rcz)→中身で判定し『セッションではない』と飛ばし失敗に数えない ③0x7FFFFFFF は値なし(数値扱い禁止) ④機器ごとに時刻軸が別 ⑤ファイル名は JST・中は UTC ⑥走り切っていないラップは finishTimestamp 無し ⑦距離配列が時刻配列より短い ⑧CAN 意味は設定で変わる ⑨JSON は UTF-8 ⑩ZIP を一時展開せずメモリ上で読む(原本を汚さない) ⑪時刻逆行・ZIP重複名は壊れた入力として拒否(int64両端のnp.diffオーバーフロー対策に比較で判定)。MBD も同様に『ヘッダと型・値なしの印・時刻軸・ラップ定義・欠損・文字コード』を最初に表にする。

- 出典: `docs/racechrono_rcz_format.md 7章・8章、rcz_reader.py、RCZ2MES_M1_report.md 6章`
- 確度: 実測（RCZ）。MBD側は未確認（これから調べる点）

### 変換の出力は stage フォルダで完成させてから入れ替える（原子的公開）

出力先の中に作業フォルダ(.rcz2mes_stage_*)を作り、DDD不変量検査・記録ファイルまで済ませてから MES に入れ替える。--force・上書き確認での失敗で既存 MES を消さない(Codex指摘[6])。不変量違反があれば MES を出さず失敗に数え出力先に何も足さず何も置換しない(M2段C。旧契約『違反でも書く』を替えた)。昇格と巻き戻しが両方失敗した時は旧MESを消さず stage を残す。convert_one を直接呼ぶ GUI/CLI にも『確認後に外部が作った同名フォルダを退避して消す』穴があり(計画前提がまちがっていた)、output appeared while converting で断る形に直した(M3b D15)。

- 出典: `rcz2mes.py:512-、RCZ2MES_M2_report.md 5・11章、RCZ2MES_M3b_report.md 6章D15`
- 確度: 実測（試験・変異試験）

### GUI・D&D・CLI は必ず convert_one() 1本を通す（結果の一致を構造で保証）

LD2MES と同じく、3経路が convert_one を通り、GUI と CLI の MES が byte 一致する試験(.DDD/.A??/.CAL/.HED全比較、記録ファイルは入力パスが違うので除外)を置く。一発変換も convert_many→convert_one を通り、GUI の Convert と記録以外全ファイル同一を試験。exe の D&D は windowed exe なので Enter 待ちの判定(CONIN$ 差し替え成功時のみ)を純関数化、stdin=DEVNULL でも待たない。Windows では NUL も isatty() が真になるので GetConsoleMode 成功時だけ端末扱い。LD2MES の _stream_is_usable が write('') で判定し読み取り専用 stdin を常に不可とする欠陥があり readable() に直した。

- 出典: `RCZ2MES_M2_report.md 2章条件1・3章・4章、rcz2mes.py:177-199、provenance.md M2表`
- 確度: 実測

### 一発変換（Convert Unconverted）の安全設計

起点=前回時刻と失敗一覧をRCZのフォルダごとに設定に持つ。出力先の台帳 .rcz2mes_manifest.json と、MES 内記録(Input:/Input SHA-256)の2つの証拠で『持ち主』を確かめ、証拠なし・別RCZ・名前衝突・フォルダでない同名・修復不能の壊れた MES は PROTECTED で触らない(Convert all でも保護のまま)。判定表9行すべてを試験にし、保護は『実行前後で出力先全ファイルの SHA-256 表が不変』まで確認。台帳だけでファイル名一致を持ち主と認めると別フォルダ同名ファイルが他MESを上書きするので、source_path のフォルダ一致または source_sha256 一致を要求(Codex critical)。署名=名前・大きさ・更新時刻(仮置き)。失敗した RCZ は次回また対象に。is_file() が偽の .rcz は黙って落とさず UNREADABLE。照合から rename までの TOCTOU は Windows に原子操作が無く棄却(放置B20 X2)。

- 出典: `rcz_batch.py、RCZ2MES_M3b_report.md 2・3・7・8章、BOUND_PENDING B20`
- 確度: 実測（実データ予行 ALREADY7・NEW10・PROTECTED0、変異7/7検出）

### LD2MES のコードは『写して使う』。import 禁止・無改変の写しは blob と byte 一致で固定

LD2MES は別レーンの生きたPJなので import せず、このフォルダへ写す。写し元 commit(0160cf0/da75b27/e85d5a8)・元パス・blob SHA-256・写した先 SHA-256・改変の要点を docs/provenance.md に記録し、無改変の写し(mes_writer/mes_reader/ddd_generator/ddd_invariants/race_env)は blob と一致を試験で照合。そのため .gitattributes で写し4本・race_env を text eol=lf に固定(作業ツリーの ddd_generator.py は CRLF で、LF 正規化すると blob と一致)。golden(固定出力)は元の blob を一時フォルダで動かして作る(LD2MES 側では何も実行しない・一時フォルダを残さない)。参照だけした物は『写していない』と別表に書く。16bit の既存書き方が変わっていないことを golden DDD/A01-03/CAL の byte 一致で証明。

- 出典: `docs/provenance.md、.gitattributes、RCZ2MES_M1_report.md 条件10・9章、RCZ2MES_process.md 2章`
- 確度: 実測

### 試験の期待値は被試験側と別の出どころから作る・mutationで試験の鋭さを確認

期待値の出どころは session.json の値・ファイル名のラップ時間(1m27s26=87.258秒)・zipfile/numpy で直読みした本数・手計算・標準ライブラリ。同じ式で作る試験は『計算の通り道の確認』と明示。核になる1か所を壊して試験が落ちることを毎案件確認(float32倍率→名目1e-7で4件落ちる、門のraiseを消すと7本中6本落ちる等)。『等価な変異は生き残る→より意味のある変異に替える』『試験の作りが甘く落ちなかった→状況を直して再確認』も記録。間違った入力(壊れたZIP・プロファイルのみ・値なしだけ)で落ちる試験も必須。

- 出典: `docs/development.md『試験の期待値の作り方』、RCZ2MES_process.md 3章、RCZ2MES_M1_report.md 4章、RCZ2MES_M3b_report.md 7章`
- 確度: 実測

### 試験が利用者の本物の設定・dist・共有フォルダに触れない隔離

設定・対応表の置き場を環境変数 RCZ2MES_SETTINGS_DIR で一時フォルダへ(subprocess にも継承)、tests/_common.py を全試験が import(test_isolation が全モジュールを検査)、test_zz_settings_untouched が実際の設置場所とdist/release の前後(名前・サイズ・更新時刻・SHA-256)を比較。らいおが dist\rcz2mes.exe を使えば dist に設定ができるのは正しい動きなので『dist に設定が無いこと』でなく『試験の前後で変わらないこと』を見る(M3a で直した)。exe を動かすとその隣の設定が書き換わるので、試験は dist ではなく一時フォルダへ写した exe で行う。GUI 試験は withdraw() した Tk、webbrowser/messagebox を差し替え。

- 出典: `docs/development.md『動かす・試す』、RCZ2MES_M3a_report.md 3章、RCZ2MES_M3a_plan_review.md 答え1、tests/test_zz_settings_untouched.py`
- 確度: 実測

### exe と配布 ZIP は『鮮度・許可リスト・展開し直し検査』で自動化

PyInstaller 単体 exe(console=False、python -m PyInstaller で PATH 非依存)。版の名前 `RCZ2MES vX.Y.Z (commit7桁[+dirty], built 日付)` を write_build_info.py が作り check_exe_version.py が検査、タイトルバーに表示。配る ZIP は手で作らず tools/make_release.py 1コマンド(検査→組み立て→ZIP検査→release/配置、失敗なら release 不変)。ZIP は許可リスト8ファイルだけ(exe・README日英・CHANGES・VERSION・マニュアルHTML日英・画像1枚)、個人語(<ユーザー名>/RACEDATA/C:\_Prog/C:\Users。exe内の圧縮Pythonコード・tuple/frozenset定数まで走査)と共有フォルダ名(seedの default_rcz_dir 1キーだけ許可)を針で検出、展開した exe が --manual-file で同梱マニュアルを持つか確認。『exeに入る物がコミット済みで exe がその状態から作られていること(+dirty の exe は配れない)』『dist\rcz2mes.exe が使用中だと作り直しに失敗』『一度誰かに渡した版は中身が変われば必ず版を上げる』。tools/ を変えると exe が古い判定になる(確実側)。ZIP名は RCZ2MES_v<版>-<commit7桁>.zip、前の版は release/old へ。

- 出典: `docs/development.md『配る ZIP の作り方』、RCZ2MES_M4_report.md 2・7章、tools/make_release.py、docs/provenance.md M4表`
- 確度: 実測（作業完了・らいおが ZIP/exe を使用確認）。他PCでの動作・Windows警告は未確認

### マニュアル・READMEは原稿(*.src.md)から機械生成し、古くならない試験を持つ

正本は docs/manual_{ja,en}.src.md と readme_{ja,en}.src.md。tools/build_manual.py が manual_*.md/html(画像base64で自己完結・外部参照0)と README を生成し --check/--selftest/--draft を持つ。生成物は手で直さない(ただしコミットする。make_release が要求・spec が exe に入れる)。差し込み {{APP_VERSION}} {{CLI_HELP}} {{CONFIG_TABLE}} {{TOC}}、版の数字直書き禁止。test_manuals が画面の text=/title=/filetypes= の定数と CLI オプションが日英両方に載ること、引用した画面の文・ログ語がコードに存在すること、派生・Fix・履歴の話題が無いこと、日英の構造対応、個人情報・内部語が無いことを機械で見る。画面の写真は別デスクトップ(CreateDesktop)+PrintWindow で人の画面・前面窓・クリップボードに触れず撮る(alpha=0 の窓は Tk が最初のイベントで前面を奪い使えなかった)。確認の messagebox は撮れないので文で説明。

- 出典: `docs/development.md、RCZ2MES_M4_report.md 2・4章、tools/build_manual.py・make_manual_shots.py`
- 確度: 実測

### CC運用の型: 指揮役CC＋サブエージェントの段（計画→検分→実装→検分→直し）

設計・指揮役のCCが、案件ごとに『A計画(サブ)→計画の検分(pass/return)→B実装(サブ)→報告の検分(試験を走らせ直す)→C直し』を回す。サブは Sonnet 5.5・effort medium、git の状態を変えない。段の間の引き継ぎはファイルだけ。発注書(order)・計画・計画の検分・報告・報告の検分を _Prompt/01_designai と 02_buildai に残す。実装後 Codex レビューは1案件最大2回(『1回目で2回で刈り取れるよう重大なものから全部』『2回目は直しの確認と新規のみ』『読むだけ・試験ビルドは走らせない』を依頼文に明記)。棄却は理由必須(例: 悪意あるZIPのメモリ枯渇＝手元の道具なので棄却・再起動条件つき)。2回後に critical/high が残れば追加レビューせず直して escalation に残す。検分は『実物で前提を確かめる』(コードを grep・ファイルを実測)ことが肝で、計画の前提がまちがっていた例(F6)が実際に出た。

- 出典: `_Prompt/01_designai/RCZ2MES_process.md、RCZ2MES_001_design.md『実装の進め方』、各 *_plan_review.md・*_report_review.md、RCZ2MES_M3b_report.md 6章D15`
- 確度: 実測

### 『完了』はらいおの Analyzer での視認まで。報告は3階層Before/After

テストPASSは完了でない。報告は『実装済み・らいおの確認待ち』と書き、3階層(コード/らいおが見る挙動/らいおの確認＝未受領)の Before/After、事実・推測・未確認の分離、ファイル名:行番号、受け入れ条件ごとの一次証跡(実行コマンドと出力の写し)を必須にする。らいおに見てもらう確認は表(何を見る・期待)1枚、返答は4項目以内に絞る。見る場所を示さなかった手順書(日付)は不備として記録。指揮役が自分で Analyzer を起動して見られる範囲(ラップの時間・Overviewの線・Circuit の軌跡)は先に見てらいおの手数を減らす(承認後)。

- 出典: `CLAUDE.md 作業ガード3、_Prompt/01_designai/RCZ2MES_process.md 5章、RCZ2MES_M1_analyzer_check.md、RCZ2MES_M3a_analyzer_check.md`
- 確度: 実測

### 残玉は『必ず対応するリスト』で受け皿を作り、放置は再起動条件つき

RCZ2MES_BOUND_PENDING.md(B1〜B23)に、各玉を『踏み抜く(いつ・どこへ)』『放置(理由＋再起動条件)』の二値で登録し、済んだら『済』にして行を消さない。発注書の What へ移した先を書く。例: 派生チャンネル・Fix・履歴は『らいおが RCZ で計算したいチャンネルを挙げたとき』まで放置、D&D の実コンソール目視は放置、共有フォルダ既定は『知り合いが使い始めたら』。手仕舞い記録(RCZ2MES_CLOSE.md)に版・commit・使っている exe・配布 ZIP・完了基準・再起動条件を書く。

- 出典: `_Prompt/01_designai/RCZ2MES_BOUND_PENDING.md、RCZ2MES_CLOSE.md`
- 確度: 実測

### git・コミット運用（このレーンだけの例外）

グローバルは『Git状態変更禁止・指示の都度』だが、RCZ2MES は CLAUDE.md 作業ガード5でらいお承認(認証パスワード)により、指揮役CCが検分を通った案件ごとにコミットし origin main へ push 可。1案件=1コミット、明示パスのみ add(-A・.・commit -a 禁止)、add の前後でインデックス確認、末尾に Lane: トレーラと Co-Authored-By、push 前に送り先提示、force・rebase・reset禁止、コミットごとにらいおへ1行報告、サブエージェントに git 状態を変えさせない。MBD2MES で同じ例外を使うなら新たにらいおの承認と CLAUDE.md 記録が要る。origin=VTRiot/RCZ2MES_dev(非公開)。

- 出典: `C:/_Prog/ECU/Logger/RCZ2MES/CLAUDE.md 作業ガード5、CLAUDE.local.md『決まりの変更の記録』`
- 確度: 実測

### bash でのパス地雷・読むだけの場所

LD2MES のフォルダ名に [MoTeC] の角括弧が含まれ、bash のグロブ文字なので Bash では必ずクォート、PowerShell は -LiteralPath。G:\マイドライブ(日本語パス)は Python へ引数で渡しスクリプトに直書きしない。原本(G:\ の RCZ、C:\RaceData、2D インストール先 C:\Program Files (x86)\Race2026、C:\ProgramData\Race2026)は読むだけ、試験は SHA-256 照合したコピー(_test_fixtures\)で。実データ前提はファイル名でなく SHA-256 で識別する。制御文字の \b を正規表現に生バイト0x08で書いてしまい .ld に当たらない試験になっていた例(M3b で発見・修正)。

- 出典: `CLAUDE.local.md パス取り扱いの注意、CLAUDE.md 作業ガード1・2、RCZ2MES_M3b_report.md 2章`
- 確度: 実測

### MES の名前・長さ・書き出し形

MES は <名前>.MES フォルダに DDD・A??(1チャンネル1ファイル)・空CAL(+HED/.IXR/.STI)。DDD は cp1252/CRLF、節[hex]、4=名前,単位,略号。名前の長さは49文字でも Analyzer が開けた(B3)ので既定名(RCZファイル名ベース)は長いままで良い。2D の知らない記録ファイル(RCZ2MES_record.txt、UTF-8)が MES に入っても Analyzer は困らない(LD2MES の前例＋実際に開けた)。DDD名は短い名前(Longitud 等)の別欄がある点に注意。

- 出典: `RCZ2MES_001_design.md、RCZ2MES_M1_analyzer_check.md 5章、BOUND_PENDING B3`
- 確度: 実測

### LD2MES 参照時に先に潰した最大の未知(U1/U2)は後続PJで再利用できる

2D の GPS の書き方(U1: 生の名前で地図が出るか、U2: 機器の印と [GPS] 節が要るか)は LD2MES レーンも未確認だった。RCZ2MES は時刻合わせが不要で試作が早いため最初のM1で試作8本(V1〜V4×2セッション)を作りらいおに見てもらい、結果を LD2MES レーンへ渡した。MBD2MES は同じ答え(V4 名＋Event.ini 名一致)を最初から使い、M1 の試作を減らせる。ただし Honda ロガー固有の GPS レート・座標系・単位(緯度経度の整数倍率)は別途確認が必要。

- 出典: `RCZ2MES_001_design.md 結論3・LD2MES レーンとの分担、RCZ2MES_M1_analyzer_check.md`
- 確度: 実測（RCZ2MES）。MBD へ同条件で効くかは未確認

## 運用の決まり

- CLAUDE.md は frontmatter(pikes_version r1.3 / os manx / manx_version r10 / manx_role managed・CCPIT managed)付き。『最上位命題(らいおの言葉の逐語)＝LD2MES とコンパチ・変換後の MES を らいおが Analyzer で開き地図(GPS軌跡)含め正しく見えるのを視認』『役割とレーン表』『参照プロジェクトとの関係(LD2MES/2D_General は読み取り専用・流用は写してから直す・元を import しない)』『入力形式の要点(実測と事実の分離)』『環境』『作業ガード』『出力』の構成。CLAUDE.local.md は git 管理外(.gitignore)で、絶対パス表・パス取り扱い注意([MoTeC]角括弧・日本語パスは引数で)・検証材料(ファイルの SHA-256 と中身の実測)・環境メモ・決まりの変更の記録・2D知見ハブへのポインタ(新知見は確度付きで1〜3行ハブへ追記)
- 作業ガード1: G:\マイドライブの原本・C:\RaceData\・2Dインストール先・C:\ProgramData\Race2026\ は読むだけ。試験はコピー。2D Analyzer(と Decompress2D・CalcTool64)の起動は らいおの承認を取ってから(開いて保存すると共有設定を書き換えうる)
- 作業ガード2: 出力文書は『事実／推測／未確認』を書き分け、コードの挙動には ファイル名:行番号。実データ前提はファイル名でなく SHA-256 で識別
- 作業ガード3(完了の定義): テスト PASS は完了でない。らいおが Analyzer で変換結果を視認するまで『完了』と宣言しない(報告は『実装済み・らいおの確認待ち』)
- 作業ガード4: 上書き前に .bak(.m2c.bak/.m3a.bak 等で既存 .bak を上書きしない)
- 作業ガード5(このレーンだけの例外): 検分を通した案件ごとに指揮役が自分のタイミングで commit・origin main へ push 可(1案件=1コミット・明示パス add・Lane: トレーラ・force 等禁止・サブエージェントに git 状態を変えさせない)。らいお認証パスワードで承認し CLAUDE.local.md に記録。MBD2MES では新規に承認が要る
- 出力: 日本語・簡潔。報告書・計画書は MD を _Prompt\02_buildai\ へ(report_id・冒頭『本報告書の読者と目的』・末尾『用語集』・同名HTMLを md2html.cjs で生成し --verify・外部依存なしの完結HTML)。らいおへの質問は最小回数・一度に一つの判断・選択式。レビュー(Codex)は1案件最大2回
- 実装はサブエージェント(Sonnet 5.5・effort medium)に任せ、指揮役CCが計画と報告を『検分』する(実物で前提を確かめ pass/return)。段の間の引き継ぎはファイルのみ。進め方は _Prompt/01_designai/RCZ2MES_process.md(全案件共通)に固定し、発注書と食い違えば発注書が正。_Prompt/01_designai に発注書・検分・必ず対応するリスト・手仕舞い記録、02_buildai に設計書・計画・報告・Analyzer確認依頼
- サブエージェントの変えない決まり: git状態を変えない・編集前 .bak・読むだけの場所を守る・Analyzer 等を起動しない・人間の窓/クリップボードに触らない(GUI試験は withdraw() した Tk)・時刻は書く直前に測る・LD2MES は写して使い provenance に記録・実データ試験材料は _test_fixtures\ にコピーしSHA-256照合・新規外部ライブラリは計画書で理由を書き検分を通す(Python3.11・numpy・tkinter標準のみ)
- 試験: tests/test_*.py(unittest)・リポのルートで `python -m unittest discover -s tests`(単独は -p)。全試験は1回(直した後にもう1回まで)。試験出力は scratch か一時フォルダ(リポ直下・_test_fixtures・out を書き換えない)。実環境の設定・対応表・dist・release・共有フォルダに触れない(RCZ2MES_SETTINGS_DIR で隔離)。最終 690本・OK(skip4は exe 作り直し前のみ)・約150秒
- 配布形態: PyInstaller 単体 exe(windowed・アイコン ICON\RCZ2MES.ico・アプリID RCZ2MES.Converter)＋ZIP(RCZ2MES_v<版>-<commit7桁>.zip＋.sha256、release/ 直下は最新のみ・前は release/old)。git には ZIP を入れない(release/README.md のみ追跡)。らいおは CLaunch の rcz2mes から dist\rcz2mes.exe を開く(ZIP の中身を dist にも置く)。exe を動かすと隣に設定(rcz2mes_config.json・channel_map.json)ができる=dist は .gitignore。版を上げるラウンド: release_notes.md に日英の節→APP_VERSION→マニュアル作り直し→写真撮り直し→全部コミット→exe作り直し→make_release
- .gitignore: build/ dist/ __pycache__ *.bak *.bak.* *.corrupt_* CLAUDE.local.md rcz2mes_config.json channel_map.json scratch/ out/(走行位置を含む生成物) /release/*(README除く) dist_build/_gen/。.gitattributes: 写し4本とrace_envを eol=lf、tests/golden・tests/fixtures を -text、*.rcz binary、dist_build/*.bat を eol=crlf(cmd.exe)。*.py の CRLF 警告はコミット前に確認
- Windows 作法: bat は ASCII+CRLF。ランチャー等の非 ASCII は注意。制御文字は \xNN/\b エスケープで書く(生0x08混入で試験が空振りした実例)。日本語パスは引数で渡す。人の画面に触れる試験・撮影は別デスクトップ(CreateDesktop)＋前面窓監視(GetForegroundWindow を0.1秒ごと記録し変われば異常終了)

## 読むべき文書

- C:/_Prog/ECU/Logger/RCZ2MES/CLAUDE.md — 最上位命題・役割・参照PJとの関係・作業ガード(完了の定義・git例外)の型。MBD2MES の CLAUDE.md の雛形
- C:/_Prog/ECU/Logger/RCZ2MES/CLAUDE.local.md — 絶対パス表・パス注意([MoTeC]角括弧)・検証材料SHA-256表・2D知見ハブへのポインタの型
- C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/02_buildai/RCZ2MES_001_design.md — 設計書r1。構成(写す/新規の表)・時間軸そろえ・既定チャンネル名・コンパチ表・段取りM1〜M4・数字の札・未確認リスク
- C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/01_designai/RCZ2MES_process.md — 全案件共通の進め方(段A/B/C・変えない決まり・試験の決まり・Codex2回・報告書の形)
- C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/01_designai/RCZ2MES_BOUND_PENDING.md — B1〜B23 の玉と判定(踏み抜く/放置+再起動条件)。地雷の履歴として最も情報密度が高い
- C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/02_buildai/RCZ2MES_M1_analyzer_check.md と RCZ2MES_M2_analyzer_check.md — GPS が地図に出る条件(V1〜V4・Event.ini 対照)の実測。MBD2MES 最初の1週間で必読
- C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/02_buildai/RCZ2MES_M3a_report.md と RCZ2MES_M3a_analyzer_check.md — .IXR/.STI の形・ラップ境目・セクター通過・Analyzerでの結果(r4が最新)
- C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/02_buildai/RCZ2MES_M2_report.md(段C追記含む)・RCZ2MES_M3b_report.md・RCZ2MES_M3c_report.md・RCZ2MES_M4_report.md — 各案件の完了報告(Codex指摘と棄却理由・計画との差・事実/推測/未確認)。M4_report_review.md 末尾に手仕舞い時の exe/ZIP 作成・Analyzer確認の実績
- C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/01_designai/RCZ2MES_CLOSE.md — 手仕舞い時点の状態(v0.5.0 bc558de)と再起動条件
- C:/_Prog/ECU/Logger/RCZ2MES/docs/development.md — 動かす・試す・マニュアル/README生成・写真撮影・配布ZIP・設定の置き場・試験の期待値の作り方・レビュー依頼
- C:/_Prog/ECU/Logger/RCZ2MES/docs/provenance.md — 写したファイルの由来台帳の書式(元パス・commit・blob SHA・改変の要点)
- C:/_Prog/ECU/Logger/RCZ2MES/docs/racechrono_rcz_format.md — 入力形式の調査資料の型(確度ラベル【確認】付き・7章『道具を作るときの落とし穴』・6章 2D の MES 側の実測)。MBD の形式メモを作る時の雛形
- C:/_Prog/ECU/Logger/RCZ2MES/docs/release_notes.md と release/README.md — 日英リリースノートの書き方と ZIP の置き場の説明
- C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ.md（続き 2D_知見ハブ_Part2.md）— 2D の MES・DDD・ラップ(LAP/IXR)・Analyzer副作用の知見ハブ。新知見は確度付きで追記する運用(らいお 2026-11-12 Yes)
- C:/_Prog/ECU/Logger/RCZ2MES/gps_entries.py, hed_download.py, lap_files.py, lap_sections.py, event_ini.py, rcz_timeline.py, mes_writer.py — 流用候補のコード本体(docstring に決定の根拠と出どころが書かれている)
