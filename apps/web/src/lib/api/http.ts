export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || ""
).replace(/\/$/, "");

type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue>;

type ApiOptions = Omit<RequestInit, "body" | "credentials"> & {
  body?: unknown;
  query?: QueryParams;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function withQuery(path: string, query?: QueryParams): string {
  if (!query) {
    return path;
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

export function apiUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) {
    return pathOrUrl;
  }
  if (pathOrUrl.startsWith("/")) {
    return `${API_BASE_URL}${pathOrUrl}`;
  }
  return `${API_BASE_URL}/${pathOrUrl}`;
}

export async function parseResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

export function errorMessage(status: number, payload: unknown): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as {detail: unknown}).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  if (typeof payload === "string" && payload.trim()) {
    return payload;
  }
  return `Request failed with HTTP ${status}`;
}

export async function request<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const {body: payload, query, ...init} = options;
  const headers = new Headers(init.headers);
  let body: BodyInit | undefined;
  if (payload !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(payload);
  }
  const response = await fetch(`${API_BASE_URL}${withQuery(path, query)}`, {
    ...init,
    body,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const payload = await parseResponse(response);
    throw new ApiError(response.status, errorMessage(response.status, payload), payload);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await parseResponse(response)) as T;
}

export function parseXhrPayload(xhr: XMLHttpRequest): unknown {
  const contentType = xhr.getResponseHeader("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(xhr.responseText || "null");
    } catch {
      return xhr.responseText;
    }
  }
  return xhr.responseText;
}

export function xhrUpload(
  url: string,
  body: Blob,
  options: {
    headers?: HeadersInit;
    withCredentials?: boolean;
    onProgress?: (loaded: number, total: number) => void;
  } = {},
): Promise<XMLHttpRequest> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.withCredentials = Boolean(options.withCredentials);
    new Headers(options.headers).forEach((value, key) => {
      xhr.setRequestHeader(key, value);
    });
    xhr.upload.onprogress = (event) => {
      const total = event.lengthComputable ? event.total : body.size;
      options.onProgress?.(event.loaded, total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr);
        return;
      }
      const payload = parseXhrPayload(xhr);
      reject(new ApiError(xhr.status, errorMessage(xhr.status, payload), payload));
    };
    xhr.onerror = () => reject(new Error("upload failed"));
    xhr.onabort = () => reject(new Error("upload aborted"));
    xhr.send(body);
  });
}
