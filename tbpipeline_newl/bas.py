"""Which TB80BAS layer a named export belongs to.

The prefix is the layer. This is a count for --list. It does not answer
the call, and the export stays in the DLL.
"""

LAYERS = ("HEAP", "STACK", "RESMGR", "CDB", "OBJ")


def layer_of(name):
    upper = name.upper()
    for layer in LAYERS:
        if upper.startswith(layer):
            return layer
    return ""


def count(imports, exports=None):
    """imports are ne.Import rows. exports is {ordinal: name} from TB80BAS,
    used when the import is by ordinal. Returns (counts, unnamed)."""
    exports = exports or {}
    counts = {layer: 0 for layer in LAYERS}
    counts["other"] = 0
    unnamed = 0
    for item in imports:
        if item.module.upper() != "TB80BAS":
            continue
        name = item.name or exports.get(item.ordinal, "")
        if not name:
            unnamed += 1
            continue
        counts[layer_of(name) or "other"] += 1
    return counts, unnamed
