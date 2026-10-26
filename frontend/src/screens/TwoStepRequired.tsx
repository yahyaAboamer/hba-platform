import { AuthShell } from "../components/AuthShell";
import { TwoStepSetup } from "../components/TwoStepSetup";
import { signOutAndLeave } from "../lib/api";

/**
 * The only thing shown while the person's access needs two-step sign-in and
 * they have not set it up (`two_step.must_set_up`). The server refuses every
 * other call meanwhile, so there is no desk to show; set it up, or sign out.
 */
export function TwoStepRequired({ onDone }: { onDone: () => void }) {
  return (
    <AuthShell eyebrow="Required for your access" title="Set up two-step sign-in">
      <p className="auth__lead">
        Your access needs a second step when you sign in. It takes a minute and a phone.
      </p>
      <TwoStepSetup onDone={onDone} />
      <button type="button" className="auth__link twostep__sign-out" onClick={() => void signOutAndLeave()}>
        Sign out
      </button>
    </AuthShell>
  );
}
