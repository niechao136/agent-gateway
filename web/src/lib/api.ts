/**
 * 控制层 API 客户端。
 *
 * 鉴权：Bearer JWT，存 localStorage。
 * v2：单一用户体系，token 带 role claim；写操作由后端按归属（owner_id）校验。
 */

const TOKEN_KEY = "ag_token";
const USER_KEY = "ag_user";

export type Role = "user" | "admin";

export interface UserInfo {
  id: number;
  username: string;
  email: string | null;
  display_name: string | null;
  role: Role;
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
  owner_id: number;
  status: "draft" | "published";
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

export function getRole(): Role | null {
  const u = getStoredUser();
  return (u?.role as Role | undefined) ?? null;
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

export function saveSession(token: string, user: UserInfo): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
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
  saveSession(r.access_token, r.user);
  return r;
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  const r = await request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  saveSession(r.access_token, r.user);
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
  return request<Agent[]>("/agents");
}

export async function createAgent(body: {
  slug: string;
  name: string;
  description?: string;
  soul?: string;
  model?: string;
  provider?: string;
  disabled_toolsets?: string[];
  status?: string;
}): Promise<Agent> {
  return request<Agent>("/agents", { method: "POST", body: JSON.stringify(body) });
}

export async function updateAgent(id: number, body: Record<string, unknown>): Promise<Agent> {
  return request<Agent>(`/agents/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteAgent(id: number): Promise<void> {
  return request<void>(`/agents/${id}`, { method: "DELETE" });
}

export async function publishAgent(id: number): Promise<Agent> {
  return request<Agent>(`/agents/${id}/publish`, { method: "POST" });
}

export async function unpublishAgent(id: number): Promise<Agent> {
  return request<Agent>(`/agents/${id}/unpublish`, { method: "POST" });
}

export async function getAgent(id: number): Promise<Agent> {
  return request<Agent>(`/agents/${id}`);
}

// ── 用户管理 ──────────────────────────────────────────────
export interface AdminUser {
  id: number;
  username: string;
  email: string | null;
  display_name: string | null;
  role: Role;
  disabled: boolean;
  created_at: string | null;
  last_login_at: string | null;
  conversation_count: number;
}

export async function listUsers(): Promise<AdminUser[]> {
  return request<AdminUser[]>("/admin/users");
}

export async function updateUser(
  id: number,
  body: { disabled?: boolean; display_name?: string; role?: Role },
): Promise<AdminUser> {
  return request<AdminUser>(`/admin/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

// ── Agent Skills ──────────────────────────────────────────
export interface AgentSkill {
  name: string;
  description: string | null;
  category: string | null;
  enabled: boolean;
  locked: boolean;
  provenance: string | null;
}

export async function listAgentSkills(agentId: number): Promise<AgentSkill[]> {
  return request<AgentSkill[]>(`/agents/${agentId}/skills`);
}

export async function toggleAgentSkill(
  agentId: number,
  name: string,
  enabled: boolean,
): Promise<AgentSkill> {
  return request<AgentSkill>(`/agents/${agentId}/skills/toggle`, {
    method: "POST",
    body: JSON.stringify({ name, enabled }),
  });
}

// ── A2A 端点 ──────────────────────────────────────────────
export interface A2AEndpoint {
  id: number;
  name: string;
  url: string;
  capabilities: string[];
  timeout: number;
  enabled: boolean;
}

export async function listA2AEndpoints(agentId: number): Promise<A2AEndpoint[]> {
  return request<A2AEndpoint[]>(`/agents/${agentId}/a2a`);
}

export async function createA2AEndpoint(
  agentId: number,
  body: { name: string; url: string; capabilities: string[]; timeout: number },
): Promise<{ endpoint: A2AEndpoint; apply_error: string | null }> {
  return request(`/agents/${agentId}/a2a`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteA2AEndpoint(agentId: number, endpointId: number): Promise<void> {
  return request<void>(`/agents/${agentId}/a2a/${endpointId}`, { method: "DELETE" });
}

// ── MCP 服务器 ────────────────────────────────────────────
export interface MCPServer {
  name: string;
  transport: string;
  url: string | null;
  command: string | null;
  args: string[] | null;
  env: Record<string, string> | null;
  enabled: boolean;
  tools?: unknown;
  source?: string | null;
  plugin?: string | null;
}

export async function listMCP(agentId: number): Promise<{ profile: string; servers: MCPServer[] }> {
  return request(`/agents/${agentId}/mcp`);
}

export async function addMCP(
  agentId: number,
  body: {
    name: string;
    transport: string;
    command?: string;
    args?: string[];
    url?: string;
    enabled?: boolean;
  },
): Promise<MCPServer> {
  return request(`/agents/${agentId}/mcp`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteMCP(agentId: number, name: string): Promise<void> {
  return request<void>(`/agents/${agentId}/mcp/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function testMCP(agentId: number, name: string): Promise<Record<string, unknown>> {
  return request(`/agents/${agentId}/mcp/${encodeURIComponent(name)}/test`, {
    method: "POST",
  });
}

export async function toggleMCP(
  agentId: number,
  name: string,
  enabled: boolean,
): Promise<unknown> {
  return request(`/agents/${agentId}/mcp/${encodeURIComponent(name)}/enabled`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

// ── 模型模板 ──────────────────────────────────────────────
export interface ModelTemplate {
  id: number;
  name: string;
  model: string;
  provider: string;
  base_url: string | null;
  has_api_key: boolean;
  description: string | null;
  created_at: string | null;
}

export async function listModelTemplates(): Promise<ModelTemplate[]> {
  return request<ModelTemplate[]>("/models");
}

export async function createModelTemplate(body: {
  name: string;
  model: string;
  provider?: string;
  base_url?: string;
  api_key?: string;
  description?: string;
}): Promise<ModelTemplate> {
  return request<ModelTemplate>("/models", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteModelTemplate(id: number): Promise<void> {
  return request<void>(`/models/${id}`, { method: "DELETE" });
}

export async function applyModelTemplate(
  agentId: number,
  templateId: number,
): Promise<{ applied: boolean; model: string }> {
  return request(`/agents/${agentId}/apply-model/${templateId}`, {
    method: "POST",
  });
}

export async function getEffectiveModel(
  agentId: number,
): Promise<{ profile: string; model: Record<string, unknown> }> {
  return request(`/agents/${agentId}/effective-model`);
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

export async function getMessages(
  id: number,
  limit = 200,
): Promise<{ id: string; role: string; content: string; toolName?: string }[]> {
  const r = await request<{ messages: { id: string; role: string; content: string; toolName?: string }[] }>(
    `/chat/conversations/${id}/messages?limit=${limit}`,
  );
  return r.messages;
}
