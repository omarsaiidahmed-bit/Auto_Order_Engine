"""Authoritative preparation and arrival schedules (Version 2.0.0).

The two schedules are deliberately independent:

* :data:`PREPARATION_SCHEDULE` -- the weekday on which each branch prepares
  its Auto Order.
* :data:`ARRIVAL_SCHEDULE` -- the weekday on which stock actually arrives at
  the branch.

They are **never merged**.  A preparation date is found first and the first
scheduled arrival *strictly after* it is used.  This matters for branches such
as ``كريم`` that prepare on four days but receive on only three; silently
attaching a preparation day to an arrival day would invent a cycle that the
business never issued.

``Friday`` has no preparation or arrival list.  A Friday reference date rolls
to the next scheduled day instead of being treated as a working day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable

__all__ = [
    "ARRIVAL_SCHEDULE",
    "AUTO_ORDER_CUTOFF_HOUR",
    "AUTO_ORDER_CUTOFF_WEEKDAY",
    "AUTO_ORDER_DELIVERY_WEEKDAY",
    "AUTO_ORDER_PREP_WEEKDAY",
    "BRANCH_ALIASES",
    "BRANCH_LABELS_EN",
    "BRANCH_OPTIONS",
    "BRANCH_SCHEDULE_WARNINGS",
    "KNOWN_UNSCHEDULED_BRANCHES",
    "PREPARATION_SCHEDULE",
    "SCHEDULE_WEEKDAYS",
    "ScheduleCycle",
    "ScheduleInfo",
    "canonical_branch",
    "compute_schedule_cycle",
    "get_branch_arrival_days",
    "get_branch_prep_days",
    "has_multiple_arrival_days",
    "has_multiple_prep_days",
    "next_arrival_date",
    "next_preparation_date",
    "normalize_branch_key",
    "schedule_for",
    "weekday_name",
]

SCHEDULE_WEEKDAYS: tuple[str, str, str, str, str, str] = (
    "السبت",
    "الأحد",
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
)

#: The known central Auto Order deadline.  It applies only to the workflow
#: whose preparation day is Wednesday and whose arrival day is Saturday.
AUTO_ORDER_PREP_WEEKDAY = "الأربعاء"
AUTO_ORDER_CUTOFF_WEEKDAY = "الخميس"
AUTO_ORDER_CUTOFF_HOUR = 14
AUTO_ORDER_DELIVERY_WEEKDAY = "السبت"

#: Authoritative preparation schedule, copied literally from the business
#: issue.  Do not derive it from the arrival schedule.
PREPARATION_SCHEDULE: dict[str, tuple[str, ...]] = {
    "السبت": (
        "العصافرة",
        "ميامي",
        "كريم",
        "جناكليس",
        "الملك حفني",
        "باكوس",
        "اسكوت",
        "سيدي بشر",
        "خالد ابن الوليد",
        "شعراوي",
        "محمد نجيب",
        "النقل والهندسة",
        "الإقبال",
        "المندرة",
        "السيوف",
        "زيزينيا",
        "سيدي جابر",
        "الأكاديمية",
    ),
    "الأحد": (
        "سموحة",
        "الدخيلة",
        "الكيلو واحد وعشرين",
        "العجمي",
        "بوابة 8",
        "الإبراهيمية",
        "العروبة",
        "فاروس",
        "البيطاش",
        "الهانوفيل",
        "كيروسيز",
        "علي ابن أبي طالب",
        "رشدي",
        "الوزان",
        "العامرية",
        "الوزارة",
        "المعسكر",
    ),
    "الاثنين": (
        "الجندي المجهول",
        "جليم",
        "كريم",
        "فلمنج",
        "فيكتوريا",
        "الأنبا تكلا",
        "الشاطبي",
        "بورسعيد",
        "المبرة",
        "محرم بك",
        "الكورنيش",
        "المرور",
        "محطة الرمل",
        "المشير",
        "بوالينو",
        "الرأس السوداء",
        "المنشية",
    ),
    "الثلاثاء": (
        "العصافرة",
        "ميامي",
        "كريم",
        "جناكليس",
        "الملك حفني",
        "باكوس",
        "اسكوت",
        "سيدي بشر",
        "خالد ابن الوليد",
        "شعراوي",
        "محمد نجيب",
        "النقل والهندسة",
        "الإقبال",
        "المندرة",
        "السيوف",
        "زيزينيا",
        "سيدي جابر",
        "الأكاديمية",
    ),
    "الأربعاء": (
        "كريم",
        "سموحة",
        "الدخيلة",
        "الكيلو واحد وعشرين",
        "العجمي",
        "بوابة 8",
        "الإبراهيمية",
        "العروبة",
        "فاروس",
        "البيطاش",
        "الهانوفيل",
        "كيروسيز",
        "علي ابن أبي طالب",
        "رشدي",
        "الوزان",
        "العامرية",
        "الوزارة",
        "المعسكر",
    ),
    "الخميس": (
        "الجندي المجهول",
        "جليم",
        "كريم",
        "فلمنج",
        "فيكتوريا",
        "الأنبا تكلا",
        "الشاطبي",
        "بورسعيد",
        "المبرة",
        "محرم بك",
        "الكورنيش",
        "المرور",
        "محطة الرمل",
        "المشير",
        "بوالينو",
        "الرأس السوداء",
        "المنشية",
    ),
}

#: Authoritative arrival schedule, copied literally from the business issue.
ARRIVAL_SCHEDULE: dict[str, tuple[str, ...]] = {
    "السبت": (
        "البيطاش",
        "العروبة",
        "الدخيلة",
        "الهانوفيل",
        "الوزارة",
        "الإبراهيمية",
        "الوزان",
        "العجمي",
        "المعسكر",
        "الكيلو واحد وعشرين",
        "كيروسيز",
        "رشدي",
        "سموحة",
        "فاروس",
        "بوابة 8",
        "علي ابن أبي طالب",
        "العامرية",
    ),
    "الأحد": (
        "كريم",
        "فلمنج",
        "فيكتوريا",
        "المنشية",
        "بورسعيد",
        "المرور",
        "محرم بك",
        "الأنبا تكلا",
        "المشير",
        "جليم",
        "الجندي المجهول",
        "الكورنيش",
        "المبرة",
        "محطة الرمل",
        "بوالينو",
        "الرأس السوداء",
        "الشاطبي",
    ),
    "الاثنين": (
        "خالد ابن الوليد",
        "اسكوت",
        "العصافرة",
        "باكوس",
        "سيدي بشر",
        "النقل والهندسة",
        "الإقبال",
        "جناكليس",
        "ميامي",
        "سيدي جابر",
        "السيوف",
        "المندرة",
        "زيزينيا",
        "الملك حفني",
        "محمد نجيب",
        "الأكاديمية",
        "شعراوي",
    ),
    "الثلاثاء": (
        "كريم",
        "البيطاش",
        "العروبة",
        "الدخيلة",
        "الهانوفيل",
        "الوزارة",
        "الإبراهيمية",
        "الوزان",
        "العجمي",
        "المعسكر",
        "الكيلو واحد وعشرين",
        "كيروسيز",
        "رشدي",
        "سموحة",
        "فاروس",
        "بوابة 8",
        "علي ابن أبي طالب",
        "العامرية",
    ),
    "الأربعاء": (
        "فلمنج",
        "فيكتوريا",
        "المنشية",
        "بورسعيد",
        "المرور",
        "محرم بك",
        "الأنبا تكلا",
        "المشير",
        "جليم",
        "الجندي المجهول",
        "الكورنيش",
        "المبرة",
        "محطة الرمل",
        "بوالينو",
        "الرأس السوداء",
        "الشاطبي",
    ),
    "الخميس": (
        "كريم",
        "خالد ابن الوليد",
        "اسكوت",
        "العصافرة",
        "باكوس",
        "سيدي بشر",
        "النقل والهندسة",
        "الإقبال",
        "جناكليس",
        "ميامي",
        "سيدي جابر",
        "السيوف",
        "المندرة",
        "زيزينيا",
        "الملك حفني",
        "محمد نجيب",
        "الأكاديمية",
        "شعراوي",
    ),
}

#: Canonical English labels for every scheduled branch.
BRANCH_LABELS_EN: dict[str, str] = {
    "العصافرة": "Al-Asafra",
    "ميامي": "Miami",
    "كريم": "Karim",
    "جناكليس": "Gnaklees",
    "الملك حفني": "El-Malek Hefni",
    "باكوس": "Bakous",
    "اسكوت": "Escot",
    "سيدي بشر": "Sidi Bishr",
    "خالد ابن الوليد": "Khaled Ibn Al-Waleed",
    "شعراوي": "Shaarawy",
    "محمد نجيب": "Mohamed Naguib",
    "النقل والهندسة": "Transport and Engineering",
    "الإقبال": "El-Iqbal",
    "المندرة": "Mandara",
    "السيوف": "El-Seyouf",
    "زيزينيا": "Zezenia",
    "سيدي جابر": "Sidi Gaber",
    "الأكاديمية": "Academy",
    "سموحة": "Smouha",
    "الدخيلة": "Dekheila",
    "الكيلو واحد وعشرين": "El-Kilo 21",
    "العجمي": "Agami",
    "بوابة 8": "Gate 8",
    "الإبراهيمية": "Ibrahimia",
    "العروبة": "Orouba",
    "فاروس": "Pharos",
    "البيطاش": "Bitash",
    "الهانوفيل": "Hanoville",
    "كيروسيز": "Kerosiz",
    "علي ابن أبي طالب": "Ali Ibn Abi Talib",
    "رشدي": "Roshdy",
    "الوزان": "El-Wazzan",
    "العامرية": "El-Amreya",
    "الوزارة": "Ministry",
    "المعسكر": "Camp",
    "الجندي المجهول": "Unknown Soldier",
    "جليم": "Gleem",
    "فلمنج": "Fleming",
    "فيكتوريا": "Victoria",
    "الأنبا تكلا": "Enbatakla",
    "الشاطبي": "Shatby",
    "بورسعيد": "Port Said",
    "المبرة": "Mabaret",
    "محرم بك": "Moharram Bek",
    "الكورنيش": "Corniche",
    "المرور": "Traffic",
    "محطة الرمل": "Raml Station",
    "المشير": "Marshal",
    "بوالينو": "Boalino",
    "الرأس السوداء": "Ras El-Soda",
    "المنشية": "Mansheya",
}

#: Branches observed in real exports that are not part of the issued
#: schedules.  They are reported, not silently mapped to a similar name.
KNOWN_UNSCHEDULED_BRANCHES: tuple[str, ...] = ("المعرض",)

#: Compatibility aliases for spellings observed in the ERP and the historical
#: panel.  The value must always be one of the canonical schedule names.
BRANCH_ALIASES: dict[str, str] = {
    "الملف حفني": "الملك حفني",
    "ملك حفني": "الملك حفني",
    "خالد بن الوليد": "خالد ابن الوليد",
    "ابن الوليد": "خالد ابن الوليد",
    "واحد وعشرين": "الكيلو واحد وعشرين",
    "الواحد وعشرين": "الكيلو واحد وعشرين",
    "الكيلو 21": "الكيلو واحد وعشرين",
    "كيلو 21": "الكيلو واحد وعشرين",
    "الكيلو واحد و عشرين": "الكيلو واحد وعشرين",
    "انباتكلا": "الأنبا تكلا",
    "الانباتكلا": "الأنبا تكلا",
    "الأنباتاكلا": "الأنبا تكلا",
    "الانبا تكلا": "الأنبا تكلا",
    "جانكليس": "جناكليس",
    "مراقيا": "العامرية",
    "يوبانيو": "بوالينو",
    "سيدى بشر": "سيدي بشر",
    "سيدى جابر": "سيدي جابر",
    "محطه الرمل": "محطة الرمل",
    "علي ابن ابي طالب": "علي ابن أبي طالب",
    "على ابن ابي طالب": "علي ابن أبي طالب",
    "النقل والهندسه": "النقل والهندسة",
    "الابراهيميه": "الإبراهيمية",
    "العروبه": "العروبة",
    "الدخيله": "الدخيلة",
    "المندره": "المندرة",
    "المنشيه": "المنشية",
    "الاقبال": "الإقبال",
    "الملك حفنى": "الملك حفني",
    "الملف حفنى": "الملك حفني",
}


def normalize_branch_key(value: object) -> str:
    """Return a comparison key for an Arabic branch name.

    The key removes whitespace and normalises Arabic letter variants, but it
    deliberately does **not** remove a leading ``ال``: that would merge
    genuinely different names in a few edge cases.
    """
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return ""
    translation = str.maketrans(
        {
            "إ": "ا",
            "أ": "ا",
            "آ": "ا",
            "ى": "ي",
            "ئ": "ي",
            "ؤ": "و",
            "ة": "ه",
        }
    )
    text = text.translate(translation)
    return "".join(
        character
        for character in text
        if not character.isspace() and character not in "-_./,()[]{}'\""
    )


_ALIAS_BY_KEY: dict[str, str] = {}
for _alias, _canonical in BRANCH_ALIASES.items():
    if _canonical not in BRANCH_LABELS_EN:
        raise RuntimeError(f"Alias target is not a scheduled branch: {_canonical!r}")
    _ALIAS_BY_KEY[normalize_branch_key(_alias)] = _canonical

_CANONICAL_BY_KEY: dict[str, str] = {
    normalize_branch_key(branch): branch for branch in BRANCH_LABELS_EN
}


def canonical_branch(value: object) -> str:
    """Return the canonical schedule name for ``value``.

    Unknown names are returned stripped and unchanged.  This is intentional:
    a typo must be visible to the caller instead of being silently attached to
    the closest branch.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    key = normalize_branch_key(text)
    return _CANONICAL_BY_KEY.get(key) or _ALIAS_BY_KEY.get(key, text)


def _weekday_index(day: str) -> int:
    """Return the schedule index of an Arabic weekday (Saturday = 0)."""
    canonical = canonical_branch(day)
    if canonical in SCHEDULE_WEEKDAYS:
        return SCHEDULE_WEEKDAYS.index(canonical)
    if canonical == "الجمعة":
        return 6
    # The schedule day names are not branch aliases; canonical_branch leaves
    # them untouched, so this fallback only runs for malformed input.
    try:
        return SCHEDULE_WEEKDAYS.index(day.strip())
    except ValueError as error:
        raise ValueError(f"Unknown weekday: {day!r}") from error


def weekday_name(value: date | datetime) -> str:
    """Return the Arabic schedule weekday of a date."""
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        raise ValueError("A valid calendar date is required.")
    # Python: Monday=0 ... Sunday=6; schedule: Saturday=0 ... Thursday=5,
    # Friday=6.
    offset = (value.weekday() + 2) % 7
    if offset == 6:
        return "الجمعة"
    return SCHEDULE_WEEKDAYS[offset]


def _next_weekday(on_or_after: date, weekday: str) -> date:
    target = _weekday_index(weekday)
    if target == 6:
        raise ValueError("Friday is not a scheduled preparation or arrival day.")
    # Convert the schedule index (Saturday=0) to Python's weekday index
    # (Monday=0): Saturday -> 5, Sunday -> 6, Monday -> 0, ...
    python_target = (target + 5) % 7
    delta = (python_target - on_or_after.weekday()) % 7
    candidate = on_or_after + timedelta(days=delta)
    for _ in range(8):
        if candidate.weekday() == python_target:
            return candidate
        candidate += timedelta(days=1)
    raise ValueError(f"Could not find the next {weekday!r}.")


def _days_for(branch: str, schedule: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    canonical = canonical_branch(branch)
    return tuple(
        day for day in SCHEDULE_WEEKDAYS if canonical in schedule.get(day, ())
    )


def get_branch_prep_days(branch: str) -> list[str]:
    """Return the canonical preparation weekdays of ``branch``."""
    return list(_days_for(branch, PREPARATION_SCHEDULE))


def get_branch_arrival_days(branch: str) -> list[str]:
    """Return the canonical arrival weekdays of ``branch``."""
    return list(_days_for(branch, ARRIVAL_SCHEDULE))


def has_multiple_prep_days(branch: str) -> bool:
    return len(get_branch_prep_days(branch)) > 1


def has_multiple_arrival_days(branch: str) -> bool:
    return len(get_branch_arrival_days(branch)) > 1


def next_preparation_date(branch: str, on_or_after: date) -> date | None:
    """Return the first preparation date on or after ``on_or_after``."""
    days = get_branch_prep_days(branch)
    if not days:
        return None
    return min(_next_weekday(on_or_after, day) for day in days)


def next_arrival_date(
    branch: str,
    after: date,
    *,
    inclusive: bool = False,
) -> date | None:
    """Return the first scheduled arrival after ``after``.

    ``inclusive=False`` is the default because an arrival on the preparation
    date is not a completed preparation-to-arrival cycle.  If the only
    scheduled day is the same weekday, the function rolls to the next week
    rather than returning a zero-day lead time.
    """
    days = get_branch_arrival_days(branch)
    if not days:
        return None
    candidates = []
    for day in days:
        candidate = _next_weekday(after, day)
        if not inclusive and candidate <= after:
            candidate += timedelta(days=7)
        candidates.append(candidate)
    return min(candidates)


@dataclass(frozen=True)
class ScheduleInfo:
    """The immutable schedule description of one branch."""

    branch: str
    prep_days: tuple[str, ...]
    arrival_days: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def multiple_prep_days(self) -> bool:
        return len(self.prep_days) > 1

    @property
    def multiple_arrival_days(self) -> bool:
        return len(self.arrival_days) > 1


#: Business warnings that cannot be inferred from the counts alone.
BRANCH_SCHEDULE_WARNINGS: dict[str, tuple[str, ...]] = {
    "كريم": (
        "الوصف السابق قال إن كريم يعمل ٣ مرات أسبوعياً، ثم ذكر ٤ أيام تجهيز "
        "و٣ أيام وصول. الجدول المعتمد نفسه يسرد كريم في تجهيز السبت "
        "والثلاثاء (تكرار قائمة السبت) والاثنين والأربعاء والخميس، أي ٥ أيام "
        "تجهيز، و٣ أيام وصول. لم يتم حذف يوم أو تعديل الجدول؛ التعارض ظاهر "
        "للمراجعة ويُستخدم أول وصول لاحق ليوم التجهيز.",
    ),
}


def schedule_for(branch: str) -> ScheduleInfo:
    """Return the schedule and every exposed inconsistency for ``branch``."""
    canonical = canonical_branch(branch)
    prep = tuple(get_branch_prep_days(canonical))
    arrival = tuple(get_branch_arrival_days(canonical))
    warnings: list[str] = list(BRANCH_SCHEDULE_WARNINGS.get(canonical, ()))
    if prep and arrival and len(prep) != len(arrival):
        warnings.append(
            f"{canonical}: {len(prep)} أيام تجهيز مقابل {len(arrival)} أيام "
            "وصول. الجدولان مستقلان؛ لا يتم دمج اليوم غير المقابل."
        )
    if not prep:
        warnings.append(f"{canonical}: لا يوجد يوم تجهيز معتمد.")
    if not arrival:
        warnings.append(f"{canonical}: لا يوجد يوم وصول معتمد.")
    return ScheduleInfo(
        branch=canonical,
        prep_days=prep,
        arrival_days=arrival,
        warnings=tuple(dict.fromkeys(warnings)),
    )


@dataclass(frozen=True)
class ScheduleCycle:
    """A concrete preparation-to-arrival cycle for a reference date."""

    branch: str
    reference_date: date
    reference_weekday: str
    preparation_date: date | None
    preparation_weekday: str
    arrival_date: date | None
    arrival_weekday: str
    prep_to_arrival_days: int | None
    processing_to_arrival_days: int | None
    cutoff_datetime: datetime | None
    auto_order_applicable: bool
    schedule: ScheduleInfo
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lead_time(self) -> int:
        if self.processing_to_arrival_days is None:
            raise ValueError(
                f"No schedule is available for branch {self.branch!r}; "
                "lead time cannot be derived."
            )
        return self.processing_to_arrival_days

    @property
    def prep_weekday(self) -> str:
        return self.preparation_weekday

    @property
    def delivery_weekday(self) -> str:
        return self.arrival_weekday

    @property
    def delivery_date(self) -> date:
        if self.arrival_date is None:
            raise ValueError(f"No arrival date for branch {self.branch!r}.")
        return self.arrival_date

    @property
    def days_ahead(self) -> int:
        return self.lead_time

    @property
    def friday_buffer(self) -> bool:
        # Retained only for backwards-compatible UI fields.  The new lead time
        # is derived from the schedule and no longer adds a fixed Friday day.
        return False


def _auto_order_cutoff(preparation_date: date) -> datetime | None:
    """Return the next Thursday 14:00 after a Wednesday preparation."""
    if weekday_name(preparation_date) != AUTO_ORDER_PREP_WEEKDAY:
        return None
    cutoff_date = _next_weekday(preparation_date, AUTO_ORDER_CUTOFF_WEEKDAY)
    return datetime.combine(cutoff_date, time(AUTO_ORDER_CUTOFF_HOUR, 0))


def compute_schedule_cycle(branch: str, reference_date: date) -> ScheduleCycle:
    """Compute the next preparation and arrival for ``branch``.

    The result exposes every intermediate date.  In particular
    ``prep_to_arrival_days`` is the schedule gap and
    ``processing_to_arrival_days`` is the lead time measured from the date the
    order is placed.
    """
    if not isinstance(reference_date, date):
        raise ValueError("Select a valid order date.")
    info = schedule_for(branch)
    prep_date = next_preparation_date(info.branch, reference_date)
    arrival_date = (
        next_arrival_date(info.branch, prep_date) if prep_date is not None else None
    )
    prep_weekday = weekday_name(prep_date) if prep_date is not None else ""
    arrival_weekday = weekday_name(arrival_date) if arrival_date is not None else ""
    prep_to_arrival = (
        (arrival_date - prep_date).days
        if prep_date is not None and arrival_date is not None
        else None
    )
    processing_to_arrival = (
        (arrival_date - reference_date).days if arrival_date is not None else None
    )
    cutoff = _auto_order_cutoff(prep_date) if prep_date is not None else None
    applicable = bool(
        cutoff is not None
        and arrival_weekday == AUTO_ORDER_DELIVERY_WEEKDAY
        and prep_weekday == AUTO_ORDER_PREP_WEEKDAY
    )
    warnings = list(info.warnings)
    if reference_date.weekday() == 4:  # Friday
        warnings.append(
            "تاريخ الطلب يوم جمعة؛ لا يوجد تجهيز أو وصول معتمد يوم الجمعة، "
            "لذلك تم الانتقال إلى أول يوم مجدول."
        )
    if prep_date is not None and arrival_date is not None and prep_to_arrival == 0:
        warnings.append(
            "دورة تجهيز ووصول في نفس اليوم؛ لم يتم اختراع يوم وسيط وتم "
            "استخدام أول وصول لاحق."
        )
    if applicable:
        warnings.append(
            "دورة Auto Order المطبقة: تجهيز الأربعاء، تعديل المدير حتى "
            "الخميس ٢ ظهراً، إغلاق الخميس ٢ ظهراً، ووصول السبت."
        )
    return ScheduleCycle(
        branch=info.branch,
        reference_date=reference_date,
        reference_weekday=weekday_name(reference_date),
        preparation_date=prep_date,
        preparation_weekday=prep_weekday,
        arrival_date=arrival_date,
        arrival_weekday=arrival_weekday,
        prep_to_arrival_days=prep_to_arrival,
        processing_to_arrival_days=processing_to_arrival,
        cutoff_datetime=cutoff,
        auto_order_applicable=applicable,
        schedule=info,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _build_branch_options() -> list[str]:
    """Return canonical scheduled branches in schedule order."""
    options: dict[str, None] = {}
    for schedule in (PREPARATION_SCHEDULE, ARRIVAL_SCHEDULE):
        for day in SCHEDULE_WEEKDAYS:
            for branch in schedule[day]:
                options.setdefault(branch, None)
    return list(options)


BRANCH_OPTIONS: list[str] = _build_branch_options()
