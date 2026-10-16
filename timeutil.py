from datetime import datetime, timezone


def utcnow() -> datetime:
    """Giờ UTC dạng naive (khớp cột DateTime hiện có), thay cho datetime.utcnow() đã lỗi thời."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
