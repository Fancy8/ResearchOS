export type HighlightRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

// Revalidate against rendered text. Persisted client rectangles are only hints.
export function highlightExactText(
  layer: HTMLElement,
  quote: string,
): HighlightRect[] | null {
  const walker = window.document.createTreeWalker(
    layer,
    NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
  );
  const characters: string[] = [];
  const locations: Array<{ node: Text; offset: number } | null> = [];
  function append(
    character: string,
    location: { node: Text; offset: number } | null,
  ) {
    if (/\s/.test(character)) {
      if (characters.length && characters[characters.length - 1] !== " ") {
        characters.push(" ");
        locations.push(location);
      }
    } else {
      characters.push(character);
      locations.push(location);
    }
  }
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node as Text;
      for (let index = 0; index < text.length; index += 1)
        append(text.data[index], { node: text, offset: index });
    } else if ((node as Element).tagName === "BR") append(" ", null);
  }
  const normalized = characters.join("").trimEnd();
  const exact = quote.replace(/\s+/g, " ").trim();
  const start = normalized.indexOf(exact);
  if (!exact || start < 0 || normalized.indexOf(exact, start + 1) >= 0)
    return null;
  const first = locations[start],
    last = locations[start + exact.length - 1];
  if (!first || !last) return null;
  const range = window.document.createRange();
  range.setStart(first.node, first.offset);
  range.setEnd(last.node, last.offset + 1);
  const parent = layer.parentElement!.getBoundingClientRect();
  const rectangles = Array.from(range.getClientRects())
    .filter((rect) => rect.width > 0 && rect.height > 0)
    .slice(0, 500)
    .map((rect) => ({
      x: rect.left - parent.left,
      y: rect.top - parent.top,
      width: rect.width,
      height: rect.height,
    }));
  return rectangles.length ? rectangles : null;
}
