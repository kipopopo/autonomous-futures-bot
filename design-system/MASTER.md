# Autonomous Futures Bot — Dashboard Design System

## Product type

Operational analytics / paper-safe futures research dashboard.

## Design direction

**Accessible dark control room with restrained data density.** The interface should feel observational, calm, and trustworthy—not like a trading casino.

Primary principles:

- real persisted API data only;
- paper-safe and read-only status always visible;
- evidence freshness and verification before visual polish;
- no neon gradients, gamification, flashing prices, or decorative chart noise;
- `—` means unavailable, `0` means actual zero, `STALE` means freshness failure, and `ERROR` means request failure;
- no metric is rendered from a fabricated fallback.

## Information architecture

Phase 2d contains one page only:

```text
Overview
├── safety/status rail
├── verified dataset identity
├── component coverage summary
├── queryable artifact inventory
└── explicit loading / empty / error states
```

Future pages must not be scaffolded in this phase.

## Color tokens

Tailwind v4-compatible HSL variables. All semantic states include text labels; color is never the only indicator.

```css
:root {
  --background: 222 24% 7%;
  --foreground: 210 25% 94%;
  --surface: 222 22% 10%;
  --surface-raised: 222 20% 13%;
  --surface-muted: 222 18% 16%;
  --border: 217 18% 24%;
  --border-subtle: 217 16% 18%;
  --text-secondary: 214 14% 70%;
  --text-muted: 214 12% 52%;
  --primary: 190 82% 55%;
  --primary-foreground: 222 30% 8%;
  --positive: 151 58% 48%;
  --negative: 4 72% 62%;
  --warning: 40 92% 62%;
  --info: 214 86% 68%;
  --ring: 190 82% 55%;
}
```

Contrast targets:

- normal text: WCAG AA 4.5:1 minimum;
- large text and UI boundaries: 3:1 minimum;
- avoid using `--text-muted` for essential information;
- positive/negative values include `POSITIVE` / `NEGATIVE` or an icon plus text.

## Typography

```text
Primary: Inter, ui-sans-serif, system-ui, sans-serif
Monospace: JetBrains Mono, ui-monospace, SFMono-Regular, monospace
```

Scale:

```text
page title       1.5rem / 1.2 / 650
section title    0.95rem / 1.3 / 650
metric value     1.35rem / 1.1 / 650
body             0.875rem / 1.5 / 400
label            0.72rem / 1.3 / 650 / 0.08em uppercase
micro metadata   0.72rem / 1.4 / 400
```

## Layout and spacing

```text
max width: 1440px
page padding: 24px desktop, 16px mobile
layout gap: 16px
card padding: 20px
card radius: 12px
control min-height: 44px
```

Responsive behavior:

- 320px: single-column cards, no horizontal overflow;
- 768px: two-column summary grid;
- 1100px: desktop sidebar + content grid;
- 1440px: capped readable content width, no stretched metric cards.

## Components

### Safety rail

Always visible above the fold:

```text
PAPER-SAFE · READ-ONLY · EXECUTION AUTHORITY: OFF
```

Use a bordered surface, not a blinking badge. Include API/catalog verification state and last successful refresh when available.

### Metric card

A metric card must contain:

```text
label
value or —
source / scope metadata
state label when unavailable or stale
```

Never show a guessed value, percentage, chart, or “healthy” state without API evidence.

### Artifact inventory

Use a compact semantic table/list:

```text
kind · symbol · interval · time coverage · rows · verification
```

Mobile layout changes rows into stacked key/value blocks; it does not hide verification state.

### Empty and error states

```text
Loading:       skeleton with aria-label="Loading verified dataset"
No data:       "No verified dataset is available for this scope."
Error:         "Dataset verification failed. No unverified data is shown."
Stale:         "Last verified refresh is stale."
```

## Motion

- default transitions: 150–200ms;
- no continuous decorative animation;
- respect `prefers-reduced-motion: reduce`;
- data refresh must not animate values in a way that implies market movement;
- Magic UI effects are limited to subtle border/entrance treatment and are disabled under reduced motion.

## Accessibility checklist

- semantic `header`, `nav`, `main`, `section`, and table/list structure;
- one `h1`, ordered heading hierarchy;
- keyboard-visible 3px focus ring;
- icon-only controls require accessible labels;
- minimum 44px interactive target;
- status text accompanies every semantic color;
- no auto-refresh control is the only way to discover freshness;
- screen reader announcement only for meaningful refresh/error changes;
- test at 320px, 768px, and 1440px.

## API boundary

The Overview page may call only:

```text
GET /health
GET /api/v1/dataset/bundle
GET /api/v1/dataset/components
```

The page must not call row queries until a later page explicitly needs a bounded time-series view. No POST, order, account, signal, or execution route belongs in this shell.

## Anti-patterns explicitly rejected

- fake `0.00%` returns or fabricated trade counts;
- hard-coded “latest update” timestamps;
- green “online” status when catalog verification failed;
- free-form order form or Buy/Sell buttons;
- neon green/red price ticker styling;
- unlabelled timezone display;
- decorative Magic UI components that compete with evidence;
- hidden error states behind an empty card.
