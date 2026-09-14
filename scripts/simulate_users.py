"""Second simulator protocol, after an invalid role-confused pilot.

The evaluated agent, benchmark, and original pilot harness remain unchanged.
"""
import argparse
import asyncio
import copy
import datetime
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab_booking.app import LabBookApp
from lab_booking.database import BookingStore
from lab_booking.evaluate import final_matches, code_digest
from lab_booking.model import ModelClient

PROMPT = """Write the next CUSTOMER message in a conversation with a lab booking desk.
You are the CUSTOMER, the person trying to make a reservation, NOT the desk assistant.
Your customer goal and speaking style are given below. Ask the desk to do the task.
Use only the goal's facts. React to the last DESK reply. If details are requested, supply them.
If the desk shows correct complete details and requests confirmation, say 'Confirm.'
If the desk reports completion, output exactly <DONE>. Otherwise output a nonempty
customer utterance. Do not say you have booked anything yourself. Do not repeat the desk's
question. Do not use role prefixes, quotation marks around the utterance, or JSON.
Follow the speaking style on the first turn. Continue until the actual goal is complete.
"""
EXAMPLES = [
    ("GOAL: Reserve instrument Z9 on 2027-03-02 from 12:00 to 13:00.\nSTYLE: direct\nDESK: Hello, how can I help?",
     "Please reserve Z9 on 2027-03-02 from 12:00 to 13:00."),
    ("GOAL: Move booking B0912 to 2027-03-04 from 15:00 to 16:00.\nSTYLE: concise\nCUSTOMER: Move B0912.\nDESK: Please provide a date, start time, and end time.",
     "Use 2027-03-04, 15:00 to 16:00."),
    ("GOAL: Cancel booking B0123.\nSTYLE: direct\nCUSTOMER: Cancel B0123.\nDESK: Please confirm cancellation of B0123. No change made yet.",
     "Confirm."),
]


async def main(args):
    scenarios = json.loads(Path(args.goals).read_text())
    destination = Path(args.output)
    destination.mkdir(parents=True,exist_ok=True)
    if (destination / "episodes.json").exists():
        raise FileExistsError("Choose a fresh output directory")
    digest = code_digest()
    config = json.loads((ROOT / "config.json").read_text())
    episodes=[]
    for index, scenario in enumerate(scenarios):
        with tempfile.TemporaryDirectory() as temporary:
            db=Path(temporary)/"lab.sqlite"
            store=BookingStore(db);store.initialize();initial=store.rows()
            app=LabBookApp(db);simulator=ModelClient(config["llm"])
            greeting=await app.chat("<start>")
            history=[{"role":"assistant","content":greeting["assistant"]}]
            turns, decisions=[],[]
            error=None
            for turn in range(args.max_turns):
                conversation="\n".join(("DESK" if h["role"]=="assistant" else "CUSTOMER")+": "+h["content"] for h in history)
                current=f"GOAL: {scenario['goal']}\nSTYLE: {scenario['style']}\n{conversation}\nNEXT CUSTOMER MESSAGE:"
                messages=[("system",PROMPT)]
                for question,answer in EXAMPLES:
                    messages.extend([("human",question),("assistant",answer)])
                messages.append(("human",current))
                try:
                    utterance=simulator.call(messages,purpose="simulated_user_v2",temperature=0.7,seed=2026+index,max_tokens=180).strip()
                    decisions.append({"input":copy.deepcopy(messages),"output":utterance})
                    if utterance=="<DONE>":
                        break
                    if not utterance:
                        error="empty_simulated_utterance"
                        break
                    result=await app.chat(utterance)
                except Exception as exception:
                    error=type(exception).__name__;break
                turns.append(result)
                history.extend([{"role":"user","content":utterance},{"role":"assistant","content":result["assistant"]}])
            success=final_matches(scenario["final"],initial,store.rows())
            episodes.append({"id":scenario["id"],"goal":scenario["goal"],"style":scenario["style"],"success":success,"error":error,
                             "turns":turns,"simulator_decisions":decisions,"simulator_calls":simulator.calls,"database_after":store.rows()})
            (destination/"episodes.json").write_text(json.dumps(episodes,indent=2)+"\n")
            print(scenario["id"],"PASS" if success else "FAIL",len(turns),error,flush=True)
    if digest!=code_digest():
        raise RuntimeError("Agent implementation changed during simulation")
    summary={"completed_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"protocol":"role-demonstrated adaptive customer, v2",
             "episodes":len(episodes),"successes":sum(e["success"] for e in episodes),"invalid_episodes":sum(e["error"] is not None for e in episodes),
             "max_turns":args.max_turns,"agent_variant":"guarded","agent_temperature":0,"simulator_temperature":0.7,
             "simulator_seeds":[2026+i for i in range(len(episodes))],"code_sha256":digest,
             "harness_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "goals_sha256":hashlib.sha256(Path(args.goals).read_bytes()).hexdigest(),
             "caveat":"Simulator revised after an invalid pilot; repeated goals are development evidence, not a blind holdout. Same model family for agent and simulator.",
             "failed_episodes":[e["id"] for e in episodes if not e["success"]]}
    (destination/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps({k:v for k,v in summary.items() if k!='code_sha256'},indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--goals",default=str(ROOT/"evaluation/simulator_goals.json"))
    parser.add_argument("--output",default=str(ROOT/"results/simulation-v2"))
    parser.add_argument("--max-turns",type=int,default=6)
    asyncio.run(main(parser.parse_args()))
