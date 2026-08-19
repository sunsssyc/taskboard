import Foundation

public struct BoardDatabaseVersion: Equatable {
    public struct FileState: Equatable {
        public let path: String
        public let exists: Bool
        public let size: UInt64
        public let modifiedAt: TimeInterval
    }

    public let files: [FileState]
}

public struct BoardDatabaseMonitor {
    public let databaseURL: URL

    public init(databaseURL: URL) {
        self.databaseURL = databaseURL
    }

    public func currentVersion(fileManager: FileManager = .default) -> BoardDatabaseVersion {
        let paths = [
            databaseURL.path,
            databaseURL.path + "-wal",
            databaseURL.path + "-shm",
        ]
        let files = paths.map { path -> BoardDatabaseVersion.FileState in
            guard let attributes = try? fileManager.attributesOfItem(atPath: path) else {
                return .init(path: path, exists: false, size: 0, modifiedAt: 0)
            }
            let size = (attributes[.size] as? NSNumber)?.uint64Value ?? 0
            let modifiedAt = (attributes[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
            return .init(path: path, exists: true, size: size, modifiedAt: modifiedAt)
        }
        return BoardDatabaseVersion(files: files)
    }
}
