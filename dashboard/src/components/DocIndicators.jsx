export default function DocIndicators({ docs }) {
  if (!docs || Object.keys(docs).length === 0) return null;
  const icons = [];
  if (docs.bol) icons.push({ icon: "\u{1F4CB}", label: "BOL", key: "bol" });
  if (docs.pod) icons.push({ icon: "\u{1F4F8}", label: "POD", key: "pod" });
  if (docs.customer_rate || docs.carrier_rate) icons.push({ icon: "\u{1F4B0}", label: "Rate", key: "rate" });
  if (docs.carrier_invoice) icons.push({ icon: "\u{1F9FE}", label: "Invoice", key: "inv" });
  if (icons.length === 0) icons.push({ icon: "\u{1F4C4}", label: `${Object.values(docs).reduce((a, b) => a + b, 0)} docs`, key: "other" });
  return (
    <span style={{ display: "inline-flex", gap: 2, marginLeft: 4 }}>
      {icons.map(ic => <span key={ic.key} title={ic.label} style={{ fontSize: 10, cursor: "default", opacity: 0.7 }}>{ic.icon}</span>)}
    </span>
  );
}
