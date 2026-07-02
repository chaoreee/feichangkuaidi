"""Human-readable trace log for a single match (delivery_spec section 4).

Each line is one event, e.g.:

    12:03:41.271 Action matchId=local-debug-l1, round=96, action=MOVE, target=S05

The log is written under ``client/logs/match_<matchId>_<playerId>.log`` and
flushed per line so that, after a match, the deliverable's ``logs/`` can be
downloaded and analysed directly (no JSON parsing, no external tooling).
matchId is unknown before ``start``: records are buffered in memory and
flushed once ``bind_match`` opens the file. Thread-safe (the receive thread
also writes error traces).
"""

import os
import threading
import time


class MatchLogger:
    def __init__(self, log_dir, player_id):
        self.log_dir = log_dir
        self.player_id = player_id
        self.match_id = None
        self.path = None
        self._fh = None
        self._buffer = []
        self._lock = threading.Lock()
        os.makedirs(log_dir, exist_ok=True)

    def bind_match(self, match_id):
        """Bind matchId after ``start``: open the log file, flush the buffer."""
        with self._lock:
            self.match_id = match_id
            safe = str(match_id).replace(os.sep, "_").replace("/", "_")
            self.path = os.path.join(
                self.log_dir, "match_%s_%s.log" % (safe, self.player_id))
            self._fh = open(self.path, "a", encoding="utf-8")
            for line in self._buffer:
                self._fh.write(line + "\n")
            self._buffer.clear()
            self._fh.flush()

    def trace(self, event, round=None, **fields):
        """Write one trace line: ``<clock> <Event> matchId=..., round=..., k=v``.

        ``None`` fields are dropped so lines stay concise. Field insertion
        order is preserved (Python 3.7+ kwargs), so callers control layout.
        """
        parts = ["matchId=%s" % (self.match_id if self.match_id is not None else "-")]
        if round is not None:
            parts.append("round=%s" % round)
        for key, value in fields.items():
            if value is None:
                continue
            parts.append("%s=%s" % (key, _fmt(value)))
        line = "%s %s %s" % (_clock(), event, ", ".join(parts))
        with self._lock:
            if self._fh is not None:
                self._fh.write(line + "\n")
                self._fh.flush()
            else:
                self._buffer.append(line)

    def close(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None


def _fmt(value):
    """Render a field value compactly on a single line (no surrounding spaces)."""
    if isinstance(value, float):
        return ("%.2f" % value).rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return "[%s]" % "|".join(_fmt(v) for v in value)
    text = str(value)
    # Keep every record on one physical line for grep/trace friendliness.
    return text.replace("\n", " ").replace("\r", " ")


def _clock():
    """Local wall-clock ``HH:MM:SS.mmm`` for ordering trace lines within a match."""
    now = time.time()
    lt = time.localtime(now)
    return "%02d:%02d:%02d.%03d" % (
        lt.tm_hour, lt.tm_min, lt.tm_sec, int((now - int(now)) * 1000))
