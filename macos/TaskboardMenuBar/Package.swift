// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "TaskboardMenuBar",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "TaskboardMenuBar", targets: ["TaskboardMenuBar"]),
        .executable(name: "TaskboardCoreSelfTest", targets: ["TaskboardCoreSelfTest"]),
    ],
    targets: [
        .target(
            name: "TaskboardAppCore",
            path: "Sources/TaskboardAppCore"
        ),
        .executableTarget(
            name: "TaskboardMenuBar",
            dependencies: ["TaskboardAppCore"],
            path: "Sources/TaskboardMenuBar",
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("ServiceManagement"),
                .linkedFramework("WebKit"),
            ]
        ),
        .executableTarget(
            name: "TaskboardCoreSelfTest",
            dependencies: ["TaskboardAppCore"],
            path: "SelfTests/TaskboardCoreSelfTest"
        ),
    ],
    swiftLanguageVersions: [.v5]
)
