import pytest

from post_run_analysis import extract_trial_helper


def test_extract_trial_helper_from_structured_analysis():
    text = """## Progress Analysis
- Finding

## Generated Trial Helper
Start with the narrowest probe.

1. Confirm reachability.
2. Record evidence from successful commands.

## Recommended Next Changes
- Keep iterating.
"""
    helper = extract_trial_helper(text)
    assert helper.startswith("Start with")
    assert "Recommended Next Changes" not in helper


@pytest.mark.parametrize("secret", [
    "Use FLAG{not-for-a-helper} as the answer.",
    "password: hunter2 is required for access.",
    "access_token=private-token should be sent.",
])
def test_generated_helper_rejects_answer_like_secrets(secret):
    with pytest.raises(ValueError, match="secret material"):
        extract_trial_helper("## Generated Trial Helper\n" + secret)
