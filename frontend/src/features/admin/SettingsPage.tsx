import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { Field, FormMessage } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

import { errorText, unwrap } from "./lib";
import { Busy, ErrorState, LoadingRows, PageHeader } from "./shared";

type Settings = components["schemas"]["InstitutionSettings"];

/**
 * Institution settings (FRONTEND_SPEC § 5.1, PRD PRC-13). The "overdue evidence deletions" line
 * arrives with the retention job (TCK-1107).
 */
export function SettingsPage() {
  const settings = useQuery({
    queryKey: ["institution-settings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/institution/settings")),
  });

  if (settings.isPending) return <LoadingRows rows={4} />;
  if (settings.isError) {
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  }
  return <SettingsForm settings={settings.data} />;
}

function SettingsForm({ settings }: { settings: Settings }) {
  const queryClient = useQueryClient();
  const [days, setDays] = useState(String(settings.evidence_retention_days));
  const [consent, setConsent] = useState(settings.default_consent_text ?? "");
  const [saved, setSaved] = useState(false);

  const dayCount = Number(days);
  const daysError =
    days === "" || !Number.isInteger(dayCount) || dayCount < 7 || dayCount > 90
      ? "Enter a whole number of days from 7 to 90."
      : undefined;
  const changed =
    dayCount !== settings.evidence_retention_days ||
    consent.trim() !== (settings.default_consent_text ?? "");

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/institution/settings", {
          body: {
            evidence_retention_days: dayCount,
            default_consent_text: consent.trim() || null,
          },
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(["institution-settings"], updated);
      setConsent(updated.default_consent_text ?? "");
      setSaved(true);
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaved(false);
    save.mutate();
  }

  return (
    <section className="max-w-2xl">
      <PageHeader
        title="Settings"
        description={`${settings.name} · Time zone ${settings.timezone}`}
      />
      <form
        onSubmit={onSubmit}
        className="bg-card shadow-card space-y-6 rounded-xl border p-6"
        noValidate
      >
        {saved && !changed && <FormMessage tone="success">Settings saved.</FormMessage>}
        {save.isError && <FormMessage tone="error">{errorText(save.error)}</FormMessage>}

        <div className="space-y-2">
          <Field label="Keep proctoring images for (days)" error={daysError}>
            {(props) => (
              <Input
                {...props}
                type="number"
                inputMode="numeric"
                min={7}
                max={90}
                className="w-32"
                value={days}
                onChange={(e) => setDays(e.target.value)}
              />
            )}
          </Field>
          <p className="text-muted-foreground text-sm">
            Webcam images are deleted automatically this many days after an exam closes (7 to 90).
            The event records stay, without images.
          </p>
        </div>

        <div className="space-y-2">
          <Field label="Default consent text">
            {(props) => (
              <Textarea
                {...props}
                rows={6}
                maxLength={5000}
                placeholder="Leave empty to use Xaminer's standard text."
                value={consent}
                onChange={(e) => setConsent(e.target.value)}
              />
            )}
          </Field>
          <p className="text-muted-foreground text-sm">
            Students read and accept this before a proctored exam. A teacher can set different text
            for one exam.
          </p>
        </div>

        <Button type="submit" disabled={!changed || Boolean(daysError) || save.isPending}>
          <Busy busy={save.isPending}>Save settings</Busy>
        </Button>
      </form>
    </section>
  );
}
