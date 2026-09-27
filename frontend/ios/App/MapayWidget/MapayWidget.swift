import SwiftUI
import UIKit
import WidgetKit

// Static placeholder for #19; #29 builds the real widget.
struct PlaceholderEntry: TimelineEntry {
    let date: Date
    let deviceId: String
}

struct Provider: TimelineProvider {
    private func entry() -> PlaceholderEntry {
        let id = UIDevice.current.identifierForVendor?.uuidString ?? "unknown"
        print("[mapay widget] identifierForVendor \(id)")
        return PlaceholderEntry(date: .now, deviceId: id)
    }

    func placeholder(in context: Context) -> PlaceholderEntry {
        PlaceholderEntry(date: .now, deviceId: "…")
    }

    func getSnapshot(in context: Context, completion: @escaping (PlaceholderEntry) -> Void) {
        completion(entry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<PlaceholderEntry>) -> Void) {
        completion(Timeline(entries: [entry()], policy: .never))
    }
}

struct MapayWidgetEntryView: View {
    var entry: PlaceholderEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Mapay").font(.headline)
            Text("no routine yet").font(.subheadline).foregroundStyle(.secondary)
            Spacer()
            Text(entry.deviceId)
                .font(.system(size: 8, design: .monospaced))
                .foregroundStyle(.tertiary)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MapayWidget: Widget {
    let kind = "MapayWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            MapayWidgetEntryView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Mapay")
        .description("Your next routine at a glance.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

#Preview(as: .systemSmall) {
    MapayWidget()
} timeline: {
    PlaceholderEntry(date: .now, deviceId: "00000000-0000-0000-0000-000000000000")
}
