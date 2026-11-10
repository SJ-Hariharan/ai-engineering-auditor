import { Suspense } from "react";
import { AuditReport } from "@/components/report/audit-report";
import { PageLoading } from "@/components/app/common";

export default function AuditPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <AuditReport />
    </Suspense>
  );
}
