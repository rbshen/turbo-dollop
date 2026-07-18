import { cn } from "@/lib/utils";

interface Props {
  children: React.ReactNode;
  className?: string;
}

export function PageContainer({ children, className }: Props) {
  return <div className={cn("max-w-7xl mx-auto px-4", className)}>{children}</div>;
}
