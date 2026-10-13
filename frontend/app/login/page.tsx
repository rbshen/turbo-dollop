import { Suspense } from "react";

import { LoginForm } from "@/components/auth/LoginForm";

export default function LoginPage() {
  // useSearchParams (the `next` parameter) needs a Suspense boundary on a prerendered page.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
