"""
Seed the ai_knowledge_base table with operational knowledge from Claude memory dump.
Run once after deployment: python3 seed_knowledge_base.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

import database as db
import config  # noqa: F401 — triggers dotenv load

ENTRIES = [
    # --- ACCOUNTS ---
    ("account_rule", "Boviet", "Boviet Solar: Contact is Ivy Yang. Located in Greenville, NC (1125 Sugg Parkway). Solar panel shipments. Facility has dock access — dock-to-dock moves, no liftgate needed. Panels are not stackable. International customer — always confirm weight in LBS and dims in inches (they provide KG and mm). Key lane: Greenville NC → RETC Fremont CA (box truck, ~$4,195). Running this lane since January 2026."),
    ("account_rule", "Boviet", "Boviet Solar: 26' box truck verified to fit 3 pallets dock-to-dock. RETC Fremont has dock + forklift + pallet jack on site. Do not book liftgate on this lane — confirmed unnecessary."),
    ("account_rule", "Tolead", "Tolead: Contact is Jacky Lim (jacky.lim@tolead.com, 718-304-6860). Hubs: LAX, DFW, ORD, JFK, and others. JFK is newest and most difficult hub. 2-year relationship at other hubs. JFK contact: jfkoperation@tolead.com. Senior contact: Jeffrey Zhang (jeffrey.zhang@tolead.com)."),
    ("account_rule", "Tolead", "Tolead KPI Requirements (JFK, effective immediately): Order confirmation within 1 hour of receipt or treated as declined. Driver info + ETA within 1 hour of acceptance. POD must be scanned and uploaded within 2 hours of delivery. Non-compliance = load goes to next available carrier."),
    ("account_rule", "Tolead", "Tolead: Joliet hub uses Cadence Global Logistics (carrier code V125821) frequently. Example load: EFJ106829, container CAIU7883017, 26,837 lbs / 429 pcs, base $475, drop fee $125 = $600 total. Lane: Joliet → Wood Dale."),
    ("account_rule", "DSV", "DSV: Contact is Patricia. Port Everglades (Florida) transload account. Uses MIFS as transload carrier. MIFS rates: $40/pallet in & out, $40/pallet/month storage pro-rated weekly ($10/pallet/week), first 3 days free. After 11 days = second week of storage kicks in. Example: 21 pallets, $1,050 carrier cost, $1,200 billed to DSV."),
    ("account_rule", "DSV", "DSV: DSV also has a Richburg SC → Wando Welch Terminal lane (dray/export). Fully documented as a case study with JSON tool schema and Postgres migration spec."),
    ("account_rule", "DHL", "DHL: Account contact is Beverly Bonelli. Key project: Rock & Roll Hall of Fame (CLT panels, Columbus transload, Cleveland delivery). Containers MAEU9169175 / 9173690 / 9228494 moved through this project. Always send detailed recap on complex moves."),
    ("account_rule", "Cadi", "Cadi Company: Contact is Ashley, Naugatuck CT → Laredo TX lane. DO NOT lock in long-term rates on this lane — Laredo is a dead-end for drivers (freight crosses into Mexico, minimal backhaul). Rate swings $500-$1,000+ between shipments. Always quote case-by-case. 5-stop delivery, non-stackable freight, CT is not a freight hub."),
    ("account_rule", "Cadi", "Cadi Company: FTZ/domestic BOL splits required. Multiple stops to Laredo. Confirm delivery orders before truck rolls — never leave without them. Rate on recent move: $4,500."),

    # --- LANE TIPS ---
    ("lane_tip", "Laredo TX", "Naugatuck CT → Laredo TX: Never lock in a long-term rate. Laredo = dead-end lane, carriers charge premium. Backhaul is nearly zero heading north out of Laredo. Typical rate volatility: $500-$1,000+ per shipment. Quote case-by-case only."),
    ("lane_tip", "Boviet", "Greenville NC → RETC Fremont CA (Boviet Solar): 26' box truck, dock-to-dock. RETC has dock + forklift. Boviet facility has dock. No liftgate. Confirmed rate range ~$4,195. Pallets may be long (95-101\") — confirm dims each run. Weight typically 5,000-6,000 lbs range."),
    ("lane_tip", None, "Novi MI → SeaTac WA (Conestoga flatbed): 2,346 miles, ~49K lbs legal, ~$2.40+ RPM. Quote $6,500-$7,000 per truck for Conestoga. If running two trucks simultaneously, price toward higher end to secure both. SeaTac/Pacific NW has decent outbound flatbed (lumber, steel, manufacturing) so backhaul is reasonable."),
    ("lane_tip", "DSV", "DSV Port Everglades transloads: First 3 days storage free, then $10/pallet/week pro-rated. Always confirm pallet count before quoting — this is what drives the math."),
    ("lane_tip", "Laredo TX", "Laredo TX lanes generally: Driver shortage + dead-end market. Always price a premium on Laredo destination. Never quote all-in on multi-week forward booking."),

    # --- RATE RULES ---
    ("rate_rule", None, "CSL quoting philosophy: Customers want freight quick, cheap, and done right — they only get two. Never apologize for pricing. When customer pushes back, reframe: which two do you want?"),
    ("rate_rule", None, "Fuel surcharge protocol: Benchmark is DOE/EIA Weekly National Average Diesel (eia.gov/petroleum/gasdiesel — updates every Monday). Only adjust rate if DOE moves more than $0.25/gal from baseline at time of quote. Applies both directions (increase AND decrease). Normal weekly fluctuations do not trigger adjustment."),
    ("rate_rule", None, "During high fuel volatility (e.g., diesel above $4.50): Never quote all-in flat rates for shipments more than a week out. Quote base linehaul + floating FSC tied to EIA weekly diesel average at time of shipment. Always tell Radka and team to apply floating FSC structure to protect the board."),
    ("rate_rule", None, "Rate schedule requests from customers: Do not commit to rate cards. Once you give a schedule, they hold you to it when carrier costs spike. Deflect to case-by-case quoting. Frame it as: 'We prioritize your loads and turn quotes around quickly — rates on this lane fluctuate based on truck availability and fuel.'"),
    ("rate_rule", None, "Equipment selection quick decision — 4 questions every time: 1) What is it? (commodity, weight, dims, pallets, hazmat, temp?), 2) How big?, 3) Where? (dock/no dock, residential, limited access?), 4) When?"),
    ("rate_rule", None, "Van vs flatbed test: Can it fit through 96\" wide × 102\" tall? YES = dry van. NO = flatbed or step deck."),
    ("rate_rule", None, "Equipment capacity reference: 53' dry van = 45,000 lbs / 26 pallets. 48' dry van = 43,000 lbs / 22 pallets. 26' straight truck = ~10,000 lbs / 12 pallets. Flatbed = 48,000 lbs. Hotshot = ~10,000 lbs. Sprinter = ~3,000 lbs."),
    ("rate_rule", None, "No dock at delivery = liftgate or flatbed with forklift on site. Confirm BEFORE quoting — this is how we get burned."),
    ("rate_rule", None, "International customers often provide weight in KG and dims in CM. Always convert: KG × 2.2 = lbs. CM ÷ 2.5 = inches. US pallet = 48\"×40\". Euro pallet = 47\"×31.5\". Ask which if they just say 'pallet.'"),
    ("rate_rule", None, "Transit time estimate: Solo driver = ~500 miles/day. Team driver = 1,000+ miles/day. Formula: Miles ÷ 500 = days, then add 1 day for pickup + 1 day buffer."),
    ("rate_rule", None, "Friday pickup rule: Friday PU → Monday delivery = weekend layover cost. Flag to customer or price it in before booking."),
    ("rate_rule", None, "Scheduling rule: Always work backward from delivery. Never book hoping the math works out."),
    ("rate_rule", None, "Before booking confirmation questions: Shipper hours, load time estimate, receiver hours, appointment required or FCFS, dock or no dock at both ends."),

    # --- SOPs ---
    ("sop", None, "Check-call / proactive communication rule: If there is ANY chance an issue touches the customer's freight or timeline, we call first. Customer should NEVER find out about a problem from someone other than us."),
    ("sop", None, "Detention protocol — Under 2 hours at delivery: Normal. Do not call customer. Tell driver and carrier to be patient."),
    ("sop", None, "Detention protocol — At 2 hours: Call customer. 'Our driver checked in at [time] and is still waiting to be unloaded. Can you check on dock status?' Collaborative, not adversarial."),
    ("sop", None, "Detention protocol — 3+ hours: Detention conversation. Check before load moves: does this customer pay detention? What's the free time? What's the rate? If in rate con = document and bill. If not in rate con = escalate to John."),
    ("sop", None, "Detention protocol — Driver told they won't be unloaded today: Immediate escalation. Call customer to confirm. Call carrier to negotiate layover. Team has authority to approve layover up to pre-set dollar amount without calling John."),
    ("sop", None, "Detention documentation — Required every time, no exceptions: Driver arrival/check-in time, time of first call to facility, customer contact name spoken to, resolution and time unloaded. If it's not logged, it didn't happen."),
    ("sop", None, "Driver complaints rule: Driver is not the enemy. When carrier calls upset about wait times — validate it, act on it, protect the relationship on both sides. Answer is never 'that's not our problem.' Answer is always 'let me make some calls.'"),
    ("sop", None, "Freight weight/dims discrepancy: If actual freight differs from what was quoted — confirm actual vs. quoted BEFORE truck moves. If it changes equipment needs or rate, address it NOW, not at delivery. Re-quote if needed."),
    ("sop", "Tolead", "POD submission standard (Tolead JFK KPI): POD must be scanned and uploaded within 2 hours of delivery. If unable, notify Tolead operations immediately."),
    ("sop", None, "Escalate to John: Oversized/permit loads, hazmat, multi-stop loads outside normal scope, detention not covered in rate con and customer is disputing, layover above pre-approved threshold, recurring detention at same facility (pattern problem)."),
    ("sop", None, "Accessorial documentation requirements — Dray: drop_fee (1-way or round-trip), chassis (split chassis or chassis usage), detention (hourly after free time), pier_pass (LA/LB specific), pre_pull (pull container day before appt), demurrage (container sitting at port/rail), exam_fee (customs exam), port_congestion (congestion surcharge)."),
    ("sop", None, "Accessorial documentation requirements — FTL: fuel_surcharge (usually % of linehaul), stopoff (additional stop), layover (overnight wait), TONU (truck ordered not used), overweight (over legal limit fees)."),
    ("sop", "Cadi", "BOL creation — Cadi Company: Requires FTZ/domestic BOL splits. Multiple stops. Always obtain delivery orders before truck rolls."),

    # --- CARRIER NOTES ---
    ("carrier_note", "MIFS", "MIFS (transload carrier — Port Everglades / DSV): Rate structure = $40/pallet in & out + $40/pallet/month storage (pro-rated weekly, $10/pallet/week). First 3 days free. Second week triggered after 11 days. Reliable for Port Everglades transload."),
    ("carrier_note", "Cadence Global Logistics", "Cadence Global Logistics (carrier code V125821): Used on Tolead Joliet → Wood Dale lane. Example rates: $475 base + $125 drop fee = $600 total on 40HC container."),
    ("carrier_note", "Laredo TX", "General carrier sourcing tip for Laredo TX lanes: Emphasize the RPM, confirm they understand no stackback restrictions, and price in the dead-end market premium upfront. Don't wait for carrier to ask."),
    ("carrier_note", None, "Flatbed/Conestoga sourcing: When pitching a load, emphasize RPM, legal weight, early morning delivery flexibility, and Pacific NW backhaul if applicable (lumber, steel, manufacturing outbound)."),

    # --- PREFERENCES ---
    ("preference", None, "Communication style (all customer-facing): Miles Davis — minimal words, maximum impact. No hedging, no filler. Be direct and confident. Don't over-explain."),
    ("preference", None, "Quote card format: Dark card on white background, CSL logo, gradient headers. Two formats — (1) Dray/Transload/OTR = one-way mileage, (2) Dray R/T = round-trip mileage. No T&C footer. Produce as copyable screenshot for email paste (not attachment)."),
    ("preference", None, "Rate negotiation framing: 'Customers want freight quick, cheap, and done right — they only get two. Which two?'"),
    ("preference", None, "When asked about rate schedules: Redirect to case-by-case with fast turnaround as the value prop. Never commit to a locked schedule on volatile lanes."),
    ("preference", None, "Fuel surcharge communication to customers: 'Rate was quoted all-in based on DOE National Average Diesel. We don't adjust for normal fluctuations. If DOE moves more than $0.25/gal from baseline, we'd revisit — and that applies both ways.'"),
]


def seed():
    db.init_pool()
    count = 0
    for category, scope, content in ENTRIES:
        try:
            db.kb_insert(category=category, content=content, scope=scope, source="memory_import")
            count += 1
        except Exception as e:
            print(f"  SKIP: {content[:60]}... — {e}")
    print(f"\nSeeded {count}/{len(ENTRIES)} knowledge base entries.")
    db.close_pool()


if __name__ == "__main__":
    seed()
