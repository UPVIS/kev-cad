// swift-tools-version: 6.0
// KevCADCore: alles an Kev CAD, was ohne Fenster laufen und getestet werden kann
// (Protokoll zum Kernel, Szene, Referenzen, Projekte). Die App-Oberfläche liegt in app/Sources/KevCAD.
import PackageDescription

let package = Package(
    name: "KevCADCore",
    platforms: [.macOS(.v15)],
    products: [.library(name: "KevCADCore", targets: ["KevCADCore"])],
    dependencies: [
        // Durch AP0 geprüfter Stand (21.10.2026), siehe PLAN-MVP.md Abschnitt 12
        .package(
            url: "https://github.com/SecondMouseAU/OCCTSwiftViewport.git",
            revision: "d9984ad46a9195f8eb91897e6cd4cf2a4e553bd0")
    ],
    targets: [
        .target(
            name: "KevCADCore",
            dependencies: [.product(name: "OCCTSwiftViewport", package: "OCCTSwiftViewport")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "KevCADCoreTests",
            dependencies: ["KevCADCore"],
            resources: [.copy("Fixtures")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
