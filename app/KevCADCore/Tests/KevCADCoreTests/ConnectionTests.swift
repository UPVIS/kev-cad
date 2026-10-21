import Darwin
import Foundation
import XCTest

@testable import KevCADCore

/// Kleiner Unix-Socket-Server für Tests (spielt den Kernel).
final class TestSocketServer: @unchecked Sendable {
    let path: String
    private var listenFD: Int32 = -1
    private var clientFD: Int32 = -1
    private let lock = NSLock()
    private var received: [Frame] = []
    private let reader = FrameReader()

    init() {
        path = "/tmp/kevcad-test-\(getpid())-\(Int.random(in: 1000...9999)).sock"
    }

    deinit { stop() }

    func listen() throws {
        unlink(path)
        listenFD = socket(AF_UNIX, SOCK_STREAM, 0)
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        withUnsafeMutableBytes(of: &addr.sun_path) { raw in
            raw.copyBytes(from: bytes)
            raw[bytes.count] = 0
        }
        addr.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let rc = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(listenFD, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
        }
        guard rc == 0, Darwin.listen(listenFD, 1) == 0 else {
            throw NSError(domain: "TestSocketServer", code: Int(errno))
        }
    }

    /// Wartet auf die App und schickt dann `data` in kleinen Stücken.
    func acceptAndSend(_ data: Data, chunk: Int = 333) {
        let fd = accept(listenFD, nil, nil)
        lock.lock()
        clientFD = fd
        lock.unlock()
        var on: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        var i = 0
        while i < data.count {
            let part = data.subdata(in: i..<min(i + chunk, data.count))
            part.withUnsafeBytes { _ = write(fd, $0.baseAddress, $0.count) }
            i += chunk
        }
    }

    /// Liest, was die App geschickt hat (blockiert bis `timeout`).
    func readFrames(count: Int, timeout: TimeInterval) -> [Frame] {
        let deadline = Date().addingTimeInterval(timeout)
        var buf = [UInt8](repeating: 0, count: 65536)
        while Date() < deadline {
            lock.lock()
            let fd = clientFD
            let have = received.count
            lock.unlock()
            if have >= count { break }
            guard fd >= 0 else {
                usleep(10_000)
                continue
            }
            var p = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
            if poll(&p, 1, 50) > 0 {
                let n = buf.withUnsafeMutableBytes { read(fd, $0.baseAddress, $0.count) }
                if n <= 0 { break }
                if let frames = try? reader.feed(Data(buf[0..<n])) {
                    lock.lock()
                    received += frames
                    lock.unlock()
                }
            }
        }
        lock.lock()
        defer { lock.unlock() }
        return received
    }

    func closeClient() {
        lock.lock()
        if clientFD >= 0 { close(clientFD) }
        clientFD = -1
        lock.unlock()
    }

    func stop() {
        closeClient()
        if listenFD >= 0 { close(listenFD) }
        listenFD = -1
        unlink(path)
    }
}

@MainActor
final class ConnectionTests: XCTestCase {
    /// Die App verbindet sich, bevor der Kernel lauscht (Wiederholversuche), liest den ganzen Testdatenstrom in
    /// Reihenfolge, schickt selbst einen Rahmen und merkt, wenn der Kernel auflegt.
    func testConnectRetryStreamAndDisconnect() throws {
        let server = TestSocketServer()
        let conn = KernelConnection()
        conn.retryInterval = 0.05
        var events: [IncomingEvent] = []
        let connected = expectation(description: "verbunden")
        let total = try XCTUnwrap(Fixtures.expected()["frames"]?.arrayValue).count
        let allMessages = expectation(description: "\(total) Nachrichten")
        let disconnected = expectation(description: "getrennt")
        // nach dem Auflegen verbindet sich die App von selbst wieder
        connected.assertForOverFulfill = false
        disconnected.assertForOverFulfill = false
        allMessages.assertForOverFulfill = false
        var messageCount = 0
        conn.onEvents = { batch in
            for e in batch {
                events.append(e)
                switch e {
                case .connected: connected.fulfill()
                case .disconnected: disconnected.fulfill()
                case .message, .part:
                    messageCount += 1
                    if messageCount == total { allMessages.fulfill() }
                case .invalid(let t, let r): XCTFail("ungültig \(t): \(r)")
                }
            }
        }
        conn.open(path: server.path)
        // Erst nach einer Weile lauschen
        Thread.sleep(forTimeInterval: 0.3)
        try server.listen()
        let stream = try Fixtures.data("stream.bin")
        DispatchQueue.global().async { server.acceptAndSend(stream) }
        wait(for: [connected, allMessages], timeout: 10)

        let kinds = events.compactMap { e -> String? in
            switch e {
            case .message(let m): return m.typeName
            case .part: return "PART_UPSERT"
            default: return nil
            }
        }
        let expected = try XCTUnwrap(Fixtures.expected()["frames"]?.arrayValue).compactMap { $0["type"]?.stringValue }
        XCTAssertEqual(kinds, expected)
        // Teile kommen schon als vorbereitete Körper-Stücke an
        let parts = events.compactMap { e -> PartRecord? in if case .part(let p) = e { return p } else { return nil } }
        XCTAssertEqual(parts.map(\.name), ["Grundplatte", "Halter/Bolzen", "Gestell/Bein vorn links"])
        XCTAssertEqual(parts.last?.header.stock?.id, "vierkantrohr-en10219-40x40x3")
        XCTAssertEqual(parts.first?.chunks.count, 1)

        var hello = HelloAppMessage(appVersion: "0.1", bundleID: "test")
        hello.seq = 1
        conn.send(try hello.frame().encoded)
        let got = server.readFrames(count: 1, timeout: 5)
        XCTAssertEqual(got.count, 1)
        let env = try JSONDecoder().decode(MessageEnvelope.self, from: got[0].header)
        XCTAssertEqual(env.type, "HELLO_APP")

        server.closeClient()
        wait(for: [disconnected], timeout: 5)
        conn.close()
        server.stop()
    }
}
