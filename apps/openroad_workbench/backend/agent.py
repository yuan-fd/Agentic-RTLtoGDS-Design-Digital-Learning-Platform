from __future__ import annotations

"""Agent assistance layer.

Deliberately *pluggable and honest*: the terminal workbench must be fully usable
with no model configured at all.  ``NullProvider`` still assembles the real
working context and surfaces retrieved EDA knowledge, and says plainly that no
model is wired up.  ``OpenAICompatProvider`` streams from any OpenAI-compatible
endpoint once a key is supplied.

Execution policy (WORKBENCH_SPEC.md): the agent may *propose* commands, it never
runs them.  Proposals are extracted from fenced code blocks so the TUI can offer
"send to terminal / copy" and the user stays in control.
"""

import asyncio
import json
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from .corpus import Corpus

CODE_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.S)
SHELL_LANGS = {"", "sh", "shell", "bash", "zsh", "console", "tcl", "tclsh", "python", "py", "makefile", "make"}

SYSTEM_PROMPT = (
    "You are the OpenROAD workbench agent, embedded next to a real terminal on an EDA server.\n"
    "You help with OpenROAD, OpenROAD-flow-scripts (ORFS), Tcl and Python automation.\n"
    "Rules:\n"
    "- Never claim you executed something. You only propose commands or scripts.\n"
    "- Prefer answers grounded in the provided context (cwd, recent output, reports, corpus).\n"
    "- When you propose a command, put it in a fenced code block and state the working directory.\n"
    "- Be concise and concrete. If the context is insufficient, say what is missing.\n"
)


class AgentProvider:
    name = "base"
    available = False

    async def stream(self, messages: List[Dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover


class NullProvider(AgentProvider):
    """No model configured: return the real context plus retrieved knowledge."""

    name = "null"
    available = True

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    async def stream(self, messages: List[Dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        context = kwargs.get("context") or {}
        question = kwargs.get("question") or ""
        lines = [
            "**未配置模型后端**（Agent 目前只做上下文与知识检索，不会编造执行结果）。",
            "",
            "当前工作上下文：",
            "",
            "```text",
        ]
        design = context.get("design") or {}
        session = context.get("session") or {}
        run = context.get("run") or {}
        lines.append("设计: %s" % (design.get("name") or "(未选择)"))
        lines.append("路径: %s" % (design.get("path") or context.get("cwd") or "-"))
        lines.append("终端: %s (%s)" % (session.get("name") or "-", session.get("status") or "-"))
        lines.append("工作目录: %s" % (context.get("cwd") or "-"))
        lines.append("当前运行: %s" % (run.get("name") or "(空闲)"))
        if run.get("stages"):
            lines.append("已观察阶段: %s" % ", ".join(run["stages"]))
        counts = context.get("artifacts") or {}
        if counts:
            lines.append("结果统计: %s" % ", ".join("%s=%d" % kv for kv in sorted(counts.items())))
        lines.append("```")

        hits = self.corpus.retrieve(question, limit=3) if question else []
        if hits:
            lines.extend(["", "相关知识（本地语料检索）：", ""])
            for index, hit in enumerate(hits, start=1):
                snippet = (hit.get("answer") or "").strip().replace("\r", "")
                snippet = snippet[:600]
                lines.append("**%d. %s**  _(score %s, %s)_" % (
                    index, hit.get("question") or "(untitled)", hit.get("score"), os.path.basename(hit.get("source", ""))))
                lines.append("")
                lines.append("```text")
                lines.append(snippet)
                lines.append("```")
                lines.append("")
        elif question:
            lines.extend(["", "_本地语料没有检索到相关内容（`~/.openroad-workbench/corpus` 为空或未收录）。_"])

        lines.extend([
            "",
            "要让它真正回答问题，任选其一：",
            "",
            "1. 在 `~/.openroad-workbench/config.json` 里设置 `agent.provider=openai`、`agent.base_url`、`agent.model`；",
            "2. 或者导出 API key 到 `OPENROAD_WORKBENCH_API_KEY` 环境变量后重启 daemon。",
        ])

        text = "\n".join(lines)
        for chunk in _chunks(text, 240):
            await asyncio.sleep(0)
            yield chunk


class OpenAICompatProvider(AgentProvider):
    name = "openai"

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 120.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.available = bool(self.base_url and self.model)

    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    async def stream(self, messages: List[Dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        if not self.available:
            raise RuntimeError("agent provider is not configured")
        import aiohttp

        payload = {"model": self.model, "messages": messages, "stream": True, "temperature": 0.2}
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = "Bearer %s" % self.api_key
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._endpoint(), json=payload, headers=headers) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError("agent endpoint %s: %s" % (response.status, body[:400]))
                async for raw in response.content:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        message = json.loads(data)
                    except Exception:
                        continue
                    choices = message.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece


def _chunks(text: str, size: int) -> List[str]:
    return [text[index:index + size] for index in range(0, len(text), size)]


def extract_commands(text: str) -> List[Dict[str, str]]:
    proposals: List[Dict[str, str]] = []
    for match in CODE_BLOCK_RE.finditer(text or ""):
        language = (match.group(1) or "").strip().lower()
        code = match.group(2).strip("\n")
        if not code:
            continue
        if language in SHELL_LANGS:
            proposals.append({"language": language or "text", "code": code})
    return proposals


class AgentService:
    def __init__(self, workbench: Any, config: Dict[str, Any]) -> None:
        self.workbench = workbench
        agent_config = (config or {}).get("agent") or {}
        self.corpus = Corpus(config.get("corpus_path"))
        try:
            count = self.corpus.load()
            self.corpus_note = "loaded %d records" % count if count else (self.corpus.error or "empty")
        except Exception as exc:  # pragma: no cover
            self.corpus_note = "corpus load failed: %s" % exc

        provider_name = (agent_config.get("provider") or "null").lower()
        self.provider: AgentProvider = NullProvider(self.corpus)
        if provider_name == "openai":
            api_key = os.environ.get(agent_config.get("api_key_env") or "OPENROAD_WORKBENCH_API_KEY", "")
            candidate = OpenAICompatProvider(
                agent_config.get("base_url", ""),
                agent_config.get("model", ""),
                api_key,
            )
            if candidate.available:
                self.provider = candidate

    # --------------------------------------------------------------- context
    def build_messages(self, question: str, context: Dict[str, Any], history: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
        hits = self.corpus.retrieve(question, limit=4)
        context_lines = [
            "design: %s" % ((context.get("design") or {}).get("name") or "(none)"),
            "design_path: %s" % ((context.get("design") or {}).get("path") or "-"),
            "cwd: %s" % (context.get("cwd") or "-"),
            "session: %s" % ((context.get("session") or {}).get("name") or "-"),
            "current_run: %s" % ((context.get("run") or {}).get("name") or "(idle)"),
            "observed_stages: %s" % ", ".join(((context.get("run") or {}).get("stages") or []) or ["-"]),
            "artifact_counts: %s" % json.dumps(context.get("artifacts") or {}, ensure_ascii=False),
            "",
            "recent terminal tail:",
        ]
        context_lines.extend((context.get("terminal_tail") or [])[-25:])
        if hits:
            context_lines.append("")
            context_lines.append("retrieved EDA corpus snippets:")
            for hit in hits:
                context_lines.append("- Q: %s" % (hit.get("question") or "")[:200])
                context_lines.append("  A: %s" % (hit.get("answer") or "")[:400])

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in (history or [])[-6:]:
            role = item.get("role")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": str(item.get("content") or "")[:4000]})
        messages.append({
            "role": "user",
            "content": "工作上下文：\n```text\n%s\n```\n\n问题：%s" % ("\n".join(context_lines), question),
        })
        return messages

    # ------------------------------------------------------------------ answer
    async def answer(
        self,
        question: str,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        context = self.workbench.context(session_id=session_id, run_id=run_id)
        conversation = None
        if conversation_id:
            conversation = self.workbench.get_conversation(conversation_id)
        if conversation is None:
            conversation = self.workbench.create_conversation(
                title=question[:40] or "新对话",
                design_id=(context.get("design") or {}).get("id"),
                session_id=session_id,
                run_id=run_id,
            )
        self.workbench.append_message(conversation.id, "user", question)
        messages = self.build_messages(question, context, history=conversation.messages[:-1])

        yield {"type": "start", "conversation_id": conversation.id, "provider": self.provider.name,
               "corpus": self.corpus.stats()}
        collected: List[str] = []
        try:
            async for piece in self.provider.stream(messages, context=context, question=question):
                collected.append(piece)
                yield {"type": "delta", "text": piece}
        except Exception as exc:
            error = "Agent 调用失败：%s" % exc
            collected.append(error)
            yield {"type": "error", "message": error}

        full = "".join(collected)
        self.workbench.append_message(conversation.id, "assistant", full,
                                      provider=self.provider.name,
                                      proposals=extract_commands(full))
        yield {"type": "done", "conversation_id": conversation.id, "text": full,
               "proposals": extract_commands(full)}

    def status(self) -> Dict[str, Any]:
        return {
            "provider": self.provider.name,
            "available": self.provider.available,
            "corpus": self.corpus.stats(),
        }
