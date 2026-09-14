# Irodori-TTS Speaker Training GUI 日本語マニュアル

[READMEへ戻る](../README.md) | [English Manual](MANUAL_EN.md)

## 1. 概要

このGUIは、Irodori-TTS v4/v4.1のSpeaker Inversion学習を補助します。

1. 話者音声をWhisperサーバーで文字起こし
2. 音声を再生しながら文章を確認・修正・承認
3. 承認済みデータからmanifestとlatentを生成
4. Speaker Embeddingを学習

Irodori-TTS本体やモデルは同梱しません。manifest生成と学習には、公式Irodori-TTSの`prepare_manifest.py`、`train.py`、uv環境を使用します。

## 2. 動作条件

- Windows 10またはWindows 11
- [uv](https://docs.astral.sh/uv/)が実行可能
- セットアップ済みの公式[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)
- 起動済みの[MiRai-Server-for-Whisper](https://github.com/Snail921/MiRai-Server-for-Whisper)
- Irodori-TTSの学習に対応したGPUと十分な空き容量

## 3. インストール

### 3.1 Irodori-TTS

使用するハードウェアに合ったextraを選びます。NVIDIA CUDA 12.8の例：

```powershell
git clone https://github.com/Aratako/Irodori-TTS.git
cd Irodori-TTS
uv sync --extra cu128
```

CPU、ROCm、Intel XPU等はIrodori-TTS公式READMEを参照してください。初回同期後、このGUIは`uv run --no-sync`を使い、選択済みのPyTorchバックエンドを変更しません。

### 3.2 Whisperサーバー

MiRai-Server-for-Whisperをセットアップし、`start_mirai_whisper_server.bat`を起動します。既定の確認先：

```text
http://127.0.0.1:8000/health
```

### 3.3 学習GUI

Irodori-TTSと同じ親フォルダーへクローンします。

```powershell
git clone https://github.com/Snail921/Irodori-TTS-Speaker-Training-GUI.git
```

```text
任意のフォルダー\
├─ Irodori-TTS\
│  ├─ .venv\
│  ├─ prepare_manifest.py
│  └─ train.py
└─ Irodori-TTS-Speaker-Training-GUI\
   └─ start_speaker_training_gui.bat
```

起動バッチは、同じ親フォルダーから公式Irodori-TTSを自動検出します。ドライブ文字やフォルダー名は固定されていません。

## 4. 起動と終了

Whisperサーバーを先に起動し、`start_speaker_training_gui.bat`をダブルクリックします。起動時に以下を確認します。

- 公式Irodori-TTSリポジトリと必要な学習ファイル
- `uv`とIrodori-TTSのuv環境
- Whisperサーバーの`/health`
- GUI用ポート7862

ブラウザーが開かない場合は<http://127.0.0.1:7862>を開きます。

終了時は`stop_speaker_training_gui.bat`を実行します。ブラウザーを閉じるだけではGUIサーバーは終了しません。実行中の文字起こし・manifest・学習を止める場合は、先にGUI内の停止ボタンを使用してください。

## 5. 話者データ

このGUIリポジトリ内に、話者ごとの`audio`フォルダーを作ります。

```text
speaker-training\
├─ 話者A\
│  └─ audio\
│     ├─ 001.wav
│     └─ 002.wav
└─ 話者B\
   └─ audio\
      └─ 001.flac
```

対応形式：`.wav`、`.flac`、`.mp3`、`.m4a`、`.ogg`、`.opus`、`.aac`、`.wma`

GUI起動後にフォルダーを追加した場合は「フォルダ一覧を更新」を押します。

## 6. 操作手順

### 6.1 文字起こし

「1. 文字起こし」タブで以下を設定します。

- **Whisper Model**：`turbo`、`large-v3`、`medium`、`small`
- **Language**：`ja`または`auto`
- **既存結果も再文字起こし**：キャッシュを無視して再処理
- **固有名詞ヒント**：キャラクター名、作品名、専門用語等

「文字起こしを開始」を押すと、各音声がWhisper APIへ送信されます。結果はキャッシュされ、既存の`metadata.jsonl`に手修正済み文章があれば保持されます。

### 6.2 文字起こし確認・修正

「2. 文字起こし確認・修正」で「文字起こしを読み込む」を押します。

- audioまたはtextセルをクリックすると、対応音声がプレイヤーへ反映され自動再生されます。
- 同じ行を再選択すると先頭から再生します。
- textセルは表内で編集できます。
- 学習に使う行だけapprovedを有効にします。
- 全件使用する場合は「全件を承認済みにする」を利用します。
- 編集後は「修正と承認状態を保存」を押します。

未承認の元音声は削除されず、次のmanifestから除外されるだけです。

### 6.3 manifest作成

「3. manifest作成・学習」で「学習準備を確認」を押し、承認件数、manifestの状態、latent数を確認します。

「manifestを作成」を押すと、承認済みデータだけを公式`prepare_manifest.py`で処理します。音声、文章、承認状態を変更した場合はmanifestを再作成してください。

### 6.4 Speaker Inversion学習

manifest処理の完了後、ベースモデルと設定を確認して「Speaker Embedding学習を開始」を押します。

| 設定 | 既定値 |
| --- | ---: |
| Precision | `fp32` |
| Batch Size | `16` |
| Gradient Accumulation | `1` |
| DataLoader Workers | `0` |
| Max Steps | `3000` |
| Save Every | `250` |

WindowsではDataLoader Workersを`0`にしてください。メモリ不足時はBatch Sizeを下げ、Gradient Accumulationを増やします。

ベースモデル欄には`model.safetensors`へのパスを指定します。GUIは環境変数`IRODORI_CHECKPOINT`、両リポジトリ内の`models-cache`、Hugging Face標準キャッシュからv4.1/v4-Smallを探索します。

学習結果：

```text
speaker-embeddings\話者名\YYYYMMDD-HHMMSS\
```

生成された`checkpoint_final.speaker.safetensors`は、対応するベースモデルとIrodori-TTSの`--ref-embed`で利用できます。

## 7. 環境変数

自動検出できないIrodori-TTSを指定：

```bat
set "IRODORI_TTS_ROOT=D:\AI\Irodori-TTS"
start_speaker_training_gui.bat
```

Whisperの接続先を変更：

```bat
set "MIRAI_WHISPER_URL=http://192.168.1.10:8000"
start_speaker_training_gui.bat
```

Whisper APIキーを使用：

```bat
set "MIRAI_WHISPER_API_KEY=your-api-key"
start_speaker_training_gui.bat
```

ベースモデルを指定：

```bat
set "IRODORI_CHECKPOINT=D:\models\Irodori-TTS-v4.1-Small\model.safetensors"
start_speaker_training_gui.bat
```

APIキーはコマンドラインやジョブログへ書き込まれません。

## 8. 生成ファイル

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

speaker-embeddings\話者名\日時\
```

`speaker-training`、`speaker-embeddings`、`models-cache`はGit管理対象外です。

## 9. GPUメモリ

manifest生成と学習ではIrodori-TTSとDACVAEをGPUへ読み込みます。学習前にIrodori-TTS推論サーバーや通常のGradio推論GUIを終了してください。

Whisperも同じGPUを使う場合は、文字起こし完了後にWhisperサーバーを終了してからmanifest生成・学習へ進むとVRAMを確保できます。保存済み文字起こしはWhisper停止後も利用できます。

## 10. トラブルシューティング

### `detected dubious ownership`

Gitが表示した正確なリポジトリだけを信頼対象に追加します。

```bat
git config --global --add safe.directory "T:/Irodori-TTS-Speaker-Training-GUI"
```

### `Irodori-TTS repository could not be found`

両リポジトリを同じ親フォルダーへ置くか、`IRODORI_TTS_ROOT`を指定します。

### `The official Irodori-TTS uv environment is not ready`

公式Irodori-TTSで、ハードウェアに合った`uv sync --extra ...`を実行します。

### `The Whisper server is not ready`

Whisperサーバーを起動し、`MIRAI_WHISPER_URL/health`の応答を確認します。

### セルを選択しても音声が再生されない

最新版へ更新して旧GUIを停止・再起動します。古いJavaScriptが残る場合は`Ctrl+F5`を押し、音声が`話者名\audio`に存在するか確認します。

### ポート7862が使用中

`stop_speaker_training_gui.bat`を実行します。不明なプロセスの場合、停止スクリプトは安全のため終了しません。

### manifestが古い

音声、文章、承認状態のいずれかが更新されています。「manifestを作成」を再実行します。

### CUDAメモリ不足

Irodori-TTS推論、Whisper、他のGPUアプリを終了します。必要ならBatch Sizeを下げます。

## 11. 更新

```powershell
git pull
```

更新後はGUIを停止・再起動してください。

## 12. ライセンス

このリポジトリは[MIT License](../LICENSE)で提供されます。Irodori-TTS、Whisper、モデル、学習素材にはそれぞれのライセンスと利用条件が適用されます。
