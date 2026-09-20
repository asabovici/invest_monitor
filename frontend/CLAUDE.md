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

Routing is the URL hash, handled by `useHashRoute` in `App.tsx` — so
screens are deep-linkable and Back works. There is no router library. The
hash carries the scope as well as the view (`#risk?portfolio=SCHAB`), so a
scoped screen is as linkable as an unscoped one.

## Scope

The rail's **Scope** group picks one portfolio or All. All is `null`, which
means the `portfolio` param is omitted and the API serves every account —
so the unscoped request is byte-identical to the one that existed before
scoping. Every view takes `portfolio: string | null` and passes it to its
fetcher; nothing else about a view changes with scope except the three
places noted below.

Portfolios with no positions are left out of the selector. The live dataset
has six, and scoping to one shows $0 on the Dashboard and a 400 on the
other three screens. A direct link to one still resolves — the filter only
decides what the rail offers.

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
- **Three views degenerate under a scope, and handle it.** Grouping by
  account is meaningless when every holding shares one: the Dashboard and
  Income by-account donuts are hidden, and Holdings forces asset-type
  grouping and drops the toggle. `.cols` is `auto-fit`, so the surviving
  card widens by itself — don't add a width override.
- **A non-zero `ApiError.status` is not "the API is down."** Scoping made
  404 (no such portfolio) and 400 (real but empty) reachable on every
  screen, so the "start it with `invest-monitor serve`" hint renders only
  when `status === 0`. Keep that guard when editing an error card.
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
