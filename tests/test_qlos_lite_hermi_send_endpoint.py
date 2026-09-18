from qlos_lite.onebot_server import _authorized_hermi_send, process_hermi_send_payload


class FakeOneBotClient:
    def __init__(self):
        self.private = []
        self.group = []
        self.private_files = []
        self.group_files = []

    def send_private_msg(self, user_id, message):
        self.private.append((user_id, message))
        return {"status": "ok", "retcode": 0}

    def send_group_msg(self, group_id, message):
        self.group.append((group_id, message))
        return {"status": "ok", "retcode": 0}

    def upload_private_file(self, user_id, file_path, name=None):
        self.private_files.append((user_id, file_path, name))
        return {"status": "ok", "retcode": 0}

    def upload_group_file(self, group_id, file_path, name=None):
        self.group_files.append((group_id, file_path, name))
        return {"status": "ok", "retcode": 0}


class UploadFailingOneBotClient(FakeOneBotClient):
    def upload_private_file(self, user_id, file_path, name=None):
        raise RuntimeError("upload unsupported")


def test_process_hermi_send_payload_sends_private_message():
    onebot = FakeOneBotClient()

    result = process_hermi_send_payload(
        {"chat_type": "private", "user_id": "1000000001", "message": "hi"},
        onebot,
    )

    assert result["ok"] is True
    assert onebot.private == [("1000000001", "hi")]


def test_process_hermi_send_payload_sends_group_message():
    onebot = FakeOneBotClient()

    result = process_hermi_send_payload(
        {"chat_type": "group", "group_id": "2000000001", "message": "hi group"},
        onebot,
    )

    assert result["ok"] is True
    assert onebot.group == [("2000000001", "hi group")]


def test_process_hermi_send_payload_uploads_private_files():
    onebot = FakeOneBotClient()

    result = process_hermi_send_payload(
        {
            "chat_type": "private",
            "user_id": "1000000001",
            "message": "report",
            "files": [{"path": "C:/tmp/report.docx", "name": "报告.docx"}],
        },
        onebot,
    )

    assert result["ok"] is True
    assert onebot.private == [("1000000001", "report")]
    assert onebot.private_files == [("1000000001", "C:/tmp/report.docx", "报告.docx")]


def test_process_hermi_send_payload_sends_images_as_qq_images_without_duplicates():
    onebot = FakeOneBotClient()

    result = process_hermi_send_payload(
        {
            "chat_type": "private",
            "user_id": "1000000001",
            "message": "截图已附上",
            "images": [{"path": "C:/tmp/screen.png", "original_name": "screen.png"}],
            "attachments": [{"type": "image", "path": "C:/tmp/screen.png", "original_name": "screen.png"}],
        },
        onebot,
    )

    assert result["ok"] is True
    assert onebot.private == [
        ("1000000001", "截图已附上"),
        ("1000000001", "[CQ:image,file=C:/tmp/screen.png]"),
    ]
    assert result["image_results"][0]["ok"] is True


def test_process_hermi_send_payload_reports_file_upload_errors_without_raising():
    onebot = UploadFailingOneBotClient()

    result = process_hermi_send_payload(
        {
            "chat_type": "private",
            "user_id": "1000000001",
            "message": "report",
            "files": [{"path": "C:/tmp/report.docx", "name": "report.docx"}],
        },
        onebot,
    )

    assert result["ok"] is True
    assert onebot.private == [("1000000001", "report")]
    assert result["file_results"][0]["ok"] is False
    assert result["file_results"][0]["error_type"] == "RuntimeError"


def test_hermi_send_auth_accepts_gateway_token():
    headers = {"Authorization": "Bearer replace-with-channel-token"}

    assert _authorized_hermi_send(headers, "onebot-secret", "replace-with-channel-token", b"{}", "127.0.0.1")


