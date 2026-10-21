"""Real, isolated solo-worker crash probe; test-only barriers and delivery audit."""

import faulthandler
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
mode, directory = sys.argv[1], Path(sys.argv[2]).resolve()
assert directory.is_relative_to(ROOT / "runtime") and mode in {"crash", "retry", "reaper", "expiry"}


def marker(name, **values):
    path = directory / name
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(path)


marker("owner.json", pid=os.getpid())
deadline = time.monotonic() + 30
while not (directory / "allow").exists():
    if time.monotonic() > deadline:
        raise RuntimeError("PROBE_BARRIER_TIMEOUT")
    time.sleep(0.02)

from celery.signals import task_postrun, task_prerun, worker_ready  # noqa: E402
from kombu.transport.redis import QoS  # noqa: E402

from app.workers import jobs  # noqa: E402
from app.workers.celery_app import celery_app  # noqa: E402

config = json.loads((directory / "probe.json").read_text(encoding="utf-8"))
diagnostic = (directory / (mode + "-stack.log")).open("w", encoding="utf-8")
faulthandler.dump_traceback_later(8, file=diagnostic)
restore_original = QoS.restore_visible


def restore_observed(self, *args, **kwargs):
    with (directory / (mode + "-restore.jsonl")).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": time.time(), "counter": self._vrestore_count}) + "\n")
    return restore_original(self, *args, **kwargs)


QoS.restore_visible = restore_observed
assert config["prefix"].startswith("researchos-crash-test-") and config["prefix"].endswith(":")
celery_app.conf.update(
    broker_transport_options={
        "visibility_timeout": 5,
        "global_keyprefix": config["prefix"],
        "polling_interval": 0.1,
    },
    visibility_timeout=5,
    result_backend_transport_options={"visibility_timeout": 5},
    task_default_queue=config["queue"],
    worker_enable_remote_control=False,
)

if mode == "reaper":
    from app.workers.dispatcher import BrokerRecoverySchedule

    schedule = BrokerRecoverySchedule(app=celery_app, interval=0.5)
    marker("ready.json", pid=os.getpid())
    while True:
        schedule.tick()
        time.sleep(0.1)


@worker_ready.connect(weak=False)
def ready(sender=None, **kwargs):
    channel = sender.task_consumer.channel
    marker(
        "ready.json",
        pid=os.getpid(),
        visibility_timeout=channel.visibility_timeout,
        prefix=channel.global_keyprefix,
        unacked=channel.unacked_key,
        observed_at=time.time(),
    )


def record(event, task, task_id):
    if task.name != "researchos.parse_pdf":
        return
    document = {
        "event": event,
        "task_id": task_id,
        "mode": mode,
        "redelivered": bool(task.request.delivery_info.get("redelivered")),
    }
    with (directory / "deliveries.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(document) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@task_prerun.connect(weak=False)
def before(task_id=None, task=None, **kwargs):
    record("started", task, task_id)


@task_postrun.connect(weak=False)
def after(task_id=None, task=None, **kwargs):
    record("finished", task, task_id)


if mode == "crash":
    original = jobs.run_contained

    def supervised(*args, **kwargs):
        def started(pid):
            marker("started.json", pid=pid)
            time.sleep(60)  # Actual parser runs; parent cannot publish/ACK yet.

        return original(*args, **kwargs, on_started=started)

    jobs.run_contained = supervised

celery_app.worker_main(
    [
        "worker",
        "--pool=solo",
        "--concurrency=1",
        "--loglevel=ERROR",
        f"--queues={config['queue']}",
        f"--hostname={config['queue']}@local",
        "--without-gossip",
        "--without-mingle",
        "--without-heartbeat",
        f"--logfile={directory / (mode + '.log')}",
    ]
)
