import { Navigate, useLocation } from "react-router-dom";

/**
 * Goes on to `to`, keeping the query, the hash and what the last screen
 * handed over (a "back to Home" label, say), so an old address lands exactly
 * where the new one would.
 */
export function Onward({ to }: { to: string }) {
  const { search, hash, state } = useLocation();
  return <Navigate to={{ pathname: to, search, hash }} state={state} replace />;
}
