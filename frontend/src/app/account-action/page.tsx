import { Suspense } from "react";
import { AccountAction } from "@/components/account-action";
export default function Page() {
  return (
    <Suspense>
      <AccountAction />
    </Suspense>
  );
}
