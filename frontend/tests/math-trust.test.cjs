// Regression for https://github.com/KaTeX/KaTeX/security/advisories/GHSA-238p-pmpm-9mq7
const { test } = require("node:test");
const assert = require("node:assert/strict");
const katex = require("katex");

test("inherited trust does not authorize user-supplied formula links", () => {
  const before = Object.getOwnPropertyDescriptor(Object.prototype, "trust");
  try {
    Object.defineProperty(Object.prototype, "trust", {
      value: true,
      writable: true,
      configurable: true,
    });
    const html = katex.renderToString("\\href{javascript:alert(1)}{probe}", {
      throwOnError: false,
    });
    assert.doesNotMatch(html, /<a\b/i);
    assert.doesNotMatch(html, /href\s*=\s*["']\s*javascript:/i);
  } finally {
    if (before) Object.defineProperty(Object.prototype, "trust", before);
    else delete Object.prototype.trust;
  }
});

test("renderer ignores trust inherited from the options prototype", () => {
  const html = katex.renderToString(
    "\\href{javascript:alert(1)}{probe}",
    Object.assign(Object.create({ trust: true }), { throwOnError: false }),
  );
  assert.doesNotMatch(html, /<a\b/i);
});

test("ordinary research mathematics still produces accessible MathML", () => {
  const html = katex.renderToString("\\frac{a}{b}+c^2", {
    throwOnError: true,
    trust: false,
  });
  assert.match(html, /class="katex"/);
  assert.match(html, /<math\b/);
  assert.match(html, /<mfrac>/);
});
