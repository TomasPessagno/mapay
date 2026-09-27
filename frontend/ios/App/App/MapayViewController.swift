import Capacitor
import UIKit

/// Registers the app-local plugins (SceneDelegate uses this instead of CAPBridgeViewController).
class MapayViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(MapayNativePlugin())
    }
}
