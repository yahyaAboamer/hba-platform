import { useEffect, useState } from "react";

type Health = { status: string };

/**
 * Placeholder shell.
 *
 * Its only job is to prove the deployment shape end to end: React builds to
 * static assets, FastAPI serves them, and the browser can reach the API from
 * the same origin. Real screens arrive with the modules that need them.
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health/ready")
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => setError("Could not reach the API"));
  }, []);

  return (
    <main
      style={{
        fontFamily: "system-ui, -apple-system, sans-serif",
        padding: "3rem",
        color: "#1a1a1a",
      }}
    >
      <h1 style={{ fontWeight: 600, margin: 0 }}>HBA Platform</h1>
      <p style={{ color: "#666", marginTop: "0.5rem" }}>
        {error ?? (health ? `API status: ${health.status}` : "Checking API…")}
      </p>
    </main>
  );
}
