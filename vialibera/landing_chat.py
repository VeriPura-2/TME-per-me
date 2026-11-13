"""The landing page conversation before sign-in: finds out whether the visitor is an exporter or a TEM, then asks
SPIN questions that fit that role. No case file exists yet, so what the visitor says is kept on the conversation
and carried over after sign-in.

The endpoint is public, so it is capped: messages per visitor, messages per network address per day, and a daily
ceiling for the whole site. Past a cap the page falls back to the scripted buttons and the TEM form.
"""
import hashlib
import json
import os
import re
import traceback
from datetime import datetime, timedelta, timezone

from . import ai_usage, db, duties, lane_requests, requirements, tools

MODEL = "claude-sonnet-5-5"
MESSAGE_CAP = 12
IP_DAILY_CAP = int(os.environ.get("LANDING_IP_DAILY_CAP", "150"))
DAILY_CEILING = int(os.environ.get("LANDING_DAILY_CEILING", "600"))
MAX_CHARS = 1000
MAX_TOKENS = 600
PRODUCT_WORDS = {"pasta": ("pasta",), "wine": ("wine", "vino", "vini"), "olive oil": ("olive oil", "oil", "olio"),
                 "cheese and dairy": ("cheese", "dairy", "formaggi", "formaggio", "latticini"),
                 "spirits": ("spirit", "spirits", "grappa", "liquor", "amaro"), "cured meat": ("cured", "salumi", "ham", "prosciutto", "meat"),
                 "preserves": ("preserve", "preserves", "jam", "sauce", "conserve"), "bakery": ("bakery", "bread", "biscuit", "biscuits", "dolci")}
COUNTRY_WORDS = {"USA": ("usa", "us", "united states", "america", "stati uniti"), "UK": ("uk", "united kingdom", "britain", "england", "regno unito"),
                 "Germany": ("germany", "germania", "deutschland"), "France": ("france", "francia"), "Spain": ("spain", "spagna"),
                 "Netherlands": ("netherlands", "olanda", "holland", "paesi bassi"), "Switzerland": ("switzerland", "svizzera"),
                 "Belgium": ("belgium", "belgio"), "Canada": ("canada",)}
QUIET_TOOLS = ("set_role", "save_answer", "show_signin", "show_preview")  # offer_preview and note_uncovered answer with an instruction: the AI must read it before it speaks
SIGNIN_MENTION = re.compile(r"sign[- ]?(in|up) button|button (is )?below|below[^.]{0,40}sign[- ]?in|pulsante[^.]{0,40}(accedi|sotto)|accedi[^.]{0,40}sotto", re.I)
VISITOR = re.compile(r"^[a-f0-9]{16,64}$")
ROLES = ("exporter", "tem", "looking")
CATEGORIES = ("pasta", "wine", "olive oil", "cheese and dairy", "spirits", "cured meat", "preserves", "bakery", "other")
COUNTRIES = ("UK", "USA", "Canada", "Switzerland", "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
             "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland", "Latvia", "Lithuania", "Luxembourg",
             "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden", "other")
TOPICS = ("product", "destination", "situation", "handling", "time", "volume", "cost", "problem", "implication", "need",
          "firm", "clients", "contact", "other_product", "transactions", "avg_value", "product_types", "markets")

NO_LIST = {"it": "MioTEM non ha ancora un elenco verificato per {p} verso {d}. Qui sotto un breve modulo Le permette di lasciare un'email per "
                 "ricevere un avviso quando sarà pronto (facoltativo). Registrarsi è gratis e permette di vedere le rotte già coperte.",
           "en": "MioTEM has no checked list for {p} to {d} yet. A short form below lets you leave an email to be told when it is ready "
                 "(optional). Signing up is free and lets you look at routes that are covered."}

OPENER = {"it": "Buongiorno. Esporta prodotti italiani, oppure è un TEM o un consulente export?",
          "en": "Hello. Do you export Italian products, or are you a TEM or export consultant?"}

FALLBACK = {"it": "Grazie, ho preso nota. Desidera dirmi altro, oppure registrarsi gratuitamente per continuare?",
            "en": "Thanks, noted. Would you like to tell me more, or sign up free to continue?"}

_SYSTEM_TEMPLATE = """You are the MioTEM guide on the public landing page. MioTEM is an agentic export assistant for Italian food
companies: it prepares the document checklist, duties and next steps for exporting Italian food. Food is available now, and
MioTEM is also adding apparel (clothing, footwear and accessories first). The visitor has not signed in yet. You speak plainly, warmly and briefly (two to four short sentences per message).

If the visitor's first message is the text of a role button ("I export Italian products", "I want to start exporting Italian products",
"I am a TEM or export consultant"), the role is already known: call set_role and go straight to the first question for that
role, without repeating the opening line. Otherwise the visitor has already seen this opening line: "Do you export Italian products, or are you a TEM or export consultant?"
(a TEM is a Trade Export Manager: a consultant who runs exports for several food companies).

STEP 1. Find out the role. As soon as it is clear, call set_role (exporter, tem or looking). A person who says they want to START exporting (or plan to) is also "exporter", a first-time exporter: ask how they plan to
handle the documents rather than how they do today. A person who only wants to
look around is "looking": answer what they ask and let them explore.

STEP 1b. Food or apparel. Right after the role is known (exporter or tem), your first question is exactly one: "Is it food, apparel or something else?"
(for a TEM: "Do your clients export food, apparel or something else?"), with OPTIONS: Food | Apparel | Something else. Skip it only if the visitor already said which.
If food: carry on as described below, nothing changes. If apparel: call note_fashion, then follow the APPAREL rules after step 2.
If something else: call note_other, then follow the OTHER rules after the APPAREL rules.

STEP 2. Ask questions that fit the role. The whole conversation depends on the role. Use SPIN: ask about the Situation,
then the Problem, then the Implication of that problem, then the Need-payoff (what would change for them if it were
solved). Ask exactly ONE question per message. Never repeat a question. Call save_answer for each answer, in the same
response as your reply. Never pressure and never gate: the visitor may skip any question.

If the role is exporter (about 8 questions in this order, fewer if the visitor is brief):
1. Situation: what they export and to which country (product and destination).
2. Situation: how they handle the export documents today, or how they plan to if they have not exported yet:
   OPTIONS: Myself or my team | A freight forwarder | A customs broker | A TEM or consultant | Not decided yet
   If they say they work with a TEM or consultant, the hours question in step 3 becomes: about how many hours a month they spend
   gathering and sending documents to their TEM (same quick ranges). Afterwards say MioTEM prepares and checks the documents
   beforehand, so that time shrinks.
3. Problem, in numbers: roughly how many hours the paperwork takes per shipment, and how many shipments a year they expect.
   Offer ranges as quick choices, for example OPTIONS: Under 2 hours | 2 to 5 hours | 5 to 10 hours | Over 10 hours. If they
   type an exact number, use that instead. Ask the shipments per year the same way.
4. Problem, in money: what they pay per shipment to a forwarder, broker or consultant for the documents (ranges as quick
   choices in euros, or an exact figure if they offer one). A first-time exporter is asked what they expect to spend.
5. Once you have hours and shipments (and fees if given), call yearly_estimate and tell them the result as THEIR estimate:
   "By your own numbers, that is between about X and Z hours a year, that is N weeks of your (or your team's) time every year, and Y euros." When they gave
   ranges, quote the range the tool returns and the weeks (40 hour weeks, as a number or fraction). Never one invented midpoint.
   Never present it as a MioTEM figure.
6. Implication: ask what that does to them (margin, lead time, a delayed shipment, a rejected label, a lost buyer). Ask,
   do not tell. Never state figures, fines or deadlines yourself.
7. Need-payoff: ask what it would mean to know the exact documents and duties for their route before they ship.
   If they handle exports themselves or have not decided, and they seem unsure or stretched, you may ask once: "Would you like an
   introduction to a TEM who works on MioTEM?" On a yes call offer_tem_intro. Never promise a match or a date: say a short form below
   lets them leave an email so MioTEM can be in touch, and that TEMs are joining soon. On a no, carry on.
8. Offer to sign in so MioTEM prepares the checklist and duties for their route, and say a preview of their route can be
   shown (when it is offered, the page will show it).
Save every answer with save_answer: product, destination, handling, time, volume, cost, problem, implication, need.

If the role is tem:
- Do NOT ask about a product or a destination country. A TEM works for many exporters.
- Situation: the firm, how many exporter clients they serve, which products and countries.
- Problem, in numbers: first ask roughly how many hours a week they spend chasing documents from clients, checking them, and keeping up
  with regulatory changes (OPTIONS: Under 5 hours | 5 to 10 hours | 10 to 20 hours | Over 20 hours; an exact number if they offer one;
  save it with save_answer topic time). Then hours per client file or per shipment, how many files a month, and what they charge or lose on a
  file (ranges as quick choices, exact if they offer one). Then call yearly_estimate and state it as THEIR estimate.
- Implication: ask what it costs them when a client file has an error or a rule changes late.
- Need-payoff: ask, never tell: "If a tool did most of that for you, would it free you to spend that time on growing your clients'
  revenue?" (OPTIONS: Yes, clearly | Partly | Not really; save with save_answer topic need). VeriPura CORE tracks regulatory changes and will be
  available in MioTEM once it is connected: you may say it is coming soon through VeriPura CORE, but never that it is available now. Then ask what a workspace with a checked
  document list per client project would change.
- Then offer to sign in: MioTEM gives a TEM a trial workspace to try with real clients (2 clients, 5 projects).
- Ask for the firm name and a contact email near the end, with consent, and save with save_answer (firm, contact).

APPAREL rules. MioTEM is adding apparel and does not have checked lists for it yet. Say so plainly and warmly in one sentence ("we are adding
apparel too"), never "extending". Then run the same discovery questions as for the role (situation, problem, implication, need-payoff),
asking about what they make (clothing, footwear, accessories), where they sell or want to sell, how they handle the documents, hours and
shipments. For apparel, save product and destination with save_answer WITHOUT a value (their own words only), so no route is set.
Never state or hint at any document, duty, label, test, restriction or compliance rule for apparel, and never name a market as covered.
Never call offer_preview or show_preview for apparel. If asked about requirements, say MioTEM is still checking them against official
sources and will not guess. Offer the notify form (note_fashion shows it) and the free sign-in as usual.

OTHER rules. The visitor exports something that is neither food nor apparel. Ask what they export (for a TEM: what their clients export) and save it
with save_answer topic other_product (their own words, no value). Then say, in one sentence, that this information is shared with the MioTEM
team, who look at which categories to add next, and ask: "Would you be willing to share a few more details: transactions a year, average
transaction value, the types of products and your target markets?" (OPTIONS: Yes | No thanks). If yes: ask ONE detail at a time and save each
with save_answer (topics transactions, avg_value, product_types, markets; their own words, ranges as quick choices where useful). Then, or
right after "No thanks", call offer_contact_form: a short form below lets them leave an email and an optional phone number for follow up, with a
consent box. Never ask for the email or phone in the chat itself. Never state or hint at any document, duty, label or compliance rule for
the category and never offer a preview.

Preview, in two steps. Step A, after the yearly estimate (exporter) or once the TEM has told you, in their own words, how many
clients they serve and which products and countries, and has answered the weekly hours question: ask permission. Call offer_preview and ask, in one short question, whether
they would like to see a preview of their route (exporter) or of a sample workspace with two example clients (TEM), with
OPTIONS: Yes, show me | Not now. Say in one sentence what they would see and how MioTEM helps: it prepares the document list
for their route, shows who prepares each document, and checks the documents before they ship. Do NOT call show_preview in the same
message. Never say or imply a preview was already offered or shown (no "the preview above", no "if you say yes") before you have asked
the offer question in an earlier message; until then do not mention a preview at all. After the offer is declined or answered, never refer to it as above. Step B, only after the visitor says yes in a later message: call show_preview, and say in one or two sentences what to look
for (which documents are theirs to prepare, which belong to the carrier, forwarder or tax warehouse, and which are marked for staff
to verify; for a TEM: one checked list per client project). Say the preview is below and do not describe its contents. If they say
not now, carry on with the implication question. If offer_preview answers that the route is not covered, follow its
instruction: no preview, say it plainly, point to the form, and ask no other question. The page builds the preview from real MioTEM data. NEVER call show_preview on the
first messages, and never invent example products or countries: use only what the visitor said. If the tool answers with an error,
simply ask your next question. Then continue with the implication or need-payoff question.

Only say the preview is below if you called show_preview and it answered ok in this conversation. Only say the sign-up button is
below if you called show_signin in that same response.

When you invite the visitor to sign in, or they say they want to, call show_signin in that same response and say the
sign-up button is below your message. Never describe a link or a page you cannot show.

Coverage: MioTEM has checked lists for these products: {PRODUCTS}; and these countries: {COUNTRIES}. If the visitor
(exporter or TEM) names a destination country outside that list, or an exporter's destination is saved as "other", say so plainly and
warmly for that country, call note_uncovered with the countries as they said them (the page then shows an optional form to be told when
they are ready), and ask whether a covered country also fits. Never guess documents or rules for an uncovered country. If the product is
clearly not food and not apparel (or not Italian), ask politely what Italian product they mean before saving it. Keep going with the questions either way.

If Saved so far contains route_noted, the page has already told the visitor there is no checked list for their route: do not repeat it,
never offer a preview, and carry on with the hours, cost and implication questions, then the sign-up offer. Write the preview question
only after offer_preview has answered ok; never write it first and correct yourself later.
An uncovered country or product never stops you: note it (note_uncovered) and carry on with the ones that are covered. If an exporter
lists several destinations, save the first covered one as the destination and note the rest. If a TEM answers vaguely ("all kinds of
food", "everything") but names covered countries, offer the preview anyway: the page uses wine and pasta examples labelled as our choice.
After the preview, ask which products matter most to their clients. If they name no covered country at all, ask for two or three typical
clients with a product and a country each (for example wine to the USA, pasta to the UK). Never tell the visitor that something "could not load" or failed: if a
tool answers with an error, simply ask your next question.

Rules:
- Never state tariffs, taxes, legal requirements, prices or deadlines. If asked, say MioTEM checks these against
  official sources once the visitor is signed in, and that you will not guess.
- Write plain text only: no asterisks, no markdown, no bullet symbols. Mention tools in one sentence or short plain lines.
Tools. When you invite sign-up (or the visitor asks what MioTEM can do), name the two or three tools from the list below that fit
this visitor and say in one short sentence what each does for them, then say the full list is further down the page. Use only the
tools, names and descriptions in this list; say plainly which are in development or coming soon and never present them as ready.
Never describe how a tool works inside.
{TOOLS}
If asked what it costs to sign in or to try: answer it, it is a buying signal. Signing in is free. For an exporter, the free
  Explore plan includes one project on a covered route with its document checklist and duties, and one free check. For a TEM,
  the trial workspace is free, with 2 clients and 5 client projects and no time limit. Do not quote the price of any paid
  plan: those are shown after sign-in. Then ask the next question or invite them to sign in.
- Never promise outcomes. Never say you are human. If asked, say you are an AI.
- Never use these words: "SaaS", "traceability", "AI-powered". Describe MioTEM as compliance document validation,
  powered by orchestrated AI-Agents. Never use em dashes.
- If the visitor writes in another language, follow them. Otherwise use the interface language below.
- When the answer is a short choice you may end with one final line: OPTIONS: first | second | third (2 to 4 choices).
- When the visitor has reached the end of the conversation allowance, close warmly and invite them to sign in: the
  conversation continues after sign-in."""
def _tool_lines():
    lab = {"live": "available now", "preview": "in development", "soon": "coming soon"}
    return "\n".join(f"- {x['name']['en']} ({lab[x['status']]}): {x['text']['en']}" for x in tools.public_catalog())


SYSTEM = _SYSTEM_TEMPLATE.replace("{TOOLS}", _tool_lines()).replace("{PRODUCTS}", ", ".join(lane_requests.COVERED_PRODUCTS)).replace("{COUNTRIES}", ", ".join(lane_requests.COVERED_COUNTRIES))

TOOLS = [
    {"name": "set_role", "description": "Record who the visitor is.",
     "input_schema": {"type": "object", "properties": {"role": {"type": "string", "enum": list(ROLES)}}, "required": ["role"]}},
    {"name": "show_preview", "description": "Make the page show a read only preview built from what the visitor told you. Exporter: "
     "call it once product and destination are saved (with value), right after the yearly estimate and before the sign-in offer. "
     "TEM: call it with examples, up to two example routes (category and country) from the products and countries they "
     "described. The page shows real checklist and duties data, so never describe its contents yourself, only say it is below.",
     "input_schema": {"type": "object", "properties": {"examples": {"type": "array", "maxItems": 2, "items": {"type": "object",
         "properties": {"category": {"type": "string"}, "country": {"type": "string"}}, "required": ["category", "country"]}}}}},
    {"name": "offer_preview", "description": "Record that you are asking the visitor whether they want to see the preview. Call it in the same "
     "response as the question. show_preview only works in a LATER message, after the visitor has said yes.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "note_uncovered", "description": "Call it when the visitor (exporter or TEM) names a destination country that is not in the covered "
     "list. Give the countries as they said them. The page then shows an optional notify-me form.",
     "input_schema": {"type": "object", "properties": {"countries": {"type": "string"}}, "required": ["countries"]}},
    {"name": "note_fashion", "description": "Call it when the visitor (exporter or TEM) says they are in apparel: clothing, footwear or accessories. "
     "Records interest only: MioTEM has no checked apparel lists yet. The page then shows an optional notify-me form.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "note_other", "description": "Call it when the visitor (exporter or TEM) says what they export is neither food nor apparel. Records interest only.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "offer_contact_form", "description": "Call it after the optional details questions (or after No thanks) in the OTHER path: the page then shows the form "
     "for email, optional phone and consent.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "offer_tem_intro", "description": "Call it when an exporter says yes to an introduction to a TEM. The page then shows an optional "
     "contact form. Records interest only, no match is promised.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "show_signin", "description": "Make the page show the sign-up button under your reply. Call it whenever you invite the "
     "visitor to sign in, and whenever they say they want to sign in. In your reply say the button is below.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "yearly_estimate", "description": "Work out the visitor's own yearly paperwork time and cost from their numbers. "
     "For a range pass the low end in the plain field and the high end in the _max field (for an open top range such as 'over 10' pass only the lower bound and say 'at least'). Never use midpoints. Returns totals and working weeks to quote as THEIR estimate.",
     "input_schema": {"type": "object", "properties": {"hours_per_shipment": {"type": "number"}, "shipments_per_year": {"type": "number"},
                                                       "cost_per_shipment_eur": {"type": "number"}, "hours_per_shipment_max": {"type": "number"},
                                                       "shipments_per_year_max": {"type": "number"}, "cost_per_shipment_eur_max": {"type": "number"}},
                      "required": ["hours_per_shipment", "shipments_per_year"]}},
    {"name": "save_answer", "description": "Record one thing the visitor told you, in their words, short. For topic product "
     "also give value: one of the product categories. For topic destination also give value: one of the countries.",
     "input_schema": {"type": "object", "properties": {"topic": {"type": "string", "enum": list(TOPICS)},
                                                       "text": {"type": "string"},
                                                       "value": {"type": "string", "description": "product: " + ", ".join(CATEGORIES) + ". destination: " + ", ".join(COUNTRIES) + " (use other if none fits)."}},
                     "required": ["topic", "text"]}},
]


def ip_hash(ip):
    return hashlib.sha256(("vl-landing:" + (ip or "unknown")).encode()).hexdigest()[:32]


def _since(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def used_today(con):
    r = con.execute("SELECT COALESCE(SUM(messages), 0) AS n FROM anon_chats WHERE updated_at>?", (_since(24),)).fetchone()
    return int(r["n"])


def _row(con, visitor):
    r = con.execute("SELECT * FROM anon_chats WHERE visitor_id=?", (visitor,)).fetchone()
    return dict(r) if r else None


def _said(state):
    """Everything the visitor told us, as one lowercase text: only their saved answers, never the AI's own examples."""
    skip = ("fashion", "other", "examples", "estimate", "category", "country", "preview_ok", "preview_offered", "uncovered", "vague_products", "tem_intro", "route_noted")
    return " ".join(" ".join(v) for k, v in state["answers"].items() if k not in skip and isinstance(v, list)).lower()


def _mentioned(said, words):
    return any(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", said) for w in words)


def run_tool(state, name, args):
    if name == "set_role" and args.get("role") in ROLES:
        state["role"] = args["role"]
        return {"ok": True}
    if name == "note_uncovered":
        where = str(args.get("countries") or "").strip()[:150]
        if not where:
            return {"error": "name the countries"}
        state["answers"]["uncovered"] = [where]
        state["offer_notify"] = True  # the page shows the notify-me form
        return {"ok": True, "instruction": "Say plainly that MioTEM has no checked list for those countries yet, that a short form below lets "
                "them leave an email to be told when they are ready (optional), then carry on with your next question."}
    if name == "note_other":
        if state.get("role") not in ("exporter", "tem"):
            return {"error": "ask the role first"}
        state["answers"]["other"] = ["yes"]
        return {"ok": True, "instruction": "Ask what they export (for a TEM: what their clients export), then follow the OTHER rules. No compliance statements."}
    if name == "offer_contact_form":
        if not state["answers"].get("other"):
            return {"error": "only after note_other"}
        state["offer_notify"] = True
        state["notify_kind"] = "other"
        return {"ok": True, "instruction": "Say a short form below lets them leave an email and an optional phone number so the MioTEM team can follow up."}
    if name == "note_fashion":
        if state.get("role") not in ("exporter", "tem"):
            return {"error": "ask the role first"}
        state["answers"]["fashion"] = ["yes"]
        state["offer_notify"] = True  # the page shows the notify-me form for apparel
        state["notify_kind"] = "fashion"
        return {"ok": True, "instruction": "Say in one sentence that MioTEM is adding apparel too and has no checked lists for it yet, that a short form below "
                "lets them leave an email to be told when it is ready (optional), then carry on with your next discovery question. No document, duty or compliance statements."}
    if name == "offer_tem_intro":
        if state.get("role") != "exporter":
            return {"error": "only for an exporter"}
        state["answers"]["tem_intro"] = ["yes"]
        state["offer_notify"] = True
        state["notify_kind"] = "tem_intro"
        return {"ok": True, "instruction": "Say a short form below lets them leave an email so MioTEM can be in touch about a TEM introduction "
                "(optional), that no match is promised yet, then carry on with your next question or the sign-up offer."}
    if name == "offer_preview":
        a = state["answers"]
        if a.get("fashion") or a.get("other"):
            return {"ready": False, "instruction": "Fashion has no checked lists yet: do NOT offer a preview. Carry on with your next discovery question or the sign-in offer."}
        if state.get("role") != "tem" and a.get("category") and a.get("country") and state.get("con") is not None \
                and not requirements.covers(a["category"], a["country"]):
            state["offer_notify"] = True  # the page shows the notify-me form; no preview is offered for a route without a list
            return {"covered": False, "instruction": "MioTEM has no checked list for this route yet. Do NOT offer a preview. Say so plainly and "
                    "warmly, say a short form below lets them leave an email to be told when it is ready (optional), and that signing up free "
                    "lets them look at routes that are covered. Ask no other question in this message."}
        if state.get("role") == "tem":
            said = _said(state)
            if not a.get("time"):
                return {"ready": False, "instruction": "Do NOT offer the preview yet: first ask how many hours a week they spend chasing documents from clients, "
                        "checking them, and keeping up with regulatory changes (OPTIONS: Under 5 hours | 5 to 10 hours | 10 to 20 hours | Over 20 hours), "
                        "and save the answer with save_answer topic time. Then offer the preview."}
            if not a.get("clients") or not any(_mentioned(said, w) for w in COUNTRY_WORDS.values()):
                return {"ready": False, "instruction": "Do NOT offer the preview yet: you still need the number of clients and at least one destination "
                        "country that MioTEM covers. Ask for them (a product and a country for two or three typical clients is ideal), then offer the preview."}
            if any(_mentioned(said, w) for w in PRODUCT_WORDS.values()):
                state["answers"].pop("vague_products", None)
            else:
                state["answers"]["vague_products"] = ["yes"]  # no product named: the sample may use wine and pasta, labelled as examples we chose
        state["answers"]["preview_offered"] = [str(state.get("messages_so_far", 0))]
        return {"ok": True, "covered": True}
    if name == "show_preview":
        if state["answers"].get("fashion") or state["answers"].get("other"):
            return {"error": "no preview for apparel or other categories yet"}
        offered = state["answers"].get("preview_offered")
        if not offered or int(offered[0]) >= state.get("messages_so_far", 0):
            return {"error": "ask first: call offer_preview and ask whether they want to see it; show_preview only after they say yes in a later message"}
        if state.get("messages_so_far", 0) < 2:
            return {"error": "too early: ask your questions first, the visitor has told you almost nothing"}
        if state.get("role") == "tem":
            said = _said(state)
            if not state["answers"].get("clients"):
                return {"error": "ask how many exporter clients they serve first"}
            vague = bool(state["answers"].get("vague_products"))
            ex = []
            for e in (args.get("examples") or [])[:2]:
                if not (isinstance(e, dict) and e.get("category") in PRODUCT_WORDS and e.get("country") in COUNTRY_WORDS
                        and _mentioned(said, COUNTRY_WORDS[e["country"]])):
                    continue
                if _mentioned(said, PRODUCT_WORDS[e["category"]]):
                    ex.append(f"{e['category']}|{e['country']}")
                elif vague and e["category"] in ("wine", "pasta"):
                    ex.append(f"{e['category']}|{e['country']}|assumed")  # the TEM named no product: labelled as our choice
            if not ex:
                return {"error": "no example may be invented: use only products and countries the visitor named"}
            state["answers"]["examples"] = ex
        else:
            if not (state["answers"].get("category") and state["answers"].get("country")):
                return {"error": "save product and destination with value first"}
            if not any(state["answers"].get(k) for k in ("handling", "time", "volume", "estimate")):
                return {"error": "ask how they handle the documents and the hours first"}
        state["offer_preview"] = True
        state["answers"]["preview_ok"] = ["yes"]  # the preview page only answers for a visitor whose preview passed these checks
        return {"ok": True}
    if name == "show_signin":
        state["offer_signin"] = True
        return {"ok": True}
    if name == "yearly_estimate":
        try:
            h, n = float(args.get("hours_per_shipment")), float(args.get("shipments_per_year"))
            c = float(args.get("cost_per_shipment_eur") or 0)
            h2 = float(args.get("hours_per_shipment_max") or h)
            n2 = float(args.get("shipments_per_year_max") or n)
            c2 = float(args.get("cost_per_shipment_eur_max") or c)
        except (TypeError, ValueError):
            return {"error": "numbers_needed"}
        if not (0 <= h <= h2 <= 1000 and 0 <= n <= n2 <= 100000 and 0 <= c <= c2 <= 1000000):
            return {"error": "out_of_range"}
        lo_h, hi_h, lo_c, hi_c = round(h * n, 1), round(h2 * n2, 1), round(c * n), round(c2 * n2)
        wk = lambda x: round(x / 40 * 4) / 4  # work weeks of 40 hours, in quarters
        rng = (lo_h, lo_c) != (hi_h, hi_c)
        out = {"hours_per_year": lo_h, "cost_per_year_eur": lo_c}
        if rng:
            out.update({"hours_per_year_max": hi_h, "cost_per_year_eur_max": hi_c})
        out.update({"work_weeks": wk(lo_h)} | ({"work_weeks_max": wk(hi_h)} if rng else {}))
        txt = f"{lo_h:g} h" + (f" to {hi_h:g} h" if rng else "")
        state["answers"]["estimate"] = [f"their own numbers: {h:g}-{h2:g} h per shipment x {n:g}-{n2:g} shipments".replace("-" + f"{h2:g} h", "" if h == h2 else "-" + f"{h2:g} h")
                                        + (f", EUR {c:g} per shipment" if c else "") + f" = {txt}"
                                        + (f", EUR {lo_c:,}" + (f" to {hi_c:,}" if rng and hi_c != lo_c else "") + " a year" if c else " a year")]
        return {**out, "note": "the visitor's own estimate, not a MioTEM figure",
                "instruction": "Say it as a range when both ends are given, never as one invented midpoint: for example 'between about 30 and 120 hours "
                "a year, that is 3/4 to 3 weeks of your (or your team's) time every year'. Give the weeks as a fraction or a number of 40 hour weeks. For an open top "
                "range say 'at least'. Quote the numbers returned, do no arithmetic of your own."}
    if name == "save_answer" and args.get("topic") in TOPICS:
        state["answers"].setdefault(args["topic"], []).append(str(args.get("text") or "")[:300])
        state["answers"][args["topic"]] = state["answers"][args["topic"]][-3:]
        value = str(args.get("value") or "")
        if args["topic"] == "product" and value:
            state["answers"]["category"] = value if value in CATEGORIES else "other"  # a product we have no list for counts as "other"
        if args["topic"] == "destination" and value:
            state["answers"]["country"] = value if value in COUNTRIES else "other"
        return {"ok": True}
    return {"error": "unknown"}


def _note(state, lang, left):
    t = f"Interface language: {'Italian' if lang == 'it' else 'English'}. Role so far: {state['role'] or 'not known yet'}."
    if state["answers"]:
        t += " Saved so far: " + json.dumps(state["answers"], ensure_ascii=False) + "."
    if left <= 1:
        t += " This is the visitor's LAST message in this conversation: answer it, then close warmly and invite them to sign in."
    return t


def message(con, body, ip, client):
    """One visitor message in, one reply out. Returns (status, body)."""
    visitor = str(body.get("visitor") or "")
    text = str(body.get("message") or "").strip()[:MAX_CHARS]
    lang = "en" if body.get("lang") == "en" else "it"
    if not VISITOR.match(visitor) or not text:
        return 400, {"error": "bad_request"}
    row = _row(con, visitor)
    state = {"role": row["role"] if row else None,
             "history": json.loads(row["history"]) if row else [],
             "answers": json.loads(row["answers"]) if row else {},
             "messages": row["messages"] if row else 0}
    if state["messages"] >= MESSAGE_CAP:
        return 429, {"error": "cap", "signin": True, "role": state["role"]}
    h = ip_hash(ip)
    mine = con.execute("SELECT COALESCE(SUM(messages), 0) AS n FROM anon_chats WHERE ip_hash=? AND updated_at>?",
                       (h, _since(24))).fetchone()["n"]
    if mine >= IP_DAILY_CAP:
        return 429, {"error": "limit", "signin": True, "role": state["role"]}  # this connection used its messages for today
    if used_today(con) >= DAILY_CEILING:
        print("landing chat: daily ceiling of %d messages reached" % DAILY_CEILING, flush=True)
        return 503, {"error": "busy", "role": state["role"]}
    state["con"] = con
    state["messages_so_far"] = state["messages"] + 1  # this message included
    left = MESSAGE_CAP - state["messages"] - 1
    history = state["history"]
    if history and history[-1]["role"] == "user" and isinstance(history[-1]["content"], list):
        history[-1]["content"].append({"type": "text", "text": text})  # the last reply ended on tool results: roles must alternate
    else:
        history.append({"role": "user", "content": text})
    usage = {}
    try:
        for _ in range(4):
            with db.outside_call():
                resp = client.messages.create(
                    model=MODEL, max_tokens=MAX_TOKENS, tools=TOOLS, messages=history[-24:],
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": _note(state, lang, left)}])
            ai_usage.add(usage, getattr(resp, "usage", None))
            history.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
            uses = [b for b in resp.content if b.type == "tool_use"]
            reply = "".join(b.text for b in resp.content if b.type == "text").strip()
            if not uses:
                break
            history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(run_tool(state, u.name, u.input))} for u in uses]})
            if reply and all(u.name in QUIET_TOOLS for u in uses):
                break  # saves need no second call; an estimate must come back to the AI before it speaks
        else:
            reply = ""
    except Exception:
        traceback.print_exc()  # the cause (connection, key, billing, overload) goes to the server log, not the visitor
        ai_usage.record(con, None, "visitor", usage, MODEL)
        return 503, {"error": "ai_unavailable", "role": state["role"]}  # history not saved: the message counts as not sent
    if not reply:
        # the AI ended without a word (only tools, or nothing): ask once more for the spoken reply, never fall back to the opening line
        try:
            if history[-1]["role"] == "assistant":
                history.pop()  # an empty turn: drop it so roles keep alternating
            with db.outside_call():
                resp = client.messages.create(
                    model=MODEL, max_tokens=MAX_TOKENS, tools=TOOLS, tool_choice={"type": "none"},
                    messages=history[-24:] + [{"role": "user", "content": "Now reply to the visitor in words: acknowledge their last answer and ask the next question."}],
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": _note(state, lang, left)}])
            ai_usage.add(usage, getattr(resp, "usage", None))
            reply = "".join(b.text for b in resp.content if b.type == "text").strip()
            if reply:
                history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        except Exception:
            reply = ""
    ai_usage.record(con, None, "visitor", usage, MODEL)
    if not reply:
        reply = FALLBACK[lang]
        history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
    a = state["answers"]
    if state["role"] == "exporter" and a.get("category") and a.get("country") and "route_noted" not in a \
            and not requirements.covers(a["category"], a["country"]):
        # the route has no checked list: say so now, not after five more questions
        a["route_noted"] = ["yes"]
        state["offer_notify"] = True
        what = ((a.get("product") or [a["category"]])[-1] or a["category"])[:60]
        where = ((a.get("destination") or [a["country"]])[-1] or a["country"])[:60]
        reply = NO_LIST[lang].format(p=what, d=where) + "\n\n" + reply
    now = db.now()
    fields = (state["role"], json.dumps(history[-24:]), json.dumps(state["answers"], ensure_ascii=False), state["messages"] + 1, now)
    if row:
        con.execute("UPDATE anon_chats SET role=?, history=?, answers=?, messages=?, updated_at=? WHERE visitor_id=?", fields + (visitor,))
    else:
        con.execute("INSERT INTO anon_chats(visitor_id, ip_hash, role, history, answers, messages, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (visitor, h, state["role"], fields[1], fields[2], fields[3], now, now))
    return 200, {"reply": reply, "role": state["role"], "left": left, "signin": left <= 0, "offer_signin": bool(state.get("offer_signin")) or bool(SIGNIN_MENTION.search(reply)),
                "offer_preview": bool(state.get("offer_preview")), "offer_notify": bool(state.get("offer_notify")),
                "notify_kind": state.get("notify_kind") or "route"}


def listing(con):
    rows = [dict(r) for r in con.execute(
        "SELECT role, answers, messages, created_at FROM anon_chats ORDER BY updated_at DESC LIMIT 100").fetchall()]
    by = {}
    for r in rows:
        by[r["role"] or "unknown"] = by.get(r["role"] or "unknown", 0) + 1
    return {"total": len(rows), "by_role": by, "chats": rows}


def claim(con, user_sub, visitor):
    """After sign-in: attach the landing conversation to the person and return what it learned. A conversation
    already claimed by someone else is not shared."""
    if not VISITOR.match(str(visitor or "")):
        return {"claimed": False}
    row = _row(con, visitor)
    if not row or (row.get("user_sub") and row["user_sub"] != user_sub):
        return {"claimed": False}
    if not row.get("user_sub"):
        con.execute("UPDATE anon_chats SET user_sub=? WHERE visitor_id=?", (user_sub, visitor))
    a = json.loads(row["answers"])
    first = lambda k: (a.get(k) or [""])[-1] if isinstance(a.get(k), list) else ""
    return {"claimed": True, "role": row["role"], "category": a.get("category"), "country": a.get("country"),
            "product": first("product"), "destination": first("destination"), "firm": first("firm"), "contact": first("contact")}


def note_for(con, user_sub):
    """A line for the project chat prompt: what this person told the landing guide before signing in."""
    if not user_sub:
        return ""
    row = con.execute("SELECT answers, role FROM anon_chats WHERE user_sub=? ORDER BY updated_at DESC LIMIT 1", (user_sub,)).fetchone()
    if not row or row["role"] != "exporter":
        return ""
    a = json.loads(row["answers"])
    told = "; ".join(f"{k}: {' / '.join(v)}" for k, v in a.items() if isinstance(v, list) and v)
    if not told:
        return ""
    return (" Before signing in, the client told our landing guide: " + told + ". Do not ask for these again. Build on the "
            "problem and the consequence they named, in your own words, and ask only what is still missing.")


def _route(con, category, country):
    """The real checklist and duties for one route, from the same data the project page uses. No AI."""
    out = {"category": category, "country": country, "covered": requirements.covers(category, country)}
    if not out["covered"]:
        return out
    req = requirements.required(category, country, set())
    data = req["data"]
    out["checked"] = req["checked"]
    out["layers"] = [{"id": k, "name": v, "items": [
        {"it": i["it"], "en": i["en"], "who": i["who"], "verified": i["verified"], "only_if": i["only_if"],
         "source": i["source"] if isinstance(i["source"], str) else None}
        for i in data["items"] if i["layer"] == k]} for k, v in data["layers"].items()]
    out["layers"] = [l for l in out["layers"] if l["items"]]
    out["documents"] = len(data["items"])
    out["staff_verify"] = sum(1 for i in data["items"] if not i["verified"])
    out["caveat"] = data["caveat"]
    out["duties"] = duties.for_case(con, {"product": {"category": category}, "market": {"country": country}})
    return out


def preview(con, visitor):
    """A read only preview built from this visitor's saved answers. Exporter: their route. TEM: a sample workspace with
    two example clients. Everything in it is real data or labelled as an example."""
    row = _row(con, str(visitor or "")) if VISITOR.match(str(visitor or "")) else None
    if not row:
        return {"kind": None}
    a = json.loads(row["answers"])
    if not a.get("preview_ok"):
        return {"kind": None}
    if row["role"] == "tem":
        pairs = [p.split("|") for p in (a.get("examples") or []) if "|" in p][:2]
        if not pairs:
            return {"kind": None}
        return {"kind": "workspace", "clients": [dict(_route(con, q[0], q[1]), name="Example client " + "AB"[n], assumed=len(q) > 2)
                                                  for n, q in enumerate(pairs)]}
    if row["role"] == "exporter" and a.get("category") and a.get("country"):
        first = lambda k: (a.get(k) or [""])[0] if isinstance(a.get(k), list) else (a.get(k) or "")
        label = (first("product") or a["category"]) + " → " + (first("destination") or a["country"])  # their own words
        return dict(_route(con, a["category"], a["country"]), kind="route", label=label)
    return {"kind": None}
