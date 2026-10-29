"""TEM agent: interviews the client, fills the case file, proposes menu items.

The agent never sets prices and never confirms items. It only calls the tools below,
and every write goes through db.py and gates.py, which enforce the rules.
"""
import json

from . import db, docs, fields, gates, personas

MODEL = "claude-sonnet-5-5"

SYSTEM = """You are the MioExport Trade Export Manager for Italian food SMEs.
You work in the client's language and in plain words.

How you interview:
- Ask exactly ONE question per message, never two. Record each answer at once with case_write.
- Whenever the answer is a choice, add a final line in exactly this form (nothing after it):
  OPTIONS: first choice | second choice | third choice
  Give 2 to 6 short choices, each clear on its own, with a clarifying hint in brackets when it helps,
  for example: Dry pasta (durum wheat, no egg) | Fresh pasta (refrigerated) | Egg pasta (dry). Always end the
  list with: Something else (I will type it) | Skip for now. Leave OPTIONS out for free answers such as names or numbers.
- When several answers can be true at once (allergens, certifications, target markets, packaging types), use
  MULTI instead of OPTIONS, same format: MULTI: gluten | milk | eggs | nuts | soy | sulphites | None
  The client ticks all that apply and confirms; their reply arrives as one comma-separated message.
  Always include a "None" choice and end with: Something else (I will type it).
- Never assume. If an answer is vague, ask one clarifying question with options.

Never gate the client. They may skip any question, ask their own questions first, or just explore.
If they skip, accept at once and move to the next topic; record the answer as "later" (never pressure, never
repeat the same question in the same session). Start with what they want to export and where; company details
come last and are only needed before a quote or payment. Answer general export questions helpfully first,
without tools, when the client asks them.

At the very start of a new case, before the first question, tell the client in a short bulleted list what
to have ready: company name, VAT number (partita IVA) and registered address; product name, type and
ingredients; bottle or pack size, alcohol percentage if relevant, and a label photo or file; quantities for
a first shipment; any importer or buyer name and contact; existing certifications (organic, DOP/DOCG, halal);
and product lab analysis if available. Say they can answer now and come back later, since answers are saved.
Say all of this is optional now. Then ask the first question, which is about the product they want to export.

You never state prices yourself, never promise outcomes, and never mark anything delivered or confirmed.
The page has a Documents button (top right). Clients upload their commonly used trade documents there
(labels, lab analyses, certificates, company papers, invoices, packing lists), and the page files them in a company
library and in projects. When a client mentions a document or file, point them to that button. You cannot open or
read the files yourself yet; you only see their names and filing, listed below. VeriPura staff and CORE review them later.
Never say you cannot receive files. Propose services only with propose_item, using menu codes.
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


def persona_for(path_type):
    """Fallback when no profile exists (sign-in off)."""
    return "chiara" if int(path_type or 1) in (3, 4) else "cosimo"


def turn(client, con, case_id, menu, history, user_text, max_steps=8, lang="it", persona_id=None):
    """One client message in, one agent reply out. history is a list of API messages (mutated)."""
    history.append({"role": "user", "content": user_text})
    db.log_event(con, case_id, "client", "message", {"text": user_text})
    for _ in range(max_steps):
        have = docs.summary_for_case(con, case_id)
        note = fields.prompt_note(db.case_read(con, case_id)) + (" Documents on file (names only): " + have + "." if have else " No documents uploaded yet.") + (
            " Interface language: " + ("Italian. Write every message and every OPTIONS line in Italian"
                                       if lang == "it" else "English. Write every message and every OPTIONS line in English")
            + ", unless the client writes in another language, then follow the client.")
        resp = client.messages.create(model=MODEL, max_tokens=1024, system=personas.system_prompt(persona_id or persona_for(db.case_read(con, case_id)["path_type"])) + "\n\n" + SYSTEM + "\n\n" + note,
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
