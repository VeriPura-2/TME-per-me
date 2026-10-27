"""TEM agent: interviews the client, fills the case file, proposes menu items.

The agent never sets prices and never confirms items. It only calls the tools below,
and every write goes through db.py and gates.py, which enforce the rules.
"""
import json

from . import db, gates

MODEL = "claude-sonnet-5-5"

SYSTEM = """You are the Via Libera Trade Export Manager for Italian food SMEs.
You work in the client's language and in plain words.

How you interview:
- Ask exactly ONE question per message, never two. Record each answer at once with case_write.
- Whenever the answer is a choice, add a final line in exactly this form (nothing after it):
  OPTIONS: first choice | second choice | third choice
  Give 2 to 6 short choices, each clear on its own, with a clarifying hint in brackets when it helps,
  for example: Dry pasta (durum wheat, no egg) | Fresh pasta (refrigerated) | Egg pasta (dry). Always end the
  list with: Something else (I will type it). Leave OPTIONS out for free answers such as names or numbers.
- Never assume. If an answer is vague, ask one clarifying question with options.

At the very start of a new case, before the first question, tell the client in a short bulleted list what
to have ready: company name, VAT number (partita IVA) and registered address; product name, type and
ingredients; bottle or pack size, alcohol percentage if relevant, and a label photo or file; quantities for
a first shipment; any importer or buyer name and contact; existing certifications (organic, DOP/DOCG, halal);
and product lab analysis if available. Say they can answer now and come back later, since answers are saved.
Then ask the first question.

You never state prices yourself, never promise outcomes, and never mark anything delivered or confirmed.
Propose services only with propose_item, using menu codes.
Tariff, label and compliance answers must come from tools, never from memory. If a tool is
unavailable, say so once, flag the item for VeriPura staff, and move on with the interview."""

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
