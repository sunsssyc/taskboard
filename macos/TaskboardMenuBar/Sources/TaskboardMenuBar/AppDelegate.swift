import AppKit
import ServiceManagement
import TaskboardAppCore

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var loginAtLaunchItem: NSMenuItem?
    private var windowController: BoardWindowController?
    private var configuration: BoardConfiguration?
    private var configurationError: Error?

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            let configuration = try BoardConfiguration.resolve()
            self.configuration = configuration
            windowController = BoardWindowController(configuration: configuration)
        } catch {
            configurationError = error
        }
        installStatusItem()
        // 桌面版可用时壳只做菜单栏薄入口,登录启动不再自动弹窗。
        if !desktopAppIsAvailable() {
            openBoard()
        }
    }

    func applicationShouldHandleReopen(
        _ sender: NSApplication,
        hasVisibleWindows flag: Bool
    ) -> Bool {
        if !flag {
            openBoard()
        }
        return true
    }

    private func installStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            let symbolName = configurationError == nil ? "checklist" : "exclamationmark.triangle"
            button.image = NSImage(
                systemSymbolName: symbolName,
                accessibilityDescription: "任务看板"
            )
            button.toolTip = configurationError == nil ? "任务看板" : "任务看板配置异常"
        }
        item.menu = makeMenu()
        statusItem = item
    }

    private func makeMenu() -> NSMenu {
        let menu = NSMenu()

        let openItem = NSMenuItem(
            title: "打开任务看板",
            action: #selector(openBoard),
            keyEquivalent: "o"
        )
        openItem.target = self
        openItem.isEnabled = configuration != nil
        menu.addItem(openItem)

        let reloadItem = NSMenuItem(
            title: "重新加载",
            action: #selector(reloadBoard),
            keyEquivalent: "r"
        )
        reloadItem.target = self
        reloadItem.isEnabled = configuration != nil
        menu.addItem(reloadItem)

        if configurationError != nil {
            let errorItem = NSMenuItem(
                title: "查看配置错误…",
                action: #selector(showConfigurationError),
                keyEquivalent: ""
            )
            errorItem.target = self
            menu.addItem(errorItem)
        }

        menu.addItem(.separator())

        let databaseItem = NSMenuItem(
            title: "在 Finder 中显示数据库",
            action: #selector(revealDatabase),
            keyEquivalent: ""
        )
        databaseItem.target = self
        databaseItem.isEnabled = configuration != nil
        menu.addItem(databaseItem)

        let loginItem = NSMenuItem(
            title: "登录时启动",
            action: #selector(toggleLaunchAtLogin),
            keyEquivalent: ""
        )
        loginItem.target = self
        menu.addItem(loginItem)
        loginAtLaunchItem = loginItem
        updateLaunchAtLoginState()

        menu.addItem(.separator())

        let quitItem = NSMenuItem(
            title: "退出任务看板",
            action: #selector(quit),
            keyEquivalent: "q"
        )
        quitItem.target = self
        menu.addItem(quitItem)
        return menu
    }

    @objc private func openBoard() {
        if activateDesktopApp() { return }
        windowController?.showBoard()
    }

    private func runningDesktopApp() -> NSRunningApplication? {
        NSRunningApplication.runningApplications(
            withBundleIdentifier: DesktopAppLocator.bundleIdentifier
        ).first
    }

    private func desktopAppIsAvailable() -> Bool {
        runningDesktopApp() != nil || DesktopAppLocator.resolve() != nil
    }

    /// 优先唤起 Tauri 桌面看板;返回 false 表示桌面版不可用,调用方回退原生窗口。
    private func activateDesktopApp() -> Bool {
        if let running = runningDesktopApp() {
            if #available(macOS 14.0, *) {
                running.activate()
            } else {
                running.activate(options: [.activateIgnoringOtherApps])
            }
            return true
        }
        guard let appURL = DesktopAppLocator.resolve() else { return false }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        NSWorkspace.shared.openApplication(at: appURL, configuration: configuration) {
            [weak self] _, error in
            guard error != nil else { return }
            DispatchQueue.main.async {
                self?.windowController?.showBoard()
            }
        }
        return true
    }

    @objc private func reloadBoard() {
        windowController?.reloadBoard()
    }

    @objc private func revealDatabase() {
        guard let configuration else { return }
        NSWorkspace.shared.activateFileViewerSelecting([configuration.databaseURL])
    }

    @objc private func showConfigurationError() {
        guard let configurationError else { return }
        presentError(title: "任务看板配置异常", error: configurationError)
    }

    @objc private func toggleLaunchAtLogin() {
        let service = SMAppService.mainApp
        do {
            switch service.status {
            case .enabled:
                try service.unregister()
            case .requiresApproval:
                SMAppService.openSystemSettingsLoginItems()
            default:
                try service.register()
            }
        } catch {
            presentError(title: "无法修改登录启动设置", error: error)
        }
        updateLaunchAtLoginState()
    }

    private func updateLaunchAtLoginState() {
        guard let loginAtLaunchItem else { return }
        switch SMAppService.mainApp.status {
        case .enabled:
            loginAtLaunchItem.state = .on
            loginAtLaunchItem.toolTip = nil
        case .requiresApproval:
            loginAtLaunchItem.state = .mixed
            loginAtLaunchItem.toolTip = "需要在系统设置的“登录项”中批准"
        default:
            loginAtLaunchItem.state = .off
            loginAtLaunchItem.toolTip = nil
        }
    }

    private func presentError(title: String, error: Error) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = error.localizedDescription
        alert.addButton(withTitle: "好")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}
