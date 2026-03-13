#!/usr/bin/env python3
"""
Port grouping dictionary for dray lane normalization.
Maps individual terminals/cities to market-level port groups.

Usage:
    from port_groups import normalize_to_port_group, PORT_GROUPS, get_group_members
"""

# Each key is the display name; values are all known aliases/terminals/cities in that market
PORT_GROUPS = {
    "LA/LB": [
        "Los Angeles", "Long Beach", "San Pedro", "Compton", "Carson", "Wilmington",
        "APM, CA", "LBCT, CA", "WBCT, CA", "TTI, CA", "TraPac, CA",
        "Everport, CA", "PCT, CA", "SSA Marine, CA", "Total Terminals, CA",
        "ITS, CA", "Yusen Terminal, CA", "LA", "LALB", "LA/LB",
        "Long Beach CA", "Long Beach, CA", "Compton CA", "Wilmington, CA",
    ],
    "NY/NJ": [
        "APM, NJ", "APM Elizabeth, NJ", "Maher Terminal, NJ", "Port Newark, NJ",
        "NYCT, NY", "Port NY, NY", "Elizabeth, NJ", "Newark, NJ", "Bayonne, NJ",
        "APM Elizabeth", "Port Newark", "NY/NJ",
    ],
    "Savannah": [
        "Savannah, GA", "Garden City, GA", "Savannah", "Garden City",
        "GPA Savannah",
    ],
    "Charleston": [
        "N Charleston, SC", "Charleston, SC", "Charleston", "Wando",
    ],
    "Houston": [
        "Houston, TX", "Houston", "Bayport", "Barbours Cut",
        "Bayport Terminal",
    ],
    "NOLA": [
        "New Orleans, LA", "Napoleon, LA", "NOLA", "New Orleans",
        "Napoleon Ave", "Port of New Orleans",
    ],
    "Miami": [
        "Miami, FL", "SFCT, FL", "Miami", "South Florida Container",
    ],
    "Jacksonville": [
        "Jacksonville, FL", "JAXPORT, FL", "Jacksonville", "JAXPORT",
        "Blount Island",
    ],
    "Norfolk": [
        "Norfolk, VA", "Norfolk", "Virginia Port",
    ],
    "Baltimore": [
        "Baltimore, MD", "Baltimore",
    ],
    "Chicago Rail": [
        "BNSF Chicago, IL", "NS Chicago, IL", "Csx Chicago, IL",
        "Chicago", "Joliet", "Elwood", "Chicago (ORD)",
        "Chicago, IL",
    ],
    "Memphis Rail": [
        "BNSF Memphis", "BNSF - Memphis", "NS Memphis", "Memphis, TN",
        "Memphis",
    ],
    "Minneapolis Rail": [
        "BNSF, MN", "BSNF Minneapolis, MN", "CP, MN",
        "Minneapolis, MN", "Minneapolis",
    ],
    "Chattanooga Rail": [
        "NS Rossville, TN", "NS - Rossville, TN", "Rossville, TN",
        "Rossville",
    ],
    "Dallas Rail": [
        "Dallas Rail", "BNSF Dallas", "Dallas, TX", "Dallas",
    ],
    "Atlanta Rail": [
        "Atlanta, GA", "Atlanta", "NS Atlanta",
    ],
    "Detroit": [
        "Detroit, MI", "Detroit",
    ],
    "Laredo": [
        "Laredo, TX", "Laredo TX", "Laredo",
        "Laredo, TX (Bob Bullock)",
    ],
}

# Build reverse lookup: normalized city → group name
_REVERSE_MAP = {}
for group, members in PORT_GROUPS.items():
    for member in members:
        _REVERSE_MAP[member.lower().strip()] = group


def normalize_to_port_group(origin_or_dest):
    """
    Given an origin or destination string, return the port group name
    if it matches any known member. Otherwise return the original string.

    Case-insensitive, strips whitespace.
    """
    if not origin_or_dest:
        return origin_or_dest
    key = origin_or_dest.lower().strip()
    # Direct match
    if key in _REVERSE_MAP:
        return _REVERSE_MAP[key]
    # Partial match: check if any member is contained in the input
    for member_lower, group in _REVERSE_MAP.items():
        if member_lower in key or key in member_lower:
            return group
    return origin_or_dest


def get_group_members(group_name):
    """Return all members for a port group, or empty list if not found."""
    return PORT_GROUPS.get(group_name, [])


def get_all_groups():
    """Return list of all port group names."""
    return list(PORT_GROUPS.keys())


def is_port_or_rail(origin_or_dest):
    """Return True if the origin/dest matches a known port or rail terminal."""
    if not origin_or_dest:
        return False
    return origin_or_dest.lower().strip() in _REVERSE_MAP
