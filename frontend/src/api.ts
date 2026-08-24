export type CurrentUser = {
  id: number;
  username: string;
  display_name: string;
  company_id: number | null;
  department_id: number | null;
  status: string;
  is_superuser: boolean;
  must_change_password: boolean;
  permissions: string[];
};
export type Entity = Record<string, unknown> & { id: number };
type ApiErrorBody = {
  detail?: string;
  message?: string;
  code?: string;
  details?: Record<string, unknown>;
  captcha_required?: boolean;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: ApiErrorBody,
  ) {
    const fieldMessage = body.details
      ? Object.entries(body.details)
          .map(
            ([field, value]) =>
              `${field}：${Array.isArray(value) ? value.join("；") : String(value)}`,
          )
          .join("；")
      : "";
    super(
      body.detail ||
        fieldMessage ||
        body.message ||
        (status === 403 ? "没有权限执行此操作。" : "请求失败，请稍后重试。"),
    );
  }
}

function cookie(name: string): string {
  const item = document.cookie
    .split("; ")
    .find((part) => part.startsWith(`${name}=`));
  return item ? decodeURIComponent(item.slice(name.length + 1)) : "";
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const csrf = cookie("csrftoken");
  if (
    !headers.has("X-CSRFToken") &&
    csrf &&
    init.method &&
    init.method !== "GET"
  )
    headers.set("X-CSRFToken", csrf);
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok)
    throw new ApiError(
      response.status,
      (await response.json().catch(() => ({}))) as ApiErrorBody,
    );
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function currentUser(): Promise<CurrentUser | null> {
  try {
    return (await request<{ user: CurrentUser }>("/api/v1/auth/me/")).user;
  } catch (error) {
    if (error instanceof ApiError && [401, 403].includes(error.status))
      return null;
    throw error;
  }
}
export async function login(
  username: string,
  password: string,
  captcha = "",
): Promise<CurrentUser> {
  const { csrf_token } = await request<{ csrf_token: string }>(
    "/api/v1/auth/session/",
  );
  return (
    await request<{ user: CurrentUser }>("/api/v1/auth/login/", {
      method: "POST",
      headers: { "X-CSRFToken": csrf_token },
      body: JSON.stringify({ username, password, captcha }),
    })
  ).user;
}
export async function logout(): Promise<void> {
  await request("/api/v1/auth/logout/", { method: "POST" });
}
export async function listEntities(path: string): Promise<Entity[]> {
  const response = await request<{ results?: Entity[] } | Entity[]>(path);
  return Array.isArray(response) ? response : response.results || [];
}
export async function postAction<T = Entity>(
  path: string,
  body: Record<string, unknown> = {},
): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}
export async function createEntity(
  path: string,
  body: Record<string, unknown>,
): Promise<Entity> {
  return request<Entity>(path, { method: "POST", body: JSON.stringify(body) });
}
export async function updateEntity(
  path: string,
  id: number,
  body: Record<string, unknown>,
): Promise<Entity> {
  return request<Entity>(`${path}${id}/`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}
export async function getDashboard(): Promise<Record<string, number>> {
  return request("/api/v1/analytics/reports/dashboard/");
}
