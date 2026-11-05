// swift-tools-version: 6.0
// KevCADCore: alles an Kev CAD, was ohne Fenster laufen und getestet werden kann
// (Protokoll zum Kernel, Szene, Referenzen, Projekte). Die App-Oberfläche liegt in app/Sources/KevCAD.
//
// KevCADWire: der plattformneutrale Teil (macOS und iOS) für den Spiegel aufs iPhone (MIRROR.md): Rahmen, Teilgeometrie,
// Teilung in Viewport-Körper, Netzformat kcad-mesh-1, Spiegel-Nachrichten und Empfängerzustand. Ohne AppKit, ohne
// Prozesse, ohne Kernel; VoiceBridge bindet nur dieses Produkt ein. KevCADCore hängt davon ab und reicht es weiter.
import PackageDescription

let package = Package(
    name: "KevCADCore",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "KevCADCore", targets: ["KevCADCore"]),
        .library(name: "KevCADWire", targets: ["KevCADWire"]),
    ],
    dependencies: [
        // Lokale Kopie des durch AP0 geprüften Stands d9984ad (PLAN-MVP.md Abschnitt 12) mit kleinen Änderungen für
        // den Viewer V2 (Darstellung zur Laufzeit, Umgebungsverdeckung, Bildzeiten): app/Packages/OCCTSwiftViewport,
        // Liste der Änderungen dort in KEVCAD-AENDERUNGEN.md
        .package(path: "../Packages/OCCTSwiftViewport")
    ],
    targets: [
        .target(
            name: "KevCADWire",
            dependencies: [.product(name: "OCCTSwiftViewport", package: "OCCTSwiftViewport")],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
        .target(
            name: "KevCADCore",
            dependencies: ["KevCADWire", .product(name: "OCCTSwiftViewport", package: "OCCTSwiftViewport")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "KevCADCoreTests",
            dependencies: ["KevCADCore"],
            resources: [.copy("Fixtures")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "KevCADWireTests",
            dependencies: ["KevCADWire"],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
    ]
)
