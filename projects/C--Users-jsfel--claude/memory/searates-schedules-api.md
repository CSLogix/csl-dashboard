---
name: SeaRates Ship Schedules v2 API
description: OpenAPI spec reference for SeaRates Ship Schedules API — endpoints, auth, params, response shapes
type: reference
---

## SeaRates Ship Schedules API v2

**Base URL**: `https://schedules.searates.com/api/v2`
**Auth**: `X-API-KEY` header

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/schedules/by-points` | Schedules between two ports (origin/dest UN/LOCODEs) |
| GET | `/schedules/by-vessel` | Schedules for a specific vessel (by IMO) |
| GET | `/schedules/by-port` | All vessel calls at a port |
| GET | `/carriers` | List all carriers (filter by schedule_type, cargo_type) |
| GET | `/carriers/{scac}` | Carrier detail by SCAC |
| GET | `/vessels` | Search vessels by name/IMO/MMSI |
| GET | `/vessels/{imo}` | Vessel detail by IMO |
| GET | `/ports/{locode}` | Port detail by UN/LOCODE |
| GET | `/usage` | API usage stats (calls remaining, expiry) |

### Key Parameters — `/schedules/by-points`
- `origin` (required): UN/LOCODE (e.g. `USLAX`)
- `destination` (required): UN/LOCODE (e.g. `CNSHA`)
- `cargo_type` (required): `GC` | `REEF` | `RORO` | `LCL`
- `from_date` (required): `yyyy-mm-dd` (must be today or future)
- `weeks` (required): 1-6
- `sort` (required): `DEP` | `ARR` | `TT`
- `carriers` (optional): comma-separated SCACs (e.g. `MSCU,MAEU,COSU`)
- `direct_only` (optional): boolean
- `multimodal` (optional): boolean (default true)

### Response Shape — by-points
```
schedules[]: schedule_id, carrier_name, carrier_scac, cargo_type,
  origin{estimated_date, port_name, port_locode, terminal_name, terminal_code},
  destination{...same...},
  legs[]: order_id, mode (VESSEL/FEEDER/WATER/BARGE/LAND/TRUCK/RAIL/INTERMODAL),
    vessel_name, vessel_imo, voyages[], departure{}, arrival{},
    service_name, service_code
  cut_off_dates[]: name, date
  transit_time (days), direct (bool), updated_at
```

### Key Parameters — `/schedules/by-vessel`
- `imo` (required): vessel IMO number
- `carriers` (optional): comma-separated SCACs
- `voyages` (optional): comma-separated voyage numbers

### Response Shape — by-vessel
```
schedules[]: schedule_id, carrier_name, carrier_scac, vessel_name, vessel_imo,
  service_name, service_code, all_voyages[],
  calling_ports[]: order_id, voyages[], skip, estimated_dates{arrival/berth/departure},
    actual_dates{...}, port_name, port_locode, terminal_name, terminal_code, cut_off_dates[]
```

### Key Parameters — `/schedules/by-port`
- `locode` (required): UN/LOCODE
- `from_date` (required): `yyyy-mm-dd`
- `weeks` (required): 1-6
- `carriers` (optional): comma-separated SCACs

### Response Shape — by-port
```
schedules[]: schedule_id, carrier_name, carrier_scac, port_name, port_locode,
  all_voyages[],
  calling_vessels[]: order_id, voyages[], skip, estimated_dates{}, actual_dates{},
    vessel_name, vessel_imo, terminal_name, terminal_code, service_name, service_code, cut_off_dates[]
```

### Error Codes
`OK`, `WRONG_PARAMETERS`, `API_KEY_WRONG`, `API_KEY_ACCESS_DENIED`, `API_KEY_EXPIRED`, `API_KEY_LIMIT_REACHED`, `API_KEY_RATE_LIMIT`, `UNEXPECTED_ERROR`

### Carrier Response Stats
`SCHEDULES_FOUND`, `SCHEDULES_NOT_FOUND`, `PENDING`, `VOYAGE_REQUIRED`, `UNEXPECTED_ERROR`, `UNSUPPORTED_DIRECTION`, `UNSUPPORTED_VESSEL`, `UNSUPPORTED_CARRIER`, `UNSUPPORTED_SCHEDULE_TYPE`, `UNSUPPORTED_CARGO_TYPE`, `MAINTENANCE`, `CARRIER_MAINTENANCE`

### Integration Status
- Container tracking: ✅ INTEGRATED (`_searates_container_track()`)
- Ship Schedules v2: NOT YET INTEGRATED — API key stored in `.env` as `SEARATES_SCHEDULES_API_KEY` (TBD)
