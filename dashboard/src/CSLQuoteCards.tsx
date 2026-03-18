import { Fragment } from "react";

const LOGO_ICON = "data:image/png;base64,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";

const grad = "linear-gradient(135deg, #00c853 0%, #00b8d4 50%, #2979ff 100%)";

/* ── Dray/Transload/OTR format (one-way mileage) ── */
const drayTransloadOTR = {
  route: [
    { label: "Port / Origin", value: "NY/NJ Ports" },
    { label: "Delivery Destination", value: "Ranger, TX 76470" },
    { label: "One-Way Mileage", value: "1,680" },
    { label: "Transit Time (One-Way)", value: "3 days" },
  ],
  sections: [
    {
      title: "Dray/Transload",
      rows: [{ desc: "All In", rate: "$1,092.50" }],
    },
    {
      title: "OTR",
      rows: [
        { desc: "53ft Van to Ranger TX", rate: "$3,852.50" },
        { desc: "Detention after 2 hrs free", rate: "$74.75" },
      ],
    },
    {
      title: "Accessorial Charges",
      rows: [
        { desc: "Storage (2 days) @ $70/day", rate: "$140.00" },
        { desc: "Port Liberty NY Toll", rate: "$250.00" },
      ],
    },
  ],
  total: "$5,339.75",
};

/* ── Dray R/T format (round-trip mileage) ── */
const drayRT = {
  route: [
    { label: "POD", value: "Minneapolis" },
    { label: "Delivery Destination", value: "Chaska, MN" },
    { label: "R/T Mileage", value: "937" },
    { label: "Transit Time (One-Way)", value: "1.5 days" },
  ],
  sections: [
    {
      title: "Charges",
      rows: [
        { desc: "Linehaul + fuel", rate: "$385.00" },
        { desc: "CP/UP Surcharge", rate: "$125.00" },
        { desc: "Split", rate: "$85.00" },
        { desc: "Chassis per day", rate: "$45.00" },
      ],
    },
    {
      title: "Transload",
      rows: [{ desc: "Handling In/Out", rate: "$550.00" }],
    },
    {
      title: "OTR",
      rows: [
        { desc: "53' Van to Coppell TX", rate: "$2,500.00" },
        { desc: "Detention after 2 hrs free", rate: "$65.00" },
      ],
    },
  ],
  total: "$3,690.00",
};

const cellLabel = {
  padding: "7px 20px",
  fontSize: 12.5,
  fontWeight: 700,
  color: "rgba(255,255,255,0.8)",
  borderBottom: "1px solid rgba(255,255,255,0.04)",
};

const cellValue = {
  padding: "7px 20px",
  fontSize: 12.5,
  fontWeight: 700,
  color: "#fff",
  textAlign: "right",
  borderBottom: "1px solid rgba(255,255,255,0.04)",
};

const sectionHead = (isLeft) => ({
  padding: "8px 20px",
  fontSize: 11,
  fontWeight: 800,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  textAlign: isLeft ? "left" : "right",
  background: "rgba(0,200,83,0.06)",
  borderTop: "2px solid",
  borderImage: grad + " 1",
  backgroundClip: "text",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  backgroundImage: grad,
});

const rowLeft = {
  padding: "8px 20px",
  fontSize: 12.5,
  fontWeight: 500,
  color: "rgba(255,255,255,0.6)",
  borderBottom: "1px solid rgba(255,255,255,0.04)",
};

const rowRight = {
  padding: "8px 20px",
  fontSize: 12.5,
  color: "#fff",
  fontWeight: 700,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
  borderBottom: "1px solid rgba(255,255,255,0.04)",
};

const totalLeft = {
  padding: "14px 20px",
  fontSize: 11,
  fontWeight: 800,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  borderTop: "2px solid",
  borderImage: grad + " 1",
  background: "rgba(0,200,83,0.04)",
  backgroundClip: "text",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  backgroundImage: grad,
  verticalAlign: "middle",
};

const totalRight = {
  padding: "14px 20px",
  fontSize: 22,
  fontWeight: 800,
  textAlign: "right",
  borderTop: "2px solid",
  borderImage: grad + " 1",
  background: "rgba(0,200,83,0.04)",
  fontVariantNumeric: "tabular-nums",
  backgroundClip: "text",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  backgroundImage: grad,
  verticalAlign: "middle",
};

export function QuoteCard({ data, label }) {
  return (
    <div style={{ flex: "1 1 400px", maxWidth: 440 }}>
      {label && (
        <div
          style={{
            textAlign: "center",
            marginBottom: 10,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "#666",
          }}
        >
          {label}
        </div>
      )}
      <table
        cellPadding={0}
        cellSpacing={0}
        style={{
          fontFamily: "'Segoe UI', -apple-system, sans-serif",
          width: "100%",
          background: "#0f1215",
          borderRadius: 10,
          overflow: "hidden",
          borderCollapse: "collapse",
          color: "#fff",
        }}
      >
        <tbody>
          {/* Header */}
          <tr>
            <td
              colSpan={2}
              style={{
                padding: "16px 20px",
                borderBottom: "1px solid rgba(255,255,255,0.06)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <img
                  src={LOGO_ICON}
                  alt="CSL"
                  style={{ height: 36, width: "auto", flexShrink: 0 }}
                />
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>
                    Common Sense Logistics
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: "rgba(255,255,255,0.3)",
                      fontWeight: 500,
                      marginTop: 1,
                    }}
                  >
                    Evans Delivery Company
                  </div>
                </div>
              </div>
            </td>
          </tr>

          {/* Route Info */}
          {data.route.map((row, i) => (
            <tr key={i}>
              <td style={cellLabel}>{row.label}</td>
              <td style={cellValue}>{row.value}</td>
            </tr>
          ))}

          {/* Spacer */}
          <tr>
            <td colSpan={2} style={{ height: 10 }} />
          </tr>

          {/* Sections */}
          {data.sections.map((section, si) => (
            <Fragment key={si}>
              <tr>
                <td style={sectionHead(true)}>{section.title}</td>
                <td style={sectionHead(false)}>Rate</td>
              </tr>
              {section.rows.map((row, ri) => (
                <tr key={ri}>
                  <td style={rowLeft}>{row.desc}</td>
                  <td style={rowRight}>{row.rate}</td>
                </tr>
              ))}
            </Fragment>
          ))}

          {/* Total */}
          <tr>
            <td style={totalLeft}>Estimated Total Invoice</td>
            <td style={totalRight}>{data.total}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function CSLQuoteCards() {
  return (
    <div style={{ background: "#ffffff", padding: 24, minHeight: "100vh" }}>
      <div
        style={{
          display: "flex",
          gap: 32,
          flexWrap: "wrap",
          justifyContent: "center",
          alignItems: "flex-start",
        }}
      >
        <QuoteCard
          data={drayTransloadOTR}
          label="Dray / Transload / OTR Format"
        />
        <QuoteCard data={drayRT} label="Dray Round-Trip Format" />
      </div>
    </div>
  );
}
