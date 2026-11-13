"""Check the public GitHub Release without blocking application startup."""
import json
import re
from urllib.request import Request, urlopen

VERSION = "1.1.0"
RELEASE_API = "https://api.github.com/repos/funny4875/DocPilot/releases/latest"
RELEASE_PAGE = "https://github.com/funny4875/DocPilot/releases/latest"


def version_tuple(tag):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(map(int, match.groups())) if match else None


def latest_version():
    request = Request(RELEASE_API, headers={"User-Agent": "DocPilot-update-check", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=5) as response:
        data = json.load(response)
    tag = data.get("tag_name", "")
    version = version_tuple(tag) if isinstance(tag, str) else None
    return tag if version and version > version_tuple(VERSION) else None
