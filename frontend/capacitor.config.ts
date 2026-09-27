import type { CapacitorConfig } from '@capacitor/cli';

// Bundle ids are fixed for the whole event (AltStore allows 10 new App IDs per week).
// The widget extension uses `${appId}.widget`, set in Xcode.
const config: CapacitorConfig = {
  appId: 'com.tomaspessagno.mapay',
  appName: 'Mapay',
  webDir: 'dist',
  ios: {
    contentInset: 'never',
  },
};

export default config;
