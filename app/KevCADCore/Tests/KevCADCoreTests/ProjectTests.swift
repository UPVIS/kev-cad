import XCTest
@testable import KevCADCore

/// Projektlogik ohne Oberfläche: Projektordner prüfen, Namen ohne Kollision, „Zuletzt geöffnet“.
final class ProjectLocatorTests: XCTestCase {
    private var temp: URL!

    override func setUpWithError() throws {
        temp = FileManager.default.temporaryDirectory
            .appendingPathComponent("kevcad-project-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temp)
    }

    private func makeProject(_ name: String, withModel: Bool = true) throws -> URL {
        let folder = temp.appendingPathComponent(name, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        if withModel {
            try "from build123d import *\n".write(
                to: folder.appendingPathComponent("model.py"), atomically: true, encoding: .utf8)
        }
        return folder
    }

    func testFolderWithModelIsProject() throws {
        let folder = try makeProject("Wandhalter")
        XCTAssertNil(ProjectLocator.check(folder))
        XCTAssertTrue(ProjectLocator.isProject(folder))
    }

    func testFolderWithoutModelIsRejected() throws {
        let folder = try makeProject("Leer", withModel: false)
        XCTAssertEqual(ProjectLocator.check(folder), .missingModel(folder.standardizedFileURL.path))
        XCTAssertTrue(ProjectLocator.Problem.missingModel(folder.path).errorDescription!.contains("model.py"))
    }

    func testMissingFolderAndPlainFile() throws {
        let missing = temp.appendingPathComponent("Gibt es nicht")
        XCTAssertEqual(ProjectLocator.check(missing), .notFound(missing.standardizedFileURL.path))
        let file = temp.appendingPathComponent("notiz.txt")
        try "x".write(to: file, atomically: true, encoding: .utf8)
        XCTAssertEqual(ProjectLocator.check(file), .notADirectory(file.standardizedFileURL.path))
    }

    func testModelFileSelectsItsFolder() throws {
        let folder = try makeProject("Regal")
        let model = folder.appendingPathComponent("model.py")
        XCTAssertEqual(ProjectLocator.projectFolder(for: model).path, folder.standardizedFileURL.path)
        XCTAssertNil(ProjectLocator.check(model))
        let info = ProjectLocator.projectInfo(for: model)
        XCTAssertEqual(info.name, "Regal")
        XCTAssertEqual(info.modelFile.lastPathComponent, "model.py")
    }

    func testModelPyAsDirectoryIsNotAProject() throws {
        let folder = try makeProject("Seltsam", withModel: false)
        try FileManager.default.createDirectory(
            at: folder.appendingPathComponent("model.py"), withIntermediateDirectories: true)
        XCTAssertEqual(ProjectLocator.check(folder), .missingModel(folder.standardizedFileURL.path))
    }

    func testUniqueFolderAvoidsCollisions() throws {
        XCTAssertEqual(ProjectLocator.uniqueFolder(named: "Wandhalter", in: temp).lastPathComponent, "Wandhalter")
        _ = try makeProject("Wandhalter")
        XCTAssertEqual(ProjectLocator.uniqueFolder(named: "Wandhalter", in: temp).lastPathComponent, "Wandhalter 2")
        _ = try makeProject("Wandhalter 2", withModel: false)
        XCTAssertEqual(ProjectLocator.uniqueFolder(named: "Wandhalter", in: temp).lastPathComponent, "Wandhalter 3")
        // APFS unterscheidet Groß- und Kleinschreibung nicht: "wandhalter" kollidiert ebenfalls.
        XCTAssertEqual(ProjectLocator.uniqueFolder(named: "wandhalter", in: temp).lastPathComponent, "wandhalter 3")
    }

    func testUniqueFolderWithInjectedCheck() {
        let taken: Set<String> = ["/p/Neues Projekt", "/p/Neues Projekt 2"]
        let url = ProjectLocator.uniqueFolder(named: "  ", in: URL(fileURLWithPath: "/p")) { taken.contains($0.path) }
        XCTAssertEqual(url.path, "/p/Neues Projekt 3")
    }

    func testSanitizedName() {
        XCTAssertEqual(ProjectLocator.sanitizedName("  Wandhalter  "), "Wandhalter")
        XCTAssertEqual(ProjectLocator.sanitizedName("Halter/Lasche: v2"), "Halter-Lasche- v2")
        XCTAssertEqual(ProjectLocator.sanitizedName("..versteckt"), "versteckt")
        XCTAssertEqual(ProjectLocator.sanitizedName("Rohr   Ø42,4\n"), "Rohr Ø42,4")
        XCTAssertEqual(ProjectLocator.sanitizedName(""), "Neues Projekt")
        XCTAssertEqual(ProjectLocator.sanitizedName("..."), "Neues Projekt")
        XCTAssertEqual(ProjectLocator.sanitizedName(String(repeating: "a", count: 200)).count, 80)
    }
}

@MainActor
final class RecentProjectsTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suite: String!

    // Eine feste Suite statt einer je Test, damit keine Reste in ~/Library/Preferences liegen bleiben.
    override func setUp() async throws {
        suite = "de.upvis.kevcad.tests.recent"
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
    }

    override func tearDown() async throws {
        defaults.removePersistentDomain(forName: suite)
        let file = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Preferences/\(suite!).plist")
        try? FileManager.default.removeItem(at: file)
    }

    private func url(_ path: String) -> URL { URL(fileURLWithPath: path, isDirectory: true) }

    func testNewestFirstAndPersisted() {
        let recent = RecentProjects(defaults: defaults, exists: { _ in true })
        recent.note(url("/p/A"), date: Date(timeIntervalSince1970: 100))
        recent.note(url("/p/B"), date: Date(timeIntervalSince1970: 200))
        XCTAssertEqual(recent.items.map(\.name), ["B", "A"])

        let reloaded = RecentProjects(defaults: defaults, exists: { _ in true })
        XCTAssertEqual(reloaded.items.map(\.path), ["/p/B", "/p/A"])
        XCTAssertEqual(reloaded.items.first?.lastOpened, Date(timeIntervalSince1970: 200))
    }

    func testDuplicatesMergeAndMoveToTop() {
        let recent = RecentProjects(defaults: defaults, exists: { _ in true })
        recent.note(url("/p/A"))
        recent.note(url("/p/B"))
        recent.note(URL(fileURLWithPath: "/p/A/"), name: "A neu")
        recent.note(URL(fileURLWithPath: "/p/x/../A"))
        XCTAssertEqual(recent.items.map(\.path), ["/p/A", "/p/B"])
        XCTAssertEqual(recent.items.count, 2)
    }

    func testLimitIsFifteen() {
        let recent = RecentProjects(defaults: defaults, exists: { _ in true })
        for i in 1...20 { recent.note(url("/p/Projekt \(i)")) }
        XCTAssertEqual(recent.items.count, 15)
        XCTAssertEqual(recent.items.first?.name, "Projekt 20")
        XCTAssertEqual(recent.items.last?.name, "Projekt 6")
        XCTAssertEqual(RecentProjects(defaults: defaults, exists: { _ in true }).items.count, 15)
    }

    func testMissingFoldersAreMarkedAndCanBeRemoved() {
        var existing: Set<String> = ["/p/A", "/p/B"]
        let recent = RecentProjects(defaults: defaults, exists: { existing.contains($0.path) })
        recent.note(url("/p/A"))
        recent.note(url("/p/B"))
        recent.note(url("/p/C"))
        XCTAssertEqual(recent.items.map(\.isMissing), [true, false, false])

        existing.remove("/p/A")
        recent.refresh()
        XCTAssertEqual(recent.items.map(\.isMissing), [true, false, true])

        recent.removeMissing()
        XCTAssertEqual(recent.items.map(\.path), ["/p/B"])
    }

    func testRemoveAndClear() {
        let recent = RecentProjects(defaults: defaults, exists: { _ in true })
        recent.note(url("/p/A"))
        recent.note(url("/p/B"))
        recent.remove(url("/p/A/"))
        XCTAssertEqual(recent.items.map(\.path), ["/p/B"])
        recent.clear()
        XCTAssertTrue(recent.items.isEmpty)
        XCTAssertTrue(RecentProjects(defaults: defaults).items.isEmpty)
    }

    func testLoadingMergesOldDuplicates() throws {
        let old = [
            RecentProject(path: "/p/A/", name: "A alt", lastOpened: Date(timeIntervalSince1970: 1)),
            RecentProject(path: "/p/A", name: "A", lastOpened: Date(timeIntervalSince1970: 5)),
            RecentProject(path: "/p/B", name: "B", lastOpened: Date(timeIntervalSince1970: 3)),
        ]
        defaults.set(try JSONEncoder().encode(old), forKey: RecentProjects.defaultsKey)
        let recent = RecentProjects(defaults: defaults, exists: { _ in true })
        XCTAssertEqual(recent.items.map(\.name), ["A", "B"])
    }

    func testMissingFlagIsNotStored() throws {
        let recent = RecentProjects(defaults: defaults, exists: { _ in false })
        recent.note(url("/p/A"))
        XCTAssertTrue(recent.items[0].isMissing)
        let json = String(data: defaults.data(forKey: RecentProjects.defaultsKey)!, encoding: .utf8)!
        XCTAssertFalse(json.contains("isMissing"))
        XCTAssertFalse(RecentProjects(defaults: defaults, exists: { _ in true }).items[0].isMissing)
    }

    func testRealFolderCheck() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-recent-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let recent = RecentProjects(defaults: defaults)
        recent.note(folder)
        XCTAssertFalse(recent.items[0].isMissing)
        try FileManager.default.removeItem(at: folder)
        recent.refresh()
        XCTAssertTrue(recent.items[0].isMissing)
    }

    func testMergeIsPure() {
        let a = RecentProject(path: "/a", name: "a", lastOpened: .distantPast)
        let b = RecentProject(path: "/b", name: "b", lastOpened: .distantPast)
        let a2 = RecentProject(path: "/a", name: "a2", lastOpened: .distantFuture)
        XCTAssertEqual(RecentProjects.merge([a, b], adding: a2, limit: 15).map(\.name), ["a2", "b"])
        XCTAssertEqual(RecentProjects.merge([a, b], adding: a2, limit: 1).map(\.name), ["a2"])
    }
}
