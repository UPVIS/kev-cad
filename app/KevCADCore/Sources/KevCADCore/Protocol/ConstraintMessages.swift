import Foundation
import simd

// CONSTRAINTS (Kernel → App, PROTOCOL.md Abschnitt „Zwangsbedingungen“): Bericht der Bedingungen nach jedem Lauf.
// Gelesen über JSONValue und so tolerant wie alle Nachrichten: fehlende oder falsch getypte Felder werden zu nil bzw.
// Vorgaben, unbekannte Felder bleiben unbeachtet.

private func vec3(_ json: JSONValue?) -> SIMD3<Float>? {
    guard let a = json?.arrayValue?.compactMap(\.doubleValue), a.count >= 3 else { return nil }
    return SIMD3(Float(a[0]), Float(a[1]), Float(a[2]))
}

extension ConstraintItem {
    public init?(json: JSONValue, index: Int) {
        guard json.objectValue != nil else { return nil }
        let art = json["art"]?.lenientString ?? "bedingung"
        self.init(
            id: json["id"]?.lenientString ?? "b\(index + 1)", art: art, gruppe: json["gruppe"]?.lenientString ?? "montage",
            symbol: json["symbol"]?.lenientString ?? art, text: json["text"]?.stringValue ?? art,
            teile: json["teile"]?.stringList ?? [],
            stand: ConstraintState(rawValue: json["stand"]?.stringValue ?? "") ?? .ungeprueft,
            schwere: json["schwere"]?.stringValue.flatMap(FindingSeverity.init(rawValue:)),
            soll: json["soll"]?.stringValue ?? "", ist: json["ist"]?.stringValue ?? "",
            abweichung: json["abweichung"]?.doubleValue, einheit: json["einheit"]?.stringValue ?? "mm",
            punkte: (json["punkte"]?.arrayValue ?? []).compactMap { vec3($0) }, zeile: json["zeile"]?.intValue,
            datei: json["datei"]?.lenientString, loesung: json["loesung"]?.stringValue,
            hinweis: json["hinweis"]?.stringValue)
        if let p = vec3(json["achse"]?["p"]), let d = vec3(json["achse"]?["d"]) { achse = (p, d) }
        wert = json["wert"]?.doubleValue
        wertEinheit = json["wert_einheit"]?.stringValue
        bereich = json["bereich"]?.arrayValue?.compactMap(\.doubleValue)
    }
}

extension ConstraintPart {
    public init?(json: JSONValue) {
        guard let name = json["name"]?.lenientString else { return nil }
        let frei: [ConstraintFreedom] = (json["freiheitsgrade"]?.arrayValue ?? []).compactMap { f in
            guard f.objectValue != nil else { return nil }
            return ConstraintFreedom(
                art: f["art"]?.stringValue ?? "drehung", text: f["text"]?.stringValue ?? "",
                gelenk: f["gelenk"]?.boolValue ?? false, unkritisch: f["unkritisch"]?.boolValue ?? false)
        }
        self.init(
            name: name, platziert: json["platziert"]?.boolValue ?? false, frei: json["frei"]?.intValue ?? 0,
            stand: json["stand"]?.stringValue ?? "bezug", bedingungen: json["bedingungen"]?.stringList ?? [],
            freiheitsgrade: frei, gelenke: json["gelenke"]?.stringList ?? [], befestigt: json["befestigt"]?.boolValue,
            amBoden: json["am_boden"]?.boolValue, verbindungen: json["verbindungen"]?.stringList ?? [],
            verletzt: json["verletzt"]?.intValue ?? 0)
    }
}

extension ConstraintFinding {
    public init?(json: JSONValue, index: Int) {
        guard json.objectValue != nil else { return nil }
        self.init(
            id: index, pruefung: json["pruefung"]?.stringValue ?? "bedingung", teile: json["teile"]?.stringList ?? [],
            schwere: FindingSeverity(rawValue: json["schwere"]?.stringValue ?? "") ?? .hinweis,
            text: json["text"]?.stringValue ?? "", soll: json["soll"]?.stringValue ?? "",
            ist: json["ist"]?.stringValue ?? "", ort: vec3(json["ort"]), loesung: json["loesung"]?.stringValue,
            bedingung: json["bedingung"]?.lenientString, zeile: json["zeile"]?.intValue)
    }
}

extension MotionRange {
    public init?(json: JSONValue) {
        guard json.objectValue != nil else { return nil }
        let frei: [[Double]] = (json["frei"]?.arrayValue ?? []).compactMap { r in
            let v = r.arrayValue?.compactMap(\.doubleValue) ?? []
            return v.count == 2 ? v : nil
        }
        let gegen = (json["kollisionen"]?.arrayValue ?? []).compactMap { $0["gegen"]?.stringValue }
        self.init(
            name: json["name"]?.stringValue ?? "Bewegung", art: json["art"]?.stringValue ?? "drehen",
            teile: json["teile"]?.stringList ?? [], von: json["von"]?.doubleValue ?? 0, bis: json["bis"]?.doubleValue ?? 0,
            frei: frei, blockiertDurch: gegen, teilweise: json["teilweise"]?.boolValue ?? false)
    }
}

extension ConstraintReport {
    public init(json: JSONValue) {
        let items = (json["items"]?.arrayValue ?? []).enumerated().compactMap { ConstraintItem(json: $1, index: $0) }
        let findings = (json["befunde"]?.arrayValue ?? []).enumerated().compactMap {
            ConstraintFinding(json: $1, index: $0)
        }
        let s = json["summe"]
        let summary = ConstraintSummary(
            gesamt: s?["gesamt"]?.intValue ?? items.count,
            erfuellt: s?["erfuellt"]?.intValue ?? items.filter { $0.stand == .erfuellt }.count,
            verletzt: s?["verletzt"]?.intValue ?? items.filter { $0.stand == .verletzt }.count,
            ungeprueft: s?["ungeprueft"]?.intValue ?? items.filter { $0.stand == .ungeprueft }.count,
            fehler: s?["fehler"]?.intValue ?? findings.filter { $0.schwere == .fehler }.count,
            warnungen: s?["warnungen"]?.intValue ?? findings.filter { $0.schwere == .warnung }.count,
            hinweise: s?["hinweise"]?.intValue ?? findings.filter { $0.schwere == .hinweis }.count)
        self.init(
            run: json["run"]?.intValue ?? 0, items: items, parts: (json["teile"]?.arrayValue ?? []).compactMap {
                ConstraintPart(json: $0)
            }, findings: findings, motions: (json["bewegungen"]?.arrayValue ?? []).compactMap { MotionRange(json: $0) },
            summary: summary, pruefMs: json["pruef_ms"]?.doubleValue, loeseMs: json["loese_ms"]?.doubleValue)
    }
}

/// CONSTRAINTS (Kernel → App) nach RUN_END und beim Verbinden.
public struct ConstraintsMessage: Sendable {
    public var report: ConstraintReport

    public init(report: ConstraintReport) {
        self.report = report
    }

    public static func decode(_ header: Data) throws -> ConstraintsMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: header)
        return ConstraintsMessage(report: ConstraintReport(json: json))
    }
}
