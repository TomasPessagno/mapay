import ActivityKit
import Foundation

// The heads-up Live Activity (#37). Compiled into both the app (starts it) and MapayWidget (draws it).
struct MapayActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        var departure: Date
        var durationMin: Int
        var summary: String       // "via SR-826 and I-95"
        var hazardCount: Int
        var topHazardType: String? // docs/design.md hazard key: flood, construction, …
        var topHazardTitle: String?
    }

    var routineId: String
    var leg: Int
    var fromName: String
    var toName: String
}
