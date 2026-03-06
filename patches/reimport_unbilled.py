"""Re-import unbilled orders with new ref1/ref2/ref3/rep columns."""
import sys
sys.path.insert(0, '/root/csl-bot/csl-doc-tracker')
from app import _parse_unbilled_excel, _map_unbilled_row, _calc_age
from datetime import datetime
import psycopg2, psycopg2.extras

with open('/tmp/unbilled_mapping.xls', 'rb') as f:
    data = f.read()

rows = _parse_unbilled_excel(data, 'unbilled_mapping.xls')
mapped = [_map_unbilled_row(r) for r in rows]
mapped = [m for m in mapped if m['order_num']]
batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')

conn = psycopg2.connect(dbname='csl_doc_tracker', user='csl_admin', host='localhost', password='031dea221bd277380c0f6002863bae954aa2dc9398727aa1')
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

cur.execute('DELETE FROM unbilled_orders WHERE dismissed = FALSE')
print('Cleared old non-dismissed orders')

for m in mapped:
    age = _calc_age(m['entered'])
    cur.execute(
        'INSERT INTO unbilled_orders (order_num, container, bill_to, ref1, ref2, ref3, tractor, entered, appt_date, dliv_dt, act_dt, age_days, rep, upload_batch) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (m['order_num'], m['container'], m['bill_to'], m['ref1'], m['ref2'], m['ref3'], m['tractor'],
         m['entered'], m['appt_date'], m['dliv_dt'], m['act_dt'], age, m['rep'], batch_id)
    )

cur.execute('SELECT rep, COUNT(*) as cnt FROM unbilled_orders WHERE dismissed = FALSE GROUP BY rep ORDER BY cnt DESC')
print('Imported %d orders. Rep breakdown:' % len(mapped))
for row in cur.fetchall():
    rep = row['rep'] if row['rep'] else '(unassigned)'
    print('  %s: %d' % (rep, row['cnt']))

cur.close()
conn.close()
print('Done!')
