# Irodori-TTS Speaker Training GUI

Irodori-TTS v4/v4.1向けのSpeaker Inversion学習GUIです。既存のIrodori-TTS環境へ必要ファイルをコピーするだけで利用できます。GUI専用のPython環境は不要です。

## 導入と起動

1. Irodori-TTS本体をセットアップし、Whisperサーバーを起動します（既定: http://127.0.0.1:8000）。
2. このリポジトリをZIPでダウンロード・展開し、次の6ファイルを、`train.py` があるIrodori-TTSフォルダへドラッグ＆ドロップします。

```text
speaker_training_gui.py
speaker_training_job_runner.py
speaker_training_transcribe_client.py
speaker_training_test_worker.py
start_speaker_training_gui.bat
open_when_ready.ps1
```

3. `Irodori-TTS/speaker-training/<話者名>/audio/` に学習音声を配置します。
4. コピーした `start_speaker_training_gui.bat` をダブルクリックします。GUIの既定URLは http://127.0.0.1:7862 です。
5. 終了するには起動時に開いたCLIウィンドウでCtrl+Cを押してください。GUIが起動した学習・前処理ジョブとテスト用プロセスも停止します。ブラウザーを閉じるだけでは終了しません。

Irodori-TTS本体の `README.md`、`LICENSE`、`docs`、`tests` を置き換える必要はありません。上記6ファイルだけをコピーしてください。

```text
Irodori-TTS/
  .venv/
  train.py
  infer.py
  prepare_manifest.py
  configs/
  speaker_training_gui.py
  speaker_training_job_runner.py
  speaker_training_transcribe_client.py
  speaker_training_test_worker.py
  start_speaker_training_gui.bat
  open_when_ready.ps1
  speaker-training/<話者名>/audio/
  speaker-embeddings/<話者名>/<日時>/
```

## 操作

文字起こし → 音声付きレビュー・修正・承認 → manifest/latent生成 → 話者埋め込み学習 → チェックポイント比較。

学習とテストはIrodori-TTS本体のコードとuv環境を使用します。文字起こしはWhisper APIを利用します。


## マニュアル

- [日本語](docs/MANUAL_JA.md)
- [English](docs/MANUAL_EN.md)

## License

MIT。Irodori-TTS、Whisper、モデルのライセンスはそれぞれの配布元に従います。

## CLIログと通信診断

GUIのジョブログはCLIにも追記分が表示されます。通信診断は `speaker-training/.jobs/network.log` に保存され、CLIにも表示されます。音声要求の接続元・Range・HTTP応答と切断時刻を記録します。`peer_matched=False` の直前要求は候補であり、切断原因の確定ではありません。元の通信例外も表示します。
