"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Đọc REDIS_URL từ config.
  • redis.from_url() chỉ tạo client, KHÔNG mở kết nối nên app vẫn khởi động được
    khi Redis chưa sẵn sàng (/health vẫn 200, /ready trả 503).
  • Timeout ngắn để request không treo lâu khi Redis chết.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: Redis không kết nối được → False."""
    try:
        return bool(r.ping())
    except redis.exceptions.RedisError:
        return False
