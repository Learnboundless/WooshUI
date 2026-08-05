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

Woosh Studio is the local Tauri desktop workstation in this repository. It provides project-based text-to-sound generation, HeartMuLa music generation, Demucs four-stem separation, model management, CPU/CUDA selection, non-destructive effects, a lightweight multitrack timeline, and Wwise/FMOD export packages.

The standard installer contains the application and a bundled `uv.exe`. On first launch, `uv` creates one controlled Python 3.12 CUDA environment for Woosh, HeartMuLa, and Demucs. The startup screen reports dependency resolution, downloads, installation, and startup progress.

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

# Independent selectable HeartMuLa/HeartCodec and Demucs model MSI/ZIP
./scripts/build-heartmula-model-msi.ps1
```

The results are written to `.artifacts/installers/`:

- `Woosh-Studio-0.2.0-no-models-x64.msi` contains no model weights.
- `Woosh-Studio-0.2.0-with-models-x64.zip` contains a selectable Woosh DFlow/Flow model installer.
- `Woosh-Studio-0.2.0-HeartMuLa-models-x64.zip` contains an independent MSI with optional HeartMuLa/HeartCodec and Demucs features. Its external payload is copied directly into `WOOSH_MODEL_HOME`; uninstalling an application does not remove shared weights.

The offline build script validates official release file sizes, SHA-256 hashes, ZIP CRCs, archive paths, and checkpoint structure before packaging. The large model ZIPs remain external to the MSI database so the package does not exceed MSI/CAB size limits. Both variants use the same application identity, so install only the preferred variant. Portable sound projects remain independent of the application installation.

## Installation

Start by installing [uv](https://docs.astral.sh/uv) first

```bash
 pip install uv
```

and then the Woosh environment, with either:

`cpu` support,

```bash
uv sync --no-default-groups --group studio --group music --extra cpu
```

or `cuda` support,

```bash
uv sync --no-default-groups --group studio --group music --extra cuda
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
