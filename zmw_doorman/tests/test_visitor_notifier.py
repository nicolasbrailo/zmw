"""Unit tests for visitor_notifier.py"""
import pytest

from visitor_notifier import VisitorNotifier


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.jobs = []   # [when, callback, cancelled]

    def now(self):
        return self.t

    def schedule(self, delay, callback):
        job = [self.t + delay, callback, False]
        self.jobs.append(job)

        def cancel():
            job[2] = True
        return cancel

    def advance(self, secs):
        self.t += secs
        for job in list(self.jobs):
            if job[0] <= self.t and not job[2]:
                job[2] = True
                job[1]()


def person(sid='s1', night=False, img='/tmp/shared/person.jpg', trigger='motion'):
    return {'session_id': sid, 'cam_alias': 'doorbell', 'trigger': trigger,
            'day_night': 'night' if night else 'day', 'notify_img_path': img}


def identified(sid='s1', vid='visitor_3', name='Belen', img='/tmp/shared/face.jpg'):
    return {'session_id': sid, 'cam_alias': 'doorbell', 'trigger': 'motion', 'day_night': 'day',
            'visitor_id': vid, 'name': name, 'notify_img_path': img}


def unknown(sid='s1', img='/tmp/shared/unknown.jpg'):
    return {'session_id': sid, 'cam_alias': 'doorbell', 'trigger': 'motion', 'day_night': 'day',
            'closest': None, 'notify_img_path': img}


CFG = {'visitor_face_wait_secs': 5, 'visitor_notify_repeat_secs': 120, 'visitor_notify_injected': False}


class TestVisitorNotifier:
    def setup_method(self):
        self.clock = FakeClock()
        self.sent = []
        self.notifier = VisitorNotifier(CFG,
                                        lambda path, text: self.sent.append((path, text)),
                                        self.clock.schedule, self.clock.now)

    def ev(self, subtopic, msg):
        self.notifier.on_visitor_event(subtopic, msg)

    def test_face_within_wait_is_sent_instead_of_person(self):
        self.ev('on_person_detected', person())
        self.clock.advance(3)
        self.ev('on_face_identified', identified())
        assert self.sent == [('/tmp/shared/face.jpg', 'Belen is at the door')]
        self.clock.advance(10)
        assert len(self.sent) == 1

    def test_no_face_sends_person_after_wait(self):
        self.ev('on_person_detected', person())
        self.clock.advance(4.9)
        assert not self.sent
        self.clock.advance(0.2)
        assert self.sent == [('/tmp/shared/person.jpg', 'Someone is at the door')]

    def test_late_face_is_one_follow_up(self):
        self.ev('on_person_detected', person())
        self.clock.advance(6)
        self.ev('on_face_detected', unknown())
        self.ev('on_face_identified', identified())
        assert self.sent == [('/tmp/shared/person.jpg', 'Someone is at the door'),
                             ('/tmp/shared/unknown.jpg', 'Unknown visitor at the door')]

    def test_unknown_then_identified_is_a_follow_up(self):
        self.ev('on_person_detected', person())
        self.ev('on_face_detected', unknown())
        self.ev('on_face_identified', identified())
        assert [t for _, t in self.sent] == ['Unknown visitor at the door', 'Belen is at the door']

    def test_night_sends_person_at_once(self):
        self.ev('on_person_detected', person(night=True))
        assert self.sent == [('/tmp/shared/person.jpg', 'Someone is at the door')]
        self.clock.advance(10)
        assert len(self.sent) == 1

    def test_same_person_not_repeated_across_sessions(self):
        self.ev('on_person_detected', person('s1'))
        self.ev('on_face_identified', identified('s1'))
        self.clock.advance(60)
        self.ev('on_person_detected', person('s2'))
        self.ev('on_face_identified', identified('s2'))
        assert len(self.sent) == 1
        # Someone else in the second session still gets through
        self.ev('on_face_identified', identified('s2', vid='visitor_4', name='Emma'))
        assert self.sent[-1][1] == 'Emma is at the door'
        self.clock.advance(121)
        self.ev('on_person_detected', person('s3'))
        self.ev('on_face_identified', identified('s3'))
        assert self.sent[-1][1] == 'Belen is at the door'

    def test_repeated_someone_is_suppressed(self):
        self.ev('on_person_detected', person('s1'))
        self.clock.advance(6)
        self.ev('on_person_detected', person('s2'))
        self.clock.advance(6)
        assert len(self.sent) == 1

    def test_injected_sessions_ignored_by_default(self):
        self.ev('on_person_detected', person(trigger='injected'))
        self.clock.advance(6)
        assert not self.sent

    def test_injected_sessions_notified_when_configured(self):
        notifier = VisitorNotifier({**CFG, 'visitor_notify_injected': True},
                                   lambda path, text: self.sent.append((path, text)),
                                   self.clock.schedule, self.clock.now)
        notifier.on_visitor_event('on_person_detected', person(trigger='injected', night=True))
        assert len(self.sent) == 1

    def test_face_without_image_uses_person_image(self):
        self.ev('on_person_detected', person())
        self.ev('on_face_identified', identified(img=None))
        assert self.sent == [('/tmp/shared/person.jpg', 'Belen is at the door')]

    def test_face_before_person_is_sent(self):
        self.ev('on_face_identified', identified())
        self.ev('on_person_detected', person())
        self.clock.advance(6)
        assert self.sent == [('/tmp/shared/face.jpg', 'Belen is at the door')]

    def test_missing_config_key_fails(self):
        for key in CFG:
            cfg = {k: v for k, v in CFG.items() if k != key}
            with pytest.raises(KeyError):
                VisitorNotifier(cfg, lambda path, text: None, self.clock.schedule, self.clock.now)

    def test_other_events_ignored(self):
        self.ev('on_new_frequent_visitor', {'session_id': 's1'})
        self.ev('on_person_detected', {'no': 'session'})
        self.clock.advance(6)
        assert not self.sent
