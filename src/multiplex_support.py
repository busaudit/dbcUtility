#!/usr/bin/env python3

"""
Multiplexed CAN signal support.

Pure domain logic for classifying, filtering, and validating multiplexed
signals within CAN messages.  No UI dependencies -- designed to be consumed
by the editor, viewer, and visualizer modules.

Terminology
-----------
- **Multiplexer signal** (``is_multiplexer=True``): the selector whose
  runtime value determines which multiplexed signals are active.  At most
  one per message in simple multiplexing.
- **Multiplexed signal** (``multiplexer_ids`` is a non-empty list): active
  only when the multiplexer signal's value matches one of its IDs.
- **Regular signal**: always present regardless of the multiplexer value.
"""

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
#  Signal classification
# ---------------------------------------------------------------------------

def classify_signal(signal: Dict[str, Any]) -> str:
    """Return ``'multiplexer'``, ``'multiplexed'``, or ``'regular'``."""
    if signal.get("is_multiplexer", False):
        return "multiplexer"
    ids = signal.get("multiplexer_ids")
    if ids and len(ids) > 0:
        return "multiplexed"
    return "regular"


def format_mux_indicator(signal: Dict[str, Any]) -> str:
    """Return a short display tag such as ``[M]``, ``[m0x5]``, or ``""``."""
    role = classify_signal(signal)
    if role == "multiplexer":
        return "[M]"
    if role == "multiplexed":
        ids = signal.get("multiplexer_ids", [])
        return "[m" + ",".join(f"0x{int(i):X}" for i in ids) + "]"
    return ""


# ---------------------------------------------------------------------------
#  Message-level queries
# ---------------------------------------------------------------------------

def is_message_multiplexed(message: Dict[str, Any]) -> bool:
    """True if the message contains at least one multiplexer signal."""
    for sig in message.get("signals", []):
        if sig.get("is_multiplexer", False):
            return True
    return False


def get_multiplexer_signal(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the multiplexer signal dict, or *None* if there isn't one."""
    for sig in message.get("signals", []):
        if sig.get("is_multiplexer", False):
            return sig
    return None


def get_multiplexer_signal_name(message: Dict[str, Any]) -> Optional[str]:
    """Return the multiplexer signal's name, or *None*."""
    mux = get_multiplexer_signal(message)
    return mux["name"] if mux else None


def get_mux_ids(message: Dict[str, Any]) -> List[int]:
    """Return a sorted list of every unique multiplexer ID used in the message."""
    ids: set = set()
    for sig in message.get("signals", []):
        for mux_id in sig.get("multiplexer_ids", []) or []:
            ids.add(int(mux_id))
    return sorted(ids)


def get_multiplexer_choices(message: Dict[str, Any]) -> Optional[Dict[int, str]]:
    """Return the multiplexer signal's value table (choices), if any.
    Keys are integer values; values are display names. Uses 'choices' or 'values' key.
    """
    mux = get_multiplexer_signal(message)
    if not mux:
        return None
    raw = mux.get("choices") or mux.get("values")
    if not raw or not isinstance(raw, dict):
        return None
    return {int(k): str(v) for k, v in raw.items()}


def format_mux_id_with_name(message: Dict[str, Any], mux_id: int) -> str:
    """Return display string for a mux ID: '0x5' or '0x5 (Name)' if the multiplexer has a choice."""
    choices = get_multiplexer_choices(message)
    hex_str = f"0x{mux_id:X}"
    if choices and mux_id in choices:
        return f"{hex_str} ({choices[mux_id]})"
    return hex_str


def get_mux_id_name_from_messages(
    messages: List[Dict[str, Any]],
    mux_id: int,
) -> Optional[str]:
    """Return the display name for a mux ID from any message's multiplexer choices."""
    for msg in messages:
        choices = get_multiplexer_choices(msg)
        if choices and mux_id in choices:
            return choices[mux_id]
    return None


# ---------------------------------------------------------------------------
#  Filtering
# ---------------------------------------------------------------------------

def filter_signals_by_mux_id(
    signals: List[Dict[str, Any]],
    mux_id: Optional[int],
) -> List[Dict[str, Any]]:
    """Filter signals for a given multiplexer ID.

    Parameters
    ----------
    signals:
        Full signal list from a message dict.
    mux_id:
        The multiplexer ID to filter on.  Pass *None* to return all signals
        unfiltered.

    Returns
    -------
    list
        Regular signals + the multiplexer signal + multiplexed signals whose
        ``multiplexer_ids`` contains *mux_id*.
    """
    if mux_id is None:
        return list(signals)

    result: List[Dict[str, Any]] = []
    for sig in signals:
        role = classify_signal(sig)
        if role == "regular":
            result.append(sig)
        elif role == "multiplexer":
            result.append(sig)
        elif role == "multiplexed":
            if mux_id in (sig.get("multiplexer_ids") or []):
                result.append(sig)
    return result


# ---------------------------------------------------------------------------
#  Validation
# ---------------------------------------------------------------------------

def validate_mux_config(message: Dict[str, Any]) -> List[str]:
    """Return human-readable warnings about the message's mux setup.

    Never raises -- problems are returned as plain strings so the UI can
    display them non-destructively.
    """
    warnings: List[str] = []
    signals = message.get("signals", [])

    mux_signals = [s for s in signals if s.get("is_multiplexer", False)]
    if len(mux_signals) > 1:
        names = ", ".join(s.get("name", "?") for s in mux_signals)
        warnings.append(
            f"Multiple multiplexer signals found ({names}). "
            "Only one multiplexer per message is supported in simple multiplexing."
        )

    mux_name = mux_signals[0]["name"] if mux_signals else None

    for sig in signals:
        role = classify_signal(sig)
        if role != "multiplexed":
            continue

        ref = sig.get("multiplexer_signal")
        ids = sig.get("multiplexer_ids") or []

        if ids and not ref:
            warnings.append(
                f"Signal '{sig.get('name', '?')}' has multiplexer IDs "
                f"but no multiplexer_signal reference."
            )
        elif ref and mux_name and ref != mux_name:
            warnings.append(
                f"Signal '{sig.get('name', '?')}' references multiplexer "
                f"'{ref}', but the message's multiplexer is '{mux_name}'."
            )
        elif ref and not mux_name:
            warnings.append(
                f"Signal '{sig.get('name', '?')}' references multiplexer "
                f"'{ref}', but no multiplexer signal exists in this message."
            )

    return warnings
