import pytest

from benchy.redact import contains_secret, redact, redact_file

SECRETS = [
    "gho_" + "A" * 36,
    "ghu_" + "b1" * 18,
    "github_pat_" + "11ABCDEFG0" * 5,
    "sk-ant-oat01-" + "x9" * 30,
    "sk-" + "Q" * 40,
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_token_shapes_are_redacted(secret):
    text = f"prefix {secret} suffix"
    out = redact(text)
    assert secret not in out and "[REDACTED]" in out
    assert contains_secret(text)


def test_key_value_and_bearer():
    assert redact('"access_token": "abc123def456ghi"') == '"access_token": "[REDACTED]"'
    assert redact("Authorization: Bearer abcdefghijklmnop1234") == "Authorization: Bearer [REDACTED]"
    assert redact("ARTIFACTORY_PASSWORD=hunter2hunter2x9") == "ARTIFACTORY_PASSWORD=[REDACTED]"


@pytest.mark.parametrize("benign", [
    "password = form.password.data",
    '"secrets_found": 0',
    "password: ${{ secrets.ARTIFACTORY_TOKEN }}",
    "commit 3d3c42e5aac5ba805825da76410c181273ba90b1",
    "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set it}",
])
def test_benign_text_untouched(benign):
    assert redact(benign) == benign


def test_redact_file(tmp_path):
    src = tmp_path / "a.log"
    src.write_text("token=gho_" + "Z" * 36 + "\nok\n")
    redact_file(src, tmp_path / "out" / "b.log")
    assert "gho_" not in (tmp_path / "out" / "b.log").read_text()
    binary = tmp_path / "bin"
    binary.write_bytes(b"\xff\xfe\x00gho_")
    redact_file(binary, tmp_path / "bin2")   # undecodable: skipped, not crashed
    assert not (tmp_path / "bin2").exists()
