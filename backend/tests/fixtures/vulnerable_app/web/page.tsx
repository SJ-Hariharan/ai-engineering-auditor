import { util } from "./missing-module";

export function Comment({ body }: { body: string }) {
  return <div dangerouslySetInnerHTML={{ __html: body }} />;
}

export function render(el: HTMLElement, html: string) {
  el.innerHTML = html;
  const key = process.env.NEXT_PUBLIC_OPENAI_API_KEY;
  try {
    eval(html);
  } catch (e) {}
  return key;
}
