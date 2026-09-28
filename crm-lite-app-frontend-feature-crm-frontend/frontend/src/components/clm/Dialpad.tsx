"use client";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

export default function Dialpad({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <input
        className="inp"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="+91 9876543210"
        disabled={disabled}
        style={{ textAlign: "center", fontSize: 18, marginBottom: 10 }}
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 10 }}>
        {KEYS.map((key) => (
          <button
            key={key}
            type="button"
            className="btn"
            disabled={disabled}
            onClick={() => onChange(value + key)}
            style={{ fontSize: 18, padding: "10px 0" }}
          >
            {key}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
        <button type="button" className="btn sm" disabled={disabled} onClick={() => onChange(value + "+")}>
          +
        </button>
        <button type="button" className="btn sm" disabled={disabled || !value} onClick={() => onChange(value.slice(0, -1))}>
          ⌫ Backspace
        </button>
        <button type="button" className="btn sm" disabled={disabled || !value} onClick={() => onChange("")}>
          Clear
        </button>
      </div>
    </div>
  );
}
