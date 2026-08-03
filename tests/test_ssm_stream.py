from ssm_stream import packet_flow_key, packet_stream_event


def _packet(src="10.0.0.5", dst="10.0.0.10", src_port="52100", dst_port="443"):
    return {
        "length": "74",
        "highest_protocol": "TCP",
        "protocol_stack": ["eth", "ip", "tcp", "tls"],
        "headers": {
            "ip": {"src": src, "dst": dst},
            "tcp": {"srcport": src_port, "dstport": dst_port, "flags": "0x0018"},
            "tls": {"record_content_type": "23"},
        },
        "payloads": {"tcp": {"data": "not included in the event"}},
    }


def test_flow_key_is_direction_independent():
    forward = _packet()
    reverse = _packet(src="10.0.0.10", dst="10.0.0.5", src_port="443", dst_port="52100")

    assert packet_flow_key(forward) == packet_flow_key(reverse)


def test_stream_event_excludes_packet_payload_and_keeps_compact_features():
    event = packet_stream_event(_packet())

    assert event["p"] == "tcp"
    assert event["len"] == "74"
    assert event["dst_port"] == "443"
    assert event["app"] == ["tls"]
    assert "payload" not in event
    assert "not included in the event" not in str(event)
