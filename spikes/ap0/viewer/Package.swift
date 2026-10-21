// swift-tools-version: 6.0
// AP0 Viewer-Test: lädt eine .kcad-Datei aus tess_probe.py in OCCTSwiftViewport und misst
// Bildrate, Picking und Offscreen-Rendering. Nur für den Test, kein Produktcode.
import PackageDescription

let package = Package(
    name: "AP0Viewer",
    platforms: [.macOS(.v15)],
    dependencies: [
        // Genau der Stand, dessen Quellcode für den Plan gelesen wurde (21.10.2026)
        .package(
            url: "https://github.com/SecondMouseAU/OCCTSwiftViewport.git",
            revision: "d9984ad46a9195f8eb91897e6cd4cf2a4e553bd0")
    ],
    targets: [
        .executableTarget(
            name: "AP0Viewer",
            dependencies: [.product(name: "OCCTSwiftViewport", package: "OCCTSwiftViewport")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        )
    ]
)
