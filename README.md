# Woosh - Sound Effect Generative Models

This repository provides inference code and open weights for the sound effect generative models developed at Sony AI. The
current public release includes four models addressing the text-to-audio (T2A) and video-to-
audio (V2A) tasks:

- **Audio encoder/decoder (Woosh-AE)**: High-quality latent encoder/decoder providing latents
for generative modeling and decoding audio from generated latents.

- **Text conditioning (Woosh-CLAP)**: Multimodal text-audio alignment model providing token la-
tents for diffusion model conditioning.

- **T2A Generation (Woosh-Flow and Woosh-DFlow)**: Original and distilled LDMs generating au-
dio unconditionally or from given a text prompt.

- **V2A Generation (Woosh-VFlow)**: Multimodal LDM generating audio from a video sequence
with optional text prompts.

## Woosh Studio for Windows

Woosh Studio is the local Tauri desktop workstation in this repository. It provides project-based text-to-sound generation, HeartMuLa music generation, Qwen3-TTS script dubbing with fixed character voices, Demucs four-stem separation, model management, CPU/CUDA selection, non-destructive effects, a lightweight multitrack timeline, and Wwise/FMOD export packages.

The Script to Speech workspace uses local Qwen3-TTS checkpoints. CustomVoice provides fixed built-in speakers with language and instruction controls; Base provides reference-audio voice cloning. Add project characters, bind each character to a voice profile, enter lines, and select the output languages, and submit the script to generate one WAV asset per enabled line and language. The speech models are Apache 2.0 and can be installed from the model library or included in the offline runtime/model distribution.

The script workspace accepts AI-generated script and voice JSON through paste, file import, or folder drag and drop. Import previews validate role bindings and offer append/replace modes with undo. Reference audio is copied into the project and can be selected, previewed, located in Explorer, or copied as an absolute path. Script edits autosave; single-line and batch generation require a successful save and complete voice/model settings.

Speech results include inline playback and prior takes. Role-language changes keep the source dialogue and prepare a local translation: existing Chinese-to-English models are reused; other language pairs use the M2M100 INT8 model bundled in every desktop installer. Translation weights are prepared automatically at first launch without a network connection or a separate download. The bundled archive stays available for local repair and model-directory changes. Asset health checks mark missing files throughout the editing views, with relink and remove-from-project actions. The script workspace also includes a Freesound reference browser: configure your own Freesound API key in Settings, search and audition official previews, then import a selected preview while retaining attribution, license, sound ID, and source URL. Without a key, the app links to Freesound for manual browsing. Task cards expose failure stages and diagnostics, retained across application restarts. Music and speech workers use an explicit UTF-8 protocol on Windows so non-ASCII text and project paths round-trip correctly.

Open **AI 工作流** in the top toolbar or **模板中心** in the script workspace to copy script/role prompts, inspect JSON examples, and export the portable `woosh-studio` Skill ZIP. The package covers sound effects, music, speech, editing, models, settings, and export, with a standard-library Python API helper. Its source lives in `woosh_studio/agent_workflow/woosh-studio`; it ships with the Python application resources and does not contain model weights or credentials. Script/voice templates use `type: woosh.script` / `woosh.voices`, `version: 1`; sound-effect and music plans are used in their generation pages or through the local API.

### Recording, reusable models and game localization

In a cloned character's reference panel, **麦克风录制** captures up to 120 seconds. Stop, audition and save the recording as a project WAV. **识别台词** uses the optional local **Whisper-large-v3-turbo** model to fill the reference transcript; the text remains editable. Install it in the model library, or copy the Hugging Face model files into `<model root>/Whisper-large-v3-turbo` for offline use. No additional Python dependency is needed beyond the bundled Transformers/Torch runtime. Transcription is local and supports reference files up to 300 seconds. Permission denial and leaving the workspace release recording resources.

Project manifests now use schema 3, with backups and migration from schemas 1/2. Choose output languages in the script workspace; use **准备多语言文本** for translation only or generate all selected text/audio in one submission. Each locale has editable display/reading text, review/lock state and its own current audio. Character voices can be shared or overridden per locale. Input fingerprints reuse valid audio and only invalidate affected language results. Completed items are saved incrementally; the task history can retry incomplete items, and an on-disk commit journal reconciles interrupted file registration. The multilingual JSON template is available in the template center; older version 1 templates remain supported.

Speech, ASR, music and separation share a persistent worker manager with one heavy-model lease. Woosh reuses its existing in-process model through the same lease. The model page shows residency, actual load counts and cache hits, with preload/release actions; Settings controls idle expiry (600 seconds by default), retaining until exit or releasing after a batch. Model/device/precision changes invalidate caches. Music variants are produced before batched stem separation. INT8 music retains the offload-owned model objects between calls while releasing GPU working memory. Speech/music/ASR worker cancellation terminates the owned process; Woosh cancellation occurs between variants.

In Export, select **游戏多语言包** for `dialogue.csv`, per-locale JSON and current audio, all linked by stable line IDs. Text-only delivery is supported; complete audio delivery rejects missing, outdated or unreviewed (when requested) entries. Engine-specific Unity/Unreal/Wwise dialogue adapters and word-level lip sync are separate future extensions; this package is engine-neutral.

Implementation and verification notes: `docs/design/model-runtime-and-game-localization.md`. Run the isolated browser microphone/localization tests with `npx playwright test --config playwright.localization.config.ts` from `frontend`; they use Edge (or PLAYWRIGHT_CHANNEL), a fake microphone and synthetic model workers, not production checkpoints.

The standard installer contains the application, a bundled `uv.exe`, and (for release builds) a verified offline Python 3.12/CUDA runtime cache. The launcher uses `uv --offline` when that runtime is present, so generation and model inference do not contact package or model servers after installation.

Set a shared model repository before running or packaging the application. The desktop launcher also reads this value directly from `HKCU\Environment`, so several local AI applications can reuse the same files:

```powershell
[Environment]::SetEnvironmentVariable(
  "WOOSH_MODEL_HOME",
  "E:\AIModels\WooshStudio",
  "User"
)
```

The model repository should be on a non-system drive with at least 30 GB free for HeartMuLa. Model downloads, `.part` files, Hugging Face caches, ModelScope caches, and Torch model caches are rooted there.

Three Windows distributions can be produced:

```powershell
# Core MSI plus a selectable offline-model MSI distribution
./scripts/build-installers.ps1

# Prepare the bundled Python/CUDA runtime used by offline release builds
./scripts/build-offline-runtime.ps1

# Independent selectable HeartMuLa/HeartCodec and Demucs model MSI/ZIP
./scripts/build-heartmula-model-msi.ps1
```

The results are written to `.artifacts/installers/`:

- `Woosh-Studio-0.2.0-no-models-x64.msi` omits optional audio-generation weights; it includes the mandatory multilingual translation weights.
- `Woosh-Studio-0.2.0-with-models-x64.zip` contains a selectable Woosh DFlow/Flow model installer.
- `Woosh-Studio-0.2.0-HeartMuLa-models-x64.zip` contains an independent MSI with optional HeartMuLa/HeartCodec and Demucs features. Its external payload is copied directly into `WOOSH_MODEL_HOME`; uninstalling an application does not remove shared weights.

The Tauri `beforeBuildCommand` runs `scripts/prepare-bundled-translation.ps1`: it fetches the pinned M2M100 source on the build machine, verifies its official weight hash, converts once to CPU INT8, smoke-tests the converted model, and caches `.artifacts/model-archives/M2M100-418M-int8.zip`. Subsequent builds verify and reuse that archive; packaging fails if it cannot be prepared. The archive is embedded inside the core MSI and includes model-card/license notices and SHA-256 checksums. Users never run this build script. At runtime, the app validates and atomically unpacks the archive into the configured shared model directory before accepting requests, preserves existing files if preparation fails, and keeps the installer copy for offline repair.

The offline build script validates official release file sizes, SHA-256 hashes, ZIP CRCs, archive paths, and checkpoint structure before packaging. The large model ZIPs remain external to the MSI database so the package does not exceed MSI/CAB size limits. Both variants use the same application identity, so install only the preferred variant. Portable sound projects remain independent of the application installation.

## Installation

Start by installing [uv](https://docs.astral.sh/uv) first

```bash
 pip install uv
```

and then the Woosh environment, with either:

`cpu` support,

```bash
uv sync --no-default-groups --group studio --group music --group speech --extra cpu
```

or `cuda` support,

```bash
uv sync --no-default-groups --group studio --group music --group speech --extra cuda
```

### Download model weights

Open model weights are available for all Woosh models trained on public datasets. You can download
and unzip the pretrained weights from the [releases](https://github.com/SonyResearch/woosh-sfx/releases)
page, or otherwise using the [github CLI](https://cli.github.com) as

```bash
gh release download v1.0.0
unzip '*.zip'
```

The checkpoints should be located in folders named `checkpoints/MODEL_NAME`, each containing config and weight files.

### Download media samples

We provide audio samples to be used as inputs to our `test_Woosh-*.py` test scripts. You can download
and unzip the file `samples.zip` from the [releases](https://github.com/SonyResearch/woosh-sfx/releases)
page, or otherwise using the [github CLI](https://cli.github.com) as

```bash
gh release download v1.0.0 -p 'samples.zip'
unzip samples.zip
```

## Usage

### Test scripts
An inference test script for every model is provided. Just run any of the following

```python
uv run test_Woosh-AE.py
uv run test_Woosh-Flow.py
uv run test_Woosh-DFlow.py
uv run test_Woosh-VFlow.py
uv run test_Woosh-DVFlow.py
uv run test_Woosh-CLAP.py
```

and the generated audio/video will be written to `outputs/` as `.wav`/`.mp4` audio/video files.

Check our [tech report](https://arxiv.org/abs/2604.01929) on arxiv.org for a description of all models.

### Gradio demos
Two basic Gradio demos, for `Woosh-Flow` and `Woosh-DFlow` models, are available. To launch a Gradio demo locally, run one of the following

```python
uv run gradio_Woosh-Flow.py
uv run gradio_Woosh-DFlow.py
```

Open a web browser on the same machine and access the demo at `https://127.0.0.1:7860`.

### API server
Woosh models can be served via our API server. Check the [API](api/) folder for usage details.

## Citation
For details about model architecture, training and evaluation, please check our tech report
available on [arxiv.org](https://arxiv.org/abs/2604.01929).

```bibtex
@misc{hadjeres2026,
      title={Woosh: A Sound Effects Foundation Model},
      author={Gaetan Hadjeres, Marc Ferras, Khaled Koutini, Benno Weck, Alexandre Bittar, Thomas Hummel, Zineb Lahrichi, Hakim Missoum, Joan Serrà and Yuki Mitsufuji},
      year={2026},
      eprint={2604.01929},
      archivePrefix={arXiv},
      primaryClass={cs.SD},
      url={https://arxiv.org/abs/2604.01929},
}
```


## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License
- The majority of the code in this repository is released under the [MIT](https://choosealicense.com/licenses/mit/) license. The video-to-audio `Woosh-VFlow` and `Woosh-DVFlow` models use adapted code from [MM-AUDIO](https://github.com/hkchengrex/MMAudio) and [MotionFormer](https://github.com/facebookresearch/Motionformer/). The code for these models is made available under [Apache v2](https://www.apache.org/licenses/LICENSE-2.0) license terms.
- The open weights in the [releases](https://github.com/SonyResearch/woosh-sfx/releases) page are released under the [CC-BY-NC](https://creativecommons.org/licenses/by-nc/4.0/) license.
- The test audio and video samples in the [releases](https://github.com/SonyResearch/woosh-sfx/releases) page contain their individual license terms in the corresponding download file.


### 0.2.1 Whisper offline distribution

The verified 0.2.1 package includes the updated MSI (with bundled multilingual translation), Whisper-large-v3-turbo weights and the offline Python/CUDA runtime. Extract the ZIP and run `Install.cmd` as administrator. The installer verifies SHA-256 checksums, reuses valid installed payloads, installs missing runtime/model files into the shared model directory, and upgrades the existing application. Audio-generation models continue to use the shared model library.

Build this distribution with `scripts/build-whisper-offline-package.py --msi <new MSI> --model <Whisper directory> --runtime <offline runtime ZIP> --output .artifacts/installers --version 0.2.1`. Its installation entry point is `scripts/install-whisper-offline.ps1`. Real-model and installed-app verification notes are in `docs/design/model-runtime-and-game-localization.md`.
