import Darwin
import Foundation
import TaskboardAppCore

enum SelfTestFailure: LocalizedError {
    case assertion(String)
    case commandFailed(Int32, String)

    var errorDescription: String? {
        switch self {
        case let .assertion(message):
            return message
        case let .commandFailed(status, message):
            return "board 自检命令失败（\(status)）：\(message)"
        }
    }
}

func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    guard condition() else {
        throw SelfTestFailure.assertion(message)
    }
}

func run(_ executable: URL, arguments: [String]) throws {
    let process = Process()
    let pipe = Pipe()
    process.executableURL = executable
    process.arguments = arguments
    process.standardOutput = pipe
    process.standardError = pipe
    try process.run()
    process.waitUntilExit()
    let output = String(
        data: pipe.fileHandleForReading.readDataToEndOfFile(),
        encoding: .utf8
    ) ?? ""
    guard process.terminationStatus == 0 else {
        throw SelfTestFailure.commandFailed(process.terminationStatus, output)
    }
}

func runSelfTests() throws {
    let fileManager = FileManager.default
    let root = fileManager.temporaryDirectory
        .appendingPathComponent("TaskboardCoreSelfTest-\(UUID().uuidString)", isDirectory: true)
    try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? fileManager.removeItem(at: root) }

    let fakeExecutable = root.appendingPathComponent("fake-board")
    try Data().write(to: fakeExecutable)
    try fileManager.setAttributes(
        [.posixPermissions: NSNumber(value: 0o755)],
        ofItemAtPath: fakeExecutable.path
    )
    let customDatabase = root.appendingPathComponent("custom.db")
    let configured = try BoardConfiguration.resolve(
        environment: [
            "TASKBOARD_BOARD_EXECUTABLE": fakeExecutable.path,
            "TASKBOARD_DB": customDatabase.path,
        ],
        homeDirectory: root,
        bundleExecutablePath: nil,
        candidatePaths: [],
        cacheDirectory: root.appendingPathComponent("config-cache")
    )
    try expect(
        configured.executableURL == fakeExecutable.standardizedFileURL,
        "环境变量没有覆盖 board 路径"
    )
    try expect(
        configured.databaseURL == customDatabase.standardizedFileURL,
        "TASKBOARD_DB 没有覆盖数据库路径"
    )

    let live = try BoardConfiguration.resolve(
        environment: ProcessInfo.processInfo.environment,
        homeDirectory: fileManager.homeDirectoryForCurrentUser,
        bundleExecutablePath: nil,
        cacheDirectory: root.appendingPathComponent("export-cache")
    )
    let database = root.appendingPathComponent("board.db")
    let integration = BoardConfiguration(
        executableURL: live.executableURL,
        databaseURL: database,
        cacheDirectoryURL: root.appendingPathComponent("export-cache")
    )
    try run(
        integration.executableURL,
        arguments: [
            "--db", database.path,
            "init", "swift-selftest", "--name", "Swift Self Test",
        ]
    )

    let monitor = BoardDatabaseMonitor(databaseURL: database)
    let before = monitor.currentVersion()
    try run(
        integration.executableURL,
        arguments: [
            "--db", database.path,
            "add", "热更新检查", "-p", "swift-selftest",
        ]
    )
    let after = monitor.currentVersion()
    try expect(before != after, "SQLite/WAL 变化没有被监测到")

    let htmlURL = try BoardExporter.exportSynchronously(configuration: integration)
    let html = try String(contentsOf: htmlURL, encoding: .utf8)
    try expect(
        html.hasPrefix("<!doctype html><meta charset=\"utf-8\">"),
        "导出 HTML 缺少 UTF-8 编码声明"
    )
    try expect(html.contains(database.path), "本地 App 导出没有保留数据库路径")
    try expect(html.contains("Swift Self Test"), "导出 HTML 缺少项目名称")
    try expect(html.contains("热更新检查"), "导出 HTML 缺少任务名称")
}

do {
    try runSelfTests()
    print("TaskboardCoreSelfTest passed")
} catch {
    fputs("TaskboardCoreSelfTest failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
