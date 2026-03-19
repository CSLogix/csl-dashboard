---
name: Data-driven port groupings plan
description: User wants port/rail cluster groupings to be data-driven (DB table + admin UI) instead of hardcoded PORT_CLUSTERS dicts
type: project
---

User wants to make Rate IQ port cluster groupings data-driven so they don't have to keep sending examples of ports that should group together.

**Why:** PORT_CLUSTERS is currently hardcoded in both frontend (RateIQView.jsx) and backend (rate_iq.py). Every new port alias or rail ramp requires a code change + redeploy. User specifically asked "is there a way we can code port groupings and map out Rate IQ now so I don't have to keep sending examples?"

**How to apply:** Build a `port_groups` table in PostgreSQL with columns like (alias, cluster_name, type: port|rail). Add an admin UI in the dashboard for CRUD. Backend loads from DB instead of hardcoded dict. Frontend fetches clusters from an API endpoint. User offered to provide a port and rail list to seed the initial data — wait for that list before implementing.
