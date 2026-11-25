"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) nên mọi worker / instance dùng chung,
    và vẫn còn sau khi restart agent.

Mỗi key là một sorted set: member = một request, score = thời điểm của request.
Cả 4 lệnh Redis chạy trong một MULTI/EXEC (pipeline transaction) nên không bị
race giữa các worker: thêm request hiện tại vào trước rồi mới đếm, và nếu vượt
giới hạn thì gỡ chính request đó ra (request bị từ chối không chiếm slot).
"""
import hashlib
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> int:
    """Raise 429 nếu vượt giới hạn. Trả về số request còn lại trong cửa sổ hiện tại."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    # Không lưu API key thô trong Redis, chỉ lưu bản băm
    redis_key = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    member = f"{now}:{uuid.uuid4().hex[:8]}"

    try:
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(redis_key, 0, now - WINDOW_SECONDS)  # bỏ request ngoài cửa sổ
        pipe.zadd(redis_key, {member: now})                        # ghi request hiện tại
        pipe.zcard(redis_key)                                      # đếm trong cửa sổ
        pipe.zrange(redis_key, 0, 0, withscores=True)              # request cũ nhất
        pipe.expire(redis_key, WINDOW_SECONDS + 5)                 # key tự dọn khi không dùng
        _, _, count, oldest, _ = pipe.execute()
    except redis.exceptions.RedisError:
        # Không đếm được thì không cho qua: tránh mất kiểm soát chi phí khi Redis chết
        raise HTTPException(status_code=503, detail="Rate limiter unavailable. Try again later.")

    if count > limit:
        try:
            r.zrem(redis_key, member)
        except redis.exceptions.RedisError:
            pass
        oldest_ts = oldest[0][1] if oldest else now
        retry_after = max(1, math.ceil(oldest_ts + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per minute. Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
    return limit - count
