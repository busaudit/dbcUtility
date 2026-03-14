#!/usr/bin/env python3

"""
DBC Comparator Module
Provides reusable comparison primitives for DBC files and editor data.

The module stays UI-agnostic and returns structured line-level and char-level
diff data that can be rendered in multiple presentation styles, including
side-by-side, unified, and structured (semantic) views.
"""

from __future__ import annotations

import copy
import difflib
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cantools
from cantools.database.conversion import BaseConversion

logger = logging.getLogger(__name__)


class DiffType(str, Enum):
    EQUAL = "equal"
    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"


class CompareSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class DiffChunk:
    text: str
    changed: bool = False


@dataclass
class DiffRow:
    diff_type: DiffType
    left_text: str = ""
    right_text: str = ""
    left_lineno: Optional[int] = None
    right_lineno: Optional[int] = None
    left_chunks: List[DiffChunk] = field(default_factory=list)
    right_chunks: List[DiffChunk] = field(default_factory=list)

    @property
    def is_changed(self) -> bool:
        return self.diff_type != DiffType.EQUAL


@dataclass
class DiffStats:
    added_lines: int = 0
    deleted_lines: int = 0
    modified_lines: int = 0
    unchanged_lines: int = 0
    changed_blocks: int = 0


@dataclass
class DiffResult:
    rows: List[DiffRow] = field(default_factory=list)
    left_label: str = ""
    right_label: str = ""
    left_path: Optional[str] = None
    right_path: Optional[str] = None
    primary_side: CompareSide = CompareSide.LEFT
    stats: DiffStats = field(default_factory=DiffStats)

    @property
    def changed_row_indices(self) -> List[int]:
        return [index for index, row in enumerate(self.rows) if row.is_changed]


def build_dbc_string(data: Dict[str, Any]) -> str:
    """Convert an editor-format data dict to a DBC text string via cantools."""
    db = cantools.database.Database(sort_signals=None)

    for msg in data.get("messages", []):
        signals = []
        for sig in msg.get("signals", []):
            conversion = BaseConversion.factory(
                scale=sig.get("scale", 1.0),
                offset=sig.get("offset", 0.0),
                choices=sig.get("choices"),
                is_float=sig.get("is_float", False),
            )
            signal = cantools.database.can.Signal(
                name=sig["name"],
                start=sig["start_bit"],
                length=sig["length"],
                byte_order=sig.get("byte_order", "little_endian"),
                is_signed=sig["is_signed"],
                raw_initial=sig.get("raw_initial"),
                raw_invalid=sig.get("raw_invalid"),
                conversion=conversion,
                minimum=sig["minimum"] if sig.get("minimum") is not None else None,
                maximum=sig["maximum"] if sig.get("maximum") is not None else None,
                unit=sig.get("unit") or None,
                comment=sig.get("comments") or None,
                receivers=sig.get("receivers", []),
                is_multiplexer=sig.get("is_multiplexer", False),
                multiplexer_ids=sig.get("multiplexer_ids") or None,
                multiplexer_signal=sig.get("multiplexer_signal") or None,
                spn=sig.get("spn"),
            )
            signals.append(signal)

        message = cantools.database.can.Message(
            frame_id=msg["frame_id"],
            name=msg["name"],
            length=msg["length"],
            signals=signals,
            comment=msg.get("comments") or None,
            senders=msg.get("senders", []),
            send_type=msg.get("send_type") or None,
            cycle_time=msg.get("cycle_time"),
            is_extended_frame=msg.get("is_extended_frame", msg["frame_id"] > 0x7FF),
            is_fd=msg.get("is_fd", False),
            bus_name=msg.get("bus_name") or None,
            unused_bit_pattern=msg.get("unused_bit_pattern", 0),
            protocol=msg.get("protocol") or None,
            sort_signals=None,
        )
        db.messages.append(message)

    return db.as_dbc_string()


def _normalize_line(line: str, ignore_whitespace: bool) -> str:
    if not ignore_whitespace:
        return line
    return " ".join(line.split())


def _split_text_lines(text: str) -> List[str]:
    """Split text into logical lines while preserving a trailing blank line."""
    if text == "":
        return []
    return text.split("\n")


def _chunk_all_changed(text: str) -> List[DiffChunk]:
    if not text:
        return []
    return [DiffChunk(text=text, changed=True)]


def _chunk_unchanged(text: str) -> List[DiffChunk]:
    if not text:
        return []
    return [DiffChunk(text=text, changed=False)]


def _build_intraline_chunks(left_text: str, right_text: str) -> tuple[List[DiffChunk], List[DiffChunk]]:
    """Build char-level chunks for a pair of related lines."""
    if left_text == right_text:
        return _chunk_unchanged(left_text), _chunk_unchanged(right_text)

    matcher = difflib.SequenceMatcher(None, left_text, right_text)
    left_chunks: List[DiffChunk] = []
    right_chunks: List[DiffChunk] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        left_part = left_text[i1:i2]
        right_part = right_text[j1:j2]
        changed = tag != "equal"

        if left_part:
            left_chunks.append(DiffChunk(text=left_part, changed=changed))
        if right_part:
            right_chunks.append(DiffChunk(text=right_part, changed=changed))

    return left_chunks, right_chunks


def _build_replace_rows(
    left_lines: List[str],
    right_lines: List[str],
    left_start: int,
    right_start: int,
) -> List[DiffRow]:
    rows: List[DiffRow] = []
    max_len = max(len(left_lines), len(right_lines))

    for index in range(max_len):
        left_text = left_lines[index] if index < len(left_lines) else ""
        right_text = right_lines[index] if index < len(right_lines) else ""
        left_lineno = left_start + index + 1 if index < len(left_lines) else None
        right_lineno = right_start + index + 1 if index < len(right_lines) else None

        if left_text and right_text:
            left_chunks, right_chunks = _build_intraline_chunks(left_text, right_text)
        elif left_text:
            left_chunks, right_chunks = _chunk_all_changed(left_text), []
        else:
            left_chunks, right_chunks = [], _chunk_all_changed(right_text)

        rows.append(
            DiffRow(
                diff_type=DiffType.REPLACE,
                left_text=left_text,
                right_text=right_text,
                left_lineno=left_lineno,
                right_lineno=right_lineno,
                left_chunks=left_chunks,
                right_chunks=right_chunks,
            )
        )

    return rows


def compute_diff_rows(
    left_lines: List[str],
    right_lines: List[str],
    *,
    ignore_whitespace: bool = False,
) -> List[DiffRow]:
    """Compute aligned side-by-side rows with char-level details."""
    normalized_left = [_normalize_line(line, ignore_whitespace) for line in left_lines]
    normalized_right = [_normalize_line(line, ignore_whitespace) for line in right_lines]
    matcher = difflib.SequenceMatcher(None, normalized_left, normalized_right)

    rows: List[DiffRow] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for left_index, right_index in zip(range(i1, i2), range(j1, j2)):
                left_text = left_lines[left_index]
                right_text = right_lines[right_index]
                left_chunks, right_chunks = _chunk_unchanged(left_text), _chunk_unchanged(right_text)
                rows.append(
                    DiffRow(
                        diff_type=DiffType.EQUAL,
                        left_text=left_text,
                        right_text=right_text,
                        left_lineno=left_index + 1,
                        right_lineno=right_index + 1,
                        left_chunks=left_chunks,
                        right_chunks=right_chunks,
                    )
                )
        elif tag == "delete":
            for left_index in range(i1, i2):
                left_text = left_lines[left_index]
                rows.append(
                    DiffRow(
                        diff_type=DiffType.DELETE,
                        left_text=left_text,
                        right_text="",
                        left_lineno=left_index + 1,
                        right_lineno=None,
                        left_chunks=_chunk_all_changed(left_text),
                        right_chunks=[],
                    )
                )
        elif tag == "insert":
            for right_index in range(j1, j2):
                right_text = right_lines[right_index]
                rows.append(
                    DiffRow(
                        diff_type=DiffType.INSERT,
                        left_text="",
                        right_text=right_text,
                        left_lineno=None,
                        right_lineno=right_index + 1,
                        left_chunks=[],
                        right_chunks=_chunk_all_changed(right_text),
                    )
                )
        elif tag == "replace":
            rows.extend(_build_replace_rows(left_lines[i1:i2], right_lines[j1:j2], i1, j1))

    return rows


def _compute_stats(rows: List[DiffRow]) -> DiffStats:
    stats = DiffStats()
    previous_changed = False

    for row in rows:
        if row.diff_type == DiffType.EQUAL:
            stats.unchanged_lines += 1
        elif row.diff_type == DiffType.INSERT:
            stats.added_lines += 1
        elif row.diff_type == DiffType.DELETE:
            stats.deleted_lines += 1
        elif row.diff_type == DiffType.REPLACE:
            stats.modified_lines += 1

        if row.is_changed and not previous_changed:
            stats.changed_blocks += 1
        previous_changed = row.is_changed

    return stats


def compare_texts(
    left_text: str,
    right_text: str,
    *,
    left_label: str = "Left",
    right_label: str = "Right",
    left_path: Optional[str] = None,
    right_path: Optional[str] = None,
    primary_side: CompareSide = CompareSide.LEFT,
    ignore_whitespace: bool = False,
) -> DiffResult:
    """Compare two raw texts and return a structured diff result."""
    left_lines = _split_text_lines(left_text)
    right_lines = _split_text_lines(right_text)
    rows = compute_diff_rows(left_lines, right_lines, ignore_whitespace=ignore_whitespace)
    return DiffResult(
        rows=rows,
        left_label=left_label,
        right_label=right_label,
        left_path=left_path,
        right_path=right_path,
        primary_side=primary_side,
        stats=_compute_stats(rows),
    )


def compare_data(
    left_data: Dict[str, Any],
    right_data: Dict[str, Any],
    *,
    left_label: str = "Original",
    right_label: str = "Modified",
    left_path: Optional[str] = None,
    right_path: Optional[str] = None,
    primary_side: CompareSide = CompareSide.LEFT,
    ignore_whitespace: bool = False,
) -> DiffResult:
    """Compare two editor-format DBC dicts after converting them to DBC text."""
    try:
        left_text = build_dbc_string(left_data)
        right_text = build_dbc_string(right_data)
    except Exception as exc:
        logger.error("Failed to build DBC strings for comparison: %s", exc)
        raise

    return compare_texts(
        left_text,
        right_text,
        left_label=left_label,
        right_label=right_label,
        left_path=left_path,
        right_path=right_path,
        primary_side=primary_side,
        ignore_whitespace=ignore_whitespace,
    )


def compare_files(
    left_path: str,
    right_path: str,
    *,
    primary_side: CompareSide = CompareSide.LEFT,
    ignore_whitespace: bool = False,
) -> DiffResult:
    """Compare two DBC files by contents."""
    with open(left_path, "r", encoding="utf-8") as handle:
        left_text = handle.read()
    with open(right_path, "r", encoding="utf-8") as handle:
        right_text = handle.read()

    return compare_texts(
        left_text,
        right_text,
        left_label=os.path.basename(left_path),
        right_label=os.path.basename(right_path),
        left_path=left_path,
        right_path=right_path,
        primary_side=primary_side,
        ignore_whitespace=ignore_whitespace,
    )


# ---------------------------------------------------------------------------
#  Structured (semantic) comparison
# ---------------------------------------------------------------------------

_SIGNAL_COMPARE_KEYS = (
    "start_bit", "length", "byte_order", "is_signed", "scale", "offset",
    "minimum", "maximum", "unit", "receivers", "is_multiplexer",
    "multiplexer_ids", "multiplexer_signal", "is_float", "comments",
)

_MESSAGE_COMPARE_KEYS = (
    "name", "length", "senders", "send_type", "cycle_time", "is_fd",
    "bus_name", "protocol", "unused_bit_pattern", "comments",
)


@dataclass
class ItemDiffStatus:
    status: str  # 'added', 'removed', 'modified', 'unchanged'
    changed_properties: List[str] = field(default_factory=list)


@dataclass
class SignalComparisonItem:
    name: str
    diff_status: ItemDiffStatus
    primary_signal: Optional[Dict[str, Any]] = None
    secondary_signal: Optional[Dict[str, Any]] = None


@dataclass
class MessageComparisonItem:
    name: str
    frame_id: int
    diff_status: ItemDiffStatus
    primary_message: Optional[Dict[str, Any]] = None
    secondary_message: Optional[Dict[str, Any]] = None
    signal_comparisons: List[SignalComparisonItem] = field(default_factory=list)


@dataclass
class StructuredDiffResult:
    message_comparisons: List[MessageComparisonItem] = field(default_factory=list)
    primary_only_count: int = 0
    secondary_only_count: int = 0
    modified_count: int = 0
    unchanged_count: int = 0


def _safe_attr(obj: Any, attr_name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, attr_name, default)
        return value() if callable(value) else value
    except Exception:
        return default


def _extract_comment(comment_obj: Any) -> str:
    if not comment_obj:
        return ""
    if isinstance(comment_obj, str):
        return comment_obj
    if isinstance(comment_obj, dict):
        for value in comment_obj.values():
            if isinstance(value, str):
                return value.strip("'\"")
        return str(comment_obj)
    return str(comment_obj)


def parse_dbc_to_dicts(dbc_text: str) -> Dict[str, Any]:
    """Parse DBC text into the editor-format dict structure via cantools.

    Returns ``{'messages': [<message_dict>, ...]}``.
    """
    if not dbc_text or not dbc_text.strip():
        return {"messages": []}

    try:
        db = cantools.database.load_string(dbc_text, database_format="dbc", strict=True)
    except cantools.database.errors.Error as exc:
        if "are overlapping in message" in str(exc):
            db = cantools.database.load_string(dbc_text, database_format="dbc", strict=False)
        else:
            raise

    messages_data: List[Dict[str, Any]] = []
    for msg in db.messages:
        signals_data: List[Dict[str, Any]] = []
        for sig in msg.signals:
            signals_data.append({
                "name": sig.name,
                "start_bit": _safe_attr(sig, "start", 0),
                "length": _safe_attr(sig, "length", 1),
                "byte_order": _safe_attr(sig, "byte_order", "little_endian"),
                "is_signed": _safe_attr(sig, "is_signed", False),
                "raw_initial": _safe_attr(sig, "raw_initial", None),
                "raw_invalid": _safe_attr(sig, "raw_invalid", None),
                "scale": _safe_attr(sig, "scale", 1.0),
                "offset": _safe_attr(sig, "offset", 0.0),
                "minimum": _safe_attr(sig, "minimum", None),
                "maximum": _safe_attr(sig, "maximum", None),
                "unit": _safe_attr(sig, "unit", "") or "",
                "receivers": [str(r) for r in (_safe_attr(sig, "receivers", []) or [])],
                "is_multiplexer": _safe_attr(sig, "is_multiplexer", False),
                "multiplexer_ids": list(_safe_attr(sig, "multiplexer_ids", []) or []),
                "multiplexer_signal": _safe_attr(sig, "multiplexer_signal", None),
                "spn": _safe_attr(sig, "spn", None),
                "choices": copy.deepcopy(_safe_attr(sig, "choices", None)),
                "is_float": _safe_attr(sig, "is_float", False),
                "comments": _extract_comment(getattr(sig, "comments", ""))
                            if getattr(sig, "comments", "") else "",
            })

        messages_data.append({
            "name": msg.name,
            "frame_id": msg.frame_id,
            "is_extended_frame": _safe_attr(msg, "is_extended_frame", msg.frame_id > 0x7FF),
            "length": msg.length,
            "senders": [str(s) for s in (_safe_attr(msg, "senders", []) or [])],
            "send_type": _safe_attr(msg, "send_type", None),
            "cycle_time": _safe_attr(msg, "cycle_time", None),
            "is_fd": _safe_attr(msg, "is_fd", False),
            "bus_name": _safe_attr(msg, "bus_name", None),
            "protocol": _safe_attr(msg, "protocol", None),
            "unused_bit_pattern": _safe_attr(msg, "unused_bit_pattern", 0),
            "signals": signals_data,
            "comments": _extract_comment(msg.comment) if msg.comment else "",
        })

    return {"messages": messages_data}


def _normalize_for_compare(value: Any) -> Any:
    """Normalise a value so that semantically identical items compare equal."""
    if value is None:
        return None
    if isinstance(value, list):
        return [_normalize_for_compare(v) for v in value]
    if isinstance(value, float):
        return round(value, 10)
    return value


def _diff_dicts(
    primary: Optional[Dict[str, Any]],
    secondary: Optional[Dict[str, Any]],
    keys: Tuple[str, ...],
) -> List[str]:
    """Return list of property names that differ between two dicts."""
    if primary is None or secondary is None:
        return list(keys) if (primary is not None or secondary is not None) else []
    changed: List[str] = []
    for key in keys:
        pv = _normalize_for_compare(primary.get(key))
        sv = _normalize_for_compare(secondary.get(key))
        if pv != sv:
            changed.append(key)
    return changed


def _compare_signals(
    primary_signals: List[Dict[str, Any]],
    secondary_signals: List[Dict[str, Any]],
) -> List[SignalComparisonItem]:
    """Match signals by name and classify each."""
    primary_map = {s["name"]: s for s in primary_signals}
    secondary_map = {s["name"]: s for s in secondary_signals}
    all_names_ordered: List[str] = []
    seen: set = set()
    for s in primary_signals:
        if s["name"] not in seen:
            all_names_ordered.append(s["name"])
            seen.add(s["name"])
    for s in secondary_signals:
        if s["name"] not in seen:
            all_names_ordered.append(s["name"])
            seen.add(s["name"])

    items: List[SignalComparisonItem] = []
    for name in all_names_ordered:
        p_sig = primary_map.get(name)
        s_sig = secondary_map.get(name)

        if p_sig and not s_sig:
            status = ItemDiffStatus(status="removed")
        elif s_sig and not p_sig:
            status = ItemDiffStatus(status="added")
        else:
            changed = _diff_dicts(p_sig, s_sig, _SIGNAL_COMPARE_KEYS)
            status = ItemDiffStatus(
                status="modified" if changed else "unchanged",
                changed_properties=changed,
            )
        items.append(SignalComparisonItem(
            name=name, diff_status=status,
            primary_signal=p_sig, secondary_signal=s_sig,
        ))
    return items


def compare_dbc_structures(
    primary_dicts: Dict[str, Any],
    secondary_dicts: Dict[str, Any],
) -> StructuredDiffResult:
    """Produce a semantic comparison of two parsed DBC data sets."""
    primary_msgs = primary_dicts.get("messages", [])
    secondary_msgs = secondary_dicts.get("messages", [])

    p_by_id: Dict[int, Dict[str, Any]] = {m["frame_id"]: m for m in primary_msgs}
    s_by_id: Dict[int, Dict[str, Any]] = {m["frame_id"]: m for m in secondary_msgs}

    all_ids_ordered: List[int] = []
    seen_ids: set = set()
    for m in primary_msgs:
        fid = m["frame_id"]
        if fid not in seen_ids:
            all_ids_ordered.append(fid)
            seen_ids.add(fid)
    for m in secondary_msgs:
        fid = m["frame_id"]
        if fid not in seen_ids:
            all_ids_ordered.append(fid)
            seen_ids.add(fid)

    result = StructuredDiffResult()
    for fid in all_ids_ordered:
        p_msg = p_by_id.get(fid)
        s_msg = s_by_id.get(fid)
        name = (p_msg or s_msg or {}).get("name", "?")

        if p_msg and not s_msg:
            msg_status = ItemDiffStatus(status="removed")
            sig_comps = _compare_signals(p_msg.get("signals", []), [])
            result.primary_only_count += 1
        elif s_msg and not p_msg:
            msg_status = ItemDiffStatus(status="added")
            sig_comps = _compare_signals([], s_msg.get("signals", []))
            result.secondary_only_count += 1
        else:
            assert p_msg is not None and s_msg is not None
            changed = _diff_dicts(p_msg, s_msg, _MESSAGE_COMPARE_KEYS)
            sig_comps = _compare_signals(
                p_msg.get("signals", []),
                s_msg.get("signals", []),
            )
            has_sig_diff = any(
                sc.diff_status.status != "unchanged" for sc in sig_comps
            )
            if changed or has_sig_diff:
                msg_status = ItemDiffStatus(status="modified", changed_properties=changed)
                result.modified_count += 1
            else:
                msg_status = ItemDiffStatus(status="unchanged")
                result.unchanged_count += 1

        result.message_comparisons.append(MessageComparisonItem(
            name=name, frame_id=fid, diff_status=msg_status,
            primary_message=p_msg, secondary_message=s_msg,
            signal_comparisons=sig_comps,
        ))

    return result
