import XCTest
@testable import KevCADCore

final class AppInfoTests: XCTestCase {
    func testPortsDifferBetweenVariants() {
        XCTAssertTrue([47823, 47824].contains(AppInfo.mcpPort))
    }

    #if os(macOS)
    /// Nur am Mac: Auf dem iPad gibt es keinen Unix-Socket zum Kernel (Verbindung über das Netz, I-2b); der Pfad im
    /// Container der App wäre dort auch zu lang (165 Byte im Simulator).
    func testSocketPathFitsUnixLimit() {
        // sockaddr_un erlaubt auf macOS 104 Byte einschließlich Nullbyte
        XCTAssertLessThan(AppInfo.kernelSocket.path.utf8.count, 104)
    }
    #endif
}
