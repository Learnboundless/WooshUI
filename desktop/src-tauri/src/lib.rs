use serde::Serialize;
use std::{
    collections::{HashMap, HashSet},
    fs::{self, OpenOptions},
    net::TcpListener,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Instant,
};
use tauri::{Manager, RunEvent, State};
use uuid::Uuid;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[derive(Clone, Serialize)]
struct BackendInfo {
    url: String,
    token: String,
}

struct BackendState {
    info: BackendInfo,
    child: Mutex<Option<Child>>,
    first_setup: bool,
    cache_path: PathBuf,
    log_path: PathBuf,
    runtime_marker: PathBuf,
    started_at: Instant,
}

#[derive(Serialize)]
struct BackendStatus {
    phase: String,
    message: String,
    detail: String,
    progress: f64,
    first_setup: bool,
    elapsed_seconds: u64,
}

struct SetupProgress {
    value: f64,
    detail: String,
}

#[tauri::command]
fn backend_info(state: State<'_, BackendState>) -> BackendInfo {
    state.info.clone()
}

#[tauri::command]
fn reveal_in_explorer(path: String) -> Result<(), String> {
    let target = PathBuf::from(path);
    if !target.exists() {
        return Err("项目目录不存在".into());
    }

    #[cfg(target_os = "windows")]
    {
        return Command::new("explorer.exe")
            .arg(target)
            .creation_flags(0x08000000)
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("无法打开资源管理器：{error}"));
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = target;
        Err("当前平台不支持资源管理器操作".into())
    }
}

fn backend_failure_detail(log: &str) -> String {
    let mut lines = log
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .rev()
        .take(4)
        .collect::<Vec<_>>();
    lines.reverse();
    if lines.is_empty() {
        "运行环境没有准备完成，请重新打开应用".into()
    } else {
        lines.join(" · ")
    }
}

#[tauri::command]
fn backend_status(state: State<'_, BackendState>) -> BackendStatus {
    let elapsed_seconds = state.started_at.elapsed().as_secs();
    let process_exit = state.child.lock().ok().and_then(|mut child| {
        child
            .as_mut()
            .and_then(|process| process.try_wait().ok())
            .flatten()
    });
    let log = fs::read_to_string(&state.log_path).unwrap_or_default();
    let setup = setup_progress(&log, directory_size(&state.cache_path));

    if let Some(status) = process_exit {
        return BackendStatus {
            phase: "failed".into(),
            message: format!("本地服务启动失败（退出码 {}），请查看运行日志", status),
            detail: backend_failure_detail(&log),
            progress: setup.value,
            first_setup: state.first_setup,
            elapsed_seconds,
        };
    }
    if log.contains("Uvicorn running on") {
        let _ = fs::write(&state.runtime_marker, env!("CARGO_PKG_VERSION"));
        return BackendStatus {
            phase: "ready".into(),
            message: "正在连接本地音频服务".into(),
            detail: "初始化完成".into(),
            progress: 1.0,
            first_setup: state.first_setup,
            elapsed_seconds,
        };
    }
    if let Some(offline) = offline_setup_progress(&log) {
        return BackendStatus {
            phase: "installing".into(),
            message: "正在安装离线模型".into(),
            detail: offline.detail,
            progress: offline.value,
            first_setup: state.first_setup,
            elapsed_seconds,
        };
    }
    if state.first_setup {
        return BackendStatus {
            phase: "installing".into(),
            message: "uv 正在准备 Python 3.12、CUDA 与音乐运行环境".into(),
            detail: setup.detail,
            progress: setup.value,
            first_setup: true,
            elapsed_seconds,
        };
    }
    BackendStatus {
        phase: "starting".into(),
        message: "正在启动本地音频服务".into(),
        detail: setup.detail,
        progress: setup.value.max(0.9),
        first_setup: false,
        elapsed_seconds,
    }
}

fn offline_setup_progress(log: &str) -> Option<SetupProgress> {
    if log.contains("WOOSH_OFFLINE_COMPLETE") {
        return None;
    }
    let line = log
        .lines()
        .rev()
        .find(|line| line.starts_with("WOOSH_OFFLINE_PROGRESS "))?;
    let mut fields = line.split_whitespace();
    fields.next()?;
    let completed = fields.next()?.parse::<u64>().ok()?;
    let total = fields.next()?.parse::<u64>().ok()?;
    let model = fields.next()?;
    Some(SetupProgress {
        value: 0.92 + 0.07 * completed as f64 / total.max(1) as f64,
        detail: format!("{model} · {completed}/{total}"),
    })
}

fn parse_download_size(text: &str) -> Option<u64> {
    let number_end =
        text.find(|character: char| !character.is_ascii_digit() && character != '.')?;
    let value = text[..number_end].parse::<f64>().ok()?;
    let multiplier = match &text[number_end..] {
        "KiB" => 1024_f64,
        "MiB" => 1024_f64.powi(2),
        "GiB" => 1024_f64.powi(3),
        _ => return None,
    };
    Some((value * multiplier) as u64)
}

fn directory_size(path: &std::path::Path) -> u64 {
    let Ok(entries) = fs::read_dir(path) else {
        return 0;
    };
    entries
        .filter_map(Result::ok)
        .map(|entry| {
            let Ok(metadata) = entry.metadata() else {
                return 0;
            };
            if metadata.is_dir() {
                directory_size(&entry.path())
            } else if metadata.is_file() {
                metadata.len()
            } else {
                0
            }
        })
        .sum()
}

fn setup_progress(log: &str, cache_bytes: u64) -> SetupProgress {
    if log.contains("Uvicorn running on") {
        return SetupProgress {
            value: 1.0,
            detail: "初始化完成".into(),
        };
    }
    if log
        .lines()
        .any(|line| line.trim_start().starts_with("Installed "))
    {
        return SetupProgress {
            value: 0.97,
            detail: "依赖安装完成，正在启动本地服务".into(),
        };
    }

    let mut sizes = HashMap::<String, u64>::new();
    let mut order = Vec::<String>::new();
    let mut completed = HashSet::<String>::new();
    for line in log.lines().map(str::trim) {
        if let Some(rest) = line.strip_prefix("Downloading ") {
            if let Some((name, size)) = rest
                .strip_suffix(')')
                .and_then(|value| value.rsplit_once(" ("))
            {
                if let Some(bytes) = parse_download_size(size) {
                    sizes.insert(name.to_string(), bytes);
                    if !order.iter().any(|item| item == name) {
                        order.push(name.to_string());
                    }
                }
            }
        }
        if let Some(name) = line.strip_prefix("Downloaded ") {
            completed.insert(name.to_string());
        }
    }

    let total_bytes: u64 = sizes.values().sum();
    if total_bytes > 0 {
        let completed_bytes: u64 = completed.iter().filter_map(|name| sizes.get(name)).sum();
        let estimated_bytes = completed_bytes.max(cache_bytes.min(total_bytes));
        let current = order
            .iter()
            .find(|name| !completed.contains(*name))
            .map(String::as_str)
            .unwrap_or("依赖");
        return SetupProgress {
            value: (0.08 + 0.84 * estimated_bytes as f64 / total_bytes as f64).min(0.92),
            detail: format!(
                "下载 {current} · {}/{} MiB · {}/{} 个包已完成",
                estimated_bytes / 1024_u64.pow(2),
                total_bytes / 1024_u64.pow(2),
                completed.len(),
                order.len()
            ),
        };
    }
    if log.contains("Creating virtual environment") {
        return SetupProgress {
            value: 0.06,
            detail: "正在创建隔离的 Python 3.12 环境".into(),
        };
    }
    SetupProgress {
        value: 0.02,
        detail: "正在解析运行依赖".into(),
    }
}

fn free_port() -> Result<u16, String> {
    TcpListener::bind("127.0.0.1:0")
        .map_err(|error| error.to_string())?
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| error.to_string())
}

fn source_directory(app: &tauri::App) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        return PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .map_err(|error| error.to_string());
    }
    app.path()
        .resource_dir()
        .map(|path| path.join("python"))
        .map_err(|error| error.to_string())
}

fn data_directory(app: &tauri::App) -> Result<PathBuf, String> {
    if let Ok(configured) = std::env::var("WOOSH_STUDIO_DATA_ROOT") {
        return Ok(PathBuf::from(configured));
    }
    app.path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())
}

fn migrate_legacy_database(app: &tauri::App, data: &std::path::Path) -> Result<(), String> {
    if cfg!(debug_assertions) || data.join("library.sqlite3").exists() {
        return Ok(());
    }
    let legacy = app
        .path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())?;
    for name in [
        "library.sqlite3",
        "library.sqlite3-wal",
        "library.sqlite3-shm",
    ] {
        let source = legacy.join(name);
        if source.is_file() {
            fs::copy(&source, data.join(name)).map_err(|error| error.to_string())?;
        }
    }
    Ok(())
}

fn uv_binary() -> PathBuf {
    if let Ok(executable) = std::env::current_exe() {
        if let Some(directory) = executable.parent() {
            for name in ["uv.exe", "uv-x86_64-pc-windows-msvc.exe"] {
                let bundled = directory.join(name);
                if bundled.exists() {
                    return bundled;
                }
            }
        }
    }
    PathBuf::from("uv")
}

fn registry_value(text: &str) -> Option<PathBuf> {
    text.lines().find_map(|line| {
        let (_, value) = line.split_once("REG_SZ")?;
        let value = value.trim();
        (!value.is_empty()).then(|| PathBuf::from(value))
    })
}

fn shared_model_directory() -> Option<PathBuf> {
    for name in ["WOOSH_MODEL_HOME", "AI_MODELS_HOME", "HF_HOME"] {
        if let Some(value) = std::env::var_os(name).filter(|value| !value.is_empty()) {
            let root = PathBuf::from(value);
            return Some(if name == "WOOSH_MODEL_HOME" {
                root
            } else {
                root.join("WooshStudio")
            });
        }
    }
    #[cfg(target_os = "windows")]
    {
        let output = Command::new("reg.exe")
            .args([
                "query",
                "HKCU\\Environment",
                "/v",
                "WOOSH_MODEL_HOME",
            ])
            .creation_flags(0x08000000)
            .output()
            .ok()?;
        if output.status.success() {
            return registry_value(&String::from_utf8_lossy(&output.stdout));
        }
    }
    None
}

fn environment_has_python_312(environment: &std::path::Path) -> bool {
    let interpreter = if cfg!(target_os = "windows") {
        environment.join("Scripts/python.exe")
    } else {
        environment.join("bin/python")
    };
    interpreter.is_file()
        && fs::read_to_string(environment.join("pyvenv.cfg"))
            .map(|config| {
                config
                    .lines()
                    .any(|line| line.trim().starts_with("version_info = 3.12."))
            })
            .unwrap_or(false)
}

fn uv_run_command(executable: &std::path::Path, source: &std::path::Path) -> Command {
    let mut command = Command::new(executable);
    command.args([
        "run",
        "--managed-python",
        "--python",
        "3.12",
        "--project",
        source.to_string_lossy().as_ref(),
        "--no-default-groups",
        "--group",
        "studio",
        "--group",
        "music",
        "--extra",
        "cuda",
        "woosh-studio-api",
    ]);
    command
}

fn spawn_backend(app: &tauri::App) -> Result<BackendState, String> {
    let port = free_port()?;
    let token = Uuid::new_v4().to_string();
    let source = source_directory(app)?;
    let app_data = data_directory(app)?;
    let logs = app_data.join("logs");
    fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
    migrate_legacy_database(app, &app_data)?;
    fs::create_dir_all(&logs).map_err(|error| error.to_string())?;
    let environment = app_data.join(".venv");
    let runtime_marker = environment.join(".woosh-runtime-version");
    let cache_path = app_data.join("uv-cache");
    let first_setup = !environment_has_python_312(&environment)
        || fs::read_to_string(&runtime_marker)
            .map(|version| version.trim() != env!("CARGO_PKG_VERSION"))
            .unwrap_or(true);
    let log_path = logs.join("api.log");
    let stdout = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&log_path)
        .map_err(|error| error.to_string())?;
    let stderr = stdout.try_clone().map_err(|error| error.to_string())?;
    let offline_models = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?
        .join("offline-model-archives");

    let uv = uv_binary();
    let mut command = uv_run_command(&uv, &source);
    command
        .current_dir(&source)
        .env("WOOSH_STUDIO_PORT", port.to_string())
        .env("WOOSH_STUDIO_TOKEN", &token)
        .env("WOOSH_STUDIO_HOME", &app_data)
        .env("UV_PROJECT_ENVIRONMENT", &environment)
        .env("UV_PYTHON_INSTALL_DIR", app_data.join("python"))
        .env("UV_CACHE_DIR", &cache_path)
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    if let Some(model_directory) = shared_model_directory() {
        fs::create_dir_all(&model_directory).map_err(|error| error.to_string())?;
        command.env("WOOSH_MODEL_HOME", model_directory);
    }
    if offline_models.is_dir() {
        command.env("WOOSH_STUDIO_OFFLINE_MODELS", offline_models);
    }
    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000);
    let child = command.spawn().map_err(|error| {
        format!("无法启动本地 Python 服务。请确认 uv 可用或重新安装应用: {error}")
    })?;
    Ok(BackendState {
        info: BackendInfo {
            url: format!("http://127.0.0.1:{port}"),
            token,
        },
        child: Mutex::new(Some(child)),
        first_setup,
        cache_path,
        log_path,
        runtime_marker,
        started_at: Instant::now(),
    })
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        if let Ok(mut child) = state.child.lock() {
            if let Some(mut process) = child.take() {
                #[cfg(target_os = "windows")]
                {
                    let process_id = process.id().to_string();
                    let _ = Command::new("taskkill")
                        .args(["/PID", &process_id, "/T", "/F"])
                        .creation_flags(0x08000000)
                        .status();
                }
                #[cfg(not(target_os = "windows"))]
                let _ = process.kill();
                let _ = process.wait();
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let application = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            backend_info,
            backend_status,
            reveal_in_explorer
        ])
        .setup(|app| {
            let state = spawn_backend(app)?;
            app.manage(state);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Woosh Studio");

    application.run(|app, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            stop_backend(app);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        backend_failure_detail, offline_setup_progress, parse_download_size, setup_progress,
        registry_value, uv_run_command,
    };
    use std::path::Path;

    #[test]
    fn parses_uv_download_sizes() {
        assert_eq!(parse_download_size("3.2GiB"), Some(3_435_973_836));
        assert_eq!(parse_download_size("7.2MiB"), Some(7_549_747));
    }

    #[test]
    fn reports_weighted_uv_setup_progress() {
        let status = setup_progress(
            "Creating virtual environment\nDownloading torch (3.2GiB)\nDownloading pillow (6.9MiB)\n Downloaded pillow\n",
            1024_u64.pow(3),
        );
        assert!(status.value > 0.3 && status.value < 0.4);
        assert!(status.detail.contains("下载 torch"));
        assert!(status.detail.contains("1024/3283 MiB"));
        assert!(status.detail.contains("1/2"));
    }

    #[test]
    fn reports_offline_model_install_progress() {
        let status = offline_setup_progress(
            "WOOSH_OFFLINE_PROGRESS 1 4 Woosh-DFlow\nWOOSH_OFFLINE_PROGRESS 1 4 Woosh-Flow\n",
        )
        .expect("offline progress");
        assert!(status.value > 0.93 && status.value < 0.94);
        assert_eq!(status.detail, "Woosh-Flow · 1/4");
    }

    #[test]
    fn restricts_uv_to_managed_python() {
        let command = uv_run_command(Path::new("uv"), Path::new("python-source"));
        let arguments = command
            .get_args()
            .map(|argument| argument.to_string_lossy().into_owned())
            .collect::<Vec<_>>();
        assert_eq!(
            &arguments[..4],
            ["run", "--managed-python", "--python", "3.12"]
        );
        assert!(arguments.windows(2).any(|pair| pair == ["--group", "music"]));
        assert!(arguments.windows(2).any(|pair| pair == ["--extra", "cuda"]));
    }

    #[test]
    fn reports_the_uv_failure_instead_of_a_generic_startup_message() {
        let detail = backend_failure_detail(
            "error: Failed to inspect Python interpreter\n  Caused by: untrusted mount point\n",
        );
        assert!(detail.contains("Failed to inspect Python interpreter"));
        assert!(detail.contains("untrusted mount point"));
    }

    #[test]
    fn parses_a_shared_model_directory_from_the_user_environment_registry() {
        let value = registry_value(
            "    WOOSH_MODEL_HOME    REG_SZ    E:\\AI Models\\WooshStudio\r\n",
        );
        assert_eq!(
            value.as_deref(),
            Some(Path::new("E:\\AI Models\\WooshStudio"))
        );
    }
}
