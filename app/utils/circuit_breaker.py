import pybreaker
import aiobreaker
from datetime import timedelta

breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=15)
aio_breaker = aiobreaker.CircuitBreaker(fail_max=3,timeout_duration=timedelta(seconds=15))

