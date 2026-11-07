// A small CSS walker for tests: lists style rules (with their enclosing
// at-rule context) and other at-rules. It handles nested @media, @supports,
// @layer, @container and CSS nesting, quoted strings and comments. It is an
// audit aid, not a CSS parser.

export interface CssStyleRule {
  selector: string;
  context: string[];
}

export interface CssAudit {
  imports: string[];
  styleRules: CssStyleRule[];
  atRules: string[];
}

const GROUPING = new Set(["@media", "@supports", "@layer", "@container", "@scope", "@starting-style", "@document"]);

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** Index of the brace matching the one at `open`, skipping escapes and quoted strings. */
function matchBrace(text: string, open: number): number {
  let depth = 0;
  let quote: string | null = null;
  for (let i = open; i < text.length; i++) {
    const ch = text[i];
    if (ch === "\\") {
      i++; // an escape (inside or outside a string) hides the next character
      continue;
    }
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return i;
  }
  throw new Error("unbalanced braces in CSS");
}

/** Statements ending in ';' before the next block (e.g. @import, declarations). */
function splitStatements(text: string): { statements: string[]; head: string } {
  const statements: string[] = [];
  let quote: string | null = null;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "\\") {
      i++;
      continue;
    }
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === ";") {
      statements.push(text.slice(start, i + 1).trim());
      start = i + 1;
    }
  }
  return { statements, head: text.slice(start).trim() };
}

export function auditCss(source: string): CssAudit {
  const audit: CssAudit = { imports: [], styleRules: [], atRules: [] };
  const walk = (text: string, context: string[]) => {
    let i = 0;
    while (i < text.length) {
      const open = text.indexOf("{", i);
      const { statements, head } = splitStatements(text.slice(i, open < 0 ? text.length : open));
      for (const s of statements) if (/^@import\b/i.test(s)) audit.imports.push(s);
      if (open < 0) break;
      const close = matchBrace(text, open);
      const body = text.slice(open + 1, close);
      if (head.startsWith("@")) {
        const name = head.split(/[\s(]/)[0].toLowerCase();
        if (GROUPING.has(name)) walk(body, [...context, head]);
        else audit.atRules.push(head);
      } else if (head) {
        audit.styleRules.push({ selector: head.replace(/\s+/g, " "), context });
        if (body.includes("{")) walk(body, [...context, `& ${head}`]);
      }
      i = close + 1;
    }
  };
  walk(stripComments(source), []);
  return audit;
}

/** Split a selector list on top-level commas (not those inside () or []). */
export function splitSelectorList(selector: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = "";
  for (let i = 0; i < selector.length; i++) {
    const ch = selector[i];
    if (ch === "\\") {
      current += ch + (selector[i + 1] ?? "");
      i++;
      continue;
    }
    if (ch === "(" || ch === "[") depth++;
    else if (ch === ")" || ch === "]") depth--;
    if (ch === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else current += ch;
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}
