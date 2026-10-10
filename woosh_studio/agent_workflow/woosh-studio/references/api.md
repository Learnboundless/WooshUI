# 本地 API 操作

服务提供 `/api/openapi.json` 和 `/api/docs`。开发服务常用 `http://127.0.0.1:8765`；桌面安装版使用动态端口和会话令牌。请从当前应用运行配置或由用户提供的连接信息取得地址，不能把默认端口当作桌面版的事实。没有连接信息时仍可生成 JSON 模板，并通过工作台导入。

`WOOSH_STUDIO_API_URL` 指向服务根 URL（不包含 `/api/v1`），`WOOSH_STUDIO_API_TOKEN` 通过 `X-Woosh-Token` 发送。助手只允许本地 loopback URL；不把本地令牌发送给远程主机。不得把令牌写进模板或交付包。

助手只依赖 Python 3 标准库：

```text
python scripts/woosh_agent.py status
python scripts/woosh_agent.py preview script.json
python scripts/woosh_agent.py request GET /models
python scripts/woosh_agent.py request POST /generations/speech --json speech-request.json
python scripts/woosh_agent.py wait JOB_ID --timeout 600
```

`--json` 从 UTF-8 文件读取请求，避免 shell 引号破坏 JSON。`wait` 只在 completed 返回 0；失败、取消、中断或超时返回非零并保留服务错误。不要因为提交请求成功就宣称音频已生成。

## 端点速查

下列路径相对于 `/api/v1`。严格字段、默认值和参数限制以当前运行版本 OpenAPI 为准。

| 操作 | 方法 / 路径 | 请求要点 |
| --- | --- | --- |
| 能力和设置 | GET /system/capabilities | 返回 settings、设备和 runtime |
| 修改设置 | PATCH /system/settings | 读取旧 settings 后合并需要变更的字段 |
| 模型 | GET /models | installed、path、license、controls、bundled；内置多语种翻译自动部署，无需调用下载接口 |
| 安装模型 | POST /models/{id}/download | 返回任务 ID；必要时先处理许可 |
| 许可 | POST /models/license | model_id、release、accepted；需用户同意 |
| 自定义模型 | POST /models/register | model_id、path |
| 移除模型 | DELETE /models/{id} | 仅在用户要求移除时 |
| 最近项目 | GET /projects/recent | 查找当前电脑的项目路径 |
| 移除最近记录 | DELETE /projects/recent | path；不删除项目文件 |
| 新建项目 | POST /projects | parent_directory、name、description |
| 打开项目 | POST /projects/open | path |
| 保存完整项目 | PUT /projects | project_path、manifest；先读最新内容 |
| 保存剧本 | PUT /projects/script | project_path、script（内部格式，不含 type/version） |
| 模板预览 | POST /scripts/preview | text：完整 JSON 字符串；返回 kind、script、warnings |
| 导入文件/文件夹 | POST /projects/resources/import | project_path、paths 字符串数组；返回 manifest、assets、documents、mappings、warnings |
| 浏览器上传 | POST /projects/resources/upload | multipart：project_path、多个 files |
| 解析文件路径 | POST /projects/resources/resolve | project_path、paths；返回 exists 和 absolute_path |
| 音效 | POST /generations | assets/templates.json 的 sfx 模板加 project_path |
| 音乐 | POST /generations/music | music 模板加 project_path |
| 配音 | POST /generations/speech | project_path、line_ids；空数组为所有启用台词 |
| 分轨 | POST /assets/{id}/separate | project_path |
| 裁剪 | POST /assets/{id}/trim | project_path、mode (manual/trim_silence)、start_seconds、end_seconds 等 |
| 翻译 | POST /translate | text、source_language（Auto/Chinese/English 等）、target_language；返回 translated 和 translation |
| Freesound 状态 | GET /freesound/status | 返回 configured；无 token 时使用网站 fallback |
| Freesound 搜索 | POST /freesound/search | query、page、page_size、filter；需要本机配置的 API key；仅返回官方 preview URL、作者、许可证和 sound URL |
| Freesound 导入 | POST /freesound/import | project_path、sound_id、preview_url、name、username、license、sound_url、duration；只接受 freesound.org 官方 HTTPS preview |
| 文件状态 | POST /projects/assets/health | path；返回每个素材/时间线源文件的 exists、reason |
| 移除素材记录 | DELETE /projects/assets | project_path、asset_ids；解除关联片段/配音，保留磁盘文件 |
| 重新关联素材 | POST /assets/{id}/relink | project_path、source_path；保留素材 ID，外部文件复制入项目 |
| 渲染预览 | POST /renders/preview | project_path、timeline、output_name |
| 异步渲染 | POST /renders | project_path、timeline、output_name |
| 导出 | POST /exports | project_path、asset_ids 或 timeline、preset |
| 队列 | GET /jobs 或 /jobs/{id} | 检查状态和 error |
| 取消/暂停/恢复 | POST /jobs/{id}/cancel、/pause、/resume | 以对应任务支持情况为准 |
| 模板 | GET /agent/templates | 共享提示词与输出示例 |
| Skill 包 | GET /agent/workflow.zip | ZIP 文件；无模型、无令牌 |

## 剧本自动制作顺序

1. `POST /projects/open` 获取项目及 existing script。
2. `POST /scripts/preview` 校验新的 JSON。处理 warnings，不跳过角色缺失。
3. 如果需要外部音频，`POST /projects/resources/import` 导入并用 mappings 返回的 relative_path 替换 reference_audio。
4. 合并角色和台词：保留现有 ID；新增 ID 不碰撞；角色更新不删除台词。用户要求替换时才整体替换 script。
5. `PUT /projects/script` 保存内部 script，不携带模板封装 type/version。
6. `POST /generations/speech` 指定一条台词进行试听；确认后批量生成。
7. 等待任务完成，重新读取项目；从 asset_id 找 relative_path 并验证文件实际存在。

## 导出请求示例

```json
{
  "project_path": "替换为真实项目根目录",
  "asset_ids": ["替换为已有素材ID"],
  "preset": {
    "format": "wav24",
    "package": "files",
    "naming_template": "{category}_{name}_{variant:02}",
    "category": "Voice"
  }
}
```

完整 timeline、效果参数和其他复杂 schema 查询当前 OpenAPI。不要自行构造未知字段。


## 录音、常驻模型与多语言

- POST /transcriptions：project_path、reference_audio（项目相对路径）、language（可省略，默认 Auto）。返回本地识别任务，完成结果含 text；必须核对原录音，不能把识别结果当作绝对准确。
- POST /generations/speech：可增加 target_locales、text_only、force、continue_on_error。默认复用仍有效的语言结果；force 生成新版本。text_only 只准备文本。
- GET /jobs/{id}/items：每句每语言的状态；POST /jobs/{id}/retry 恢复剧本任务，跳过已完成且仍有效的音频。
- GET /models/runtime 查看常驻状态；POST /models/runtime/release 释放空闲推理模型；POST /models/{model_id}/preload 预加载配音/识别/音乐/分轨模型。
- POST /exports/localization：project_path、target_locales、mode（text/complete）、require_approved、format（wav24/wav16/flac/ogg）。完整包检查当前文本与音频一致性，返回导出任务。

应用内麦克风录制由用户点击发起，保存为项目 WAV 后复用识别接口。参考录音最多 120 秒；已有文件转写最多 300 秒。识别使用安装到共享模型库的 Whisper-large-v3-turbo，推理只读本地权重。
