"""Garage web routes: generic scenario blueprint + a debug endpoint."""

from app.core.events import EventBus

emit_event = EventBus("garage")


def extend(bp) -> None:
    from app.web.dashboard import requires_trainer_no_csrf

    @bp.route("/debug/send-press", methods=["POST"])
    @requires_trainer_no_csrf
    def debug_send_press():
        """[DEBUG] Trigger a synthetic press_emitted event (no score change)."""
        bp.event_bus({"event": "press_emitted", "counter": 0, "debug": True})
        return "", 204
