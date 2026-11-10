"use client";

import { useRef, useState } from "react";
import { FileArchive, Upload, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export const MAX_ZIP_BYTES = 50 * 1024 * 1024;

export function validateZip(f: File): string | null {
  if (!f.name.toLowerCase().endsWith(".zip")) return "Only .zip files are supported.";
  if (f.size > MAX_ZIP_BYTES) return `File is ${(f.size / 1048576).toFixed(1)} MB; the limit is 50 MB.`;
  if (f.size === 0) return "File is empty.";
  return null;
}

export function ZipDropzone({
  file,
  onFile,
  disabled,
}: {
  file: File | null;
  onFile: (f: File | null) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const take = (f: File | undefined) => {
    if (!f) return;
    const err = validateZip(f);
    setError(err);
    onFile(err ? null : f);
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!disabled) take(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center transition-colors",
          over ? "border-brand bg-brand/5" : "bg-muted/20",
        )}
      >
        {file ? (
          <div className="flex items-center gap-2 text-sm">
            <FileArchive className="size-4 text-muted-foreground" aria-hidden />
            <span className="font-mono break-all">{file.name}</span>
            <span className="text-muted-foreground">({(file.size / 1048576).toFixed(2)} MB)</span>
            <Button variant="ghost" size="icon-xs" onClick={() => onFile(null)} aria-label="Remove file" disabled={disabled}>
              <X />
            </Button>
          </div>
        ) : (
          <>
            <Upload className="size-5 text-muted-foreground" aria-hidden />
            <p className="text-sm">Drag and drop a .zip here, or</p>
            <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => inputRef.current?.click()}>
              Choose file
            </Button>
            <p className="text-xs text-muted-foreground">Maximum 50 MB</p>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            take(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-sev-critical">
          {error}
        </p>
      )}
    </div>
  );
}
