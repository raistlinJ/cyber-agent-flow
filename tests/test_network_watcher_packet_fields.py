import json
from types import SimpleNamespace

import pytest

import network_watcher
from network_watcher import DEFAULT_PACKET_FIELDS, NetworkWatcher


def _layer(name, **fields):
    return SimpleNamespace(layer_name=name, field_names=list(fields), **fields)


def _packet(*layers):
    packet = SimpleNamespace(
        layers=list(layers),
        sniff_time="2026-08-02 23:00:00",
        length="128",
        highest_layer="HTTP",
    )
    for layer in layers:
        setattr(packet, layer.layer_name, layer)
    return packet


def test_default_packet_fields_preserve_existing_decoded_output():
    watcher = NetworkWatcher(event_store=None)
    eth = _layer("eth", src="00:11:22:33:44:55", dst="66:77:88:99:aa:bb")
    ip = _layer("ip", src="192.0.2.1", dst="198.51.100.2")
    tcp = _layer("tcp", srcport="443", dstport="50123", payload="68656c6c6f")
    http = _layer("http", request_method="GET", host="example.test")
    packet = _packet(eth, ip, tcp, http)

    record, payload_bytes = watcher._packet_record(packet)

    assert watcher.packet_fields == set(DEFAULT_PACKET_FIELDS)
    assert record["timestamp"] == "2026-08-02 23:00:00"
    assert record["length"] == "128"
    assert record["protocol_stack"] == ["eth", "ip", "tcp", "http"]
    assert set(record["headers"]) == {"eth", "ip", "tcp", "http"}
    assert record["payloads"]["tcp"]["data"] == "hello"
    assert payload_bytes == 5


def test_packet_field_selection_limits_metadata_headers_and_payloads():
    watcher = NetworkWatcher(event_store=None)
    watcher.packet_fields = {"metadata.length", "network.ipv4", "transport.tcp_payload"}
    watcher.max_packet_payload_bytes = 4
    eth = _layer("eth", src="00:11:22:33:44:55")
    ip = _layer("ip", src="192.0.2.1", dst="198.51.100.2")
    tcp = _layer("tcp", srcport="443", payload="68656c6c6f")

    record, payload_bytes = watcher._packet_record(_packet(eth, ip, tcp))

    assert record == {
        "length": "128",
        "headers": {"ip": {"src": "192.0.2.1", "dst": "198.51.100.2"}},
        "payloads": {
            "tcp": {
                "encoding": "utf-8",
                "data": "hell",
                "original_bytes": 5,
                "truncated": True,
            }
        },
    }
    assert payload_bytes == 5


def test_packet_field_configuration_is_normalized_and_bounded():
    watcher = NetworkWatcher(event_store=None)

    assert watcher._normalize_packet_fields(["metadata.length", "not.a.real.field"]) == {"metadata.length"}
    assert watcher._normalize_packet_fields(None) == set(DEFAULT_PACKET_FIELDS)
    assert watcher._bounded_int("9000", 384, 32, 8192) == 8192
    assert watcher._bounded_int("invalid", 384, 32, 8192) == 384
    assert watcher._normalize_max_packets("500") == 500
    assert watcher._normalize_max_packets("0") is None


def test_unlimited_packet_cap_serializes_all_available_records():
    watcher = NetworkWatcher(event_store=None)
    records = [{"packet": index} for index in range(3)]

    watcher.max_packets_per_analysis = 2
    assert json.loads(watcher._serialize_packet_batch(records))["packet_count"] == 2

    watcher.max_packets_per_analysis = None
    assert json.loads(watcher._serialize_packet_batch(records))["packet_count"] == 3


def test_ssm_alert_threshold_respects_per_flow_cooldown():
    watcher = NetworkWatcher(event_store=None)
    watcher.ssm_alert_threshold = 0.72
    watcher.ssm_alert_cooldown_seconds = 60

    assert watcher._should_emit_ssm_alert("tcp|a:1|b:443", 0.72)
    assert not watcher._should_emit_ssm_alert("tcp|a:1|b:443", 0.90)
    assert not watcher._should_emit_ssm_alert("tcp|a:1|b:443", 0.71)
    assert watcher._should_emit_ssm_alert("tcp|c:1|d:443", 0.90)


def test_suricata_eve_record_is_normalized_to_the_shared_flow_shape():
    watcher = NetworkWatcher(event_store=None)
    eve = {
        "timestamp": "2026-08-03T16:00:00.000000+0000",
        "event_type": "tls",
        "flow_id": 123456,
        "community_id": "1:example",
        "src_ip": "192.0.2.10",
        "dest_ip": "198.51.100.20",
        "src_port": 50000,
        "dest_port": 443,
        "proto": "TCP",
        "app_proto": "tls",
        "tls": {"sni": "api.example.test", "version": "TLS 1.3", "ja3": "abc"},
    }

    record = watcher._suricata_record(eve)

    assert record["highest_protocol"] == "tls"
    assert record["headers"]["ip"] == {"src": "192.0.2.10", "dst": "198.51.100.20"}
    assert record["headers"]["tcp"] == {"srcport": "50000", "dstport": "443"}
    assert record["headers"]["suricata"]["sni"] == "api.example.test"
    assert record["headers"]["tls"] == {"present": True}


def test_suricata_event_selection_filters_unselected_types():
    watcher = NetworkWatcher(event_store=None)
    watcher.suricata_event_types = {"flow"}

    assert watcher._suricata_record({"event_type": "dns"}) is None
    assert watcher._suricata_record({"event_type": "flow", "flow": {"state": "established"}})


def test_remote_ssm_endpoint_uses_the_explicit_stream_contract():
    watcher = NetworkWatcher(event_store=None)
    watcher.api_url = "https://gpu.example.test/v1/models"

    assert watcher._remote_ssm_endpoint() == "https://gpu.example.test/v1/ssm/events"


def test_cyber_agent_flow_context_is_bounded_and_only_sent_on_updates(tmp_path, monkeypatch):
    transcript = tmp_path / "runs" / "run-1" / "transcript.md"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("first session update", encoding="utf-8")
    monkeypatch.setattr(network_watcher.os.path, "abspath", lambda _path: str(tmp_path / "network_watcher.py"))

    watcher = NetworkWatcher(event_store=None)
    watcher.run_id = "run-1"
    watcher.use_cyber_agent_flow_data = True

    assert watcher._cyber_agent_flow_update() == "first session update"
    assert watcher._cyber_agent_flow_update() == ""


def test_suricata_readiness_gate_blocks_eve_mode_when_binary_is_missing(monkeypatch):
    watcher = NetworkWatcher(event_store=None)
    monkeypatch.setattr(watcher, "_refresh_suricata_status", lambda include_version=True: {
        "available": False, "executable": "", "version": ""
    })

    with pytest.raises(RuntimeError, match="Suricata is not installed"):
        watcher.start(
            "run", "ignored", "", "", "",
            capture_source="suricata_eve",
        )
