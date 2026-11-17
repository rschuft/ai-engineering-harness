import { describe, expect, it } from "vitest";
import {
  CANVAS_ORIGIN,
  canvasConversationUrl,
  checkedId,
  engineeringSessionPath,
  sessionDetailOf,
} from "./session-detail";
import { answer } from "../test/outcome-fixtures";
import standaloneSource from "../../scripts/canvas-standalone.mjs?raw";

// The shell's one checked builder of addresses that carry a projection-supplied value (U-01.2).

const CID = "055b27f3-903e-5eb9-8758-197c1029ade7";
const OUT = "3f6a2c1d-9b4e-4f7a-8c2d-5e1b0a9f7d63";
const HOSTILE: unknown[] = [
  undefined, null, 42, {}, [], "", CID.toUpperCase(), ` ${CID}`, `${CID} `, `${CID}\n`, `${CID}/x`, `${CID}?x=1`,
  `${CID}#x`, `../${CID}`, "../threads", "//203.0.113.9/", "http://203.0.113.9/", "javascript:alert(1)",
  "%2e%2e%2fthreads", `${CID.slice(0, -1)}`, `${CID}0`, CID.replace(/-/g, ""), "055b27f3_903e_5eb9_8758_197c1029ade7",
];

describe("the checked builder", () => {
  it("accepts a lower-case UUID only", () => {
    expect(checkedId(CID)).toBe(CID);
    for (const value of HOSTILE) expect(checkedId(value), String(value)).toBeNull();
  });

  it("builds the frame's address from the shell's constant Canvas origin and path only", () => {
    expect(CANVAS_ORIGIN).toBe("http://127.0.0.1:13330");
    expect(canvasConversationUrl(CID)).toBe(`http://127.0.0.1:13330/conversations/${CID}`);
    for (const value of HOSTILE) expect(canvasConversationUrl(value), String(value)).toBeNull();
    // the start command serves Canvas on that origin
    expect(standaloneSource).toContain("export const CANVAS_PORT = 13330;");
    expect(standaloneSource).toContain('export const LOOPBACK = "127.0.0.1";');
  });

  it("builds the shell's own engineering route from two ids only", () => {
    expect(engineeringSessionPath(OUT, CID)).toBe(`/engineering/outcomes/${OUT}/sessions/${CID}`);
    for (const value of HOSTILE) {
      expect(engineeringSessionPath(value, CID), String(value)).toBeNull();
      expect(engineeringSessionPath(OUT, value), String(value)).toBeNull();
    }
  });
});

describe("the projection's session-detail action, as the shell reads it", () => {
  it("is available for a fixture-bound attempt whose id and path are exactly the shell's own", () => {
    const [attempt] = answer("running-turn-sent").body.attempts;
    const detail = sessionDetailOf(attempt);
    expect(detail).toEqual({ available: true, conversationId: attempt.conversationId });
  });

  it("is refused for a live-bound or unbound attempt, with the projection's code and reason", () => {
    for (const name of ["published-live", "authority-unbound"]) {
      const [attempt] = answer(name).body.attempts;
      const detail = sessionDetailOf(attempt);
      expect(detail.available, name).toBe(false);
      expect(detail, name).toEqual({ available: false, code: "SESSION_ACCESS_UNAVAILABLE", reason: attempt.sessionDetail.reason });
    }
  });

  it("refuses an action whose id, path or authority is not exactly what the shell would build", () => {
    const base = { conversationId: CID, canvasPath: `/conversations/${CID}`, authority: "fixture" };
    expect(sessionDetailOf({ sessionDetail: base }).available).toBe(true);
    const bad = [
      { ...base, conversationId: "../threads" },
      { ...base, conversationId: CID.toUpperCase(), canvasPath: `/conversations/${CID.toUpperCase()}` },
      { ...base, canvasPath: `/conversations/${CID}/../x` },
      { ...base, canvasPath: "//203.0.113.9/conversations/x" },
      { ...base, canvasPath: `http://203.0.113.9/conversations/${CID}` },
      { ...base, authority: "live" },
      { ...base, authority: undefined },
    ];
    for (const sessionDetail of bad) {
      expect(sessionDetailOf({ sessionDetail }).available, JSON.stringify(sessionDetail)).toBe(false);
    }
    expect(sessionDetailOf({}).available).toBe(false);
    expect(sessionDetailOf(null).available).toBe(false);
  });
});
