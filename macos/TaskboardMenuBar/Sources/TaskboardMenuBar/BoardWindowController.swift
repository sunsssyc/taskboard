import AppKit
import TaskboardAppCore
import WebKit

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
        webView = WKWebView(frame: .zero)

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
