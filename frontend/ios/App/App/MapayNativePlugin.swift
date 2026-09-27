import ActivityKit
import Capacitor
import Foundation

/// App-local Capacitor plugin (#37): starts, updates and ends the heads-up Live Activity.
/// JS: `registerPlugin('MapayNative')`, see src/headsup/liveActivity.ts.
@objc(MapayNativePlugin)
public class MapayNativePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MapayNativePlugin"
    public let jsName = "MapayNative"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "startLiveActivity", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "endLiveActivity", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "areActivitiesEnabled", returnType: CAPPluginReturnPromise),
    ]

    /// How long a Live Activity stays up after its departure time.
    private static let lingerAfterDeparture: TimeInterval = 10 * 60

    @objc func areActivitiesEnabled(_ call: CAPPluginCall) {
        call.resolve(["enabled": ActivityAuthorizationInfo().areActivitiesEnabled])
    }

    /// Starts the Live Activity for a leg, or updates it if that leg's is already running.
    /// Any other leg's activity is ended, so only one heads-up is ever up.
    @objc func startLiveActivity(_ call: CAPPluginCall) {
        guard let routineId = call.getString("routineId"),
              let leg = call.getInt("leg"),
              let departureMs = call.getDouble("departureMs") else {
            call.reject("routineId, leg and departureMs are required")
            return
        }
        let attributes = MapayActivityAttributes(
            routineId: routineId,
            leg: leg,
            fromName: call.getString("fromName") ?? "",
            toName: call.getString("toName") ?? ""
        )
        let departure = Date(timeIntervalSince1970: departureMs / 1000)
        let state = MapayActivityAttributes.ContentState(
            departure: departure,
            durationMin: call.getInt("durationMin") ?? 0,
            summary: call.getString("summary") ?? "",
            hazardCount: call.getInt("hazardCount") ?? 0,
            topHazardType: call.getString("topHazardType"),
            topHazardTitle: call.getString("topHazardTitle")
        )
        let content = ActivityContent(state: state, staleDate: departure)

        Task {
            for activity in Activity<MapayActivityAttributes>.activities {
                let same = activity.attributes.routineId == routineId && activity.attributes.leg == leg
                let expired = activity.content.state.departure.addingTimeInterval(Self.lingerAfterDeparture) < .now
                if same && !expired {
                    await activity.update(content)
                    call.resolve(["id": activity.id, "updated": true])
                    return
                }
                await activity.end(nil, dismissalPolicy: .immediate)
            }
            guard ActivityAuthorizationInfo().areActivitiesEnabled else {
                call.reject("Live Activities are turned off for Mapay")
                return
            }
            do {
                let activity = try Activity.request(attributes: attributes, content: content, pushType: nil)
                call.resolve(["id": activity.id, "updated": false])
            } catch {
                call.reject("Couldn't start the Live Activity: \(error.localizedDescription)")
            }
        }
    }

    /// Ends the activity for `routineId`/`leg`, or every Mapay activity when they're omitted.
    @objc func endLiveActivity(_ call: CAPPluginCall) {
        let routineId = call.getString("routineId")
        let leg = call.getInt("leg")
        Task {
            for activity in Activity<MapayActivityAttributes>.activities
            where (routineId == nil || activity.attributes.routineId == routineId) && (leg == nil || activity.attributes.leg == leg) {
                await activity.end(nil, dismissalPolicy: .immediate)
            }
            call.resolve()
        }
    }
}
