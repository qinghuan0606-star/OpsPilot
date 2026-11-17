import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MessageView } from "./MessageView";
import type { Conversation } from "../types";

describe("answer presentation", () => {
  it("shows the answer and source without internal timing or route metadata", () => {
    const conversation: Conversation = {
      id: "chat-1",
      title: "RPM 依赖冲突",
      updatedAt: 0,
      messages: [{
        id: "answer-1",
        role: "assistant",
        state: "complete",
        content: "升级后提示 missing libGeoIP.so.1，需补齐对应模块包。",
        strategy: "multi",
        latencyMs: 4200,
        citations: [{
          citation_id: "kb:chunk-1",
          kind: "knowledge",
          chunk_id: "chunk-1",
          document_id: "rpm_dependency_conflict",
          title: "RPM 依赖冲突",
          section: null,
          locator: "rpm_dependency_conflict_01",
          excerpt: "missing libGeoIP.so.1",
        }],
      }],
    };
    const html = renderToStaticMarkup(
      <MessageView conversation={conversation} busy={false} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(html).toContain("libGeoIP");
    expect(html).toContain("RPM 依赖冲突");
    expect(html).not.toContain("多跳检索");
    expect(html).not.toContain("4.2 秒");
  });
});
