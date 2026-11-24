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
export const API_BASE = "/api";

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

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

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

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ ok: boolean }> {
  return request("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
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

/** 管理列表：admin 全部 / 普通用户自己的（别名统一各页面调用）。 */
export async function listAgents(): Promise<Agent[]> {
  return request<Agent[]>("/agents");
}

export async function getAgent(id: number): Promise<Agent> {  return request<Agent>(`/agents/${id}`);
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

// ── 自定义 Skill（批次 2）────────────────────────────────
export interface CustomSkill {
  id: number;
  name: string;
  owner_id: number;
  description: string | null;
  is_shared: boolean;
  bound_agents: number[];
}

export async function listSkills(): Promise<CustomSkill[]> {
  return request<CustomSkill[]>("/skills");
}

export interface SkillDetail extends CustomSkill {
  content: string;
  files: Record<string, string> | null;
}

export async function getSkill(id: number): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${id}`);
}

export async function createSkill(body: {
  name: string;
  description?: string;
  content: string;
  files?: Record<string, string>;
  is_shared?: boolean;
}): Promise<CustomSkill> {
  return request<CustomSkill>("/skills", { method: "POST", body: JSON.stringify(body) });
}

export async function updateSkill(
  id: number,
  body: { description?: string; content?: string; files?: Record<string, string>; is_shared?: boolean },
): Promise<CustomSkill> {
  return request<CustomSkill>(`/skills/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteSkill(id: number, force = false): Promise<void> {
  return request<void>(`/skills/${id}${force ? "?force=true" : ""}`, { method: "DELETE" });
}

// ── 内置 Skill（批次 2）──────────────────────────────────
export interface BuiltinSkill {
  name: string;
  description: string | null;
  enabled: boolean;
}

export async function listBuiltinSkills(): Promise<BuiltinSkill[]> {
  return request<BuiltinSkill[]>("/skills/builtin");
}

/** 某 Agent 的内置 Skill 选择（默认全不选）。 */
export interface AgentBuiltinSkill {
  name: string;
  description: string | null;
  selected: boolean;
}

export async function listAgentBuiltinSkills(
  agentId: number,
): Promise<{ agent_id: number; profile: string; skills: AgentBuiltinSkill[] }> {
  return request(`/agents/${agentId}/skills/builtin`);
}

export async function setAgentBuiltinSkills(
  agentId: number,
  skillNames: string[],
): Promise<{ agent_id: number; selected: string[]; changed: string[]; errors: string[] }> {
  return request(`/agents/${agentId}/skills/builtin`, {
    method: "PUT",
    body: JSON.stringify({ skill_names: skillNames }),
  });
}

export async function toggleBuiltinSkill(
  name: string,
  enabled: boolean,
  affectedAgentIds: number[],
): Promise<{ name: string; enabled: boolean; agents: { agent_id: number; ok: boolean; error?: string }[]; errors: string[] }> {
  return request(`/skills/builtin/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ enabled, affected_agent_ids: affectedAgentIds }),
  });
}

export async function bindAgentSkills(
  agentId: number,
  skillIds: number[],
): Promise<{ bound: number; sync: Record<string, unknown> }> {
  return request(`/agents/${agentId}/skills`, {
    method: "PUT",
    body: JSON.stringify({ skill_ids: skillIds }),
  });
}

export async function listAgentSkillBindings(
  agentId: number,
): Promise<{ agent_id: number; profile: string; bound: CustomSkill[] }> {
  return request(`/agents/${agentId}/skills`);
}

// ── toolset catalog（批次 2）─────────────────────────────
export interface ToolsetCatalogItem {
  name: string;
  risk?: string;
  tools: string[];
}

export async function getToolsetCatalog(): Promise<{
  source: "dashboard" | "static";
  toolsets: ToolsetCatalogItem[];
}> {
  return request("/toolsets");
}

// ── MCP 服务器（批次 2 独立表）───────────────────────────
export type AuthType = "none" | "bearer" | "header" | "query" | "basic";

export interface MCPServer {
  id: number;
  name: string;
  owner_id: number;
  description: string | null;
  transport: "stdio" | "sse" | "http" | "streamable_http";
  command: string | null;
  args: string[] | null;
  env: Record<string, string> | null;
  url: string | null;
  auth_type: AuthType;
  has_token: boolean;
  auth_name: string | null;
  is_shared: boolean;
  enabled: boolean;
}

export interface MCPBody {
  name: string;
  description?: string;
  transport?: MCPServer["transport"];
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  auth_type?: AuthType;
  token?: string;
  auth_name?: string;
  is_shared?: boolean;
  enabled?: boolean;
}

export async function listMCPServers(): Promise<MCPServer[]> {
  return request<MCPServer[]>("/mcp");
}

export async function createMCPServer(body: MCPBody): Promise<MCPServer> {
  return request<MCPServer>("/mcp", { method: "POST", body: JSON.stringify(body) });
}

export async function updateMCPServer(
  id: number,
  body: Partial<MCPBody> & { token?: string },
): Promise<MCPServer> {
  return request<MCPServer>(`/mcp/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteMCPServer(id: number, force = false): Promise<void> {
  return request<void>(`/mcp/${id}${force ? "?force=true" : ""}`, { method: "DELETE" });
}

export async function testMCPServer(id: number): Promise<Record<string, unknown>> {
  return request(`/mcp/${id}/test`, { method: "POST" });
}

export interface AgentMCPBindings {
  agent_id: number;
  profile: string;
  bound: MCPServer[];
  effective_in_profile: unknown;
}

export async function getAgentMCP(agentId: number): Promise<AgentMCPBindings> {
  return request(`/agents/${agentId}/mcp`);
}

export async function setAgentMCP(
  agentId: number,
  mcpServerIds: number[],
): Promise<{ bound: number; sync: Record<string, unknown> }> {
  return request(`/agents/${agentId}/mcp`, {
    method: "PUT",
    body: JSON.stringify({ mcp_server_ids: mcpServerIds }),
  });
}

export async function createAndBindMCP(
  agentId: number,
  body: MCPBody,
): Promise<{ created: boolean; server: MCPServer; sync: Record<string, unknown> }> {
  return request(`/agents/${agentId}/mcp/create-and-bind`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ── A2A 出站端点（批次 2 独立表）─────────────────────────
export interface A2AEndpoint {
  id: number;
  name: string;
  owner_id: number;
  description: string | null;
  target_type: "external" | "internal";
  target_agent_id: number | null;
  url: string;
  capabilities: string[] | null;
  timeout: number;
  auth_type: AuthType;
  has_token: boolean;
  auth_name: string | null;
  is_shared: boolean;
  enabled: boolean;
}

export interface A2AEndpointBody {
  name: string;
  description?: string;
  url?: string;
  target_type?: "external" | "internal";
  target_agent_id?: number | null;
  capabilities?: string[];
  timeout?: number;
  auth_type?: AuthType;
  token?: string;
  auth_name?: string;
  is_shared?: boolean;
  enabled?: boolean;
}

/** 已发布的 Agent（供 A2A 内部互调选择目标） */
export async function listPublishedAgents(): Promise<Agent[]> {
  return request<Agent[]>("/chat/agents");
}

export async function testA2AEndpoint(id: number): Promise<{ ok: boolean; name?: string; url?: string; message?: string }> {
  return request(`/a2a/endpoints/${id}/test`, { method: "POST" });
}

export async function listA2AEndpoints(): Promise<A2AEndpoint[]> {
  return request<A2AEndpoint[]>("/a2a/endpoints");
}

export async function createA2AEndpoint(body: A2AEndpointBody): Promise<A2AEndpoint> {
  return request<A2AEndpoint>("/a2a/endpoints", { method: "POST", body: JSON.stringify(body) });
}

export async function updateA2AEndpoint(
  id: number,
  body: Partial<A2AEndpointBody>,
): Promise<A2AEndpoint> {
  return request<A2AEndpoint>(`/a2a/endpoints/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteA2AEndpoint(id: number, force = false): Promise<void> {
  return request<void>(`/a2a/endpoints/${id}${force ? "?force=true" : ""}`, { method: "DELETE" });
}

export interface AgentA2ABindings {
  agent_id: number;
  profile: string;
  bound: A2AEndpoint[];
  effective_in_profile: unknown;
}

export async function getAgentA2A(agentId: number): Promise<AgentA2ABindings> {
  return request(`/agents/${agentId}/a2a`);
}

export async function setAgentA2A(
  agentId: number,
  endpointIds: number[],
): Promise<{ bound: number; sync: Record<string, unknown> }> {
  return request(`/agents/${agentId}/a2a`, {
    method: "PUT",
    body: JSON.stringify({ endpoint_ids: endpointIds }),
  });
}

export async function createAndBindA2A(
  agentId: number,
  body: A2AEndpointBody,
): Promise<{ created: boolean; endpoint: A2AEndpoint; sync: Record<string, unknown> }> {
  return request(`/agents/${agentId}/a2a/create-and-bind`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface A2AInboundStatus {
  ok?: boolean;
  [k: string]: unknown;
}

export async function getA2AInbound(): Promise<A2AInboundStatus> {
  return request("/a2a/inbound");
}

export async function pingA2AInbound(): Promise<A2AInboundStatus> {
  return request("/a2a/inbound/ping", { method: "POST" });
}

// ── 连接器（批次 3）──────────────────────────────────────
export type ConnectorPlatform = "telegram" | "feishu" | "slack";

export interface ConnectorRuntime {
  state: "idle" | "connecting" | "connected" | "error" | "stopped";
  last_error: string | null;
  last_connected_at: number | null;
  messages_in: number;
  messages_out: number;
}

export interface Connector {
  id: number;
  name: string;
  owner_id: number;
  platform: ConnectorPlatform;
  agent_id: number;
  agent_slug?: string | null;
  credentials: Record<string, string>;
  enabled: boolean;
  runtime?: ConnectorRuntime | null;
}

const PLATFORM_CREDENTIALS: Record<ConnectorPlatform, string[]> = {
  telegram: ["bot_token"],
  feishu: ["app_id", "app_secret"],
  slack: ["app_token", "bot_token"],
};

export function platformCredentialFields(p: ConnectorPlatform): string[] {
  return PLATFORM_CREDENTIALS[p];
}

export async function listConnectors(): Promise<Connector[]> {
  return request<Connector[]>("/connectors");
}

export async function createConnector(body: {
  name: string;
  platform: ConnectorPlatform;
  agent_id: number;
  credentials: Record<string, string>;
  enabled?: boolean;
}): Promise<Connector> {
  return request<Connector>("/connectors", { method: "POST", body: JSON.stringify(body) });
}

export async function updateConnector(
  id: number,
  body: { name?: string; agent_id?: number; credentials?: Record<string, string>; enabled?: boolean },
): Promise<Connector> {
  return request<Connector>(`/connectors/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteConnector(id: number): Promise<void> {
  return request<void>(`/connectors/${id}`, { method: "DELETE" });
}

export async function restartConnector(id: number): Promise<unknown> {
  return request(`/connectors/${id}/restart`, { method: "POST" });
}

export async function testConnector(id: number): Promise<Record<string, unknown>> {
  return request(`/connectors/${id}/test`, { method: "POST" });
}

/** SSE 订阅连接器状态变更（批次 4 决策：SSE 推送）。 */
export function subscribeConnectorStatus(
  onMessage: (connectors: Connector[]) => void,
): () => void {
  const es = new EventSource(`${API_BASE}/connectors/events`, { withCredentials: false });
  es.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch {
      /* 忽略坏帧 */
    }
  };
  return () => es.close();
}

// ── Agent API Key（批次 3）───────────────────────────────
export interface AgentAPIKey {
  id: number;
  agent_id: number;
  name: string;
  key_prefix: string;
  enabled: boolean;
  created_at: string | null;
  last_used_at: string | null;
}

export interface AgentAPIKeyCreated extends AgentAPIKey {
  key: string; // 明文仅此一次
}

export async function listAgentAPIKeys(agentId: number): Promise<AgentAPIKey[]> {
  return request<AgentAPIKey[]>(`/agents/${agentId}/api-keys`);
}

export async function createAgentAPIKey(
  agentId: number,
  name: string,
): Promise<AgentAPIKeyCreated> {
  return request<AgentAPIKeyCreated>(`/agents/${agentId}/api-keys`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function updateAgentAPIKey(
  agentId: number,
  keyId: number,
  body: { enabled?: boolean; name?: string },
): Promise<AgentAPIKey> {
  return request<AgentAPIKey>(`/agents/${agentId}/api-keys/${keyId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteAgentAPIKey(agentId: number, keyId: number): Promise<void> {
  return request<void>(`/agents/${agentId}/api-keys/${keyId}`, { method: "DELETE" });
}

// ── 模型模板 ──────────────────────────────────────────────
export interface ModelTemplate {
  id: number;
  name: string;
  owner_id: number;
  model: string;
  provider: string;
  base_url: string | null;
  has_api_key: boolean;
  description: string | null;
  is_shared: boolean;
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
  is_shared?: boolean;
}): Promise<ModelTemplate> {
  return request<ModelTemplate>("/models", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface ModelTestResult {
  ok: boolean;
  detail: string;
  status?: number;
  models?: string[];
}

export async function testModelTemplate(id: number): Promise<ModelTestResult> {
  return request(`/models/${id}/test`, { method: "POST" });
}

export async function updateModelTemplate(
  id: number,
  body: {
    model?: string;
    provider?: string;
    base_url?: string;
    api_key?: string;
    description?: string;
    is_shared?: boolean;
  },
): Promise<ModelTemplate> {
  return request<ModelTemplate>(`/models/${id}`, {
    method: "PATCH",
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

// ── 知识库（RAGFlow）──────────────────────────────────────
export interface RagflowSite {
  id: number;
  name: string;
  base_url: string;
  has_api_key: boolean;
  is_shared: boolean;
  enabled: boolean;
}

export interface RagflowSiteDetail extends RagflowSite {
  api_key_masked: string;
}

export interface KnowledgeBase {
  id: number;
  name: string;
  owner_id: number;
  site_id: number;
  site_name: string;
  description: string | null;
  source: string;
  has_api_key: boolean;
  dataset_id: string | null;
  dataset_name: string | null;
  is_shared: boolean;
  enabled: boolean;
}

export interface DatasetItem {
  id: string;
  name: string;
}

export function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  return request("/knowledge");
}

export function createKnowledgeBase(body: {
  name: string;
  site_id: number;
  description?: string;
  dataset_id?: string;
  dataset_name?: string;
  is_shared?: boolean;
  enabled?: boolean;
}): Promise<KnowledgeBase> {
  return request("/knowledge", { method: "POST", body: JSON.stringify(body) });
}

// ── RAGFlow 站点 ─────────────────────────────────────────
export function listRagflowSites(): Promise<RagflowSite[]> {
  return request("/knowledge/sites");
}
export function getRagflowSite(id: number): Promise<RagflowSiteDetail> {
  return request(`/knowledge/sites/${id}`);
}
export function createRagflowSite(body: {
  name: string;
  base_url: string;
  api_key: string;
  is_shared?: boolean;
  enabled?: boolean;
}): Promise<RagflowSite> {
  return request("/knowledge/sites", { method: "POST", body: JSON.stringify(body) });
}
export function updateRagflowSite(id: number, body: Record<string, unknown>): Promise<RagflowSite> {
  return request(`/knowledge/sites/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}
export function deleteRagflowSite(id: number, force = false): Promise<void> {
  return request(`/knowledge/sites/${id}${force ? "?force=true" : ""}`, { method: "DELETE" });
}
export function testRagflowSite(id: number): Promise<{ ok: boolean; message: string }> {
  return request(`/knowledge/sites/${id}/test`, { method: "POST" });
}
export function listSiteDatasets(id: number): Promise<DatasetItem[]> {
  return request(`/knowledge/sites/${id}/datasets`);
}

export function updateKnowledgeBase(
  id: number,
  body: Record<string, unknown>,
): Promise<KnowledgeBase> {
  return request(`/knowledge/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteKnowledgeBase(id: number, force = false): Promise<void> {
  return request(`/knowledge/${id}${force ? "?force=true" : ""}`, { method: "DELETE" });
}

export function listRagflowDatasets(body: {
  base_url: string;
  api_key: string;
}): Promise<{ datasets: DatasetItem[] }> {
  const q = new URLSearchParams({ base_url: body.base_url, api_key: body.api_key });
  return request<DatasetItem[]>(`/knowledge/list-datasets?${q.toString()}`).then((datasets) => ({
    datasets,
  }));
}

export function testKnowledgeBase(id: number): Promise<{ ok: boolean; message: string }> {
  return request(`/knowledge/${id}/test`, { method: "POST" });
}

export function getAgentKnowledge(agentId: number): Promise<KnowledgeBase[]> {
  return request(`/agents/${agentId}/knowledge`);
}

export function setAgentKnowledge(
  agentId: number,
  kb_ids: number[],
): Promise<{ bound: number; sync: unknown }> {
  return request(`/agents/${agentId}/knowledge`, {
    method: "PUT",
    body: JSON.stringify({ kb_ids }),
  });
}

export async function getAgentSoul(agentId: number): Promise<{ soul: string }> {
  return request(`/agents/${agentId}/soul`);
}

export async function getForcedToolsets(
  agentId: number,
): Promise<{ forced: string[]; reasons: Record<string, string> }> {
  return request(`/agents/${agentId}/forced-toolsets`);
}

// ── 定时自动化任务 ────────────────────────────────────────
export interface ScheduledTask {
  id: number;
  name: string;
  owner_id: number;
  enabled: boolean;
  schedule_kind: "interval" | "cron";
  every_seconds: number;
  cron_expr: string | null;
  action_type: "agent_message" | "a2a_call";
  target_agent_id: number | null;
  a2a_endpoint_id: number | null;
  payload: string;
  delivery: string;
  webhook_url: string | null;
  connector_id: number | null;
  knowledge_id: number | null;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
}

export interface TaskRunInfo {
  id: number;
  started_at: string;
  status: string;
  summary: string | null;
  delivered: string | null;
}

export const DELIVERY_LABELS: Record<string, string> = {
  log: "执行日志",
  session: "存入会话",
  webhook: "Webhook",
  connector: "发送到连接器",
  knowledge: "写入知识库",
};

export function listTasks(): Promise<ScheduledTask[]> { return request("/tasks"); }
export function createTask(body: Partial<ScheduledTask>): Promise<ScheduledTask> {
  return request("/tasks", { method: "POST", body: JSON.stringify(body) });
}
export function updateTask(id: number, body: Partial<ScheduledTask>): Promise<ScheduledTask> {
  return request(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}
export function deleteTask(id: number): Promise<void> {
  return request(`/tasks/${id}`, { method: "DELETE" });
}
export function runTaskNow(id: number): Promise<{ ok: boolean; summary: string }> {
  return request(`/tasks/${id}/run`, { method: "POST" });
}
export function listTaskRuns(id: number): Promise<TaskRunInfo[]> { return request(`/tasks/${id}/runs`); }

