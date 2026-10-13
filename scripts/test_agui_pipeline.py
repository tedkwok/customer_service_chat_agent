"""Mock-mode test of the AG-UI event pipeline (no LLM / Redis / DB / Chroma).

Covers, end to end at the module level:
  1. agent_implementation() with a fake coordinator agent -> correct AG-UI
     event sequence (RunStarted -> TextMessage* -> ToolCall* -> RunFinished),
     with subagent model calls filtered out of the chat stream.
  2. The non-streaming fallback path (model emits only on_chat_model_end).
  3. agent_implementation() error path -> RunErrorEvent.
  4. Round-trip of every emitted event through the production pipeline:
     model_dump_json -> (Redis string) -> augi_obj_parse -> EventEncoder.encode
     -> SSE bytes, preserving subtype-specific fields (delta, message_id, ...).

Run:  .venv/bin/python scripts/test_agui_pipeline.py
"""

import asyncio
import os
import sys

# Dummy environment so module-level clients/engines construct without
# connecting to anything (nothing here performs network I/O).
os.environ.setdefault("LITELLM_API_KEY", "sk-test-dummy")
os.environ.setdefault("POSTGRES_DATABASE_URL", "postgresql://u:p@localhost:5432/none")
os.environ.setdefault("MYSQL_CONNECTION_URL", "mysql+pymysql://u:p@localhost:3306/none")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8001")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ag_ui.encoder import EventEncoder  # noqa: E402

import app.agent.implementation as impl  # noqa: E402
from app.utils.augi_parse import agui_obj_parse  # noqa: E402


PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


class _Chunk:
    def __init__(self, content):
        self.content = content


class _Output:
    def __init__(self, content):
        self.content = content


def ev(name, run_id, data=None, metadata=None):
    return {"event": name, "run_id": run_id, "name": name,
            "data": data or {}, "metadata": metadata or {}}


async def stub_stream_full():
    """Root model streams text; subagent call must be filtered; render tool fires."""
    yield ev("on_chat_model_start", "r-model", {}, {})
    yield ev("on_chat_model_stream", "r-model", {"chunk": _Chunk("Hello ")}, {})
    yield ev("on_chat_model_stream", "r-model", {"chunk": _Chunk("there.")}, {})
    yield ev("on_chat_model_end", "r-model", {"output": _Output("Hello there.")}, {})
    # Subagent internal model call: has a checkpoint ns -> must NOT reach the UI.
    yield ev("on_chat_model_start", "r-sub",
             {}, {"langgraph_checkpoint_ns": "task:abc", "langgraph_node": "tools"})
    yield ev("on_chat_model_stream", "r-sub",
             {"chunk": _Chunk("internal brief")}, {"langgraph_checkpoint_ns": "task:abc"})
    yield ev("on_chat_model_end", "r-sub",
             {"output": _Output("internal brief")}, {"langgraph_checkpoint_ns": "task:abc"})
    # Render tool call -> TOOL_CALL_* events.
    yield {"event": "on_tool_start", "run_id": "r-tool", "name": "render_product_card",
           "data": {"input": {"product_id": "P001", "product_name": "Aurora Wireless Headphones",
                              "product_price": 1299.0, "stock_amount": 45}}, "metadata": {}}
    yield {"event": "on_tool_end", "run_id": "r-tool", "name": "render_product_card",
           "data": {"output": "Success: product card component displayed."},
           "metadata": {}}


async def stub_stream_fallback_only():
    """Non-streaming model: only on_chat_model_end -> fallback text message."""
    yield ev("on_chat_model_end", "r-model2", {"output": _Output("Final answer.")}, {})


class FakeAgent:
    def __init__(self, stream):
        self._stream = stream

    def astream_events(self, _input, config=None, version=None):
        return self._stream


class _FakeStoreObj:
    async def setup(self):
        pass


class _FakeStoreCM:
    async def __aenter__(self):
        return _FakeStoreObj()

    async def __aexit__(self, *args):
        return False


class _FakeStore:
    @classmethod
    def from_conn_string(cls, _url):
        return _FakeStoreCM()


async def collect(agen):
    return [e async for e in agen]


async def main():
    global PASS, FAIL

    real_store = impl.AsyncPostgresStore
    real_build = impl.coordinator.build_coordinator_agent
    impl.AsyncPostgresStore = _FakeStore

    try:
        # ---- 1. full happy path ------------------------------------------- #
        impl.coordinator.build_coordinator_agent = lambda user_id, store: asyncio.ensure_future(
            _return(FakeAgent(stub_stream_full())))
        events = await collect(impl.agent_implementation("u1", "t1", "hi", "w1"))
        types = [e.type.value if hasattr(e.type, "value") else str(e.type) for e in events]

        print("\n[1] full happy path")
        check("starts with RUN_STARTED", types[0] == "RUN_STARTED", f"got {types[0]}")
        check("ends with RUN_FINISHED", types[-1] == "RUN_FINISHED", f"got {types[-1]}")
        check("has TEXT_MESSAGE_START", "TEXT_MESSAGE_START" in types)
        check("has TEXT_MESSAGE_END", "TEXT_MESSAGE_END" in types)
        deltas = [e.delta for e in events if type(e).__name__ == "TextMessageContentEvent"]
        check("deltas streamed in order", deltas == ["Hello ", "there."], f"got {deltas}")
        check("subagent text filtered", "internal brief" not in
              [getattr(e, "delta", "") for e in events])
        check("TOOL_CALL_START present", "TOOL_CALL_START" in types)
        check("TOOL_CALL_ARGS present", "TOOL_CALL_ARGS" in types)
        check("TOOL_CALL_END present", "TOOL_CALL_END" in types)
        tool_start = next(e for e in events if type(e).__name__ == "ToolCallStartEvent")
        check("tool_call_name correct", tool_start.tool_call_name == "render_product_card")
        tool_args = next(e for e in events if type(e).__name__ == "ToolCallArgsEvent")
        check("tool args carry product_id", '"P001"' in tool_args.delta)
        run_started = events[0]
        check("thread_id preserved", run_started.thread_id == "t1")
        run_finished = events[-1]
        check("run ids match", run_started.run_id == run_finished.run_id)

        # ---- 2. fallback path ---------------------------------------------- #
        impl.coordinator.build_coordinator_agent = lambda user_id, store: asyncio.ensure_future(
            _return(FakeAgent(stub_stream_fallback_only())))
        events2 = await collect(impl.agent_implementation("u1", "t1", "hi", "w1"))
        types2 = [e.type.value if hasattr(e.type, "value") else str(e.type) for e in events2]
        print("\n[2] non-streaming fallback")
        check("fallback text emitted", "TEXT_MESSAGE_CONTENT" in types2)
        deltas2 = [e.delta for e in events2 if type(e).__name__ == "TextMessageContentEvent"]
        check("fallback text correct", deltas2 == ["Final answer."], f"got {deltas2}")
        check("run still finished", types2[-1] == "RUN_FINISHED")

        # ---- 2b. oversized fallback: delta splitting ------------------------ #
        big_text = ("A" * 7999) + " WORD " + ("B" * 19000)  # ~27k chars total

        async def stub_stream_big():
            yield ev("on_chat_model_end", "r-big", {"output": _Output(big_text)}, {})

        impl.coordinator.build_coordinator_agent = lambda user_id, store: asyncio.ensure_future(
            _return(FakeAgent(stub_stream_big())))
        events2b = await collect(impl.agent_implementation("u1", "t1", "hi", "w1"))
        print("\n[2b] oversized payload splitting (Response.response cap = 10000)")
        check("oversized run still finishes",
              (events2b[-1].type.value if hasattr(events2b[-1].type, "value")
               else str(events2b[-1].type)) == "RUN_FINISHED")
        content_events = [e for e in events2b if type(e).__name__ == "TextMessageContentEvent"]
        check("fallback split into multiple deltas", len(content_events) >= 4,
              f"got {len(content_events)}")
        rejoined = "".join(e.delta for e in content_events)
        check("split deltas reassemble losslessly", rejoined == big_text,
              f"len {len(rejoined)} vs {len(big_text)}")
        oversized = [len(e.model_dump_json()) for e in events2b
                     if len(e.model_dump_json()) > 10000]
        check("every serialised event fits the bus cap (<=10000)", not oversized,
              f"oversized: {oversized}")

        # ---- 3. error path -------------------------------------------------- #
        async def _boom(user_id, store):
            raise RuntimeError("boom-agent-build")

        impl.coordinator.build_coordinator_agent = _boom
        events3 = await collect(impl.agent_implementation("u1", "t1", "hi", "w1"))
        types3 = [e.type.value if hasattr(e.type, "value") else str(e.type) for e in events3]
        print("\n[3] error path")
        check("RUN_STARTED then RUN_ERROR", types3 == ["RUN_STARTED", "RUN_ERROR"], f"got {types3}")
        check("error message propagated", getattr(events3[-1], "message", "") == "boom-agent-build")

        # ---- 4. production round-trip --------------------------------------- #
        print("\n[4] Redis/SSE round-trip (model_dump_json -> augi_obj_parse -> EventEncoder)")
        encoder = EventEncoder(accept="text/event-stream")
        ok = True
        for e in events:
            wire = e.model_dump_json()
            parsed = agui_obj_parse(wire)
            if type(parsed).__name__ != type(e).__name__:
                ok = False
                print(f"        subtype lost: {type(e).__name__} -> {type(parsed).__name__}")
            for field in ("delta", "message_id", "tool_call_id", "tool_call_name", "thread_id", "run_id"):
                if hasattr(e, field) and getattr(e, field) is not None:
                    if getattr(parsed, field, None) != getattr(e, field):
                        ok = False
                        print(f"        field lost: {type(e).__name__}.{field}")
            encoded = encoder.encode(parsed)
            frame = encoded if isinstance(encoded, str) else encoded.decode("utf-8", "replace")
            if "data:" not in frame or '"type"' not in frame:
                ok = False
                print(f"        bad SSE frame for {type(e).__name__}: {encoded!r}")
        check("all events survive round-trip + SSE encoding", ok)

    finally:
        impl.AsyncPostgresStore = real_store
        impl.coordinator.build_coordinator_agent = real_build

    print(f"\n{'='*50}\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


async def _return(value):
    return value


if __name__ == "__main__":
    asyncio.run(main())
