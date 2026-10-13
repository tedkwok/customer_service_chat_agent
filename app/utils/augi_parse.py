from pydantic import TypeAdapter

from ag_ui.core import BaseEvent, Event

# ag_ui.core.Event is the SDK's own discriminated union (keyed on the "type"
# literal). Validating against the BaseEvent base class directly would
# silently drop subtype-specific fields (delta, message_id, ...) on the Redis
# round-trip, so always parse through the union.
_event_adapter: TypeAdapter = TypeAdapter(Event)


def agui_obj_parse(response: str) -> BaseEvent:
    """Parse one AG-UI event from its JSON wire form, preserving the subtype."""
    return _event_adapter.validate_json(response)
