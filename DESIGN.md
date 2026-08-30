# DESIGN.md

## Product

**imgw-merge-weather**

A self-hosted weather visualization tool for IMGW CMM MERGE precipitation forecasts.

The product should feel like a meteorological operations interface, not a generic homelab admin panel.

---

# Design Direction

Target visual language:

> Windy / RainViewer weather visualization combined with the restraint and information density of Grafana.

The UI should be:

- weather-first,
- map/image-first,
- dark,
- compact,
- technical,
- information-dense,
- timeline-driven,
- restrained,
- responsive.

Avoid:

- marketing-page layouts,
- giant SaaS cards,
- excessive gradients,
- excessive shadows,
- glassmorphism,
- decorative UI competing with the weather colors,
- large empty areas,
- oversized rounded corners.

The weather imagery is the colorful part of the application.

The surrounding interface should remain visually neutral.

---

# Primary User Question

The first screen should answer:

> What does the latest precipitation forecast look like?

Not:

> What background jobs are currently running?

Forecast ingestion, scheduler state, and video generation are operational capabilities, but they are secondary to the weather visualization.

---

# Main Layout

Desktop concept:

```text
┌───────────────────────────────────────────────────────────────┐
│ imgw-merge-weather      11:20 UTC        ● LIVE         ⚙    │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│                                                               │
│                    MERGE WEATHER VIEWER                       │
│                                                               │
│                    precipitation map                          │
│                                                               │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│ ◀  ▶   ━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━     │
│       11:20   12:00   12:50   14:00   ...        19:20       │
├────────────────────────────────────────────┬──────────────────┤
│ FORECAST RUNS                              │ CURRENT RUN      │
│                                            │                  │
│ ● 11:20  latest                           │ MERGE            │
│   11:10                                    │ 8 h              │
│   11:00                                    │ 10 min step      │
│   10:50                                    │ 49 frames        │
│                                            │ ~1 km            │
│                                            │ updated 2m ago   │
└────────────────────────────────────────────┴──────────────────┘
```

The weather viewer should occupy approximately:

```text
65–75%
```

of the immediately visible primary content area.

---

# Navigation

Keep navigation minimal.

Preferred top bar:

```text
imgw-merge-weather      Latest Forecast     History     ● LIVE
```

Potential future items:

```text
Videos
Settings
```

Do not introduce a large permanent sidebar unless the feature count genuinely requires it.

For the early application, a header + contextual side panel is preferable.

---

# Color System

Use very dark neutral charcoal surfaces.

Avoid strongly blue application chrome because precipitation maps already contain multiple strong colors.

Suggested tokens:

```css
:root {
  --bg: #090b0e;
  --surface: #101318;
  --surface-raised: #15191f;
  --surface-hover: #1b2027;

  --border: #242a32;
  --border-strong: #343b45;

  --text: #f4f6f8;
  --text-secondary: #a0a7b0;
  --text-subtle: #69727d;

  --accent: #64b5f6;
  --accent-muted: rgba(100, 181, 246, 0.15);

  --success: #56d364;
  --warning: #e3b341;
  --danger: #f85149;

  --radius-sm: 4px;
  --radius-md: 8px;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
}
```

Exact colors may be adjusted during implementation.

---

# Weather Color Rule

Do not reuse precipitation intensity colors as generic application state colors.

For example, if the source imagery uses:

```text
green
yellow
orange
red
```

for weather intensity, do not build a UI where every button/status also uses those same colors heavily.

Weather visualization should remain visually dominant and immediately readable.

---

# Typography

Preferred UI font:

```text
Inter
```

or:

```text
Geist
```

Preferred numeric/technical font:

```text
Geist Mono
JetBrains Mono
```

If avoiding bundled external fonts, use robust system fallbacks.

Use monospaced/tabular numerals for:

```text
11:20 UTC
29.08.2026
49 / 49
+03:00
1 km
5 FPS
```

Time should not visually jump as values update.

---

# Type Scale

Keep typography compact.

Suggested hierarchy:

```text
Page title        18–20 px
Section title     12–14 px uppercase / letter spacing
Primary timestamp 24–32 px
Body              13–14 px
Metadata          11–12 px
```

Avoid large marketing-style 48–72 px headings.

---

# Weather Viewer

The viewer is the primary component.

Render the selected run's newest completed forecast video inside a centered 1:1 stage.
The MP4 must preserve its source aspect ratio with `object-fit: contain`; fill the stage
and any unused viewer area with solid black rather than stretching or cropping
meteorological imagery. Raw IMGW JPEGs remain ingestion inputs and are not rendered by
the browser UI.

Responsibilities:

- show the selected run's forecast video,
- maintain video aspect ratio,
- allow fit-to-container,
- expose current frame time,
- expose forecast offset,
- support MP4 playback,
- support timeline selection,
- support historical run selection.

Do not distort imagery.

Use neutral background outside image bounds.

Example:

```text
┌─────────────────────────────────────────────┐
│                                             │
│            IMGW MERGE FRAME                 │
│                                             │
│                                             │
│  29 AUG 2026                  +03:20        │
│  12:50 UTC                                  │
└─────────────────────────────────────────────┘
```

Timestamp overlay may be in the UI outside the source image rather than modifying the remote image.

---

# Timeline

The forecast timeline should become a signature component of the product.

Basic:

```text
10:50 ━━ 11:50 ━━ 12:50 ━━ 13:50 ━━ 14:50 ━━ 15:50
                   ●
                 12:50
```

Requirements:

- horizontally scrollable on small screens,
- click to select,
- drag/scrub to select,
- selected marker,
- major hour labels,
- minor 10-minute ticks,
- keyboard accessibility where practical,
- optional playhead.

Display both:

```text
absolute time
forecast offset
```

where useful.

Example:

```text
12:50
+02:30
```

---

# Playback Controls

Keep controls compact.

Example:

```text
|◀   ◀   ▶   ▶|       5 FPS       LOOP
```

Initial capabilities:

- previous frame,
- play,
- pause,
- next frame,
- optional loop.

Avoid overly large media controls.

The custom weather controls operate the embedded MP4 directly. Timeline selection seeks
to the encoded forecast timestamp; previous/next step through encoded forecast times;
play/pause and keyboard controls operate the same video element. Avoid a second set of
native media controls in the primary viewer.

---

# NOW Boundary

When future RainGRS support exists, observation and forecast must be visually distinct.

Target:

```text
PAST / OBSERVED            FORECAST
────────────────────────────●────────────────────────────
                           NOW
```

Potential visual treatment:

- observed timeline slightly neutral,
- forecast timeline accent color,
- vertical NOW marker,
- explicit labels.

Never blur observed and forecast data into one unlabeled sequence.

---

# Freshness

Freshness is a primary UI signal.

Header example:

```text
● LIVE · updated 3m ago
```

Possible states:

```text
LIVE
FRESH
DELAYED
STALE
OFFLINE
```

Suggested initial thresholds:

```text
FRESH      < 15 min
DELAYED    15–60 min
STALE      > 60 min
```

Use compact status indicators.

Avoid huge alert banners unless data is genuinely unavailable.

---

# Current Run Metadata

Prefer compact metadata blocks instead of large cards.

Good:

```text
PRODUCT
MERGE

RANGE
8 h

STEP
10 min

FRAMES
49

RESOLUTION
~1 km
```

Bad:

```text
╭────────────────────────────╮
│                            │
│      Forecast range        │
│                            │
│          8 hours           │
│                            │
╰────────────────────────────╯
```

Use thin separators and small uppercase labels.

---

# Forecast Run Browser

The recent-run selector should be compact.

Example:

```text
FORECAST RUNS

● 11:20      latest
  11:10
  11:00
  10:50
  10:40
```

Each run may show:

- publication/discovery time,
- freshness,
- completion state,
- warning if incomplete.

Selecting another run should not feel like navigating to an entirely different application screen.

On desktop, use a side panel.

On mobile, use a bottom sheet or select control.

---

# Video Generation

Video generation is secondary.

Do not make the primary screen revolve around:

```text
GENERATE VIDEO
```

Instead:

```text
Latest forecast

[ Play ] [ Generate video ] [ More ]
```

Open configuration in a drawer or modal.

Suggested fields:

```text
Forecast run
Range
Animation speed
Motion smoothing
Output FPS (advanced)
Format
Timestamp overlay
```

Formats:

```text
Source
1:1
16:9
9:16
```

---

# Video Preset Preview

Show framing visually.

Example:

```text
┌─────────┐
│         │
│   1:1   │
│         │
└─────────┘

┌─────────────────┐
│      16:9       │
└─────────────────┘

┌───────┐
│       │
│  9:16 │
│       │
└───────┘
```

This is more useful than a plain text dropdown once multiple presets exist.

---

# Generated Videos

Generated videos should live in a secondary view/panel.

On initial load, rank forecast runs newest-first and open the newest run that owns a
completed MP4; artifact creation time must not make an older forecast appear newer.
When automatic video generation is enabled, each refreshed latest run receives one
default source MP4, and startup reconciles a missing video for the latest completed run.
When a selected forecast run has a completed video, its newest completed MP4 is embedded in the main
weather viewer. The browser UI is video-only: it does not request or display
individual IMGW JPEGs. Runs without a completed MP4 show an explicit generation or
rendering state. Generation history, metadata, deletion, and other job controls remain
in the secondary panel.

Display:

```text
29 Aug 2026
11:20 → 19:20

1:1 · 1080×1080
3 source frames/s · 30 FPS output
Crossfade
2.8 MB

[ Play ] [ Download ] [ Delete ]
```

For active rendering:

```text
Rendering MP4…
```

Use a thin progress bar.

Do not allow job-management UI to dominate the main forecast viewer.

---

# Cards and Surfaces

Use cards sparingly.

Preferred:

- thin borders,
- flat surfaces,
- small radius,
- compact padding.

Avoid:

- huge 24–32 px radii,
- heavy drop shadows,
- floating glass panels,
- nested cards inside cards.

Most sections can be separated by:

```text
border-top
border-left
spacing
```

rather than individual cards.

---

# Buttons

Buttons should be compact.

Primary button reserved for a genuinely primary action.

Examples:

```text
Generate video
Refresh
Download
```

Secondary icon buttons:

```text
play
pause
previous
next
more
```

Do not create a page full of bright accent buttons.

---

# Icons

Use a small consistent icon set.

Potential choices:

```text
Lucide
```

or handcrafted minimal SVGs.

Use icons for:

- play,
- pause,
- previous,
- next,
- download,
- refresh,
- settings,
- warning,
- delete.

Do not use icons as decoration where text is clearer.

---

# Loading States

Weather loading should preserve layout.

Use:

- image placeholder,
- subtle pulse if desired,
- fixed timeline area,
- status text.

Examples:

```text
Loading latest forecast…
Downloading 18 / 49 frames…
Rendering video…
```

Do not use fake loading delays.

---

# Error States

Errors must be explicit but compact.

Examples:

```text
Latest MERGE frame unavailable.
Last successful update: 11:10 UTC.
```

```text
Forecast run incomplete.
Missing: 14:20 UTC, 14:30 UTC.
```

```text
IMGW CMM is currently unreachable.
```

Provide retry action where relevant.

Never silently display stale data as if it were live.

---

# Empty State

If no weather run exists:

```text
No MERGE forecast has been collected yet.

[ Fetch latest forecast ]
```

Do not show generic illustration art.

---

# Responsive Design

## Desktop

Preferred layout:

```text
viewer
timeline
metadata + run browser
```

Use available horizontal space for forecast imagery.

## Tablet

- viewer full width,
- run browser below or collapsible,
- timeline scrollable.

## Mobile

Single-column layout:

```text
header
weather viewer
timestamp
controls
timeline
metadata
run selector
video actions
```

The weather frame must remain readable.

Timeline may horizontally scroll.

---

# Accessibility

Minimum requirements:

- keyboard-focusable timeline controls,
- visible focus states,
- sufficient contrast,
- labels for icon buttons,
- no status communicated only through color,
- use semantic buttons,
- useful image alt text where applicable.

For weather frames, alt text may include:

```text
IMGW MERGE precipitation forecast for 29 Aug 2026 at 12:50 UTC
```

---

# Motion

Use restrained motion.

Good:

- frame crossfade of 100–150 ms if it improves visual continuity,
- subtle panel transition,
- timeline playhead movement.

Avoid:

- bouncing,
- spring-heavy UI,
- decorative page transitions.

Animation should serve weather interpretation.

---

# Dashboard Anti-Pattern

Do not make the homepage:

```text
[144 jobs] [49 frames] [2.8 MB] [Server OK]

[Generate]

[Recent Jobs Table]
```

This is an operations dashboard pattern, but it does not serve the primary weather use case.

Instead:

```text
WEATHER
first

OPERATIONS
second
```

---

# Header

Suggested desktop header:

```text
imgw-merge-weather     MERGE · Poland      ● LIVE · updated 3m ago      ⚙
```

Potential metadata:

- current local time,
- current selected run,
- source status.

Keep height modest.

---

# Visual Identity

The project should not imitate IMGW branding.

Use a neutral technical identity.

Possible wordmark:

```text
imgw-merge-weather
```

with lowercase developer-tool styling.

Avoid creating an unofficial logo that could be mistaken for IMGW.

---

# Desired Overall Feel

The final application should feel like:

```text
meteorological instrument
+
developer/homelab tool
```

not:

```text
consumer weather app
```

and not:

```text
SaaS analytics dashboard
```

A user should be able to open the page, immediately see the newest precipitation forecast, scrub through time, understand how fresh the data is, and only then interact with administrative features such as video generation.
