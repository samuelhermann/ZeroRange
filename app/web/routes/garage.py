"""Garage web routes: generic scenario blueprint + a debug endpoint."""

from app.core.events import EventBus

emit_event = EventBus("garage")


def extend(bp) -> None:
    @bp.route("/debug/send-press", methods=["POST"])
    def debug_send_press():
        """[DEBUG] Trigger a synthetic press_emitted event (no score change)."""
        bp.event_bus({"event": "press_emitted", "counter": 0, "debug": True})
        return "", 204
