# Front end

Vite + React + TypeScript SPA, styled after ProjectionLab, talking to the
FastAPI app in `src/api/`. It runs **alongside** the Streamlit dashboard —
Streamlit still owns agent chat, trade entry, position editing, the security
master and production jobs, and nothing was removed from it.

```bash
uv run invest-monitor serve   # API on :8000
npm run dev                   # UI  on :5173 (proxies to the API)
npm run build                 # tsc -b && vite build
```

## Screens

| View | Endpoint | Notes |
|---|---|---|
| `views/Dashboard.tsx` | `/dashboard` | Value series, donuts, stacked bars, holdings table |
| `views/Holdings.tsx` | `/dashboard` | Same payload, grouped by account or asset type |
| `views/Exposure.tsx` | `/exposure` | Look-through asset class + equity sector |
| `views/Risk.tsx` | `/risk` | Success ring, fan chart, trailing metrics |
| `views/Income.tsx` | `/income` | Projection by type, account and holding |

Routing is the URL hash (`#risk`), handled by `useHashView` in `App.tsx` —
so screens are deep-linkable and Back works. There is no router library.

## Things that will bite you

- **Every FastAPI router prefix must be listed in `vite.config.ts`.** A
  missing prefix falls through to Vite and the view shows "the API isn't
  responding" while the server is perfectly healthy. This has already
  happened twice; the list is commented for that reason.
- **Colours come from CSS custom properties, read at render time** via
  `cssVar()` in `lib.ts`. Charts are hand-built SVG, so they can't inherit
  colour — they read the token. `useThemeTick()` forces a re-render when the
  theme changes; without it charts keep the previous theme's palette.
- **Colour follows the entity, never its rank.** `colorForType()` maps a
  fixed slot per asset type, so re-sorting a donut by size never repaints a
  series. Don't index a palette array by position in a sorted list.
- **The categorical palette is validated, not chosen by eye.** Light and
  dark each have their own steps (dark is re-stepped against the dark
  surface, not an inverted flip) and both pass the six-checks validator in
  the `dataviz` skill — lightness band, chroma floor, CVD separation,
  normal-vision floor, contrast. Two blues adjacent in the order failed;
  that's why there's a rose. Re-run the validator before changing any of the
  `--c1`…`--c5` tokens.
- **`erasableSyntaxOnly` is on.** No constructor parameter properties
  (`constructor(readonly x: number)`), and React 19 has no global `JSX`
  namespace — import `ReactNode` instead of writing `JSX.Element`.

## Conventions

- Numbers use `.num` (`tabular-nums`); money goes through `usd()` or
  `compact()` in `lib.ts`, which put the sign outside the currency symbol
  (`-$315`, never `$-315`).
- Every view handles three states explicitly: error (with the command to
  start the API), loading skeleton, and loaded. `ApiError.status === 0`
  means the fetch never reached the server.
- Wide content scrolls in its own `.tablescroll`; the page body never
  scrolls sideways.
- Uncertainty is shown, not hidden. Where a number rests on incomplete data
  the view says so inline — the constant-holdings caveat on the Dashboard
  series, coverage badges on Exposure, excluded price points on Risk, the
  "paying nothing" card on Income. Don't quietly drop these when editing.
