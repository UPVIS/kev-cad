import KevCADCore
import SwiftUI

#if os(macOS)
import AppKit
#else
import UIKit
#endif

// Dateien weitergeben auf Mac und iPad (Paket I-8, PLAN-IPAD.md Abschnitt 9).
//
// Der Kernel schreibt Exporte, 3MF, PDF, CSV und Videos am Mac. Am Mac zeigt Kev CAD sie im Finder. Das iPad hat keinen
// Finder und die Dateien nicht: Dort heißt derselbe Knopf „Teilen“, holt die Datei bei Bedarf vom Mac (`DateiActions`,
// PROTOCOL.md „I-8 Datei ans Gerät“) und öffnet das Teilen-Blatt des Systems. Darin stehen Sichern in Dateien, AirDrop,
// Drucken (PDF, Bilder) und Apps wie Bambu Handy für 3MF.

/// Knopf für eine Datei, die der Kernel genannt hat: am Mac „Im Finder zeigen“, auf dem iPad „Teilen“.
struct DateiKnopf: View {
    @ObservedObject var model: AppModel
    var datei: URL
    /// Text am Mac (Vorgabe „Im Finder zeigen“); auf dem iPad heißt der Knopf immer „Teilen“.
    var titelMac = "Im Finder zeigen"
    /// Nur ein Symbol (Ordner bzw. Teilen), etwa in engen Zeilen
    var kompakt = false

    var body: some View {
        #if os(macOS)
        Button {
            Dateiablage.imFinderZeigen([datei])
        } label: {
            if kompakt { Image(systemName: "folder") } else { Text(titelMac) }
        }
        .help("\(datei.lastPathComponent) im Finder zeigen")
        #else
        DateiTeilenKnopf(model: model, dateien: [datei], kompakt: kompakt)
        #endif
    }
}

/// Teilen-Knopf für Dateien des Kernels, auf Mac und iPad (am Mac ohne Holen, die Dateien liegen dort).
struct DateiTeilenKnopf: View {
    @ObservedObject var model: AppModel
    var dateien: [URL]
    var titel = "Teilen"
    var kompakt = false
    @State private var laedt: Double?
    @State private var fehler: String?
    @State private var rahmen: CGRect = .zero

    private var aktionen: DateiActions? { model.actions as? DateiActions }

    var body: some View {
        Button {
            Task { await teilen() }
        } label: {
            HStack(spacing: 6) {
                if let laedt {
                    ProgressView(value: laedt > 0 ? laedt : nil).progressViewStyle(.circular).controlSize(.small)
                } else {
                    Image(systemName: "square.and.arrow.up")
                }
                if !kompakt { Text(laedt == nil ? titel : "Vom Mac holen …") }
            }
        }
        .disabled(dateien.isEmpty || laedt != nil || aktionen?.kannDateienHolen == false)
        .help(aktionen?.kannDateienHolen == false ? "Kev CAD am Mac aktualisieren, dann lassen sich Dateien teilen"
              : dateien.count == 1 ? "\(dateien[0].lastPathComponent) teilen" : "\(dateien.count) Dateien teilen")
        .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { rahmen = $0 }
        .alert("Teilen ging nicht", isPresented: Binding(get: { fehler != nil }, set: { if !$0 { fehler = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(fehler ?? "")
        }
    }

    private func teilen() async {
        guard let aktionen else { return fehler = "Keine Verbindung zum Kern der App" }
        laedt = 0
        defer { laedt = nil }
        var lokal: [URL] = []
        do {
            for (i, d) in dateien.enumerated() {
                lokal.append(try await aktionen.dateiFuerGeraet(d) { anteil in
                    laedt = (Double(i) + anteil) / Double(dateien.count)
                })
            }
        } catch {
            fehler = "\(error)"
            return
        }
        TeilenBlatt.zeigen(lokal, von: rahmen)
    }
}

/// Teilen-Blatt des Systems (Weg im Kern: `Dateiablage.teilen`).
@MainActor
enum TeilenBlatt {
    static func zeigen(_ urls: [URL], von rahmen: CGRect) { Dateiablage.teilen(urls, von: rahmen) }
}
