# Tolead + Boviet All-Hub Column Fix — Mar 5, 2026

## Hub Column Maps (confirmed correct)

### ORD
| Idx | Header | Code Key |
|-----|--------|----------|
| 1 | LINE # | col_load_id |
| 2 | APT ID | col_appt_id (NEW) |
| 3 | APPT DATE & TIME | col_delivery (NEW) |
| 4 | Date | col_date |
| 5 | Time | col_time |
| 6 | Pickup Address | col_origin (shorten) |
| 7 | Destination | col_dest (shorten) |
| 8 | Loads | col_loads (NEW) |
| 9 | Status | col_status |
| 15 | Tracking | col_efj |
| 16 | Trailer # | col_trailer |
| 17 | Driver Contact | col_phone (NEW) |

Start row: 790. Needs to Cover: status="New".

### JFK
| Idx | Header | Code Key |
|-----|--------|----------|
| 0 | LINE # | col_load_id |
| 3 | Date | col_date |
| 4 | Time | col_time |
| 5 | Delivery Date | col_delivery (NEW) |
| 6 | Pickup Address | col_origin |
| 7 | Destination | col_dest |
| 9 | Status | col_status |
| 14 | Tracking | col_efj |
| 15 | Trailer # | col_trailer |
| 16 | Driver Phone | col_phone (NEW) |

Start row: 184. Default origin: "Garden City, NY". Needs to Cover: status="New".

### LAX (3 cols were WRONG, now fixed)
| Idx | Header | Code Key | Was |
|-----|--------|----------|-----|
| 0 | EFJ Pro # | col_efj | OK |
| 3 | Load ID | col_load_id | OK |
| 4 | Date | col_date | OK |
| 5 | Time | col_time | OK |
| 6 | Pickup Location | col_origin | was None |
| 7 | Destination | col_dest | was 6 |
| 8 | Delivery Date/Time | col_delivery | NEW |
| 9 | Status | col_status | was 8 |
| 11 | Trailer # | col_trailer | was 10 |
| 12 | Driver Phone | col_phone | NEW |

Start row: 755. Default origin: "Vernon, CA". Needs to Cover: status="Unassigned".

### DFW (already correct, unchanged)
Start row: 172. Needs to Cover: col_loads_j logic (E+J columns).

### Boviet Piedra (3 cols were WRONG in boviet_monitor.py + app.py)
| Idx | Header | Code Key | Was |
|-----|--------|----------|-----|
| 0 | EFJ Pro # | efj_col | OK |
| 2 | Load ID | load_id_col | OK |
| 6 | Pickup Date/Time | pickup_col | was 5 |
| 7 | Delivery Date/Time | delivery_col | was 6 |
| 8 | Status | status_col | was 7 |
| 11 | Driver Phone# | phone_col | NEW |
| 12 | Trailer# | trailer_col | NEW |

Default origin: "Greenville, NC". Default dest: "Mexia, TX". Start row: 45.

### Boviet Hanson (cols were OK, added phone/trailer)
| Idx | Header | Code Key |
|-----|--------|----------|
| 0 | EFJ Pro# | efj_col |
| 1 | Load ID | load_id_col |
| 4 | Pickup Date/Time | pickup_col (NEW) |
| 5 | Del Date/Time | delivery_col (NEW) |
| 6 | Status | status_col |
| 8 | Driver Phone# | phone_col (NEW) |
| 10 | Trailer# | trailer_col (NEW) |

## Patches Applied (in order)
1. `patch_tolead_hubs_v3.py` — tolead_monitor.py: ORD/JFK/LAX configs + generalized POD reminder
2. `patch_app_all_hubs.py` — app.py: all hub cols + _shorten_address + Boviet fixes (3 of 11 failed)
3. `patch_app_fix_broken.py` — app.py: fixed broken _shorten_address insertion + legacy ORD block + hub status block
4. `patch_daily_summary_hubs.py` — daily_summary.py: ORD/JFK/LAX configs + generalized Needs to Cover
5. `patch_boviet_pod.py` — boviet_monitor.py: Piedra col fixes + phone/trailer + POD reminder
6. `patch_boviet_to_process.py` — boviet_monitor.py: fixed to_process.append format mismatch
7. `patch_ftl_pod.py` — ftl_monitor.py: POD reminder email after Need POD auto-status
8. `patch_skip_statuses_universal.py` — 3 files: case-insensitive status checks (14 fixes)
9. `patch_start_rows.py` — 3 files: start_row offsets for all hubs
10. `patch_fix_app_startrow.py` — app.py: fixed for loop indentation (dropped out of try block)
11. `patch_piedra_start_row.py` — 3 files: Piedra start_row=45 (boviet_monitor, app, daily_summary)

## Lessons Learned
- `str.replace()` replaces ALL occurrences — anchor strings must be unique (broke _shorten_address insertion)
- Indentation-sensitive patches need exact space counts — for loop at 12 spaces vs 16 breaks try/except
- `_send_email()` param order is `(to, subject, body)` — the old DFW POD reminder had it wrong, silently failing
- Always syntax-check after patching: `python3 -c 'import py_compile; ...'`
