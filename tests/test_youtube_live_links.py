"""
Nightly debug run: a YouTube live-stream link (youtube.com/live/<id>, which is
what the Share button gives for a live or past stream) and a YouTube Music link
(music.youtube.com/watch?v=<id>) were refused with "Could not extract video ID",
although both name an ordinary video id.
"""
import pytest

import app as appmod


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/live/abcdefghijk",
    "https://youtube.com/live/abcdefghijk?si=xyz",
    "https://m.youtube.com/live/abcdefghijk",
    "https://music.youtube.com/watch?v=abcdefghijk&list=RDx",
])
def test_live_and_music_links_give_the_id(url):
    assert appmod._extract_video_id(url) == "abcdefghijk"


@pytest.mark.parametrize("url", [
    "https://evil.com/live/abcdefghijk",
    "https://music.evil.com/watch?v=abcdefghijk",
    "https://youtube.com.evil.com/live/abcdefghijk",
])
def test_other_hosts_still_refused(url):
    assert appmod._extract_video_id(url) is None
