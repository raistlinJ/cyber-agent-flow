import os
import threading
import json
import time
import requests
import queue
import logging
import psutil

try:
    import pyshark
    _PYSHARK_AVAILABLE = True
except ImportError:
    _PYSHARK_AVAILABLE = False


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

        self._buffer = queue.Queue()
        self._last_flush_time = 0
        
        # Metrics
        self.packets_captured = 0
        self.bytes_extracted = 0
        self.total_inference_time = 0.0
        self.inference_count = 0

    def start(self, run_id: str, interface: str, api_url: str, model: str, api_key: str):
        if not self.watcher_available:
            raise RuntimeError("pyshark is not installed.")
        
        self.stop()
        self.run_id = run_id
        self.interface = interface
        self.api_url = api_url
        self.model = model
        self.api_key = api_key
        
        # Reset metrics
        self.packets_captured = 0
        self.bytes_extracted = 0
        self.total_inference_time = 0.0
        self.inference_count = 0
        
        self._stop_event.clear()
        self.running = True
        
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

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if hasattr(self, '_analyzer_thread') and self._analyzer_thread and self._analyzer_thread.is_alive():
            self._analyzer_thread.join(timeout=3)
        self._thread = None
        self._analyzer_thread = None
        logging.info("[NetworkWatcher] Stopped.")

    def status(self) -> dict:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        
        avg_inference = 0.0
        if self.inference_count > 0:
            avg_inference = self.total_inference_time / self.inference_count
            
        return {
            "available": self.watcher_available,
            "running": self.running,
            "interface": self.interface,
            "api_url": self.api_url,
            "model": self.model,
            "metrics": {
                "cpu_percent": cpu_percent,
                "mem_used_mb": mem.used // (1024 * 1024),
                "mem_free_mb": mem.available // (1024 * 1024),
                "mem_percent": mem.percent,
                "packets_captured": self.packets_captured,
                "bytes_extracted": self.bytes_extracted,
                "avg_inference_sec": round(avg_inference, 2)
            }
        }

    def _capture_loop(self):
        try:
            # Parse interfaces: if comma separated, make a list
            if isinstance(self.interface, str) and ',' in self.interface:
                ifaces = [i.strip() for i in self.interface.split(',') if i.strip()]
            else:
                ifaces = self.interface

            capture = pyshark.LiveCapture(
                interface=ifaces,
                bpf_filter="tcp and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12]&0xf0)>>2)) != 0)"
            )
            for packet in capture.sniff_continuously():
                if self._stop_event.is_set():
                    break
                
                try:
                    self.packets_captured += 1
                    if hasattr(packet, 'tcp') and hasattr(packet.tcp, 'payload'):
                        # Extract raw ASCII payload
                        raw_hex = packet.tcp.payload.replace(':', '')
                        try:
                            ascii_text = bytearray.fromhex(raw_hex).decode('utf-8', errors='ignore')
                            if ascii_text.strip():
                                self.bytes_extracted += len(ascii_text)
                                self._buffer.put(ascii_text)
                        except Exception:
                            pass
                except AttributeError:
                    continue
        except Exception as e:
            logging.error(f"[NetworkWatcher] Capture error: {e}")
            self.running = False

    def _analyzer_loop(self):
        while not self._stop_event.is_set():
            batch = ""
            # Gather available text in buffer
            while not self._buffer.empty():
                try:
                    batch += self._buffer.get_nowait() + "\n"
                except queue.Empty:
                    break
            
            if batch.strip():
                self._analyze_batch(batch)
            
            # Wait a bit before next batch to prevent spamming
            time.sleep(5)

    def _analyze_batch(self, batch: str):
        prompt = (
            "You are an anomaly detection SSM watching a live packet stream. "
            "Describe anything interesting; meaning ascii or anything that can be inferred from it. "
            "If you see plaintext credentials, API keys, sensitive server banners, or anything notable, "
            "output a concise JSON alert like {\"alert\": \"<description>\"}. "
            "If nothing interesting is found, output nothing.\n\n"
            "PAYLOAD:\n"
            f"{batch[:4000]}"  # cap to 4k chars per request as safety
        )

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 150
        }

        try:
            start_time = time.time()
            resp = requests.post(self.api_url, json=payload, headers=headers, timeout=10)
            elapsed = time.time() - start_time
            self.total_inference_time += elapsed
            self.inference_count += 1
            
            if resp.status_code == 200:
                data = resp.json()
                content = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                if content and "alert" in content.lower():
                    # Parse out alert if it is JSON or just output raw
                    self._emit_alert(content)
        except Exception as e:
            logging.error(f"[NetworkWatcher] SSM API error: {e}")

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
