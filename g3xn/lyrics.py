"""Song lyrics for the stage view, looked up on LRCLIB (lrclib.net: free, no key).

    find("Sultans of Swing", "Dire Straits") -> {"song", "artist", "lyrics", "source"} or None

The words are fetched for the user's own gig file; nothing is kept here.
"""
import json
import urllib.parse
import urllib.request

SEARCH = "https://lrclib.net/api/search"
AGENT = "g3xn (https://github.com/cwoodard1121/zoom-g3xn-agent-skill)"   # LRCLIB asks clients to name themselves


class LyricsError(Exception):
    pass


def find(song, artist=None, timeout=10):
    """The best match's plain lyrics, or None if LRCLIB has no words for it."""
    query = {"track_name": song}
    if artist:
        query["artist_name"] = artist
    hits = _get(SEARCH + "?" + urllib.parse.urlencode(query), timeout)
    if not hits and artist:                       # artists are often spelled differently; try the title alone
        hits = _get(SEARCH + "?" + urllib.parse.urlencode({"q": "%s %s" % (song, artist)}), timeout)
    for hit in hits:
        if hit.get("plainLyrics") and not hit.get("instrumental"):
            return {"song": hit.get("trackName") or song, "artist": hit.get("artistName") or artist,
                    "lyrics": hit["plainLyrics"].strip(), "source": "LRCLIB"}
    return None


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except (OSError, ValueError) as e:
        raise LyricsError("Couldn't reach LRCLIB for lyrics (%s). Is this computer online?" % e) from e
