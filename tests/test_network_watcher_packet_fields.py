import json
from types import SimpleNamespace

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
