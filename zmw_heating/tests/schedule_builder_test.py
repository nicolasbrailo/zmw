from datetime import datetime
import json
import os
import tempfile
import unittest

from schedule import Schedule, AllowOn
from schedule_builder import ScheduleBuilder
from schedule_test import FakeClock, StateChangeSaver, ignore_state_changes

NO_RULES = []

def get_schedule_all_slots(policy):
    clock = FakeClock(0, 0)
    sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES, clock)
    for hr in range(0, 24):
        for qr in range(0, 4):
            sut.set_slot(hr, qr*15, allow_on=policy)
    sut.apply_template_to_today()
    return sut.as_json()


class RuleAlwaysOn:
    def apply(self, sched):
        sched.set_now_from_rule(True, self.__class__.__name__)
class RuleAlwaysOff:
    def apply(self, sched):
        sched.set_now_from_rule(False, self.__class__.__name__)
class RuleAlwaysOnAgain:
    def apply(self, sched):
        sched.set_now_from_rule(True, self.__class__.__name__)


class ScheduleBuilderTest(unittest.TestCase):
    def test_default_schedule_off(self):
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        for hr in range(0, 24):
            for qr in range(0,4):
                slot = sut.active().get_slot(hr, qr*15)
                self.assertEqual(slot.allow_on, AllowOn.NEVER)

    def test_jsonifies(self):
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        sut.active().set_slot(21, 45, allow_on=AllowOn.ALWAYS, reason="Serialization test")
        self.assertTrue('"Serialization test"' in sut.as_json())
        json.loads(sut.as_json()) # Throw on invalid json

    def test_load_template_bad_json(self):
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        sut.from_json("{aasd")

    def test_serdeser(self):
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        sut.active().set_slot(21, 45, allow_on=AllowOn.ALWAYS, reason="Sertest")
        sut2 = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        sut2.from_json(sut.as_json())
        slot = sut.active().get_slot(21, 45)
        self.assertEqual(slot.allow_on, AllowOn.ALWAYS)
        self.assertEqual(slot.reason, "Sertest")

    def test_deser_sched_only(self):
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        sut.from_json('{"active": [{"hour": 23, "minute": 30, "allow_on": "Always", "reason": "Sertest"}]}')
        for hr in range(0, 24):
            for qr in range(0,4):
                slot = sut.active().get_slot(hr, qr*15)
                if hr == 23 and qr == 2:
                    self.assertEqual(slot.allow_on, AllowOn.ALWAYS)
                    self.assertEqual(slot.reason, "Sertest")
                else:
                    self.assertEqual(slot.allow_on, AllowOn.NEVER)

    def test_deser_tmpl_only(self):
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        sut.from_json('{"template": [{"hour": 23, "minute": 30, "allow_on": "Always", "reason": "Sertest"}]}')
        for hr in range(0, 24):
            for qr in range(0,4):
                slot = sut.get_slot(hr, qr*15)
                if hr == 23 and qr == 2:
                    self.assertEqual(slot.allow_on, AllowOn.ALWAYS)
                    self.assertEqual(slot.reason, "Sertest")
                else:
                    self.assertEqual(slot.allow_on, AllowOn.NEVER)

    def test_creates_state_file(self):
        fname = None
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            fname = temp_file.name
        self.assertFalse(os.path.exists(fname))
        sut = ScheduleBuilder(ignore_state_changes, fname, NO_RULES)
        self.assertTrue(os.path.isfile(fname))
        os.remove(fname)

    def test_reads_state_file(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=True) as temp_file:
            temp_file.write(get_schedule_all_slots(AllowOn.ALWAYS))
            temp_file.flush()
            sut = ScheduleBuilder(ignore_state_changes, temp_file.name, NO_RULES)
            for hr in range(0, 24):
                for mn in range(0, 60):
                    self.assertEqual(sut.get_slot(hr, mn).allow_on, AllowOn.ALWAYS, f"Failed template slot {hr}:{mn}")

    def test_default_tmpl_all_of(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            os.remove(temp_file.name)
            sut = ScheduleBuilder(ignore_state_changes, temp_file.name, NO_RULES)
            for hr in range(0, 24):
                for mn in range(0, 60):
                    self.assertEqual(sut.get_slot(hr, mn).allow_on, AllowOn.NEVER, f"Failed template slot {hr}:{mn}")
                    self.assertEqual(sut.active().get_slot(hr, mn).allow_on, AllowOn.NEVER, f"Failed template slot {hr}:{mn}")

    def test_survives_wrong_ser_file(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=True) as temp_file:
            temp_file.write('random garbage')
            temp_file.flush()
            sut = ScheduleBuilder(ignore_state_changes, temp_file.name, NO_RULES)

    def test_serializes_state_on_tick(self):
        fname = None
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            fname = temp_file.name
        sut = ScheduleBuilder(ignore_state_changes, fname, NO_RULES)
        self.assertTrue(os.path.isfile(fname))
        os.remove(fname)
        self.assertFalse(os.path.exists(fname))
        sut.tick()
        self.assertTrue(os.path.isfile(fname))
        os.remove(fname)

    def test_serializes_state(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=True) as temp_file:
            sut = ScheduleBuilder(ignore_state_changes, temp_file.name, NO_RULES)
            sut.set_slot(15, 30, allow_on=AllowOn.ALWAYS, reason="Hola")
            sut.active().set_slot(18, 45, allow_on=AllowOn.ALWAYS, reason="Hola")
            sut.save_state()
            with open(temp_file.name, "r") as fp:
                saved_state = json.loads(fp.read())
                found = False
                for slot in saved_state['template']:
                    if slot['hour'] == 15 and slot['minute'] == 30:
                        found = True
                        self.assertEqual(slot['allow_on'], AllowOn.ALWAYS)
                        self.assertEqual(slot['reason'], "Hola")
                        break
                found = False
                for slot in saved_state['active']:
                    print(slot)
                    if slot['hour'] == 18 and slot['minute'] == 45:
                        found = True
                        self.assertEqual(slot['allow_on'], AllowOn.ALWAYS)
                        self.assertEqual(slot['reason'], "Hola")
                        break
                self.assertTrue(found)

    def test_tick_applies_template(self):
        clock = FakeClock(15, 10)
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES, clock)
        self.assertEqual(sut.active().get_slot(15, 0).allow_on, AllowOn.NEVER)
        sut.set_slot(15, 0, allow_on=AllowOn.ALWAYS)
        clock.set_t(15, 20)
        sut.tick()
        self.assertEqual(sut.active().get_slot(15, 0).allow_on, AllowOn.ALWAYS)

    def test_set_slot_resets_boiler_state_off(self):
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES)
        sut.set_slot(15, 0, allow_on=AllowOn.ALWAYS)
        self.assertEqual(sut.get_slot(15, 0).request_on, True)
        self.assertEqual(sut.get_slot(15, 0).allow_on, AllowOn.ALWAYS)
        sut.set_slot(15, 0, allow_on=AllowOn.RULE)
        self.assertEqual(sut.get_slot(15, 0).request_on, False)
        self.assertEqual(sut.get_slot(15, 0).allow_on, AllowOn.RULE)

    def test_tick_applies_template_to_next_day(self):
        clock = FakeClock(0, 0)
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES, clock)
        sut.from_json(get_schedule_all_slots(AllowOn.ALWAYS))
        # Pass one: set current schedule off, ensure template is on so it applies to next day
        for hr in range(0, 24):
            for mn in range(0, 60):
                clock.set_t(hr, mn)
                sut.tick()
                sut.active().set_slot(hr, mn, AllowOn.NEVER)
                self.assertEqual(sut.get_slot(hr, mn).allow_on, AllowOn.ALWAYS, f"Failed template slot {hr}:{mn}")
        # Second loop: the template should have been applied to all next day (and subsequent days)
        for hr in range(0, 48):
            for mn in range(0, 60):
                hr = hr % 24
                clock.set_t(hr, mn)
                sut.tick()
                self.assertEqual(sut.active().get_slot(hr, mn).allow_on, AllowOn.ALWAYS, f"Failed template slot {hr}:{mn}")

    def test_apply_template_on_user_ask(self):
        clock = FakeClock(0, 0)
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES, clock)
        sut.from_json(get_schedule_all_slots(AllowOn.ALWAYS))
        for hr in range(0, 24):
            for mn in range(0, 60):
                self.assertEqual(sut.active().get_slot(hr, mn).allow_on, AllowOn.ALWAYS, f"Failed template slot {hr}:{mn}")

    def test_reset_tmpl(self):
        clock = FakeClock(15, 10)
        sut = ScheduleBuilder(ignore_state_changes, None, NO_RULES, clock)
        sut.from_json(get_schedule_all_slots(AllowOn.ALWAYS))
        sut.apply_template_to_today()
        sut.reset_template(AllowOn.NEVER)
        for hr in range(0, 24):
            for mn in range(0, 60, 15):
                self.assertEqual(sut.active().get_slot(hr, mn).allow_on, AllowOn.ALWAYS, f"Failed slot {hr}:{mn}")
                self.assertEqual(sut.get_slot(hr, mn).allow_on, AllowOn.NEVER, f"Failed template slot {hr}:{mn}")
        sut.apply_template_to_today()
        sut.reset_template(AllowOn.RULE)
        for hr in range(0, 24):
            for mn in range(0, 60, 15):
                self.assertEqual(sut.active().get_slot(hr, mn).allow_on, AllowOn.NEVER, f"Failed slot {hr}:{mn}")
                self.assertEqual(sut.get_slot(hr, mn).allow_on, AllowOn.RULE, f"Failed template slot {hr}:{mn}")

    def test_apply_rules(self):
        clock = FakeClock(15, 30)
        sut = ScheduleBuilder(ignore_state_changes, None, [RuleAlwaysOff()], clock)
        sut.from_json(get_schedule_all_slots(AllowOn.ALWAYS))
        sut.active().set_slot(15, 30, allow_on=AllowOn.RULE)

        self.assertEqual(sut.active().get_slot(15, 30).allow_on, AllowOn.RULE)
        self.assertEqual(sut.active().get_slot(15, 30).request_on, True)
        sut.tick()
        self.assertEqual(sut.active().get_slot(15, 30).allow_on, AllowOn.RULE)
        self.assertEqual(sut.active().get_slot(15, 30).reason, "RuleAlwaysOff")
        self.assertEqual(sut.active().get_slot(15, 30).request_on, False)

    def test_apply_rules_in_order(self):
        clock = FakeClock(15, 30)
        sut = ScheduleBuilder(ignore_state_changes, None, [RuleAlwaysOn(), RuleAlwaysOff()], clock)
        sut.from_json(get_schedule_all_slots(AllowOn.ALWAYS))
        sut.active().set_slot(15, 30, allow_on=AllowOn.RULE)
        sut.tick()
        self.assertEqual(sut.active().get_slot(15, 30).reason, "RuleAlwaysOff")
        self.assertEqual(sut.active().get_slot(15, 30).request_on, False)

    def test_apply_multiple_rules_notify_last(self):
        clock = FakeClock(15, 30)
        state_change_saver = StateChangeSaver()
        sut = ScheduleBuilder(state_change_saver.save_state_changes, None, [RuleAlwaysOn(), RuleAlwaysOff(), RuleAlwaysOnAgain()], clock)

        sut.from_json(get_schedule_all_slots(AllowOn.ALWAYS))
        sut.active().set_slot(15, 30, allow_on=AllowOn.RULE)
        sut.tick()

        self.assertEqual(state_change_saver.saved_new.allow_on, AllowOn.RULE)
        self.assertEqual(state_change_saver.saved_new.request_on, True)
        self.assertEqual(state_change_saver.saved_new.reason, "RuleAlwaysOnAgain")

    def test_apply_rules_and_tick_notify_once(self):
        clock = FakeClock(15, 0)
        state_change_saver = StateChangeSaver()
        sut = ScheduleBuilder(state_change_saver.save_state_changes, None, [RuleAlwaysOn(), RuleAlwaysOff(), RuleAlwaysOnAgain()], clock)

        sut.from_json(get_schedule_all_slots(AllowOn.NEVER))
        sut.active().set_slot(15, 15, allow_on=AllowOn.RULE)
        sut.active().set_slot(15, 30, allow_on=AllowOn.RULE)
        sut.tick()

        start_count = state_change_saver.count
        self.assertEqual(state_change_saver.saved_new.allow_on, AllowOn.NEVER)
        self.assertEqual(state_change_saver.saved_new.request_on, False)

        clock.set_t(15, 15)
        sut.tick()
        self.assertEqual(state_change_saver.count, start_count + 1)
        self.assertEqual(state_change_saver.saved_old.allow_on, AllowOn.NEVER)
        self.assertEqual(state_change_saver.saved_old.request_on, False)
        self.assertEqual(state_change_saver.saved_new.allow_on, AllowOn.RULE)
        self.assertEqual(state_change_saver.saved_new.request_on, True)
        self.assertEqual(state_change_saver.saved_new.reason, "RuleAlwaysOnAgain")

        clock.set_t(15, 20)
        sut.tick()
        self.assertEqual(state_change_saver.count, start_count + 1)

        clock.set_t(15, 30)
        sut.tick()
        self.assertEqual(state_change_saver.count, start_count + 1)

        clock.set_t(15, 45)
        sut.tick()
        self.assertEqual(state_change_saver.count, start_count + 2)


if __name__ == '__main__':
    unittest.main()
