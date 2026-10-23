"""Meaningful seasonality/ranking regressions using synthetic evidence only."""
import unittest
from market_radar.monthly_analysis import timing_profiles,listing_evidence,review_tables
from market_radar.seasonal_data import monthly_top_five
from market_radar.seasonal import family_match


SETTINGS={"min_positive_week_points_per_q4":3,"min_completed_years_for_timing":2,"ramp_up_profile_threshold_pct":40}


def data_for(values):
    rows=[]
    for year,indices in values.items():
        for month,index in zip((10,11,12),indices):
            rows.append({"keyword_id":"K-test","year":year,"month":month,"observed_days":31 if month!=11 else 30,
                "calendar_days":31 if month!=11 else 30,"mean_interest_index":index,"positive_source_points":4 if index else 0,
                "source_url":"https://example.test","source_raw_file":"raw/test.json","observation_status":"complete_month"})
    return {"as_of_date":"2026-10-22","market":"US","history_years":[2023,2024,2025,2026],"trends":rows,
        "keywords":[{"keyword_id":"K-test","keyword":"halloween lights","component_id":"test","same_period_yoy_change_pct":None}]}


def candidate(asin,family,band,profile=100,status="historical_q4_peak"):
    return {"month":10,"asin":asin,"timing_keyword_id":family,"current_purchase_band_lower_bound":band,
        "historical_profile_pct_of_own_q4_peak":profile,"timing_status":status}


class MonthlyTests(unittest.TestCase):
    def test_halloween_peak_is_derived_from_history_and_partial_2026_is_excluded(self):
        data=data_for({2023:[90,10,1],2024:[100,8,1],2025:[95,5,1],2026:[1,100,100]})
        profiles=timing_profiles(data,SETTINGS)
        self.assertEqual(profiles[0]["timing_status"],"historical_q4_peak")
        self.assertEqual(profiles[0]["peak_years"],[2023,2024,2025])
        self.assertEqual(profiles[1]["timing_status"],"preparation_or_off_peak")

    def test_flat_series_does_not_become_three_seasonal_peaks(self):
        profiles=timing_profiles(data_for({2023:[10,10,10],2024:[10,10,10]}),SETTINGS)
        self.assertFalse(any(r["timing_status"] in ("historical_q4_peak","historical_build_up") for r in profiles))

    def test_zero_signal_does_not_produce_hot_month(self):
        profiles=timing_profiles(data_for({2023:[0,0,0],2024:[0,0,0],2025:[0,0,0]}),SETTINGS)
        self.assertTrue(all(r["timing_status"]=="insufficient_search_history" for r in profiles))

    def test_top_five_diversifies_families_and_does_not_force_five_records(self):
        rows=[candidate("A","K-a",10000),candidate("B","K-a",9000),candidate("C","K-b",1000)]
        result=monthly_top_five({"product_month_opportunities":rows},SETTINGS)
        self.assertEqual([r["asin"] for r in result],["A","C","B"])
        self.assertEqual(len(result),3)

    def test_high_current_band_does_not_make_off_season_product_hot(self):
        result=monthly_top_five({"product_month_opportunities":[candidate("A","K-a",99999,5,"preparation_or_off_peak"),candidate("B","K-b",1000)]},SETTINGS)
        self.assertEqual([r["asin"] for r in result],["B"])

    def test_keyword_peak_without_current_product_purchase_badge_is_not_top_five(self):
        result=monthly_top_five({"product_month_opportunities":[candidate("A","K-a",None)]},SETTINGS)
        self.assertEqual(result,[])

    def test_craft_family_does_not_accept_face_paint_only(self):
        family={"required_patterns":["halloween","craft|diy|art kits?"]}
        self.assertFalse(family_match("Halloween face body paint palette artist costume",family))
        self.assertTrue(family_match("Halloween DIY craft kits",family))

    def test_gift_basket_family_does_not_accept_a_lighter_marketed_as_a_gift(self):
        family={"required_patterns":["christmas|xmas|holiday","gift baskets?|gift box(?:es)?|gift sets?"]}
        self.assertFalse(family_match("Electric Candle Lighter Christmas Stocking Stuffers Gift",family))
        self.assertFalse(family_match("Fidget Toys Christmas Stocking Stuffer Easter Basket Stuffer Gift",family))
        self.assertFalse(family_match("Boo Basket Stuffers Christmas Gift for Women Shower Steamers",family))
        self.assertTrue(family_match("Christmas gift basket with snacks",family))

    def test_listing_quote_position_is_reproducible(self):
        text="Halloween lights battery powered set"
        data={"products":[{"asin":"A","product_name":text,"seller_features":"","description":"","source_url":"https://example.test","source_raw_file":"raw/test.json","observed_at_utc":"test"}],
              "product_components":[{"asin":"A","component_id":"lights","matched_text":"lights"}]}
        quote=listing_evidence(data)[0]
        self.assertEqual(text[quote["quote_start"]:quote["quote_end_exclusive"]],quote["verbatim_quote"])

    def test_future_review_month_is_blank_not_zero(self):
        summary,_=review_tables({"reviews":[],"customer_needs":[],"as_of_date":"2026-10-22","history_years":[2023,2024,2025,2026]})
        self.assertIsNone(summary[-1]["review_texts_in_sample"])
        self.assertEqual(summary[0]["review_texts_in_sample"],0)

    def test_family_requires_season_and_product_form(self):
        family={"required_patterns":["halloween","window|cling"]}
        self.assertTrue(family_match("Halloween window clings",family))
        self.assertFalse(family_match("Christmas window clings",family))
        self.assertFalse(family_match("Halloween gift box",family))


if __name__=="__main__":unittest.main()
