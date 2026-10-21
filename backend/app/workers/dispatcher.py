import time
from contextlib import contextmanager

import redis

from app.workers.celery_app import celery_app
from app.workers.jobs import dispatch_once


@contextmanager
def broker_channel(app):
    options = dict(app.conf.broker_transport_options)
    options.setdefault("socket_connect_timeout", 5)
    options.setdefault("socket_timeout", 5)
    with app.connection_for_read(connect_timeout=5, transport_options=options) as connection:
        if connection.transport.driver_type != "redis":
            raise RuntimeError("BROKER_RECOVERY_REQUIRES_REDIS")
        with connection.channel() as channel:
            yield channel


def broker_state(app=celery_app):
    """Read queue/index counters only; never expose task bodies or credentials."""
    with broker_channel(app) as channel:
        queue, now = app.conf.task_default_queue, time.time()

        # Kombu 5.6.2's prefix mixin covers only selected commands, excluding
        # ZCARD/ZRANGE/ZCOUNT/TTL. A raw client sharing this exact pool gives all
        # read commands the same explicit physical namespace, without double-prefixing.
        def key(name):
            return f"{channel.global_keyprefix}{name}"

        with redis.Redis(connection_pool=channel.client.connection_pool) as inspector:
            with inspector.pipeline() as pipe:
                for priority in channel.priority_steps:
                    pipe.llen(key(channel._q_for_pri(queue, priority)))
                pipe.hlen(key(channel.unacked_key))
                pipe.zcard(key(channel.unacked_index_key))
                pipe.zrange(key(channel.unacked_index_key), 0, 0, withscores=True)
                pipe.zcount(key(channel.unacked_index_key), 0, now - channel.visibility_timeout)
                pipe.ttl(key(channel.unacked_mutex_key))
                result = pipe.execute()
        count = len(channel.priority_steps)
        unacked, indexed, oldest, expired, mutex_ttl = result[count:]
        return {
            "queue": queue,
            "ready": sum(result[:count]),
            "unacked": unacked,
            "delivery_index_entries": indexed,
            "oldest_unacked_age_seconds": max(0, round(now - oldest[0][1], 3)) if oldest else None,
            "expired_unacked": expired,
            "visibility_timeout_seconds": channel.visibility_timeout,
            "restore_mutex_ttl_seconds": mutex_ttl,
            "keyprefix_configured": bool(channel.global_keyprefix),
        }


class ExpirySchedule:
    def __init__(self, interval=60):
        self.interval, self.next_run = interval, 0.0

    def tick(self):
        now = time.monotonic()
        if now < self.next_run:
            return False
        celery_app.send_task("researchos.expire_artifacts", args=[], retry=False)
        self.next_run = now + self.interval
        return True


class BrokerRecoverySchedule:
    """Drive Redis's atomic visibility restore outside busy/crashed consumers.

    Kombu's pinned Redis QoS supplies the mutex, cutoff, original routing and
    WATCH/MULTI restore. This process only schedules bounded sweeps; it never
    consumes tasks or invents replacement message IDs.
    """

    def __init__(self, app=celery_app, interval=10):
        if not 0 < interval <= 300:
            raise ValueError("BROKER_RECOVERY_INTERVAL_INVALID")
        self.app, self.interval, self.next_run = app, interval, 0.0

    def tick(self):
        now = time.monotonic()
        if now < self.next_run:
            return False
        with broker_channel(self.app) as channel:
            # At most 100 expired deliveries per tick, using precisely this
            # application's broker namespace and visibility timeout.
            channel.qos.restore_visible(num=100, interval=1)
        self.next_run = time.monotonic() + self.interval
        return True


def dispatch_iteration(recovery, expiry):
    # Recovery or periodic scheduling failure must not suppress lease/outbox work.
    for name, operation in (
        ("broker_recovery", recovery.tick),
        ("outbox", dispatch_once),
        ("expiry_schedule", expiry.tick),
    ):
        try:
            operation()
        except Exception:
            # Exception values may contain broker/DB parameters and credentials.
            print(f"dispatcher_{name}_failed", flush=True)


if __name__ == "__main__":
    recovery, expiry = BrokerRecoverySchedule(), ExpirySchedule()
    while True:
        dispatch_iteration(recovery, expiry)
        time.sleep(2)
