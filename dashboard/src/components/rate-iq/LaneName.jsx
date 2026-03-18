import React from 'react';
import { splitCityState } from './constants';

/**
 * Render a city label with an optional, visually de-emphasized state.
 *
 * @param {object} props
 * @param {string} props.city - Pre-parsed city name.
 * @param {string} props.state - Pre-parsed state abbreviation.
 * @param {string} props.raw - Fallback "City, ST" string to parse client-side when `city`/`state` are not provided.
 * @param {boolean} [props.bold=true] - Whether the city text should use a heavier font weight.
 * @param {number|string} [props.citySize] - City font size (px or CSS size); when omitted, inherits font size.
 * @param {number} [props.stateSize=11] - State font size in px.
 * @returns {JSX.Element} A span containing the formatted city and optional state, or an em dash when no city is available.
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
