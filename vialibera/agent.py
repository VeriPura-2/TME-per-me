"""TEM agent: interviews the client, fills the case file, proposes menu items.

The agent never sets prices and never confirms items. It only calls the tools below,
and every write goes through db.py and gates.py, which enforce the rules.
"""
import json

from . import db, gates

MODEL = "claude-sonnet-5-5"

SYSTEM = """You are the Via Libera Trade Export Manager for Italian food SMEs.
Interview the client in plain language, one or two questions at a time, in the client's language.
Record every fact with case_write. Propose services only with propose_item, using menu codes.
You never state prices yourself, never promise outcomes, and never mark anything delivered or confirmed.
Tariff, label and compliance answers must come from tools, never from memory. If a tool is
unavailable, say so and flag the item for VeriPura staff."""

TOOLS = [
    {"name": "case_read", "description": "Read the current case file.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "case_write",
     "description": "Merge fields into the company, product or market section of the case file.",
     "input_schema": {"type": "object", "properties": {
         "section": {"type": "string", "enum": ["company", "product", "market"]},
         "fields": {"type": "object"}}, "required": ["section", "fields"]}},
    {"name": "propose_item", "description": "Propose a menu item for the client by code. Price comes from the menu.",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}},
                      "required": ["code"]}},
]


def run_tool(con, case_id, menu, name, args):
    try:
        if name == "case_read":
            return db.case_read(con, case_id)
        if name == "case_write":
            return db.case_write(con, case_id, args["section"], args["fields"])
        if name == "propose_item":
            iid = gates.add_item(con, case_id, args["code"], menu)
            return {"item_id": iid, "state": "proposed"}
    except (gates.GateError, KeyError, ValueError) as e:
        return {"error": str(e)}
    return {"error": f"unknown tool {name}"}


def turn(client, con, case_id, menu, history, user_text, max_steps=8):
    """One client message in, one agent reply out. history is a list of API messages (mutated)."""
    history.append({"role": "user", "content": user_text})
    db.log_event(con, case_id, "client", "message", {"text": user_text})
    for _ in range(max_steps):
        resp = client.messages.create(model=MODEL, max_tokens=1024, system=SYSTEM,
                                      tools=TOOLS, messages=history)
        history.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            text = "".join(b.text for b in resp.content if b.type == "text")
            db.log_event(con, case_id, "agent", "message", {"text": text})
            return text
        results = [{"type": "tool_result", "tool_use_id": u.id,
                    "content": json.dumps(run_tool(con, case_id, menu, u.name, u.input), default=str)}
                   for u in uses]
        history.append({"role": "user", "content": results})
    return "I need a VeriPura team member to continue this one."
