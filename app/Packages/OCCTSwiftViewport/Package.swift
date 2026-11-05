// swift-tools-version: 6.0
// Lokale Kopie von OCCTSwiftViewport für Kev CAD (Herkunft und Änderungen in KEVCAD-AENDERUNGEN.md).
// Gegenüber dem Original nur die Bibliothek, ohne Tests und Beispiele.
import PackageDescription

let package = Package(
    name: "OCCTSwiftViewport",
    platforms: [
        .iOS(.v18),
        .macOS(.v15),
        .visionOS(.v1),
    ],
    products: [
        .library(
            name: "OCCTSwiftViewport",
            targets: ["OCCTSwiftViewport"]
        )
    ],
    targets: [
        .target(
            name: "OCCTSwiftViewport",
            path: "Sources/OCCTSwiftViewport",
            resources: [
                .process("Renderer/Shaders.metal")
            ],
            swiftSettings: [
                .swiftLanguageMode(.v6)
            ]
        )
    ]
)
