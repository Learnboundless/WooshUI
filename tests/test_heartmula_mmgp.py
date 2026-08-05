import os
from pathlib import Path
from types import MethodType

import pytest

from woosh_studio.heartmula_mmgp import (
    _configure_int8_muq_output,
    _load_codec,
    _preload_codec_codebooks,
)


class FakeManager:
    def __init__(self) -> None:
        self.blocks_of_modules = {
            "codec": [],
            "codec/flow_matching.vq_embed.layers.0": [],
            "codec/flow_matching.vq_embed.layers.1": [],
            "codec/flow_matching.estimator.layers.0": [],
        }
        self.blocks_of_modules_sizes = {
            name: index + 1
            for index, name in enumerate(self.blocks_of_modules)
        }
        self.preloaded_blocks_per_model = {"codec": {"existing": 100}}


def test_codec_codebook_blocks_are_registered_for_preloading() -> None:
    manager = FakeManager()

    blocks = _preload_codec_codebooks(manager, expected_count=2)

    assert blocks == (
        "flow_matching.vq_embed.layers.0",
        "flow_matching.vq_embed.layers.1",
    )
    assert manager.preloaded_blocks_per_model["codec"] == {
        "existing": 100,
        "flow_matching.vq_embed.layers.0": 2,
        "flow_matching.vq_embed.layers.1": 3,
    }


def test_codec_codebook_preloading_fails_when_layout_changes() -> None:
    manager = FakeManager()

    with pytest.raises(RuntimeError, match="预期 8 个，实际 2 个"):
        _preload_codec_codebooks(manager, expected_count=8)


def test_int8_muq_output_matches_float32_quantized_embeddings() -> None:
    import torch

    class FakeMula(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.muq_linear = torch.nn.Identity()

    model = FakeMula()
    _configure_int8_muq_output(model)

    output = model.muq_linear(torch.zeros(2, 4, dtype=torch.bfloat16))

    assert output.dtype == torch.float32


@pytest.mark.skipif(
    "WOOSH_HEARTMULA_TEST_MODEL_ROOT" not in os.environ,
    reason="需要显式提供真实 HeartMuLa 模型目录",
)
def test_real_codec_codebook_lookup_after_mmgp_offload() -> None:
    import torch
    from mmgp import offload

    if not torch.cuda.is_available():
        pytest.skip("需要 CUDA")

    codec_root = (
        Path(os.environ["WOOSH_HEARTMULA_TEST_MODEL_ROOT"]) / "HeartCodec-oss"
    )
    codec = _load_codec(codec_root)

    def lookup_codes(self, codes):
        return self.flow_matching.vq_embed.get_output_from_indices(codes)

    codec.lookup_codes = MethodType(lookup_codes, codec)
    codec._offload_hooks = ["lookup_codes"]
    manager = offload.profile(
        {"codec": codec},
        profile_no=5,
        budgets={"codec": 2500, "*": 1500},
        verboseLevel=0,
        quantizeTransformer=False,
    )
    _preload_codec_codebooks(
        manager,
        expected_count=codec.config.num_quantizers,
    )
    manager.unload_all()

    try:
        indices = torch.zeros((1, 372, 8), dtype=torch.long, device="cuda")
        output = codec.lookup_codes(indices)
        assert output.shape == (1, 372, 512)
        assert output.device.type == "cuda"
    finally:
        manager.unload_all()
