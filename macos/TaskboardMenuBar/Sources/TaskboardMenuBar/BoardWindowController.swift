import AppKit
import TaskboardAppCore
import WebKit

/// 接收页面里拖动排序/置顶的偏好变更,落盘到库旁的 *.view.json。
/// 独立小对象持有回调,避免 userContentController 与窗口控制器互相持有。
private final class ViewPrefsMessageHandler: NSObject, WKScriptMessageHandler {
    private let prefsURL: URL

    init(prefsURL: URL) {
        self.prefsURL = prefsURL
    }

    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        var prefs: [String: [String]] = [:]
        for key in ["order", "pinned"] {
            if let list = body[key] as? [String] {
                prefs[key] = list.map { String($0.prefix(200)) }
            }
        }
        guard prefs.count == 2 else { return }
        guard let data = try? JSONSerialization.data(
            withJSONObject: prefs, options: [.prettyPrinted, .sortedKeys]
        ) else { return }
        try? data.write(to: prefsURL, options: .atomic)
    }
}

/// 接收页面里状态 chip 的变更请求,经 board CLI 写库。
/// 成功后库版本号变化,BoardDatabaseMonitor 会在 1 秒内触发重新导出,页面自动刷新。
private final class StatusMessageHandler: NSObject, WKScriptMessageHandler {
    private static let commands = ["todo": "todo", "active": "start", "waiting": "wait", "done": "done"]
    private let executableURL: URL
    private let databaseURL: URL

    init(executableURL: URL, databaseURL: URL) {
        self.executableURL = executableURL
        self.databaseURL = databaseURL
    }

    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let project = body["project"] as? String, !project.isEmpty,
              let ref = body["ref"] as? Int,
              let status = body["status"] as? String,
              let command = Self.commands[status] else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            let errorPipe = Pipe()
            process.executableURL = self.executableURL
            process.arguments = ["--db", self.databaseURL.path, command, String(ref), "-p", project]
            process.standardError = errorPipe
            do {
                try process.run()
            } catch {
                self.report("无法启动 board:\n\(error.localizedDescription)")
                return
            }
            process.waitUntilExit()
            guard process.terminationStatus == 0 else {
                let detail = String(
                    data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8
                ) ?? ""
                self.report("修改状态失败(退出码 \(process.terminationStatus)):\n\(detail)")
                return
            }
        }
    }

    private func report(_ message: String) {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.messageText = message
            alert.alertStyle = .warning
            alert.runModal()
        }
    }
}

final class BoardWindowController: NSWindowController, NSWindowDelegate, WKNavigationDelegate {
    private let configuration: BoardConfiguration
    private let exporter: BoardExporter
    private let monitor: BoardDatabaseMonitor
    private let webView: WKWebView
    private var timer: Timer?
    private var lastVersion: BoardDatabaseVersion?
    private var isExporting = false
    private var pendingRefresh = false

    init(configuration: BoardConfiguration) {
        self.configuration = configuration
        exporter = BoardExporter(configuration: configuration)
        monitor = BoardDatabaseMonitor(databaseURL: configuration.databaseURL)
        let webConfiguration = WKWebViewConfiguration()
        webConfiguration.userContentController.add(
            ViewPrefsMessageHandler(prefsURL: configuration.viewPrefsURL), name: "boardView"
        )
        webConfiguration.userContentController.add(
            StatusMessageHandler(
                executableURL: configuration.executableURL,
                databaseURL: configuration.databaseURL
            ), name: "boardStatus"
        )
        webView = WKWebView(frame: .zero, configuration: webConfiguration)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1180, height: 780),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "任务看板"
        window.minSize = NSSize(width: 760, height: 520)
        window.isReleasedWhenClosed = false
        window.center()
        window.contentView = webView

        super.init(window: window)
        window.delegate = self
        webView.navigationDelegate = self
        webView.uiDelegate = self
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func showBoard() {
        guard let window else { return }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startMonitoring()
        refresh(force: webView.url == nil)
    }

    func reloadBoard() {
        startMonitoring()
        refresh(force: true)
    }

    private func startMonitoring() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.refresh(force: false)
        }
        if let timer {
            RunLoop.main.add(timer, forMode: .common)
        }
    }

    private func stopMonitoring() {
        timer?.invalidate()
        timer = nil
    }

    private func refresh(force: Bool) {
        let version = monitor.currentVersion()
        guard force || version != lastVersion else { return }
        guard !isExporting else {
            pendingRefresh = true
            return
        }

        isExporting = true
        pendingRefresh = false
        if webView.url == nil {
            showMessage(title: "正在载入任务看板…", detail: configuration.databaseURL.path)
        }

        exporter.export { [weak self] result in
            guard let self else { return }
            self.isExporting = false
            switch result {
            case let .success(url):
                // board export 自身也会短暂打开 SQLite/WAL。记录导出完成后的版本，
                // 避免把自己的读取误判成下一轮外部修改而形成刷新循环。
                self.lastVersion = self.monitor.currentVersion()
                do {
                    let data = try Data(contentsOf: url)
                    self.webView.load(
                        data,
                        mimeType: "text/html",
                        characterEncodingName: "utf-8",
                        baseURL: self.configuration.cacheDirectoryURL
                    )
                } catch {
                    self.lastVersion = nil
                    self.showMessage(title: "无法读取任务看板", detail: error.localizedDescription)
                }
            case let .failure(error):
                self.lastVersion = nil
                self.showMessage(title: "无法载入任务看板", detail: error.localizedDescription)
            }

            if self.pendingRefresh {
                self.refresh(force: true)
            }
        }
    }

    private func showMessage(title: String, detail: String) {
        let html = """
        <!doctype html>
        <meta charset="utf-8">
        <style>
          :root { color-scheme: light dark; font-family: -apple-system, sans-serif; }
          body { display:grid; place-items:center; min-height:100vh; margin:0; }
          main { max-width:720px; padding:32px; text-align:center; }
          h1 { font-size:22px; margin:0 0 12px; }
          p { opacity:.65; line-height:1.6; overflow-wrap:anywhere; }
        </style>
        <main><h1>\(htmlEscaped(title))</h1><p>\(htmlEscaped(detail))</p></main>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    private func htmlEscaped(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }

    func windowWillClose(_ notification: Notification) {
        stopMonitoring()
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        if navigationAction.navigationType == .linkActivated,
           let url = navigationAction.request.url,
           !url.isFileURL {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
}

/// WKWebView 默认不实现 JS alert/confirm 面板(confirm 会直接返回 false),
/// 状态改为“已完成”前的确认框依赖这里。
extension BoardWindowController: WKUIDelegate {
    func webView(_ webView: WKWebView,
                 runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView,
                 runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "确认")
        alert.addButton(withTitle: "取消")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }
}
