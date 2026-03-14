def normalize_location_label(label: str) -> str:
    txt = str(label or "").strip().lower()
    if not txt:
        return ""
    out = []
    for ch in txt:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    norm = " ".join("".join(out).split())
    if norm in ("jita", "jita iv moon 4 caldari navy assembly plant", "jita 44", "jita 4 4", "jita44"):
        return "jita"
    if norm == "1st" or norm.startswith("1st "):
        return "1st"
    if norm in ("ualx", "ualx 3", "ualx3"):
        return "ualx"
    if norm in ("o 4t", "o4 t"):
        return "o4t"
    if norm in ("c j6mt", "cj6mt", "c j 6mt", "cj6", "c j6", "c j 6"):
        return "c_j6mt"
    return norm


def label_to_slug(label: str) -> str:
    s = (label or "").strip().lower()
    if not s:
        return "unknown"
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif ch.isspace():
            out.append("_")
    slug = "".join(out).strip("_")
    return slug or "unknown"


def normalize_pair_key(src: str, dst: str) -> tuple[str, str]:
    return normalize_location_label(src), normalize_location_label(dst)
