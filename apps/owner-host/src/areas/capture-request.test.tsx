import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StoredChat } from "./ChatArea";
import { ACKNOWLEDGEMENT, CAPTURE_TOOL, formatRequest, isCaptureRequest, sha256Hex } from "./chat-adapter";
import { CAPTURE_CODES, INTEGRATION_ORIGIN, SESSION_HEADER, createIntegrationClient, type FetchLike } from "../identity/owner-session";

// The request form and the capture (plan leaf P-01.3) against a fake
// Integration process that keeps threads and messages in memory and answers
// the capture route as integrations/ownerhost/capture.py does: it compares
// the request's sha256 with the stored message's text and answers one commit
// per message (created, then found). No model is connected; the setup's
// network guard refuses any real request.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";
const OBJECTIVE = "Titles become URL slugs — café stays readable.";
const CRITERIA = ['slugify("Hello World") returns "hello-world"', "An empty title gives an empty slug"];
const SUGGESTION = "Use the python-slugify package";
const LAYOUT = [
  "Change: add-slugify",
  `Objective: ${OBJECTIVE}`,
  "Acceptance criteria:",
  ...CRITERIA.map((c) => `- ${c}`),
  `Suggestion: ${SUGGESTION}`,
].join("\n");
// hashlib.sha256(LAYOUT.encode('utf-8')).hexdigest(), computed by Python: the browser's digest must equal it.
const LAYOUT_SHA256 = "4165417107dc52fd0803a77ce603b46337c3f27d87019d25648d6faef7453ab7";
const COMMIT = "0123456789abcdef0123456789abcdef01234567";

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

type Seen = { method: string; path: string; body: any; phase: "start" | "end"; status?: number };

class FakeIntegration {
  threads = new Map<string, { localId: string; messages: { parentId: string | null; message: any }[] }>();
  captured = new Map<string, string>();
  seen: Seen[] = [];
  refusal: { status: number; code: string; detail: string } | null = null;
  hold: ((method: string, path: string, body: any) => Promise<void> | undefined) | null = null;
  workTree: string | null = null;

  constructor(readonly credential: string) {}

  fetchImpl: FetchLike = async (url, init) => {
    expect(url.startsWith(INTEGRATION_ORIGIN + "/")).toBe(true);
    expect((init.headers as Record<string, string>)[SESSION_HEADER]).toBe(this.credential);
    const path = url.slice(INTEGRATION_ORIGIN.length);
    const method = init.method ?? "GET";
    const body = init.body === undefined ? undefined : JSON.parse(init.body as string);
    this.seen.push({ method, path, body, phase: "start" });
    await this.hold?.(method, path, body);
    const [status, answer] = await this.route(method, path, body);
    this.seen.push({ method, path, body, phase: "end", status });
    return new Response(JSON.stringify(answer), { status });
  };

  captures(phase: "start" | "end" = "end"): Seen[] {
    return this.seen.filter((s) => s.phase === phase && s.path.endsWith("/capture"));
  }

  private async route(method: string, path: string, body: any): Promise<[number, unknown]> {
    let m: RegExpMatchArray | null;
    if (path === "/threads" && method === "GET") return [200, { threads: [] }];
    if (path === "/threads" && method === "POST") {
      const remoteId = "3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162";
      if (!this.threads.has(remoteId)) this.threads.set(remoteId, { localId: body.localId, messages: [] });
      return [200, { remoteId }];
    }
    if ((m = path.match(/^\/threads\/([^/]+)\/messages\/([^/]+)\/capture$/))) {
      const thread = this.threads.get(decodeURIComponent(m[1]));
      const stored = thread?.messages.find((s) => s.message.id === decodeURIComponent(m![2]));
      if (!stored) return [404, { code: "MESSAGE_NOT_FOUND" }];
      if (this.refusal) return [this.refusal.status, { code: this.refusal.code, detail: this.refusal.detail }];
      if ((await sha256Hex(stored.message.content[0].text)) !== body.sha256) return [409, { code: "CAPTURE_MESSAGE_MISMATCH" }];
      const created = !this.captured.has(stored.message.id);
      this.captured.set(stored.message.id, COMMIT);
      const answer = { change: "add-slugify", commit: COMMIT, created, receipt: `owner-ui/intent-capture/v1/x/${stored.message.id}` };
      return [200, this.workTree === null ? answer : { ...answer, workTree: this.workTree }];
    }
    if ((m = path.match(/^\/threads\/([^/]+)\/messages$/)) && method === "POST") {
      this.threads.get(decodeURIComponent(m[1]))!.messages.push({ parentId: body.parentId, message: body.message });
      return [200, { id: body.message.id, seq: 1, revision: 1, changed: true }];
    }
    if ((m = path.match(/^\/threads\/([^/]+)\/messages$/))) return [200, { messages: [] }];
    return [404, { code: "NOT_FOUND" }];
  }

  stored(): any[] {
    return [...this.threads.values()].flatMap((t) => t.messages.map((s) => s.message));
  }
}

function renderChat(fake: FakeIntegration) {
  render(<StoredChat client={createIntegrationClient(fake.credential, fake.fetchImpl)} />);
}

async function fillForm() {
  const form = await screen.findByTestId("request-form");
  const type = (label: string, value: string) =>
    fireEvent.change(within(form).getByRole("textbox", { name: label }), { target: { value } });
  await act(async () => {
    type("Change name", "  add-slugify ");
    type("Objective", OBJECTIVE);
    type("Acceptance criterion 1", CRITERIA[0]);
    fireEvent.click(within(form).getByRole("button", { name: "Add a criterion" }));
  });
  await act(async () => {
    type("Acceptance criterion 2", ` ${CRITERIA[1]} `);
    fireEvent.click(within(form).getByRole("button", { name: "Add a suggestion" }));
  });
  await act(async () => {
    type("Suggestion (a method you propose; recorded as a hypothesis, not as the objective) 1", SUGGESTION);
  });
  return form;
}

async function sendRequest(form: HTMLElement) {
  await act(async () => {
    fireEvent.click(within(form).getByRole("button", { name: "Send the request" }));
  });
}

describe("the request form and the capture (P-01.3)", () => {
  it("builds the fixed layout the capture parses, and Python's digest of it is the browser's", async () => {
    expect(
      formatRequest({ change: " add-slugify", objective: OBJECTIVE, criteria: [CRITERIA[0], "", CRITERIA[1] + " "], suggestions: [SUGGESTION] }),
    ).toBe(LAYOUT);
    expect(await sha256Hex(LAYOUT)).toBe(LAYOUT_SHA256);
    expect(isCaptureRequest(LAYOUT)).toBe(true);
    expect(isCaptureRequest("Please add slugify.")).toBe(false);
  });

  it("sends one message in the layout, captures it once it is stored, and shows the commit on a card", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    const form = await fillForm();
    expect(within(form).getByTestId("request-preview").textContent).toBe(LAYOUT);
    await sendRequest(form);
    const card = await screen.findByTestId("capture-card");
    await waitFor(() => expect(card.getAttribute("data-state")).toBe("captured"));
    expect(within(card).getByTestId("capture-commit").textContent).toBe(COMMIT);
    const [user] = fake.stored();
    expect(user.content).toEqual([{ type: "text", text: LAYOUT }]);
    const [capture] = fake.captures("start");
    expect(capture.path).toBe(`/threads/3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162/messages/${user.id}/capture`);
    expect(capture.body).toEqual({ sha256: LAYOUT_SHA256 });
    // the capture was asked only after the statement's append was answered
    const appendEnd = fake.seen.findIndex((s) => s.phase === "end" && s.body?.message?.id === user.id);
    expect(appendEnd).toBeGreaterThanOrEqual(0);
    expect(fake.seen.indexOf(capture)).toBeGreaterThan(appendEnd);
    // the reply is the card: a tool call whose result is the service's answer, stored as the assistant message
    await waitFor(() => expect(fake.stored()).toHaveLength(2));
    const reply = fake.stored()[1];
    expect(reply.content).toEqual([
      {
        type: "tool-call",
        toolCallId: `capture-${user.id}`,
        toolName: CAPTURE_TOOL,
        args: { messageId: user.id },
        argsText: JSON.stringify({ messageId: user.id }),
        result: { captured: true, change: "add-slugify", commit: COMMIT, created: true, receipt: `owner-ui/intent-capture/v1/x/${user.id}` },
      },
    ]);
    expect(within(form).getByRole("textbox", { name: "Change name" })).toHaveProperty("value", "");
  });

  it("waits for the statement to be stored before it asks for the capture", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    let release!: () => void;
    const released = new Promise<void>((resolve) => (release = resolve));
    fake.hold = (method, path, body) => (method === "POST" && path.endsWith("/messages") && body?.message?.role === "user" ? released : undefined);
    renderChat(fake);
    await sendRequest(await fillForm());
    await waitFor(() => expect(fake.seen.some((s) => s.phase === "start" && s.body?.message?.role === "user")).toBe(true));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(fake.captures("start")).toEqual([]);
    release();
    await waitFor(() => expect(fake.captures()).toHaveLength(1));
    expect(fake.captures()[0].status).toBe(200);
  });

  it("shows a refusal with its stable code and the service's detail, and nothing else", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    fake.refusal = { status: 422, code: "CAPTURE_LAYOUT_INVALID", detail: "line 4: a criterion is empty" };
    renderChat(fake);
    await sendRequest(await fillForm());
    const card = await screen.findByTestId("capture-card");
    await waitFor(() => expect(card.getAttribute("data-state")).toBe("refused"));
    expect(within(card).getByTestId("capture-code").textContent).toBe("CAPTURE_LAYOUT_INVALID");
    expect(card.textContent).toContain("line 4: a criterion is empty");
    expect(fake.captures()).toHaveLength(1);
  });

  it("tells the Owner when the work tree does not hold the captured commit's files", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    fake.workTree = "not brought to the commit";
    renderChat(fake);
    await sendRequest(await fillForm());
    const card = await screen.findByTestId("capture-card");
    await waitFor(() => expect(card.getAttribute("data-state")).toBe("captured"));
    expect(within(card).getByTestId("capture-work-tree").textContent).toContain("not brought to the commit");
    await waitFor(() => expect(fake.stored()).toHaveLength(2));
    expect(fake.stored()[1].content[0].result.workTree).toBe("not brought to the commit");
  });

  it("shows no work-tree note when the answer has none", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    await sendRequest(await fillForm());
    const card = await screen.findByTestId("capture-card");
    await waitFor(() => expect(card.getAttribute("data-state")).toBe("captured"));
    expect(within(card).queryByTestId("capture-work-tree")).toBeNull();
  });

  it("answers an ordinary message with the fixed acknowledgement and asks for no capture", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    const thread = await screen.findByTestId("chat-thread");
    await act(async () => {
      fireEvent.change(within(thread).getByRole("textbox", { name: "Message" }), { target: { value: "Please add slugify." } });
    });
    await act(async () => {
      fireEvent.click(within(thread).getByRole("button", { name: "Send" }));
    });
    await waitFor(() => expect(fake.stored()).toHaveLength(2));
    expect(fake.stored()[1].content).toEqual([{ type: "text", text: ACKNOWLEDGEMENT }]);
    expect(fake.captures("start")).toEqual([]);
  });

  it("keeps Send disabled until the name is kebab-case and an objective and a criterion are given", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    const form = await screen.findByTestId("request-form");
    const send = within(form).getByRole("button", { name: "Send the request" });
    expect(send).toHaveProperty("disabled", true);
    await act(async () => {
      fireEvent.change(within(form).getByRole("textbox", { name: "Change name" }), { target: { value: "Add Slugify" } });
      fireEvent.change(within(form).getByRole("textbox", { name: "Objective" }), { target: { value: OBJECTIVE } });
      fireEvent.change(within(form).getByRole("textbox", { name: "Acceptance criterion 1" }), { target: { value: CRITERIA[0] } });
    });
    expect(send).toHaveProperty("disabled", true);
    await act(async () => {
      fireEvent.change(within(form).getByRole("textbox", { name: "Change name" }), { target: { value: "add-slugify" } });
    });
    expect(send).toHaveProperty("disabled", false);
    expect(fake.seen.filter((s) => s.method === "POST")).toEqual([]);
  });

  it("knows every refusal code of the capture route", () => {
    expect([...CAPTURE_CODES].sort()).toEqual(
      [
        "CAPTURE_CHANGE_EXISTS", "CAPTURE_COMMIT_REFUSED", "CAPTURE_CONFIG_INVALID", "CAPTURE_GIT_FAILED",
        "CAPTURE_LAYOUT_INVALID", "CAPTURE_MESSAGE_MISMATCH", "CAPTURE_NOT_A_STATEMENT", "CAPTURE_OUTCOME_UNKNOWN",
        "CAPTURE_PROJECT_UNAVAILABLE", "CAPTURE_PROJECT_UNCONFIGURED", "CAPTURE_RECEIPT_CONFLICT",
        "CAPTURE_STORE_UNAVAILABLE", "COMMIT_IDENTITY_INVALID", "COMMIT_IDENTITY_PLACEHOLDER", "COMMIT_IDENTITY_UNAVAILABLE",
        "CAPTURE_COMMIT_UNREACHABLE", "CAPTURE_PROJECT_IS_HARNESS", "CAPTURE_SESSION_UNRECOGNIZED",
      ].sort(),
    );
  });
});
