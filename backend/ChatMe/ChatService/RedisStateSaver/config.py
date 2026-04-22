try:
    from ChatMe.ChatMeConfig import get_redis_state_saver_url
    REDIS_URL = get_redis_state_saver_url()
except Exception:
    REDIS_URL = "redis://:123456@localhost:6379/1"