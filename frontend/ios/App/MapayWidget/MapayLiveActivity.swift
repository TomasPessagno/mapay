import ActivityKit
import SwiftUI
import WidgetKit

// Duolingo-style heads-up (#37, docs/design.md › The heads-up): a loud gradient banner tinted by the
// top hazard, a big rounded countdown, the route, and Start / Customize.

struct HazardStyle {
    let color: Color
    let symbol: String

    // Colours are the light-mode hazard tokens from src/map/legend.ts.
    static func of(_ type: String?) -> HazardStyle {
        switch type {
        case "flood": return HazardStyle(color: Color(hex: 0x32ADE6), symbol: "water.waves")
        case "weather": return HazardStyle(color: Color(hex: 0x5856D6), symbol: "cloud.heavyrain.fill")
        case "construction": return HazardStyle(color: Color(hex: 0xFF9500), symbol: "cone.fill")
        case "closure": return HazardStyle(color: Color(hex: 0x3A3A3C), symbol: "minus.circle.fill")
        case "congestion": return HazardStyle(color: Color(hex: 0xFF3B30), symbol: "car.2.fill")
        case "no_sidewalk": return HazardStyle(color: Color(hex: 0xAF52DE), symbol: "figure.walk")
        case "pothole": return HazardStyle(color: Color(hex: 0xA2845E), symbol: "circle.bottomhalf.filled")
        case "incident": return HazardStyle(color: Color(hex: 0xFF2D55), symbol: "exclamationmark.triangle.fill")
        case "event": return HazardStyle(color: Color(hex: 0x34C759), symbol: "calendar")
        default: return HazardStyle(color: Color(hex: 0x007AFF), symbol: "checkmark.seal.fill")
        }
    }

    var gradient: LinearGradient {
        LinearGradient(colors: [color, color.darkened(by: 0.35)], startPoint: .topLeading, endPoint: .bottomTrailing)
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }

    func darkened(by amount: Double) -> Color {
        var (r, g, b, a): (CGFloat, CGFloat, CGFloat, CGFloat) = (0, 0, 0, 0)
        UIColor(self).getRed(&r, green: &g, blue: &b, alpha: &a)
        let k = CGFloat(1 - amount)
        return Color(red: Double(r * k), green: Double(g * k), blue: Double(b * k))
    }
}

private func deepLink(_ action: String, _ attributes: MapayActivityAttributes) -> URL {
    URL(string: "mapay://\(action)?routine=\(attributes.routineId)&leg=\(attributes.leg)")!
}

/// Counts down on its own (no updates needed); "Leave now" once departure has passed.
struct Countdown: View {
    let departure: Date
    let isStale: Bool

    var body: some View {
        if !isStale && departure > .now {
            Text(timerInterval: Date.now...departure, countsDown: true)
                .monospacedDigit()
        } else {
            Text("Leave now")
        }
    }
}

struct LockScreenBanner: View {
    let context: ActivityViewContext<MapayActivityAttributes>

    var body: some View {
        let state = context.state
        let style = HazardStyle.of(state.topHazardType)
        let leaving = context.isStale || state.departure <= .now

        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Image(systemName: style.symbol)
                        .font(.caption.weight(.bold))
                        .padding(5)
                        .background(.white.opacity(0.25), in: Circle())
                    Text(state.hazardCount == 0 ? "No hazards" : state.hazardCount == 1 ? "1 hazard" : "\(state.hazardCount) hazards")
                        .font(.caption.weight(.semibold))
                }

                Countdown(departure: state.departure, isStale: context.isStale)
                    .font(.system(size: 40, weight: .bold, design: .rounded))
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)

                Text(leaving ? "to \(context.attributes.toName)" : "left to leave for \(context.attributes.toName)")
                    .font(.system(.subheadline, design: .rounded).weight(.semibold))

                Text("\(context.attributes.fromName) → \(context.attributes.toName) · \(state.durationMin) min trip · \(state.summary)")
                    .font(.caption)
                    .opacity(0.85)
                    .lineLimit(1)

                HStack(spacing: 8) {
                    Link(destination: deepLink("start", context.attributes)) {
                        Label("Start", systemImage: "location.fill")
                            .font(.caption.weight(.bold))
                            .padding(.horizontal, 12).padding(.vertical, 6)
                            .background(.white, in: Capsule())
                            .foregroundStyle(style.color)
                    }
                    Link(destination: deepLink("customize", context.attributes)) {
                        Label("Customize", systemImage: "slider.horizontal.3")
                            .font(.caption.weight(.bold))
                            .padding(.horizontal, 12).padding(.vertical, 6)
                            .background(.white.opacity(0.25), in: Capsule())
                    }
                }
                .padding(.top, 2)
            }

            Spacer(minLength: 0)

            // The "mascot": a car heading into the top hazard.
            ZStack(alignment: .topTrailing) {
                Image(systemName: "car.fill")
                    .font(.system(size: 54, weight: .bold))
                    .padding(.top, 22).padding(.trailing, 16)
                Image(systemName: style.symbol)
                    .font(.system(size: 30, weight: .bold))
                    .padding(8)
                    .background(.white.opacity(0.25), in: Circle())
            }
        }
        .foregroundStyle(.white)
        .padding(16)
        .background(style.gradient)
    }
}

struct MapayLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: MapayActivityAttributes.self) { context in
            LockScreenBanner(context: context)
                .activityBackgroundTint(HazardStyle.of(context.state.topHazardType).color)
                .activitySystemActionForegroundColor(.white)
                .widgetURL(deepLink("customize", context.attributes))
        } dynamicIsland: { context in
            let style = HazardStyle.of(context.state.topHazardType)
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label {
                        Text("\(context.attributes.fromName) → \(context.attributes.toName)")
                            .font(.caption.weight(.semibold))
                    } icon: {
                        Image(systemName: "car.fill").foregroundStyle(style.color)
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Countdown(departure: context.state.departure, isStale: context.isStale)
                        .font(.system(.title3, design: .rounded).weight(.bold))
                        .foregroundStyle(style.color)
                        .frame(maxWidth: 90, alignment: .trailing)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 8) {
                        if let title = context.state.topHazardTitle {
                            Label(title, systemImage: style.symbol)
                                .font(.caption)
                                .foregroundStyle(style.color)
                                .lineLimit(1)
                        }
                        Text("\(context.state.durationMin) min trip · \(context.state.summary)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                        HStack {
                            Link(destination: deepLink("start", context.attributes)) {
                                Label("Start", systemImage: "location.fill")
                                    .font(.caption.weight(.bold))
                                    .frame(maxWidth: .infinity).padding(.vertical, 6)
                                    .background(style.color, in: Capsule())
                                    .foregroundStyle(.white)
                            }
                            Link(destination: deepLink("customize", context.attributes)) {
                                Label("Customize", systemImage: "slider.horizontal.3")
                                    .font(.caption.weight(.bold))
                                    .frame(maxWidth: .infinity).padding(.vertical, 6)
                                    .background(.white.opacity(0.15), in: Capsule())
                            }
                        }
                    }
                }
            } compactLeading: {
                Image(systemName: "car.fill").foregroundStyle(style.color)
            } compactTrailing: {
                Countdown(departure: context.state.departure, isStale: context.isStale)
                    .font(.system(.caption, design: .rounded).weight(.bold))
                    .foregroundStyle(style.color)
                    .frame(maxWidth: 56)
            } minimal: {
                Image(systemName: "car.fill").foregroundStyle(style.color)
            }
            .widgetURL(deepLink("customize", context.attributes))
            .keylineTint(style.color)
        }
    }
}

extension MapayActivityAttributes {
    static var preview: MapayActivityAttributes {
        MapayActivityAttributes(routineId: "rt-fiu", leg: 0, fromName: "MMC", toName: "BBC")
    }
}

extension MapayActivityAttributes.ContentState {
    static var flood: Self {
        .init(departure: .now.addingTimeInterval(28 * 60), durationMin: 41, summary: "via SR-826 and I-95",
              hazardCount: 2, topHazardType: "flood", topHazardTitle: "Flooded street on NE 151st St")
    }
}

#Preview("Lock Screen", as: .content, using: MapayActivityAttributes.preview) {
    MapayLiveActivity()
} contentStates: {
    MapayActivityAttributes.ContentState.flood
}
