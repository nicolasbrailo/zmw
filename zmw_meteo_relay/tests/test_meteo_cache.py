from datetime import datetime, timedelta

import pytest

from meteo_cache import MeteoCache, distance_km, parse_latlon


class FakeJob:
    def __init__(self, sched, kw):
        self.sched = sched
        self.kw = kw
        self.removed = False

    def remove(self):
        self.removed = True
        self.sched.jobs.remove(self)


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, **kw):
        job = FakeJob(self, kw)
        self.jobs.append(job)
        return job

    def date_jobs(self):
        return [j for j in self.jobs if j.kw.get('trigger') == 'date']


class FakeFetch:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, lat, lon):
        self.calls.append((lat, lon))
        if self.fail:
            raise RuntimeError("boom")
        return {'latitude': lat, 'longitude': lon, 'current': {'temperature_2m': 12.3}}


HOME = (51.5428, -0.1289)


def _cache(**kw):
    fetch, sched = FakeFetch(), FakeScheduler()
    args = dict(fetch_fn=fetch, scheduler=sched, default_latlon=HOME, update_interval_secs=30 * 60,
                dedup_radius_km=3.0, max_locations=3, retry_base_secs=30)
    args.update(kw)
    return MeteoCache(**args), fetch, sched


def test_distance():
    assert distance_km(*HOME, *HOME) == pytest.approx(0)
    # London -> Paris is ~344 km
    assert distance_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(344, rel=0.02)


def test_parse_latlon():
    assert parse_latlon("51.5", "-0.12") == (51.5, -0.12)
    for bad in [("91", "0"), ("0", "181"), ("x", "0"), (None, "0"), ("nan", "0")]:
        with pytest.raises(ValueError):
            parse_latlon(*bad)


def test_default_location_served_without_latlon():
    cache, fetch, _ = _cache()
    cache.refresh(cache.default_location())
    loc = cache.get_location_for_request()
    assert loc.is_default
    assert loc.weather['current']['temperature_2m'] == 12.3
    assert len(fetch.calls) == 1


def test_nearby_requests_are_deduplicated():
    cache, fetch, _ = _cache()
    a = cache.get_location_for_request(48.8566, 2.3522)
    b = cache.get_location_for_request(48.8600, 2.3500)  # ~0.4 km away
    assert a is b
    assert len(cache.get_locations()) == 2  # default + Paris
    assert len(fetch.calls) == 1  # New location fetched once, on demand
    assert a.request_count == 2


def test_nearby_default_location_is_reused():
    cache, _, _ = _cache()
    loc = cache.get_location_for_request(HOME[0] + 0.001, HOME[1])
    assert loc.is_default
    assert len(cache.get_locations()) == 1


def test_far_requests_create_new_locations_and_evict_lru():
    cache, _, _ = _cache(max_locations=3)
    paris = cache.get_location_for_request(48.8566, 2.3522)
    berlin = cache.get_location_for_request(52.52, 13.405)
    cache.get_location_for_request(48.8566, 2.3522)  # Paris is now more recent than Berlin
    madrid = cache.get_location_for_request(40.4168, -3.7038)
    locs = cache.get_locations()
    assert len(locs) == 3
    assert berlin not in locs and berlin.evicted
    assert paris in locs and madrid in locs
    assert cache.default_location() in locs


def test_failed_new_location_has_no_weather_and_schedules_retry():
    cache, fetch, sched = _cache()
    fetch.fail = True
    loc = cache.get_location_for_request(48.8566, 2.3522)
    assert loc.weather is None
    assert loc.last_error == "boom"
    assert loc.retry_count == 1
    assert len(sched.date_jobs()) == 1


def test_backoff_doubles_and_stops_before_next_periodic():
    cache, fetch, sched = _cache(update_interval_secs=30 * 60, retry_base_secs=30)
    loc = cache.default_location()
    fetch.fail = True
    delays = []
    for _ in range(20):
        before = datetime.now()
        cache.refresh(loc)
        jobs = sched.date_jobs()
        if not jobs:
            break
        assert len(jobs) == 1  # Never more than one pending retry per location
        delays.append((jobs[0].kw['run_date'] - before).total_seconds())
        jobs[0].remove()  # Simulate the job firing
    # 30, 60, 120, 240, 480, 960 secs; 1920 would be past the 30 min periodic update
    assert [round(d / 30) * 30 for d in delays] == [30, 60, 120, 240, 480, 960]
    assert loc.retry_count == 0  # Next periodic failure restarts the sequence
    assert loc.next_retry_at is None


def test_success_cancels_pending_retry():
    cache, fetch, sched = _cache()
    loc = cache.default_location()
    fetch.fail = True
    cache.refresh(loc)
    job = sched.date_jobs()[0]
    fetch.fail = False
    assert cache.refresh(loc)
    assert job.removed
    assert loc.last_error is None and loc.retry_count == 0
    assert loc.weather is not None


def test_periodic_skips_recently_fetched_locations():
    cache, fetch, sched = _cache()
    periodic = [j for j in sched.jobs if j.kw.get('trigger') == 'interval'][0]
    cache.get_location_for_request(48.8566, 2.3522)  # Fetched now
    fetch.calls.clear()
    periodic.kw['func']()
    assert fetch.calls == [HOME]  # Only the never-fetched default


def test_periodic_refetches_stale_locations():
    cache, fetch, sched = _cache()
    periodic = [j for j in sched.jobs if j.kw.get('trigger') == 'interval'][0]
    loc = cache.get_location_for_request(48.8566, 2.3522)
    loc.fetched_at = datetime.now() - timedelta(minutes=29)
    fetch.calls.clear()
    periodic.kw['func']()
    assert sorted(fetch.calls) == sorted([HOME, (48.8566, 2.3522)])


def test_persist_and_restore():
    saved = []
    cache, _, _ = _cache(persist_fn=saved.append)
    cache.get_location_for_request(48.8566, 2.3522)
    assert saved
    restored, _, _ = _cache(persisted=saved[-1])
    locs = restored.get_locations()
    assert len(locs) == 2
    paris = [l for l in locs if not l.is_default][0]
    assert paris.weather['latitude'] == 48.8566
    assert paris.fetched_at is not None


def test_restore_with_moved_default():
    saved = []
    cache, _, _ = _cache(persist_fn=saved.append)
    cache.get_location_for_request(48.8566, 2.3522)
    restored, _, _ = _cache(persisted=saved[-1], default_latlon=(48.8566, 2.3522))
    assert restored.default_location().lat == 48.8566
    assert sum(1 for l in restored.get_locations() if l.is_default) == 1


def test_on_update_called_on_success_only():
    updates = []
    cache, fetch, _ = _cache(on_update=updates.append)
    loc = cache.default_location()
    fetch.fail = True
    cache.refresh(loc)
    assert updates == []
    fetch.fail = False
    cache.refresh(loc)
    assert updates == [loc]
    paris = cache.get_location_for_request(48.8566, 2.3522)
    assert updates == [loc, paris]


def test_on_update_failure_doesnt_break_refresh():
    def boom(_loc):
        raise RuntimeError("callback failed")
    cache, _, _ = _cache(on_update=boom)
    assert cache.refresh(cache.default_location())
