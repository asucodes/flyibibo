"""Flight lookup behind a provider interface.

Why an interface: the prototype ships a mock so the pipeline is
offline-safe and you don't burn a paid quota while iterating on CSS.
Swapping to live data is an env change (FLIGHT_PROVIDER=serpapi), not a
code change.

Why a seeded generator instead of a static fixture file: a fixture only
covers the routes someone remembered to write down. A generator seeded
by the route itself produces stable, plausible results for any
destination - and stable matters, because a demo where the flights
change every refresh looks broken.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
from datetime import datetime, timedelta
from typing import Protocol

from travel.schemas import FlightOption, FlightResult, SpendTier

# --------------------------------------------------------------------------
# Small reference data
# --------------------------------------------------------------------------

# IATA codes for common origins/destinations. Extend freely - an unknown
# city falls back to a derived three-letter code.
AIRPORTS: dict[str, tuple[str, float, float]] = {
    "delhi": ("DEL", 28.5562, 77.1000),
    "new delhi": ("DEL", 28.5562, 77.1000),
    "mumbai": ("BOM", 19.0896, 72.8656),
    "bengaluru": ("BLR", 13.1986, 77.7066),
    "bangalore": ("BLR", 13.1986, 77.7066),
    "chennai": ("MAA", 12.9941, 80.1709),
    "kolkata": ("CCU", 22.6547, 88.4467),
    "hyderabad": ("HYD", 17.2403, 78.4294),
    "kanpur": ("KNU", 26.4410, 80.3645),
    "lucknow": ("LKO", 26.7606, 80.8893),
    "goa": ("GOI", 15.3808, 73.8314),
    "jaipur": ("JAI", 26.8242, 75.8122),
    "kochi": ("COK", 10.1520, 76.4019),
    "tokyo": ("NRT", 35.7720, 140.3929),
    "osaka": ("KIX", 34.4347, 135.2440),
    "kyoto": ("KIX", 34.4347, 135.2440),
    "seoul": ("ICN", 37.4602, 126.4407),
    "bangkok": ("BKK", 13.6900, 100.7501),
    "singapore": ("SIN", 1.3644, 103.9915),
    "kuala lumpur": ("KUL", 2.7456, 101.7099),
    "bali": ("DPS", -8.7482, 115.1672),
    "dubai": ("DXB", 25.2532, 55.3657),
    "doha": ("DOH", 25.2731, 51.6081),
    "istanbul": ("IST", 41.2753, 28.7519),
    "london": ("LHR", 51.4700, -0.4543),
    "paris": ("CDG", 49.0097, 2.5479),
    "amsterdam": ("AMS", 52.3105, 4.7683),
    "frankfurt": ("FRA", 50.0379, 8.5622),
    "rome": ("FCO", 41.8003, 12.2389),
    "barcelona": ("BCN", 41.2974, 2.0833),
    "zurich": ("ZRH", 47.4647, 8.5492),
    "reykjavik": ("KEF", 63.9850, -22.6056),
    "new york": ("JFK", 40.6413, -73.7781),
    "san francisco": ("SFO", 37.6213, -122.3790),
    "los angeles": ("LAX", 33.9416, -118.4085),
    "toronto": ("YYZ", 43.6777, -79.6248),
    "mexico city": ("MEX", 19.4361, -99.0719),
    "sao paulo": ("GRU", -23.4356, -46.4731),
    "cairo": ("CAI", 30.1219, 31.4056),
    "nairobi": ("NBO", -1.3192, 36.9278),
    "cape town": ("CPT", -33.9715, 18.6021),
    "sydney": ("SYD", -33.9399, 151.1753),
    "melbourne": ("MEL", -37.6690, 144.8410),
    "auckland": ("AKL", -37.0082, 174.7850),
    "colombo": ("CMB", 7.1808, 79.8841),
    "kathmandu": ("KTM", 27.6966, 85.3618),
    "tashkent": ("TAS", 41.2579, 69.2812),
    "almaty": ("ALA", 43.3521, 77.0405),
    "baku": ("GYD", 40.4675, 50.0467),
    "tbilisi": ("TBS", 41.6692, 44.9546),
}

CARRIERS: dict[str, list[str]] = {
    "IN": ["IndiGo", "Air India", "Vistara", "SpiceJet", "Akasa Air"],
    "GULF": ["Emirates", "Qatar Airways", "Etihad", "flydubai", "Oman Air"],
    "ASIA": ["Singapore Airlines", "Thai Airways", "ANA", "Korean Air", "Cathay Pacific"],
    "EU": ["Lufthansa", "Air France", "KLM", "British Airways", "Swiss"],
    "LCC": ["AirAsia", "Scoot", "VietJet", "ZipAir"],
}

CURRENCY_PER_KM: dict[str, float] = {
    "INR": 6.2,
    "USD": 0.075,
    "EUR": 0.068,
    "GBP": 0.058,
}

# Rough hub-and-spoke multiplier applied to great-circle distance, since
# real routings are not straight lines.
ROUTE_FACTOR = 1.18


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _resolve(city: str) -> tuple[str, float, float]:
    key = (city or "").strip().lower()
    if key in AIRPORTS:
        return AIRPORTS[key]
    digest = hashlib.sha1(key.encode()).hexdigest()
    code = "".join(c for c in key.upper() if c.isalpha())[:3] or "XXX"
    lat = (int(digest[:4], 16) % 12000) / 100.0 - 60.0
    lon = (int(digest[4:8], 16) % 35800) / 100.0 - 179.0
    return code, lat, lon


def _region(origin_code: str, dest_code: str) -> list[str]:
    if origin_code == dest_code:
        return CARRIERS["IN"]
    domestic = {o[0] for o in AIRPORTS.values()}
    if origin_code in domestic and dest_code in domestic:
        return CARRIERS["IN"]
    if dest_code in {"DXB", "DOH", "AUH", "MCT"} or origin_code in {"DXB", "DOH", "AUH", "MCT"}:
        return CARRIERS["GULF"]
    if dest_code in {"SIN", "BKK", "KIX", "NRT", "ICN", "HKG", "DPS", "KUL"}:
        return CARRIERS["ASIA"] + CARRIERS["LCC"]
    return CARRIERS["EU"]


# --------------------------------------------------------------------------
# Provider protocol
# --------------------------------------------------------------------------

class FlightProvider(Protocol):
    name: str

    def search(
        self,
        origin: str,
        destination: str,
        depart_date: str | None,
        travellers: int = 1,
        currency: str = "INR",
        spend_tier: SpendTier = SpendTier.MIDRANGE,
        max_results: int = 4,
    ) -> FlightResult: ...


# --------------------------------------------------------------------------
# Mock provider
# --------------------------------------------------------------------------

class MockFlightProvider:
    """Deterministic, plausible flights for any route.

    Seeded from (origin, destination, date) so the same query always
    returns the same options. No network, no key, no quota.
    """

    name = "mock"

    def search(
        self,
        origin: str,
        destination: str,
        depart_date: str | None = None,
        travellers: int = 1,
        currency: str = "INR",
        spend_tier: SpendTier = SpendTier.MIDRANGE,
        max_results: int = 4,
    ) -> FlightResult:
        o_code, o_lat, o_lon = _resolve(origin)
        d_code, d_lat, d_lon = _resolve(destination)
        km = _haversine_km(o_lat, o_lon, d_lat, d_lon) * ROUTE_FACTOR

        seed_src = f"{o_code}|{d_code}|{depart_date or 'unspecified'}"
        seed = int(hashlib.sha256(seed_src.encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)

        pool = _region(o_code, d_code)
        base_depart = self._parse_depart(depart_date, rng)
        per_km = CURRENCY_PER_KM.get(currency, CURRENCY_PER_KM["INR"])

        tier_mult = {
            SpendTier.SHOESTRING: 0.82,
            SpendTier.MIDRANGE: 1.0,
            SpendTier.COMFORT: 1.22,
            SpendTier.LUXURY: 1.75,
        }[spend_tier]

        options: list[FlightOption] = []
        for i in range(max_results):
            stops = 0 if km < 2500 and i % 2 == 0 else (1 if i % 3 else 2)
            stops = min(stops, 0 if km < 900 else 2)

            # Non-stop costs more; each stop adds time and shaves fare.
            speed = 780 + rng.randint(-40, 60)
            flight_min = int(km / speed * 60) + rng.randint(25, 55) + stops * rng.randint(55, 130)
            flight_min = max(flight_min, 45)

            # Distance has a sub-linear effect on fare: long-haul is not
            # linearly more expensive per km.
            fare = (km ** 0.86) * per_km * tier_mult
            fare *= 1.0 - stops * 0.09
            fare *= rng.uniform(0.86, 1.24)
            fare = max(round(fare / 10.0) * 10.0, 1200.0)

            depart = base_depart + timedelta(minutes=rng.randint(0, 15) * 30 + i * 95)
            arrive = depart + timedelta(minutes=flight_min)

            options.append(
                FlightOption(
                    airline=rng.choice(pool),
                    flight_no=f"{''.join(c for c in rng.choice(pool) if c.isupper())[:2] or 'FL'}{rng.randint(100, 989)}",
                    origin=o_code,
                    destination=d_code,
                    depart=depart.strftime("%Y-%m-%dT%H:%M"),
                    arrive=arrive.strftime("%Y-%m-%dT%H:%M"),
                    duration_min=flight_min,
                    stops=stops,
                    price=round(fare * travellers, 2),
                    currency=currency,
                    booking_url=(
                        "https://www.google.com/travel/flights?q="
                        f"Flights%20from%20{o_code}%20to%20{d_code}%20on%20"
                        f"{depart.strftime('%Y-%m-%d')}"
                    ),
                    is_red_eye=depart.hour >= 22 or depart.hour < 6,
                )
            )

        options.sort(key=lambda f: (f.price, f.stops, f.duration_min))
        return FlightResult(
            options=options,
            provider=self.name,
            cheapest_price=min((o.price for o in options), default=None),
            note=(
                f"Simulated fares for {o_code}->{d_code} (~{int(km)} km). "
                "Set FLIGHT_PROVIDER=serpapi for live pricing."
            ),
        )

    @staticmethod
    def _parse_depart(depart_date: str | None, rng: random.Random) -> datetime:
        if depart_date:
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%d-%m-%Y"):
                try:
                    return datetime.strptime(depart_date[: len(fmt) + 2].strip(), fmt)
                except ValueError:
                    continue
        return datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=rng.randint(21, 70))


# --------------------------------------------------------------------------
# Live provider (stub - flip FLIGHT_PROVIDER=serpapi to use)
# --------------------------------------------------------------------------

class SerpApiFlightProvider:
    """Live Google Flights results via SerpAPI.

    Left as a thin stub on purpose: the free tier is small, so it should
    only be exercised once the rest of the pipeline is stable. Implement
    `search` by calling the `google_flights` engine and mapping its
    `best_flights` / `other_flights` payload onto FlightOption.
    """

    name = "serpapi"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "SERPAPI_API_KEY is not set. Either add it to .env or use "
                "FLIGHT_PROVIDER=mock."
            )

    def search(self, *args, **kwargs) -> FlightResult:  # pragma: no cover - stub
        raise NotImplementedError(
            "SerpApiFlightProvider is a stub. Implement search() against "
            "https://serpapi.com/google-flights-api and map the response "
            "onto FlightOption. Until then use FLIGHT_PROVIDER=mock."
        )


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def get_flight_provider(name: str | None = None) -> FlightProvider:
    resolved = (name or os.environ.get("FLIGHT_PROVIDER") or "mock").strip().lower()
    if resolved == "serpapi":
        return SerpApiFlightProvider()
    return MockFlightProvider()
