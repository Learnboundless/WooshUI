# 剧本与角色导入格式 v1

工作台接受一个 JSON 对象，也接受完整的 ```json 代码块（.json/.txt/.md）。导入会先预览；单次最多 100 个角色、2000 句台词、2 MB。

剧本顶层：`type: "woosh.script"`、`version: 1`、`title`、`voices`、`lines`。
角色顶层：`type: "woosh.voices"`、`version: 1`、`voices`。不能包含台词。
原始 `{title, voices, lines}` 兼容现有项目脚本格式。

## 角色 voices[]

| 字段 | 规则 |
| --- | --- |
| id | 唯一非空字符串。已有角色应保留 ID |
| name | 唯一非空角色名 |
| mode | custom_voice 或 clone |
| language | Chinese / English / Japanese / Korean / German / French / Russian / Portuguese / Spanish / Italian / Auto |
| speaker | 内置音色：Vivian / Serena / Uncle_Fu / Dylan / Eric / Ryan / Aiden / Ono_Anna / Sohee |
| instruct | CustomVoice 的默认语气和表演指导；clone 仅作为创作备注，实际语气来自参考录音。文本描述本身不能创造新的说话人音色 |
| reference_audio | clone 的真实音频路径；没有文件时为 null |
| reference_text | 参考音频实际说出的文本；不要放角色介绍或拟生成的台词 |

参考文件夹示例：`scene/script.json` 和 `scene/voices/luo.wav`。JSON 使用 `voices/luo.wav`，把 scene 文件夹整体拖入。应用保留目录结构、复制文件并匹配路径。文件同名且无法唯一匹配时，在角色面板手动选择正确音频，不猜测。

## 台词 lines[]

| 字段 | 规则 |
| --- | --- |
| id | 唯一非空字符串 |
| character | 角色名称 |
| voice_id | 本次 voices 中的角色 ID；缺省时尝试按 character 精确匹配 |
| text | 非空、实际要说的台词 |
| language | 目标配音语言，使用上述语言枚举，默认 Chinese |
| source_language | 原文语言，默认 Auto。汉字/假名/韩文/西里尔字符可按脚本识别；其他拉丁字母语言默认 English，应显式选择 |
| translation | 可选，由本地翻译产生的 source_text、source_language、target_language、text、model_id；一般 AI 导入模板不需要填写 |
| instruct | 本句情绪、停顿与表演指导 |
| enabled | true 或 false，默认 true |

不要提供 `asset_id`，导入时会清除跨项目的生成结果关联。未知字段会被拒绝。用 `/scripts/preview` 获得与界面一致的完整校验，不用仅靠 JSON 能解析来判断兼容。

## 导入行为

- **追加剧本**：追加角色和台词；重复的角色 ID、名称与台词 ID 会重新分配以保留原内容。
- **替换剧本**：替换标题、角色和台词，已有音频素材保留。界面提供一次撤销。
- **角色模板**：同 ID 或同名角色更新配置；其余角色保留，绑定台词继续存在，旧配音标记清除以提示重新生成。
- 缺少音色绑定或克隆资源可以先导入，但生成前必须补齐。无效 JSON、重复 ID、未知字段或引用不存在的角色 ID 会显示具体错误。

完整可用示例见 `assets/script.example.json` 和 `assets/voices.example.json`。`assets/templates.json` 同时供应用界面读取，避免提示词与导入格式分叉。


## 多语言格式 v2

v1 继续兼容。多语言模板使用 `type: "woosh.script", version: 2`，新增：

- 剧本：`source_locale`、`target_locales`、`glossary`。locale 支持 zh-CN、en、ja、ko、de、fr、ru、pt、es、it。
- 台词：稳定的 id、可选 key/scene_id/context，以及按 locale 索引的 localizations。
- 语言版本：text 为显示文本，spoken_text 可覆盖读法；source_text/source_language 标识原文，locked 防止自动覆盖，review_status 为 draft/approved/stale。source_language 使用 Chinese/English/Japanese 等引擎语言名。
- 角色：locale_overrides[locale] 可指定完整的 mode/speaker/instruct/reference_audio/reference_text，未覆盖时继承默认音色。
- 不导入生成结果的 asset_id/input_fingerprint；各语言引用都会清除。保留用户提供的稳定台词 ID。
- 原文变化时，锁定译文仍保留但需要重新核对；各语言音频独立生成和更新。

可导入示例：assets/script.multilingual.example.json。
