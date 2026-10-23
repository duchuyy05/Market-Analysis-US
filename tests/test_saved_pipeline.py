"""Rebuild saved evidence offline to catch changes introduced by pipeline cleanup."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import tempfile
import unittest

from market_radar.io import ROOT
from market_radar.seasonal_data import build_seasonal_data, verify_seasonal_data
from market_radar.seasonal_report import generate_report


class SavedPipelineTests(unittest.TestCase):
    def test_saved_sources_rebuild_reproducible_csv_tables(self):
        source = ROOT/"data/seasonal-gifts-us"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            shutil.copyfile(source/"collection.json",output/"collection.json")
            shutil.copytree(source/"raw",output/"raw")
            if (source/"supplements").exists():
                shutil.copytree(source/"supplements",output/"supplements")
            with redirect_stdout(io.StringIO()):
                build_seasonal_data(output)
                generate_report(output)
                verify_seasonal_data(output)
            expected = {p.name:p.read_bytes() for p in output.glob("*.csv")}
            with redirect_stdout(io.StringIO()):
                build_seasonal_data(output)
                generate_report(output)
                verify_seasonal_data(output)
            self.assertEqual(expected,{p.name:p.read_bytes() for p in output.glob("*.csv")})
            self.assertIn("keyword_product_evidence.csv",expected)


if __name__ == "__main__":
    unittest.main()
