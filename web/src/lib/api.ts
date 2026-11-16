/**
 * 控制层 API 客户端。
 *
 * 鉴权：Bearer JWT，存 localStorage。
 * scope 由后端校验：user token 只能访问 /api/chat/*，admin token 访问 /api/admin/*。
 */

const TOKEN_KEY = "ag_token";
const SCOPE_KEY = "ag_scope";
const USER_KEY = "ag_user";

export type Scope = "user" | "admin";

export interface UserInfo {
  id: number;
  username: string;
  email: string | null;
  display_name: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserInfo;
}

export interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  profile_name: string;
  status: "draft" | "published";
  toolset_tier: "public" | "member" | "admin";
  disabled_toolsets: string[];
  gateway_running?: boolean | null;
  profile_exists?: boolean | null;
}

export interface Conversation {
  id: number;
  agent_id: number;
  agent_slug: string | null;
  hermes_session_id: string;
  title: string | null;
  created_at: string;
  last_active_at: string;
}

// ── token 管理 ────────────────────────────────────────────
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function hasToken(): boolean {
  return !!getToken();
}

export function getScope(): Scope | null {
  if (typeof window === "undefined") return null;
  return (localStorage.getItem(SCOPE_KEY) as Scope | null) ?? null;
}

export function getStoredUser(): UserInfo | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserInfo;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: UserInfo, scope: Scope): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(SCOPE_KEY, scope);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(SCOPE_KEY);
  localStorage.removeItem(USER_KEY);
}

// ── 基础请求 ──────────────────────────────────────────────
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`/api${path}`, { ...init, headers });

  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
      location.href = "/login";
    }
    throw new ApiError("登录已失效，请重新登录", 401);
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) {
        detail = body.detail.map((d: { msg?: string }) => d.msg ?? "").join("；");
      }
    } catch {
      /* 非 JSON 响应，保留默认文案 */
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ── 鉴权 API ──────────────────────────────────────────────
export async function register(input: {
  username: string;
  password: string;
  email?: string;
  display_name?: string;
}): Promise<TokenResponse> {
  const r = await request<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
  saveSession(r.access_token, r.user, "user");
  return r;
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  const r = await request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  saveSession(r.access_token, r.user, "user");
  return r;
}

export async function me(): Promise<UserInfo> {
  return request<UserInfo>("/auth/me");
}

export function logout(): void {
  clearSession();
}

// ── Agent ────────────────────────────────────────────────
export async function listVisibleAgents(): Promise<Agent[]> {
  return request<Agent[]>("/chat/agents");
}

export async function listAllAgents(): Promise<Agent[]> {
  return request<Agent[]>("/admin/agents");
}

export async function createAgent(body: {
  slug: string;
  name: string;
  description?: string;
  soul?: string;
  model?: string;
  provider?: string;
  toolset_tier?: string;
  status?: string;
}): Promise<Agent> {
  return request<Agent>("/admin/agents", { method: "POST", body: JSON.stringify(body) });
}

export async function updateAgent(id: number, body: Record<string, unknown>): Promise<Agent> {
  return request<Agent>(`/admin/agents/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteAgent(id: number): Promise<void> {
  return request<void>(`/admin/agents/${id}`, { method: "DELETE" });
}

export async function publishAgent(id: number): Promise<Agent> {
  return request<Agent>(`/admin/agents/${id}/publish`, { method: "POST" });
}

export async function unpublishAgent(id: number): Promise<Agent> {
  return request<Agent>(`/admin/agents/${id}/unpublish`, { method: "POST" });
}

// ── 会话 ──────────────────────────────────────────────────
export async function listConversations(agentSlug?: string): Promise<Conversation[]> {
  const q = agentSlug ? `?agent_slug=${encodeURIComponent(agentSlug)}` : "";
  return request<Conversation[]>(`/chat/conversations${q}`);
}

export async function createConversation(
  agentSlug: string,
  firstMessage?: string,
): Promise<Conversation> {
  return request<Conversation>("/chat/conversations", {
    method: "POST",
    body: JSON.stringify({ agent_slug: agentSlug, first_message: firstMessage }),
  });
}

export async function getConversation(id: number): Promise<Conversation> {
  return request<Conversation>(`/chat/conversations/${id}`);
}

export async function deleteConversation(id: number): Promise<void> {
  return request<void>(`/chat/conversations/${id}`, { method: "DELETE" });
}

export async function getMessages(id: number, limit = 100): Promise<unknown[]> {
  const r = await request<{ messages: unknown[] }>(
    `/chat/conversations/${id}/messages?limit=${limit}`,
  );
  return r.messages;
}
