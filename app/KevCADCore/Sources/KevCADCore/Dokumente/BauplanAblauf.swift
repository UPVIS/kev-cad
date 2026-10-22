import Foundation
import simd

// Durchspielen des Bauplans (DOKUMENTE.md D7, Anhang P6-A2): welche Teile je Schritt zu sehen sind und wo die neuen
// Teile während des Einfahrens stehen. Ohne Viewport, mit `swift test` prüfbar; der App-Kern setzt die Lage über
// SceneStore.setAnimationPose (dieselbe Technik wie die Animationen).

public struct BauplanPose: Equatable, Sendable {
    /// Teile, die zu sehen sind (montiert und neu).
    public var sichtbar: Set<String>
    /// Neue Teile dieses Schritts.
    public var neu: Set<String>
    /// Versatz der neuen Teile (Welt, mm); 0 = eingebaut.
    public var versatz: [String: SIMD3<Float>]
    public var rotation: simd_quatf?
    public var ausschnittMin: SIMD3<Float>?
    public var ausschnittMax: SIMD3<Float>?
}

public enum BauplanAblauf {
    /// Schritte zum Durchspielen: alle Montageschritte; ohne Montage alle Schritte, die Teile haben.
    public static func schritte(_ plan: Bauplan) -> [String] {
        if let m = plan.montage, !m.schritte.isEmpty { return m.schritte.map(\.id) }
        return plan.alleSchritte.filter { !$0.teile.isEmpty }.map(\.id)
    }

    /// Bis einschließlich `schritt` montierte Teile: Hauptmontage alle früheren Hauptschritte, Vormontage nur die
    /// Schritte derselben Baugruppe. Andere Abschnitte: der fertige Stand.
    public static func montiert(_ plan: Bauplan, bis schritt: String) -> Set<String>? {
        guard let m = plan.montage, let k = m.schritte.firstIndex(where: { $0.id == schritt }) else { return nil }
        let gruppe = m.schritte[k].baugruppe
        var teile = Set<String>()
        for s in m.schritte[...k] where s.baugruppe == gruppe {
            teile.formUnion(s.neu.isEmpty ? s.teile : s.neu)
        }
        return teile
    }

    /// Startversatz eines neuen Teils: aus der Explosion des Schrittbilds, sonst gegen die Fügerichtung um den Weg.
    public static func startVersatz(_ s: BauplanSchritt, teil: String) -> SIMD3<Float> {
        if let e = s.bild?.explosion[teil] { return e }
        if let e = s.einbau.first(where: { $0.teile.contains(teil) || $0.name == teil }), let r = e.richtung {
            let n = simd_length(r) > 1e-6 ? simd_normalize(r) : r
            return -n * Float(max(e.weg, 0))
        }
        return .zero
    }

    /// Weiche Bewegung (am Anfang und Ende langsamer).
    public static func weich(_ t: Double) -> Double {
        let x = min(1, max(0, t))
        return x * x * (3 - 2 * x)
    }

    /// Zeitfenster je Einbaueinheit: erst das Hauptteil, dann die Verbindungsmittel, leicht versetzt (wie man baut).
    static func fortschritt(_ t: Double, einheit i: Int, von n: Int) -> Double {
        guard n > 1 else { return weich(t) }
        let versatz = min(0.18, 0.55 / Double(n - 1))
        let dauer = 1 - versatz * Double(n - 1)
        return weich((t - versatz * Double(i)) / dauer)
    }

    /// Lage aller Teile in `schritt` bei `fortschritt` (0 … 1). `alle` sind alle Teile der Szene; was nicht montiert
    /// ist, wird ausgeblendet.
    public static func pose(_ plan: Bauplan, schritt id: String, fortschritt t: Double) -> BauplanPose? {
        guard let s = plan.schritt(id) else { return nil }
        let neu = Set(s.neu.isEmpty ? s.teile : s.neu)
        var sichtbar = montiert(plan, bis: id) ?? Set(plan.alleSchritte.flatMap(\.teile))
        sichtbar.formUnion(neu)
        // Einheiten in der Reihenfolge der Montagefolge; Teile ohne Einheit fahren mit der ersten
        var einheiten: [[String]] = s.einbau.map { $0.teile.isEmpty ? [$0.name] : $0.teile }.filter { !$0.isEmpty }
        let erfasst = Set(einheiten.flatMap { $0 })
        let rest = s.neu.filter { !erfasst.contains($0) }
        if !rest.isEmpty {
            if einheiten.isEmpty { einheiten = [rest] } else { einheiten[0] += rest }
        }
        var versatz: [String: SIMD3<Float>] = [:]
        for (i, e) in einheiten.enumerated() {
            let f = Float(1 - fortschritt(t, einheit: i, von: einheiten.count))
            for teil in e where neu.contains(teil) {
                let v = startVersatz(s, teil: teil) * f
                if simd_length(v) > 0.01 { versatz[teil] = v }
            }
        }
        return BauplanPose(sichtbar: sichtbar, neu: neu, versatz: versatz, rotation: s.bild?.rotation,
                           ausschnittMin: s.bild?.ausschnittMin, ausschnittMax: s.bild?.ausschnittMax)
    }
}
