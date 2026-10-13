// ---------------------------------------------------------------------------
// Generative UI: the backend agent calls render_* tools with verified facts;
// the AG-UI TOOL_CALL events drive these bound React components inside the
// chat. Plain render (not render-and-wait) — the backend synthesises the tool
// result itself, so the component is display-only.
// ---------------------------------------------------------------------------

interface ProductCardArgs {
  product_id?: string;
  product_name?: string;
  product_price?: number;
  stock_amount?: number;
  note?: string;
}

export function ProductCard({ args }: { args: ProductCardArgs }) {
  return (
    <div className="render-card">
      <h3>
        {args.product_name || "Product"}{" "}
        <span className="pill">{args.product_id || ""}</span>
      </h3>
      <div className="row">
        {args.product_price !== undefined && (
          <span>Price: <strong>{args.product_price.toFixed(2)}</strong></span>
        )}
        {args.stock_amount !== undefined && <span>In stock: {args.stock_amount}</span>}
        {args.note && <span className="pill">{args.note}</span>}
      </div>
    </div>
  );
}

interface MembershipStatusArgs {
  membership_level?: string;
  account_balance?: number;
  next_tier?: string;
  next_tier_requirement?: string;
}

export function MembershipStatus({ args }: { args: MembershipStatusArgs }) {
  return (
    <div className="render-card">
      <h3>
        Membership <span className="pill">{args.membership_level || "?"}</span>
      </h3>
      <div className="row">
        {args.account_balance !== undefined && (
          <span>Balance: <strong>{args.account_balance.toFixed(2)}</strong></span>
        )}
        {args.next_tier && <span>Next tier: {args.next_tier}</span>}
        {args.next_tier_requirement && <span>Still needed: {args.next_tier_requirement}</span>}
      </div>
    </div>
  );
}

interface PurchaseSummaryArgs {
  product_id?: string;
  product_name?: string;
  quantity?: number;
  total_price?: number;
  new_balance?: number;
}

export function PurchaseSummary({ args }: { args: PurchaseSummaryArgs }) {
  return (
    <div className="render-card">
      <h3>Purchase receipt</h3>
      <div className="row">
        <span>
          {args.quantity ?? "–"} × {args.product_name || "item"}{" "}
          <span className="pill">{args.product_id || ""}</span>
        </span>
        {args.total_price !== undefined && (
          <span>Total: <strong>{args.total_price.toFixed(2)}</strong></span>
        )}
        {args.new_balance !== undefined && (
          <span>New balance: <strong>{args.new_balance.toFixed(2)}</strong></span>
        )}
      </div>
    </div>
  );
}

interface RefundStatusArgs {
  purchase_id?: string;
  status?: string;
  eta_days?: number;
}

export function RefundStatus({ args }: { args: RefundStatusArgs }) {
  return (
    <div className="render-card">
      <h3>
        Refund <span className="pill">{args.status || "unknown"}</span>
      </h3>
      <div className="row">
        {args.purchase_id && <span>Purchase: {args.purchase_id}</span>}
        {args.eta_days ? <span>ETA: ~{args.eta_days} day(s)</span> : null}
      </div>
    </div>
  );
}

// Maps an AG-UI tool-call name to its bound component. Args arrive as the
// JSON parsed from the accumulated TOOL_CALL_ARGS deltas.
export function RenderToolComponent({
  name,
  args,
}: {
  name: string;
  args?: Record<string, unknown>;
}) {
  switch (name) {
    case "render_product_card":
      return <ProductCard args={(args ?? {}) as ProductCardArgs} />;
    case "render_membership_status":
      return <MembershipStatus args={(args ?? {}) as MembershipStatusArgs} />;
    case "render_purchase_summary":
      return <PurchaseSummary args={(args ?? {}) as PurchaseSummaryArgs} />;
    case "render_refund_status":
      return <RefundStatus args={(args ?? {}) as RefundStatusArgs} />;
    default:
      return (
        <div className="render-card">
          <div className="row">
            <span className="pill">⚙ {name}</span>
          </div>
        </div>
      );
  }
}
