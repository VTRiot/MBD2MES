# -*- coding: utf-8 -*-
"""変換ソフト用の、アプリに依存しない進捗ダイアログ一式（テンプレート）。

このフォルダごと自分のアプリへ写し、パッケージ名は好きに変えてよい（中は相対 import だけ）。
  progress.py         段の名前と重み（アプリが渡す設定）・全体の %・残りの目安
  jobs.py             変換を別スレッドで回し、進み・ログ・結果を主スレッドへ運ぶ
  progress_dialog.py  モーダルの進捗ダイアログ（Converting...・Cancel・Done）
  busy_animation.py   右の余白で動く GIF

使い方の最小例は、このフォルダの外の gui_wiring_example.py。
"""
