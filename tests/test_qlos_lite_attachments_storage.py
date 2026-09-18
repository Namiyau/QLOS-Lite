from pathlib import Path

from qlos_lite.attachments import prepare_attachments
from qlos_lite.models import QQMessageEvent


def _event(user_id: str = "1000000001") -> QQMessageEvent:
    return QQMessageEvent(
        message_id="m-file",
        chat_type="private",
        user_id=user_id,
        nickname="Alice",
        raw_message="[file]",
        text="[file]",
        attachments=[],
    )


def test_prepare_attachments_copies_local_files_under_qq_user_folder(tmp_path: Path):
    source = tmp_path / "source" / "报告.pdf"
    source.parent.mkdir()
    source.write_bytes(b"pdf-bytes")
    event = _event("222333")
    event.attachments = [f"file:{source}"]

    refs = prepare_attachments(event, tmp_path / "Hermi资料")

    stored = tmp_path / "Hermi资料" / "222333" / "报告.pdf"
    assert stored.read_bytes() == b"pdf-bytes"
    assert len(refs) == 1
    assert refs[0].startswith("file:")
    assert str(stored) in refs[0]
    assert "relative=Hermi资料/222333/报告.pdf" in refs[0].replace("\\", "/")
    index_text = (tmp_path / "Hermi资料" / "index.jsonl").read_text(encoding="utf-8")
    assert '"user_id":"222333"' in index_text
    assert "报告.pdf" in index_text


def test_prepare_attachments_uses_unique_names_for_same_filename(tmp_path: Path):
    first = tmp_path / "a" / "note.txt"
    second = tmp_path / "b" / "note.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    event = _event("222333")
    event.attachments = [f"file:{first}", f"file:{second}"]

    refs = prepare_attachments(event, tmp_path / "Hermi资料")

    stored_dir = tmp_path / "Hermi资料" / "222333"
    assert (stored_dir / "note.txt").read_text(encoding="utf-8") == "one"
    assert (stored_dir / "note-2.txt").read_text(encoding="utf-8") == "two"
    assert any("note-2.txt" in ref for ref in refs)


def test_prepare_attachments_can_resolve_onebot_file_id(tmp_path: Path):
    resolved_source = tmp_path / "napcat-cache" / "report.docx"
    resolved_source.parent.mkdir()
    resolved_source.write_bytes(b"docx")
    event = _event("222333")
    event.attachments = ["file:report.docx | file_id=file-abc | name=报告.docx"]

    def resolve_file(file_id: str):
        assert file_id == "file-abc"
        return {"path": str(resolved_source), "name": "报告.docx"}

    refs = prepare_attachments(event, tmp_path / "Hermi资料", resolve_file=resolve_file)

    stored = tmp_path / "Hermi资料" / "222333" / "报告.docx"
    assert stored.read_bytes() == b"docx"
    assert str(stored) in refs[0]
    assert "relative=Hermi资料/222333/报告.docx" in refs[0].replace("\\", "/")

