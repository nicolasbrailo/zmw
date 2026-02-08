import json
import unittest

from rules import create_rules_from_config
from rules_predictive_target_temp import PredictiveTargetTemperature


class PredictiveTargetTemperatureTest(unittest.TestCase):
    def test_create_PredictiveTargetTemperature(self):
        cfg = """[{
            "name": "PredictiveTargetTemperature",
            "sensor": "OliviaAQMSensor",
            "metric": "temperature",
            "target_time": "8:00",
            "start": "4:00",
            "days": "weekend",
            "target_min_temp": 19,
            "target_max_temp": 20
        }]"""
        rules = create_rules_from_config(json.loads(cfg))
        self.assertEqual(len(rules), 1)
        self.assertEqual(type(rules[0]), PredictiveTargetTemperature)
        self.assertEqual(rules[0].sensor_name, "OliviaAQMSensor")
        self.assertEqual(rules[0].metric, "temperature")
        self.assertEqual(rules[0].target_min_temp, 19)
        self.assertEqual(rules[0].target_max_temp, 20)
        self.assertEqual(rules[0].days, "weekend")

    def test_fails_create_PredictiveTargetTemperature(self):
        # Missing sensor key
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "metric": "temperature", "target_time": "8:00", "start": "4:00", "days": "all", "target_min_temp": 19, "target_max_temp": 20}]"""))

        # Missing metric key
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "target_time": "8:00", "start": "4:00", "days": "all", "target_min_temp": 19, "target_max_temp": 20}]"""))

        # Absurd temperature fails
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "8:00", "start": "4:00", "days": "all", "target_min_temp": 19, "target_max_temp": -40}]"""))
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "8:00", "start": "4:00", "days": "all", "target_min_temp": -40, "target_max_temp": 20}]"""))
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "8:00", "start": "4:00", "days": "all", "target_min_temp": 19, "target_max_temp": 123}]"""))
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "8:00", "start": "4:00", "days": "all", "target_min_temp": 123, "target_max_temp": 20}]"""))

        # min > max
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "8:00", "start": "4:00", "days": "all", "target_min_temp": 25, "target_max_temp": 20}]"""))

        # Invalid days
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "8:00", "start": "4:00", "days": "xX", "target_min_temp": 19, "target_max_temp": 20}]"""))

        # Invalid time format
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "99:00", "start": "4:00", "days": "all", "target_min_temp": 19, "target_max_temp": 20}]"""))
        self.assertRaises(ValueError, create_rules_from_config, json.loads(
            """[{"name": "PredictiveTargetTemperature", "sensor": "S1", "metric": "temperature", "target_time": "8:00", "start": "99:00", "days": "all", "target_min_temp": 19, "target_max_temp": 20}]"""))


if __name__ == '__main__':
    unittest.main()
