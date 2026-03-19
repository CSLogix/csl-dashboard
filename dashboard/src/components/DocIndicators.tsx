/**
 * Render small emoji indicators for document types present in the provided docs object.
 *
 * @param {Object} docs - Object of boolean-like or numeric indicators for document types.
 *   Recognized keys: `bol`, `pod`, `customer_rate`, `carrier_rate`, `carrier_invoice`, `msds`.
 *   Values may be truthy/falsey or numeric; when no specific indicators are truthy the component
 *   falls back to a single icon labeled with the total count (sum of Object.values(docs)).
 * @returns {JSX.Element|null} A span containing one or more icon spans for each detected document indicator, or `null` if `docs` is falsy or has no keys.
 */
export default function DocIndicators({ docs }) {
  if (!docs || Object.keys(docs).length === 0) return null;
  const icons = [];
  if (docs.bol) icons.push({ icon: "\u{1F4CB}", label: "BOL", key: "bol" });
  if (docs.pod) icons.push({ icon: "\u{1F4F8}", label: "POD", key: "pod" });
  if (docs.customer_rate || docs.carrier_rate) icons.push({ icon: "\u{1F4B0}", label: "Rate", key: "rate" });
  if (docs.carrier_invoice) icons.push({ icon: "\u{1F9FE}", label: "Invoice", key: "inv" });
  if (docs.msds) icons.push({ icon: "\u2623\uFE0F", label: "MSDS", key: "msds" });
  if (icons.length === 0) icons.push({ icon: "\u{1F4C4}", label: `${Object.values(docs).reduce((a, b) => a + b, 0)} docs`, key: "other" });
  return (
    <span style={{ display: "inline-flex", gap: 2, marginLeft: 4 }}>
      {icons.map(ic => <span key={ic.key} title={ic.label} style={{ fontSize: 11, cursor: "default", opacity: 0.7 }}>{ic.icon}</span>)}
    </span>
  );
}
