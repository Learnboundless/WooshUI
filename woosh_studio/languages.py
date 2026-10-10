"""Project locales are independent of the application's display language."""
LOCALES = {
    "zh-CN": ("Chinese", "中文"), "en": ("English", "英语"),
    "ja": ("Japanese", "日语"), "ko": ("Korean", "韩语"),
    "de": ("German", "德语"), "fr": ("French", "法语"),
    "ru": ("Russian", "俄语"), "pt": ("Portuguese", "葡萄牙语"),
    "es": ("Spanish", "西班牙语"), "it": ("Italian", "意大利语"),
}


def locale_for(language: str) -> str:
    if language in LOCALES:
        return language
    for locale, (engine, _) in LOCALES.items():
        if engine == language:
            return locale
    raise ValueError(f"不支持的语言: {language}")


def validate_locales(values):
    result = []
    for value in values:
        if value not in LOCALES:
            raise ValueError(f"不支持的输出语言: {value}")
        if value not in result:
            result.append(value)
    return result
