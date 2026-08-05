from __future__ import annotations

import json
from pathlib import Path
from types import MethodType
from typing import Any


MAX_GENERATION_CACHE_FRAMES = 4096
CODEC_CODEBOOK_BLOCK_PREFIX = "flow_matching.vq_embed.layers."


def _strip_rope_cache(state_dict: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "backbone.layers.0.attn.pos_embeddings.theta",
        "backbone.layers.0.attn.pos_embeddings.cache",
        "decoder.layers.0.attn.pos_embeddings.theta",
        "decoder.layers.0.attn.pos_embeddings.cache",
    ):
        state_dict.pop(key, None)
    return state_dict


def _first_weight(directory: Path) -> Path:
    shards = sorted(directory.glob("model-*.safetensors"))
    if shards:
        return shards[0]
    weight = directory / "model.safetensors"
    if weight.is_file():
        return weight
    raise FileNotFoundError(f"找不到模型权重: {directory}")


def _load_codec(codec_root: Path):
    import torch
    from accelerate import init_empty_weights
    from heartlib.heartcodec.configuration_heartcodec import HeartCodecConfig
    from heartlib.heartcodec.modeling_heartcodec import HeartCodec
    from mmgp import offload

    codec_config = HeartCodecConfig(
        **json.loads((codec_root / "config.json").read_text(encoding="utf-8"))
    )
    with init_empty_weights():
        codec = HeartCodec(codec_config)
    codec._offload_hooks = ["detokenize"]
    codec._model_dtype = torch.float32
    offload.load_model_data(
        codec,
        str(_first_weight(codec_root)),
        default_dtype=torch.float32,
        writable_tensors=False,
    )
    codec.eval()
    return codec


def _preload_codec_codebooks(
    manager: Any,
    *,
    model_id: str = "codec",
    expected_count: int,
) -> tuple[str, ...]:
    full_prefix = f"{model_id}/{CODEC_CODEBOOK_BLOCK_PREFIX}"
    blocks = tuple(
        full_name.split("/", 1)[1]
        for full_name in manager.blocks_of_modules
        if full_name.startswith(full_prefix)
    )
    if len(blocks) != expected_count:
        raise RuntimeError(
            "HeartCodec codebook 分块识别失败: "
            f"预期 {expected_count} 个，实际 {len(blocks)} 个"
        )

    preloaded = manager.preloaded_blocks_per_model[model_id]
    for block_name in blocks:
        full_name = f"{model_id}/{block_name}"
        preloaded.setdefault(block_name, manager.blocks_of_modules_sizes[full_name])
    return blocks


def _configure_int8_muq_output(model) -> None:
    def keep_float32(_module, _inputs, output):
        return output.float()

    model.muq_linear.register_forward_hook(keep_float32)


def _configure_cuda_caches(model, device, dtype) -> None:
    import torch

    def setup_caches(self, max_batch_size: int) -> None:
        try:
            self.reset_caches()
        except RuntimeError:
            pass
        with device:
            if not self.backbone.caches_are_setup():
                self.backbone.setup_caches(
                    max_batch_size,
                    dtype,
                    decoder_max_seq_len=MAX_GENERATION_CACHE_FRAMES,
                )
            if not self.decoder.caches_are_setup():
                self.decoder.setup_caches(
                    max_batch_size,
                    dtype,
                    decoder_max_seq_len=self.config.audio_num_codebooks,
                )
            if (
                getattr(self, "backbone_causal_mask", None) is None
                or self.backbone_causal_mask.device != device
            ):
                self.register_buffer(
                    "backbone_causal_mask",
                    torch.tril(
                        torch.ones(
                            MAX_GENERATION_CACHE_FRAMES,
                            MAX_GENERATION_CACHE_FRAMES,
                            dtype=torch.bool,
                            device=device,
                        )
                    ),
                )
            if (
                getattr(self, "decoder_causal_mask", None) is None
                or self.decoder_causal_mask.device != device
            ):
                self.register_buffer(
                    "decoder_causal_mask",
                    torch.tril(
                        torch.ones(
                            self.config.audio_num_codebooks,
                            self.config.audio_num_codebooks,
                            dtype=torch.bool,
                            device=device,
                        )
                    ),
                )

    model.setup_caches = MethodType(setup_caches, model)


def _configure_staged_unload(pipeline, manager) -> None:
    import gc

    import torch
    from torchtune.modules import delete_kv_caches

    forward_complete = False

    def unload(self) -> None:
        nonlocal forward_complete
        if not forward_complete:
            if self._mula is not None:
                if self._mula.backbone.caches_are_setup():
                    delete_kv_caches(self._mula.backbone)
                if self._mula.decoder.caches_are_setup():
                    delete_kv_caches(self._mula.decoder)
                self._mula.backbone_causal_mask = None
                self._mula.decoder_causal_mask = None
            manager.unload_all()
            self._mula = None
            forward_complete = True
        else:
            manager.unload_all()
            self._codec = None
        gc.collect()
        torch.cuda.empty_cache()

    pipeline._unload = MethodType(unload, pipeline)


def create_pipeline(model_root: Path, device, *, use_int8: bool):
    import torch
    from accelerate import init_empty_weights
    from heartlib.heartmula.configuration_heartmula import HeartMuLaConfig
    from heartlib.heartmula.modeling_heartmula import HeartMuLa
    from heartlib.pipelines.music_generation import HeartMuLaGenPipeline
    from mmgp import offload

    model_root = model_root.resolve()
    mula_root = model_root / "HeartMuLa-oss-3B-happy-new-year"
    codec_root = model_root / "HeartCodec-oss"
    pipeline = HeartMuLaGenPipeline.from_pretrained(
        pretrained_path=str(model_root),
        device={"mula": device, "codec": device},
        dtype={"mula": torch.bfloat16, "codec": torch.float32},
        version="3B-happy-new-year",
        lazy_load=True,
    )

    mula_config = HeartMuLaConfig(
        **json.loads((mula_root / "config.json").read_text(encoding="utf-8"))
    )
    with init_empty_weights():
        mula = HeartMuLa(mula_config)
    offload.load_model_data(
        mula,
        str(_first_weight(mula_root)),
        default_dtype=torch.bfloat16,
        writable_tensors=False,
        preprocess_sd=_strip_rope_cache,
    )
    mula.eval()

    codec = _load_codec(codec_root)

    manager = offload.profile(
        {
            "transformer": mula,
            "codec": codec,
        },
        profile_no=5,
        budgets={
            "transformer": 2500,
            "codec": 2500,
            "*": 1500,
        },
        verboseLevel=0,
        quantizeTransformer=use_int8,
    )
    # ResidualVQ reads codebook buffers directly instead of calling a module
    # forward, so mmgp cannot discover and load these blocks through hooks.
    _preload_codec_codebooks(
        manager,
        expected_count=codec.config.num_quantizers,
    )
    if use_int8:
        # Quanto embeddings return float32, while autocast leaves the MuQ
        # projection in bfloat16. HeartLib assigns both into the same tensor.
        _configure_int8_muq_output(mula)
    _configure_cuda_caches(mula, device, torch.bfloat16)
    _configure_staged_unload(pipeline, manager)
    pipeline._mula = mula
    pipeline._codec = codec
    pipeline.mula_device = device
    pipeline.codec_device = device
    pipeline.mula_dtype = torch.bfloat16
    pipeline.codec_dtype = torch.float32
    return pipeline
