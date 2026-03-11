"""
Date format normalizer for CSL Bot.
Converts all date formats to MM-DD or MM-DD HH:MM (military time).
"""

import re
from datetime import datetime, timedelta

EXCEL_EPOCH = datetime(1899, 12, 30)


def clean_date(raw):
    """Normalize a date string to MM-DD or MM-DD HH:MM format.

    Returns None for empty/invalid input, normalized string otherwise.
    Midnight (00:00) is stripped to date-only.
    """
    if not raw:
        return None

    s = str(raw).strip()
    if not s or s.lower() in ('none', 'null', 'n/a', '-', '\u2014', ''):
        return None

    # Excel serial number (5-digit like 46101)
    if re.match(r'^\d{5}$', s):
        try:
            dt = EXCEL_EPOCH + timedelta(days=int(s))
            return dt.strftime('%m-%d')
        except Exception:
            pass

    # Try structured formats (most specific first)
    formats = [
        ('%m/%d/%Y %H:%M:%S', True),
        ('%m/%d/%Y %H:%M', True),
        ('%Y-%m-%d %H:%M:%S', True),
        ('%Y-%m-%d %H:%M', True),
        ('%m/%d/%y %H:%M', True),
        ('%m-%d %H:%M', True),
        ('%m/%d %H:%M', True),
        ('%m-%d %H:%M:%S', True),
        ('%m/%d %H:%M:%S', True),
        ('%m-%d %I:%M %p', True),
        ('%m/%d %I:%M %p', True),
        ('%m-%d %I:%M:%S %p', True),
        ('%m/%d/%Y', False),
        ('%Y-%m-%d', False),
        ('%m/%d/%y', False),
        ('%m/%d', False),
        ('%m-%d', False),
        ('%d-%b', False),
        ('%b-%d', False),
    ]

    for fmt, has_time in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if has_time:
                if dt.hour == 0 and dt.minute == 0:
                    return dt.strftime('%m-%d')
                return dt.strftime('%m-%d %H:%M')
            return dt.strftime('%m-%d')
        except ValueError:
            continue

    # Regex fallback: extract MM-DD and optional HH:MM
    m = re.match(r'(\d{1,2})[/\-](\d{1,2})', s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            time_m = re.search(r'(\d{1,2}):(\d{2})', s)
            if time_m:
                hour, minute = int(time_m.group(1)), int(time_m.group(2))
                if re.search(r'[Pp][Mm]', s):
                    if hour != 12:
                        hour += 12
                elif re.search(r'[Aa][Mm]', s):
                    if hour == 12:
                        hour = 0
                if hour == 0 and minute == 0:
                    return f'{month:02d}-{day:02d}'
                return f'{month:02d}-{day:02d} {hour:02d}:{minute:02d}'
            return f'{month:02d}-{day:02d}'

    return s  # Return raw if nothing worked
