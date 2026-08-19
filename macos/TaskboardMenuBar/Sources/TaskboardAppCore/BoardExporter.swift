import Foundation

public enum BoardExportError: LocalizedError {
    case failed(status: Int32, message: String)
    case outputMissing(URL)

    public var errorDescription: String? {
        switch self {
        case let .failed(status, message):
            return "board export 失败（退出码 \(status)）：\n\(message)"
        case let .outputMissing(url):
            return "board export 未生成文件：\(url.path)"
        }
    }
}

public final class BoardExporter {
    public let configuration: BoardConfiguration
    private let queue = DispatchQueue(label: "com.coinex.taskboard.export", qos: .userInitiated)

    public init(configuration: BoardConfiguration) {
        self.configuration = configuration
    }

    public func export(completion: @escaping (Result<URL, Error>) -> Void) {
        queue.async { [configuration] in
            let result = Result { try Self.exportSynchronously(configuration: configuration) }
            DispatchQueue.main.async {
                completion(result)
            }
        }
    }

    public static func exportSynchronously(
        configuration: BoardConfiguration,
        fileManager: FileManager = .default
    ) throws -> URL {
        try fileManager.createDirectory(
            at: configuration.cacheDirectoryURL,
            withIntermediateDirectories: true
        )
        let outputURL = configuration.cacheDirectoryURL.appendingPathComponent("board.html")
        let temporaryURL = configuration.cacheDirectoryURL.appendingPathComponent("board.next.html")
        try? fileManager.removeItem(at: temporaryURL)

        let process = Process()
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.executableURL = configuration.executableURL
        process.arguments = [
            "--db", configuration.databaseURL.path,
            "export", "--show-paths", "--out", temporaryURL.path,
        ]
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        try process.run()
        process.waitUntilExit()

        let standardOutput = String(
            data: outputPipe.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        ) ?? ""
        let standardError = String(
            data: errorPipe.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        ) ?? ""
        guard process.terminationStatus == 0 else {
            let message = [standardError, standardOutput]
                .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
                .joined(separator: "\n")
            throw BoardExportError.failed(status: process.terminationStatus, message: message)
        }
        guard fileManager.fileExists(atPath: temporaryURL.path) else {
            throw BoardExportError.outputMissing(temporaryURL)
        }

        try? fileManager.removeItem(at: outputURL)
        try fileManager.moveItem(at: temporaryURL, to: outputURL)
        return outputURL
    }
}
