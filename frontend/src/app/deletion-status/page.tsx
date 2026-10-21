import { Suspense } from "react";
import { DeletionStatus } from "@/components/deletion-status";
export default function Page() {
  return (
    <Suspense>
      <DeletionStatus />
    </Suspense>
  );
}
