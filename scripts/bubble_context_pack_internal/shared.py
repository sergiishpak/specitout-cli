import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .constants import (
    EXPRESSION_NON_SOURCE_TYPES,
    EXPRESSION_SOURCE_TYPES,
    NAMED_COLLECTION_KEYS,
    STOPWORDS,
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with Path(path).open() as handle:
        return json.load(handle)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def is_bubble_collection(value):
    return isinstance(value, dict) and "length" in value


def iter_named_collection(name, value):
    if not isinstance(value, dict):
        return []
    if is_bubble_collection(value):
        return [(key, child) for key, child in value.items() if key != "length"]
    if name not in NAMED_COLLECTION_KEYS:
        return []
    return [(key, child) for key, child in value.items() if key != "length"]


def normalize_string(value):
    if value is None:
        return ""
    value = str(value).strip().lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def slugify(value):
    value = normalize_string(value)
    if not value:
        return "unnamed"
    return value.replace(" ", "-")


def slugify_identifier(value):
    value = str(value).strip()
    if not value:
        return "unnamed"
    value = re.sub(r"[^A-Za-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "unnamed"


def stable_source_suffix(value):
    raw = str(value)
    visible = slugify_identifier(raw).lower()
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{visible}-{digest}"


def make_synthetic_source_id(entity_type, source_path, local_key=None):
    parts = ["synthetic", entity_type, source_path]
    if local_key is not None:
        parts.append(str(local_key))
    return "::".join(parts)


def build_entity_key(entity_type, display_name, source_id, compact=False):
    display_slug = slugify(display_name)[:80] or "unnamed"
    raw_source = str(source_id)
    if compact or len(raw_source) > 80:
        digest = hashlib.sha1(raw_source.encode("utf-8")).hexdigest()[:12]
        return f"{entity_type}:{display_slug}--{digest}"
    return f"{entity_type}:{display_slug}--{stable_source_suffix(raw_source)}"


def tokenize_text(value):
    normalized = normalize_string(value)
    if not normalized:
        return []
    return [token for token in normalized.split() if token and token not in STOPWORDS]


def unique_list(values):
    seen = set()
    ordered = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def unique_list_of_dicts(rows):
    seen = set()
    ordered = []
    for row in rows:
        key = json.dumps(row, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(row)
    return ordered


def canonical_hash(value):
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def looks_like_expression_node(value):
    if not isinstance(value, dict):
        return False
    type_name = value.get("type")
    if not isinstance(type_name, str):
        return False
    if any(key in value for key in {"is_slidable", "next", "args", "said"}):
        return True
    if type_name.endswith("Expression"):
        return True
    if type_name in EXPRESSION_SOURCE_TYPES | EXPRESSION_NON_SOURCE_TYPES:
        return True
    return False


def classify_data_source_node(value):
    if not isinstance(value, dict):
        return None
    type_name = value.get("type")
    if not isinstance(type_name, str):
        return None
    if type_name in EXPRESSION_SOURCE_TYPES:
        return type_name
    if type_name.startswith("Current") or type_name.endswith("Data"):
        return type_name
    if type_name in {"GetElement", "ThisElement", "ElementParent", "ParentGroup", "InjectedValue", "PreviousStep"}:
        return type_name
    return None


def keyword_matches(keyword, token_set, normalized_text):
    normalized_keyword = normalize_string(keyword)
    if not normalized_keyword:
        return False
    if " " in normalized_keyword:
        return normalized_keyword in normalized_text
    return normalized_keyword in token_set


def classify_index_path(path):
    if path.startswith("styles."):
        return "style"
    if ".%wf." in path:
        return "workflow"
    if path.startswith("%p3."):
        return "page"
    if path.startswith("%ed."):
        return "component"
    if path.startswith("mobile_views."):
        return "mobile_view"
    return path.split(".", 1)[0]


def normalize_index_path_tokens(tokens):
    normalized = []
    for token in tokens:
        if token == "workflows":
            normalized.append("%wf")
        elif token == "elements":
            normalized.append("%el")
        else:
            normalized.append(token)
    return normalized


def count_collection_items(value):
    return len(iter_named_collection("__", value))


def safe_json_loads(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def redact_secret_value(value):
    if value in (None, "", False):
        return value
    if isinstance(value, str):
        return {
            "redacted": True,
            "length": len(value),
            "prefix": value[:4] if len(value) >= 4 else value,
            "suffix": value[-4:] if len(value) >= 4 else value,
        }
    if isinstance(value, dict):
        return {key: redact_secret_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [redact_secret_value(item) for item in value]
    return {"redacted": True}


def merge_redacted_records(client_value, secure_value):
    payload = {}
    if isinstance(client_value, dict):
        payload["client_safe"] = client_value
    elif client_value is not None:
        payload["client_safe"] = client_value
    if isinstance(secure_value, dict):
        payload["secure_redacted"] = redact_secret_value(secure_value)
    elif secure_value is not None:
        payload["secure_redacted"] = redact_secret_value(secure_value)
    return payload
