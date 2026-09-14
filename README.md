# Irodori-TTS Speaker Training GUI

[Irodori-TTS](https://github.com/Aratako/Irodori-TTS) v4/v4.1向けのSpeaker Inversion学習GUIです。

文字起こし、音声を再生しながらの確認・修正、承認データだけを使ったmanifest生成、Speaker Embedding学習、バックグラウンドジョブのログ確認と停止を、1つのGradio画面から操作できます。

Whisperは[MiRai-Server-for-Whisper](https://github.com/Snail921/MiRai-Server-for-Whisper)のHTTP APIを利用します。Irodori-TTSのPythonや学習コードは同梱せず、公式Irodori-TTSリポジトリのuv環境、`prepare_manifest.py`、`train.py`をそのまま使用します。

## 主な機能

- 話者ごとの音声フォルダー管理
- Whisper APIによる音声の一括文字起こし
- 既存の文字起こしキャッシュ再利用
- 手修正済み`metadata.jsonl`の保持
- 音声再生付きレビュー表
- 文字起こしの直接編集と承認管理
- 承認済みデータだけを使ったmanifest・latent生成
- Speaker Inversion学習
- 学習設定、ログ、進捗、出力先の表示
- manifest生成・文字起こし・学習ジョブの停止

## 必要なもの

- Windows 10またはWindows 11
- [uv](https://docs.astral.sh/uv/)
- セットアップ済みの公式[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)
- 起動済みの[MiRai-Server-for-Whisper](https://github.com/Snail921/MiRai-Server-for-Whisper)
- Irodori-TTSの学習に対応したGPU環境

## セットアップ

### 1. Irodori-TTSをセットアップする

NVIDIA CUDA 12.8の例です。使用するハードウェアに合ったextraは、公式Irodori-TTSのREADMEで確認してください。

```powershell
git clone https://github.com/Aratako/Irodori-TTS.git
cd Irodori-TTS
uv sync --extra cu128
```

一度`uv sync`が完了した後、このGUIは`uv run --no-sync`を使用します。Irodori-TTS環境を勝手に再同期したり、別のPyTorchバックエンドへ変更したりしません。

### 2. このGUIをクローンする

公式Irodori-TTSと同じ親フォルダーへクローンするのが最も簡単です。

```text
任意のフォルダー\
├─ Irodori-TTS\
└─ Irodori-TTS-Speaker-Training-GUI\
```

```powershell
git clone https://github.com/Snail921/Irodori-TTS-Speaker-Training-GUI.git
```

フォルダー名やドライブ文字は固定されていません。標準配置で見つからない場合は、起動前に公式リポジトリを明示できます。

```bat
set "IRODORI_TTS_ROOT=D:\AI\Irodori-TTS"
```

### 3. Whisperサーバーを起動する

MiRai-Server-for-Whisperの`start_mirai_whisper_server.bat`を起動し、次のヘルスチェックが応答することを確認します。

```text
http://127.0.0.1:8000/health
```

### 4. 学習GUIを起動する

`start_speaker_training_gui.bat`をダブルクリックします。準備が整うと、ブラウザーで次のURLが開きます。

```text
http://127.0.0.1:7862
```

終了するときは`stop_speaker_training_gui.bat`を実行します。ブラウザーのタブを閉じるだけではGUIサーバーは終了しません。

## データの配置

このリポジトリ内に、話者ごとの`audio`フォルダーを作成します。

```text
speaker-training\
└─ 話者名\
   └─ audio\
      ├─ 001.wav
      ├─ 002.wav
      └─ 003.wav
```

起動後にフォルダーを追加した場合は、GUIの「フォルダ一覧を更新」を押してください。

## 使い方

### 1. 文字起こし

話者とWhisperモデルを選択し、「文字起こしを開始」を押します。既存のAPI結果はキャッシュされ、再実行時に利用されます。「既存結果も再文字起こし」を有効にするとキャッシュを更新します。

既存の`metadata.jsonl`に手修正された文章がある場合、その文章は自動文字起こしで上書きされません。

### 2. 確認・修正

「文字起こしを読み込む」を押します。表のaudioまたはtextセルを選ぶと対応する音声が再生されます。textは表内で編集できます。学習に使用する行のapprovedを有効にし、「修正と承認状態を保存」を押します。

### 3. manifest作成・学習

「学習準備を確認」、「manifestを作成」の順に実行し、manifest処理の完了後に「Speaker Embedding学習を開始」を押します。

学習結果は次の場所へ実行ごとに保存されます。

```text
speaker-embeddings\話者名\YYYYMMDD-HHMMSS\
```

## 接続設定

Whisperサーバーの既定URLは`http://127.0.0.1:8000`です。別PCや別ポートを使用する場合は、起動前に環境変数を設定します。

```bat
set "MIRAI_WHISPER_URL=http://192.168.1.10:8000"
```

WhisperサーバーでAPIキーを有効にした場合は、次も設定します。

```bat
set "MIRAI_WHISPER_API_KEY=your-api-key"
```

APIキーはコマンドラインやジョブログへ保存されず、環境変数を通してクライアントへ渡されます。

## GPUメモリについて

manifest生成とSpeaker Inversion学習ではIrodori-TTSモデルとDACVAEをGPUへ読み込みます。Irodori-TTS推論サーバーや通常のGradio GUIを同時に動かすと、VRAM不足になる可能性があります。学習前にIrodori-TTSの推論プロセスを終了してください。

Whisperサーバーも同じGPUを使用する場合は、文字起こしを完了してからWhisperサーバーを終了し、その後manifest生成・学習へ進むとVRAMを確保しやすくなります。文字起こし結果はローカルへ保存されるため、レビューと学習時にWhisperサーバーは不要です。

## 生成されるファイル

`speaker-training`と`speaker-embeddings`は`.gitignore`の対象です。

```text
speaker-training\話者名\
├─ audio\
├─ metadata.jsonl
├─ transcription_review.csv
├─ review_state.json
├─ approved_metadata.jsonl
├─ train_manifest.jsonl
├─ transcriptions\
├─ latents\
└─ .jobs\
```

## トラブルシューティング

### Irodori-TTS repository could not be found

公式Irodori-TTSとこのGUIを同じ親フォルダーへ配置するか、`IRODORI_TTS_ROOT`を設定してください。

### The official Irodori-TTS uv environment is not ready

公式Irodori-TTSフォルダーで、ハードウェアに合った`uv sync --extra ...`を実行してください。

### The Whisper server is not ready

MiRai-Server-for-Whisperを先に起動し、`MIRAI_WHISPER_URL`とポートを確認してください。

### ポート7862が既に使用されている

`stop_speaker_training_gui.bat`を実行してから、もう一度起動してください。不明なプロセスがポートを使用している場合、停止スクリプトは安全のため終了させません。

## ライセンス

このリポジトリのコードはMIT Licenseです。Irodori-TTS本体、Whisper、および各モデルにはそれぞれのライセンスが適用されます。
