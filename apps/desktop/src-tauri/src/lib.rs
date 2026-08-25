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
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LoadBoardResponse {
    snapshot: Value,
    source: String,
    view_prefs: ViewPrefs,
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

fn execute(attempt: &CommandAttempt, database: Option<&str>) -> Result<Value, String> {
    let mut command = Command::new(&attempt.program);
    command
        .args(&attempt.prefix_args)
        .args(export_args(database));
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

    serde_json::from_slice(&output.stdout)
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
        .invoke_handler(tauri::generate_handler![load_board, save_view_prefs])
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
