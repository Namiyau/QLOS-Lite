from qlos_lite.logger import scrub_sensitive


def test_scrub_sensitive_does_not_corrupt_plain_token_word():
    record = {
        "message_id": "plain-token-message",
        "text": "auth token variant smoke",
    }

    assert scrub_sensitive(record) == record


def test_scrub_sensitive_hides_known_secret_markers():
    record = {"text": "OPENAI_API_KEY=abc cookie=secret"}

    scrubbed = scrub_sensitive(record)

    assert "OPENAI_API_KEY" not in scrubbed["text"]
    assert "cookie=" not in scrubbed["text"]


def test_scrub_sensitive_keeps_env_filename_mentions():
    record = {"text": "配置到 .env 里"}

    assert scrub_sensitive(record) == record


def test_scrub_sensitive_preserves_diagnostic_key_lists():
    record = {"keys": ["post_type", "message_type"], "top_level_fields": ["arrayMsg"]}

    assert scrub_sensitive(record) == record


def test_scrub_sensitive_removes_secret_field_names():
    record = {"api_key": "secret", "access_token": "secret", "text": "ok"}

    assert scrub_sensitive(record) == {"text": "ok"}
