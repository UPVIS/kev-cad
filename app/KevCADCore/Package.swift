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
        // Durch AP0 geprüfter Stand (21.10.2026), siehe PLAN-MVP.md Abschnitt 12
        .package(
            url: "https://github.com/SecondMouseAU/OCCTSwiftViewport.git",
            revision: "d9984ad46a9195f8eb91897e6cd4cf2a4e553bd0")
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
