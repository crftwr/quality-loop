"""Scripts run in the guest, from a run's stage - never imported on the host.

``launch.py`` starts a product's script in the desktop session with no console
window; ``screen_agent.py`` performs one screen operation there. Both use
only the standard library and the quality_loop files the stage carries
(`quality_loop.guest.Guest.stage`).
"""
