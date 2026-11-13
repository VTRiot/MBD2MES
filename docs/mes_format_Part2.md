---
title: MES 書き出し側リファレンス（MBD2MES 用）part2 ラップ・Event.ini・GPS・試験・食い違い・未解明・出典
status: active
updated: 2026-11-13
upstream: C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ.md
---

# MES 書き出し側リファレンス part2/2

前半: part1（読者と目的・確度ラベル・構成・DDD・生データ・HED）。確度ラベルは part1 冒頭と同じ。

## 5. ラップ・セクター（LAP・IXR・STI）

- 境界の正本は `.LAP`（トリガそのまま）と `.IXR`（ダウンロード後に直した版）。Analyzer は IXR があれば IXR、無ければ LAP を使う。HED の `[Laptimes]` は表示用の写し（ハブ §4、`mes-format.md` 結論）[実測]。2007 年資料の LAP・IXR の見出しは中身と逆（ハブ §4）
- 書き出しは `.IXR` と `.STI` だけにした。`.LAP` だけの形は使わず確かめていない（`Ld2Mes_013_owner_check.md` 98 行）[未確認]。LD2MES の 013 試作では、P4（`_DN`＝下りだけの境目＋`.STI`、IXR＋`MainSamplingRate=400` だけの最小 HED）でラップが出てセクターが出た（同 90〜98 行）。P1〜P3・P5〜P7 は見ていない（同 98 行）
- `.IXR` の符号化（int32 リトルエンディアンの語の列。`RCZ2MES/lap_files.py:61-77`、仕様の出どころは LD2MES 013 でらいおが確認した P4）:
  - `0, 0`／`(標本番号, 累積距離 m)×N`（境目 N 本。標本番号は 0 以上で厳密に増加）／`(記録の終わりの標本, 全体の距離 m)`／`(N<<16)|offset`（offset＝8＋8×(N+1)）／`MainSamplingRate`／`N`／`0`
  - N の上限は offset が 16 bit に収まる範囲（`lap_files.py:37`）。0 本なら IXR を書かない（`:87-100`）
  - 標本番号＝floor((t−t0)×Hz/1000＋0.5)（`lap_sections.py` 冒頭の docstring）。同じ標本の境目は 1 本にまとめる
- 結果 [受理]: 3 本の RCZ（片道・周回・ジムカーナ）で、Analyzer のラップが RaceChrono のラップと 1 標本（400 Hz で 2.5 ms）以内で一致し、最速の印も同じ周になった。周回でつながるラップ（前の周の終わり＝次の周の始まり）も数えられた。Analyzer はラップを切り直さず、Event.ini に `[TrackChecked]` も書かなかった（`RCZ2MES_M3a_analyzer_check.md` §1）。Analyzer の一覧は「境目の数＋1」本に見え、先頭は記録の前の区間、末尾は後の区間と読める [推定: 3 例の観察からの一般化]
- `.STI` の符号化（`lap_files.py:79-85`）: `件数, MainSamplingRate, 0`、続けて `(標本番号, 区間番号 0 始まり, −1, −1)×件数`（時刻順）。3・4 語目の −1 は 013 で調べた実物 1026 件が全部同じ値（同 :28）。区間が 4 つ表示され、合計がラップに合った（301・688・826・1260 m、Analyzer が HED の `[SectionTimes]` へ同じ値を書いた）[受理]（M3a 確認 3-2、らいおが Section times の画面で確認）
- 実データの IXR の末尾 16 byte は書き出し側の末尾と値が違う。実データ F4 を int16 で読むと `[80,8,7088,0,8,−1,0,337]`（ハブ・`mes-format.md:73`）。int32 の語に直すと `[(8<<16)|80, 7088, 0xFFFF0008, 337<<16]` で、1 語目は (N<<16)|offset（N＝8、offset＝8＋8×9＝80）と書き出し側の式に合う [推定: 計算]。2 語目は書き出し側では MainSamplingRate の位置だが 7088 で、3 語目は上位が −1、4 語目は 337 が入る。これらの意味は未解明（§10）。書き出し側の末尾でもラップは出た [受理]
- 距離の列: 実データの F4 は途中から 1 周ごとに +1667 m（`EVENT.INI` の FIXEDTRACKLENGTH＝1667）でそろえた値らしい [推定]。RCZ2MES は GPS の累積距離を使う。算出の詳細は `lap_sections.py` の LapPlan で、本調査では未精読 [未確認]
- ラップの「距離でのトリガ挿入」専用機能は Analyzer に見つからない（ハブ §4）。LapChecker・CalcTool `SetLapTrigger` が近い

## 6. Event.ini（イベントフォルダ）

- 場所は MES の親フォルダ。cp1252 の INI。`[Special channels]` の `GPS_Latitude`・`GPS_Longitude` が、地図に使う位置チャネルの名前を指す。キー・値は大文字小文字を区別しない（実物に `GPS_LATITUDE=LATITUDE` がある）（`event_ini.py:24-41`）[実測]
- 変換側は書かない（RCZ2MES・LD2MES とも）。読んで、書く MES の位置チャネル名と違えば警告するだけ（`event_ini.py:44-61`）
- Analyzer は、行が無いとき `GPS_Longitude=Longitude`・`GPS_Latitude=Latitude` を書き足す。V4 を開いたときに足され（M1 5-2）、A の試験イベントでも再現した（M2）[受理]。他に `Laptimes segments=` などの欄があり意味は [未確認]（ハブ §5）
- 実データの `C:/RaceData/` 配下の Event.ini には `GPS_Latitude=Latitude` の形が 5 イベントにある（RCZ2MES M1 確認 5-2）[実測]
- 親フォルダには `Users.ini`（実行ユーザー名の追記）・`GPS Sections.txt`（セクターの線の位置。イベントに 1 つで MES ごとでない。別コースの MES が同居したときの見え方は [未確認]・RCZ2MES 台帳 B19）が増えうる

## 7. GPS チャネル（地図を出す条件）

- 実データの形 [実測]（F5-02M-01.DDD を直接読んだ）: 生の位置 `[344] Lat_dez`・`[345] Lon_dez`＝`1=1,1080,C0,0,40,20,320`／`3=0,1,0,33D6BF95,0,0,…`／`6=FFFFFFFC,W,S228D9,A45,,45`、12.5 Hz・4 byte 幅（符号付きと読める）・倍率 1e-7。計算後 `[35C] Latitude`・`[35B] Longitude`＝種別 101・`6=8,F,S228D9,C05`（Longitude は S228D10・C04）＝float64・gain 1。`[340] V_Sat`＝u16・0.01 km/h・A41。`[35E] V_GPS`＝種別 101・C08。単位は deg・km/h
- 書く形 [受理]（RCZ2MES 変種 V4 が既定。`gps_entries.py:123-151`、M1 確認 5 章でらいおが地図を確認）:
  - 名前 `Latitude`・`Longitude`・`V_GPS`（短い名前は `Latitude`・`Longitud`）
  - 位置は 32 bit・符号なし `<u4`・度×1e7 の整数・倍率 `33D6BF95`・offset 0・`6=` 第1 `FFFFFFFC`・型文字 `W`（`gps_entries.py:28-58`）。元の RCZ の位置は 1/6,000,000 度の整数で、度へ換算してから符号化する（`rcz_channels.py:24,165`）
  - `6=` 第3 に実物の機器の印（Latitude `S227D9`・Longitude `S227D10`・V_GPS `S227D5`・Course `S227D8`・Altitude `S227D11`・HorAccu `S227D14`。`gps_entries.py:133-139`）。F4 の値の写しで、F5 は `S228` 系 [実測]。印の意味・必要性は未確認（台帳 B7）
  - HED に `[GPS]` 節: `Rate=10`・`Version=22.1213`・`MaxDropOutTime=0`・`ChannelRate_Hi=100`・`ChannelRate_Lo=10`・`LeapSecond=18`・`ShiftTime=0`・`AverageMulti=4`・`LateralDynamics=2`・`MSR=<基準Hz>`（`gps_entries.py:82-92`。F4 実物 HED の写しで、MSR と ShiftTime だけ本ツールの値）
  - 付随チャネル: `Course`（deg・周期値）・`Altitude`・`HorAccu`・`Distance_GPS`（m）。地図に効くと確かめたのは保護した 3 本（Latitude・Longitude・V_GPS）だけ（`map_rules.py:21`）
- 地図が出る条件の観察 [受理]: 生の名前 `Lat_dez`・`Lon_dez` に `[GPS]` 節と印を付けた V3 では出ず、V4 で出た。V3 と V4 の DDD の差は `4=` の 3 行（名前）だけで HED は同じ（M1 5 章、diff で確認）。Event.ini に `GPS_Latitude=Lat_dez`・`GPS_Longitude=Lon_dez` と書いたイベントでは V1（生の名前・`[GPS]` 節なし）でも地図が出た（M2 確認 #3）。結論「Analyzer は Event.ini の `[Special channels]` に書かれた名前のチャネルを位置として使う」は、この 2 本の対照から導いた推論 [推定]（M2 #4 の区分）
- つまり MBD2MES の最小要件の見立ては、位置チャネルを 32 bit・倍率 1e-7 で書き、その名前を Event.ini の GPS_Latitude／GPS_Longitude の値と一致させること [推定]。名前を `Latitude`・`Longitude` にして Event.ini に行が無ければ Analyzer が足す。`[GPS]` 節・機器の印・V_GPS が地図に要るかは未検証（V4 から外した実験が無い）[未確認]
- 名前を `Latitude`・`Longitude`・`V_GPS` から変える／出さないと地図が壊れる（RCZ2MES が GUI で変更を禁止する根拠）。`Course`・`Altitude`・`HorAccu` の名前を変えて壊れないかは [未確認]（台帳 B16）
- 地図タイルは Analyzer がネットワークから取得し、`C:/RaceData/GPSMapCache/` に 1 ファイル約 100 MB（実測 104,857,654 byte）保存する [実測]（`HA22S_M130_hed_format_decode.md` §2.1）。オフライン時の挙動は [未確認]
- 緯度 0 未満・経度 0 未満（南半球・西半球）は書けない（part1 §2-3）。MBDA2 の用途が国内なら実害なし [推定]
- 1 Hz に落ちた区間（RCZ の場合は内蔵 GPS への切替）は、標本の間を直前の値で保つ設計（part1 §3）。Analyzer での見え方は [未確認]（M1 5-1 は「窓が小さく判断できない」、確認表も「答えは無い」。ALT-V4 は Circuit 窓に軌跡が出たところまで）

## 8. 書き出しの必須条件（まとめ）

1. 全チャネルの標本数＝レート×共通の時間長。短いチャネルは黙って捨てられる [実測]
2. レートは基準 Hz の整数分の 1。基準は DDD から読まれる。400 Hz は受理実績あり [受理]。800 Hz は 2D 純正の実走ログでの実績（変換ソフトで書いた MES の受理は未確認）
3. DDD は cp1252・CRLF・節ごとに空行。DDD の通し番号・拡張子・名前の一意性を守る（part1 §2）[受理]
4. 位置は 32 bit・倍率 `33D6BF95`・名前を Event.ini と一致 [受理: 書いた形。一致が要るのは推定]
5. HED の `[DOWNLOAD]` に日付・時刻・`MainSamplingRate` を書くと日付表示が出て、IXR の標本番号が読める [受理]。ラップを書くなら IXR（と STI）[受理]
6. 作業フォルダで全部書いてから rename し、不変量チェックを通す [受理]

## 9. 食い違い（両方の根拠を並べる。どちらにも丸めない）

| # | 論点 | 一方の根拠 | もう一方の根拠 |
|---|---|---|---|
| X1 | DDD の文字コード | ハブ §2・2007 年資料 §3 の【注】: latin-1 で読む（cp1252 だと未定義バイトで落ちる実データあり） | `mes_reader.py:24`・`ddd_invariants.py:49`・`mes_writer.py:45`: cp1252・strict。`mes-format.md:26` の表も cp1252・CRLF。書く側は cp1252 で受理 [受理] |
| X2 | 型文字 W の意味 | 2007 年資料 §3-2（MD 版）: W＝符号なし 2 byte、I＝符号なし 4 byte、F＝単精度 | 実データ F5 の Lat_dez は `6=FFFFFFFC,W`（`6=` 第1 から 4 byte 幅 [実測]。符号付きは推測＝`gps_entries.py:29` のコメントも「推測」）。幅は `6=` 第1 が決める。書き出し側も位置を W＋FFFFFFFC＋`<u4` で書き受理 [受理]。符号の扱いは正の値でしか確かめていない |
| X3 | ラップ系を書くか | ハブ §3: 参考実装はラップ系（LAP・IXR・HED）を書かない（2026-11-12 時点の記述） | RCZ2MES M3a（`1ecd45f`）は IXR・STI・HED を書き、Analyzer が受理 [受理]。LD2MES には `lap_files.py`（Ld2Mes-015）があり、013 の P4 で IXR・STI 形式が受理された（Ld2Mes-015 の書き出し全体の受理は本調査で未確認）。ハブ §3 は古くなっているので、解けた分をハブへ移す対象 |
| X3b | HED は無ければ Analyzer が作る | ハブ §3: 書かなくてよい | `[DOWNLOAD]` を書くと日付が出る（M3a 3-2）。両立する（書けば残り、書かなければ作られる）が、書くほうが日付表示で優位 |
| X4 | IXR 末尾 16 byte | ハブ §5: 7088・337 の意味は未解明（実データ F4） | 書き出し側は末尾を `MainSamplingRate, N, 0` で書いて受理 [受理]。実データの語と一致しない（part2 §5）。受理の事実は実データの意味を解かない |
| X5 | サンプル数の式 | LD2MES `mes_writer.py:48-57`: round(レート×時間長) | RCZ2MES `rcz_timeline.py:90-92`: ceil(T×レート/1000)。どちらも Analyzer が受理 [受理]。端数でどちらが要るかは [未確認] |
| X6 | V_Sat の非表示の原因 | `HA22S_M130_hed_format_decode.md` §5.2（09-04）: 原因未解明・最重要 | `mes_writer.py:48-57` のコメント: 短いチャネルが黙って捨てられた実測（同 09-04 の実機確認）。時系列で後者が解釈を与えたが、当時の報告は更新されていない |
| X7 | float64 の gain の読み取り | ハブ §3: 参考実装の読み取りの穴 | 写した `mes_reader.py:47-53` は `zfill(8)` と float32 前提で、16 桁を渡すとコード上は `struct.error`（RCZ2MES 側の読み戻しも未修正）[推定] |

## 10. 未解明（ハブ §5 を写し、実装から解けた分には注記）

- `.IXR` 末尾 16 byte の 7088・337 の意味。k=1・2 だけトラック長に揃っていない理由。注記: 1 語目は (N<<16)|offset で説明できる（§5）。残りは未解決
- `.IST`・`.STI`・`.SEC` のイベント ID と意味。注記: `.STI` はセクター通過の列として書け、Analyzer が読むと分かった（§5・[受理]）。`.IST`・`.SEC` は未解決
- HED `[DOWNLOAD]` の `LapMeter [m]=0`・`SecMeter [m]=0`・`TRIGGER [rpm]=0` の意味。注記: 書かなくても受理（part1 §4）。意味は未解決
- F5 でロガーがトリガに使った基準点の出どころ。F4 の IXR を作った Analyzer の操作。`EVENT.INI` の `Laptime segments=65.67` の意味。注記: 解けていない
- 2D の加工が DDD・A??・CAL を書き換えるか。注記: 実例では DDD のチャネル名の行 2 行だけが書き換わり、A??・CAL・HED は無変更（f6 調査 §3.1。書いた主体は不明）。行の特定は名前でなく拡張子で行うのが安全（同 §4）
- LapChecker がトリガ 0 本でも動くか。注記: 解けていない
- `3=` 第 7 項（3F800000）の意味。注記: 書き出し側は全節に定数で書いて受理（part1 §2-2。個別の A/B は未確認）。意味は未解決
- 2007 年資料の PDF の図の見た目。注記: 解けていない
- 追加（実装から出た新規）: `6=` 第 3 欄の機器の印（`S227D9` と `S228D9`）の意味と必要性（台帳 B7）。`1=` 第1〜第4 の意味。`5=` 第2・`2=`・`7=` の意味。負の座標・符号付き整数の書き方。MBD の `.MBD` 自体の構造は本書の範囲外

## 11. Analyzer で開いたときの副作用と試験の作法

- 副作用 [実測]（`HA22S_M130_hed_format_decode.md` §2.1、RCZ2MES M1〜M3a 確認書、f6 調査 M3）:
  - 開いた MES: HED を作る／更新する（`[Laptimes]`・`[SectionTimes]`）
  - 親フォルダ: `Event.ini`・`Users.ini`・`GPS Sections.txt`
  - `C:/RaceData/GPSMapCache/`（衛星画像・約 100 MB・ネットワーク取得）
  - `C:/ProgramData/Race2026/Analyzer.ini` の Recent Files（最近のファイル 10 件が入れ替わる。起動前の写し `Analyzer.ini.before_*` から戻した）
  - 開かなかった MES は無汚染（A/B 実験）
- 作法: ①試験はコピーで。原本（`C:/RaceData/` 配下）は読むだけ ②試験用のイベントフォルダを `out/` の中に作り、Event.ini・Users.ini を実イベントから写して置く ③Analyzer の起動は人の承認を取ってから（共有の設定を書き換えうる） ④起動前後で 4 範囲の差分を取る（MES フォルダ内・親フォルダ・`C:/RaceData/` 直下・`GPSMapCache/`）。RCZ2MES は Analyzer を窓メッセージと PrintWindow だけで操作し、RaceData の計測は書き込み拒否で保持した（M1 確認 5-1）⑤完了の判定は人が Analyzer でデータと地図を見ること。テスト PASS は完了でない
- 開いてよいものの目安: M1 試験は 33 チャネル（Nr 0〜32）のチャネル一覧が出た [受理]。メニュー操作が要る画面（Section times・チャネル一覧）は自動化で開けず、人の目が要った

## 12. 出典の一覧（絶対パス・/ 区切り）

- 上流正本: `C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ.md`・`C:/RagVault/VehicleDevelopment/ECU開発/ロガー_2D/2D_知見ハブ_Part2.md`
- 2007 年資料の MD 版・命名規則: `C:/_Prog/ECU/Car/HA22S_MoTeC_M130/Manuals/2D/2Dロギングデータ保存形式.md`・`C:/_Prog/ECU/Car/HA22S_MoTeC_M130/Manuals/2D/MES命名規則.txt`
- 実データ調査: `C:/_Prog/ECU/Logger/2D_General/_Prompt/01_designai/2DG_000_ref/research_raw/mes-format.md`
- HED 解読: `C:/_Prog/ECU/Car/HA22S_MoTeC_M130/Report/CC/260904_HED_Format_Decode/HA22S_M130_hed_format_decode.md`
- 書き出し実装（RCZ2MES）: `C:/_Prog/ECU/Logger/RCZ2MES/mes_writer.py`・`ddd_generator.py`・`ddd_invariants.py`・`lap_files.py`・`lap_sections.py`・`event_ini.py`・`gps_entries.py`・`hed_download.py`・`rcz_timeline.py`・`rcz_channels.py`・`map_rules.py`・`mes_reader.py`・`rcz2mes.py`
- 書き出し実装（LD2MES）: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/mes_writer.py`（RCZ2MES のものとバイト同一）・同フォルダの `ddd_generator.py`（改行を除き RCZ2MES と同一）・`lap_files.py`・`gps_channels.py`
- LD2MES の F6 調査: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/scratch/evidence_008/f6_2d_processing_findings.md`
- ラップ試作の Analyzer 確認（013）: `C:/_Prog/GMN_Gemini/04_Bike_Car/Ld2MesConverter/[MoTeC]Ld2MesConverter/_Prompt/02_buildai/Ld2Mes_013_owner_check.md`
- Analyzer での受理確認（RCZ2MES）: `C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/02_buildai/RCZ2MES_M1_analyzer_check.md`・`RCZ2MES_M2_analyzer_check.md`・`RCZ2MES_M3a_analyzer_check.md`
- 設計書・台帳（RCZ2MES）: `C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/02_buildai/RCZ2MES_001_design.md`・`C:/_Prog/ECU/Logger/RCZ2MES/_Prompt/01_designai/RCZ2MES_BOUND_PENDING.md`
- 実データ（読み取りのみ・DDD を直接読んだ）: `C:/RaceData/01_02M/25/0406-2_SuzukaTwin.25/F5-02M-01.MES/F5-02M-01.DDD`・`C:/RaceData/01_02M/25/0406-2_SuzukaTwin.25/F4-02M-01.MES/F4-02M-01.DDD`（機器の印と `.STI` の存在の確認のみ）

注記（調査の限界）: ハブ §6 のうち HED 解読以外の research_raw（help-chm・analyzer-strings・web）、LD2MES の HA22S 側報告（260905・260904 の LD2MES 実装報告）、RCZ2MES の `lap_sections.py` の距離の算出部分、Ld2Mes-015 の書き出し全体は精読していない。精読した範囲の外の記述は書いていない。
