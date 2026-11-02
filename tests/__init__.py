# Tests never call the live tariff services: an unreachable network is the default.
# Live behaviour is checked separately with: python -m vialibera.check_tariffs
from vialibera.adapters import tariff as _tariff
from vialibera.adapters.base import AdapterError as _AdapterError


def _offline(url, timeout=20):
    raise _AdapterError("unavailable", "network disabled in tests")


_tariff.http_get = _offline

# The VIES service is never called from tests either.
from vialibera import vat_check as _vat_check


def _vies_offline(url, timeout=8):
    raise OSError("network disabled in tests")


_vat_check._http = _vies_offline
