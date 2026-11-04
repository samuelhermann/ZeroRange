"""Coffee web routes.

The page, SSE stream and status API come from app/web/scenario_blueprint.py.
``emit_event`` is kept for backward compatibility with external scripts: it
now publishes through the cross-process event bus.
"""

from app.core.events import EventBus

emit_event = EventBus("coffee")
