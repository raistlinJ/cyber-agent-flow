import os
import threading
import json
import time
import base64
import requests
import queue
import logging
import psutil
import shutil
import subprocess
import re
from datetime import datetime
from ssm_stream import LlamaCppSsmRuntime, SsmObservation, packet_flow_key, packet_stream_event

try:
    import pyshark
    _PYSHARK_AVAILABLE = True
except ImportError:
    _PYSHARK_AVAILABLE = False


DEFAULT_MAX_PACKET_PAYLOAD_BYTES = 384
MAX_CONFIGURED_PACKET_PAYLOAD_BYTES = 8_192
MAX_HEADER_FIELDS_PER_PROTOCOL = 24
MAX_HEADER_VALUE_CHARS = 256
DEFAULT_MAX_PACKETS_PER_ANALYSIS = 12
MAX_CONFIGURED_PACKETS_PER_ANALYSIS = 500
MAX_ANALYSIS_CHARS = 8_000
MAX_CYBER_AGENT_FLOW_CONTEXT_CHARS = 2_000
DEFAULT_ANALYSIS_INTERVAL_SECONDS = 5
MAX_ANALYSIS_INTERVAL_SECONDS = 300
DEFAULT_SSM_ALERT_THRESHOLD = 0.72
DEFAULT_SSM_ALERT_COOLDOWN_SECONDS = 60
DEFAULT_SURICATA_EVE_PATH = "/var/log/suricata/eve.json"
DEFAULT_SURICATA_EVENT_TYPES = frozenset({"flow", "dns", "http", "tls", "alert", "anomaly", "fileinfo"})
PAYLOAD_FIELD_NAMES = {"payload", "data", "file_data", "tcp_segment_data"}

# These defaults match the previously hard-coded packet record: core metadata,
# every decoded protocol header, transport payload samples, application data,
# and TLS metadata are included unless the operator opts out.
DEFAULT_PACKET_FIELDS = frozenset({
    "metadata.timestamp",
    "metadata.length",
    "metadata.highest_protocol",
    "metadata.protocol_stack",
    "link.ethernet",
    "link.arp",
    "network.ipv4",
    "network.ipv6",
    "network.icmp",
    "network.icmpv6",
    "transport.tcp_headers",
    "transport.tcp_payload",
    "transport.udp_headers",
    "transport.udp_payload",
    "application.http",
    "application.http2",
    "application.dns",
    "application.tls",
    "headers.other",
})

HEADER_LAYER_FIELDS = {
    "link.ethernet": {"eth", "sll", "sll2"},
    "link.arp": {"arp"},
    "network.ipv4": {"ip"},
    "network.ipv6": {"ipv6"},
    "network.icmp": {"icmp"},
    "network.icmpv6": {"icmpv6"},
    "transport.tcp_headers": {"tcp"},
    "transport.udp_headers": {"udp"},
    "application.http": {"http"},
    "application.http2": {"http2"},
    "application.dns": {"dns"},
    "application.tls": {"tls", "ssl"},
}
KNOWN_HEADER_LAYERS = frozenset().union(*HEADER_LAYER_FIELDS.values())


class NetworkWatcher:
    def __init__(self, event_store):
        self._thread = None
        self._stop_event = threading.Event()
        self.watcher_available = _PYSHARK_AVAILABLE
        self.running = False
        self.interface = "eth0"
        self.api_url = "http://localhost:8000/v1/chat/completions"
        self.model = "mamba-130m"
        self.api_key = ""
        self.run_id = None
        self.event_store = event_store
        self.analysis_interval_seconds = DEFAULT_ANALYSIS_INTERVAL_SECONDS
        self.max_packet_payload_bytes = DEFAULT_MAX_PACKET_PAYLOAD_BYTES
        self.max_packets_per_analysis = DEFAULT_MAX_PACKETS_PER_ANALYSIS
        self.packet_fields = set(DEFAULT_PACKET_FIELDS)
        self.capture_source = "python"
        self.suricata_eve_path = DEFAULT_SURICATA_EVE_PATH
        self.suricata_event_types = set(DEFAULT_SURICATA_EVENT_TYPES)
        # Checked once at application startup, then refreshed before a
        # Suricata watcher starts or when the setup UI requests a refresh.
        self.suricata_status = self._refresh_suricata_status(include_version=False)
        self.analysis_engine = "llamacpp_ssm"
        self.ssm_alert_threshold = DEFAULT_SSM_ALERT_THRESHOLD
        self.ssm_alert_cooldown_seconds = DEFAULT_SSM_ALERT_COOLDOWN_SECONDS
        self.use_cyber_agent_flow_data = False
        self._caf_context_mtime = None
        self._caf_context_last_check = 0.0
        self._ssm_runtime = None
        self._last_alert_by_flow = {}
        self._suricata_process = None

        self._buffer = queue.Queue(maxsize=500)
        self._last_flush_time = 0

        # Metrics
        self.packets_captured = 0
        self.packets_analyzed = 0
        self.bytes_extracted = 0
        self.packets_dropped = 0
        self.total_tokens_analyzed = 0
        self.total_inference_time = 0.0
        self.inference_count = 0
        self.inference_in_flight = 0
        self.alerts_emitted = 0
        self.logs = []
        # Keep model diagnostics separate from the general operational log so
        # the UI can clear them without losing capture-status context.
        self._interaction_lock = threading.Lock()
        self.interactions = []
        self.interaction_revision = 0

    def _record_interaction(self, interaction: dict):
        """Retain a bounded, clearable record of each SLM/LLM request."""
        with self._interaction_lock:
            interaction = dict(interaction)
            interaction["id"] = self.interaction_revision + 1
            self.interactions.append(interaction)
            if len(self.interactions) > 100:
                self.interactions = self.interactions[-100:]
            self.interaction_revision += 1
            return interaction["id"]

    def _update_interaction(self, interaction_id: int, **updates):
        """Update a pending interaction once its model request resolves."""
        with self._interaction_lock:
            for interaction in reversed(self.interactions):
                if interaction.get("id") == interaction_id:
                    interaction.update(updates)
                    self.interaction_revision += 1
                    return

    def get_interactions(self) -> tuple[int, list[dict]]:
        with self._interaction_lock:
            return self.interaction_revision, [dict(entry) for entry in self.interactions]

    def clear_interactions(self):
        with self._interaction_lock:
            self.interactions = []
            self.interaction_revision += 1

    def _add_log(self, kind: str, message: str):
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "kind": kind,  # 'info', 'alert', 'packet', 'error'
            "message": message
        }
        self.logs.append(entry)
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    @staticmethod
    def _safe_value(value, max_chars: int = MAX_HEADER_VALUE_CHARS) -> str:
        """Normalize PyShark field values into compact, JSON-safe strings."""
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        value = str(value).replace("\x00", "\\x00")
        return value[:max_chars]

    def _layer_headers(self, layer) -> dict:
        """Collect bounded decoded header fields from a PyShark protocol layer."""
        headers = {}
        for field_name in list(getattr(layer, "field_names", []) or []):
            if len(headers) >= MAX_HEADER_FIELDS_PER_PROTOCOL:
                break
            if field_name in PAYLOAD_FIELD_NAMES or field_name.endswith(".payload"):
                continue
            try:
                value = getattr(layer, field_name, None)
                if value is None and hasattr(layer, "get_field_value"):
                    value = layer.get_field_value(field_name)
                normalized = self._safe_value(value)
                if normalized:
                    headers[field_name] = normalized
            except Exception:
                continue
        return headers

    def _payload_summary(self, raw_hex: str) -> tuple[dict | None, int]:
        """Preserve a bounded TCP/UDP payload without corrupting binary data."""
        try:
            raw = bytes.fromhex((raw_hex or "").replace(":", ""))
        except ValueError:
            return None, 0
        if not raw:
            return None, 0

        sample = raw[:self.max_packet_payload_bytes]
        is_truncated = len(sample) < len(raw)
        try:
            text = sample.decode("utf-8")
            printable_ratio = sum(char.isprintable() or char in "\r\n\t" for char in text) / max(len(text), 1)
        except UnicodeDecodeError:
            text = ""
            printable_ratio = 0

        if printable_ratio >= 0.85:
            return {
                "encoding": "utf-8",
                "data": text,
                "original_bytes": len(raw),
                "truncated": is_truncated,
            }, len(raw)
        return {
            "encoding": "base64",
            "data": base64.b64encode(sample).decode("ascii"),
            "original_bytes": len(raw),
            "truncated": is_truncated,
        }, len(raw)

    def _headers_enabled_for_layer(self, layer_name: str) -> bool:
        """Return whether decoded header fields for a protocol should be forwarded."""
        for field_id, layer_names in HEADER_LAYER_FIELDS.items():
            if field_id in self.packet_fields and layer_name in layer_names:
                return True
        return "headers.other" in self.packet_fields and layer_name not in KNOWN_HEADER_LAYERS

    def _packet_record(self, packet) -> tuple[dict, int]:
        """Build the compact decoded packet representation sent to the model."""
        layers = list(getattr(packet, "layers", []) or [])
        protocol_stack = [getattr(layer, "layer_name", "unknown") for layer in layers]
        headers = {}
        for layer in layers:
            layer_name = getattr(layer, "layer_name", "unknown")
            if not self._headers_enabled_for_layer(layer_name):
                continue
            layer_headers = self._layer_headers(layer)
            if layer_headers:
                headers[layer_name] = layer_headers

        record = {}
        if "metadata.timestamp" in self.packet_fields:
            record["timestamp"] = str(getattr(packet, "sniff_time", ""))
        if "metadata.length" in self.packet_fields:
            record["length"] = self._safe_value(getattr(packet, "length", ""))
        if "metadata.highest_protocol" in self.packet_fields:
            record["highest_protocol"] = self._safe_value(getattr(packet, "highest_layer", ""))
        if "metadata.protocol_stack" in self.packet_fields:
            record["protocol_stack"] = protocol_stack
        if headers:
            record["headers"] = headers

        payloads = {}
        payload_bytes = 0
        for protocol, field_id in (("tcp", "transport.tcp_payload"), ("udp", "transport.udp_payload")):
            if field_id not in self.packet_fields:
                continue
            layer = getattr(packet, protocol, None)
            raw_hex = getattr(layer, "payload", "") if layer else ""
            summary, size = self._payload_summary(raw_hex)
            if summary:
                payloads[protocol] = summary
                payload_bytes += size
        for protocol, field_id in (("http", "application.http"), ("http2", "application.http2"), ("dns", "application.dns")):
            if field_id not in self.packet_fields:
                continue
            layer = getattr(packet, protocol, None)
            if not layer:
                continue
            raw_application_data = getattr(layer, "file_data", None) or getattr(layer, "data", None)
            application_data = self._safe_value(raw_application_data, self.max_packet_payload_bytes)
            if application_data:
                payloads[protocol] = {
                    "encoding": "utf-8",
                    "data": application_data,
                    "truncated": len(str(raw_application_data)) > len(application_data),
                }
        if "application.tls" in self.packet_fields and (getattr(packet, "tls", None) or getattr(packet, "ssl", None)):
            payloads["https"] = {
                "encrypted": True,
                "note": "TLS record bytes are included in tcp payload; plaintext requires configured TLS decryption keys.",
            }
        if payloads:
            record["payloads"] = payloads
        return record, payload_bytes

    def _serialize_packet_batch(self, records: list[dict]) -> str:
        """Keep batch size deterministic before it reaches the model context."""
        selected = []
        records_to_serialize = records if self.max_packets_per_analysis is None else records[:self.max_packets_per_analysis]
        for record in records_to_serialize:
            candidate = selected + [record]
            serialized = json.dumps({"packets": candidate}, ensure_ascii=False, separators=(",", ":"))
            if len(serialized) > MAX_ANALYSIS_CHARS and selected:
                break
            selected = candidate
        return json.dumps({"packet_count": len(selected), "packets": selected}, ensure_ascii=False, separators=(",", ":"))

    def start(self, run_id: str, interface: str, api_url: str, model: str, api_key: str,
              ssl_verify: bool = True, request_timeout: int = 60, system_prompt: str = "",
              analysis_interval_seconds: int = DEFAULT_ANALYSIS_INTERVAL_SECONDS,
              max_packet_payload_bytes: int = DEFAULT_MAX_PACKET_PAYLOAD_BYTES,
              max_packets_per_analysis: int = DEFAULT_MAX_PACKETS_PER_ANALYSIS,
              packet_fields: list[str] | None = None, analysis_engine: str = "llamacpp_ssm",
              ssm_model_path: str = "", ssm_gpu_layers: int = 0,
              ssm_context_tokens: int = 1024, ssm_max_flows: int = 256,
              ssm_alert_threshold: float = DEFAULT_SSM_ALERT_THRESHOLD,
              ssm_alert_cooldown_seconds: int = DEFAULT_SSM_ALERT_COOLDOWN_SECONDS,
              capture_source: str = "python", suricata_eve_path: str = DEFAULT_SURICATA_EVE_PATH,
              suricata_event_types: list[str] | None = None,
              use_cyber_agent_flow_data: bool = False):
        self.capture_source = "suricata_eve" if capture_source == "suricata_eve" else "python"
        if self.capture_source == "python" and not self.watcher_available:
            raise RuntimeError("pyshark is not installed. Select Suricata EVE JSON or install pyshark.")
        if self.capture_source == "suricata_eve":
            status = self._refresh_suricata_status(include_version=True)
            if not status["available"]:
                raise RuntimeError(
                    "Suricata is not installed or not on PATH. Install Suricata on this host before enabling EVE JSON mode."
                )

        self.stop()
        self.run_id = run_id
        self.interface = interface
        self.api_url = api_url
        self.model = model
        self.api_key = api_key
        self.ssl_verify = bool(ssl_verify)
        self.request_timeout = int(request_timeout) if request_timeout else 60
        self.system_prompt = (system_prompt or "").strip()
        self.analysis_interval_seconds = self._bounded_int(
            analysis_interval_seconds,
            DEFAULT_ANALYSIS_INTERVAL_SECONDS,
            1,
            MAX_ANALYSIS_INTERVAL_SECONDS,
        )
        self.max_packet_payload_bytes = self._bounded_int(
            max_packet_payload_bytes,
            DEFAULT_MAX_PACKET_PAYLOAD_BYTES,
            32,
            MAX_CONFIGURED_PACKET_PAYLOAD_BYTES,
        )
        self.max_packets_per_analysis = self._normalize_max_packets(max_packets_per_analysis)
        self.packet_fields = self._normalize_packet_fields(packet_fields)
        self.suricata_eve_path = str(suricata_eve_path or DEFAULT_SURICATA_EVE_PATH).strip()
        self.suricata_event_types = self._normalize_suricata_event_types(suricata_event_types)
        self.use_cyber_agent_flow_data = bool(use_cyber_agent_flow_data)
        self._caf_context_mtime = None
        self._caf_context_last_check = 0.0
        self.analysis_engine = analysis_engine if analysis_engine in {"batch_llm", "llamacpp_ssm", "remote_ssm"} else "llamacpp_ssm"
        self.ssm_alert_threshold = self._bounded_float(
            ssm_alert_threshold, DEFAULT_SSM_ALERT_THRESHOLD, 0.05, 1.0
        )
        self.ssm_alert_cooldown_seconds = self._bounded_int(
            ssm_alert_cooldown_seconds, DEFAULT_SSM_ALERT_COOLDOWN_SECONDS, 0, 3600
        )
        self._last_alert_by_flow = {}
        self._ssm_runtime = None
        if self.analysis_engine == "llamacpp_ssm":
            self._ssm_runtime = LlamaCppSsmRuntime(
                ssm_model_path,
                n_ctx=ssm_context_tokens,
                n_gpu_layers=ssm_gpu_layers,
                max_flows=ssm_max_flows,
            )
            self._ssm_runtime.start()
        elif not self.model:
            raise RuntimeError(
                "Select a model for periodic batch analysis or an SSM model for the remote stream service."
            )

        # Reset metrics & logs
        self.packets_captured = 0
        self.packets_analyzed = 0
        self.bytes_extracted = 0
        self.packets_dropped = 0
        self.total_tokens_analyzed = 0
        self.total_inference_time = 0.0
        self.inference_count = 0
        self.inference_in_flight = 0
        self.alerts_emitted = 0
        self.logs = []
        self.clear_interactions()
        self._buffer = queue.Queue(maxsize=500)

        if self.capture_source == "suricata_eve":
            try:
                self._start_suricata_capture()
            except Exception:
                if self._ssm_runtime:
                    self._ssm_runtime.stop()
                    self._ssm_runtime = None
                raise

        self._stop_event.clear()
        self.running = True

        self._add_log(
            "info",
            f"NetworkWatcher started from {self._capture_source_label()} "
            f"({self._engine_label()}; payload cap {self.max_packet_payload_bytes} B)",
        )

        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="network-watcher-capture"
        )
        self._thread.start()

        self._analyzer_thread = threading.Thread(
            target=self._analyzer_loop,
            daemon=True,
            name="network-watcher-analyzer"
        )
        self._analyzer_thread.start()
        logging.info(f"[NetworkWatcher] Started on interface {self.interface} for run {self.run_id}")

    @staticmethod
    def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(int(value), maximum))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bounded_float(value, default: float, minimum: float, maximum: float) -> float:
        try:
            return max(minimum, min(float(value), maximum))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_packet_fields(packet_fields) -> set[str]:
        if packet_fields is None:
            return set(DEFAULT_PACKET_FIELDS)
        if not isinstance(packet_fields, (list, tuple, set)):
            return set(DEFAULT_PACKET_FIELDS)
        return {str(field) for field in packet_fields if str(field) in DEFAULT_PACKET_FIELDS}

    @staticmethod
    def _normalize_suricata_event_types(event_types) -> set[str]:
        if event_types is None:
            return set(DEFAULT_SURICATA_EVENT_TYPES)
        if not isinstance(event_types, (list, tuple, set)):
            return set(DEFAULT_SURICATA_EVENT_TYPES)
        return {str(event_type) for event_type in event_types if str(event_type) in DEFAULT_SURICATA_EVENT_TYPES}

    @staticmethod
    def _normalize_max_packets(value) -> int | None:
        """Treat zero as unlimited, while retaining a safe queue-backed upper bound."""
        try:
            if int(value) == 0:
                return None
        except (TypeError, ValueError):
            pass
        return NetworkWatcher._bounded_int(
            value,
            DEFAULT_MAX_PACKETS_PER_ANALYSIS,
            1,
            MAX_CONFIGURED_PACKETS_PER_ANALYSIS,
        )

    def _max_packets_label(self) -> str:
        return "unlimited" if self.max_packets_per_analysis is None else str(self.max_packets_per_analysis)

    def _engine_label(self) -> str:
        if self.analysis_engine == "batch_llm":
            return f"periodic packet-batch LLM; sends every {self.analysis_interval_seconds}s"
        if self.analysis_engine == "llamacpp_ssm":
            return "local llama.cpp recurrent SSM; every packet processed immediately"
        return "remote SSM stream service; every normalized event is sent immediately"

    def _capture_source_label(self) -> str:
        if self.capture_source == "suricata_eve":
            return f"Suricata EVE JSON ({self.suricata_eve_path})"
        return f"Python packet decoder on interface {self.interface}"

    def _start_suricata_capture(self):
        """Launch Suricata for one selected live interface before tailing EVE."""
        selected_interfaces = [value.strip() for value in str(self.interface or "").split(",") if value.strip()]
        if len(selected_interfaces) != 1:
            raise RuntimeError("Suricata EVE mode requires exactly one selected network interface.")
        interface = selected_interfaces[0]
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", interface):
            raise RuntimeError("Suricata EVE mode received an invalid network interface name.")
        executable = self.suricata_status.get("executable") or shutil.which("suricata")
        if not executable:
            raise RuntimeError("Suricata is not installed or not on PATH.")

        log_directory = os.path.dirname(os.path.abspath(self.suricata_eve_path))
        if not log_directory:
            raise RuntimeError("Enter a valid Suricata EVE JSON path.")
        try:
            os.makedirs(log_directory, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Could not create Suricata log directory {log_directory}: {exc}") from exc

        command = [executable, "-i", interface, "-l", log_directory]
        try:
            self._suricata_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start Suricata on {interface}: {exc}") from exc
        self._add_log("info", f"Started Suricata on {interface}; writing EVE under {log_directory}.")

    def _refresh_suricata_status(self, include_version: bool = True) -> dict:
        """Return local Suricata readiness without modifying the host system."""
        executable = shutil.which("suricata")
        status = {"available": bool(executable), "executable": executable or "", "version": ""}
        if executable and include_version:
            try:
                result = subprocess.run(
                    [executable, "-V"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                status["version"] = (result.stdout or result.stderr or "").strip().splitlines()[0][:160]
            except (OSError, subprocess.SubprocessError):
                status["version"] = "Detected (version probe unavailable)"
        self.suricata_status = status
        return status

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if hasattr(self, '_analyzer_thread') and self._analyzer_thread and self._analyzer_thread.is_alive():
            self._analyzer_thread.join(timeout=3)
        self._thread = None
        self._analyzer_thread = None
        if self._ssm_runtime:
            self._ssm_runtime.stop()
            self._ssm_runtime = None
        if self._suricata_process:
            if self._suricata_process.poll() is None:
                self._suricata_process.terminate()
                try:
                    self._suricata_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._suricata_process.kill()
            self._suricata_process = None
        self._add_log("info", "NetworkWatcher stopped.")
        logging.info("[NetworkWatcher] Stopped.")

    def _check_bpf_permissions(self) -> bool:
        """Check if macOS /dev/bpf* devices are accessible by current user."""
        if os.path.exists('/dev/bpf0'):
            if not os.access('/dev/bpf0', os.R_OK | os.W_OK):
                try:
                    os.system('sudo -n chmod 666 /dev/bpf* >/dev/null 2>&1')
                except Exception:
                    pass
                if not os.access('/dev/bpf0', os.R_OK | os.W_OK):
                    return False
        return True

    def status(self) -> dict:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        avg_inference = 0.0
        if self.inference_count > 0:
            avg_inference = self.total_inference_time / self.inference_count

        bpf_ok = self.capture_source != "python" or self._check_bpf_permissions()
        with self._interaction_lock:
            interaction_revision = self.interaction_revision
            interaction_count = len(self.interactions)

        return {
            "available": self.watcher_available if self.capture_source == "python" else True,
            "running": self.running,
            "interface": self.interface,
            "api_url": self.api_url,
            "model": self.model,
            "configuration": {
                "capture_source": self.capture_source,
                "suricata_status": dict(self.suricata_status),
                "suricata_eve_path": self.suricata_eve_path,
                "suricata_event_types": sorted(self.suricata_event_types),
                "analysis_engine": self.analysis_engine,
                "analysis_interval_seconds": self.analysis_interval_seconds,
                "max_packet_payload_bytes": self.max_packet_payload_bytes,
                "max_packets_per_analysis": self.max_packets_per_analysis,
                "packet_fields": sorted(self.packet_fields),
                "use_cyber_agent_flow_data": self.use_cyber_agent_flow_data,
                "ssm_alert_threshold": self.ssm_alert_threshold,
                "ssm_alert_cooldown_seconds": self.ssm_alert_cooldown_seconds,
            },
            "ssm_runtime": self._ssm_runtime.status() if self._ssm_runtime else ({
                "available": True,
                "loaded": self.running,
                "remote": True,
                "endpoint": self._remote_ssm_endpoint(),
                "model": self.model,
            } if self.analysis_engine == "remote_ssm" else None),
            "bpf_permission_ok": bpf_ok,
            "capture_error": getattr(self, 'capture_error', None),
            "interaction_revision": interaction_revision,
            "interaction_count": interaction_count,
            "metrics": {
                "cpu_percent": cpu_percent,
                "mem_used_mb": mem.used // (1024 * 1024),
                "mem_free_mb": mem.available // (1024 * 1024),
                "mem_percent": mem.percent,
                "packets_captured": self.packets_captured,
                "packets_analyzed": self.packets_analyzed,
                "bytes_extracted": self.bytes_extracted,
                "packets_dropped": self.packets_dropped,
                "total_tokens": self.total_tokens_analyzed,
                "inference_count": self.inference_count,
                "inference_in_flight": self.inference_in_flight,
                "avg_inference_sec": round(avg_inference, 2),
                "alerts_emitted": self.alerts_emitted,
            }
        }

    def _capture_loop(self):
        if self.capture_source == "suricata_eve":
            self._suricata_eve_loop()
            return

        self.capture_error = None
        if not self._check_bpf_permissions():
            msg = "BPF Permission Denied: /dev/bpf* is not readable. Run 'sudo chmod 666 /dev/bpf*' in terminal to allow packet capture."
            logging.error(f"[NetworkWatcher] {msg}")
            self._add_log("error", msg)
            self.capture_error = msg
            # Try to run chmod 666 /dev/bpf* via sudo helper if available

        try:
            # Parse interfaces: if comma separated, make a list
            if isinstance(self.interface, str) and ',' in self.interface:
                ifaces = [i.strip() for i in self.interface.split(',') if i.strip()]
            else:
                ifaces = self.interface

            logging.info(f"[NetworkWatcher] Starting LiveCapture on {ifaces}")
            self._add_log("info", f"Listening on interface: {ifaces}")

            # Keep filtering in libpcap/TShark while Python normalizes only
            # decoded records that will be forwarded to the model.
            capture = pyshark.LiveCapture(
                interface=ifaces,
                bpf_filter="tcp or udp or icmp or icmp6 or arp"
            )
            for packet in capture.sniff_continuously():
                if self._stop_event.is_set():
                    break

                try:
                    record, payload_bytes = self._packet_record(packet)
                    self._enqueue_record(record, payload_bytes, "Captured")
                except Exception:
                    continue
        except Exception as e:
            err_msg = f"Capture failed: {e}"
            logging.error(f"[NetworkWatcher] {err_msg}")
            self._add_log("error", err_msg)
            self.capture_error = err_msg
            self.running = False

    def _enqueue_record(self, record: dict, extracted_bytes: int, noun: str):
        self.packets_captured += 1
        self.bytes_extracted += extracted_bytes
        try:
            self._buffer.put_nowait(record)
        except queue.Full:
            self.packets_dropped += 1
        if self.packets_captured % 10 == 0:
            self._add_log("packet", f"{noun} {self.packets_captured} events ({self.bytes_extracted} bytes normalized)")

    def _suricata_eve_loop(self):
        """Tail newly-written EVE JSON lines and normalize selected event types."""
        self.capture_error = None
        handle = None
        inode = None
        position = 0
        self._add_log("info", f"Tailing Suricata EVE JSON: {self.suricata_eve_path}")
        try:
            while not self._stop_event.is_set():
                if self._suricata_process and self._suricata_process.poll() is not None:
                    self.capture_error = "Suricata exited before the watcher was stopped. Check its local configuration and capture permissions."
                    self._add_log("error", self.capture_error)
                    self.running = False
                    return
                try:
                    stat = os.stat(self.suricata_eve_path)
                    rotated = inode is not None and inode != stat.st_ino
                    truncated = handle is not None and stat.st_size < position
                    if handle is None or rotated or truncated:
                        if handle:
                            handle.close()
                        handle = open(self.suricata_eve_path, "r", encoding="utf-8", errors="replace")
                        handle.seek(0, os.SEEK_END)
                        position = handle.tell()
                        inode = stat.st_ino
                        self._add_log("info", "Connected to Suricata EVE stream; reading new events only.")

                    line = handle.readline()
                    if not line:
                        self._stop_event.wait(0.2)
                        continue
                    position = handle.tell()
                    try:
                        eve_event = json.loads(line)
                    except json.JSONDecodeError:
                        self._add_log("error", "Skipped malformed Suricata EVE JSON line.")
                        continue
                    if not isinstance(eve_event, dict):
                        self._add_log("error", "Skipped non-object Suricata EVE JSON record.")
                        continue
                    record = self._suricata_record(eve_event)
                    if record is not None:
                        self._enqueue_record(record, len(line.encode("utf-8")), "Ingested")
                except FileNotFoundError:
                    self._add_log("info", f"Waiting for Suricata EVE file: {self.suricata_eve_path}")
                    self._stop_event.wait(1)
                except OSError as exc:
                    self.capture_error = f"Suricata EVE read failed: {exc}"
                    self._add_log("error", self.capture_error)
                    self._stop_event.wait(1)
        finally:
            if handle:
                handle.close()

    def _suricata_record(self, eve_event: dict) -> dict | None:
        """Reduce an EVE record to bounded, model-safe network features."""
        event_type = str(eve_event.get("event_type") or "")
        if event_type not in self.suricata_event_types:
            return None

        proto = str(eve_event.get("proto") or "").lower()
        app_proto = str(eve_event.get("app_proto") or "").lower()
        source_ip = self._safe_value(eve_event.get("src_ip"))
        destination_ip = self._safe_value(eve_event.get("dest_ip"))
        source_port = self._safe_value(eve_event.get("src_port"))
        destination_port = self._safe_value(eve_event.get("dest_port"))
        headers = {
            "ip": {"src": source_ip, "dst": destination_ip},
            "suricata": self._suricata_summary(eve_event, event_type),
        }
        if proto in {"tcp", "udp"}:
            headers[proto] = {"srcport": source_port, "dstport": destination_port}
        if event_type in {"http", "dns", "tls"}:
            headers[event_type] = {"present": True}

        return {
            "timestamp": self._safe_value(eve_event.get("timestamp")),
            "length": self._safe_value((eve_event.get("flow") or {}).get("bytes_toserver") or "0"),
            "highest_protocol": app_proto or proto or event_type,
            "protocol_stack": ["suricata", event_type, *([app_proto] if app_proto else [])],
            "headers": headers,
        }

    def _suricata_summary(self, eve_event: dict, event_type: str) -> dict:
        """Allowlist EVE fields so large/unsafe nested JSON never reaches the model."""
        summary = {
            "event_type": event_type,
            "flow_id": self._safe_value(eve_event.get("flow_id")),
            "community_id": self._safe_value(eve_event.get("community_id")),
            "proto": self._safe_value(eve_event.get("proto")),
            "app_proto": self._safe_value(eve_event.get("app_proto")),
        }
        nested_fields = {
            "flow": ("pkts_toserver", "pkts_toclient", "bytes_toserver", "bytes_toclient", "state", "reason"),
            "dns": ("type", "rrname", "rrtype", "rcode"),
            "http": ("hostname", "url", "http_method", "status", "http_user_agent"),
            "tls": ("sni", "version", "cipher", "ja3", "ja3s", "ja4"),
            "alert": ("signature", "category", "severity", "action", "gid", "signature_id"),
            "anomaly": ("type", "event", "layer", "code"),
            "fileinfo": ("filename", "magic", "mime", "sha256", "state", "size"),
        }
        nested = eve_event.get(event_type) or {}
        if isinstance(nested, dict):
            for field_name in nested_fields.get(event_type, ()):
                value = self._safe_value(nested.get(field_name))
                if value:
                    summary[field_name] = value
        return {key: value for key, value in summary.items() if value not in ("", None)}

    def _analyzer_loop(self):
        if self.analysis_engine in {"llamacpp_ssm", "remote_ssm"}:
            self._stream_analyzer_loop()
            return
        while not self._stop_event.is_set():
            batch = []
            # Gather a bounded number of decoded packet records in each batch.
            while self.max_packets_per_analysis is None or len(batch) < self.max_packets_per_analysis:
                try:
                    batch.append(self._buffer.get_nowait())
                except queue.Empty:
                    break

            if batch:
                self.packets_analyzed += len(batch)
                self._analyze_batch(batch)

            # Wait between sends, but allow stop() to interrupt immediately.
            self._stop_event.wait(self.analysis_interval_seconds)

    def _stream_analyzer_loop(self):
        """Consume events as they arrive; no batch prompt or network round trip."""
        while not self._stop_event.is_set():
            try:
                record = self._buffer.get(timeout=0.25)
            except queue.Empty:
                continue
            self.packets_analyzed += 1
            self._analyze_stream_record(record)

    def _analyze_stream_record(self, record: dict):
        if self.analysis_engine == "llamacpp_ssm" and not self._ssm_runtime:
            return
        started = time.time()
        flow_key = packet_flow_key(record)
        event = packet_stream_event(record)
        cyber_agent_flow_update = self._cyber_agent_flow_update()
        if cyber_agent_flow_update:
            event["cyber_agent_flow"] = {"transcript_update": cyber_agent_flow_update}
        interaction_id = self._record_interaction({
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "engine": "llamacpp_ssm",
            "model": self._ssm_runtime.model_path if self._ssm_runtime else self.model,
            "endpoint": "local llama-cpp-python runtime" if self._ssm_runtime else self._remote_ssm_endpoint(),
            "request": {"flow": flow_key, "event": event},
            "prompt": "",
            "response": "",
            "http_status": None,
            "elapsed_ms": None,
            "outcome": "pending",
            "error": "",
            "analysis": "",
        })
        try:
            observation = self._ssm_runtime.observe(flow_key, event) if self._ssm_runtime else self._observe_remote_ssm(flow_key, event)
            elapsed = time.time() - started
            self.total_inference_time += elapsed
            self.inference_count += 1
            self.total_tokens_analyzed += len(observation.event) // 4
            is_alert = self._should_emit_ssm_alert(observation.flow_key, observation.score)
            analysis = (
                f"{'Alert' if is_alert else 'Stream score'} {observation.score:.3f} "
                f"for flow {observation.flow_key} ({observation.active_flows} active flow states)."
            )
            self._update_interaction(
                interaction_id,
                response=json.dumps({"score": observation.score, "flow": observation.flow_key}),
                elapsed_ms=round(elapsed * 1000),
                outcome="success",
                analysis=analysis,
            )
            if is_alert:
                self.alerts_emitted += 1
                self._add_log("alert", f"SSM alert score {observation.score:.3f}: {observation.flow_key}")
                self._emit_alert(
                    f"Local SSM anomaly score {observation.score:.3f} exceeded the "
                    f"{self.ssm_alert_threshold:.2f} threshold for flow {observation.flow_key}."
                )
        except Exception as exc:
            elapsed = time.time() - started
            self.total_inference_time += elapsed
            self.inference_count += 1
            self._update_interaction(
                interaction_id,
                elapsed_ms=round(elapsed * 1000),
                outcome="error",
                error=str(exc),
                analysis="",
            )
            self._add_log("error", f"SSM event evaluation failed: {exc}")

    def _cyber_agent_flow_update(self) -> str:
        """Return a bounded transcript update only when the active run changes."""
        if not self.use_cyber_agent_flow_data or not self.run_id:
            return ""
        now = time.monotonic()
        if now - self._caf_context_last_check < 1.0:
            return ""
        self._caf_context_last_check = now
        transcript_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "runs", str(self.run_id), "transcript.md"
        )
        try:
            stat = os.stat(transcript_path)
            if self._caf_context_mtime == stat.st_mtime_ns:
                return ""
            with open(transcript_path, "rb") as transcript:
                transcript.seek(max(0, stat.st_size - MAX_CYBER_AGENT_FLOW_CONTEXT_CHARS))
                update = transcript.read(MAX_CYBER_AGENT_FLOW_CONTEXT_CHARS).decode("utf-8", errors="replace").strip()
            self._caf_context_mtime = stat.st_mtime_ns
            return update
        except OSError:
            return ""

    def _remote_ssm_endpoint(self) -> str:
        """Map an existing provider base URL to the explicit stream-service contract."""
        target_url = (self.api_url or "").rstrip("/")
        for suffix in ("/v1/chat/completions", "/v1/completions", "/api/chat", "/v1/models", "/api/tags"):
            if target_url.endswith(suffix):
                target_url = target_url[:-len(suffix)]
                break
        if target_url.endswith("/v1"):
            target_url = target_url[:-3]
        return f"{target_url}/v1/ssm/events"

    def _observe_remote_ssm(self, flow_key: str, event: dict) -> SsmObservation:
        """Send one normalized event to a remote service that owns per-flow state."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = requests.post(
            self._remote_ssm_endpoint(),
            json={"model": self.model, "flow_key": flow_key, "event": event},
            headers=headers,
            timeout=(10, self.request_timeout),
            verify=self.ssl_verify,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Remote SSM service returned HTTP {response.status_code}.")
        payload = response.json() or {}
        score = self._bounded_float(
            payload.get("score", payload.get("anomaly_score")), 0.0, 0.0, 1.0
        )
        return SsmObservation(
            flow_key=str(payload.get("flow_key") or flow_key),
            event=json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            score=score,
            model_score=score,
            active_flows=self._bounded_int(payload.get("active_flows"), 0, 0, 1_000_000),
        )

    def _should_emit_ssm_alert(self, flow_key: str, score: float) -> bool:
        if score < self.ssm_alert_threshold:
            return False
        now = time.monotonic()
        last_alert = self._last_alert_by_flow.get(flow_key)
        if last_alert is not None and now - last_alert < self.ssm_alert_cooldown_seconds:
            return False
        self._last_alert_by_flow[flow_key] = now
        return True

    def _analyze_batch(self, batch: list[dict]):
        serialized_batch = self._serialize_packet_batch(batch)
        estimated_tokens = len(serialized_batch) // 4
        self.total_tokens_analyzed += estimated_tokens

        base_instructions = self.system_prompt if (hasattr(self, 'system_prompt') and self.system_prompt and self.system_prompt.strip()) else (
            "You are an anomaly detection SSM watching a live packet stream. "
            "Review the structured packet records: protocol stack, decoded headers, and bounded payloads. "
            "Treat HTTPS payload bytes as encrypted unless the record explicitly contains decoded HTTP data. "
            "If you see plaintext credentials, API keys, sensitive server banners, or anything notable, "
            "state the finding in 2-3 concise sentences. Return only the final observation, with no internal reasoning. "
            "If nothing interesting is found, say that clearly."
        )

        cyber_agent_flow_update = self._cyber_agent_flow_update()
        cyber_agent_flow_section = (
            f"\n\nCYBER_AGENT_FLOW_UPDATE:\n{cyber_agent_flow_update}"
            if cyber_agent_flow_update else ""
        )
        prompt = f"{base_instructions}\n\nPACKETS_JSON:\n{serialized_batch}{cyber_agent_flow_section}"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        target_url = (self.api_url or '').rstrip('/')
        if not (target_url.endswith('/v1/chat/completions') or target_url.endswith('/api/chat') or target_url.endswith('/v1/completions')):
            target_url = f"{target_url}/v1/chat/completions"

        if target_url.endswith('/api/chat'):
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1}
            }
        else:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 150
            }

        interaction_id = self._record_interaction({
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "model": self.model,
            "endpoint": target_url,
            "request": payload,
            "prompt": prompt,
            "response": "",
            "http_status": None,
            "elapsed_ms": None,
            "outcome": "pending",
            "error": "",
            "analysis": "",
        })
        start_time = time.time()
        response_text = ""
        response_received = False
        response_status = None
        request_started = False
        try:
            self._add_log("info", f"Analyzing {len(batch)} decoded packets ({len(serialized_batch)} chars, ~{estimated_tokens} tokens)...")
            verify_ssl = getattr(self, 'ssl_verify', True)
            read_timeout = getattr(self, 'request_timeout', 60)
            self.inference_in_flight += 1
            request_started = True
            resp = requests.post(target_url, json=payload, headers=headers, timeout=(10, read_timeout), verify=verify_ssl)
            elapsed = time.time() - start_time
            self.total_inference_time += elapsed
            self.inference_count += 1
            response_text = getattr(resp, "text", "")
            response_received = True
            response_status = resp.status_code

            if resp.status_code == 200:
                data = resp.json()
                content = ""
                reasoning_content = ""
                if "choices" in data and len(data["choices"]):
                    message = data["choices"][0].get("message", {})
                    content = message.get("content", "").strip()
                    reasoning_content = message.get("reasoning_content", "").strip()
                elif "message" in data:
                    content = data["message"].get("content", "").strip()
                    reasoning_content = data["message"].get("reasoning_content", "").strip()
                analysis = content or reasoning_content

                if analysis:
                    self._add_log("alert" if "alert" in analysis.lower() else "info", f"SSM Analysis Output: {analysis}")
                    if "alert" in analysis.lower():
                        self.alerts_emitted += 1
                        self._emit_alert(analysis)
                else:
                    self._add_log("info", "Model returned no final analysis text.")
                self._update_interaction(
                    interaction_id,
                    response=response_text,
                    http_status=resp.status_code,
                    elapsed_ms=round(elapsed * 1000),
                    outcome="success",
                    error="",
                    analysis=analysis,
                )
            else:
                self._add_log("error", f"SSM API ({target_url}) returned status {resp.status_code}")
                self._update_interaction(
                    interaction_id,
                    response=response_text,
                    http_status=resp.status_code,
                    elapsed_ms=round(elapsed * 1000),
                    outcome="http_error",
                    error=f"HTTP {resp.status_code}",
                )
        except Exception as e:
            elapsed = time.time() - start_time
            if not response_received:
                self.total_inference_time += elapsed
                self.inference_count += 1
            logging.error(f"[NetworkWatcher] SSM API error: {e}")
            self._add_log("error", f"SSM API request failed: {e}")
            self._update_interaction(
                interaction_id,
                response=response_text,
                http_status=response_status,
                elapsed_ms=round(elapsed * 1000),
                outcome="error",
                error=str(e),
            )
        finally:
            if request_started:
                self.inference_in_flight = max(0, self.inference_in_flight - 1)

    def _emit_alert(self, message: str):
        if not self.run_id or not self.event_store:
            return

        logging.info(f"[NetworkWatcher] Alert emitted: {message}")
        self.event_store.append_event(
            self.run_id,
            None,
            "agent_alert",
            {
                "source": "NetworkWatcher (SSM)",
                "message": message,
                "urgency": "high"
            }
        )
