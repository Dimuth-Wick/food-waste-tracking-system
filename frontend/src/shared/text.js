// "cupcake" -> "cupcakes", "bread roll" -> "bread rolls", "peach" -> "peaches".
export function plural(word, count = 2) {
  if (count === 1 || !word) return word;
  if (/(ss|x|z|ch|sh)$/.test(word)) return `${word}es`;
  if (word.endsWith("s")) return word;
  if (/[^aeiou]y$/.test(word)) return `${word.slice(0, -1)}ies`;
  return `${word}s`;
}

export function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}
