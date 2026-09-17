# Irodori-TTS Speaker Training GUI

[Irodori-TTS](https://github.com/Aratako/Irodori-TTS) v4/v4.1向けのSpeaker Inversion学習GUIです。

文字起こし、音声を聴きながらの確認・修正、承認データからのmanifest生成、Speaker Embedding学習、ステップ別チェックポイントのテストまでを1つのGradio画面から操作できます。Whisper処理には[MiRai-Server-for-Whisper](https://github.com/Snail921/MiRai-Server-for-Whisper)のHTTP APIを使用し、学習とテストには公式Irodori-TTSクローンのuv環境とコードをそのまま利用します。

## Manuals / マニュアル

- [日本語マニュアル](docs/MANUAL_JA.md)
- [English Manual](docs/MANUAL_EN.md)

## Features

- Whisper APIによる音声の一括文字起こし
- キャッシュ再利用と手修正済み`metadata.jsonl`の保持
- セル選択による対応音声の自動再生
- 表内での文字起こし修正・承認管理
- 承認済みデータだけを使ったmanifest・latent生成
- Speaker Inversion学習、ログ表示、停止操作
- 保存されたステップ別Speaker Embeddingによるテスト音声生成・完了後の自動再生
- 公式Irodori-TTSリポジトリとuv環境の自動検出
- ドライブ文字やPython実行ファイルへの固定パスなし

## Quick start

1. 公式[Irodori-TTS](https://github.com/Aratako/Irodori-TTS)をクローンし、ハードウェアに合ったextraで`uv sync`を実行します。
2. [MiRai-Server-for-Whisper](https://github.com/Snail921/MiRai-Server-for-Whisper)をセットアップし、サーバーを起動します。
3. このリポジトリをIrodori-TTSと同じ親フォルダーへクローンします。
4. `speaker-training\話者名\audio\`へ学習音声を配置します。
5. `start_speaker_training_gui.bat`をダブルクリックします。

推奨配置：

```text
任意のフォルダー\
├─ Irodori-TTS\
└─ Irodori-TTS-Speaker-Training-GUI\
```

GUIは既定で<http://127.0.0.1:7862>、Whisperサーバーは<http://127.0.0.1:8000>を使用します。

詳しい導入方法、設定、操作手順、トラブルシューティングは[日本語マニュアル](docs/MANUAL_JA.md)または[English Manual](docs/MANUAL_EN.md)を参照してください。

## License

This project is licensed under the [MIT License](LICENSE). Irodori-TTS, Whisper, and their model weights are governed by their respective licenses and terms.
