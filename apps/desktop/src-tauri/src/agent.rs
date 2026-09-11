use serde::Deserialize;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender, TryRecvError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use url::Url;

const RPC_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_PROMPT_CHARS: usize = 13_000;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AgentDispatchRequest {
    pub provider: String,
    pub project: String,
    pub reference: u32,
    pub title: String,
    pub detail: Option<String>,
    pub accept: Option<String>,
    pub repository_path: String,
}

#[derive(Debug)]
pub struct AgentLaunch {
    pub provider: String,
    pub dispatch_id: String,
    pub repository_path: String,
    pub status: String,
    pub external_thread_id: Option<String>,
    pub external_turn_id: Option<String>,
    pub warning: Option<String>,
}

pub struct CodexProcess {
    cancel: Sender<()>,
    worker: Option<JoinHandle<()>>,
}

impl Drop for CodexProcess {
    fn drop(&mut self) {
        let _ = self.cancel.send(());
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

#[cfg(test)]
impl CodexProcess {
    pub fn wait_until_finished(&self, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        while !self.worker.as_ref().is_some_and(JoinHandle::is_finished) {
            if Instant::now() >= deadline {
                return false;
            }
            thread::sleep(Duration::from_millis(100));
        }
        true
    }
}

fn clean_text(value: &str, label: &str, max_chars: usize) -> Result<String, String> {
    let value = value.trim();
    if value.is_empty() || value.contains('\0') || value.chars().count() > max_chars {
        return Err(format!("{label}无效"));
    }
    Ok(value.to_owned())
}

fn validated_repository(value: &str) -> Result<PathBuf, String> {
    let path = PathBuf::from(value);
    if !path.is_absolute() {
        return Err("Agent 工作目录必须是绝对路径".into());
    }
    if !path.is_dir() {
        return Err(format!(
            "Agent 工作目录不存在或不是目录：{}",
            path.display()
        ));
    }
    fs::canonicalize(&path)
        .map_err(|error| format!("无法解析 Agent 工作目录 {}：{error}", path.display()))
}

fn dispatch_id(provider: &str, reference: u32) -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("{provider}-{millis}-{}-{reference}", std::process::id())
}

fn truncated(value: String, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value;
    }
    let mut result: String = value.chars().take(max_chars.saturating_sub(18)).collect();
    result.push_str("\n\n[内容已截断]");
    result
}

pub fn task_prompt(request: &AgentDispatchRequest, dispatch_id: &str) -> Result<String, String> {
    let project = clean_text(&request.project, "需求 key", 120)?;
    let title = clean_text(&request.title, "任务标题", 500)?;
    if request.reference == 0 {
        return Err("任务编号无效".into());
    }
    let repository = validated_repository(&request.repository_path)?;
    let mut sections = vec![
        "你正在接手 Taskboard 派发的本地开发任务。".to_owned(),
        format!("派发标识：{dispatch_id}"),
        format!("需求：{project}"),
        format!("任务：#{} {title}", request.reference),
        format!("工作目录：{}", repository.display()),
    ];
    if let Some(detail) = request
        .detail
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        sections.push(format!("任务说明：\n{detail}"));
    }
    if let Some(accept) = request
        .accept
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        sections.push(format!("验收条件：\n{accept}"));
    }
    sections.push(
        "执行要求：\n- 先阅读仓库内 AGENTS.md、CLAUDE.md 等项目说明。\n- 只在上述工作目录和任务范围内操作。\n- 完成后运行与改动相称的测试，并明确报告改动、验证结果和遗留风险。"
            .to_owned(),
    );
    Ok(truncated(sections.join("\n\n"), MAX_PROMPT_CHARS))
}

fn codex_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(configured) = env::var("TASKBOARD_CODEX_EXECUTABLE") {
        if !configured.trim().is_empty() {
            candidates.push(PathBuf::from(configured));
        }
    }
    candidates.extend([
        PathBuf::from("/Applications/ChatGPT.app/Contents/Resources/codex"),
        PathBuf::from("/Applications/Codex.app/Contents/Resources/codex"),
        PathBuf::from("/opt/homebrew/bin/codex"),
        PathBuf::from("/usr/local/bin/codex"),
    ]);
    candidates
}

fn codex_executable() -> Result<PathBuf, String> {
    codex_candidates()
        .into_iter()
        .find(|candidate| candidate.is_file())
        .ok_or_else(|| {
            "找不到 Codex CLI；请安装或更新 ChatGPT/Codex 桌面应用，或设置 TASKBOARD_CODEX_EXECUTABLE"
                .into()
        })
}

fn desktop_codex_installed() -> bool {
    Path::new("/Applications/ChatGPT.app").is_dir() || Path::new("/Applications/Codex.app").is_dir()
}

fn send_message(stdin: &mut ChildStdin, payload: &Value) -> Result<(), String> {
    serde_json::to_writer(&mut *stdin, payload)
        .map_err(|error| format!("无法编码 Codex app-server 请求：{error}"))?;
    stdin
        .write_all(b"\n")
        .and_then(|_| stdin.flush())
        .map_err(|error| format!("无法写入 Codex app-server：{error}"))
}

fn rpc_call(
    stdin: &mut ChildStdin,
    receiver: &Receiver<String>,
    id: u64,
    method: &str,
    params: Value,
) -> Result<Value, String> {
    send_message(
        stdin,
        &json!({ "id": id, "method": method, "params": params }),
    )?;
    let deadline = Instant::now() + RPC_TIMEOUT;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(format!("Codex app-server 响应超时：{method}"));
        }
        let line = match receiver.recv_timeout(remaining) {
            Ok(line) => line,
            Err(RecvTimeoutError::Timeout) => {
                return Err(format!("Codex app-server 响应超时：{method}"));
            }
            Err(RecvTimeoutError::Disconnected) => {
                return Err(format!("Codex app-server 在 {method} 前已退出"));
            }
        };
        let message: Value = serde_json::from_str(&line)
            .map_err(|error| format!("Codex app-server 返回无效 JSON：{error}"))?;
        if message.get("id").and_then(Value::as_u64) != Some(id) {
            continue;
        }
        if let Some(error) = message.get("error") {
            return Err(format!("Codex {method} 失败：{error}"));
        }
        return message
            .get("result")
            .cloned()
            .ok_or_else(|| format!("Codex {method} 响应缺少 result"));
    }
}

fn spawn_stdout_reader(stdout: impl std::io::Read + Send + 'static) -> Receiver<String> {
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let _ = sender.send(line);
        }
    });
    receiver
}

fn drain_output(output: impl std::io::Read + Send + 'static) {
    thread::spawn(move || {
        for line in BufReader::new(output).lines() {
            if line.is_err() {
                break;
            }
        }
    });
}

fn project_id_from_list(projects: &Value, repository: &Path) -> Option<String> {
    projects
        .get("data")?
        .as_array()?
        .iter()
        .find(|project| {
            project
                .get("roots")
                .and_then(Value::as_array)
                .is_some_and(|roots| {
                    roots.iter().any(|root| {
                        root.get("path")
                            .and_then(Value::as_str)
                            .and_then(|path| fs::canonicalize(path).ok())
                            .as_deref()
                            == Some(repository)
                    })
                })
        })?
        .get("id")?
        .as_str()
        .map(str::to_owned)
}

fn codex_project_id(
    stdin: &mut ChildStdin,
    receiver: &Receiver<String>,
    repository: &Path,
    next_rpc_id: &mut u64,
) -> Result<String, String> {
    let mut cursor: Option<String> = None;
    loop {
        let result = rpc_call(
            stdin,
            receiver,
            *next_rpc_id,
            "project/list",
            json!({ "cursor": cursor, "limit": 100 }),
        )?;
        *next_rpc_id += 1;
        if let Some(project_id) = project_id_from_list(&result, repository) {
            return Ok(project_id);
        }
        cursor = result
            .get("nextCursor")
            .and_then(Value::as_str)
            .map(str::to_owned);
        if cursor.is_none() {
            break;
        }
    }

    let name = repository
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or("repo");
    let created = rpc_call(
        stdin,
        receiver,
        *next_rpc_id,
        "project/create",
        json!({
            "idempotencyKey": format!("taskboard-project:{}", repository.display()),
            "name": name,
            "roots": [{ "path": repository }],
            "metadata": { "source": "taskboard" }
        }),
    )?;
    *next_rpc_id += 1;
    created
        .pointer("/project/id")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| "Codex project/create 未返回项目 ID".to_string())
}

fn codex_thread_url(thread_id: &str) -> Result<Url, String> {
    let thread_id = clean_text(thread_id, "Codex 线程 ID", 120)?;
    let mut url = Url::parse("codex://threads/")
        .map_err(|error| format!("无法生成 Codex 线程深链：{error}"))?;
    url.path_segments_mut()
        .map_err(|_| "无法生成 Codex 线程深链".to_string())?
        .push(&thread_id);
    Ok(url)
}

fn open_codex_thread(thread_id: &str) -> Result<(), String> {
    let url = codex_thread_url(thread_id)?;
    let output = Command::new("/usr/bin/open")
        .arg(url.as_str())
        .output()
        .map_err(|error| format!("无法打开 Codex 线程：{error}"))?;
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    Err(if stderr.is_empty() {
        format!("Codex 线程打开失败：{}", output.status)
    } else {
        format!("Codex 线程打开失败：{stderr}")
    })
}

fn turn_completed(message: &str, turn_id: &str) -> bool {
    let Ok(message) = serde_json::from_str::<Value>(message) else {
        return false;
    };
    message.get("method").and_then(Value::as_str) == Some("turn/completed")
        && message.pointer("/params/turn/id").and_then(Value::as_str) == Some(turn_id)
}

fn monitor_codex_turn(
    mut child: Child,
    stdin: ChildStdin,
    receiver: Receiver<String>,
    cancel: Receiver<()>,
    turn_id: String,
) {
    loop {
        match cancel.try_recv() {
            Ok(()) | Err(TryRecvError::Disconnected) => break,
            Err(TryRecvError::Empty) => {}
        }
        match receiver.recv_timeout(Duration::from_millis(250)) {
            Ok(message) if turn_completed(&message, &turn_id) => break,
            Ok(_) | Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => break,
        }
    }
    drop(stdin);
    let _ = child.kill();
    let _ = child.wait();
}

fn launch_codex(
    request: &AgentDispatchRequest,
    repository: &Path,
    dispatch_id: String,
    prompt: String,
    sandbox: &str,
) -> Result<(AgentLaunch, CodexProcess), String> {
    if !desktop_codex_installed() {
        return Err("未安装 ChatGPT/Codex 桌面应用".into());
    }
    let executable = codex_executable()?;
    let mut child = Command::new(&executable)
        .args(["app-server", "--listen", "stdio://"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("无法启动 Codex app-server：{error}"))?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "无法连接 Codex 标准输入".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "无法连接 Codex 标准输出".to_string())?;
    let receiver = spawn_stdout_reader(stdout);
    if let Some(stderr) = child.stderr.take() {
        drain_output(stderr);
    }

    let result = (|| {
        rpc_call(
            &mut stdin,
            &receiver,
            1,
            "initialize",
            json!({
                "clientInfo": { "name": "taskboard", "title": "Taskboard", "version": "0.1.0" },
                "capabilities": { "experimentalApi": true }
            }),
        )?;
        send_message(&mut stdin, &json!({ "method": "initialized" }))?;
        let mut next_rpc_id = 2;
        let project_id = codex_project_id(&mut stdin, &receiver, repository, &mut next_rpc_id)?;
        let thread = rpc_call(
            &mut stdin,
            &receiver,
            next_rpc_id,
            "thread/start",
            json!({
                "cwd": repository,
                "approvalPolicy": "never",
                "sandbox": sandbox,
                "serviceName": "taskboard",
                "projectId": project_id
            }),
        )?;
        next_rpc_id += 1;
        let thread_id = thread
            .pointer("/thread/id")
            .and_then(Value::as_str)
            .ok_or_else(|| "Codex thread/start 未返回线程 ID".to_string())?
            .to_owned();
        let assigned_project_id = thread.pointer("/thread/projectId").and_then(Value::as_str);
        if assigned_project_id != Some(project_id.as_str()) {
            return Err(format!(
                "Codex thread/start 未绑定目标项目：期望 {project_id}，实际 {}",
                assigned_project_id.unwrap_or("未分配")
            ));
        }
        rpc_call(
            &mut stdin,
            &receiver,
            next_rpc_id,
            "thread/name/set",
            json!({
                "threadId": thread_id,
                "name": format!("#{} {}", request.reference, request.title.trim())
            }),
        )?;
        next_rpc_id += 1;
        let turn = rpc_call(
            &mut stdin,
            &receiver,
            next_rpc_id,
            "turn/start",
            json!({
                "threadId": thread_id,
                "cwd": repository,
                "input": [{ "type": "text", "text": prompt }]
            }),
        )?;
        let turn_id = turn
            .pointer("/turn/id")
            .and_then(Value::as_str)
            .ok_or_else(|| "Codex turn/start 未返回运行 ID".to_string())?
            .to_owned();
        Ok::<_, String>((thread_id, turn_id))
    })();

    let (thread_id, turn_id) = match result {
        Ok(ids) => ids,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };
    // `turn/start` 已经把首条任务写入目标线程；应立即打开该线程，而不是只打开
    // 一个没有当前任务上下文的通用仓库工作区。
    let warning = open_codex_thread(&thread_id).err();
    let (cancel_sender, cancel_receiver) = mpsc::channel();
    let monitor_turn_id = turn_id.clone();
    let worker = thread::spawn(move || {
        monitor_codex_turn(child, stdin, receiver, cancel_receiver, monitor_turn_id)
    });
    Ok((
        AgentLaunch {
            provider: "codex".into(),
            dispatch_id,
            repository_path: repository.to_string_lossy().into_owned(),
            status: "submitted".into(),
            external_thread_id: Some(thread_id),
            external_turn_id: Some(turn_id),
            warning,
        },
        CodexProcess {
            cancel: cancel_sender,
            worker: Some(worker),
        },
    ))
}

pub fn claude_url(prompt: &str, repository: &Path) -> Result<Url, String> {
    let mut url = Url::parse("claude://code/new")
        .map_err(|error| format!("无法生成 Claude 深链：{error}"))?;
    url.query_pairs_mut()
        .append_pair("q", prompt)
        .append_pair("folder", &repository.to_string_lossy());
    Ok(url)
}

fn launch_claude(
    repository: &Path,
    dispatch_id: String,
    prompt: String,
) -> Result<AgentLaunch, String> {
    if !Path::new("/Applications/Claude.app").is_dir() {
        return Err("未安装 Claude 桌面应用".into());
    }
    let url = claude_url(&prompt, repository)?;
    let output = Command::new("/usr/bin/open")
        .arg(url.as_str())
        .output()
        .map_err(|error| format!("无法打开 Claude 桌面应用：{error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        return Err(if stderr.is_empty() {
            format!("Claude 桌面应用启动失败：{}", output.status)
        } else {
            format!("Claude 桌面应用启动失败：{stderr}")
        });
    }
    Ok(AgentLaunch {
        provider: "claude".into(),
        dispatch_id,
        repository_path: repository.to_string_lossy().into_owned(),
        // 官方深链只预填，不自动提交；用户确认目录并发送后 Claude 才会生成会话 ID。
        status: "opened".into(),
        external_thread_id: None,
        external_turn_id: None,
        warning: None,
    })
}

fn launch_with_codex_sandbox(
    request: &AgentDispatchRequest,
    codex_sandbox: &str,
) -> Result<(AgentLaunch, Option<CodexProcess>), String> {
    let repository = validated_repository(&request.repository_path)?;
    let provider = clean_text(&request.provider, "Agent", 20)?.to_lowercase();
    if !matches!(provider.as_str(), "codex" | "claude") {
        return Err("Agent 只能选择 Codex 或 Claude".into());
    }
    let dispatch_id = dispatch_id(&provider, request.reference);
    let prompt = task_prompt(request, &dispatch_id)?;
    match provider.as_str() {
        "codex" => {
            let (launch, process) =
                launch_codex(request, &repository, dispatch_id, prompt, codex_sandbox)?;
            Ok((launch, Some(process)))
        }
        "claude" => Ok((launch_claude(&repository, dispatch_id, prompt)?, None)),
        _ => unreachable!(),
    }
}

pub fn launch(
    request: &AgentDispatchRequest,
) -> Result<(AgentLaunch, Option<CodexProcess>), String> {
    launch_with_codex_sandbox(request, "workspace-write")
}

#[cfg(test)]
pub fn launch_read_only_smoke(
    request: &AgentDispatchRequest,
) -> Result<(AgentLaunch, Option<CodexProcess>), String> {
    launch_with_codex_sandbox(request, "read-only")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(repository: &Path) -> AgentDispatchRequest {
        AgentDispatchRequest {
            provider: "codex".into(),
            project: "taskboard".into(),
            reference: 33,
            title: "接入桌面 Agent".into(),
            detail: Some("从负责人入口派发任务。".into()),
            accept: Some("记录线程 ID。".into()),
            repository_path: repository.to_string_lossy().into_owned(),
        }
    }

    #[test]
    fn prompt_keeps_task_identity_and_acceptance() {
        let repository = std::env::temp_dir();
        let prompt =
            task_prompt(&request(&repository), "dispatch-33").expect("prompt should build");
        assert!(prompt.contains("派发标识：dispatch-33"));
        assert!(prompt.contains("任务：#33 接入桌面 Agent"));
        assert!(prompt.contains("验收条件：\n记录线程 ID。"));
        assert!(prompt.contains(
            repository
                .canonicalize()
                .unwrap()
                .to_string_lossy()
                .as_ref()
        ));
    }

    #[test]
    fn claude_deep_link_prefills_prompt_and_folder() {
        let repository = std::env::temp_dir();
        let url = claude_url("处理 #33 与空 格", &repository).expect("URL should build");
        assert_eq!(url.scheme(), "claude");
        assert_eq!(url.host_str(), Some("code"));
        assert_eq!(url.path(), "/new");
        let pairs: std::collections::HashMap<_, _> = url.query_pairs().into_owned().collect();
        assert_eq!(pairs.get("q").map(String::as_str), Some("处理 #33 与空 格"));
        assert_eq!(
            pairs.get("folder").map(String::as_str),
            Some(repository.to_string_lossy().as_ref())
        );
    }

    #[test]
    fn codex_deep_link_targets_created_thread() {
        let url =
            codex_thread_url("01a0421d-f35b-7772-99ae-11dc0015b797").expect("URL should build");
        assert_eq!(
            url.as_str(),
            "codex://threads/01a0421d-f35b-7772-99ae-11dc0015b797"
        );
    }

    #[test]
    fn completion_notification_matches_only_target_turn() {
        let matching = json!({
            "method": "turn/completed",
            "params": { "turn": { "id": "turn-33" } }
        });
        let other = json!({
            "method": "turn/completed",
            "params": { "turn": { "id": "turn-34" } }
        });
        assert!(turn_completed(&matching.to_string(), "turn-33"));
        assert!(!turn_completed(&other.to_string(), "turn-33"));
    }

    #[test]
    fn repository_must_exist_and_be_absolute() {
        let mut invalid = request(Path::new("relative"));
        assert!(task_prompt(&invalid, "dispatch")
            .unwrap_err()
            .contains("绝对路径"));
        invalid.repository_path = "/private/tmp/taskboard-missing-agent-directory".into();
        assert!(task_prompt(&invalid, "dispatch")
            .unwrap_err()
            .contains("不存在"));
    }

    #[test]
    fn project_lookup_matches_canonical_repository_root() {
        let repository = std::env::temp_dir().canonicalize().unwrap();
        let projects = json!({
            "data": [
                {
                    "id": "project-other",
                    "roots": [{ "path": "/private/var/empty" }]
                },
                {
                    "id": "project-repo",
                    "roots": [{ "path": repository }]
                }
            ]
        });
        assert_eq!(
            project_id_from_list(&projects, &repository).as_deref(),
            Some("project-repo")
        );
    }
}
