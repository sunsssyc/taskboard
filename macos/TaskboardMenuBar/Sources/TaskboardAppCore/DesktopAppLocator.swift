import Foundation

/// 定位 Tauri 桌面看板 App(apps/desktop),供菜单栏壳唤起主窗口。
public struct DesktopAppLocator {
    /// 与 apps/desktop/src-tauri/tauri.conf.json 的 identifier 保持一致。
    public static let bundleIdentifier = "com.sunsssyc.taskboard"

    public static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        bundleAppPath: String? = Bundle.main.object(
            forInfoDictionaryKey: "TaskboardDesktopApp"
        ) as? String,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        candidatePaths: [String]? = nil
    ) -> URL? {
        let defaultCandidates = [
            "/Applications/Taskboard Desktop.app",
            homeDirectory.appendingPathComponent("Applications/Taskboard Desktop.app").path,
        ]
        let configured = [
            environment["TASKBOARD_DESKTOP_APP"],
            bundleAppPath,
        ].compactMap { value -> String? in
            guard let value, !value.isEmpty else { return nil }
            return value
        }
        for path in configured + (candidatePaths ?? defaultCandidates) {
            let url = URL(fileURLWithPath: path).standardizedFileURL
            if identifier(ofAppAt: url) == bundleIdentifier {
                return url
            }
        }
        return nil
    }

    /// 读取候选 .app 的 CFBundleIdentifier;壳的历史安装同样叫 Taskboard.app,靠它避免唤起自身。
    public static func identifier(ofAppAt url: URL) -> String? {
        let plistURL = url.appendingPathComponent("Contents/Info.plist")
        guard let data = try? Data(contentsOf: plistURL),
              let plist = try? PropertyListSerialization.propertyList(
                  from: data,
                  options: [],
                  format: nil
              ),
              let dictionary = plist as? [String: Any]
        else { return nil }
        return dictionary["CFBundleIdentifier"] as? String
    }
}
