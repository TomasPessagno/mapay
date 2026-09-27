import SwiftUI
import UIKit
import WidgetKit

// Home-screen widget (#29, AGENTS.md › Pre-route heads-up › Home-screen widget). No App Groups on a free
// Apple ID, so it fetches /routines/upcoming itself with the same identifierForVendor as the app.

// MARK: - Data (the routines-upcoming.json contract, only the fields the widget draws)

struct UpcomingLeg: Decodable {
    struct Place: Decodable { let name: String }
    struct Hazard: Decodable {
        let hazard_type: String
        let title: String
    }

    let routine_id: String
    let routine_name: String
    let leg: Int
    let from: Place
    let to: Place
    var departure_at: Date
    var heads_up_at: Date
    let duration_s: Int
    let summary: String
    let top_hazards: [Hazard]

    func shifted(by offset: TimeInterval) -> UpcomingLeg {
        var copy = self
        copy.departure_at = departure_at.addingTimeInterval(offset)
        copy.heads_up_at = heads_up_at.addingTimeInterval(offset)
        return copy
    }

    func link(_ action: String) -> URL {
        URL(string: "mapay://\(action)?routine=\(routine_id)&leg=\(leg)")!
    }
}

private struct UpcomingResponse: Decodable { let items: [UpcomingLeg] }

enum UpcomingSource {
    /// `MapayAPIBaseURL` in Info.plist, from the MAPAY_API_BASE_URL build setting:
    /// empty → the bundled mock; ".../mocks" → the Vite dev server's mock file; otherwise the API.
    static var baseURL: String {
        (Bundle.main.object(forInfoDictionaryKey: "MapayAPIBaseURL") as? String ?? "")
            .trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
    }

    static var usesMocks: Bool { baseURL.isEmpty || baseURL.hasSuffix("/mocks") }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        let plain = ISO8601DateFormatter()
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        decoder.dateDecodingStrategy = .custom { d in
            let s = try d.singleValueContainer().decode(String.self)
            if let date = plain.date(from: s) ?? fractional.date(from: s) { return date }
            throw DecodingError.dataCorrupted(.init(codingPath: d.codingPath, debugDescription: "Bad date \(s)"))
        }
        return decoder
    }()

    static func fetch() async throws -> [UpcomingLeg] {
        let legs: [UpcomingLeg]
        if baseURL.isEmpty {
            legs = try bundledMock()
        } else if usesMocks {
            do {
                legs = try await get(URL(string: "\(baseURL)/routines-upcoming.json")!)
            } catch {
                legs = try bundledMock() // the dev server isn't running
            }
        } else {
            return try await get(URL(string: "\(baseURL)/routines/upcoming?compact=1&limit=3")!)
        }
        return shiftedForDemo(legs)
    }

    private static func get(_ url: URL) async throws -> [UpcomingLeg] {
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.setValue(UIDevice.current.identifierForVendor?.uuidString ?? "unknown", forHTTPHeaderField: "X-Device-Id")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try decoder.decode(UpcomingResponse.self, from: data).items
    }

    private static func bundledMock() throws -> [UpcomingLeg] {
        guard let url = Bundle.main.url(forResource: "routines-upcoming", withExtension: "json") else {
            throw URLError(.fileDoesNotExist)
        }
        return try decoder.decode(UpcomingResponse.self, from: Data(contentsOf: url)).items
    }

    /// Mock times are fixed days ahead; shift them so the first leg's heads-up starts now (like the
    /// app's Live Activity debug path, which departs 30 min after the app opens). The anchor is kept
    /// until that leg has departed, so reloads don't restart the countdown.
    private static func shiftedForDemo(_ legs: [UpcomingLeg]) -> [UpcomingLeg] {
        guard let first = legs.min(by: { $0.departure_at < $1.departure_at }) else { return legs }
        let key = "mockHeadsUpAnchor"
        let lead = first.departure_at.timeIntervalSince(first.heads_up_at)
        var anchor = UserDefaults.standard.object(forKey: key) as? Date ?? .distantPast
        if anchor.addingTimeInterval(lead) < .now {
            anchor = .now
            UserDefaults.standard.set(anchor, forKey: key)
        }
        let offset = anchor.timeIntervalSince(first.heads_up_at)
        return legs.map { $0.shifted(by: offset) }
    }
}

// MARK: - Timeline

struct LegEntry: TimelineEntry {
    enum Mode { case idle, headsUp, empty, offline }
    let date: Date
    let mode: Mode
    let leg: UpcomingLeg?
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> LegEntry {
        LegEntry(date: .now, mode: .headsUp, leg: SampleData.leg)
    }

    func getSnapshot(in context: Context, completion: @escaping (LegEntry) -> Void) {
        if context.isPreview {
            completion(placeholder(in: context))
            return
        }
        Task {
            let legs = (try? await UpcomingSource.fetch()) ?? []
            completion(Self.entries(for: legs, now: .now).first ?? placeholder(in: context))
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<LegEntry>) -> Void) {
        Task {
            let now = Date.now
            do {
                let legs = try await UpcomingSource.fetch()
                completion(Timeline(entries: Self.entries(for: legs, now: now), policy: .after(Self.reloadDate(for: legs, now: now))))
            } catch {
                completion(Timeline(entries: [LegEntry(date: now, mode: .offline, leg: nil)], policy: .after(now.addingTimeInterval(15 * 60))))
            }
        }
    }

    /// idle → heads-up at `heads_up_at` → the next leg after departure; entries switch without a reload.
    static func entries(for legs: [UpcomingLeg], now: Date) -> [LegEntry] {
        var entries: [LegEntry] = []
        var cursor = now
        for leg in legs.sorted(by: { $0.departure_at < $1.departure_at }) where leg.departure_at > cursor {
            if leg.heads_up_at > cursor {
                entries.append(LegEntry(date: cursor, mode: .idle, leg: leg))
                entries.append(LegEntry(date: leg.heads_up_at, mode: .headsUp, leg: leg))
            } else {
                entries.append(LegEntry(date: cursor, mode: .headsUp, leg: leg))
            }
            cursor = leg.departure_at
        }
        entries.append(LegEntry(date: cursor, mode: .empty, leg: nil))
        return entries
    }

    /// `.after(next heads-up start − 15 min)` so hazards are fresh when heads-up mode begins.
    static func reloadDate(for legs: [UpcomingLeg], now: Date) -> Date {
        let nextHeadsUp = legs.map(\.heads_up_at).filter { $0 > now }.min()
        let target = nextHeadsUp?.addingTimeInterval(-15 * 60) ?? now.addingTimeInterval(60 * 60)
        return max(target, now.addingTimeInterval(5 * 60))
    }
}

// MARK: - Views

private let timeFormat: Date.FormatStyle = .dateTime.weekday(.abbreviated).hour().minute()

struct MapayWidgetEntryView: View {
    @Environment(\.widgetFamily) private var family
    @Environment(\.widgetRenderingMode) private var renderingMode
    let entry: LegEntry

    private var style: HazardStyle { HazardStyle.of(entry.leg?.top_hazards.first?.hazard_type) }
    private var loud: Bool { entry.mode == .headsUp && renderingMode == .fullColor }

    var body: some View {
        Group {
            switch entry.mode {
            case .empty: message("No trips coming up", systemImage: "checkmark.circle")
            case .offline: message("Can't reach Mapay", systemImage: "wifi.slash")
            case .idle, .headsUp:
                if let leg = entry.leg {
                    switch family {
                    case .systemSmall: small(leg)
                    case .systemMedium: medium(leg)
                    default: large(leg)
                    }
                }
            }
        }
        .foregroundStyle(loud ? AnyShapeStyle(.white) : AnyShapeStyle(.primary))
        .containerBackground(for: .widget) {
            if loud { style.gradient } else { Color(.secondarySystemBackground) }
        }
        .widgetURL(entry.leg?.link("customize"))
    }

    // Small: leave time (or countdown) + hazard count.
    private func small(_ leg: UpcomingLeg) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            header(leg)
            Spacer(minLength: 0)
            countdownOrTime(leg, size: 28)
            Text(entry.mode == .headsUp ? "to leave for \(leg.to.name)" : "\(leg.from.name) → \(leg.to.name)")
                .font(.caption2.weight(.semibold))
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // Medium: route, countdown, top hazard, both buttons.
    private func medium(_ leg: UpcomingLeg) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                route(leg)
                Spacer(minLength: 8)
                // Timer text takes all the width it's offered, so pin it to the trailing edge.
                countdownOrTime(leg, size: 26)
                    .multilineTextAlignment(.trailing)
                    .frame(maxWidth: 120, alignment: .trailing)
            }
            if let top = leg.top_hazards.first { hazardRow(top) } else { tripLine(leg) }
            Spacer(minLength: 0)
            buttons(leg)
        }
    }

    // Large (the Duolingo-style one): route, big countdown, top 3 hazards, both buttons.
    private func large(_ leg: UpcomingLeg) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            header(leg)
            route(leg)
            VStack(alignment: .leading, spacing: 0) {
                countdownOrTime(leg, size: 52)
                Text(entry.mode == .headsUp ? "left to leave for \(leg.to.name)" : "Next trip")
                    .font(.system(.subheadline, design: .rounded).weight(.semibold))
            }
            tripLine(leg)
            VStack(alignment: .leading, spacing: 6) {
                if leg.top_hazards.isEmpty {
                    Label("No hazards on the route", systemImage: "checkmark.seal.fill").font(.footnote)
                }
                ForEach(Array(leg.top_hazards.prefix(3).enumerated()), id: \.offset) { _, hazard in hazardRow(hazard) }
            }
            Spacer(minLength: 0)
            buttons(leg)
        }
    }

    private func header(_ leg: UpcomingLeg) -> some View {
        HStack(spacing: 6) {
            Image(systemName: entry.mode == .headsUp ? style.symbol : "car.fill")
                .font(.caption.weight(.bold))
                .widgetAccentable()
            Text(leg.top_hazards.isEmpty ? "No hazards" : leg.top_hazards.count == 1 ? "1 hazard" : "\(leg.top_hazards.count) hazards")
                .font(.caption.weight(.semibold))
        }
    }

    private func route(_ leg: UpcomingLeg) -> some View {
        Text("\(leg.from.name) → \(leg.to.name)")
            .font(.headline)
            .lineLimit(1)
            .widgetAccentable()
    }

    @ViewBuilder
    private func countdownOrTime(_ leg: UpcomingLeg, size: CGFloat) -> some View {
        Group {
            if entry.mode == .headsUp {
                Text(leg.departure_at, style: .timer)
            } else {
                Text(leg.departure_at, format: timeFormat)
            }
        }
        .font(.system(size: size, weight: .bold, design: .rounded))
        .monospacedDigit()
        .lineLimit(1)
        .minimumScaleFactor(0.5)
        .widgetAccentable()
    }

    private func tripLine(_ leg: UpcomingLeg) -> some View {
        Text("\(leg.duration_s / 60) min trip · \(leg.summary)")
            .font(.caption)
            .opacity(0.85)
            .lineLimit(1)
    }

    private func hazardRow(_ hazard: UpcomingLeg.Hazard) -> some View {
        Label {
            Text(hazard.title).lineLimit(1)
        } icon: {
            Image(systemName: HazardStyle.of(hazard.hazard_type).symbol)
                .foregroundStyle(loud ? AnyShapeStyle(.white) : AnyShapeStyle(HazardStyle.of(hazard.hazard_type).color))
                .widgetAccentable()
        }
        .font(.footnote.weight(.medium))
    }

    private func buttons(_ leg: UpcomingLeg) -> some View {
        HStack(spacing: 8) {
            Link(destination: leg.link("start")) {
                Label("Start", systemImage: "location.fill")
                    .font(.caption.weight(.bold))
                    .frame(maxWidth: .infinity).padding(.vertical, 7)
                    .background(loud ? AnyShapeStyle(.white) : AnyShapeStyle(Color.accentColor), in: Capsule())
                    .foregroundStyle(loud ? AnyShapeStyle(style.color) : AnyShapeStyle(.white))
            }
            .widgetAccentable()
            Link(destination: leg.link("customize")) {
                Label("Customize", systemImage: "slider.horizontal.3")
                    .font(.caption.weight(.bold))
                    .frame(maxWidth: .infinity).padding(.vertical, 7)
                    .background(.white.opacity(loud ? 0.25 : 0), in: Capsule())
                    .overlay(Capsule().stroke(.secondary.opacity(loud ? 0 : 0.5)))
            }
        }
    }

    private func message(_ text: String, systemImage: String) -> some View {
        VStack(spacing: 6) {
            Image(systemName: systemImage).font(.title2).widgetAccentable()
            Text("Mapay").font(.headline)
            Text(text).font(.caption).foregroundStyle(.secondary)
        }
    }
}

struct MapayWidget: Widget {
    let kind = "MapayWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            MapayWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("Mapay")
        .description("Your next trip, and a countdown when it's time to leave.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

enum SampleData {
    static let leg = UpcomingLeg(
        routine_id: "rt-fiu", routine_name: "FIU campuses", leg: 0,
        from: .init(name: "MMC"), to: .init(name: "BBC"),
        departure_at: .now.addingTimeInterval(28 * 60), heads_up_at: .now.addingTimeInterval(-2 * 60),
        duration_s: 2460, summary: "via SR-826 and I-95",
        top_hazards: [
            .init(hazard_type: "flood", title: "Flooded street on NE 151st St"),
            .init(hazard_type: "congestion", title: "Heavy traffic on SR-826"),
        ]
    )
}

#Preview(as: .systemLarge) {
    MapayWidget()
} timeline: {
    LegEntry(date: .now, mode: .headsUp, leg: SampleData.leg)
    LegEntry(date: .now, mode: .idle, leg: SampleData.leg)
}
