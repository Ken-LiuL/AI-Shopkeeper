"""通用异步重试装饰器，指数退避。"""

import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def async_retry(max_retries=3, backoff_base=1.0, exceptions=(Exception,)):
    """异步重试装饰器，指数退避。"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        wait = backoff_base * (2 ** (attempt - 1))
                        logger.warning(f"{func.__name__} attempt {attempt}/{max_retries} failed: {e}, retrying in {wait}s")
                        await asyncio.sleep(wait)
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {e}")
            raise last_exc
        return wrapper
    return decorator
