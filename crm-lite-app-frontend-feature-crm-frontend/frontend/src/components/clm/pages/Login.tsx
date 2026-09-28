"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import BrandMark from "../BrandMark";
import TachyonMarketingPanel from "../TachyonMarketingPanel";
import { ApiError, useApi } from "@/lib/api/client";
import { changePassword, login, type EmployeeInfo } from "@/lib/api/auth";
import { loginSuccess, passwordChanged } from "@/lib/features/authSlice";
import { useAppDispatch } from "@/lib/hooks";

export default function Login() {
  const api = useApi();
  const dispatch = useAppDispatch();
  const router = useRouter();

  // Two-step flow: first a normal login, then — only if the account still
  // has a system-generated temp password (must_change_password) — a forced
  // password change before landing in the app. See auth_service.py's
  // create_employee()/login() on the backend.
  const [pendingChange, setPendingChange] = useState<{ token: string; employee: EmployeeInfo } | null>(null);

  return (
    <div className="auth-shell">
      <TachyonMarketingPanel />
      <div className="auth-form-side">
        <div className="login-card card">
          <div className="login-brand">
            <div className="login-brand-mark">
              <BrandMark fill="#ffffff" />
            </div>
            <div className="login-brand-name">Tachyon Connect</div>
          </div>
          {pendingChange ? (
            <ChangePasswordForm
              token={pendingChange.token}
              employee={pendingChange.employee}
              onDone={() => {
                dispatch(passwordChanged());
                router.replace("/");
              }}
            />
          ) : (
            <LoginForm
              onLoggedIn={(token, employee, mustChangePassword) => {
                if (mustChangePassword) {
                  setPendingChange({ token, employee });
                } else {
                  dispatch(loginSuccess({ token, employee, mustChangePassword: false }));
                  router.replace("/");
                }
              }}
            />
          )}
        </div>
      </div>
    </div>
  );

  function LoginForm({
    onLoggedIn,
  }: {
    onLoggedIn: (token: string, employee: EmployeeInfo, mustChangePassword: boolean) => void;
  }) {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    function submit() {
      setError(null);
      if (!email.trim() || !password) {
        setError("Enter your email and password.");
        return;
      }
      startTransition(async () => {
        try {
          const result = await login(api, { email: email.trim(), password });
          onLoggedIn(result.access_token, result.employee, result.must_change_password);
        } catch (err) {
          setError(err instanceof ApiError ? err.message : "Couldn't sign in. Try again.");
        }
      });
    }

    return (
      <form
        className="login-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <h1 className="login-title">Sign in</h1>
        <div className="field">
          <div className="lab">Email</div>
          <input
            className="inp"
            type="email"
            autoComplete="username"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <div className="lab">Password</div>
          <input
            className="inp"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && <div className="help err">{error}</div>}
        <button type="submit" className="btn primary login-submit" disabled={isPending}>
          {isPending ? "Signing in…" : "Sign in"}
        </button>
        <Link href="/setup" className="btn login-submit" style={{ marginTop: 8, textAlign: "center" }}>
          Set up admin account
        </Link>
      </form>
    );
  }

  function ChangePasswordForm({
    token,
    employee,
    onDone,
  }: {
    token: string;
    employee: EmployeeInfo;
    onDone: () => void;
  }) {
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [isPending, startTransition] = useTransition();

    function submit() {
      setError(null);
      if (newPassword.length < 8) {
        setError("New password must be at least 8 characters.");
        return;
      }
      if (newPassword !== confirmPassword) {
        setError("New passwords don't match.");
        return;
      }
      startTransition(async () => {
        try {
          // change-password needs the just-issued token before it's in the
          // store yet — set it first so useApi()'s request() picks it up.
          dispatch(loginSuccess({ token, employee, mustChangePassword: true }));
          await changePassword(api, { current_password: currentPassword, new_password: newPassword });
          onDone();
        } catch (err) {
          setError(err instanceof ApiError ? err.message : "Couldn't update your password. Try again.");
        }
      });
    }

    return (
      <form
        className="login-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <h1 className="login-title">Set your password</h1>
        <p className="login-sub">
          Welcome, {employee.full_name ?? employee.email}. This account was created with a temporary
          password — set your own before continuing.
        </p>
        <div className="field">
          <div className="lab">Temporary password</div>
          <input
            className="inp"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
        </div>
        <div className="field">
          <div className="lab">New password</div>
          <input
            className="inp"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
        </div>
        <div className="field">
          <div className="lab">Confirm new password</div>
          <input
            className="inp"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
        </div>
        {error && <div className="help err">{error}</div>}
        <button type="submit" className="btn primary login-submit" disabled={isPending}>
          {isPending ? "Saving…" : "Set password and continue"}
        </button>
      </form>
    );
  }
}
