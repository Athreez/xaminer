import { LogOut, MonitorX } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { logout, logoutEverywhere, useSession } from "@/auth/hooks";
import { Button } from "@/components/ui/button";

/** Who is logged in, with log out and log out everywhere (PRD AUTH-04). */
export function UserMenu({ compact = false }: { compact?: boolean }) {
  const session = useSession();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  if (session.status !== "authenticated") return null;
  const { user } = session;

  async function leave(everywhere: boolean) {
    await (everywhere ? logoutEverywhere() : logout());
    navigate("/login", {
      replace: true,
      state: {
        notice: everywhere ? "You're logged out on every device." : "You're logged out.",
      },
    });
  }

  return (
    <div className={compact ? "flex items-center gap-2" : "space-y-2"}>
      <div className={compact ? "hidden text-right sm:block" : "px-3"}>
        <p className="text-sm font-semibold">{user.full_name}</p>
        <p className="text-muted-foreground text-xs">{user.institution_name}</p>
      </div>
      {confirming ? (
        <div role="group" aria-label="Log out on every device?" className="space-y-2 px-1">
          <p className="text-sm">Log out on every device?</p>
          <div className="flex gap-2">
            <Button size="sm" variant="destructive" onClick={() => void leave(true)}>
              Yes, everywhere
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className={compact ? "flex gap-1" : "flex flex-col gap-1"}>
          <Button
            variant="ghost"
            size="sm"
            className="justify-start"
            onClick={() => void leave(false)}
          >
            <LogOut /> Log out
          </Button>
          {!compact && (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground justify-start"
              onClick={() => setConfirming(true)}
            >
              <MonitorX /> Log out everywhere
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
