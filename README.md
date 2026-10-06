# Irodori-TTS Speaker Training GUI

Irodori-TTS v4/v4.1向けのSpeaker Inversion学習GUIです。既存のIrodori-TTS環境へ必要ファイルをコピーするだけで利用できます。GUI専用のPython環境は不要です。

## 導入と起動

1. Irodori-TTS本体をセットアップし、Whisperサーバーを起動します（既定: http://127.0.0.1:8000）。
2. このリポジトリをZIPでダウンロード・展開し、次の7ファイルを、`train.py` があるIrodori-TTSフォルダへドラッグ＆ドロップします。

```text
speaker_training_gui.py
speaker_training_job_runner.py
speaker_training_transcribe_client.py
start_speaker_training_gui.bat
stop_speaker_training_gui.bat
stop_speaker_training_gui.ps1
open_when_ready.ps1
```

3. `Irodori-TTS/speaker-training/<話者名>/audio/` に学習音声を配置します。
4. コピーした `start_speaker_training_gui.bat` をダブルクリックします。GUIの既定URLは http://127.0.0.1:7862 です。

Irodori-TTS本体の `README.md`、`LICENSE`、`docs`、`tests` を置き換える必要はありません。上記7ファイルだけをコピーしてください。

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
  start_speaker_training_gui.bat
  stop_speaker_training_gui.bat
  stop_speaker_training_gui.ps1
  open_when_ready.ps1
  speaker-training/<話者名>/audio/
  speaker-embeddings/<話者名>/<日時>/
```

## 操作

文字起こし → 音声付きレビュー・修正・承認 → manifest/latent生成 → 話者埋め込み学習 → チェックポイント比較。

学習とテストはIrodori-TTS本体のコードとuv環境を使用します。文字起こしだけがWhisper APIを利用します。API推論サーバー経由の学習ではありません。現在のGUIはCUDAを使用します。

## 既存配置からの移行

旧GUIを停止し、実行中のジョブがない状態で、既存の `speaker-training` と `speaker-embeddings` をIrodori-TTS側へコピーしてください。同名フォルダがある場合は内容を確認してからコピーしてください。旧データは動作確認まで保持してください。

`metadata.jsonl` などには旧音声の絶対パスが含まれるため、コピー後にGUIのレビューで「修正と承認状態を保存」を実行し、manifestを再生成してください。既存の学習済み埋め込みはそのまま利用できます。

従来の別ディレクトリ配置も引き続き利用できます。起動バッチは同じフォルダの本体を優先し、見つからなければ `IRODORI_TTS_ROOT` や隣接フォルダを確認します。

## マニュアル

- [日本語](docs/MANUAL_JA.md)
- [English](docs/MANUAL_EN.md)

## License

MIT。Irodori-TTS、Whisper、モデルのライセンスはそれぞれの配布元に従います。
