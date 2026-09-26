import type { RouteResponse } from "../lib/types";

interface Props {
  departAt: Date;
  onRoute: (r: RouteResponse) => void;
}

export default function DestinationWidget({ departAt, onRoute }: Props) {
  // TODO: "Where to?" input + conditions strip; call api.route
  return <div className="destination-widget">Where to?</div>;
}
