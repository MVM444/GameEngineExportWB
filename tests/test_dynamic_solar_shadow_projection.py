"""Full-cycle validation for Castle's dynamic Solar shadow projection."""

from __future__ import annotations

import math
import unittest

from freecad.GameEngineExportWB.core import exporter_x3d
from freecad.GameEngineExportWB.core import solar


LATITUDE_DEG = 9.933
LONGITUDE_DEG = -84.1
TIMEZONE_HOURS = -6.0
NORTH_DEG = 90.0
TEST_DAYS = (1, 80, 172, 266, 355)
SHADOW_CENTER = (11.0, 1.15, -7.0)
SHADOW_RADIUS = 30.0
SHADOW_DISTANCE = 60.0
POLE_HEIGHT = 3.0


def _state(day: int, hour: float):
    sun = solar.approximate_sun_position(
        day,
        hour,
        LATITUDE_DEG,
        LONGITUDE_DEG,
        TIMEZONE_HOURS,
        NORTH_DEG,
    )
    direction = (-sun[0], -sun[2], sun[1])
    location = exporter_x3d._solar_shadow_projection_location(
        SHADOW_CENTER,
        direction,
        SHADOW_DISTANCE,
    )
    up = exporter_x3d._solar_shadow_up_vector(direction)
    altitude = math.degrees(math.asin(max(-1.0, min(1.0, sun[2]))))
    daylight = max(0.0, min(1.0, sun[2] * 2.0))
    shadow_length = None
    shadow_endpoint = None
    if sun[2] > 0.0:
        scale = POLE_HEIGHT / sun[2]
        shadow_endpoint = (-sun[0] * scale, -sun[1] * scale)
        shadow_length = math.hypot(*shadow_endpoint)
    return {
        "sun": sun,
        "direction": direction,
        "location": location,
        "up": up,
        "altitude": altitude,
        "daylight": daylight,
        "shadow_length": shadow_length,
        "shadow_endpoint": shadow_endpoint,
    }


def _angle_deg(left, right) -> float:
    cosine = sum(a * b for a, b in zip(left, right))
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


class DynamicSolarShadowProjectionTests(unittest.TestCase):
    def assert_state_geometry(self, state):
        direction = state["direction"]
        location = state["location"]
        up = state["up"]
        self.assertAlmostEqual(1.0, math.sqrt(sum(value * value for value in direction)), places=9)
        self.assertAlmostEqual(
            SHADOW_DISTANCE,
            math.sqrt(
                sum(
                    (location[index] - SHADOW_CENTER[index]) ** 2
                    for index in range(3)
                )
            ),
            places=9,
        )
        for index in range(3):
            self.assertAlmostEqual(
                SHADOW_CENTER[index],
                location[index] + direction[index] * SHADOW_DISTANCE,
                places=9,
            )
        self.assertAlmostEqual(
            0.0,
            sum(up[index] * direction[index] for index in range(3)),
            places=9,
        )

    def test_complete_24_hour_cycle_on_multiple_dates(self):
        for day in TEST_DAYS:
            states = [_state(day, float(hour)) for hour in range(24)]
            with self.subTest(day=day):
                for state in states:
                    self.assert_state_geometry(state)
                for previous, current in zip(states, states[1:]):
                    self.assertLess(
                        _angle_deg(previous["direction"], current["direction"]),
                        20.0,
                    )
                self.assertTrue(any(state["altitude"] > 0.0 for state in states))
                self.assertTrue(any(state["altitude"] < 0.0 for state in states))

    def test_quarter_hour_continuity_through_sunrise_and_sunset(self):
        for day in TEST_DAYS:
            samples = [_state(day, quarter / 4.0) for quarter in range(97)]
            crossings = []
            for index in range(1, len(samples)):
                before = samples[index - 1]["altitude"]
                after = samples[index]["altitude"]
                if (before <= 0.0 < after) or (before >= 0.0 > after):
                    crossings.append(index)
            with self.subTest(day=day):
                self.assertEqual(2, len(crossings))
                for crossing in crossings:
                    start = max(1, crossing - 4)
                    stop = min(len(samples), crossing + 5)
                    for index in range(start, stop):
                        previous = samples[index - 1]
                        current = samples[index]
                        self.assert_state_geometry(current)
                        self.assertLess(
                            _angle_deg(previous["direction"], current["direction"]),
                            5.0,
                        )
                        self.assertLessEqual(
                            abs(previous["daylight"] - current["daylight"]),
                            0.15,
                        )
                        expected_location_delta = SHADOW_DISTANCE * math.sqrt(
                            sum(
                                (
                                    previous["direction"][axis]
                                    - current["direction"][axis]
                                )
                                ** 2
                                for axis in range(3)
                            )
                        )
                        actual_location_delta = math.sqrt(
                            sum(
                                (
                                    previous["location"][axis]
                                    - current["location"][axis]
                                )
                                ** 2
                                for axis in range(3)
                            )
                        )
                        self.assertAlmostEqual(
                            expected_location_delta,
                            actual_location_delta,
                            places=9,
                        )

    def test_shadow_length_and_direction_for_all_daylight_quarter_hours(self):
        for day in TEST_DAYS:
            previous_endpoint = None
            for quarter in range(97):
                hour = quarter / 4.0
                state = _state(day, hour)
                if state["altitude"] <= 0.25:
                    previous_endpoint = None
                    continue
                with self.subTest(day=day, hour=hour):
                    expected_length = POLE_HEIGHT / math.tan(
                        math.radians(state["altitude"])
                    )
                    self.assertAlmostEqual(
                        expected_length,
                        state["shadow_length"],
                        places=9,
                    )
                    endpoint = state["shadow_endpoint"]
                    sun = state["sun"]
                    self.assertLessEqual(endpoint[0] * sun[0], 1e-9)
                    self.assertLessEqual(endpoint[1] * sun[1], 1e-9)
                    if previous_endpoint is not None:
                        self.assertTrue(
                            all(math.isfinite(value) for value in endpoint)
                        )
                    previous_endpoint = endpoint

    def test_projection_depth_and_rectangle_cover_bounding_sphere(self):
        near = SHADOW_DISTANCE - SHADOW_RADIUS
        far = SHADOW_DISTANCE + SHADOW_RADIUS
        for day in TEST_DAYS:
            for hour in range(24):
                state = _state(day, float(hour))
                direction = state["direction"]
                location = state["location"]
                closest = tuple(
                    SHADOW_CENTER[index] - direction[index] * SHADOW_RADIUS
                    for index in range(3)
                )
                farthest = tuple(
                    SHADOW_CENTER[index] + direction[index] * SHADOW_RADIUS
                    for index in range(3)
                )
                closest_depth = sum(
                    (closest[index] - location[index]) * direction[index]
                    for index in range(3)
                )
                farthest_depth = sum(
                    (farthest[index] - location[index]) * direction[index]
                    for index in range(3)
                )
                self.assertAlmostEqual(near, closest_depth, places=9)
                self.assertAlmostEqual(far, farthest_depth, places=9)


if __name__ == "__main__":
    unittest.main()
