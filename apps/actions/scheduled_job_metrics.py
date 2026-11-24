"""OpenTelemetry instruments for the scheduled jobs.

Runs happen in the Celery worker or an external scheduler, so values are read
from ``ScheduledJobCounter`` and ``ScheduledJobState`` at collect time.
Attributes are ``job``, ``status``, and ``kind`` only. ``redis_up`` and the
beat timestamp are omitted when the broker is not configured, matching the old
Prometheus scrape.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

_CACHE_SECONDS = 1.0
_cached_at = 0.0
_cached: ScheduledSample | None = None

RUNS = 'shellui_hosting_scheduled_job_runs_total'
ITEMS = 'shellui_hosting_scheduled_job_items_total'
LAST_SUCCESS = 'shellui_hosting_scheduled_job_last_success_timestamp_seconds'
LAST_RUN = 'shellui_hosting_scheduled_job_last_run_timestamp_seconds'
DURATION = 'shellui_hosting_scheduled_job_last_run_duration_seconds'
OVERDUE = 'shellui_hosting_scheduled_job_overdue'
SCHEDULER_ENABLED = 'shellui_hosting_scheduler_enabled'
REDIS_UP = 'shellui_hosting_scheduler_redis_up'
BEAT_LAST_SEEN = 'shellui_hosting_scheduler_beat_last_seen_timestamp_seconds'


@dataclass(frozen=True)
class ScheduledSample:
    runs: tuple[tuple[str, str, int], ...]
    items: tuple[tuple[str, str, int], ...]
    last_success: tuple[tuple[str, float], ...]
    last_started: tuple[tuple[str, float], ...]
    duration: tuple[tuple[str, float], ...]
    overdue: tuple[tuple[str, int], ...]
    scheduler_enabled: int
    redis_up: int | None
    beat_last_seen: float | None


def clear_snapshot_cache() -> None:
    global _cached_at, _cached
    _cached_at = 0.0
    _cached = None


def _sample() -> ScheduledSample:
    from django.utils import timezone

    from apps.actions.models import ScheduledJobCounter
    from apps.actions.scheduled_jobs import (
        JOBS,
        RUN_STATUSES,
        beat_last_seen,
        ensure_states,
        is_overdue,
        redis_reachable,
        scheduler_enabled,
    )

    now = timezone.now()
    states = ensure_states()
    counters = {(row.job, row.name): row.value for row in ScheduledJobCounter.objects.filter(job__in=list(JOBS))}
    runs: list[tuple[str, str, int]] = []
    items: list[tuple[str, str, int]] = []
    last_success: list[tuple[str, float]] = []
    last_started: list[tuple[str, float]] = []
    duration: list[tuple[str, float]] = []
    overdue: list[tuple[str, int]] = []
    for name, spec in JOBS.items():
        state = states[name]
        for status in RUN_STATUSES:
            runs.append((name, status, counters.get((name, f'runs.{status}'), 0)))
        for kind in spec.item_kinds:
            items.append((name, kind, counters.get((name, f'items.{kind}'), 0)))
        last_success.append((name, state.last_success_at.timestamp() if state.last_success_at else 0))
        last_started.append((name, state.last_started_at.timestamp() if state.last_started_at else 0))
        if state.last_duration_ms is not None:
            duration.append((name, state.last_duration_ms / 1000.0))
        overdue.append((name, 1 if is_overdue(spec, state, now) else 0))
    reachable = redis_reachable()
    beat = beat_last_seen() if reachable else None
    return ScheduledSample(
        runs=tuple(runs),
        items=tuple(items),
        last_success=tuple(last_success),
        last_started=tuple(last_started),
        duration=tuple(duration),
        overdue=tuple(overdue),
        scheduler_enabled=1 if scheduler_enabled() else 0,
        redis_up=None if reachable is None else (1 if reachable else 0),
        beat_last_seen=None if beat is None else beat.timestamp(),
    )


def _cached_sample() -> ScheduledSample:
    global _cached_at, _cached
    now = time.monotonic()
    if _cached is not None and now - _cached_at < _CACHE_SECONDS:
        return _cached
    sample = _sample()
    _cached = sample
    _cached_at = now
    return sample


def register_scheduled_job_metrics(meter) -> None:
    from opentelemetry.metrics import Observation
    from shellui_django.telemetry import canonical_metric_name

    def runs(_options):
        for job, status, value in _cached_sample().runs:
            yield Observation(value, {'job': job, 'status': status})

    def items(_options):
        for job, kind, value in _cached_sample().items:
            yield Observation(value, {'job': job, 'kind': kind})

    def last_success(_options):
        for job, value in _cached_sample().last_success:
            yield Observation(value, {'job': job})

    def last_started(_options):
        for job, value in _cached_sample().last_started:
            yield Observation(value, {'job': job})

    def duration(_options):
        for job, value in _cached_sample().duration:
            yield Observation(value, {'job': job})

    def overdue(_options):
        for job, value in _cached_sample().overdue:
            yield Observation(value, {'job': job})

    def enabled(_options):
        yield Observation(_cached_sample().scheduler_enabled)

    def redis_up(_options):
        value = _cached_sample().redis_up
        if value is not None:
            yield Observation(value)

    def beat(_options):
        value = _cached_sample().beat_last_seen
        if value is not None:
            yield Observation(value)

    meter.create_observable_counter(
        canonical_metric_name(RUNS),
        callbacks=[runs],
        unit='1',
        description='Finished scheduled job runs by status (succeeded, failed, skipped_locked).',
    )
    meter.create_observable_counter(
        canonical_metric_name(ITEMS),
        callbacks=[items],
        unit='1',
        description='Items processed by scheduled job runs, by kind.',
    )
    meter.create_observable_gauge(
        canonical_metric_name(LAST_SUCCESS),
        callbacks=[last_success],
        unit='s',
        description='Unix time when the last successful run finished (0 before the first one).',
    )
    meter.create_observable_gauge(
        canonical_metric_name(LAST_RUN),
        callbacks=[last_started],
        unit='s',
        description='Unix time when the last run started (0 before the first one).',
    )
    meter.create_observable_gauge(
        canonical_metric_name(DURATION),
        callbacks=[duration],
        unit='s',
        description='Duration of the last finished run.',
    )
    meter.create_observable_gauge(
        canonical_metric_name(OVERDUE),
        callbacks=[overdue],
        unit='1',
        description='1 when the last successful run is older than 3 times the job interval.',
    )
    meter.create_observable_gauge(
        canonical_metric_name(SCHEDULER_ENABLED),
        callbacks=[enabled],
        unit='1',
        description='1 when the in-container Celery worker and beat run (SCHEDULER_ENABLED).',
    )
    meter.create_observable_gauge(
        canonical_metric_name(REDIS_UP),
        callbacks=[redis_up],
        unit='1',
        description='1 when the scheduler broker (Redis) answers PING.',
    )
    meter.create_observable_gauge(
        canonical_metric_name(BEAT_LAST_SEEN),
        callbacks=[beat],
        unit='s',
        description='Unix time when Celery beat last published a scheduled job.',
    )
