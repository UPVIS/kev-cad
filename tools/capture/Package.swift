// swift-tools-version: 6.0
// kevcad-capture: aus einem Handyvideo mit Apple Object Capture eine Referenz für Kev CAD rekonstruieren
// (Bilder auswählen, PhotogrammetrySession, Boden abschneiden, ausrichten, Maßstab, Bericht).
// Keine Abhängigkeiten außer Apple-Frameworks. Siehe README.md.
import PackageDescription

let package = Package(
    name: "kevcad-capture",
    platforms: [.macOS(.v15)],
    products: [.executable(name: "kevcad-capture", targets: ["kevcad-capture"])],
    targets: [
        .target(
            name: "CaptureCore",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .executableTarget(
            name: "kevcad-capture",
            dependencies: ["CaptureCore"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "CaptureCoreTests",
            dependencies: ["CaptureCore"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
