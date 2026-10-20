const MAX_STROKES = 40;

// Hand-counting tally marks: four uprights, then a fifth stroke across them.
export default function Tally({ count }) {
  if (count === 0 || count > MAX_STROKES) return null;
  const groups = [];
  for (let start = 0; start < count; start += 5) {
    groups.push(Math.min(5, count - start));
  }
  return (
    <div className="fc-tally" aria-hidden="true">
      {groups.map((strokes, group) => (
        <svg key={group} viewBox="0 0 46 40" className="fc-tally-group">
          {Array.from({ length: Math.min(strokes, 4) }, (_, stroke) => (
            <line key={stroke} x1={7 + stroke * 10} y1="4" x2={7 + stroke * 10} y2="36" />
          ))}
          {strokes === 5 && <line className="fc-tally-cross" x1="1" y1="30" x2="45" y2="10" />}
        </svg>
      ))}
    </div>
  );
}
