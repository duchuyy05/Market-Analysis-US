"""Regressions for real CSV downloads, including filenames with digits."""
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from market_radar.csv_exports import csv_files, csv_downloads_html
from market_radar.local_app import Jobs, LocalServer


class Links(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.links = []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


class CSVExports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)/"data"/"csv-fixture"
        self.output.mkdir(parents=True)
        (self.output/"monthly_top5.csv").write_text('asin,note\nTEST000001,"First line\nsecond line"\nTEST000002,normal\n',encoding="utf-8-sig")
        (self.output/"reviews.csv").write_text('asin,text\nTEST000001,"quoted, text"\n',encoding="utf-8-sig")
        (self.output/".private.csv").write_text("private,value",encoding="utf-8")
        (self.output/"not-an-export.csv").write_text("private,value",encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_lists_only_actual_public_csvs_and_counts_records_not_text_lines(self):
        files = csv_files(self.output)
        self.assertEqual([f["filename"] for f in files],["monthly_top5.csv","reviews.csv"])
        self.assertEqual([f["rows"] for f in files],[2,1])
        self.assertIn("tháng",files[0]["title"])
        self.assertTrue(all(f["description"] for f in files))

    def test_download_list_links_every_available_file_with_native_download_attribute(self):
        files = csv_files(self.output)
        document = csv_downloads_html(files,expanded=True)
        links = Links(document).links
        self.assertEqual([a["href"] for a in links],[f["filename"] for f in files])
        self.assertEqual([a["download"] for a in links],[a["href"] for a in links])
        self.assertIn('class="csv-picker" open',document)
        self.assertIn("2 file",document)
        self.assertNotIn(".private.csv",document)

    def test_empty_folder_has_no_broken_download_links(self):
        empty = self.output/"empty"
        empty.mkdir()
        files = csv_files(empty)
        self.assertEqual(files,[])
        self.assertEqual(Links(csv_downloads_html(files)).links,[])

    def test_http_serves_csv_names_with_digits_as_attachments_and_blocks_private_paths(self):
        manager = Jobs(Path(self.temp.name))
        server = LocalServer(("127.0.0.1",0),manager)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}/runs/csv-fixture/"
        try:
            for name in ("monthly_top5.csv","reviews.csv"):
                with urlopen(base+name) as response:
                    self.assertEqual(response.status,200)
                    self.assertEqual(response.headers.get_content_type(),"text/csv")
                    self.assertEqual(response.headers["Content-Disposition"],f'attachment; filename="{name}"')
                    self.assertEqual(response.read(),(self.output/name).read_bytes())
            for name in (".private.csv","../outside.csv","raw/secret.csv","not-an-export.csv"):
                with self.assertRaises(HTTPError) as error:
                    urlopen(base+name)
                self.assertEqual(error.exception.code,404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_two_dashboards_cannot_silently_share_the_same_port(self):
        manager = Jobs(Path(self.temp.name))
        first = LocalServer(("127.0.0.1",0),manager)
        second = None
        try:
            with self.assertRaises(OSError):
                second = LocalServer(first.server_address,manager)
        finally:
            if second:
                second.server_close()
            first.server_close()


if __name__ == "__main__":
    unittest.main()
