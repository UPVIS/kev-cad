import AppKit
import KevCADCore
import SwiftUI

/// Zustand der Versionsleiste je Projektfenster (nur Oberfläche): sichtbar, aufgeklappte Folgen, ausgewählte Version,
/// offene Dialoge. Über `focusedSceneObject` erreichen ihn auch die Menübefehle.
@MainActor
final class VersionenZustand: ObservableObject {
    /// Leiste „Versionen“ rechts neben dem Viewport; bleibt über Neustarts hinweg, wie sie zuletzt war.
    @Published var zeigeLeiste = UserDefaults.standard.object(forKey: "showVersionen") as? Bool ?? true {
        didSet { UserDefaults.standard.set(zeigeLeiste, forKey: "showVersionen") }
    }
    @Published var aufgeklappt: Set<String> = []
    @Published var auswahl: Int?
    /// Meilenstein-Dialog: Version (nil = aktueller Stand), vorbelegter Titel und Notiz.
    @Published var meilensteinDialog: MeilensteinDialogDaten?
    /// Dialog „Variante anlegen“: von dieser Version (nil = aktueller Stand).
    @Published var varianteDialog: VarianteDialogDaten?
    @Published var umbenennenDialog: VersionVariante?
    @Published var zeigeVergleichDetail = false

    static let breite: CGFloat = 318

    func meilensteinSetzen(_ v: VersionEintrag? = nil) {
        meilensteinDialog = MeilensteinDialogDaten(
            version: v?.nr, aktuell: v == nil || v?.aktuell == true, titel: v?.meilenstein?.titel ?? "",
            notiz: v?.meilenstein?.notiz ?? "", bearbeiten: v?.meilenstein != nil)
    }

    func varianteAnlegen(von v: VersionEintrag? = nil) {
        varianteDialog = VarianteDialogDaten(von: v?.nr)
    }
}

struct MeilensteinDialogDaten: Identifiable {
    let id = UUID()
    var version: Int?
    var aktuell: Bool
    var titel: String
    var notiz: String
    var bearbeiten: Bool
}

struct VarianteDialogDaten: Identifiable {
    let id = UUID()
    var von: Int?
}

/// Vorschaubilder aus `.kevcad/versionen/bilder`, zwischengespeichert nach Pfad und Änderungszeit.
@MainActor
final class VorschauCache {
    static let shared = VorschauCache()
    private var bilder: [String: (Date, NSImage)] = [:]

    func bild(_ url: URL?) -> NSImage? {
        guard let url else { return nil }
        let datum = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
        if let (d, img) = bilder[url.path], d == datum { return img }
        guard let img = NSImage(contentsOf: url) else { return nil }
        if bilder.count > 600 { bilder.removeAll() }
        bilder[url.path] = (datum, img)
        return img
    }
}

enum VersionenText {
    /// „vor 3 Min.“, „Heute, 14:32“, „Gestern, 09:10“.
    static func zeit(_ d: Date, jetzt: Date = Date()) -> String {
        let s = jetzt.timeIntervalSince(d)
        if s < 45 { return "gerade eben" }
        if s < 3600 { return "vor \(max(1, Int((s / 60).rounded()))) Min." }
        return KevFormat.recentDate(d, now: jetzt)
    }

    static func kennzahlen(_ k: VersionKennzahlen?) -> String {
        guard let k else { return "Kennzahlen folgen" }
        var bits = [KevFormat.count(k.teile, one: "Teil", many: "Teile")]
        if let m = k.masseKg { bits.append(KevFormat.kg(m)) }
        if let e = k.kosten { bits.append(KevFormat.euro(e)) }
        return bits.joined(separator: " · ")
    }

    static func werSymbol(_ w: VersionEintrag.Wer) -> String {
        switch w {
        case .kevin: return "person.fill"
        case .agent: return "sparkles"
        case .kevcad: return "gearshape.fill"
        case .unbekannt: return "bolt.badge.automatic"
        }
    }

    static func quelleSymbol(_ v: VersionEintrag) -> String? {
        switch v.quelle {
        case "wiederherstellen": return "arrow.uturn.backward.circle"
        case "sicherung": return "tray.and.arrow.down"
        case "uebernahme": return "clock.arrow.circlepath"
        default: return nil
        }
    }

    static func wert(_ x: Double?) -> String {
        guard let x else { return "–" }
        return x == x.rounded() && abs(x) < 1e9 ? KevFormat.integer(Int(x)) : KevFormat.number(x, digits: 3)
    }
}

/// Dialoge der Versionen am Projektfenster: Meilenstein, Variante, Umbenennen, Vergleichsdetails.
struct VersionenBlaetter: ViewModifier {
    @ObservedObject var model: AppModel
    @ObservedObject var zustand: VersionenZustand

    func body(content: Content) -> some View {
        content
            .sheet(item: $zustand.meilensteinDialog) { d in MeilensteinDialog(daten: d, model: model) }
            .sheet(item: $zustand.varianteDialog) { d in VarianteDialog(daten: d, model: model, store: model.versionen) }
            .sheet(item: $zustand.umbenennenDialog) { v in VarianteUmbenennenDialog(variante: v, model: model) }
            .sheet(isPresented: $zustand.zeigeVergleichDetail) { VergleichDetail(store: model.versionen) }
    }
}
