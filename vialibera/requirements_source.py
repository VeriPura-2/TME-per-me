"""The one door to the required-documents data (22 Nov 2026).

Every module asks this interface, never requirements.py directly, so the source can move from the checked
rows in requirements.py to VeriPura Core without touching the rest of the app.

REQUIREMENTS_SOURCE=local (default): requirements.py.
REQUIREMENTS_SOURCE=core: not built yet. Until a Core version exists the app keeps using requirements.py and
says so once in the server log, so a wrong setting never empties the checklists.

The local source looks names up on requirements.py at call time, so tests that patch requirements.* still apply.
"""
import os

from . import requirements as _local


class LocalRequirements:
    """requirements.py: Wave 1 rows checked by staff, with official sources where we have one."""
    name = "local"

    # questions about one route
    def covers(self, category, country, vertical="food"):
        return _local.covers(category, country, vertical)

    def required(self, category, country, on_file_types, vertical="food"):
        return _local.required(category, country, on_file_types, vertical)

    def lane(self, category, country, vertical="food"):
        return _local.lane(category, country, vertical)

    # reference lists
    @property
    def products(self):
        return _local.PRODUCTS

    @property
    def destinations(self):
        return _local.DESTINATIONS

    @property
    def eu_destinations(self):
        return _local.EU_D

    # the rows and their official sources, for the weekly source watch
    @property
    def rows(self):
        return _local.ROWS

    @property
    def not_needed(self):
        return _local.NOT_NEEDED

    def watch_url(self, source):
        return _local.watch_url(source)

    def importer_only(self, row):
        return _local.importer_only(row)


_SOURCES = {"local": LocalRequirements}
_warned = False


def get():
    """The active requirements source."""
    global _warned
    want = (os.environ.get("REQUIREMENTS_SOURCE") or "local").strip().lower()
    if want not in _SOURCES:
        if not _warned:
            print("requirements source %r is not available yet: using requirements.py" % want, flush=True)
            _warned = True
        want = "local"
    return _SOURCES[want]()
