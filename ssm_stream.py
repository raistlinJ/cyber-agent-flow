"""Local llama.cpp-backed state management for the network stream watcher.

This module intentionally keeps packet capture and model execution separate.  It
loads a GGUF model in the watcher process, keeps a bounded state per network
flow, and exposes a compact score for the watcher to use as an alert gate.

Only recurrent GGUF architectures are accepted for the streaming path.  A
transformer can be served by llama.cpp too, but retaining a full KV cache for
each flow is not the constant-state SSM design this watcher is intended to
demonstrate.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import threading
import time
from typing import Any

try:  # Optional dependency: normal deployments do not need it until enabled.
    from llama_cpp import Llama, llama_cpp
    _LLAMA_CPP_IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - depends on the local runtime
    Llama = None
    llama_cpp = None
    _LLAMA_CPP_IMPORT_ERROR = str(exc)


@dataclass(frozen=True)
class SsmObservation:
    flow_key: str
    event: str
    score: float
    model_score: float | None
    active_flows: int


class LlamaCppSsmRuntime:
    """A bounded per-flow recurrent-model state store.

    llama-cpp-python exposes ``save_state``/``load_state`` on ``Llama``.  For
    recurrent models, that state is the compact hidden state we need to retain
    between events.  The margin score below is a lightweight surprise proxy:
    it compares the observed event tokens with the model's most likely tokens.
    It is deliberately an alert *signal*, not a claim that an arbitrary GGUF is
    a pre-trained intrusion detector.
    """

    def __init__(
        self,
        model_path: str,
        *,
        n_ctx: int = 1024,
        n_gpu_layers: int = 0,
        max_flows: int = 256,
    ):
        self.model_path = model_path
        self.n_ctx = max(128, min(int(n_ctx), 8192))
        self.n_gpu_layers = int(n_gpu_layers)
        self.max_flows = max(16, min(int(max_flows), 2048))
        self._llm = None
        self._states: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self.events_processed = 0
        self.state_evictions = 0
        self.last_score: float | None = None
        self.last_error = ""
        self.is_recurrent = False

    @property
    def available(self) -> bool:
        return Llama is not None

    @property
    def active_flows(self) -> int:
        return len(self._states)

    def start(self) -> None:
        if not self.available:
            raise RuntimeError(
                "llama-cpp-python is not installed. Install the optional local SSM runtime "
                "with: pip install llama-cpp-python"
            )
        if not self.model_path:
            raise RuntimeError("A local GGUF model path is required for the llama.cpp SSM engine.")

        try:
            self._llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                logits_all=True,
                verbose=False,
            )
            self.is_recurrent = self._model_is_recurrent()
            if not self.is_recurrent:
                self._llm = None
                raise RuntimeError(
                    "The selected GGUF is not a recurrent/SSM architecture. "
                    "Choose a llama.cpp-supported recurrent model (for example, a Mamba-family GGUF)."
                )
        except RuntimeError:
            raise
        except Exception as exc:  # pragma: no cover - requires a real model
            self._llm = None
            raise RuntimeError(f"Could not load local GGUF model: {exc}") from exc

    def stop(self) -> None:
        with self._lock:
            self._states.clear()
            self._llm = None

    def forget_flows(self, flow_keys: set[str]) -> int:
        """Drop explicit flow states and return how many were released."""
        if not flow_keys:
            return 0
        with self._lock:
            removed = 0
            for flow_key in flow_keys:
                if self._states.pop(flow_key, None) is not None:
                    removed += 1
            self.state_evictions += removed
            return removed

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "loaded": self._llm is not None,
            "recurrent": self.is_recurrent,
            "model_path": self.model_path,
            "n_ctx": self.n_ctx,
            "n_gpu_layers": self.n_gpu_layers,
            "max_flows": self.max_flows,
            "active_flows": self.active_flows,
            "events_processed": self.events_processed,
            "state_evictions": self.state_evictions,
            "last_score": self.last_score,
            "error": self.last_error,
        }

    def observe(self, flow_key: str, event: dict[str, Any]) -> SsmObservation:
        if self._llm is None:
            raise RuntimeError("Local SSM runtime is not loaded.")

        event_text = self._event_text(event)
        with self._lock:
            prior_state = self._states.pop(flow_key, None)
            try:
                if prior_state is None:
                    self._llm.reset()
                else:
                    self._llm.load_state(prior_state)

                tokens = self._llm.tokenize(event_text.encode("utf-8"), add_bos=prior_state is None)
                # Short, normalized events preserve the stream nature and avoid
                # accidental context growth from decoded packet payloads.
                tokens = tokens[:128]
                if not tokens:
                    return SsmObservation(flow_key, event_text, 0.0, None, self.active_flows)
                self._llm.eval(tokens)
                model_score = self._surprise_proxy(tokens)
                self._states[flow_key] = self._llm.save_state()
                while len(self._states) > self.max_flows:
                    self._states.popitem(last=False)
                    self.state_evictions += 1
                self.events_processed += 1
                self.last_score = model_score
                return SsmObservation(flow_key, event_text, model_score, model_score, self.active_flows)
            except Exception as exc:  # pragma: no cover - requires a real model
                self.last_error = str(exc)
                raise RuntimeError(f"SSM event evaluation failed: {exc}") from exc

    def _model_is_recurrent(self) -> bool:
        """Use the native capability check when the installed binding exposes it."""
        try:
            model = getattr(self._llm, "_model", None)
            capability = getattr(llama_cpp, "llama_model_is_recurrent", None)
            return bool(model is not None and capability and capability(model))
        except Exception:
            return False

    def _surprise_proxy(self, tokens: list[int]) -> float:
        """Return a bounded token-surprise signal from logits produced by eval()."""
        scores = getattr(self._llm, "scores", None)
        if scores is None:
            scores = getattr(self._llm, "_scores", None)
        if scores is None or len(tokens) < 2:
            return 0.0

        margins: list[float] = []
        # Score row i predicts token i + 1.  We intentionally skip the first
        # token because a restored model state does not guarantee an exposed
        # pre-event logits row in every llama-cpp-python release.
        rows = min(len(scores), len(tokens) - 1)
        for index in range(rows):
            try:
                row = scores[index]
                target = float(row[tokens[index + 1]])
                maximum = float(row.max())
                margins.append(max(0.0, maximum - target))
            except (IndexError, TypeError, ValueError, AttributeError):
                continue
        if not margins:
            return 0.0
        # A margin of ~12 logits is already extremely surprising; cap it to a
        # stable 0..1 signal that operators can threshold in the UI.
        return round(min(1.0, sum(margins) / len(margins) / 12.0), 4)

    @staticmethod
    def _event_text(event: dict[str, Any]) -> str:
        """Serialize only stable stream features, never raw packet bodies."""
        return json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def packet_flow_key(record: dict[str, Any]) -> str:
    """Create a stable bidirectional 5-tuple-like key from decoded headers."""
    headers = record.get("headers") or {}
    network = headers.get("ip") or headers.get("ipv6") or {}
    transport = headers.get("tcp") or headers.get("udp") or {}
    source = str(network.get("src") or network.get("src_host") or "?")
    destination = str(network.get("dst") or network.get("dst_host") or "?")
    source_port = str(transport.get("srcport") or transport.get("src_port") or "")
    destination_port = str(transport.get("dstport") or transport.get("dst_port") or "")
    protocol = "tcp" if "tcp" in headers else "udp" if "udp" in headers else str(record.get("highest_protocol") or "other")
    endpoints = sorted(((source, source_port), (destination, destination_port)))
    return f"{protocol}|{endpoints[0][0]}:{endpoints[0][1]}|{endpoints[1][0]}:{endpoints[1][1]}"


def packet_stream_event(record: dict[str, Any]) -> dict[str, Any]:
    """Map a decoded packet to a small, payload-free SSM event."""
    headers = record.get("headers") or {}
    tcp = headers.get("tcp") or {}
    udp = headers.get("udp") or {}
    application = [name for name in ("http", "http2", "dns", "tls", "ssl") if name in headers]
    transport = tcp or udp
    return {
        "p": "tcp" if tcp else "udp" if udp else str(record.get("highest_protocol") or "other").lower(),
        "len": record.get("length") or "0",
        "flags": tcp.get("flags") or tcp.get("flags_str") or "",
        "src_port": transport.get("srcport") or transport.get("src_port") or "",
        "dst_port": transport.get("dstport") or transport.get("dst_port") or "",
        "app": application,
        "stack": record.get("protocol_stack") or [],
        "at": int(time.time()),
    }
