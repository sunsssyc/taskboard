use serde::Serialize;
use serde_json::Value;
use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LoadBoardResponse {
    snapshot: Value,
    source: String,
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
fn load_board() -> Result<LoadBoardResponse, String> {
    let attempts = command_attempts();
    let database = env::var("TASKBOARD_DB").ok();
    let mut errors = Vec::new();
    for attempt in attempts {
        match execute(&attempt, database.as_deref()) {
            Ok(snapshot) => {
                return Ok(LoadBoardResponse {
                    snapshot,
                    source: attempt.source,
                });
            }
            Err(error) => errors.push(error),
        }
    }

    Err(format!("无法读取任务看板。已尝试：\n{}", errors.join("\n")))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![load_board])
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
}
