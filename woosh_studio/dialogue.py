from __future__ import annotations

import re
from threading import Lock

from .models import MULTILINGUAL_MODEL_ID, TRANSLATION_MODEL_ID

LANGUAGE_CODES = {
    "Chinese": "zh",
    "English": "en",
    "Japanese": "ja",
    "Korean": "ko",
    "German": "de",
    "French": "fr",
    "Russian": "ru",
    "Portuguese": "pt",
    "Spanish": "es",
    "Italian": "it",
}


def detect_language(text: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text):
        return "Japanese"
    if re.search(r"[\uac00-\ud7af]", text):
        return "Korean"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "Chinese"
    if re.search(r"[\u0400-\u04ff]", text):
        return "Russian"
    # Latin-script languages are ambiguous; the editor offers an explicit source selector.
    return "English"


class DialogueTranslator:
    def __init__(self, models, chinese_to_english):
        self.models = models
        self.chinese_to_english = chinese_to_english
        self._lock = Lock()
        self._loaded_path = None
        self._translator = None
        self._tokenizer = None

    def unload(self):
        with self._lock:
            self._loaded_path = self._translator = self._tokenizer = None

    def translate(
        self, text: str, source_language: str = "Auto", target_language: str = "English"
    ) -> dict:
        text = text.strip()
        if not text:
            raise ValueError("需要翻译的文本不能为空")
        source = detect_language(text) if source_language == "Auto" else source_language
        target = source if target_language == "Auto" else target_language
        if source not in LANGUAGE_CODES or target not in LANGUAGE_CODES:
            raise ValueError("不支持的翻译语言")
        if source == target:
            translated, model_id = text, "identity"
        elif (
            source == "Chinese"
            and target == "English"
            and self.models._translation_valid(self.models.translation_path())
        ):
            translated = self.chinese_to_english.translate(text)
            model_id = TRANSLATION_MODEL_ID
        else:
            path = self.models.model_path(MULTILINGUAL_MODEL_ID)
            if not self.models._multilingual_valid(path):
                path = self.models.ensure_bundled_translation()
            if not self.models._multilingual_valid(path):
                raise RuntimeError(
                    f"内置多语种翻译资源缺失（{MULTILINGUAL_MODEL_ID}）。请使用包含翻译组件的完整安装包修复应用，无需单独下载模型。"
                )
            with self._lock:
                from .model_runtime import model_revision
                key = (path, model_revision(path))
                if self._loaded_path != key:
                    import ctranslate2
                    from transformers import M2M100Tokenizer

                    self._tokenizer = M2M100Tokenizer.from_pretrained(
                        str(path / "tokenizer"), local_files_only=True
                    )
                    self._translator = ctranslate2.Translator(
                        str(path), device="cpu", compute_type="int8"
                    )
                    self._loaded_path = key
                tokenizer = self._tokenizer
                tokenizer.src_lang = LANGUAGE_CODES[source]
                ids = tokenizer.encode(text)
                if len(ids) > 900:
                    raise ValueError("单句太长，请拆分为较短的对白后再翻译")
                prefix = tokenizer.convert_ids_to_tokens(
                    tokenizer.get_lang_id(LANGUAGE_CODES[target])
                )
                result = self._translator.translate_batch(
                    [tokenizer.convert_ids_to_tokens(ids)],
                    target_prefix=[[prefix]],
                    beam_size=4,
                    max_decoding_length=1024,
                )[0]
                output_ids = tokenizer.convert_tokens_to_ids(result.hypotheses[0])
                translated = tokenizer.decode(
                    output_ids, skip_special_tokens=True
                ).strip()
                model_id = MULTILINGUAL_MODEL_ID
        if not translated.strip():
            raise RuntimeError("本地翻译模型返回空文本")
        return {
            "source_text": text,
            "source_language": source,
            "target_language": target,
            "text": translated,
            "model_id": model_id,
        }
