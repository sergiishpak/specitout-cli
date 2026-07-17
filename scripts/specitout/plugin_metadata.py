from __future__ import annotations

KNOWN_BUBBLE_PLUGIN_NAMES = {
    "1529535510382x166541069778419700": "myAlerts!",
    "1631898919530x371869522674581500": "Audio Recorder",
    "1580238841425x582072028873097200": "Rich Text Editor",
    "1624452847207x422862489544294400": "Air Native plugin by Zeroqode",
    "1587152243584x838254107788574700": "Custom Audio Player",
    "1608827595218x711669301717762000": "1T - CSV Uploader",
}


def enrich_plugin_label(plugin_id: str) -> str:
    if plugin_id in {"ionic", "select2", "appconnector", "apiconnector2", "materialicons"}:
        return plugin_id
    url = f"https://bubble.io/plugin/{plugin_id}"
    display_name = KNOWN_BUBBLE_PLUGIN_NAMES.get(plugin_id)
    if display_name:
        return f"{display_name} ({plugin_id}) - {url}"
    return f"{plugin_id} - {url}"


def known_plugin_id_for_label(label: str) -> str | None:
    normalized = _normalize(label)
    for plugin_id, display_name in KNOWN_BUBBLE_PLUGIN_NAMES.items():
        if normalized in {_normalize(plugin_id), _normalize(display_name)}:
            return plugin_id
    return None


def _normalize(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").lower().split())
