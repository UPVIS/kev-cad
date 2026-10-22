import CoreGraphics
import Foundation

/// Rückgängig für Zeichnungsänderungen: Der Kernel kennt kein Rückgängig, also rechnet die App zu jeder Änderung die
/// Gegenoperationen aus dem Stand davor (Blatt und Darstellung) und dem ACK (neue Kennungen). Was sich so nicht
/// umkehren lässt (Ansicht löschen, Automatik zurücksetzen), liefert nil; dafür gibt es die Versionen.
public enum ZeichnungsUmkehr {
    /// Gegenoperationen in der Reihenfolge, in der sie zu schicken sind, oder nil.
    public static func gegen(_ ops: [ZeichnungsOp], vorher z: Zeichnung, bearbeitung: ZeichnungsBearbeitung) -> [ZeichnungsOp]? {
        var out: [ZeichnungsOp] = []
        var unterdrueckt = z.blatt.unterdrueckt.count
        for (i, op) in ops.enumerated() {
            let erg = i < bearbeitung.ergebnisse.count ? bearbeitung.ergebnisse[i] : nil
            if let erg, !erg.ok { continue }  // gescheiterte Operation hat nichts geändert
            guard let g = gegen(op, vorher: z, ergebnis: erg, unterdrueckt: &unterdrueckt) else { return nil }
            out.insert(contentsOf: g, at: 0)
        }
        return out.isEmpty ? nil : out
    }

    static func gegen(_ op: ZeichnungsOp, vorher z: Zeichnung, ergebnis: ZeichnungsBearbeitung.Ergebnis?,
                      unterdrueckt: inout Int) -> [ZeichnungsOp]? {
        let b = z.blatt
        switch op {
        case .massVerschieben(let id, let versatz, let textLage):
            guard let m = b.mass(id) else { return nil }
            var g: [ZeichnungsOp] = []
            if versatz != nil, let alt = m.versatz { g.append(.massVerschieben(id: id, versatz: alt, textLage: nil)) }
            if textLage != nil, let d = z.mass(id) {
                g.append(.massVerschieben(id: id, versatz: nil, textLage: d.textAnker))
            }
            if !m.fest { g.append(.massAendern(id: id, text: nil, toleranz: nil, fest: false)) }
            return g.isEmpty ? nil : g
        case .massLoeschen(let id):
            guard let m = b.mass(id) else { return nil }
            if m.quelle == "auto" {
                // Gelöschte automatische Maße werden unterdrückt (am Ende der Liste); Aufheben bringt sie zurück
                let i = unterdrueckt
                unterdrueckt += 1
                return [.unterdrueckungAufheben(index: i)]
            }
            return [.massNeu(art: m.art, ansicht: m.ansicht, richtung: m.richtung, versatz: m.versatz, klicks: [],
                             bezuege: m.bezuege, text: m.text, toleranz: m.toleranz)]
        case .massNeu:
            guard let id = ergebnis?.id else { return nil }
            return [.massLoeschen(id: id)]
        case .massAendern(let id, _, _, _):
            guard let m = b.mass(id) else { return nil }
            return [.massAendern(id: id, text: m.text ?? "", toleranz: m.toleranz ?? "", fest: m.fest)]
        case .ansichtNeu, .schnittNeu, .einzelheitNeu:
            guard let id = ergebnis?.id else { return nil }
            return [.ansichtLoeschen(id: id)]
        case .ansichtVerschieben(let id, _):
            let lage = b.ansicht(id)?.lage ?? z.gruppe(id).map { CGPoint(x: $0.rahmen.midX, y: $0.rahmen.midY) }
            guard let lage else { return nil }
            return [.ansichtVerschieben(id: id, lage: lage)]
        case .ansichtLoeschen:
            return nil
        case .massstab:
            return [.massstab(b.massstab)]
        case .format:
            return [.format(b.format, ausrichtung: b.ausrichtung)]
        case .notiz:
            guard let id = ergebnis?.id else { return nil }
            return [.notizLoeschen(id: id)]
        case .notizLoeschen(let id):
            guard let n = b.notizen.first(where: { $0.id == id }) else { return nil }
            var zeiger: ZeichnungsKlick?
            if let zj = n.zeiger, let p = zj["punkt"]?.doubles, p.count >= 2 {
                zeiger = ZeichnungsKlick(ansicht: zj["ansicht"]?.stringValue, punkt: CGPoint(x: p[0], y: p[1]))
            }
            return [.notiz(text: n.text, lage: n.lage, zeiger: zeiger)]
        case .schriftfeld(let feld, _):
            return [.schriftfeld(feld: feld, wert: b.schriftfeld[feld] ?? .null)]
        case .auto(let ansichten, let masse, let zuruecksetzen):
            if zuruecksetzen == true { return nil }
            return [.auto(ansichten: ansichten == nil ? nil : b.autoAnsichten, masse: masse == nil ? nil : b.autoMasse,
                          zuruecksetzen: nil)]
        case .unterdrueckungAufheben, .roh:
            return nil
        }
    }
}
