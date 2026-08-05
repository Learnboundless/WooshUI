from woosh_studio.jobs import error_code_for_message
from woosh_studio.schemas import ErrorCode


def test_runtime_errors_use_stable_api_codes() -> None:
    assert error_code_for_message("CUDA out of memory") == ErrorCode.GPU_OOM
    assert (
        error_code_for_message("模型尚未安装: HeartMuLa-3B")
        == ErrorCode.MODEL_NOT_INSTALLED
    )
    assert (
        error_code_for_message("HeartMuLa 安装至少需要 30 GB 可用空间")
        == ErrorCode.DISK_SPACE_LOW
    )
    assert (
        error_code_for_message("下载官方权重前必须确认许可")
        == ErrorCode.LICENSE_NOT_ACCEPTED
    )
