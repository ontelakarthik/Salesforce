"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import BrandMark from "../BrandMark";
import { ApiError, useApi } from "@/lib/api/client";
import { setupAdmin, type SetupAdminOut } from "@/lib/api/auth";

/** First-run setup — creates the very first ADMIN account directly through
 * the UI instead of an operator running scripts/bootstrap_admin.py by hand.
 * Only ever works once: the backend permanently rejects this the moment any
 * employee already exists (see auth_service.setup_admin()), so this can't
 * become a general "anyone can sign up as admin" hole — after the first
 * real admin is created, this page just shows that error and links back to
 * /login. Mirrors "Add employee" exactly: no password field here — a temp
 * password is generated and emailed, then sign-in and the forced
 * password-change happen at /login like any other account. */
export default function Setup() {
  const api = useApi();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [alreadyDone, setAlreadyDone] = useState(false);
  const [result, setResult] = useState<SetupAdminOut | null>(null);
  const [isPending, startTransition] = useTransition();

  function submit() {
    setError(null);
    if (!fullName.trim() || !email.trim()) {
      setError("Enter your name and email.");
      return;
    }
    startTransition(async () => {
      try {
        setResult(await setupAdmin(api, { email: email.trim(), full_name: fullName.trim() }));
      } catch (err) {
        if (err instanceof ApiError && err.code === "SETUP_ALREADY_COMPLETED") {
          setAlreadyDone(true);
        } else {
          setError(err instanceof ApiError ? err.message : "Couldn't set up the admin account. Try again.");
        }
      }
    });
  }

  return (
    <div className="login-page">
      <div className="login-card card">
        <div className="login-brand">
          <div className="login-brand-mark">
            <BrandMark fill="#ffffff" />
          </div>
          <div className="login-brand-name">Tachyon Connect</div>
        </div>
        {alreadyDone ? (
          <div className="login-form">
            <h1 className="login-title">Already set up</h1>
            <p className="login-sub">
              An admin account already exists for this CRM — set-up only ever runs once.
            </p>
            <Link href="/login" className="btn primary login-submit" style={{ textAlign: "center" }}>
              Go to sign in
            </Link>
          </div>
        ) : result ? (
          <div className="login-form">
            <h1 className="login-title">Check your email</h1>
            {result.password_email_sent ? (
              <p className="login-sub">
                A temporary password was sent to <b>{result.email}</b>. Sign in with it below, and
                you&apos;ll be asked to set your own password.
              </p>
            ) : (
              <>
                <p className="login-sub">
                  Email isn&apos;t configured on this deployment, so nothing was sent — save this
                  temporary password now, it won&apos;t be shown again:
                </p>
                <p className="login-sub" style={{ fontFamily: "monospace", fontSize: 16 }}>
                  {result.temp_password}
                </p>
              </>
            )}
            <Link href="/login" className="btn primary login-submit" style={{ textAlign: "center" }}>
              Go to sign in
            </Link>
          </div>
        ) : (
          <form
            className="login-form"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <h1 className="login-title">Set up your admin account</h1>
            <p className="login-sub">
              This creates the first administrator for a brand-new CRM Lite deployment — it only
              works once. A temporary password will be emailed to you.
            </p>
            <div className="field">
              <div className="lab">Full name</div>
              <input className="inp" autoFocus value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div className="field">
              <div className="lab">Email</div>
              <input
                className="inp" type="email" autoComplete="username"
                value={email} onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            {error && <div className="help err">{error}</div>}
            <button type="submit" className="btn primary login-submit" disabled={isPending}>
              {isPending ? "Setting up…" : "Create admin account"}
            </button>
            <div className="login-sub" style={{ marginTop: 12 }}>
              Already set up? <Link href="/login">Sign in instead</Link>.
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
