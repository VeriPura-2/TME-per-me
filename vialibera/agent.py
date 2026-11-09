"""TEM agent: interviews the client, fills the case file, proposes menu items.

The agent never sets prices and never confirms items. It only calls the tools below,
and every write goes through db.py and gates.py, which enforce the rules.
"""
import json

from . import ai_usage, db, docs, fields, gates, masaf, personas

MODEL = "claude-sonnet-5-5"

SYSTEM = """You are the MioTEM Trade Export Manager for Italian food SMEs.
You work in the client's language and in plain words.

How you interview:
- Ask exactly ONE question per message, never two. Record each answer at once with case_write.
- Save calls: record EVERYTHING the client told you in this message (every section) with case_write calls made
  together, in the SAME response as your reply (next question included), never in separate steps. One case_write per
  section, using only the keys listed under FIELDS. Example: "dried pasta to the UK" is product.category = pasta and
  market.country = UK, both saved in that one response.
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

What MioTEM covers today, with a verified document checklist and duties: dried pasta, wine, olive oil and cheese,
from Italy to the United Kingdom, the USA, Canada, Switzerland and all 26 other European Union countries (Germany,
France, Spain, the Netherlands, Belgium and Austria are fully researched; for the other 20 the national rules are still
to be checked by staff). When the client wants another product or another country:
- Say it plainly and warmly, without internal words (never "wave", "lane", "phase", "roadmap", "not built"). For example:
  "MioTEM does not yet have a checked document list for [product] to [country]. We add new countries and products
  based on what exporters ask for, so your request counts. May I note a few details? You can skip any of them."
- Record it at once with lane_request (product and country), then ask, one at a time and each skippable: when they
  plan to ship, a rough volume, and whether they already have a buyer there. Record each answer with lane_request.
- Close with: their request is recorded and our team reviews these requests to decide what to add next. Never
  promise a date or that it will be added. Offer to help with general export questions meanwhile, and point out
  that for any covered country you can prepare the full document checklist and duties right away.
- Record the destination in case_write as "other" only if no covered country applies.

You never state prices yourself, never promise outcomes, and never mark anything delivered or confirmed.
The page has a Documents button (top right). Clients upload their commonly used trade documents there
(labels, lab analyses, certificates, company papers, invoices, packing lists), and the page files them in a company
library and in projects. When a client mentions a document or file, point them to that button. You cannot open or
read the files yourself yet; you only see their names and filing, listed below. VeriPura staff and CORE review them later.
Never say you cannot receive files. Propose services only with propose_item, using menu codes.
Certification: when the client says the product is DOP, IGP, DOCG, DOC or IGT, follow the CERTIFICATION line of the case note. A certification
stays "claimed" until staff or CORE have seen the certificate; never call it verified or confirmed yourself.
Tariff, label and compliance answers must come from tools, never from memory. If a tool is
unavailable, say so once, flag the item for VeriPura staff, and move on with the interview."""

from . import tools as tools_catalog  # noqa: E402  (the AI tool guide is part of the cached prompt)
GUIDE = fields.field_guide() + "\n\n" + tools_catalog.ai_guide()

TOOLS = [
    {"name": "case_read", "description": "Read the current case file.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "case_write",
     "description": "Merge fields into the company, product or market section of the case file.",
     "input_schema": {"type": "object", "properties": {
         "section": {"type": "string", "enum": ["company", "product", "market"]},
         "fields": {"type": "object"}}, "required": ["section", "fields"]}},
    {"name": "lane_request",
     "description": "Record a request for a product or destination country MioTEM does not cover yet. Call it again as "
                    "details come in; later calls update the same request.",
     "input_schema": {"type": "object", "properties": {
         "product": {"type": "string"}, "country": {"type": "string"},
         "timing": {"type": "string", "description": "when they want to ship, in their words"},
         "volume": {"type": "string", "description": "rough first-shipment or yearly volume, in their words"},
         "buyer": {"type": "string", "description": "yes, no, or the buyer's situation, in their words"},
         "notes": {"type": "string"}}}},
    {"name": "control_body",
     "description": "Look up which control body MASAF lists for a protected product name (DOP, IGP, DOCG, DOC, IGT, STG). "
                    "Says who may control the name, not that the client is certified. Quote the list date and say so.",
     "input_schema": {"type": "object", "properties": {"denomination": {"type": "string"}}, "required": ["denomination"]}},
    {"name": "propose_item", "description": "Propose a menu item for the client by code. Price comes from the menu.",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}},
                      "required": ["code"]}},
]


def run_tool(con, case_id, menu, name, args):
    try:
        if name == "case_read":
            return db.case_read(con, case_id)
        if name == "case_write":
            ok, err = fields.check_write(args.get("section"), args.get("fields"))
            if ok:
                db.case_write(con, case_id, args["section"], ok)
            if err:
                return {"saved": sorted(ok), "error": err}  # the agent sees this and writes the rest correctly
            return {"saved": sorted(ok)}
        if name == "lane_request":
            from . import lane_requests
            return lane_requests.record(con, case_id, None, args, source="chat")
        if name == "control_body":
            return masaf.describe(args["denomination"])
        if name == "propose_item":
            iid = gates.add_item(con, case_id, args["code"], menu)
            return {"item_id": iid, "state": "proposed"}
    except (gates.GateError, KeyError, ValueError) as e:
        return {"error": str(e)}
    return {"error": f"unknown tool {name}"}


def persona_for(path_type):
    """Fallback when no profile exists (sign-in off)."""
    return "chiara" if int(path_type or 1) in (3, 4) else "cosimo"


QUIET_TOOLS = {"case_write", "lane_request"}  # saves whose result the agent does not need to see before replying


def system_blocks(fixed, note):
    """Prompt caching: tools and the fixed instructions (persona and rules) form a prefix that is the same on every
    call of a conversation, so it is marked for the cache and billed at the cache-read price on repeat calls.
    The case note changes as answers come in, so it goes after the cache mark."""
    return [{"type": "text", "text": fixed, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": note}]


def cached_messages(history):
    """A copy of the history with a cache mark on its last block, so the conversation so far is read from the
    cache on the next call (the second call of a turn, or the next message within a few minutes).
    The saved history is never changed: marks must not pile up (the API allows at most 4)."""
    if not history:
        return history
    out = list(history)
    last = dict(out[-1])
    content = last["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content]
    if not blocks:
        return out
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    last["content"] = blocks
    out[-1] = last
    return out


def turn(client, con, case_id, menu, history, user_text, max_steps=8, lang="it", persona_id=None, usage=None):
    """One client message in, one agent reply out. history is a list of API messages (mutated).
    usage, when given, is a dict that collects the tokens of every AI call made for this message (ai_usage.add)."""
    last = history[-1] if history else None
    if last and last["role"] == "user" and isinstance(last["content"], list):
        # the previous reply ended without a follow-up call: its tool results are still the last user message,
        # so the new message joins it (the API needs user and assistant turns to alternate)
        last["content"].append({"type": "text", "text": user_text})
    else:
        history.append({"role": "user", "content": user_text})
    db.log_event(con, case_id, "client", "message", {"text": user_text})
    for _ in range(max_steps):
        have = docs.summary_for_case(con, case_id)
        note = fields.prompt_note(db.case_read(con, case_id)) + (" Documents on file (names only): " + have + "." if have else " No documents uploaded yet.") + (
            " Interface language: " + ("Italian. Write every message and every OPTIONS line in Italian"
                                       if lang == "it" else "English. Write every message and every OPTIONS line in English")
            + ", unless the client writes in another language, then follow the client.")
        fixed = personas.system_prompt(persona_id or persona_for(db.case_read(con, case_id)["path_type"])) + "\n\n" + SYSTEM + "\n\n" + GUIDE
        with db.outside_call():  # 5 to 30 s: the database connection is lent back meanwhile
            resp = client.messages.create(model=MODEL, max_tokens=1024, system=system_blocks(fixed, note), tools=TOOLS,
                                          messages=cached_messages(history))
        if usage is not None:
            ai_usage.add(usage, getattr(resp, "usage", None))
        history.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            text = "".join(b.text for b in resp.content if b.type == "text")
            db.log_event(con, case_id, "agent", "message", {"text": text})
            return text
        outcomes = [run_tool(con, case_id, menu, u.name, u.input) for u in uses]
        results = [{"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(o, default=str)}
                   for u, o in zip(uses, outcomes)]
        history.append({"role": "user", "content": results})
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if text and all(u.name in QUIET_TOOLS for u in uses) and not any(isinstance(o, dict) and o.get("error") for o in outcomes):
            # one call per message: the reply came with the saves and every save worked, so no second call is needed
            db.log_event(con, case_id, "agent", "message", {"text": text})
            return text
    return "I need a VeriPura team member to continue this one."
