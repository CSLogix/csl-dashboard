import React from 'react';
import { splitCityState } from './constants';

/**
 * Renders a city/state location with the state de-emphasized.
 * City appears bold in primary text color, state appears smaller and dimmed.
 *
 * @param {object} props
 * @param {string} props.city - Pre-parsed city name
 * @param {string} props.state - Pre-parsed state abbreviation
 * @param {string} props.raw - Fallback "City, ST" string (parsed client-side if city/state not provided)
 * @param {boolean} props.bold - Whether city text is bold (default: true)
 * @param {number} props.citySize - City font size in px (default: inherit)
 * @param {number} props.stateSize - State font size in px (default: 11)
 */
export default function LaneName({ city, state, raw, bold = true, citySize, stateSize = 11 }) {
  let displayCity = city;
  let displayState = state;

  // Client-side fallback: parse "City, ST" from raw if structured fields not provided
  if (!displayCity && raw) {
    const parsed = splitCityState(raw);
    displayCity = parsed.city;
    displayState = parsed.state;
  }

  if (!displayCity) return <span style={{ color: "#5A6478" }}>{"\u2014"}</span>;

  return (
    <span style={{ whiteSpace: "nowrap" }}>
      <span style={{
        fontWeight: bold ? 700 : 500,
        color: "#F0F2F5",
        fontSize: citySize || "inherit",
      }}>
        {displayCity}
      </span>
      {displayState && (
        <span style={{
          color: "#5A6478",
          fontSize: stateSize,
          fontWeight: 500,
          marginLeft: 3,
          opacity: 0.8,
          letterSpacing: "0.02em",
        }}>
          {displayState}
        </span>
      )}
    </span>
  );
}
