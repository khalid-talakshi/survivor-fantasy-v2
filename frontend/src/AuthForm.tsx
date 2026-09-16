import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useForm } from "@tanstack/react-form";
import { useApp } from "./router";
import { consumeUnauthorizedReason } from "./lib/auth-callback";

export function AuthForm({ passwordSetup = false, next, reason }: { passwordSetup?: boolean; next?: string; reason?: "unauthorized" }) {
  const app = useApp();
  const navigate = useNavigate();
  const [submitError, setSubmitError] = useState<string | null>(() => {
    const hasRememberedUnauthorizedReason = consumeUnauthorizedReason();
    return reason === "unauthorized" || hasRememberedUnauthorizedReason ? "Your session ended or your invitation could not be verified. Please sign in again." : null;
  });
  const form = useForm({
    defaultValues: { email: "", password: "", confirmation: "" },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      const result = passwordSetup ? await app.auth.updatePassword(value.password) : await app.auth.signIn(value.email, value.password);
      if (result.error) { setSubmitError("We could not complete authentication. Check your details and try again."); return; }
      await app.queryClient.invalidateQueries({ queryKey: ["session"] });
      const destination = passwordSetup ? (sessionStorage.getItem("sf:next") ?? "/app") : (next ?? sessionStorage.getItem("sf:next") ?? "/app");
      sessionStorage.removeItem("sf:next");
      await navigate({ to: destination });
    },
  });
  return <main className="auth-page"><div className="auth-card"><Link className="brand" to="/"><span className="brand-mark">SF</span><span>Survivor Fantasy</span></Link><h1>{passwordSetup ? "Set your password" : "Welcome back"}</h1><p>{passwordSetup ? "Secure your invitation before entering the league." : "Sign in with the email you were invited with."}</p>{submitError && <p className="form-error" role="alert" aria-live="polite">{submitError}</p>}<form onSubmit={(event) => { event.preventDefault(); void form.handleSubmit(); }} noValidate>{!passwordSetup && <form.Field name="email" validators={{ onChange: ({ value }) => value.includes("@") ? undefined : "Enter a valid email." }}>{(field) => <label htmlFor={field.name}>Email<input id={field.name} name={field.name} type="email" autoComplete="email" value={field.state.value} aria-invalid={field.state.meta.errors.length > 0} aria-describedby={`${field.name}-error`} onChange={(e) => field.handleChange(e.target.value)} />{field.state.meta.errors.map((error) => <small id={`${field.name}-error`} role="alert" key={error}>{error}</small>)}</label>}</form.Field>}<form.Field name="password" validators={{ onChange: ({ value }) => value.length >= 8 ? undefined : "Use at least 8 characters." }}>{(field) => <label htmlFor={field.name}>Password<input id={field.name} name={field.name} type="password" value={field.state.value} aria-invalid={field.state.meta.errors.length > 0} aria-describedby={`${field.name}-error`} onChange={(e) => field.handleChange(e.target.value)} />{field.state.meta.errors.map((error) => <small id={`${field.name}-error`} role="alert" key={error}>{error}</small>)}</label>}</form.Field>{passwordSetup && <form.Field name="confirmation" validators={{ onChangeListenTo: ["password"], onChange: ({ value, fieldApi }) => value === fieldApi.form.getFieldValue("password") ? undefined : "Passwords must match.", onSubmit: ({ value, fieldApi }) => value === fieldApi.form.getFieldValue("password") ? undefined : "Passwords must match." }}>{(field) => <label htmlFor={field.name}>Confirm password<input id={field.name} name={field.name} type="password" value={field.state.value} aria-invalid={field.state.meta.errors.length > 0} aria-describedby={`${field.name}-error`} onChange={(e) => field.handleChange(e.target.value)} />{field.state.meta.errors.map((error) => <small id={`${field.name}-error`} role="alert" key={error}>{error}</small>)}</label>}</form.Field>}<form.Subscribe selector={(state) => [Boolean(state.canSubmit), Boolean(state.isSubmitting)]}>{([canSubmit, submitting]) => <button type="submit" disabled={!canSubmit || submitting}>{submitting ? "Working…" : passwordSetup ? "Set password" : "Sign in"}</button>}</form.Subscribe></form></div></main>;
}
