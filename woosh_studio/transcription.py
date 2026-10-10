from pathlib import Path

import soundfile as sf

from .languages import LOCALES
from .localization import file_digest
from .models import WHISPER_MODEL_ID
from .schemas import JobStatus


class TranscriptionService:
    def __init__(self, models, projects, system, runtime):
        self.models, self.projects, self.system, self.runtime = models, projects, system, runtime

    def validate(self, request):
        root = Path(request.project_path).expanduser().resolve()
        self.projects.open(root)
        path = Path(request.reference_audio).expanduser()
        path = path.resolve() if path.is_absolute() else self.projects.resolve_project_file(root, request.reference_audio)
        if not path.is_file():
            raise ValueError("参考音频不存在，请重新录制或选择文件")
        if request.language != "Auto" and request.language not in {value[0] for value in LOCALES.values()}:
            raise ValueError("不支持的识别语言")
        if path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError("参考音频不能超过 200 MB")
        info = sf.info(path)
        if info.frames <= 0 or info.duration > 300:
            raise ValueError("参考音频必须有声音，且不超过 5 分钟")
        if not self.models.is_installed(WHISPER_MODEL_ID):
            raise ValueError(f"模型尚未安装: {WHISPER_MODEL_ID}，请到模型页面安装语音转文字模型")
        return path

    def worker(self, request):
        def run(job_id, update, control):
            path = self.validate(request)
            source_hash = file_digest(path)
            update(status=JobStatus.QUEUED, stage="等待语音识别模型", progress=0)
            result = self.runtime.run("woosh_studio.asr_worker", {
                "command": "transcribe", "model_id": WHISPER_MODEL_ID,
                "model_path": str(self.models.model_path(WHISPER_MODEL_ID)), "source_path": str(path),
                "language": request.language, "device": self.system.capabilities().effective_device,
                "job_id": job_id,
            }, control, lambda event: update(status=JobStatus.RUNNING, stage=event.get("stage", "识别录音"), progress=event.get("progress", 0)))
            if source_hash != file_digest(path):
                raise ValueError("识别过程中参考音频发生变化，请重新识别")
            return {**result, "source_sha256": source_hash, "reference_audio": request.reference_audio,
                    "model_id": WHISPER_MODEL_ID, "project_path": request.project_path}
        return run
