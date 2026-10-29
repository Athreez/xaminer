import { Badge } from "@/components/ui/badge";

import { statusLabel, type UserStatus } from "./lib";

export function StatusBadge({ status, locked }: { status: UserStatus; locked?: boolean }) {
  const tone = {
    ACTIVE: "bg-success-soft text-success border-success/30",
    INVITED: "bg-selection-soft text-selection border-selection/30",
    DEACTIVATED: "bg-muted text-muted-foreground border-border",
  }[status];
  return (
    <span className="inline-flex gap-1">
      <Badge variant="outline" className={tone}>
        {statusLabel[status]}
      </Badge>
      {locked && (
        <Badge variant="outline" className="bg-warning-soft text-warning border-warning/30">
          Locked
        </Badge>
      )}
    </span>
  );
}
