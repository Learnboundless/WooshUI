import numpy as np
import soundfile as sf
from woosh_studio.signal_analysis import analyze_audio, protect_peak


def test_analysis_uses_real_samples_and_stereo_phase_does_not_cancel(tmp_path):
    sr = 48000
    sine = 0.4 * np.sin(2 * np.pi * 1000 * np.arange(sr) / sr)
    file = tmp_path / "tone.wav"
    sf.write(file, np.column_stack((sine, -sine)), sr, subtype="FLOAT")
    data = analyze_audio(file)
    assert abs(data["dominant_frequency_hz"] - 1000) < 30
    assert data["channel_count"] == 2
    assert max(pair[1] for pair in data["peaks"]) > 0.39
    assert len(data["spectrogram"]) > 20 and len(data["spectrogram"][0]) > 20
    assert 0.39 < data["peak"] < 0.41


def test_peak_protection_preserves_shape_without_hard_clipping():
    source = np.array([[0.2, -0.1], [1.56, -1.2], [-0.6, 0.3]], dtype=np.float32)
    output, stats = protect_peak(source)
    assert np.max(np.abs(output)) <= 0.981
    assert np.allclose(output, source * stats["gain"])
    assert stats["gain"] < 1
    unchanged, _ = protect_peak(source * 0.1)
    assert np.allclose(unchanged, source * 0.1)
