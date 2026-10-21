import KevCADCore
import SwiftUI

// Phase 5 (Strang ANI): Zeitleiste unter dem Viewport. Liest AnimationModel, ruft AnimationActions
// (`model.actions as? AnimationActions`). Unsichtbar, solange das Modell keine Animation hat.

/// Zeitleiste: Animationsauswahl, Abspielen, Bild für Bild, Schleife, Geschwindigkeit, Schieber mit Kollisionsmarken,
/// Zeit und Bild, Kamerafahrt, Kollisionsprüfung, Video, Bewegung zurücksetzen.
struct AnimationTimeline: View {
    @ObservedObject var model: AppModel
    @ObservedObject var animation: AnimationModel

    private var actions: AnimationActions? { model.actions as? AnimationActions }

    var body: some View {
        if animation.hasAnimation {
            VStack(spacing: 0) {
                Divider()
                HStack(spacing: 10) {
                    picker
                    transport
                    AnimationTrack(animation: animation, clock: animation.clock) { actions?.seekAnimation(to: $0) }
                        .frame(minWidth: 180)
                    AnimationTimeLabel(animation: animation, clock: animation.clock)
                    tools
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                AnimationInfoRow(animation: animation, clock: animation.clock)
            }
            .background(.bar)
            .controlSize(.small)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    // MARK: Teile

    private var picker: some View {
        Menu {
            ForEach(animation.entries) { e in
                Button {
                    actions?.selectAnimation(e.name)
                } label: {
                    if e.name == animation.selected {
                        Label("\(e.name) · \(KevFormat.number(e.duration, digits: 1)) s", systemImage: "checkmark")
                    } else {
                        Text("\(e.name) · \(KevFormat.number(e.duration, digits: 1)) s")
                    }
                }
            }
        } label: {
            Label(animation.current?.name ?? "Animation", systemImage: "film.stack")
                .lineLimit(1)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(animation.entries.count > 1 ? "Animation wählen (\(animation.entries.count) im Modell)"
              : "Animation aus model.py")
    }

    private var transport: some View {
        HStack(spacing: 2) {
            iconButton("backward.end.fill", help: "Zum Anfang (Umschalt+←)") { actions?.jumpToAnimationStart() }
            iconButton("backward.frame.fill", help: "Ein Bild zurück (←)") { actions?.stepAnimation(frames: -1) }
            iconButton(animation.playing ? "pause.fill" : "play.fill",
                       help: animation.playing ? "Anhalten (Leertaste)" : "Abspielen (Leertaste)") {
                actions?.togglePlayback()
            }
            .font(.system(size: 15))
            iconButton("forward.frame.fill", help: "Ein Bild vor (→)") { actions?.stepAnimation(frames: 1) }
            iconButton("forward.end.fill", help: "Zum Ende (Umschalt+→)") { actions?.jumpToAnimationEnd() }
            Toggle(isOn: Binding(get: { animation.loop }, set: { actions?.setAnimationLoop($0) })) {
                Image(systemName: "repeat")
            }
            .toggleStyle(.button)
            .buttonStyle(.borderless)
            .help(animation.loop ? "Schleife an" : "Schleife aus")
            Menu {
                ForEach([0.25, 0.5, 1.0, 2.0, 4.0], id: \.self) { s in
                    Button(Self.speedText(s)) { actions?.setAnimationSpeed(s) }
                }
            } label: {
                Text(Self.speedText(animation.speed))
                    .monospacedDigit()
                    .frame(minWidth: 30)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help("Geschwindigkeit")
        }
    }

    private func iconButton(_ symbol: String, help: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .frame(width: 22, height: 20)
                .contentShape(Rectangle())
        }
        .buttonStyle(.borderless)
        .help(help)
    }

    static func speedText(_ s: Double) -> String {
        (s == s.rounded() ? String(Int(s)) : KevFormat.number(s, digits: 2)) + "×"
    }

    private var tools: some View {
        HStack(spacing: 6) {
            if animation.current?.hasCamera == true {
                Toggle(isOn: Binding(get: { animation.followsCamera }, set: { actions?.setFollowsAnimationCamera($0) })) {
                    Image(systemName: "video")
                }
                .toggleStyle(.button)
                .buttonStyle(.borderless)
                .help(animation.followsCamera ? "Kamerafahrt an: der Viewer folgt anim.ansicht" : "Kamerafahrt aus")
            }
            collisionButton
            AnimationVideoButton(clock: animation.clock, actions: actions)
            Button {
                actions?.resetAnimationPose()
            } label: {
                Image(systemName: "arrow.uturn.backward")
            }
            .buttonStyle(.borderless)
            .disabled(!animation.posed)
            .help("Bewegung zurücksetzen: alle Teile in die Lage aus model.py")
        }
    }

    @ViewBuilder
    private var collisionButton: some View {
        switch animation.collisionState {
        case .checking:
            ProgressView().controlSize(.mini).help("Kollisionen werden geprüft …")
        default:
            Button {
                actions?.checkAnimationCollisions()
            } label: {
                HStack(spacing: 3) {
                    Image(systemName: collisionSymbol)
                        .foregroundStyle(collisionTint)
                    if case .checked = animation.collisionState, !animation.collisions.isEmpty {
                        Text("\(animation.collisions.count)").monospacedDigit().foregroundStyle(.red)
                    }
                }
            }
            .buttonStyle(.borderless)
            .help(collisionHelp)
        }
    }

    private var collisionSymbol: String {
        switch animation.collisionState {
        case .checked: return animation.collisions.isEmpty ? "checkmark.shield" : "exclamationmark.triangle.fill"
        case .failed: return "exclamationmark.shield"
        default: return "shield.lefthalf.filled"
        }
    }

    private var collisionTint: Color {
        switch animation.collisionState {
        case .checked: return animation.collisions.isEmpty ? .green : .red
        case .failed: return .orange
        default: return .primary
        }
    }

    private var collisionHelp: String {
        switch animation.collisionState {
        case .unchecked: return "Kollisionen prüfen (jedes 3. Bild, exakt)"
        case .checking: return "Kollisionen werden geprüft …"
        case .checked(let frames, let ms):
            let head = animation.collisions.isEmpty ? "Keine Kollision" : KevFormat.count(
                animation.collisions.count, one: "Kollision", many: "Kollisionen")
            return "\(head) · \(frames) Bilder in \(KevFormat.duration(ms: Int(ms))) geprüft · Klick prüft neu"
        case .failed(let m): return "Prüfung fehlgeschlagen: \(m)"
        }
    }
}

/// Zeit und Bild (beobachtet nur die Uhr).
struct AnimationTimeLabel: View {
    @ObservedObject var animation: AnimationModel
    @ObservedObject var clock: AnimationClock

    var body: some View {
        VStack(alignment: .trailing, spacing: 0) {
            Text("\(KevFormat.number(clock.time, digits: 2)) / \(KevFormat.number(animation.duration, digits: 2)) s")
            Text("Bild \(clock.frame) / \(animation.lastFrame)")
                .foregroundStyle(.secondary)
        }
        .font(.caption.monospacedDigit())
        .frame(minWidth: 104, alignment: .trailing)
    }
}

/// Video-Knopf bzw. Fortschritt.
struct AnimationVideoButton: View {
    @ObservedObject var clock: AnimationClock
    var actions: AnimationActions?

    var body: some View {
        switch clock.video {
        case .rendering, .encoding:
            ProgressView(value: fraction)
                .progressViewStyle(.circular)
                .controlSize(.mini)
                .help("Video entsteht …")
        default:
            Menu {
                Button("MP4 (H.264), 1920 × 1080") { actions?.exportAnimationVideo(width: 1920, format: "mp4") }
                Button("MP4 (H.264), 3840 × 2160") { actions?.exportAnimationVideo(width: 3840, format: "mp4") }
                Button("ProRes 422, 1920 × 1080") { actions?.exportAnimationVideo(width: 1920, format: "prores") }
            } label: {
                Image(systemName: "film")
            } primaryAction: {
                actions?.exportAnimationVideo(width: 1920, format: "mp4")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help("Video nach output/animationen/ (Klick: MP4 1920 × 1080)")
        }
    }

    private var fraction: Double {
        if case .rendering(let k, let n) = clock.video, n > 0 { return Double(k) / Double(n) }
        return 1
    }
}

/// Zweite Zeile: Kollision im aktuellen Bild und Videofortschritt.
struct AnimationInfoRow: View {
    @ObservedObject var animation: AnimationModel
    @ObservedObject var clock: AnimationClock

    var body: some View {
        if !animation.activeCollisions.isEmpty || clock.video != .idle {
            HStack(spacing: 12) {
                if let c = animation.activeCollisions.first {
                    Label {
                        Text("Kollision \(c.parts.joined(separator: " ↔ ")) · Eindringtiefe \(KevFormat.mm(c.depth, digits: 2))"
                             + (animation.activeCollisions.count > 1 ? " (+\(animation.activeCollisions.count - 1))" : ""))
                            .lineLimit(1)
                            .truncationMode(.middle)
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                    }
                }
                Spacer(minLength: 0)
                AnimationVideoStatus(clock: clock)
            }
            .font(.caption)
            .padding(.horizontal, 12)
            .padding(.bottom, 6)
        }
    }
}

/// Fortschritt der Videoausgabe (Zeitleiste und Statusleiste).
struct AnimationVideoStatus: View {
    @ObservedObject var clock: AnimationClock

    var body: some View {
        switch clock.video {
        case .idle:
            EmptyView()
        case .rendering(let k, let n):
            HStack(spacing: 6) {
                ProgressView(value: Double(k), total: Double(max(n, 1))).frame(width: 90)
                Text("Video: Bild \(k) von \(n)").monospacedDigit()
            }
        case .encoding:
            HStack(spacing: 6) {
                ProgressView().controlSize(.mini)
                Text("Video wird geschrieben …")
            }
        case .finished(let path):
            Label("Video: \((path as NSString).lastPathComponent)", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.secondary)
                .help(path)
        case .failed(let message):
            Label("Video: \(message)", systemImage: "xmark.octagon.fill")
                .foregroundStyle(.red)
                .lineLimit(1)
                .help(message)
        }
    }
}

/// Schieber der Zeitleiste mit Sekundenstrichen, Kollisionsspannen (rot) und Abspielkopf. Klicken oder Ziehen springt.
struct AnimationTrack: View {
    @ObservedObject var animation: AnimationModel
    @ObservedObject var clock: AnimationClock
    var seek: (Double) -> Void

    var body: some View {
        GeometryReader { geo in
            let w = max(geo.size.width, 1)
            let d = max(animation.duration, 1e-6)
            let x = { (t: Double) -> CGFloat in CGFloat(t / d) * w }
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.secondary.opacity(0.18))
                    .frame(height: 6)
                Capsule()
                    .fill(Color.accentColor.opacity(animation.posed ? 0.55 : 0.2))
                    .frame(width: max(0, x(clock.time)), height: 6)
                ForEach(secondTicks, id: \.self) { s in
                    Rectangle()
                        .fill(Color.secondary.opacity(0.45))
                        .frame(width: 1, height: s.truncatingRemainder(dividingBy: 5) == 0 ? 12 : 7)
                        .offset(x: x(s) - 0.5)
                }
                ForEach(animation.collisions) { c in
                    let start = x(c.from), end = x(c.to)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.red.opacity(0.75))
                        .frame(width: max(4, end - start), height: 10)
                        .offset(x: max(0, start - (end - start < 4 ? 2 : 0)))
                        .help("Kollision \(c.parts.joined(separator: " ↔ ")) · \(KevFormat.number(c.from, digits: 2)) bis "
                              + "\(KevFormat.number(c.to, digits: 2)) s · Eindringtiefe \(KevFormat.mm(c.depth, digits: 2))")
                        .onTapGesture { seek(c.time) }
                }
                Circle()
                    .fill(Color.accentColor)
                    .overlay(Circle().strokeBorder(.white.opacity(0.9), lineWidth: 1.5))
                    .shadow(color: .black.opacity(0.25), radius: 1, y: 0.5)
                    .frame(width: 13, height: 13)
                    .offset(x: x(clock.time) - 6.5)
            }
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in seek(min(max(Double(g.location.x / w), 0), 1) * d) }
            )
        }
        .frame(height: 24)
        .help("Zeit: klicken oder ziehen")
    }

    private var secondTicks: [Double] {
        let d = animation.duration
        guard d > 0 else { return [] }
        let step: Double = d > 60 ? 10 : (d > 20 ? 5 : 1)
        return stride(from: step, to: d, by: step).map { $0 }
    }
}

/// Statusleiste: Fortschritt der Videoausgabe (nur solange ein Video entsteht oder gerade fertig wurde).
struct AnimationStatusItem: View {
    @ObservedObject var clock: AnimationClock

    var body: some View {
        if clock.video != .idle {
            HStack(spacing: 0) {
                Divider().frame(height: 14).padding(.horizontal, 10)
                AnimationVideoStatus(clock: clock)
                    .font(.subheadline)
            }
        }
    }
}
