import Foundation

public enum BoardConfigurationError: LocalizedError, Equatable {
    case executableNotFound([String])

    public var errorDescription: String? {
        switch self {
        case let .executableNotFound(paths):
            return "找不到 board 命令。检查过：\n" + paths.joined(separator: "\n")
        }
    }
}

public struct BoardConfiguration: Equatable {
    public let executableURL: URL
    public let databaseURL: URL
    public let cacheDirectoryURL: URL

    public init(executableURL: URL, databaseURL: URL, cacheDirectoryURL: URL) {
        self.executableURL = executableURL
        self.databaseURL = databaseURL
        self.cacheDirectoryURL = cacheDirectoryURL
    }

    /// 侧边栏视图偏好(排序/置顶)的 sidecar 路径,与 Python 端 view_prefs_path 一致。
    public var viewPrefsURL: URL {
        databaseURL.deletingPathExtension().appendingPathExtension("view.json")
    }

    public static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        bundleExecutablePath: String? = Bundle.main.object(
            forInfoDictionaryKey: "TaskboardBoardExecutable"
        ) as? String,
        candidatePaths: [String]? = nil,
        cacheDirectory: URL? = nil,
        fileManager: FileManager = .default
    ) throws -> BoardConfiguration {
        let defaultCandidates = [
            "/opt/anaconda3/bin/board",
            "/opt/homebrew/bin/board",
            "/usr/local/bin/board",
            homeDirectory.appendingPathComponent(".local/bin/board").path,
        ]
        let configured = [
            environment["TASKBOARD_BOARD_EXECUTABLE"],
            bundleExecutablePath,
        ].compactMap { value -> String? in
            guard let value, !value.isEmpty else { return nil }
            return value
        }
        let candidates = configured + (candidatePaths ?? defaultCandidates)
        guard let executablePath = candidates.first(where: fileManager.isExecutableFile) else {
            throw BoardConfigurationError.executableNotFound(candidates)
        }

        let databaseURL: URL
        if let explicitDatabase = environment["TASKBOARD_DB"], !explicitDatabase.isEmpty {
            databaseURL = URL(fileURLWithPath: explicitDatabase).standardizedFileURL
        } else {
            let taskboardHome: URL
            if let configuredHome = environment["TASKBOARD_HOME"], !configuredHome.isEmpty {
                taskboardHome = URL(fileURLWithPath: configuredHome).standardizedFileURL
            } else {
                taskboardHome = homeDirectory.appendingPathComponent(".taskboard", isDirectory: true)
            }
            databaseURL = taskboardHome.appendingPathComponent("board.db")
        }

        let resolvedCache = cacheDirectory
            ?? fileManager.urls(for: .cachesDirectory, in: .userDomainMask).first?
                .appendingPathComponent("TaskboardMenuBar", isDirectory: true)
            ?? homeDirectory.appendingPathComponent("Library/Caches/TaskboardMenuBar", isDirectory: true)

        return BoardConfiguration(
            executableURL: URL(fileURLWithPath: executablePath).standardizedFileURL,
            databaseURL: databaseURL,
            cacheDirectoryURL: resolvedCache
        )
    }
}
