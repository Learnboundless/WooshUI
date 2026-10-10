from woosh_studio.speech_options import speech_segments, token_budget


def test_sentence_splitting_keeps_content_and_caps_model_work():
    text = "The world began to get strange, the world was hopeless and God had given us up. We needed to save ourselves and reclaim our homeland."
    segments = speech_segments(text, "English")
    assert len(segments) == 2
    assert " ".join(segments) == text
    assert all(80 <= token_budget(segment, "English") < 300 for segment in segments)


def test_cjk_and_long_unpunctuated_dialogue_are_bounded():
    assert speech_segments("你好。我们走吧！", "Chinese") == ["你好。", "我们走吧！"]
    pieces = speech_segments("天地玄黄" * 100, "Chinese")
    assert "".join(pieces) == "天地玄黄" * 100
    assert max(map(len, pieces)) <= 90
