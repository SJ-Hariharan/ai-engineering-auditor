"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAction } from "@/hooks/use-api";
import type { ProjectDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorNote, Panel } from "@/components/app/common";
import { useApp } from "@/components/app/app-context";
import { formatDate } from "@/lib/format";

export function ConsentDialog({
  open,
  onOpenChange,
  onConfirm,
  pending,
  error,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onConfirm: () => void;
  pending: boolean;
  error: Error | null;
}) {
  const { ai } = useApp();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Allow AI features for this project?</DialogTitle>
          <DialogDescription>Please read what this changes before you agree.</DialogDescription>
        </DialogHeader>
        <ul className="list-disc space-y-2 pl-5 text-sm">
          <li>
            Redacted code excerpts (files, symbols, findings) will be sent to the configured provider
            {ai && ai.provider !== "none" ? (
              <>
                : <strong>{ai.provider}</strong> / <code className="font-mono text-xs">{ai.model}</code>
                {!ai.configured && " (not currently configured with an API key)"}
              </>
            ) : (
              <> (no provider is configured on this server right now, so nothing will be sent until one is)</>
            )}
            .
          </li>
          <li>Detected secrets are redacted before anything leaves the server.</li>
          <li>AI output is always labelled as AI-generated. AI never creates findings or changes the score.</li>
          <li>You can turn this off at any time from the project settings.</li>
        </ul>
        <ErrorNote error={error} />
        <DialogFooter className="mt-2 flex-col gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={onConfirm} disabled={pending}>{pending ? "Saving…" : "Enable AI features"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ProjectSettings({ project, onChange }: { project: ProjectDetail; onChange: (p: ProjectDetail) => void }) {
  const router = useRouter();
  const { ai } = useApp();
  const [name, setName] = useState(project.name);
  const [consentOpen, setConsentOpen] = useState(false);
  const [delOpen, setDelOpen] = useState(false);

  const rename = useAction(async () => onChange(await api.updateProject(project.id, { name: name.trim() })));
  const consent = useAction(async (v: boolean) => {
    onChange(await api.updateProject(project.id, { llm_consent: v }));
    setConsentOpen(false);
  });
  const del = useAction(async () => {
    await api.deleteProject(project.id);
    router.replace("/");
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">Project name</h3>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void rename.run();
          }}
        >
          <Label htmlFor="proj-name" className="sr-only">Project name</Label>
          <Input id="proj-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
          <Button type="submit" variant="outline" disabled={rename.pending || !name.trim() || name.trim() === project.name}>
            Rename
          </Button>
        </form>
        <ErrorNote error={rename.error} />
      </Panel>

      <Panel className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">AI features</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Explanations, learning questions and AI-written fixes. Off by default.
              {project.llm_consent && project.llm_consent_at && ` Enabled ${formatDate(project.llm_consent_at)}.`}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Provider: {ai ? (ai.provider === "none" ? "none configured" : `${ai.provider} / ${ai.model}${ai.configured ? "" : " (no API key)"}`) : "unknown"}
            </p>
          </div>
          <Switch
            checked={project.llm_consent}
            aria-label="Allow AI features"
            disabled={consent.pending}
            onCheckedChange={(v) => {
              if (v) setConsentOpen(true);
              else void consent.run(false);
            }}
          />
        </div>
        {!consentOpen && <ErrorNote error={consent.error} />}
      </Panel>

      <Panel className="space-y-3 border-sev-critical/30 p-4 lg:col-span-2">
        <h3 className="text-sm font-semibold">Danger zone</h3>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">Deleting a project removes all of its audits, findings, fixes and the stored source. This cannot be undone.</p>
          <Button variant="destructive" onClick={() => setDelOpen(true)}>Delete project</Button>
        </div>
      </Panel>

      <ConsentDialog
        open={consentOpen}
        onOpenChange={setConsentOpen}
        onConfirm={() => void consent.run(true)}
        pending={consent.pending}
        error={consent.error}
      />
      <Dialog open={delOpen} onOpenChange={setDelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete “{project.name}”?</DialogTitle>
            <DialogDescription>All audits, findings, fixes and stored source for this project will be permanently deleted.</DialogDescription>
          </DialogHeader>
          <ErrorNote error={del.error} />
          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={() => setDelOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={del.pending} onClick={() => void del.run()}>
              {del.pending ? "Deleting…" : "Delete permanently"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
