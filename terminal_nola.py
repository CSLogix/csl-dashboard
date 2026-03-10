"""
terminal_nola.py — Ports America Terminal Availability (NAP_NO + others)
API: https://twpapi.pachesapeake.com/api/track/GetContainers
- No auth required, public JSON endpoint
- Works for all PA terminals via siteId param
- Write results to Col K (Pickup) and Col N (Bot Notes)
"""
import requests
from datetime import datetime

API_URL = "https://twpapi.pachesapeake.com/api/track/GetContainers"
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.portsamerica.com/",
    "Origin": "https://www.portsamerica.com",
}

# siteId mapping for Ports America terminals
SITE_IDS = {
    "napoleon_nola":    "NAP_NO",
    "pnct_newark":      "PNCT_NJ",
    "seagirt_balt":     "SGT_BAL",
    # WBCT uses a separate backend - handled elsewhere
}


def get_terminal_status(container_numbers, site_id="NAP_NO", timeout=12):
    """
    Query PA terminal API for container availability.

    Args:
        container_numbers: list of container numbers (up to 10)
        site_id: Ports America terminal siteId (default NAP_NO = Napoleon NOLA)
        timeout: request timeout seconds

    Returns:
        dict: {container_number: parsed_status_dict}
              Returns empty dict on error.
    """
    if not container_numbers:
        return {}

    # API accepts comma-separated list; up to 10 per request
    key = ",".join(container_numbers[:10])
    today = datetime.today().strftime("%m/%d/%Y")

    try:
        r = requests.get(
            API_URL,
            params={"siteId": site_id, "key": key, "pickupDate": today},
            headers=HDRS,
            timeout=timeout,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
    except Exception:
        return {}

    results = {}
    for item in data:
        cnum = item.get("ContainerNumber", "").upper()
        if not cnum:
            continue

        # Availability
        avail_code = item.get("Available", 0)
        ready = (avail_code == 1)

        # Location/State
        location = item.get("Location") or item.get("State") or ""

        # Individual hold statuses
        customs = item.get("CustomReleaseStatus") or ""
        carrier = item.get("CarrierReleaseStatus") or ""
        usda    = item.get("UsdaStatus") or ""
        yard    = item.get("YardReleaseStatus") or ""
        misc    = item.get("MiscHoldStatus") or ""
        tmf     = item.get("TmfStatus") or ""
        misc_types = item.get("MiscHoldTypes") or []

        # Dates
        begin_delivery  = item.get("BeginDeliveryDate")  # when available for pickup
        last_free_date  = item.get("LastFreeDate")        # LFD (port free days)
        demurrage_end   = item.get("DemurrageEndDate")    # demurrage through
        demurrage_amt   = item.get("DemurrageAmount", 0.0) or 0.0

        # Vessel info
        vessel = item.get("VesselName") or ""
        voyage = item.get("VoyageNumber") or ""

        # Build hold summary for Bot Notes
        holds = []
        if carrier and carrier.upper() != "RELEASED":
            holds.append(f"Carrier:{carrier}")
        if customs and customs.upper() != "RELEASED":
            holds.append(f"Customs:{customs}")
        if usda:
            holds.append(f"USDA:{usda}")
        if misc or misc_types:
            tag = misc or ",".join(misc_types)
            holds.append(f"Misc:{tag}")
        if tmf:
            holds.append(f"TMF:{tmf}")
        if yard and yard.upper() != "RELEASED":
            holds.append(f"Yard:{yard}")
        if demurrage_amt > 0:
            holds.append(f"Demurrage:${demurrage_amt:.0f}")

        # Bot notes string
        if ready:
            note_parts = [f"AVAIL ✓"]
        else:
            note_parts = [f"Avail:NO"]
        if location:
            note_parts.append(f"Loc:{location}")
        if holds:
            note_parts.append("|".join(holds))
        if last_free_date:
            note_parts.append(f"LFD:{last_free_date}")
        if demurrage_end and demurrage_amt > 0:
            note_parts.append(f"Dem thru:{demurrage_end}")
        if vessel:
            note_parts.append(f"Vessel:{vessel} {voyage}".strip())

        bot_notes = " | ".join(note_parts)

        # Pickup date — only set when container is actually ready
        pickup_date = None
        if ready and begin_delivery:
            # Format as MM/DD if not already
            try:
                from datetime import datetime as dt
                d = dt.fromisoformat(begin_delivery.split("T")[0])
                pickup_date = d.strftime("%m/%d")
            except Exception:
                pickup_date = begin_delivery[:10]

        results[cnum] = {
            "ready": ready,
            "location": location,
            "holds": holds,
            "bot_notes": bot_notes,
            "pickup_date": pickup_date,
            "last_free_date": last_free_date,
            "vessel": vessel,
            "voyage": voyage,
            "demurrage_amount": demurrage_amt,
            "raw": {
                "customs": customs,
                "carrier": carrier,
                "misc": misc,
                "misc_types": misc_types,
                "tmf": tmf,
                "usda": usda,
            }
        }

    return results


def check_nola_containers(container_numbers):
    """Convenience wrapper for Napoleon NOLA terminal."""
    return get_terminal_status(container_numbers, site_id="NAP_NO")


def check_pnct_containers(container_numbers):
    """Convenience wrapper for PNCT Newark terminal."""
    return get_terminal_status(container_numbers, site_id="PNCT_NJ")


def check_seagirt_containers(container_numbers):
    """Convenience wrapper for Seagirt Baltimore terminal."""
    return get_terminal_status(container_numbers, site_id="SGT_BAL")


if __name__ == "__main__":
    # Quick test
    import json
    test = ["ECMU4761730", "ECMU7542382", "TCNU1107982", "TRHU8199990"]
    print("Testing NOLA containers...")
    r = check_nola_containers(test)
    for cnum, status in r.items():
        print(f"\n{cnum}:")
        print(f"  Ready:      {status['ready']}")
        print(f"  Location:   {status['location']}")
        print(f"  Holds:      {status['holds']}")
        print(f"  Bot Notes:  {status['bot_notes']}")
        print(f"  Pickup:     {status['pickup_date']}")
        print(f"  LFD:        {status['last_free_date']}")
        print(f"  Vessel:     {status['vessel']} {status['voyage']}")
