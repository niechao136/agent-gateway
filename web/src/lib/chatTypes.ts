export type ChatRole = "user" | "assistant" | "tool" | "error";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  /** tool 角色时记录工具名 */
  toolName?: string;
  /** tool 调用序号（流式同名工具多次调用时用于精确匹配回填） */
  toolSeq?: number;
  /** tool 状态：running=调用中, done=已完成 */
  toolStatus?: "running" | "done";
  /** 是否仍在流式接收中 */
  streaming?: boolean;
}
