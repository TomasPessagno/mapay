import type { RouteResponse } from "../lib/types";

export default function RouteCard({ route }: { route: RouteResponse }) {
  // TODO: baseline vs hazard-aware comparison, briefing text, "Open in..." buttons
  return <div className="route-card">{route.briefing}</div>;
}
