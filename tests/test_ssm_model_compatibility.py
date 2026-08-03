from app import _detect_ssm_compatibility, _extract_provider_models


def test_ssm_compatibility_marks_known_recurrent_families_as_likely():
    result = _detect_ssm_compatibility("falcon-mamba:7b")

    assert result["status"] == "likely_recurrent"


def test_ssm_compatibility_marks_hybrid_and_transformer_models_conservatively():
    assert _detect_ssm_compatibility("jamba-instruct")["status"] == "hybrid_verify"
    assert _detect_ssm_compatibility("llama3.3")["status"] == "not_ssm"


def test_ollama_model_discovery_includes_ssm_compatibility_metadata():
    models = _extract_provider_models("ollama_direct", {
        "models": [{"name": "mamba:130m", "details": {"family": "mamba"}}]
    })

    assert models[0]["ssm_compatibility"]["status"] == "likely_recurrent"
