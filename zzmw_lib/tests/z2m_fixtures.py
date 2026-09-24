import json
import logging

# Comment out for output in unit test
print("Disable stdout log for test")
logging.getLogger().addHandler(logging.NullHandler())

def get_broken_thing():
    return json.loads('''{
        "definition": null,
        "endpoints": {},
        "friendly_name": "foo",
        "ieee_address": "bar",
        "interview_completed": false,
        "interviewing": false,
        "network_address": 27798,
        "supported": false,
        "type": "Unknown"
    }''')


def get_a_lamp():
    return json.loads('''{
        "date_code": "20200312",
        "definition": {
            "description": "TRADFRI LED bulb E27 1000 lumen, dimmable, white spectrum, opal white",
            "exposes": [
                {
                    "features": [
                        {
                            "access": 7,
                            "description": "On/off state of this light",
                            "name": "state",
                            "property": "state",
                            "type": "binary",
                            "value_off": "OFF",
                            "value_on": "ON",
                            "value_toggle": "TOGGLE"
                        },
                        {
                            "access": 7,
                            "description": "Brightness of this light",
                            "name": "brightness",
                            "property": "brightness",
                            "type": "numeric",
                            "value_max": 254,
                            "value_min": 0
                        },
                        {
                            "access": 7,
                            "description": "Color temperature of this light",
                            "name": "color_temp",
                            "presets": [
                                {
                                    "description": "Coolest temperature supported",
                                    "name": "coolest",
                                    "value": 250
                                },
                                {
                                    "description": "Cool temperature (250 mireds / 4000 Kelvin)",
                                    "name": "cool",
                                    "value": 250
                                },
                                {
                                    "description": "Neutral temperature (370 mireds / 2700 Kelvin)",
                                    "name": "neutral",
                                    "value": 370
                                },
                                {
                                    "description": "Warm temperature (454 mireds / 2200 Kelvin)",
                                    "name": "warm",
                                    "value": 454
                                },
                                {
                                    "description": "Warmest temperature supported",
                                    "name": "warmest",
                                    "value": 454
                                }
                            ],
                            "property": "color_temp",
                            "type": "numeric",
                            "unit": "mired",
                            "value_max": 454,
                            "value_min": 250
                        },
                        {
                            "access": 7,
                            "description": "Color temperature after cold power on of this light",
                            "name": "color_temp_startup",
                            "presets": [
                                {
                                    "description": "Coolest temperature supported",
                                    "name": "coolest",
                                    "value": 250
                                },
                                {
                                    "description": "Cool temperature (250 mireds / 4000 Kelvin)",
                                    "name": "cool",
                                    "value": 250
                                },
                                {
                                    "description": "Neutral temperature (370 mireds / 2700 Kelvin)",
                                    "name": "neutral",
                                    "value": 370
                                },
                                {
                                    "description": "Warm temperature (454 mireds / 2200 Kelvin)",
                                    "name": "warm",
                                    "value": 454
                                },
                                {
                                    "description": "Warmest temperature supported",
                                    "name": "warmest",
                                    "value": 454
                                },
                                {
                                    "description": "Restore previous color_temp on cold power on",
                                    "name": "previous",
                                    "value": 65535
                                }
                            ],
                            "property": "color_temp_startup",
                            "type": "numeric",
                            "unit": "mired",
                            "value_max": 454,
                            "value_min": 250
                        }
                    ],
                    "type": "light"
                },
                {
                    "access": 2,
                    "description": "Triggers an effect on the light (e.g. make light blink for a few seconds)",
                    "name": "effect",
                    "property": "effect",
                    "type": "enum",
                    "values": [
                        "blink",
                        "breathe",
                        "okay",
                        "channel_change",
                        "finish_effect",
                        "stop_effect"
                    ]
                },
                {
                    "access": 7,
                    "description": "Controls the behavior when the device is powered on",
                    "name": "power_on_behavior",
                    "property": "power_on_behavior",
                    "type": "enum",
                    "values": [
                        "off",
                        "previous",
                        "on"
                    ]
                },
                {
                    "access": 1,
                    "description": "Link quality (signal strength)",
                    "name": "linkquality",
                    "property": "linkquality",
                    "type": "numeric",
                    "unit": "lqi",
                    "value_max": 255,
                    "value_min": 0
                }
            ],
            "model": "LED1732G11",
            "options": [
                {
                    "access": 2,
                    "description": "Controls the transition time (in seconds) of on/off, brightness, color temperature (if applicable) and color (if applicable) changes. Defaults to `0` (no transition).",
                    "name": "transition",
                    "property": "transition",
                    "type": "numeric",
                    "value_min": 0
                },
                {
                    "access": 2,
                    "description": "When enabled colors will be synced, e.g. if the light supports both color x/y and color temperature a conversion from color x/y to color temperature will be done when setting the x/y color (default true).",
                    "name": "color_sync",
                    "property": "color_sync",
                    "type": "binary",
                    "value_off": false,
                    "value_on": true
                }
            ],
            "supports_ota": true,
            "vendor": "IKEA"
        },
        "endpoints": {
            "1": {
                "bindings": [],
                "clusters": {
                    "input": [
                        "genBasic",
                        "genIdentify",
                        "genGroups",
                        "genScenes",
                        "genOnOff",
                        "genLevelCtrl",
                        "lightingColorCtrl",
                        "touchlink",
                        "64636"
                    ],
                    "output": [
                        "genScenes",
                        "genOta",
                        "genPollCtrl",
                        "touchlink"
                    ]
                },
                "configured_reportings": [],
                "scenes": []
            },
            "242": {
                "bindings": [],
                "clusters": {
                    "input": [
                        "greenPower"
                    ],
                    "output": [
                        "greenPower"
                    ]
                },
                "configured_reportings": [],
                "scenes": []
            }
        },
        "friendly_name": "Oficina",
        "ieee_address": "0x847127fffecda276",
        "interview_completed": true,
        "interviewing": false,
        "manufacturer": "IKEA of Sweden",
        "model_id": "TRADFRI bulb E27 WS opal 1000lm",
        "network_address": 14587,
        "power_source": "Mains (single phase)",
        "software_build_id": "2.0.029",
        "supported": true,
        "type": "Router"
    }''')


def get_lamp_multiple_types():
    return json.loads('''{
        "date_code": "20200312",
        "definition": {
          "description": "TRADFRI LED bulb E27 1000 lumen, dimmable, white spectrum, opal white",
          "exposes": [
            {
              "features": [
                {
                  "access": 7,
                  "description": "On/off state of this light",
                  "label": "State",
                  "name": "state",
                  "property": "state",
                  "type": "binary",
                  "value_off": "OFF",
                  "value_on": "ON",
                  "value_toggle": "TOGGLE"
                }
              ],
              "type": "first_thing_type"
            },
            {
              "access": 7,
              "description": "Advanced color behavior",
              "features": [
                {
                  "access": 2,
                  "description": "Controls whether color and color temperature can be set while light is off",
                  "label": "Execute if off",
                  "name": "execute_if_off",
                  "property": "execute_if_off",
                  "type": "binary",
                  "value_off": 0,
                  "value_on": 1
                }
              ],
              "label": "Color options",
              "name": "color_options",
              "property": "color_options",
              "type": "second_thing_type"
            }
          ],
          "model": "LED1732G11",
          "supports_ota": 1,
          "vendor": "IKEA"
        },
        "disabled": 0,
        "friendly_name": "Lamp2_IkeaWhiteColor",
        "ieee_address": "0x847127fffecda276",
        "interview_completed": 1,
        "interviewing": 0,
        "manufacturer": "IKEA of Sweden",
        "model_id": "TRADFRI bulb E27 WS opal 1000lm",
        "network_address": 51402,
        "power_source": "Mains (single phase)",
        "software_build_id": "2.0.029",
        "supported": 1,
        "type": "Router"
      }''')

def get_contact_sensor():
    return json.loads('''{
        "date_code": "20161128",
        "definition": {
            "description": "Aqara door & window contact sensor",
            "exposes": [
                {
                    "access": 1,
                    "description": "Remaining battery in %",
                    "name": "battery",
                    "property": "battery",
                    "type": "numeric",
                    "unit": "%",
                    "value_max": 100,
                    "value_min": 0
                },
                {
                    "access": 1,
                    "description": "Indicates if the contact is closed (= true) or open (= false)",
                    "name": "contact",
                    "property": "contact",
                    "type": "binary",
                    "value_off": true,
                    "value_on": false
                },
                {
                    "access": 1,
                    "description": "Measured temperature value",
                    "name": "temperature",
                    "property": "temperature",
                    "type": "numeric",
                    "unit": "\u00b0C"
                },
                {
                    "access": 1,
                    "description": "Voltage of the battery in millivolts",
                    "name": "voltage",
                    "property": "voltage",
                    "type": "numeric",
                    "unit": "mV"
                },
                {
                    "access": 1,
                    "description": "Link quality (signal strength)",
                    "name": "linkquality",
                    "property": "linkquality",
                    "type": "numeric",
                    "unit": "lqi",
                    "value_max": 255,
                    "value_min": 0
                }
            ],
            "model": "MCCGQ11LM",
            "options": [
                {
                    "access": 2,
                    "description": "Number of digits after decimal point for temperature, takes into effect on next report of device.",
                    "name": "temperature_precision",
                    "property": "temperature_precision",
                    "type": "numeric",
                    "value_max": 3,
                    "value_min": 0
                },
                {
                    "access": 2,
                    "description": "Calibrates the temperature value (absolute offset), takes into effect on next report of device.",
                    "name": "temperature_calibration",
                    "property": "temperature_calibration",
                    "type": "numeric"
                }
            ],
            "supports_ota": false,
            "vendor": "Xiaomi"
        },
        "endpoints": {
            "1": {
                "bindings": [],
                "clusters": {
                    "input": [
                        "genBasic",
                        "genIdentify",
                        "65535",
                        "genOnOff"
                    ],
                    "output": [
                        "genBasic",
                        "genGroups",
                        "65535"
                    ]
                },
                "configured_reportings": [],
                "scenes": []
            }
        },
        "friendly_name": "SensorPuertaEntrada",
        "ieee_address": "0x00158d0008ad5e77",
        "interview_completed": true,
        "interviewing": false,
        "manufacturer": "LUMI",
        "model_id": "lumi.sensor_magnet.aq2",
        "network_address": 14916,
        "power_source": "Battery",
        "software_build_id": "3000-0001",
        "supported": true,
        "type": "EndDevice"
    }''')


def get_motion_sensor():
    return json.loads('''{
        "date_code": "20190308",
        "definition": {
            "description": "TRADFRI motion sensor",
            "exposes": [
                {
                    "access": 1,
                    "description": "Remaining battery in %",
                    "name": "battery",
                    "property": "battery",
                    "type": "numeric",
                    "unit": "%",
                    "value_max": 100,
                    "value_min": 0
                },
                {
                    "access": 1,
                    "description": "Indicates whether the device detected occupancy",
                    "name": "occupancy",
                    "property": "occupancy",
                    "type": "binary",
                    "value_off": false,
                    "value_on": true
                },
                {
                    "access": 1,
                    "name": "requested_brightness_level",
                    "property": "requested_brightness_level",
                    "type": "numeric",
                    "value_max": 254,
                    "value_min": 76
                },
                {
                    "access": 1,
                    "name": "requested_brightness_percent",
                    "property": "requested_brightness_percent",
                    "type": "numeric",
                    "value_max": 100,
                    "value_min": 30
                },
                {
                    "access": 1,
                    "description": "Indicates whether the device detected bright light (works only in night mode)",
                    "name": "illuminance_above_threshold",
                    "property": "illuminance_above_threshold",
                    "type": "binary",
                    "value_off": false,
                    "value_on": true
                },
                {
                    "access": 1,
                    "description": "Link quality (signal strength)",
                    "name": "linkquality",
                    "property": "linkquality",
                    "type": "numeric",
                    "unit": "lqi",
                    "value_max": 255,
                    "value_min": 0
                }
            ],
            "model": "E1525/E1745",
            "options": [
                {
                    "access": 2,
                    "description": "Time in seconds after which occupancy is cleared after detecting it (default 90 seconds).",
                    "name": "occupancy_timeout",
                    "property": "occupancy_timeout",
                    "type": "numeric",
                    "value_min": 0
                },
                {
                    "access": 2,
                    "description": "Set to false to also send messages when illuminance is above threshold in night mode (default true).",
                    "name": "illuminance_below_threshold_check",
                    "property": "illuminance_below_threshold_check",
                    "type": "binary",
                    "value_off": false,
                    "value_on": true
                }
            ],
            "supports_ota": true,
            "vendor": "IKEA"
        },
        "endpoints": {
            "1": {
                "bindings": [
                    {
                        "cluster": "genPollCtrl",
                        "target": {
                            "endpoint": 1,
                            "ieee_address": "0x00124b0022a54d1d",
                            "type": "endpoint"
                        }
                    },
                    {
                        "cluster": "genPowerCfg",
                        "target": {
                            "endpoint": 1,
                            "ieee_address": "0x00124b0022a54d1d",
                            "type": "endpoint"
                        }
                    }
                ],
                "clusters": {
                    "input": [
                        "genBasic",
                        "genPowerCfg",
                        "genIdentify",
                        "genAlarms",
                        "genPollCtrl",
                        "touchlink",
                        "64636"
                    ],
                    "output": [
                        "genIdentify",
                        "genGroups",
                        "genOnOff",
                        "genLevelCtrl",
                        "genOta",
                        "touchlink"
                    ]
                },
                "configured_reportings": [
                    {
                        "attribute": "batteryPercentageRemaining",
                        "cluster": "genPowerCfg",
                        "maximum_report_interval": 62000,
                        "minimum_report_interval": 3600,
                        "reportable_change": 0
                    }
                ],
                "scenes": []
            }
        },
        "friendly_name": "MotionSensor1",
        "ieee_address": "0x94deb8fffe6c209e",
        "interview_completed": true,
        "interviewing": false,
        "manufacturer": "IKEA of Sweden",
        "model_id": "TRADFRI motion sensor",
        "network_address": 58826,
        "power_source": "Battery",
        "software_build_id": "2.0.022",
        "supported": true,
        "type": "EndDevice"
    }''')

def get_lamp_with_composite_action():
    return json.loads('''{
        "date_code": "20170908",
        "definition": {
            "description": "Hue white and color ambiance E26/E27/E14",
            "exposes": [
                {
                    "features": [
                        {
                            "access": 7,
                            "description": "On/off state of this light",
                            "name": "state",
                            "property": "state",
                            "type": "binary",
                            "value_off": "OFF",
                            "value_on": "ON",
                            "value_toggle": "TOGGLE"
                        },
                        {
                            "access": 7,
                            "description": "Color temperature of this light",
                            "name": "color_temp",
                            "presets": [
                                {
                                    "description": "Coolest temperature supported",
                                    "name": "coolest",
                                    "value": 153
                                },
                                {
                                    "description": "Cool temperature (250 mireds / 4000 Kelvin)",
                                    "name": "cool",
                                    "value": 250
                                },
                                {
                                    "description": "Neutral temperature (370 mireds / 2700 Kelvin)",
                                    "name": "neutral",
                                    "value": 370
                                },
                                {
                                    "description": "Warm temperature (454 mireds / 2200 Kelvin)",
                                    "name": "warm",
                                    "value": 454
                                },
                                {
                                    "description": "Warmest temperature supported",
                                    "name": "warmest",
                                    "value": 500
                                }
                            ],
                            "property": "color_temp",
                            "type": "numeric",
                            "unit": "mired",
                            "value_max": 500,
                            "value_min": 153
                        },
                        {
                            "description": "Color of this light in the CIE 1931 color space (x/y)",
                            "features": [
                                {
                                    "access": 7,
                                    "name": "x",
                                    "property": "x",
                                    "type": "numeric"
                                },
                                {
                                    "access": 7,
                                    "name": "y",
                                    "property": "y",
                                    "type": "numeric"
                                }
                            ],
                            "name": "color_xy",
                            "property": "color",
                            "type": "composite"
                        },
                        {
                            "description": "Color of this light expressed as hue/saturation",
                            "features": [
                                {
                                    "access": 7,
                                    "name": "hue",
                                    "property": "hue",
                                    "type": "numeric"
                                },
                                {
                                    "access": 7,
                                    "name": "saturation",
                                    "property": "saturation",
                                    "type": "numeric"
                                }
                            ],
                            "name": "color_hs",
                            "property": "color",
                            "type": "composite"
                        }
                    ],
                    "type": "light"
                },
                {
                    "access": 2,
                    "description": "Triggers an effect on the light (e.g. make light blink for a few seconds)",
                    "name": "effect",
                    "property": "effect",
                    "type": "enum",
                    "values": [
                        "blink",
                        "breathe",
                        "okay",
                        "channel_change",
                        "finish_effect",
                        "stop_effect"
                    ]
                },
                {
                    "access": 1,
                    "description": "Link quality (signal strength)",
                    "name": "linkquality",
                    "property": "linkquality",
                    "type": "numeric",
                    "unit": "lqi",
                    "value_max": 255,
                    "value_min": 0
                }
            ],
            "model": "9290012573A",
            "options": [
                {
                    "access": 2,
                    "description": "Controls the transition time (in seconds) of on/off, brightness, color temperature (if applicable) and color (if applicable) changes. Defaults to `0` (no transition).",
                    "name": "transition",
                    "property": "transition",
                    "type": "numeric",
                    "value_min": 0
                },
                {
                    "access": 2,
                    "description": "When enabled colors will be synced, e.g. if the light supports both color x/y and color temperature a conversion from color x/y to color temperature will be done when setting the x/y color (default true).",
                    "name": "color_sync",
                    "property": "color_sync",
                    "type": "binary",
                    "value_off": false,
                    "value_on": true
                }
            ],
            "supports_ota": true,
            "vendor": "Philips"
        },
        "endpoints": {
            "11": {
                "bindings": [],
                "clusters": {
                    "input": [
                        "genBasic",
                        "genIdentify",
                        "genGroups",
                        "genScenes",
                        "genOnOff",
                        "genLevelCtrl",
                        "lightingColorCtrl",
                        "touchlink",
                        "manuSpecificUbisysDimmerSetup"
                    ],
                    "output": [
                        "genOta"
                    ]
                },
                "configured_reportings": [],
                "scenes": []
            },
            "242": {
                "bindings": [],
                "clusters": {
                    "input": [
                        "greenPower"
                    ],
                    "output": [
                        "greenPower"
                    ]
                },
                "configured_reportings": [],
                "scenes": []
            }
        },
        "friendly_name": "Belador",
        "ieee_address": "0x00178801021c2f01",
        "interview_completed": true,
        "interviewing": false,
        "manufacturer": "Philips",
        "model_id": "LCT012",
        "network_address": 31027,
        "power_source": "Mains (single phase)",
        "software_build_id": "1.29.0_r21169",
        "supported": true,
        "type": "Router"
    }''')
