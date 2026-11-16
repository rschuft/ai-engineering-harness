import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { DEFAULT_AREA_PATH } from "../areas";
import { useOwnerSession } from "./OwnerSessionContext";
import { REFUSAL_TEXT } from "./owner-session";

/**
 * The login view (plan leaf U-01.3): the Owner pastes the credential the
 * enroll command showed at his console. It is verified with the Integration
 * process before the shell keeps it. The field is emptied after each attempt,
 * so the credential is not left in the form; a verified credential stays in
 * the page's memory and in localStorage while the Owner is signed in.
 */
export function SignIn() {
  const { state, signIn, signOut } = useOwnerSession();
  const navigate = useNavigate();
  const [value, setValue] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const candidate = value.trim();
    setValue("");
    if (await signIn(candidate)) navigate(DEFAULT_AREA_PATH);
  }

  if (state.status === "signed-in") {
    return (
      <section className="owner-area" aria-labelledby="sign-in-heading" data-testid="area-sign-in">
        <h2 id="sign-in-heading" className="owner-area__title">
          Signed in
        </h2>
        <p>
          Session <code>{state.session.sessionId.slice(0, 8)}</code>, until {state.session.expiresAt}.
        </p>
        <button type="button" onClick={signOut}>
          Sign out
        </button>
      </section>
    );
  }

  const refusal = state.status === "signed-out" ? state.refusal : null;
  return (
    <section className="owner-area" aria-labelledby="sign-in-heading" data-testid="area-sign-in">
      <h2 id="sign-in-heading" className="owner-area__title">
        Sign in
      </h2>
      <p>
        Paste the Owner UI session credential that the enroll command showed at your console. Once verified, it is
        kept in this browser until you sign out, or until the Integration process refuses it (expired or replaced by
        a newer enrollment) when the shell next checks it.
      </p>
      <form onSubmit={submit} aria-label="Sign in">
        <label htmlFor="owner-credential">Owner UI session credential</label>
        <input
          id="owner-credential"
          name="owner-credential"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={state.status === "checking"}
        />
        <button type="submit" disabled={state.status === "checking" || value.trim() === ""}>
          Sign in
        </button>
      </form>
      {state.status === "unreachable" ? (
        <p role="alert" data-testid="sign-in-refusal" data-code="UNREACHABLE">
          {REFUSAL_TEXT.UNREACHABLE}
        </p>
      ) : null}
      {refusal ? (
        <p role="alert" data-testid="sign-in-refusal" data-code={refusal}>
          {REFUSAL_TEXT[refusal]}
        </p>
      ) : null}
    </section>
  );
}
