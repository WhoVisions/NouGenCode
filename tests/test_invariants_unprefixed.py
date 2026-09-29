from nougencode.security.invariants import ConcentricSecurityGate

# Synthetic, clearly invalid fixture shaped like a Cloudflare Global API Key.
FAKE_KEY = "0" * 37


def test_detects_unprefixed_assigned_key():
    src = f"const authKey = '{FAKE_KEY}';"
    kinds = [v.violation_type for v in ConcentricSecurityGate.audit_code(src)]
    assert "CREDENTIAL_EXPOSURE" in kinds


def test_snippet_never_echoes_credential():
    src = f"const authKey = '{FAKE_KEY}';"
    for v in ConcentricSecurityGate.audit_code(src):
        assert FAKE_KEY[:8] not in v.matched_snippet


def test_env_lookup_is_clean():
    src = "const apiToken = process.env.CLOUDFLARE_API_TOKEN;"
    assert ConcentricSecurityGate.audit_code(src) == []
