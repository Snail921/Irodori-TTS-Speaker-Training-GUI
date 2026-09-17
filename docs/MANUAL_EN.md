# Irodori-TTS Speaker Training GUI — English Manual

[Back to README](../README.md) | [日本語マニュアル](MANUAL_JA.md)

## 1. Overview

This GUI assists with Speaker Inversion training for Irodori-TTS v4/v4.1.

1. Transcribe speaker audio through a Whisper server.
2. Listen to each clip while reviewing, editing, and approving its transcript.
3. Generate DACVAE latents and a training manifest from approved rows.
4. Train a reusable Speaker Embedding.

Irodori-TTS and its model weights are not bundled. Manifest preparation and training use `prepare_manifest.py`, `train.py`, and the uv environment from an official Irodori-TTS checkout.

## 2. Requirements

- Windows 10 or Windows 11
- [uv](https://docs.astral.sh/uv/) available from Command Prompt
- A configured checkout of the official [Irodori-TTS](https://github.com/Aratako/Irodori-TTS)
- A running [MiRai-Server-for-Whisper](https://github.com/Snail921/MiRai-Server-for-Whisper)
- A GPU supported by Irodori-TTS training and sufficient free storage

## 3. Installation

### 3.1 Irodori-TTS

Choose the backend extra for your hardware. Example for NVIDIA CUDA 12.8:

```powershell
git clone https://github.com/Aratako/Irodori-TTS.git
cd Irodori-TTS
uv sync --extra cu128
```

See the official Irodori-TTS README for CPU, ROCm, and Intel XPU options. After the initial sync, this GUI uses `uv run --no-sync`; it does not resync the project or replace your selected PyTorch backend.

### 3.2 Whisper server

Configure MiRai-Server-for-Whisper and start `start_mirai_whisper_server.bat`. Its default health endpoint is:

```text
http://127.0.0.1:8000/health
```

### 3.3 Training GUI

Clone this repository beside the official Irodori-TTS checkout:

```powershell
git clone https://github.com/Snail921/Irodori-TTS-Speaker-Training-GUI.git
```

```text
Any parent folder\
├─ Irodori-TTS\
│  ├─ .venv\
│  ├─ prepare_manifest.py
│  └─ train.py
└─ Irodori-TTS-Speaker-Training-GUI\
   └─ start_speaker_training_gui.bat
```

The launcher searches sibling directories for a valid official checkout. Drive letters and folder names are not hard-coded.

## 4. Starting and stopping

Start the Whisper server, then double-click `start_speaker_training_gui.bat`. The launcher verifies:

- The official Irodori-TTS checkout and training files
- `uv` and the Irodori-TTS uv environment
- The Whisper `/health` endpoint
- GUI port 7862

If the browser does not open automatically, visit <http://127.0.0.1:7862>.

Run `stop_speaker_training_gui.bat` to stop the GUI server. Closing the browser tab does not stop it. To terminate an active transcription, manifest, or training process, use its Stop button in the GUI first.

## 5. Preparing speaker data

Create one directory per speaker under `speaker-training`, with source clips in an `audio` subdirectory:

```text
speaker-training\
├─ Speaker A\
│  └─ audio\
│     ├─ 001.wav
│     └─ 002.wav
└─ Speaker B\
   └─ audio\
      └─ 001.flac
```

Supported formats: `.wav`, `.flac`, `.mp3`, `.m4a`, `.ogg`, `.opus`, `.aac`, and `.wma`.

If you add a speaker while the GUI is open, click **Refresh folder list**.

## 6. Workflow

### 6.1 Transcription

In the **1. Transcription** tab, select:

- **Whisper Model:** `turbo`, `large-v3`, `medium`, or `small`
- **Language:** `ja` or `auto`
- **Retranscribe existing results:** ignore cached results
- **Proper-name hints:** optional character names, titles, or specialist terms

Click **Start transcription**. Each clip is uploaded to the Whisper API. Results are cached, and manually edited text already present in `metadata.jsonl` is preserved.

### 6.2 Review and correction

Open **2. Review and correct transcription**, then click **Load transcription**.

- Clicking an audio or text cell loads the matching clip and starts playback.
- Selecting the same row again restarts playback from the beginning.
- Text cells can be edited directly.
- Enable **approved** only for rows to include in training.
- Use **Approve all** if every row is acceptable.
- Click **Save corrections and approval state** after editing.

Unapproved source files are retained and excluded only from the next manifest.

### 6.3 Manifest preparation

In **3. Manifest and training**, click **Check training readiness** to see approval count, manifest freshness, and latent count.

Click **Create manifest**. Approved audio is processed by the official `prepare_manifest.py`. Recreate the manifest whenever source audio, transcript text, or approval state changes.

### 6.4 Speaker Inversion training

After manifest preparation completes, verify the base model and settings, then click **Start Speaker Embedding training**.

| Setting | Default |
| --- | ---: |
| Precision | `fp32` |
| Batch Size | `16` |
| Gradient Accumulation | `1` |
| DataLoader Workers | `0` |
| Max Steps | `3000` |
| Save Every | `250` |

Keep DataLoader Workers at `0` on Windows. If memory is insufficient, lower Batch Size and increase Gradient Accumulation.

The Base Model field expects a path to `model.safetensors`. The GUI searches `IRODORI_CHECKPOINT`, `models-cache` under both repositories, and the standard Hugging Face cache for v4.1/v4-Small.

Training outputs are stored under:

```text
speaker-embeddings\Speaker name\YYYYMMDD-HHMMSS\
```

Use `checkpoint_final.speaker.safetensors` with its corresponding base model through Irodori-TTS `--ref-embed`.

### 6.5 Testing step checkpoints

Tab **4. Test** synthesizes speech with each saved `*.speaker.safetensors` so you can compare checkpoints by listening.

1. Select a speaker and refresh the saved models.
2. Select a Speaker Embedding and the matching V4/V4.1-Small base model used for training.
3. Enter any text and, optionally, a style caption.
4. Start test synthesis and wait for `completed` with exit code `0`.
5. Load the generated audio into the player and listen.

For a fair comparison, keep the text, caption, precision, number of steps, and seed unchanged; switch only the Speaker Embedding. The default seed is `1234`. Evaluate speaker similarity, pronunciation, accent, artifacts, consistency on longer sentences, and caption response. Test several different sentences rather than choosing from a single sample. The GUI deliberately does not assign an automatic quality score or ranking.

Generated WAV files are saved in a `tests` directory beside the selected training checkpoint. Test inference also uses the GPU, so avoid running it at the same time as training or another Irodori-TTS inference process.

## 7. Environment variables

Select the Irodori-TTS checkout manually:

```bat
set "IRODORI_TTS_ROOT=D:\AI\Irodori-TTS"
start_speaker_training_gui.bat
```

Change the Whisper server URL:

```bat
set "MIRAI_WHISPER_URL=http://192.168.1.10:8000"
start_speaker_training_gui.bat
```

Use a Whisper API key:

```bat
set "MIRAI_WHISPER_API_KEY=your-api-key"
start_speaker_training_gui.bat
```

Select a base checkpoint:

```bat
set "IRODORI_CHECKPOINT=D:\models\Irodori-TTS-v4.1-Small\model.safetensors"
start_speaker_training_gui.bat
```

The API key is inherited through the environment and is not written to the command line or job logs.

## 8. Generated files

```text
speaker-training\Speaker name\
├─ audio\
├─ metadata.jsonl
├─ transcription_review.csv
├─ review_state.json
├─ approved_metadata.jsonl
├─ train_manifest.jsonl
├─ transcriptions\
├─ latents\
└─ .jobs\

speaker-embeddings\Speaker\Timestamp\
├─ checkpoint_*.speaker.safetensors
└─ tests\
```

`speaker-training`, `speaker-embeddings`, and `models-cache` are excluded from Git.

## 9. GPU memory

Manifest preparation and training load Irodori-TTS components and DACVAE onto the GPU. Stop the Irodori-TTS inference server and regular Gradio inference UI before training.

If Whisper uses the same GPU, finish transcription and stop the Whisper server before manifest preparation. Cached transcripts remain available after the server stops.

## 10. Troubleshooting

### `detected dubious ownership`

Add only the exact checkout reported by Git as a trusted directory:

```bat
git config --global --add safe.directory "T:/Irodori-TTS-Speaker-Training-GUI"
```

### `Irodori-TTS repository could not be found`

Place both repositories under one parent directory or set `IRODORI_TTS_ROOT`.

### `The official Irodori-TTS uv environment is not ready`

Run the appropriate `uv sync --extra ...` command in the official Irodori-TTS directory.

### `The Whisper server is not ready`

Start the Whisper server and verify that `MIRAI_WHISPER_URL/health` responds.

### Clicking a table cell does not play audio

Pull the latest version, stop the old GUI, and restart it. Press `Ctrl+F5` if the browser cached old JavaScript. Verify that the clip exists under `Speaker name\audio`.

### Port 7862 is already in use

Run `stop_speaker_training_gui.bat`. For safety, it refuses to terminate an unknown process that owns the port.

### The manifest is stale

Audio, transcript text, or approval state changed. Run **Create manifest** again.

### CUDA out of memory

Stop Irodori-TTS inference, Whisper, and other GPU applications. Lower Batch Size if necessary.

## 11. Updating

```powershell
git pull
```

Stop and restart the GUI after updating.

## 12. License

This repository is provided under the [MIT License](../LICENSE). Irodori-TTS, Whisper, model weights, and training material remain subject to their respective licenses and terms.
