from __future__ import annotations
import math
import re


def speech_segments(text: str, language: str) -> list[str]:
    text = text.strip()
    if not text:
        raise ValueError("配音文本不能为空")
    limit = 90 if language in {"Chinese", "Japanese", "Korean"} else 170
    sentences = re.split(r"(?<=[。！？!?；;])\s*|(?<=[.])\s+|\n+", text)
    output = []
    for sentence in sentences:
        sentence = sentence.strip()
        while len(sentence) > limit:
            candidates = [
                sentence.rfind(mark, 0, limit) for mark in ("，", ",", " ", "、")
            ]
            split = max(candidates)
            if split < limit // 3:
                split = limit
            else:
                split += 1
            output.append(sentence[:split].strip())
            sentence = sentence[split:].strip()
        if sentence:
            output.append(sentence)
    if len(output) > 40:
        raise ValueError("单句台词过长，请拆成多句后配音")
    return output


def token_budget(text: str, language: str) -> int:
    if language in {"Chinese", "Japanese", "Korean"}:
        expected_seconds = max(1.5, len(re.sub(r"\s|[，。！？、,.!?]", "", text)) / 3.5)
    else:
        expected_seconds = max(1.5, len(text.split()) / 2.3)
    return min(512, max(80, math.ceil(expected_seconds * 12.5 * 1.9) + 30))
