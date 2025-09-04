import re
import dateparser
from datetime import date


def extract_dates_and_leave_type(text: str):
    """Extract leave_type and (start_date, end_date) from free text using regex + dateparser."""
    lower = text.lower()

    # 1) leave type
    leave_type = None
    for key, norm in LEAVE_ALIASES.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            leave_type = norm
            break

    # 2) explicit yyyy-mm-dd
    iso_dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    start_date = end_date = None
    if len(iso_dates) == 1:
        start_date = end_date = dateparser.parse(iso_dates[0]).date()
    elif len(iso_dates) >= 2:
        start_date = dateparser.parse(iso_dates[0]).date()
        end_date = dateparser.parse(iso_dates[1]).date()

    # 3) natural ranges like "from next monday to wednesday"
    if start_date is None:
        m = re.search(r"from (.+?) to (.+)", lower)
        if m:
            s, e = m.groups()
            start_date = parse_natural_date(s)
            end_date = parse_natural_date(e)

    # 4) single natural like "tomorrow" (1 day leave)
    if start_date is None:
        for kw in ["today", "tomorrow", "next monday", "next tuesday", "next week"]:
            if kw in lower:
                sd = parse_natural_date(kw)
                if sd:
                    start_date = end_date = sd
                break

    return leave_type, start_date, end_date


def is_holiday(d: date, holidays_map: dict) -> bool:
    year = str(d.year)
    return str(d) in holidays_map.get(year, [])


def classify_intent_rough(text: str) -> str:
    """Very rough routing using keywords + sentiment model as fallback.
    Returns: one of {"check_balance", "apply_leave", "policy_query", "smalltalk"}
    """
    t = text.lower()
    if any(k in t for k in ["balance", "leave balance", "how many leaves", "remaining leaves"]):
        return "check_balance"
    if any(k in t for k in ["apply", "take leave", "request leave", "book leave"]):
        return "apply_leave"
    if any(k in t for k in ["policy", "maternity", "paternity", "casual leave policy"]):
        return "policy_query"

    # fallback sentiment to separate negative chatter
    label = intent_classifier(text)[0]['label']
    return "smalltalk_neg" if label == "NEGATIVE" else "smalltalk"
