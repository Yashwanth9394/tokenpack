// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "TokenPack",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
    ],
    products: [
        .library(
            name: "TokenPack",
            targets: ["TokenPack"]
        ),
    ],
    targets: [
        .target(
            name: "TokenPack",
            path: "Sources/TokenPack"
        ),
    ]
)
