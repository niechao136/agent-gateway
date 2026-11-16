export type ChatRole = "user" | "assistant" | "tool" | "error";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  /** tool 角色时记录工具名 */
  toolName?: string;
  /** 是否仍在流式接收中 */
  streaming?: boolean;
}
