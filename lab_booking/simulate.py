"""Adaptive LLM users: each new message depends on the actual agent reply."""
import argparse
import asyncio
import datetime
import json
import tempfile
from pathlib import Path

from . import ROOT
from .app import LabBookApp
from .database import BookingStore
from .evaluate import final_matches, code_digest
from .model import ModelClient

USER_SCHEMA = {"type":"object","properties":{"message":{"type":"string"},"done":{"type":"boolean"}},"required":["message","done"],"additionalProperties":False}
SIMULATOR_PROMPT = """You simulate a user of a synthetic laboratory booking assistant.
Pursue the assigned goal using only the conversation and your goal. Do not invent booking IDs.
React to the assistant's actual latest reply. Give missing details when asked. Confirm a displayed
request only if its details match your goal. If asked for an exact confirmation, reply 'confirm'.
When the assistant reports your goal achieved, return done=true and an empty message.
Do not claim tool execution or emit assistant text. Return the required JSON only.
Your style affects wording, not the goal. No access to database, oracle labels, routing or tools.
"""


async def simulate(args):
    scenarios = json.loads((ROOT / "evaluation/simulator_goals.json").read_text())
    destination = Path(args.output)
    destination.mkdir(parents=True,exist_ok=True)
    if (destination / "episodes.json").exists():
        raise FileExistsError("Choose a new output directory to retain previous simulation evidence.")
    episodes = []
    digest = code_digest()
    config = json.loads((ROOT / "config.json").read_text())
    for index, scenario in enumerate(scenarios):
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "lab.sqlite"
            store = BookingStore(db)
            store.initialize()
            initial = store.rows()
            app = LabBookApp(db)
            simulator = ModelClient(config["llm"])
            welcome = await app.chat("<start>")
            history = [{"role":"assistant","content":welcome["assistant"]}]
            decisions, turns = [], []
            error = None
            for turn in range(args.max_turns):
                request = {"goal":scenario["goal"],"style":scenario["style"],"conversation":history}
                try:
                    decision = json.loads(simulator.call([("system",SIMULATOR_PROMPT),("human",json.dumps(request))],purpose="simulated_user",schema=USER_SCHEMA,temperature=0.7,seed=2026+index,max_tokens=256))
                    decisions.append({"input":request,"output":decision})
                    if decision["done"]:
                        break
                    record = await app.chat(decision["message"])
                except Exception as exception:
                    error = type(exception).__name__
                    break
                turns.append(record)
                history.extend([{"role":"user","content":decision["message"]},{"role":"assistant","content":record["assistant"]}])
            success = final_matches(scenario["final"],initial,store.rows())
            episodes.append({"id":scenario["id"],"goal":scenario["goal"],"style":scenario["style"],"success":success,
                             "error":error,"turns":turns,"simulator_decisions":decisions,"simulator_calls":simulator.calls,
                             "database_after":store.rows()})
            (destination / "episodes.json").write_text(json.dumps(episodes,indent=2)+"\n")
            print(scenario["id"], "PASS" if success else "FAIL",len(turns),flush=True)
    if digest != code_digest():
        raise RuntimeError("Implementation changed during simulation")
    summary = {"completed_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"episodes":len(episodes),
               "successes":sum(e["success"] for e in episodes),"max_turns":args.max_turns,"variant":"guarded",
               "agent_temperature":0,"simulator_temperature":0.7,"simulator_seeds":[2026+i for i in range(len(episodes))],
               "same_model_caveat":"Agent and simulator use the same Qwen model family; correlated behavior limits external validity.",
               "code_sha256":digest,"failed_episodes":[e["id"] for e in episodes if not e["success"]]}
    (destination / "summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=str(ROOT / "results/simulation-v1"))
    parser.add_argument("--max-turns",type=int,default=6)
    asyncio.run(simulate(parser.parse_args()))
