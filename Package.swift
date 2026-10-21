// swift-tools-version: 6.0
// Schlankes Paket im Wurzelordner, damit andere Projekte (VoiceBridge) KevCADWire per Git-URL einbinden können.
// Es enthält nur den plattformneutralen Teil für den Spiegel aufs iPhone (MIRROR.md) und zeigt per `path:` auf die
// Quellen in app/KevCADCore (keine Kopie). Kev CAD selbst baut weiter über app/KevCADCore/Package.swift.
import PackageDescription

let package = Package(
    name: "KevCADWire",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "KevCADWire", targets: ["KevCADWire"])
    ],
    dependencies: [
        // Gleiche Revision wie in app/KevCADCore/Package.swift (durch AP0 geprüft)
        .package(
            url: "https://github.com/SecondMouseAU/OCCTSwiftViewport.git",
            revision: "d9984ad46a9195f8eb91897e6cd4cf2a4e553bd0")
    ],
    targets: [
        .target(
            name: "KevCADWire",
            dependencies: [.product(name: "OCCTSwiftViewport", package: "OCCTSwiftViewport")],
            path: "app/KevCADCore/Sources/KevCADWire",
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
        .testTarget(
            name: "KevCADWireTests",
            dependencies: ["KevCADWire"],
            path: "app/KevCADCore/Tests/KevCADWireTests",
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
    ]
)
