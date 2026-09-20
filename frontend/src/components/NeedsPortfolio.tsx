/** Shown when a per-portfolio screen is viewed under "All portfolios".
 *
 *  These screens are backed by endpoints that take a portfolio in the path
 *  and define no all-accounts form. Aggregating client-side would mean
 *  inventing a number the backend never computed — attribution windows
 *  differ per portfolio, so summing them is arithmetic on incomparable
 *  ranges. Asking is honest; guessing is not.
 */
export function NeedsPortfolio({ what }: { what: string }) {
  return (
    <div className="card state">
      <h2>Pick a portfolio</h2>
      <p>{what} is calculated per portfolio, so there’s no all-accounts view.</p>
      <p className="sub">Choose one under <b>Scope</b> in the sidebar.</p>
    </div>
  )
}
