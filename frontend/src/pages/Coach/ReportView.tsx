import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function ReportView({ markdown }: { markdown: string }) {
  return (
    <div className="max-w-none text-[color:var(--foreground)] [&_p]:text-[color:var(--muted)] [&_li]:text-[color:var(--muted)] [&_strong]:text-[color:var(--foreground)] [&_code]:rounded [&_code]:bg-[color:var(--surface-raised)] [&_code]:px-1 [&_pre]:bg-[color:var(--surface-raised)] [&_pre]:p-3 [&_pre]:rounded-md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  );
}
