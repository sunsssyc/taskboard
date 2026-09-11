mod agent;

use agent::{AgentDispatchRequest, AgentLaunch, CodexProcess};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;

const VIEW_PREF_MAX_ITEMS: usize = 500;
const VIEW_PREF_MAX_CHARS: usize = 200;

#[derive(Debug, Clone, Default, Deserialize, PartialEq, Serialize)]
struct ViewPrefs {
    order: Vec<String>,
    pinned: Vec<String>,
}

#[derive(Default)]
struct BridgeState {
    database: Mutex<Option<PathBuf>>,
    codex_processes: Mutex<Vec<CodexProcess>>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LoadBoardResponse {
    snapshot: Value,
    source: String,
    view_prefs: ViewPrefs,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AgentDispatchResponse {
    provider: String,
    dispatch_id: String,
    repository_path: String,
    status: String,
    external_thread_id: Option<String>,
    external_turn_id: Option<String>,
    started_at: String,
    warning: Option<String>,
}

#[derive(Debug)]
struct CommandAttempt {
    program: String,
    prefix_args: Vec<String>,
    current_dir: Option<PathBuf>,
    source: String,
}

fn export_args(database: Option<&str>) -> Vec<String> {
    let mut args = Vec::new();
    if let Some(database) = database.filter(|value| !value.trim().is_empty()) {
        args.push("--db".into());
        args.push(database.into());
    }
    args.extend([
        "export".into(),
        "--json".into(),
        "--all".into(),
        "--show-paths".into(),
        "--out".into(),
        "-".into(),
    ]);
    args
}

fn development_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn view_prefs_path(database: &Path) -> PathBuf {
    let stem = database
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("board");
    database.with_file_name(format!("{stem}.view.json"))
}

fn clean_pref_list(values: Vec<String>) -> Vec<String> {
    values
        .into_iter()
        .take(VIEW_PREF_MAX_ITEMS)
        .filter(|value| !value.is_empty() && !value.contains('\0'))
        .map(|value| value.chars().take(VIEW_PREF_MAX_CHARS).collect())
        .collect()
}

fn clean_view_prefs(prefs: ViewPrefs) -> ViewPrefs {
    ViewPrefs {
        order: clean_pref_list(prefs.order),
        pinned: clean_pref_list(prefs.pinned),
    }
}

fn load_view_prefs(database: &Path) -> ViewPrefs {
    let Ok(bytes) = fs::read(view_prefs_path(database)) else {
        return ViewPrefs::default();
    };
    serde_json::from_slice::<ViewPrefs>(&bytes)
        .map(clean_view_prefs)
        .unwrap_or_default()
}

fn write_view_prefs(database: &Path, prefs: ViewPrefs) -> Result<ViewPrefs, String> {
    let cleaned = clean_view_prefs(prefs);
    let path = view_prefs_path(database);
    let temporary = path.with_file_name(format!(
        "{}.next",
        path.file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("board.view.json")
    ));
    let mut payload = serde_json::to_vec_pretty(&cleaned)
        .map_err(|error| format!("无法编码视图偏好：{error}"))?;
    payload.push(b'\n');
    fs::write(&temporary, payload)
        .map_err(|error| format!("无法写入视图偏好 {}：{error}", temporary.display()))?;
    fs::rename(&temporary, &path)
        .map_err(|error| format!("无法保存视图偏好 {}：{error}", path.display()))?;
    Ok(cleaned)
}

fn snapshot_database(snapshot: &Value) -> Option<PathBuf> {
    snapshot
        .get("db")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

fn command_attempts() -> Vec<CommandAttempt> {
    let mut attempts = Vec::new();

    if let Ok(executable) = env::var("TASKBOARD_BOARD_EXECUTABLE") {
        if !executable.trim().is_empty() {
            attempts.push(CommandAttempt {
                program: executable,
                prefix_args: Vec::new(),
                current_dir: None,
                source: "TASKBOARD_BOARD_EXECUTABLE".into(),
            });
        }
    }

    let root = development_root();
    if cfg!(debug_assertions) && root.join("pyproject.toml").is_file() {
        let python = env::var("TASKBOARD_PYTHON").unwrap_or_else(|_| {
            if cfg!(windows) {
                "python".into()
            } else {
                "python3".into()
            }
        });
        attempts.push(CommandAttempt {
            program: python,
            prefix_args: vec!["-m".into(), "taskboard.cli".into()],
            current_dir: Some(root),
            source: "Python 模块（开发）".into(),
        });
    }

    // Finder 启动的 .app 只有精简 PATH,按 Swift 壳 BoardConfiguration 的候选路径探测。
    let home = env::var("HOME").unwrap_or_default();
    for candidate in [
        "/opt/anaconda3/bin/board".into(),
        "/opt/homebrew/bin/board".into(),
        "/usr/local/bin/board".into(),
        format!("{home}/.local/bin/board"),
    ] {
        if Path::new(&candidate).is_file() {
            attempts.push(CommandAttempt {
                program: candidate.clone(),
                prefix_args: Vec::new(),
                current_dir: None,
                source: candidate,
            });
        }
    }

    attempts.push(CommandAttempt {
        program: "board".into(),
        prefix_args: Vec::new(),
        current_dir: None,
        source: "PATH 中的 board".into(),
    });
    attempts
}

fn run_board(attempt: &CommandAttempt, args: &[String]) -> Result<Vec<u8>, String> {
    let mut command = Command::new(&attempt.program);
    command.args(&attempt.prefix_args).args(args);
    if let Some(directory) = &attempt.current_dir {
        command.current_dir(directory);
    }
    command.env("NO_COLOR", "1");

    let output = command
        .output()
        .map_err(|error| format!("{}：{}", attempt.source, error))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        let detail = if stderr.is_empty() {
            format!("退出码 {}", output.status)
        } else {
            stderr
        };
        return Err(format!("{}：{}", attempt.source, detail));
    }

    Ok(output.stdout)
}

fn execute(attempt: &CommandAttempt, database: Option<&str>) -> Result<Value, String> {
    let stdout = run_board(attempt, &export_args(database))?;
    serde_json::from_slice(&stdout)
        .map_err(|error| format!("{} 返回了无效 JSON：{}", attempt.source, error))
}

#[tauri::command]
fn load_board(state: tauri::State<'_, BridgeState>) -> Result<LoadBoardResponse, String> {
    let attempts = command_attempts();
    let database = env::var("TASKBOARD_DB").ok();
    let mut errors = Vec::new();
    for attempt in attempts {
        match execute(&attempt, database.as_deref()) {
            Ok(snapshot) => {
                let database = snapshot_database(&snapshot);
                let view_prefs = database.as_deref().map(load_view_prefs).unwrap_or_default();
                *state
                    .database
                    .lock()
                    .map_err(|_| "无法记录当前数据库路径".to_string())? = database;
                return Ok(LoadBoardResponse {
                    snapshot,
                    source: attempt.source,
                    view_prefs,
                });
            }
            Err(error) => errors.push(error),
        }
    }

    Err(format!("无法读取任务看板。已尝试：\n{}", errors.join("\n")))
}

/// 与 board serve 网页同一状态白名单;放弃等其余写入仍走 CLI,依赖判断与 HEAD 记录由 CLI 负责。
const STATUS_SUBCOMMANDS: [(&str, &str); 4] = [
    ("todo", "todo"),
    ("active", "start"),
    ("waiting", "wait"),
    ("done", "done"),
];
const OWNER_VALUES: [&str; 4] = ["", "你", "我", "双方"];

fn validated_project(project: &str) -> Result<&str, String> {
    let project = project.trim();
    if project.is_empty() || project.len() > 120 || project.starts_with('-') {
        return Err("需求 key 无效".into());
    }
    Ok(project)
}

fn status_args(
    database: Option<&str>,
    subcommand: &str,
    reference: u32,
    project: &str,
) -> Vec<String> {
    let mut args = Vec::new();
    if let Some(database) = database.filter(|value| !value.trim().is_empty()) {
        args.push("--db".into());
        args.push(database.into());
    }
    args.extend([
        subcommand.into(),
        reference.to_string(),
        "-p".into(),
        project.into(),
    ]);
    args
}

fn owner_args(database: Option<&str>, reference: u32, project: &str, owner: &str) -> Vec<String> {
    let mut args = Vec::new();
    if let Some(database) = database.filter(|value| !value.trim().is_empty()) {
        args.push("--db".into());
        args.push(database.into());
    }
    args.extend([
        "edit".into(),
        reference.to_string(),
        "--owner".into(),
        owner.into(),
        "-p".into(),
        project.into(),
    ]);
    args
}

fn priority_args(
    database: Option<&str>,
    reference: u32,
    project: &str,
    priority: u8,
) -> Vec<String> {
    let mut args = Vec::new();
    if let Some(database) = database.filter(|value| !value.trim().is_empty()) {
        args.push("--db".into());
        args.push(database.into());
    }
    args.extend([
        "edit".into(),
        reference.to_string(),
        "--priority".into(),
        format!("P{priority}"),
        "-p".into(),
        project.into(),
    ]);
    args
}

fn project_archive_args(database: &Path, project: &str, archived: bool) -> Vec<String> {
    vec![
        "--db".into(),
        database.to_string_lossy().into_owned(),
        "set".into(),
        "-p".into(),
        project.into(),
        if archived {
            "--archive".into()
        } else {
            "--unarchive".into()
        },
    ]
}

fn agent_run_args(
    database: &Path,
    project: &str,
    reference: u32,
    launch: &AgentLaunch,
) -> Vec<String> {
    let mut args = vec![
        "--db".into(),
        database.to_string_lossy().into_owned(),
        "agent-run".into(),
        reference.to_string(),
        "--provider".into(),
        launch.provider.clone(),
        "--dispatch-id".into(),
        launch.dispatch_id.clone(),
        "--repository".into(),
        launch.repository_path.clone(),
        "--status".into(),
        launch.status.clone(),
        "-p".into(),
        project.into(),
    ];
    if let Some(thread_id) = &launch.external_thread_id {
        args.extend(["--thread-id".into(), thread_id.clone()]);
    }
    if let Some(turn_id) = &launch.external_turn_id {
        args.extend(["--turn-id".into(), turn_id.clone()]);
    }
    if let Some(warning) = &launch.warning {
        args.extend(["--error".into(), warning.clone()]);
    }
    args
}

fn record_agent_launch(
    database: &Path,
    project: &str,
    reference: u32,
    launch: &AgentLaunch,
) -> Result<String, String> {
    let args = agent_run_args(database, project, reference, launch);
    let mut errors = Vec::new();
    for attempt in command_attempts() {
        match run_board(&attempt, &args) {
            Ok(stdout) => {
                let row: Value = serde_json::from_slice(&stdout)
                    .map_err(|error| format!("Agent 已启动，但看板返回无效记录：{error}"))?;
                return row
                    .get("started_at")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
                    .ok_or_else(|| "Agent 已启动，但看板记录缺少开始时间".to_string());
            }
            Err(error) => errors.push(error),
        }
    }
    Err(format!(
        "Agent 已启动，但无法保存派发记录。已尝试：\n{}",
        errors.join("\n")
    ))
}

fn trusted_agent_request(
    database: &Path,
    request: &AgentDispatchRequest,
) -> Result<AgentDispatchRequest, String> {
    let requested_repository = fs::canonicalize(&request.repository_path).map_err(|error| {
        format!(
            "无法解析 Agent 工作目录 {}：{error}",
            request.repository_path
        )
    })?;
    let database_text = database.to_string_lossy();
    let mut errors = Vec::new();
    for attempt in command_attempts() {
        match execute(&attempt, Some(&database_text)) {
            Ok(snapshot) => {
                let project = snapshot
                    .get("projects")
                    .and_then(Value::as_array)
                    .and_then(|projects| {
                        projects.iter().find(|project| {
                            project.get("key").and_then(Value::as_str)
                                == Some(request.project.as_str())
                        })
                    })
                    .ok_or_else(|| format!("看板里没有需求 {}", request.project))?;
                let task = project
                    .get("tasks")
                    .and_then(Value::as_array)
                    .and_then(|tasks| {
                        tasks.iter().find(|task| {
                            task.get("ref").and_then(Value::as_u64)
                                == Some(u64::from(request.reference))
                        })
                    })
                    .ok_or_else(|| {
                        format!("{} 里没有任务 #{}", request.project, request.reference)
                    })?;
                let repository_allowed = task
                    .get("repositories")
                    .and_then(Value::as_array)
                    .is_some_and(|repositories| {
                        repositories.iter().any(|repository| {
                            repository
                                .get("path")
                                .and_then(Value::as_str)
                                .and_then(|path| fs::canonicalize(path).ok())
                                .as_deref()
                                == Some(requested_repository.as_path())
                        })
                    });
                if !repository_allowed {
                    return Err(format!(
                        "仓库 {} 未关联到 {} #{}",
                        request.repository_path, request.project, request.reference
                    ));
                }
                return Ok(AgentDispatchRequest {
                    provider: request.provider.clone(),
                    project: request.project.clone(),
                    reference: request.reference,
                    title: task
                        .get("title")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_owned(),
                    detail: task
                        .get("detail")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    accept: task
                        .get("accept")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    repository_path: requested_repository.to_string_lossy().into_owned(),
                });
            }
            Err(error) => errors.push(error),
        }
    }
    Err(format!(
        "无法核对待派发任务。已尝试：\n{}",
        errors.join("\n")
    ))
}

#[tauri::command]
fn set_task_status(project: String, reference: u32, status: String) -> Result<(), String> {
    let subcommand = STATUS_SUBCOMMANDS
        .iter()
        .find(|(name, _)| *name == status)
        .map(|(_, subcommand)| *subcommand)
        .ok_or_else(|| "桌面端只允许 todo/active/waiting/done".to_string())?;
    let project = validated_project(&project)?;

    let database = env::var("TASKBOARD_DB").ok();
    let args = status_args(database.as_deref(), subcommand, reference, project);
    let mut errors = Vec::new();
    for attempt in command_attempts() {
        match run_board(&attempt, &args) {
            Ok(_) => return Ok(()),
            Err(error) => errors.push(error),
        }
    }
    Err(format!("无法更新任务状态。已尝试：\n{}", errors.join("\n")))
}

#[tauri::command]
fn set_task_owner(project: String, reference: u32, owner: String) -> Result<(), String> {
    if !OWNER_VALUES.contains(&owner.as_str()) {
        return Err("桌面端只允许用户/Agent/双方/未分配".into());
    }
    let project = validated_project(&project)?;
    let database = env::var("TASKBOARD_DB").ok();
    let args = owner_args(database.as_deref(), reference, project, &owner);
    let mut errors = Vec::new();
    for attempt in command_attempts() {
        match run_board(&attempt, &args) {
            Ok(_) => return Ok(()),
            Err(error) => errors.push(error),
        }
    }
    Err(format!(
        "无法更新任务负责人。已尝试：\n{}",
        errors.join("\n")
    ))
}

#[tauri::command]
fn set_task_priority(project: String, reference: u32, priority: u8) -> Result<(), String> {
    if priority > 3 {
        return Err("桌面端只允许 P0/P1/P2/P3".into());
    }
    let project = validated_project(&project)?;
    let database = env::var("TASKBOARD_DB").ok();
    let args = priority_args(database.as_deref(), reference, project, priority);
    let mut errors = Vec::new();
    for attempt in command_attempts() {
        match run_board(&attempt, &args) {
            Ok(_) => return Ok(()),
            Err(error) => errors.push(error),
        }
    }
    Err(format!(
        "无法更新任务优先级。已尝试：\n{}",
        errors.join("\n")
    ))
}

#[tauri::command]
fn set_project_archived(
    state: tauri::State<'_, BridgeState>,
    project: String,
    archived: bool,
) -> Result<(), String> {
    let project = validated_project(&project)?;
    let database = state
        .database
        .lock()
        .map_err(|_| "无法读取当前数据库路径".to_string())?
        .clone()
        .ok_or_else(|| "任务看板尚未载入，不能完成需求".to_string())?;
    let args = project_archive_args(&database, project, archived);
    let mut errors = Vec::new();
    for attempt in command_attempts() {
        match run_board(&attempt, &args) {
            Ok(_) => return Ok(()),
            Err(error) => errors.push(error),
        }
    }
    Err(format!(
        "无法{}需求。已尝试：\n{}",
        if archived { "完成" } else { "恢复" },
        errors.join("\n")
    ))
}

#[tauri::command]
fn dispatch_task_agent(
    state: tauri::State<'_, BridgeState>,
    request: AgentDispatchRequest,
) -> Result<AgentDispatchResponse, String> {
    let project = validated_project(&request.project)?.to_owned();
    let database = state
        .database
        .lock()
        .map_err(|_| "无法读取当前数据库路径".to_string())?
        .clone()
        .ok_or_else(|| "任务看板尚未载入，不能派发任务".to_string())?;
    let request = trusted_agent_request(&database, &request)?;
    let (launch, process) = agent::launch(&request)?;
    let started_at = record_agent_launch(&database, &project, request.reference, &launch)?;
    if let Some(process) = process {
        state
            .codex_processes
            .lock()
            .map_err(|_| "派发已记录，但无法保持 Codex app-server 连接".to_string())?
            .push(process);
    }
    Ok(AgentDispatchResponse {
        provider: launch.provider,
        dispatch_id: launch.dispatch_id,
        repository_path: launch.repository_path,
        status: launch.status,
        external_thread_id: launch.external_thread_id,
        external_turn_id: launch.external_turn_id,
        started_at,
        warning: launch.warning,
    })
}

#[tauri::command]
fn save_view_prefs(
    state: tauri::State<'_, BridgeState>,
    prefs: ViewPrefs,
) -> Result<ViewPrefs, String> {
    let database = state
        .database
        .lock()
        .map_err(|_| "无法读取当前数据库路径".to_string())?
        .clone()
        .ok_or_else(|| "任务看板尚未载入，不能保存视图偏好".to_string())?;
    write_view_prefs(&database, prefs)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BridgeState::default())
        .invoke_handler(tauri::generate_handler![
            load_board,
            dispatch_task_agent,
            save_view_prefs,
            set_project_archived,
            set_task_owner,
            set_task_priority,
            set_task_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running Taskboard desktop");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn development_root_contains_python_project() {
        assert!(development_root().join("pyproject.toml").is_file());
    }

    #[test]
    fn export_command_is_read_only() {
        let args = export_args(Some("/tmp/taskboard-test.db"));
        assert!(args
            .windows(2)
            .any(|pair| pair[0] == "--db" && pair[1] == "/tmp/taskboard-test.db"));
        assert!(args
            .windows(2)
            .any(|pair| pair[0] == "export" && pair[1] == "--json"));
        assert!(args
            .windows(2)
            .any(|pair| pair[0] == "--out" && pair[1] == "-"));
        assert!(args.iter().any(|arg| arg == "--all"));
        assert!(!args
            .iter()
            .any(|arg| { matches!(arg.as_str(), "add" | "start" | "wait" | "done" | "todo") }));
    }

    #[test]
    fn development_bridge_reads_python_snapshot() {
        let root = development_root();
        let database = env::temp_dir().join(format!(
            "taskboard-tauri-bridge-{}-{}.db",
            std::process::id(),
            std::thread::current().name().unwrap_or("test")
        ));
        let python = env::var("TASKBOARD_PYTHON").unwrap_or_else(|_| "python3".into());
        let database_text = database.to_string_lossy().into_owned();
        let status = Command::new(&python)
            .current_dir(&root)
            .args([
                "-m",
                "taskboard.cli",
                "--db",
                &database_text,
                "init",
                "bridge-test",
                "--name",
                "Bridge Test",
            ])
            .status()
            .expect("Python board command should start");
        assert!(status.success());

        let attempt = CommandAttempt {
            program: python,
            prefix_args: vec!["-m".into(), "taskboard.cli".into()],
            current_dir: Some(root),
            source: "test Python bridge".into(),
        };
        let snapshot = execute(&attempt, Some(&database_text)).expect("snapshot should load");
        assert_eq!(snapshot["projects"][0]["key"], "bridge-test");

        for suffix in ["", "-wal", "-shm"] {
            let _ = std::fs::remove_file(format!("{}{}", database_text, suffix));
        }
    }

    #[test]
    fn status_command_maps_web_whitelist_to_cli() {
        let args = status_args(Some("/tmp/db"), "start", 27, "reg-calibration");
        assert_eq!(
            args,
            vec!["--db", "/tmp/db", "start", "27", "-p", "reg-calibration"]
        );
        assert!(STATUS_SUBCOMMANDS
            .iter()
            .all(|(_, subcommand)| matches!(*subcommand, "todo" | "start" | "wait" | "done")));
        assert!(!STATUS_SUBCOMMANDS
            .iter()
            .any(|(name, _)| matches!(*name, "dropped" | "rm" | "drop")));
    }

    #[test]
    fn owner_command_maps_assignment_to_cli_without_expanding_values() {
        let args = owner_args(Some("/tmp/db"), 32, "taskboard", "我");
        assert_eq!(
            args,
            vec![
                "--db",
                "/tmp/db",
                "edit",
                "32",
                "--owner",
                "我",
                "-p",
                "taskboard"
            ]
        );
        assert_eq!(OWNER_VALUES, ["", "你", "我", "双方"]);
    }

    #[test]
    fn priority_command_maps_to_explicit_cli_value() {
        let args = priority_args(Some("/tmp/db"), 38, "reg-calibration", 0);
        assert_eq!(
            args,
            vec![
                "--db",
                "/tmp/db",
                "edit",
                "38",
                "--priority",
                "P0",
                "-p",
                "reg-calibration"
            ]
        );
    }

    #[test]
    fn project_archive_command_is_reversible_and_scoped() {
        assert_eq!(
            project_archive_args(Path::new("/tmp/db"), "taskboard", true),
            vec!["--db", "/tmp/db", "set", "-p", "taskboard", "--archive"]
        );
        assert_eq!(
            project_archive_args(Path::new("/tmp/db"), "taskboard", false),
            vec!["--db", "/tmp/db", "set", "-p", "taskboard", "--unarchive"]
        );
    }

    #[test]
    fn agent_run_command_records_only_public_dispatch_ids() {
        let launch = AgentLaunch {
            provider: "codex".into(),
            dispatch_id: "codex-123".into(),
            repository_path: "/tmp/taskboard".into(),
            status: "submitted".into(),
            external_thread_id: Some("thread-1".into()),
            external_turn_id: Some("turn-1".into()),
            warning: None,
        };
        let args = agent_run_args(Path::new("/tmp/board.db"), "taskboard", 33, &launch);
        assert!(args
            .windows(2)
            .any(|pair| pair == ["--thread-id", "thread-1"]));
        assert!(args.windows(2).any(|pair| pair == ["--turn-id", "turn-1"]));
        assert!(!args
            .iter()
            .any(|arg| arg.contains(".codex") || arg.contains("Claude")));
    }

    #[test]
    #[ignore = "会创建真实 Codex 桌面线程，仅在手工验收 Agent 派发时运行"]
    fn real_codex_dispatch_smoke_records_public_ids() {
        let root =
            env::temp_dir().join(format!("taskboard-real-agent-smoke-{}", std::process::id()));
        let repository = env::var_os("TASKBOARD_AGENT_SMOKE_REPOSITORY")
            .map(PathBuf::from)
            .unwrap_or_else(|| root.join("repo"));
        fs::create_dir_all(&repository).expect("smoke repository should exist");
        let repository = repository
            .canonicalize()
            .expect("smoke repository should resolve");
        let database = root.join("board.db");
        let python = env::var("TASKBOARD_PYTHON").unwrap_or_else(|_| "python3".into());
        let attempt = CommandAttempt {
            program: python,
            prefix_args: vec!["-m".into(), "taskboard.cli".into()],
            current_dir: Some(development_root()),
            source: "smoke Python bridge".into(),
        };
        let database_text = database.to_string_lossy().into_owned();
        let repository_text = repository.to_string_lossy().into_owned();
        run_board(
            &attempt,
            &[
                "--db".into(),
                database_text.clone(),
                "init".into(),
                "smoke".into(),
                "--name".into(),
                "Agent Smoke".into(),
                "--repo".into(),
                repository_text.clone(),
            ],
        )
        .expect("smoke project should initialize");
        run_board(
            &attempt,
            &[
                "--db".into(),
                database_text.clone(),
                "add".into(),
                "仅回复 TASKBOARD_TEMP_REPO_SMOKE_OK，不修改文件".into(),
                "--detail".into(),
                "读取提示后只回复 TASKBOARD_TEMP_REPO_SMOKE_OK。".into(),
                "--accept".into(),
                "不得创建、修改或删除任何文件。".into(),
                "--repo".into(),
                repository_text.clone(),
                "-p".into(),
                "smoke".into(),
            ],
        )
        .expect("smoke task should initialize");
        let request = AgentDispatchRequest {
            provider: "codex".into(),
            project: "smoke".into(),
            reference: 1,
            title: "stale client title".into(),
            detail: None,
            accept: None,
            repository_path: repository_text,
        };
        let trusted = trusted_agent_request(&database, &request).expect("task should be trusted");
        assert_eq!(
            trusted.title,
            "仅回复 TASKBOARD_TEMP_REPO_SMOKE_OK，不修改文件"
        );
        let (launch, process) =
            agent::launch_read_only_smoke(&trusted).expect("Codex should accept the turn");
        let started_at =
            record_agent_launch(&database, "smoke", 1, &launch).expect("run should persist");
        println!(
            "smoke started_at={started_at} thread={} turn={}",
            launch.external_thread_id.as_deref().unwrap_or("missing"),
            launch.external_turn_id.as_deref().unwrap_or("missing")
        );
        assert!(launch.external_thread_id.is_some());
        assert!(launch.external_turn_id.is_some());
        let process = process.expect("Codex monitor should be retained");
        assert!(
            process.wait_until_finished(std::time::Duration::from_secs(55)),
            "Codex smoke turn should finish and hand off to the desktop app"
        );
        drop(process);
        let snapshot = execute(&attempt, Some(&database_text)).expect("snapshot should reload");
        assert_eq!(
            snapshot["projects"][0]["tasks"][0]["agent_runs"][0]["status"],
            "submitted"
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn view_prefs_path_matches_python_sidecar_name() {
        assert_eq!(
            view_prefs_path(Path::new("/tmp/board.db")),
            PathBuf::from("/tmp/board.view.json")
        );
    }

    #[test]
    fn view_prefs_round_trip_is_clean_and_shared() {
        let database = env::temp_dir().join(format!(
            "taskboard-tauri-prefs-{}-{}.db",
            std::process::id(),
            std::thread::current().name().unwrap_or("test")
        ));
        let expected = ViewPrefs {
            order: vec!["beta".into(), "alpha".into()],
            pinned: vec!["beta".into()],
        };
        assert_eq!(
            write_view_prefs(&database, expected.clone()).expect("prefs should save"),
            expected
        );
        assert_eq!(load_view_prefs(&database), expected);
        let _ = fs::remove_file(view_prefs_path(&database));
    }
}
