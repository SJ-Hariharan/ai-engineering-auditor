"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { GitBranch, FileArchive } from "lucide-react";
import { api } from "@/lib/api";
import { useAction } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ErrorNote, Panel } from "@/components/app/common";
import { ZipDropzone } from "@/components/app/zip-dropzone";
import type { ProjectDetail } from "@/lib/types";

export function NewAuditPanel() {
  const router = useRouter();
  const [tab, setTab] = useState<string>("github");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");

  const go = (p: ProjectDetail) => {
    const a = p.audits[0] ?? p.latest_audit;
    router.push(a ? `/audits/${a.id}` : `/projects/${p.id}`);
  };
  const gh = useAction(async () => go(await api.createGithubProject(url.trim(), branch.trim() || undefined)));
  const zip = useAction(async () => {
    if (file) go(await api.uploadProject(file, name.trim() || undefined));
  });

  return (
    <Panel className="p-4">
      <h2 className="mb-3 text-sm font-semibold">New audit</h2>
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="github"><GitBranch /> GitHub URL</TabsTrigger>
          <TabsTrigger value="zip"><FileArchive /> ZIP upload</TabsTrigger>
        </TabsList>
        <TabsContent value="github" className="pt-3">
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              void gh.run();
            }}
          >
            <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
              <div className="space-y-1.5">
                <Label htmlFor="gh-url">Repository URL</Label>
                <Input
                  id="gh-url"
                  type="url"
                  required
                  placeholder="https://github.com/owner/repo"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="gh-branch">Branch (optional)</Label>
                <Input id="gh-branch" placeholder="default branch" value={branch} onChange={(e) => setBranch(e.target.value)} />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">Public repositories are cloned read-only.</p>
            <ErrorNote error={gh.error} />
            <Button type="submit" disabled={gh.pending || !url.trim()}>
              {gh.pending ? "Starting…" : "Start audit"}
            </Button>
          </form>
        </TabsContent>
        <TabsContent value="zip" className="pt-3">
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              void zip.run();
            }}
          >
            <ZipDropzone file={file} onFile={setFile} disabled={zip.pending} />
            <div className="space-y-1.5 sm:max-w-xs">
              <Label htmlFor="zip-name">Project name (optional)</Label>
              <Input id="zip-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="defaults to the file name" />
            </div>
            <ErrorNote error={zip.error} />
            <Button type="submit" disabled={zip.pending || !file}>
              {zip.pending ? "Uploading…" : "Upload and audit"}
            </Button>
          </form>
        </TabsContent>
      </Tabs>
    </Panel>
  );
}
