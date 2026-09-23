"""Typed contracts for the flyibibo travel pipeline.

These schemas are the whole design. Because every agent shares one
model and one endpoint, the only things that distinguish an agent are
its prompt, its context slice, its tools, and *the schema it must
satisfy*. Get these right and any model works; get them wrong and no
model rescues the pipeline.

Every stage returns exactly one of these types, so the pipeline can
compose without a human reading prose in between.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class Interest(str, Enum):
    FOOD = "food"
    SHOPPING = "shopping"
    NIGHTLIFE = "nightlife"
    HISTORY = "history"
    NATURE = "nature"
    PHOTOGRAPHY = "photography"
    SPORTS = "sports"
    CULTURE = "culture"


class Diet(str, Enum):
    ANY = "any"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    HALAL = "halal"
    JAIN = "jain"
    GLUTEN_FREE = "gluten_free"


class Pace(str, Enum):
    RELAXED = "relaxed"
    BALANCED = "balanced"
    PACKED = "packed"


class SpendTier(str, Enum):
    SHOESTRING = "shoestring"
    MIDRANGE = "midrange"
    COMFORT = "comfort"
    LUXURY = "luxury"


class POICategory(str, Enum):
    LANDMARK = "landmark"
    MUSEUM = "museum"
    TEMPLE = "temple"
    PARK = "park"
    MARKET = "market"
    NEIGHBOURHOOD = "neighbourhood"
    VIEWPOINT = "viewpoint"
    EXPERIENCE = "experience"


class ItemKind(str, Enum):
    SIGHT = "sight"
    MEAL = "meal"
    TRANSIT = "transit"
    REST = "rest"
    ACTIVITY = "activity"


# --------------------------------------------------------------------------
# Intake
# --------------------------------------------------------------------------

class TripBrief(BaseModel):
    """The typed contract every downstream agent reads.

    Filled in two passes: the extractor populates whatever the raw
    prompt already states, then the clarify step asks ONLY for the
    remaining gaps. Never ask the user something you already know.
    """

    destination: str
    origin: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    nights: int | None = Field(default=None, ge=1, le=60)
    travellers: int = Field(default=1, ge=1, le=20)
    budget_total: float | None = Field(default=None, ge=0)
    currency: str = "INR"
    spend_tier: SpendTier = SpendTier.MIDRANGE
    diet: Diet = Diet.ANY
    interests: list[Interest] = Field(default_factory=list)
    pace: Pace = Pace.BALANCED
    must_see: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    notes: str | None = None

    def missing_slots(self) -> list[str]:
        """Slots the extractor could not fill from the raw prompt.

        Drives the clarify form. Deliberately excludes anything with a
        sane default (travellers, currency, pace, diet) so the form stays
        short - a twelve-question form loses the user.
        """
        gaps: list[str] = []
        if not self.destination:
            gaps.append("destination")
        if not self.nights and not (self.start_date and self.end_date):
            gaps.append("duration")
        if self.budget_total is None:
            gaps.append("budget")
        if not self.interests:
            gaps.append("interests")
        return gaps


# --------------------------------------------------------------------------
# Flights
# --------------------------------------------------------------------------

class FlightOption(BaseModel):
    airline: str
    flight_no: str | None = None
    origin: str
    destination: str
    depart: str = Field(description="ISO 8601 local time")
    arrive: str = Field(description="ISO 8601 local time")
    duration_min: int = Field(ge=0)
    stops: int = Field(default=0, ge=0)
    price: float = Field(ge=0)
    currency: str = "INR"
    booking_url: str | None = None
    is_red_eye: bool = False

    @property
    def duration_label(self) -> str:
        h, m = divmod(self.duration_min, 60)
        return f"{h}h {m:02d}m"

    @property
    def stops_label(self) -> str:
        return "non-stop" if self.stops == 0 else f"{self.stops} stop" + ("s" if self.stops > 1 else "")


class FlightResult(BaseModel):
    options: list[FlightOption] = Field(default_factory=list)
    provider: str = "mock"
    cheapest_price: float | None = None
    note: str | None = None

    def rank(self) -> list[FlightOption]:
        """Cheapest first, then fewest stops, then shortest."""
        return sorted(self.options, key=lambda f: (f.price, f.stops, f.duration_min))


# --------------------------------------------------------------------------
# Places
# --------------------------------------------------------------------------

class POI(BaseModel):
    """A point of interest.

    lat/lng are mandatory: the route optimizer clusters by district so
    that each day stays in one area, and that clustering needs real
    coordinates. closed_days is mandatory for the same reason - a day
    plan that sends you to a museum on its closing day is worse than no
    plan at all.
    """

    name: str
    category: POICategory
    district: str | None = None
    lat: float
    lng: float
    why: str = Field(description="One sentence on why it earns a slot")
    suggested_minutes: int = Field(default=90, ge=15, le=600)
    best_time: Literal["morning", "afternoon", "evening", "any"] = "any"
    closed_days: list[str] = Field(default_factory=list)
    indoor: bool = False
    photo_url: str | None = None
    source_url: str | None = None


class Restaurant(BaseModel):
    name: str
    cuisine: str
    district: str | None = None
    lat: float
    lng: float
    price_level: int = Field(default=2, ge=1, le=4)
    diet_ok: list[Diet] = Field(default_factory=list)
    signature: str | None = Field(default=None, description="What to actually order")
    photo_url: str | None = None
    source_url: str | None = None


class Hotel(BaseModel):
    name: str
    area: str
    lat: float | None = None
    lng: float | None = None
    price_per_night: float
    currency: str = "INR"
    rating: float | None = Field(default=None, ge=0, le=10)
    why: str
    photo_url: str | None = None
    booking_url: str | None = None


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

class DayItem(BaseModel):
    time: str = Field(description="24h local, e.g. '09:30'")
    kind: ItemKind
    title: str
    ref_name: str | None = Field(default=None, description="Name of the POI/Restaurant this maps to")
    minutes: int = Field(default=90, ge=0)
    note: str | None = None
    transit_from_previous: str | None = Field(
        default=None, description="e.g. '12 min metro, ~40 rupees'"
    )


class DayPlan(BaseModel):
    day_index: int = Field(ge=1)
    date: date | None = None
    theme: str = Field(description="Short label, e.g. 'Old town on foot'")
    district: str | None = None
    items: list[DayItem] = Field(default_factory=list)

    @property
    def total_minutes(self) -> int:
        return sum(i.minutes for i in self.items)


class BudgetLine(BaseModel):
    category: str
    low: float = Field(ge=0)
    high: float = Field(ge=0)
    note: str | None = None


class BudgetBreakdown(BaseModel):
    currency: str = "INR"
    lines: list[BudgetLine] = Field(default_factory=list)
    total_low: float = 0.0
    total_high: float = 0.0
    within_budget: bool | None = None
    verdict: str | None = None


class Itinerary(BaseModel):
    """What the synthesizer emits and the template renders.

    The LLM never writes HTML. It fills this structure; the template
    turns it into a page. That keeps output deterministic, makes styling
    a CSS edit rather than a re-roll, and means a truncated model
    response degrades one field instead of the whole page.
    """

    brief: TripBrief
    title: str = Field(description="Evocative page title, e.g. 'Five days in Kyoto, slowly'")
    subtitle: str | None = None
    pitch: str = Field(description="The hook paragraph - why this trip, why now")
    hero_image_url: str | None = None
    flights: FlightResult | None = None
    hotels: list[Hotel] = Field(default_factory=list)
    days: list[DayPlan] = Field(default_factory=list)
    budget: BudgetBreakdown | None = None
    packing: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    generated_at: str | None = None
