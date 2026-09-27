import type { CapacitorConfig } from '@capacitor/cli';
import { KeyboardResize } from '@capacitor/keyboard';

// Bundle ids are fixed for the whole event (AltStore allows 10 new App IDs per week).
// The widget extension uses `${appId}.widget`, set in Xcode.
const config: CapacitorConfig = {
  appId: 'com.tomaspessagno.mapay',
  appName: 'Mapay',
  webDir: 'dist',
  ios: {
    contentInset: 'never',
    // The web view itself never scrolls; Ionic's scroll containers do. Stops the keyboard from pushing the page up.
    scrollEnabled: false,
  },
  plugins: {
    // The keyboard overlays the app instead of resizing it, so the map and the tab bar stay put.
    Keyboard: {
      resize: KeyboardResize.None,
    },
  },
};

export default config;
