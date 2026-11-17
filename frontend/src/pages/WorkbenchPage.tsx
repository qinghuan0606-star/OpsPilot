import { useMemo, useRef, useState } from "react";
import { EvidencePanel } from "../components/EvidencePanel";
import { Composer } from "../components/Composer";
import { MessageView } from "../components/MessageView";
import { useChat } from "../hooks/useChat";
import type { ActionProposal } from "../types";

const SUGGESTIONS = [
  { title: "RPM 升级故障", prompt: "我升级了 nginx 的 RPM 软件包，但是现在服务启动失败，帮我分析一下原因" },
  { title: "服务状态", prompt: "帮我查一下 lab-node-2 的 docker 服务状态" },
  { title: "系统基线", prompt: "lab-node-1 的内核版本和发行版是什么" },
  { title: "磁盘排查", prompt: "lab-node-2 的 /data 使用率很高，怎么排查" },
];

export function WorkbenchPage() {
  const chat = useChat();
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const lastAssistant = useMemo(
    () => chat.active?.messages.filter((message) => message.role === "assistant").at(-1) ?? null,
    [chat.active],
  );

  function confirm(action: ActionProposal, messageId: string) {
    if (!chat.active) return;
    const conversationId = chat.active.id;
    void chat.send("确认执行", action.action_id).then((succeeded) => {
      if (succeeded) chat.dismissAction(conversationId, messageId);
    });
  }

  return (
    <div className="workbench">
      <div className="workbench-main">
        {chat.active ? (
          <div className="chat-content">
            <MessageView
              conversation={chat.active}
              busy={chat.busy}
              onConfirm={confirm}
              onCancel={(messageId) => chat.active && chat.dismissAction(chat.active.id, messageId)}
            />
          </div>
        ) : (
          <div className="welcome">
            <div className="welcome-inner">
              <h1>OpsPilot 智能运维工作台</h1>
              <p>
                OpsPilot 五路诊断策略：直接回答、单跳检索、多跳诊断、工具取证、拒答。
                工具为 mock 后端，所有数据均为模拟。
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((item) => (
                  <button key={item.title} onClick={() => { setDraft(item.prompt); inputRef.current?.focus(); }}>
                    <span><strong>{item.title}</strong><small>{item.prompt}</small></span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        <Composer
          busy={chat.busy}
          onSend={(message) => void chat.send(message)}
          onStop={chat.stop}
          draft={draft}
          onDraft={setDraft}
          inputRef={inputRef}
        />
      </div>
      {lastAssistant ? <EvidencePanel message={lastAssistant} /> : (
        <aside className="inspector">
          <section><h3>工作流节点</h3><p className="muted">提一个问题，这里会显示 guardrail → intent → router → retrieve → assess → plan → execute → answer 的真实节点与工具调用。</p></section>
        </aside>
      )}
    </div>
  );
}
