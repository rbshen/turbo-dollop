interface Props {
  mode: "bar" | "line";
  onChange: (mode: "bar" | "line") => void;
}

export function ModeToggle({ mode, onChange }: Props) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-zinc-700 text-xs">
      {(["bar", "line"] as const).map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => onChange(m)}
          className={`px-2.5 py-1 capitalize transition-colors ${
            mode === m ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {m}
        </button>
      ))}
    </div>
  );
}
