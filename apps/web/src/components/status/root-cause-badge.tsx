import type { RootCause } from "../../api/types";
import { formatRootCause } from "./root-cause-format";

export function RootCauseBadge({ cause }: { cause: RootCause | string }) {
  return (
    <span className={`root-cause cause-${cause}`}>
      {formatRootCause(cause)}
    </span>
  );
}
