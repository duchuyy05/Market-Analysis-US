from datetime import date
import unittest
from market_radar.seasonality import monthly_period, weighted_mean, period_keyword_summary


KEYWORD = {"keyword_id":"K-test", "keyword":"bath bomb gift set", "id":"bath_bombs", "name":"Bath bombs", "demand_scope":"gift_set", "keyword_origin":"web matched", "tavily_source_count":1}


def point(start, end, value):
    return {"keyword_id":"K-test", "period_start":start, "period_end_exclusive":end,
            "interest_index":value, "anchor_index":20, "batch_id":"G1", "source_raw_file":"raw/test.json"}


class SeasonalityTests(unittest.TestCase):
    def test_future_months_are_blank_not_zero(self):
        rows = monthly_period([], [KEYWORD], [2026], date(2026,10,22),[10,11,12])
        self.assertEqual(rows[1]["observation_status"], "not_yet_observed")
        self.assertIsNone(rows[1]["mean_interest_index"])

    def test_week_crossing_month_boundary_is_day_weighted(self):
        series = [point("2025-09-28","2025-10-05",40), point("2025-10-05","2025-10-12",20)]
        value, days, _ = weighted_mean(series, date(2025,10,1), date(2025,10,12))
        self.assertEqual(days, 11)
        self.assertAlmostEqual(value, (4*40+7*20)/11, places=4)

    def test_zero_source_value_is_not_missing_but_is_low_signal(self):
        rows = monthly_period([point("2025-10-01","2025-11-01",0)], [KEYWORD], [2025], date(2026,10,22),[10,11,12])
        self.assertEqual(rows[0]["mean_interest_index"], 0)
        self.assertEqual(rows[0]["observation_status"], "below_search_reporting_threshold")

    def test_current_partial_season_is_not_compared_to_full_previous_season(self):
        series = [point("2025-10-01","2025-10-12",10), point("2025-10-12","2025-10-23",10), point("2025-11-01","2026-01-01",90),
                  point("2026-10-01","2026-10-12",20), point("2026-10-12","2026-10-23",20)]
        monthly = monthly_period(series,[KEYWORD],[2025,2026],date(2026,10,22),[10,11,12])
        summary = period_keyword_summary([KEYWORD],monthly,date(2026,10,22),[10,11,12],series)[0]
        self.assertEqual(summary["same_period_yoy_change_pct"],100)
        self.assertEqual(summary["period_2026_status"],"partial_period")


if __name__ == "__main__":
    unittest.main()
