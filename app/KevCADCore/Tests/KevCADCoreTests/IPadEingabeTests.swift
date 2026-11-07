#if os(iOS)
import UIKit
import XCTest

@testable import KevCADCore

/// I-3b (PLAN-IPAD.md, 4.7): Am Magic Keyboard gelten dieselben Kürzel wie am Mac (Tastenbelegung.swift ist die einzige
/// Quelle); die HID-Codes des iPad werden den Tastencodes des Mac zugeordnet.
@MainActor
final class IPadEingabeTests: XCTestCase {
    private func befehl(_ hid: UIKeyboardHIDUsage, _ zeichen: String?, _ flags: UIKeyModifierFlags = []) -> ViewerBefehl? {
        Tastenbelegung.befehl(keyCode: NavigationInputView.macTastencode(hid) ?? 0xFFFF, zeichen: zeichen, flags: flags)
    }

    func testZiffernblockUndSondertastenWieAmMac() {
        XCTAssertEqual(NavigationInputView.macTastencode(.keypad1), 83)
        XCTAssertEqual(befehl(.keypad1, "1"), .vorne)
        XCTAssertEqual(befehl(.keypad7, "7", .control), .unten)
        XCTAssertEqual(befehl(.keypad5, "5"), .projektion)
        XCTAssertEqual(befehl(.keyboardHome, nil), .allesEinrahmen)
        XCTAssertEqual(befehl(.keyboardGraveAccentAndTilde, "^"), .ansichtMenue)
        XCTAssertEqual(befehl(.keyboardNonUSBackslash, "^"), .ansichtMenue)
    }

    func testBuchstabenUeberDasZeichen() {
        XCTAssertNil(NavigationInputView.macTastencode(.keyboardH))
        XCTAssertEqual(befehl(.keyboardH, "h"), .ausblenden)
        XCTAssertEqual(befehl(.keyboardH, "h", .shift), .andereAusblenden)
        XCTAssertEqual(befehl(.keyboardM, "m"), .messen)
        XCTAssertEqual(befehl(.keyboardM, "m", .shift), .masseUmschalten)
        XCTAssertEqual(befehl(.keyboardM, "m", .alternate), .masseLoeschen)
        XCTAssertEqual(befehl(.keyboardV, "v"), .sprechen)
        XCTAssertEqual(befehl(.keyboardQ, "q"), .werkzeugkranz, "Q öffnet den Werkzeugkranz wie am Mac (I-4)")
    }
}
#endif
