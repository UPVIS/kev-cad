import XCTest
@testable import KevCADCore

final class AppInfoTests: XCTestCase {
    func testPortsDifferBetweenVariants() {
        XCTAssertTrue([47823, 47824].contains(AppInfo.mcpPort))
    }

    func testSocketPathFitsUnixLimit() {
        // sockaddr_un erlaubt auf macOS 104 Byte einschließlich Nullbyte
        XCTAssertLessThan(AppInfo.kernelSocket.path.utf8.count, 104)
    }
}
