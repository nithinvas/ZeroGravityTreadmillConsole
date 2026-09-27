// Small fetch helpers: every failure becomes an Error carrying the backend's message.

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as T;
}

export async function postJson<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as T;
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    // not JSON
  }
  return `Request failed (${res.status})`;
}

/** Waits `ms`, so a capture averages only readings taken after the weight was placed. */
export const settle = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
