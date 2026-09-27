# Mapay design spec

**Direction: Apple-like.** Mapay should feel like it came with the iPhone: Apple Maps' layout, the calm confidence of Weather, and Duolingo's friendly nudge. We follow Apple's Human Interface Guidelines and the current iOS look (Liquid Glass, since iOS 26): content first, controls floating on translucent glass, rounded shapes.

> **Maybe later:** IBM Carbon's data-visualization style (IBM Plex, Carbon Charts) could suit dense data screens such as corridor history or stats. It's parked; for now everything follows this spec.

---

## Principles

1. **Map first.** The map fills the screen. Everything else floats above it or lives in a bottom sheet.
2. **One glance.** Answer "when do I leave, and what's in the way?" in one look: a time, the top two hazards, one primary button.
3. **Quiet interface, loud data.** The interface uses system greys, glass and one tint (blue). Colour is saved for hazards and the route.
4. **Honest.** Every hazard shows its source and time: the news story, the satellite pass, the report.
5. **Native behaviour.** Standard gestures, sheets and haptics. Dynamic Type, Dark Mode, Reduce Motion and Reduce Transparency are respected.

---

## How we build it

| Surface | Built with | Why |
| --- | --- | --- |
| App screens | React + **Ionic React in iOS mode**, inside Capacitor | Ionic ships iOS-style components (sheets with detents, grouped lists, segmented controls, toggles, tab bar), and the UI can be built in a browser without the Mac |
| Map | Google Maps JavaScript API with light + dark cloud-styled Map IDs | Routes and places come from Google, and Google's terms require showing them on a Google map |
| Home-screen + Lock Screen widgets, Live Activity | SwiftUI (WidgetKit, ActivityKit) in **one** widget extension | Only native code can draw these; one extension keeps us inside AltStore's 3-app limit |
| Notifications | iOS local notifications (Capacitor Local Notifications) | Standard iOS banner, attached image and long-press actions |
| Icons | SF Symbols in the native pieces; Ionicons (iOS style) in the web UI | SF Symbols are licensed for Apple-platform UI, and the web build also runs in browsers |

---

## Layout

### Tab bar

Three tabs: **Map**, **Routines**, **Preferences**. Floating glass tab bar; Map is the default tab.

### Map (home)

- Full-screen map with a muted style (soft land, grey roads, calm water) so hazard colours stand out. The dark style follows the system.
- **Bottom sheet**, Apple Maps style, with three detents:
  - *Small:* search field "Where to?" and a chip for the next leg ("MMC → BBC · 9:30 AM").
  - *Medium:* the heads-up card when a leg is due; otherwise "Around you" (nearby hazards) and today's conditions (tide, rain).
  - *Large:* full lists, hazard details, search results.
- **Floating controls** (top right, glass, 44 pt): Layers, Locate me, Report (+).
- The Layers sheet is also the legend: each row has the colour swatch, icon, name and an on/off switch.

### Route

- After picking a destination, the sheet shows route options as cards: trip time (large), distance, hazard chips ("2 floods · 1 closure") and a "Recommended" tag on Mapay's pick.
- Chosen route: blue line with a white casing. Alternatives: the same blue at 45 % opacity.
- **Focus mode:** hazards more than ~150 m from the chosen route fade to 30 %; hazards on the route get an icon badge along the line.
- Primary button (full width, filled blue, capsule): **Open in Google Maps**. Secondary text button: Apple Maps (origin → destination only).

### Hazard detail (sheet, medium)

Icon in its category colour, title ("Flooded street") and place, then one line each for:
- source with link ("NBC6 · 40 min ago", "Sentinel-1 pass · Sep 26, 6:14 AM");
- confidence ("High", "Unconfirmed");
- when it expires.

Satellite items also show before/after images.

### Routines tab

- iOS grouped (inset) list. Each routine is a group: name, legs ("MMC → BBC · 9:30 AM", "BBC → MMC · 5–7 PM"), repeat ("Weekdays") and an on/off switch.
- **Routine editor** (grouped form):
  - Places: From / To rows with search.
  - Legs: each leg opens a leg editor with a segmented control **At | Between** and compact time pickers. An "Add the way back" button creates the reverse leg.
  - Repeat: Every day / Every week (pick the day) / Custom (weekday chips S M T W T F S).
  - Heads-up: 15 / 30 / 45 / 60 min before (default 30).
  - Preferences for this routine: "Use my defaults" or override.
  - Arrive by: hidden until it ships.

### Preferences tab

- One row per hazard type: icon, colour, name and a pop-up menu **Avoid / Prefer to avoid / Don't care**.
- Neighbourhoods to avoid: token field with search ("Brickell ×").
- Toggles: avoid tolls, avoid highways.
- Navigate with: Google Maps (default, keeps Mapay's waypoints), Apple Maps or Waze (origin → destination only).

### Customize (sheet, large)

- Multi-line text field, placeholder "e.g. stop at a Starbucks and stay off the Palmetto", with suggestion chips: Add a stop, Avoid floods, Leave later, Avoid a neighbourhood.
- Result: old and new route cards side by side, a 1–2 sentence explanation in secondary text, and the primary **Open in Google Maps** button.

---

## The heads-up (the Duolingo moment)

The same content everywhere: route, leave time + countdown, trip time, top hazards, **Start** and **Customize**. The star is the **Live Activity** on the Lock Screen, styled like Duolingo's streak banner: loud, colourful and impossible to miss.

| Surface | Look |
| --- | --- |
| In-app card | Top of the map sheet, which rises to medium. Large rounded card (corner radius 26) with a big countdown in SF Pro Rounded ("Leave in 28 min"), the route in Title 2, two hazard rows with icon chips, and two buttons: filled blue **Start**, tinted **Customize**. Warning haptic when it appears with hazards. |
| Local notification | Title "MMC → BBC · leave in 30 min", body with the top 2 hazards, route image attached. Long-press shows **Start** / **Customize**. |
| Home-screen widget | **Large** (4 × 4) is the Duolingo-style one. Idle: next leg and time. Heads-up: tinted background, big countdown (`Text(date, style: .timer)`), top 3 hazards, Start / Customize. **Medium:** route, countdown, top hazard, both buttons. **Small:** leave time + hazard count. |
| Lock Screen widgets (P1) | Rectangular: "Leave 9:30 AM · 2 hazards". Inline: "MMC → BBC 9:30 AM". Circular: countdown ring. |
| Live Activity (P0, the main one) | Lock Screen banner like Duolingo's: a gradient background tinted by the top hazard's colour (system blue with no hazards), white text, a big SF Pro Rounded countdown ("0:28:12 left to leave for BBC"), the route and trip time, the hazard count with the top hazard's symbol, and a large SF Symbols illustration on the right (car + hazard glyph) instead of a mascot. Dynamic Island: compact = car symbol + countdown; expanded = route, countdown, top hazard, Start / Customize. It starts whenever the app is opened within 8 h of a leg (no server push with a free Apple ID), from the T−30 notification, and from the demo button. |

Widget rules:
- Support the tinted and clear Home Screen styles: mark the key elements `widgetAccentable()`. Hazard colours get flattened there, so icons and shapes must carry the meaning.
- Buttons are deep links: `mapay://start?routine=…&leg=…` and `mapay://customize?routine=…&leg=…`.
- Empty state: "Add a routine" with a link into the Routines tab.

---

## Visual tokens

### Colour

- **Interface:** iOS system colours only: `label`, `secondaryLabel`, `tertiaryLabel`, `systemBackground`, `secondarySystemBackground`, `systemGroupedBackground`, `separator`. Tint = system blue. In the web view, Ionic's iOS theme provides these; define matching CSS variables for light and dark.
- **Route:** system blue `#007AFF` (dark `#0A84FF`).
- **Hazards:** Apple's system hues, so the data palette feels native. Native code uses the system colours directly (`Color(.systemCyan)` etc.) so they track the OS; the web view uses these values:

| Hazard | Colour | Light | Dark | Drawn as |
| --- | --- | --- | --- | --- |
| Flooded street | Cyan | `#32ADE6` | `#64D2FF` | Wide translucent band on streets + areas with outline, water-waves icon |
| Heavy rain / weather alert | Indigo | `#5856D6` | `#5E5CE6` | Translucent area (25 %), no outline, cloud-rain icon |
| Construction | Orange | `#FF9500` | `#FF9F0A` | Cone icon + area outline |
| Road closure | Label | `#1C1C1E` | `#F2F2F7` | Dashed line + no-entry icon |
| Congestion | Yellow → red → dark red | `#FFCC00` → `#FF3B30` → `#A50E0E` | same, 1 pt wider | Line along the road |
| No sidewalk | Purple | `#AF52DE` | `#BF5AF2` | Dotted line, zoom ≥ 15 only |
| Pothole | Brown | `#A2845E` | `#AC8E68` | Small dot |
| Incident / police / news | Pink | `#FF2D55` | `#FF375F` | Pin with `!` |
| Event / holiday | Green | `#34C759` | `#30D158` | Pin with calendar icon |

- Colour is never the only signal: every hazard also has its icon and line style.
- Points get a 1.5 pt halo: white in light mode, black in dark mode.
- Never put text on a hazard colour without checking contrast (≥ 4.5:1).
- The reference picture is [`legend.svg`](legend.svg); the tokens live in `frontend/src/map/legend.ts`.

### Typography

System font (SF Pro) everywhere: `-apple-system` in CSS. SF Pro Rounded (`ui-rounded` in CSS) for countdowns and big numbers. iOS text styles at the default size:

| Style | Size / line (pt) | Weight | Used for |
| --- | --- | --- | --- |
| Large Title | 34 / 41 | Bold | Tab titles |
| Title 2 | 22 / 28 | Bold | Heads-up route, sheet titles |
| Title 3 | 20 / 25 | Semibold | Card titles |
| Headline | 17 / 22 | Semibold | Row titles, buttons |
| Body | 17 / 22 | Regular | Text |
| Callout | 16 / 21 | Regular | Explanations |
| Subheadline | 15 / 20 | Regular | Secondary rows |
| Footnote | 13 / 18 | Regular | Sources, timestamps |
| Caption 1 | 12 / 16 | Regular | Chips, legend |
| Caption 2 | 11 / 13 | Regular | Map labels |

Dynamic Type: turn on Ionic's dynamic font scaling (built on `-apple-system-body`). The native pieces use the text styles directly.

### Shape, spacing and materials

- 4 pt grid, 16 pt side margins, list rows ≥ 44 pt, touch targets ≥ 44 × 44 pt.
- Corners: cards 22–26 pt; buttons and chips are capsules; map controls are circles.
- Glass on floating controls, the sheet header and the tab bar: `background: rgb(255 255 255 / 0.72)` (dark: `rgb(28 28 30 / 0.72)`) with `backdrop-filter: saturate(180%) blur(20px)` plus the `-webkit-` prefix. Solid fallback when Reduce Transparency is on.
- Shadows: soft and rare, floating controls only.

### Motion and haptics

- Sheets and cards use Ionic's iOS spring animations. No custom bouncy effects; respect Reduce Motion.
- Haptics (`@capacitor/haptics`): selection tick on sheet detents and segmented controls, success when a route opens, warning when the heads-up appears with hazards.

---

## Copy

- Short, calm and friendly: "Leave in 25 min." "Flooding near BBC. We'll route you around it." Sentence case, no exclamation marks in alerts.
- Times and units follow the device locale (in the US: "9:30 AM", miles).
- Say where data came from and how fresh it is; say "predicted" when it's a prediction.

## Accessibility

- VoiceOver labels on every map item and control, e.g. "Flooded street on NE 2nd Ave, high confidence, observed 2 hours ago".
- Text contrast ≥ 4.5:1; colour is never the only signal.
- Dynamic Type up to the accessibility sizes without truncating the heads-up buttons.
