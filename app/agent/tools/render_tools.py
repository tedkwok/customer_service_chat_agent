"""Generative-UI render tools.

These are real backend tools the coordinator can call, but their effect is on
the FRONTEND: the agent event layer (app/agent/implementation.py) watches for
tool calls with these names and emits AG-UI TOOL_CALL_* events, and the
CopilotKit client renders the matching React component (registered via
useCopilotAction({name, render})) from the call arguments. Because the Redis
event bus is one-way, the backend synthesises the tool result itself — each
tool just returns a short confirmation string so the agent loop can continue.
"""

from langchain.tools import tool


RENDER_TOOL_NAMES = frozenset({
    "render_product_card",
    "render_membership_status",
    "render_purchase_summary",
    "render_refund_status",
})


@tool("render_product_card")
def render_product_card(product_id: str, product_name: str, product_price: float, stock_amount: int, note: str = "") -> str:
    """Display a product card component in the customer's chat UI.

       Use whenever you present a specific product to the customer: browsing
       results, price checks, stock checks, or a product the customer asks
       about. Render the card first, then summarise it in your text reply.

       Args:
         product_id: The product id from get_product_info (e.g. P001).
         product_name: The product's display name.
         product_price: The current unit price.
         stock_amount: The current stock amount.
         note: Optional one-line highlight (e.g. "Low stock", "New arrival").
    """
    return "Success: product card component displayed to the customer."


@tool("render_membership_status")
def render_membership_status(membership_level: str, account_balance: float, next_tier: str = "", next_tier_requirement: str = "") -> str:
    """Display the customer's membership status panel in the chat UI.

       Use when the customer asks about their membership level, account
       balance, or progress towards the next tier. Render the panel first,
       then summarise it in your text reply.

       Args:
         membership_level: The customer's current level (Basic/Silver/Gold/Platinum).
         account_balance: The customer's current account balance.
         next_tier: The next tier name, if one exists above the current level.
         next_tier_requirement: What is still needed to reach the next tier
           (e.g. "2,300 more spend and 3 more months of account age").
    """
    return "Success: membership status component displayed to the customer."


@tool("render_purchase_summary")
def render_purchase_summary(product_id: str, product_name: str, quantity: int, total_price: float, new_balance: float) -> str:
    """Display a purchase receipt summary component in the chat UI.

       Use immediately after a successful purchase to confirm to the customer
       exactly what was bought and the resulting balance. Render the summary
       first, then confirm in your text reply.

       Args:
         product_id: The purchased product id.
         product_name: The purchased product's display name.
         quantity: The quantity purchased.
         total_price: quantity x unit price actually charged.
         new_balance: The customer's account balance after the purchase.
    """
    return "Success: purchase summary component displayed to the customer."


@tool("render_refund_status")
def render_refund_status(purchase_id: str, status: str, eta_days: int = 0) -> str:
    """Display a refund request status component in the chat UI.

       Use when a refund request is submitted or the customer asks about a
       refund's progress. Render the status card first, then explain in your
       text reply.

       Args:
         purchase_id: The purchase record id being refunded.
         status: Current status — one of Submitted, PendingApproval,
           Approved, Rejected, Completed.
         eta_days: Expected days until the refund is completed (0 if unknown).
    """
    return "Success: refund status component displayed to the customer."
