// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "PromptPack",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
    ],
    products: [
        .library(
            name: "PromptPack",
            targets: ["PromptPack"]
        ),
    ],
    targets: [
        .target(
            name: "PromptPack",
            path: "Sources/PromptPack"
        ),
    ]
)
